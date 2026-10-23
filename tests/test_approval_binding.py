# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_approval_binding.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""By default a repair cycle verifies with Ed25519 public keys only, and an approval names the patch it approves and expires."""
import unittest
from datetime import datetime, timedelta, timezone

from hydra_umc_dev_server.repair_cycle import (
    STATE_APPROVED,
    STATE_BLOCKED,
    STATE_BUILD_TEST_PASSED,
    Approval,
    RepairCandidate,
    RepairCycle,
)
from hydra_umc_dev_server.runner import RunResult
from hydra_umc_dev_server.signing import generate_key_pair

INC, BASE, TARGET, CASE = "inc-1", "base-1", "t1", "case-1"
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def _green():
    return RunResult(task_id="t", outcome="completed", exit_code=0, duration_seconds=1.0)


def _candidate(seed):
    return RepairCandidate("c1", INC, BASE, TARGET, "patch-1").signed_ed25519(seed)


def _approval(seed, **over):
    data = dict(candidate_id="c1", approved_by="ana", approved_for_base=BASE, approved_for_target=TARGET,
                approved_patch_ref="patch-1", expires_at="2026-01-01T13:00:00Z")
    data.update(over)
    return Approval(**data).signed_ed25519(seed)


def _cycle_at_build_test_passed(candidate_public, candidate):
    cycle = RepairCycle(INC, BASE, TARGET, CASE, clock=lambda: NOW)
    cycle.confirm_repro({"reproduced": True, "repro_case_id": CASE})
    cycle.raise_incident()
    cycle.receive_candidate(candidate, candidate_public)
    cycle.run_regression(_green())
    cycle.run_build_test(_green())
    assert cycle.state == STATE_BUILD_TEST_PASSED, cycle.reason
    return cycle


class AsymmetricByDefaultTests(unittest.TestCase):
    def test_a_shared_secret_cannot_verify_a_candidate_by_default(self):
        cycle = RepairCycle(INC, BASE, TARGET, CASE)
        cycle.confirm_repro({"reproduced": True, "repro_case_id": CASE})
        cycle.raise_incident()
        out = cycle.receive_candidate(RepairCandidate("c1", INC, BASE, TARGET, "patch-1").signed("secret"), "secret")
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("Ed25519", out.reason)

    def test_the_shared_secret_is_an_opt_in(self):
        cycle = RepairCycle(INC, BASE, TARGET, CASE, allow_symmetric_keys=True)
        cycle.confirm_repro({"reproduced": True, "repro_case_id": CASE})
        cycle.raise_incident()
        out = cycle.receive_candidate(RepairCandidate("c1", INC, BASE, TARGET, "patch-1").signed("secret"), "secret")
        self.assertTrue(out.ok, out.reason)

    def test_a_shared_secret_cannot_verify_an_approval_by_default(self):
        seed, public = generate_key_pair()
        cycle = _cycle_at_build_test_passed(public, _candidate(seed))
        out = cycle.apply_approval(Approval("c1", "ana", BASE, TARGET, approved_patch_ref="patch-1", expires_at="2026-01-01T13:00:00Z").signed("secret"), "secret")
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("Ed25519", out.reason)


class BoundApprovalTests(unittest.TestCase):
    def setUp(self):
        self.cand_seed, self.cand_public = generate_key_pair()
        self.appr_seed, self.appr_public = generate_key_pair()

    def _cycle(self):
        return _cycle_at_build_test_passed(self.cand_public, _candidate(self.cand_seed))

    def test_a_bound_unexpired_approval_is_accepted(self):
        cycle = self._cycle()
        out = cycle.apply_approval(_approval(self.appr_seed), self.appr_public)
        self.assertTrue(out.ok, out.reason)
        self.assertEqual(cycle.state, STATE_APPROVED)

    def test_an_approval_for_another_patch_is_refused(self):
        cycle = self._cycle()
        out = cycle.apply_approval(_approval(self.appr_seed, approved_patch_ref="patch-2"), self.appr_public)
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("different patch", out.reason)

    def test_an_approval_that_names_no_patch_is_refused_by_default(self):
        cycle = self._cycle()
        out = cycle.apply_approval(_approval(self.appr_seed, approved_patch_ref=""), self.appr_public)
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("does not name the patch", out.reason)

    def test_an_expired_approval_is_refused(self):
        cycle = self._cycle()
        past = (NOW - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        out = cycle.apply_approval(_approval(self.appr_seed, expires_at=past), self.appr_public)
        self.assertEqual(cycle.state, STATE_BLOCKED)
        self.assertIn("expired", out.reason)

    def test_an_approval_with_no_or_a_malformed_expiry_is_refused_by_default(self):
        for bad in ("", "tomorrow", "2026-01-01T13:00:00"):  # the last one has no UTC offset
            cycle = self._cycle()
            out = cycle.apply_approval(_approval(self.appr_seed, expires_at=bad), self.appr_public)
            self.assertEqual(cycle.state, STATE_BLOCKED, bad)
            self.assertIn("expiry", out.reason, bad)

    def test_the_patch_and_the_expiry_are_part_of_what_is_signed(self):
        approval = _approval(self.appr_seed)
        later = Approval(**{**approval.__dict__, "expires_at": "2099-01-01T00:00:00Z"})
        self.assertTrue(approval.signature_ok(self.appr_public))
        self.assertFalse(later.signature_ok(self.appr_public))
        other_patch = Approval(**{**approval.__dict__, "approved_patch_ref": "patch-2"})
        self.assertFalse(other_patch.signature_ok(self.appr_public))

    def test_an_old_approval_without_the_new_fields_still_verifies(self):
        old = Approval("c1", "ana", BASE, TARGET).signed_ed25519(self.appr_seed)
        self.assertTrue(old.signature_ok(self.appr_public))
