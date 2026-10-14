# SkillLens 继任开发任务书（HANDOVER）

> 2026-10-09 重编（v2），交接对象：**继续开发本项目的 AI agent（或人类工程师）**。
> 上一版（2026-10-02）基于 v2.1 前状态；本版覆盖 v2.1→v2.7 全部演进
> （AH 空间面板/AI 测试工程师日常化/AJ 异常分类学/AK 异常收敛层/差距
> 行动清单全清）。配合 `AGENTS.md`（操作宪法）+ `PROJECT-GUIDE.md`（导览）。
> **文末 §8 是给你的完整提示词套件。**

## 0. 一句话现状（诚实版）

产品主干全通：**录制→学习→回放→断言→报告→链编排→插件页内执行**端到端
真机验证；差距行动清单 P0/P1/P2/防再生 100% 收口；AK 异常收敛层（四码
分类+预算+熔断）已落地。AM 期望-观测对比/AN 跨步状态传递/健壮性体检亦收官
（见 §2.5）。测试基线 **server 740 / web 81 / ext 147**（s45+AO 后）。
技能库 249 活跃（八系统+通用）、16 链（六系统业务链全 pass）、2952 run。
**它已是"内部可用产品形态"**——免登录开箱即用、异常有收敛、错误白话直达、
重启零改动复跑 8/8（2026-10-13 宿主重启实证，见 §2.6）。
剩余工作为新方向候选（52 链全量回归轮/多账号并发/生产部署——见 §3）。

## 1. 项目是什么（不变，一图）

```
Chrome 插件（capture.ts 录制/net-hook 网络钩子/space-panel 悬浮面板/
executor.html 执行页）──事件──▶ FastAPI server（ingestion 对齐学习
replay 双通道回放 exec AK 收敛层）──▶ SQLite + Web 工作台 + 面板
```

三条产品宪法（零例外）：C1 影子模式（写操作须确认）；C2 真实流量分轨；
C3 全链路落库（含失败 LLM 调用，URL 脱敏）。LLM 只做命名/归因，判定全确定性。

## 2. v2.1→v2.7 演进账本（你接手时已存在的能力）

| 块 | 能力 | 关键提交 |
|---|---|---|
| AF/AG 适配器+插件执行 | 8 系统 YAML 清单；插件完整执行节点 | v2.1 |
| AH 空间面板 | 油猴式悬浮面板（shadow DOM）；链编排 v2（子链/setup/自动登录）；AH6 页内执行去跳板 | 2026-10-08 |
| AI 测试工程师日常化 | 录制停录自动学习；跨步传值 ${stepN.字段}/${unique:}；CI 出口（wait=1 退出码）；库治理 | 2026-10-08 |
| AJ 异常分类学 | failure_class E1-E4（e1_env 不进分母）；AJ2 登录守卫（URL+标题双证据）；证据体验（retain-on-failure 写优先）；自愈透明度（晋升 diff/supersede 回滚） | 2026-10-09 上半 |
| 差距行动清单 | P0/P1/P2/防再生全清：Dolibarr 断言回放反哺（from-run 端点）；禅道矩阵轮+技能归并 99→40；query 感知模板（templatize_query）；层4 背书激活；编排渗透率 2.6%→7.0%；四系统录制补课（13 技能） | 2026-10-09 |
| 用户报障闭环 | 131 run 洪泛三防线（plan 节流 409/SW 持久锁）；面板 TDZ 永卡修复；系统隔离失效修复；免登录（PLUGIN_TRUST+plugin-session） | 2026-10-09 |
| AK 异常收敛层 | 四码分类（cancelled/timeout/transient/fatal）；双端预算传递（run 120s 硬封顶+CDP terminateExecution 强杀）；通道熔断（OPEN 快败 e2_infra）；白话错误映射 | f0959f3 |

## 2.5 2026-10-10 会话增量（24 提交，交接前必读）

本节由当日会话追加（c945bcf→4160d42 全链在 git log）：
- **AK6 收官**：批次1（风暴四缺口：running 守卫/收割常态化/终态拒收/插件四码）+批次2（swallow 收敛件）+批次3（extension 盘点）——「决策吞错零静默」。
- **AM 全片**：期望-观测对比（expect_write=证据派生∪词表→写水位快败）+登录守卫+failureKind 三态+插件 run 步骤合成（详情页从"无步骤"到全呈现）。
- **AN 闭环**：pickedRow+${stepN.row}+row_anchor_from 注入（链 14 E2E：A 选行→B 行操作转向同列）。
- **s44 换参矩阵**：换参机制全验证（ERPNext 6/6+Odoo 2/2+Snipe 4/4+Dolibarr 187+315）。
- **315/303 追踪链**：编译器 3 污染（__ID__ 锚/动作时点锚/步级异 host goto）+执行器 8 缺陷（input[submit] 五通道/expectModal/假 pass 收口/**文档型写证据导航丢失**/error 路径证据丢弃）+判定层假 pass 收口——全部真机实证闭环。
- **基础设施**：testpaths（收集地雷）/test.db 每进程 pid 隔离（lesson #59 机制化）/lessons #56-59。
- 基线：**server 730 / web 81 / ext 147**（s45+AO 后 740，见 §2.7）。

