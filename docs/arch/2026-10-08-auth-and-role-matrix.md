# 认证与角色矩阵（Auth & Role Matrix）

> 2026-10-08。viewer=只读契约的**代码级权威定义**：三层防线（router 级 `require_user` →
> 端点级 `WRITE_GUARD` → 点位级 `require_role`）+ 全量端点矩阵 + token 生命周期。
> 三轮评审 R3-1/R3-2 修复后首次做到"注释、测试、代码三方一致"。
> 直测：`server/tests/test_role_gates.py`、`test_auth_api.py`、`test_auth.py`。

## 1. 认证机制（`server/app/api/auth.py`）

| 机制 | 实现 | 出处 |
|---|---|---|
| 口令哈希 | PBKDF2-SHA256，**100k 轮**加盐 | auth.py `hash_password` |
| token 签发 | `secrets.token_urlsafe` 明文只在响应出现一次；库中只存 **SHA-256 哈希** | auth.py login |
| token 校验 | 哈希后查库 + `secrets.compare_digest` **恒定时间**比较 | auth.py `require_user` |
| 过期清理 | TTL 7 天；**命中过期即删行**（不待定时任务） | auth.py:62-64 |
| 吊销 | `POST /auth/logout` 删当前 token（只吊销所持，无全局撤销——单租户可接受，记录项） | — |
| 计时侧信道 | 未知用户也对固定 `_DUMMY_HASH` 跑一次完整 PBKDF2（100k 轮，数十毫秒量级），抹平"用户存在与否"的响应时差，堵用户名枚举 | auth.py:66（三轮 R3-A4） |
| 登录失败限速 | 无（记录项：单机本地工具，属部署侧反代职责） | — |
| 角色枚举 | `admin` / `reviewer` / `viewer`（建号：`POST /auth/users`，仅 admin） | models.User.role |

依赖注入链：`require_user`（验 token → 注入 `User`）→ `require_role(*roles)`（验角色 → 403
`requires role: (…)`）。**`WRITE_GUARD = [Depends(require_role("admin","reviewer"))]`
（auth.py:53-55）是 viewer=只读契约的唯一来源**——所有变更端点逐个声明
`dependencies=WRITE_GUARD`，不要另造局部副本（现存例外：adapters.py:31 的 `_WRITE_GUARD`
同义重复，属卫生债，收敛中）。

## 2. 豁免面（不挂 require_user，各有注释依据）

| 端点 | 依据 |
|---|---|
| `GET /health` | 探活 |
| `POST /auth/login` | 签发 token 本身 |
| `POST /auth/logout` | 无害：只吊销调用者自己所持 token |
| `POST /sessions`、`POST /sessions/{id}/events`（events 豁免组） | 插件采集通道拿不到用户 token，设计豁免；改验 **`X-SkillLens-Agent: 1`** 头 + 批量上限 2000 条（413）+ 逐条幂等落库。**威胁模型明示**：CORS 默认 `*` 下该头只是减速带（预检必过、可伪造），非边界；单机正确缓解 = 收紧 `ALLOWED_ORIGINS`，共享 secret 升级排私有化（三轮 A3） |

SPA 静态挂载在全部 router 之后（`main.py`），API 路由优先命中，无吞路由问题。

## 3. 全量端点矩阵（API_PREFIX=/api/v1）

记号：U=require_user（任意角色可读）；W=WRITE_GUARD（admin/reviewer）；R(x)=require_role。
**变更面 = W 或 R 的端点**。GET 类除特别说明外全部 U。

