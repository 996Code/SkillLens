# Sprint 22：块 T 视觉回归断言（断言第 6 层）

> 主计划 v1.6 块 T。对标 Applitools/Percy/Mabl 的截图基线比对——我们已有回放快照存档，
> 本块补"比对引擎+判定+呈现"。确定性，无 LLM（宪法：判定全确定性）。
> TDD 先红后绿；完成后走阶段闸门仪式。

## 设计决策

- **图像库**：Pillow（唯一新依赖；纯 Python 做 PNG 解码+缩放不现实）。
- **比对算法**（两级，全确定性）：
  1. dHash（9×8 灰度差分哈希，64 位）初筛——汉明距离 ≤ `VISUAL_HASH_MAX_DISTANCE`（默认 4）直接 pass；
  2. 距离超限 → 像素级比对：逐像素通道差 > `VISUAL_PIXEL_TOLERANCE`（默认 16）计为差异像素，差异占比 ≤ `VISUAL_DIFF_THRESHOLD`（默认 2%）pass；尺寸不同按基线尺寸缩放后比对并记 size_changed 标志。
- **基线生命周期**：skill 首次 execute PASS → 截图存基线（`artifacts/visual/{skill_id}/baseline.png` + visual_baseline 表行）；此后每次 execute 都比对并把结果作为断言 kind=visual_baseline 追加进 assertion_results（自动进一致性统计）；基线可人工重置（reviewer/admin，删除后下次 PASS 重建）。
- **shadow 不比对**（不启浏览器，C1 语义不变）。
- **存储**：baseline.png + latest.png（比对时更新，供前后图并排）；latest 截图仅在有基线时保存。

## 任务

### T1 比对引擎（纯函数）
- app/replay/visual.py：dhash / compare_images(baseline, current) → {passed, hash_distance, diff_ratio, threshold, size_changed}；阈值走 config（env 可调）。
- 测试：同图距离 0；改图超阈 fail；占比阈值边界；尺寸变化。

### T2 基线模型+迁移+runner 集成
- models：VisualBaseline（skill_id 唯一、file_path、image_hash、width/height、source_run_id、created_at）；迁移。
- runner._execute_skill：PASS 且无基线 → 存基线；有基线 → 截 latest.png、比对、追加断言结果、参与 status 判定。
- conftest：REPLAY_ARTIFACT_DIR 指测试临时目录（防污染真实 artifacts）。
- 测试（真实 Playwright page + route mock）：首 PASS 建基线；页面改版后回放 → visual 断言 fail → run fail；重置后下次 PASS 重建。

### T3 API
- app/api/visual.py：GET /skills/{id}/visual-baseline（基线信息+最近比对结果）、POST .../reset（reviewer/admin）、GET .../image?which=baseline|latest（FileResponse，无用户路径输入防穿越）。
- main.py 挂 guarded router。
- 测试：建基线后端点返回；reset viewer 403 / reviewer 200；image 200/404。

### T4 前端呈现
- SkillDetail 视觉回归区块：基线/最新图并排 + 比对结果（diff_ratio、pass/fail 徽标）+ 重置按钮（admin/reviewer 可见）。
- vitest：区块渲染、无基线空态、viewer 无重置按钮。

### T5 收尾
- 三套测试全绿 + 浏览器实测（真实回放建基线→改版→fail→重置闭环）+ 截图入库 demo/sprint22/ + 用户测试报告 + 文档（server README/arch）+ 合并 main。

## 验收标准（对照主计划块 T）

- [ ] T1 首次 execute PASS 存视觉基线，可人工重置
- [ ] T2 感知哈希初筛+差异占比阈值（配置化），确定性无 LLM
- [ ] T3 比对结果作为断言 kind=visual_baseline 参与回放判定与一致性统计
- [ ] T4 报告/详情显示视觉差异结果与前后图并排
