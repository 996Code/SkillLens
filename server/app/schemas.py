from typing import Literal

from pydantic import BaseModel


class RawEventIn(BaseModel):
    seq: int
    ts: int          # epoch 毫秒
    kind: Literal["ui", "action", "network", "console", "navigation"]
    payload: dict
