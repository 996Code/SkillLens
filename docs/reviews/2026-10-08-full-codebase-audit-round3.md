# 2026-10-08 全库代码评审（第三轮 · 七域并行深审）

> **范围**：`server/app`（11,980 行 Python，34 模块）、`server/tests`（76 文件）、`server/web/src`
> （6,468 行）、`extension/src`（3,109 行 + 11 测试文件）、`server/scripts`、`scripts/`、`deploy/`、
> `docker-compose.yml`、`server/Dockerfile`、`server/alembic/versions`（37 支迁移）、`server/adapters/*.yaml`（9 份清单）。
> **方式**：七个子代理按域并行逐文件深审（只读、不改代码）→ 本人机械复核安全红线 → 关键发现本人读源码验证
> → TDD 先红后绿修复 → 三套回归。二轮报告见 `2026-10-07-full-codebase-audit.md`（其修复项本轮**逐条复验在位**，无回退）。
> **背景**：平台化四阶段（P1 画像 / P2 指纹 / P2.5 URL 匹配 / P3 扩链 / P4 Firefly 零代码接入）收口、
> 基线 server 508 / web 54 / extension 83 之后的第三轮全量闸门审查。
> **本轮定位**：前两轮查的是"有没有违规"，本轮查的是"**声称的语义是否真的成立**"——七域里有 5 个 🔴
> 属于"测试恒绿但生产必错"或"注释自称 X 实现是 Y"的漂移型缺陷，单靠跑测试永远发现不了。

## 一、结论总览

| 域 | 深审对象 | 🔴 | 🟡 | 🟢 | 本轮修复 | 缓修/记录 |
|---|---|---|---|---|---|---|
| A 安全与鉴权 | 24 router / 97 端点 / auth / events / 文件端面 | 2 | 4 | 4 | 4 | 6 |
| B 回放与执行引擎 | `app/replay/*` 12 文件 + executor API | 1 | 7 | 6 | 8 | 6 |
| C 数据管道与学习 | `app/ingestion/*`、`app/learning/*`、`app/change/*`、models/alembic | 2 | 6 | 3 | 5 | 6 |
| D 插件（MV3） | `extension/src` 全部（executor.ts 1,549 行重点） | 2 | 8 | 9 | 8 | 9 |
| E 工作台（Vue） | `server/web/src` 21 视图/组件 + api.ts | 1 | 9 | 6 | 12 | 4 |
| F 脚本与部署 | `scripts/`、`server/scripts/`、`deploy/`、compose、Dockerfile | 1 | 6 | 4 | 11 | 2 |
| G 适配器清单 | `app/adapters/*` 6 文件 + 9 份 yaml + 向导 UI | 0 | 3 | 2 | 5 | 1 |
| **合计** | — | **9** | **43** | **34** | **53** | **34** |

| 维度 | 结论 |
|---|---|
| 安全红线 | **1 处硬编码内网 IP 回归（F 域）已清零**；无 LLM key / 网关域名 / 凭据入库；`git grep 192.168` 提交前自扫为空 |
| 鉴权覆盖 | 从"21/24 router 挂 require_user + 4 处角色门"升级为 **router 级 require_user 全覆盖 + 31 个变更端点挂 `WRITE_GUARD` + 9 处点位 `require_role`**；viewer=只读契约首次与代码一致 |
| 宪法执行 | C1 判定全确定性补上最后一个缺口（executor 自愈提案硬门禁）；C3 全链路落库补齐录制侧失败调用；C2 学习轨道分轨仍缺（产品决策，见§六） |
| 正确性 | 本轮最重的一类缺陷是**"替身测试掩盖的真实语义失效"**：写水位被 GET 噪声击穿、`/[*\s]/` 转义丢一层、`Skill.system` 有模型无迁移、脱敏词表四处副本漂移——四者共同点是"测试全绿、生产必错" |
| 卫生 | 死代码清理 11 处；`execute_plan`（~540 行）与 `execute()`（1,549 行文件内）两大巨函数仍为最大债务，与二轮同因缓修 |
| 文档 | 本轮同步补 8 篇 `docs/arch/`、重写 3 份 README 导览、`project-lessons.md` +9 条、主计划 v2.3 |

**方法论收获（本轮新增的四类"防漂移"装置，均已落成测试而非口头纪律）**
1. **跨文件一致性测试**：脱敏词表四份物理副本（TS / MAIN-world JS / Python / 页内注入 JS）由
   `extension/src/shared/redact-parity.test.ts` 读源码断言词集相等——副本无法消除（CRXJS 原样复制
   `injected/*.js` 不做 TS 转换、页内注入代码不能 import），那就让漂移在 CI 里失败。
2. **结构测试自带非空守卫**：`executor-injected-regex.test.ts` 除断言"零单反斜杠转义"外，还断言
   `expression: \`` 出现次数 ≥10 且含特定字面量——否则实现改名后测试静默恒绿（vacuous pass）。
3. **schema 双向漂移守卫**：`tests/test_schema_drift.py` 跑真实 `alembic upgrade head` 到临时库，
   对比 metadata 的**列与索引**——`create_all` 建表的测试永远抓不到"模型加了列忘了写迁移"。
4. **判定逻辑单一事实源 + 逐字内嵌**：`app/replay/export_shared.py` 被 `exporter.py` 以源码文本内嵌进
   生成的独立 Playwright 脚本，服务端与导出脚本再不可能各判一套 PASS/FAIL。

## 二、安全红线机械复核（逐条）

| 红线（agents.md §三） | 复核方式 | 结论 |
|---|---|---|
| 真实 LLM key / 网关域名 | 全库 `git grep -nE "sk-\|api_key\s*=\s*['\"]"` + `.env` 是否 gitignore | ✅ 无命中；`.env` 在 `.gitignore` |
| njmind 内网凭据与地址 | `git grep 192.168`、`git grep 10\.` + 逐个脚本读 env 分支 | 🔴→✅ `scripts/auto_record.py:71` 一处 `or "http://192.168.99.22/mb3/1/"` 兜底（二轮修复的回归），已改 `sys.exit`；其余全部 env 读取或 127.0.0.1 |
| 脚本 env 缺失不写 fallback | 逐个 `scripts/*.py`、`server/scripts/*.py` 读 | ✅ 全部显式 exit；`live_browser.py` 本轮补齐凭据 fail-fast |
| llm_call_log 异常摘要 URL 脱敏 | `app/llm/gateway.py` + `app/replay/sanitize.py` 全调用点 | ✅ 未回退；本轮补齐 replay 步骤 error 与归因 prompt 两处（见§四 B3） |
| 插件侧密码框 + 敏感 label 双脱敏 | `capture.ts`/`snapshot.ts`/`net-hook.js`/`executor.ts` 四处 | 🔴→✅ 词表四处漂移（net-hook 少 4 词、全部副本缺中文形态），已统一为 16 词 + 一致性测试 |
| 会话态/凭据文件不入公共临时目录 | `scripts/njmind_login.py`、`auto_record.py` | ✅ `/tmp/njmind-state.json` → 仓库根 `.njmind-state.json`（gitignore）、`/tmp/skilllens-ext-profile` → `.ext-profile*/`（gitignore） |
| 提交前 diff 扫敏感串 | 本轮提交前执行 | ✅ 见§七 |

