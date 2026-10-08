# 服务端回放/执行引擎（Replay Engine）架构

> 2026-10-08。基于当日代码逐行核实撰写；所有 `file.py:NN` 引用以
> `server/app/replay/` 为默认目录（API 层写全路径）。配套阅读：
> `docs/arch/extension-executor-protocol.md`（插件执行器，微指令协议对偶）、
> `docs/arch/2026-10-07-platform-interaction-profile.md`（交互画像）。
> 文中 Sprint 标记（S24/S37/S42/S43 等）与代码注释同源，指向实测根因。

## 1. 职责与全链路位置

一句话：把归纳出的 Skill（骨架+断言）在真实浏览器里确定性地重放一遍，
产出可审计的 ReplayRun（计划/逐步结果/断言判定/归因/截图），并在定位失败、
字段校验失败时走受控自愈。

```
录制(extension) → 学习(ingestion/alignment/induce) → Skill+OutcomeAssertion
  → 回放/执行【本模块】 → 证据(observed/snapshot/screenshot/toast)
  → 断言评估(assert_eval) → 终态落库(ReplayRun)
  → 自愈(repair 提案 / field_types 换值 / flaky 重试) → 晋升(supersede 新版本)
```

两条执行通道共用本模块的计划编译与断言判定：
- **服务端通道**：Playwright 直驱浏览器（`runner.py`），入口 `POST /api/v1/skills/{id}/replay`（`server/app/api/replay.py:30`）。
- **插件通道**：服务端只编译微指令+判定，浏览器操作在用户 Chrome 内（`server/app/api/executor.py`，协议见 extension-executor-protocol.md）。

宪法约束落地：C1 shadow 门控在开浏览器之前（runner.py:1222-1241）；C3 失败/异常也落 run（runner.py:1114-1123、1210-1219）；LLM 只做归因/提案/字段分类，判定全确定性（runner.py:1188-1203、repair.py:1-6、field_types.py:192-199）。

## 2. 模块地图

| 文件 | 职责 | 关键入口 | 直测 |
|---|---|---|---|
| runner.py (1311 行) | 浏览器生命周期、逐步执行、证据采集、终态编排 | `run_replay` / `run_replay_batch` / `execute_plan` / `_attempt` / `_execute_skill` | test_runner_browser / test_runner_watermark / test_step_screenshots / test_flaky_rerun / test_replay_failure / test_replay_headless |
| locate.py | 多信号语义定位链 + 结构兜底 + 评分兜底 | `locate` / `_try_locate` / `_scored_fallback` | test_runner_browser（定位系列） |
| plan.py | 事件流+骨架 → 可执行计划；C1 写方法判定 | `compile_skeleton_plan` / `requires_confirmation` | test_replay_plan |
| repair.py | 定位自愈提案：LLM 提案→locate 实测→晋升 supersede | `generate_proposals` / `load_repair_map` / `record_usage` | test_locate_repair / test_heal_supersede |
| assert_eval.py | 断言评估（服务端判定的唯一实现） | `evaluate_assertions` / `path_matches` | test_assert_eval / test_jeecg_chain_override |
| export_shared.py | 导出脚本判定逻辑单一事实源（被逐字内嵌） | `judge_api_status` / `judge_state_signal` | test_export |
| exporter.py | skill/flow → 自包含 Playwright 脚本 | `export_playwright` | test_export / test_flow_export |
| page_snapshot.py | 回放侧 UI 快照（forms/labels/tables/toasts）+ 脱敏 | `collect_page_snapshot` | test_runner_browser / test_step_screenshots |
| field_types.py | 字段类型知识库：校验/生成/LLM 归因 | `resolve_type` / `generate_value` / `record_success` | test_field_types |
| flow_graph.py | run/skill/学习链 → 流程图；业务状态派生 | `derive_states` / `build_run_flow` | test_flow_graph2 |
| flow_runner.py | 合成流程执行（复用 runner 浏览器入口） | `execute_flow` | test_flows |
| visual.py | 视觉回归（dHash+像素差，无 LLM） | `compare_images` / `dhash` | test_visual / test_visual_baseline |
| resolver.py | locate 策略矩阵 → 插件端候选序列+JS | `compile_resolve_candidates` / `build_resolver_js` | test_resolver / test_executor_protocol |
| server/app/api/replay.py | REST：replay/batch/run 查询/流程图/步骤截图 | `replay` / `get_step_screenshot` | test_replay_api |
| server/app/api/executor.py | 插件执行器端点：plan/step/finish | `compile_executor_plan` / `executor_step` | test_executor_protocol / test_executor_heal_gate |

