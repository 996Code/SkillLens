# Sprint 21 用户测试报告：块 S 协作与准入（G4 前置）

> 日期：2026-09-27 · 分支：s21-collab-auth · 计划：docs/superpowers/plans/2026-09-27-sprint21-collab-auth.md
> 目标：工作台从单用户裸奔 → 三角色账号体系（admin/reviewer/viewer），解除 G4 试点闸口硬阻塞。

## 一、测试覆盖与结果

### 1. 三套测试全绿

| 套件 | 结果 | 说明 |
|---|---|---|
| server pytest | **297 passed**（279 存量 + 18 新增） | 存量测试**零改动**（conftest client 夹具内置 admin 会话）；新增 test_auth.py(7) + test_auth_api.py(9) + test_reviews 新增(2) |
| web vitest | **40 passed**（34 存量 + 6 新增） | auth.spec.ts(5) + ReviewPortal viewer 用例(1)；ReviewPortal 存量用例适配登录态评审 |
| extension | **31 passed** | 不受影响（插件只调豁免通道 health/sessions/events） |

### 2. API 层实测（curl）

- 无 token 访问 `/api/v1/skills` → **401** ✓
- `POST /auth/login` 错误密码 → 401；正确 → token+user ✓
- 插件豁免通道：`/health`、`POST /sessions` 无 token 正常 ✓

### 3. 浏览器用户层实测（真实操作路径）

| # | 场景 | 结果 | 截图 |
|---|---|---|---|
| 1 | 未登录访问 /skills | 路由守卫自动跳 /login ✓ | 01-login.png |
| 2 | 错误密码登录 | 显示"用户名或密码错误"，不建会话 ✓ | — |
| 3 | admin 登录 | 跳 /skills，侧边栏显示"admin（admin）"+ 登出按钮，9 个技能正常加载 ✓ | 02-skills-admin.png |
| 4 | reviewer1 评审 | 评审人自动取登录身份（"评审人：reviewer1"），提交 run #5 成功，队列 5→4 ✓ | 03-review-portal.png |
| 5 | viewer1 只读 | 评审表单隐藏，显示"当前账号为只读（viewer），无评审权限"，列表仍可读 ✓ | 04-viewer-readonly.png |
| 6 | 登出 | token 失效，回登录页 ✓ | — |
| 7 | 控制台 | 全程**零报错** ✓ | — |

## 二、易用性发现表

| 级别 | 发现 | 处置 |
|---|---|---|
| P2 | 登录页无"记住我"（token 7 天过期后需重登） | 可接受——试点期安全优先；后续可加续期 |
| P3 | admin 建号只有 API（`POST /auth/users`），无界面 | 转后续需求（试点期 admin 一人够用，命令行建号可接受） |
| P3 | 401 过期跳登录时无"会话已过期"提示 | 转后续需求（直接跳转不丢数据，可接受） |

## 三、安全审查结论

- 密码 pbkdf2_hmac（10 万次迭代，stdlib 零新依赖），比对用 `secrets.compare_digest`（防时序）✓
- token 只存 SHA-256 哈希（明文不落库），登出即删，7 天过期 ✓
- 登录失败统一"用户名或密码错误"（不泄露用户是否存在）✓
- 豁免通道最小化：仅 health + 插件上报（插件无凭据注入能力，通道边界写入 main.py 注释）✓
- 截图脚本凭据改环境变量读取（审查中发现硬编码，已修复）✓
- diff 敏感串扫描：无 key/密码/域名泄露 ✓

## 四、耦合审查结论

- `app/auth.py` 纯函数层（无 FastAPI 依赖），`app/api/auth.py` 只做 HTTP 适配——分层干净 ✓
- 认证挂载集中在 main.py（`dependencies=[Depends(require_user)]`），各 router 零侵入 ✓
- reviews.py 从 `app.api.auth` 导入 `require_role`（API 模块间一处导入）——可接受，接口稳定
- 存量 279 测试零改动通过——破坏面控制达成 ✓

## 五、遗留与后续

- 块 S 验收标准 S1-S4 全部达成；G4 闸口的账号体系前置已就绪
- 后续按主计划 v1.6 顺序：块 T（视觉回归断言）→ V（性能基线）→ U（自愈闭环）→ W（集成出口）
