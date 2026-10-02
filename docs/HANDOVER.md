# SkillLens 工作交接总档（HANDOVER）

> 2026-10-02 编制。接手者（人类或 AI）从本文起步，配合 `PROJECT-GUIDE.md`
> （项目导览）与 `AGENTS.md`（操作宪法）使用。**文末附完整接手提示词套件。**
> 本文档与项目记忆（auto memory）互为镜像：记忆供 AI 会话续接，本文供
> 人类接手与归档。

## 0. 一句话现状

**产品全里程碑（MVP→M4 + v1.6-v2.0 差距块）技术完成，七系统核心业务闭环验证
通过（S43-4），可进入试点。** 唯一外部待办：G4 真实试点团队指定（用户输入）。
唯一技术未竟项：JeecG Sync/Fill 链式 override（详见 §6）。

## 1. 项目是什么（30 秒版）

SkillLens = AI 软件学习 + 变更智能。Chrome 插件影子采集用户在内部系统的真实
操作（UI+Network+State 三通道证据）→ 语义动作 → 窗口对齐 → LLM 命名 + 确定性
回查归纳出可回放 Skill → 断言生成（6 层证据）→ 语义定位回放 → Expected vs
Observed Delta 四分类变更报告（Expected / Missing / Unexpected / Drift）→
夜间定向回归 → 晨间评审门户 → Webhook 通知。

三条产品宪法（零例外）：
- **C1 影子模式**：destructive 操作未确认绝不执行（编译期定格 + DB 不变量）
- **C2 真实流量分轨**：demo | real_traffic 标记贯穿
- **C3 全链路落库**：含失败的 LLM 调用，异常摘要 URL 脱敏

LLM 边界纪律：**LLM 只做命名/结构化/归因/提案，一切判定确定性可复现。**

差异化定位（对外叙事，全员背诵，详见 COLLABORATION-CHARTER §七）：
Evidence Graph + 四分类（需求预期 vs 实际）、LLM 边界纪律、私有化架构级默认、
C1 零例外。不正面撞 Katalon 的"需求直出脚本"，做全赛道无人做的变更智能。

## 2. 仓库结构速览

```
SkillLens/
├── AGENTS.md / PROJECT-GUIDE.md / README.md   ← 宪法三件套（本文为第四件）
├── docs/HANDOVER.md                            ← 本文（交接总档）
├── docs/specs/                                 ← 产品宪法 + 交付主计划（v2.0）
├── docs/arch/                                  ← 17 份架构契约（按主题）
├── docs/references/project-lessons.md          ← 踩坑经验库（持续追加）
├── docs/COLLABORATION-CHARTER.md               ← 协作宪章（用户全部要求）
├── server/        FastAPI + SQLAlchemy + SQLite + Playwright（后端+回放引擎）
├── server/web/    Vue3 + TS + Vite 工作台前端
├── extension/     Chrome MV3 插件（采集，TS）
├── scripts/       实操脚本（live_browser/auto_record/各 Sprint 截图）
├── demo/sprintN/  每 Sprint 验收记录+截图+用户测试报告
└── docker-compose 相关                          ← 目标系统容器（见 §4）
```

## 3. 当前能力全景（S43-4 出口状态）

### 3.1 核心管道（全部可用）
- 采集：Chrome MV3 影子采集，UI+Network+State 三通道，密码/敏感字段双脱敏
- 学习：窗口对齐（含动态值归一）、噪声过滤、Skill 归纳（LLM 命名+回查防幻觉）、
  字段类型 LLM 归因、流程合成
- 回放：语义定位（5 级链+评分兜底）、C1 影子门控、flaky 重跑、自愈闭环
  （定位失败→LLM 提案→实测验证→N 次晋升→supersede 新版本）、Playwright 导出
