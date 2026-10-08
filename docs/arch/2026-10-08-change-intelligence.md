# 变更智能（Change Intelligence）：需求 → 预期变更 → 观测 → 分类 → 报告

> 2026-10-08。一句话职责：把一条**软件需求文本**结构化为可机器核对的预期变更清单
> （ExpectedDelta），在真实系统上执行技能得到**观测**（ObservedDelta），再**确定性**分类为
> expected/missing/unexpected/drift 四桶并生成报告——"需求是否真的实现了"由证据回答，不由人拍板。
> 宪法依据：C1（人工确认门 + 判定全确定性）、C3（全链路落库）。

## 1. 数据模型（`server/app/models.py`）

| 表 | 关键列 | 谁写 | 谁读 |
|---|---|---|---|
| `expected_delta` | `requirement_text` / `requirement_id` / `external_ref` / `feature` / `changes`(JSON) / `status` / `reviewed_by` | api/change.py | classify、impact、web DeltaReport |
| `observed_delta` | `expected_delta_id` / `skill_id` / `replay_run_id` / `items`(JSON) / `duration_ms` | change/observed.py | classify、perf |
| `change_report` | `expected_delta_id` / `observed_delta_id` / `result`(JSON 四桶) | api/change.py /report | web 报告页 |

状态机（`expected_delta.status`）：`draft` →（人工 confirm，`reviewed_by`=登录用户）→ `confirmed`
→（observe 产生 ObservedDelta）→（report 分类）→ `reported`。

## 2. 生命周期与端点（`server/app/api/change.py`，全部挂鉴权，见角色矩阵）

| 端点 | 鉴权 | 行为 |
|---|---|---|
| `POST /expected-deltas` | `WRITE_GUARD` | LLM 把需求文本结构化为 `{feature, changes[]}`（`change/expected.py:build_prompt`）；`parse_delta` 贪婪正则提 JSON；`verify_delta` 确定性校验（类型 ∈ {ui_action, api_add, api_status}、非空、≤20 条——`expected.py:33-40`），**校验失败不入库**，原始 LLM 输出照落 llm_call_log（C3） |
| `POST /expected-deltas/{id}/confirm` | `require_role(admin,reviewer)` + **reviewed_by 取登录态** | C1 人工门：body 只可带修订后的 `changes`（会先 `verify_delta`，无效则 422 要求提交修订）；`row.reviewed_by = user.username`（`change.py:63`）。确认成功后 `link_discoveries` 把 changes 与 `discovered_feature` 按 api 模板/anchor label 配对 |
| `POST /expected-deltas/{id}/observe` | `WRITE_GUARD` | `run_observe`：跑一次真实回放（`run_replay`，confirm_side_effect 默认 false）→ `extract_observed` **纯确定性**提取观测（executed 的 ok click/input → ui_action；assertion_results 的 api_template → api_add / api_status）→ 落 ObservedDelta。shadow run 天然提取为空（executed/assertion_results 为 None，`observed.py:8-10`） |
| `POST /expected-deltas/{id}/report` | `WRITE_GUARD` | `classify_delta` 四桶分类（§4）+ `perf.py` 性能比对，落 change_report |
| `GET /expected-deltas/{id}` | require_user | 详情 |

## 3. 为什么 C1 确认门必须取登录态（三轮评审 R3-2）

原实现 `reviewed_by` 取请求体——任何 viewer 提交 `{"reviewed_by": "admin"}` 即可"代表管理员"完成
确认并触发后续 execute，审计不可抵赖性失效。对照 `reviews.py:73` 早已正确用 `user.username`。
现两处（change/dev_plans）统一 `Depends(require_role("admin","reviewer"))` + 落库登录名，
请求体字段已删除。直测：`server/tests/test_role_gates.py`（冒充 admin 的 viewer → 403；
reviewer → 落库为 reviewer 用户名）。

## 4. classify_delta 判定规则（`change/classify.py:27-86`，全确定性）

输入：expected changes（可能经人工修订，**原样保留**——`expected.py:64` 注释明示）与 observed items。

- **畸形条目防御**（本轮加固）：`_well_formed()` 要求 dict 且 `type`/`value` 非空——人工修订可
  造出缺键行，畸形项不参与匹配，按 C3 **带 reason** 记入 missing/unexpected（`_malformed_entry`），
  绝不 KeyError 500。
