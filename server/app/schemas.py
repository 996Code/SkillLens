from typing import Literal

from pydantic import BaseModel, Field


class RawEventIn(BaseModel):
    seq: int
    ts: int          # epoch 毫秒
    page_id: str = Field(default="", max_length=40)
    # "snapshot"：Sprint 8 块B UI 状态快照（C3：快照事件落 raw_event）
    kind: Literal["ui", "action", "network", "console", "navigation", "snapshot"]
    payload: dict


class AlignRequest(BaseModel):
    session_ids: list[str] = Field(min_length=2, max_length=10)
