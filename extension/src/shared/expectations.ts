// AM 块（期望-观测对比异常检测）：插件端步级期望判定纯函数。
// 设计：docs/specs/2026-10-10-am-expectation-anomaly-detection.md
// 业界依据：Frappe 官方 cypress 提交判定=等写请求（S43-4 实证）；
// 服务端 runner 写水位同语义（runner.py write_response_count）。
// 词表与服务端 failure_class._LOGIN_URL_RE 同源（双端一致性由
// login-guard 词表测试锁定，redact-parity 同模式）。

/** 写方法集合（与服务端 WRITE_METHODS 同语义） */
const WRITE_METHODS = new Set(["POST", "PUT", "PATCH"]);

/** networkLog 条目（executor.ts 采集形态的最小投影） */
export interface NetworkEntry {
  method?: string;
  status?: number;
}

/** 写响应计数（服务端 write_response_count 同语义：只认写响应——
 * GET 噪声不抬高水位，被前端校验拦下的提交才会暴露为无写请求） */
export function writeResponseCount(log: NetworkEntry[]): number {
  return log.filter((e) => WRITE_METHODS.has((e.method || "GET").toUpperCase())).length;
}

/** AM1 写效果判定：submit 类 click 后，写水位是否上涨。
 * mark=点击前的写响应计数；未上涨=静默失败（提交被拦截）。 */
export function writeEffectFired(log: NetworkEntry[], mark: number): boolean {
  return writeResponseCount(log) > mark;
}

/** AM2 登录页 URL 判定：goto 后落登录路径=登录态丢失（e1_env）。
 * 词表与服务端 _LOGIN_URL_RE 同源：
 * /login\b|/login\?|login\.php|/signin|[?&][a-z_]+=login\b */
const LOGIN_URL_RE =
  /\/login\b|\/login\?|login\.php|\/signin|[?&][a-z_]+=login\b/i;

export function isLoginUrl(url: string): boolean {
  return LOGIN_URL_RE.test(url || "");
}
