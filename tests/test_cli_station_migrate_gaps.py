# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_cli_station_migrate_gaps.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The answers of `station preflight` and `migrate plan` that the coverage report of the CI leaves open: the verdict of a preflight (pass and fail), a source
root with no git checkout in it and a plan that the destinations refuse. The host inspector and the planner are replaced by stand-ins, so nothing here
reads the real host or needs git (evidence: simulator)."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hydra_umc_dev_server import cli
from hydra_umc_dev_server.cli import main
from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.preflight import PreflightCheck, PreflightReport

EXAMPLE = Path(__file__).resolve().parent.parent / "configs" / "remote-station.example.json"
DESTINATIONS = {
    "reference_root": "/srv/hydra-umc-dev/repos",
    "local_changes_root": "/srv/hydra-umc-dev/migration/local",
    "private_root": "/srv/hydra-umc-dev/private",
    "work_in_progress_root": "/srv/hydra-umc-dev/migration/wip",
}


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class StationPreflightVerdictTests(unittest.TestCase):
    def preflight(self, checks):
        with mock.patch.object(cli, "SystemHostInspector", return_value=object()), mock.patch.object(cli, "run_preflight", return_value=PreflightReport(tuple(checks))):
            return run_main(["station", "preflight", str(EXAMPLE)])

    def test_a_report_with_no_failure_ends_with_pass(self):
        code, out, err = self.preflight([PreflightCheck("python", True, "3.12"), PreflightCheck("disk", True, "40 GB free")])
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out[: out.rindex("PREFLIGHT=PASS")])["ok"])
        self.assertTrue(out.rstrip().endswith("PREFLIGHT=PASS"))
        self.assertEqual(err, "")

    def test_a_failed_check_is_named_on_the_error_stream_and_the_exit_is_one(self):
        code, out, err = self.preflight([PreflightCheck("python", True, "3.12"), PreflightCheck("disk", False, "1 GB free"), PreflightCheck("port", False, "in use")])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["failures"], ["disk", "port"])
        self.assertIn("PREFLIGHT=FAIL disk, port", err)
        self.assertNotIn("PREFLIGHT=PASS", out)


class MigratePlanRefusalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.destinations = self.root / "destinations.json"
        self.destinations.write_text(json.dumps(DESTINATIONS), encoding="utf-8")

    def test_a_source_root_with_no_git_checkout_is_reported(self):
        source = self.root / "empty"
        source.mkdir()
        code, out, err = run_main(["migrate", "plan", str(source), "--destinations", str(self.destinations)])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("no git checkout found at", err)
        self.assertIn(str(source), err)

    def test_a_plan_that_the_destinations_refuse_is_reported_and_prints_nothing(self):
        inspector = mock.Mock()
        inspector.is_repo.return_value = True
        with mock.patch.object(cli, "SystemSourceInspector", return_value=inspector), \
                mock.patch.object(cli, "build_repo_inventory", return_value=object()), \
                mock.patch.object(cli, "build_migration_plan", side_effect=ConfigValidationError("the destination is inside the source")):
            code, out, err = run_main(["migrate", "plan", str(self.root), "--destinations", str(self.destinations)])
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("REFUSED: the destination is inside the source", err)


if __name__ == "__main__":
    unittest.main()
