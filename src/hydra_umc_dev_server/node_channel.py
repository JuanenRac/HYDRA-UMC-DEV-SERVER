# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/node_channel.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The channel a node uses to hand an escalation to this server: one token per node, issued and revocable.

A node that escalates (the local technician) posts an `incident-transport/1` message to `POST /v1/incident-transport`. The
channel proves WHO the node is with a token that belongs to that node alone:

* `node-token issue NODE --out FILE` makes a new token for the node and writes it to FILE (created new, mode 0600, never
  printed). The server keeps only the SHA-256 of the token in its tokens file, so a leaked tokens file gives no token.
  Issuing again for the same node REPLACES the token (a rotation): the old one stops working at once.
* `node-token revoke NODE` stops a node: its token is refused from the next request on (the file is read on every request,
  there is nothing to restart).
* The token only opens this one route. It is not the token of the rest of the API, which is not accepted here.
* Behind the token the message is still verified as before (`verify_message`: the node of the token must be the sender,
  the HMAC of the node, the time window, the nonce and the rate), so a stolen token alone cannot forge a message.

The route exists only when the configuration file of the channel is given to `serve` (`--node-channel FILE`); without it the
route answers 404. Every figure and path is in that file, none in the code.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import ConfigValidationError, load_json_document
from .incident_transport import (
    IncidentMessage,
    NodeRegistry,
    SqliteVerifierState,
    TransportPolicy,
    verify_message,
)

TOKENS_SCHEMA = "dev-server-node-tokens/1"
TOKEN_PREFIX = "hnt1_"
MIN_TOKEN_LENGTH = 40
NODE_LABEL = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
MESSAGE_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
MAX_BODY_LIMIT = 1_048_576


class NodeChannelError(ValueError):
    """The channel or its tokens file cannot be used; the text says why (never a token)."""


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_tokens(path: Path) -> dict[str, dict[str, Any]]:
    """The nodes of the tokens file (an absent file is an empty one)."""
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise NodeChannelError(f"cannot read the tokens file: {exc.__class__.__name__}") from exc
    nodes = data.get("nodes") if isinstance(data, dict) else None
    if not isinstance(data, dict) or data.get("schema") != TOKENS_SCHEMA or not isinstance(nodes, dict):
        raise NodeChannelError("the tokens file is not a node-tokens file")
    return nodes


