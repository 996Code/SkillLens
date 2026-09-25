from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from app.api import (
    audit,
    baseline,
    cards,
    change,
    events,
    health,
    ingest,
    llm_skills,
    replay,
    reports,
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

app = FastAPI(title="SkillLens Local Agent")
# CORS 由 ALLOWED_ORIGINS 配置（默认 * 兼容插件直连；私有化收紧见 deploy/README.md）。
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(events.router, prefix=API_PREFIX)
app.include_router(ingest.router, prefix=API_PREFIX)
app.include_router(llm_skills.router, prefix=API_PREFIX)
app.include_router(replay.router, prefix=API_PREFIX)
app.include_router(change.router, prefix=API_PREFIX)
app.include_router(baseline.router, prefix=API_PREFIX)
app.include_router(cards.router, prefix=API_PREFIX)
app.include_router(reports.router, prefix=API_PREFIX)
app.include_router(audit.router, prefix=API_PREFIX)

# StaticFiles mount 在 "/" 会拦截一切路径——必须放在全部 include_router 之后，
# FastAPI 按注册顺序匹配路由，/api/v1/* 先命中 API，其余落到静态托管（SPA fallback）。
if _WEB_DIST.is_dir():
    app.mount("/", SPAStaticFiles(directory=str(_WEB_DIST), html=True), name="web")
