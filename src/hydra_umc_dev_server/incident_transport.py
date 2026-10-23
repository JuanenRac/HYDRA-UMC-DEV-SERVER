# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/incident_transport.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""DS07 - an authenticated incident transport for the round trip with
HYDRA-UMC-OPS-AGENT.

This is a real protocol object, not a manual file drop. Every message is
HMAC-signed by a registered node and carries a nonce, a timestamp and a
contract version. `verify_message()` rejects, each with a named code and
each defended by test:

  * an unregistered identity           -> `unknown-identity`
  * a bad or missing signature         -> `bad-signature`
  * a node claiming to be another      -> `impersonation`
  * a replayed nonce                   -> `replay`
  * a timestamp outside the window     -> `stale`
  * too many messages in the window    -> `overloaded`
  * an incompatible contract version   -> `incompatible-version`

`IncidentSession` runs the full round trip - submit -> diagnosis ->
post-deploy verification - not just the submit. A dropped connection
leaves the session in `pending-ack`; `reconcile()` re-sends it, so a
network blip never loses or double-counts an incident.
"""
from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import secrets
import math
import sqlite3
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from .config import ConfigValidationError, _require_positive_int, _require_str

CONTRACT_VERSION = "incident-transport/1"

KIND_INCIDENT = "incident"
KIND_DIAGNOSIS = "diagnosis"
KIND_DEPLOY_VERIFICATION = "deploy-verification"
KIND_ACK = "ack"
_KINDS = (KIND_INCIDENT, KIND_DIAGNOSIS, KIND_DEPLOY_VERIFICATION, KIND_ACK)


# ---------------------------------------------------------------------------
# Registry + policy
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class NodeRegistry:
    """node_id -> shared HMAC secret. Built in memory or from a secrets
    file that is never committed (see docs/INCIDENT_TRANSPORT.md)."""

    secrets: dict[str, str] = field(default_factory=dict)

    def is_registered(self, node_id: str) -> bool:
        return node_id in self.secrets

    def secret_for(self, node_id: str) -> str | None:
        return self.secrets.get(node_id)


@dataclass(frozen=True)
class TransportPolicy:
    contract_version: str = CONTRACT_VERSION
    replay_window_seconds: int = 120
    max_messages_per_minute: int = 60

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "replay_window_seconds": self.replay_window_seconds,
            "max_messages_per_minute": self.max_messages_per_minute,
        }

    @staticmethod
    def from_dict(data: object) -> "TransportPolicy":
        if not isinstance(data, dict):
            raise ConfigValidationError("transport policy must be a JSON object")
        errors: list[str] = []
        version = _require_str(data, "contract_version", errors)
        if version and not _compatible(version):
            errors.append(f"'contract_version' {version!r} is not compatible with {CONTRACT_VERSION!r}")
        window = _require_positive_int(data, "replay_window_seconds", errors, default=120)
        rate = _require_positive_int(data, "max_messages_per_minute", errors, default=60)
        if errors:
            raise ConfigValidationError("; ".join(errors))
        return TransportPolicy(contract_version=version, replay_window_seconds=window, max_messages_per_minute=rate)


def _compatible(version: str) -> bool:
    return version == CONTRACT_VERSION or version.startswith("incident-transport/1.")


# ---------------------------------------------------------------------------
# Message + signing
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class IncidentMessage:
    message_id: str
    from_node: str
    to_node: str
    kind: str
    contract_version: str
    nonce: str
    sent_at: float
    payload: dict[str, Any]
    mac: str = ""

    def _signing_bytes(self) -> bytes:
        body = {
            "message_id": self.message_id,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "kind": self.kind,
            "contract_version": self.contract_version,
            "nonce": self.nonce,
            "sent_at": self.sent_at,
            "payload": self.payload,
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")

    def signed(self, secret: str) -> "IncidentMessage":
        mac = hmac.new(secret.encode("utf-8"), self._signing_bytes(), hashlib.sha256).hexdigest()
        return IncidentMessage(**{**self.to_dict(include_mac=False), "mac": mac})

    def to_dict(self, *, include_mac: bool = True) -> dict[str, Any]:
        d = {
            "message_id": self.message_id,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "kind": self.kind,
            "contract_version": self.contract_version,
            "nonce": self.nonce,
            "sent_at": self.sent_at,
            "payload": self.payload,
        }
        if include_mac:
            d["mac"] = self.mac
        return d

    @staticmethod
    def from_dict(data: object) -> "IncidentMessage":
        if not isinstance(data, dict):
            raise ConfigValidationError("incident message must be a JSON object")
        errors: list[str] = []
        fields = ("message_id", "from_node", "to_node", "kind", "contract_version", "nonce")
        values = {name: _require_str(data, name, errors) for name in fields}
        if values["kind"] and values["kind"] not in _KINDS:
            errors.append(f"'kind' must be one of {_KINDS}, not {values['kind']!r}")
        sent_at = data.get("sent_at")
        if isinstance(sent_at, bool) or not isinstance(sent_at, (int, float)):
            errors.append("'sent_at' must be a number (unix seconds)")
            sent_at = 0.0
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            errors.append("'payload' must be a JSON object")
            payload = {}
        mac = data.get("mac", "")
        if not isinstance(mac, str):
            errors.append("'mac' must be a string")
            mac = ""
        if errors:
            raise ConfigValidationError("; ".join(errors))
        return IncidentMessage(
            message_id=values["message_id"], from_node=values["from_node"], to_node=values["to_node"],
            kind=values["kind"], contract_version=values["contract_version"], nonce=values["nonce"],
            sent_at=float(sent_at), payload=payload, mac=mac,
        )


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    code: str | None = None
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "code": self.code, "reason": self.reason}


@dataclass
class VerifierState:
    """Mutable per-verifier state: nonces already seen, and per-node
    message timestamps for rate limiting. A test owns one of these.

    It lives in memory, so it is lost with the process: a replayed message is
    caught only by the process that saw the original. `SqliteVerifierState`
    keeps the same state in a file, for a verifier that is started once per
    message (the `incident verify` command) or by several processes."""

    seen_nonces: set[str] = field(default_factory=set)
    # when each nonce was accepted, so nonces older than the replay window can be
    # forgotten (a message that old is refused as stale anyway)
    nonce_times: dict[str, float] = field(default_factory=dict)
    rate_log: dict[str, list[float]] = field(default_factory=dict)

    # The operations `verify_message` needs, so another store can stand in for the memory.
    @contextlib.contextmanager
    def exclusive(self) -> Iterator[None]:
        yield

    def nonce_seen(self, nonce: str) -> bool:
        return nonce in self.seen_nonces

    def messages_in_window(self, node: str, at: float, window: float = 60.0) -> int:
        recent = self.rate_log.setdefault(node, [])
        recent[:] = [t for t in recent if at - t < window]
        return len(recent)

    def accept(self, node: str, nonce: str, at: float, replay_window: float) -> None:
        for old_nonce, seen_at in list(self.nonce_times.items()):
            if at - seen_at > replay_window:
                self.nonce_times.pop(old_nonce, None)
                self.seen_nonces.discard(old_nonce)
        self.seen_nonces.add(nonce)
        self.nonce_times[nonce] = at
        self.rate_log.setdefault(node, []).append(at)


class SqliteVerifierState(VerifierState):
    """The same state in a SQLite file (WAL), shared by every process that opens it. The check and the
    update of one message happen inside one `BEGIN IMMEDIATE` transaction, so two processes verifying
    the same message cannot both accept it. Entries older than their window are purged on every accept."""

    def __init__(self, path: str) -> None:
        super().__init__()
        self._conn = sqlite3.connect(path, isolation_level=None, timeout=10.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(
            "CREATE TABLE IF NOT EXISTS nonces (nonce TEXT PRIMARY KEY, at REAL NOT NULL);"
            "CREATE TABLE IF NOT EXISTS messages (node TEXT NOT NULL, at REAL NOT NULL);"
            "CREATE INDEX IF NOT EXISTS messages_by_node ON messages(node, at);"
        )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SqliteVerifierState":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @contextlib.contextmanager
    def exclusive(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    def nonce_seen(self, nonce: str) -> bool:
        return self._conn.execute("SELECT 1 FROM nonces WHERE nonce = ?", (nonce,)).fetchone() is not None

    def messages_in_window(self, node: str, at: float, window: float = 60.0) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM messages WHERE node = ? AND ? - at < ?", (node, at, window)).fetchone()
        return int(row[0])

    def accept(self, node: str, nonce: str, at: float, replay_window: float) -> None:
        self._conn.execute("DELETE FROM nonces WHERE ? - at > ?", (at, replay_window))
        self._conn.execute("DELETE FROM messages WHERE ? - at >= 60.0", (at,))
        self._conn.execute("INSERT INTO nonces(nonce, at) VALUES (?, ?)", (nonce, at))
        self._conn.execute("INSERT INTO messages(node, at) VALUES (?, ?)", (node, at))


def verify_message(
    message: IncidentMessage,
    registry: NodeRegistry,
    policy: TransportPolicy,
    state: VerifierState,
    *,
    authenticated_as: str,
    now: float | None = None,
    expected_to_node: str | None = None,
) -> VerifyResult:
    """`authenticated_as` is the identity the channel proved (e.g. the TLS
    client cert CN, or the connection's login). Every other property of
    the message is checked against it and the policy."""
    at = time.time() if now is None else now

    if not registry.is_registered(authenticated_as):
        return VerifyResult(False, "unknown-identity", f"{authenticated_as!r} is not a registered node")
    if message.from_node != authenticated_as:
        return VerifyResult(
            False, "impersonation",
            f"message claims from_node {message.from_node!r} but the channel is authenticated as {authenticated_as!r}",
        )
    if expected_to_node is not None and message.to_node != expected_to_node:
        return VerifyResult(
            False, "wrong-recipient",
            f"message is addressed to {message.to_node!r}, not to {expected_to_node!r}",
        )
    if not _compatible(message.contract_version):
        return VerifyResult(False, "incompatible-version",
                            f"{message.contract_version!r} is not compatible with {policy.contract_version!r}")

    secret = registry.secret_for(authenticated_as) or ""
    expected = message.signed(secret).mac
    if not message.mac or not hmac.compare_digest(message.mac, expected):
        return VerifyResult(False, "bad-signature", "HMAC does not match the registered secret")

    if not math.isfinite(message.sent_at):
        return VerifyResult(False, "stale", "sent_at is not a finite number")
    if abs(at - message.sent_at) > policy.replay_window_seconds:
        return VerifyResult(False, "stale",
                            f"sent_at is {abs(at - message.sent_at):.0f}s from now, outside the "
                            f"{policy.replay_window_seconds}s window")
    # the check and the update are one step: two verifiers of the same state cannot both accept one message
    with state.exclusive():
        if state.nonce_seen(message.nonce):
            return VerifyResult(False, "replay", f"nonce {message.nonce!r} was already accepted")

        recent = state.messages_in_window(authenticated_as, at)
        if recent >= policy.max_messages_per_minute:
            return VerifyResult(False, "overloaded",
                                f"{authenticated_as!r} sent {recent} messages in the last minute "
                                f"(limit {policy.max_messages_per_minute})")

        state.accept(authenticated_as, message.nonce, at, policy.replay_window_seconds)
    return VerifyResult(True)


# ---------------------------------------------------------------------------
# Round-trip session
# ---------------------------------------------------------------------------
@runtime_checkable
class Channel(Protocol):
    def send(self, message: IncidentMessage) -> None: ...

    def poll(self) -> IncidentMessage | None:
        """Next inbound message, or None. Never blocks."""


STATE_SUBMITTED = "submitted"
STATE_PENDING_ACK = "pending-ack"
STATE_DIAGNOSED = "diagnosed"
STATE_DEPLOY_VERIFIED = "deploy-verified"
STATE_FAILED = "failed"


@dataclass
class IncidentSession:
    """The DEV-SERVER side of one incident's round trip."""

    self_node: str
    peer_node: str
    secret: str
    channel: Channel
    # The peer's own secret: what its messages are signed with. Without it no
    # inbound message can be verified, so none is accepted.
    peer_secret: str = ""
    policy: TransportPolicy = field(default_factory=TransportPolicy)
    state: str = STATE_SUBMITTED
    incident_id: str = ""
    last_sent: IncidentMessage | None = None
    diagnosis: dict[str, Any] | None = None
    deploy_verification: dict[str, Any] | None = None
    # inbound messages refused by pump(), with the reason (for logs and tests)
    rejected: list[str] = field(default_factory=list)
    _seq: int = 0
    _verifier: VerifierState = field(default_factory=VerifierState)

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self.self_node}-{self._seq:04d}"

    def _new_nonce(self) -> str:
        # unpredictable and unique across restarts (a counter starts again at 1)
        return f"n-{secrets.token_hex(12)}"

    def submit_incident(self, incident_id: str, payload: dict[str, Any], *, now: float | None = None) -> IncidentMessage:
        at = time.time() if now is None else now
        self.incident_id = incident_id
        msg = IncidentMessage(
            message_id=self._next_id("inc"), from_node=self.self_node, to_node=self.peer_node,
            kind=KIND_INCIDENT, contract_version=CONTRACT_VERSION, nonce=self._new_nonce(),
            sent_at=at, payload={"incident_id": incident_id, **payload},
        ).signed(self.secret)
        self.channel.send(msg)
        self.last_sent = msg
        self.state = STATE_PENDING_ACK
        return msg

    def pump(self, *, now: float | None = None) -> None:
        """Consume every inbound message and advance the state machine. Each
        message must pass verify_message() as coming from the peer (signature,
        recipient, version, freshness, nonce, rate), carry this incident's id, and
        the state only moves forward: a late or forged message can neither confirm a
        deployment nor undo a verified one."""
        registry = NodeRegistry(secrets={self.peer_node: self.peer_secret} if self.peer_secret else {})
        while True:
            msg = self.channel.poll()
            if msg is None:
                return
            result = verify_message(
                msg, registry, self.policy, self._verifier,
                authenticated_as=self.peer_node, now=now, expected_to_node=self.self_node,
            )
            if not result.ok:
                self.rejected.append(f"{result.code}: {result.reason}")
                continue
            if msg.payload.get("incident_id") != self.incident_id:
                self.rejected.append("wrong-incident: the message is about another incident")
                continue
            if self.state in (STATE_DEPLOY_VERIFIED, STATE_FAILED):
                self.rejected.append(f"closed: the session already ended as {self.state!r}")
                continue
            if msg.kind == KIND_ACK:
                if self.state == STATE_PENDING_ACK:
                    self.state = STATE_SUBMITTED
            elif msg.kind == KIND_DIAGNOSIS:
                self.diagnosis = dict(msg.payload)
                self.state = STATE_DIAGNOSED
            elif msg.kind == KIND_DEPLOY_VERIFICATION:
                self.deploy_verification = dict(msg.payload)
                verified = msg.payload.get("verified") is True
                self.state = STATE_DEPLOY_VERIFIED if verified else STATE_FAILED

    def reconcile(self, *, now: float | None = None) -> bool:
        """If the last message is still unacked (a dropped connection),
        re-send the SAME incident with a FRESH nonce and message id - the
        anti-replay check stays strict, and the peer de-dupes on the
        stable `payload.incident_id` (already has it -> just re-ack; never
        got it -> process it). Returns True if a re-send happened."""
        if self.state != STATE_PENDING_ACK or self.last_sent is None:
            return False
        at = time.time() if now is None else now
        resend = IncidentMessage(
            message_id=self._next_id("inc"), from_node=self.self_node, to_node=self.peer_node,
            kind=self.last_sent.kind, contract_version=CONTRACT_VERSION, nonce=self._new_nonce(),
            sent_at=at, payload=dict(self.last_sent.payload),
        ).signed(self.secret)
        self.channel.send(resend)
        self.last_sent = resend
        return True