- 断言：6 层证据（ui_text/网络模板/DB 不变量/状态信号/evidence_count/视觉）
- 变更智能：四分类纯函数、性能漂移（滚动中位数×1.5）、Expected Delta 确认流
- 运行时：画布编排（DAG）、夜间定向回归、晨间评审门户、Webhook 通知
- 工作台：图优先导航（/graph 图工作台：左树+总览+流程图+执行图+学习图+
  状态机归纳）、时间线（LLM IO 全留存）、测试套件（流水线）

### 3.2 七系统验证矩阵（S43-4，2026-10-01/02）

| 系统 | 业务链 | 技能 # | 结果 |
|---|---|---|---|
| Snipe-IT | 资产 Create→Checkout→Checkin | 154-156 | 3/3 PASS |
| 禅道 | QA：需求→用例→测试单→执行 | 166-169 | 4/4 PASS |
| Odoo | 销售：报价→确认→开票 | 178-180 | 3/3 PASS |
| Dolibarr | 订单：第三方→订单→确认→开票 | 188-191 | 4/4 PASS |
| JeecgBoot | 在线表单：建表→同步→填数 | 269-271 | Create PASS；Sync/Fill 未竟 |
| ERPNext | CRM：客户→报价→销售订单 | 234-236 | 3/3 PASS（22 步长链） |
| 若依 | 权限：角色→用户→新账号登录 | 256-258 | 3/3 PASS |

**23 技能学成，22 回放全 PASS。** 覆盖 5 种前端框架（zui/element-plus/
ant-design-vue/owl/select2+Bootstrap），详见 demo/sprint43/user-test-report.md。

### 3.3 测试基线（合并前提：三套全绿）
```
cd server && uv run pytest -q                        # 447 passed
cd server/web && npm test                            # 54 passed
cd extension && npm run build && npm test            # 76 passed
```

## 4. 环境与运维（Windows 开发机）

### 4.1 目标系统容器（docker）
| 系统 | 端口 | 容器备注 |
|---|---|---|
| Odoo 18 | 8069 | XML-RPC 8070；状态注入用 docker exec -e ODOO_PW |
| Dolibarr | 8080 | DOLI_PW 注入；模块激活必须走 UI toggle |
| 禅道 | 8081 | ZENTAO_PW 注入 |
| JeecgBoot | 8082 | 源码构建；redis/mysql 依赖 |
| Snipe-IT | 8093 | APP_KEY 必须够长（key:generate 重建）；maria 容器内命令是 mariadb 非 mysql |
| ERPNext | 8090 | bench 容器；Frappe API 验证 |
| 若依 | 8095 | 源码构建（prod-api）；初始密码弹"安全提示" |
| njmind（真实） | 192.168.99.22 | 明搭云，G2 已两次真实发版验收 |

**宿主机重启后**：`docker start` 全部容器 + 重启 8710/9222。SW 冷启动须轮询
等待；8710 不在线则 START_RECORDING 报 Failed to fetch。

### 4.2 SkillLens 自身
```bash
# 后端
cd server && uv sync && uv run alembic upgrade head
cp .env.docker.example .env     # 填 LLM_*/NJMIND_*（gitignore，永不提交）
uv run python -m app.create_user <用户名> <密码> admin
uv run uvicorn app.main:app --port 8710

# 常驻可见浏览器（录制/回放全程用户可见——用户要求）
cd server && uv run python ../scripts/live_browser.py 9222
#   server 环境变量：REPLAY_CDP_URL=http://127.0.0.1:9222
#   采集环境变量：RECORD_CDP_URL=http://127.0.0.1:9222
```

### 4.3 Windows 铁律
- Node 命令前缀 `export PATH="/d/github/.tools/node-v24.18.0-win-x64:$PATH"`
  （系统 22.10 静默坏测试）；vite pin ~8.2.2；缺 win32 绑定补装
  `npm i @rolldown/binding-win32-x64-msvc --no-save`
- uv.lock 被镜像改写属正常，提交前 `git checkout -- server/uv.lock`
- 杀 8710 端口：`powershell -NoProfile -ExecutionPolicy Bypass -File D:/tmp/kill_8710.ps1`
- subprocess 中文输出必须 `encoding="utf-8", errors="replace"`（默认 GBK 崩）
- MV3 SW 不热替换：改插件后须重启常驻浏览器
- 品牌 Chrome 137+ 禁 --load-extension：自动化采集用 Playwright 自带 chromium；
  回放可用真 Chrome（REPLAY_CHANNEL=chrome）
