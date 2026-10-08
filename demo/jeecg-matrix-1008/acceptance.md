# 2026-10-08 JeecG 链路真机矩阵 + popup 回放入口修复 验收记录

> 用户指令："你再把 geecg 的系统好好看看，我希望你把链路都试一试" +
> "插件里面以前可以选择回放的东西，现在为啥又没了"。
> 执行路径：全程 executor.html（chrome.debugger 插件真实路径，非 Playwright 复现），
> 常驻浏览器 9222 全程可见。

## 1. 环境恢复（前置事故）

- **事故**：JeecG/ERPNext 全部容器端口（8095/8092/8090）宿主不可达。根因不是 Docker 转发坏——
  是 **Hyper-V 动态端口保留吞掉了 7998-8097 段**（`netsh int ipv4 show excludedportrange`），
  容器 recreate 时 `bind: access forbidden`。
- **修复**：管理员 `net stop winnat && net start winnat`（清动态保留）→ force-recreate 各栈；
  预占 8710/9222 永久排除防复发。
- JeecG 登录态随容器 recreate 丢失 → CDP 驱动重登（admin，凭据读 jeecg.yaml；
  Vue 受控输入必须走原生 setter——直接 value= 会被框架状态覆盖）。

## 2. JeecG 链路矩阵（executor.html 真实路径 ×3 轮）

代表链选择（45 个 JeecG 技能按链型覆盖）：269 表格创建（Online 表单三段链第 1 段）、
263/271 Online 表单创建/数据创建（旧版三段链）、118 字典条目创建、74 字典查询（带搜索变量）、
261 数据库同步。驱动：`server/scripts/jeecg_matrix.py`（CDP 开 executor 页签+代点开始按钮+
DB 轮询对账——SQLite 快照隔离要求轮询每轮新开 session）。

| 轮次 | 结果 | 说明 |
|---|---|---|
| R1 | 4/6（269✓ 118✓ 74✓ 261✓；263✗ 271✗） | 269 需换参（sl_form_* 撞名则 duplicate 拒）；263/271 定位 miss |
| R2 | 4/4（269 换参 118 74 261） | 稳定复验 |
| R3 | 4/4（浏览器重启加载新构建后） | 与构建变更解耦验证 |
| 负例 | 269 不换参也 PASS | 录制原值 sl_form_a26513 重复创建未被拦——待深究（duplicate/check 覆盖面） |

- 写操作真实生效：`onl_cgform_head` 里 sl_form_c1020/c2r1/c3r2/c4r3 均真实建出。
- **263/271 失败定性（非执行器缺陷）**：`click:*表名` 定位 miss → 介入 2 次耗尽。根因是
  **数据环境漂移**——录制时（10-03）Online 表单列表首屏行集合与现在不同（列表被 e14631/test_*
  等行占据），row-anchor 锚定的行不在首屏。属"链对列表分页/排序的适应性"缺口，改进方向：
  定位兜底加"搜索/翻页找行"；短期处置=用 269+271 新链替代或重录。

## 3. popup"回放入口没了"根因与修复（用户报告问题）

**根因（两个叠加）**：
1. **token 失效**：popup 技能列表依赖插件 storage 的 `sl_executor_token`（`GET /executor/skills`
   401 → 只显示一行错误文案，列表"消失"）。触发：token 7 天 TTL 过期/服务端口令重置。
   且存在 UX 断链：**工作台登录并不会自动把 token 配给插件**（写入只发生在 executor.html?token=
   打开时），普通用户无自助恢复路径。
2. **slice(0,20) 截断**：库已 288 技能，JeecG 的 45 个排在 39 位之后——即使 token 有效，
   JeecG 组也基本被吞掉（"插件里选不到 JeecG 的链"）。

**修复（TDD）**：
- 新抽 `extension/src/popup-render.ts` 纯函数：**全量渲染不截断**（分组+180px 滚动）+
  **搜索框**（系统/技能名过滤）+ 空态/无匹配态；popup.ts 变接线层。
- 401 catch 显示可操作恢复指引（buildHint：去工作台生成 executor.html 链接或重新下发 token）。
- `popup.html` 加搜索框；`popup.test.ts` 4 用例（全量不截断/过滤+空态/回调带 id/指引文案）。
- 真机验证：重启常驻浏览器（MV3 不热替换）→ popup 列表恢复分组渲染；
  搜索"JeecG"→ 仅"JeecG 表单"组 45 行。✓

**遗留（记录为改进项）**：工作台侧加"连接插件"按钮（一键生成 executor.html?token= 链接），
让 401 恢复不需人工拼 URL——进 backlog。

## 4. 测试

- extension：**103/103 全绿**（99→103，+popup 4 例）；`npm run build` 通过；
  真机（9222）popup 列表/搜索 + 矩阵 3 轮复验通过。
- server：未动（本次仅 extension/脚本）；jeecg_matrix.py/jeecg_login.py/popup_check.py
  为验收脚本（含 SQLite 快照轮询、Vue 原生 setter、CDP 代点等实证注释）。

## 5. 环境快照

- 常驻浏览器 9222（Chrome 153，扩展 iifhfc…，登录态：JeecG✓）；server 8710 运行中。
- admin 口令本轮重置（本地演示库自处置惯例）。
