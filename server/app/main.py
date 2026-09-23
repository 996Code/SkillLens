from fastapi import FastAPI

from app.api import events, health
from app.config import API_PREFIX

app = FastAPI(title="SkillLens Local Agent")
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(events.router, prefix=API_PREFIX)
