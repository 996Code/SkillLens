# 全系统差距分析与测试计划调整（2026-10-09，4 agent 并行深查）

> 4 路并行：链路深度抽查 / 未知系统归因 / 禅道差距 / Odoo-Dolibarr-Snipe 贫瘠根因。
> 两个 P0 已当场修复（e327cc2）：extension 分类补线、系统派生兜底。

## 一、系统健康度总表（修复后口径）

| 系统 | 技能 | 断言覆盖 | 链 | 自愈活跃 | 30天失败画像 | 诊断 |
|---|---|---|---|---|---|---|
| 禅道项目 | 99 | 96%（但 /index.php 无区分度） | **0** | **唯一闭环**（27v/3p/2个v2+） | fail+error 59%，42% 技能从未回放 | 资产最多杠杆最低 |
| 若依权限 | 52 | 85%（8 裸奔） | 1 | 弱（10/4） | 85 fail 未归因 | 归因+断言双欠账 |
| ERPNext 客户 | 47 | 94% | 0 | **积压最大**（26 proposed 仅 7 verified） | 定位失败 55 条全库最多，flaky 1.9% 最高 | 漂移第二重、验证欠账 |
| JeecG 表单 | 45 | 100% | **5** | 活跃（28/11/4r） | fail 51%+lost 10.6%，139 未归因 | 漂移最重但仪表最全 |
| Snipe 资产 | 22 | **55%**（14 假 pass） | 0 | 少 | — | 欠断言，判定半失明 |
| Odoo 销售 | 12 | 1/12 | 0 | 5 proposed 0 verified | **lost 49%** | 环境不稳+骨架噪声 |
| Dolibarr 订单 | 10 | **0%**（59/61 纯假 pass） | 0 | 2 | pass 假象 | **全库最大风险点** |
| Firefly III | 1 | — | 0 | — | — | P4 终验证据，正常 |

## 二、已当场修复的 P0（e327cc2）

1. **extension 主通道分类缺位**——占 fail/error 54% 的通道从不写
   failure_class（AJ1 只接了 server 路径）。三处终态写点补线+2 红绿测试。
   分类是派生值，历史 run 可重算，补线即全量生效。
2. **系统派生两个洞**——17 个"未知系统"实为禅道 6+Odoo 11（会话零
   navigation：SPA/iframe 录制窗口无整页加载），1 个裸 host 实为 Firefly。
   兜底链（action.url）+映射补齐后：禅道 99/Odoo 12/Firefly 1，零残留。
3. **P0-3 Dolibarr 断言 0→有（2026-10-09 完成）**——根因比预想深：
   录制侧 net-hook 只包 fetch/XHR，Dolibarr 经典表单整页提交两头瞎
   （api_calls=0 + after 快照缺失），**补录也救不了**。解法换道
   "回放反哺"：服务端回放 observed 走 Playwright 全响应捕获（含表单
   POST），从 pass run 的写响应引导 api_status 断言（确定性，C3 合规）。
   落地链（TDD 全程红→绿）：
   - `POST /skills/{id}/assertions/from-run`：bootstrap_from_run（动态段
     归一 {id}、查询型模板排除、同模板幂等、只认 pass run）
   - api_status payload 加可选 `method` 过滤：经典表单 GET 页面加载与
     POST 提交共享路径（query 忽略），防 GET 200 稀释写期望
   - trends 加 `unverified_pass`：0 断言技能的 pass 显性化
     （Dolibarr 32/禅道 8/若依 11/Snipe 14——假 pass 工厂可见）
   - 顺带根治三个挡路 bug：AJ2 守卫只接 fail 态+只认 URL（Dolibarr
     登录页在根路径标题 "Login @ 24.0.0" 两头漏）→ login_page_evidence
     谓词（error 态+标题证据）；适配器登录假成功（url_not_contains
     默认 "login" 对经典表单失效）→ text_contains 双通道判定
     （dolibarr.yaml 补 "My Dashboard"）；fill 后统一补 Enter 在经典
     表单直接提交（readback 卡 30s 超时判失败）→ 元素失连=提前提交
   - 真机验证：7/10 技能断言 0→1 且回放全 pass（run 1642-1648）；
     187/190/191 为纯导航技能（无写请求，断言无从引导，由
     unverified_pass 诚实标记）；188/189 视觉基线过期重录

## 三、各系统欠缺与行动清单（调整后的测试计划）

### P0（立即）
| # | 动作 | 系统 | 理由 |
|---|---|---|---|
| 1 | ~~extension 分类补线~~ | 全部 | ✅ 已修 |
| 2 | ~~系统派生兜底~~ | Odoo/禅道/Firefly | ✅ 已修 |
| 3 | ~~Dolibarr 断言 0→有~~ | Dolibarr | ✅ 已修（回放反哺通道，见§二.3） |
| 4 | ~~起容器~~ | 三系统+禅道 | ✅ 已起（六系统探活 8069/8080/8081/8082/8096/8090 全通） |
| 5 | ~~禅道矩阵轮~~（P0-5，提前完成） | 禅道 | ✅ 40 基名代表全跑（run 1703-1742）：14 pass/20 fail/6 error，失败全 e3_drift 零 e1/e2——AJ1 分类器实战数据落库。失败归因：状态依赖定位失败 20（技能需前置数据，编排 setup 是产品答案）+视觉漂移 3+断言 2。**矩阵轮本身挖出两个真 bug 已修**：批回放路径漏传 system（登录态不注入+守卫永假）；禅道 query 风格登录 URL（f=login）不被分类词表匹配（误判 e3_drift→已补词表，e1_env 正确） |

