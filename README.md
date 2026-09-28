# SkillLens

> **让 AI 学会你们公司的软件，并在每次版本更新后自动判断：应该改变的有没有改变，不应该改变的有没有被破坏。**

AI 软件学习 + 变更智能产品：Chrome 插件观察真实用户如何使用软件，从 UI/Network/State 证据中归纳 Skill 与 Outcome，形成 Evidence-backed System Model；版本更新时用 Expected Delta vs Observed Delta 做四分类变更智能报告，支撑夜间自动回归与晨间人工评审。

## 核心能力（全部实测验证）

| 能力 | 说明 |
|---|---|
| **学习** | 真实用户操作 → 语义动作 → Skill 归纳（LLM 命名 + 确定性回查防幻觉），变量自动识别 |
| **回放** | 语义定位（非 CSS selector）+ 换参数回放 + PASS/FAIL 确定性判定 |
| **变更智能** | 需求 → Expected Delta（人工确认）→ Observed → **四分类报告**（Expected/Missing/Unexpected/Drift） |
| **夜间工程** | Impact Analysis（变更→受影响 Skill）→ 定向回归 → 编排画布 → 晨间评审门户 |
| **审计** | 全链路落库（C3）：会话→窗口→语义动作→Skill→回放→报告，一条链点到底 |
| **自愈** | 定位失败→LLM 提案→确定性验证→回放自愈→N 次晋升→supersede 生成 skill 新版本；flaky 自动重试 |
| **视觉/性能回归** | 截图基线比对（dHash+像素占比）+ 耗时/API 延迟滚动基线，漂移进四分类 |
| **集成出口** | Playwright 脚本导出（skill/flow，独立运行可审计）/ Webhook 通知（企微/钉钉/Slack）/ Jira 条目关联 |
| **协作** | 三角色账号体系（admin/reviewer/viewer）+ API 认证 + 评审绑定真实用户 |

## 快速开始

```bash
# 1. 后端（Python 3.12+，uv）
cd server && uv sync && uv run alembic upgrade head
uv run pytest -q                    # 全量测试（无需真实 LLM key）
cp .env.docker.example server/.env  # 填 LLM_*/NJMIND_*（gitignore 排除）
uv run uvicorn app.main:app --port 8710

# 2. 插件（Node ≥22.12）
cd extension && npm install && npm run build
# Chrome → chrome://extensions → 开发者模式 → 加载 extension/dist

# 3. 工作台
open http://127.0.0.1:8710/skills   # Skill 库 / 四分类报告 / 审计 / 画布 / 评审
```

私有化部署（Docker Compose）：见 `deploy/README.md`。

## 文档地图

| 文档 | 内容 |
|---|---|
| [产品宪法](docs/specs/2026-09-23-skilllens-mvp-design.md) | 愿景/硬性约束 C1-C3/阶段地图/竞品调研 |
| [交付主计划](docs/specs/2026-09-24-master-delivery-plan.md) | M1-M4 里程碑/功能块 A-Q/闸口 G1-G6（唯一范围基准） |
| [项目导览](PROJECT-GUIDE.md) | 目录地图/关键机制/怎么跑/**AI 学习提示词**（新成员与 AI 接手起点） |
| [协作宪章](docs/COLLABORATION-CHARTER.md) | 项目所有者全部要求汇总（传承文档） |
| [工作规范](AGENTS.md) | 阶段闸门仪式/TDD/安全红线/环境要点 |
| [原始设想](docs/references/ai_software_learning_change_intelligence_v3.md) | 43 节完整思路 |
| [踩坑经验](docs/references/project-lessons.md) | 17 条实战教训 |
| [SWOT 与迭代](docs/reviews/2026-09-25-swot-iteration.md) | 优势/劣势/机会/威胁 + 优先级 |
| 代码导览 | [server](server/README.md) / [extension](extension/README.md) / [web](server/web/README.md) |
| 验收记录 | demo/sprint0 ~ sprint27（每 Sprint 实测证据 + 截图 + 用户测试报告） |

## 差异化（为什么不是"又一个测试工具"）

- **Evidence Graph + 四分类**：Katalon 已占"需求直出脚本"，我们做"需求预期 vs 实际"的变更智能——黑盒无源码系统的 spec 验证无人占位
- **LLM 边界纪律**：LLM 只做命名/结构化/归因，判定全确定性 + 人工确认——规避"LLM Judge 系统性盲区"
- **私有化架构级默认**：数据不出网/客户自带 Key/信创兼容
- **C1 影子门控**：destructive 操作零例外不执行（编译期定格 + DB 不变量）

## 测试基线

server **354 passed** / web **50 passed** / extension **31 passed**（三套全绿是每个 Sprint 的合并前提）
