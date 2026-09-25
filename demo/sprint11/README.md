# Sprint 11 验收记录：真实发版验收 ×2（块 E，M2 出口）

日期：2026-09-25。环境：8710 server + 常驻浏览器 + 真实 LLM + 明搭云 192.168.99.22。
SOP：docs/arch/2026-09-25-release-sop.md（E1）。

## 发版 1：新增"请假申请"表单（真实变更，用户授权创建）

| 步骤 | 结果 |
|---|---|
| 需求 | 新增请假申请表单（请假人/类型/起止日期/天数/事由） |
| Expected（真实 LLM draft + 人工确认） | draft 5：LLM 产 ui_action 完整描述 + 猜测 API（/leave/form/...）；人工修订为真实观测形态（getFormConfigByCode） |
| 真实变更 | 表单已创建（formCode=qingjiashenqing，6 字段，权限齐备）——demo/sprint10 截图存档 |
| Observe | skill 7 回放 **pass**（8 项） |
| **Report 5** | **expected 0 / missing 3 / unexpected 8 / drift 0** |

**四分类解读（真实可解释）**：
- missing 3 = 新表单页面 + getFormConfigByCode——表单**真实存在**但回放路径（ceshi000001 保存流）不经过 → **机制边界①：回放路径外的新功能不可见**（N1 立项依据坐实）
- unexpected 8 = 既有保存流完整保留 → **回归面完好**（replay PASS）
- getFormConfigByCode 实际在回放页载时被调用，但页载 GET 在锚点窗口外、不进断言模板 → **机制边界②：observed 提取范围=断言命中的 API**

## 发版 2：ceshi000001 新增"备注"字段（回放路径上的真实变更）

| 步骤 | 结果 |
|---|---|
| 需求 | ceshi000001 新增备注字段（beizhu），保存接口保持正常 |
| Expected | draft 6：LLM 直接给出正确 api_status 预测（saveFormConfig/saveTableConfig -> 200，需求文本引导有效） |
| 真实变更 | 备注字段已添加保存（18 字段，业务码 200） |
| Observe | skill 7 回放 **pass**（8 项） |
| **Report 6** | **expected 2 / missing 1 / unexpected 6 / drift 0** |

**四分类解读**：
- **expected 2 正向命中**（saveFormConfig api_add + api_status）——**四分类 Expected 匹配在真实发版首次验证成功**
- missing 1 = "新增备注字段" ui_action——快照已采集该字段（after_snapshot 22 forms）但设计器预览输入框共享 placeholder"请输入"、字段名不进 label → **机制边界③：UI 证据已采集但 label 消歧不足**（S8 台账预告，现有发版级实证）
- 回归面：保存流程未被破坏 ✓

## N1 观察数据汇总（v1.3 观察项，块 N 输入）

| 边界 | 实证 | 块 N 对应 |
|---|---|---|
| ①回放路径外新功能不可见 | 发版1 missing 3 | N1 新功能增量发现 |
| ②observed 只提取断言命中 API | 页载 GET 不可见 | N1/N4 |
| ③快照 label 消歧不足 | 发版2 备注字段无法定位 | N3+label 消歧（S8 台账） |

## M2 出口对照

| 标准 | 状态 |
|---|---|
| 两次真实发版四分类报告产出 | ✅ report 5/6，截图 3 张 |
| 四分类准确（真实可解释） | ✅ 两次报告逐项解读如上；expected 正向命中 + 回归面验证 |
| 报告在工作台呈现 | ✅ /reports/5、/reports/6 + /audit 证据链 |
| **团队认可有行动价值** | ⏳ **待用户核签（E3 评审）** |

## 结论

机制层面 M2 出口标准达成；三次机制边界发现全部转化为块 N 的精确立项依据。**等用户评审：打开 http://127.0.0.1:8710/reports/5 与 /reports/6（或看 demo/sprint11/screenshots/），核签"有行动价值"即 M2 出口闭合。**
