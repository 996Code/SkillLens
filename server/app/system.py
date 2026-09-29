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
    "192.168.99.22": "njmind",
    "127.0.0.1:8069": "Odoo",
    "127.0.0.1:8080": "Dolibarr",
    "127.0.0.1:8090": "ERPNext",
}


def system_label(host: str) -> str:
    if not host:
        return "未知系统"
    return HOST_SYSTEM.get(host, host)


def _session_hosts(db: Session) -> dict[str, str]:
    """session_id → 首条 navigation 的 host（一次查询批量派生）。"""
    nav: dict[str, str] = {}
    rows = db.execute(
        select(RawEvent.session_id, RawEvent.payload).where(RawEvent.kind == "navigation")
        .order_by(RawEvent.ts, RawEvent.seq)).all()
    for sid, payload in rows:
        if sid not in nav:
            url = (payload or {}).get("url", "")
            nav[sid] = urlparse(url).netloc if url else ""
    return nav


def skill_systems(db: Session) -> dict[int, str]:
    """skill_id → 目标系统名（活跃 skill 批量派生）。"""
    nav = _session_hosts(db)
    aligns = {a.id: (a.session_ids or [])
              for a in db.query(Alignment.id, Alignment.session_ids).all()}
    out: dict[int, str] = {}
    for s in db.query(Skill.id, Skill.alignment_id).filter(
            Skill.status != "superseded").all():
        ref = (aligns.get(s.alignment_id) or [""])[0]
        out[s.id] = system_label(nav.get(ref, ""))
    return out


def session_system(db: Session, session_id: str) -> str:
    """单会话的目标系统名（时间线 recording 行用）。"""
    row = db.execute(
        select(RawEvent.payload).where(RawEvent.kind == "navigation",
                                       RawEvent.session_id == session_id)
        .order_by(RawEvent.ts, RawEvent.seq).limit(1)).first()
    url = ((row[0] if row else None) or {}).get("url", "")
    return system_label(urlparse(url).netloc if url else "")
