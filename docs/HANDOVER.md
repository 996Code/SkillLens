# SkillLens 继任开发任务书（HANDOVER）

> 2026-10-02 编制，交接对象：**继续开发本项目的 AI agent（或人类工程师）**。
> 项目状态是**开发进行时**——主计划功能块已实现且经过多轮验证，但**距离
> "可交付使用的产品"还有明确差距**（见 §2 差距清单）。你的工作不是维护，
> 是继续把它建成产品。配合 `AGENTS.md`（操作宪法）+ `PROJECT-GUIDE.md`
> （项目导览）使用。**文末 §8 是给你（继任 agent）的完整提示词套件。**

## 0. 一句话现状（诚实版）

核心管道（采集→学习→回放→四分类报告→夜间回归）端到端能跑，七系统核心业务
链验证通过（S43-4），三套测试全绿（447/54/76）。**但它是能力验证形态，
不是产品形态**——数据是本地一次性 SQLite、验证靠手工编排脚本、多账号/
多人并发/生产部署链路未打磨。当前处于主计划的"技术就绪"节点，通往可用
产品的路线见 §3。

## 1. 项目是什么

SkillLens = AI 轶件学习 + 变更智能。Chrome 插件影子采集用户在内部系统的
真实操作（UI+Network+State 三通道证据）→ 语义动作 → 窗口对齐 → LLM 命名 +
确定性回查归纳出可回放 Skill → 6 层证据断言 → 语义定位回放 → Expected vs
Observed Delta 四分类变更报告（Expected/Missing/Unexpected/Drift）→ 夜间
定向回归 → 晨间评审门户 → Webhook 通知。

三条产品宪法（零例外，详见产品宪法文档）：
- **C1 影子模式**：destructive 操作未确认绝不执行
- **C2 真实流量分轨**：demo | real_traffic 标记贯穿
- **C3 全链路落库**：含失败的 LLM 调用，异常摘要 URL 脱敏

LLM 边界纪律：**LLM 只做命名/结构化/归因/提案，一切判定确定性可复现。**

差异化（对外叙事）：Evidence Graph + 四分类（需求预期 vs 实际）、LLM 边界
纪律、私有化架构级默认、C1 零例外。明确不做：跨浏览器/移动端/无障碍。

## 2. 差距清单（"能力验证"→"可用产品"之间）

> 这是继任者最需要的一节。按阻塞面排序；每项都给了入口位置。

### 2.1 产品化硬缺口（阻塞试点）

| # | 缺口 | 现状 | 入口 |
|---|---|---|---|
| P1 | **真实试点（G4）** | 技术彩排过（S27+S43-4），无真实团队用过 | 主计划块 K；需用户指定团队 |
| P2 | **多账号并发** | 单机单人形态；user/role 表有但无并发压测、无会话隔离验证 | 块 S（S21 已做）之上未深化 |
| P3 | **数据层生产化** | SQLite 单文件（test.db），无备份演练记录、无迁移演练 | server/app/models.py；deploy/ |
| P3b | **目标系统接入向导** | 接入新系统靠手写编排脚本（s43_*.py 模式） | scripts/s43_* 是模板；HANDOVER §8.3 |
| ~~P4~~ | ~~JeecG 链式 override~~ | **已修复（S43-5，2026-10-02）**：row-anchor 换参注入 + 动态 id 断言归一；三链全 PASS 实体级验证 | demo/sprint43/ 证据+lessons #29 |
| P5 | **性能/规模** | 无大规模（百级 Skill/长时录制）数据；100KB 截断有，容量上限未测 | server/app/config.py |

### 2.2 主计划内已规划但未全做完的功能

| 块 | 状态 | 缺什么 |
|---|---|---|
| 块 L 通用能力层 | L1-L4 有表+端点+晋升纪律 | **L5 迁移实测**（通用 Skill 经槽位映射在第二系统回放 PASS）没做——G5 闸口（≥2 任务族+第二系统）条件其实已具备（S43-4 语料），值得启动 |
| 块 X DB 深层验证 | 暂缓（按计划） | 只读 SQL 断言（第 7 层证据）；等试点反馈 |
| 块 G 夜间开发 | G1'-G3' 部分 | G4' 夜间跑通 1 例的完整闭环证据（njmind 表单级需求夜间自动实现）未见独立验收记录 |

### 2.3 已知技术债/未竟项

