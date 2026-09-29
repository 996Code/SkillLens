import json

from playwright.async_api import async_playwright

from app.replay.runner import execute_plan

FORM_HTML = """
<html><body>
  <input placeholder="请输入" />
  <button role="button">保存</button>
</body></html>
"""


async def test_execute_plan_semantic_locate():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        # R1: 固定 mock origin，避免 about:blank 上相对 fetch 解析失败；charset 防 UTF-8 被按 Latin-1 解码
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=FORM_HTML))
        await page.goto("http://mock.local/")
        calls = []

        async def handle_save(route):
            calls.append(route.request.url)
            await route.fulfill(status=200, body='{"code":200}')

        await page.route("**/api/save", handle_save)
        plan = {"url": "http://mock.local/", "steps": [
            {"kind": "input", "name": "请输入", "value": "v1", "original_value": "o"},
            {"kind": "click", "label": "保存"},
        ]}
        # 注入一个真实触发 fetch 的按钮行为（绝对 URL，确保 route **/api/save 捕获）
        await page.evaluate("""() => {
          document.querySelector('button').addEventListener('click',
            () => fetch('http://mock.local/api/save', {method: 'POST'}));
        }""")
        result = await execute_plan(page, plan)
        await browser.close()
    assert [s["ok"] for s in result["executed"]] == [True, True]
    assert result["executed"][0]["strategy"] in ("placeholder",)
    assert len(result["observed"]) == 1 and result["observed"][0]["status"] == 200
    assert len(calls) == 1


async def test_execute_plan_waits_for_awaited_templates():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=FORM_HTML))
        await page.goto("http://mock.local/")
        plan = {"url": "http://mock.local/", "steps": [
            {"kind": "click", "label": "保存"},
        ]}
        # 保存后链式请求延迟 2.5s 才发出——超过旧固定 1.5s 收尾窗口
        await page.route("**/api/slow",
                         lambda route: route.fulfill(status=200, body='{"code":200}'))
        await page.evaluate("""() => {
          document.querySelector('button').addEventListener('click',
            () => setTimeout(
              () => fetch('http://mock.local/api/slow', {method: 'POST'}),
              2500));
        }""")
        result = await execute_plan(
            page, plan, awaited_templates=["/api/slow"], settle_timeout_ms=6000)
        await browser.close()
    assert result["executed"][0]["ok"] is True
    assert any("/api/slow" in o["url"] for o in result["observed"]), \
        f"延迟 2.5s 的链式请求未被等到: {result['observed']}"


async def test_execute_plan_stops_on_missing_element():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(FORM_HTML)
        plan = {"url": "about:blank", "steps": [
            {"kind": "click", "label": "不存在的按钮"},
            {"kind": "click", "label": "保存"},
        ]}
        result = await execute_plan(page, plan)
        await browser.close()
    assert result["executed"][0]["ok"] is False
    assert result["executed"][1]["ok"] is False and result["executed"][1]["error"] == "not attempted"


async def test_execute_plan_input_survives_hydration_overwrite():
    """水合竞态：SPA 在首次 input 后把值改回旧值，fill 必须确认值真的写入。"""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=FORM_HTML))
        await page.goto("http://mock.local/")
        await page.evaluate("""() => {
          let n = 0;
          const input = document.querySelector('input');
          input.addEventListener('input', () => {
            if (n++ === 0) input.value = '旧值';
          });
        }""")
        plan = {"url": "http://mock.local/", "steps": [
            {"kind": "input", "name": "请输入", "value": "新值",
             "original_value": "旧值"},
        ]}
        result = await execute_plan(page, plan)
        final = await page.locator("input").input_value()
        await browser.close()
    assert result["executed"][0]["ok"] is True
    assert final == "新值"


