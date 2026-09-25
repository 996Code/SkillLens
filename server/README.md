# SkillLens Server 代码导览

> 面向新接手者：模块地图、数据流、测试与运维入口。架构决策见 `docs/specs/`，踩坑见 `docs/references/project-lessons.md`。

## 快速开始

```bash
cd server
uv sync                                   # 依赖
uv run alembic upgrade head               # 迁移（SQLite ./skilllens.db）
uv run pytest -q                          # 全量测试（FakeProvider，无需真实 key）
uv run uvicorn app.main:app --port 8710   # 起服务
```

LLM/njmind 凭据经 `server/.env`（gitignore 排除，键名见 `.env.docker.example`）。无 key 时 LLM 走 FakeProvider（`LLM_FAKE_RESPONSE` 可定制脚本响应）。

## 模块地图（app/）

```
main.py            FastAPI 入口：CORS(ALLOWED_ORIGINS)、路由挂载、/web 静态托管(S9+)
config.py          env 读取（load_dotenv，进程变量优先）
db.py / models.py  SQLAlchemy engine 与全部 ORM 模型
schemas.py         上报协议 Pydantic（RawEventIn.kind = action|network|navigation|snapshot）

api/               端点层（薄，业务在 ingestion/learning/change）
  ingest.py        POST /sessions、/events、/{sid}/process、/align、GET alignments、semantic-actions、field-changes
  llm_skills.py    POST /alignments/{aid}/induce、/skills/{sid}/assertions、/assertions/{id}/verify、GET /skills（排除 superseded）
  reviews.py       POST/GET /reviews（夜间 agent_run 评审门户）+ GET /reviews/pending（未评审队列）
  replay.py        POST /skills/{sid}/replay、GET /replay-runs/{rid}
  change.py        expected-deltas（draft/confirm/observe/report 四段）
  baseline.py      GET /baseline/skills（C2 对比锚指标）
  health.py        GET /health

ingestion/         ② 确定性数据处理管道（每级产物落库，C3）
  process.py       process 端点编排：事件→窗口→semantic_action；assign_snapshots 快照归属
  windows.py       Transaction Window 切窗（锚点=主动动作；2s 网络空闲关闭）
  url_template.py  URL 模板化（/orders/92382 → /orders/{id}）
  signals.py       响应体状态信号提取（顶层 status|state|code|result）
  alignment.py     多 Episode 骨架对齐（LCS）+ window_params 参数对账
  variables.py     变量识别（param/input 双轨）
  fielddiff.py     reqBody 展平/diff/截断（8KB+sha256 保护，cap_value）
  fieldchange.py   字段级 Before/After（层 2a，同 session 相邻同模板 POST diff）

learning/          ③ 学习引擎（③）
  skill.py         induce：LLM 命名 + 确定性回查降级 candidate；re-induce 版本演化（旧行 superseded 保留，v3 §29）
  outcome.py       generate_assertions（api_status/state_signal/field_change，只取骨架证据范围）

llm/               ④ LLM Gateway（自研薄封装）
  provider.py      FakeProvider / OpenAICompatProvider
  gateway.py       complete()：成功与失败（脱敏 URL）均落 llm_call_log（C3）

replay/            ⑤ 回放 Runner
  plan.py          骨架→执行计划；requires_confirmation（C1 门控依据：POST/write）
  locate.py        语义定位（placeholder/role-button，非 CSS）
  runner.py        execute_plan（水合竞态防护）+ run_replay（shadow 短路/截图/LLM 归因）
  assert_eval.py   确定性断言评估（path_matches 模板匹配）
  环境开关：REPLAY_HEADLESS=0 前台 / REPLAY_CHANNEL=chrome 真Chrome / REPLAY_CDP_URL 常驻窗口

change/            ⑥ 变更智能
  expected.py      需求→LLM draft→人工 confirm（verify_delta 校验三类型）
  observed.py      observe 编排（复用 run_replay）+ extract_observed 确定性提取
  classify.py      四分类（expected/missing/unexpected/drift，纯函数）
```

## 核心数据流

```
插件采集 → raw_event ─process→ transaction_window + semantic_action（含 state_before/after）
    ↓ /align          alignment（骨架+变量+window_params）
    ↓ /induce         skill（LLM 命名，失败/回查不过→candidate）
    ↓ /assertions     outcome_assertion（层2/3）
    ↓ /replay|observe replay_run（shadow 门控 C1 / PASS-FAIL / 截图 / LLM 归因）
    ↓ /report         delta_report（四分类）
全程 llm_call_log（成功+失败）
```

## 测试与运维

- 测试：`uv run pytest -q`（conftest 预置空 key → FakeProvider 铁律；浏览器测试走 playwright chromium）
- 基线快照：`uv run python ../scripts/baseline_snapshot.py` → `demo/baseline/*.json`
- 全自动闭环：`uv run python ../scripts/auto_record.py --note <标记>`（RECORD_CDP_URL 可连常驻窗口）
- 常驻可视化浏览器：`uv run python ../scripts/live_browser.py 9222`（配合 REPLAY_CDP_URL）
- 部署：Docker Compose（见 `deploy/README.md`）

## 设计红线速查

- **C1**：destructive/未确认 → shadow（replay.py 门控 + observe 409 短路），零例外。
- **C3**：任何新管道环节的中间产物必须落库；LLM 失败调用也落（gateway）。
- **安全**：真实 key/网关域名/njmind 凭据不进代码/测试/文档/提交/日志（llm_call_log 异常摘要已 URL 脱敏；插件侧密码框+敏感 label 双脱敏）。
- **LLM 边界**：LLM 只做命名/结构化/归因；判定（断言/四分类）全确定性。
