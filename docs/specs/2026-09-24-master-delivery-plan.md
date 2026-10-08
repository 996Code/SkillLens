# SkillLens 交付主计划（Master Delivery Plan）

> 版本：v1.0（2026-09-24）。本文档是"从现在到交付"的唯一主计划，后续所有 Sprint 计划从本计划派生。
> 阅读方式：§1 现状盘点 → §2 交付定义 → §3 里程碑 → §4 功能规划（按交付块）→ §5 依赖与闸口 → §6 执行与变更流程。
> 修订规则：任何范围/顺序变更须在本文档留痕（§7 变更记录），并同步宪法与路线图。

---

## 1. 现状盘点（2026-09-24，main = a8c1f3d）

**已具备能力（MVP，全部实测验证）：**

| 层 | 能力 | 验证状态 |
|---|---|---|
| 采集 | MV3 插件：UI/Action/Network 事件 + 脱敏 + 批量上报 | Windows 实测（双语数据两轮） |
| Ingestion | URL 模板化 / Transaction Window / 状态信号 | 102 项测试 |
| 学习 | 多 Episode 对齐 / 变量识别（跨语言）/ LLM 命名 / 确定性回查 | 真实 LLM（qwen3.7-plus）验证 |
| 断言 | 层 2/3 自动生成 + 证据回验 | 4/4 PASS 实测 |
| 回放 | 语义定位 / 换参数 / 影子门控（C1）/ 水合竞态防护 | 常驻窗口可见回放 PASS |
| 变更智能 | Expected（LLM+人工确认）/ Observed / 四分类报告 | 3/1/5/0 实测（含 Missing/Unexpected 构造） |
| 部署 | Docker Compose 私有化 + 常驻浏览器工作流 | 压轴 E2E 139s |
| 工具链 | 全自动闭环脚本 / Windows 适配 / 测试基线 102+ | 本次会话固化 |

**已停驻在分支的工作：** sprint7-tech-debt-baseline 分支（a4c3a40）：complete() 异常落库 + 孤儿 404（105 passed），待主计划确认后随 S7 合入。

**已知欠账（S7 处理）：** LLM 失败调用零记录（分支已修）、re-induce 孤儿 500（分支已修）、100KB reqBody diff 无截断、align 无窗口参数对账、无 C2 对比基线数据。

**硬性约束（宪法，全计划生效）：** C1 影子模式 / C2 Phase 2 起真实流量 / C3 全链路持久化；§12#2 学习引擎+变更智能之外投入 ≤30%。

---

## 2. 交付定义（什么叫做"交付"）

**商业承诺（宪法 §0.2）：** 让 AI 学会客户公司的软件，并在每次版本更新后自动判断：应该改变的有没有改变，不应该改变的有没有被破坏。

**交付判据（三层，全部满足）：**

| 层 | 判据 | 验证方式 |
|---|---|---|
| 功能 | 完整闭环可运转：学习→回放→四分类，夜间流水线可编排调度 | 试点团队环境实跑 |
| 价值 | ≥1 个付费团队在私有化环境跑完整闭环 ≥2 周，报告被真实使用 | 试点运行报告 |
| 工程 | 测试全绿 / 部署 ≤5 分钟 / 备份恢复演练通过 / 安全审计无高危 | S17 验收清单 |

---

## 3. 里程碑（M1-M4，对应宪法四阶段）

```
M1 功能可用   ── S7-S9   ── 管道无债 + UI 快照补盲 + 工作台可视化
M2 真实验证   ── S10-S11 ── 真实流量学习达标 + 两次真实发版报告被认可【= Phase 2 出口】
M3 夜间工程   ── S12-S15 ── Agent 运行时 + 夜间开发 + 编排画布 + 晨间评审【= Phase 3 出口】
M4 交付       ── S16-S18 ── 全闭环贯通 + 加固 + 试点运行【= 付费交付】
```

每个里程碑设**放行评审**：逐条核对出口标准 + 宪法 §12 防跑偏清单，用户签字后才开下一里程碑的闸口 Sprint（§5）。

---

## 4. 功能规划（按交付块；每块 = 功能点 × 验收标准 × 测试要求）

### 块 A：管道可靠性（S7）——为 M2 铺地基

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| A1 | LLM 调用失败也落库 | 错误 key 触发 induce → llm_call_log 有 error 行（含异常类型/耗时/prompt）→ API 返回 500 而非静默 | TDD（分支已完成） |
| A2 | re-induce 无孤儿 | 二次 induce 后旧断言 verify 返回 404，DB 无孤儿行 | TDD（分支已完成） |
| A3 | 大 reqBody 截断+哈希 | >8KB body 落库带 truncated+sha256；diff 在截断文上 | TDD |
| A4 | 对齐窗口参数对账 | alignment 带 window_params（idle_ms/max_window_ms 快照，不一致记 warn） | TDD + 迁移 |
| A5 | 演示基线快照 | GET /baseline/skills + snapshot 脚本导出 JSON（C2 的 80% 对比锚） | TDD + 实跑产出 |

