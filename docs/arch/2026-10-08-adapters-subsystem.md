# 适配器/清单子系统（Adapters & Manifest）：声明式系统接入架构

> 2026-10-08。代码位置：`server/app/adapters/`（manifest/urlmatch/fingerprint/
> probes/steps/flows/routines）+ `server/app/api/adapters.py` + `server/adapters/*.yaml`。
> 配套阅读：`docs/arch/2026-10-07-platform-interaction-profile.md`（P1-P4 四阶段
> 演进史与真机验证记录——本文不重复其阶段叙事，聚焦**机制解剖与安全边界**）；
> `docs/arch/extension-executor-protocol.md`（画像的插件端消费协议）。

## 1. 一句话职责

**把"接入一个目标业务系统"从写代码降为写一份 YAML**：登录编排、探针验证、
业务链、交互画像、URL 接管声明全部声明化，服务端各解释器（steps/probes/
urlmatch/fingerprint）机械消费。

对照旧世界：S43 时代 7 个系统各有一份手写编排脚本（`scripts/s43_*.py`），
每接一个系统改一次代码；8 份存量清单的头注释仍标明其出身——"从
s43_xxx.py 机械提取"（如 `server/adapters/ruoyi.yaml:1`、`odoo.yaml:1`）。
新世界终验：Firefly III 纯 YAML 接入，零代码改动（`server/adapters/firefly.yaml:1`、
平台化文档 §四）。设计三原则见 `manifest.py:1-10`：①例程库而非无限 DSL
（6 原语，怪癖=routine 按名引用）；②探针第一公民；③flows 可选
（缺省=登录引导+人工走查+探针验证）。

## 2. 清单文件解剖

### 2.1 字段总表（schema=`manifest.py` 的 pydantic 模型）

| 字段 | 类型 | 必填 | 语义 | 谁消费 |
|---|---|---|---|---|
| `id` | str | ✅ | 清单唯一 id，须与文件名/PUT 路径一致 | `adapters.py:94-95`（id≠path 拒 422）；urlmatch tie-break（`urlmatch.py:58`） |
| `label` | str | — | 展示名 | `adapters.py:43` |
| `target.base_url` | str | ✅ | 系统根 URL；goto 相对路径拼接基准 | `steps.py:36-37`、`probes.py:37`（`${base_url}` 插值） |
| `target.compose` | str? | — | compose 文件引用 | schema 声明（`manifest.py:31-33`），当前无运行时消费 |
| `credentials.username` | str | — | 登录用户名，`${username}` 插值源 | `probes.py:38` |
| `credentials.password_env` | str? | 二选一 | 环境变量**名**（生产形态）——值只在运行时 `os.environ` 取 | `probes.py:39-40`；与 literal 互斥校验 `manifest.py:41-47` |
| `credentials.password_literal` | str? | 二选一 | 明文口令，**仅限本地演示容器**，loader 必产 lint | `probes.py:41-42`；lint `manifest.py:239-242` |
| `login.steps` | Step[] | — | 登录步（六原语） | `steps.py:110`（login） |
| `login.post_login` | str[] | — | 登录后例程名（如 close_guide） | `steps.py:111-113` → `routines.py:9-13` |
| `login.success.url_not_contains` | str | 默认"login" | 登录成功判定①：URL 不含该串 | `steps.py:116-117` |
| `login.success.text_contains` | str? | — | 判定②：页面可见文本 | `steps.py:118-122` |
| `login.admin_nickname` | str? | — | 期望管理员昵称——已登录但身份不符时强制退出重登（矩阵轮间换参残留，若依 258 实证） | `steps.py:87-95`；schema 注释 `manifest.py:73-75`（曾 extra=ignore 静默丢弃致校验死代码） |
| `flows[].name/steps` | FlowDef | — | 走查流（录制素材） | `flows.py:10-16` → `scripts/af4_record.py:132` |
| `probes[].id/kind` | Probe | — | kind=`docker-exec|http`（pattern 封死，`manifest.py:98`） | `probes.py:114-117` |
| `probes[].container/shell` | str | docker-exec 必填 | 容器名+shell 命令（`${…}` 插值后 `docker exec`） | `probes.py:76-92`；形态校验 `manifest.py:107-113` |
| `probes[].request` | HttpRequest | http 必填 | method/url/json（`json` 为 alias，`manifest.py:86`） | `probes.py:95-111` |
| `probes[].assert` | status/contains | — | http 探针确定性断言；缺省=status<400 | `probes.py:104-111` |
| `probes[].parse_regex` | str? | — | 输出首捕获组抽取 | `probes.py:120-124`（**无生产调用方**，见 §11） |
| `chains[].name/rounds/skills` | Chain | — | 业务链声明（rounds=换参轮数） | `skills` 字段当前仅 `adapters.py:48` 计数展示 |
| `chains[].replay[]` | skill/overrides/verify | — | 回放+探针验证条目；`${ts}` 每轮注入 | `scripts/af5_chain.py:51-86` |
| `interaction_profile` | 五维画像 | — | dropdown/modal_submit/form_fill/row_action/route_guard，执行器特化分支的声明式载体 | `executor.py:257-262` 随 plan 下发；模型 `manifest.py:143-186`（详见平台化文档 §一） |
| `url_matches` | str[] | — | 油猴 @match 式 URL 接管声明；无声明=不参与配对 | `urlmatch.py:50-62`；消费点见 §4 |

