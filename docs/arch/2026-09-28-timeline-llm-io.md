# S32：链路时间线 + LLM IO 全留存

> 2026-09-28，分支 s26b-flow-export。需求：每一次运行、每一步的链路/日志/输入输出/
> 思考统一留存并可视化；LLM 调用的完整输入输出可查。
> 宪法依据：C3 全链路落库（含失败调用）——本块把落库的数据补齐"可视化统一入口"。

## 后端契约

### GET /api/v1/timeline（app/api/timeline.py）

按时间倒序聚合全流水线环节，每项 `{type, id, title, subtitle, ts}`：

| type | 来源表 | title / subtitle |
|---|---|---|
| session | recording_session | `采集 {id[:8]}` / 事件 N · 语义 N · note（计数 GROUP BY 聚合） |
| alignment | alignment | `对齐 #id` / 骨架 N 步 · 会话 N |
| skill | skill | `Skill #id name` / status · 置信度 · 证据数 |
| replay | replay_run | `回放 #id` / status · mode · 步数 · 断言数 · 耗时 |
| report | delta_report | `报告 #id` / E/M/U/D 四分类计数 |
| review | review | `评审 #id` / decision by reviewer |
| llm | llm_call_log | `LLM purpose` / provider · latency · tokens |
| agent_run | agent_run | `运行 #id graph` / status · 节点数 |

- `limit` Query（1~200，默认 50）；各表先各自 limit 再合并排序截断。
- 鉴权：require_user（同其余 guarded 路由）。

### GET /api/v1/audit/llm-logs/{id}（app/api/audit.py）

单条 LLM 调用**完整** prompt/response（区别于列表端点 200 字符摘要）：

- 返回 `{id, purpose, provider, model, prompt, response, prompt_tokens,
  completion_tokens, latency_ms, created_at}`；
- 404 = 不存在；鉴权同 audit 路由组。
- 设计权衡：按需单条取用（前端点击展开时才拉），不经列表端点全量外泄——
  与 M3"列表只给摘要"原则兼容，完整审计仍可 DB 直查。

## 前端（server/web/src/views/TimelineView.vue）

- 路由 `/timeline`，侧边栏"链路"入口（第 7 项）。
- 类型过滤 chip：全部 + 8 类型，带实时计数；再点一次取消。
- 竖向时间轴：类型色点（8 色映射 TYPE_META）+ 时间 + 标题 + 摘要。
- 交互：
  - LLM 项点击 → 按需拉取 `llm-logs/{id}` 展开完整 prompt/response
    （Map 缓存已展开项；竞态守卫：切走后晚到响应丢弃）；
  - skill 项展开"下钻查看"→ `/skills/{id}`；session 项 → `/audit`。

## 测试

- server：`tests/test_timeline.py`（聚合排序/limit/完整 IO/404，TDD 先红后绿）。
- web：`tests/TimelineView.spec.ts`（渲染/过滤/LLM 展开/下钻链接 4 用例）；
  `App.spec.ts` 导航断言加"链路"。
- 浏览器实测：`scripts/s32_screenshots.py`（注入本地铸 token，四步用户路径 +
  截图入 demo/sprint32/screenshots/）。