- docker exec 路径转换：`MSYS_NO_PATHCONV=1` 前缀

### 4.4 凭据模式（安全红线）
- 目标系统凭据经环境变量注入：ZENTAO_PW / ODOO_PW / DOLI_PW / ERPPW /
  SNIPE_PW / RuoYi 等——**字面值永不入代码/脚本/提交/文档**（禅道密码曾泄漏
  进 commit，amend 重写根治；教训：探测脚本转正式脚本时先扫密码字面量）
- 本地容器测试凭据可入脚本（若依 admin/admin123、Jeecg admin/123456、
  ERPNext Administrator/admin、Snipe admin/Snipe@618local）——仅限本地演示环境
- SkillLens 自身 LLM key/网关域名/njmind 凭据：.env（gitignore）永不出现在
  任何产物；提交前 diff 扫敏感串（sk-/密码值/域名）
- 登录类验证走编排层 API（如若依 POST /prod-api/login 拿 token），避免把
  '[REDACTED]' 占位输入回放

## 5. 开发纪律（详见 AGENTS.md，此处为最高频项）

1. **阶段闸门仪式**：三套测试全绿→代码审查(耦合+安全)→文档补全→浏览器用户层
   实测(截图入库)→用户测试报告→合并 main+删分支。Sprint 完成必走，缺一不可。
2. **TDD 先红后绿**；测试即规格（brief 与测试矛盾以测试为准）。
3. **成熟项目对照（强制，2026-10-02 固化）**：动手写实现/修 bug 前，先查同类
   问题的成熟 harness 怎么解——目标系统官方测试套件优先（容器内一手源码，
   如 Frappe 的 cypress/support/commands.js、Odoo 自己的 tour），其次
   Playwright/Healenium 等基础设施库源码。结论落到代码前注明出处模式。
4. **Debug 铁律（用户 2026-10-02 批评后固化）**："只要是超时，那肯定是有交互
   你没识别到"——先查页面现场（提示/弹窗/下拉开态/DOM 计数），不空等；页面
   有 alert/校验提示必须先看再动手。
5. LLM 产物异常先查 llm_call_log 实际输入输出，别先怪模型。
6. 计划外功能必须先进主计划获确认再动手。
7. 自主闭环授权：能自己验证的全自己闭环并如实报告（含盲区声明），只有真正的
   外部组织输入才留给用户；获"你来定"授权后按 Sprint 连跑不逐块请示。

## 6. 未竟项与下一步

### 6.1 技术：JeecG Sync/Fill 链式 override（小）
Sync 技能（#270）的行点击步 labels 是录制时的行文本（表名），回放新表时行
过滤不到目标行。修法：换参时把行文本注入 override（row-anchor 换参注入——
类似 runner 的 _row_anchor_token 分支，把 "override 变量" 也映射到行锚词）。
Create（#269）已全 PASS，物理表真实建出，阻塞面小。

### 6.2 流程：G4 试点团队（唯一外部输入）
技术已彩排验证（S27 彩排+S43-4 七系统）。需要用户指定真实试点团队 → K 块
两周试点（变更检测真实运行）。块 X（DB 深层验证）等试点反馈后定。

### 6.3 建议下一步顺序
1. 跑通三套测试确认基线（447/54/76）
2. 若继续技术线：JeecG 链式 override（§6.1）→ 补 Sync/Fill 回放全 PASS
3. 若走交付线：与用户对齐 G4 试点团队 → K 块试点启动（S18 计划在主计划）

## 7. 关键机制速查表