## 2.6 2026-10-11~13 会话增量（编排渗透率+链回归 8/8，交接前必读）

- **AJ2 全闭环**（9865f2b）：插件端登录恢复——AM2 守卫（URL 词表∪
  表单特征双通道）触发→服务端跑适配器登录例程（凭据不出 YAML）→
  cookie 经 CDP 注入常驻浏览器→重试当前步。禅道容器重启丢态端到端
  session_recovered=true→pass。
- **编排渗透率两批**（71f3f62+5e6648b）：存量链四通病根治（goto
  折叠/空断言语义/icon title 定位/跨系统断言守卫）+星号归一+坏断言
  三族清理（expect_value=fail/code=0/success 动态业务结果当期望）。
- **goto 容错通用化**（095ee6e，修类不修个案）：goto URL 换参注入
  （段边界正则）+${stepN.res_id} 提取（写后首个数字段 GET）+文档型
  写响应 URL 更新——新录制自动免疫实例值漂移。
- **重录批**（b324eb7+d2b0230）：318/320 Snipe v2 完整语料学成；
  Odoo 报价完整语料=技能 321+链 21。
- **链回归 8/8 全绿**（ebc6e67+a6b04de）：六系统八链全 pass。
  Odoo 双根治：action id 漂移（XML ID 稳定形态 `#action=sale.
  action_quotations`）+m2o 关系字段适配（placeholder "Type to
  find"→输入→等下拉→mousedown+click——select2 同族）。
- **恢复性 pass 判定**（6fe056c）：fail finish 也评估断言，非空且
  全过+失败步全 miss→改判 pass+flaky。
- **全面检查收官**（5480e08+f0c8c34）：三套全量+链 8/8+导航 29
  引用零缺失+基线三处同步+红线 IP 归一 TEST-NET。
- **296/链 10 收口+重启零改动实证**（2026-10-13）：296 标
  superseded→321、旧链 10 删除（入口去重）；宿主重启后零代码零
  脚本改动直接复跑全量链回归 **8/8**——重启类故障已按类根治
  （XML ID 稳定形态/AJ2 恢复/AM2 表单守卫/goto 换参），剩余仅
  环境运维（docker start+起 server/浏览器）。

## 2.7 2026-10-14 会话增量（s45 全量回归轮，交接前必读）

- **s45 回归轮**（0624bc8+复验提交）：52 格矩阵（10-06 P3 矩阵技能
  superseded 映射后 25 技能×2 轮）+16 链全量，两阶段真机跑——
  **基线八链零回归**；Phase A 22/48 失败全数分诊四族（F1 无换参协议
  实例值重复 22 格/F2 坏断言 4 格/F3 __ID__ 已知缺口/F4 ERPNext 235/236
  表单双加载漂移——后者待深挖）。基线 **server 740**（s45 +3、AO4 +7 新测试）。
- **F2 技能级坏断言清理**：链级清理（5e6648b）漏了生成入口——全库
  984→674 条（动态业务结果值 success/code 0/纯祝词 toast 全族，备份
  demo/sprint45/bad-assertions-removed.json）+outcome.py 生成守卫
  `_is_dynamic_business_result`；157/285 稳定 fail→真机转绿。
- **恢复性 pass 判定 error 洞**（run 3210/3241 双实证假阳）：插件
  failedSteps 排除 error 步且 AM1 快败走专用中止路径再绕过收集→
  服务端断言恰好全过就翻 pass。双端修+专用路径补计；修复后真恢复
  正确带 flaky（3227/3229/3233），拦截步如实 fail（3243）。
- 回归脚本 `scripts/s45_regression.py`（--matrix/--chains/--chain N）；
  报告 demo/sprint45/regression-report.{md,json}。
