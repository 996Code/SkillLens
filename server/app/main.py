from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import change, events, health, ingest, llm_skills, replay
from app.config import API_PREFIX

app = FastAPI(title="SkillLens Local Agent")
# POC 阶段：本地 Agent 仅监听 127.0.0.1，CORS 全放开以支持插件 content script
# 跨域上报；私有化阶段改为 background service worker 转发后需收紧。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(events.router, prefix=API_PREFIX)
app.include_router(ingest.router, prefix=API_PREFIX)
app.include_router(llm_skills.router, prefix=API_PREFIX)
app.include_router(replay.router, prefix=API_PREFIX)
app.include_router(change.router, prefix=API_PREFIX)
