# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_scenario_ingest_server_faults.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The real sender against a stand-in for HYDRA-UMC-SERVER that logs in, refuses, redirects, hangs up and goes away.

The stand-in is a stdlib HTTP server on this machine; nothing leaves it and no real server is involved.
"""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from hydra_umc_dev_server.config import ConfigValidationError
from hydra_umc_dev_server.scenario_ingest import (
    LOGIN_ROUTE,
    SCENARIO_ROUTE,
    IngestSettings,
    load_ingest_settings,
    outcome_problem,
    post_scenario_outcome,
)

OUTCOME = {
    "schema_version": "1.0", "scenario_id": "s1", "run_id": "r1", "base_fingerprint": "abc", "phase": "before",
    "repro_case": "case-1", "observed": {"outcome": "reproduced"}, "timestamp_utc": "2026-01-01T00:00:00Z",
}


class StandIn:
    """Plays one scripted answer per request path and records what arrived."""

    def __init__(self, scenario=(201, {"seq": 7}), login=(200, {"token": "login-token-value"})):
        owner = self
        self.scenario, self.login = scenario, login
        self.requests: list[tuple[str, dict, bytes]] = []
        self.hits_elsewhere = 0

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                owner.requests.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
                action = owner.login if self.path == LOGIN_ROUTE else owner.scenario
                if action == "redirect":
                    self.send_response(307)
                    self.send_header("Location", f"http://127.0.0.1:{owner.port}/elsewhere")
                    self.end_headers()
                elif action == "hangup":
                    self.connection.close()
                else:
                    status, payload = action
                    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
                    self.send_response(status)
                    self.end_headers()
                    self.wfile.write(raw)

            def do_GET(self):
                owner.hits_elsewhere += 1
                self.send_response(200)
                self.end_headers()

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


class IngestAgainstAStandIn(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)
        self.token_file = self.dir / "token"
        self.token_file.write_text("file-token-value\n", encoding="utf-8")
        self.password_file = self.dir / "password"
        self.password_file.write_text("the-password\n", encoding="utf-8")

    def stand_in(self, **kwargs):
        stand_in = StandIn(**kwargs)
        self.addCleanup(stand_in.stop)
        return stand_in

    def settings(self, stand_in, **kwargs):
        values = dict(server_url=stand_in.url, token_file=str(self.token_file), timeout_seconds=2.0)
        values.update(kwargs)
        return IngestSettings(**values)

    def test_a_kept_outcome_carries_the_bearer_token_and_returns_the_sequence_number(self):
        stand_in = self.stand_in()
        result = post_scenario_outcome(OUTCOME, self.settings(stand_in))
        self.assertEqual((result.ok, result.status, result.seq), (True, 201, 7))
        path, headers, body = stand_in.requests[0]
        self.assertEqual(path, SCENARIO_ROUTE)
        self.assertEqual(headers["authorization"], "Bearer file-token-value")
        self.assertEqual(json.loads(body), OUTCOME)

    def test_every_refusal_of_the_server_is_told_in_words_and_never_raised(self):
        words = {400: "does not take", 401: "refused the credential", 403: "may not hand in", 404: "feed off", 503: "cannot sign", 500: "did not keep"}
        for status, text in words.items():
            stand_in = self.stand_in(scenario=(status, {}))
            result = post_scenario_outcome(OUTCOME, self.settings(stand_in))
            self.assertFalse(result.ok, status)
            self.assertEqual(result.status, status)
            self.assertIn(text, result.detail)
            self.assertIn(f"HTTP {status}", result.detail)

    def test_a_created_answer_that_is_not_json_is_still_a_success_without_a_sequence(self):
        stand_in = self.stand_in(scenario=(201, b"not json"))
        result = post_scenario_outcome(OUTCOME, self.settings(stand_in))
        self.assertEqual((result.ok, result.seq), (True, None))
        stand_in = self.stand_in(scenario=(201, {"seq": "seven"}))
        self.assertIsNone(post_scenario_outcome(OUTCOME, self.settings(stand_in)).seq)

    def test_a_redirect_is_never_followed_and_the_token_goes_nowhere_else(self):
        stand_in = self.stand_in(scenario="redirect")
        result = post_scenario_outcome(OUTCOME, self.settings(stand_in))
        self.assertFalse(result.ok)
        self.assertEqual(result.status, 307)
        self.assertEqual(stand_in.hits_elsewhere, 0)

    def test_a_server_that_hangs_up_or_is_not_there_is_a_result_not_an_exception(self):
        stand_in = self.stand_in(scenario="hangup")
        result = post_scenario_outcome(OUTCOME, self.settings(stand_in))
        self.assertEqual((result.ok, result.status), (False, None))
        self.assertIn("cannot be reached", result.detail)
        stand_in.stop()
        again = post_scenario_outcome(OUTCOME, self.settings(stand_in))
        self.assertEqual((again.ok, again.status), (False, None))
        self.assertIn("cannot be reached", again.detail)

    def test_without_a_token_file_the_account_logs_in_first_and_the_login_token_is_used(self):
        stand_in = self.stand_in()
        settings = self.settings(stand_in, token_file=None, username="ana", password_file=str(self.password_file))
        result = post_scenario_outcome(OUTCOME, settings)
        self.assertTrue(result.ok)
        self.assertEqual([path for path, _, _ in stand_in.requests], [LOGIN_ROUTE, SCENARIO_ROUTE])
        self.assertEqual(json.loads(stand_in.requests[0][2]), {"username": "ana", "password": "the-password"})
        self.assertEqual(stand_in.requests[1][1]["authorization"], "Bearer login-token-value")

    def test_a_failed_login_stops_before_the_outcome_is_sent(self):
        for login in ((401, {}), (200, {}), (200, {"token": ""}), (200, {"token": 5}), (200, b"junk"), "hangup", "redirect"):
            stand_in = self.stand_in(login=login)
            settings = self.settings(stand_in, token_file=None, username="ana", password_file=str(self.password_file))
            result = post_scenario_outcome(OUTCOME, settings)
            self.assertFalse(result.ok, login)
            self.assertEqual([path for path, _, _ in stand_in.requests], [LOGIN_ROUTE], login)

    def test_a_missing_or_empty_credential_sends_nothing(self):
        stand_in = self.stand_in()
        empty = self.dir / "empty"
        empty.write_text("  \n", encoding="utf-8")
        for settings in (
            self.settings(stand_in, token_file=None),
            self.settings(stand_in, token_file=str(empty)),
            self.settings(stand_in, token_file=str(self.dir / "absent")),
            self.settings(stand_in, token_file=None, username="ana"),
            self.settings(stand_in, token_file=None, username="ana", password_file=str(empty)),
            self.settings(stand_in, token_file=None, password_file=str(self.password_file)),
        ):
            result = post_scenario_outcome(OUTCOME, settings)
            self.assertFalse(result.ok)
            self.assertIn("no credential", result.detail)
        self.assertEqual(stand_in.requests, [])

    def test_an_address_that_could_leak_the_credential_is_refused_before_any_request(self):
        stand_in = self.stand_in()
        for url in ("ftp://127.0.0.1/x", "http:///nohost", "http://user:pw@127.0.0.1:1/x", "http://user@127.0.0.1:1/x", "http://example.org/x", ""):
            result = post_scenario_outcome(OUTCOME, self.settings(stand_in, server_url=url))
            self.assertFalse(result.ok, url)
            self.assertIsNone(result.status)
        self.assertEqual(stand_in.requests, [])

    def test_a_malformed_outcome_is_refused_without_touching_the_network(self):
        stand_in = self.stand_in()
        bad = [
            "text", [], {}, {**OUTCOME, "schema_version": "2.0"}, {**OUTCOME, "phase": "during"},
            {**OUTCOME, "scenario_id": ""}, {**OUTCOME, "run_id": 5}, {**OUTCOME, "observed": []},
            {**OUTCOME, "observed": {"outcome": "maybe"}}, {k: v for k, v in OUTCOME.items() if k != "repro_case"},
        ]
        for outcome in bad:
            self.assertIsNotNone(outcome_problem(outcome), outcome)
            self.assertFalse(post_scenario_outcome(outcome, self.settings(stand_in)).ok)
        self.assertEqual(stand_in.requests, [])
        for phase in ("before", "after"):
            for observed in ("reproduced", "not-reproduced", "error"):
                self.assertIsNone(outcome_problem({**OUTCOME, "phase": phase, "observed": {"outcome": observed}}))

    def test_a_trailing_slash_on_the_address_does_not_double_the_route(self):
        stand_in = self.stand_in()
        self.assertTrue(post_scenario_outcome(OUTCOME, self.settings(stand_in, server_url=stand_in.url + "/")).ok)
        self.assertEqual(stand_in.requests[0][0], SCENARIO_ROUTE)

    def test_the_result_dictionary_has_the_documented_keys(self):
        stand_in = self.stand_in()
        self.assertEqual(
            post_scenario_outcome(OUTCOME, self.settings(stand_in)).to_dict(),
            {"ok": True, "status": 201, "detail": "kept by the server", "seq": 7},
        )


class LoaderRefusals(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "ingest.json"

    def load(self, document):
        self.path.write_text(json.dumps(document), encoding="utf-8")
        return load_ingest_settings(self.path)

    def test_a_switched_off_document_gives_nothing_even_when_it_is_incomplete(self):
        self.assertIsNone(self.load({"enabled": False}))
        self.assertIsNone(self.load({}))

    def test_a_malformed_document_is_refused_in_every_field(self):
        base = {"enabled": True, "server_url": "https://s.example", "token_file": "/t"}
        bad = [
            {**base, "surprise": 1}, {**base, "enabled": "yes"}, {**base, "allow_plain_http": 1}, {**base, "server_url": 5},
            {**base, "server_url": "  "}, {**base, "token_file": ""}, {**base, "timeout_seconds": True},
            {**base, "timeout_seconds": 0.05}, {**base, "timeout_seconds": 601}, {**base, "timeout_seconds": "5"},
            {"enabled": True, "token_file": "/t"}, {"enabled": True, "server_url": "https://s.example"},
            {"enabled": True, "server_url": "https://s.example", "username": "ana"},
        ]
        for document in bad:
            with self.assertRaises(ConfigValidationError, msg=document):
                self.load(document)

    def test_the_limits_of_the_timeout_and_the_two_credential_forms_are_accepted(self):
        for timeout in (0.1, 600, 5):
            settings = self.load({"enabled": True, "server_url": "https://s.example", "token_file": "/t", "timeout_seconds": timeout})
            self.assertEqual(settings.timeout_seconds, float(timeout))
        settings = self.load({"enabled": True, "server_url": "http://127.0.0.1:1", "username": "a", "password_file": "/p", "allow_plain_http": True})
        self.assertEqual((settings.username, settings.password_file, settings.allow_plain_http), ("a", "/p", True))


if __name__ == "__main__":
    unittest.main()
