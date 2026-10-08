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

## 认证与角色（S21 块 S；三轮评审后契约升级，详见 `docs/arch/2026-10-08-auth-and-role-matrix.md`）

- 工作台 API 默认要求 `Authorization: Bearer <token>`；豁免通道仅 `/health`、`/auth/login|logout` 与插件上报（`POST /sessions`、`POST /sessions/{id}/events`，改验 `X-SkillLens-Agent` 头 + 单批 ≤2000 条）。
- 账号三级：`admin`（建号/全权）> `reviewer`（可评审/可写）> `viewer`（**只读**）。viewer=只读由
  `WRITE_GUARD`（`api/auth.py:55`，require_role(admin,reviewer)）在 **31 个变更端点**逐个声明强制
  （`POST /replay`、各 execute/run、DELETE、LLM 调用组等）；C1 确认类（change/dev_plans confirm）另取登录态落 `reviewed_by`。建号：`uv run python -m app.create_user <用户名> <密码> <role>`（空库无默认账号）。
- 会话 DB 化（`auth_token` 表存 SHA-256 哈希，7 天过期，登出即删）；密码 pbkdf2-100k（stdlib）；
  login 计时侧信道已抹平（未知用户也跑一次哈希）。
- 评审人从登录态取（`review.user_id` 关联账号，存量行 NULL 兼容展示）。

## 视觉回归（S22 块 T）

- 断言第 6 层：skill 首次 execute PASS 截图存视觉基线（`visual_baseline` 表 + `artifacts/visual/{sid}/baseline.png`）；此后每次 execute 比对并把结果作为断言 kind=visual_baseline 追加进 assertion_results（参与回放判定）。
- 两级比对全确定性（无 LLM）：dHash 汉明距离初筛（≤`VISUAL_HASH_MAX_DISTANCE` 直接 pass）→ 像素差异占比（≤`VISUAL_DIFF_THRESHOLD` pass，逐像素容差 `VISUAL_PIXEL_TOLERANCE`）；尺寸不同按基线缩放比对。阈值均 env 可调。
- 采集能力缺失（截图失败/文件无效）→ 视觉层整体跳过不计失败（与 assert_eval 无快照 fail-open 同语义）。
- 基线重置：`POST /api/v1/skills/{id}/visual-baseline/reset`（reviewer/admin），下次 PASS 重建；前端详情页基线/最近回放图并排 + 差异统计。
- 动态内容页面（新闻站等轮播内容）会持续触发视觉漂移 FAIL——属预期行为（漂移检测正是目的）；内部稳定系统用默认 2% 阈值，公网站点需调 `VISUAL_DIFF_THRESHOLD`。

## 性能基线（S23 块 V）

- 采集：`replay_run.duration_ms`（execute 回放耗时）+ `plan.api_latencies`（断言模板级 API 延迟，request/response 事件配对）。
- 基线：滚动中位数（该 skill 最近 10 次 execute 回放，从 replay_run 重算，无基线表）。
- 判定：current > 中位数 × `PERF_DRIFT_RATIO`（默认 1.5，严格大于）→ drift 项进四分类报告（type=perf）；历史不足 3 次不判定。
- 呈现：报告页性能基线区块（中位数/本次/趋势条），`GET /reports/{id}/perf` 只读派生端点。

## 自愈与维护闭环（S24 块 U）

- **定位修复提案**：回放定位失败 → LLM（locate_repair）从页面可见元素提案新标签 → **确定性验证**（locate 实测命中）→ verified 参与后续回放自愈；verify_count ≥ `LOCATE_AUTO_PROMOTE_N`（默认 3）自动晋升 promoted；人工否决 `POST /locate-proposals/{id}/reject`（reviewer/admin）。
- **flaky 重跑**：execute fail 自动重试一次（`REPLAY_FLAKY_RERUN`，默认开）；重试 pass → status=pass + `flaky` 标记（进一致性统计 flaky_runs），首次失败明细嵌入 `plan.first_attempt`（C3）。
- **归因链**：提案带 source_run_id，详情页"自愈提案"区块展示 失败→归因→提案→验证 全链。
- 宪法边界：LLM 只提案不判定；proposed（未验证）提案永不参与回放。
- **晋升回写（S26）**：提案晋升（自动 N 次/人工 promote）→ 经 S15 supersede 机制生成 skill 新版本——骨架步加 healed `label` 覆盖（compile 优先取，录制事件不动），断言复制，旧版本 superseded 保留可审计；新版本回放无需提案兜底。

## 集成出口（S25 块 W）

