# Sprint 0 端到端验收记录

日期：2026-09-23
环境：macOS + Chrome（插件以开发者模式加载 `extension/dist`）+ uvicorn（127.0.0.1:8710）+ SQLite（server/skilllens.db）
被学习系统：njmind / 明搭云-MingBuilder（http://192.168.99.22 ，表单设计器 field-edit 页）

## 验收结论：5/5 通过

| # | 检查项（计划 Task 11 Step 3） | 结果 | 证据 |
|---|------------------------------|------|------|
| 1 | navigation 事件 | ✅ | seq 0 `page-load`，标题"明搭云-MingBuilder" |
| 2 | input 事件且字段值正确 | ✅ | seq 10/16/19 三条 input，值 `111223333`/`3213213`/`fuwenben1432432` |
| 3 | click/submit 语义标签（非 CSS selector） | ✅ | `单选`、`点击选择特殊字符`、`插入`、`保存`、`请输入` |
| 4 | network 含表单提交 POST | ✅ | 首轮 session：click`保存`(16) → `POST /codeBack/formConfig/saveFormConfig` 200 → `POST /codeBack/tableConfig/saveTableConfig` 200 |
| 5 | 同 session seq 单调无重复 | ✅ | 21 条事件 seq 0~20 唯一（DB 唯一约束兜底） |

完整时间线见 `session-dump.txt`（含 Action↔Network 交错）。

## E2E 过程中发现并修复的三个集成缺陷（单测无法覆盖）

1. **CORS 预检 405**（fix 9393593）：MV3 content script 的跨域 fetch 需预检，FastAPI 加 CORSMiddleware。
2. **MV3 IndexedDB 隔离**（fix 1f63568）：CS 与 SW 不共享 IndexedDB，事件流改为 CS → runtime 消息 → SW 落库上报。
3. **input 采集键过窄**（fix 3a50ec6）：仅 `target.name` 导致 njmind 输入框（无 name/id）全被跳过；改为 name→id→placeholder→aria-label 回退链。

## 过程发现（记入台账，Sprint 1 处理）

- CORS 坏掉期间 ensureSession 失败会**丢弃事件**（emit 前置依赖），需降级为本地缓冲。
- 每个页面实例创建一个 session（25+ 个 session），语义上应一次录制任务一个 session，需弹窗/开关控制录制并复用 session。
- change 事件依赖失焦触发；React 受控组件场景可能需监听 input 事件（njmind 实测 change 可用）。
- `GET / 404`（SW 存活探测）无影响，但说明 SW 周期性唤醒连 server。

## 复现步骤

```bash
cd server && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8710
cd extension && npm run build          # Chrome 加载 dist，刷新目标页面
# 在目标系统上正常操作，约 5 秒后：
sqlite3 server/skilllens.db "SELECT kind, count(*) FROM raw_event GROUP BY kind;"
```
