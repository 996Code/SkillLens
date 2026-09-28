"""S26 补充：流程（synth_flow）Playwright 导出（S25 遗留 P3，TDD 先红）。

- 导出脚本自包含：子进程独立运行打本地 mock → PASS；
- 步骤失败（按钮不存在）→ FAIL 非零退出；
- 404：flow 不存在。
"""
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
</body></html>"""


class _Handler(BaseHTTPRequestHandler):
    fail_mode = False

    def do_GET(self):
        body = (FORM_HTML if not _Handler.fail_mode
                else FORM_HTML.replace(">保存<", ">改名了<")).encode("utf-8")
        self.send_response(200)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def _start_server() -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _seed_flow(base_url: str) -> int:
    from app.db import SessionLocal
    from app.models import SynthFlow
    db = SessionLocal()
    try:
        row = SynthFlow(
            goal="测试流程导出", system_hint="mock",
            steps=[
                {"kind": "goto", "target": base_url},
                {"kind": "input", "target": "请输入", "value": "导出值"},
                {"kind": "click", "target": "保存"},
            ],
            status="proposed", notes="", evidence_refs=[],
            execution_log=None)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


async def test_flow_export_runs_standalone(client):
    server = _start_server()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}/"
        fid = _seed_flow(base_url)
        resp = await client.get(f"/api/v1/flows/{fid}/export/playwright")
        assert resp.status_code == 200
        with tempfile.NamedTemporaryFile(
                suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write(resp.text)
            path = f.name
        proc = subprocess.run([sys.executable, path], capture_output=True,
                              text=True, timeout=120)
        Path(path).unlink()
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "PASS" in proc.stdout
    finally:
        server.shutdown()
        _Handler.fail_mode = False


async def test_flow_export_step_failure(client):
    server = _start_server()
    try:
        base_url = f"http://127.0.0.1:{server.server_address[1]}/"
        fid = _seed_flow(base_url)
        _Handler.fail_mode = True          # 按钮改名 → click 定位失败
        resp = await client.get(f"/api/v1/flows/{fid}/export/playwright")
        with tempfile.NamedTemporaryFile(
                suffix=".py", delete=False, mode="w", encoding="utf-8") as f:
            f.write(resp.text)
            path = f.name
        proc = subprocess.run([sys.executable, path], capture_output=True,
                              text=True, timeout=120)
        Path(path).unlink()
        assert proc.returncode == 1
        assert "FAIL" in proc.stdout
    finally:
        server.shutdown()
        _Handler.fail_mode = False


async def test_flow_export_404(client):
    resp = await client.get("/api/v1/flows/99999/export/playwright")
    assert resp.status_code == 404