### 块 B：UI 证据层（S8）——补最大盲区

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| B1 | 插件状态快照 | 锚点前 1s + 空闲后 2s 采集表单值/状态标签/表格行数，进 raw_event | 插件单测 + 真机 E2E |
| B2 | semantic_action 承载 state_before/after | 快照解析进现有字段（schema 与回放共用） | TDD |
| B3 | 层 2 断言支持 ui_text | 字段默认值变化 → 断言 FAIL（当前测不出的场景） | TDD：构造默认值变更 |
| B4 | 回放前后快照 | 回放执行采 before/after 快照入 replay_run，报告可见前后对比 | TDD + 浏览器实看 |

### 块 C：工作台 v0（S9）——报告可视化

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| C1 | Skill 列表/详情页 | 骨架/变量/断言/证据计数/置信度，从现有 API 渲染 | 浏览器实看 |
| C2 | 四分类报告页 | expected/missing/unexpected/drift 分栏 + 证据下钻链接 | 浏览器实看 |
| C3 | 回放触发 | 页面按钮 → observe（shadow/execute 选择）→ 结果展示 | 端到端实操 |
| C4 | 只读边界 | 无编辑功能；静态托管 + 现有 API，无新后端逻辑 | 代码审查 |

### 块 D：真实流量切换（S10）【闸口 G1：目标系统授权】

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| D1 | 目标系统适配配置化 | URL 模板/信号/定位策略配置化；njmind→新系统只改配置 | 双系统回归 |
| D2 | 噪声过滤 | 走错/中断/并行/废路径窗口过滤，过滤率可量化 | 构造噪声数据集 |
| D3 | 多路径分桶 | skill_strategy 落地；路径 A/B 各自成桶再对齐 | TDD |
| D4 | evidence_edge 基础表 | 实体/页面/动作/API/状态边入库，带证据计数 | TDD + 迁移 |
| D5 | 真实流量学习 | ≥1 个 learned Skill，置信度 ≥ 基线 80%（A5 对比） | 实跑数据评审 |

### 块 E：真实发版验收（S11）【闸口 G2：两次真实发版】

| # | 功能点 | 验收标准 |
|---|---|---|
| E1 | 发版流水线操作手册 | 需求→Expected→发版→Observe→报告→评审 SOP 文档化 |
| E2 | 两次真实发版报告 | 四分类准确（Missing/Unexpected 真实出现），团队评审核签 |
| E3 | 工作台承载评审 | 评审在工作台页面上完成（C 块的实战首用） |

### 块 F：Agent 运行时（S12）

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| F1 | LangGraph 底座 | 夜间调度器（cron 驱动回放套件）+ Agent 执行环境 | TDD |
| F2 | Impact Analysis | 版本 diff → evidence_edge 图遍历 → 受影响 Skill → 定向回归清单 | 构造变更实测 |
| F3 | 回放并发与配额 | 多 Skill 并行回放不串扰（profile 隔离） | TDD |

### 块 G：夜间开发（S13）【闸口 G3：njmind 开发自动化授权】

| # | 功能点 | 验收标准 |
|---|---|---|
| G1' | 需求→开发计划 | Expected Delta + System Model → 结构化计划（表单/逻辑变更清单） |
| G2' | 低代码自动实现 | 经 njmind 配置 API 自动改表单/逻辑 → 构建 |
| G3' | C1 延伸门控 | destructive 变更默认 shadow 只出计划，确认后执行 |
| G4' | 夜间跑通 1 例 | 1 个表单级需求夜间自动实现，次日核对生效 |

### 块 H：编排画布（S14）——图形化编排主体

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| H1 | 节点画布 UI | 节点类型（需求源/Coding/Testing/回归选择/评审输出）+ 连线数据流 | 浏览器实操 |
| H2 | DAG→LangGraph 编译 | 画布保存为 DAG JSON → 后端编译执行 | TDD |
| H3 | 运行可视化 | 运行历史 + 节点产物下钻（截图/断言/报告） | 浏览器实看 |
| H4 | 首条流水线 | "需求→夜间开发→定向回归→晨间报告"画布编排真实跑通 | E2E |

### 块 I：晨间评审 + Skill 演化（S15）

| # | 功能点 | 验收标准 |
|---|---|---|
| I1 | Review 门户雏形 | PR 式评审流（摘要/证据链/四分类），通过/驳回/打回 |
| I2 | Skill 版本演化 | re-learn 产生新版本，断言历史保留（version 字段落地） |
| I3 | 夜间全流水线 1 例 | 需求→开发→测试→报告→评审通过【= Phase 3 出口】 |

### 块 J：交付加固（S16-S17）【闸口 G4：试点团队】

| # | 功能点 | 验收标准 |
|---|---|---|
| J1 | 全闭环贯通 | 白天录需求→夜间开发测试→晨间评审→归档学习完整转 |
| J2 | 安装/部署向导 | 空机到运行 ≤30 分钟，含插件安装引导 |
| J3 | 备份恢复演练 | 数据卷备份→恢复→验证全通过 |
| J4 | 安全审计 | 凭据/日志/网络边界/CORS 收紧复查，无高危 |
| J5 | 性能收尾 | 100KB diff、回放并发、镜像瘦身（遗留清单清零） |

### 块 K：试点运行（S18）

