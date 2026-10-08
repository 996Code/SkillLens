# 环境变量契约（Env Contract）：全部 env 的唯一权威清单

> 2026-10-08。规则先于清单：**凡是本表没有的 env，代码里就不该出现**——新增 env 必须同步本表
> （这是 `docs/reviews/2026-10-08-full-codebase-audit-round3.md` 定下的纪律）。
> 红线（agents.md §三）：承载机密的 env **只进 `server/.env`（已 gitignore）**，永不入库、永不打印；
> 脚本 env 缺失一律 `sys.exit` 报错，**不写 fallback**（唯一例外见 §5 NJMIND_HOST）。

## 1. server 运行时（`server/app/config.py`，`load_dotenv()` 读 `server/.env`，进程 env 优先）

| 变量 | 消费点 | 默认值 | 缺失时行为 | 必填? | 说明 |
|---|---|---|---|---|---|
| `DATABASE_URL` | config.py:11；conftest.py **硬编码覆盖**为 `sqlite:///./test.db` | `sqlite:///./skilllens.db` | 用默认 | 部署时必 | compose 里是 `sqlite:////data/skilllens.db`（绝对路径进 volume） |
| `ALLOWED_ORIGINS` | main.py（CORS） | `*` | 用默认 | 生产必收紧 | `*` 下 events 豁免通道只剩减速带（见§7）；部署文档已明示 |
| `REPLAY_ARTIFACT_DIR` | config.py:16-18 | `<repo>/artifacts` | 用默认 | 否 | 回放截图落盘根，server runner 与插件 executor 双执行器同源（compose: `/data/artifacts`） |
| `NIGHTLY_CRON` | agents/scheduler.py | off（不启动） | 不启动 | 否 | 仅 `nightly` 一个合法值；默认关 |
| `WEBHOOK_URL` / `WEBHOOK_FORMAT` | integrations/webhook.py | 空=禁用 | 禁用 | 否 | 企业微信/钉钉机器人；URL 本身含密钥，属机密，只进 .env |
| `PII_PATTERNS` | replay/page_snapshot.py（追加到敏感词表） | 空 | 行为不变 | 否 | 私有化自定义（如 `idcard,phone`）；与插件词表无关，仅服务端快照侧 |
| `VISUAL_HASH_MAX_DISTANCE` / `VISUAL_PIXEL_TOLERANCE` / `VISUAL_DIFF_THRESHOLD` | replay/visual.py | 4 / 16 / 0.02 | 用默认 | 否 | 视觉回归三阈值 |
| `PERF_DRIFT_RATIO` | perf 分析 | 1.5 | 用默认 | 否 | current > 中位数×ratio 判漂移 |

## 2. LLM 网关（全部属机密，只进 `server/.env`）

| 变量 | 消费点 | 默认值 | 缺失时行为 | 必填? | 说明 |
|---|---|---|---|---|---|
| `LLM_BASE_URL` | config.py:20 | `""` | 空串 | 生产必 | 网关地址；**永不入库、日志 URL 脱敏** |
| `LLM_API_KEY` | config.py:21 | `""` | 空串 | 生产必 | `git grep sk-` 提交前自扫 |
| `LLM_MODEL` | config.py:22 | `fake-model` | 用默认 | 生产必 | 当前 `deepseek-chat` |
| `LLM_MAX_TOKENS` | config.py:23 | 4096 | 用默认 | 否 | — |
| `LLM_FAKE_RESPONSE` | llm/gateway.py | 未设=真调网关 | 真调 | **测试专用** | 设值后所有 LLM 调用返回该字符串（单测/集成测试的确定性开关；`test_executor_protocol.py` 等大量依赖） |

## 3. 回放与执行（`server/app/replay/runner.py` 等）

| 变量 | 消费点 | 默认值 | 缺失时行为 | 说明 |
|---|---|---|---|---|
| `REPLAY_CHANNEL` | runner.py 启动分发 | 未设=playwright 自带 chromium | 用自带 | 设 `chrome` 用本机真 Chrome（品牌 Chrome 137+ 禁 `--load-extension`，自动化走自带 chromium；回放可用真 Chrome） |
| `REPLAY_HEADLESS` | runner.py | 未设=headless | — | `0`/`false` = 有头（常驻浏览器工作流推荐，全程用户可见） |
| `REPLAY_CDP_URL` | runner.py | 未设=自起浏览器 | 自起 | `http://127.0.0.1:9222` = 连常驻浏览器（`scripts/live_browser.py 9222` 先起） |
| `REPLAY_STORAGE_STATE` | runner.py（import 时读，与同文件"调用时读"惯例不一致——已记债务） | 空 | 无登录态 | 复用已保存的 storage_state |
| `RECORD_CDP_URL` | server/scripts 采集链 | — | — | 采集侧 CDP 常驻浏览器地址 |
| `REPLAY_FLAKY_RERUN` | config.py | `1` | — | execute fail 自动重试一次 |
| `LOCATE_AUTO_PROMOTE_N` | replay/repair.py | 3 | — | 定位提案通过 N 次自动晋升（supersede 链）；测试常设 1 |
| `PLAYWRIGHT_CHANNEL` | 部分脚本 | — | — | 下载 host 用 `PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright`（一次性命令，非常驻 env） |

