# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_incident_transport.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS07 - authenticated incident transport. Every rejection code, plus
the full round trip and reconciliation after a dropped connection, in
memory - no file drop, no network."""
import unittest
from pathlib import Path

from hydra_umc_dev_server.config import ConfigValidationError, load_json_document
from hydra_umc_dev_server.incident_transport import (
    CONTRACT_VERSION,
    KIND_ACK,
    KIND_DEPLOY_VERIFICATION,
    KIND_DIAGNOSIS,
    KIND_INCIDENT,
    STATE_DEPLOY_VERIFIED,
    STATE_PENDING_ACK,
    Channel,
    IncidentMessage,
    IncidentSession,
    NodeRegistry,
    TransportPolicy,
    VerifierState,
    verify_message,
)

_EXAMPLE = Path(__file__).resolve().parent.parent / "configs" / "incident-transport.example.json"
_DEV, _OPS = "dev-server-01", "ops-agent-01"
_SECRETS = {_DEV: "dev-secret", _OPS: "ops-secret"}


def _registry() -> NodeRegistry:
    return NodeRegistry(secrets=dict(_SECRETS))


def _policy() -> TransportPolicy:
    return TransportPolicy.from_dict(load_json_document(_EXAMPLE))


def _msg(*, from_node=_DEV, to_node=_OPS, kind=KIND_INCIDENT, nonce="n1", sent_at=1000.0,
         payload=None, version=CONTRACT_VERSION, secret=None) -> IncidentMessage:
    m = IncidentMessage(
        message_id="m1", from_node=from_node, to_node=to_node, kind=kind,
        contract_version=version, nonce=nonce, sent_at=sent_at, payload=payload or {"incident_id": "INC-1"},
    )
    return m.signed(_SECRETS[from_node] if secret is None else secret)


class VerifyRejectionTests(unittest.TestCase):
    def setUp(self):
        self.reg, self.pol = _registry(), _policy()

    def _verify(self, message, *, authenticated_as=_DEV, now=1000.0, state=None):
        return verify_message(message, self.reg, self.pol, state or VerifierState(),
                              authenticated_as=authenticated_as, now=now)

    def test_a_valid_message_is_accepted_and_its_nonce_is_remembered(self):
        state = VerifierState()
        r = self._verify(_msg(), state=state)
        self.assertTrue(r.ok, r.reason)
        self.assertIn("n1", state.seen_nonces)

    def test_an_unregistered_identity_is_rejected(self):
        r = self._verify(_msg(), authenticated_as="ghost-node")
        self.assertEqual(r.code, "unknown-identity")

    def test_a_bad_signature_is_rejected(self):
        r = self._verify(_msg(secret="wrong-secret"))
        self.assertEqual(r.code, "bad-signature")

    def test_a_node_claiming_to_be_another_is_rejected(self):
        # signed correctly as dev-server-01, but the channel authenticated as ops-agent-01
        r = self._verify(_msg(from_node=_DEV), authenticated_as=_OPS)
        self.assertEqual(r.code, "impersonation")

    def test_a_replayed_nonce_is_rejected(self):
        state = VerifierState()
        self.assertTrue(self._verify(_msg(nonce="dup"), state=state).ok)
        self.assertEqual(self._verify(_msg(nonce="dup", sent_at=1000.0), state=state).code, "replay")

    def test_a_stale_timestamp_is_rejected(self):
        r = self._verify(_msg(sent_at=100.0), now=1000.0)  # 900s old, window is 120
        self.assertEqual(r.code, "stale")

    def test_an_incompatible_contract_version_is_rejected(self):
        r = self._verify(_msg(version="incident-transport/2"))
        self.assertEqual(r.code, "incompatible-version")

    def test_an_overloaded_sender_is_rejected(self):
        state = VerifierState()
        for i in range(self.pol.max_messages_per_minute):
            self.assertTrue(self._verify(_msg(nonce=f"n{i}"), state=state, now=1000.0).ok)
        r = self._verify(_msg(nonce="n-over"), state=state, now=1000.0)
        self.assertEqual(r.code, "overloaded")


# ---------------------------------------------------------------------------
# Round trip
# ---------------------------------------------------------------------------
class PairedChannel:
    """An in-memory two-endpoint channel. No file, no socket."""

    def __init__(self):
        self._to_a: list[IncidentMessage] = []
        self._to_b: list[IncidentMessage] = []

    def endpoint(self, side: str) -> "PairedEndpoint":
        return PairedEndpoint(self, side)


class PairedEndpoint:
    def __init__(self, ch: PairedChannel, side: str):
        self._ch, self._side = ch, side

    def send(self, message: IncidentMessage) -> None:
        (self._ch._to_b if self._side == "a" else self._ch._to_a).append(message)

    def poll(self) -> IncidentMessage | None:
        box = self._ch._to_a if self._side == "a" else self._ch._to_b
        return box.pop(0) if box else None


class FakeOpsAgent:
    """The peer side. Verifies, acks, diagnoses, then reports a
    post-deploy verification. De-dupes on payload.incident_id."""

    def __init__(self, endpoint: PairedEndpoint, *, deploy_verified: bool = True):
        self.ep = endpoint
        self.reg, self.pol, self.state = _registry(), _policy(), VerifierState()
        self.handled: set[str] = set()
        self.deploy_verified = deploy_verified
        self._seq = 0

    def _mk(self, kind: str, payload: dict) -> IncidentMessage:
        self._seq += 1
        return IncidentMessage(
            message_id=f"ops-{self._seq}", from_node=_OPS, to_node=_DEV, kind=kind,
            contract_version=CONTRACT_VERSION, nonce=f"ops-n-{self._seq}", sent_at=1000.0, payload=payload,
        ).signed(_SECRETS[_OPS])

    def pump(self, *, now: float = 1000.0) -> None:
        while True:
            msg = self.ep.poll()
            if msg is None:
                return
            r = verify_message(msg, self.reg, self.pol, self.state, authenticated_as=_DEV, now=now)
            if not r.ok:
                continue
            if msg.kind != KIND_INCIDENT:
                continue
            incident_id = msg.payload.get("incident_id", "")
            self.ep.send(self._mk(KIND_ACK, {"incident_id": incident_id}))
            if incident_id in self.handled:
                continue  # a reconciled re-send - ack again, do not re-process
            self.handled.add(incident_id)
            self.ep.send(self._mk(KIND_DIAGNOSIS, {"incident_id": incident_id, "summary": "unit inactive"}))
            self.ep.send(self._mk(KIND_DEPLOY_VERIFICATION, {"incident_id": incident_id, "verified": self.deploy_verified}))


class RoundTripTests(unittest.TestCase):
    def _wire(self, **ops_kw):
        ch = PairedChannel()
        session = IncidentSession(self_node=_DEV, peer_node=_OPS, secret=_SECRETS[_DEV], channel=ch.endpoint("a"))
        ops = FakeOpsAgent(ch.endpoint("b"), **ops_kw)
        return session, ops

    def test_the_full_submit_diagnosis_deploy_verification_round_trip(self):
        session, ops = self._wire()
        session.submit_incident("INC-42", {"service": "hydra-umc-server", "detail": "not active"}, now=1000.0)
        ops.pump()
        session.pump()
        self.assertEqual(session.state, STATE_DEPLOY_VERIFIED)
        self.assertEqual(session.diagnosis["summary"], "unit inactive")
        self.assertTrue(session.deploy_verification["verified"])

    def test_a_failed_post_deploy_verification_ends_the_session_in_failed(self):
        session, ops = self._wire(deploy_verified=False)
        session.submit_incident("INC-7", {}, now=1000.0)
        ops.pump()
        session.pump()
        self.assertEqual(session.state, "failed")

    def test_a_dropped_connection_leaves_a_reconcilable_state_never_a_lost_incident(self):
        session, ops = self._wire()
        session.submit_incident("INC-9", {}, now=1000.0)
        # network drop: the ops agent never sees the first message
        ch = session.channel._ch  # type: ignore[attr-defined]
        ch._to_b.clear()
        self.assertEqual(session.state, STATE_PENDING_ACK)
        # reconcile re-sends the SAME incident with a fresh nonce
        self.assertTrue(session.reconcile(now=1100.0))
        resent = ch._to_b[-1]
        self.assertNotEqual(resent.nonce, "n1")
        self.assertEqual(resent.payload["incident_id"], "INC-9")
        ops.pump(now=1100.0)
        session.pump()
        self.assertEqual(session.state, STATE_DEPLOY_VERIFIED)
        self.assertEqual(len(ops.handled), 1)  # processed once, not twice


class MessageAndPolicyShapeTests(unittest.TestCase):
    def test_a_message_round_trips_through_to_dict_from_dict(self):
        m = _msg()
        again = IncidentMessage.from_dict(m.to_dict())
        self.assertEqual(again.to_dict(), m.to_dict())

    def test_the_shipped_policy_example_is_valid(self):
        self.assertEqual(_policy().contract_version, CONTRACT_VERSION)

    def test_the_policy_rejects_an_incompatible_contract_version(self):
        with self.assertRaises(ConfigValidationError):
            TransportPolicy.from_dict({"contract_version": "incident-transport/9"})

    def test_the_paired_endpoint_satisfies_the_channel_protocol(self):
        self.assertIsInstance(PairedChannel().endpoint("a"), Channel)


if __name__ == "__main__":
    unittest.main()
