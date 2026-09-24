from app.replay.plan import compile_replay_plan, compile_skeleton_plan, requires_confirmation


def ev(kind, ptype=None, **payload):
    return {"seq": 0, "ts": 0, "kind": kind,
            "payload": {"type": ptype, **payload} if ptype else payload}


EVENTS = [
    ev("navigation", "page-load", url="http://t/form"),
    ev("action", "click", target={"label": "请输入"}),
    ev("action", "input", name="请输入", value="旧值"),
    ev("action", "click", target={"label": ""}),          # 空 label 丢弃
    ev("action", "click", target={"label": "保存"}),
]


def test_compile_clicks_and_inputs():
    plan = compile_replay_plan(EVENTS, {})
    assert plan["url"] == "http://t/form"
    assert plan["steps"] == [
        {"kind": "click", "label": "请输入"},
        {"kind": "input", "name": "请输入", "value": "旧值", "original_value": "旧值"},
        {"kind": "click", "label": "保存"},
    ]


def test_compile_override_injects_value():
    plan = compile_replay_plan(EVENTS, {"请输入": "新值888"})
    step = plan["steps"][1]
    assert step["value"] == "新值888" and step["original_value"] == "旧值"


def test_requires_confirmation_on_post():
    assert requires_confirmation([{"signature": "click:保存|POST:/a/save"}]) is True
    assert requires_confirmation([{"signature": "click:查"}]) is False
    assert requires_confirmation([]) is False


def test_requires_confirmation_on_write_methods():
    # PUT/PATCH/DELETE 同为副作用方法，未确认一律影子（C1 本意，非仅 POST）
    assert requires_confirmation([{"signature": "click:改|PUT:/a/1"}]) is True
    assert requires_confirmation([{"signature": "click:改|PATCH:/a/1"}]) is True
    assert requires_confirmation([{"signature": "click:删|DELETE:/a/1"}]) is True
    # GET 查询无副作用，不需确认
    assert requires_confirmation([{"signature": "click:查|GET:/a/1"}]) is False


def test_url_fallback_from_action_event():
    events = [
        ev("action", "click", target={"label": "保存"}, url="http://t/from-action"),
    ]
    assert compile_replay_plan(events, {})["url"] == "http://t/from-action"


def test_url_prefers_navigation_over_action():
    events = [
        ev("navigation", "page-load", url="http://t/nav"),
        ev("action", "click", target={"label": "x"}, url="http://t/other"),
    ]
    assert compile_replay_plan(events, {})["url"] == "http://t/nav"


def _win(anchor_label, wq):
    return {"signature": f"click:{anchor_label}", "session_window_seqs": {"s1": wq}}


EVENTS_SKELETON = [
    ev("navigation", "page-load", url="http://t/form"),
    ev("action", "input", name="字段A", value="old"),
    ev("action", "click", target={"label": "打开"}),
    ev("action", "click", target={"label": "保存"}),
    ev("action", "click", target={"label": "多余操作"}),   # 非骨架步，不得进入计划
]


def test_skeleton_plan_only_skeleton_steps():
    skeleton = [_win("打开", 0), _win("保存", 1)]
    plan = compile_skeleton_plan(EVENTS_SKELETON, skeleton, "s1", {},
                                 [{"name": "字段A", "values": {"s1": "old"}}])
    kinds = [(s["kind"], s.get("label") or s.get("name")) for s in plan["steps"]]
    assert kinds == [("input", "字段A"), ("click", "打开"), ("click", "保存")]
    assert "多余操作" not in str(plan["steps"])


def test_skeleton_plan_override_value():
    skeleton = [_win("保存", 0)]
    plan = compile_skeleton_plan(EVENTS_SKELETON, skeleton, "s1", {"字段A": "new"},
                                 [{"name": "字段A", "values": {"s1": "old"}}])
    assert plan["steps"][0]["value"] == "new" and plan["steps"][0]["original_value"] == "old"
