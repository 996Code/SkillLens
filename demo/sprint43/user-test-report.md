# Sprint 43 用户测试报告：全系统核心业务多角度闭环验证（S43-4）

> 2026-10-02。测试人：代理（用户授权自主闭环）。
> 触发：用户"把你下载的开源系统全部走一遍闭环，完善的流程业务测试，不要光知道
> 基础数据，每个系统都有核心流程，这个必须多个角度走几遍"。

## 1. 验证范围与形态

七个目标系统（六个 docker 部署 + njmind 真实系统前序已验），每系统核心业务链：

```
2 轮人工路径录制（换数据）→ 学习管道归纳 → 换参回放（技能编排 API）
→ 实体级验证（直查目标系统 DB/API，确认实体真实建出/流转）
```

与单步冒烟的本质区别：**验证的是完整业务语义**（下单→确认→开票；建角色→建
用户→新账号登录），不是单页 CRUD。

## 2. 七系统成果总表

| 系统 | 业务链 | 技能 # | 回放 | 实体级验证 | 关键提交 |
|---|---|---|---|---|---|
| Snipe-IT | 资产生命周期：Create→Checkout→Checkin | 154/155/156 | 3/3 PASS | 资产真实建出+签出签入 assigned_to 翻转 | 2fcea43 |
| 禅道 | QA 链：需求→用例→测试单→用例执行 | 166/167/168/169 | 4/4 PASS | story/case/testtask+执行结果落库 | ac88817 |
| Odoo | 销售链：报价→确认→开票 | 178/179/180 | 3/3 PASS | sale.order 状态验证 | 8d1bf1a |
| Dolibarr | 订单链：第三方→订单→确认→开票 | 188/189/190/191 | 4/4 PASS | 订单 PROV→validated、发票建出 | 3a47d58 |
| JeecgBoot | 在线表单链：建表→同步→填数据 | 269/270/271 | 3/3 PASS（S43-5 链式 override 修复后） | onl_cgform_head+SHOW TABLES+数据行 | 07cf50c |
| ERPNext | CRM 链：客户→报价→销售订单 | 234/235/236 | 3/3 PASS（22 步长链） | Frappe API count_doc 确认 | 8231e6e |
| 若依 | 权限链：建角色→建用户→新账号登录 | 256/257/258 | 3/3 PASS | 新账号 POST /prod-api/login 拿 token（API 级证据） | 606ceed |

合计 **23 个技能学成，23 个换参回放全 PASS**（S43-5 补齐 JeecG 链式 override 后）。

## 3. 本 Sprint 根治的技术缺口（按发现顺序）

### 3.1 Snipe-IT：select2 AJAX 下拉全链打通
- select2 渲染层容器与 hidden select 无 DOM 关联 → 采集侧 select2HostSelect
  （渲染层取相邻 hidden select 的 name 进 labels）；回放侧容器组选择器优先序
  + select2 专属策略（开容器→填搜索框→点结果）。
- 弹层搜索输入无 name/id/placeholder → inputKey 表单组 label 终极回退
  （.select2-search__field 类信号 + "--open 类且前邻即 hidden select"锚定）。

### 3.2 禅道：跨 frame 定位优先级
- iframe 业务页图标操作（a[title=执行]）与顶层菜单同名纯文本冲突 → locate
  两级遍历（第一轮全 frame 只找可见 [title=]，第二轮原全策略链）。

### 3.3 Odoo：空库 view sample 模式
- Odoo 空库时列表行 opacity 0.33 + pointer-events:none——Playwright/browser-use/
  JS 合成事件全部不可交互（不是事件层问题，是 Odoo 产品逻辑）。XML-RPC 种一条
  真实单据后完全恢复。状态依赖经容器内 XML-RPC 查 id 注入。

### 3.4 Dolibarr：模块激活必须走 UI toggle
- DB 手插 llx_const 不完整（菜单/权限注册缺失）→ admin/modules.php toggle 才
  跑完整模块 init。用户权限补插 llx_user_rights。

### 3.5 ERPNext：Frappe 官方 harness 模式根治提交判定与勾选
- **intercept+wait**：写类按钮点击后等写请求（POST）落地，无 POST 即"提交被拦"
  判失败——根治 Save 假阳性（点击 ok 但服务端拒了）。
- **checkbox 勾选**：官方 cypress 用 check(force=True)——modal spinner 循环
  动画使 Playwright stability 检查永不满足，force=True 跳过 actionability 直击。