| 机制 | 位置 | 一句话 |
|---|---|---|
| C1 影子门控 | replay/plan.py + runner | 写操作未确认 → shadow run 零浏览器 |
| 语义定位 | replay/locate.py | 5 级语义链+评分兜底（Healenium 式多信号） |
| 自愈闭环 | replay/repair.py + api/locate_proposals.py | LLM 提案→实测验证→晋升→supersede |
| 写类按钮判定 | replay/runner.py | Frappe intercept+wait：等 POST 落地，无 POST 判"提交被拦" |
| 动态值对齐 | ingestion/alignment.py | 双侧归一 click:⟨dyn⟩ + 孤立对位置缝合（动态特征门） |
| inputKey 回退链 | extension/src/shared/input-key.ts | name→id→placeholder→aria→类信号→表单组 label |
| 四分类 | change/classify.py | 纯函数可重算复现 |
| flaky 重跑 | runner _attempt | fail 重试一次，不一致标 flaky |
| Playwright 导出 | replay/exporter.py | skill/flow → 自包含脚本 |

## 8. 接手提示词套件（6 枚场景化）

> 用法：接手者遇到对应场景时，直接投喂整段提示词给 AI（含本文件路径上下文）。
> 每枚提示词自包含：身份+必读文件+铁律+场景任务。所有提示词都假定 AI 已能
> 读本仓库文件。

### 8.1 通用接手（新会话冷启动）

```
你是 SkillLens 项目的全栈贡献者（需求/PM/开发/测试一体，用户授权自主闭环）。
按以下顺序学习并遵守全部纪律：

【必读（按序）】
1. docs/HANDOVER.md（交接总档——现状全景+环境+未竟项+提示词套件）
2. AGENTS.md（操作宪法——闸门仪式/TDD/安全红线/环境要点）
3. PROJECT-GUIDE.md（项目导览——目录地图+机制速查）
4. docs/COLLABORATION-CHARTER.md（协作宪章——项目所有者全部要求）
5. docs/specs/2026-09-23-skilllens-mvp-design.md（产品宪法 C1/C2/C3）
6. docs/specs/2026-09-24-master-delivery-plan.md（主计划 v2.0——唯一范围基准）
7. docs/references/project-lessons.md（踩坑经验库）

【环境自检（动手前必做）】
- 三套测试基线：server 447 / web 54 / extension 76（命令见 HANDOVER §3.3）
- 8710 在线（不在线则 START_RECORDING 报 Failed to fetch）
- 目标系统容器全启（端口表见 HANDOVER §4.1）

【铁律——违反任何一条都是事故】
1. C1 影子模式零例外；C3 全链路落库含失败调用。
2. LLM 只做命名/结构化/归因/提案，判定全确定性可复现。
3. TDD 先红后绿；测试即规格。
4. 计划外功能先修订主计划获确认再动手。
5. Sprint 必走闸门仪式（七步，见 AGENTS.md §一）。
6. 安全红线：真实 key/域名/凭据不入任何产物；提交前 diff 扫敏感串。
7. 成熟项目对照强制：修 bug 前先查目标系统官方 harness。
8. Debug 铁律：超时=有交互没识别到，先查页面现场不空等。
9. 能自验的全自闭环并如实报告（含盲区声明）。

【第一个任务】
跑通三套测试确认基线 → 读主计划 §7 变更记录（v1.0→v2.0 演进史）→ 从
demo/sprint43/user-test-report.md 看最近验收形态 → 报告你对现状的理解和
发现的任何疑问。
```

### 8.2 E2E 回放失败排查（最常用）

