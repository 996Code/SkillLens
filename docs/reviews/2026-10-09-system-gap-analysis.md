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

## 三、各系统欠缺与行动清单（调整后的测试计划）

### P0（立即）
| # | 动作 | 系统 | 理由 |
|---|---|---|---|
| 1 | ~~extension 分类补线~~ | 全部 | ✅ 已修 |
| 2 | ~~系统派生兜底~~ | Odoo/禅道/Firefly | ✅ 已修 |
| 3 | **Dolibarr 断言 0→有** | Dolibarr | 10 技能全裸奔、59 pass 无判定=纯假 pass 工厂（空断言 all([])==True 直接 pass）。补录带 API 抓取会话→generate_assertions→回放验证。**同时给空断言 pass 加显式标记或移出分母** |
| 4 | **起容器**（odoo/dolibarr/snipe/zentao/firefly 全 Exited 255） | 三系统+禅道 | 任何补课的硬前置；落实"重启后全量 docker start"例程 |

### P1（本周）
| # | 动作 | 系统 |
|---|---|---|
| 5 | Snipe+若依裸奔技能补断言（Snipe 14 假 pass/若依 8 裸奔） | Snipe/若依 |
| 6 | ERPNext 自愈验证积压清理（26 proposed→verified/promoted，让自愈参与回放） | ERPNext |
| 7 | 禅道重跑矩阵补 AJ1/AJ2 数据（技能最多系统对新防线零数据；至少 34 个基名代表） | 禅道 |
| 8 | 禅道 candidate 清障（9 个=10-06 LLM 网关配额耗尽污染，重跑命名） | 禅道 |

### P2（排期）
| # | 动作 | 系统 |
|---|---|---|
| 9 | 禅道技能归并（53 个编号拷贝→34 基名，S15 supersede 机制现成从未用过） | 禅道 |
| 10 | 禅道断言升级（/index.php 单入口无区分度→story_count 探针补 layer4 实体级验证） | 禅道 |
| 11 | 三系统录制补课（各 3-5 链×2 轮多日战役，Odoo 优先） | Odoo/Doli/Snipe |
| 12 | 学习管道清障（Dolibarr iframe 窗口分桶/Snipe model-create 标记/Odoo 剔 onchange 噪声） | 三系统 |
| 13 | 层4 背书激活（evidence_count≥3 全库为 0——回放 pass 不累加，只有人工 verify 累加） | 全部 |
| 14 | 编排渗透率（2%——链只用了 6 个技能；以 JeecG 5 链为样板在高频技能上补链化） | 全部 |

### P3（远期）
- Odoo lost 49% 先修 CDP 断连稳定性
- 禅道 CaseRun iframe 二级行操作（采集层豁免→正式支持或归档边界）
- zentao.yaml bug-chain 重复行机械残留

## 四、防再生（已识别待做）

1. 录制侧补首帧：capture.ts 在 recording false→true 时让已加载页面补发 navigation（105 会话零 navigation 的根治）
2. 空断言 pass 显式标记（Dolibarr 型假 pass 防线）
3. HOST_SYSTEM 从 adapters/*.yaml 清单生成（映射同源，新系统零代码接入即有系统名）
4. 会话落库后 navigation=0 时健康端点告警

## 五、测试矩阵调整（结论）

**从"均匀覆盖"转向"按健康度分配"**：
- JeecG/禅道/ERPNext：已有资产，重点转向**链化+自愈验证+断言升级**（盘活存量）
- 若依/Snipe：**补断言**（判定层修复，回放才有意义）
- Dolibarr：**从 0 重建断言+重录**（当前 pass 率是幻觉）
- Odoo：**先修环境再谈内容**（lost 49% 下内容结论无意义）
- 新防线（AJ1 分类/AJ2 守卫）需要**禅道矩阵轮**积累数据（技能最多系统零覆盖）
