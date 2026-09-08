# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_inventory.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import json
import tempfile
import unittest
from pathlib import Path

from hydra_umc_dev_server.inventory import scan_project_manifests


def _write_manifest(path: Path, **fields) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "hydra-umc.project.json").write_text(json.dumps(fields), encoding="utf-8")


class ScanProjectManifestsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_missing_root_is_a_real_reported_issue_not_a_crash(self):
        result = scan_project_manifests(self.root / "does-not-exist")
        self.assertEqual(result.projects, ())
        self.assertEqual(len(result.issues), 1)
        self.assertIn("not a real directory", result.issues[0].reason)

    def test_an_empty_root_yields_nothing_and_no_issues(self):
        result = scan_project_manifests(self.root)
        self.assertEqual(result.projects, ())
        self.assertEqual(result.issues, ())

    def test_a_subdirectory_with_no_manifest_is_silently_not_a_project(self):
        (self.root / "not-a-hydra-project").mkdir()
        result = scan_project_manifests(self.root)
        self.assertEqual(result.projects, ())
        self.assertEqual(result.issues, (), "a subdirectory with no manifest at all is not an ISSUE")

    def test_a_real_valid_manifest_is_read_correctly(self):
        _write_manifest(self.root / "HYDRA-UMC-EXAMPLE", name="HYDRA-UMC-EXAMPLE", version="1.2.3", maturity="established")
        result = scan_project_manifests(self.root)
        self.assertEqual(len(result.projects), 1)
        self.assertEqual(result.projects[0].name, "HYDRA-UMC-EXAMPLE")
        self.assertEqual(result.projects[0].version, "1.2.3")
        self.assertEqual(result.projects[0].maturity, "established")

    def test_two_real_projects_are_both_found_in_sorted_order(self):
        _write_manifest(self.root / "b-project", name="B", version="0.0.1", maturity="scaffolding")
        _write_manifest(self.root / "a-project", name="A", version="0.0.1", maturity="scaffolding")
        result = scan_project_manifests(self.root)
        self.assertEqual([p.name for p in result.projects], ["A", "B"])

    def test_malformed_json_is_a_real_reported_issue_not_silently_skipped(self):
        project_dir = self.root / "broken"
        project_dir.mkdir()
        (project_dir / "hydra-umc.project.json").write_text("{not json", encoding="utf-8")
        result = scan_project_manifests(self.root)
        self.assertEqual(result.projects, ())
        self.assertEqual(len(result.issues), 1)
        self.assertIn("not valid JSON", result.issues[0].reason)

    def test_a_manifest_missing_a_required_field_is_a_real_reported_issue(self):
        _write_manifest(self.root / "incomplete", name="Incomplete")  # no version/maturity
        result = scan_project_manifests(self.root)
        self.assertEqual(result.projects, ())
        self.assertEqual(len(result.issues), 1)
        self.assertIn("missing/empty required field(s)", result.issues[0].reason)
        self.assertIn("version", result.issues[0].reason)

    def test_a_manifest_that_is_a_json_array_not_object_is_a_real_reported_issue(self):
        project_dir = self.root / "wrong-shape"
        project_dir.mkdir()
        (project_dir / "hydra-umc.project.json").write_text("[1, 2, 3]", encoding="utf-8")
        result = scan_project_manifests(self.root)
        self.assertEqual(result.projects, ())
        self.assertIn("not a JSON object", result.issues[0].reason)

    def test_this_repositorys_own_real_manifest_is_discovered(self):
        # The concrete form of DS01's own acceptance criterion: "el
        # catalogo reconoce el nuevo manifiesto en fixtures" - here,
        # against this repository's own real hydra-umc.project.json, one
        # directory up from tests/.
        real_root = Path(__file__).resolve().parent.parent.parent
        result = scan_project_manifests(real_root)
        names = [p.name for p in result.projects]
        self.assertIn("HYDRA-UMC-DEV-SERVER", names)


if __name__ == "__main__":
    unittest.main()
