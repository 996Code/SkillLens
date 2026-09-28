# S34 块 1：竞品差距补齐——回放 run 详情页 + 截图点击放大

> 2026-09-28。需求：对标参考系统（Katalon TrueTest / mabl / Testim / Applitools /
> QA Wolf）盘点差距并补齐高价值项。
> 差距结论：自愈/视觉基线/版本演化/换参回放/flaky/性能基线/导出/Webhook/
> 需求关联/夜间调度/评审门户均已对齐；欠缺 ①run 级详情下钻页 ②截图点击放大
> ③多目标系统实证（块 2）。本块补 ①②。

## 交付

### 回放 run 详情页（/replay-runs/{runId}）

- 头部：状态大字（四态分色）+ mode/flaky 徽标 + duration_ms + created_at + Skill 链接
- 执行步骤表：kind/目标/定位策略（含 repair: 前缀）/成败与失败原因
- 步骤截图墙（ShotGallery，点击放大）
- 断言明细表 + 失败归因 + 前后快照 forms 对比（同 ReplayLaunch 结果区）
- 入口：时间线 replay 项"下钻 run 详情"；直达 URL 可分享

### ShotGallery 共享组件（src/components/ShotGallery.vue）

- 网格缩略图 + lightbox（Teleport 全屏遮罩，点遮罩关闭）
- 自取图（fetchStepScreenshot blob URL），watch 换源重取、卸载 revoke
- 单张失败显示"截图缺失"占位，不阻塞整墙
- TimelineView 内联截图墙替换为本组件（获得点击放大能力）

### 共享格式化（src/run-format.ts）

- assertExpect / assertObserved / snapshotDiffRows / shotCaption /
  stepScreenshotFiles——ReplayLaunch 与 ReplayRunView 同源，消除两份拷贝

### 后端

- GET /replay-runs/{id} 与 POST /skills/{id}/replay 响应补
  duration_ms / flaky / created_at（TDD：test_replay_run_detail_fields）

## 测试

- server：test_replay_api.py +1（run 详情字段契约）
- web：ReplayRunView.spec.ts（头部/步骤/断言/归因 + lightbox 开关）+2；
  TimelineView/ReplayLaunch 回归适配
- 浏览器实测：scripts/s34_block1_screenshots.py 四步用户路径
  （详情页直达 → 截图墙 → lightbox 开关 → 时间线下钻），截图入 demo/sprint34/