- **匹配按对象身份消费**（本轮加固）：`matched_ids: set[int]` + `id(o)`——旧实现 `list.index()`
  对重复 `(type,value)` 永远返回首个，第二条重复观测永不被标记 matched 而误报 unexpected。
- **api_status 特判**：期望值形如 `"/x/y -> 200"`（`_api_of` 拆解）；同 api 命中但 code 不等 → **drift**
  （`f"{api}: {want} -> {got}"`）而非 missing；drift 项对应的 observed 条目不算 unexpected。
- **ui_action 宽匹配**：`e.value in o.value or o.value in e.value`（子串互含，容忍"点击 保存" vs
  "点击了保存按钮"的措辞差）。
- 输出四桶：`expected`（双方都有）/ `missing`（期望了没观测到）/ `unexpected`（观测到没期望——
  变更外的行为外溢）/ `drift`（同 api 状态漂移）。

## 5. 性能比对（`change/perf.py`）

观测 run 的 `duration_ms` 与该 skill 历史基线（中位数）比对，`current > median × PERF_DRIFT_RATIO`
（默认 1.5，env 可调）判漂移；历史 <3 次不判定（样本不足宁缺毋滥）。结果并入报告。

## 6. 影响分析（`app/api/impact.py` + `app/impact/`）

`POST /impact/analyze`：给定变更点（api 模板 / anchor label），反查哪些 skill 的骨架或断言
引用了它 → 输出受影响技能清单与证据边，供"改这里会炸哪些链"的回归圈定。`GET /impact/last`
取最近一次分析。匹配双形态：裸模板 vs 方法前缀（`_template_to_actions`/`_anchor_to_actions`）。

## 7. dev_plans 与 LLM 边界（`app/api/dev_plans.py` + `app/agents/devplan.py`）

- `POST /dev-plans`：LLM 把需求分解为开发计划步骤（**只做分解**）；`verify_dev_plan` 确定性回查
  （步骤可映射到既有技能/发现，回查失败落 draft + notes 不吞，C3）。
- `POST /dev-plans/{id}/confirm`：C1 人工门，同 §3 取登录态（`dev_plans.py:73`）。
- `POST /dev-plans/{id}/execute`：`agents/dev_executor.py` 按计划逐步浏览器执行。
- dev_executor 读 `NJMIND_*` env（fail-fast，不写 fallback）。

## 8. 已知债务（代码确证）

| 项 | 位置 | 说明 |
|---|---|---|
| classify 的 `ui_action` 子串互含过宽 | classify.py:66-68 | "输入 name=甲" 会匹配 "输入 name=甲乙"——观测侧有值截断时可能双向误配；目前无实测误判案例，收紧需先定观测值归一规则 |
| ObservedDelta 无 source 分轨 | models.py | 与 C2 相关：demo 与 real_traffic 的观测混在同一 expected_delta 下（同 §ingestion C5，产品决策） |
| 报告页路由参数名 `deltaId` 实际承载 report id | web DeltaReport.vue | 命名误导（E11，卫生项） |

## 9. 测试覆盖地图

| 行为 | 覆盖 | 位置 |
|---|---|---|
| LLM 结构化 + verify 失败拒收 + llm_call_log 留痕 | ✅ | test_expected_delta.py |
| confirm 人工门角色/登录态/修订校验 422 | ✅ | test_role_gates.py、test_expected_delta.py |
| observe 确定性提取（ok 步/断言模板/shadow 空） | ✅ | test_observed_delta.py |
| classify 四桶 + api_status drift + ui_action 宽匹配 | ✅ | test_delta_classify.py |
| classify 重复 (type,value) 按身份消费、畸形条目带 reason 不崩 | ✅ | test_delta_classify.py（本轮 +） |
| perf 漂移阈值/样本不足不判 | ✅ | test_perf.py、test_perf_report.py |
| impact 模板/锚点双形态命中 | ✅ | test_impact.py |
| dev_plans 分解/confirm/execute + LLM 边界 | ✅ | test_dev_plans.py |
| **未覆盖**：报告端到端（confirm→observe→report 全链 API 级） | ❌ | 分段都有、串联无 |
