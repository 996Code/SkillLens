"""S38 目标系统维度：从操作流程的参考会话首条 navigation URL 派生系统。

用户视角：测试产物按目标系统分组（njmind/Odoo/Dolibarr/ERPNext…），
不再全部平铺。派生是确定性的（host 映射表 + 兜底 host 本身），
不引入新表——URL 是既有证据（C3）。

防再生③：HOST_SYSTEM/SYSTEM_ADAPTER 从 adapters/*.yaml 的 system_label
+base_url 生成（单一事实源）——新系统零代码接入即有系统名，不再两处
映射漂移（firefly 8096 曾漏配实证）。njmind host 经 env 注入（内网拓扑
不入库）。
"""
import os
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Alignment, RawEvent, Skill


def _maps_from_adapters() -> tuple[dict[str, str], dict[str, str]]:
    """adapters/*.yaml → (HOST_SYSTEM, SYSTEM_ADAPTER)。yaml 读失败
    fail-open 返回空映射（系统名兜底 host 本身，不阻塞主流程）。"""
    host_map: dict[str, str] = {}
    sys_adapter: dict[str, str] = {}
    try:
        from app.adapters.manifest import load_adapter_dir
        ms, _ = load_adapter_dir(Path("adapters"))
        for m in ms:
            if not m.system_label:
                continue
            host = urlparse(m.target.base_url).netloc
            if host:
                host_map[host] = m.system_label
                sys_adapter[m.system_label] = m.id
    except Exception:
        pass
    return host_map, sys_adapter


_ADAPTER_HOSTS, _ADAPTER_SYSTEMS = _maps_from_adapters()

HOST_SYSTEM = {
    **_ADAPTER_HOSTS,
    **({os.environ["NJMIND_HOST"]: "njmind 内网"}
      if os.environ.get("NJMIND_HOST") else {}),
}


def system_label(host: str) -> str:
    if not host:
        return "未知系统"
    return HOST_SYSTEM.get(host, host)


# 系统名 → 适配器清单 id（server/adapters/*.yaml）。URL 通配符未命中时的
# 兜底配对通道——与 HOST_SYSTEM 同源（yaml system_label 生成）
SYSTEM_ADAPTER = {
    **_ADAPTER_SYSTEMS,
    "njmind 内网": "njmind",
}


def _session_hosts(db: Session, session_ids: set[str] | None = None) -> dict[str, str]:
    """session_id → 首条 navigation 的 host（一次查询批量派生）。
    S42：给定 session_ids 时只查相关行——全表 navigation 扫描是
    list_suites 等列表端点的 N+1 放大器。
    归因报告（2026-10-09）：105/875 会话零 navigation（SPA/iframe 录制窗口
    无整页加载——禅道 about:blank iframe、Odoo hash 路由）。兜底链：
    navigation 缺失时取首条 action 事件的 payload.url（纯确定性）。
    17 个"未知系统"技能由此归位（禅道 6+Odoo 11）。"""
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
    # 兜底：无 navigation 的会话取首条 action 的 url host（确定性派生）
    missing = {sid for sid in ref_sids if sid not in nav}
    if missing:
        q2 = select(RawEvent.session_id, RawEvent.payload).where(
            RawEvent.kind == "action",
            RawEvent.session_id.in_(missing))
        for sid, payload in db.execute(
                q2.order_by(RawEvent.ts, RawEvent.seq)).all():
            if sid in nav:
                continue
            u = str((payload or {}).get("url") or "")
            if u.startswith("http"):
                try:
                    from urllib.parse import urlparse as _up
                    nav[sid] = _up(u).netloc
                except Exception:
                    pass
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
