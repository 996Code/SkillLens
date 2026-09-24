# Sprint 7 验收记录：技术债清障 + 演示基线固化

日期：2026-09-24。分支 sprint7-tech-debt-baseline（a4c3a40 → 695e541 → 90982e2 → 本次验收合并）。
环境：Windows + uvicorn 8710（真实 LLM qwen3.7-plus，新令牌）+ 常驻浏览器 CDP + SQLite。

## 验收标准（计划 Task 6）

> 四项技术债清零 + C2 对比基线产出，全量测试绿。

## 结果

| # | 验收项 | 结果 | 证据 |
|---|---|---|---|
| 1 | LLM 调用失败也落库（C3 补全） | ✅ | 无效 key induce → HTTP 500 + llm_call_log error 行（`HTTPStatusError: 401`、tokens=None、latency 236ms） |
| 2 | re-induce 无孤儿 | ✅ | alignment 3 二次 induce（真实 LLM，skill 5）→ 旧断言 9-12 DB 残留=0，旧 id verify → 404 |
| 3 | 100KB reqBody 截断保护 | ✅（单测+逻辑审查） | truncate_req_body/cap_value + `_truncated` 标记行（sha256 hex）；历史会话均 <8KB 无活数据（预期）；截断致 JSON 解析失败自动回退原文 diff |
| 4 | align 窗口参数对账 | ✅ | 活数据：双语会话 align → `{"idle_ms":2000,"max_window_ms":8000,"consistent":true}`；迁移 8372eac6b160 up/down 实跑验证 |
| 5 | 演示基线快照（C2 对比锚） | ✅ | GET /baseline/skills 4 项；demo/baseline/2026-09-24-baseline.json（真实数据：4 skill、含 0.75 pass_rate 的真实 FAIL 痕迹） |
| 6 | 全量回归 | ✅ | server 114 passed（102 基线+12 新）、extension 19 passed |

## 实施方式

SDD 子代理执行 Task 1-5（每任务 TDD 先红后绿），Task 6 真实环境验收主线程执行。

## 过程记录

- T3 实现与计划偏离一处（合理）：FieldChange 无独立 payload 列，截断标记嵌进 changes JSON（`field:"_truncated"` 行）；outcome.py 消费方天然兼容（无 before/after 键被跳过）。
- T4 迁移手写（避开 lessons #13 autogenerate 假 NOT NULL 噪音）。
- 验收 1 顺带验证了"先查实际输入再怪模型"路径：401 error 行带完整 URL 与异常类型，可直接定位网关拒绝。

## 遗留（M1 后续）

- CORS 收紧与镜像瘦身（J5 交付加固收尾，非阻塞）。
- window_params 历史行均为 null（字段随新 align 产生）——S10 真实流量前会自然积累。

## Sprint 回顾（宪法 §12）

- #1 主链路更近：四项债全部是管道可靠性，C2 锚已立。
- #2 非③⑥投入：全部 server 端管道/存储，合规。
- #5/#7 C1 零违规、C3 新增失败路径落库。
- #9/#10 客观达成（114+19 全绿，验收表逐条证据）。
