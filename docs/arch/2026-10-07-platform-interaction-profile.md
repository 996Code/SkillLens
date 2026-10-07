# 平台化组件化四阶段（P1-P4）：系统交互差异声明式架构

> 2026-10-05/06/07。触发：用户"后续接入新系统，交互肯定有很大差异，
> 这时候如何让其适应改系统"+"组件、链路回放和系统配对，然后系统可以
> 在后台通过 url 匹配上，支持类似油猴的那种通配符匹配，从而做到自动
> 隔离"。目标：**新系统接入零手写编排脚本、零改执行器源码**。

## 架构转变

```
旧：执行器源码里堆系统特化分支（JeecG dropdown、若依 modal、ERPNext
    通道……），每接一个系统改一次 executor.ts
新：交互画像（YAML 声明）+ 指纹自动生成 + URL 自动配对 —— 执行器退化为
    画像解释器，系统差异全部声明化进 adapters/*.yaml
```

四阶段闭环（全部终验 PASS）：

| 阶段 | 内容 | 提交 |
|---|---|---|
| P1 | 交互画像架构：InteractionProfile 五维组件（dropdown/modal_submit/form_fill/row_action/route_guard），随 plan 下发，执行器解释 | 17fc73b |
| P2 | 画像指纹自动生成：贴系统页面 HTML → 组件库/框架识别 → 画像草稿 YAML | 3cf691e |
| P2.5 | URL 通配符匹配：油猴 @match 语义，goto/采集 URL → adapter 自动配对隔离 | 386a2d8 |
| P3 | 七系统扩链（每系统+1-2 业务链）+ 录制框架 raw CDP 重写 | bfb1c31 |
| P4 | Firefly III 全新系统纯 YAML 接入终验（零代码） | 2d9a0db |

## 一、交互画像（P1）

### 数据模型（server/app/adapters/manifest.py）

```python
InteractionProfile:
  dropdown:       DropdownProfile      # engine/menu_item_match(includes|exact)/
                                         # menu_item_click(trusted|elclick)/mount_wait_ms
  modal_submit:   ModalSubmitProfile   # selector/button_regex/pick(last|first_visible)/
                                         # render_wait_ms
  form_fill:      FormFillProfile      # framework(generic|frappe)/field_locators 序/
                                         # same_label_priority(modal_first|first)
  row_action:     RowActionProfile     # anchor_match(insensitive|sensitive)/scroll_into_view
  route_guard:    RouteGuardProfile    # async_set_route/normalize_new_suffix
```

- 全部字段有默认值——无画像清单走内置默认=通用行为（向后兼容存量 7 系统）。
- 画像随 `/executor/skills/{id}/plan` 下发（`interaction_profile` 字段），同时落 `run.plan`（复现/诊断可查）。
- 执行器侧（extension executor.ts）：`__ip = plan.interaction_profile`，dropdown 菜单项匹配模式/挂载窗口、modal 提交按钮正则/选择器/取位由画像驱动。

### 指纹自动生成（P2，server/app/adapters/fingerprint.py）

`POST /adapters/fingerprint`（body: dom+url）→ 组件库/框架识别 → 画像草稿 YAML：

- ui_library 指纹：`ant-(modal|btn|dropdown)` → ant-design；`el-(dropdown|message-box)` → element-plus
- framework 指纹：`data-fieldname`/`data-label=` → frappe
- 每条识别规则源自 7 系统实战铁证（如 includes 匹配=JeecG 270 图标文本混入）
- 工作台 AdaptersView 集成：贴 HTML → 出画像 YAML → 贴进清单即接入

## 二、URL 通配符匹配（P2.5，server/app/adapters/urlmatch.py）

油猴 @match 语义：

```
url_matches: ["http://127.0.0.1:8095/*"]   # * 通配任意字符
```

- **specificity = 模式去通配符后长度**——具体规则胜过通配（多清单命中同一 URL 时最长者赢）
- query 忽略（对齐油猴）；无声明=不参与匹配（显式声明制，存量清单零影响）
- 消费点①执行侧：`executor_plan` 端点取 instructions 的 goto URL → `_ma(url, manifests)` 命中 adapter；未命中回退 skill.system 名称映射
- 消费点②采集侧：插件 popup 开录时活动页 URL → `GET /adapters/match?url=` → 命中系统建会话（自动隔离）
- **注意**：该端点挂鉴权守卫——插件侧必须带 Bearer（评审修复 R6，曾因裸 fetch 401 静默失效）

## 三、矩阵扩链与录制框架（P3）

- v21_matrix.py CHAINS 扩至 52 条（8 系统×2 业务链×2 轮换参）；skill_vars 换参三层注入（fill value+click label 实例值 key+row-anchor）；ERPNext 跨单引用注入最新 Open quotation。
- p3_record.py 录制框架全 raw CDP 重写（websockets 直连 CDP/SW target）：根治 Playwright Node driver 连外部浏览器时 dialog manager 竞态崩溃（六轮实证不治本——popup 常驻/单 driver/独立连接皆试过，'No dialog is showing' uncaught 杀 driver）。CDPage 三原语（goto/fill/click_text）+ sw_evaluate（SW target 直连 Runtime.evaluate 直控插件录制）。

## 四、零代码接入终验（P4）

Firefly III（全新系统，演示容器）：纯 YAML 接入闭环——清单声明（登录/链/探针豁免）→ URL 配对 → p3_record 录制 → 学习（skill #291）→ 插件执行 PASS。全程零执行器改动、零服务端代码改动。

## 五、安全红线（2026-10-07 评审修复）

本架构新增面引入的安全边界（评审实锤后修复）：

1. `/adapters/{id}` 路径穿越——白名单字符校验（`[A-Za-z0-9_-]+`）
2. `/adapters/match` 鉴权——插件侧带 Bearer（曾 401 静默回退 njmind）
3. 画像/指纹端点均在 require_user 守卫后

## 真机验证

- 矩阵 52/52 全 PASS（8 系统，插件真实路径，每链 2 轮换参）
- 7/7 系统 URL 自动配对（服务端路径）+ 插件开录路径修复后复验
- Firefly 零代码接入全程用户可见（live_browser 9222 常驻浏览器）
- 测试基线：server 506 / web 54 / extension 83（评审新增安全用例 server 2 + extension 7）