Step 微形态：YAML `- goto: /x`、`- fill: ["sel","val"]`、`- routine: name` →
`_steps_from_raw` 归一为 `Step(op,arg,arg2)`（`manifest.py:205-220`）；op 白名单
= 六原语 `PRIMITIVES`（`manifest.py:18`），越界拒收（`manifest.py:55-59`）。

### 2.2 范例（ruoyi.yaml 骨架，口令一律占位符）

```yaml
id: ruoyi
label: 若依 RuoYi-Vue3
target: {base_url: "http://127.0.0.1:8093"}
credentials:
  username: admin
  password_literal: "<REDACTED>"        # 本地演示容器（lint 警告属预期）
login:
  steps:
    - goto: /
    - fill: ["[placeholder=账号]", "${username}"]
    - fill: ["[placeholder=密码]", "${password}"]
    - click: "button:has-text(\"登\")"
  post_login: [confirm_el_box]           # 例程按名引用（routines.py）
  success: {url_not_contains: login, text_contains: 首页}
probes:
  - id: role_count
    kind: docker-exec
    container: ruoyi-mysql               # 容器名过 _CONTAINER_PATTERN 白名单
    shell: 'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -e "SELECT COUNT(*) …"'
chains:
  - name: perm-chain
    rounds: 2
    skills: [RuoYiRoleCreate, RuoYiUserCreate, RuoYiLoginVerify]
    replay:
      - skill: RuoYiRoleCreate
        overrides: {"请输入角色名称": "SL回放${ts}"}
        verify: {probe: role_count, expect: increased}
url_matches: ["http://127.0.0.1:8093/*"]
interaction_profile: {…}                 # 五维画像，见平台化文档
flows:
  - name: dept-chain
    steps:
      - goto: /system/dept
      - click: "button:has-text(\"新增\")"
      - fill: ["input[placeholder=请输入部门名称]", "SL部门${data}"]
```

仓内现存 **8 份**清单：odoo/dolibarr/erpnext/snipe/zentao/ruoyi/jeecg/firefly
（验收测试枚举 `test_adapter_manifest.py:128-130`）+ 辅助脚本
`server/adapters/scripts/zentao_db.sh`。njmind 清单**不随仓发布**（内网地址
红线），但 `system.py:39-48` 的 `SYSTEM_ADAPTER` 保留 `"njmind 内网"→njmind`
映射，本地放置 njmind.yaml 即被目录扫描自动拾取。

## 3. 加载与容错

- **目录扫描**：`load_adapter_dir`（`manifest.py:344-359`）按文件名序 glob
  `*.yaml` 逐份 `load_manifest_text`。
- **单文件降级**：任一份解析/校验抛异常 → 记 `parse_error` lint 条目（异常摘要
  截 200 字符）并 `continue`，健康清单照常返回。根因：评审三轮 #6——一份坏
  YAML 曾令 `/adapters` 全线 500（`manifest.py:345-346`）。
