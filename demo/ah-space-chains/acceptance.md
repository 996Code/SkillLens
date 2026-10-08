# 2026-10-08 块 AH 空间与链编排 P1 验收记录

> 用户方向裁定（主计划 v2.4）：① 交互全在插件弹窗（工作台不参与执行流）；
> ② 链=纯数据+通用规则（降耦合）。真机全程常驻浏览器 9222 可见。

## 1. 交付内容

| 片 | 内容 | 验证 |
|---|---|---|
| AH1 | `chain` 表（迁移 7d37f2e57c2e）+ CRUD（`app/api/chains.py`：POST/GET/DELETE 挂 WRITE_GUARD；GET 详情附技能概要） | test_chains_api.py 3 用例（建/列/过滤/删/悬空 skill 422/viewer 403）；schema drift 守卫联动 |
| AH2 | `extension/src/shared/chain-rules.ts`：`${unique:前缀}` 规则解释纯函数（同轮共享时间戳、未知规则保留原文） | chain-rules.test.ts 5 用例 |
| AH3 | executor.html 链模式（`?chain=<id>`）：拉链→**整链 C1 一次确认**（确认卡列全部步骤）→逐步执行（unique 规则解析）→步进报告→fail 即停 | 真机（下） |
| AH4 | 空间小窗：popup「空间」按钮→右上角 420×560 独立窗；当前 tab 经 `/adapters/match` 识别系统（响应新增 `system` 字段）→只显示该系统回放→点选组链（按点击顺序）→保存/立即执行 | 真机（下） |
| AH5 | 真机验收+审查 | 本文档 |

## 2. 真机验收（JeecG）

1. **系统识别**：打开 JeecG → 空间小窗显示"JeecG 表单"✓，列表仅该系统 45 条回放 ✓
2. **组链**：点选"表格创建"+"字典条目创建"→ 排序 1. 表格创建 → 2. 字典条目创建 → 保存
   "真机验收链"出现在已保存链区（执行/删按钮）✓
3. **链执行**（executor.html?chain=2，269 带 unique 规则 + 118）：
   - 步骤 1/2：#269 表格创建 → **pass（9 步）**，unique 生效——`sl_form_muz1qg76`
     （时间戳 base36）真实建进 `onl_cgform_head` ✓
   - 步骤 2/2：#118 字典条目创建 → **pass（5 步）**
   - 链执行结束：**2/2 步通过（pass）** ✓
4. **fail 即停验证**（链 v1 无 unique 规则）：269 撞名 fail → "链在第 1 步未通过——停止
   后续步骤（已执行 1/2）"——步进报告与停止语义正确 ✓
5. **整链 C1**：auto=1 跳过（验收授权）；人工模式确认卡列出全部步骤一次授权（代码路径，
   与单技能 confirm 同款交互）

## 3. 实证发现（已修/已记）

- **override key 语义**：链 steps 的 overrides key 必须用 fill 步的 `name`（录制时的字段
  label，如 `*表名`），不是 input_variables 的变量名（`*表名称`）——一字之差静默不生效
  （1592 实证：seq7 命中、seq5 没换）。已入 lessons #49；P2 改进：空间组链时从技能
  input_variables 自动带出候选 key。
- **迁移后必须重启 server**：SQLite 连接池旧连接看不到新表（no such table: chain，
  重启即愈）——已入 lessons（运维惯例强化）。
- **CRXJS 非 manifest 入口页**（space.html）需 vite `rollupOptions.input` 显式声明，
  否则不转译不产出。
- **requires_confirmation 同源**：chains 的技能概要改用 `plan.requires_confirmation`
  （与 /executor/skills 同一实现，避免双源判定漂移）。

## 4. 测试

- extension **108/108**（+chain-rules 5）；build 通过（dist 含 space.html）
- server 定向 28/28（chains 3 + url_match 11 + schema_drift 3 + role_gates 11）
- 全量基线不变：server 546 / web 78 / extension 99→108

## 5. P2 待办（主计划 AH 块已记）

跨步值绑定（`${stepN.变量}`——从写响应证据提取真实值）；链执行历史回看；
superseded 技能自动跟最新版；组链时 overrides 编辑 UI（自动带候选 key）。
