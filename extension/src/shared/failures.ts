// AK6 批次1（复盘缺口④）：插件侧四码失败分类——与 server app/exec/failures.py
// 同词表（单一事实源纪律：改动须双端同步，redact-parity 同模式）。
// 用途：api() 超时 / attach 冲突等裸 throw 改走结构化分类——retryable 是
// 分类输出而非事后猜（zcode failure-classifier 模式）；SW 重启重复消费
// 旧请求时，复活请求的错误也能被正确归类而非全新建 run。
export type ExecCode = "cancelled" | "timeout" | "transient" | "fatal";

const CANCEL_PAT = /AbortError|aborted|用户停止|已请求停止|shouldStop|中断/i;
const TIMEOUT_PAT = /TimeoutError|超时|api timeout|预算耗尽|budget exhausted/i;
const TRANSIENT_PAT =
  /Execution context was destroyed|Frame (has been |was )?detached|Cannot find context with specified id|Target closed|Session with given ID not found|Connection reset by peer|WebSocket is already closed|net::ERR_CONNECTION_RESET/i;

export function isTransient(message: string): boolean {
  return TRANSIENT_PAT.test(message || "");
}

export function classifyErr(err: unknown): ExecCode {
  const msg = err instanceof Error ? `${err.message}` : String(err ?? "");
  const name = err instanceof Error ? err.constructor.name : "";
  if (name === "AbortError" || CANCEL_PAT.test(msg)) return "cancelled";
  if (name === "TimeoutError" || TIMEOUT_PAT.test(msg)) {
    return isTransient(msg) ? "transient" : "timeout";
  }
  if (isTransient(msg)) return "transient";
  return "fatal";
}

/** attach 冲突形态（131 run/13s + 620 run 风暴实证）：fatal 不重试——
 * 原样重试无意义（DevTools 占用不会自己消失），白话直达用户。 */
export function isAttachConflict(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err ?? "");
  return /Another debugger is already attached|Debugger is not attached/i.test(msg);
}

export interface ExecFailure {
  code: ExecCode;
  retryable: boolean;
  plain: string;
}

const PLAIN: Record<ExecCode, string> = {
  cancelled: "已停止（用户中断）",
  timeout: "步骤超时——页面加载慢或元素未出现",
  transient: "页面瞬断（已自动恢复重试）",
  fatal: "执行失败",
};

export function describeFailure(err: unknown): ExecFailure {
  const code = classifyErr(err);
  const retryable = code === "transient";
  let plain = PLAIN[code];
  if (isAttachConflict(err)) {
    plain = "浏览器调试口被占用（如开着 DevTools）——关闭后重试";
  }
  return { code, retryable, plain };
}