- **loader 级 lint（绝不静默）**：`password_literal` 出现必警（`manifest.py:239-242`）；
  `url_matches` 含 `?` 必警——匹配引擎剥 query，此类模式永不命中（评审 #5b，
  `manifest.py:245-250`）。
- **容器 id 白名单**：`_CONTAINER_PATTERN = ^[A-Za-z0-9][A-Za-z0-9_.-]*$`
  （`manifest.py:22`）挂在 Probe.container 的 pydantic pattern（`manifest.py:99`）。
  为什么：container 名直入 `docker exec` argv——`-`/`.` 开头会被 docker 解析为
  选项（`--user=0` → root 进容器），而清单是 reviewer 可写盘的输入，等于
  参数注入面。schema 层之外还有**运行时复验** `_check_container`
  （`probes.py:24-30`），防程序化 `model_construct` 绕过 schema。

## 4. URL 通配符匹配（urlmatch.py）

油猴 @match 语义，编译规则：

| 规则 | 实现 | 依据 |
|---|---|---|
| host 段 `*` → `[^./]*`（至多一个 label） | `_compile_segment(host=True)`（`urlmatch.py:24-26`） | 评审 #5a：`.*` 曾让 `http://evil.com/.example.com/x` 伪装命中 `http://*.example.com/*` |
| 路径段 `*` → `.*`（跨 `/`） | 同上 host=False 分支 | 油猴同语义；测试 `test_url_match.py:75` |
| query 剥离后比对 | `url_pattern_match` 重组 scheme://netloc/path（`urlmatch.py:42-43`） | 评审 #5b；含 `?` 的模式永不命中 → loader lint（§3） |
| 模式无路径尾（`http://host`）→ target 去尾 `/` 再比 | `urlmatch.py:44-46` | 站点根匹配 |
| specificity = 模式去 `*` 后长度，降序；同分按 manifest id 升序 | `match_adapter` key=`(-len, id)`（`urlmatch.py:58`） | 评审 #5c：确定性收敛，不依赖文件迭代序 |

无 `url_matches` 声明的清单不参与匹配（显式声明制，`urlmatch.py:52-56`）。

**消费点三处**：
1. **执行侧自动配对**：`POST /executor/skills/{id}/plan` 取首条 goto URL →
   `match_adapter` 命中清单 → 其 `interaction_profile` 随 plan 下发并落
   `run.plan`（`executor.py:239-267`）；未命中回退 `SYSTEM_ADAPTER`
   系统名映射（`executor.py:253-256`、`system.py:39-48`）。
2. **采集侧自动隔离**：插件 popup 开录 → `GET /adapters/match?url=` →
   命中即以该系统建会话，未命中/超时回退默认（`extension/src/background/session.ts:15-45`）。
   **该端点在 require_user 守卫后**（`main.py:123` `_GUARDED`）——插件必须带
   Bearer，否则 401 静默回退（评审实锤根因，`session.ts:27-29`）。
3. **工作台/调试**：`adapters.py:120-129` 直接返回 `{adapter_id, label}`。

## 5. 探针运行时（probes.py）

- **docker-exec**：`docker exec <container> sh -c <shell>` 子进程
  （`probes.py:81-85`），Windows 要点两处：`MSYS_NO_PATHCONV=1` 防 Git Bash
  路径转换、`encoding="utf-8", errors="replace"`（lesson #28，`probes.py:80-84`）。
  stdout 按行/制表符切为元组行（`probes.py:91-92`）——`compare_expect`
  的 `increased` 语义读 `v[0][0]`（`probes.py:139-143`）。
- **辅助脚本注入**：复杂 shell 不塞清单（设计原则①的 escape hatch）——
  `server/adapters/scripts/*.sh` 每次探针前幂等 `docker cp` 进容器
  `/opt/skilllens/`（`probes.py:62-73`）；禅道 DB 密码抽取即此形态
  （`zentao.yaml:17-19` 注释：密码不落清单/日志）。
