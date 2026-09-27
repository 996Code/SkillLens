# Sprint 25 用户测试报告：块 W 集成出口（v1.6 收官）

> 日期：2026-09-27 · 分支：s25-integrations · 计划：docs/superpowers/plans/2026-09-27-sprint25-integrations.md
> 目标：让"变更智能"进入团队真实工作流；导出直接回应 QA Wolf"确定性代码进仓库"论点。

## 一、多维度测试矩阵结果

| 维度 | 用例 | 结果 |
|---|---|---|
| **真机独立运行（终极）** | skill 8（新浪搜索）导出脚本**脱离平台**子进程独立打真实公网站点 → PASS（退出码 0），全部 API 断言通过 | ✓ |
| **真机独立运行（受控）** | 导出脚本打本地 http.server mock → PASS；服务端改 500 → FAIL（退出码 1 + 明细） | ✓ test_export ×3 |
| **断言含盖** | api_status + state_signal 在导出脚本内判定；ui_text/field_change/视觉以注释标注"工作台侧判定"（不伪造能力边界） | ✓ |
| **格式** | webhook 四格式 payload（wecom/dingtalk/slack/generic）+ 未知格式回落 generic | ✓ test_webhook ×6 |
| **触发点** | 报告生成 → 一次推送（含报告 id 与四分类计数）；画布运行完成 → 推送；WEBHOOK_URL 空 → 零调用 | ✓ |
| **健壮性** | webhook 推送失败（500/超时）→ 返回 False 不抛（fire-and-forget 不阻塞主流程） | ✓ |
| **字段** | external_ref 创建/GET 透出/报告页展示；缺省 null 不渲染（存量零影响） | ✓ 后端 2 + vitest |
| **前端** | 详情页"导出 Playwright 脚本"按钮；报告页外部需求编号 | ✓ vitest ×2 + 浏览器 |
| **回归** | 存量 334 全绿 | ✓ 348 passed |

### 三套测试

| 套件 | 结果 |
|---|---|
| server pytest | **348 passed**（334+14：external_ref 2 + webhook 9 + export 3） |
| web vitest | **50 passed**（48+2：integrations.spec.ts） |
| extension | **31 passed** |

## 二、交付内容

- **W1 Playwright 导出**：`GET /skills/{id}/export/playwright` → 自包含脚本（内联语义定位
  与模板匹配，与工作台同规则）；OVERRIDES 顶部可改换参回放；导出脚本可进用户仓库/CI
  ——"确定性可审计导出"直接回应 QA Wolf 论点
- **W2 Webhook**：`WEBHOOK_URL`+`WEBHOOK_FORMAT` 配置化；报告生成与画布/夜间运行完成
  触发推送；fire-and-forget
- **W3 需求条目关联**：expected_delta.external_ref（Jira key 等）存字段+报告页展示；
  v1 不做 Jira API 对接（计划明确）

## 三、审查结论

- 导出脚本不内嵌任何凭据/网关信息（纯公开步骤+断言）✓
- webhook payload 只含报告摘要（无敏感数据）；URL 走 env 不落库 ✓
- exporter 模板匹配与 assert_eval 同规则（`{id}`/数字/UUID 段过滤）——导出与工作台判定一致性 ✓
- diff 敏感串扫描：无泄露 ✓

## 四、易用性发现

| 级别 | 发现 | 处置 |
|---|---|---|
| P3 | 导出脚本无 C1 门控概念（脚本即真实执行）——语义正确：导出=人工取走执行权 | 文档注明 |
| P3 | 流程（synth_flow）暂无导出端点 | 转后续需求 |
| P3 | webhook 无重试队列 | 可接受——fire-and-forget 设计，失败有 logging |

## 五、截图

- `screenshots/01-export-button.png`：详情页导出按钮

## 六、验收标准对照（主计划块 W）

- [x] W1 skill → 可执行 Playwright 脚本导出（含断言），导出脚本独立运行验证（真实新浪站点 PASS）
- [x] W2 报告生成/运行完成 → webhook 推送（企微/钉钉/Slack 格式，URL 配置化）
- [x] W3 expected_delta 关联外部需求编号（存字段+展示）
