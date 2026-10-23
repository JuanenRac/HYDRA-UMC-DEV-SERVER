# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/repair_cycle.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""DS08 - one fully controlled repair cycle, chaining the pieces already
built:

    repro-confirmed -> incident-raised -> candidate-received
      -> regression-passed -> build-test-passed -> approved
      -> installed -> verified   (or -> recovered / -> blocked)

Every step is gated, each defended by test:

  * an unreproduced failure never opens the cycle.
  * a candidate whose signature does not verify (tampered), or that is
    pinned to a DIFFERENT base fingerprint or a DIFFERENT target, is
    blocked - not silently accepted.
  * regression and build-test must actually be green (a `RunResult` with
    outcome `completed` and exit code 0).
  * an approval must be signed by a registered approver AND be FOR this
    exact base and target - an approval issued for another base/target
    is blocked.
  * install goes to an isolated location through an injectable seam, not
    the real target; a failed post-install verification triggers
    `rollback()` and the cycle ends `recovered`, never `verified`.
  * the /T07 "apparent success" control: verification is only trusted
    if the base fingerprint is STILL the one the candidate was built
    for, and if the evidence references the SAME repro case.

Nothing here touches a real service - the installer and the run results
are injected.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from .config import ConfigValidationError, _require_str
from .signing import is_public_key, sign_body, signature_matches

STATE_NOT_STARTED = "not-started"
STATE_BLOCKED = "blocked"
STATE_REPRO_CONFIRMED = "repro-confirmed"
STATE_INCIDENT_RAISED = "incident-raised"
STATE_CANDIDATE_RECEIVED = "candidate-received"
STATE_REGRESSION_PASSED = "regression-passed"
STATE_BUILD_TEST_PASSED = "build-test-passed"
STATE_APPROVED = "approved"
STATE_INSTALLED = "installed"
STATE_VERIFIED = "verified"
STATE_RECOVERED = "recovered"


def _parse_expiry(text: str) -> datetime | None:
    """A UTC ISO 8601 moment (``2026-01-31T12:00:00Z``), or None when it is empty or not a moment with a UTC offset."""
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        return None
    return moment.astimezone(timezone.utc)


def _sign(secret: str, body: dict[str, Any]) -> str:
    canon = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canon, hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class RepairCandidate:
    candidate_id: str
    for_incident_id: str
    for_base_fingerprint: str
    for_target: str
    patch_ref: str
    signature: str = ""

    def _body(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "for_incident_id": self.for_incident_id,
            "for_base_fingerprint": self.for_base_fingerprint,
            "for_target": self.for_target,
            "patch_ref": self.patch_ref,
        }

    def signed(self, secret: str) -> "RepairCandidate":
        return RepairCandidate(**{**self._body(), "signature": _sign(secret, self._body())})

    def signed_ed25519(self, seed: str) -> "RepairCandidate":
        """Signed with the private key (`ed25519-seed:...`) of the signer; the checker needs only the public key."""
        return RepairCandidate(**{**self._body(), "signature": sign_body(seed, self._body())})

    def signature_ok(self, key: str) -> bool:
        """`key` is the HMAC secret of the signer, or its public key (`ed25519-public:...`) for a candidate
        signed with `signed_ed25519`. The two kinds never mix."""
        return signature_matches(key, self._body(), self.signature)

    def to_dict(self) -> dict[str, Any]:
        return {**self._body(), "signature": self.signature}

    @staticmethod
    def from_dict(data: object) -> "RepairCandidate":
        if not isinstance(data, dict):
            raise ConfigValidationError("repair candidate must be a JSON object")
        errors: list[str] = []
        f = {n: _require_str(data, n, errors) for n in
             ("candidate_id", "for_incident_id", "for_base_fingerprint", "for_target", "patch_ref")}
        sig = data.get("signature", "")
        if not isinstance(sig, str):
            errors.append("'signature' must be a string")
            sig = ""
        if errors:
            raise ConfigValidationError("; ".join(errors))
        return RepairCandidate(f["candidate_id"], f["for_incident_id"], f["for_base_fingerprint"],
                               f["for_target"], f["patch_ref"], sig)