### P1（本周）
| # | 动作 | 系统 |
|---|---|---|
| 5 | Snipe+若依裸奔技能补断言（Snipe 14 假 pass/若依 8 裸奔）——回放反哺通道（from-run 端点）已就绪，直接复用 Dolibarr 流程 | Snipe/若依 |
| 6 | ERPNext 自愈验证积压清理（26 proposed→verified/promoted，让自愈参与回放） | ERPNext |
| 7 | ~~禅道重跑矩阵补 AJ1/AJ2 数据~~ | 禅道 | ✅ 见 P0-5 |
| 8 | ~~禅道 candidate 清障~~ | 禅道 | ✅ 扩为全系统提案积压清理（95 个 proposed：JeecG 28/ERPNext 26/Odoo 14/禅道 13/若依 10 等）——确定性垃圾词表 `is_junk_label`（网关配额错误消息×10/占位符 .YYYY.×12/幻觉指令 Check again×9 等）生成时拦截（防再生）+存量 36 条批量拒绝；59 个真实候选（Save/New/Customer/查询类）保留待 verify |
| 6 | ~~ERPNext 自愈验证积压清理~~ | ERPNext | ✅ 并入上行：垃圾清障后 59 个真实 proposed 候选保留（verified 机制门控参与回放，不阻塞）；晋升走既有 LOCATE_AUTO_PROMOTE_N 通道 |

### P2（排期）
| # | 动作 | 系统 |
|---|---|---|
| 9 | ~~禅道技能归并~~ | 禅道 | ✅ 59 编号拷贝→40 基名（S15 supersede 链；候选 7 个全同名 LLM 命名失败也归并）；活跃 99→40 |
| 10 | ~~禅道断言升级~~ | 禅道 | ✅ query 感知模板落地：templatize_query（路由语义参数入模板，敏感/动态/分页排序/回跳参数剔除）+path_matches query 同值全含匹配（模板无 query 零破坏，export_shared 同步同源）；实测禅道真实 URL 产出 m=bug&f=resolve/m=testcase&f=create 等高区分度模板；存量断言回归 5/5 pass。新录制会话自动获得 query 模板（93/95 都落 /index.php 的时代结束） |
| 11 | ~~三系统录制补课（第一轮）~~ | Odoo/Doli/Snipe | ✅ 第一轮完成：Odoo 3 技能（报价创建/确认/发票）+Dolibarr 4 技能（第三方/订单/确认/发票）+Snipe 3 技能（资产创建/借出/归还）录制学习；回放验证 Dolibarr 4/4+Snipe 3/3+Odoo 2/3 pass（298 录到登录步骤污染已归档）；断言反哺 9 技能。**顺带根治**：系统派生跳过 /404 错误页 navigation（首帧补发副作用——录制开始的停留页若是网关 404 会污染系统派生，Odoo 技能曾被标 njmind）。多轮×换参战役可按此模式续跑 |
| 12 | 学习管道清障（Odoo 部分） | Odoo | ✅ 查询型词表补 Odoo RPC 名（onchange/web_read/mail thread/render_public_asset/get_views）防再生+存量 34 条噪声断言清除（36→2 只剩真实写） |
| 13 | ~~层4 背书激活~~ | 全部 | ✅ 回放 pass 的断言命中与人工 verify 同权重累加 evidence_count（≥3 标 layer4_verified）——(kind, api_template) 联合定位防同模板双计（TDD 3 用例） |
| 14 | ~~编排渗透率提升~~ | 全部 | ✅ 6→12 链、2.6%→7.0%（16 技能入链），覆盖六系统（禅道×2/Snipe/Odoo/JeecG/Dolibarr/若依）；全部 wait=1 真机 pass。**实证沉淀**：①链设计第一律=用自足技能（状态依赖技能组合会互相破坏前置——Snipe 查找→更新链因未传资产选择 fail，换成双查找链 pass）；②ERPNext 全技能过时（容器重启后 0 pass，客户保存有必填密码录制缺陷）→归入 P2-11 重录战役 |

### P3（远期）
- Odoo lost 49% 先修 CDP 断连稳定性
- 禅道 CaseRun iframe 二级行操作（采集层豁免→正式支持或归档边界）
- zentao.yaml bug-chain 重复行机械残留

## 四、防再生（全部落地 ✅）

1. ✅ 录制侧补首帧：capture.ts 在 recording false→true 时补发首帧 navigation（两个 toggle 点：GET_STATE/storage.onChanged；顶层帧限定防 iframe 噪声；旧初始 emit 段收敛为同一路径防双发）
2. ✅ 空断言 pass 显式标记：trends unverified_pass 口径（P0-3 已落）
3. ✅ HOST_SYSTEM/SYSTEM_ADAPTER 从 adapters/*.yaml 生成（yaml 新增 system_label 字段=系统名唯一事实源；八清单全配；系统名与历史完全一致零迁移；NJMIND_HOST env 项保留）
4. ✅ 会话 navigation=0 比率进 /health 端点（count/total/ratio——采集退化可见）

附：P3 zentao.yaml bug-chain 重复 fill 行清理。

## 五、测试矩阵调整（结论）

**从"均匀覆盖"转向"按健康度分配"**：
- JeecG/禅道/ERPNext：已有资产，重点转向**链化+自愈验证+断言升级**（盘活存量）
- 若依/Snipe：**补断言**（判定层修复，回放才有意义）
- Dolibarr：**从 0 重建断言+重录**（当前 pass 率是幻觉）
- Odoo：**先修环境再谈内容**（lost 49% 下内容结论无意义）
- 新防线（AJ1 分类/AJ2 守卫）需要**禅道矩阵轮**积累数据（技能最多系统零覆盖）