## 3. 一次回放的完整时序（POST /skills/{id}/replay → ReplayRun）

1. **API 前置**：skill 不存在 404；`status == "superseded"` 409 指向新版本（api/replay.py:33-36）。写守卫 `WRITE_GUARD` 挂路由（api/replay.py:30）。
2. **C1 shadow 门控**（runner.py:1244-1248 → 1222-1241）：骨架任一窗口签名含 `POST:/PUT:/PATCH:/DELETE:`（plan.py:212-218）且未 `confirm_side_effect` → 编译计划后直接落 `mode=shadow, status=shadow` 的 run，**不启浏览器**（Sprint 4 验收语义）。
3. **浏览器启动**（runner.py:1253-1263）：整体在 `async with _launch()` 内——S13 曾把执行移出 with 块导致必 error（注释 runner.py:1250-1252）。三个环境变量分发：`REPLAY_HEADLESS`（默认无头，runner.py:40-42）、`REPLAY_CHANNEL=chrome` 用真 Chrome（45-47）、`REPLAY_CDP_URL` 连常驻浏览器（50-52）。CDP 模式复用 `browser.contexts[0]`（带登录态与插件，66-70）并置 `shared_ctx=True`——收尾时不关该 context（1026-1027、804-812）。
4. **计划编译**（runner.py:1041-1048 → plan.py:53-209）：取 `alignment.session_ids[0]` 参考会话的 RawEvent 按 (ts,seq) 排序，`compile_skeleton_plan` 只编译骨架窗口锚点步（详见 §4 前的小节 plan 语义）：
   - 骨架 click 步：`session_window_seqs[ref_sid]` 指向窗口的 anchor；healed label（自愈晋升回写）优先于录制 label（plan.py:104-106）；`⟨dyn⟩` 占位还原为参考会话原始 label（108-111）；空 label 步丢弃（112-115）。锚点匹配用**对象身份** `id(a)`——ts/seq 可能重号（122-128）。
   - input 步按参考会话**事件时序**交错插入锚点之间（S34：Odoo 表单在锚点点击后才出现，一律前置必定位失败，plan.py:56-63、166-183）；S42-7 录制到的 input 全部进步（常量字段缺失会被表单校验拦，168-171）；值优先级 overrides > 录制原值。
   - navigation 事件按时间序插 goto 步：首航由 `plan.url` 承载只记 seen；去 hash/query 的路径级变化才插；Frappe 一次性草稿 URL `/desk|app/{dt}/new-{dt}-{随机}` 归一化为 `/app/{dt}/new`（144-165、29-50）——归一化 URL 进 plan，原始 query 可能带会话 token 不得持久化（161-164）。
5. **断言准备**（runner.py:1052-1062）：ui_text 断言的期望值若命中 overrides 键则跟随换参值（否则换参必 FAIL，语义错误，1056-1062）。
6. **单次尝试 `_attempt`**（runner.py:879-1027，无 DB 写，异常收敛为 error attempt 不上抛）：
   - 开 context/page → `goto(plan.url)` → before 快照（page_snapshot.py）→ 起始页截图+步骤截图目录（fail-open：替身无 screenshot 能力则整轮不采，899-910）。
   - `execute_plan` 逐步执行（§3.1），`awaited_templates` 取断言的 `api_template` 清单（913-915）。
   - after 快照 → 定位失败步（error 含 "semantic locate failed"）触发 `generate_proposals`（页面还开着可 locate 实测；提案生成失败 fail-open，921-936）。
   - `evaluate_assertions`（§5）→ 状态判定：无任何 ok 步 = error；断言全过 = pass；否则 fail（942-948）。
   - **S42-7 说真话门**：pass 但最后一个带 validation_errors 的步在最后一个 ok 步之后 → 改判 fail（校验拦截是确定性证据：业务动作没发生；S43-4 时序豁免只拦"错误是最后状态"，949-964）。
   - 视觉回归（S22）：无基线且 pass → 建基线（run 落库后补 VisualBaseline 行，1161-1172）；有基线 → dHash 初筛+像素差比对追加断言（visual.py:40-75）；**换参回放时视觉差异记录不判定**（预期行为，消假阴性，989-994）。
   - fail/error 时在 ctx 关闭前截全屏+取 page.title（999-1006）。