## 三、🔴 确证违规与修复（9 项，全部 TDD 先红后绿）

### R3-1 viewer 角色形同虚设：25 个变更端点只挂 require_user（A 域）
**位置** `server/app/main.py:99-123` + 各 api 模块。角色门此前只覆盖 4 处（adapters PUT、
locate_proposals、reviews POST、visual reset）。viewer 可直接 `POST /skills/{id}/replay`
（`confirm_side_effect=true` 时对目标系统执行**真实写操作**）、`/dev-plans/{id}/execute`、
`/flows/{id}/execute`、`/canvas/{id}/run`、`/suites/{id}/run`、`DELETE /suites/{id}`、
field_types CUD、generic_skills promote、llm_skills induce/verify（烧 LLM 配额）、ingest
process/align、executor plan/step/finish。代码注释与测试都宣称"viewer 只读"，与矩阵不符。
**修复** `app/api/auth.py:53-55` 新增唯一来源 `WRITE_GUARD = [Depends(require_role("admin","reviewer"))]`，
11 个 api 模块的 **31 个变更端点**逐个声明 `dependencies=WRITE_GUARD`（读端点不动，viewer 保留全量 GET）。
**测试** `server/tests/test_role_gates.py`（viewer 对写端点 403 / reviewer 200 的矩阵断言）。

### R3-2 C1 人工确认门可被冒充（A 域）
**位置** `app/api/change.py:27,60`、`app/api/dev_plans.py:62,75`——`confirm` 的 `reviewed_by` 取自
**请求体**：任何 viewer 提交 `{"reviewed_by":"admin"}` 即可完成 expected-delta / dev-plan 的 C1 确认，
随后 execute。对照 `reviews.py:73` 早已正确取 `user.username`。审计不可抵赖性被破坏。
**修复** 两处改 `user: User = Depends(require_role("admin","reviewer"))` + `row.reviewed_by = user.username`
（`change.py:63`、`dev_plans.py:73`），请求体字段删除。
**测试** `test_role_gates.py` 冒充用例（body 写 admin、登录 viewer → 403；登录 reviewer → 落库为 reviewer 用户名）。

### R3-3 `Skill.system` 有模型无迁移：全新部署必崩（C 域）
**位置** `app/models.py:133` 定义 `Skill.system`，但 36 支迁移无一给 `skill` 表 `add_column('system')`。
运行时 `app/db.py` 不 `create_all`，schema 全靠 alembic——`alembic upgrade head` 出来的库缺该列，
而 ORM 对 `db.query(Skill)` 会 SELECT 全部映射列 → 生产上**任何** skill 查询都 `no such column: skill.system`。
测试因 `conftest.py` 用 `create_all` 建列而永远掩盖此漂移。
**根因追查** 该列其实是**死列**：全库无 `Skill(system=...)` 赋值，`executor.py:251` 读 `skill.system or ""`
恒为空串，真实系统派生走 `app/system.py`（首条 navigation 的 host 映射）。
**修复** 删除该列 + 删除 executor 的 fallback 分支（比补一支迁移更干净：迁移会为一个从不写入的列留永久负担）。
**装置** 新增 `server/tests/test_schema_drift.py`：真实 `alembic upgrade head` 到临时 SQLite，
对比 metadata 的**列集合与索引集合**——同类漂移从此在 CI 失败。当前索引漂移为零（本轮
`DiscoveredFeature.api_template/anchor_label` 补索引 + 迁移 `a3f1c8d2e6b4`）。

### R3-4 `induce_skill` 空骨架分支 NameError（该路径从未成功执行过）（C 域）
**位置** `app/learning/skill.py:100` 在 `if not alignment.skeleton:` 分支执行
`db.query(OutcomeAssertion)`，而文件顶部只导入 `Alignment, Skill, SkillStrategy`——
对**已有旧 skill** 的 alignment 重新 induce 且骨架变空时必 500。
既有测试 `test_induce_empty_skeleton_skips_llm` 只测"全新无旧 skill"，`for s in old` 不进入，故未暴露。
**修复** 该分支的"删旧 skill + 删策略 + 删断言"整体移除（与 S15"不覆盖旧版本"相悖，且新行还不带 version），
改走与正常分支同一套 `_supersede()`（`skill.py:92`）：新行 `version=max+1`、旧行 `status=superseded`+
`superseded_by`，断言/策略保留作历史。
**测试** `test_skill.py` 补"已有旧 skill + 重 induce 成空骨架"回归用例。

### R3-5 "预拉放行"水位被 GET 噪声击穿：提交拦截判定实际失效（B 域）
**位置** `app/replay/runner.py:548-552`——`if not saw_write and len(observed) > recent_write_mark: saw_write = True`。
`observed` 收**所有**响应（含 GET），`recent_write_mark` 只在写响应窗口更新且初始为 0；
真实页面加载后 `len(observed)` 几乎必然 > 水位 → S43-4 引入的"点击后无写请求 = 提交被前端校验拦下 = 判失败"
在生产环境形同虚设，**被拦的提交会被放行成 pass**。测试能断言"提交被拦"
（`test_runner_browser.py:493`）只因替身页面此前零响应，恰好掩盖缺陷。
**修复** `runner.py:30` 抽出纯函数 `write_response_count(observed)`（只数 POST/PUT/PATCH），
水位判定与 `recent_write_mark` 更新（`runner.py:556,596`）统一改用它。
**测试** `server/tests/test_runner_watermark.py`（纯函数级）+ `test_runner_browser.py` 补
"点击前已有 GET 响应"的用例——即此前缺失的那个前提。

### R3-6 脱敏词表四处物理副本漂移，录制路径漏脱敏（D 域 + G 域）
**位置** 四份副本：① `extension/src/shared/redact.ts`（TS 正典，10 词）② `extension/src/injected/net-hook.js:5`
（MAIN-world 纯 JS，**只有 6 词**，注释自称"同源语义"）③ `server/app/replay/page_snapshot.py:24`
（**只有 6 词**，注释自称"与 redact.ts 同词表"）④ `executor.ts:396` 页内注入的 `const SENS`（10 词）。
后果：录制路径中 `?api_key=xxx` 的 URL query、JSON 体里的 `apikey` 字段**明文**落 IndexedDB → 上报服务端
→ 进 `raw_event` → 进 LLM 归因 prompt；快照侧同理。
**追加发现（本人复核）** 四份副本**全部缺中文形态**——目标系统是中文业务系统（禅道/JeecG/若依/njmind），
`type=text` 且 label 为「密码/口令/密钥/令牌/凭证/验证码」的字段不命中任何一份词表，值明文进 snapshot forms。
**修复** 四份统一为 **16 词**（10 英文 + 6 中文）：`redact.ts:5`（正典，注释点名三处镜像）、
`net-hook.js:8`、`page_snapshot.py:24-31`、`executor.ts` 页内 `const SENS`。
**装置** `extension/src/shared/redact-parity.test.ts`（`// @vitest-environment node`，用 `import.meta.url`
读四处源码文本，正则/引号列表两种解析器提取词集，断言四份相等 + 中文形态覆盖 + 词表无重复）。
**测试** `capture-redact.test.ts`（jsdom + `vi.stubGlobal("location", …)`：page-load/click/submit 事件的
URL 必须含 `[REDACTED]`、不含 `abc123`/`k-99`、保留 `id=5` 与 host/path——系统派生依赖首条 navigation 的 host）。