def _save_tokens(path: Path, nodes: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump({"schema": TOKENS_SCHEMA, "nodes": nodes}, stream, indent=2, sort_keys=True)
    os.replace(temporary, path)


def issue_token(tokens_file: Path, node: str, out_file: Path) -> None:
    """Makes the token of `node`, writes it to `out_file` (new file, 0600) and keeps only its hash. The node's older token stops working."""
    if not NODE_LABEL.match(node):
        raise NodeChannelError("the node name has characters a node name does not have")
    out_file = Path(out_file)
    if out_file.exists():
        raise NodeChannelError("the output file already exists: the token is written to a new file")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    nodes = load_tokens(tokens_file)
    # the token goes to its file first: if that fails nothing was changed in the tokens file
    out_file.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(out_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        stream.write(token + "\n")
    nodes[node] = {"token_sha256": _hash(token), "issued_at": _now(), "revoked_at": None}
    _save_tokens(tokens_file, nodes)


def revoke_token(tokens_file: Path, node: str) -> None:
    nodes = load_tokens(tokens_file)
    if node not in nodes:
        raise NodeChannelError("no token was issued for that node")
    nodes[node]["revoked_at"] = _now()
    _save_tokens(tokens_file, nodes)


def authenticate(tokens_file: Path, presented: str) -> str | None:
    """The node whose live token this is, or None. Every entry is compared so the time does not tell which node exists."""
    if not isinstance(presented, str) or len(presented) < MIN_TOKEN_LENGTH or not presented.startswith(TOKEN_PREFIX):
        return None
    digest = _hash(presented)
    found: str | None = None
    for node, entry in load_tokens(tokens_file).items():
        if hmac.compare_digest(str(entry.get("token_sha256", "")), digest) and entry.get("revoked_at") is None:
            found = node
    return found


@dataclass(frozen=True)
class ChannelSettings:
    """Read from the configuration file of the channel; nothing here has a default that opens anything."""

    tokens_file: Path
    registry_file: Path
    state_file: Path
    inbox_dir: Path
    to_node: str
    policy: TransportPolicy
    max_body_bytes: int = 65_536

    @staticmethod
    def load(path: Path) -> "ChannelSettings":
        try:
            data = load_json_document(Path(path))
        except ConfigValidationError as exc:
            raise NodeChannelError(str(exc)) from exc
        unknown = sorted(set(data) - {"tokens_file", "registry_file", "state_file", "inbox_dir", "to_node", "policy", "max_body_bytes"})
        if unknown:
            raise NodeChannelError(f"the channel file has unknown key(s): {', '.join(unknown)}")
        for key in ("tokens_file", "registry_file", "state_file", "inbox_dir", "to_node"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise NodeChannelError(f"the channel file needs '{key}' as text")
        if not NODE_LABEL.match(data["to_node"]):
            raise NodeChannelError("'to_node' has characters a node name does not have")
        limit = data.get("max_body_bytes", 65_536)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 256 <= limit <= MAX_BODY_LIMIT:
            raise NodeChannelError(f"'max_body_bytes' must be a whole number between 256 and {MAX_BODY_LIMIT}")
        try:
            policy = TransportPolicy.from_dict(data.get("policy", {"contract_version": "incident-transport/1"}))
        except ConfigValidationError as exc:
            raise NodeChannelError(str(exc)) from exc
        return ChannelSettings(Path(data["tokens_file"]), Path(data["registry_file"]), Path(data["state_file"]), Path(data["inbox_dir"]),
                               data["to_node"], policy, limit)


class NodeChannel:
    """Answers the posts of the nodes: `(status, body)` for an `Authorization` header and a raw body."""

    def __init__(self, settings: ChannelSettings) -> None:
        self.settings = settings

    def handle(self, authorization: str, raw_body: bytes, *, now: float | None = None) -> tuple[int, dict[str, Any]]:
        scheme, _, presented = (authorization or "").partition(" ")
        try:
            node = authenticate(self.settings.tokens_file, presented) if scheme == "Bearer" else None
        except NodeChannelError:
            return 503, {"ok": False, "error": "the channel is not available"}
        if node is None:
            return 401, {"ok": False, "error": "unauthorized"}
        if len(raw_body) > self.settings.max_body_bytes:
            return 413, {"ok": False, "error": "too large"}
        try:
            data = json.loads(raw_body.decode("utf-8"))
            message = IncidentMessage.from_dict(data)
        except (UnicodeDecodeError, ValueError, ConfigValidationError):
            return 400, {"ok": False, "error": "not an incident-transport message"}
        if not MESSAGE_ID.match(message.message_id):
            return 400, {"ok": False, "error": "message_id"}
        try:
            registry_raw = load_json_document(self.settings.registry_file)
            if not all(isinstance(value, str) for value in registry_raw.values()):
                raise ConfigValidationError("registry")
            registry = NodeRegistry(secrets={str(k): str(v) for k, v in registry_raw.items()})
            with SqliteVerifierState(str(self.settings.state_file)) as state:
                result = verify_message(message, registry, self.settings.policy, state, authenticated_as=node,
                                        now=now, expected_to_node=self.settings.to_node)
        except (ConfigValidationError, OSError):
            return 503, {"ok": False, "error": "the channel is not available"}
        if not result.ok:
            return 403, {"ok": False, "code": result.code}
        inbox = self.settings.inbox_dir
        inbox.mkdir(parents=True, exist_ok=True)
        target = inbox / (message.message_id.replace(":", "_") + ".json")
        try:
            descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:  # the same escalation again with a fresh nonce: acknowledged, not stored twice
            return 200, {"ok": True, "duplicate": True, "message_id": message.message_id}
        except OSError:
            return 503, {"ok": False, "error": "the channel is not available"}
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"from_node": node, "received_at": _now(), "message": message.to_dict(include_mac=False)}, stream, indent=2, sort_keys=True)
        return 200, {"ok": True, "duplicate": False, "message_id": message.message_id}

