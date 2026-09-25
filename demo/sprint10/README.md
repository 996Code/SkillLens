# Sprint 10 验收记录：真实流量切换（M2-块D，C2 生效）

日期：2026-09-25。分支 sprint10-real-traffic。
环境：8710 server（S10 代码）+ 常驻浏览器（CDP，新 SW 实例）+ njmind 192.168.99.22 + 真实 LLM。

## 验收标准（主计划块 D / 计划 Task 5-6）

> C2：真实流量归纳 Skill，置信度 ≥ 演示基线 80%；噪声处理与多路径分桶落地；对比测量可复现。

## 结果

| # | 验收项 | 结果 | 证据 |
|---|---|---|---|
| D1 | 流量标记 | ✅ | 4 个 real_traffic 会话（source 字段实测落库；popup→real_traffic / auto_record→demo） |
| D2 | 噪声过滤 | ✅（规则就位，本批数据未触发） | 四规则 13 用例 + filtered_window 落库审计端点；本次采集的浏览噪声被窗口切分自然吸收（跨页噪声另见发现#1） |
| D3 | 多路径分桶 | ✅ | 三会话 align 出 **2 桶**（保存流 ×2 + 重复保存流 ×1），skill_strategy 落库 |
| D4 | evidence_edge | ✅ | contains/calls 边落库（幂等累加，re-induce 不清） |
| D5 | **C2 真实流量学习** | ✅ | **真实流量 Skill #7：conf 1.0 / evidence 3 / 4 断言全 PASS / 回放 pass（8 观测项）** |
| — | **C2 对比测量** | ✅ | `confidence_ratio 1.087 ≥ 0.8 → meets_c2: true`；pass_rate_ratio 1.0 |
| — | 工作台呈现 | ✅ | source 徽标（真实流量绿）+ 基线对比区块（截图 2 张入 demo/sprint10/screenshots/） |
| — | 全量回归 | ✅ | server 165 / web 17 / extension 24 |

## C2 对比数据（GET /baseline/compare）

```json
{"demo": {"count": 5, "avg_confidence": 0.92, "avg_pass_rate": 1.0},
 "real_traffic": {"count": 1, "avg_confidence": 1.0, "avg_pass_rate": 1.0},
 "vs_baseline": {"confidence_ratio": 1.087, "pass_rate_ratio": 1.0, "meets_c2": true}}
```

## 过程发现（记入 lessons/台账）

1. **跨页噪声的数据质量问题**：多标签页会话中各页 CS 独立 seq，交错后窗口切分吸收了浏览噪声但事件流可读性差（会话 1 弃用）。真实多页噪声的完整处理是 S11+ 的观察项（单页内噪声已被本轮验证）。
2. **MV3 SW 不热替换**：dist 重建后运行中的 SW 仍是旧代码——`chrome.runtime.reload()` 后 SW 进入不可唤醒状态，须**浏览器重启**才换新（本次 source 标记失效的根因，已花一轮排查）。记入 lessons #16。
3. CDP 驱动的"真实感操作流"（走错/逛菜单/重复保存）可行，但跨页导航步在采集质量上不如人手操作——后续真实噪声样本优先用户日常录制。

## Sprint 回顾（宪法 §12）

- #1 C2 主链路闭环 ✓（真实流量→归纳→回放→对比达标）；#4 阶段纪律：未提前碰 Phase 3 内容 ✓。
- #6 C2 输入标记：demo/real_traffic 明确分轨 ✓；#7 C3：过滤决策/分桶/证据边全落库 ✓。
- #9/#10 客观达成（对比 JSON + 截图 + 三套测试）✓。

## M2 进度

S10 ✅ → S11 真实发版验收 ×2【闸口 G2：两次真实需求变更 + 团队评审】。
