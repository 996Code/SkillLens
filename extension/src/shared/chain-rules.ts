// AH2 链规则解释器（纯函数）：链=数据+规则的"规则"半边。
// 服务端只存不解释（降耦合）；执行期在插件侧把规则字符串解析成真实值。
// AI2：新增 ${stepN.字段} 跨步绑定——从上一步写请求证据提取真值注入本步。
export interface ChainStep {
  skill_id: number;
  overrides: Record<string, string>;
}

// 步骤执行产出：写请求证据（url/reqBody 已脱敏——提取的是"业务字段值"，
// 凭据类字段本就被掩码，不构成新的泄漏面）
export interface StepEvidence {
  url?: string;
  reqBody?: string;
  // AN 跨步状态传递：行点击选中的行标识（executor row-trigger 命中时
  // 捕获行首格文本——跨重渲稳定的行键）。选择类输出→输入的句柄。
  pickedRow?: string;
}

// 从单条写请求体提取字段值：支持 JSON（"key":"value"）与
// urlencoded（key=value&）两形态（net-hook redactReqBody 同源格式）
export function extractField(reqBody: string | undefined, key: string): string | null {
  if (!reqBody || !key) return null;
  // JSON 形态："key":"value" 或 "key": value（含嵌套）
  const jq = new RegExp(`"${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"\\s*:\\s*"([^"]*)"`);
  const jm = jq.exec(reqBody);
  if (jm) return jm[1];
  const jn = new RegExp(`"${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"\\s*:\\s*([0-9]+|true|false)`);
  const jnm = jn.exec(reqBody);
  if (jnm) return jnm[1];
  // urlencoded：key=value（& 或串尾截止）
  const uq = new RegExp(`(?:^|[&;])${key.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}=([^&;]*)`);
  const um = uq.exec(reqBody);
  if (um) return um[1];
  return null;
}

// 跨步取值：${stepN.字段} → 在第 N 步（1 起）的写请求证据里找该字段。
// 写请求=POST/PUT/PATCH 优先；多条命中取最后一条（终态语义）。
// AN：${stepN.row} 特殊键 → 第 N 步的 pickedRow（行选择句柄，多条取末条）。
export function extractStepValue(
  stepEvidences: StepEvidence[], ref: string,
): string | null {
  const m = /^\$\{step(\d+)\.([^}]+)\}$/.exec(ref);
  if (!m) return null;
  const n = Number(m[1]);
  const key = m[2].trim();
  if (n < 1 || n > stepEvidences.length) return null;
  const writes = (stepEvidences[n - 1] instanceof Array
    ? stepEvidences[n - 1] : [stepEvidences[n - 1]]) as StepEvidence[];
  if (key === "row") {
    for (let i = writes.length - 1; i >= 0; i--) {
      if (writes[i]?.pickedRow) return writes[i].pickedRow!;
    }
    return null;
  }
  if (key === "res_id") {
    // 重录批（goto 实例段通用化）：步末 GET URL 的末位数字段=新实体
    // id（创建流保存后页面跳 /hardware/{id}——响应 URL 已在
    // responseReceived 更新为重定向后最终 URL）
    for (let i = writes.length - 1; i >= 0; i--) {
      const w = writes[i];
      if (!w || (w.method || "GET").toUpperCase() !== "GET") continue;
      const m = String(w.url || "").match(/\/(\d+)(?:\/[^\/]*)?$/);
      if (m) {
        // 多数字段取末位数字（/hardware/45/edit → 45）：找路径里
        // 最后一个纯数字段
        const segs = String(w.url || "").split("?")[0].split("/")
          .filter(Boolean);
        for (let j = segs.length - 1; j >= 0; j--) {
          if (/^\d+$/.test(segs[j])) return segs[j];
        }
      }
    }
    return null;
  }
  for (let i = writes.length - 1; i >= 0; i--) {
    const v = extractField(writes[i]?.reqBody, key);
    if (v != null) return v;
  }
  return null;
}

// AN row_anchor_from 注入原料：第 fromStep 步（1 起）的 pickedRow。
// 越界/无句柄返回 null（调用方保留原锚——防静默错值同 resolveValue
// 纪律）。自引用天然防：执行到第 K 步时 stepCtx 只有 K-1 条。
export function resolveRowAnchor(
  fromStep: number, stepCtx?: StepEvidence[],
): string | null {
  if (!stepCtx || fromStep < 1 || fromStep > stepCtx.length) return null;
  const writes = (stepCtx[fromStep - 1] instanceof Array
    ? stepCtx[fromStep - 1] : [stepCtx[fromStep - 1]]) as StepEvidence[];
  for (let i = writes.length - 1; i >= 0; i--) {
    if (writes[i]?.pickedRow) return writes[i].pickedRow!;
  }
  return null;
}

// ${unique:前缀} → 前缀 + 时间戳 base36（每次执行唯一——JeecG 撞名根治）
// 未识别的 ${...} 保留原文（向后兼容）
export function resolveRule(value: string, now: number = Date.now()): string {
  const m = /^\$\{unique:([^}]*)\}$/.exec(value);
  if (m) return `${m[1]}${now.toString(36)}`;
  return value;
}

// 单值解析（含跨步绑定）：stepCtx 为前序步骤产出（可空=纯 unique 模式）
export function resolveValue(
  value: string,
  stepCtx?: StepEvidence[],
  now: number = Date.now(),
): string {
  const sm = /^\$\{step(\d+)\.([^}]+)\}$/.exec(value);
  if (sm && stepCtx) {
    const v = extractStepValue(stepCtx, value);
    if (v != null) return v;
    return value; // 绑定未命中保留原文（执行期日志可见——防静默错值）
  }
  return resolveRule(value, now);
}

export function resolveStepOverrides(
  step: ChainStep,
  stepCtx?: StepEvidence[],
  now: number = Date.now(),
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(step.overrides || {})) {
    out[k] = resolveValue(v, stepCtx, now);
  }
  return out;
}

// 整链解析：同一时刻生成的 unique 值共享同一时间戳；跨步绑定按执行
// 进度传 ctx（AI2：由 executor-page 在每步后 append 该步 observed）
export function resolveChainSteps(
  steps: ChainStep[],
  now: number = Date.now(),
): Array<{ skill_id: number; overrides: Record<string, string> }> {
  return steps.map((s) => ({ skill_id: s.skill_id, overrides: resolveStepOverrides(s, undefined, now) }));
}