- **Playwright 导出**：`GET /skills/{id}/export/playwright` → 自包含可执行脚本（内联语义定位与模板匹配，与工作台同规则；OVERRIDES 顶部换参）。流程导出同构：`GET /flows/{id}/export/playwright`。导出即人工取走执行权（无 C1 门控）。
- **Webhook**：`WEBHOOK_URL`（空=关）+ `WEBHOOK_FORMAT`（wecom|dingtalk|slack|generic）；报告生成与画布/夜间运行完成触发，fire-and-forget。
- **需求条目关联**：expected_delta.external_ref（Jira key 等）创建时可带、报告页展示；v1 不做 Jira API 对接。

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

replay/            ⑤ 回放 Runner（内部架构详见 docs/arch/2026-10-08-replay-engine.md）
  plan.py          骨架→执行计划（goto 步 URL 已归一化：草稿尾缀重写/query 剥离）
  locate.py        语义定位（placeholder/role-button；两级全 frame 遍历；12 轮重试）
  runner.py        execute_plan + run_replay（写水位=write_response_count 只数写响应；
                   预拉放行/在途写等待=集合差；失败收敛 _error_run）
  repair.py        自愈提案（幻觉"只记录不拦截"，确定性 locate 复核——与 executor 硬门禁的分歧见 arch 文档§6）
  assert_eval.py   确定性断言评估（_ID_SEGMENT 动态 id 归一）
  export_shared.py 导出判定单一事实源（exporter 逐字内嵌进生成脚本）
  exporter.py      Playwright 导出（_safe_doc_text 防模板注入）
  page_snapshot.py 页面快照（全 frame 聚合；脱敏词表与插件同源——一致性由 redact-parity 测试守护）
  环境开关：REPLAY_HEADLESS=0 前台 / REPLAY_CHANNEL=chrome 真Chrome / REPLAY_CDP_URL 常驻窗口

adapters/          ⑦ 平台化适配架构（v2.1 块 AF + 平台化四阶段）
  manifest.py      声明式清单 schema：登录/探针/业务链 + interaction_profile
                   （P1 交互画像五维组件）+ url_matches（P2.5 通配符声明）
  urlmatch.py      P2.5 URL 匹配引擎（油猴 @match 语义；specificity=去*长度）
  fingerprint.py   P2 画像指纹（DOM→组件库识别→画像草稿；POST /adapters/fingerprint）
  probes.py        AF2 探针运行时（docker-exec/http 双形态；密码只从 env 取）
  lint.py          清单合规检查（password_literal 警告等）
  runtime.py       登录/流程步骤解释器
  步骤原语：goto/fill/click/select/wait —— 复杂 shell 走 adapters/scripts/*.sh

change/            ⑥ 变更智能
  expected.py      需求→LLM draft→人工 confirm（verify_delta 校验三类型）
  observed.py      observe 编排（复用 run_replay）+ extract_observed 确定性提取
  classify.py      四分类（expected/missing/unexpected/drift，纯函数）
```

平台化四阶段架构契约（P1 画像/P2 指纹/P2.5 URL 匹配/P3 扩链/P4 零代码接入）：
`docs/arch/2026-10-07-platform-interaction-profile.md`。矩阵脚本：
`server/scripts/v21_matrix.py`（52 链）；raw CDP 录制：`server/scripts/p3_record.py`。

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

- 测试：`uv run pytest -q`（conftest 预置空 key → FakeProvider 铁律；浏览器测试走 playwright chromium）。
  **勿与另一 pytest 进程并行**（conftest 硬编码 ./test.db 会互撞，lessons #43）；全量 20 分钟一轮，
  日志重定向文件查看（管道 tail 会丢输出）。
- 守卫测试（提交前必绿）：`tests/test_schema_drift.py`（模型↔迁移 列+索引 双向比对——加列必须同批写迁移）。
- 基线快照：`uv run python ../scripts/baseline_snapshot.py` → `demo/baseline/*.json`
- 全自动闭环：`uv run python ../scripts/auto_record.py --note <标记>`（RECORD_CDP_URL 可连常驻窗口）
- 常驻可视化浏览器：`uv run python ../scripts/live_browser.py 9222`（配合 REPLAY_CDP_URL）
- 部署：Docker Compose（见 `deploy/README.md`；端口全部 127.0.0.1 绑定、非 root 运行、uv pin 0.8.4）
- 环境变量契约（全部 env 的权威清单）：`docs/arch/2026-10-08-env-contract.md`——**表外即违例**。

## 设计红线速查

- **C1**：destructive/未确认 → shadow（replay.py 门控 + observe 409 短路），零例外。
- **C3**：任何新管道环节的中间产物必须落库；LLM 失败调用也落（gateway）。
- **安全**：真实 key/网关域名/njmind 凭据不进代码/测试/文档/提交/日志（llm_call_log 异常摘要已 URL 脱敏；插件侧密码框+敏感 label 双脱敏）。
- **LLM 边界**：LLM 只做命名/结构化/归因；判定（断言/四分类）全确定性。
