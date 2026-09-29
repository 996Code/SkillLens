# S36：ERPNext 多目标验证 + 多信号定位架构

> 2026-09-29。需求：再上流行系统（ERPNext）；元素定位不能逐 UI 框架打补丁。
> 栈：deploy/erpnext（frappe_docker 官方 pwd.yml，10 服务，端口 8090）。
> ERPNext v16：安装向导经 bench setup_complete 跳过；管理员 Administrator/admin。

## 核心成果

**ERPNext（开源 ERP 第二极，Frappe 框架）录制→学习→换参回放→副作用落库闭环**：
- skill #64 CustomerCreationFlow（Add Customer → customer_name → Save）
- 换参回放 run 190：**3 步全 ok**，tabCustomer 真实创建 "ErpNext Replay M9"
- 2/3 断言绿；唯一 fail 为瞬态 toast 断言（state_signal 期望 "Changes saved"
  toast——回放快照时机错过瞬态元素，已知边界）

## 多信号定位架构（回应"无法枚举所有 UI 框架模式"）

**思路转变**：采集侧不再"猜对一个标签"，而是一次性收集元素的全部定位信号；
回放侧逐候选×全策略扫描。任何框架暴露任一信号即可定位，新框架零适配。

### 采集侧（extension describe-element.ts）

- `labels: string[]`：aria-label / placeholder / title / input.value / 文本 /
  data-fieldname / name / 稳定 id（去重、优先序；框架自动 id 剔除）
- `ordinal`：同类兄弟序号（结构兜底信号）
- `label = labels[0]`（骨架签名兼容）
- inputKey（input 事件采集闸门）同步补 data-fieldname——Frappe 模态输入框
  无 name/id/placeholder/aria，此前整个事件被丢弃

### 回放侧（server locate.py）

- 快路径：首选 label 走全策略矩阵（role/text/placeholder/label/id/name-attr/
  data-fieldname/input-value）
- 慢路径：候选 labels 逐个重试；结构兜底（path 祖先链 + ordinal nth-of-type，
  唯一命中才用——宁缺毋滥）
- **可见匹配遍历**：同标签多元素时不再 .first（隐藏元素常在 DOM 前）
- **模态优先**：多个可见匹配时优先开放模态/对话框内的（ERPNext 列表
  "存过滤器"Save 与模态 Save 同名同可见——用户交互上下文在顶层容器，
  通用 UI 原则非框架适配）
- **fill 控件优先序**（prefer_controls）：Frappe 把字段名渲染成可见帮助文本，
  text/role 策略会抢先命中文本节点——fill 场景控件类策略前置

### 数据流

capture target.labels/tag/ordinal/path → plan 步透传 → runner → locate。
（compile_skeleton_plan click/input 步均携带多信号）

## 已知问题：Playwright node driver 崩溃（用户留意项）

**现象**：录制脚本在 ERPNext 页面交互后，下一个 driver 调用抛
"Connection closed while reading from the driver"。
**根因**：Playwright node driver 自身未处理的 Promise rejection
（stderr 见 `triggerUncaughtException(err, true /* fromPromise */)`），
Node 15+ 默认 unhandled rejection 即进程退出。与 ERPNext 页面（Frappe
socketio websocket + 重 SPA）交互相关；Odoo/Dolibarr/njmind 未复现。
**规避**（s36_erpnext_full.py 已用）：①每轮录制独立 playwright 连接
（崩溃只损失当轮）②流程后等待用 asyncio.sleep 替代 page.wait_for_timeout。
**后续**：升级 Playwright 版本观察是否修复；必要时向 playwright 上游报 issue。

## 部署备注

- ERPNext compose 端口改 8090（避开 Dolibarr 8080）
- JeecgBoot 镜像被 registry 镜像源 403（放弃）；禅道（easysoft/zentao）
  镜像已拉取，部署验证留 S37
- Snipe-IT 8081 已部署（mariadb + 迁移完成），其 .env 模板用 docker-link
  旧式变量名（MYSQL_PORT_3306_TCP_ADDR/MYSQL_USER），验证留 S37