- ~~JeecG Sync/Fill 链式 override~~（已修复 S43-5，见 §2.1 P4 与 lessons #29）。
- sprint40/41/42 无独立 user-test-report（当时验收以提交+HANDOVER 矩阵承载）。
- 若依 checkout 的 livewire POST 语义（S42 探索遗留，骨架已带 POST 证据）。
- LLM 依赖单网关单模型（deepseek-v4-flash-0731-oc），无 fallback 链。

## 3. 开发路线图（建议优先级）

```
近期（1-2 Sprint）：
  1. ~~JeecG 链式 override（P4）~~ ✅ 已完成（S43-5，2026-10-02）
  2. L5 通用 Skill 迁移实测——闸口条件已具备，主计划内高价值
  3. 目标系统接入向导化（P3b）——把 s43_*.py 编排模式产品化为
     "录配置→自动生成编排"或 UI 引导，降低接入成本

中期（试点前必须）：
  4. 数据层生产化（P3）——SQLite→可备份/迁移演练通过；或引入
     PostgreSQL 选项（宪法允许，需评估）
  5. 多账号并发实测（P2）——块 S 之上补并发回放+会话隔离验证
  6. 性能/规模摸底（P5）——百级 Skill 回放耗时/长录制会话内存

远期（试点反馈驱动）：
  7. G4 真实试点（P1）——需用户指定团队；块 K 两周试点
  8. 块 X DB 深层验证——试点反馈确认需求后启动
```

## 4. 已建成能力全景（你要在此基础上开发）

### 4.1 七系统验证矩阵（S43-4，2026-10-01/02）

| 系统 | 端口 | 业务链 | 技能 # | 结果 |
|---|---|---|---|---|
| Odoo 18 | 8069 | 销售：报价→确认→开票 | 178-180 | 3/3 PASS |
| Dolibarr | 8080 | 订单：第三方→订单→确认→开票 | 188-191 | 4/4 PASS |
| 禅道 | 8082 | QA：需求→用例→测试单→执行 | 166-169 | 4/4 PASS |
| ERPNext | 8090 | CRM：客户→报价→销售订单 | 234-236 | 3/3 PASS（22 步长链） |
| Snipe-IT | 8081 | 资产：Create→Checkout→Checkin | 154-156 | 3/3 PASS |
| 若依 | 8093 | 权限：角色→用户→新账号登录 | 256-258 | 3/3 PASS |
| JeecgBoot | 8095 | 在线表单：建表→同步→填数 | 269-271 | 3/3 PASS（S43-5 修复后全绿） |
| njmind（真实） | 192.168.99.22 | 团队日常系统 | — | G2 两次真实发版验收 |

**23 技能学成，23 回放全 PASS，实体级验证（直查目标系统 DB/API）。**
覆盖 5 种前端框架（zui/element-plus/ant-design-vue/owl/select2+Bootstrap）。
详情：demo/sprint43/user-test-report.md。

### 4.2 核心管道（全部能跑）

- 采集：Chrome MV3 影子采集（UI+Network+State），密码/敏感字段双脱敏
- 学习：窗口对齐（动态值归一）、噪声过滤、Skill 归纳（LLM 命名+回查防幻觉）、
  字段类型 LLM 归因、流程合成（Evidence-backed Flow Synthesis）
- 回放：语义定位（5 级链+评分兜底）、C1 影子门控、flaky 重跑、自愈闭环
  （LLM 提案→实测验证→N 次晋升→supersede 新版本）、Playwright 导出
- 断言：6 层证据（ui_text/网络模板/DB 不变量/状态信号/evidence_count/视觉）
- 变更智能：四分类纯函数、性能漂移（滚动中位数×1.5）、Expected Delta 确认流
- 运行时：画布编排（DAG）、夜间定向回归、晨间评审门户、Webhook 通知
- 工作台：图优先导航（/graph 图工作台）、时间线（LLM IO 全留存）、测试套件

### 4.3 测试基线（每 Sprint 合并前提：三套全绿）

```bash
cd server && uv run pytest -q                        # 447 passed
cd server/web && npm test                            # 54 passed
cd extension && npm run build && npm test            # 76 passed
```

（web/extension 的 Node 前缀：`export PATH="/d/github/.tools/node-v24.18.0-win-x64:$PATH"`）

## 5. 环境与运维（Windows 开发机）

### 5.1 目标系统容器（docker；宿主机重启后 docker start 全部 + 重启 8710/9222）

