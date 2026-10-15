# AP：零仪式录制——架构契约（AP1-AP3 全量）

> 2026-10-15 落地。设计：`docs/specs/2026-10-14-ap-zero-ritual-recording-design.md`。
> 改 ambient/切分/发现流模块前必读。

## 1. 链路

```text
用户打开接管站（url_matches 白名单）
  → AP1 ambient 自动开录（source=ambient，C2 分轨）
    → 用户离开接管站 → 自动停录 + AI1 待学标记
      → AP2 切分（三信号）+ 闸门（三判据，discard 留痕）
        → 过闸段 → DiscoveredFlow（pending 待发现）
          → AP3 人审（空间面板卡片）
            → 确认 → 段事件复制成新会话 → 既有 process→align→induce
              → LLM 命名技能（candidate/learned）
```

模块：`extension/src/background/ambient.ts`（AP1）、
`server/app/learning/segment.py`（AP2 纯函数）、
`server/app/api/discovered_flows.py`（AP3）、
`extension/src/content/space-panel.ts`（发现卡片）。

## 2. 不变量

1. **白名单制**：仅在已声明接管的系统域录（/adapters/match——非全网录，
   信任边界）。match 失败 fail-closed 不开录。
2. **用户显式优先**：sl_ambient 标记区分会话归属——ambient 不覆盖用户
   开录、不越权停止用户会话；显式开录前 ambient 会话先 flush（缓冲不丢）。
3. **C2 分轨**：ambient 源独立于 real_traffic/demo——学习口径不污染。
4. **C1 影子**：ambient 只录不执行。
5. **C3 全落库**：discard 段留痕（DiscoveredFlow.auto_discarded+reason）；
   ambient trace 落 storage。
6. **判定全确定性**：切分/闸门纯规则（GateConfig 参数可配）；LLM 只在
   人审确认后的 induce 命名（宪法 C1）。
7. **幂等**：segment 对同会话 409；confirm 只允许 pending 态。

## 3. API

| 端点 | 行为 |
|---|---|
| POST /sessions/{sid}/segment | 仅 ambient；切分+建 DiscoveredFlow；重复 409 |
| GET /discovered-flows?status= | 四态列表（pending/confirmed/discarded/auto_discarded） |
| POST /discovered-flows/{id}/confirm | 段→新会话→process→align→induce→skill_id 回填 |
| POST /discovered-flows/{id}/discard | 人审丢弃（reason=user_discarded） |

## 4. 切分/闸门参数（GateConfig 默认）

- idle_s=90（短空闲边界）；write_quiet_s=30（写边界静默窗）；
  min_events=5（误触下限）；loop_path_depth=2（导航闭环详情深度）
- 闸门：无写且无闭环=pure_browsing；<5=too_few_events；
  全输入无提交=no_submit

## 5. 已知坑（实证）

- **Chrome 扩展 SW 模块图缓存极粘**：改 SW 代码后版本 bump+浏览器重启
  都可能不够——须 chrome.runtime.reload()（真机验证前必做）。
- **MV3 reload 后旧 tab content script context 失效**（不轮询不采集）——
  真机验证须全重启浏览器。
- 切分边界消费语义：切分触发即消费写时间戳（同事件双信号/后续交互
  不重复触发）。

## 6. 后续衔接

- 归并建议：确认时 Jaccard 相似骨架比对→提示"与技能 X 相似"（只建议）。
- AP×AR：发现流确认产出的技能可一键组建场景（Scenario origin=learned）。
- popup 显示 ambient 状态（当前 note 文案区分）。
