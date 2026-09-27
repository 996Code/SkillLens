"""S24 块 U：定位修复提案——LLM 只提案，确定性验证（locate 实测）后才生效。

- load_repair_map：verified/promoted 提案 → 回放 fallback 映射；
- generate_proposals：定位失败后（页面还开着）采快照 → LLM 提案 → locate 实测；
- record_usage：自愈成功计数，verify_count ≥ LOCATE_AUTO_PROMOTE_N 自动晋升。
"""
import json

from sqlalchemy.orm import Session

from app.llm.gateway import complete
from app.models import LocateProposal
from app.replay.locate import locate
from app.replay.page_snapshot import collect_page_snapshot

ACTIVE_STATUSES = ("verified", "promoted")


def load_repair_map(db: Session, skill_id: int) -> dict[str, dict]:
    """{step_label: {"label": proposed_label, "id": proposal_id}}——仅活跃提案。"""
    rows = db.query(LocateProposal).filter(
        LocateProposal.skill_id == skill_id,
        LocateProposal.status.in_(ACTIVE_STATUSES)).all()
    return {r.step_label: {"label": r.proposed_label, "id": r.id} for r in rows}


async def generate_proposals(db: Session, page, skill_id: int,
                             failed_labels: list[str]) -> list[LocateProposal]:
    """定位失败标签逐个提案：LLM 从页面可见元素选新标签 → locate 实测验证。

    同 skill+step_label 已有活跃提案（却仍失败）→ 跳过（提案已失效，重生成无意义）。
    LLM 输出为空/等于原标签/验证失败 → 停留 proposed（不参与回放）。
    """
    created: list[LocateProposal] = []
    for label in failed_labels:
        existing = db.query(LocateProposal).filter(
            LocateProposal.skill_id == skill_id,
            LocateProposal.step_label == label,
            LocateProposal.status.in_(ACTIVE_STATUSES)).first()
        if existing is not None:
            continue
        snap = await collect_page_snapshot(page, phase="repair")
        texts = [l["text"] for l in snap.get("labels", [])]
        forms = [f["label"] for f in snap.get("forms", []) if f.get("label")]
        prompt = (
            f"自动化回放中按钮定位失败。原标签：{label}\n"
            f"当前页面可见文本元素：{json.dumps(texts + forms, ensure_ascii=False)}\n"
            "从上述元素中选出最可能对应同一操作的新标签，"
            "只输出标签文本本身，不要任何解释。"
        )
        result = complete(db, "locate_repair", prompt)
        proposed = (result.text or "").strip().strip('"').splitlines()[0].strip()[:100]
        if not proposed or proposed == label:
            continue
        status = "proposed"
        strategy = ""
        try:
            _, strategy = await locate(page, proposed)
            status = "verified"
        except Exception:
            pass  # 确定性验证未命中 → 停留 proposed
        row = LocateProposal(skill_id=skill_id, step_label=label,
                             proposed_label=proposed, strategy=strategy,
                             status=status)
        db.add(row)
        db.commit()
        db.refresh(row)
        created.append(row)
    return created


def record_usage(db: Session, proposal_ids: list[int]) -> None:
    """自愈成功计数；verified 且 verify_count ≥ N → 自动晋升 promoted。

    N 调用时读 env（LOCATE_AUTO_PROMOTE_N，默认 3）——可测试可配置。
    """
    import os
    n = int(os.environ.get("LOCATE_AUTO_PROMOTE_N", "3"))
    for pid in proposal_ids:
        row = db.get(LocateProposal, pid)
        if row is None or row.status not in ACTIVE_STATUSES:
            continue
        row.verify_count += 1
        if row.status == "verified" and row.verify_count >= n:
            row.status = "promoted"
    db.commit()
