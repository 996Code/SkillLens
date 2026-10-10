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
    events = [
        _nav("http://127.0.0.1:8080/societe/list.php"),
        _act("http://127.0.0.1:8080/societe/card.php?id=16&socid=10"),
        _nav("http://127.0.0.1:8080/societe/card.php?id=16&socid=10"),
    ]
    # 数字 id=16 是编辑流有效锚——仍取末条
    assert "id=16" in _plan_url(events)