| # | 功能点 | 验收标准 |
|---|---|---|
| K1 | 试点 ≥2 周 | 真实团队真实使用，周报迭代 |
| K2 | 交付判据达成 | §2 三层判据全部满足 → 签约交付 |

### 块 L：通用能力层（跨系统 Skill 泛化）——M2 出口后启动

> 2026-09-25 用户方向裁定：Skill 不能绑死单一系统，须归纳总结为通用能力。
> 决策：分阶段通用化——**引擎延后到语料够格**，防 N=1 空泛归纳（宪法证据优先精神）。

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| L1 | 通用 Skill 模型 | generic_skill 表（能力模板+槽位 schema）+ 与系统绑定 Skill 的映射关系 | TDD+迁移 |
| L2 | 归纳端点 | 多个系统绑定 Skill → LLM 提议通用模板 → **确定性回查**（证据模式必须能在各源 Skill 的 evidence_edge 中找到） | TDD |
| L3 | 晋升纪律 | 单系统归纳 = candidate；**双系统绑定+回放通过** = learned（与现有 candidate→learned→validated 同构） | TDD |
| L4 | 槽位映射 | 新系统接入：通用模板 + 槽位填空（按钮语义/API 模板/权限模型）→ 学习成本从"学流程"降为"对映射" | 双系统实测 |
| L5 | 迁移实测 | 通用 Skill 在第二系统上经槽位映射后回放 PASS | E2E |

**入口标准（启动块 L 的闸口 G5）**：≥2 个不同任务族（如 表单创建/查询检索/审批流转）在主系统学扎实；最好有第二系统可验证。
**前置积累（S11 起零成本执行）**：真实流量语料多样化——录制复合任务（多步/含分支），验证系统内参数化复用（现有 variables 机制即系统内通用化）。
**设计补注（v1.3，源自 v3 §30）**：分层是双维度——①同系统 UI 实现版本化（按钮改名 V1→V2 不重学业务 Skill）+ ②跨系统槽位映射。块 L 设计须同时覆盖。

### 块 M：链路审计（S10.5，S11 前执行）——C3 可视化

> 2026-09-25 审查发现（docs/reviews/2026-09-25-master-plan-audit.md G-1）：C3 承诺"可审计"但无界面；S11 团队评审需要证据链载体。

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| M1 | 会话链路下钻 | /audit：会话列表（source/事件数/过滤数）→ 窗口（kept/filtered+原因）→ 语义动作（含前后快照）→ 对齐（骨架/分桶）→ Skill → 回放历史，一条链点到底 | 端点 TDD + 浏览器实测 |
| M2 | 证据图视图 | evidence_edge 按 type/src 分组列表（src→dst/计数/首见/最近），type 过滤 | TDD + 浏览器实测 |
| M3 | LLM 调用日志 | purpose/model/tokens/耗时列表，prompt/response 摘要（200 字截断） | TDD + 浏览器实测 |
| M4 | 噪声过滤决策视图 | trace 内每窗口显式 kept/reason（read_only/orphan_click/overlong/empty_label） | TDD + 浏览器实测 |

### 块 N：学习深化（M2 出口前后）——补全 v3 设想缺口

> 2026-09-25 审查发现（G-2~G-5 + S-3）：v3 明确设想但主计划缺失的学习能力。

| # | 功能点 | 验收标准 | 依赖 |
|---|---|---|---|
| N1 | 新功能增量发现 | 发版后插件发现新 UI 元素/新 API → 自动建 candidate（observed_count=1, conf≈0.45），随使用晋升 | S11 场景验证 |
| N2 | Requirement 先验对齐 | Expected Delta 与新发现 candidate 自动关联（需求↔观察到的特征） | N1 |
| N3 | Outcome 层1 显式提示采集 | toast/成功消息进 state_signals（插件采集+signals 扩展），层1-5 证据链补全第一层 | 无 |
| N4 | Outcome 层4/5 | 历史成功样本断言（层4）+ 多结果一致性校验（层5）落点细化并实施 | S11 后语料 |
| N5 | Active Probing 设计评估 | 主动探测（观察→规则猜测→边界值验证）出设计文档；实施依赖可重置测试环境授权（闸口 G6） | C1 边界+环境 |

### 块 S：协作与准入（S21）——G4 前置

> 2026-09-27 v1.6 对标差距分析（docs/reviews/2026-09-27-competitor-gap-analysis.md）：工作台无登录/单用户是试点团队的硬阻塞。

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| S1 | 用户与角色 | user 表（username/password_hash/role）+ 迁移；角色 admin/reviewer/viewer 三级；admin 可建用户 | TDD |
| S2 | 登录与会话 | 登录端点 + token 会话（过期/登出）；API 默认要求认证（插件上报通道除外，沿用现有 ingest 鉴权边界） | TDD |
| S3 | 评审绑定 | review.reviewer 关联真实 user；评审门户显示评审人身份；viewer 不能提交评审 | TDD |
| S4 | 前端接入 | 登录页 + 路由守卫 + 当前用户显示/登出；角色可见性控制（viewer 只读） | vitest + 浏览器实测 |

### 块 T：视觉回归断言（S22）——断言第 6 层

