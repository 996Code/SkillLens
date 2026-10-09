# AN 块：跨步状态传递——选择类输出→输入（设计）

> 2026-10-10 立项。触发：HANDOVER §3.2（编排渗透率 7%→30% 的钥匙）。
> 实证：skill 141（资产状态更新）fail——「第5步 Save 被拦，提示
> **请选择列表项**」（run 1817/1826）：前序步的行选择未传递到本步。

## 一、问题

现有跨步传值（AI2 `${stepN.字段}`）只从**写请求体**提取字段值——
覆盖「创建→引用」链。缺口是**选择类输出**：

| 场景 | 输出形态 | 现有机制 |
|---|---|---|
| 步1 建实体（POST）→ 步2 引用其字段 | 写请求体字段 | ✅ ${stepN.字段} |
| 步1 查找/过滤列表 → 步2 操作**选中的行** | 行点击选中的行 | ❌ 无传递通道 |

行选择不是 fill 值也不是写请求——是 UI 行交互。141 铁证：查找步
过滤出目标行后，更新步的行锚还是录制时的旧行文本 → Save 报
「请选择列表项」。

## 二、业界对照

- **Playwright locator reuse**：`const row = page.getByRole('row', {name: X})`
  ——定位器是一等值，可跨语句传递复用（同一次执行内）。
- **Katalon Test Object**：测试对象入库带变量化定位属性，用例间引用。
- **SkillLens 既有等价物**：row-anchor 换参（overrides 字符串替换锚）——
  但要求链构建者知道**旧锚文本**（脆弱：锚=录制时行文本）。

## 三、设计：pickedRow 句柄 + row_anchor_from 注入

```
步N（行触发 click 命中）──捕获──▶ pickedRow（行首格文本，跨重渲稳定行键）
                                        │
步K（row_anchor_from: N）◀──resolveRowAnchor──┘
   └─ 执行期：本步 row-trigger 候选的 anchor 直接替换为 pickedRow
      （无需知道旧锚文本——与 overrides 字符串替换互补）
```

三切片：

| # | 切片 | 侧 | 要点 |
|---|---|---|---|
| AN1 | pickedRow 捕获 | executor | row-trigger 命中时捕获行首格文本（≤80 字符）→ evidence.pickedRow → runSkill 聚合返回 pickedRows |
| AN2 | ${stepN.row} 规则 | chain-rules | StepEvidence 增 pickedRow 字段；`${stepN.row}` 特殊键提取（多条取末条=终态语义）；resolveRowAnchor(fromStep, ctx) |
| AN3 | row_anchor_from 注入 | 双端 | 链步骤 schema 增 row_anchor_from（ge=1）；executor-page 解析传参；executor 步循环替换候选 anchor（单次注入，未命中保留原锚） |

**防呆纪律**（与 resolveValue 同款）：注入未命中（来源步无句柄/越界）
保留原锚+日志可见——防静默错值。

## 四、不做（边界）

- 不做 pickedRow 的多行集合（本批单行句柄——多选场景后续）
- 不做服务端 chain_runner 的同款注入（服务端回放路径行锚走 overrides
  字符串替换已覆盖；插件链是编排主路径）
- 不改 ${stepN.字段} 语义（正交互补）

## 五、落地记录（2026-10-10）

- chain-rules：StepEvidence.pickedRow + ${stepN.row} + resolveRowAnchor
  （4 新用例 13/13）
- executor：row-trigger JS 捕获行首格 → evidence.pickedRow +
  stepPickedRows 聚合返回；runSkill 增 rowAnchor 参数（步循环单次注入
  候选 anchor）
- executor-page：stepCtx push observed+pickedRow；row_anchor_from 解析
  （未命中保留原锚+日志）
- server：ChainStepIn.row_anchor_from（ge=1 校验，测试 4/4）
- extension 全量 140/140

真机验收（第一轮，2026-10-10，链 13=139 查找→141 状态更新）：

- **机制无回归**：链执行正常走完 139 pass；AM2「目标站不可达」快败
  在 Snipe 容器掉线时顺带真机验证（2827 秒败 vs 旧行为无界等待）。
- **组合问题定位（第二轮待办）**：141 fail 于 Select Status/Select a
  Model miss——根因是 141 的 goto 重置 139 的搜索态（Snipe create 页
  的表单展开依赖先 Search），属**技能录制/链组合**问题非 AN 机制缺陷。
  且近期语料无真 row-trigger 技能对（139 的锚是选择器非行锚）。
- **第二轮前置**：录制「查找→选中（行触发）→更新」技能对（Snipe
  资产行勾选/行操作），再组链验收 row_anchor_from 注入闭环。
