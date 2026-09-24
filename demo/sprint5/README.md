# Sprint 5 验收记录：演示 3——njmind 改一个需求 → 四分类报告

日期：2026-09-24。Skill #2 `SaveFormAndTableConfig`（Sprint 4.5 全自动录制诱导，learned，
4 断言），登录态 `scripts/njmind_login.py` 自动产出注入（REPLAY_STORAGE_STATE）。

## 验收标准（spec §7 Sprint 5）

> 演示 3：njmind 改一个需求 → 输出报告；四分类中 Missing 和 Unexpected 至少各能被真实构造触发一次。

## 流程实录

### 1. 需求 → Expected Delta（真实 LLM，qwen3.7-plus）

需求文本：`表单设计器保存后应调用表格配置保存接口，且接口返回成功状态`

LLM 原始产物（draft，llm_call_log purpose=expected_delta）：

```json
[{"type": "api_add", "value": "/formConfig/saveTableConfig"},
 {"type": "api_status", "value": "/formConfig/saveTableConfig/code -> 200"}]
```

**人工修订**（confirm 时覆盖——spec §4.6 "人工确认后生效"的弥合入口）：

```json
[{"type": "ui_action", "value": "点击 保存"},
 {"type": "api_add", "value": "/codeBack/tableConfig/saveTableConfig"},
 {"type": "api_status", "value": "/codeBack/tableConfig/saveTableConfig -> 200"},
 {"type": "ui_action", "value": "新增复制按钮"}]
```

修订点：LLM 的 api 模板缺 `/codeBack` 前缀与 `tableConfig` 段、api_status 多 `/code` 段
（与观测形态不一致）；补 ui_action 两条——其中"新增复制按钮"**故意虚构**（真实系统没有），
用于构造 Missing。

### 2. Observe（真实回放）

`POST /expected-deltas/1/observe`（skill_id=2, overrides 请输入=delta-demo-001,
confirm_side_effect=true）→ 回放 run 13 **pass**（表单真实改名），8 观测项
（详见 delta-report.txt）。

### 3. 四分类报告（确定性，无 LLM 参与判定）

| 分类 | 数量 | 内容 |
|------|------|------|
| expected | 3 | 点击 保存；/codeBack/tableConfig/saveTableConfig（api_add + api_status -> 200） |
| **missing** | 1 | **新增复制按钮**（验收点 ✓——需求说要有，实际没有） |
| **unexpected** | 5 | **输入 请输入=delta-demo-001；saveFormConfig + getTableConfigByFormConfigId（各 api_add + api_status）**（验收点 ✓——需求未提，实际发生） |
| drift | 0 | 无时序数据（MVP 设计内） |

### 4. C1 核验（shadow 短路）

`confirm_side_effect=false` → HTTP 409 `{"detail": "shadow run 未执行，无观测"}`；
observed_delta 表仍 1 条（无新增）。持久回归测试 `test_observe_shadow_returns_409` 已入库。

## 结论

spec §7 Sprint 5 验收标准全达成：演示 3 完整链路（需求→LLM→人工确认→真实回放→四分类报告）
真实跑通，Missing 与 Unexpected 均被真实构造触发。测试基线 pytest 90。

## LLM 边界核验（spec §12 #8）

- 生成走 LLM（expected_delta purpose 落 llm_call_log）✓
- verify_delta/classify_delta 纯函数无 LLM；四分类判定全确定性 ✓
- LLM 产物形态与观测值不一致时靠人工 confirm 修订弥合（设计内路径）✓