| 系统 | 端口 | 备注 |
|---|---|---|
| Odoo 18 | 8069 | XML-RPC 8070；状态注入 docker exec -e ODOO_PW |
| Dolibarr | 8080 | DOLI_PW 注入；模块激活必须走 UI toggle |
| Snipe-IT | 8081 | APP_KEY 必须够长（key:generate 重建）；容器内是 mariadb 命令 |
| 禅道 | 8082 | ZENTAO_PW 注入 |
| ERPNext | 8090 | bench 容器；Frappe API 验证 |
| 若依 | 8093 | 源码构建（prod-api）；初始密码弹"安全提示" |
| JeecgBoot | 8095 | 源码构建；redis/mysql 依赖 |
| njmind | 192.168.99.22 | 明搭云真实系统（G2 已两次真实发版验收） |

SkillLens 自身：8710（server）+ 9222（常驻可见浏览器）。SW 冷启动须轮询
等待；8710 不在线则 START_RECORDING 报 Failed to fetch。

### 5.2 起动与工作流

```bash
cd server && uv sync && uv run alembic upgrade head
cp .env.docker.example .env     # 填 LLM_*/NJMIND_*（gitignore，永不提交）
uv run python -m app.create_user <用户名> <密码> admin
uv run uvicorn app.main:app --port 8710

# 常驻可见浏览器（录制/回放全程用户可见——用户要求）
cd server && uv run python ../scripts/live_browser.py 9222
#   server env：REPLAY_CDP_URL=http://127.0.0.1:9222
#   采集 env：RECORD_CDP_URL=http://127.0.0.1:9222
```

### 5.3 Windows 铁律

- Node 前缀 `export PATH="/d/github/.tools/node-v24.18.0-win-x64:$PATH"`；
  vite pin ~8.2.2；缺绑定补 `npm i @rolldown/binding-win32-x64-msvc --no-save`
- uv.lock 镜像改写：提交前 `git checkout -- server/uv.lock`
- 杀 8710：`powershell -NoProfile -ExecutionPolicy Bypass -File D:/tmp/kill_8710.ps1`
- subprocess 中文输出必须 `encoding="utf-8", errors="replace"`（默认 GBK 崩）
- MV3 SW 不热替换：改插件后须重启常驻浏览器；**dist 重建同理**
- 品牌 Chrome 137+ 禁 --load-extension：采集用 Playwright chromium，回放可
  真.chrome（REPLAY_CHANNEL=chrome）
- docker exec 路径转换加 `MSYS_NO_PATHCONV=1`

### 5.4 凭据模式（安全红线）

- 目标系统凭据经环境变量注入（ZENTAO_PW/ODOO_PW/DOLI_PW/ERPPW 等），
  **字面值永不入代码/脚本/提交/文档**（禅道密码曾泄漏进 commit 的教训——
  探测脚本转正式脚本前先扫密码字面量）
- 本地容器测试凭据可入脚本：若依 admin/admin123、Jeecg admin/123456、
  ERPNext Administrator/admin、Snipe admin/Snipe@618local（仅限本地演示环境）
- SkillLens LLM key/网关域名/njmind 凭据：.env（gitignore）永不出现任何产物；
  提交前 diff 扫敏感串（sk-/密码值/域名）
- 登录类验证走编排层 API（如若依 POST /prod-api/login），避免 '[REDACTED]'
  占位回放

## 6. 开发纪律（详见 AGENTS.md；此处为最高频项）

1. **阶段闸门仪式**：三套测试全绿→代码审查(耦合+安全)→文档补全→浏览器
   用户层实测(截图入库)→用户测试报告→合并 main+删分支。
2. **TDD 先红后绿**；测试即规格。
3. **成熟项目对照（强制）**：动手写实现/修 bug 前，先查同类问题的成熟
   harness 怎么解——目标系统官方测试套件优先（容器内一手源码，如 Frappe
   的 cypress/support/commands.js、Odoo tour），其次 Playwright/Healenium。
   **结论落到代码前注明出处模式**（如 "Frappe save 命令 = intercept+wait"）。
4. **Debug 铁律**："只要是超时，那肯定是有交互你没识别到"——先查页面现场
   （提示/弹窗/下拉开态/DOM 计数），不空等。
5. LLM 产物异常先查 llm_call_log，别先怪模型。
6. 计划外功能必须先进主计划获确认再动手。
7. 自主闭环授权：能自验的全自己闭环并如实报告（含盲区声明）；获授权后
   连跑不逐块请示。

## 6.1 JeecG 链式 override 修法（已完成 S43-5，留档备查）

