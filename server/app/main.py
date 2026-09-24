from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import change, events, health, ingest, llm_skills, replay
from app.config import ALLOWED_ORIGINS, API_PREFIX

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
