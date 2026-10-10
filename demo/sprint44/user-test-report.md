# Sprint44 验收报告：多轮×换参矩阵战役（2026-10-10）

> HANDOVER §3.3 / §8.2：四系统技能×2 换参，真实执行页路径（executor.html），
> 验收=断言命中+无假 pass。执行脚本：scripts/s44_matrix.py（CDP 驱动
> 执行页——面板/执行页真实路径，非 API 直调）。

## 一、矩阵结果（20 格）

| 系统 | 技能 | 换参键 | 结果 | 写请求 | 判定 |
|---|---|---|---|---|---|
| ERPNext | 213 客户保存（10）×2 | customer_name | **pass ×2** | 13/格 | 换参生效+创建真实 |
| ERPNext | 216 客户保存（11）×2 | customer_name | **pass ×2** | 13/格 | 同上 |
| ERPNext | 2 客户创建 ×2 | customer_name | **pass ×2** | 11/格 | 含旧 fail 技能复活（当时登录态） |
| Odoo | 1 合作伙伴快速创建 ×2 | e.g. Lumber Inc | **pass ×2** | 15/格 | 换参生效（placeholder 型 fill 名） |
| Dolibarr | 187 创建订单 ×2（无 fill） | — | **pass ×2** | —（无参回归格） | 回归绿 |
| Dolibarr | 185/188 创建合作伙伴 ×4 | name | **fail ×4** | 0 | 录制产物缺陷（见二.1） |
| Snipe | 303/304/305 ×6 | asset_tags/assigned_user/— | **fail ×6** | 0 | 环境态漂移（见二.2） |

**换参机制判定：8/8 通过**（ERPNext+Odoo 全格——唯一值换参生效、写请求真实触发、
断言命中、AM1 写水位零假 pass：步 ok 无写的格全部如实 fail，无一假 pass）。

## 二、失败分类（诚实归因——非换参问题）

1. **Dolibarr 185/188：录制 URL 带 `__ID__` 占位**——录制脱 id 产物。
   goto `card.php?id=__ID__&socid=N` 落视图态（无表单）→ fill miss。
   182-184 同病（编辑流）。**后续需求：Dolibarr 合作伙伴技能重录**
   （action=create 干净流）。
2. **Snipe 303-305：容器重启后状态漂移**——同技能昨日（10-09）全 pass，
   今日容器重启后 create 页重定向列表、行操作 miss。e1_env 类
   （环境态），AM2 未报登录页（非登录问题——页面可达但行为变）。
   **后续需求：Snipe 容器重启后状态恢复例程/重录**。

## 三、矩阵过程的工具链实证

- AM1 写水位：fail 格全部 0 写+如实 fail（无假 pass）——期望-观测
  对比护航生效。
- AM2 登录守卫：Snipe 容器掉线时曾秒败「目标站不可达」（链 13 验证）。
- 矩阵脚本坑：CDP evaluate 表达式 `]` 缺失致 SyntaxError 返回 null
  （脚本错误被当 NO_BUTTON）——已修。

## 四、结论

- 换参回放机制（fill_ 键换参+唯一值+写断言）在 ERPNext/Odoo **全绿**，
  Dolibarr/Snipe 失败为录制产物与环境态（已转后续需求，非机制缺陷）。
- 基线：server 713 / extension 141。
