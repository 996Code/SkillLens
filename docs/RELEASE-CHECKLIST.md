# SkillLens v2.1 上线交付清单（2026-10-04）

> 交付状态：**可上线**（私有化试点就绪）。本清单为上线检查单一屏总览。

## 1. 交付能力矩阵

| 能力 | 状态 | 验证证据 |
|---|---|---|
| 采集→学习→回放→四分类核心管道 | ✅ | S43-4 七系统 23 技能 23 回放全 PASS |
| 插件执行节点（v2.1 架构） | ✅ | AG5 双端一致（JeecG/Odoo 双 pass）+七系统矩阵 |
| 适配器清单（声明式接入） | ✅ | 7 系统清单+工作台 /graph/adapters 向导 UI |
| 证据链（截图/快照/审计） | ✅ | 插件端步骤截图落盘+before/after 快照+工作台回看 |
| 当轮 LLM 介入（自愈） | ✅ | erpnext/jeecg 实证 miss→heal→ok；上限 2 次超限判 fail |
| C1 影子门控 | ✅ | 确认卡+auto=1 验收模式+服务端双保险 |
| UX 基线 | ✅ | 用户代理评审闭环：两致命根治+结果卡+日志白话+时区 |

## 2. 插件端核心链实测（矩阵收官，DB 为准）

| 系统 | 结果 | 备注 |
|---|---|---|
| zentao | **3/3 pass** | 断言层根治后 QA 链贯通 |
| dolibarr | **3/3 pass** | 订单链 |
| odoo | pass（登录后） | 矩阵需系统级登录（已修） |
| snipe | 1/2 | 资产链 |
| ruoyi | 1/3 | 257 pass |
| erpnext | fail | fill 介入生效；Save 步深度适配=迭代项 |
| jeecg | fail | fill 介入生效；保存步深度适配=迭代项 |

## 3. 测试基线

server **489** / web **54** / extension **76**（全绿；489 含 v2.1 全部新用例）

## 4. 已知限制（如实声明，迭代项）

1. erpnext/jeecg 插件端 Save 步（Frappe 表单架构/JeecG 抽屉组合链的
   fill+save 深度适配）——服务端回放这两系统全 PASS（S43-4），插件端
   为迭代项
2. JeecG #269 连续多轮 UI 态漂移（探针如实检出）
3. 心跳 lost 为被动收割（/executor/skills 访问触发，无独立进程）

## 5. 上线操作（私有化）

```bash
# 1. 部署（docker compose 或裸机）
cd server && uv sync && uv run alembic upgrade head
cp .env.docker.example .env     # 填 LLM_*/NJMIND_*
uv run python -m app.create_user <用户名> <密码> admin
uv run uvicorn app.main:app --port 8710

# 2. 插件安装：extension/dist → chrome://extensions 加载已解压

# 3. 新系统接入：工作台 /graph/adapters → 编辑清单（实时校验）→ 保存

# 4. 验收：popup 选技能 → executor 页执行 → 工作台回看
```

## 6. 安全检查（本清单出具前已扫）

- 全仓敏感串扫描：无真实 key/密码/域名（历史文档空模板除外）
- 凭据模式：目标系统凭据 password_env（生产）/password_literal（本地
  演示+lint 警告）；LLM key .env（gitignore）
- llm_call_log URL 脱敏+插件双脱敏：未回退
- C1/C2/C3：影子门控/流量分轨/全链路落库——v2.1 全程未违反