### R3-7 注入页内 JS 的模板串转义丢一层：fill 把 label 里的字母 s 全剥掉（D 域）
**位置** `executor.ts:1318,1324`（resolver 兜底 fill 路径）——写在反引号模板串里的 `/[*\s]/g`，
`\s` 在模板字面量中被烹饪成字面 `s`，页面实际收到 `/[*s]/g`：**把 label 里的字母 s 全部剥掉**
（"Sales"→"Sale"、"Status"→"tatu"），form-item label 匹配对任何含 s 的英文标签必失败。
主拷贝 `executor.ts:602,608` 写的是 `/[*\\s]/g`（正确）。同型缺陷还有 `:322` 的 `/确\s*定|Cancel|取消/`。
这正是二轮记录为"缓修"的 fill 双拷贝——本轮确证它已从"重复"退化为"行为级 bug"。
**修复** 三处转义补一层（`\\s`）；页内注入代码里所有正则/换行转义一律双写。
**装置** `extension/src/background/executor-injected-regex.test.ts`：扫描全部 `expression: \`…\`` 模板串
（跳过 `${…}` 插值），断言**零**单反斜杠转义；并自带非空守卫（`expression: \`` 出现次数 ≥10、
必须含 `label.replace(/[*\\s]/g, '')` 字面量），防止实现改名后测试静默恒绿。
**dist 验证** 构建产物中确认含 `label.replace(/[*\s]/g`（编译后正好一层）与 `确\s*定|Cancel`。
**未做** 双拷贝合并为单一 builder 仍属重构项（见§六），本轮先消除缺陷本身。

### R3-8 AdaptersView：select 失败后保存会把 A 系统 YAML 写进 B 系统（E 域）
**位置** `server/web/src/views/graph/AdaptersView.vue:105-113,132-146`——`select()` 无 try/catch、
`res.ok=false` 时静默跳过，但 `selected` 已切到新适配器而 `yamlText` 仍是**上一个**适配器的内容；
此时点"保存"即 PUT 错误 YAML 覆盖目标适配器（静默数据破坏）。`save()` 本身也无 try/catch、无 busy 防重。
**修复** select 失败清空 yamlText + 错误提示 + 加载失败禁用保存；save 加 try/catch + busy 防重。
**测试** `server/web/tests/AdaptersView.spec.ts`（新建，含"select 失败后保存不得 PUT"用例）。

### R3-9 掩码回显 + 原文 PUT = 保存即销毁凭据（G 域，本人复核子代理修复时发现）
**位置** G 域子代理为修 F3（GET `/adapters/{id}/yaml` 向所有登录用户回吐清单原文，含 `password_literal`
与登录用户名）加了 `redact_manifest_text()` 打码；但 web 编辑器的路径是 **GET 回显 → 用户改两行 → PUT 原文**，
打码后的 `***` 会被原样写回磁盘，**演示容器凭据一次保存即永久丢失**。
**修复** `app/adapters/manifest.py:318` 新增 `restore_masked_secrets(new_text, old_text)`：
保存时把仍是掩码的敏感键按**行级 FIFO** 回填磁盘旧值（不重序列化，保留用户注释；同名键多次出现按出现序配对；
用户显式改写的新值优先）。`app/api/adapters.py::save_adapter` 读旧文本 → 回填 → 校验 → 写盘。
**测试** `test_adapters_api.py::test_put_round_trip_preserves_masked_secret`（GET 回显改中文名后 PUT，
断言磁盘仍含原口令）与 `test_put_explicit_secret_overrides_mask`（显式改写优先于掩码）。
**教训** 子代理的"安全修复"必须按**真实调用路径**复核，不能只看它自己的报告（已入 project-lessons）。

## 四、🟡 中危处置（43 项：修复 34、缓修/记录 9）

### A 域 安全与鉴权
| # | 项 | 处置 |
|---|---|---|
| A1 | F3 GET yaml 回吐凭据 | ✅ `redact_manifest_text()` 打码 + `restore_masked_secrets()` 回填（R3-9）；GET 保持 viewer 可读（清单结构本身是文档价值） |
| A2 | F4 events 批量无上限可撑爆 SQLite | ✅ `app/api/events.py:19` `MAX_EVENTS_PER_BATCH = 2000`（客户端 BATCH=50，40 倍余量）→ 413；测试 `test_events.py` |
| A3 | F4 `X-SkillLens-Agent` 守卫在 CORS `*` 下只是减速带 | ⏸ 记录：升级为 env 注入共享 secret 属协议改造（插件配对时下发），排私有化；部署文档已强调生产必须收紧 `ALLOWED_ORIGINS` |
| A4 | F6 login 计时侧信道可枚举用户名 | ✅ `app/api/auth.py:66` 模块级 `_DUMMY_HASH`，未知用户也跑一次 100k 轮 pbkdf2 抹平计时；测试 `test_auth_api.py` |
| A5 | F6 login 无失败限速 | ⏸ 记录：单租户本地工具，限速属部署侧（反代）职责，文档明示 |
| A6 | F5 token 走 URL（`executor.html?token=`） | ⏸ 递延（二轮 #11 同款）：一次性 code 换票属协议改造；已有 `replaceState` 补救 |

