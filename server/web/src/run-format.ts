// S34：回放 run 展示共享格式化（ReplayLaunch / ReplayRunView 两处同源）。
import type { AssertionResult, PageSnapshot, ReplayPlan } from "./api";

/** 断言明细的人读期望。 */
export function assertExpect(r: AssertionResult): string {
  const p = r.payload || {};
  switch (r.kind) {
    case "api_status":
      return `${p.api_template} → ${p.expect_status}`;
    case "state_signal":
      return `${p.field}=${p.expect_value}（${p.api_template}）`;
    case "ui_text":
      return `${p.label}: ${p.before} → ${p.after}`;
    case "field_change":
      return `${p.field}: ${p.before} → ${p.after}`;
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