async def test_collect_page_snapshot_forms():
    """快照采集：placeholder 作 label、input_value 取值、密码框跳过、敏感脱敏。"""
    from app.replay.page_snapshot import collect_page_snapshot
    html = """
    <html><body>
      <input placeholder="备注" value="v1" />
      <input type="password" placeholder="密码" value="secret" />
      <input aria-label="API Token" value="tk-123" />
    </body></html>
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html)
        snap = await collect_page_snapshot(page)
        await browser.close()
    labels = [f["label"] for f in snap["forms"]]
    assert "备注" in labels
    assert "密码" not in labels                      # 密码框整体跳过
    by_label = {f["label"]: f["value"] for f in snap["forms"]}
    assert by_label["备注"] == "v1"
    assert by_label["API Token"] == "[REDACTED]"     # token 命中敏感词表
    assert set(snap) >= {"forms", "labels", "tables"}  # 结构键与插件 Snapshot 对齐


async def test_collect_page_snapshot_field_caps():
    """红线对齐：>50 字段截断且 overflow=true；单值 1024 截断。"""
    from app.replay.page_snapshot import collect_page_snapshot
    fields = "".join(f'<input placeholder="f{i}" value="v" />' for i in range(60))
    html = f"<html><body>{fields}<input placeholder='big' value='{'x' * 2000}' /></body></html>"
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html)
        snap = await collect_page_snapshot(page)
        await browser.close()
    assert len(snap["forms"]) == 50
    assert snap["overflow"] is True
    assert all(len(f["value"]) <= 1024 for f in snap["forms"])


async def test_collect_page_snapshot_label_truncation():
    """label 文本兜底超 100 截断——与插件 describe-element.ts slice(0,100) 同源对齐。"""
    from app.replay.page_snapshot import collect_page_snapshot
    long_text = "长" * 180
    html = f"""
    <html><body>
      <textarea>{long_text}</textarea>
      <div class="tag">{'标' * 180}</div>
    </body></html>
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html)
        snap = await collect_page_snapshot(page)
        await browser.close()
    # textarea 无 aria/placeholder/title → 兜底累积文本，须截 100
    form_labels = [f["label"] for f in snap["forms"]]
    assert len(form_labels) == 1 and len(form_labels[0]) == 100, form_labels
    # labels（状态标签）同样按 100 截断
    assert len(snap["labels"]) == 1 and len(snap["labels"][0]["text"]) == 100


class _DetachingPage:
    """代理真实 page：字段句柄全部拿到后立即 goto（执行上下文销毁），
    模拟采集途中页面跳转/React 重渲染导致句柄 detach
    （Playwright 抛 "Execution context was destroyed"）。"""

    def __init__(self, page):
        self._page = page
        self._navigated = False

    async def query_selector_all(self, selector):
        els = await self._page.query_selector_all(selector)
        if not self._navigated and els:
            self._navigated = True
            await self._page.goto("about:blank")  # 句柄全部失效
        return els

    def __getattr__(self, name):
        return getattr(self._page, name)


async def test_collect_page_snapshot_detached_element_tolerated():
    """元素在采集过程中 detach（上下文销毁）→ 跳过该字段/标签继续，
    collect 整体不抛异常（不把 run 打成 error）。"""
    from app.replay.page_snapshot import collect_page_snapshot
    html = """
    <html><body>
      <input placeholder="f0" value="v0" />
      <span class="tag">t0</span>
    </body></html>
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html)
        snap = await collect_page_snapshot(_DetachingPage(page))
        await browser.close()
    # 所有句柄 detach → 字段/标签被跳过，返回结构完整的空快照而非抛异常
    assert snap["forms"] == [] and snap["labels"] == [], snap


async def test_collect_page_snapshot_labels_hidden_ancestor_filtered():
    """labels 可见过滤：closest hidden 祖先（display:none/visibility:hidden/
    hidden 属性/祖先 aria-hidden）近似过滤，与插件 CS 侧行为对齐。"""
    from app.replay.page_snapshot import collect_page_snapshot
    html = """
    <html><body>
      <span class="tag">visible</span>
      <div style="display:none"><span class="tag">displayNone</span></div>
      <div style="visibility:hidden"><span class="tag">visHidden</span></div>
      <div hidden><span class="tag">attrHidden</span></div>
      <div aria-hidden="true"><span class="tag">ariaHiddenAncestor</span></div>
      <span class="tag" aria-hidden="true">ariaHiddenSelf</span>
    </body></html>
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html)
        snap = await collect_page_snapshot(page)
        await browser.close()
    texts = [l["text"] for l in snap["labels"]]
    assert texts == ["visible"], texts


