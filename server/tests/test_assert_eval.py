from app.replay.assert_eval import evaluate_assertions, path_matches


def test_path_matches_templated():
    assert path_matches("http://h/orders/92382/save?x=1", "/orders/{id}/save") is True
    assert path_matches("http://h/orders/abc/save", "/orders/{id}/save") is False


def test_evaluate_api_status():
    assertions = [{"kind": "api_status", "payload": {"api_template": "/a/save", "expect_status": 200}}]
    observed = [{"url": "http://h/a/1/save", "status": 200, "body": ""},
                {"url": "http://h/other", "status": 500, "body": ""}]
    result = evaluate_assertions(assertions, observed)
    assert result[0]["passed"] is True and result[0]["observed_status"] == 200


def test_evaluate_api_status_missing():
    assertions = [{"kind": "api_status", "payload": {"api_template": "/a/save", "expect_status": 200}}]
    result = evaluate_assertions(assertions, [{"url": "http://h/b", "status": 200, "body": ""}])
    assert result[0]["passed"] is False and result[0]["observed_status"] is None


def test_evaluate_state_signal():
    assertions = [{"kind": "state_signal",
                   "payload": {"api_template": "/a/save", "field": "code", "expect_value": 200}}]
    observed = [{"url": "http://h/a/save", "status": 200, "body": '{"code":200,"data":{"state":"OK"}}'}]
    result = evaluate_assertions(assertions, observed)
    assert result[0]["passed"] is True


def test_state_signal_write_response_not_masked_by_page_load():
    """S42-12：写响应后同模板的页面加载（GET）不得污染终态判定——
    禅道实测：保存 POST 返回 result=success，随后 zin 页面加载（GET）
    响应体无 result 字段，"取最后一次匹配"把成功判定吃成失败。"""
    assertions = [{"kind": "state_signal",
                   "payload": {"api_template": "/index.php", "field": "result",
                               "expect_value": "success"}}]
    observed = [
        {"url": "http://h/index.php?m=project&f=create&zin=1", "status": 200,
         "method": "POST", "body": '{"result":"success","message":"保存成功"}'},
        {"url": "http://h/index.php?m=project&f=create&copyProjectID=47", "status": 200,
         "method": "GET", "body": '[{"name":"configJS","data":"<script>..."}]'},
    ]
    result = evaluate_assertions(assertions, observed)
    assert result[0]["passed"] is True, result[0]


def test_state_signal_write_failure_still_fails():
    """写响应本身失败（result=fail）时不得被后续 GET 掩盖成通过。"""
    assertions = [{"kind": "state_signal",
                   "payload": {"api_template": "/index.php", "field": "result",
                               "expect_value": "success"}}]
    observed = [
        {"url": "http://h/index.php?m=project&f=create&zin=1", "status": 200,
         "method": "POST", "body": '{"result":"fail","message":{"end":["不能为空"]}}'},
        {"url": "http://h/index.php?m=project&f=browse", "status": 200,
         "method": "GET", "body": '<html></html>'},
    ]
    result = evaluate_assertions(assertions, observed)
    assert result[0]["passed"] is False


def test_state_signal_no_method_falls_back_to_last():
    """旧格式 observed 无 method 字段——回退到原"最后一次匹配"语义。"""
    assertions = [{"kind": "state_signal",
                   "payload": {"api_template": "/a/save", "field": "code", "expect_value": 200}}]
    observed = [{"url": "http://h/a/save", "status": 200, "body": '{"code":200}'}]
    result = evaluate_assertions(assertions, observed)
    assert result[0]["passed"] is True


def _ui_text_payload():
    return {"label": "备注", "before": "旧值", "after": "新值"}


def _after_snapshot(value):
    return {"forms": [{"label": "备注", "value": value}], "labels": [], "tables": []}


def test_evaluate_ui_text_match():
    a = [{"kind": "ui_text", "payload": _ui_text_payload()}]
    r = evaluate_assertions(a, [], after_snapshot=_after_snapshot("新值"))
    assert r[0]["passed"] is True
    assert r[0]["observed_status"] is None


def test_evaluate_ui_text_mismatch():
    a = [{"kind": "ui_text", "payload": _ui_text_payload()}]
    r = evaluate_assertions(a, [], after_snapshot=_after_snapshot("别的值"))
    assert r[0]["passed"] is False


def test_evaluate_ui_text_no_snapshot_skipped():
    """回放无 after 快照（无采集能力）→ skipped（passed=True），不计失败。"""
    a = [{"kind": "ui_text", "payload": _ui_text_payload()}]
    r = evaluate_assertions(a, [])
    assert r[0]["passed"] is True
    assert r[0]["skipped"] == "ui_text 无回放快照，跳过"


