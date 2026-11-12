# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_trust_rotation.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The trust directory of the CM5 and the signed rotation of its keys: only the key being replaced can replace itself, the log is a chain that cannot
be edited or reordered, the switch is off by default and a refused rotation leaves the store and the log as they were."""
import contextlib
import io
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from hydra_umc_dev_server import trust_rotation as tr
from hydra_umc_dev_server.cli import main
from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.signing import generate_key_pair, sign_body
from hydra_umc_dev_server.trust_store import TrustStore, load_trust_store, save_trust_store, trust_store_from_config

SEED_A, PUB_A = generate_key_pair()
SEED_B, PUB_B = generate_key_pair()
SEED_C, PUB_C = generate_key_pair()
SEED_X, PUB_X = generate_key_pair()


def make_store() -> TrustStore:
    store, problems = trust_store_from_config({"trusted_keys": {"approver 1": PUB_A, "bench": PUB_X}})
    assert not problems
    return store


def fake_stat(mode: int, uid: int = 0):
    return SimpleNamespace(st_mode=mode, st_uid=uid)


class Directory(unittest.TestCase):
    def check(self, entries: dict[str, object], **kwargs):
        def lstat(path):
            key = path.name if path.name in (tr.STORE_NAME, tr.LOG_NAME) else "dir"
            if key not in entries:
                raise OSError("missing")
            return entries[key]

        return tr.check_trust_dir(Path("/etc/hydra-umc/trust"), lstat=lstat, **kwargs)

    def test_a_root_directory_of_mode_0700_is_fit(self):
        self.assertEqual(self.check({"dir": fake_stat(stat.S_IFDIR | 0o700)}), [])

    def test_the_default_location_is_outside_the_data_of_the_applications(self):
        self.assertEqual(tr.TRUST_DIR, Path("/etc/hydra-umc/trust"))

    def test_every_way_of_being_unfit_is_named(self):
        cases = {
            "not owned by root": fake_stat(stat.S_IFDIR | 0o700, uid=1000),
            "open to the group or to others": fake_stat(stat.S_IFDIR | 0o750),
            "is a symbolic link": fake_stat(stat.S_IFLNK | 0o700),
            "is not a directory": fake_stat(stat.S_IFREG | 0o700),
        }
        for expected, info in cases.items():
            problems = self.check({"dir": info})
            self.assertTrue(any(expected in problem for problem in problems), (expected, problems))

    def test_a_missing_directory(self):
        self.assertIn("does not exist", self.check({})[0])

    def test_files_that_others_can_write_or_that_are_not_root_s_are_named(self):
        dir_info = fake_stat(stat.S_IFDIR | 0o700)
        problems = self.check({"dir": dir_info, tr.STORE_NAME: fake_stat(stat.S_IFREG | 0o666), tr.LOG_NAME: fake_stat(stat.S_IFREG | 0o644, uid=7)})
        self.assertTrue(any("trust.json can be written" in problem for problem in problems))
        self.assertTrue(any("rotation.log is not owned by root" in problem for problem in problems))
        self.assertEqual(self.check({"dir": dir_info, tr.STORE_NAME: fake_stat(stat.S_IFREG | 0o644)}), [])

    def test_a_directory_inside_the_data_of_an_application_is_refused(self):
        with tempfile.TemporaryDirectory() as scratch:
            data = Path(scratch) / "app-data"
            inside = data / "trust"
            inside.mkdir(parents=True)
            problems = tr.check_trust_dir(inside, app_data_dirs=(data,), lstat=lambda p: fake_stat(stat.S_IFDIR | 0o700))
            self.assertTrue(any("inside the data of an application" in problem for problem in problems))
            self.assertEqual(tr.check_trust_dir(inside, app_data_dirs=(Path(scratch) / "other",), lstat=lambda p: fake_stat(stat.S_IFDIR | 0o700)), [])

    def test_only_root_creates_it(self):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            self.skipTest("running as root")
        with tempfile.TemporaryDirectory() as scratch, self.assertRaises(ConfigValidationError):
            tr.ensure_trust_dir(Path(scratch) / "trust")


def rotate(store: TrustStore, records: list, old: str, new: str, new_key: str, seed: str, *, enabled: bool = True):
    body = tr.rotation_body(store, records, old, new, new_key)
    signature = tr.sign_rotation(seed, body)
    return body, signature, tr.apply_rotation(store, records, body, signature, enabled=enabled)


class Rotation(unittest.TestCase):
    def test_the_old_key_signs_the_new_one_in_and_is_revoked(self):
        store = make_store()
        _, _, (updated, record) = rotate(store, [], "approver 1", "approver 2", PUB_B, SEED_A)
        self.assertEqual(updated.key_for("approver 2"), PUB_B)
        self.assertIn("approver 1", updated.revoked)
        self.assertIsNone(updated.key_for("approver 1"))
        self.assertEqual(updated.key_for("bench"), PUB_X, "the other aliases are not touched")
        self.assertEqual((record["sequence"], record["body"]["previous"]), (1, tr.GENESIS))
        self.assertEqual(tr.verify_log([record]), [])

    def test_a_second_rotation_chains_to_the_first(self):
        store = make_store()
        _, _, (store, first) = rotate(store, [], "approver 1", "approver 2", PUB_B, SEED_A)
        _, _, (store, second) = rotate(store, [first], "approver 2", "approver 3", PUB_C, SEED_B)
        self.assertEqual(second["body"]["previous"], first["hash"])
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(tr.verify_log([first, second]), [])
        self.assertEqual(store.active_aliases(), ["approver 3", "bench"])

    def test_the_switch_is_off_by_default_and_by_environment_only_with_a_one(self):
        self.assertFalse(tr.rotation_enabled({}))
        self.assertFalse(tr.rotation_enabled({tr.ROTATION_ENV: "true"}))
        self.assertTrue(tr.rotation_enabled({tr.ROTATION_ENV: "1"}))
        with self.assertRaisesRegex(ConfigValidationError, "off"):
            rotate(make_store(), [], "approver 1", "approver 2", PUB_B, SEED_A, enabled=False)

    def test_a_statement_signed_by_another_key_is_refused(self):
        for seed in (SEED_B, SEED_X):
            with self.assertRaisesRegex(ConfigValidationError, "not signed by the key it replaces"):
                rotate(make_store(), [], "approver 1", "approver 2", PUB_B, seed)

    def test_a_tampered_statement_is_refused(self):
        store = make_store()
        body = tr.rotation_body(store, [], "approver 1", "approver 2", PUB_B)
        signature = tr.sign_rotation(SEED_A, body)
        for field, value in (("new_key", PUB_C), ("new", "approver 9"), ("sequence", 2), ("previous", "1" * 64)):
            forged = {**body, field: value}
            with self.assertRaises(ConfigValidationError, msg=field):
                tr.apply_rotation(store, [], forged, signature, enabled=True)
        with self.assertRaises(ConfigValidationError):
            tr.apply_rotation(store, [], {**body, "extra": 1}, signature, enabled=True)
        with self.assertRaises(ConfigValidationError):
            tr.apply_rotation(store, [], {k: v for k, v in body.items() if k != "action"}, signature, enabled=True)

    def test_the_statement_has_to_describe_the_store_as_it_is(self):
        store = make_store()
        wrong_key = {**tr.rotation_body(store, [], "approver 1", "approver 2", PUB_B), "old_key": PUB_C}
        with self.assertRaises(ConfigValidationError):
            tr.apply_rotation(store, [], wrong_key, sign_body(SEED_C, wrong_key), enabled=True)
        with self.assertRaises(ConfigValidationError):
            tr.rotation_body(store, [], "nobody", "approver 2", PUB_B)

    def test_a_revoked_alias_cannot_rotate_and_an_existing_alias_or_key_cannot_come_in(self):
        store = make_store().with_revoked("bench")
        with self.assertRaises(ConfigValidationError):
            tr.rotation_body(store, [], "bench", "bench 2", PUB_C)
        store = make_store()
        for new, key in (("bench", PUB_B), ("approver 2", PUB_X), ("approver 2", PUB_A), ("approver 1", PUB_B), ("bad/alias", PUB_B), ("approver 2", "ed25519-public:zz"), ("approver 2", "ed25519-seed:" + "00" * 32)):
            body = {"action": tr.ACTION, "old": "approver 1", "old_key": PUB_A, "new": new, "new_key": key, "sequence": 1, "previous": tr.GENESIS}
            with self.assertRaises(ConfigValidationError, msg=(new, key[:20])):
                tr.apply_rotation(store, [], body, sign_body(SEED_A, body), enabled=True)

    def test_a_replayed_statement_is_refused(self):
        store = make_store()
        body, signature, (updated, record) = rotate(store, [], "approver 1", "approver 2", PUB_B, SEED_A)
        with self.assertRaises(ConfigValidationError):
            tr.apply_rotation(updated, [record], body, signature, enabled=True)
        with self.assertRaises(ConfigValidationError):
            tr.apply_rotation(store, [record], body, signature, enabled=True)

    def test_a_damaged_log_stops_every_rotation(self):
        store = make_store()
        _, _, (_, record) = rotate(store, [], "approver 1", "approver 2", PUB_B, SEED_A)
        body = tr.rotation_body(store, [], "bench", "bench 2", PUB_C)
        signature = tr.sign_rotation(SEED_X, body)
        for damaged in ({**record, "hash": "0" * 64}, {**record, "sequence": 2}, {**record, "signature": record["signature"][:-4] + "AAAA"}):
            self.assertTrue(tr.verify_log([damaged]))
            with self.assertRaisesRegex(ConfigValidationError, "damaged"):
                tr.apply_rotation(store, [damaged], body, signature, enabled=True)

    def test_a_reordered_or_cut_log_is_found(self):
        store = make_store()
        _, _, (store, first) = rotate(store, [], "approver 1", "approver 2", PUB_B, SEED_A)
        _, _, (store, second) = rotate(store, [first], "approver 2", "approver 3", PUB_C, SEED_B)
        self.assertTrue(tr.verify_log([second, first]))
        self.assertTrue(tr.verify_log([second]))
        self.assertTrue(tr.verify_log([{"sequence": 1}]))


class OnDisk(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.dir = Path(self.scratch.name)
        save_trust_store(self.dir / tr.STORE_NAME, make_store())

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def files(self):
        key = self.dir / "new.pub"
        key.write_text(PUB_B, encoding="utf-8")
        seed = self.dir / "old.seed"
        seed.write_text(SEED_A, encoding="utf-8")
        return key, seed

    def test_the_whole_flow_through_the_command_line(self):
        key, seed = self.files()
        code, out, _ = self.run_cli("trust", "rotation-body", str(self.dir), "--old", "approver 1", "--new", "approver 2", "--new-public-key-file", str(key))
        self.assertEqual(code, 0)
        body_file = self.dir / "body.json"
        body_file.write_text(out, encoding="utf-8")
        code, signature, err = self.run_cli("trust", "sign-rotation", "--body-file", str(body_file), "--seed-file", str(seed))
        self.assertEqual(code, 0, err)
        self.assertNotIn(SEED_A, signature + err)
        signature_file = self.dir / "body.sig"
        signature_file.write_text(signature, encoding="utf-8")
        args = ("trust", "rotate", str(self.dir), "--body-file", str(body_file), "--signature-file", str(signature_file), "--skip-dir-check")
        before = (self.dir / tr.STORE_NAME).read_text(encoding="utf-8")
        code, _, err = self.run_cli(*args)
        self.assertEqual(code, 1, "off by default")
        self.assertIn("off", err)
        self.assertEqual((self.dir / tr.STORE_NAME).read_text(encoding="utf-8"), before)
        self.assertFalse((self.dir / tr.LOG_NAME).exists())
        code, out, err = self.run_cli(*args, "--enable-rotation")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["trusted"], ["approver 2", "bench"])
        code, out, err = self.run_cli("trust", "log", str(self.dir))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["rotations"], 1)
        code, _, err = self.run_cli(*args, "--enable-rotation")
        self.assertEqual(code, 1, "the same statement cannot be applied twice")
        self.assertEqual(len((self.dir / tr.LOG_NAME).read_text(encoding="utf-8").splitlines()), 1)

    def test_the_default_directory_is_checked_before_a_rotation(self):
        key, _ = self.files()
        code, _, err = self.run_cli("trust", "rotate", str(self.dir), "--body-file", str(key), "--signature-file", str(key), "--enable-rotation")
        if os.name == "nt":
            self.assertEqual(code, 1)
        self.assertIn("REFUSED", err)

    def test_the_log_command_finds_a_log_that_does_not_agree_with_the_store(self):
        store = make_store()
        _, _, (_, record) = rotate(store, [], "approver 1", "approver 2", PUB_B, SEED_A)
        (self.dir / tr.LOG_NAME).write_text(json.dumps(record) + "\n", encoding="utf-8")
        code, _, err = self.run_cli("trust", "log", str(self.dir))
        self.assertEqual(code, 1)
        self.assertIn("not revoked", err)

    def test_a_log_line_that_is_not_json_is_an_error(self):
        (self.dir / tr.LOG_NAME).write_text("not json\n", encoding="utf-8")
        with self.assertRaises(ConfigValidationError):
            tr.read_log(self.dir / tr.LOG_NAME)
        code, _, err = self.run_cli("trust", "log", str(self.dir))
        self.assertEqual(code, 1)
        self.assertIn("INVALID", err)

    def test_signing_never_prints_the_private_key_even_on_failure(self):
        seed = self.dir / "bad.seed"
        seed.write_text(SEED_A, encoding="utf-8")
        body = self.dir / "bad.json"
        body.write_text("{not json", encoding="utf-8")
        code, out, err = self.run_cli("trust", "sign-rotation", "--body-file", str(body), "--seed-file", str(seed))
        self.assertEqual(code, 1)
        self.assertNotIn(SEED_A, out + err)

    def test_the_store_after_a_rotation_still_loads_without_problems(self):
        key, seed = self.files()
        store, _ = load_trust_store(self.dir / tr.STORE_NAME)
        body = tr.rotation_body(store, [], "approver 1", "approver 2", PUB_B)
        tr.rotate_in_directory(self.dir, body, tr.sign_rotation(SEED_A, body), enabled=True)
        loaded, problems = load_trust_store(self.dir / tr.STORE_NAME)
        self.assertEqual(problems, [])
        self.assertEqual(loaded.active_aliases(), ["approver 2", "bench"])
        self.assertEqual(tr.log_agrees_with_store(loaded, tr.read_log(self.dir / tr.LOG_NAME)), [])

    def test_check_dir_command(self):
        code, _, err = self.run_cli("trust", "check-dir", str(self.dir / "missing"))
        self.assertEqual(code, 1)
        self.assertIn("UNFIT", err)


if __name__ == "__main__":
    unittest.main()