- **rc≠0 必抛**：`_run_docker` 与 `_exec_docker` 非零返回码一律 RuntimeError，
  stderr 摘要先过 `sanitize_error` 脱敏再截 200 字符（`probes.py:49-59, 86-90`）。
  根因：评审 #3——曾只读 stdout，容器名错/脚本缺/SQL 报错全被吞成
  "空输出=通过"。命令回显只带前 3 个 argv（`probes.py:58`），不落完整 shell。
- **http 探针**：httpx 请求 + 确定性断言（status/contains），无 assert 时
  status<400 即真（`probes.py:95-111`）。
- **`compare_expect` 空观测语义**（`probes.py:127-152`）：`equals` 下
  None/空串/空行集 = "命令无产出"（死探针信号）→ 直接 False，**不得**判
  "状态一致"（`[] == []` 曾让死探针静默通过）；`bool False` 是 http 探针
  合法观测值，不算空（`probes.py:128-129`）。`increased` 空观测经 int 转换
  失败取 -1，天然不满足 `>`。
- **插值**：`${base_url}/${username}/${password}/${env:VAR}`
  （`probes.py:33-46`）；password 值只在运行时从 `os.environ[password_env]`
  取——清单存变量名不存值（生产形态红线，`probes.py:8-9`）。

## 6. 步骤解释器与链编排（steps/flows/routines/af5_chain）

**六原语 → Playwright 动作**（`steps.py:33-66`）：

| op | 语义 | 实测参数 |
|---|---|---|
| goto | 相对路径拼 base_url；`wait_until=domcontentloaded` | +2000ms（`steps.py:38-39`） |
| fill | `_locate_any_frame` 定位（主 frame 优先，miss 逐子 frame——禅道 iframe 架构泛化，`steps.py:19-30`）；值经 interpolate | +300ms |
| click | 同上定位 | +**2500ms**——800ms 时禅道 CaseRun 实测锚点窗口 api_count=0 被 read_only 滤除（`steps.py:52-54`） |
| select | `select_option(arg2)` | — |
| wait | `int(arg)` **毫秒** | `steps.py:61` |
| routine | 例程库按名调用（`routines.py:82-88`：close_guide/confirm_el_box/biz_frame_submit/select2_pick/el_select_pick） | 未知例程抛错（`routines.py:11-12`） |

**login（幂等）**（`steps.py:74-123`）：访问 base_url 不落 login 路径 → 已登录
直通；但**身份校验**先行——声明 `admin_nickname` 时昵称不符 → `_force_logout`
（清 cookie/storage 直达登录页，UI 退出链 el-dropdown hover 时序不稳，
`steps.py:135-150`）；未声明时走通用检测 `_looks_like_swapped_user`：
正则 `^(?:[ES][L0-9]|M[A-Z])`（`steps.py:126-132`）识别换参产物昵称
（v21_matrix `E{rnd}{ts}`、`M{A|B|C}{ts}x{n}`、zentao `SL回放${ts}`）——
旧正则 `^[ES][L0-9]` 漏 M 形态，"注释对、正则错"，评审 #4 收口。

**flows**：`build_flow_script` 纯展开为 `[{flow, steps}]`（`flows.py:10-16`），
真机消费在 `scripts/af4_record.py`（录制走查：登录 → 插件 START_RECORDING →
run_steps（`${data}` 按轮次注入甲/乙，`af4_record.py:78-81`）→ STOP → 学习管道）。

**chains**：编排在 `scripts/af5_chain.py`（清单 chains 驱动 replay→verify）：
skill 引用数字串直引（LLM 命名不稳定，id 最稳——`af5_chain.py:38-48`、
`jeecg.yaml:29-30`）；overrides `${ts}` 每链一轮注入（`af5_chain.py:62-63`）；
verify 探针 before/after + `compare_expect`，after 带 2s×5 重试窗口（实体落库
异步延迟——JeecG addAll 200 后台 sync 建表，`af5_chain.py:73-83`）。

## 7. 指纹与画像自动生成（fingerprint.py）

输入：页面 HTML 片段 + URL（`POST /adapters/fingerprint`，body `{dom, url}`，
`adapters.py:100-117`）。两级纯函数：