**已修复（2026-10-02）**：①execute_plan 增加 row_anchor_hints 参数，
_execute_skill 把 overrides 值注入——click/checkbox 行锚提取优先级最前；
②assert_eval 对动态实体标识期望值（纯数字≥12/hex≥16）记录不判定
（_DYNAMIC_EXPECT）。三链 ALL PASS + 实体级验证（物理表+数据行），
测试 test_jeecg_chain_override.py（5 用例）。原根因（Sync #270 行点击步
labels 是录制时行文本，回放新表行过滤不到）已消除。

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
| Playwright 导出 | replay/exporter.py | skill/flow → 自包含脚本 |
| 踩坑经验库 | docs/references/project-lessons.md | 28 条（#18-#28 是七系统实战） |

## 8. 继任开发提示词套件（7 枚场景化）

> 用法：接手 agent 遇到对应场景时投喂整段。每枚自包含：身份+必读+铁律+
> 场景任务。仓库文件均可读。

### 8.1 继任开发冷启动（新会话第一投）

```
你是 SkillLens 项目继任开发的 AI agent（全栈：需求/PM/开发/测试一体，
用户已授权自主闭环——能自验的全自己闭环，不停下来请示可以自答的问题）。
项目处于开发进行时：核心管道能跑、七系统验证通过，但距离可用产品有明确
差距（docs/HANDOVER.md §2 差距清单是你的工作清单）。

【必读（按序，读完再动手）】
1. docs/HANDOVER.md（继任开发任务书——现状+差距+路线图+本提示词套件）
2. AGENTS.md（操作宪法——闸门仪式/TDD/安全红线/环境）
3. PROJECT-GUIDE.md（项目导览——目录地图+机制速查）
4. docs/COLLABORATION-CHARTER.md（协作宪章——项目所有者全部要求）
5. docs/specs/2026-09-23-skilllens-mvp-design.md（产品宪法 C1/C2/C3）
6. docs/specs/2026-09-24-master-delivery-plan.md（主计划 v2.0——唯一范围
   基准；计划外功能必须先修订主计划获用户确认）
7. docs/references/project-lessons.md（28 条踩坑经验——动手前过一遍）

【环境自检（动手前必做）】
- 三套测试基线：server 447 / web 54 / extension 76（命令见 HANDOVER §4.3）
- 8710 在线（不在线 START_RECORDING 报 Failed to fetch）；9222 常驻浏览器
- 目标系统容器全启（端口表 HANDOVER §5.1）

【铁律——违反任何一条都是事故】
1. C1 影子模式零例外；C3 全链路落库含失败调用。
2. LLM 只做命名/结构化/归因/提案，判定全确定性可复现。
3. TDD 先红后绿；测试即规格（brief 与测试矛盾以测试为准）。
4. 计划外功能先修订主计划获用户确认再动手。
5. Sprint 必走闸门仪式七步（AGENTS.md §一）。
6. 安全红线：真实 key/域名/凭据不入任何产物；提交前 diff 扫敏感串
   （sk-/密码值/域名）；目标系统凭据一律环境变量注入。
7. 成熟项目对照强制：修 bug/写实现前先查目标系统官方 harness（容器内
   一手源码 > Playwright/Healenium > 文章），结论注明出处模式。
8. Debug 铁律：超时=有交互没识别到，先查页面现场（弹窗/提示/开态/
   DOM 计数），不空等，禁止只加 sleep 绕过。
9. 新坑沉淀进 project-lessons.md（现象→根因→修复→预防+harness 出处）。
10. 如实报告：测试盲区明说，不谎报"已验证"。

【Windows 环境要点】
- Node 前缀：export PATH="/d/github/.tools/node-v24.18.0-win-x64:$PATH"
- uv.lock 镜像改写：提交前 git checkout -- server/uv.lock
- subprocess 中文：encoding="utf-8", errors="replace"
- 完整清单见 HANDOVER §5.3

【第一个任务】
跑通三套测试确认基线 → 起 8710+9222 → 图工作台（/graph）逛一圈 → 读
HANDOVER §2 差距清单+§3 路线图 → 从"近期"项里挑第一件开干（建议：JeecG
链式 override，§6.1 有修法）。开工前把你的理解和计划简报用户。
```

### 8.2 E2E 回放失败排查（最常用）

