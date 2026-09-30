"""S42-7 字段类型知识库 API：Web 维护（增删改查）+ 自愈统计。

- GET    /field-types            列表（含 learned/manual/builtin 统计）
- POST   /field-types            新增规则（manual）
- PUT    /field-types/{id}       修改（label_pattern/field_type/example_value）
- DELETE /field-types/{id}       删除
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import FieldTypeHint
from app.replay.field_types import BUILTIN_RULES

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


class FieldTypeIn(BaseModel):
    label_pattern: str = Field(min_length=1, max_length=100)
    field_type: str = Field(min_length=1, max_length=30)
    example_value: str = Field(default="", max_length=200)


def _item(r: FieldTypeHint) -> dict:
    return {"id": r.id, "label_pattern": r.label_pattern,
            "field_type": r.field_type, "example_value": r.example_value,
            "source": r.source, "source_skill_id": r.source_skill_id,
            "success_count": r.success_count or 0,
            "created_at": r.created_at.isoformat()}


@router.get("/field-types")
async def list_field_types(db: Session = Depends(get_db)) -> dict:
    rows = db.execute(select(FieldTypeHint).order_by(
        FieldTypeHint.success_count.desc(), FieldTypeHint.id)).scalars().all()
    return {"items": [_item(r) for r in rows],
            "builtin_types": sorted({r["field_type"] for r in BUILTIN_RULES})}


@router.post("/field-types")
async def create_field_type(body: FieldTypeIn,
                            db: Session = Depends(get_db)) -> dict:
    dup = db.execute(select(FieldTypeHint).where(
        FieldTypeHint.label_pattern == body.label_pattern)).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=409, detail="label_pattern 已存在")
    row = FieldTypeHint(label_pattern=body.label_pattern,
                        field_type=body.field_type,
                        example_value=body.example_value, source="manual")
    db.add(row)
    db.commit()
    db.refresh(row)
    return _item(row)


@router.put("/field-types/{hint_id}")
async def update_field_type(hint_id: int, body: FieldTypeIn,
                            db: Session = Depends(get_db)) -> dict:
    row = db.get(FieldTypeHint, hint_id)
    if not row:
        raise HTTPException(status_code=404, detail="field type not found")
    row.label_pattern = body.label_pattern
    row.field_type = body.field_type
    row.example_value = body.example_value
    db.commit()
    db.refresh(row)
    return _item(row)


@router.delete("/field-types/{hint_id}")
async def delete_field_type(hint_id: int,
                            db: Session = Depends(get_db)) -> dict:
    row = db.get(FieldTypeHint, hint_id)
    if not row:
        raise HTTPException(status_code=404, detail="field type not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