1. `fingerprint_page`（`fingerprint.py:23-38`）：DOM 正则 →
   `{ui_library: ant-design|element-plus|generic, framework: frappe|generic,
   has_table_rows, has_name_inputs}`。铁证指纹：`ant-(modal|btn|dropdown|form|table)`
   类名、`data-fieldname`/`data-label=` → frappe。
2. `detect_profile`（`fingerprint.py:41-102`）：指纹 → `InteractionProfile`
   草稿。每条规则源自 7 系统实战（ant-design → `menu_item_match=includes`
   图标文本混入 JeecG 270 铁证、`pick=last_visible` footer 隐藏副本；
   frappe → `async_set_route/normalize_new_suffix=true`）。

输出 `{fingerprint, profile_yaml}`——profile_yaml 即可贴进清单的
`interaction_profile:` 片段。工作台位置：AdaptersView 页内"交互画像指纹识别"
面板（`AdaptersView.vue:39-52`，路由 `/graph/adapters`，`router.ts:42`），
贴 HTML → 出草稿 → 贴进上方编辑器 → 校验 → 保存。

## 8. 凭据与脱敏（重点）

**现实约束**：演示容器口令必须能被录制/回放/探针运行时取到，仓内 8 份清单
全部内嵌 `password_literal`（lint 常亮属预期，如 `ruoyi.yaml:8` 注释）；生产
形态是 `password_env`（值只存 env，清单存变量名）。由此产生完整的
**脱敏-回填闭环**：

```
磁盘原文 ──GET /adapters/{id}/yaml──▶ redact_manifest_text ──▶ 编辑器（秘密=***）
   ▲                                                              │ 用户改 label 等
   └──PUT：restore_masked_secrets(new, old) 回填掩码键 ◀───────────┘
```

- **GET 回显打码**：`redact_manifest_text`（`manifest.py:285-302`）——
  敏感键正则 `password|secret|token|api_?key|credential`（`manifest.py:256`），
  **`*_env` 结尾豁免**（存的是变量名引用非值，掩掉会毁排障信息，
  `manifest.py:259-261`）；敏感键持容器（credentials 块）时递归逐键裁决，
  不整块掩掉（块内 username/password_env 非秘密，`manifest.py:268-270`）；
  解析成功走 `safe_dump` 重序列化，**解析失败降级行级正则掩码**
  `_LINE_MASK_RE`（`manifest.py:280-302`）——任何路径绝不原文返回秘密值。
  viewer 也不得见（评审 #1，`adapters.py:73-75`）。
- **PUT 掩码回填 `restore_masked_secrets`**（`manifest.py:318-341`）：
  **为什么必须回填**——GET 回显是脱敏文本，编辑器原样 PUT 会把字面 `***`
  写进磁盘清单，"改个 label 顺手销毁演示容器口令，登录静默失败且无从排查"
  （`manifest.py:321-324`）。机制：`MASK_VALUE="***"` 哨兵（`manifest.py:306`）；
  从磁盘旧文本按 `_SECRET_VALUE_RE` 收集敏感键旧值（含原引号形态，回填后
  YAML 语义不变，`manifest.py:313-315`），新文本里**仍是掩码**的敏感键按
  出现序配对回填（`_MASKED_SECRET_RE` 覆盖块式与内联 flow 两种形态，
  `manifest.py:309-311`）；**用户显式改写过的值以新值为准**（只回填掩码键）；
  无旧值可回填时保持掩码原样（`manifest.py:337-338`）。**行级替换而非重
  序列化**——保留用户注释（`manifest.py:324-325`）。保存链：先读旧文本 →
  回填 → 校验（422）→ id 与路径一致性（422）→ `write_text(newline="\n")`
  （`adapters.py:82-97`）。
- **前端串档守卫**：`yamlFor` 记录当前编辑文本对应的 adapter id，加载失败/
  未加载时保存按钮禁用——防 A 的 YAML 被 PUT 到 B 上静默毁配置
  （`AdaptersView.vue:71-74, 146-147`）；晚到响应若已切换清单则丢弃
  （`AdaptersView.vue:120`）。