> 对标 Applitools/Percy/Mabl：截图基线比对。我们已有回放前后快照存档，缺"比对引擎+判定"。

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| T1 | 视觉基线 | skill 首次 execute PASS 后快照存为视觉基线（visual_baseline 表）；基线可人工重置 | TDD+迁移 |
| T2 | 感知比对 | 回放后快照 vs 基线：感知哈希初筛 + 差异区域占比阈值（配置化），产出 pass/fail + 差异摘要 | TDD（确定性，无 LLM） |
| T3 | 断言集成 | 比对结果作为断言 kind=visual_baseline 参与回放判定与一致性统计 | TDD |
| T4 | 报告呈现 | 四分类报告/技能详情显示视觉差异结果与前后图并排 | 浏览器实测 |

### 块 V：性能基线（S23）——性能漂移进四分类

> UiPath 2026-09-26 发布 agentic 性能测试——方向被验证。我们 duration_ms/API 时序已在采集，边际成本低；差异点：性能漂移进 drift 分类而非独立产品。

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| V1 | 性能基线 | skill 回放耗时 + 关键 API 延迟的滚动基线（中位数±带宽） | TDD |
| V2 | 漂移判定 | 回放耗时/API 延迟超基线带宽 → drift 项进四分类报告（确定性阈值） | TDD |
| V3 | 呈现 | 报告页性能漂移区块 + 趋势（最近 N 次回放耗时） | 浏览器实测 |

### 块 U：自愈与维护闭环（S24）

> 对标 Testim/Mabl/Functionize 的 self-healing + QA Wolf 的 AI 维护代理。宪法边界：LLM 只提案，确定性验证后才生效。

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| U1 | 定位修复提案 | 回放定位失败 → LLM 基于当前页面快照提议新定位（label/selector）→ 影子验证通过才写入提案库；人工 confirm 或连续 N 次影子通过后自动晋升 | TDD（C1 纪律） |
| U2 | flaky 重跑策略 | 回放失败自动重跑 1 次（配置化），两次结果不一致标记 flaky 进一致性统计 | TDD |
| U3 | 归因→修复闭环 | replay_failure_attribution 归因结果与 U1 提案关联，形成"失败→归因→修复→验证"链路可视化 | TDD + 浏览器实测 |

### 块 W：集成出口（S25）

> 让"变更智能"进入团队真实工作流；导出直接回应 QA Wolf"确定性代码进仓库"论点。

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| W1 | Playwright 导出 | skill/流程 → 可执行 Playwright 脚本导出（含断言），导出脚本可独立运行 | TDD + 真机运行验证 |
| W2 | Webhook 通知 | 报告生成/夜间运行完成 → webhook 推送（企微/钉钉/Slack 格式，URL 配置化） | TDD |
| W3 | 需求条目关联 | expected_delta 可关联外部需求编号（Jira issue key 等，v1 仅存字段+展示，不做 Jira API 对接） | TDD |

### 块 X：DB 深层验证（暂缓，试点反馈后定）

> 只读 SQL 断言（DB 状态作为第 7 层证据）。依赖：目标系统 DB 只读账号授权（新闸口 G7）。K 块试点反馈确认需求后再启动。

### 块 AF：适配器架构（P3b 升级，v2.1 新增）

> 2026-10-03 用户方向裁定：SkillLens 做基座，目标系统适配以插件（声明式清单）支持自定义。
> 依据：S43-4 七系统 2549 行编排脚本解剖——约 60% 是逐字相同的基座骨架，每系统真正
> 不同的只有 4 类（登录怪癖/走查步骤/实体探针/状态注入）。设计三原则：
> ①例程库而非无限 DSL（6 原语 goto/fill/click/select/wait/routine，怪癖收编进例程库）；
> ②探针是第一公民（docker-exec/http 统一抽象，同服务实体验证+状态注入+块 X）；
> ③flow 走查可选（缺省时退化为登录引导+人工走查+探针验证）。

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| AF0 | schema spike 定稿 | 本表（6 原语+探针 kinds+chains 结构）评审通过 | 评审记录 |
| AF1 | manifest Pydantic schema+loader | ✅ 7 系统清单（从 s43 脚本机械提取）全部通过校验；password_literal lint 警告（安全红线） | TDD |
| AF2 | 探针运行时 | ✅ docker-exec/http+parse+凭据 env 注入+辅助脚本自动注入；禅道 zt_story 全量 18 与手跑逐位一致 | TDD |
| AF3 | 登录+例程库 | ✅ 六原语解释器+例程五件套+幂等登录（已登录直通）；**7 系统真机登录全 PASS**（2026-10-03：禅道/Odoo 经本地容器凭据重置后补验——重置操作经 DB/odoo shell，凭据入清单 literal+lint 标注） | TDD+真机 |
| AF4 | flow 步骤解释器 | ✅ 禅道 Story/Case/Testtask 3 流学成 learned #272-274（4b326c0）；CaseRun iframe 二级行操作=采集层窗口限制，走人工走查（原则③） | TDD+真机 |
| AF5 | 链编排器 | ✅ af5_chain.py（4fca744）：幂等登录+id 直引+换参回放+探针 verify（异步窗口）；JeecG 270/271 pass（269 UI 态漂移已知项，探针如实检出） | TDD+真机 |
| AF6 | 接入向导 UI | ✅（8617bd3）工作台 /graph/adapters：7 系统卡+YAML 编辑器+实时校验/保存（API TDD 6 用例）+executor UX 整改（确认卡带技能名+结果卡带工作台链接——用户代理评审驱动）；浏览器实操验收+截图入库 | 浏览器实操 |