@dataclass(frozen=True)
class Approval:
    candidate_id: str
    approved_by: str
    approved_for_base: str
    approved_for_target: str
    signature: str = ""
    # The patch the approver looked at (the candidate's patch_ref) and the moment the approval stops being valid (UTC, ISO 8601,
    # for example 2026-01-31T12:00:00Z). Both are part of what is signed; a cycle that requires bound approvals refuses one without them.
    approved_patch_ref: str = ""
    expires_at: str = ""

    def _body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "candidate_id": self.candidate_id,
            "approved_by": self.approved_by,
            "approved_for_base": self.approved_for_base,
            "approved_for_target": self.approved_for_target,
        }
        # only when set, so an approval signed before these fields existed keeps verifying
        if self.approved_patch_ref:
            body["approved_patch_ref"] = self.approved_patch_ref
        if self.expires_at:
            body["expires_at"] = self.expires_at
        return body

    def signed(self, secret: str) -> "Approval":
        return Approval(**{**self._body(), "signature": _sign(secret, self._body())})

    def signed_ed25519(self, seed: str) -> "Approval":
        return Approval(**{**self._body(), "signature": sign_body(seed, self._body())})

    def signature_ok(self, key: str) -> bool:
        return signature_matches(key, self._body(), self.signature)


@runtime_checkable
class IsolatedInstaller(Protocol):
    def install(self, candidate: RepairCandidate) -> bool:
        """Install into an ISOLATED location (never the real target).
        Returns True on success."""

    def rollback(self) -> None:
        """Undo the last install."""


@dataclass(frozen=True)
class StepOutcome:
    ok: bool
    state: str
    reason: str | None = None


