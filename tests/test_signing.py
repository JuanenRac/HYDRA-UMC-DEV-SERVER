# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_signing.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Ed25519 against the test vectors of RFC 8032, and its use on repair candidates, approvals and backup
manifests: a key pair is checked with the public key alone, and the two kinds of key never mix."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_dev_server.cli import main
from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.operations import (
    BackupManifest,
    create_backup,
    manifest_signature_ok,
    restore_backup,
    sign_manifest,
    verify_backup,
)
from hydra_umc_dev_server.repair_cycle import Approval, RepairCandidate, check_candidate
from hydra_umc_dev_server.signing import (
    generate_key_pair,
    public_key_bytes,
    public_key_from_seed,
    sign_bytes,
    sign_body,
    signature_matches,
    verify_body,
    verify_bytes,
)

# RFC 8032, section 7.1
VECTORS = (
    (
        "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
        "",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
)


class Rfc8032Tests(unittest.TestCase):
    def test_the_first_two_vectors_give_the_public_key_and_the_signature_of_the_rfc(self):
        for seed, public, message, signature in VECTORS[:2]:
            with self.subTest(message=message):
                self.assertEqual(public_key_bytes(bytes.fromhex(seed)).hex(), public)
                self.assertEqual(sign_bytes(bytes.fromhex(seed), bytes.fromhex(message)).hex(), signature)
                self.assertTrue(verify_bytes(bytes.fromhex(public), bytes.fromhex(message), bytes.fromhex(signature)))

    def test_the_third_vector_signature_verifies(self):
        seed, _, message, signature = VECTORS[2]
        public = public_key_bytes(bytes.fromhex(seed))
        self.assertEqual(sign_bytes(bytes.fromhex(seed), bytes.fromhex(message)).hex(), signature)
        self.assertTrue(verify_bytes(public, bytes.fromhex(message), bytes.fromhex(signature)))

    def test_a_changed_message_a_changed_signature_or_another_key_do_not_verify(self):
        seed, public, message, signature = (bytes.fromhex(x) for x in VECTORS[1])
        self.assertFalse(verify_bytes(public, message + b"x", signature))
        broken = bytearray(signature)
        broken[10] ^= 1
        self.assertFalse(verify_bytes(public, message, bytes(broken)))
        other = public_key_bytes(bytes(32))
        self.assertFalse(verify_bytes(other, message, signature))
        self.assertFalse(verify_bytes(public, message, signature[:-1]))
        self.assertFalse(verify_bytes(public[:-1], message, signature))

    def test_a_signature_whose_scalar_is_not_reduced_is_refused(self):
        seed, public, message, signature = (bytes.fromhex(x) for x in VECTORS[1])
        l_order = 2**252 + 27742317777372353535851937790883648493
        malleable = signature[:32] + int.to_bytes(int.from_bytes(signature[32:], "little") + l_order, 32, "little")
        self.assertFalse(verify_bytes(public, message, malleable))

    def test_generated_keys_are_text_that_round_trips(self):
        seed, public = generate_key_pair()
        self.assertTrue(seed.startswith("ed25519-seed:") and public.startswith("ed25519-public:"))
        self.assertEqual(public_key_from_seed(seed), public)
        self.assertNotEqual(generate_key_pair()[0], seed)
        with self.assertRaises(ConfigValidationError):
            public_key_from_seed("not a key")


class BodySignatureTests(unittest.TestCase):
    def test_a_body_signature_verifies_with_the_public_key_only(self):
        seed, public = generate_key_pair()
        body = {"a": 1, "b": ["x"]}
        signature = sign_body(seed, body)
        self.assertTrue(signature.startswith("ed25519:"))
        self.assertTrue(verify_body(public, {"b": ["x"], "a": 1}, signature))  # the order of the keys does not matter
        self.assertFalse(verify_body(public, {"a": 2, "b": ["x"]}, signature))

    def test_malformed_keys_and_signatures_are_not_valid_not_a_crash(self):
        seed, public = generate_key_pair()
        signature = sign_body(seed, {"a": 1})
        for bad_key in ("", "ed25519-public:zz", seed):
            self.assertFalse(verify_body(bad_key, {"a": 1}, signature))
        for bad_signature in ("", "ed25519:", "ed25519:zz", signature[:-2], "hmac:" + signature):
            self.assertFalse(verify_body(public, {"a": 1}, bad_signature))

    def test_the_two_kinds_of_key_never_mix(self):
        seed, public = generate_key_pair()
        body = {"a": 1}
        asymmetric = sign_body(seed, body)
        import hmac as hmac_module

        mac = hmac_module.new(b"secret", json.dumps(body, sort_keys=True, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()
        self.assertTrue(signature_matches(public, body, asymmetric))
        self.assertTrue(signature_matches("secret", body, mac))
        self.assertFalse(signature_matches(public, body, mac), "a public key must not accept an HMAC signature (downgrade)")
        self.assertFalse(signature_matches("secret", body, asymmetric))
        self.assertFalse(signature_matches(public, body, ""))


def _candidate(**extra):
    data = dict(candidate_id="c1", for_incident_id="inc-1", for_base_fingerprint="base-1", for_target="t1", patch_ref="p1")
    data.update(extra)
    return RepairCandidate(**data)


class RepairSigningTests(unittest.TestCase):
    def test_a_candidate_signed_with_a_key_pair_is_checked_with_the_public_key(self):
        seed, public = generate_key_pair()
        candidate = _candidate().signed_ed25519(seed)
        check = check_candidate(candidate, public, incident_id="inc-1", base_fingerprint="base-1", target="t1")
        self.assertTrue(check.accepted, check.reason)

    def test_a_tampered_or_misdirected_candidate_is_refused(self):
        seed, public = generate_key_pair()
        candidate = _candidate().signed_ed25519(seed)
        tampered = RepairCandidate(**{**candidate.to_dict(), "patch_ref": "evil"})
        self.assertFalse(check_candidate(tampered, public, incident_id="inc-1", base_fingerprint="base-1", target="t1").accepted)
        self.assertFalse(check_candidate(candidate, public, incident_id="inc-2", base_fingerprint="base-1", target="t1").accepted)
        other_public = generate_key_pair()[1]
        self.assertFalse(check_candidate(candidate, other_public, incident_id="inc-1", base_fingerprint="base-1", target="t1").accepted)

    def test_an_hmac_candidate_still_works_and_is_not_accepted_under_a_public_key(self):
        hmac_candidate = _candidate().signed("secret")
        self.assertTrue(check_candidate(hmac_candidate, "secret", incident_id="inc-1", base_fingerprint="base-1", target="t1").accepted)
        public = generate_key_pair()[1]
        self.assertFalse(check_candidate(hmac_candidate, public, incident_id="inc-1", base_fingerprint="base-1", target="t1").accepted)

    def test_an_approval_signed_with_a_key_pair(self):
        seed, public = generate_key_pair()
        approval = Approval("c1", "ana", "base-1", "t1").signed_ed25519(seed)
        self.assertTrue(approval.signature_ok(public))
        self.assertFalse(approval.signature_ok(generate_key_pair()[1]))
        self.assertFalse(Approval("c1", "ana", "base-1", "t1").signature_ok(public))


class FakeBackupFs:
    def __init__(self, files=None):
        self.blobs = dict(files or {})

    def read_bytes(self, path):
        return self.blobs[path]

    def write_bytes(self, path, data):
        self.blobs[path] = data

    def sha256(self, path):
        return hashlib.sha256(self.blobs[path]).hexdigest()

    def exists(self, path):
        return path in self.blobs


class BackupSigningTests(unittest.TestCase):
    def setUp(self):
        self.fs = FakeBackupFs({"/state/queue.sqlite3": b"queue"})
        self.manifest = create_backup("/state", ["queue.sqlite3"], "/backups/b1", self.fs, backup_id="b1", instance_id="dev-1")
        self.seed, self.public = generate_key_pair()

    def test_a_signed_manifest_verifies_and_restores(self):
        signature = sign_manifest(self.manifest, self.seed)
        self.assertTrue(manifest_signature_ok(self.manifest, signature, self.public))
        result = verify_backup(self.manifest, "/backups/b1", self.fs, public_key=self.public, signature=signature)
        self.assertTrue(result.ok)
        self.assertTrue(result.signature_valid)
        restored = restore_backup(
            self.manifest, "/backups/b1", "/restore", self.fs, expected_instance_id="dev-1", public_key=self.public, signature=signature,
        )
        self.assertTrue(restored.ok, restored.reason)

    def test_a_regenerated_manifest_over_replaced_files_is_caught_by_the_signature(self):
        signature = sign_manifest(self.manifest, self.seed)
        self.fs.blobs["/backups/b1/queue.sqlite3"] = b"replaced"
        forged = BackupManifest("b1", "dev-1", self.manifest.schema_version, {"queue.sqlite3": hashlib.sha256(b"replaced").hexdigest()})
        self.assertTrue(verify_backup(forged, "/backups/b1", self.fs).ok, "without a key the forged manifest passes: that is the gap")
        checked = verify_backup(forged, "/backups/b1", self.fs, public_key=self.public, signature=signature)
        self.assertFalse(checked.ok)
        self.assertFalse(checked.signature_valid)
        restored = restore_backup(
            forged, "/backups/b1", "/restore", self.fs, expected_instance_id="dev-1", public_key=self.public, signature=signature,
        )
        self.assertFalse(restored.ok)
        self.assertIn("not signed", restored.reason)
        self.assertNotIn("/restore/queue.sqlite3", self.fs.blobs)

    def test_a_key_without_a_signature_is_not_ok(self):
        result = verify_backup(self.manifest, "/backups/b1", self.fs, public_key=self.public)
        self.assertFalse(result.ok)
        self.assertFalse(result.signature_valid)

    def test_without_a_key_nothing_changes(self):
        result = verify_backup(self.manifest, "/backups/b1", self.fs)
        self.assertTrue(result.ok)
        self.assertIsNone(result.signature_valid)


class SigningCommandTests(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_keygen_sign_and_verify_through_the_command_line(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / "backup").mkdir()
            (tmp / "backup" / "file.bin").write_bytes(b"real bytes")
            manifest = tmp / "manifest.json"
            manifest.write_text(json.dumps({
                "backup_id": "b1", "instance_id": "dev-1", "schema_version": "dev-server-state/1",
                "files": {"file.bin": hashlib.sha256(b"real bytes").hexdigest()},
            }), encoding="utf-8")
            private, public, signature = tmp / "key.private", tmp / "key.public", tmp / "manifest.sig"
            self.assertEqual(self.run_main(["ops", "keygen", "--private-key-file", str(private), "--public-key-file", str(public)])[0], 0)
            self.assertEqual(self.run_main(["ops", "keygen", "--private-key-file", str(private), "--public-key-file", str(public)])[0], 1, "never overwrites a key")
            code, out, _ = self.run_main(["ops", "sign-backup", str(manifest), "--private-key-file", str(private), "--output", str(signature)])
            self.assertEqual(code, 0)
            self.assertEqual(out.strip(), signature.read_text(encoding="utf-8").strip())
            common = ["ops", "verify-backup", str(manifest), "--backup-root", str(tmp / "backup")]
            self.assertEqual(self.run_main(common)[0], 0)
            code, out, _ = self.run_main(common + ["--public-key-file", str(public), "--signature-file", str(signature)])
            self.assertEqual((code, json.loads(out)["signature_valid"]), (0, True))
            self.assertEqual(self.run_main(common + ["--public-key-file", str(public)])[0], 1, "a key with no signature is not ok")
            # a manifest edited after it was signed
            edited = json.loads(manifest.read_text(encoding="utf-8"))
            edited["instance_id"] = "dev-2"
            manifest.write_text(json.dumps(edited), encoding="utf-8")
            self.assertEqual(self.run_main(common + ["--public-key-file", str(public), "--signature-file", str(signature)])[0], 1)

    def test_a_signature_file_without_a_public_key_is_refused(self):
        with tempfile.TemporaryDirectory() as t:
            manifest = Path(t) / "m.json"
            manifest.write_text(json.dumps({"backup_id": "b", "instance_id": "i", "schema_version": "s", "files": {}}), encoding="utf-8")
            code, _, err = self.run_main(["ops", "verify-backup", str(manifest), "--backup-root", t, "--signature-file", str(manifest)])
            self.assertEqual(code, 1)
            self.assertIn("--public-key-file", err)

    def test_check_candidate_accepts_a_public_key_file(self):
        seed, public = generate_key_pair()
        with tempfile.TemporaryDirectory() as t:
            tmp = Path(t)
            (tmp / "candidate.json").write_text(json.dumps(_candidate().signed_ed25519(seed).to_dict()), encoding="utf-8")
            (tmp / "public").write_text(public + "\n", encoding="utf-8")
            argv = ["repair", "check-candidate", str(tmp / "candidate.json"), "--secret-file", str(tmp / "public"),
                    "--incident", "inc-1", "--base", "base-1", "--target", "t1"]
            self.assertEqual(self.run_main(argv)[0], 0)
            argv[argv.index("inc-1")] = "inc-9"
            self.assertEqual(self.run_main(argv)[0], 1)


class NativeBackendTests(unittest.TestCase):
    """The `cryptography` package, when it is installed, must give exactly what the pure code gives; without it the pure code answers."""

    def setUp(self):
        import os

        self._saved = os.environ.get("HYDRA_UMC_DEV_SERVER_PURE_ED25519")
        os.environ.pop("HYDRA_UMC_DEV_SERVER_PURE_ED25519", None)
        self.addCleanup(self._restore)

    def _restore(self):
        import os

        if self._saved is None:
            os.environ.pop("HYDRA_UMC_DEV_SERVER_PURE_ED25519", None)
        else:
            os.environ["HYDRA_UMC_DEV_SERVER_PURE_ED25519"] = self._saved

    def test_the_pure_backend_can_be_forced(self):
        import os

        from hydra_umc_dev_server.signing import signing_backend

        os.environ["HYDRA_UMC_DEV_SERVER_PURE_ED25519"] = "1"
        self.assertEqual(signing_backend(), "pure")

    def test_native_and_pure_agree_on_keys_and_signatures(self):
        import os

        from hydra_umc_dev_server import signing

        if signing.signing_backend() != "native":
            self.skipTest("the cryptography package is not installed: only the pure backend exists here")
        for seed in (bytes(32), bytes(range(32)), hashlib.sha256(b"seed").digest(), b"\xff" * 32):
            for message in (b"", b"abc", b"x" * 1000):
                native_public = signing.public_key_bytes(seed)
                native_signature = signing.sign_bytes(seed, message)
                os.environ["HYDRA_UMC_DEV_SERVER_PURE_ED25519"] = "1"
                try:
                    self.assertEqual(signing.public_key_bytes(seed), native_public)
                    self.assertEqual(signing.sign_bytes(seed, message), native_signature)
                    self.assertTrue(signing.verify_bytes(native_public, message, native_signature))
                finally:
                    os.environ.pop("HYDRA_UMC_DEV_SERVER_PURE_ED25519", None)


if __name__ == "__main__":
    unittest.main()
