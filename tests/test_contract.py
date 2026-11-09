# -*- coding: utf-8 -*-
"""对接契约自检：/api/health 与 /api/manifest 必须返回真实、可解析、无隐私的 JSON。

不依赖任何第三方库，也不连供应商：临时数据目录 + 进程内起一个 ThreadingHTTPServer。
运行：python -m unittest discover -s tests
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT))


class ContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 先把数据目录指到临时目录，再导入面板：避免碰真实 config.json / 素材 / 产出
        cls._tmp = tempfile.TemporaryDirectory()
        os.environ["VOICE_STUDIO_HOME"] = cls._tmp.name
        from panel import server as panel_server  # noqa: PLC0415

        cls.panel_server = panel_server
        cls.httpd = panel_server.ThreadingHTTPServer(("127.0.0.1", 0), panel_server.Handler)
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls._tmp.cleanup()
        os.environ.pop("VOICE_STUDIO_HOME", None)

    def _get(self, path: str):
        url = f"http://127.0.0.1:{self.port}{path}"
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def test_health(self) -> None:
        status, body = self._get("/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(body["ok"], True)
        self.assertEqual(body["id"], "voice")
        self.assertEqual(body["version"], self.panel_server.config.VERSION)
        self.assertIsInstance(body["uptime_s"], int)
        self.assertGreaterEqual(body["uptime_s"], 0)

    def test_manifest(self) -> None:
        status, body = self._get("/api/manifest")
        self.assertEqual(status, 200)
        self.assertEqual(body["ok"], True)
        expected = json.loads((PLUGIN_ROOT / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(body["metadata"], expected)
        runtime = body["runtime"]
        self.assertEqual(runtime["port"], self.port)  # 实际监听端口，而不是配置里的 17878
        self.assertEqual(runtime["pid"], os.getpid())
        self.assertIsInstance(datetime.fromisoformat(runtime["started_at"]), datetime)

    def test_metadata_declares_contract(self) -> None:
        meta = json.loads((PLUGIN_ROOT / "metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["id"], "voice")
        caps = meta["capabilities"]
        self.assertTrue(3 <= len(caps) <= 6)
        self.assertTrue(all(isinstance(c, str) and c.strip() for c in caps))
        standalone = meta["standalone"]
        self.assertIs(standalone["works_alone"], True)
        self.assertIsInstance(standalone["needs"], list)
        self.assertTrue(standalone["how"].strip())
        self.assertTrue((PLUGIN_ROOT / meta["contract"]).is_file())

    def test_readonly_endpoints_do_not_leak_secrets(self) -> None:
        for path in ("/api/health", "/api/manifest"):
            _, body = self._get(path)
            raw = json.dumps(body, ensure_ascii=False).lower()
            self.assertNotIn("api_key", raw)
            self.assertNotIn("sk-", raw)
            self.assertNotIn("c:\\users\\", raw)

    def test_unknown_route_still_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/nope", timeout=10)
        err = ctx.exception
        try:
            self.assertEqual(err.code, 404)
            self.assertEqual(json.loads(err.read().decode("utf-8"))["error"], "not found")
        finally:
            err.close()


if __name__ == "__main__":
    unittest.main()