class RepairCycle:
    """One incident's controlled repair, driven step by step. A new cycle is
    "not-started"; any gate failure sets `state = "blocked"` with a reason,
    and a blocked cycle is final: every later step answers "blocked" and
    changes nothing."""

    def __init__(
        self,
        incident_id: str,
        base_fingerprint: str,
        target: str,
        repro_case_id: str,
        *,
        allow_symmetric_keys: bool = False,
        require_bound_approval: bool = True,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        # By default only Ed25519 public keys verify a candidate or an approval: an HMAC secret has to be on the verifying side too, so
        # whoever can verify could also forge. `allow_symmetric_keys` keeps the shared secret as an opt-in compatibility mode.
        self.allow_symmetric_keys = allow_symmetric_keys
        # By default an approval must name the patch it approves and carry an expiry that has not passed.
        self.require_bound_approval = require_bound_approval
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self.incident_id = incident_id
        self.base_fingerprint = base_fingerprint
        self.target = target
        self.repro_case_id = repro_case_id
        self.state = STATE_NOT_STARTED
        self.reason: str | None = "not started"
        self.candidate: RepairCandidate | None = None

    def _block(self, reason: str) -> StepOutcome:
        if self.state == STATE_BLOCKED:  # already final: keep the reason that blocked it
            return StepOutcome(False, self.state, self.reason)
        self.state, self.reason = STATE_BLOCKED, reason
        return StepOutcome(False, self.state, reason)

    def _advance(self, state: str) -> StepOutcome:
        self.state, self.reason = state, None
        return StepOutcome(True, state)

    def confirm_repro(self, evidence: dict[str, Any]) -> StepOutcome:
        if self.state != STATE_NOT_STARTED:
            return self._block(f"cannot confirm the reproduction from state {self.state!r}")
        if evidence.get("reproduced") is not True or evidence.get("repro_case_id") != self.repro_case_id:
            return self._block("the failure was not reproduced for this repro case")
        return self._advance(STATE_REPRO_CONFIRMED)

    def raise_incident(self) -> StepOutcome:
        if self.state != STATE_REPRO_CONFIRMED:
            return self._block(f"cannot raise an incident from state {self.state!r}")
        return self._advance(STATE_INCIDENT_RAISED)

    def receive_candidate(self, candidate: RepairCandidate, candidate_secret: str) -> StepOutcome:
        if self.state != STATE_INCIDENT_RAISED:
            return self._block(f"cannot receive a candidate from state {self.state!r}")
        if not self.allow_symmetric_keys and not is_public_key(candidate_secret):
            return self._block("a shared secret cannot verify a candidate: register the signer's Ed25519 public key")
        if not candidate.signature_ok(candidate_secret):
            return self._block("candidate signature does not verify - tampered or unsigned")
        if candidate.for_incident_id != self.incident_id:
            return self._block("candidate is for a different incident")
        if candidate.for_base_fingerprint != self.base_fingerprint:
            return self._block("candidate is pinned to a different base fingerprint")
        if candidate.for_target != self.target:
            return self._block("candidate is for a different target")
        self.candidate = candidate
        return self._advance(STATE_CANDIDATE_RECEIVED)

    def run_regression(self, run_result: Any) -> StepOutcome:
        if self.state != STATE_CANDIDATE_RECEIVED:
            return self._block(f"cannot run regression from state {self.state!r}")
        if getattr(run_result, "outcome", None) != "completed" or getattr(run_result, "exit_code", None) != 0:
            return self._block("regression did not pass")
        return self._advance(STATE_REGRESSION_PASSED)

    def run_build_test(self, run_result: Any) -> StepOutcome:
        if self.state != STATE_REGRESSION_PASSED:
            return self._block(f"cannot run build-test from state {self.state!r}")
        if getattr(run_result, "outcome", None) != "completed" or getattr(run_result, "exit_code", None) != 0:
            return self._block("build-test did not pass")
        return self._advance(STATE_BUILD_TEST_PASSED)

    def apply_approval(self, approval: Approval, approver_secret: str | None) -> StepOutcome:
        if self.state != STATE_BUILD_TEST_PASSED:
            return self._block(f"cannot apply an approval from state {self.state!r}")
        if approver_secret is None:
            return self._block(f"approver {approval.approved_by!r} is not registered")
        if not self.allow_symmetric_keys and not is_public_key(approver_secret):
            return self._block("a shared secret cannot verify an approval: register the approver's Ed25519 public key")
        if not approval.signature_ok(approver_secret):
            return self._block("approval signature does not verify")
        if self.candidate is None:
            return self._block("no candidate was received")
        if approval.candidate_id != self.candidate.candidate_id:
            return self._block("approval is for a different candidate")
        if approval.approved_patch_ref and approval.approved_patch_ref != self.candidate.patch_ref:
            return self._block("approval was issued for a different patch")
        if self.require_bound_approval and not approval.approved_patch_ref:
            return self._block("approval does not name the patch it approves")
        if approval.expires_at or self.require_bound_approval:
            expiry = _parse_expiry(approval.expires_at)
            if expiry is None:
                return self._block("approval carries no valid expiry (UTC, ISO 8601)")
            if self._clock() >= expiry:
                return self._block("approval has expired")
        if approval.approved_for_base != self.base_fingerprint:
            return self._block("approval was issued for a different base")
        if approval.approved_for_target != self.target:
            return self._block("approval was issued for a different target")
        return self._advance(STATE_APPROVED)

    def install_isolated(self, installer: IsolatedInstaller) -> StepOutcome:
        if self.state != STATE_APPROVED:
            return self._block(f"cannot install from state {self.state!r}")
        if self.candidate is None:
            return self._block("no candidate was received")
        if not installer.install(self.candidate):
            return self._block("isolated install failed")
        return self._advance(STATE_INSTALLED)

    def verify(self, evidence: dict[str, Any], installer: IsolatedInstaller, *, observed_base_fingerprint: str) -> StepOutcome:
        if self.state != STATE_INSTALLED:
            return self._block(f"cannot verify from state {self.state!r}")
        # /T07 control: a base that moved mid-cycle voids the result.
        if observed_base_fingerprint != self.base_fingerprint:
            installer.rollback()
            return self._block("base fingerprint changed during the cycle - the result is not trusted")
        if evidence.get("repro_case_id") != self.repro_case_id:
            installer.rollback()
            return self._block("verification evidence is for a different repro case")
        if evidence.get("verified") is not True:
            installer.rollback()
            self.state, self.reason = STATE_RECOVERED, "post-install verification failed - rolled back"
            return StepOutcome(False, self.state, self.reason)
        return self._advance(STATE_VERIFIED)


# ---------------------------------------------------------------------------
# The CLI-testable half: check one candidate in isolation
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class CandidateCheck:
    accepted: bool
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"accepted": self.accepted, "reason": self.reason}


def check_candidate(
    candidate: RepairCandidate,
    candidate_secret: str,
    *,
    incident_id: str,
    base_fingerprint: str,
    target: str,
) -> CandidateCheck:
    """The gate `receive_candidate` applies, usable without a live cycle."""
    if not candidate.signature_ok(candidate_secret):
        return CandidateCheck(False, "signature does not verify - tampered or unsigned")
    if candidate.for_incident_id != incident_id:
        return CandidateCheck(False, "candidate is for a different incident")
    if candidate.for_base_fingerprint != base_fingerprint:
        return CandidateCheck(False, "candidate is pinned to a different base fingerprint")
    if candidate.for_target != target:
        return CandidateCheck(False, "candidate is for a different target")
    return CandidateCheck(True)