def test_evaluate_ui_text_label_missing_fails():
    """快照存在但 label 缺失 → FAIL：字段消失是真实回归信号，不再吞掉。"""
    a = [{"kind": "ui_text", "payload": _ui_text_payload()}]
    r = evaluate_assertions(
        a, [], after_snapshot={"forms": [{"label": "其他", "value": "x"}],
                               "labels": [], "tables": []})
    assert r[0]["passed"] is False, r
    assert r[0]["skipped"] == "回放快照中字段缺失"


def test_evaluate_ui_text_label_missing_with_write_skipped():
    """S42-12：字段缺失但写响应已发生（表单被提交消费/页面导航离开）——
    字段消失是流程完成的预期结果（禅道 Bug 创建 picker 值由 click 步
    执行、提交后表单整体消失），记录不判定。"""
    a = [{"kind": "ui_text", "payload": _ui_text_payload()}]
    r = evaluate_assertions(
        a, [{"url": "http://h/x/save", "status": 200, "method": "POST", "body": ""}],
        after_snapshot={"forms": [{"label": "搜索", "value": ""}],
                        "labels": [], "tables": []})
    assert r[0]["passed"] is True, r
    assert "提交" in r[0]["skipped"]


def test_evaluate_toast_signal_from_snapshot():
    """层1 toast 断言走 after 快照 toasts 通道（不走响应体）。"""
    from app.replay.assert_eval import evaluate_assertions
    assertions = [{"kind": "state_signal",
                    "payload": {"api_template": "/x/save", "field": "toast",
                                "expect_value": "保存成功"}}]
    # 快照含目标 toast → PASS
    r = evaluate_assertions(assertions, [{"url": "http://t/x/save", "status": 200, "body": ""}],
                            after_snapshot={"toasts": ["保存成功"]})
    assert r[0]["passed"] is True
    # 快照无该 toast → skipped（S37 语义修正：toast 瞬态，未捕获不判失败）
    r2 = evaluate_assertions(assertions, [{"url": "http://t/x/save", "status": 200, "body": ""}],
                             after_snapshot={"toasts": ["别的提示"]})
    assert r2[0]["passed"] is True and r2[0].get("skipped")
    # 无快照能力 → skipped（fail-open，不计失败）
    r3 = evaluate_assertions(assertions, [{"url": "http://t/x/save", "status": 200, "body": ""}],
                              after_snapshot=None)
    assert r3[0]["passed"] is True and r3[0].get("skipped")


def test_evaluate_toast_with_observed_toasts_channel():
    """S37 断言语义根治：toast 是瞬态元素，after 快照时机必然错过——
    回放期间轮询捕获的 toasts（observed_toasts）参与判定；
    两个通道都未观察到 → skipped（瞬态性本质，不产生假阴性）。"""
    assertions = [{"kind": "state_signal",
                   "payload": {"api_template": "/x/save", "field": "toast",
                               "expect_value": "保存成功"}}]
    observed = [{"url": "http://t/x/save", "status": 200, "body": ""}]
    # 轮询通道捕获到（快照错过）→ PASS
    r = evaluate_assertions(assertions, observed,
                            after_snapshot={"toasts": []},
                            observed_toasts=["保存成功"])
    assert r[0]["passed"] is True
    # 两通道都空 → skipped 而非 fail
    r2 = evaluate_assertions(assertions, observed,
                             after_snapshot={"toasts": []},
                             observed_toasts=[])
    assert r2[0]["passed"] is True
    assert "瞬态" in r2[0].get("skipped", "")
    # 快照通道命中（兼容旧路径）→ PASS
    r3 = evaluate_assertions(assertions, observed,
                             after_snapshot={"toasts": ["保存成功"]},
                             observed_toasts=[])
    assert r3[0]["passed"] is True


def test_state_signal_row_context_recorded_not_judged():
    """S42 业务测试发现（若依岗位修改）：GET /{id} 的行属性（如 status）
    是行上下文——回放命中的行与录制行不同（首行受保护 disabled，
    定位选首个 enabled），期望值天然漂移。此类断言记录不判定
    （与 S37-1 视觉动态数据同哲学）。"""
    assertions = [{"kind": "state_signal",
                   "payload": {"api_template": "/prod-api/system/post/{id}",
                               "field": "data.status", "expect_value": "0",
                               "context": True}}]
    observed = [{"url": "http://t/prod-api/system/post/9", "status": 200,
                 "body": '{"code":200,"data":{"status":"1"}}'}]
    r = evaluate_assertions(assertions, observed, after_snapshot={})
    assert r[0]["passed"] is True
    assert "上下文" in r[0].get("skipped", "")


