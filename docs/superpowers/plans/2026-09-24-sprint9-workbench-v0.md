# Sprint 9 工作台 v0 Implementation Plan（M1-块C）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 派生自：`docs/specs/2026-09-24-master-delivery-plan.md` 块 C（C1-C4）。

**Goal:** 只读+触发的工作台 Web 界面：Skill 卡片、四分类报告页、回放触发——让"报告被团队评审"有载体（M2 闸口 G2 的评审界面），全程不写新后端业务逻辑。

**Architecture:** ①FastAPI 静态托管 `server/web/dist`（StaticFiles mount，index.html fallback），生产同容器零新增部署面；②前端 Vite+Vue3 单页（无 UI 框架依赖也可，选 Vue 因画布 S14 复用其生态——现在引入最小 core）；③数据全走现有 API：GET /skills、GET /skills/{id}/assertions、GET /expected-deltas/{id}、POST /expected-deltas/{id}/observe、GET /replay-runs/{id}；新增一个只读聚合端点 GET /api/v1/skills/{id}/card（骨架+变量+断言+最近 run 概要，避免前端拼 N 次请求）。回放触发带 shadow/execute 选择（execute 需勾选"我已确认副作用"复选，前端二次确认弹层——C1 的 UI 化呈现）。

**Tech Stack:** Vue 3 + Vite（extension 工具链已有 Vite 经验；Node 24 便携版 PATH）；后端零新依赖。

**Spec:** 主计划块 C；宪法 §0.3 Phase 2 出口（"报告被团队认可"的载体）。

## Global Constraints

- **只读边界**：工作台不得出现任何编辑 Skill/断言/Expected 的入口（confirm 仍走 API/curl，UI 化留给 S11 评审实战后定）。执行类仅 observe 触发。
- **C1 UI 化**：execute 模式 = 单选"shadow（默认）" + 复选"确认执行副作用"二要素齐备才发 confirm_side_effect=true。
- **API 纪律**：仅新增 GET /skills/{id}/card 一个只读端点；其余全复用。
- **测试**：后端 card 端点 TDD；前端组件 vitest（关键交互：模式选择门控）；整体浏览器实看验收（宪法工作方式）。
- **测试基线**：S8 合入后数字；每任务全量绿。

---

### Task 1: card 聚合端点（TDD）

**Files:**
- New: `server/app/api/cards.py`
- Modify: `server/app/main.py`（挂路由）
- Test: `server/tests/test_cards_api.py`

**Interfaces:**
- Produces: `GET /api/v1/skills/{id}/card` → `{skill 概要, skeleton[], input_variables, assertions[{id,kind,layer,payload}], last_run{status,mode,ts}, evidence_count, window_params(S7)}`；404 处理。

- [ ] **Step 1: 红**——造 skill+断言+run → card 返回聚合结构。
- [ ] **Step 2: 绿**——实现 + main 挂载。
- [ ] **Step 3: 全量**。

### Task 2: 前端骨架与路由

**Files:**
- New: `server/web/`（Vite+Vue 项目：package.json/vite.config/index.html/src/main.ts/App.vue/router）
- Modify: `server/app/main.py`（StaticFiles 挂 /web 路径，dist 不存在时跳过挂载不崩）

**Interfaces:**
- Produces: 路由 `/skills`、`/skills/:id`、`/reports/:deltaId`；API base 相对路径（同源部署零配置）。

- [ ] **Step 1: 脚手架**——npm create vite（vue-ts 模板最小裁剪），dev 代理 8710。
- [ ] **Step 2: 三路由空页 + 导航壳**——构建通过（Node 24 PATH），vitest 起步用例。
- [ ] **Step 3: 后端挂载**——`uv run uvicorn` 后 http://127.0.0.1:8710/web/ 可达（index fallback）。

### Task 3: Skill 列表与详情页（C1）

**Files:**
- New: `server/web/src/views/SkillsList.vue`、`SkillDetail.vue`、`api.ts`

**Interfaces:**
- Consumes: GET /skills、GET /skills/{id}/card。

- [ ] **Step 1: 列表**——卡片网格：name/status 徽标/confidence/evidence_count/断言数（card.last_run 状态点）。
- [ ] **Step 2: 详情**——骨架签名步骤流、变量值域、断言表（kind/layer/期望）、窗口参数、证据计数；空态/404 态。
- [ ] **Step 3: vitest**——api.ts mock 下两视图渲染断言（关键数据上屏）。

### Task 4: 四分类报告页（C2）

**Files:**
- New: `server/web/src/views/DeltaReport.vue`

**Interfaces:**
- Consumes: GET /expected-deltas/{id} + 报告数据（delta_report 行——新增只读 GET /api/v1/reports/{id} 若无现成读取端点，TDD）。

- [ ] **Step 1: 红+绿（如需新端点）**——reports 读取端点。
- [ ] **Step 2: 四栏视图**——expected/missing/unexpected/drift 分色卡；每项 type 徽标 + value；missing 红/unexpected 橙/drift 灰。
- [ ] **Step 3: 证据下钻**——api_* 项链接到对应 skill 断言行（跳详情锚点）。

### Task 5: 回放触发与结果（C3+C1 UI）

**Files:**
- New: `server/web/src/views/ReplayLaunch.vue`（或并入 SkillDetail 区块）
- Modify: `server/app/api/cards.py`（如需 run 概要补字段）

**Interfaces:**
- Consumes: POST /expected-deltas/{id}/observe（或 /skills/{id}/replay）、GET /replay-runs/{id} 轮询。

- [ ] **Step 1: 表单**——skill 选择 + overrides 键值对编辑（来自 card.input_variables）+ 模式单选（shadow 默认）+ 副作用确认复选；二者不齐禁用提交。
- [ ] **Step 2: 结果页**——run 状态（pass/fail/shadow/error 色）、断言明细表、失败归因文本块、（S8 后）前后快照对比区。
- [ ] **Step 3: vitest**——门控逻辑单测：shadow 默认安全、复选未勾禁用、勾选后 confirm_side_effect=true。
- [ ] **Step 4: 浏览器实测**——真实 server 上 shadow 409 与 execute PASS 各一次。

### Task 6: 验收 + 合并

- [ ] **Step 1: 端到端实看**——不看 DB/curl 完成"看报告→触发 shadow→触发 execute→看结果"全流程（宪法 UI 类交付标准）。
- [ ] **Step 2: 全量回归**——pytest + server/web vitest + extension vitest（三套）。
- [ ] **Step 3: lessons + 合并 main**。
- [ ] **Step 4: M1 放行预审**——对照主计划 M1（S7 债清+基线锚、S8 快照补盲、S9 可视化）逐条自检表，提交用户放行 M2。
