# =============================================================================
# HYDRA-UMC-DEV-SERVER - tests/test_api.py
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0 - see LICENSE
# =============================================================================
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
