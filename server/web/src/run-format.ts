// S34：执行 run 展示共享格式化（ReplayLaunch / ReplayRunView 两处同源）。
import type { AssertionResult, PageSnapshot, ReplayPlan } from "./api";

/** 断言明细的人读期望（AssertionResult 结果行 / AssertionRow 断言行通用）。
 * api_template 可选降级：缺失时不渲染括号后缀（评审：双源合并统一行为）。 */
export function assertExpect(
  r: { kind?: string; payload?: Record<string, unknown> | null },
): string {
  const p = r.payload || {};
  const tpl = p.api_template ? `（${p.api_template}）` : "";
  switch (r.kind) {
    case "api_status":
      return `${p.api_template} → ${p.expect_status}`;
    case "state_signal":
      return `${p.field}=${p.expect_value}${tpl}`;
    case "ui_text":
      return `${p.label}: ${p.before} → ${p.after}`;
    case "field_change":
      return `${p.field}: ${p.before} → ${p.after}${tpl}`;
    default:
      return JSON.stringify(p);
  }
}

export function assertObserved(r: AssertionResult): string {
  return r.observed_status == null ? "—" : String(r.observed_status);
}

/** 快照对比行：label + before → after，只保留有差异的行（前 10 行）。 */
export function snapshotDiffRows(plan: ReplayPlan | null): {
  label: string;
  from: string;
  to: string;
}[] {
  const before: { label: string; value: string }[] = plan?.before_snapshot?.forms ?? [];
  const after: { label: string; value: string }[] = plan?.after_snapshot?.forms ?? [];
  const afterByLabel = new Map(after.map((f) => [f.label, f.value]));
  return before
    .filter((f) => afterByLabel.get(f.label) !== f.value)
    .slice(0, 10)
    .map((f) => ({
      label: f.label,
      from: f.value,
      to: afterByLabel.get(f.label) ?? "（字段已消失）",
    }));
}

/** 步骤截图说明：start.png→起始页；step-NN→kind label（失败）。 */
export function shotCaption(
  file: string,
  executed: Record<string, unknown>[] | null,
): string {
  if (file === "start.png") return "起始页";
  const step = (executed || []).find((s) => s.screenshot === file);
  if (!step) return file;
  const label = String(step.label ?? step.name ?? "");
  return `${String(step.kind ?? "")} ${label}${step.ok ? "" : "（失败）"}`;
}

/** plan.step_screenshots 类型收窄。 */
export function stepScreenshotFiles(
  plan: ReplayPlan | null,
): { dir: string; files: string[] } | null {
  const meta = (plan as { step_screenshots?: { dir: string; files: string[] } } | null)
    ?.step_screenshots;
  return meta?.files?.length ? meta : null;
}

/** ISO 时间 → "YYYY-MM-DD HH:mm:ss"（毫秒/时区截断）。 */
export function fmtTime(ts: string | null | undefined): string {
  return ts ? ts.replace("T", " ").replace(/\.\d+.*$/, "") : "—";
}

/** AM3 期望三态呈现（docs/specs/2026-10-10-am-*.md AM3）：失败步的
 * 语义分类——定位失败（元素没找到）/ 效果未触发（点了但没生效——
 * AM1 写水位/登录守卫的形态）/ 步骤错误（其余）。词表与
 * server plain_errors._DETAIL_PATTERNS 同源锚（点击后无写请求等）。
 */
export function failureKind(step: { ok?: boolean; error?: string | null } | null | undefined):
  "" | "locate" | "effect" | "error" {
  if (!step || step.ok !== false) return "";
  const e = String(step.error || "");
  if (/semantic locate failed|定位失败|triggering|miss/i.test(e)) return "locate";
  if (/点击后无写请求|提交被拦|登录态丢失|目标站不可达/.test(e)) return "effect";
  return "error";
}

/** AM3 三态的人读标签 */
export const FAILURE_KIND_LABEL: Record<string, string> = {
  locate: "定位失败——元素未找到（页面改版或前置状态缺失）",
  effect: "效果未触发——操作成功但预期结果未发生（提交被拦/登录态丢失）",
  error: "步骤错误——执行中异常",
};