### 块 AG：扩展执行后端（chrome.debugger 桥接，v2.1 新增）

> 2026-10-03 用户方向裁定：回放不都在服务器跑——Chrome 插件作桥梁调用客户端执行。
> 架构：瘦执行器——定位/评分/写判定/C1 门控/断言全留服务端，插件只执行微指令+回传
> 证据（避免 execute_plan 双实现漂移）。技术底座：chrome.debugger attach 后走 CDP
> Input.dispatch*（与 Playwright 同源可信输入，isTrusted=true，规避合成事件坑
> lesson #19）；Network 域观察响应体（webRequest 读不了 body）。红利：真实登录态
> 回放（密码脱敏死结消失）+ P2 并发执行面（每用户浏览器=执行节点）。

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| AG0 | spike 验风险 | ✅ 已完成（2026-10-03，lesson #30）：attach/可信点击/网络体捕获/detach 4/4；SW 事件驱动期间不杀；冲突形态明确 | spike 记录 |
| AG1 | 微指令协议规格 | ✅ 契约 v0.2+四端点+seq 幂等+当轮介入（上限 2 次，超限继续序列由断言判——fail 留下轮语义）；attach 冲突路径 ✅ | TDD |
| AG2 | resolver 编译器+debugger 原语 | ✅ 候选编译（14 策略含 aria-attr/row-anchor/menuitem-css）+对拍护栏；可信 click/fill+Network 体+多 frame resolve；scrollIntoView+rect 重取统一 anchor | TDD+真机 |
| AG3 | popup 执行交互 | ✅ 终局架构=独立 executor.html 页（a4bdb86）：popup 选技能→跳执行页；C1 确认卡+auto=1 验收模式；实时日志（[停止]按钮 P2 待接真停） | TDD+真机 |
| AG4 | 服务端断言接线 | ✅ finish(done) 吃证据跑 evaluate_assertions→pass/fail 重判（1e4deab）；executor=extension 标记 ✅（repair_map 插件端接线 P2） | TDD |
| AG5 | 客户端闭环验收 | ✅（3ca080a）JeecG #271+Odoo #1 双端 pass 一致；禅道 #272 执行全 ok 断言 2/3 如实 fail；真实登录态 3/3 | E2E |

### 明确不做（v1.6 决策记录）

跨浏览器（Firefox/WebKit）、移动端、无障碍校验——私有化内部 Web 系统场景下 Chromium 是事实标准，投入产出比不成立。竞品有此能力不构成跟进理由。

---

## 5. 依赖与闸口（关键路径）

```
S7(A) → S8(B) → S9(C) → 【G1 目标系统授权】S10(D) → 【G2 两次真实发版】S11(E) = M2
                                    ↓ 放行评审
        S12(F) → 【G3 开发自动化授权】S13(G) → S14(H) → S15(I) = M3
                                    ↓ 放行评审
        【G4 试点团队】S16(J1) → S17(J2-J5) → S18(K) = M4 交付
```

**闸口清单（需用户/团队准备的外部输入）：**

| 闸口 | 需要什么 | 建议提前量 |
|---|---|---|
| G1 (S10) | 团队测试常用系统的选定 + 采集授权 + 测试账号 | S8 期间 |
| G2 (S11) | 两次真实需求变更排期 + 评审人 | S10 期间 |
| G3 (S13) | njmind 开发侧自动化授权（配置 API/账号） | S12 期间 |
| G4 (S16) | 试点团队/客户确定 | S14 期间；**v1.6 起前置块 S（协作与准入）须先完成** |

**v2.1 执行序（块 AF/AG，2026-10-03 起）：**

```
AG0 spike ✅（2026-10-03，lesson #30：4/4 PASS+SW 保活+冲突形态）
AG1 协议 server 侧 ✅（端点组+迁移+4 用例；契约文档 docs/arch/extension-executor-protocol.md）
  → AF1 manifest schema+7 系统清单回填 ✅ → AF2 探针运行时 ✅ → AF3 登录+例程库 ✅
    （批 1 五系统真机 PASS；禅道/Odoo 待 env 凭据复验）
  → AG2 resolver 编译器+原语 → AG3 popup 执行交互 → AG4 断言接线
  → AF4 flow 解释器 → AF5 链编排器（JeecG 三链对齐 ALL PASS）
  → AG5 客户端闭环验收（popup 执行+双端一致性）
  → AF6 接入向导 UI（闸门④浏览器实操）
```

架构定案（2026-10-03 用户澄清）：**插件=完整执行节点，用户在 popup 选择并点击执行
（含写技能，点击即 C1 授权）；服务器=管理+知识库，不下发任务**。夜间/画布批量暂留
服务端 Playwright 兜底。依据：AF1-AF3 零依赖可立即开工；AG5 前置 AF5（清单技能
用于双端一致性对比）。

### 块 AH：空间与链编排（v2.4 新增，2026-10-08 用户方向裁定）

