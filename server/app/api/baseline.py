"""演示基线指标 API（Task 5）：为 C2「真实流量置信度 ≥ 演示基线 80%」提供对比锚。

assertion_pass_rate 取该 skill 最近一条 assertion_results 非空的 replay_run 的
passed 比例（shadow/异常 run 的 assertion_results 为 NULL，不参与；无任何有效
run 时为 null——outcome_assertion 行不存历史，replay_run 是唯一可靠来源）。

S10 Task5 扩展：
- /baseline/skills 每项加 source（skill 对齐首个 session 的来源，缺省 demo）；
- 新增 GET /baseline/compare：demo vs real_traffic 聚合对比摘要（不动既有
  /baseline/skills 数组结构——scripts/baseline_snapshot.py 等消费方零破坏）。
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import Alignment, OutcomeAssertion, RecordingSession, ReplayRun, Skill

router = APIRouter()

# C2 达标线：真实流量归纳置信度 ≥ 演示基线 80%
C2_CONFIDENCE_RATIO = 0.8


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _latest_pass_rate(db: Session, skill_id: int) -> float | None:
    run = db.execute(
        select(ReplayRun).where(ReplayRun.skill_id == skill_id,
                                ReplayRun.assertion_results.is_not(None))
        .order_by(ReplayRun.id.desc()).limit(1)
    ).scalar_one_or_none()
    if run is None:
        return None
    results = run.assertion_results or []
    if not results:
        return None
    passed = sum(1 for r in results if r.get("passed"))
    return round(passed / len(results), 4)


def _session_sources(db: Session) -> dict[str, str]:
    """session_id -> source 映射（一次性载入，避免逐 skill 逐 session 查询）。"""
    return {sid: source for sid, source in db.execute(
        select(RecordingSession.id, RecordingSession.source)).all()}


def _skill_source(db: Session, skill: Skill,
                  sources: dict[str, str] | None = None) -> str:
    """skill 的来源：其 alignment 首个 session 的 source；查不到（含旧数据）默认 demo。"""
    sources = sources if sources is not None else _session_sources(db)
    if not skill.alignment_id:
        return "demo"
    alignment = db.get(Alignment, skill.alignment_id)
    session_ids = (alignment.session_ids or []) if alignment else []
    for sid in session_ids:
        if sid in sources:
            return sources[sid] or "demo"
    return "demo"


def _baseline_item(db: Session, skill: Skill,
                   sources: dict[str, str] | None = None) -> dict:
    assertion_count = db.query(OutcomeAssertion).filter(
        OutcomeAssertion.skill_id == skill.id).count()
    return {
        "skill_id": skill.id,
        "name": skill.name,
        "status": skill.status,
        "confidence": skill.confidence,
        "evidence_count": skill.evidence_count,
        "assertion_count": assertion_count,
        "assertion_pass_rate": _latest_pass_rate(db, skill.id),
        "input_var_names": [v.get("name") for v in skill.input_variables or []
                            if v.get("name")],
        "window_params": (db.get(Alignment, skill.alignment_id).window_params
                          if skill.alignment_id else None),
        "source": _skill_source(db, skill, sources),
    }


@router.get("/baseline/skills")
async def list_baseline_skills(db: Session = Depends(get_db)) -> list:
    sources = _session_sources(db)
    rows = db.query(Skill).order_by(Skill.id).all()
    return [_baseline_item(db, s, sources) for s in rows]


@router.get("/baseline/skills/{skill_id}")
async def get_baseline_skill(skill_id: int, db: Session = Depends(get_db)) -> dict:
    skill = db.get(Skill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="skill not found")
    return _baseline_item(db, skill)


def _avg(values: list[float]) -> float | None:
    """非空均值（round 4）；空列表 → None。"""
    return round(sum(values) / len(values), 4) if values else None


def _ratio(num: float | None, den: float | None) -> float | None:
    """num/den（round 4）；任一侧缺失或分母为 0 → None（不可比）。"""
    if num is None or den is None or den == 0:
        return None
    return round(num / den, 4)


@router.get("/baseline/compare")
async def compare_baseline(db: Session = Depends(get_db)) -> dict:
    """S10 Task5：demo vs real_traffic 聚合对比（C2 测量闭环的报告端点）。

    avg_pass_rate 只对有有效 replay_run 的 skill 求均值（无 run 侧为 None）；
    meets_c2 只看置信度比（宪法 C2 措辞），比率不可得（无 real 或 demo 分母为 0
    /为 None）时为 False——语义=「尚不能宣称达标」，而非「失败」。
    """
    sources = _session_sources(db)
    rows = db.query(Skill).order_by(Skill.id).all()
    groups: dict[str, list[dict]] = {"demo": [], "real_traffic": []}
    for s in rows:
        item = _baseline_item(db, s, sources)
        groups.setdefault(item["source"], []).append(item)

    def summarize(items: list[dict]) -> dict:
        rates = [i["assertion_pass_rate"] for i in items
                 if i["assertion_pass_rate"] is not None]
        return {
            "count": len(items),
            "avg_confidence": _avg([i["confidence"] for i in items]),
            "avg_pass_rate": _avg(rates),
        }

    demo = summarize(groups["demo"])
    real = summarize(groups["real_traffic"])
    confidence_ratio = _ratio(real["avg_confidence"], demo["avg_confidence"])
    return {
        "demo": demo,
        "real_traffic": real,
        "vs_baseline": {
            "confidence_ratio": confidence_ratio,
            "pass_rate_ratio": _ratio(real["avg_pass_rate"], demo["avg_pass_rate"]),
            "meets_c2": confidence_ratio is not None and confidence_ratio >= C2_CONFIDENCE_RATIO,
        },
    }