7. **`execute_plan` 逐步执行**（runner.py:260-801）——引擎主体：
   - 证据监听：`on_request` 记时刻、`on_response` 同步壳内 `create_task` 收 `{url,status,method,body[:8192],latency_ms}`（Playwright 对 async 回调支持不稳，307-324）。
   - toast 轮询 `_poll_toasts`（S37：toast 瞬态，after 快照必错过；轮询 12 类常见容器，S43-4 提升到循环前——写等待窗口也要轮，275-305）。
   - 步循环三 kind：goto（337-344）/ click（345-608）/ input（609-748）；任一步失败后剩余步记 `not attempted`（329-331）；日期控件 Enter 提前提交表单 → `early_submitted`，剩余步记 skipped、判定交断言（332-335、725-734）。
   - click 步要点：定位走 `_locate_with_repair`（160-192：locate 失败先 3×500ms 短重试再查 repair_map）；row-trigger 行内点击（359-391，行锚优先级 row_anchor_hints > labels 宿主行文本，须含 ASCII alnum 防纯中文提示误判）；写类按钮 intercept+wait（§6）；checkbox 走 `_check_row_checkbox` 降级链（73-148：force-check → 原生 el.click → force-click，每级核实 `:checked`；Frappe 官方 harness 模式——不直写 checked 防污染写水位基线，138-140）；普通 click 超时降级 force（重渲型 UI stability 等待超时，510-516）；点击后探测表单校验错误（fail-open 记录不判定，526-534）；写请求在途等待 ≤8s（ERPNext map_docs 2-4s，575-593）+ SPA 跳转等加载（598-606）。
   - input 步要点：`[REDACTED]` 脱敏值跳过不回填（609-615）；类型守卫——命中不可填元素时按 `input[data-fieldname=]` 等重定位（624-640）；select2 开容器→搜索→点选项（649-679）；原生 SELECT 走 select_option（680-682）；普通 fill 三轮重试：fill+End 键（Frappe 搜索框监听 keyup，684-693）、modal 内 0 行时重发 input 事件（React setter，694-711）、统一补 Enter（Frappe 行内编辑 fill 不提交值，721-724）、读回验证防水合回写（njmind 实测，641-643、735-739）；读回失败抛"输入被页面回写覆盖"（742-743）。
   - 失败步附现场文本证据（url 尾 60 字符+可见按钮文本 ≤14 个——截图不可机读，归因需确定性 DOM 摘要，752-768）。
   - 收尾：`awaited_templates` 全命中即止，否则等满 settle_timeout（只认步骤后新到达的响应——S42-12 模板可能已被步前页面加载命中，769-790）；按模板聚合 API 延迟中位数（791-799）。
8. **重试编排 `_execute_skill`**（runner.py:1030-1207）：
   - 字段自愈重试（S42-7）：fail 且有 validation_errors → `_heal_plan_inputs` 按类型知识库换值（只改"类型可判定且当前值不合法"，宁缺毋滥，815-846；同类型共享生成值——密码/确认密码必须一致，823-824）；规则全不命中 → LLM 归因字段类型（层 3，854-876）再走确定性生成；重试 pass 才采纳并 `record_success` 反哺知识库（1087-1099）。
   - flaky 重试（S24）：仍 fail 且 `REPLAY_FLAKY_RERUN=1`（默认开）→ 原 plan 重跑一次；pass 标 `flaky=True`，首次失败明细嵌 `plan.first_attempt`（C3 审计，1100-1112）。
   - 执行阶段异常 → 落 error run，attribution 经 `sanitize_error` URL 脱敏（安全红线，1114-1123）。
