# S34 块 2：多目标验证（本地 Docker Odoo）+ 三个泛化修复

> 2026-09-29。需求：不能只在 njmind（192.168.99.22）上自测——本地 Docker 部署
> 开源 ERP 做第二目标系统，全链路验证语义定位/学习/回放的跨系统泛化能力。
> 栈：deploy/odoo/docker-compose.yml（postgres:16 + odoo:17，Contacts 模块）。

## 验证结论（核心成果）

**录制 → 学习 → 换参回放 → 副作用真实落库，在第二个 ERP 上完整闭环**：

- skill #38 PartnerQuickCreateFlow（Odoo Contacts 新建联系人，2 步骨架 + 1 输入变量）
- 换参回放 run 179 **pass**：click New → input "e.g. Lumber Inc"=**Odoo Replay Dynamic C1**
  （新动态值）→ click Save manually（图标按钮经 aria-label 定位）→ 4 断言全过
- Odoo DB 确认 res_partner id=12 "Odoo Replay Dynamic C1" 由回放真实创建
- 4 张步骤截图上屏（run 详情页 /replay-runs/179 浏览器实测通过）

## 三个泛化缺口与修复（TDD）

### ① 图标按钮描述上溯（extension/src/shared/describe-element.ts）

Odoo 的 Save/Edit 按钮无文本只有图标，点击命中的是内部 `<i>` 元素
（label 空 → 噪声过滤丢弃 → 关键动作丢失）。修复：describeElement
上溯至最近可操作祖先（button/a/input/select/textarea/[role=button]，
3 层封顶）取其 aria-label——Save 按钮的 "Save manually" 得以采集，
回放侧 locate 的 get_by_role("button", name=) 直接闭环。
（+4 extension 用例，31→35）

### ② 窗口对齐 API 集交集（app/ingestion/alignment.py）

话多 SPA 的窗口 API 集带偶发请求（autocomplete/mail 轮询逐轮不同），
两轮签名只差一个 API → LCS 精确匹配把整步丢出骨架（skill #34 EmptyFlow
根因）。修复：锚点（type:label）相同视为同一步，API 段取全会话**交集**
（单侧独有 API 不进骨架——"单侧独有窗口不得进骨架"语义延伸到 API 级）；
buckets 改按锚点序列分桶（偶发 API 差异不拆桶）。
（+2 server 用例；skill #37 两步骨架学成验证）

### ③ input 步时序交错（app/replay/plan.py compile_skeleton_plan）

原实现把所有 input 变量**前置**在骨架步之前——njmind 表单先于锚点存在
所以碰巧对；Odoo 表单在 click New 之后才出现 → 前置 fill 必然定位失败。
修复：按参考会话**事件时序**交错插入（锚点按对象身份匹配，ts/seq 可能
重号）；纯 overrides 造的无事件变量保持旧前置语义；锚点缺失兜底按序补齐。
（+2 server 用例）

## 已知边界（记录为后续需求）

- Search 流程（纯查询无写请求）：Odoo 搜索框 input+回车产生 0 语义动作
  （窗口无后续 network 证据）→ 无法学习。查询类流程需要不同的窗口语义。
- Update 流程学偏（skill #35 MailThreadInspector）：锚点选中 chatter 头像
  而非 Edit 按钮（录制脚本点击路径噪声）——录制操作规范性问题，非管道缺陷。
- Odoo 录制脚本节奏须模拟真实用户（动作间 >2s 停顿），否则 input 被吞进
  上一窗口（IDLE_MS 2s 语义）。

## 复现

```
cd deploy/odoo && docker compose up -d
cd server && uv run python ../scripts/s34_odoo_init.py        # 建库+登录
uv run python ../scripts/s34_odoo_record.py                   # 录制+学习
# 回放：POST /api/v1/skills/38/replay {"overrides":{"e.g. Lumber Inc":"..."},"confirm_side_effect":true}
```