async def test_run_replay_lands_before_after_snapshots(client, monkeypatch):
    """T4 集成：run_replay 前后各采快照落 replay_run，after 反映注入值。"""
    import json as _json
    import app.replay.runner as rm
    from app.db import SessionLocal
    from app.models import ReplayRun

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.setenv("LLM_FAKE_RESPONSE",
                       _json.dumps({"name": "SaveForm", "description": "d"}))
    sid = (await client.post("/api/v1/sessions", json={})).json()["session_id"]
    events = [
        {"seq": 0, "ts": 0, "kind": "navigation", "payload": {"type": "page-load", "url": "http://mock.local/"}},
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
    aid = (await client.post("/api/v1/align",
                            json={"session_ids": [sid, sid]})).json()["alignment_id"]
    skill = (await client.post(f"/api/v1/alignments/{aid}/induce")).json()
    await client.post(f"/api/v1/skills/{skill['id']}/assertions")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.route("http://mock.local/", lambda route: route.fulfill(
            status=200, content_type="text/html; charset=utf-8", body=FORM_HTML))
        await page.goto("http://mock.local/")
        monkeypatch.setattr(rm, "_launch", lambda: _FakePW(page, browser))

        db = SessionLocal()
        try:
            run = await rm.run_replay(db, skill["id"], {"请输入": "注入值"}, True)
        finally:
            db.close()

    assert run.mode == "execute"
    assert run.executed is not None           # executed 保持步骤列表（消费方零破坏）
    plan_row = run.plan
    b_map = {f["label"]: f["value"] for f in plan_row["before_snapshot"]["forms"]}
    assert b_map.get("请输入") == ""                     # 执行前字段存在但为空
    after_forms = plan_row["after_snapshot"]["forms"]
    assert any(f["label"] == "请输入" and f["value"] == "注入值"
               for f in after_forms), after_forms


class _FakePW:
    """把 runner 的浏览器入口指到测试已备好的真实 page（表单页已 route+goto）。"""
    def __init__(self, page, browser):
        self._page, self._browser = page, browser

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def chromium_launch(self):
        return _FakeBrowser(self._page, self._browser)


class _FakeBrowser:
    def __init__(self, page, browser):
        self._page, self._browser = page, browser

    async def new_context(self, storage_state=None):
        return _FakeCtx(self._page)

    async def close(self):
        pass  # 生命周期由测试的 async with 管


class _FakeCtx:
    def __init__(self, page):
        self._page = page

    async def new_page(self):
        return self._page


async def test_locate_multi_label_fallback():
    """S36 多信号定位：首选 label 不存在时逐个尝试候选 labels
    （Frappe 等框架首选 placeholder 缺失、只有 data-fieldname）。"""
    from app.replay.locate import locate
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""
        <html><body>
          <input data-fieldname="customer_name" />
          <button id="b1">保存</button>
        </body></html>""")
        loc, strategy = await locate(page, "电话", labels=["customer_name"])
        assert await loc.get_attribute("data-fieldname") == "customer_name"
        assert strategy == "data-fieldname"
        await browser.close()


async def test_locate_structural_fallback():
    """S36 结构兜底：无任何属性的元素按 path+ordinal nth-of-type 定位
    （唯一命中才用，宁缺毋滥）。"""
    from app.replay.locate import locate
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""
        <html><body>
          <div><div><button>甲</button><button>乙</button><button>丙</button></div></div>
        </body></html>""")
        # 目标是第 2 个 button（乙），无任何属性
        loc, strategy = await locate(page, "不存在的标签", tag="button",
                                     ordinal=2, path="div>div>button")
        assert await loc.text_content() == "乙"
        assert strategy == "structural"
        await browser.close()


async def test_execute_plan_uses_label_fallback():
    """S36 端到端：步骤首选 label 定位失败时用候选 labels（data-fieldname）
    命中——多信号方案在执行器层生效。"""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""
        <html><body>
          <input data-fieldname="customer_name" />
          <button id="save-btn" data-fieldname="save_btn">Save</button>
        </body></html>""")
        plan = {"url": "about:blank", "steps": [
            {"kind": "input", "name": "不存在的名字", "value": "v1",
             "labels": ["customer_name"]},
            {"kind": "click", "label": "保存", "labels": ["save_btn"]},
        ]}
        result = await execute_plan(page, plan)
        await browser.close()
    assert [s["ok"] for s in result["executed"]] == [True, True]
    assert result["executed"][0]["strategy"] == "data-fieldname"


async def test_execute_plan_captures_transient_toast():
    """S37 断言语义根治：toast 瞬态（500ms 后消失）——settle 窗口内
    轮询捕获，after 快照时机必然错过但 observed_toasts 能拿到。"""
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("""
        <html><body>
          <button id="save">保存</button>
          <div class="toast" id="t" style="display:none">保存成功</div>
          <script>
            document.getElementById('save').addEventListener('click', () => {
              const t = document.getElementById('t');
              t.style.display = 'block';
              setTimeout(() => { t.style.display = 'none'; }, 600);
            });
          </script>
        </body></html>""")
        plan = {"url": "about:blank", "steps": [
            {"kind": "click", "label": "保存"},
        ]}
        result = await execute_plan(page, plan)
        await browser.close()
    assert result["executed"][0]["ok"] is True
    assert "保存成功" in result.get("observed_toasts", []), result.get("observed_toasts")
