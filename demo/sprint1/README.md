# Sprint 1 端到端验收记录（演示 1：提交表单被切成语义窗口）

日期：2026-09-23
环境：macOS + Chrome（加载 extension/dist）+ uvicorn（127.0.0.1:8710）+ SQLite
被学习系统：njmind / 明搭云-MingBuilder（表单设计器 field-edit 页）
验收 session：`5c8a8d7f-5017-4ea6-a8af-1630fc2a33b3`（note=保存表单，popup 开录创建）

## 验收结论：6/6 通过

| # | 检查项（计划 Task 9 Step 3） | 结果 | 证据 |
|---|------------------------------|------|------|
| 1 | 单 session（录制开关生效） | ✅ | 一次录制只产生 1 条 recording_session（对比 Sprint 0 的每页 25+ 条） |
| 2 | click/submit 语义标签窗口 | ✅ | 9 窗口，label 如 `保存`/`组合字段`/`插入` |
| 3 | api_calls 含提交类 POST（模板化） | ✅ | w8：`POST /codeBack/formConfig/saveFormConfig` → `GET getTableConfigByFormConfigId` → `POST /codeBack/tableConfig/saveTableConfig` |
| 4 | state_signals ≥1 | ✅ | w8 `saveTableConfig:code=200`、w1/w2 各 1 条（fix2 后） |
| 5 | 停止后不新增 | ✅ | 停止后 raw_event 无新行、server 无新 events POST |
| 6 | process 幂等 | ✅ | 重跑两次均 9 窗口，无重复 |

完整窗口转储见 `semantic-actions-dump.txt`。核心成果（w8）：

```
click "保存"
  → POST /codeBack/formConfig/saveFormConfig        (200, 580ms)
  → GET  /codeBack/tableConfig/getTableConfigByFormConfigId?formConfigId={id}
  → POST /codeBack/tableConfig/saveTableConfig      (200)
  state: code=200
```

## E2E 过程中发现并修复的缺陷

1. **fix1（c595974）停止时序竞态 + 门控兜底**：stopRecording 清 storage 早于周期 flush，停止后到达的事件被 deferred 永久滞留——改为清除前用旧 sid 做最终上报（finalFlushWithSession）；capture 加 3s 轮询兜底门控。
2. **fix2（41864dc）状态信号不认 njmind 约定**：njmind 业务码在顶层 `code`，原正则 `^(status|state)$` 匹配不到——扩为 `^(status|state|code|result)$`。
3. **非代码问题（操作机制）**：插件重载后未刷新页面会产生孤儿 content script（`Extension context invalidated`），表现为静默 0 采集——正确顺序：重载插件 → 刷新页面 → 开录。

## 遗留（Sprint 2 议题）

- 后缀状态字段（`formState`/`orderStatus` 等）未匹配，需设计后缀匹配规则与歧义处理；
- popup 应自检已打开标签页是否含孤儿脚本并提示刷新；
- 顶层 `code` 与 `status` 并存时信号翻倍（消费侧知悉）；
- 无 session 时 deferred 事件每 6s take→put 空转。

## 复现步骤

```bash
cd server && uv run alembic upgrade head && uv run uvicorn app.main:app --port 8710
cd extension && npm run build        # Chrome 加载 dist，刷新目标页面
# popup 开录 → 操作表单（输入+保存）→ 停止
SID=$(sqlite3 server/skilllens.db "SELECT id FROM recording_session ORDER BY rowid DESC LIMIT 1")
curl -s -X POST http://127.0.0.1:8710/api/v1/sessions/$SID/process
curl -s http://127.0.0.1:8710/api/v1/sessions/$SID/semantic-actions | python3 -m json.tool
```
