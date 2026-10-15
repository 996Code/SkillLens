"""AR1 legacy TestSuite → Scenario 确定性迁移规则。"""
from app.scenario.migration import classify_suite_definition


def test_same_system_suite_reuses_exact_simple_scenario():
    decision = classify_suite_definition(
        suite_skill_ids=[3, 7],
        skill_systems={3: "JeecG 表单", 7: "JeecG 表单"},
        scenarios=[
            {"id": 11, "system": "JeecG 表单", "steps": [
                {"skill_id": 3, "overrides": {}},
                {"skill_id": 7, "overrides": {}},
            ]},
        ],
    )
    assert decision.kind == "reuse"
    assert decision.scenario_id == 11
    assert decision.system == "JeecG 表单"


def test_same_system_suite_does_not_dedupe_non_simple_scenario():
    decision = classify_suite_definition(
        suite_skill_ids=[3, 7],
        skill_systems={3: "JeecG 表单", 7: "JeecG 表单"},
        scenarios=[
            {"id": 11, "system": "JeecG 表单", "steps": [
                {"skill_id": 3, "overrides": {"name": "x"}},
                {"skill_id": 7, "overrides": {}},
            ]},
        ],
    )
    assert decision.kind == "create"
    assert decision.scenario_id is None


def test_mixed_system_suite_stays_legacy():
    decision = classify_suite_definition(
        suite_skill_ids=[1, 2],
        skill_systems={1: "Odoo 销售", 2: "ERPNext 客户"},
        scenarios=[],
    )
    assert decision.kind == "legacy_mixed_system"
    assert decision.scenario_id is None
    assert "ERPNext 客户" in decision.reason
    assert "Odoo 销售" in decision.reason


def test_unknown_system_suite_stays_legacy():
    decision = classify_suite_definition(
        suite_skill_ids=[1],
        skill_systems={1: "未知系统"},
        scenarios=[],
    )
    assert decision.kind == "legacy_unknown_system"
