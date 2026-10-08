// AH2 链规则解释器（纯函数）：链=数据+规则的"规则"半边。
// 服务端只存不解释（降耦合）；执行期在插件侧把规则字符串解析成真实值。
export interface ChainStep {
  skill_id: number;
  overrides: Record<string, string>;
}

// ${unique:前缀} → 前缀 + 时间戳 base36（每次执行唯一——JeecG 撞名根治）
// 未识别的 ${...} 保留原文（P2 的 ${stepN.变量} 绑定落地前不误伤）
export function resolveRule(value: string, now: number = Date.now()): string {
  const m = /^\$\{unique:([^}]*)\}$/.exec(value);
  if (!m) return value;
  return `${m[1]}${now.toString(36)}`;
}

export function resolveStepOverrides(
  step: ChainStep,
  now: number = Date.now(),
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(step.overrides || {})) {
    out[k] = resolveRule(v, now);
  }
  return out;
}

// 整链解析：同一时刻生成的 unique 值共享同一时间戳（同轮执行内可对账，
// 跨轮必不同）
export function resolveChainSteps(
  steps: ChainStep[],
  now: number = Date.now(),
): Array<{ skill_id: number; overrides: Record<string, string> }> {
  return steps.map((s) => ({ skill_id: s.skill_id, overrides: resolveStepOverrides(s, now) }));
}
