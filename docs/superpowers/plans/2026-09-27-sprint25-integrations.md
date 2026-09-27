# Sprint 25：块 W 集成出口（v1.6 最后一个执行块）

> 主计划 v1.6 块 W。让"变更智能"进入团队真实工作流；导出直接回应
> QA Wolf"确定性代码进仓库"论点。TDD 先红后绿；多维度测试；完成后走阶段闸门仪式。

## 设计决策

- **W1 Playwright 导出**：`GET /skills/{id}/export/playwright` → 自包含 Python 脚本
  （内联语义定位函数，与 locate.py 同策略链）；步骤=骨架计划；断言=api_status/
  state_signal 经 expect_response 实现，其余 kind 以注释标注"工作台侧判定"；
  变量=脚本顶部 OVERRIDES 字典。**真机验证**：导出脚本以子进程独立运行打真实
  本地 HTTP 服务（http.server mock），期望退出码 0 + PASS 输出。
- **W2 Webhook**：`WEBHOOK_URL`（空=关）+ `WEBHOOK_FORMAT`（wecom|dingtalk|slack|generic）。
  触发点：报告生成（change.report）+ 画布运行完成。httpx POST fire-and-forget，
  失败 logging 不阻塞主流程。多格式 payload 单测（MockTransport）。
- **W3 需求条目关联**：expected_delta 加 `external_ref` 列（String(100) nullable）；
  创建时可带；GET 透出；DeltaReport 需求上下文展示。v1 不做 Jira API 对接（计划明确）。

## 多维度测试矩阵

| 维度 | 覆盖 |
|---|---|
| 真机独立运行 | 导出脚本子进程跑真实 http.server mock 页 → PASS |
| 断言含盖 | api_status/state_signal 在导出脚本中生效（改状态码 → 脚本 FAIL 非零退出） |
| 格式 | webhook 四格式 payload 结构单测（MockTransport） |
| 触发点 | 报告生成触发一次推送；WEBHOOK_URL 空=零调用 |
| 字段 | external_ref 创建/透出/报告页展示；缺省不显示 |
| 回归 | 存量 334 全绿 |

## 任务

- T1 W3 external_ref（列+迁移+API+前端展示）
- T2 W2 webhook 模块+触发点
- T3 W1 导出器+端点+真机运行验证
- T4 前端（导出入口按钮）+ 收尾闸门（三套全绿+浏览器实测+截图+报告+文档+合并）