### B 域 回放与执行引擎
| # | 项 | 处置 |
|---|---|---|
| B1 | pend_writes 按 `len(req_times)` 切片，而 `on_response` 会 `pop` → 索引漂移使在途写请求被判"无 pending"，0.4s 即 break，后续定位落在未稳定页面 | ✅ `runner.py:578-582` 改**集合差**（点击时刻 `inflight_before = set(req_times)`，pending = `set(req_times) - inflight_before`） |
| B2 | `compile_skeleton_plan` 算了归一化 `path` 却只用于去重，goto 步插的是**原始** `nav_url`：Frappe 一次性草稿地址回放随机重定向，且 query（可能含会话令牌）随 plan 落库；`runner.py:332` 注释"归一化由编译侧保证"与实现不符 | ✅ `plan.py:162` goto 步改用归一化 `path`（草稿尾缀已重写、query/hash 已剥）；`test_replay_plan.py` 补 goto 用例 |
| B3 | 步骤级 error 原文（含 URL）落库并进 LLM 归因 prompt，未走 `sanitize_error`（`runner.py:755` 的 `scene` 含 `page.url[-60:]`，Playwright 异常本身内嵌完整 URL；`flow_runner.py:92,109` 同）→ 与 `sanitize.py` 自述纪律冲突，且 gateway 只脱敏 failure 摘要、success prompt 原文入库 | ✅ 步骤 error 与归因 prompt 统一过 `sanitize_error`，flow_runner 同步 |
| B4 | `build_state_machine` 节点 id 用**裸状态值**：`status=1` 与 `docstatus=1` 合并成一个节点，先到的 label 获胜、两个字段的转移边画在同一节点上，状态机图失真 | ✅ `flow_graph.py:173-200` 节点 id 改复合键 `field=value`；`field`/`value` 以**新增**属性下发（不改既有键名，响应契约保持）；`test_flow_graph2.py` 补跨 field 同值用例 |
| B5 | exporter 与服务端判定语义**四处漂移**：① `_ID_SEGMENT` 缺 `[0-9a-fA-F]{16,}`（S43-5 已在 assert_eval 加，导出未同步）② api_status 判定 `all(h != expect)` 才 fail（服务端是 `all(s == expect)` 才 pass）③ state_signal 任一命中即可（服务端取最后一次写响应）④ locate 链是 5 策略简化版却自称"与 locate.py 同策略链"→ 导出脚本 PASS/FAIL 可与工作台互相矛盾，击穿"确定性可审计"卖点 | ✅ 新增 `app/replay/export_shared.py`（`_ID_SEGMENT`/`static_segments`/`path_matches`/`judge_api_status`/`judge_state_signal`，只依赖标准库），`exporter.py` 把该文件源码**逐字内嵌**进生成脚本；`test_export.py` +92 行以 `assert_eval` 为基准比对 pattern 与判定行为 |
| B6 | 导出脚本模板注入：`skill.name` / `flow.goal`（LLM 产物或用户输入）裸插三引号 docstring，含 `'''` 即破坏生成的 .py 结构，可注入任意代码到用户将执行的脚本 | ✅ `exporter.py:24` `_safe_doc_text()` 消毒后内插 |
| B7 | `collect_page_snapshot` 不穿 iframe（全部 `page.query_selector_all` 仅主 frame）：禅道综合界面这类 iframe 架构下 forms/labels/toasts 恒空 → ui_text 断言全 skip、toast 补充通道失效、repair 提案池为空 | ✅ `page_snapshot.py:72` `_iter_frames()`（主 frame 优先 + 子 frame 聚合，与 `locate._try_locate` 同构；限额是**全局总量**非逐 frame；frame 销毁竞态跳过；无 `frames` 属性的测试替身回退单 page） |
| B8 | CDP `shared_ctx` 模式下 `ctx.new_page()` 开的 page 从无 `page.close()`：常驻浏览器（9222 工作流）标签随 attempt × skill 无限增长 | ⏸ 缓修：需真机常驻浏览器轮验证（finally 分支改动会影响 52 链矩阵的收尾时序） |
| B9 | `execute_plan` ~540 行巨函数 + 三处逻辑重复（行锚 token 正则在 runner/resolver 各一份、Frappe 草稿 URL 正则在 plan.py 两处、locate 策略矩阵三份） | ⏸ 缓修（二轮 #6 同因）：重构面大，需 52 链真机回归支撑；本轮已先把**判定逻辑**收口到 export_shared（B5），正则常量单一来源随重构一起做 |

### C 域 数据管道与学习
| # | 项 | 处置 |
|---|---|---|
| C1 | JSON 列一律硬索引，畸形行触发 KeyError：`learning/outcome.py:135,139,151,160-163` 与 `change/classify.py:16,20,23,45,50-53`；尤其 `expected.py:64` 明确"changes 保留原样供人工修订"，校验失败行的元素可能缺 `value`/`type`，随后流入 `classify_delta` 直接崩 | ✅ `classify.py` 新增 `_well_formed()` / `_malformed_entry()`：畸形条目不参与匹配，按 C3**带 reason 记入** missing/unexpected（可见不吞），不 500；`outcome.py` 同类跳过 + `logger.warning` |
| C2 | `classify_delta` 用 `list.index()` 标记 matched：observed 中重复 `(type,value)` 时第二条永不被标记 → 误判 `unexpected` | ✅ 改按**对象身份**消费（`matched_ids: set[int]` + `id(o)`），drift 项对应的 observed 不算 unexpected；`test_delta_classify.py` 补重复值用例 |
| C3 | `DiscoveredFeature.api_template/anchor_label` 无索引：`_find_row` 每个候选各查一次 → 每次 process 随表增长线性劣化 | ✅ 两列加 `index=True` + 迁移 `a3f1c8d2e6b4` + `test_schema_drift.py` 索引守卫 |
| C4 | 服务端 ingestion 写路径不做二次脱敏（`events.py:59` payload 原样落库、`fieldchange.py` 只长度截断、`process.py` 落 state_before/after）——插件漏一个字段，凭据/PII 即明文入库 | ⏸ 缓修：需先定"服务端二次脱敏是否会破坏证据可回放性"（脱敏后的值无法用于回放注入），属产品取舍；本轮改为把插件侧四道脱敏**钉死**（R3-6 一致性测试） |
| C5 | C2 宪法：学习轨道未分轨——`/align` 接受任意 `session_ids` 不校验 `RecordingSession.source`，demo 与 real_traffic 会话可混入同一骨架 | ⏸ 记录（产品决策）：分轨需要"真实流量技能"独立生命周期设计，进主计划待用户确认 |
| C6 | `field_change` 每模板只 diff **最后两次 POST**（`fieldchange.py:31-33` 取 `seqs[-2], seqs[-1]`），"建→改→再改"流程的早期变更静默丢弃，与 C3 有张力 | ⏸ 记录：语义是有意取舍（末对 = 最终态），但缺审计行；改进方案（逐相邻对全量 diff 或落降级说明）进 backlog |
| C7 | `skill_id` 全缺外键与级联：`OutcomeAssertion/SkillStrategy/ReplayRun/VisualBaseline/LocateProposal.skill_id` 均为裸 Integer；删 skill 会留孤儿行 | ⏸ 缓修：补 FK + `ondelete=CASCADE` 需要数据清洗迁移（现存孤儿行会让迁移失败），独立排期 |
| C8 | `alignment.py:232` while 循环内每次重建 `{(a,b) for a,b in pairs}` → O(steps×pairs)；`_bucket_sessions` 对每对 session 调 LCS | ⏸ 缓修：当前会话规模（≤30）下无实测劣化；性能项进 backlog |
| C9 | `DateTime` 列未带 `timezone=True` 却写入 aware datetime（`utcnow()` 产 `datetime.now(timezone.utc)`）→ 落库丢 tz，跨 naive/aware 比较有隐患（如 `AuthToken.expires_at` 过期判定） | ⏸ 缓修：全项目统一（列加 tz 或统一存 naive UTC）是横切改动，需一次性迁移 |