9. **落库与终态**：plan 旁挂 before/after_snapshot、api_latencies、business_states（flow_graph.derive_states 从响应体 status/state/code/docstatus 确定性派生，flow_graph.py:50-66）、step_screenshots 清单、first_attempt/field_healed（1130-1150）→ 写 ReplayRun（mode=execute，1151-1156）。
10. **自愈计数与晋升**：`record_usage` **只在 run 整体 pass 时**计数——S43-1 实证：状态依赖失败下 LLM 会从空状态页选出无关元素且 locate 验证通过，失败运行反复计数会把垃圾提案晋升成污染技能（1174-1180、repair.py:82-98）。verify_count ≥ `LOCATE_AUTO_PROMOTE_N`（默认 3）→ promoted → `_apply_proposal_version` 走 supersede 链：拷贝当前活跃 skill、骨架打 healed label（按签名锚点 `type:label` 匹配，repair.py:101-112）、断言复制、version=max+1、旧行 `status=superseded` + `superseded_by` 指向（repair.py:115-157）。
11. **LLM 归因**（fail/error 才调）：prompt=页面标题+失败步+失败断言，限 100 字中文（1188-1196）；归因调用失败不再落重复 error run（S42：异常上抛会二次计数，1197-1203）；截图路径进 `artifact_path`（1204）。

批回放 `run_replay_batch`（1269-1311）：一次 launch 逐 skill 串行；shadow 项前置落库，全 shadow 批次零 launch；单 skill 异常不中断批次。

## 4. 定位链（locate.py）

三层递进，全部确定性；每层失败才进下一层。

**层 1：语义策略矩阵 × 两级 frame 遍历**（`locate` 12 轮 × [label, *labels]，locate.py:291-299；12 轮≈11s 覆盖 ERPNext Submit 写后重渲 ~4.5s 实测，5 轮不够）。frame 遍历分两轮（14-29）：
- 第一轮 strong_only：全 frame 只找可见 `[title=label]`（排除 sidebar/navbar/nav-link 导航容器；fill 场景整轮跳过——grid 单元格 div 也带 title，41-67）。根因：禅道 iframe 图标操作 `a[title=执行]` 与顶层菜单文本"执行"同名，按 frame×策略全序遍历主 frame 的 text 会抢先命中，点错导航走错页（35-39）。
- 第二轮全策略按序（69-199）：role-button 精确名（子串匹配会抢——"保存模板" vs "保存"，70-73）→ form-group-control/native（>3 字符才启，短 label "on" 子串误命中任何含该文本的表单组，75-98）→ select2-by-name → title-attr(XPath 排导航) → menuitem（裸 text 会中侧栏同名导航，118-122）→ text（排 tooltip/aria-hidden/导航，123-132）→ placeholder 精确 → el-select 容器 → label → id → name-attr → data-fieldname（先 typed 后 any——包装 div 同带该属性且 DOM 序在前，150-156）→ input-value（布尔 label 走 list-row-check 行内框，表头全选框语义不同，157-166）→ role-button-substr（词边界 regex：多词整名锚定 'Get Items' 不吃 'Get Items From'，中文子串即语义，167-173、394-412）→ select2 表单组 → 必填星号剥离的 cgf-item/form-item-bare（181-189）。
- fill 场景（prefer_controls）重排：placeholder→label→name-attr→data-fieldname→id→input-value→role-button→text（控件优先——Frappe 把字段名渲染成可见帮助文本，text 会抢先命中不可填节点，190-200）。
- 单候选命中裁决（201-246）：可见优先、enabled 优先（若依受保护行按钮 disabled）、活动加载态（仅 is-loading/spinning——禅道 load-indicator 是常驻 class 会永久拦截）视为未就绪跳过、多可见时开放模态内优先（ERPNext 列表 Save 与模态 Save 同名同可见——用户交互上下文在模态，通用 UI 原则）。
- XPath 字符串经 `_xpath_str` 处理引号（XPath 1.0 无转义，含 `'` 用 concat 拼接，4-11）。

**层 2：结构兜底**（300-313）：采集侧 path 祖先链 + ordinal nth-of-type，**count==1 且可见才用**——结构路径跨版本极脆，多命中意味着歧义，宁缺毋滥交给层 3/失败。

