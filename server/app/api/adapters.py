"""AF6 清单管理 API：工作台读/校验/保存 adapters/*.yaml（向导后端）。

- GET  /adapters → 清单摘要列表（含 lint）
- POST /adapters/validate → YAML 校验（不落盘，向导实时反馈）
- PUT  /adapters/{id} → 保存（校验通过才写盘）
"""
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.adapters.manifest import load_manifest_text, load_adapter_dir
from app.db import SessionLocal

router = APIRouter()

ADAPTERS_DIR = Path(__file__).resolve().parents[3] / "server" / "adapters"

# 安全红线：adapter_id 直接拼文件路径——白名单字符校验防 `..`/盘符穿越
# （GET 可任意读盘、PUT 可任意写盘的越权面）
def _check_adapter_id(adapter_id: str) -> None:
    import re
    if not re.fullmatch(r"[A-Za-z0-9_-]+", adapter_id):
        raise HTTPException(422, "adapter_id 仅允许字母/数字/下划线/连字符")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/adapters")
async def list_adapters(db: Session = Depends(get_db)) -> list:
    manifests, lints = load_adapter_dir(ADAPTERS_DIR)
    lint_map: dict[str, list] = {}
    for l in lints:
        lint_map.setdefault(l.file, []).append(l.message)
    out = []
    for m in manifests:
        out.append({
            "id": m.id, "label": m.label or m.id,
            "base_url": m.target.base_url,
            "has_login": m.login is not None,
            "probe_count": len(m.probes),
            "flow_count": len(m.flows or []),
            "chain_count": len(m.chains),
            "lints": lint_map.get(f"{m.id}.yaml", []),
        })
    return out


class ValidateRequest(BaseModel):
    yaml: str


@router.post("/adapters/validate")
async def validate_adapter(body: ValidateRequest,
                           db: Session = Depends(get_db)) -> dict:
    try:
        _, lints = load_manifest_text(body.yaml)
        return {"valid": True, "lints": [l.message for l in lints]}
    except Exception as e:
        return {"valid": False, "error": str(e)[:300]}


@router.get("/adapters/{adapter_id}/yaml")
async def get_adapter_yaml(adapter_id: str,
                           db: Session = Depends(get_db)) -> dict:
    _check_adapter_id(adapter_id)
    f = ADAPTERS_DIR / f"{adapter_id}.yaml"
    if not f.is_file():
        raise HTTPException(404, "adapter not found")
    return {"yaml": f.read_text(encoding="utf-8")}


class SaveRequest(BaseModel):
    yaml: str


@router.put("/adapters/{adapter_id}")
async def save_adapter(adapter_id: str, body: SaveRequest,
                       db: Session = Depends(get_db)) -> dict:
    _check_adapter_id(adapter_id)
    try:
        m, lints = load_manifest_text(body.yaml)
    except Exception as e:
        raise HTTPException(422, f"清单校验失败: {str(e)[:200]}")
    if m.id != adapter_id:
        raise HTTPException(422, f"id 不匹配（body={m.id}, path={adapter_id}）")
    dest = ADAPTERS_DIR / f"{adapter_id}.yaml"
    dest.write_text(body.yaml, encoding="utf-8", newline="\n")
    return {"saved": str(dest), "lints": [l.message for l in lints]}


class FingerprintRequest(BaseModel):
    """P2 画像指纹：新系统接入时贴一段系统页面 HTML（或后续录制器自动
    采集）→ 识别组件库/框架 → 生成 interaction_profile 画像草稿 YAML。"""
    dom: str
    url: str = ""


@router.post("/adapters/fingerprint")
async def adapter_fingerprint(body: FingerprintRequest) -> dict:
    from app.adapters.fingerprint import detect_profile, fingerprint_page
    fp = fingerprint_page(body.dom, body.url)
    profile = detect_profile(fp)
    # 画像 → YAML 片段（贴进清单即接入）
    import yaml as _yaml
    ip_yaml = _yaml.safe_dump(
        {"interaction_profile": profile.model_dump()},
        allow_unicode=True, default_flow_style=False, sort_keys=False)
    return {"fingerprint": fp, "profile_yaml": ip_yaml}


@router.get("/adapters/match")
async def adapter_match_by_url(url: str) -> dict:
    """P2.5 URL 自动配对（插件采集侧消费）：录制的页面 URL → 命中的
    adapter id（url_matches 通配符——油猴 @match 语义）。未命中=空。"""
    from app.adapters.manifest import load_adapter_dir
    from app.adapters.urlmatch import match_adapter
    manifests, _ = load_adapter_dir(ADAPTERS_DIR)
    hit = match_adapter(url, manifests)
    return {"adapter_id": hit.id if hit else None,
            "label": hit.label if hit else None}