### D 域 插件（MV3）
| # | 项 | 处置 |
|---|---|---|
| D1 | 敏感词表纯英文，中文 label 字段绕过脱敏 | ✅ 并入 R3-6（16 词四副本 + 一致性测试） |
| D2 | click/navigation/snapshot 证据中的 `location.href` 未过 URL 脱敏（`capture.ts:251,264,275`、`executor.ts:418`）——net-hook 只护网络请求 URL，不护**文档** URL；SSO 回跳的 `?token=`/`?ticket=` 明文进 IndexedDB 并上报 | ✅ `capture.ts:29` 新增 `pageUrl()`（`redactNetworkUrl(location.href)`）替换 4 处调用；`executor.ts:437-440` 快照 `page.url` 在 SW 侧补一道（页内表达式无法 import）；host/path 保持不动（系统派生依赖首条 navigation 的 host）；测试 `capture-redact.test.ts` |
| D3 | C3 违规：录制路径的**失败**网络调用不落库——fetch reject 时 await 抛出无 post；XHR 只挂 `load`，error/timeout/abort 全丢（执行器侧有 `Network.loadingFailed`，录制侧没有） | ✅ `net-hook.js`：fetch 包 try/catch 先 post `{status:0, error:"network"}` 再**原样抛出**（不吞页面异常）；XHR 补 `error`/`timeout`/`abort` 三监听。失败路径同样走脱敏（红线不因失败豁免）。测试 +4 例（`net-hook.test.ts`） |
| D4 | `finally` 无条件 `chrome.tabs.remove(tabId)`：复用**用户自己开的**空白页签执行后把它关掉，销毁用户页签 | ✅ `executor.ts:269` 新增 `releaseExecTab(debuggee, tabId, reused)`——自建页签 remove，复用页签 `tabs.update` 导航回 about:blank；两处收尾点（attach 失败 / finally）统一走它 |
| D5 | 截图 base64 `slice(0,300000)` 截断产生**非法 PNG**，服务端按 `.png` 落盘 → 工作台碎图 | ✅ 超限整张丢弃（宁缺毋坏——快照文本证据才是断言原料）；`executor.ts:442-448` |
| D6 | `Page.createIsolatedWorld` 参数拼写 `grantUniveralAccess`（CDP 正名 `grantUniversalAccess`）——静默被忽略的死参数 | ✅ 改正拼写 |
| D7 | `firstLocateAfterGoto` 语义被 snapshot 步破坏（off-by-one）：`stepsSinceGoto` 对每条非 goto 指令递增，而典型序列是 goto→snapshot(before)→click，首个 click 拿到 1 → 8 次尝试预算 + reload 自愈（注释明言"只保留给 goto 后首个定位"）**永远不生效** | ⏸ 缓修：修好即**激活一条从未被真机验证过的 reload 自愈路径**，可能改变 52 链矩阵行为；须与真机回归轮同做 |
| D8 | Get Items 直调第二拷贝缺 `X-Frappe-CSRF-Token`（`executor.ts:659-691` vs `703-733`）：Frappe 严格模式下第二段必 417/403 然后静默回落 UI 路径 | ⏸ 缓修：同 D7——补上头即激活直调 API 路径（当前实际走的是 UI 回落路径且 100% 通过），需真机验证后再合并双拷贝 |
| D9 | hover-trigger 分支把"只 hover 未 click"报告为 `clicked:true`（label 元素恰在 `.el-dropdown` 容器内时 `inDd.length>=1` 判定极宽）→ 后续步骤在菜单未开的页面上假执行 | ⏸ 缓修：改动直接翻转成功语义，可能让当前"侥幸通过"的链暴露真实缺陷——须真机矩阵轮同做（届时预期会掉通过率，那是正确结果） |
| D10 | `uploader.ts` retries 计数在 SW 内存（SW 被杀即归零 → 无限重试）、idb 无 TTL/上限（deferred 事件永久堆积，server 长期不可达时每 30s 空转一轮） | ⏸ 缓修：需改 idb 记录结构（重试计数 + 首见时间戳写进记录本体）并配迁移式清理，独立排期 |
| D11 | 页内任意脚本可 postMessage 伪造 `skilllens-net` 事件污染自己的录制 | ⏸ 记录：自污染，威胁有限（页面 XSS 已能直接改 DOM）；一次性 nonce 握手进 backlog |

### E 域 工作台（Vue）
| # | 项 | 处置 |
|---|---|---|
| E1 | `SkillGraphView` 视觉回归 blob URL 组件卸载不释放（二轮只修了"覆盖时 revoke"与竞态）→ 长会话反复切流程持续泄漏 | ✅ 补 `onBeforeUnmount` revoke 两个 URL |
| E2 | `payloadSummary` 与 `run-format.assertExpect` 双源且已漂移（`field_change` 分支一份带 `api_template` 一份不带） | ✅ 删除 `payloadSummary`，`assertExpect` 泛化签名（结果行/断言行通用、`api_template` 可选降级）；新建 `tests/run-format.spec.ts` 定版行为 |
| E3 | `ReplayLaunch` / `ReplayRunView` 缺路由参数 watch（SkillGraphView 已加）→ 从 /graph/run/3 → /graph/run/4 不刷新，展示旧 run | ✅ 两页补 `watch(route.params.*)` 重载 + ReplayLaunch 重置表单态；spec 同步 |
| E4 | `api.ts` 类型漂移：`LastRun` 缺 `flaky`（后端 `cards.py:41` 实际返回，模板已消费） | ✅ 补 `flaky: boolean` |
| E5 | `api.ts` 4 处 POST 各复制 15 行"parse detail else 状态行"样板 | ✅ 抽 `send<T>(path, init)` + `jsonInit()`，错误文案与收口前**逐字一致**（不破坏既有断言） |
| E6 | `GraphOverview` 系统色条选择器全部失配（CSS 用短名 `njmind`/`Odoo`，实际 system 值是 `SYSTEM_ORDER` 全名）→ 所有圆点渲染默认灰，分色是死代码 | ✅ 配色收口到 `system-group.ts` 的 `SYSTEM_COLORS` + `systemColor()`，模板内联绑定；新建 `tests/system-group.spec.ts` |
| E7 | `CanvasView` `nodeSeq = nodes.length`：删过节点后 id 不连续（n1,n3）→ 新增节点生成重复 id "n3"（VueFlow key 冲突/边错连）；`onSelectCanvas` 无 seq 守卫 | ✅ `maxNodeNum()` 取现有 id 最大数字后缀 +1；加与 AuditView 同款 `selectSeq` 守卫（含 catch 分支） |
| E8 | `SuitesView.showHistory` 裸调无错误处理，且 history 残留上一套件旧数据 | ✅ try/catch/finally + 换套件先清空 + loading/error 状态（带 `data-testid`） |
| E9 | `FlowGraph` / `ShotGallery` 截图竞态（快速点两个带截图节点，晚到旧响应覆盖且旧 blob 未 revoke；ShotGallery 交错执行互相 revoke 对方 URL → 碎图） | ✅ 两处自增 seq 丢弃过期响应 + 卸载时 `seq += 1` 使晚到响应直接 revoke |
| E10 | 次要：`App.vue` doLogout 死代码、`FieldTypesView` 删除无 confirm（与 SuitesView 不一致）、`AuditView`/`DeltaReport` 独立请求串行 await | ✅ 死代码删除、confirm 补齐、串行改 `Promise.all` |
| E11 | `DeltaReport` 路由参数名 `deltaId` 实际承载 report id；左树"报告"硬编码 `/graph/reports/1`；AdaptersView 绕过 api.ts 直接 authedFetch 且样式不走设计令牌 | ⏸ 记录：命名/风格统一项，与 AdaptersView 接入 api.ts 一起做（避免本轮改动面继续扩大） |

