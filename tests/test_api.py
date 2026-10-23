# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_api.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
import json
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from hydra_umc_dev_server import api as api_module
from hydra_umc_dev_server.api import ApiConfigError, DevServer, MAX_BODY_BYTES, validate_bind

TOKEN = "t" * 32


class ConfigTests(unittest.TestCase):
    def test_only_loopback_addresses_and_real_tokens_are_accepted(self):
        validate_bind("127.0.0.1", TOKEN)
        validate_bind("::1", TOKEN)
        for host in ("0.0.0.0", "192.168.0.10", "localhost", ""):
            with self.assertRaises(ApiConfigError, msg=host):
                validate_bind(host, TOKEN)
        for token in ("", "short", None):
            with self.assertRaises(ApiConfigError, msg=token):
                validate_bind("127.0.0.1", token)

    def test_the_server_refuses_to_start_on_a_public_address(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ApiConfigError):
                DevServer(("0.0.0.0", 0), token=TOKEN, workspace_root=Path(tmp), plugins_root=Path(tmp))


class ApiTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.workspace = root / "ws"
        self.plugins = root / "plugins"
        (self.workspace / "proj").mkdir(parents=True)
        (self.workspace / "proj" / "hydra-umc.project.json").write_text(
            json.dumps({"name": "proj", "version": "0.1.0", "maturity": "scaffolding"}), encoding="utf-8"
        )
        plugin = self.plugins / "demo"
        plugin.mkdir(parents=True)
        (plugin / "plugin.json").write_text(
            json.dumps({"name": "demo", "version": "0.1.0", "api_version": 1, "entry": "plugin.py"}), encoding="utf-8"
        )
        (plugin / "plugin.py").write_text("def register(r):\n    r.add_check('ping', lambda: {'pong': True})\n", encoding="utf-8")
        self.server = DevServer(("127.0.0.1", 0), token=TOKEN, workspace_root=self.workspace, plugins_root=self.plugins)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self._stop)

    def _stop(self):
        self.server.shutdown()
        self.server.server_close()

    def _call(self, method, path, body=None, token=TOKEN, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        request = urllib.request.Request(self.base + path, data=data, method=method)
        if token is not None:
            request.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_health_needs_no_token_but_everything_else_does(self):
        self.assertEqual(self._call("GET", "/v1/health", token=None)[0], 200)
        for method, path in (("GET", "/v1/inventory"), ("GET", "/v1/plugins"), ("POST", "/v1/plugins/rescan")):
            self.assertEqual(self._call(method, path, token=None)[0], 401, path)
            self.assertEqual(self._call(method, path, token="x" * 32)[0], 401, path)

    def test_inventory_lists_the_workspace_manifests(self):
        status, body = self._call("GET", "/v1/inventory")
        self.assertEqual(status, 200)
        self.assertEqual([p["name"] for p in body["projects"]], ["proj"])

    def test_the_plugin_lifecycle_over_http(self):
        status, body = self._call("GET", "/v1/plugins")
        self.assertEqual(body["plugins"][0]["state"], "discovered")
        digest = body["plugins"][0]["sha256"]

        self.assertEqual(self._call("POST", "/v1/plugins/demo/checks/ping")[0], 409)  # not enabled yet
        status, body = self._call("POST", "/v1/plugins/demo/enable", {"sha256": "0" * 64})
        self.assertEqual((status, body["state"]), (409, "failed"))
        status, body = self._call("POST", "/v1/plugins/demo/enable", {"sha256": digest})
        self.assertEqual((status, body["state"]), (200, "enabled"))
        self.assertEqual(self._call("POST", "/v1/plugins/demo/checks/ping"), (200, {"status": "ok", "result": {"pong": True}}))
        self.assertEqual(self._call("POST", "/v1/plugins/demo/disable")[1]["state"], "disabled")
        self.assertEqual(self._call("POST", "/v1/plugins/demo/checks/ping")[0], 409)

    def test_errors_are_named(self):
        self.assertEqual(self._call("POST", "/v1/plugins/ghost/enable", {"sha256": "0" * 64})[0], 404)
        self.assertEqual(self._call("POST", "/v1/plugins/demo/enable", {})[0], 400)
        self.assertEqual(self._call("POST", "/v1/plugins/demo/enable", raw=b"not json")[0], 400)
        self.assertEqual(self._call("POST", "/v1/plugins/demo/enable", raw=b"[1]")[0], 400)
        self.assertEqual(self._call("POST", "/v1/plugins/demo/enable", raw=b"x" * (MAX_BODY_BYTES + 1))[0], 413)
        self.assertEqual(self._call("GET", "/v1/nothing")[0], 404)
        self.assertEqual(self._call("POST", "/v1/nothing")[0], 404)

    def test_rescan_picks_up_a_new_plugin(self):
        new = self.plugins / "second"
        new.mkdir()
        (new / "plugin.json").write_text(
            json.dumps({"name": "second", "version": "0.1.0", "api_version": 1, "entry": "plugin.py"}), encoding="utf-8"
        )
        (new / "plugin.py").write_text("def register(r): pass\n", encoding="utf-8")
        status, body = self._call("POST", "/v1/plugins/rescan")
        self.assertEqual(status, 200)
        self.assertEqual([p["name"] for p in body["plugins"]], ["demo", "second"])

    def test_an_idle_connection_is_dropped_and_the_server_keeps_serving(self):
        self.assertGreater(api_module._Handler.timeout, 0)
        original = api_module._Handler.timeout
        api_module._Handler.timeout = 0.3
        self.addCleanup(setattr, api_module._Handler, "timeout", original)
        idle = socket.create_connection(self.server.server_address, timeout=5)
        self.addCleanup(idle.close)
        idle.sendall(b"POST /v1/plugins/rescan HTTP/1.1\r\nHost: x\r\nContent-Length: 10\r\n")  # headers never finish
        idle.settimeout(5)
        self.assertEqual(idle.recv(1024), b"")  # the server closed it instead of waiting forever
        self.assertEqual(self._call("GET", "/v1/health", token=None)[0], 200)


    def test_the_audit_trail_lists_the_requests_without_bodies_tokens_or_queries(self):
        self._call("GET", "/v1/inventory?secret=1")
        self._call("GET", "/v1/inventory", token="wrong" * 8)
        self._call("POST", "/v1/plugins/demo/enable", {"sha256": "0" * 64})
        status, body = self._call("GET", "/v1/audit")
        self.assertEqual(status, 200)
        entries = body["entries"]
        self.assertEqual([(e["method"], e["path"], e["status"]) for e in entries[:3]],
                         [("GET", "/v1/inventory", 200), ("GET", "/v1/inventory", 401), ("POST", "/v1/plugins/demo/enable", 409)])
        self.assertTrue(all(set(e) == {"at", "method", "path", "status", "client"} for e in entries))
        self.assertNotIn("secret", json.dumps(entries))
        self.assertNotIn("wrong", json.dumps(entries))
        self.assertEqual(self._call("GET", "/v1/audit", token=None)[0], 401)

    def test_the_audit_trail_is_a_ring(self):
        for _ in range(api_module.AUDIT_ENTRIES + 5):
            self.server.audit.append({"n": 1})
        self.assertEqual(len(self.server.audit), api_module.AUDIT_ENTRIES)


class ConnectionCapTests(unittest.TestCase):
    def test_a_connection_over_the_cap_is_answered_503_and_the_slot_comes_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = DevServer(("127.0.0.1", 0), token=TOKEN, workspace_root=Path(tmp), plugins_root=Path(tmp), max_connections=1)
            threading.Thread(target=server.serve_forever, daemon=True).start()

            def stop():
                server.shutdown()
                server.server_close()

            self.addCleanup(stop)
            holder = socket.create_connection(server.server_address, timeout=5)  # takes the only slot and says nothing
            self.addCleanup(holder.close)
            deadline = time.time() + 5
            status = 0
            while time.time() < deadline and status != 503:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/v1/health", timeout=5) as response:
                        status = response.status
                except urllib.error.HTTPError as error:
                    status = error.code
                time.sleep(0.05)
            self.assertEqual(status, 503)
            holder.close()
            deadline = time.time() + 5
            while time.time() < deadline and status != 200:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{server.server_address[1]}/v1/health", timeout=5) as response:
                        status = response.status
                except urllib.error.HTTPError as error:
                    status = error.code
                time.sleep(0.05)
            self.assertEqual(status, 200, "the slot was given back when the connection closed")

    def test_a_cap_below_one_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ApiConfigError):
                DevServer(("127.0.0.1", 0), token=TOKEN, workspace_root=Path(tmp), plugins_root=Path(tmp), max_connections=0)


