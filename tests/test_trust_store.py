# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_trust_store.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The trust store: alias -> public key. Only public keys, a revoked alias never verifies, an unknown signer is not a pass,
and the private key never reaches the store."""
import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from hydra_umc_dev_server.cli import main
from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.operations import BackupManifest, restore_backup, sign_manifest, verify_backup
from hydra_umc_dev_server.repair_cycle import Approval, RepairCandidate, RepairCycle, check_candidate_trusted
from hydra_umc_dev_server.signing import generate_key_pair
from hydra_umc_dev_server.trust_store import TrustStore, load_trust_store, save_trust_store, trust_store_from_config

SEED_A, PUB_A = generate_key_pair()
SEED_B, PUB_B = generate_key_pair()
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _store() -> TrustStore:
    store, problems = trust_store_from_config({"trusted_keys": {"Ana bench 1": PUB_A, "release approver": PUB_B}})
    assert not problems
    return store


class FakeFs:
    def __init__(self, files):
        self.files = files

    def exists(self, path):
        return path in self.files

    def sha256(self, path):
        return self.files[path]


class StoreContentTests(unittest.TestCase):
    def test_public_keys_load_and_are_listed_in_order(self):
        self.assertEqual(_store().active_aliases(), ["Ana bench 1", "release approver"])

    def test_a_private_key_in_the_store_is_left_out_and_named_without_its_value(self):
        store, problems = trust_store_from_config({"trusted_keys": {"oops": SEED_A, "Ana": PUB_A}})
        self.assertEqual(store.active_aliases(), ["Ana"])
        self.assertEqual(len(problems), 1)
        self.assertIn("'oops'", problems[0])
        self.assertIn("private key", problems[0])
        self.assertNotIn(SEED_A.split(":")[1], problems[0])

    def test_malformed_entries_and_aliases_are_left_out(self):
        store, problems = trust_store_from_config({"trusted_keys": {"": PUB_A, "x" * 41: PUB_A, "ok": "ed25519-public:zz", "n": 5}})
        self.assertEqual(store.active_aliases(), [])
        self.assertEqual(len(problems), 4)

    def test_the_wrong_shape_is_a_problem_not_an_exception(self):
        _, problems = trust_store_from_config({"trusted_keys": [], "revoked": "x"})
        self.assertEqual(len(problems), 2)
        self.assertEqual(trust_store_from_config(["x"])[1], ["the trust store must be a JSON object"])

    def test_with_key_refuses_a_seed_a_bad_alias_and_a_different_key_under_the_same_alias(self):
        store = TrustStore()
        with self.assertRaises(ConfigValidationError):
            store.with_key("Ana", SEED_A)
        with self.assertRaises(ConfigValidationError):
            store.with_key("bad/alias", PUB_A)
        store = store.with_key("Ana", PUB_A)
        self.assertEqual(store.with_key("Ana", PUB_A), store)
        with self.assertRaises(ConfigValidationError):
            store.with_key("Ana", PUB_B)

    def test_the_shipped_example_loads_without_problems(self):
        example = Path(__file__).resolve().parent.parent / "configs" / "trust-store.example.json"
        store, problems = load_trust_store(example)
        self.assertEqual(problems, [])
        self.assertEqual(store.active_aliases(), ["release approver"])

    def test_a_missing_file_is_an_error_not_an_empty_store(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ConfigValidationError):
            load_trust_store(Path(tmp) / "nope.json")


class VerifyTests(unittest.TestCase):
    def test_identify_names_the_signer_and_an_unknown_signer_is_none(self):
        body = {"a": 1}
        seed_c, _ = generate_key_pair()
        from hydra_umc_dev_server.signing import sign_body

        self.assertEqual(_store().identify(body, sign_body(SEED_A, body)), "Ana bench 1")
        self.assertIsNone(_store().identify(body, sign_body(seed_c, body)))
        self.assertIsNone(_store().identify(body, ""))
        self.assertIsNone(_store().identify({"a": 2}, sign_body(SEED_A, body)))

    def test_a_revoked_alias_never_verifies(self):
        from hydra_umc_dev_server.signing import sign_body

        body = {"a": 1}
        revoked = _store().with_revoked("Ana bench 1")
        self.assertIsNone(revoked.identify(body, sign_body(SEED_A, body)))
        self.assertFalse(revoked.verify(body, sign_body(SEED_A, body), signer="Ana bench 1"))
        self.assertIsNone(revoked.key_for("Ana bench 1"))

    def test_signer_pins_the_alias(self):
        from hydra_umc_dev_server.signing import sign_body

        body = {"a": 1}
        signature = sign_body(SEED_A, body)
        self.assertTrue(_store().verify(body, signature, signer="Ana bench 1"))
        self.assertFalse(_store().verify(body, signature, signer="release approver"))
        self.assertFalse(_store().verify(body, signature, signer="nobody"))

    def test_an_hmac_signature_is_never_accepted_by_the_store(self):
        candidate = RepairCandidate("c1", "inc", "base", "target", "patch").signed("shared secret")
        check = check_candidate_trusted(candidate, _store(), incident_id="inc", base_fingerprint="base", target="target")
        self.assertFalse(check.accepted)


class RepairTests(unittest.TestCase):
    def _candidate(self, seed=SEED_A):
        return RepairCandidate("c1", "inc", "base", "target", "patch").signed_ed25519(seed)

    def test_check_candidate_trusted_names_the_signer(self):
        check = check_candidate_trusted(self._candidate(), _store(), incident_id="inc", base_fingerprint="base", target="target")
        self.assertTrue(check.accepted)
        self.assertEqual(check.to_dict()["signer"], "Ana bench 1")

    def test_an_untrusted_key_and_a_wrong_incident_are_blocked(self):
        seed_c, _ = generate_key_pair()
        check = check_candidate_trusted(self._candidate(seed_c), _store(), incident_id="inc", base_fingerprint="base", target="target")
        self.assertFalse(check.accepted)
        self.assertIn("trust store", check.reason)
        wrong = check_candidate_trusted(self._candidate(), _store(), incident_id="other", base_fingerprint="base", target="target")
        self.assertFalse(wrong.accepted)

    def _cycle(self):
        cycle = RepairCycle("inc", "base", "target", "repro", clock=lambda: NOW)
        cycle.confirm_repro({"reproduced": True, "repro_case_id": "repro"})
        cycle.raise_incident()
        return cycle

    def test_the_cycle_takes_the_candidate_and_the_approval_from_the_store(self):
        cycle = self._cycle()
        self.assertTrue(cycle.receive_candidate_trusted(self._candidate(), _store()).ok)
        self.assertEqual(cycle.candidate_signer, "Ana bench 1")
        cycle.run_regression(type("R", (), {"outcome": "completed", "exit_code": 0})())
        cycle.run_build_test(type("R", (), {"outcome": "completed", "exit_code": 0})())
        approval = Approval(
            "c1", "release approver", "base", "target",
            approved_patch_ref="patch", expires_at=(NOW + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        ).signed_ed25519(SEED_B)
        self.assertTrue(cycle.apply_approval_trusted(approval, _store()).ok)
        self.assertEqual(cycle.state, "approved")

    def test_an_approver_that_is_not_in_the_store_or_is_revoked_blocks(self):
        for store in (_store(), _store().with_revoked("release approver")):
            cycle = self._cycle()
            cycle.receive_candidate_trusted(self._candidate(), store)
            cycle.run_regression(type("R", (), {"outcome": "completed", "exit_code": 0})())
            cycle.run_build_test(type("R", (), {"outcome": "completed", "exit_code": 0})())
            who = "release approver" if "release approver" in store.revoked else "stranger"
            approval = Approval(
                "c1", who, "base", "target",
                approved_patch_ref="patch", expires_at=(NOW + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ).signed_ed25519(SEED_B)
            self.assertFalse(cycle.apply_approval_trusted(approval, store).ok)
            self.assertEqual(cycle.state, "blocked")

    def test_a_candidate_signed_by_a_revoked_key_is_blocked(self):
        cycle = self._cycle()
        outcome = cycle.receive_candidate_trusted(self._candidate(), _store().with_revoked("Ana bench 1"))
        self.assertFalse(outcome.ok)


class BackupTests(unittest.TestCase):
    def _manifest(self):
        return BackupManifest(backup_id="b1", instance_id="inst", schema_version="1", files={"a.txt": "h1"}), FakeFs({"/b/a.txt": "h1"})

    def test_a_manifest_signed_by_a_trusted_alias_verifies_and_names_it(self):
        manifest, fs = self._manifest()
        result = verify_backup(manifest, "/b", fs, signature=sign_manifest(manifest, SEED_A), trust_store=_store())
        self.assertTrue(result.ok)
        self.assertEqual(result.to_dict()["signer"], "Ana bench 1")

    def test_unsigned_untrusted_and_revoked_are_not_ok(self):
        manifest, fs = self._manifest()
        seed_c, _ = generate_key_pair()
        for signature, store in (
            ("", _store()),
            (sign_manifest(manifest, seed_c), _store()),
            (sign_manifest(manifest, SEED_A), _store().with_revoked("Ana bench 1")),
        ):
            result = verify_backup(manifest, "/b", fs, signature=signature, trust_store=store)
            self.assertFalse(result.ok)
            self.assertIs(result.signature_valid, False)

    def test_restore_with_a_store_refuses_a_manifest_nobody_trusted_signed(self):
        manifest, fs = self._manifest()
        seed_c, _ = generate_key_pair()
        result = restore_backup(
            manifest, "/b", "/r", fs, expected_instance_id="inst", expected_schema_version="1",
            signature=sign_manifest(manifest, seed_c), trust_store=_store(),
        )
        self.assertFalse(result.ok)
        self.assertIn("not signed", result.reason)


class CliTests(unittest.TestCase):
    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_add_list_revoke_round_trip_and_the_file_holds_public_keys_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store_file = tmp_path / "trust.json"
            (tmp_path / "ana.pub").write_text(PUB_A, encoding="utf-8")
            (tmp_path / "ana.key").write_text(SEED_A, encoding="utf-8")
            code, out, _ = self._run("trust", "add", str(store_file), "Ana", "--public-key-file", str(tmp_path / "ana.pub"))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["trusted"], ["Ana"])
            code, _, err = self._run("trust", "add", str(store_file), "Mallory", "--public-key-file", str(tmp_path / "ana.key"))
            self.assertEqual(code, 1)
            self.assertIn("private key", err)
            self.assertNotIn(SEED_A.split(":")[1], store_file.read_text(encoding="utf-8"))
            code, out, _ = self._run("trust", "revoke", str(store_file), "Ana")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out), {"trusted": [], "revoked": ["Ana"]})
            code, out, _ = self._run("trust", "list", str(store_file))
            self.assertEqual(json.loads(out)["revoked"], ["Ana"])
            code, _, err = self._run("trust", "revoke", str(store_file), "Nobody")
            self.assertEqual(code, 1)

    def test_check_candidate_and_verify_backup_with_a_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store_file = tmp_path / "trust.json"
            save_trust_store(store_file, _store())
            candidate = tmp_path / "cand.json"
            candidate.write_text(json.dumps(RepairCandidate("c1", "inc", "base", "target", "patch").signed_ed25519(SEED_A).to_dict()), encoding="utf-8")
            args = ("repair", "check-candidate", str(candidate), "--incident", "inc", "--base", "base", "--target", "target")
            code, out, _ = self._run(*args, "--trust-store", str(store_file))
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(out)["signer"], "Ana bench 1")
            code, _, _ = self._run(*args, "--trust-store", str(store_file), "--signer", "release approver")
            self.assertEqual(code, 1)
            code, _, err = self._run(*args)
            self.assertEqual(code, 1)
            self.assertIn("exactly one", err)
            code, _, _ = self._run(*args, "--trust-store", str(tmp_path / "missing.json"))
            self.assertEqual(code, 1)

            backup = tmp_path / "backup"
            backup.mkdir()
            (backup / "a.txt").write_text("hello", encoding="utf-8")
            import hashlib

            digest = hashlib.sha256(b"hello").hexdigest()
            manifest = BackupManifest(backup_id="b1", instance_id="inst", schema_version="1", files={"a.txt": digest})
            manifest_file = tmp_path / "manifest.json"
            manifest_file.write_text(json.dumps(manifest.to_dict()), encoding="utf-8")
            signature_file = tmp_path / "manifest.sig"
            signature_file.write_text(sign_manifest(manifest, SEED_A), encoding="utf-8")
            base = ("ops", "verify-backup", str(manifest_file), "--backup-root", str(backup))
            code, out, _ = self._run(*base, "--trust-store", str(store_file), "--signature-file", str(signature_file))
            self.assertEqual(code, 0, out)
            self.assertEqual(json.loads(out)["signer"], "Ana bench 1")
            code, _, _ = self._run(*base, "--trust-store", str(store_file))
            self.assertEqual(code, 1, "no signature, no pass")
            code, _, err = self._run(*base, "--signer", "x")
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