用户裁定两条架构原则：**① 交互全在插件弹窗内实现（工作台不参与执行流）；
② 链=纯数据+通用规则（降耦合，不为任何系统写执行代码）**。

| 片 | 内容 | 验收 |
|---|---|---|
| AH1 | 服务端 chain 数据层：`chain` 表（name/system/steps JSON）+ CRUD（WRITE_GUARD） | TDD：建/列/按系统过滤/删/角色门禁；schema drift 守卫联动 |
| AH2 | 链规则解释器（插件纯函数）：`${unique:前缀}` 唯一值生成 | TDD 直测 |
| AH3 | executor.html 链模式：`?chain=<id>` 顺序执行、unique 规则、**整链 C1 一次确认**（确认卡列全部步骤）、步进报告、fail 即停 | 真机：JeecG 链 269+118 全 pass |
| AH4 | 空间小窗：popup「空间」按钮 → 右上角独立小窗（chrome.windows.create）；当前 tab 系统**经 P2.5 /adapters/match 识别** → 只显示该系统回放 → 多选组链 → 保存/立即执行 | 真机：打开 JeecG → 空间 → 仅见 JeecG 链 → 组链保存执行 |
| AH5 | 真机验收+审查+文档 | 三套测试全绿+评审记录 |

**P2（后续）**：跨步值绑定（`${stepN.变量}`——从上一步写响应证据提取真实值，
如 addAll 返回的表名）；链执行历史回看；链步骤引用 superseded 技能时自动跟最新版。
**已知风险**：跨步绑定涉及行锚（263/271 教训），P1 用 unique 规则+人工指定绕开；
组链原子步优先用新录短链（旧长链对数据环境敏感）。

**v2.4 执行序**：AH1 → AH2 → AH3 → AH4 → AH5（真机矩阵含环境预检：端口/登录态探活）。

## 6. 执行与变更流程

- **Sprint 执行**：派生计划 → docs/superpowers/plans/ → SDD 子代理执行（TDD 先红后绿）→ 全量测试绿 + 实测验收 → 本地合 main + 删分支。
- **每 Sprint 完成定义**：计划验收标准逐条达成 + pytest 全绿 + 新功能配新用例 + 部署类实测 + UI 类浏览器实看 + lessons 记录。
- **放行评审（里程碑间）**：用户按 §3 核对出口标准 + §12 防跑偏清单，签字开闸。
- **变更**：范围/顺序变化改本文档 §7 + 同步宪法/路线图，禁止口头改约。

## 7. 变更记录

