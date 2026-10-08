# AI 自愈定位器产品调研（2026-10-08，多 agent 学习第 4 路）

> 来源：Testim/mabl/Healenium/Functionize 官方文档+源码一手 + VON Similo 论文（arXiv 2310.02046）。

## 一、Testim：Smart Locators 多属性评分

录制时存一组属性（tag/id/name/text/CSS/相对位置），运行时按"属性稳定性"评分选优，
客户流量持续训练。被业界批评"静默自愈无假阳性面板"（Autonoma 对比文）。

## 二、mabl：auto-heal 工程闭环（最值得学）

- 录制建**元素历史**（30+ 属性+祖先），执行先用历史找 strong match，找不到才自愈
- 标准自愈=全页面部分匹配评分；**高级自愈=生成式 AI 语义相似——严格门控
  （仅云端+测试已在 plan 成功运行 ≥5 次才启用）**
- **持久化门控**：测试最终通过且属 plan run 才更新模型；断言失败则自愈不保存；
  元素历史按环境分轨；低置信度直接失败不硬愈
- **透明度三件套**：Insights 自愈流（聚合可审）；Find Summary 置信度面板
  （置信度+贡献因子）；元素历史版本表+时钟图标回滚（错误自愈 rollback-and-edit）

## 三、Healenium：评分算法源码实证

多属性加权 Levenshtein，满分 350：TAG=100/LCS路径=100/ID=50/CLASS=40/内文=30/
其他属性=30（INDEX=0）。路径高度门控（>5 且 LCS/高度<0.7 直接 0 分）剪枝。
取前 1000 候选→生成 XPath/CSS→**验证唯一命中才 healed**。
报告含 score(0-1)/healed locator/截图；score-threshold 默认 0.5；IDEA 逐条 Keep。
后端已有 Elitia LLM 集成（开源界也在走 LLM 路线）。**AGPL-3.0 双许可——只学算法重实现，安全。**

## 四、Functionize + LLM 定位学术实证

Functionize：多属性指纹+**视觉-DOM 混合检测**+行为感知（用户流仍成立才愈）。
**VON Similo 论文关键发现**：LLM 不直接生成定位器，而是**从传统算法 Top-10 候选中
精选**——失败率再降 42.9%（91.3%→95.0%），LLM 推理 47% 靠上下文 17% 靠语义，
代价 ~2s+$0.045/次，且有 10 例覆盖了原本正确的答案（防回归闸的必要性实证）。

## 五、我们领先点清单

1. **LLM 提案+确定性 locate 验证+verify 计数晋升**：比 mabl 单次通过即入库证据更厚，
   比 VON Similo（无防回归）多验证闸
2. **技能版本 supersede 链**：业界独有——自愈产生可审计可回滚的技能演化史
   （mabl 只有元素属性版本）
3. LLM 为主提案器（业界多为属性权重 Gen-1，LLM 均严格门控）
4. 本地自托管无云绑定
5. 提案表结构化落库=透明度面板的数据底座

## 该抄的 Top5

| # | 项 | 来源 |
|---|---|---|
| 1 | 元素历史版本表+一键回滚 UI 呈现层 | mabl（supersede 链比它强但缺呈现） |
| 2 | 置信度面板（verify 明细+LLM 归因理由），低置信只告警不晋升 | mabl Find Summary |
| 3 | 持久化门控：verify 外加"下游步骤成功"证据位+按环境分轨+每技能禁用自愈逃生门 | mabl |
| 4 | **属性权重预筛+LLM 精选两段式**（省 token/提速/抗覆盖回归，实证+42.9%） | Healenium+VON |
| 5 | Insights 自愈聚合流+Slack/Teams 通知 | mabl |

Sources: tricentis.com/blog/testim-locator-technologies、
help.mabl.com/hc/en-us/articles/{19078583792404,19078598947092,19078158616340,19083854354324}、
github.com/healenium/{healenium,healenium-web,healenium-backend}、
repo1.maven.org/maven2/com/epam/healenium/tree-comparing/0.4.14/、
healenium.io/docs/report、functionize.com/automated-testing/self-healing-test-automation、
arxiv.org/html/2310.02046v1、getautonoma.com/blog/ai-self-healing-test-automation
