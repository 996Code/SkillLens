# S35：多开源 ERP 全面模拟（Odoo 多流程 + Dolibarr 第三目标）

> 2026-09-29。需求：多找开源 ERP、不只测单一线路、全面模拟。
> 目标系统：njmind（内网）+ Odoo 17（SPA，S34）+ **Dolibarr 24（PHP 经典多页，本块新增）**
> ——三种架构形态（内网 Vue SPA / Python SPA / PHP 整页加载）。

## 部署

- `deploy/dolibarr/docker-compose.yml`：mariadb:11 + dolibarr/dolibarr:latest（8080）
- 首装：DOLI_INSTALL_AUTO 自动建库；公司信息最小化配置；模块经 UI 正规激活
  （Third Parties id=1 / Products——DB 直插 MAIN_MODULE_* 常量不注册权限，无效）
- 语言注意：会话语言随浏览器 locale（中文），脚本定位须语言无关（href 模式）

## 全面模拟结果

### Odoo（4 流程 × 2 轮换数据，scripts/s35_odoo_full.py）

| 流程 | Skill | 结果 |
|---|---|---|
| CreateContactRich（名+电话） | #41 | **换参回放 run 180 pass**（动态值） |
| DeleteContact（勾选→Actions→Delete→unlink API） | #40 | 学成（4 步含 unlink 证据）；回放 error（见缺口②） |
| CreateTag（跨菜单 Configuration→Tags→New） | #42 | 学成（3 步） |
| UpdateContact | #39 | EmptyFlow（见缺口①） |

### Dolibarr（4 流程 × 2 轮，scripts/s35_doli_full.py）

| 流程 | Skill | 结果 |
|---|---|---|
| CreateThirdParty（name+phone） | #51 | **换参回放 run 183 pass**；llx_societe rowid=8 "Doli Replay G7" 真实落库 |
| CreateProduct（ref+label） | #45 | 学成 |
| SearchThirdParty（列表搜索） | #47 | 学成（name 兜底修复后） |
| UpdateThirdParty（行点击→编辑→改名→保存） | #50 | 学成（4 步） |

## 三个新泛化修复（TDD）

### ① submit 事件描述提交按钮（extension/src/content/capture.ts）

submit 的 e.target 是 form——textContent 含内联脚本，label 被污染且不可定位。
改用 `e.submitter`（提交按钮）。

### ② 无可访问名元素的兜底链（describe-element.ts + locate.py）

- label 链补 `input.value`（input[type=submit] 的 value 是唯一人读标签）
  与 `name` 属性兜底（Dolibarr 搜索键 name="button_search_x" 无任何可访问名）；
  空 text 不再短路 `??` 链。
- locate 补 `[name="{label}"]` 策略（name-attr）与采集侧兜底链闭环。

### ③ click+submit 双计治理（app/ingestion/windows.py）

表单提交一次用户动作产生 click+submit 两个锚点 → 骨架重复步 → 回放第二次
点击时页面已离开必失败。规则：submit 与当前窗 click 锚**同 label** 时不另开窗
（label 不同如键盘直提表单仍开新窗）。

## 诚实记录的缺口（后续需求）

1. **数据依赖锚点**（P1）：点击列表行/记录卡时 label=记录名（"Doli Third E1"），
   两轮数据不同 → 锚点不匹配 → EmptyFlow（Odoo UpdateContact #39 根因）；
   首行稳定时碰巧对齐（Dolibarr Update #50）。需要锚点 label 模板化或结构匹配。
2. **空 label 步回放**（P2）：勾选框等无 label 点击进骨架（"click:"），计划编译
   丢弃空 label 步 → Odoo Delete 回放缺勾选步 → Actions 定位失败。
3. **Odoo Search 0 语义动作**（P2，S34 已记录）：纯查询无写请求窗口被过滤。

## 复现

```
cd deploy/dolibarr && docker compose up -d   # + Odoo（deploy/odoo）
cd server && uv run python ../scripts/s35_odoo_full.py
            uv run python ../scripts/s35_doli_full.py
# 回放：POST /skills/51/replay {"overrides":{"name":"...","phone":"..."},"confirm_side_effect":true}
```
