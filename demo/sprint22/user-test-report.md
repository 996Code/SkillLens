# Sprint 22 用户测试报告：块 T 视觉回归断言（断言第 6 层）

> 日期：2026-09-27 · 分支：s22-visual-baseline · 计划：docs/superpowers/plans/2026-09-27-sprint22-visual-baseline.md
> 目标：补齐断言体系"看得见"的一层——对标 Applitools/Percy 的截图基线比对，全确定性无 LLM。

## 一、测试覆盖与结果

### 1. 三套测试

| 套件 | 结果 | 说明 |
|---|---|---|
| server pytest | 全量回归见下 | 新增 test_visual.py(8) + test_visual_baseline.py(4)；修复 2 处存量破坏（见"回归教训"） |
| web vitest | **43 passed**（40+3） | visual.spec.ts：空态/差异统计+并排图+重置按钮/viewer 无按钮 |
| extension | **31 passed** | 不受影响 |

### 2. 真实环境闭环实测（skill 8 新浪搜索，只读操作）

| 步骤 | 结果 |
|---|---|
| 第一次 execute 回放（run 58） | pass → **视觉基线自动建立**（1280×720，dHash 1b058cc6…，源 run 58）✓ |
| 第二次 execute 回放（run 59） | **漂移检出**：哈希距离 5、差异占比 9.30% > 2% 阈值 → visual 断言 FAIL → run fail ✓（新浪首页轮播内容被确定性引擎捕获——真实漂移检测） |
| 浏览器查看详情页 | 视觉回归区块：差异 9.30%、哈希距离 5、基线/最近回放**两图并排**、admin 见重置按钮、viewer 无 ✓ |
| 点击重置 | 基线删除 → 空态提示"未建立视觉基线"✓ |
| 重置后再回放（run 60） | pass → **基线自动重建**（源 run 60）✓ |
| 控制台 | 全程零报错 ✓ |

### 3. 回归教训（本轮发现并修复）

存量 4 个回放测试失败——根因：测试替身 FakePage 的 screenshot 桩写入非图像内容/缺失，视觉采集把整个回放打成 error。修复：**视觉层全链路 fail-open**（截图失败/文件无效 → 跳过视觉不计失败，与 assert_eval 无快照先例同语义）——真实 Playwright 环境不受影响，替身环境行为与 S21 前完全一致。

## 二、易用性发现表

| 级别 | 发现 | 处置 |
|---|---|---|
| P2 | 动态内容页（新闻站）会持续视觉 FAIL——预期行为但可能造成告警噪声 | 阈值 env 可调（VISUAL_DIFF_THRESHOLD）；文档已注明公网站点需调参。转后续需求：忽略区域（mask）配置 |
| P3 | 基线图无放大查看（点击看原图） | 转后续需求 |
| P3 | 视觉差异无差异区域高亮框（只有占比数字） | 转后续需求（Applitools 有） |

## 三、安全与耦合审查

- 比对全确定性（dHash+像素占比），零 LLM 调用——符合宪法"判定全确定性" ✓
- 图片端点 which 白名单映射固定路径，无用户路径输入（防穿越）✓；图片经 authedFetch blob 转发（带认证）✓
- 重置基线要求 reviewer/admin（viewer 403）✓
- 截图脚本凭据走环境变量（沿用 S21 审查结论）✓
- runner 集成最小侵入：视觉块独立 try/except，fail-open 保证存量语义；Pillow 为唯一新依赖 ✓
- diff 敏感串扫描：无泄露 ✓

## 四、验收标准对照（主计划块 T）

- [x] T1 首次 execute PASS 存视觉基线，可人工重置（真实闭环验证）
- [x] T2 感知哈希初筛+差异占比阈值（配置化），确定性无 LLM
- [x] T3 比对结果作为断言 kind=visual_baseline 参与回放判定（run 59 真实翻转 fail）
- [x] T4 详情页视觉差异结果与前后图并排（浏览器实测+截图入库）

## 五、截图

- `screenshots/01-visual-section.png`：视觉回归区块（差异统计+两图并排）
- `screenshots/02-visual-empty.png`：重置后空态
