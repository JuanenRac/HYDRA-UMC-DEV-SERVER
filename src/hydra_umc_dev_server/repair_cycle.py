# =============================================================================
# HYDRA-UMC-DEV-SERVER - src/hydra_umc_dev_server/repair_cycle.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
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
  * the I60/T07 "apparent success" control: verification is only trusted
    if the base fingerprint is STILL the one the candidate was built
    for, and if the evidence references the SAME repro case.

Nothing here touches a real service - the installer and the run results
are injected.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .config import ConfigValidationError, _require_str

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

    def signature_ok(self, secret: str) -> bool:
        return bool(self.signature) and hmac.compare_digest(self.signature, _sign(secret, self._body()))

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

    def _body(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "approved_by": self.approved_by,
            "approved_for_base": self.approved_for_base,
            "approved_for_target": self.approved_for_target,
        }

    def signed(self, secret: str) -> "Approval":
        return Approval(**{**self._body(), "signature": _sign(secret, self._body())})

    def signature_ok(self, secret: str) -> bool:
        return bool(self.signature) and hmac.compare_digest(self.signature, _sign(secret, self._body()))


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
    """One incident's controlled repair, driven step by step. Any gate
    failure sets `state = "blocked"` with a reason and every later step
    is a no-op."""

    def __init__(self, incident_id: str, base_fingerprint: str, target: str, repro_case_id: str) -> None:
        self.incident_id = incident_id
        self.base_fingerprint = base_fingerprint
        self.target = target
        self.repro_case_id = repro_case_id
        self.state = STATE_BLOCKED
        self.reason: str | None = "not started"
        self.candidate: RepairCandidate | None = None

    def _block(self, reason: str) -> StepOutcome:
        self.state, self.reason = STATE_BLOCKED, reason
        return StepOutcome(False, self.state, reason)

    def _advance(self, state: str) -> StepOutcome:
        self.state, self.reason = state, None
        return StepOutcome(True, state)

    def confirm_repro(self, evidence: dict[str, Any]) -> StepOutcome:
        if not evidence.get("reproduced") or evidence.get("repro_case_id") != self.repro_case_id:
            return self._block("the failure was not reproduced for this repro case")
        return self._advance(STATE_REPRO_CONFIRMED)

    def raise_incident(self) -> StepOutcome:
        if self.state != STATE_REPRO_CONFIRMED:
            return self._block(f"cannot raise an incident from state {self.state!r}")
        return self._advance(STATE_INCIDENT_RAISED)

    def receive_candidate(self, candidate: RepairCandidate, candidate_secret: str) -> StepOutcome:
        if self.state != STATE_INCIDENT_RAISED:
            return self._block(f"cannot receive a candidate from state {self.state!r}")
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
        if not approval.signature_ok(approver_secret):
            return self._block("approval signature does not verify")
        assert self.candidate is not None
        if approval.candidate_id != self.candidate.candidate_id:
            return self._block("approval is for a different candidate")
        if approval.approved_for_base != self.base_fingerprint:
            return self._block("approval was issued for a different base")
        if approval.approved_for_target != self.target:
            return self._block("approval was issued for a different target")
        return self._advance(STATE_APPROVED)

    def install_isolated(self, installer: IsolatedInstaller) -> StepOutcome:
        if self.state != STATE_APPROVED:
            return self._block(f"cannot install from state {self.state!r}")
        assert self.candidate is not None
        if not installer.install(self.candidate):
            return self._block("isolated install failed")
        return self._advance(STATE_INSTALLED)

    def verify(self, evidence: dict[str, Any], installer: IsolatedInstaller, *, observed_base_fingerprint: str) -> StepOutcome:
        if self.state != STATE_INSTALLED:
            return self._block(f"cannot verify from state {self.state!r}")
        # I60/T07 control: a base that moved mid-cycle voids the result.
        if observed_base_fingerprint != self.base_fingerprint:
            installer.rollback()
            return self._block("base fingerprint changed during the cycle - the result is not trusted")
        if evidence.get("repro_case_id") != self.repro_case_id:
            installer.rollback()
            return self._block("verification evidence is for a different repro case")
        if not evidence.get("verified"):
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