- 2026-09-24 v1.0：初版。S7 前两任务已停驻分支（a4c3a40）待随 S7 合入。
- 2026-09-24 v1.1：M1 放行（S7/S8/S9 全合入，78641ac）；**G1 闸口解除：目标系统 = 192.168.99.22（明搭云，团队日常测试系统）**——D1"配置化适配"保留（为未来切换打基础），S10 重点落在 C2 真实流量学习与噪声处理。
- 2026-09-25 v1.2：**新增块 L 通用能力层**（用户方向裁定：Skill 须跨系统通用化）。分阶段决策：引擎延后至语料够格（闸口 G5：≥2 任务族+第二系统），S11 起零成本积累多样化语料；通用 Skill 沿用证据晋升纪律（单系统=candidate，双系统=learned）。S10 已完成（C2 达成，ratio 1.087）。
- 2026-09-25 v1.3：**全面审查后新增块 M（链路审计 4 点）+ 块 N（学习深化 5 点）**，功能点 44→53。补注：块 L 分层双维度（v3 §30）；S17 安全审计明确含 PII 规则配置化；**S11 验收增观察项——第一次真实变更时记录系统对新功能的发现行为（N1 天然实验场）**。审查报告：docs/reviews/2026-09-25-master-plan-audit.md。执行顺序：块 M（S11 前）→ S11（G2）→ 块 N → 块 L（G5）。
- 2026-09-25 v1.3.1（S12 执行期修订）：①N4 实施发现计划笔误——outcome_assertion 原无 evidence_count 列，补列+迁移（d9b1e4c7a2f5），层4 资产语义为"重建断言不清零计数"；②N1 实施形态确认：v1 纯确定性记录（discovered_feature 表），LLM 命名留待后续 induce 复用；③块 M/S11 已完成（M2 机制出口达成，用户终验待做）。
- 2026-09-25 v1.4（用户方向指令）：**新增块 P「公网站点泛化实测」**（百度/新浪等——采集/学习/回放全链在陌生系统上的鲁棒性验证，G5 语料积累）+ **块 Q「UI 升级」**（参考业界测试平台 UI，工作台/画布/评审视觉与交互打磨）+ 文档更新（根 README/产品总览）+ SWOT 迭代分析（docs/reviews/）。执行顺序：P → SWOT/文档 → Q。
- 2026-09-25 v1.5（用户方向指令：多站点测试+归纳生成新流程+角色定位完整产品团队）：**新增块 R「流程生成（Flow Synthesis）」**——Evidence-backed 流程合成：目标 → LLM 分解为步骤序列 → 确定性回查每步引用（action/API 必须在证据图中）→ C1 门控执行 → 成功后自学习为 candidate skill（v3 §27）。差异化：Katalon 凭空生成脚本，我们生成"证据支持的流程组合"。含多站点实测扩展（块 P 深化：网易/搜狐等 2-3 站）。S18 T4 夜间一例并入 S19 执行。
- 2026-09-27 v1.6（用户方向指令：对标差距分析+规划，用户授权"你来定"）：**新增块 S「协作与准入」（G4 前置）+ 块 T「视觉回归断言」+ 块 V「性能基线」+ 块 U「自愈与维护闭环」+ 块 W「集成出口」**，功能点 53→73；块 X「DB 深层验证」暂缓（试点反馈后定）。依据：docs/reviews/2026-09-27-competitor-gap-analysis.md（对标 Katalon TrueTest/UiPath/Meticulous/QA Wolf/Testim/Mabl/Applitools；新情报：UiPath 2026-09-26 发布 agentic 性能测试）。执行顺序：S → T → V → U → W。**明确不做**：跨浏览器/移动端/无障碍校验（决策依据记录在案）。
- 2026-09-28 v1.6.1（用户指令："你把只要你可以去做验证的，全部都做了。别等我去做"）：**G2 技术核验通过（代理自验）**——report #5/#6 观测项与四分类均可从底层 replay_run 确定性重算复现，浏览器渲染零错误（docs/reviews/2026-09-28-g2-self-verification.md）。同日启动 **Sprint 26：S24 遗留 P2**——自愈提案晋升后经 S15 supersede 机制回写 skill 骨架生成新版本（自愈闭环收口）。
- 2026-09-28 v1.7（用户方向反馈："控制台ui、交互太简单了"+"测试链路太简单，完全无法让人信服"）：**新增块 Y「工作台 UI v2」**（对标 Katalon/Applitools/QA Wolf 视觉标准：仪表盘首页/设计系统升级/技能列表过滤搜索/报告可视化强化/全局加载态空态 toast）+ **块 Z「深度链路测试」**（真实发版模拟：njmind 表单真实加字段→重采集→四分类应检出；三重故障注入矩阵：定位失败+视觉漂移+性能漂移同场；夜间全流程 E2E：画布定向回归+评审+webhook 全链）。执行顺序：Y → Z。
- 2026-09-29 v1.8（系统重定向，用户："不是以流程图为底座打造的系统"）：**新增块 AA「图基座重构」**——图优先导航（/graph 图工作台：左树+图卡总览+流程图详情+执行图），S39 双路由合并；S40 数据清零+UI 重做（搜索/折叠/真图）；S41 用户八问修复。功能点 73→79。
- 2026-09-30 v1.9（自愈+图基座深化）：**新增块 AB「自愈系统缺陷根治」**（record_usage 只在 run 整体 pass 时计数——垃圾提案污染根治；状态依赖失败不生成）+ **块 AC「图基座第二步」**（状态机归纳/学习图五层 trace/画布子图展开）+ **块 AD「字段类型 LLM 归因」**（llm_attribute_type 枚举约束落库，自愈接线只归因校验错误提到的字段）。测试基线 server 440 / web 54 / extension 69。
- 2026-10-01/02 v2.0（用户："把开源系统全部走一遍闭环，完善的流程业务测试，不要光知道基础数据，每个系统都有核心流程，多个角度走几遍"）：**新增块 AE「全系统核心业务多角度闭环」**（S43-4）——七系统（Snipe-IT 资产/禅道 QA/Odoo 销售/Dolibarr 订单/JeecgBoot 字典+在线表单/ERPNext CRM/若依权限）每系统核心业务链 2 轮录制→学习→换参回放→实体级验证；23 技能学成、22 回放全 PASS（JeecG 表单链 Create 全 PASS、Sync/Fill 步骤层过+物理表建出，链式 override 列未竟项）。**同步固化「成熟项目对照」开发纪律**（用户强制：遇坑先查目标系统官方 harness——Frappe cypress intercept+wait/check(force)、Odoo tour 种数据、Healenium LCS 评分，已入 AGENTS.md §二）。功能点 79→86。测试基线 server 447 / web 54 / extension 76。验收：demo/sprint43/user-test-report.md。
- 2026-10-02 v2.0.1：S43-5 收尾——JeecG 链式 override 修复（row-anchor 换参注入+动态 id 断言归一，commit 246b752），七系统 **23 技能 23 回放全 PASS**。测试基线 server 452 / web 54 / extension 76。lessons #29。
- 2026-10-03 v2.1（用户方向裁定："做一套基座，系统适配作为插件支持自定义"+"回放不都在服务器上，用 Chrome 插件作桥梁调用客户端"）：**新增块 AF「适配器架构」**（P3b 升级：manifest 清单+探针运行时+例程库+链编排器+向导 UI，7 片含 AF0 schema 定稿）+ **块 AG「扩展执行后端」**（chrome.debugger 桥接客户端执行：瘦执行器架构+微指令协议+双后端一致性，6 片含 AG0 spike）。功能点 86→99。
- 2026-10-03 v2.1 落地完成（13/13 片）：AF0-AF6+AG0-AG5 全完成（AG5 验收 3ca080a：JeecG #271/Odoo #1 双端 pass 一致+真实登录态 3/3；架构定局=插件执行节点/服务器管理不下发）。测试基线 server 482 / web 54 / extension 76。剩余：AF6 向导 UI；P2 待办（心跳 lost/停止真接/repair_map 插件端/介入超限判 fail 细化）。七系统核心链矩阵（插件端全技能×2 轮）进行中。
- 2026-10-05 zcode 浏览器层全源码学习落地（b7adb74）：browserView 11 文件精读→docs/references/zcode-browser-harness-study.md（五层架构+差距表 10 项）；逐模式真机实证后 executor 六根因根治（探针准入/双通道点击+效果验证/禁 reload/fill modal 优先+name+iframe/豁免持久化/overrides 注入+配额串防线）；插件端验收 禅道272/JeecG269/Odoo1 **3/3 PASS**+登录态 3/3（JeecG 数据污染 25 条清理；?fill_ 换参支持）。测试基线 server 490 / web 54 / extension 76。lessons #35。服务端已知外部项：LLM 网关配额耗尽（attribution 污染已加防线）、visual_baseline 对写操作天然漂移。
- 2026-10-06 v2.1.1（平台化组件化四阶段终验 PASS）：**P1 交互画像**（InteractionProfile 五维组件随 plan 下发，执行器解释器化，17fc73b）→ **P2 画像指纹**（贴 HTML 识别组件库出画像草稿，3cf691e）→ **P2.5 URL 通配符匹配**（油猴 @match 语义，系统按 URL 自动配对隔离，386a2d8）→ **P3 扩链**（8 系统 52 链矩阵 52/52 全 PASS；录制框架 raw CDP 重写根治 Playwright driver dialog 竞态崩溃，bfb1c31）→ **P4 Firefly III 零代码接入终验**（全新系统纯 YAML 接入闭环，2d9a0db）。架构契约：docs/arch/2026-10-07-platform-interaction-profile.md。八系统 53 技能全绿。
- 2026-10-07 v2.2（全库代码评审+两轮修复）：四域深审（server/app+scripts/extension/web，docs/reviews/2026-10-07-full-codebase-audit.md）——一轮红线 6 处修复（网关 IP env 化/路径穿越白名单/attribution 脱敏/snapshot 三重脱敏/CDP 网络证据脱敏/插件配对 401）；二轮中危 11/13 清零+卫生 28 项（events 跨域守卫+批量幂等/adapters 写盘限 reviewer/admin/stale-run 心跳判据/执行器全局重置+listener 清理/EXECUTOR_RUN 改执行页/web 竞态守卫+blob revoke+fmtTime/分组共享抽取）。缓修 2 项（execute() 重构、token 一次性换票——需 52 链真机回归支撑，独立排期）。测试基线 server 508 / web 54 / extension 83。
- 2026-10-08 v2.3（三轮全库评审+修复+文档补全）：七域并行深审（安全鉴权/回放引擎/数据管道与学习/插件/工作台/脚本部署/适配器；报告 docs/reviews/2026-10-08-full-codebase-audit-round3.md）——本轮定位"声称的语义是否真的成立"：🔴 9 项全修（viewer 角色形同虚设→WRITE_GUARD 31 变更端点+C1 确认冒充→取登录态 / Skill.system 有模型无迁移→删列+schema 双向 drift 守卫 / induce 空骨架 NameError / 写水位被 GET 噪声击穿 / 脱敏词表四处漂移→16 词+跨文件一致性测试 / 注入模板转义丢层 / AdaptersView select 失败错写系统 / auto_record IP 兜底回归）；🟡 43 项修 34 缓 9（掩码回填防"保存即毁凭据"、net-hook 失败调用留痕 C3、export_shared 判定同源逐字内嵌、快照穿 iframe、classify 畸形防御+按身份消费、2 支脚本 fail-fast、端口 127.0.0.1 绑定+非 root+uv pin 等）；🟢 34 项清 22。新增四类防漂移装置（一致性测试/非空守卫/迁移 drift 守卫/同源内嵌）。文档 +8 篇 arch（replay-engine/ingestion-pipeline/adapters-subsystem/auth-and-role-matrix/redaction-defense-in-depth/env-contract/change-intelligence/schema-migration-discipline）+ lessons #38-#46。缓修 34 项逐条附理由（插件三处"路径激活型"须与真机矩阵轮同批；C2 学习分轨待产品决策；conftest test.db 并行互撞待 CI 分片）。测试基线 **server 546 / web 78 / extension 99**。
- 2026-10-08 v2.4（用户方向裁定：空间与链编排）：**新增块 AH**——交互全在插件弹窗（工作台不参与执行流）、链=纯数据+通用规则（降耦合）。AH1 服务端 chain 数据层（表+CRUD+WRITE_GUARD）→ AH2 规则解释器（${unique:}）→ AH3 executor.html 链模式（顺序执行+整链 C1+步进报告）→ AH4 空间小窗（P2.5 match 识别当前系统→过滤→多选组链）→ AH5 真机验收（JeecG 269+118 链）。P2：跨步值绑定/执行历史/superseded 跟版。触发背景：JeecG 矩阵 3 轮验收（06a339e）+ popup 回放列表双根因修复后用户提出组合执行需求。
