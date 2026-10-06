"""S38 目标系统维度：从操作流程的参考会话首条 navigation URL 派生系统。

用户视角：测试产物按目标系统分组（njmind/Odoo/Dolibarr/ERPNext…），
不再全部平铺。派生是确定性的（host 映射表 + 兜底 host 本身），
不引入新表——URL 是既有证据（C3）。
"""
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alignment, RawEvent, Skill

# 已知部署的 host → 系统名（新系统自动兜底为 host 本身）
HOST_SYSTEM = {
    "192.168.99.22": "njmind 内网",
    "127.0.0.1:8069": "Odoo 销售",
    "127.0.0.1:8080": "Dolibarr 订单",
    "127.0.0.1:8090": "ERPNext 客户",
    "127.0.0.1:8081": "Snipe 资产",
    "127.0.0.1:8082": "禅道项目",
    "127.0.0.1:8093": "若依权限",
    "127.0.0.1:8095": "JeecG 表单",
}


def system_label(host: str) -> str:
    if not host:
        return "未知系统"
    return HOST_SYSTEM.get(host, host)


def _session_hosts(db: Session, session_ids: set[str] | None = None) -> dict[str, str]:
    """session_id → 首条 navigation 的 host（一次查询批量派生）。
    S42：给定 session_ids 时只查相关行——全表 navigation 扫描是
    list_suites 等列表端点的 N+1 放大器。"""
    nav: dict[str, str] = {}
    q = select(RawEvent.session_id, RawEvent.payload).where(RawEvent.kind == "navigation")
    if session_ids is not None:
        if not session_ids:
            return nav
        q = q.where(RawEvent.session_id.in_(session_ids))
    rows = db.execute(q.order_by(RawEvent.ts, RawEvent.seq)).all()
    for sid, payload in rows:
        if sid not in nav:
            url = (payload or {}).get("url", "")
            nav[sid] = urlparse(url).netloc if url else ""
    return nav


def skill_systems(db: Session, skill_ids: list[int] | None = None) -> dict[int, str]:
    """skill_id → 目标系统名（活跃 skill 批量派生）。
    S42：可选 skill_ids 过滤——列表端点按需派生，不再全表扫描。"""
    q = db.query(Skill.id, Skill.alignment_id).filter(Skill.status != "superseded")
    if skill_ids is not None:
        if not skill_ids:
            return {}
        q = q.filter(Skill.id.in_(skill_ids))
    skills = q.all()
    if not skills:
        return {}
    aligns = {a.id: (a.session_ids or [])
              for a in db.query(Alignment.id, Alignment.session_ids).filter(
                  Alignment.id.in_({s.alignment_id for s in skills})).all()}
    ref_sids = {(a or [""])[0] for a in aligns.values() if a}
    nav = _session_hosts(db, ref_sids)
    return {s.id: system_label(nav.get((aligns.get(s.alignment_id) or [""])[0], ""))
            for s in skills}


def session_systems(db: Session, session_ids: list[str]) -> dict[str, str]:
    """S42：批量版 session_system——时间线 recording 行逐条查询的 N+1 修复。"""
    hosts = _session_hosts(db, set(session_ids))
    return {sid: system_label(h) for sid, h in hosts.items()}


def session_system(db: Session, session_id: str) -> str:
    """单会话的目标系统名（时间线 recording 行用）。"""
    row = db.execute(
        select(RawEvent.payload).where(RawEvent.kind == "navigation",
                                       RawEvent.session_id == session_id)
        .order_by(RawEvent.ts, RawEvent.seq).limit(1)).first()
    url = ((row[0] if row else None) or {}).get("url", "")
    return system_label(urlparse(url).netloc if url else "")
