from fastapi import FastAPI

from app.api import health
from app.config import API_PREFIX

app = FastAPI(title="SkillLens Local Agent")
app.include_router(health.router, prefix=API_PREFIX)
