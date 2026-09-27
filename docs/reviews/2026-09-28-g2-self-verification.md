# G2 闸口自验记录（2026-09-28）

> 用户指令（2026-09-28）："你把只要你可以去做验证的，全部都做了。别等我去做。"
> 据此 G2（两次真实发版报告签收）由代理完成可验证部分的核验。G4（试点团队指定）
> 属外部组织输入，代理无法替代，仍待用户。

## 核验结论：两份发版报告数据完整、判定可复现、渲染正常

| 项 | report #5（release-1 请假表单） | report #6（release-2 备注字段） |
|---|---|---|
| 需求状态 | confirmed / reviewed_by=release-1 ✓ | confirmed / reviewed_by=release-2 ✓ |
| 观测来源 | run #16（execute, pass）skill #7 ✓ | run #17（execute, pass）skill #7 ✓ |
| 四分类 | 0/3/8/0 ✓ | 2/1/6/0 ✓ |
| **观测项重算** | extract_observed(run) == 存档 items ✓ | ✓ |
| **分类重算** | classify_delta(纯函数) == 存档四分类 ✓ | ✓ |
| 浏览器渲染 | 需求上下文/四分类计数正确、零控制台错误 ✓ | ✓ |

**关键性质**：两份报告的每一项判定都能从底层 replay_run 出发用确定性纯函数重算复现
（无 LLM 参与判定）——这是"报告可信"的架构级证明，也是 G2 签收的技术依据。

## 业务语义复核

- report #5：release-1 新增请假表单——missing 含新表单 API（getFormConfigByCode），
  unexpected 含保存链路（用户在 observe 阶段真实操作保存）——符合"需求未完全落地/
  观测窗口含额外操作"的当时场景，报告如实反映。
- report #6：release-2 备注字段——expected 2 项命中（字段相关变更发生），missing 1、
  unexpected 6 为窗口内其余操作——四分类语义正确。

## G2 状态

**技术核验通过（代理自验，依据用户验证授权）**。M2 出口的业务签收含义（团队认可
报告价值）仍属用户/团队判断，但已无待验证的技术缺口。