```
你在排查 SkillLens 的回放失败。技能回放某步超时或定位失败。

【先读】docs/HANDOVER.md §5（Debug 铁律）+ §7（机制速查）；
docs/references/project-lessons.md（同类坑可能已有解）。

【强制流程——顺序不可跳】
1. 查 llm_call_log：如果是学习/归纳问题，先看实际输入输出，别怪模型。
2. 查页面现场（不是看日志空等）：
   a. 截图/快照：有没有 alert、确认框、校验提示（红字）、加载遮罩？
   b. 目标元素 DOM 计数：元素在不在？被遮挡？disabled？在 iframe 里？
   c. 下拉/弹层开态：select2 弹层挂 body 与宿主无 DOM 关联（锚定法见
      input-key.ts 的 select2 分支）。
3. 查成熟项目：这个目标系统的官方 harness 怎么操作这个元素？
   （Frappe→容器内 cypress/support/commands.js；Odoo→容器内 tour 源码；
    element-plus 组件→其测试套件；通用→Playwright/Healenium 源码）
   结论落到代码前注明出处模式（如 "Frappe save 命令 = intercept+wait"）。
4. 根因分类后修复，禁止只加 sleep/加大超时绕过。

【已知高频坑（S43 沉淀）】
- 提交"成功"但实体没建：写类按钮没等 POST 落地（假阳性）——intercept+wait。
- checkbox 点不上：modal spinner 动画让 stability 永不满足——check(force=True)。
- 初始密码登录后页面锁死：强制"安全提示"弹窗没点确定。
- 空库列表不可交互：view sample 模式——先种一条真实数据。
- 模块功能缺失：必须走 UI toggle 激活，DB 直插不完整。
- 行点击定位到错行：跨 frame 纯文本同名抢match——[title=] 优先轮。
- 中文行文本过滤失败：无空格，用 ASCII 词边界 regex 切锚词。
- 无 name/id/placeholder 的输入框：表单组 label 终极回退（.ant-form-item 内）。
- el-select 空下拉：.el-select__placeholder 容器裸 span 文本，非 input 属性。

【修复后】
- 修 runner/locate 等引擎代码：必须配测试（TDD），全量回归三套。
- 修编排脚本：先扫密码字面量再转正式（安全红线历史事故）。
```

### 8.3 新目标系统接入

```
你要把一个新系统接入 SkillLens 验证（录制→学习→回放闭环）。参考 S43-4
七系统的做法（demo/sprint43/user-test-report.md §2 成果表+§3 根治记录）。

【标准流程】
1. 部署（docker 优先），凭据用环境变量注入（模式：ZENTAO_PW/ODOO_PW）。
2. 人工走通核心业务链一遍（先手工再自动化——用户方法论）。
3. 编排录制脚本：2 轮不同数据（参考 server/scripts/s43_erpnext_crm.py）。
   - 录制经 server API（START_RECORDING/STOP_RECORDING），SW 冷启动须轮询。
   - 常驻浏览器 9222（scripts/live_browser.py）全程用户可见。
4. 学习归纳 → 检查 skill 骨架质量（steps/labels/断言）。
5. 换参回放（参考 s43_erpnext_replay.py：override 换数据+实体级验证）。
6. 实体级验证：直查目标系统 DB/API 确认实体真实建出/流转（不是只看回放
   http 200）。
7. 失败排查按 8.2 提示词流程（成熟项目对照强制）。

【已知系统特性备忘】
- select2 AJAX 下拉：必须走 UI（点容器→搜→点结果），原生 select options 恒空。
- many2one（Odoo/ERPNext）：输入搜索选结果。
- SPA 路由直达：Odoo /web#action=xxx；JeecG 抽屉表单；禅道 iframe 业务页。
- 提交按钮按文本定位（页面常有多个 form，如搜索表单也是 submit）。
- 状态依赖注入：最新实体 id 经目标系统 API/DB 查出后注入 override。

【收尾】
- 证据 JSON 入 demo/sprintNN/（技能映射+回放结果）。
- 截图入 demo/sprintNN/screenshots/。
- 更新 HANDOVER §3.2 验证矩阵和项目记忆。
```

### 8.4 发版/变更验证（四分类核心场景）