**层 3：评分兜底**（Healenium 式，314-321、325-391）：页内 JS 一趟对可交互元素多信号打分（text/value/name/id/placeholder/title/aria 精确 +5，长 label 子串 +3，tag +1，开放模态 +2，可见 +1）；**top1 ≥ 5（至少一个强信号精确命中）且 top1−top2 ≥ 2（消歧）才命中**。两个阈值都是"宁缺毋滥"：定位错误的代价（点错按钮提交错数据）远高于定位失败的代价（步骤 fail → 提案/归因链兜底），实测消歧对象是 'on' 误中 party_name、'Get Items' vs 'Get Items From' 这类前缀/子串歧义（315-317、368-369）。

全链失败抛 `LookupError("semantic locate failed: ...")`——该字符串是 `_attempt` 识别"定位失败步"送提案链的约定标记（runner.py:925-928）。

## 5. 写请求水位与"预拉放行"

- **判定来源**：Frappe 官方 Cypress save 命令 = intercept+wait（S43-4 成熟 harness 对照，runner.py:392-395）——写类按钮点击后等写响应到达；超时未达 = "提交被拦"判失败，拦截文案（collect_validation_errors）进 error 供归因（561-574）。POST 是否发出是普适判据，toast 文案只是归因证据。
- **写类按钮识别**（399-405）：label 归一化（小写去空白）后，子串含 save/submit/确认/保存/提交，或整名 ∈ {getitems, yes, create}。整词匹配防 "Get Items From"（开菜单）命中 "getitems"（确认动作）。
- **两步提交豁免**（407-416）：下一步 label 是确认词（yes/确定/ok/是/getitems/create）→ 本步不判写（Submit 只开确认弹窗，写请求由 Yes 步发出）。
- **基线**：`write_base = len(observed)` 必须在点击前取——点击到判定窗口内请求可能已完成入列（395-397、415-416）。
- **`write_response_count`**（30-33）：水位只数 `method ∈ (POST,PUT,PATCH)` 的响应。**为什么不数 observed 总条数**：页面加载/轮询的 GET 噪声会抬高水位——被前端校验拦下的提交（无 POST）在总数比较下会被误放行成 pass。直测：test_runner_watermark.py 四例 + `test_execute_plan_intercepted_submit_fails_despite_get_noise`。
- **预拉放行 `recent_write_mark`**（279-281、555-560、594-597）：非写按钮交互（如勾选行）可能触发框架写请求（Frappe run_doc_method 预拉）；每个点击步的 8s 在途窗口结束时把当前写响应计数记入 `recent_write_mark`。后续写按钮点击无新请求、但全局写计数已高于该水位 → 视为"业务动作已由前一交互发生、框架去重"，放行不判拦截。直测 `test_execute_plan_prefetch_write_releases_later_button`。
- 点击前还会断开页面里的 `__sl_cb_lock` MutationObserver（538-543），防自身观察锁干扰。

## 6. 自愈与提案：两条路径的刻意分歧

| | executor 路径（插件，api/executor.py） | replay 路径（服务端，repair.py） |
|---|---|---|
| 触发 | 插件上报 `result=miss`（当轮介入） | `locate` 抛 LookupError 后 `_attempt` 收集失败标签 |
| LLM 输入 | 插件证据 `page_texts + form_labels`（370-377） | 服务端现场 `collect_page_snapshot` 的 labels+forms（repair.py:42-50） |
| 幻觉门禁 | **硬门禁**：提案必须逐字出现在本轮证据池，否则 `status=rejected / strategy=not_on_page` 落库留痕、**不 heal**（388-398）；基础设施错误串（"Token额度"等 HTTP 200 形态的网关报错）同样不采纳（380-391） | **只记录不拦截**：`proposed not in pool` 仅打 warning 日志（repair.py:55-64） |
| 采纳判据 | on_page → 重编译候选、cursor 回退、healed 指令随响应下发重试当前步；**不写回 plan.executor_instructions**（跨轮污染实证，400-408） | 确定性 `locate(page, proposed)` 实测：命中 → verified，未中 → 停留 proposed 不参与回放（repair.py:66-71） |
| 额度 | 每 run 2 次；**计数先行**——LLM 不可达/提案为空也占额度（介入是"尝试"，超限判 fail 不依赖网关可用性，363-365）；用满再 miss → run=fail 留下轮跨 run 自愈（412-421） | 无当轮额度；同 skill+step_label 已有活跃提案仍失败 → 跳过重生成（提案已失效，repair.py:31-40） |
| 晋升 | promoted 提案在 plan 编译期注入（**只取 promoted 不取 verified**——269 实证 verified 可能错配：'保存'→'请输入表名' 验证命中的是搜索框，注入后保存步永久改错，executor.py:210-227） | `record_usage` 计数（仅 run pass，§3 第 10 步）≥N 自动晋升走 supersede |

