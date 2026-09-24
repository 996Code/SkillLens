from app.replay.plan import compile_replay_plan, requires_confirmation


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