- **AO 块引擎零系统知识外置**（v2.8.7，b72327e/f4fb51f/d10da2e）：
  AO1 菜单/表单容器/控件/校验选择器上画像（插件 4 处+服务端
  locate/探测层）；AO3 select2 全套 fill 协议按 dropdown.engine 声明
  驱动（Snipe/Odoo 已显式声明）；AO4 resolver 编译矩阵画像化（选择器
  随候选下发）。AO2 零改动实证（八系统全默认即对）。顺手修 3 个
  预存在缺陷（fill 优先序/AM1 拦截丢证据/select2 open 态可见性）。
  每批真机链回归护航（8/8、4/4、5/5）——"平台+组件化"按严格标准
  成立（引擎运行时组件知识全在画像声明轨道）。
- 遗留行动项：①ERPNext 235/236 表单双加载深挖（对照 Frappe 官方
  cypress fill+save 协议）②矩阵协议写技能补 unique 换参（对齐 s44）
  ③链 1/5 与 261/304/141 转清理或重录候选。

## 3. 差距清单（下一步工作，按优先级）

### 高（下一冲刺）——原三高优已全部完成（见 §2.5）
**（差距清单 2026-10-11 全部清零）**
- Livewire/select2 适配（5fee920）：303 三真根因修复（select2
  mouseup+click+原生 change / fill 定位链 name 前置 / 跨系统脏断言
  清除）——终验双 pass+库级确认；引擎级惠及所有 select2 系统。
- 收割 last_step_at 落列+索引（迁移 a7c8d9e0f1a2）+generation 三
  通道新鲜度闸+健壮性体检 🔴🟡 全清（39f4044+edb439b）——均已收口。

下一步方向（按优先级）：
0. **AJ2 已全闭环**（9865f2b）：插件端登录态自动恢复落地（守卫触发→
   服务端跑适配器登录例程→cookie 注入常驻浏览器→重试当前步）——
   禅道容器重启丢态场景端到端验证（session_recovered=true→pass）。
1. **链回归 8/8 全绿收官**（ebc6e67）：六系统八链全 pass——
   2/3/11（JeecG）+7（禅道）+17（Dolibarr 订单全链 4/4）+19
   （Snipe 生命周期 3/3）+20（AN 行锚）+21（Odoo 报价 m2o 适配）。
   Odoo 双根治：action id 漂移（XML ID 稳定形态）+m2o 关系字段
   适配（下拉选中协议——与 select2 同族）。
   2026-10-13 收口：296 标 superseded→321、旧链 10 删除（重录
   实际由 321+链 21 满足——induce 产新行非原地更新）；宿主重启
   后零改动复跑 8/8（重启韧性实证）。
2. 多账号并发与生产部署（容器保活/会话保活属此域）。

### 中
4. ERPNext 技能深录（当前 2/3；SO 转单状态依赖已归档待跨步传递解锁）
5. Odoo CDP 断连稳定性（P3 遗留；lost 49% 复现与根治）
6. 禅道 CaseRun iframe 二级行操作（正式支持或归档边界）

### 低/远期
7. 自动换通道（CDP↔Playwright 故障切换，AL 块候选）
8. 多账号/多人并发/生产部署链路（详见上一版 §生产化）

## 4. 环境速查（Windows 开发机，务必先读 AGENTS.md §四）

- server 8710：`cd server && uv run uvicorn app.main:app --host 0.0.0.0 --port 8710`
  （2026-10-14 起绑 0.0.0.0——局域网 IP 可访问（防火墙规则 SkillLens 8710 已加）；仅限可信内网：PLUGIN_TRUST 免登录+弱密码）
  （**PLUGIN_TRUST=1 前缀启动**——免登录依赖；.env 已含该行则直接启动）
- 常驻浏览器 9222：`uv run --project server python scripts/live_browser.py 9222`
  （**改插件代码后必须重启它**——MV3 不热替换）
- 容器：`docker start odoo-db-1 odoo-odoo-1 dolibarr-db-1 dolibarr-dolibarr-1
  snipeit-db-1 snipeit-snipeit-1 zentao p4test-firefly-db-1 p4test-firefly-1
  ruoyi-mysql ruoyi-server ruoyi-web`（erpnext/jeecg 常驻）
- token：`cd server && uv run python -c "from app.auth import issue_token;
  from app.db import SessionLocal; from app.models import User;
  db=SessionLocal(); print(issue_token(db, db.query(User).filter_by(username='admin').first().id))"`
- 系统登录态：`server/artifacts/states/<适配器>.json`（守卫自动恢复会写；
  ERPNext 登录例程 2026-10-09 修好——#login_email/Continue + Desktop 双通道）

## 5. 测试与质量闸门（不变，复述关键）

- 三套全绿才算完成：server `uv run pytest -q`（740）；extension
  `export PATH="/d/github/.tools/node-v24.18.0-win-x64:$PATH" && npm test`（147）
