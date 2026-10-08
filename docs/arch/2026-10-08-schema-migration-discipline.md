# Schema 与迁移纪律（Schema & Migration Discipline）

> 2026-10-08。一句话：**测试建库用 `create_all`、生产建库走 alembic——两条路径的偏差
> 必须有守卫测试盯着，否则"模型加了列忘了写迁移"这类缺陷测试恒绿、全新部署必崩**
> （三轮评审 R3-3 实证：`Skill.system` 有模型无迁移，任何生产库上 skill 查询都会
> `no such column` 崩）。本文定义双路径的分工、漂移守卫和加列操作规程。

## 1. 两条建库路径与其偏差面

| 路径 | 谁用 | 建库方式 |
|---|---|---|
| 生产 | `alembic upgrade head`（deploy/RELEASE-CHECKLIST 流程） | 逐支迁移演进，历史可追溯 |
| 测试 | `server/tests/conftest.py` | `Base.metadata.create_all`（按**当前模型**直接建，永远"最新"） |

偏差 = `Base.metadata` 与"全部迁移跑完的库"不一致。conftest 的选择让所有测试对漂移
**免疫**（这是它能掩盖 R3-3 的原因），因此漂移只能靠专门测试抓。

## 2. 漂移守卫：`server/tests/test_schema_drift.py`

- 做法真实：临时目录建空 SQLite → `alembic.config` 指过去 → `command.upgrade(cfg, "head")`
  → `PRAGMA table_info` / `index_list+index_info` 提取**列与索引** → 与 `Base.metadata`
  各表比对。
- 列比对：迁移库每表列集 == 模型列集（双向——缺列=模型新增没写迁移；多列=模型删了列没写
  drop 迁移，当前无此类）。
- 索引比对（本轮扩展）：`{tuple(sorted(ix.columns.keys())) for ix in table.indexes}` 对比
  迁移库实际索引——`DiscoveredFeature.api_template/anchor_label` 的索引若漏写迁移，
  性能修复就会"测试快、生产慢"。当前索引漂移为零。
- 当前**无任何豁免项**（零白名单）：任何表对不上都直接失败。若未来确需豁免，必须逐条注明
  原因——否则守卫形同虚设。

## 3. 加列/加索引操作规程（TDD 顺序）

1. 先写迁移失败的红测试（改 `models.py` → `test_schema_drift` 红）。
2. `uv run alembic revision --autogenerate -m "…"` 生成迁移；**人工审阅**：
   autogenerate 对 `server_default`/nullable 的推断常需手修；down_revision 挂当前 head。
3. 命名规范：`<hex>_<蛇形主题>`（现存 38 支全部符合；本轮
   `a3f1c8d2e6b4_discovered_feature_indexes.py`）。
4. 提供对称 downgrade（drop_column/drop_index）——升级可回退是底线。
5. 跑 `test_schema_drift.py` 绿 + 全量回归。
6. **部署提醒**：compose 起服前先 `alembic upgrade head`（RELEASE-CHECKLIST 已含）。

## 4. 已知债务（确证，非猜测）

| 项 | 位置 | 影响 | 缓修理由 |
|---|---|---|---|
| `skill_id` 无 ForeignKey/ondelete | `OutcomeAssertion/SkillStrategy/ReplayRun/VisualBaseline/LocateProposal` | 删 skill 留孤儿行 | 加 FK 前需先清洗存量孤儿行（否则迁移失败），独立排期 |
| `DateTime` 列无 `timezone=True` | 全部 `created_at/first_seen/…` | 落库丢 tz；naive/aware 混比有隐患（如 AuthToken.expires_at） | 横切改动需一次性迁移；统一方向（列加 tz vs 全存 naive UTC）未定 |
| `conftest.py` 硬编码 `sqlite:///./test.db` | conftest:25 | **并行两套 pytest 互撞**（三轮实测：成片 `no such table: user`） | CI 并行分片前改每进程独立库名 |

## 5. 测试覆盖

| 行为 | 覆盖 |
|---|---|
| 列漂移双向守卫 | ✅ test_schema_drift.py |
| 索引漂移守卫 | ✅（本轮 +） |
| 迁移可升级到 head | ✅（守卫本身即全量 upgrade） |
| **缺口**：downgrade 可回退到 base 无测试（规程§3-4 靠人工审阅） | ❌ |
| **缺口**：SQLite→PG 方言差异（生产换库时 autogenerate 产物需复核） | ❌（当前仅 SQLite） |
