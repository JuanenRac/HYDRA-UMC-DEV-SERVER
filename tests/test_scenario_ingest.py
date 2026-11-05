# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_scenario_ingest.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
#
# The sending end of POST /api/ingest/scenario-outcome, from a repair cycle and from the CLI. The stand-in server of the shared SDK
# (conformance/fake-server) answers when the SDK checkout is at hand (HYDRA_UMC_SDK_DIR, or a HYDRA-UMC-SDK folder next to this
# repository); a small server of this file always answers too.
# =============================================================================
import http.server
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from hydra_umc_dev_server import cli
from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.repair_cycle import STATE_VERIFIED, RepairCycle
from hydra_umc_dev_server.scenario_ingest import IngestSettings, load_ingest_settings, outcome_problem, outcome_sink, post_scenario_outcome

from test_repair_cycle import _BASE, _CASE, _INC, _TARGET, FakeInstaller, _drive_to_installed


def _fake_server_module():
    candidates = []
    if os.environ.get("HYDRA_UMC_SDK_DIR"):
        candidates.append(Path(os.environ["HYDRA_UMC_SDK_DIR"]))
    for parent in Path(__file__).resolve().parents:
        candidates.extend([parent.parent / "HYDRA-UMC-SDK", parent / "HYDRA-UMC-SDK"])
    for sdk in candidates:
        folder = sdk / "conformance" / "fake-server"
        if (folder / "hydra_fake_server.py").is_file():
            sys.path.insert(0, str(folder))
            try:
                import hydra_fake_server  # type: ignore[import-not-found]

                return hydra_fake_server
            except Exception:  # noqa: BLE001
                return None
    return None


FAKE = _fake_server_module()

OUTCOME = {
    "schema_version": "1.0", "scenario_id": "inc-1", "run_id": "inc-1:before", "base_fingerprint": "abc", "phase": "before",
    "repro_case": "case", "observed": {"outcome": "reproduced"}, "timestamp_utc": "2026-01-01T00:00:00+00:00",
}