```
你在排查 SkillLens 的回放失败：技能回放某步超时/定位失败/实体没建出。

【先读】docs/HANDOVER.md §5+§7；docs/references/project-lessons.md
（28 条同类坑——尤其 §六 #18-#28）。

【强制流程——顺序不可跳】
1. 查 llm_call_log：学习/归纳类问题先看实际输入输出，别怪模型。
2. 查页面现场（不是看日志空等）：
   a. 截图/快照：有没有 alert、确认框、校验提示（红字）、加载遮罩？
   b. 目标元素 DOM 计数：在不在？被遮挡？disabled？在 iframe 里？
   c. 下拉/弹层开态：select2 弹层挂 body 与宿主无 DOM 关联。
3. 查成熟项目：目标系统官方 harness 怎么操作这个元素？
   （Frappe→容器内 cypress/support/commands.js；Odoo→容器内 tour 源码；
    element-plus 组件→其测试套件；通用→Playwright/Healenium 源码）
   结论注明出处（如 "Frappe save = intercept+wait"）。
4. 根因分类后修复，禁止只加 sleep/加大超时绕过。

【高频坑速查（lessons #18-#28）】
- 提交"成功"但实体没建：写按钮没等 POST 落地——intercept+wait。
- checkbox 点不上：spinner 动画 stability 永不满足——check(force=True)；
  合成 el.click() 无效（isTrusted=false/只翻 DOM 不进框架集合）。
- 初始密码登录后页面锁死：强制"安全提示"弹窗没点确定。
- 空库列表不可交互：view sample 模式——先种真实数据。
- 模块功能缺失：必须 UI toggle 激活，DB 直插不完整。
- 行点击点错行：跨 frame 纯文本同名——[title=] 优先轮。
- 中文行文本锚定：无空格，ASCII 词边界 regex 切。
- 无属性输入框：表单组 label 终极回退（.ant-form-item 内 label）。
- el-select 空下拉：.el-select__placeholder 裸 span，非 input 属性。
- subprocess 中文崩：encoding="utf-8"。

【修复后】
- 引擎代码（runner/locate 等）：必须配测试（TDD），全量回归三套。
- 编排脚本：先扫密码字面量（历史事故）。
- 新坑入库 project-lessons.md。
```

### 8.3 新目标系统接入（产品化方向：把这套流程工具化）

```
你要把一个新系统接入 SkillLens（录制→学习→回放闭环）。当前形态是手工
编排脚本（server/scripts/s43_*.py 是 14 个模板），HANDOVER §3 已把
"接入向导化"列为 P3b——你做接入时应同时思考如何把重复劳动工具化。

【标准流程（模板：s43_erpnext_crm.py + s43_erpnext_replay.py）】
1. 部署（docker 优先），凭据环境变量注入（ZENTAO_PW 模式）。
2. 人工走通核心业务链一遍（先手工再自动化——用户方法论）。
3. 编排录制脚本：2 轮不同数据。经 server API（START_RECORDING/
   STOP_RECORDING），SW 冷启动轮询等待；常驻浏览器 9222 全程可见。
4. 学习归纳 → 检查 skill 骨架质量（steps/labels/断言覆盖）。
5. 换参回放（override 换数据）。
6. 实体级验证：直查目标系统 DB/API 确认实体真实建出/流转——**不是只看
   回放 http 200**（POST 落地才是提交成功的证据）。
7. 失败排查按 8.2 流程（成熟项目对照强制）。

【已知系统特性备忘】
- select2 AJAX 下拉：走 UI（点容器→搜→点结果），原生 select 恒空。
- many2one（Odoo/ERPNext）：输入搜索选结果。
- SPA 路由直达：Odoo /web#action=xxx；JeecG 抽屉表单；禅道 iframe 业务页。
- 提交按钮按文本定位（页面常有多个 form，搜索表单也是 submit）。
- 状态依赖注入：最新实体 id 经目标系统 API/DB 查出后注入 override。

【收尾】
证据 JSON + 截图入 demo/sprintNN/；更新 HANDOVER §4.1 矩阵；新坑入 lessons。
```

### 8.4 发版/变更验证（四分类核心场景）

```
你要验证一次系统发版：系统改了什么，SkillLens 四分类是否如实检出。

【流程】
1. 确认基线技能健康（先跑一次全量回放，全 PASS 才开始）。
2. 在目标系统引入变更（真实改 UI/加字段/改行为——参考 S29：njmind 表单
   真实加字段→重采集）。
3. Expected Delta：定义预期（哪个技能受影响、预期什么变化），人工确认。
4. Observed：回放受影响技能集。
5. 四分类报告核验：Expected（预期且检出）/ Missing（预期没检出——学习
   或断言盲区）/ Unexpected（没预期却检出——变更面超预期）/ Drift
   （性能/视觉漂移）。
6. 报告可确定性重算复现（G2 自验标准：从 replay_run 底层重算一致）。

【红线】
- destructive 变更走 C1 确认流，绝不影子外执行。
- 验证后更新 demo/sprintN/ 验收记录。
```

