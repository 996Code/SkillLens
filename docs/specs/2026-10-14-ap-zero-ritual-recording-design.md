# AP 块：零仪式录制（Implicit / Ambient Recording）设计方案

> 2026-10-14 用户提出方向 + 业界调研 + 架构积木核实完成。
> **状态：设计已细化、未立项未动手**——下次继续时从本文档 §6 落地路线
> 直接开工（先补 §7 主计划立项记录）。
> 背景：用户想法——"强依赖用户的录制（定义名称、开始、结束）能不能简化？
> 只要打开目标网站就自动监控录制，后台分析、总结、合并。"

## 1. 业界调研结论（一手来源，2026-10-14 调研）

**没有任何产品做成"插件常驻+打开目标站即录+任务级切分+LLM 命名+多录归并"
的完整形态。** 三类玩家各自逼近：

| 产品 | 形态 | 关键机制 | 卡点 |
|---|---|---|---|
| **Meticulous**（最接近） | script tag 全录日常操作 | **回避任务切分**——整段会话回放+代码分支覆盖驱动测试策划；mock 后端响应免测试账号 | 要改代码集成；不产出命名流程 |
| **Katalon TrueTest** | 生产遥测→测试 | 频次排名挑旅程+与现有套件 diff 补缺口+**强制人审晋级** | 依赖遥测管道 |
| **Reflect**（SmartBear） | 会话内零仪式 | 托管浏览器打开 URL 即全录 | 会话边界仍显式（创建/保存） |
| 对照组（mabl/Testim/DevTools Recorder） | 全部显式 Start/Stop | — | QA Wolf 已转 agentic 探索，录制器退场 |

**可直接采用的事实标准**：
- 会话级切分：**30 分钟空闲 / 24h 上限**（PostHog/FullStory/Microsoft Clarity 三家一致）
- 任务级切分：神策数据的**边界事件切割**（"支付完成"类业务信号当任务边界）
- 噪声处理：**没人删事件**——Clarity 标注（rage/dead click）、TrueTest 频次排名，保留+分层

**核心卡点**（FullStory 官方点破）：意图缺失——全录后"哪段是任务、断言什么"
没有信号。ProdPerfect（生产流量直转测试）已死；幸存者都加了**人审关口**。

来源：meticulous.ai / katalon.com/truetest / smartbear.com/product/reflect /
posthog.com/docs/data/sessions / help.fullstory.com / learn.microsoft.com/clarity /
manual.sensorsdata.cn（Session 切割）/ fullstory.com/blog/record-and-playback-vs-session-replay

## 2. 我们的差异化（为什么值得做）

1. **纯插件侧常驻录制**——对比 Meticulous 要改代码、TrueTest 要遥测管道
2. **LLM 只做命名/归因/合并建议，判定保持确定性**——恰好符合 C1-C3 宪法
3. **多次录制归并成可复用链**——全行业空白（现有 supersede 机制是独有底座）

## 3. 架构积木盘点（2026-10-14 已核实）

**可直接复用（改造量小）**：
- 录制开关是纯 storage 位（`sl_recording`，capture.ts:19-54 storage.onChanged
  跟随）——SW 可按 URL 自动拨
- URL→系统配对现成：P2.5 油猴 @match（插件已在消费 `/adapters/match`，
  session.ts:23-36）
- 停录自动学习现成（AI1：停录→process→induce→60s 进空间面板）
- LLM 命名管道现成（宪法划定 LLM 唯一职责）
- supersede 归并有先例（禅道 99→40、296→321）
- `scripts/auto_record.py` 已实证 SW 程序化开关录制（runtime.sendMessage
  START/STOP_RECORDING 经扩展页面中转）

**真正的缺口（=工作量大头）**：
1. **任务级切分器**——会话内把"闲逛"与"任务流"切开（业界无现成答案）
2. **噪声闸门**——纯浏览流不进学习管道（防 is_junk_label 防线被冲垮）
3. **合并决策**——两段录制是同任务→归并还是 supersede