class _Answer(http.server.BaseHTTPRequestHandler):
    status = 201
    seen: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        type(self).seen.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(length) or b"{}")))
        self.send_response(type(self).status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"seq": 3}')

    def log_message(self, format, *args):  # noqa: A002
        pass


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        _Answer.seen, _Answer.status = [], 201
        self.httpd = http.server.HTTPServer(("127.0.0.1", 0), _Answer)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.token = Path(self.tmp.name) / "token"
        self.token.write_text("tok-9\n", encoding="utf-8")
        self.settings = IngestSettings(f"http://127.0.0.1:{self.httpd.server_address[1]}", token_file=str(self.token))

    def test_the_outcome_goes_with_the_token(self):
        result = post_scenario_outcome(OUTCOME, self.settings)
        self.assertTrue(result.ok)
        self.assertEqual(result.seq, 3)
        self.assertEqual(_Answer.seen[0][:2], ("/api/ingest/scenario-outcome", "Bearer tok-9"))

    def test_refusals_are_results_and_a_bad_outcome_or_address_is_never_sent(self):
        _Answer.status = 404
        refused = post_scenario_outcome(OUTCOME, self.settings)
        self.assertEqual((refused.ok, refused.status), (False, 404))
        self.assertIn("feed off", refused.detail)
        self.assertIn("lacks", outcome_problem({"schema_version": "1.0"}))
        _Answer.seen.clear()
        self.assertFalse(post_scenario_outcome({"x": 1}, self.settings).ok)
        plain = post_scenario_outcome(OUTCOME, IngestSettings("http://server.example:3000", token_file=str(self.token)))
        self.assertIn("HTTPS", plain.detail)
        self.assertEqual(_Answer.seen, [])

    def test_a_repair_cycle_hands_on_the_run_before_and_the_run_after(self):
        sink, results = outcome_sink(self.settings)
        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE, allow_symmetric_keys=True, require_bound_approval=False, outcome_sink=sink)
        installer = FakeInstaller()
        _drive_to_installed(cycle, installer)
        cycle.verify({"repro_case_id": _CASE, "verified": True}, installer, observed_base_fingerprint=_BASE)
        self.assertEqual(cycle.state, STATE_VERIFIED)
        self.assertEqual([body["phase"] for _, _, body in _Answer.seen], ["before", "after"])
        self.assertEqual([body["observed"]["outcome"] for _, _, body in _Answer.seen], ["reproduced", "not-reproduced"])
        self.assertEqual([body["scenario_id"] for _, _, body in _Answer.seen], [_INC, _INC])
        self.assertTrue(all(r.ok for r in results))

    def test_a_sink_that_fails_does_not_change_the_cycle(self):
        def broken(_outcome):
            raise RuntimeError("boom")

        cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE, allow_symmetric_keys=True, require_bound_approval=False, outcome_sink=broken)
        installer = FakeInstaller()
        _drive_to_installed(cycle, installer)
        self.assertTrue(cycle.verify({"repro_case_id": _CASE, "verified": True}, installer, observed_base_fingerprint=_BASE).ok)

    def test_the_cli_sends_one_outcome_and_is_off_by_default(self):
        tmp = Path(self.tmp.name)
        outcome = tmp / "outcome.json"
        outcome.write_text(json.dumps(OUTCOME), encoding="utf-8")
        config = tmp / "ingest.json"
        config.write_text(json.dumps({"enabled": True, "server_url": self.settings.server_url, "token_file": str(self.token)}), encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(["repair", "report-outcome", str(outcome), "--config", str(config)])
        self.assertEqual(code, 0, err.getvalue())
        self.assertTrue(json.loads(out.getvalue())["ok"])
        self.assertNotIn("tok-9", out.getvalue() + err.getvalue())
        config.write_text(json.dumps({"enabled": False}), encoding="utf-8")
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["repair", "report-outcome", str(outcome), "--config", str(config)]), 1)

    def test_the_document_is_checked(self):
        path = Path(self.tmp.name) / "c.json"
        for body in ({"enabled": True}, {"enabled": True, "server_url": "https://s"}, {"enabled": "yes"}, {"timeout_seconds": 0}, {"surprise": 1}):
            path.write_text(json.dumps(body), encoding="utf-8")
            with self.assertRaises(ConfigValidationError):
                load_ingest_settings(path)
        path.write_text(json.dumps({}), encoding="utf-8")
        self.assertIsNone(load_ingest_settings(path))
        self.assertEqual(outcome_sink(None), (None, []))


@unittest.skipUnless(FAKE is not None, "the SDK checkout with the stand-in server is not at hand")
class FakeServerTests(unittest.TestCase):
    def test_the_server_keeps_both_runs_of_a_cycle(self):
        state = FAKE.FakeHydra(robots=1)
        httpd, _ = FAKE.start(state)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        with tempfile.TemporaryDirectory() as tmp:
            password = Path(tmp) / "pw"
            password.write_text("admin\n", encoding="utf-8")
            settings = IngestSettings(f"http://127.0.0.1:{httpd.server_address[1]}", username="admin", password_file=str(password))
            sink, results = outcome_sink(settings)
            cycle = RepairCycle(_INC, _BASE, _TARGET, _CASE, allow_symmetric_keys=True, require_bound_approval=False, outcome_sink=sink)
            installer = FakeInstaller()
            _drive_to_installed(cycle, installer)
            cycle.verify({"repro_case_id": _CASE, "verified": True}, installer, observed_base_fingerprint=_BASE)
        self.assertEqual([o["phase"] for o in state.scenario_outcomes], ["before", "after"])
        self.assertTrue(all(r.ok for r in results), [r.detail for r in results])


if __name__ == "__main__":
    unittest.main()