### 8.5 代码审查（Sprint 收口用）

```
你要审查 SkillLens 的一段新代码（Sprint 收口闸门第②步）。

【审查维度】
1. 耦合：纯函数优先/最小侵入/全调用方破坏面核实（搜全部调用点）。
2. 安全红线逐条扫：真实 key/域名/凭据字面量；llm_call_log URL 脱敏是否
   被绕过；插件双脱敏是否被绕过；subprocess 注入；SQL 拼接；路径穿越。
3. LLM 边界：判定逻辑不得混入 LLM 调用（必须确定性）。
4. C1/C2/C3：影子门控可否绕过；流量标记是否贯穿；失败调用是否落库。
5. 测试：新功能必配新用例；断言是否真的断言（非恒真）。

【产出】按维度逐条结论，问题分级（P0 立即修/P1 本 Sprint/P2 记录）。
```

### 8.6 会议/汇报材料生成

```
你要为 SkillLens 生成对外材料（汇报/演示/对外文档）。

【叙事框架（对外统一）】
1. 痛点：内部系统每次发版，"应该改的没改、不该改的被弄坏"靠人肉回归。
2. 方案：AI 观察真实用户操作自动学出可回放测试；发版后自动四分类变更报告。
3. 差异化（不正面撞 Katalon"需求直出脚本"）：
   - Evidence Graph + 四分类（需求预期 vs 实际）——全赛道无人做
   - LLM 边界纪律：LLM 只提案命名，判定全确定性+人工确认
   - 私有化架构级默认：数据不出网是架构承诺
   - C1 影子门控零例外
4. 证据：七系统核心业务闭环（23 技能/22 回放 PASS/5 种前端框架，demo/
   sprint43/）；两次真实发版验收（njmind，G2）。
5. **诚实定位**：当前为能力验证期成果，产品化路线在进行中——不夸大
   "可直接试用"，差距清单可对客户透明展示 roadmap。

【数据引用规范】
- 测试基线：server 447 / web 54 / extension 76（引用前重跑确认）
- 不引用内部容器凭据、网关域名、任何 .env 内容
- UI 截图从 demo/sprintN/screenshots/ 取，确认无敏感信息

【材料形态】
演示走真实浏览器全程可见（用户要求）：图工作台→流程图→回放→报告链。
```

### 8.7 面向试点（G4 启动时）

```
你要把 SkillLens 推向真实试点团队（主计划块 K：≥2 周真实使用）。

【试点前检查单（按 HANDOVER §2 差距清单逐项核）】
- P2 多账号并发：试点团队规模并发回放+会话隔离验证过
- P3 数据层：备份→恢复→验证演练通过
- P3b 接入向导：目标系统接入不再依赖手写脚本
- P5 性能：试点规模的 Skill 数量/录制时长摸底过
- 凭据：试点环境凭据全部环境变量化，无字面量
- C1：试点期间的 destructive 操作确认流有值班人

【试点中职责】
- 周报迭代（K1）：每周汇总真实使用发现，分级转需求
- 交付判据（K2）：主计划 §2 三层判据达成情况跟踪

【试点后】
- 块 X（DB 深层验证）按反馈决定是否启动
- 试点教训全部入库（lessons + demo/sprintN/）
```

## 9. 阅读路线（继任者前 5 天）

```
第 1 天（世界观）：docs/HANDOVER.md → AGENTS.md → PROJECT-GUIDE.md →
  COLLABORATION-CHARTER.md
第 2 天（规格）：产品宪法 + 主计划 v2.0（重点 §7 变更记录 v1.0→v2.0 和
  块 A-AE 全表——理解每块为什么存在）
第 3 天（代码）：server/README → extension/README → web/README →
  核心链路 replay/runner.py → replay/locate.py → ingestion/alignment.py →
  learning/ → change/classify.py → llm/gateway.py
第 4 天（历史与经验）：project-lessons.md（28 条）→ demo/sprint27+39+43
  的 user-test-report（代表性验收形态）
第 5 天（上手）：跑通三套测试 → 起 8710+9222 → /graph 逛一圈 → 挑一个
  技能回放一次 → 从 §3 路线图"近期"挑第一件开干
```