- **路径穿越防护 `_check_adapter_id`**：adapter_id 直接拼文件路径
  （`ADAPTERS_DIR / f"{adapter_id}.yaml"`），白名单 `[A-Za-z0-9_-]+` 全匹配
  拒 `..`/盘符——否则 GET 可任意读盘、PUT 可任意写盘（`adapters.py:22-27`）。
- **容器 id 白名单**：见 §3（docker argv 注入面，schema+运行时双层）。

## 9. API 与角色矩阵

全部端点挂 `_GUARDED = [Depends(require_user)]`（`main.py:123, 102`）——
未认证 401。写盘端点另挂 `_WRITE_GUARD = require_role("admin","reviewer")`
（`adapters.py:30-31`——写盘探针可触发 docker-exec，viewer 只读）。

| 端点 | 方法 | viewer | reviewer/admin | 说明 |
|---|---|---|---|---|
| `/adapters` | GET | ✅ | ✅ | 摘要列表+lint（`adapters.py:34-51`） |
| `/adapters/validate` | POST | ✅ | ✅ | 校验不落盘，向导实时反馈（`adapters.py:58-64`） |
| `/adapters/{id}/yaml` | GET | ✅ | ✅ | **脱敏回显**（`adapters.py:67-75`） |
| `/adapters/{id}` | PUT | ❌403 | ✅ | 回填+校验+写盘（`adapters.py:82-97`） |
| `/adapters/fingerprint` | POST | ✅ | ✅ | 只算不写（`adapters.py:107-117`） |
| `/adapters/match` | GET | ✅ | ✅ | 插件侧须带 Bearer（§4 消费点 2） |

角色语义单一来源：`WRITE_GUARD` 注释——viewer=只读契约（`api/auth.py:53-55`）。

## 10. 接入一个新系统（照代码写）

1. **起演示容器**（docker compose），确认宿主可达 base_url。
2. **画像草稿**：工作台 `/graph/adapters` 页"交互画像指纹识别"面板贴一段
   系统页面 HTML → `POST /adapters/fingerprint` → 得 `profile_yaml`（§7）。
3. **写清单**：新建 `server/adapters/<id>.yaml`（或先在工作台编辑器写）：
   `id/label/target.base_url/credentials`（演示容器可 `password_literal`，
   lint 属预期）+ `login.steps`（六原语；`${username}/${password}` 插值）+
   `login.success` + `url_matches: ["http://<host>:<port>/*"]` + 步骤 2 的
   `interaction_profile`。参照 `firefly.yaml`（最精简 P4 终验形态）。
4. **校验**：编辑器"校验"钮 → `POST /adapters/validate`（不落盘）；有
   `url_match_query`/`password_literal` lint 按提示处置。
5. **保存**：admin/reviewer 账号"保存" → `PUT /adapters/{id}`（id 须与路径
   一致，`adapters.py:94-95`）。落盘即被 `load_adapter_dir` 拾取——URL 自动
   配对（§4）立即生效，插件在该系统页面开录即自动隔离建会话。
6. **（可选）探针**：声明 `probes`——docker-exec 探针给 container（白名单
   字符）+shell；复杂/含密 shell 放 `server/adapters/scripts/*.sh`（自动注入
   容器 `/opt/skilllens/`，§5）。验证：`uv run python -c "…run_probe…"` 或
   直接走步骤 7 的链验证。
7. **（可选）flows/chains**：`flows` 供 `af4_record.py` 走查录制（`${data}`
   轮次注入）；`chains.replay` 供 `af5_chain.py <id>` 回放+探针验证
   （`expect: increased/equals`）。技能引用推荐数字 id 直引（§6）。
8. **（可选）兜底映射**：若该系统会出现在历史会话分组/未声明 url_matches 的
   场景，在 `system.py` 的 `HOST_SYSTEM`+`SYSTEM_ADAPTER` 同步加条目
   （两表同源维护防漂移，`system.py:37-38`）——这是唯一需要改代码的环节，
   纯回放/录制路径不需要（Firefly P4 即零代码）。

## 11. 已知债务与缓修项（代码确证）