### F 域 脚本与部署
| # | 项 | 处置 |
|---|---|---|
| F1 | `auto_record.py` 的 `NJMIND_DESIGNER_URL`/`HOST` fail-fast 守卫失效：HOST 缺失时拼出 `"http:///mb3/..."` 仍含 `"://"`，守卫永不触发，畸形 URL 直达 `page.goto` | ✅ 守卫改判**来源环境变量本身**是否为空 |
| F2 | `live_browser.py` 凭据不 fail-fast（`cfg.get("NJMIND_USER") or ""` 静默空串登录，缺凭据表现为"表单定位超时"的间接症状） | ✅ 与 auto_record 对齐补 `sys.exit`（报错文案说明为何显式报） |
| F3 | 硬编码 `/tmp`（Windows 依赖盘符解析）+ 会话态落公共临时目录：`njmind_login.py:24` 默认输出 `/tmp/njmind-state.json`（含内网登录 cookie 的 storage_state 明文世界可读）、`auto_record.py:97` `/tmp/skilllens-ext-profile` | ✅ 统一改仓库根相对路径（`.njmind-state.json` / `.ext-profile*/`），`.gitignore` 补 3 条（含 `*.log`——`webhook_receiver.py` 写 `server/webhook_received.log` 此前有入库风险） |
| F4 | `v21_matrix.py`：async 轮次里同步 `httpx.Client` + SQLAlchemy 阻塞事件循环；硬编码 ERPNext 凭据与 `http://127.0.0.1:8090`（同文件 skill_vars 段已从 manifest 读凭据，此处退化）；硬编码录制实例单号；`_ext_id()` 读 manifest 的 **`name`** 字段当扩展 id 拼 `chrome-extension://`（现值必失效） | ✅ 同步 IO 走 `asyncio.to_thread`；凭据统一读 manifest；单号提为具名常量 `ERPNEXT_BASE_QUOTATION` 并注明"绑定特定 demo 库快照"；扩展 id 改从 CDP `/json` 的 `chrome-extension://` 目标**运行时反查**（找不到即 exit 并说明常驻浏览器未起） |
| F5 | `p3_record.py` `urllib.request.urlopen` 未传 timeout（CDP/服务挂起即永久阻塞，`to_thread` 用对了但线程会吊死） | ✅ 统一 `URLOPEN_TIMEOUT = 10` |
| F6 | deploy：端口全网卡绑定（`8710:8710`、8069/8080/8081/8090 均绑 0.0.0.0，内网机器上暴露到局域网）；`server/Dockerfile` 无 `USER`（root 运行且内含 playwright chromium）；`COPY --from=ghcr.io/astral-sh/uv:latest` 不可复现 | ✅ 全部端口加 `127.0.0.1:` 前缀；Dockerfile 建 `appuser` 非 root 运行（`PLAYWRIGHT_BROWSERS_PATH=/ms-playwright` 共享路径 + `/data/artifacts` 预建授权，named volume 首挂载继承镜像内属主）；uv pin `0.8.4` |
| F7 | `crud_chain_test.py`/`deep_chain_test.py` 在 async 函数里用同步 `httpx.get` | ✅ 改 `await asyncio.to_thread(...)` |
| F8 | `except Exception: pass` 共 10+ 处（多为菜单探测类有意 fail-open）；`v21_matrix` skill_vars 的宽 catch 会把"卡片拉取失败"静默降级为换参缺失；CHAINS 硬编码 skill id 绑定活库状态 | ⏸ 记录：宽 catch 处补日志 + CHAINS 注明前置库快照要求，与 v21_matrix 整体重构一起做 |

### G 域 适配器清单
| # | 项 | 处置 |
|---|---|---|
| G1 | URL 通配符匹配：host `*` 编译过宽、query 处理未文档化、同分并列时配对不确定 | ✅ `urlmatch.py`：host `*`→`[^./]*`（不跨点）、path `*`→`.*`、query 剥离语义写进 docstring、新增 `url_match_query` lint、tie-break 确定化 `(-specificity, id)`；`test_url_match.py` +43 行 |
| G2 | 容器 id 直接进 `docker exec` 参数（注入面）；单个清单解析失败拖垮整目录 | ✅ `manifest.py` `_CONTAINER_PATTERN = ^[A-Za-z0-9][A-Za-z0-9_.-]*$` + `probes._check_container`；`load_adapter_dir` 改**逐文件降级**为 `parse_error`（一份坏清单不再让 8 份好清单消失）；`probes` rc≠0 抛错但 stderr 消毒 |
| G3 | `Login` 缺 admin 昵称形态；`steps.py` 用户名/口令互换无检测；`compare_expect` 空观察语义模糊 | ✅ `Login.admin_nickname` 字段；`_looks_like_swapped_user`（`^(?:[ES][L0-9]|M[A-Z])` 形态判定，命中即报"疑似填反"而非静默失败）；`compare_expect` 空观察语义写进 docstring + 测试 |
| G4 | 清单口令 env 注入改造（凭据不落 yaml） | ⏸ 记录：排私有化（本地演示容器凭据与部署默认值一致，非内网机密） |
| G5 | 系统名 → 适配器 id 的兜底配对通道缺失（URL 通配符未命中时无从配对） | ✅ `app/system.py:37` 新增 `SYSTEM_ADAPTER` 映射（与 `HOST_SYSTEM` 同源维护，避免两处漂移） |

## 五、🟢 卫生项（34 项，本轮清 22）

**死代码/漂移（已清）**：`repair.py:159-184` `_label_related`/`_has_cjk`（S43-4 改"只记录不拦截"后遗留）、
`flow_graph.py:90,106` `shot_idx` 赋值后从未使用、`locate.py:300-304` 三元两分支结果相同 + `last` 变量冗余、
`page_snapshot.py:50` `_field_label` 的 `page` 形参未用、`locate.py:289-291` 注释"扩到 8 轮"vs 实际
`range(12)`、`App.vue` doLogout、`executor.ts:1280` `await sleep(0)`、`SkillGraphView.payloadSummary`。

**正确性小修（已修）**：`field_types._gen_id_card` 生日段用 `randint(10000,99999)` 前两位（10-99）大概率非法日期
→ 改月 1-12 / 日 1-28；`resolve_type` 每次全表扫（heal 逐字段调用 O(n·m)）→ 排序 + `limit(500)` 下推 SQL
（同数据同答案，确定性）；`record_success` 的 `scalar_one_or_none` 在同 pattern 多行（manual/learned/llm 并存）
时抛 `MultipleResultsFound`，被 `run_replay` 兜底捕获后**把已 pass 的回放打成 error run** → 改
`order_by(success_count desc, id).limit(1)`。

