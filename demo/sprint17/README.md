# Sprint 17 验收记录：语义定位强化 + 通用能力层（块 L 落地）

日期：2026-09-25。分支 sprint17-semantic-generic。SWOT P0/P1 落地。

## 验收结果

| # | 功能点 | 结果 | 真实证据 |
|---|---|---|---|
| T1 | 语义定位强化 | ✅ | 插件 input-key 跳过框架自动生成 id（rc_select_N/ant-/纯数字）——28 passed（+1 用例） |
| L1 | generic_skill 模型 | ✅ | 表+模型+迁移 a8c3e1f7b4d9 |
| L2 | 归纳端点 | ✅ | 真实 LLM 从 njmind#7+新浪#8 归纳出 `SubmitInputAction`（4 槽位：input_control/submit_button/primary_api/status_field），**确定性回查通过** |
| L3 | 晋升纪律 | ✅ | 双系统（/codeBack + /api）+ 双源回放 PASS + **回查未通过不可晋升**（新增纪律）→ learned |
| L4/L5 | 槽位映射+迁移 | ✅ | map→新浪 skill complete=True（槽位↔变量/锚点/API 全对齐） |
| — | 工作台呈现 | ✅ | 列表页"通用能力层"区块（3 行 learned 徽标，截图 01） |
| — | 三套测试 | ✅ | server **247**（232→247）/ extension **28**（27→28）/ web 34 |

## 实施中的真发现与修复

1. **LLM 幻觉被确定性回查抓住**（设计验证的实战证明）：第二轮归纳 LLM 编造了不存在的 `state_signal:/api/search:code` 断言 → 回查失败 → candidate+notes → **新增晋升纪律堵洞**（回查失败的 candidate 不许升 learned）。
2. **列表值回查误判**：LLM 把 API 槽位示例聚成数组，回查按整串匹配失败 → 修为逐元素回查。
3. **前端 API 路径笔误**（/generic-skills 缺 /api/v1 前缀 → SPA fallback 吞 HTML → fail-open 静默）——浏览器实测抓出。

## UI 评估（用户指令：测试时确认界面是否需优化）

S16 新 UI（侧栏/令牌/统一组件）在 S17 浏览器实测中表现良好：区块自动继承 `.block`/`.tbl`/`.badge` 全局类零额外样式。**待优化项记录**：①通用 Skill 无详情页（点击行无交互——后续加）②槽位 examples 在列表页未展示（详情页需求）③侧栏在窄窗口（<1000px）会挤压内容区。均低优先级，不阻塞。

## Sprint 回顾（宪法 §12）

- #1 块 L（用户裁定的通用化方向）全量落地 ✓；#8 LLM 边界：归纳回查实战抓住幻觉 ✓。
- G5 闸口正式闭合：双系统归纳→晋升→映射全链真库通过。