| 债务 | 证据 | 缓修理由/去向 |
|---|---|---|
| 口令 env 注入改造（清单只存变量名） | 仓内 8 份全部 `password_literal`，lint 常亮（`manifest.py:239-242`） | 仅限本地演示容器；生产/私有化部署切 `password_env`（schema 已支持互斥校验） |
| `parse_regex`/`parse_probe_output` 无生产调用方 | 声明 `manifest.py:102`、实现 `probes.py:120-124`、`erpnext.yaml:21` 在用，但链验证路径直接消费原始元组行（`af5_chain.py:66-83`），全仓无调用 | 预留语义未接线 |
| `ReplayItem` 死模型 | `manifest.py:116-122` 定义，Chain 实际用 `ReplayWithVerify`（`manifest.py:130-140`），无引用 | 待清理 |
| `parse_error` lint 不出 API | `load_adapter_dir` 收集（`manifest.py:352-355`），但 `list_adapters` 只按**成功加载的 manifest** 关联 lint（`adapters.py:41-50`）——坏文件在 GET /adapters 里静默消失 | 观测缺口；文件仍在磁盘，工作台不可见 |
| lint 关联假设文件名=id.yaml | `adapters.py:49` `lint_map.get(f"{m.id}.yaml")`——文件名≠id 时 lint 丢失 | 命名纪律兜底 |
| 通用身份校验选择器 `.user-nickname` 硬编码 | `steps.py:88-91, 99-102`——若依 DOM 类名，其他系统 evaluate 得空串即 no-op | 待画像化（进 interaction_profile） |
| `_recheck_or_login` 不校验 `text_contains` | `steps.py:169-172` 只查 url_not_contains，login 主路径查双条件（`steps.py:116-122`） | 复核路径从简 |
| `select2_pick`/`el_select_pick` 的 `selector_arg` 不可达 | 例程签名收参（`routines.py:59, 72`），但 routine 原语只传名（`steps.py:62-64`、`routines.py:9-13`） | 注释自认"AF4 传参形态扩展" |
| ruoyi `login_ok` 探针 `${new_user}/${new_pass}` 无插值通道 | `ruoyi.yaml:29-34`；`interpolate` 只认 base_url/username/password/env:VAR（`probes.py:33-46`）——占位符原样发出 | 该探针未被 chains.replay 引用，暂哑 |

## 12. 测试覆盖地图

| 文件 | 覆盖 |
|---|---|
| `server/tests/test_adapter_manifest.py` | schema 校验/互斥凭据/原语白名单/lint（password_literal、url_match_query）/目录容错（坏文件存活）/仓内 8 清单全量验收（`test_repo_seven_system_adapters_validate`，名"seven"实为 8）/容器注入拒绝/画像 roundtrip+默认值/`TestRedactManifestText` 5 例（掩码、env 豁免、嵌套、不可解析降级、非敏感不动） |
| `server/tests/test_adapter_probes.py` | interpolate/docker-exec/http 探针（monkeypatch 子进程）/parse_regex 抽取/compare_expect（含空观测=False）/rc≠0 抛错/辅助脚本注入失败抛错/容器守卫拒选项形态名 |
| `server/tests/test_adapter_steps.py` | fill 插值/登录成败判定/例程注册表+未知例程/`_looks_like_swapped_user` 形态矩阵/admin_nickname 不符强制重登 |
| `server/tests/test_adapters_api.py` | 列表/validate 好坏/PUT 保存与拒绝/**GET 脱敏**/**PUT 掩码回填 round-trip**/显式改写覆盖掩码/路径穿越 422/写角色 403 |
| `server/tests/test_url_match.py` | 端口精确/通配 host/specificity 择最specific/无声明排除/**host 通配不跨界欺骗**/路径通配跨 `/`/query 模式永不命中但 lint/同分按 id/**match API 鉴权** |
| `server/tests/test_adapter_fingerprint.py` | ant/element/frappe/generic 四路识别 + fingerprint API |
| `server/tests/test_adapter_flows.py` | build_flow_script 展开/空 flows |
| `server/web/tests/AdaptersView.spec.ts` | 编辑器数据破坏守卫 3 例：加载成功可保存/加载失败清文本+禁保存+不发 PUT/保存网络错可恢复 |
