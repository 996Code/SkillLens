# 全量审查+健壮性体检报告（2026-10-10，会话收官）

> 范围：bbb4279^..HEAD（本会话 26 提交，46 文件）+ 全库活体。
> 方法：三套测试全量 + 双 Agent 深审（安全红线/健壮性）+ 活体八项
> + 并发竞态实测。审查即修（🔴 全清零），🟡 按价值分流。

## 一、测试基线（全绿）

| 套 | 结果 |
|---|---|
| server | **720/720** |
| web | **81/81** |
| extension | **141/141** |

## 二、活体健壮性八项（8/8 过）

| 项 | 结果 |
|---|---|
| 不存在技能 plan | 404 快拒 |
| 畸形请求体 | 422 |
| 历史详情（含插件步合成） | 200 |
| 终态 run 重放 finish | 409 拒收 |
| 链字段往返（row_anchor_from） | 200 保真 |
| 全库 running 残留 | 0 |
| **并发 6 路 plan（同技能）** | **1×200+5×409**（守卫并发下有效） |
| 收割幂等 | ✓ |

## 三、审查发现与处置

### 🔴 安全红线（3 项，已全修——39f4044）

1. 测试/注释内嵌真实内网 IP（11 处：test_exec_failures/
   test_plan_url_doli/test_replay_batch_system/test_replay_failure/
   test_sanitize/plan.py）→ 全量替换 TEST-NET 保留段 192.0.2.99
   （语义不变，32 用例验证）。
2. evidence.error 内嵌原始 URL（目标站不可达/登录态丢失）→
   redactNetworkUrl 后组装。
3. sanitize 裸 IP:port 盲区 → _BARE_HOST_RE（IP[:port]/path+内网
   域名后缀）补脱，定向 5/5。

### 🟡 健壮性（3 项，留档排期——评级：中，无崩溃/挂死级）

1. **plan 409 守卫竞态**：check-then-insert 非原子——双客户端同 skill
   同时发起理论可双放行（实测 6 路并发未穿透——SQLite 串行写保护；
   竞态窗口毫秒级）。建议：事务内重查或唯一活跃约束（需迁移，独立批）。
2. **_reap_stale_runs 规模性能**：每次 plan 全表扫 running（status
   无索引）+逐行反序列化 MB 级 plan JSON。僵尸堆积时（118 条实证形态）
   每请求内存尖峰。建议：last_step_at 落列+索引（迁移批）。
3. **AM1 水位循环不查预算**：expect_write 步固定等 6s 不看
   runBudget——长计划可超支约 1 分钟。建议：循环内查 exhausted()
   （小改，下批顺手）。

### 🟡 脱敏深水（2 项，留档）

4. multipart/form-data 请求体：非 JSON 回退不识别 multipart 分节
   ——含密码字段整段截断入 reqBody。建议：multipart 整段丢弃或分节脱敏。
5. fill 步 value_after：label 命中敏感词表（密码型）时明文入
   received。建议：按词表判 label 后置 [REDACTED]。

### 🟢 建议级（3 项，已核实不紧急）

- get_run 合成对 executor_state 脏数据（非 dict）缺 isinstance 防御
- networkLog 重定向同 requestId 重复入列（水位虚高方向——重定向
  POST 少见；Map 索引化时一并做）
- conftest 残留 sl-test-*.db（SIGKILL 态）——pid 复用自愈，可加启动扫

### 无发现域

expectations/failures 纯函数、chain-rules 防御完备、网络监听 reqBody
主路径脱敏完整、running 守卫/收割/终态拒收逻辑正确、conftest test.db
机制（并发 worker 隔离验证）。

## 三.5 修复批次（edb439b，🟡 全清）

①AM1 水位循环查预算 ②value_after 敏感脱敏 ③multipart 整段掩码
④networkLog 重定向去重 ⑤plan 并发原子化（让位制）+get_run 脏数据防御。
剩余：仅 🟡②收割规模性能（last_step_at 落列+索引——需 DB 迁移，
当前残留恒 0 不紧迫，留独立迁移批）。基线 server 722 / ext 142。

## 四、健壮性评级

**中强**：四层异常防线（机制/语义/判定/呈现）全部真机验证；
🔴 清零后无已知安全缺口；🟡 集中在并发原子性与规模性能（SQLite
单机形态的固有限制，均有明确修法与排期）。