**分歧理由**（两处代码注释均明写）：executor 侧证据池是插件一次性上报的快照文本，服务端无法复核——幻觉 label 照单采纳 = 白烧一次介入额度（总额 2）+ 污染提案库（verify/promote 链会把不存在的 label 晋升进骨架），所以硬门禁（executor.py:388-390）。replay 侧页面还开着，提案要过**确定性 locate 实测**才生效（宪法：LLM 只提案，判定确定性），幻觉提案自然停在 proposed；而 snapshot 池在不同采集层结构下覆盖面不同，硬拦截会误杀合法同义改名（'保存'→'提交表单' 无词重叠但真实存在于页面），故只记日志交人工 reject 流程（repair.py:55-58）。直测：test_executor_heal_gate.py 五例（含 rejected 仍计介入额度）、test_locate_repair.py 六例（unverified/rejected 提案不被 load_repair_map 使用等）。

## 7. 导出脚本与服务端判定同源

`GET /api/v1/skills/{id}/export/playwright`（api/export.py:24-32）生成自包含脚本。**为什么不能 import**：生成脚本必须零 SkillLens 依赖独立运行；判定逻辑若手抄副本必漂移（评审#1：曾四处漂移）——导出脚本与工作台 PASS/FAIL 不一致会击穿"确定性可审计"的产品主张（export_shared.py:1-16）。机制：`inspect.getsource(export_shared)` 把模块源码**逐字内嵌**进模板（exporter.py:21、43-46），只允许标准库依赖。test_export 以 assert_eval 为基准 import 两侧比对 `_ID_SEGMENT` pattern 与判定行为（test_export.py:142-173）。

已内嵌同源的判定：动态 id 段归一（`_ID_SEGMENT`：纯数字/36 位 UUID/≥16 位 hex，assert_eval.py:7）、`path_matches`（{id} 通配+query 忽略+静态段序列相等，assert_eval.py:21-25）、api_status **全部**等于期望（混合 200+500 判 FAIL）、state_signal 取最后一次**写响应**终态 + 空 body code 回退 HTTP status（export_shared.py:52-73）。

导出脚本的 locate 是全策略链的 5 策略子集（role→text→placeholder→label→id，exporter.py:57-80）——docstring 明示"导出脚本定位失败不代表工作台回放失败"（不伪造能力边界）。ui_text/field_change/visual 断言以注释标注"工作台侧判定"（52）。

**模板注入防护**（评审#2）：skill.name/flow.goal 是 LLM 产物或用户输入，原样内插 docstring 时 `'''`/换行可截断三引号把任意语句注入用户将要执行的脚本；`_safe_doc_text` 折叠空白+转义反斜杠与双引号（exporter.py:24-29），test_export 用 AST 断言无活语句（test_export.py:176-209）。

## 8. 快照与脱敏（page_snapshot.py）

