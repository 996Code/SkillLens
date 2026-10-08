"""schema 漂移守卫：models 元数据 vs `alembic upgrade head` 建出的真实库。

生产库只由 alembic 建（docs/RELEASE-CHECKLIST.md 部署步、deploy/README.md
故障表），测试库却走 `Base.metadata.create_all`（conftest）——模型加了列而
漏写迁移时全套测试恒绿，全新部署一查该表即 "no such column"。
三轮评审 🔴 实证：`Skill.system` 有模型无迁移，且该列从不写入（死列）。
"""
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def migrated_schema(monkeypatch):
    from alembic import command
    from alembic.config import Config

    url = "sqlite:///" + (Path(tempfile.mkdtemp(prefix="sl-drift-")) / "d.db").as_posix()
    monkeypatch.setenv("DATABASE_URL", url)   # alembic/env.py 以此覆盖 ini
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")

    import sqlalchemy as sa
    insp = sa.inspect(sa.create_engine(url))
    tables = [t for t in insp.get_table_names() if t != "alembic_version"]
    return {
        "columns": {t: {c["name"] for c in insp.get_columns(t)} for t in tables},
        # 索引按「表 → 被索引列的元组集合」比，不比索引名（历史迁移命名不统一）
        "indexes": {t: {tuple(ix["column_names"]) for ix in insp.get_indexes(t)}
                    for t in tables},
    }


@pytest.fixture
def migrated_columns(migrated_schema):
    return migrated_schema["columns"]


def test_every_model_table_has_a_migration(migrated_columns):
    from app.models import Base
    missing = sorted(t.name for t in Base.metadata.sorted_tables
                     if t.name not in migrated_columns)
    assert not missing, f"模型有表但迁移未建：{missing}"


def test_every_model_column_exists_after_upgrade_head(migrated_columns):
    from app.models import Base
    drift = {t.name: sorted({c.name for c in t.columns} - migrated_columns[t.name])
             for t in Base.metadata.sorted_tables if t.name in migrated_columns}
    drift = {k: v for k, v in drift.items() if v}
    assert not drift, (
        f"模型有列但迁移未加（全新部署必崩 no such column）：{drift}——"
        "补迁移，或删掉从不写入的死列")


def test_every_model_index_exists_after_upgrade_head(migrated_schema):
    """index=True 漏写迁移不会崩，只会让线上查询静默退化成全表扫——
    比缺列更难发现，故同样纳入漂移守卫。"""
    from app.models import Base
    migrated = migrated_schema["indexes"]
    drift = {}
    for t in Base.metadata.sorted_tables:
        want = {tuple(sorted(ix.columns.keys())) for ix in t.indexes}
        have = {tuple(sorted(cols)) for cols in migrated.get(t.name, set())}
        missing = want - have
        if missing:
            drift[t.name] = sorted(map(list, missing))
    assert not drift, f"模型声明了索引但迁移未建（线上全表扫）：{drift}"
