"""S12 N1：新功能增量发现（process 管道发现步）。

语义（v1 纯确定性，不调 LLM——命名留给后续 induce）：
- 收集会话全部 api_calls 模板 + 锚点 labels，与 known_templates
  （调用方传 evidence_edge.dst 全局集合）差分；已知者跳过；
- 新模板 upsert：同 api_template 已存在 → observed_count+1（跨会话累加），
  不存在 → 插入 status=new；新锚点 label 同理（api_template 为空的行 = 纯 UI 发现）；
- 幂等：session_id 记录最近一次贡献的会话，同会话重 process 跳过累加
  （"同会话重跑不重复计数，跨会话累加"；A→B→重跑 A 会再计一次，v1 已知简化）。

纯函数（collect_candidates/is_known）与 db 操作（sync_discoveries）分离。
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DiscoveredFeature


def collect_candidates(semantic_actions: list[dict]) -> list[dict]:
    """从 semantic_actions 收集发现候选（去重，保序）。

    输入行形状同 process 落库字段：{"anchor_type", "target", "api_calls"}。
    输出：[{"kind": "api", "method": "POST", "value": 模板},
           {"kind": "anchor", "method": "click", "value": label}]。
    """
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def _add(kind: str, method: str, value: str) -> None:
        key = (kind, value)
        if value and key not in seen:
            seen.add(key)
            out.append({"kind": kind, "method": method, "value": value})

    for sa in semantic_actions:
        for call in sa.get("api_calls") or []:
            _add("api", str(call.get("method") or ""), str(call.get("template") or ""))
        label = str(((sa.get("target") or {}).get("label")) or "")
        _add("anchor", str(sa.get("anchor_type") or ""), label)
    return out


def is_known(candidate: dict, known_templates: set[str]) -> bool:
    """已知判定：裸值或 "type:值" 签名任一命中即已知。

    evidence_edge.dst 的 action 边是 "click:保存"、calls 边是 "POST:/x" 格式，
    而候选的裸值是 label / API 路径模板——两种形态都算已知。
    """
    value = candidate["value"]
    return value in known_templates or f"{candidate['method']}:{value}" in known_templates


def _find_row(db: Session, candidate: dict) -> DiscoveredFeature | None:
    if candidate["kind"] == "api":
        return db.execute(
            select(DiscoveredFeature).where(DiscoveredFeature.api_template == candidate["value"])
        ).scalar_one_or_none()
    # 纯 UI 发现：api_template 为空的行按 anchor_label 匹配
    return db.execute(
        select(DiscoveredFeature).where(DiscoveredFeature.anchor_label == candidate["value"],
                                        DiscoveredFeature.api_template.is_(None))
    ).scalar_one_or_none()


def sync_discoveries(db: Session, session_id: str, semantic_actions: list[dict],
                     known_templates: set[str]) -> list[dict]:
    """差分 + upsert，返回新增/更新摘要 [{"action": added|updated, "kind", "value"}]。"""
    summary: list[dict] = []
    now = datetime.now(timezone.utc)
    for cand in collect_candidates(semantic_actions):
        if is_known(cand, known_templates):
            continue
        row = _find_row(db, cand)
        if row is None:
            db.add(DiscoveredFeature(
                session_id=session_id,
                api_template=cand["value"] if cand["kind"] == "api" else None,
                anchor_label=cand["value"] if cand["kind"] == "anchor" else None,
                observed_count=1, first_seen=now, last_seen=now, status="new"))
            summary.append({"action": "added", "kind": cand["kind"], "value": cand["value"]})
        elif row.session_id == session_id:
            continue  # 同会话重跑：已贡献过，跳过（幂等）
        else:
            row.observed_count += 1
            row.last_seen = now
            row.session_id = session_id  # 记录最近贡献会话，供同会话幂等判定
            summary.append({"action": "updated", "kind": cand["kind"], "value": cand["value"]})
    db.commit()
    return summary