- 两步提交 Submit→Yes 豁免（plan 全量已知，下一步是确认词则本步豁免写判定）。
- 断言生成剔除查询型 RPC（reportview/search_link 等——它们不改变状态）。

### 3.6 若依：动态值对齐归一 + el-select 占位定位
- **对齐层动态值双修**（Healenium 位置+类型相似思想）：①label 命中本会话
  input 值（≥3字符）的 click 跨会话互异 → 双侧归一 click:⟨dyn⟩ 占位键；
  ②孤立 1v1 落单 click 对按位置缝合（动态特征门：≥4字符且含 ASCII alnum，
  防"国内/国际"稳定词误缝）。
- el-select 空下拉渲染为 .el-select__placeholder 容器裸 span 文本（非 input
  属性）→ locate 专属策略。
- 初始密码登录强制"安全提示"弹窗、退出确认框 → _confirm_logout_box 统一处理。

### 3.7 JeecgBoot：无属性输入变量化
- 设计器抽屉 input 无 name/id/placeholder → inputKey 表单组 label 终极回退
  （.cgf-item/.ant-form-item 内 label 文本，如"*表名"）；断言 hex 动态 id
  （[0-9a-fA-F]{16,}）视为动态段；URL 模板化同步。

## 4. 官方 harness 方法论沉淀（用户强制要求，已固化进 AGENTS.md）

> 用户原话："你看看 zcode 等等让你下载的来源的 harness，以后我们都要参照这些，
> 写到你的流程里面去，你的开发流程，bug 修复流程"

| 坑 | 官方做法 | 落地 |
|---|---|---|
| 提交是否成功（toast 文案不可靠） | Frappe cypress：intercept+wait 写请求 | runner.py 写类按钮等 POST 落地 |
| 模态动画中点不上元素 | Frappe cypress：check(force=True) | _check_row_checkbox 三级降级 |
| 空库不可交互 | Odoo tour：先种数据 | XML-RPC 种单据 |
| 模块激活 | Dolibarr 文档：modules.php UI | UI toggle |
| 定位评分多信号 | Healenium LCS 评分 | locate 评分兜底层 |

## 5. 已知未竟项（如实声明）

1. ~~JeecG Sync/Fill 链式 override~~ **已修复（S43-5，2026-10-02 晚）**：
   - 根因：行点击步 labels 是录制时行文本（旧表名），换参回放新表行过滤不到；
     另一条断言期望值是纯数字实体 id，跨轮必漂移误判。
   - 修复：①execute_plan 增加 row_anchor_hints（override 值注入行锚，click
     与 checkbox 两分支优先级最前）；②assert_eval 对动态实体标识期望
     （纯数字≥12/hex≥16）记录不判定（与 URL 层 _ID_SEGMENT 同哲学）。
   - 复验：三链 ALL PASS（Create 表单 11→12 / Sync 物理表 0→1 / Fill
     status=pass + sl_rp* 表 1 行真实数据）；#270 详情页最近执行 pass；
     新增测试 test_jeecg_chain_override.py 5 用例；回放域回归 83 passed。
   - 截图：screenshots/jeecg-sync-skill270-after-fix.png。
2. **G4 试点团队**：唯一无法代理的外部输入。

## 6. 三套测试基线

- server：447 passed（含 S43-4 新增对齐归一/定位/断言用例）
- web：54 passed
- extension：76 passed（select2 采集/checkbox 宿主行文本/inputKey 回退链）

## 7. 证据文件

- 技能 ID 映射：`*-chain.json`（7 份）
- 回放+实体验证结果：`*-replay.json`（4 份：erpnext/ruoyi/jeecg + odoo 记录在
  s43_odoo_replay.py 输出、snipe/zentao/dolibarr 记录在各自 replay 脚本输出）
- 截图：`screenshots/`（ruoyi-perm-loggedin、ruoyi-user-form、erp-* 6 张、
  jeecg-* 3 张、snipe-setup 4 张）
- 编排脚本：`server/scripts/s43_*.py`（14 个，录制+回放+验证一体）

## 8. 结论

七系统核心业务链闭环达成。学习→换参回放→实体级验证的完整能力在 7 个异构
系统（5 种前端框架：zui/element-plus/ant-design-vue/owl/select2+Bootstrap）
上验证通过，官方 harness 方法论贯穿修复全程。
