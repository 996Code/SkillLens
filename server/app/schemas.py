from typing import Literal

from pydantic import BaseModel, Field


class RawEventIn(BaseModel):
    seq: int
    ts: int          # epoch 毫秒
    page_id: str = Field(default="", max_length=40)
    kind: Literal["ui", "action", "network", "console", "navigation"]
    payload: dict
