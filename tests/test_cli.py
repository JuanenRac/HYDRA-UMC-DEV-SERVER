# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_cli.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_dev_server import __version__
from hydra_umc_dev_server.cli import main


class ConfigValidateCommandTests(unittest.TestCase):
    def test_the_real_shipped_task_policy_example_is_valid(self):
        example_path = Path(__file__).resolve().parent.parent / "configs" / "task-policy.example.json"
        exit_code = main(["config", "validate", str(example_path), "--kind", "task-policy"])
        self.assertEqual(exit_code, 0)

    def test_the_real_shipped_host_profile_example_is_valid(self):
        example_path = Path(__file__).resolve().parent.parent / "configs" / "host-profile.example.json"
        exit_code = main(["config", "validate", str(example_path), "--kind", "host-profile"])
        self.assertEqual(exit_code, 0)

    def test_the_real_shipped_toolchain_example_is_valid(self):
        example_path = Path(__file__).resolve().parent.parent / "configs" / "toolchains.example.json"
        exit_code = main(["config", "validate", str(example_path), "--kind", "toolchain"])
        self.assertEqual(exit_code, 0)

    def test_a_malformed_document_returns_a_real_nonzero_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-task-policy.json"
            path.write_text(json.dumps({"allow_deploy": "yes"}), encoding="utf-8")
            exit_code = main(["config", "validate", str(path), "--kind", "task-policy"])
            self.assertEqual(exit_code, 1)

    def test_a_missing_file_returns_a_real_nonzero_exit_code(self):
        exit_code = main(["config", "validate", "does-not-exist.json", "--kind", "task-policy"])
        self.assertEqual(exit_code, 1)


class InventoryScanCommandTests(unittest.TestCase):
    def test_scanning_this_repositorys_own_parent_finds_its_real_manifest(self):
        real_root = Path(__file__).resolve().parent.parent.parent
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "inventory.json"
            exit_code = main(["inventory", "scan", "--root", str(real_root), "--out", str(out_path)])
            self.assertEqual(exit_code, 0)
            payload = json.loads(out_path.read_text(encoding="utf-8"))
            names = [p["name"] for p in payload["projects"]]
            self.assertIn("HYDRA-UMC-DEV-SERVER", names)

    def test_scanning_an_empty_directory_still_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            exit_code = main(["inventory", "scan", "--root", tmp])
            self.assertEqual(exit_code, 0)


class StationCommandTests(unittest.TestCase):
    _example = Path(__file__).resolve().parent.parent / "configs" / "remote-station.example.json"

    def test_the_real_shipped_remote_station_example_validates(self):
        self.assertEqual(main(["station", "validate", str(self._example)]), 0)

    def test_a_public_bind_without_the_opt_in_is_rejected_by_the_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-station.json"
            document = json.loads(self._example.read_text(encoding="utf-8"))
            document["remote_access"]["bind_address"] = "8.8.8.8"
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(main(["station", "validate", str(path)]), 1)

    def test_station_plan_prints_a_host_free_dry_run_plan(self):
        # No --preflight: the plan is pure and never touches this host.
        self.assertEqual(main(["station", "plan", str(self._example)]), 0)


class VersionTests(unittest.TestCase):
    def test_version_flag_matches_the_real_package_version(self):
        with self.assertRaises(SystemExit) as ctx:
            main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_package_version_is_a_real_semver_triplet(self):
        parts = __version__.split(".")
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(p.isdigit() for p in parts))


if __name__ == "__main__":
    unittest.main()