def test_state_signal_effect_still_judged():
    """非 context 标记的 state_signal（写响应/集合读取）仍严格判定。"""
    assertions = [{"kind": "state_signal",
                   "payload": {"api_template": "/x/save", "field": "code",
                               "expect_value": 200}}]
    observed = [{"url": "http://t/x/save", "status": 200,
                 "body": '{"code":500}'}]
    r = evaluate_assertions(assertions, observed, after_snapshot={})
    assert r[0]["passed"] is False


def test_ui_text_field_consumed_by_submit_skipped():
    """S42 业务测试发现：对话框表单提交后字段随对话框关闭——
    input 步执行成功（字段存在且已填）+ after 快照字段缺失
    → 字段被提交消费，非回归信号。"""
    assertions = [{"kind": "ui_text",
                   "payload": {"label": "请输入岗位名称", "before": "",
                               "after": "回放值"}}]
    observed = []
    executed = [{"kind": "input", "name": "请输入岗位名称", "value": "回放值", "ok": True},
                {"kind": "click", "label": "确 定", "ok": True}]
    r = evaluate_assertions(assertions, observed,
                            after_snapshot={"forms": []},
                            executed_steps=executed)
    assert r[0]["passed"] is True
    assert "提交" in r[0].get("skipped", "")


def test_ui_text_label_missing_without_input_step_still_fails():
    """无对应 input 步的字段缺失仍是回归信号（表单未打开等）。"""
    assertions = [{"kind": "ui_text",
                   "payload": {"label": "请输入岗位名称", "before": "",
                               "after": "x"}}]
    observed = []
    executed = [{"kind": "click", "label": "确 定", "ok": True}]
    r = evaluate_assertions(assertions, observed,
                            after_snapshot={"forms": []},
                            executed_steps=executed)
    assert r[0]["passed"] is False


def test_ui_text_label_collision_filled_by_input_step():
    """S42 业务测试发现：搜索框与对话框字段同 label（placeholder 相同），
    after 快照命中的是搜索框（值空）。input 步已按期望值填入且 ok
    → 值的设置有执行证据 → 记录不判定。"""
    assertions = [{"kind": "ui_text",
                   "payload": {"label": "请输入岗位名称", "before": "",
                               "after": "回放值"}}]
    executed = [{"kind": "input", "name": "请输入岗位名称", "value": "回放值", "ok": True},
                {"kind": "click", "label": "确 定", "ok": True}]
    # after 快照的 forms 命中同 label 的搜索框（值空）
    r = evaluate_assertions(assertions, [],
                            after_snapshot={"forms": [{"label": "请输入岗位名称", "value": ""}]},
                            executed_steps=executed)
    assert r[0]["passed"] is True
    assert "input 步" in r[0].get("skipped", "")


def test_ui_text_value_mismatch_without_fill_evidence_fails():
    """无 input 步执行证据的值不符仍 FAIL（真实回归信号）。"""
    assertions = [{"kind": "ui_text",
                   "payload": {"label": "状态", "before": "草稿", "after": "已保存"}}]
    r = evaluate_assertions(assertions, [],
                            after_snapshot={"forms": [{"label": "状态", "value": "草稿"}]},
                            executed_steps=[{"kind": "click", "label": "保存", "ok": True}])
    assert r[0]["passed"] is False


def test_api_status_method_filter():
    """经典表单系统（Dolibarr 实证）：GET 页面加载与 POST 提交共享路径
    （query 忽略）——payload 带 method 时只按同方法命中判定，GET 200
    不稀释 POST 302 的期望；无 method 保持旧语义（全命中比对）。"""
    from app.replay.assert_eval import evaluate_assertions
    observed = [
        {"url": "http://h/societe/card.php?action=create", "status": 200,
         "method": "GET", "body": ""},
        {"url": "http://h/societe/card.php?action=create", "status": 302,
         "method": "POST", "body": ""},
    ]
    a = [{"kind": "api_status",
          "payload": {"api_template": "/societe/card.php", "expect_status": 302,
                      "method": "POST"}}]
    r = evaluate_assertions(a, observed)
    assert r[0]["passed"] is True
    assert r[0]["observed_status"] == 302
    # 无 method：全命中比对（旧语义）——GET 200 与 POST 302 并存判 fail
    a_old = [{"kind": "api_status",
              "payload": {"api_template": "/societe/card.php",
                          "expect_status": 302}}]
    r_old = evaluate_assertions(a_old, observed)
    assert r_old[0]["passed"] is False
    # 带方法但写请求缺失（提交被拦）→ fail（真实回归信号）
    a_miss = [{"kind": "api_status",
               "payload": {"api_template": "/societe/card.php",
                           "expect_status": 302, "method": "POST"}}]
    r_miss = evaluate_assertions(a_miss, observed[:1])
    assert r_miss[0]["passed"] is False