## 4. 设计：三片（AP1-AP3）

### AP1 常驻采集
- SW 监听 tab 更新：URL 命中任一 adapter url_matches → 自动拨 `sl_recording`
  （打开被接管站即录；离开则停）
- 事件/会话带 **ambient 源标记**（C2 分轨——防污染 real_traffic 学习口径，
  events.py:41 的 source 字段扩展 "ambient" 值）
- 用户显式开录仍优先（popup 开录 = real_traffic，不被 ambient 覆盖）

### AP2 任务切分 + 噪声闸门（纯确定性规则，参数可配）
切分信号（会话内，从 RawEvent 流派生）：
- **短空闲**：90s 无交互 → 候选边界（对齐会话级 30min 事实标准的任务级缩小版）
- **导航闭环**：列表→详情→回列表（URL 形态回环）
- **写操作边界事件**：写请求（POST/PUT/PATCH）+ 后续 30s 无新交互 → 任务完成信号
  （神策边界事件模式）

闸门（discard 流不进学习，但 C3 全落库留痕可查）：
- 无任何写操作 且 无导航闭环 → discard（纯浏览）
- 事件数 < 5 → discard（误触）
- 全是输入无提交 → discard（半途而废）

### AP3 发现流 + 一键入库（学 TrueTest 人审关口）
- 切出的任务流跑现有 process→align→induce（LLM 自动命名）
- 进"待发现"状态（新 session status 或独立表）——空间面板显示
  "发现 N 个流程"卡片：名称+步骤摘要+来源系统
- 用户点确认 → 转正式 candidate 技能（现有晋升轨道）
- 归并建议：同系统相似骨架（Jaccard 阈值）→ 提示"与技能 X 相似，可
  supersede/组链"——只建议不自动执行

### 红线（不破）
- C1 影子：ambient 只录不执行
- C2 分轨：ambient 源标记独立于 real_traffic
- C3 全落库：discard 流也留痕（reason 字段记闸门判据）

## 5. 风险与对策

| 风险 | 对策 |
|---|---|
| 切分错误（两任务揉一/一任务撕两） | 切分器纯规则+参数可配；发现流人审兜底（确认前可看步骤摘要） |
| 学习管道被噪声冲垮 | 闸门三判据 discard 不进 process；ambient 标记与 real_traffic 分轨 |
| LLM 成本（每段都 induce） | 只对过闸门的任务流 induce；discard 零 LLM 调用 |
| "被录制"信任问题 | 插件仅在已声明接管的系统域录（url_matches 白名单制，非全网录） |

## 6. 落地路线（下次开工入口）

1. **立项**：主计划 §7 加 AP 块变更记录（本文档为设计依据）
2. **AP1**（~1 天）：SW tab 监听+auto 拨 sl_recording+ambient 源标记；TDD +
   真机（打开 Snipe 站自动出录制红点）
3. **AP2**（~2 天）：切分器+闸门纯函数（服务端 `app/learning/segment.py` 新
   模块）+参数配置；TDD 用真实历史会话回放调参
4. **AP3**（~1-2 天）：发现流状态+面板卡片+确认端点+归并建议；
   真机验收=用户日常用一个系统半天，看发现流出的是否真任务
5. 验收后文档同步（arch/ 新篇+HANDOVER 增量）

## 7. 关联文件索引（改哪里）

| 位置 | 内容 |
|---|---|
| `extension/src/background/uploader.ts` | 会话创建（加 ambient 源标记） |
| `extension/src/background/session.ts` | URL→系统配对（auto 拨录制位在这） |
| `extension/src/content/capture.ts` | 录制位跟随（无需改——storage 驱动） |
| `server/app/api/events.py:41` | C2 源标记（扩 ambient 值） |
| `server/app/learning/`（新 segment.py） | AP2 切分器+闸门 |
| `extension/src/content/space-panel*` | AP3 发现流卡片 |
| `server/app/adapters/manifest.py` | url_matches（白名单源） |
| 现成参考：`scripts/auto_record.py` | SW 程序化开关录制实证 |