class OpenApiDocumentTests(unittest.TestCase):
    """docs/openapi.json describes the routes the handler serves, no more and no fewer."""

    def test_every_route_of_the_handler_is_in_the_document_and_the_other_way_round(self):
        import re

        document = json.loads((Path(__file__).resolve().parent.parent / "docs" / "openapi.json").read_text(encoding="utf-8"))
        documented = {(method.upper(), path) for path, item in document["paths"].items() for method in item}
        source = (Path(__file__).resolve().parent.parent / "src" / "hydra_umc_dev_server" / "api.py").read_text(encoding="utf-8")
        served = set()
        get_part, post_part = source.split("def do_POST")
        served |= {("GET", p) for p in re.findall(r'path == "(/v1/[a-z/]+)"', get_part)}
        served |= {("POST", p) for p in re.findall(r'path == "(/v1/[a-z/]+)"', post_part)}
        served |= {("POST", "/v1/plugins/{name}/" + word) for word in ("enable", "disable")}
        served |= {("POST", f"/v1/plugins/{{name}}/{kind}/{{{kind[:-1]}}}") for kind in ("checks", "reports", "generators")}
        self.assertEqual(documented, served)

    def test_the_document_names_the_busy_answer_and_the_limit(self):
        text = (Path(__file__).resolve().parent.parent / "docs" / "openapi.json").read_text(encoding="utf-8")
        self.assertIn(str(api_module.MAX_CONNECTIONS), text)
        self.assertIn(str(api_module.MAX_BODY_BYTES), text)


if __name__ == "__main__":
    unittest.main()
