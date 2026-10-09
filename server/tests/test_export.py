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
                              text=True, timeout=120, encoding="utf-8",
                              errors="replace")
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
                              text=True, timeout=120, encoding="utf-8",
                              errors="replace")
        Path(path).unlink()
        assert proc.returncode == 1
        assert "FAIL" in proc.stdout
    finally:
        server.shutdown()
        _Handler.fail_mode = False


async def test_export_404(client):
    resp = await client.get("/api/v1/skills/99999/export/playwright")
    assert resp.status_code == 404


# ---------- 评审#1：判定逻辑单一事实源（export_shared 内嵌，非手抄副本） ----------

async def test_export_script_judgment_single_source(client, monkeypatch):
    """生成脚本内嵌 export_shared 源码：_ID_SEGMENT 与 assert_eval 同
    pattern（S43-5 长 hex 动态段）；api_status 混合结果判 FAIL（服务端
    all(s==expect) 语义）；state_signal 取最后一次写响应（终态语义）。"""
    from app.replay import assert_eval
    server, base_url = _start_server()
    try:
        skill = await _seed_skill(client, monkeypatch, base_url)
        resp = await client.get(f"/api/v1/skills/{skill['id']}/export/playwright")
        src = resp.text
    finally:
        server.shutdown()
    assert "与 locate.py 同策略链" not in src   # 虚假声明已纠正（评审#1d）
    ns = {"__name__": "gen_script"}             # 防 __main__ 守卫执行 main()
    exec(compile(src, "<gen>", "exec"), ns)
    # 动态段规则与 assert_eval 完全一致（import 两侧比对，非字符串抄本）
    assert ns["_ID_SEGMENT"].pattern == assert_eval._ID_SEGMENT.pattern
    assert ns["static_segments"]("/form/0123456789abcdef/x") == \
        assert_eval._static_segments("/form/0123456789abcdef/x") == ["form", "x"]
    assert ns["path_matches"]("http://h/a/0123456789abcdef/save?x=1", "/a/{id}/save")
    # P2-10 query 感知匹配：内嵌副本与服务端实现同语义（模板带 query
    # 须同值全含；无 query 旧语义）
    assert ns["path_matches"]("http://h/index.php?m=bug&f=close&x=1",
                               "/index.php?m=bug&f=close") is True
    assert ns["path_matches"]("http://h/index.php?m=bug&f=browse",
                               "/index.php?m=bug&f=close") is False
    # api_status：混合结果（200+500）→ FAIL（旧导出 all(h != expect) 会误 PASS）
    mixed = [{"status": 200}, {"status": 500}]
    assert ns["judge_api_status"](mixed, 200) is False
    assert ns["judge_api_status"]([{"status": 200}, {"status": 200}], 200) is True
    assert ns["judge_api_status"]([], 200) is False
    # state_signal：多次写响应取最后一次（终态）；GET 噪声不污染判定
    hits = [{"method": "POST", "status": 200, "body": '{"code":500}'},
            {"method": "GET", "status": 200, "body": '{"code":999}'},
            {"method": "POST", "status": 200, "body": '{"code":200}'}]
    assert ns["judge_state_signal"](hits, "code", 200) is True
    assert ns["judge_state_signal"](hits, "code", 999) is False
    assert ns["judge_state_signal"](hits, "code", 500) is False  # 首次写不是终态


def _assert_no_live_injection(src: str):
    """生成脚本必须可编译，且 AST 中不存在被注入的活语句（import os /
    os.system 调用）——消毒后恶意名称只以惰性文本存在于 docstring。"""
    import ast
    tree = ast.parse(src)   # SyntaxError = 结构被注入破坏 → 直接失败
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name.split(".")[0] == "os" for a in node.names), src[:400]
        if isinstance(node, ast.ImportFrom):
            assert (node.module or "").split(".")[0] != "os", src[:400]
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            assert node.func.attr not in ("system", "popen", "exec"), src[:400]


async def test_export_script_skill_name_injection_inert(client, monkeypatch):
    """评审#2：skill.name 含 ''' / 引号 / 换行 → 生成脚本仍可编译，
    注入语句只存在于 docstring 文本（AST 无活代码）。"""
    from app.db import SessionLocal
    from app.models import Skill
    server, base_url = _start_server()
    try:
        skill = await _seed_skill(client, monkeypatch, base_url)
        db = SessionLocal()
        try:
            row = db.get(Skill, skill["id"])
            row.name = "x''' ; import os; os.system(\"id\") #\n\"\"\"y"
            db.commit()
        finally:
            db.close()
        resp = await client.get(f"/api/v1/skills/{skill['id']}/export/playwright")
        src = resp.text
    finally:
        server.shutdown()
    _assert_no_live_injection(src)


async def test_export_flow_goal_injection_inert(client):
    """评审#2：flow.goal 同款注入 → 流程导出脚本仍可编译、无活语句。"""
    from app.db import SessionLocal
    from app.models import SynthFlow
    from app.replay.exporter import export_flow_playwright
    db = SessionLocal()
    try:
        flow = SynthFlow(goal='g""" ; import os; os.system("id") #',
                         system_hint="h",
                         steps=[{"kind": "goto", "target": "http://t/"}],
                         evidence_refs=[])
        db.add(flow)
        db.commit()
        db.refresh(flow)
        src = export_flow_playwright(db, flow.id)
    finally:
        db.close()
    _assert_no_live_injection(src)