```
你要验证一次系统发版：系统改了什么，SkillLens 的四分类报告是否如实检出。

【流程】
1. 确认基线技能健康（先跑一次全量回放，全 PASS 才开始）。
2. 在目标系统引入变更（真实改 UI/加字段/改行为——参考 S29 深度链路做法：
   njmind 表单真实加字段→重采集）。
3. 触发 Expected Delta：POST /api/change/expected-deltas 定义预期（哪个技能
   应该受影响、预期什么变化），人工确认。
4. 执行 Observed：回放受影响技能集。
5. 生成四分类报告并核验：
   - Expected（预期且检出）✓
   - Missing（预期但没检出——学习/断言有盲区）
   - Unexpected（没预期但检出——变更面超预期）
   - Drift（性能/视觉漂移）
6. 报告可确定性重算复现（G2 自验标准：从 replay_run 底层重算，报告与重算
   一致）。

【红线】
- destructive 变更必须走 C1 确认流，绝不影子外执行。
- 每次真实验证后更新 demo/sprintN/ 验收记录。
```

### 8.5 代码审查（Sprint 收口用）

```
你要审查 SkillLens 的一段新代码（Sprint 收口闸门第②步）。

【审查维度】
1. 耦合：新代码是否与现有实现不当耦合？纯函数优先/最小侵入/全调用方
   破坏面核实（搜全部调用点）。
2. 安全红线逐条扫：
   - 真实 LLM key/网关域名/njmind 凭据字面量（sk-/密码值/域名）
   - llm_call_log 异常摘要 URL 脱敏是否被绕过/回退
   - 插件密码框+敏感 label 双脱敏是否被绕过
   - subprocess 注入（shell=True+用户输入拼接）
   - SQL 拼接（应走参数绑定）
   - 路径穿越（用户可控路径）
3. LLM 边界：判定逻辑是否混入 LLM 调用？（必须确定性）
4. C1/C2/C3：影子门控是否可绕过；流量标记是否贯穿；失败调用是否落库。
5. 测试：新功能必配新用例；断言是否真的断言（不是恒真）。

【产出】
按维度逐条给结论，发现问题分级（P0 立即修/P1 本 Sprint/P2 记录）。
```

### 8.6 会议/汇报材料生成

```
你要为 SkillLens 生成对外材料（汇报/演示/对外文档）。

【叙事框架（对外统一，全员背诵）】
1. 痛点：内部系统每次发版，"应该改的没改、不该改的被弄坏"靠人肉回归。
2. 方案：AI 观察真实用户操作自动学出可回放测试；发版后自动四分类变更报告。
3. 差异化（不正面撞 Katalon"需求直出脚本"）：
   - Evidence Graph + 四分类（需求预期 vs 实际）——全赛道无人做
   - LLM 边界纪律：LLM 只提案命名，判定全确定性+人工确认
   - 私有化架构级默认：数据不出网是架构承诺
   - C1 影子门控零例外
4. 证据：七系统核心业务闭环（23 技能/22 回放 PASS/5 种前端框架）——
   demo/sprint43/；两次真实发版验收（njmind，G2）。

【数据引用规范】
- 测试基线：server 447 / web 54 / extension 76（引用前重跑确认）
- 系统数：7 个目标系统 + 1 个真实系统（njmind）
- 不引用内部容器凭据、网关域名、任何 .env 内容。
- UI 截图从 demo/sprintN/screenshots/ 取，确认无敏感信息。

【材料形态】
- 演示脚本：真实浏览器全程可见（用户要求），走图工作台→流程图→回放→报告链。
```

## 9. 文档地图（接手者阅读顺序）

```
第 1 天（世界观）：
  docs/HANDOVER.md → AGENTS.md → PROJECT-GUIDE.md → COLLABORATION-CHARTER.md
第 2 天（规格）：
  docs/specs/ 两份宪法/主计划（重点 §7 变更记录 v1.0→v2.0）
第 3 天（代码）：
  server/README.md → extension/README.md → server/web/README.md
  核心链路：replay/runner.py → replay/locate.py → ingestion/alignment.py →
  learning/ → change/classify.py → llm/gateway.py
第 4 天（历史与经验）：
  docs/references/project-lessons.md → docs/arch/（按需）→
  demo/sprint27+39+43/user-test-report.md（代表性验收形态）
第 5 天（上手）：
  跑通三套测试 → 起 8710+9222 → 图工作台逛一圈 → 挑一个技能回放一次
```
