"""s44 跟进：_plan_url 跳过 Dolibarr 提交后 __ID__ 重定向（实例占位段）。

矩阵实证（demo/sprint44）：Dolibarr 创建流录制的导航链 =
action=create → [fill+save 动作] → id=__ID__&socid=N（提交后重定向，
__ID__ 是 Dolibarr create 表单隐藏 id 占位）——旧逻辑取末条 navigation
→ plan url 带 __ID__ → 回放落视图态无表单。
修：末条含非数字 id= 参数（__ID__ 类占位）时回退前一条同 host 导航；
数字 id（编辑流锚）行为不变。
"""
from app.replay.plan import _plan_url


def _nav(url: str) -> dict:
    return {"kind": "navigation", "payload": {"url": url}}


def _act(url: str) -> dict:
    return {"kind": "action", "payload": {"type": "input", "url": url, "name": "n", "value": "v"}}


def test_doli_post_submit_idid_falls_back_to_create():
    events = [
        _nav("http://127.0.0.1:8080/societe/card.php?action=create"),
        _act("http://127.0.0.1:8080/societe/card.php?action=create"),
        _nav("http://127.0.0.1:8080/societe/card.php?id=__ID__&socid=42"),
    ]
    assert _plan_url(events) == "http://127.0.0.1:8080/societe/card.php?action=create"


def test_numeric_id_edit_flow_unchanged():
    # 真实编辑流形态：nav(list)→点行(act)→nav(card)→fill+save(act)
    # ——card 导航之后还有动作（在编辑页上操作）→ card 是动作时点页
    events = [
        _nav("http://127.0.0.1:8080/societe/list.php"),
        _act("http://127.0.0.1:8080/societe/card.php?id=16&socid=10"),
        _nav("http://127.0.0.1:8080/societe/card.php?id=16&socid=10"),
        _act("http://127.0.0.1:8080/societe/card.php?id=16&socid=10"),
    ]
    # 数字 id=16 是编辑流有效锚——仍取末条（动作发生时所在页）
    assert "id=16" in _plan_url(events)


def test_snipe_post_submit_nav_not_chosen():
    """Snipe 形态：create 表单 → [fill+save] → 提交后跳 /hardware/31 →
    （框架又回列表 /hardware）。回放锚必须是动作发生时的 URL
    （/hardware/create），非提交后导航——旧行为锚到列表页，
    回放第一步就落错页全 miss（s44 Snipe 0/6 实证）。"""
    events = [
        _nav("http://127.0.0.1:8081/hardware/create"),
        _act("http://127.0.0.1:8081/hardware/create"),
        _nav("http://127.0.0.1:8081/hardware/31"),
        _nav("http://127.0.0.1:8081/hardware"),
    ]
    assert _plan_url(events).endswith("/hardware/create")


def test_action_time_url_still_supports_nav_chain():
    """Frappe 形态不变：动作前的导航链（首页→表单页）仍取末条
    （动作时所在页）——首条动作前的导航才是有效锚。"""
    events = [
        _nav("http://h/app/home"),
        _nav("http://h/app/customer/new"),
        _act("http://h/app/customer/new"),
    ]
    assert _plan_url(events).endswith("/app/customer/new")


def test_doli_create_button_annotated():
    """s44 假 pass 实证（run 2890）：Dolibarr「创建合作方」input[submit]
    型保存步——经典表单提交无 fetch 证据（证据派生不命中）→ 词表兜底
    必须覆盖「创建」。"""
    from app.replay.plan import WRITE_SUB
    assert "创建" in WRITE_SUB
