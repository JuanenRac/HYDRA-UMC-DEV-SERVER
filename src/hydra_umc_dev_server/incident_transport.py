# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/incident_transport.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
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

import hashlib
import hmac
import json
import time
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
    message timestamps for rate limiting. A test owns one of these."""

    seen_nonces: set[str] = field(default_factory=set)
    rate_log: dict[str, list[float]] = field(default_factory=dict)


def verify_message(
    message: IncidentMessage,
    registry: NodeRegistry,
    policy: TransportPolicy,
    state: VerifierState,
    *,
    authenticated_as: str,
    now: float | None = None,
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
    if not _compatible(message.contract_version):
        return VerifyResult(False, "incompatible-version",
                            f"{message.contract_version!r} is not compatible with {policy.contract_version!r}")

    secret = registry.secret_for(authenticated_as) or ""
    expected = message.signed(secret).mac
    if not message.mac or not hmac.compare_digest(message.mac, expected):
        return VerifyResult(False, "bad-signature", "HMAC does not match the registered secret")

    if abs(at - message.sent_at) > policy.replay_window_seconds:
        return VerifyResult(False, "stale",
                            f"sent_at is {abs(at - message.sent_at):.0f}s from now, outside the "
                            f"{policy.replay_window_seconds}s window")
    if message.nonce in state.seen_nonces:
        return VerifyResult(False, "replay", f"nonce {message.nonce!r} was already accepted")

    window = state.rate_log.setdefault(authenticated_as, [])
    window[:] = [t for t in window if at - t < 60.0]
    if len(window) >= policy.max_messages_per_minute:
        return VerifyResult(False, "overloaded",
                            f"{authenticated_as!r} sent {len(window)} messages in the last minute "
                            f"(limit {policy.max_messages_per_minute})")

    state.seen_nonces.add(message.nonce)
    window.append(at)
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
    state: str = STATE_SUBMITTED
    incident_id: str = ""
    last_sent: IncidentMessage | None = None
    diagnosis: dict[str, Any] | None = None
    deploy_verification: dict[str, Any] | None = None
    _seq: int = 0

    def _next_id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self.self_node}-{self._seq:04d}"

    def submit_incident(self, incident_id: str, payload: dict[str, Any], *, now: float | None = None) -> IncidentMessage:
        at = time.time() if now is None else now
        self.incident_id = incident_id
        msg = IncidentMessage(
            message_id=self._next_id("inc"), from_node=self.self_node, to_node=self.peer_node,
            kind=KIND_INCIDENT, contract_version=CONTRACT_VERSION, nonce=self._next_id("n"),
            sent_at=at, payload={"incident_id": incident_id, **payload},
        ).signed(self.secret)
        self.channel.send(msg)
        self.last_sent = msg
        self.state = STATE_PENDING_ACK
        return msg

    def pump(self) -> None:
        """Consume every inbound message and advance the state machine."""
        while True:
            msg = self.channel.poll()
            if msg is None:
                return
            if msg.kind == KIND_ACK:
                if self.state == STATE_PENDING_ACK:
                    self.state = STATE_SUBMITTED
            elif msg.kind == KIND_DIAGNOSIS:
                self.diagnosis = dict(msg.payload)
                self.state = STATE_DIAGNOSED
            elif msg.kind == KIND_DEPLOY_VERIFICATION:
                self.deploy_verification = dict(msg.payload)
                verified = bool(msg.payload.get("verified"))
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
            kind=self.last_sent.kind, contract_version=CONTRACT_VERSION, nonce=self._next_id("n"),
            sent_at=at, payload=dict(self.last_sent.payload),
        ).signed(self.secret)
        self.channel.send(resend)
        self.last_sent = resend
        return True
