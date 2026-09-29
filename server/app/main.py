from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from app.api import (
    audit,
    auth,
    dashboard,
    baseline,
    canvas,
    cards,
    change,
    discoveries,
    dev_plans,
    events,
    export,
    flows,
    generic_skills,
    health,
    impact,
    ingest,
    llm_skills,
    locate_proposals,
    replay,
    reports,
    suites,
    reviews,
    timeline,
    visual,
)
from app.config import ALLOWED_ORIGINS, API_PREFIX

# 工作台前端构建产物（npm run build 后存在）；dev 模式下无 dist，跳过挂载不崩。
_WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


class SPAStaticFiles(StaticFiles):
    """SPA fallback：页面路径未命中（如 /skills、/reports/1 深链）回 index.html。

    html=True 只覆盖"目录"路径，任意深链需手动兜底；API 路由先注册不受影响。
    仅当请求看起来是页面（无扩展名）时兜底，避免吞掉真实的静态 404。
    """

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code == 404 and "." not in path.rsplit("/", 1)[-1]:
                return await super().get_response("index.html", scope)
            raise

@asynccontextmanager
async def _lifespan(app: FastAPI):
    # S13 F1：NIGHTLY_CRON=nightly 时拉起夜间图调度循环（默认 off 不启动）
    from app.agents.scheduler import start_nightly_scheduler
    # S14 H4：启动时若 canvas_dag 空则播种预置"定向回归流水线"；
    # 迁移未跑（表缺失）时跳过不阻断启动
    from app.db import SessionLocal
    try:
        from app.agents.canvas import ensure_preset
        db = SessionLocal()
        try:
            ensure_preset(db)
        finally:
            db.close()
    except Exception as exc:
        # 播种非关键路径：迁移未跑/库锁等跳过，但必须留痕区分真实故障
        import logging
        logging.warning("canvas 预置播种跳过: %s", exc)
    await start_nightly_scheduler()
    yield


app = FastAPI(title="SkillLens Local Agent", lifespan=_lifespan)
# CORS 由 ALLOWED_ORIGINS 配置（默认 * 兼容插件直连；私有化收紧见 deploy/README.md）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(auth.router, prefix=API_PREFIX)
# S21 块 S：插件上报通道（events：建会话/上报事件）豁免认证；其余 API 默认要求 Bearer token
app.include_router(events.router, prefix=API_PREFIX)
_GUARDED = [Depends(auth.require_user)]
app.include_router(ingest.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(llm_skills.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(replay.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(change.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(baseline.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(cards.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(reports.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(audit.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(discoveries.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(impact.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(canvas.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(reviews.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(generic_skills.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(dev_plans.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(flows.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(visual.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(locate_proposals.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(export.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(dashboard.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(timeline.router, prefix=API_PREFIX, dependencies=_GUARDED)
app.include_router(suites.router, prefix=API_PREFIX, dependencies=_GUARDED)

# StaticFiles mount 在 "/" 会拦截一切路径——必须放在全部 include_router 之后，
# FastAPI 按注册顺序匹配路由，/api/v1/* 先命中 API，其余落到静态托管（SPA fallback）。
if _WEB_DIST.is_dir():
    app.mount("/", SPAStaticFiles(directory=str(_WEB_DIST), html=True), name="web")
