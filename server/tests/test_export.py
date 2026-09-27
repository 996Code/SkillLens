"""S25 块 W1：Playwright 导出（TDD 先红，真机独立运行验证）。

- 导出脚本自包含：子进程独立运行打真实本地 HTTP 服务 → PASS（退出码 0）；
- 断言生效：服务端改回 500 → 脚本 FAIL（非零退出）；
- 端点：404（skill 不存在）/ 200（text/x-python）。
"""
import json
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FORM_HTML = """<html><body>
<form>
  <input name="请输入" placeholder="请输入"/>
  <button type="submit">保存</button>
</form>
<script>
document.querySelector("button").addEventListener("click", e => {
  e.preventDefault();
  fetch("/a/1/save", {method: "POST", body: "{}"});
});
</script>
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    fail_mode = False  # 类属性由测试切换（500 模式）

    def do_GET(self):
        body = FORM_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if _Handler.fail_mode:
            body = b'{"code":500}'
            status = 500
        else:
            body = b'{"code":200}'
            status = 200
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _start_server() -> tuple[ThreadingHTTPServer, str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, f"http://127.0.0.1:{port}/"


async def _seed_skill(client, monkeypatch, base_url) -> dict:
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       json.dumps({"name": "SaveForm", "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation",
         "payload": {"type": "page-load", "url": base_url}},
        {"seq": 1, "ts": 100, "kind": "action",
         "payload": {"type": "input", "name": "请输入", "value": "旧"}},
        {"seq": 2, "ts": 200, "kind": "action",
         "payload": {"type": "click", "target": {"label": "保存"}}},
        {"seq": 3, "ts": 260, "kind": "network",
         "payload": {"method": "POST", "url": "/a/1/save", "status": 200,
                     "reqBody": "{}", "resBody": '{"code":200}'}},
    ]
    await client.post(f"/api/v1/sessions/{sid}/events", json=events)
    await client.post(f"/api/v1/sessions/{sid}/process")
    aid = (await client.post("/api/v1/align", json={"session_ids": [sid, sid]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")
    return skill


async def test_export_script_runs_standalone_and_passes(client, monkeypatch):
    server, base_url = _start_server()
    try:
        skill = await _seed_skill(client, monkeypatch, base_url)
        resp = await client.get(f"/api/v1/skills/{skill['id']}/export/playwright")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/x-python")

        script = resp.text
        assert "API_ASSERTIONS" in script and "locate" in script
        with tempfile.NamedTemporaryFile(
                suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write(script)
            path = f.name
        proc = subprocess.run([sys.executable, path], capture_output=True,
                              text=True, timeout=120)
        Path(path).unlink()
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "PASS" in proc.stdout
    finally:
        server.shutdown()
        _Handler.fail_mode = False


async def test_export_script_fails_when_assertion_broken(client, monkeypatch):
    server, base_url = _start_server()
    try:
        skill = await _seed_skill(client, monkeypatch, base_url)
        resp = await client.get(f"/api/v1/skills/{skill['id']}/export/playwright")
        script = resp.text
        _Handler.fail_mode = True          # 服务端 500 → api_status 断言 FAIL
        with tempfile.NamedTemporaryFile(
                suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write(script)
            path = f.name
        proc = subprocess.run([sys.executable, path], capture_output=True,
                              text=True, timeout=120)
        Path(path).unlink()
        assert proc.returncode == 1
        assert "FAIL" in proc.stdout
    finally:
        server.shutdown()
        _Handler.fail_mode = False


async def test_export_404(client):
    resp = await client.get("/api/v1/skills/99999/export/playwright")
    assert resp.status_code == 404