- schema 与插件 Snapshot 对齐：`{phase, ts, forms[{label,value}], labels[{text}], tables[{label,rows}], toasts?, overflow?}`（1-9）。
- **frame 遍历**：`_iter_frames` 主 frame 经传入 page 对象本身（测试替身以 query_selector_all 拦截模拟 detach）+ 全部子 frame（72-83）。评审#6：iframe 架构应用（禅道综合页）不走 frame 遍历则 forms/labels/toasts 全空——ui_text 断言静默跳过、toast 通道失效、修复提案池为空。frame 销毁（导航竞态）逐 frame 容错跳过（96-97）。
- **限额是全局总量非逐 frame**：MAX_FIELDS=50（溢出置 `overflow=True` 停止采集）、MAX_VALUE_CHARS=1024、MAX_LABELS=20、MAX_TABLES=10、toasts ≤3 条×100 字符（17-22、86-126、129-154）。直测 `test_snapshot_caps_global_across_frames`。
- **密码框整体跳过**：`type=password` 连 label 都不落（105-106）；其余字段值按 label 匹配敏感词表打 `[REDACTED]`（51-52）；toast 文本含敏感词整条丢弃（152-153）。
- **词表四处物理副本**：TS 主表 `extension/src/shared/redact.ts` + MAIN world 纯 JS `net-hook.js` + `executor.ts` 页内快照 + server `page_snapshot.py:27-31`（CRXJS 原样复制 injected/*.js 无法 import TS，只能靠跨文件断言兜漂移）——一致性由 `extension/src/shared/redact-parity.test.ts:29-47` 守护（含中文词覆盖与去重检查）。`config.PII_PATTERNS`（env）可追加私有化部署自定义词（34-45）。
- label 兜底链与采集端 describe-element 同源：aria-label → placeholder → title → 累积文本截 100（55-69）；元素 detach 返回 "" 不抛。

## 9. 失败与资源清理路径

| 场景 | 处理 | 位置 |
|---|---|---|
| 启动/计划编译异常 | `_error_run`：status=error、plan=None、attribution 经 `sanitize_error` URL 脱敏（异常常内嵌目标系统地址——安全红线） | runner.py:1210-1219、1264-1266 |
| `_attempt` 内任意异常 | 收敛为 error attempt（error_text 截 500），不上抛 | runner.py:1016-1024 |
| 执行阶段异常（attempt.error_text 非空） | 落 error run 后 return（C3 执行审计不可缺） | runner.py:1114-1123 |
| context 关闭 | `finally` 中 `_close_ctx_quietly`——替身无 close 跳过、关闭异常吞掉不掩盖已落库结果；**shared_ctx（CDP 常驻）不关** | runner.py:804-812、1025-1027 |
| browser 关闭 | run_replay/batch 的 `finally` 中 close，异常吞掉 | runner.py:1258-1263、1304-1308 |
| 归因 LLM 失败 | attribution 记"归因调用失败"+脱敏异常，**不**把 fail run 变重复 error run | runner.py:1197-1203 |
| 步骤级失败 | 后续步 not attempted；失败现场文本+截图随 entry 落库 | runner.py:328-331、752-768 |
| 插件通道 run 卡死 | `_reap_stale_runs`：running >10min（判据=last_step_at 非 created_at）→ lost，在 /executor/skills 访问时顺带收割 | api/executor.py:43-72 |
| 插件 goto error | run=fail + 脱敏 attribution，不让后续步在错误页假执行 | api/executor.py:424-433 |

截图证据链：起始页 start.png + 每步 step-NN.png（成功失败都拍——失败画面是归因关键证据，runner.py:195-205）；出图端点白名单双校验（文件名 regex ∧ plan.step_screenshots.files）防路径穿越（api/replay.py:91-108）。

## 10. 已知债务与缓修项（均代码确证）

1. **execute_plan 巨函数**（runner.py:260-801，~540 行）：click/input 两分支各自内嵌 checkbox 降级链、select2 流程、写水位判定、水合重试——多次 S43 补丁叠加，圈复杂度高；直测靠替身 page 但分支覆盖不全（§11）。
2. **locate 策略矩阵三份副本**：locate.py（服务端 Playwright 版）、resolver.py（插件候选编译版，注释自认"语义强度序同源"但选择器形态不同）、exporter.py（导出 5 策略子集）。resolver 有 parity 测（test_resolver.py `test_resolver_locate_parity_on_real_page`），exporter 子集明示不等价；但 locate.py 新增策略需人工同步 resolver——无机械守护。
3. **判定逻辑双实现**：assert_eval.py（服务端）与 export_shared.py（导出内嵌）靠 test_export 行为比对守护，非同一份代码；且 export_shared 的 `judge_state_signal` **未含** assert_eval 的三条"记录不判定"通道（`_DYNAMIC_EXPECT` 动态期望值、行上下文 context、map_docs 等价通道，assert_eval.py:95-104、125-133、154-161）——换参/动态 id 场景导出脚本可能比工作台更严（FAIL vs pass）。
4. **goto 步截图孤儿**：runner.py:343-344 先 `executed.append({**step,"ok":True})` 再对**另一个临时 dict** 调 `_shot_step`——screenshot 键写在丢弃对象上，goto 步截图落盘但不进 `plan.step_screenshots.files`，白名单端点取不到（click/input 步传同一 entry 对象无此问题）。
5. **死代码 NameError 守卫**：runner.py:382-386、520-524 对 `entry_pending_note` 包 `except NameError`——该变量在 execute_plan 作用域 282 行必已定义，异常分支不可达。
6. **`_locate_with_repair` 重试叠加**：locate 本身 12×1s，失败后外层再 3 轮完整 locate（runner.py:179-187）——最坏 ~48 轮/44s 单步定位耗时，无总量预算。
7. **runner.py:436 排版损伤**：`prev.get("value")` 与 `len(...)` 间大段空格续行（语义正确但易误读）。
8. **`_execute_skill` 的 `confirm_side_effect` 形参未使用**（runner.py:1030-1032）——shadow 门控已在上游 `_shadow_run_if_gated` 完成，参数残留。
9. **toast 断言永不 FAIL**：state_signal/toast 两通道均未观察到 → passed=True+skipped（assert_eval.py:110-124，设计选择"瞬态性本质不产生假阴性"，代价是 toast 层断言只有正证据无负证据）。
10. **flow_graph.build_run_flow 断言节点分叉**：`prev` 在 assert 循环内不推进（flow_graph.py:116-127），全部断言并列挂链尾——注释明示"从链尾分叉"，是有意行为但读代码易误判。

## 11. 测试覆盖地图

| 行为 | 覆盖 | 位置 |
|---|---|---|
| execute_plan 定位/水合/toast/校验错误/select/select2/日期 Enter/晚到内容重试 | ✅ 替身 page | test_runner_browser.py（30+ 例） |
| 写水位：GET 噪声不计数、拦截提交判 fail、预拉放行 | ✅ | test_runner_watermark.py、test_runner_browser.py 末二例 |
| locate 策略：多 label/enabled 优先/结构兜底/title/form-group/loading 跳过/select2/评分消歧 | ✅ | test_runner_browser.py locate 系列 |
| 提案闭环：生成→verified→使用→pass 计数→晋升 supersede；unverified/rejected 不用；fail run 不计数 | ✅ | test_locate_repair.py、test_heal_supersede.py |
| plan 编译：骨架步/overrides/时序交错/goto 归一化 URL/C1 写方法 | ✅ | test_replay_plan.py（11 例） |
| 断言语义：api_status/state_signal 终态写/ui_text 消费跳过/toast 双通道/行上下文/动态期望值 | ✅ | test_assert_eval.py、test_jeecg_chain_override.py |
| 导出：独立子进程真跑 PASS/FAIL、判定同源比对、模板注入 AST 断言 | ✅ | test_export.py、test_flow_export.py |
| 步骤截图：采集/清单落 plan/fail-open/iframe 快照/全局限额 | ✅ | test_step_screenshots.py |
| executor 协议：指令编译/seq 幂等/介入超限/聚焦步豁免/finish 重判/row-anchor 换参 | ✅ | test_executor_protocol.py（9 例） |
| executor 幻觉硬门禁：page_texts/form_labels 采纳、幻觉拒绝、基础设施错误串、rejected 计额度 | ✅ | test_executor_heal_gate.py（5 例） |
| 失败路径：fail 归因/pass 不归因/执行异常落 error/归因失败不重复 error/脱敏 | ✅ | test_replay_failure.py |
| flaky 重试、headless/channel/CDP env 分发、字段类型库、resolver parity、visual 比对 | ✅ | test_flaky_rerun / test_replay_headless / test_field_types / test_resolver / test_visual |
| **未覆盖**：`_check_row_checkbox` 降级链（force-check/native-click/force-click 及 `:checked` 核实） | ❌ 无直测（依赖 Frappe 真机，矩阵链实测兜底） | — |
| **未覆盖**：row-trigger 的 `entry_pending_note`/checkbox_mode 传递、`early_submitted` 跳过链、8s 在途写等待窗口、SPA 跳转等待 | ❌ 分支无直测 | runner.py:359-391、332-335、575-606 |
| **未覆盖**：goto 步截图（且现行为孤儿，见 §10.4） | ❌ | runner.py:343-344 |
| **未覆盖**：CDP shared_ctx 真连常驻浏览器路径（替身仅模拟 contexts 属性） | ❌ 真机流程（live_browser 9222）人工验证 | runner.py:59-70 |