- TDD 先红后绿；真机验证（插件路径必须 executor.html/面板真实路径）
- 阶段闸门仪式：测试→审查→文档→浏览器实测→报告→合并（AGENTS.md §一）

## 6. 已知坑（新增 2026-10-09，全部实证）

- **ERPNext 根路径假成功**：/ 对未登录返回 200 SPA 壳（JS 异步跳 login）
  ——登录判定必须双通道（URL+title "Desktop"）
- **首帧补发两形态污染**：404 停留页（已跳过）+跨系统停留页（多数派
  host 派生+plan url 取同 host 末条 navigation）
- **密码字段采集红线**：录制跳过密码字段（骨架无此步）——ERPNext portal
  密码必填由 runner 密码补步自愈兜底
- **MV3 SW 重启丢互斥**：内存 flag 会复位——storage 持久锁兜底
- **经典表单 Enter 提前提交**：fill 后统一补 Enter 在 Dolibarr 类系统
  直接提交表单——元素失连=early_submitted 语义
- **python open('/d/tmp/x') 落 D:\d	mp**（当前盘相对）——bash /d/tmp 是
  D:	mp；跨进程调 API 用 httpx 不用 subprocess curl（GBK 解码崩）

## 7. 文档地图（更新后）

- 主计划（唯一范围基准）：docs/specs/2026-09-24-master-delivery-plan.md（v2.8.5）
- AK 设计：docs/specs/2026-10-09-ak-exception-convergence-design.md
- AM/AN 设计：docs/specs/2026-10-10-am-expectation-anomaly-detection.md
  / 2026-10-10-an-cross-step-state.md
- 差距分析（已全收口）：docs/reviews/2026-10-09-system-gap-analysis.md
- 健壮性体检：docs/reviews/2026-10-10-robustness-audit.md
- AJ 调研：docs/references/harness-study-v2-*.md（5 篇）
- lessons：docs/references/project-lessons.md（#1-#59）
- 架构契约：docs/arch/（25 篇）

## 8. 继任 agent 提示词套件

### 8.1 开工提示词（直接粘贴给下一个 agent）

```
你是 SkillLens 项目的继任开发者。先读三份文件建立认知：
1. docs/HANDOVER.md（本任务书——现状+差距清单+环境速查+已知坑，重点 §2.6）
2. AGENTS.md（操作宪法——测试/审查/闸门仪式/安全红线）
3. docs/specs/2026-09-24-master-delivery-plan.md 的 §7 变更记录（近 20 条了解演进）

然后按序做：
① 跑通三套测试确认基线（server 740 / web 81 / extension 147——命令在 HANDOVER §5）
② 起环境：server 8710（PLUGIN_TRUST=1）+ 常驻浏览器 9222 + docker 容器
  （命令在 HANDOVER §4；改插件后必须重启 9222 浏览器）
③ 差距清单已全部清零——从 HANDOVER §3 下一步方向候选开工
  （52 链全量回归轮/多账号并发与生产部署/执行页 UX 两候选），
  先向用户确认方向再动手；计划外范围变更先进主计划获确认。
工作纪律：TDD 先红后绿；每个完成项真机验证（插件路径走 executor.html
真实路径）+审查+文档同步+git 提交；用户授权自主推进（只汇报进展不问
"继续吗"）；遇 bug 先查成熟项目（zcode-src/ 本地源码+目标系统官方
harness）再动手；异常处理走 AK 收敛层；提交前红线自扫（敏感串+git
grep 192.168）。
```

### 8.2 专项提示词（按需追加）

**跨步状态传递设计**：
```
读 docs/HANDOVER.md §3.2（Snipe 资产链实证）+ extension/src/shared/chain-rules.ts
（现有 ${stepN.字段} 机制）。设计"选择类输出→输入"传递：候选方案=步骤产物
row-ref 句柄（executed 步骤携带 pickedRow 标识，下一步 click 的 row_anchor
注入）。先业界对照（Playwright locator reuse/Katalon test object），出设计
文档进主计划，TDD 落地。验收：Snipe 查找→更新链 pass。
```

**多轮×换参战役**：
```
读 scripts/s43_*.py 四个录制脚本模式（HANDOVER §6 已知坑先过）。
对 Odoo/Dolibarr/Snipe/ERPNext 各跑第二轮：换参回放（unique 推荐+
fill_ 候选机制已有），矩阵=每系统 3 技能×2 换参，验收=断言命中+无假 pass。
产出：demo/sprint44/ 验收记录。
```

## 9. 给继任者的最后一句

这个项目的哲学是**证据链完整性**（C3）和**确定性判定**——每个功能都能
回答"你怎么知道它工作"。保持这个纪律，差距清单就是路线图。
