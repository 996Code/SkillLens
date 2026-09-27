# Sprint 21：块 S 协作与准入（G4 前置）

> 主计划 v1.6 块 S。目标：工作台从单用户裸奔 → 三角色账号体系，解除 G4 试点闸口的硬阻塞。
> TDD 先红后绿；完成后走阶段闸门仪式（三套测试→审查→文档→浏览器实测→报告→合并）。

## 现状与边界

- 现状：无任何认证；279 个测试经唯一中心夹具 `client`（tests/conftest.py）打 API；插件只调 3 个端点（/health、POST /sessions、POST /sessions/{id}/events）。
- 豁免通道（不加认证）：health、events（插件上报）。其余 API 默认要求 Bearer token。
- 密码哈希：stdlib `hashlib.pbkdf2_hmac`（不引入新依赖），格式 `pbkdf2$<iter>$<salt_hex>$<hash_hex>`。
- 会话：DB 表 auth_token（存 token 哈希，不存明文），过期时间可配置，登出即删。
- 引导：`python -m app.create_user <username> <password> <role>` 建号；空库无用户时无法登录（不做默认弱口令）。

## 任务

### T1 用户与会话模型（S1+S2 后端基础）
- models.py：User（username 唯一/password_hash/role/created_at）、AuthToken（user_id/token_hash/expires_at）。
- app/auth.py：hash_password/verify_password、create_user、issue_token、resolve_token（过期/不存在→None）。
- 迁移：alembic 新 revision（user + auth_token 两表）。
- 测试（先红）：test_auth.py —— 哈希往返、错误密码拒绝、过期 token 拒绝、登出后 token 失效。

### T2 认证 API + 依赖注入
- app/api/auth.py：POST /auth/login（→token+user）、POST /auth/logout、GET /auth/me、POST /auth/users（仅 admin）。
- `require_user` / `require_role("admin")` FastAPI 依赖；main.py 对除 health/events 外全部 router 挂 `dependencies=[Depends(require_user)]`。
- conftest：client 夹具建 admin+token 并注入默认 Authorization 头（存量 279 测试零改动通过）。
- 测试：无 token 401、viewer 访问 admin 端点 403、登录/登出/me 全链。

### T3 评审绑定（S3）
- review 表加 user_id（nullable，迁移）；POST /reviews 从登录态取 reviewer（请求体不再收 reviewer 字段），viewer 403。
- 测试：登录评审落 user_id+username；viewer 403；存量评审行（user_id NULL）列表正常显示。

### T4 前端接入（S4）
- api.ts：统一带 Authorization 头；401 → 跳 /login。
- LoginView.vue + 路由守卫（无 token 一律去 /login）+ App 顶部当前用户/登出。
- 角色可见性：viewer 隐藏评审表单（后端已强制，前端仅 UX）。
- vitest：登录成功存 token、失败提示、守卫重定向、401 跳转。

### T5 收尾
- 全量三套测试 + 浏览器实测（登录/角色/评审全路径）+ 截图入库 demo/sprint21/ + 用户测试报告 + deploy/README 补建号说明 + 合并 main。

## 验收标准（对照主计划块 S）

- [ ] S1 user 表+迁移，三角色，admin 可建用户
- [ ] S2 登录/token 会话，API 默认认证，插件通道豁免
- [ ] S3 review 绑定真实用户，viewer 不能评审
- [ ] S4 登录页/守卫/角色可见性
- [ ] 存量 279 测试零改动全绿；新功能全配新用例