## 4. 目标系统凭据（**机密红线**，只进 `server/.env`，脚本缺失即 `sys.exit`）

| 变量 | 消费点 | 说明 |
|---|---|---|
| `NJMIND_LOGIN_URL` | scripts/njmind_login.py、auto_record.py、live_browser.py 等 5 脚本 + agents/dev_executor.py | 登录页地址；**永不入库**（2026-10-07 评审后全脚本 fail-fast） |
| `NJMIND_BASE_URL` | 采集/链脚本 | 网关基址 |
| `NJMIND_DESIGNER_URL` | auto_record.py 等 | 设计器地址 |
| `NJMIND_HOST` | system.py:19（host→系统名映射）、auto_record.py | **唯一允许的"缺省回退"例外**：`system.py` 的 `os.environ["NJMIND_HOST"]` 用 `[...]` 直接下标——缺 NJMIND_HOST 时 KeyError 起服失败（等效 fail-fast）；auto_record 侧已改判"来源变量本身为空即 exit" |
| `NJMIND_USER` / `NJMIND_PASS` | njmind_login.py、live_browser.py、auto_record.py | 凭据对；live_browser 本轮补 fail-fast（此前空串静默登录，表现为表单定位超时的间接症状） |

本地演示容器凭据（非机密，部署默认值一致）：`server/adapters/*.yaml` 内嵌
`password_literal`（odoo-admin-local / doli-admin-local / snipe-pw-local / admin123 / admin 等），
GET 回显打码 `***`、PUT 保存时掩码回填（见 `2026-10-08-adapters-subsystem.md` §8）。
env 注入改造排私有化（G4）。

## 5. 部署（compose / Dockerfile）

| 变量 | 位置 | 说明 |
|---|---|---|
| `DATABASE_URL` / `REPLAY_ARTIFACT_DIR` | docker-compose.yml environment | `sqlite:////data/skilllens.db` / `/data/artifacts`（进 named volume） |
| `MARIADB_*` / `DOLI_*` / `POSTGRES_*` / `ERPNext`/odoo/snipe 各自 env | deploy/*/docker-compose.yml | 本地演示容器出厂默认，与部署文档一致 |
| uv 镜像 | server/Dockerfile | **pin `ghcr.io/astral-sh/uv:0.8.4`**（latest 不可复现）；非 root `appuser` 运行 |
| 端口绑定 | 全部 compose | 一律 `127.0.0.1:` 前缀（本轮改），不再暴露局域网 |

## 6. 测试/验收脚本专用（不进 .env，跑时给）

| 变量 | 脚本 | 语义 |
|---|---|---|
| `S21_ADMIN_PW` / `S21_VIEWER_PW` | server/scripts/验收脚本 | 建号口令（本地测试值） |
| `S22_SKILL_ID` / `S23_REPORT_ID` / `S24_SKILL_ID` | 同上 | 指定被测对象 id |
| `SL_BASE` / `SL_RUN_ID` | 同上 | server 基址 / run id |
| `ODOO_*` / `ZENTAO_PW` / `DOLI_PW` | 链测试脚本 | 容器口令（读 manifest 或本地默认） |
| `LLM_FAKE_RESPONSE` | 全测试 | 见§2 |

## 7. 附：`X-SkillLens-Agent` 请求头（非 env，但同属"events 通道鉴权"）

- **谁发**：插件三上报点（uploader.ts / capture 间接 / executor api()）均带 `X-SkillLens-Agent: 1`。
- **谁校验**：`app/api/events.py` 的两个豁免端点（POST /sessions、POST /sessions/{id}/events）——
  这两个端点不挂 require_user（插件拿不到用户 token，设计豁免），改验该头。
- **威胁模型与局限（三轮评审 A3，已记录）**：CORS `*` + `allow_headers *` 下恶意网页的预检必过，
  随手带上该头即可伪造会话/事件——它只挡表单类简单请求，是**减速带不是边界**；另有
  `MAX_EVENTS_PER_BATCH=2000` 的 413 批量上限兜底。升级为 env 注入共享 secret（插件配对时下发）
  排私有化；单机部署的正确缓解是收紧 `ALLOWED_ORIGINS`。

## 8. 新增一个环境变量的检查清单

1. 读：`config.py` 统一 `os.environ.get`（模块级常量），还是运行点读（可测试性优先）？——同文件惯例是"调用时读"。
2. 写：机密吗？→ 只进 `server/.env` + `.env.example` 占位 + 本表§标注"机密"；非机密默认值给不给？
3. 验：缺它时 fail-fast（`sys.exit`/KeyError）还是合理默认？脚本类一律 fail-fast。
4. 记：更新本表 + `.env.example`（若适用）——**表外即违例**。
5. 提交前：`git grep <VAR_NAME>` 确认没有值形态（只有名字）出现在代码/文档之外的地方。