**记录未改（12 项，附理由）**：`execute_plan`/`execute()` 巨函数与 fill 双拷贝合并（B9/D7-D9，需真机轮）；
`runner.py:26` `STORAGE_STATE` import 时读 env 与同文件"调用时读 env（可测试）"惯例不一致；
`runner.py:358-384` 过度缩进 8 格 + 429 行中嵌大段连续空格（疑似合并残留，纯格式，随重构一起）；
`runner.py:1022` `confirm_side_effect` 形参体内未用（门控已前置）；`goto` 步截图写进一次性 dict 致落盘文件
永不被索引（`runner.py:336-337`，孤儿文件——改动涉及 executed entry 构造顺序，与 B8 同批做）；
`visual.py:62-72` 纯 Python 逐像素 O(w×h)（1080p≈2M 次循环，可 `ImageChops.difference`+histogram）
与 `:53` `result["error"]=str(exc)` 未脱敏（含本地路径）；`assert_eval.py:94` 非 ui_text 断言缺
`api_template` 直接 KeyError、`:162` `value == p["expect_value"]` 类型严格（body int vs 期望 str 假阴性）；
`compile_replay_plan` 仅测试引用生产零调用；`resolve()` 每 frame 每 attempt 建 2 个 isolated world
（8 轮重试下累积 16×frames 个，直到导航才释放）；`popup.ts:75-77` 两处静态 innerHTML（无注入但与
replaceChildren 风格不一）与 `:102` 手拼 URL；`manifest.config.ts:13` `alarms` 0.1 分钟被 Chrome clamp 到 30s
而 `uploader.ts:112` 注释写"6s"（误导）。

## 六、缓修与记录项汇总（34 项，每项附触发条件）

| 项 | 类型 | 缓修理由 | 何时必须做 |
|---|---|---|---|
| executor 路径硬门禁 vs `repair.py` 只记录不拦截 | **设计分歧（本轮新记）** | 两条路径的失败代价不同：executor 侧提案会经 verify/promote 链**晋升进骨架**（幻觉 label 污染是永久的）且白烧介入额度（总额 2）；replay 侧提案只用于本次定位，有确定性 `locate()` 复核兜底 | 若 replay 侧提案也接入晋升链，必须同步上硬门禁 |
| C2 学习轨道未分轨（C5） | 产品决策 | 需"真实流量技能"独立生命周期设计 | 进主计划待用户确认 |
| `skill_id` 无 FK/级联（C7） | 迁移风险 | 现存孤儿行会让加 FK 的迁移失败，需先清洗 | 私有化部署前 |
| `DateTime` 未带 tz（C9） | 横切改动 | 全项目统一 + 一次性迁移 | 出现第一例 tz 相关 bug 时立即做 |
| 服务端二次脱敏（C4） | 取舍未定 | 脱敏后的值无法用于回放注入，会削弱证据可回放性 | 与 C5 一起定 |
| `fieldchange` 只取末对（C6） | 语义取舍 | 末对 = 最终态是有意选择，缺的是审计行 | 出现"早期变更丢失"的实际排障需求时 |
| token 走 URL（A6）/ events 共享 secret（A3）/ login 限速（A5） | 协议与部署改造 | 单机本地工具威胁模型下非边界；一次性换票属协议改造 | 私有化/多用户部署前必做 |
| IDOR / 无所有权作用域 | 设计边界 | 单租户工具，无租户概念 | 多租户化前须补 scoping（已写入 HANDOVER） |
| `execute_plan` / `execute()` 巨函数（B9） | 重构 | 改动面大，需 52 链真机回归支撑 | 与 P1 画像覆盖面提升合并做 |
| D7/D8/D9（插件三处"激活未验证路径"） | 需真机轮 | 修好即激活从未被真机验证过的路径（reload 自愈 / Frappe 直调 API / hover 后校验菜单），可能翻转现有通过率 | 下一次真机矩阵轮**同批**做，并预期通过率变化是正确结果 |
| D10 uploader TTL / B8 page.close / goto 截图归属 | 需真机轮 | 涉及 SW 生命周期与常驻浏览器收尾时序 | 同上 |
| idb 记录结构改造（D10 前置） | 数据迁移 | 重试计数与首见时间戳要写进记录本体 | 与 D10 同批 |
| `conftest.py` 硬编码 `sqlite:///./test.db` | **测试基础设施（本轮新记）** | 并行跑两套 pytest 会互撞（本轮实测：一套跑时另一套出现成片 `no such table: user`） | 需要在 CI 里并行分片时立即改为每进程独立库名 |
| E11 命名/风格统一、G4 口令 env 注入、F8 宽 catch 补日志 | 卫生 | 与各自模块的重构合并 | 顺手做 |

## 七、验证

**三套测试（本轮终态）**
- server：`cd server && uv run pytest -q` → 见下方"基线"（新增 5 个测试文件：`test_schema_drift.py`、
  `test_role_gates.py`、`test_runner_watermark.py`、`test_executor_heal_gate.py`、`test_scheduler.py`；
  另 `test_export.py`/`test_field_types.py`/`test_flow_graph2.py`/`test_outcome.py`/`test_skill.py`/
  `test_replay_plan.py`/`test_runner_browser.py`/`test_url_match.py`/`test_delta_classify.py`/
  `test_adapters_api.py`/`test_adapter_manifest.py`/`test_adapter_probes.py`/`test_step_screenshots.py`/
  `test_events.py`/`test_auth_api.py`/`test_executor_protocol.py` 均有用例增量）
- web：`cd server/web && npm test` → 新增 3 个 spec（`AdaptersView`、`run-format`、`system-group`），
  另 5 个既有 spec 有用例增量
- extension：`npm run build && npm test` → **11 文件 / 99 通过**（基线 83，+16：`redact-parity` 5、
  `executor-injected-regex` 3、`capture-redact` 4、`net-hook` +4）；构建产物 grep 验证转义与词表已进 dist

**基线**：**server 546 / web 78 / extension 99**（全绿；server 全量 20 分钟一轮，
其中 36 errors + 11 failed 系起跑时与另一 pytest 进程共用 `./test.db` 互撞——11 failed
单独重跑 15/15 通过、36 errors 全为 `no such table: user` 撞库特征，lessons #43 记录在案；
修复项均有定向测试先行验证）。已同步主计划 v2.3 条目。

**红线自扫（提交前）**：`git grep 192.168`（空）、`git grep -nE "sk-[A-Za-z0-9]{20}"`（空）、
`git diff --cached | grep -iE "password.*[:=].*['\"][^'\"]{6,}"`（仅测试占位与 `***` 掩码）、
`git checkout -- server/uv.lock`（镜像重写还原）。

