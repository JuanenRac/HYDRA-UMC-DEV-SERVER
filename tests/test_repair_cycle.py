# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_repair_cycle.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
"""DS08 - one fully controlled repair cycle. The happy path resolves the
case; a tampered / misdirected / mis-approved candidate is blocked; a
failed post-install check rolls back."""
import unittest

from hydra_umc_dev_server.repair_cycle import (
    STATE_BLOCKED,
    STATE_RECOVERED,
    STATE_VERIFIED,
    Approval,
    IsolatedInstaller,
    RepairCandidate,
    RepairCycle,
    check_candidate,
)
from hydra_umc_dev_server.runner import RunResult

_INC, _BASE, _TARGET, _CASE = "INC-42", "base-abc", "test-node", "repro-1"
_CAND_SECRET, _APPROVER_SECRET = "candidate-signer-secret", "approver-secret"


def _candidate(**over) -> RepairCandidate:
    data = dict(candidate_id="cand-1", for_incident_id=_INC, for_base_fingerprint=_BASE,
                for_target=_TARGET, patch_ref="a1b2c3d")
    data.update(over)
    return RepairCandidate(**data).signed(_CAND_SECRET)


def _approval(**over) -> Approval:
    data = dict(candidate_id="cand-1", approved_by="lead", approved_for_base=_BASE, approved_for_target=_TARGET)
    data.update(over)
    return Approval(**data).signed(_APPROVER_SECRET)


def _green() -> RunResult:
    return RunResult(task_id="t", outcome="completed", exit_code=0, duration_seconds=1.0)


def _red() -> RunResult:
    return RunResult(task_id="t", outcome="completed", exit_code=1, duration_seconds=1.0)


class FakeInstaller:
    def __init__(self, *, install_ok=True):
        self.install_ok = install_ok
        self.installed = False
        self.rolled_back = False

    def install(self, candidate) -> bool:
        self.installed = self.install_ok
        return self.install_ok

    def rollback(self) -> None:
        self.rolled_back = True


def _drive_to_installed(cycle: RepairCycle, installer, *, candidate=None, approval=None):
    cycle.confirm_repro({"reproduced": True, "repro_case_id": _CASE})
    cycle.raise_incident()
    cycle.receive_candidate(candidate or _candidate(), _CAND_SECRET)
    cycle.run_regression(_green())
    cycle.run_build_test(_green())
    cycle.apply_approval(approval or _approval(), _APPROVER_SECRET)
    cycle.install_isolated(installer)


class HappyPathTests(unittest.TestCase):
    def test_a_correct_candidate_runs_the_whole_cycle_to_verified(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        inst = FakeInstaller()
        _drive_to_installed(cycle, inst)
        out = cycle.verify({"repro_case_id": _CASE, "verified": True}, inst, observed_base_fingerprint=_BASE)
        self.assertTrue(out.ok)
        self.assertEqual(cycle.state, STATE_VERIFIED)
        self.assertTrue(inst.installed)
        self.assertFalse(inst.rolled_back)


class BlockedCandidateTests(unittest.TestCase):
    def test_an_unreproduced_failure_never_opens_the_cycle(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        out = cycle.confirm_repro({"reproduced": False, "repro_case_id": _CASE})
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("not reproduced", out.reason)

    def test_a_tampered_candidate_signature_is_blocked(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        cycle.confirm_repro({"reproduced": True, "repro_case_id": _CASE})
        cycle.raise_incident()
        tampered = RepairCandidate(**{**_candidate().to_dict(), "patch_ref": "evil"})  # body changed, sig now stale
        out = cycle.receive_candidate(tampered, _CAND_SECRET)
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("signature", out.reason)

    def test_a_candidate_for_another_base_is_blocked(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        cycle.confirm_repro({"reproduced": True, "repro_case_id": _CASE})
        cycle.raise_incident()
        out = cycle.receive_candidate(_candidate(for_base_fingerprint="other-base"), _CAND_SECRET)
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("base fingerprint", out.reason)

    def test_a_candidate_for_another_target_is_blocked(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        cycle.confirm_repro({"reproduced": True, "repro_case_id": _CASE})
        cycle.raise_incident()
        out = cycle.receive_candidate(_candidate(for_target="prod-node"), _CAND_SECRET)
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("target", out.reason)

    def test_a_red_regression_blocks_the_cycle(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        cycle.confirm_repro({"reproduced": True, "repro_case_id": _CASE})
        cycle.raise_incident()
        cycle.receive_candidate(_candidate(), _CAND_SECRET)
        out = cycle.run_regression(_red())
        self.assertEqual(cycle.state, STATE_BLOCKED)


class ApprovalTests(unittest.TestCase):
    def _to_build_test_passed(self, cycle):
        cycle.confirm_repro({"reproduced": True, "repro_case_id": _CASE})
        cycle.raise_incident()
        cycle.receive_candidate(_candidate(), _CAND_SECRET)
        cycle.run_regression(_green())
        cycle.run_build_test(_green())

    def test_an_unregistered_approver_is_blocked(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        self._to_build_test_passed(cycle)
        out = cycle.apply_approval(_approval(), None)
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("not registered", out.reason)

    def test_an_approval_issued_for_another_base_is_blocked(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        self._to_build_test_passed(cycle)
        out = cycle.apply_approval(_approval(approved_for_base="another-base"), _APPROVER_SECRET)
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("different base", out.reason)

    def test_an_approval_issued_for_another_target_is_blocked(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        self._to_build_test_passed(cycle)
        out = cycle.apply_approval(_approval(approved_for_target="prod-node"), _APPROVER_SECRET)
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("different target", out.reason)


class PostInstallRecoveryTests(unittest.TestCase):
    def test_a_failed_verification_rolls_back_and_ends_recovered(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        inst = FakeInstaller()
        _drive_to_installed(cycle, inst)
        out = cycle.verify({"repro_case_id": _CASE, "verified": False}, inst, observed_base_fingerprint=_BASE)
        self.assertFalse(out.ok)
        self.assertEqual(cycle.state, STATE_RECOVERED)
        self.assertTrue(inst.rolled_back)

    def test_a_base_that_moved_mid_cycle_voids_the_result_and_rolls_back(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        inst = FakeInstaller()
        _drive_to_installed(cycle, inst)
        out = cycle.verify({"repro_case_id": _CASE, "verified": True}, inst, observed_base_fingerprint="moved-base")
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("base fingerprint changed", out.reason)
        self.assertTrue(inst.rolled_back)

    def test_verification_evidence_for_a_different_repro_case_is_not_trusted(self):
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE)
        inst = FakeInstaller()
        _drive_to_installed(cycle, inst)
        out = cycle.verify({"repro_case_id": "some-other-case", "verified": True}, inst, observed_base_fingerprint=_BASE)
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertTrue(inst.rolled_back)


class CheckCandidateTests(unittest.TestCase):
    def test_the_fake_installer_satisfies_the_protocol(self):
        self.assertIsInstance(FakeInstaller(), IsolatedInstaller)

    def test_check_candidate_accepts_a_correct_one_and_names_each_mismatch(self):
        self.assertTrue(check_candidate(_candidate(), _CAND_SECRET, incident_id=_INC, base_fingerprint=_BASE, target=_TARGET).accepted)
        self.assertFalse(check_candidate(_candidate(), "wrong", incident_id=_INC, base_fingerprint=_BASE, target=_TARGET).accepted)
        self.assertIn("different incident", check_candidate(_candidate(for_incident_id="INC-9"), _CAND_SECRET, incident_id=_INC, base_fingerprint=_BASE, target=_TARGET).reason)


if __name__ == "__main__":
    unittest.main()