| 路由组 | 变更端点（W/R） | 只读端点（U） |
|---|---|---|
| auth | `POST /auth/users` **R(admin)** | GET /auth/me |
| adapters | `PUT /adapters/{id}` **W** | GET /adapters、GET /{id}/yaml（**凭据打码**）、POST /validate、POST /fingerprint、GET /match |
| canvas | POST /canvas、POST /{id}/run **W** | GET /canvas、/{id}、/{id}/flow、/runs/{rid}、/{id}/runs |
| cards | — | GET ×5（flow/state-machine/learning-graph/card/consistency） |
| change | POST /expected-deltas、/{id}/observe、/{id}/report **W**；POST /{id}/confirm **R(admin,reviewer)+落登录名** | GET /expected-deltas/{id} |
| dashboard | — | GET /dashboard |
| dev_plans | POST /dev-plans、/{id}/execute **W**；POST /{id}/confirm **R(admin,reviewer)+落登录名** | GET 列表/详情 |
| discoveries | — | GET /discoveries |
| executor | POST /skills/{id}/plan、/runs/{rid}/step、/runs/{rid}/finish **W** | GET /executor/skills（副作用：收割 stale run 改状态） |
| export | — | GET /skills/{id}/export/playwright、/flows/{id}/export/playwright |
| field_types | POST、PUT /{id}、DELETE /{id} **W** | GET /field-types |
| flows | POST /flows/generate、POST /{id}/execute **W** | GET 列表/详情 |
| generic_skills | POST induce、/{id}/promote、/{id}/map **W** | GET ×2 |
| impact | POST /impact/analyze **W** | GET /impact/last |
| ingest | POST /sessions/{sid}/process、POST /align **W** | GET semantic-actions、filtered-windows、alignments/{id} |
| llm_skills | POST field-changes、/alignments/{id}/induce、/skills/{id}/assertions、/assertions/{id}/verify **W** | GET ×3 |
| locate_proposals | POST /{id}/reject、/{id}/promote **R(reviewer,admin)** | GET /skills/{id}/locate-proposals |
| replay | POST /skills/{id}/replay、POST /skills/replay-batch **W** | GET /runs/{rid}、/flow、/step-screenshot（双白名单防穿越） |
| reports | — | GET /reports/{id}、/{id}/perf |
| reviews | POST /reviews **R(reviewer,admin)+落登录名** | GET /reviews、/reviews/pending |
| suites | POST /suites、DELETE /{id}、POST /{id}/run **W** | GET ×3 |
| timeline | — | GET /timeline |
| visual | POST /{id}/visual-baseline/reset **R(reviewer,admin)** | GET baseline、image（which 枚举白名单） |

要点：`POST /skills/{id}/replay`（`confirm_side_effect=true` 时对目标系统**真实写操作**）、
各 execute/run 类（触发浏览器自动化）、llm_skills 组（烧 LLM 配额）、DELETE 类全部在 W/R 后——
viewer 从"实际可调"收窄为"只读"（三轮 R3-1：此前 25 个变更端点只挂 U）。

## 4. C1 人工确认门（confirm 类端点）

`change.py:45-63`、`dev_plans.py:62-75`：`reviewed_by` **取登录态**（`user.username`），
请求体不再接受该字段——任何角色无法冒名确认（三轮 R3-2）。`reviews.py`、`locate_proposals.py`
本就正确。审计字段由此可抵赖性成立。

## 5. 已知边界与记录项

| 项 | 定性 | 时机 |
|---|---|---|
| 无所有权作用域（IDOR 面） | **设计边界**：单租户本地工具，资源按自增 id 直查，任何登录用户可读全部数据 | 多租户化前必须补 scoping（HANDOVER 已明示） |
| token 进 URL（executor.html?token=） | 已知递延：浏览器历史/Referer 泄漏面；已有 `replaceState` 补救 + 7 天 TTL + logout 吊销 | 私有化前改一次性 code 换票 |
| events 共享 secret、login 限速 | 见§2 与 env-contract §7 | 私有化 |
| web localStorage 存 token | 同源部署缓解，取舍在 UI 架构文档明示 | 同上 |
| SQL 注入面 | **干净**：全库无 `text()`/拼接 SQL；`order_by` 全静态列 | — |
| 文件端面 | adapter_id 白名单、截图双白名单、visual which 枚举、executor 截图名 int 派生——三轮复核无新穿越 | — |

## 6. 测试覆盖

- `test_role_gates.py`：viewer 对全部 W/R 变更端点 403、reviewer 200 的矩阵断言 + confirm 冒充用例
  （body 带 `reviewed_by:"admin"` 登录 viewer → 403；登录 reviewer → 落库 reviewer 用户名）。
- `test_auth_api.py`：建号 R(admin)、过期 token 401 即删、logout 吊销、login 计时抹平（本轮 +）。
- `test_auth.py`：哈希/校验/过期单元。
- **缺口**：API 级"过期 token 访问受保护端点 401 且 DB 行被清"（单元已有，端到端无）；
  W 覆盖是逐端点声明的——新增变更端点忘挂守卫不会被现有测试自动抓到（改进方向：按
  OpenAPI 规范自动断言"非 GET 端点必有角色依赖"）。