**一处测试即规格的最小修正（记录）**：`test_executor_protocol.py::test_executor_intervention_exhausted_fails`
原依赖"LLM 返回任意字符串即被采纳"来耗尽介入额度——这与本轮上的 C1 硬门禁（提案必须逐字出现在证据池）冲突。
按"brief 与测试矛盾以测试为准、最小修正并记录"：给该用例补 `LLM_FAKE_RESPONSE="保存"` 且把首步 label 改为
`"保存旧名"`，构成真实的"按钮改名 → 提案命中页面文本 → heal → 额度耗尽"场景，docstring 已写明修正原因。
另：`test_rejected_proposal_still_counts_intervention` 的首版前提写错（以为被拒提案会重发当前步），
实测不 heal 时 cursor **正常推进**（重发同 seq 返回 `duplicate: True`），已按实际语义重写断言。

## 八、对照表扬（本轮沉淀的正向资产）

- **宪法执行到位且有牙齿**：LLM 全部输出经确定性门禁——`llm_attribute_type` 枚举白名单、repair 提案
  `locate()` 实测验证才 verified、自愈计数只在 run pass 时累加（`runner.py:1169` 注释里的"污染晋升"教训）；
  `generic.py`/`synthesis.py`/`devplan.py` 把 LLM 严格限定为命名/结构化/分解，配确定性回查，回查失败落
  candidate/proposed/draft + notes 不吞（C3）。
- **C3 审计纪律扎实**：`_attempt` 无 DB 写、异常收敛为 error attempt；`_error_run`/finally/
  `_close_ctx_quietly` 保证启动、执行、归因各阶段异常都有落库出口且不掩盖原始结果；`noise_filter`+
  `FilteredWindow` 只标不删；`process_session` 重跑先删派生表再重建；`fieldchange` 幂等。
- **`locate.py` 工程质量高**：两级遍历（强语义全 frame 先行）解决 iframe 同名抢占、`_xpath_str` 引号完备处理、
  结构兜底"唯一命中才用" + 评分 top1/top2 差距阈值的宁缺毋滥设计。
- **token/口令存储姿势标准**：token 仅存 SHA-256 哈希、口令 PBKDF2-100k 加盐、`secrets.compare_digest`
  恒定时间比较、过期 token 命中即删。
- **文件端面三重防线**：adapter_id 白名单正则、step-screenshot 双白名单（正则 ∩ 元数据 files）、
  visual image `which` 枚举——二轮修复无回退，本轮未发现新的任意路径读/写。
- **SQL 层零原生拼接**：全库无 `text()`/字符串拼 SQL，`order_by` 全为静态列表达式（无客户端排序参数）。
- **注释即决策记录**：铁证编号（ERPNext 236 / 若依 258 / 禅道 246）、lesson 引用、S 编号考古遍布全库——
  本轮 5 个 🔴 里有 4 个是靠"注释声称的语义 vs 实现"对不上而定位的，这套可追溯性本身就是资产。
- **`page_snapshot` 与插件端红线逐字段对齐**（同词表、≤50 字段/≤1024 字符、密码框整体跳过）。
- **竞态守卫模式（seq 单调递增）**已在 AuditView/SkillGraphView/TimelineView/FlowGraph/ShotGallery/CanvasView
  六处规范落地（本轮补后三处）。
- **v21_matrix 的"点击前快照 run id + 纯 DB 轮询对账"**设计规避了 Playwright attach 断连竞态。

## 九、测试覆盖缺口（本轮补 21 处，仍缺 14 处）

**本轮已补**：schema 双向漂移（列 + 索引）、viewer 写端点 403 矩阵、confirm 冒充、写水位纯函数 + 带 GET 噪声的
提交拦截、导出脚本与 assert_eval 判定一致性、状态机跨 field 同值冲突、快照 iframe 场景、字段类型三处
（身份证日期合法性 / resolve_type 有界扫描 / record_success 多行）、畸形 JSON 条目（classify + outcome）、
重复 observed 值、调度循环夜间失败存活 + stop 取消 + 默认 off + next_run 跨日、events 批量 413、
login 计时抹平、executor 提案硬门禁 4 例（页面文本命中 / 表单 label 命中 / 幻觉拒绝 / 基础设施错误串拒绝）+
被拒仍计额度、脱敏词表四处一致、注入表达式转义扫描、文档 URL 脱敏、net-hook 失败调用留痕、
掩码回填往返 + 显式改写优先、AdaptersView select 失败不写错系统、run-format/system-group 纯函数定版。

**仍缺（按风险排序）**
1. `executor.ts`（1,549 行）仍近乎零直测：resolve 候选 JS builder、fill 表达式 builder、label 归一化都可抽纯函数
   ——本轮只加了"源码级"守卫（转义扫描），行为级仍无。
2. `uploader`：eventKey 碰撞、retries 超限丢弃、deferred 回写路径。
3. `idb.takeEvents` 批量边界（恰好 batch 条 / 空表）。
4. `executor-page` 参数解析（`skill=NaN`、`fill_` 提取、`auto=1`）。
5. `flow_runner.execute_flow` 的 `shared_ctx`（CDP）路径无用例（C1 门控与失败收敛有）。
6. `fieldchange.extract_field_changes` 无专属测试（仅 `test_fielddiff` 覆盖原语）；>2 次 POST 只取末对的行为无测。
7. `discovery.sync_discoveries` 跨会话累加幂等（A→B→重跑 A）与 `_find_row` 的 api vs 纯 UI 分支。
8. `alignment.collect_window_params` 的 consistent/inconsistent/None 三分支。
9. `variables.param_variables` 中 `window_seq >= len(windows)` 越界跳过分支。
10. `synthesis.verify_steps`/`collect_evidence` 的 `system_hint` 前缀过滤（跨系统证据隔离）。
11. `impact._template_to_actions`/`_anchor_to_actions` 的裸模板 vs 方法前缀双形态匹配。
12. "过期 token 访问受保护端点 401 且 DB 行被清"的 API 级用例（单元级已有）。
13. 无测试的视图/组件：GraphOverview、GraphWorkspace（左树/搜索/折叠）、LearningGraphView。
14. `visual.py` 比对与 `assert_eval` 的边界（缺 `api_template`、int vs str 期望值）。

## 十、本轮之后必须记住的四条（已入 `docs/references/project-lessons.md`）

1. **模型加列必须同批写迁移**：`create_all` 建表的测试恒绿，而全新 `alembic upgrade head` 部署必崩——
   守卫只能是"跑真迁移再比 metadata"（列与索引都比）。
2. **结构性/源码扫描测试必须自带非空守卫**：断言"没有坏模式"的测试，在实现改名后会静默恒绿。
3. **注入页内 JS 的模板串转义会少一层**：写在反引号里的 `\s` 到页面就成了字面 `s`；所有注入转义一律双写，
   并配扫描测试。
4. **同一份安全词表若不得不存在多份物理副本，就必须有一份跨文件一致性测试**；
   **脱敏回显必须配掩码回填**，否则"安全修复"本身会在第一次保存时销毁凭据。
