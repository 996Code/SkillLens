"""Deterministic legacy TestSuite → Scenario migration decisions."""
from dataclasses import dataclass
from typing import Literal


MigrationKind = Literal[
    "reuse", "create", "legacy_mixed_system", "legacy_unknown_system"
]


@dataclass(frozen=True)
class SuiteMigrationDecision:
    kind: MigrationKind
    system: str | None
    scenario_id: int | None = None
    reason: str = ""


def _is_simple_skill_sequence(steps: list, skill_ids: list[int]) -> bool:
    if len(steps) != len(skill_ids):
        return False
    for step, skill_id in zip(steps, skill_ids):
        if step.get("skill_id") != skill_id:
            return False
        if step.get("scenario_id") is not None:
            return False
        if step.get("overrides"):
            return False
        if step.get("setup"):
            return False
        if step.get("enabled", True) is False:
            return False
        if step.get("cleanup"):
            return False
        if step.get("row_anchor_from") is not None:
            return False
    return True


def classify_suite_definition(
    *,
    suite_skill_ids: list[int],
    skill_systems: dict[int, str],
    scenarios: list[dict],
) -> SuiteMigrationDecision:
    systems = {skill_systems.get(skill_id, "未知系统")
               for skill_id in suite_skill_ids}
    if not systems or "未知系统" in systems:
        return SuiteMigrationDecision(
            kind="legacy_unknown_system",
            system=None,
            reason="技能系统无法确定",
        )
    if len(systems) != 1:
        names = "、".join(sorted(systems))
        return SuiteMigrationDecision(
            kind="legacy_mixed_system",
            system=None,
            reason=f"混合系统套件：{names}",
        )

    system = next(iter(systems))
    for scenario in scenarios:
        if scenario.get("system") != system:
            continue
        if _is_simple_skill_sequence(scenario.get("steps") or [], suite_skill_ids):
            return SuiteMigrationDecision(
                kind="reuse", system=system,
                scenario_id=int(scenario["id"]),
                reason="有序 Skill 序列与简单场景完全一致",
            )
    return SuiteMigrationDecision(
        kind="create", system=system,
        reason="同系统套件转换为 legacy_suite 场景",
    )
