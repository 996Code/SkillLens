// MAIN world 网络观察脚本（fetch / XHR 包装）。
// 注意：CRXJS 对 web_accessible_resources 条目按原样复制（不做 TS→JS 转换），
// 因此本文件必须是纯 JavaScript（不可含 TS 注解），路径与 manifest/capture.ts 引用一致。
const MASK = "[REDACTED]";
const SENSITIVE = /password|passwd|secret|token|authorization|cookie/i;

function redact(obj) {
  if (Array.isArray(obj)) return obj.map(redact);
  if (obj && typeof obj === "object") {
    return Object.fromEntries(
      Object.entries(obj).map(([k, v]) => [k, SENSITIVE.test(k) ? MASK : redact(v)]),
    );
  }
  return obj;
}

// 响应体脱敏：字符串内容可解析为 JSON 时递归 redact，否则保持原文截断。
function redactBody(raw) {
  const text = String(raw ?? "");
  try {
    return JSON.stringify(redact(JSON.parse(text))).slice(0, 2000);
  } catch {
    return redactFormString(text).slice(0, 2000);
  }
}

// S42 安全红线：请求体字符串形态（JSON / urlencoded）必须脱敏——
// fetch(url, {body: JSON.stringify({password})}) 是最常见登录形态。
function redactReqBody(body) {
  if (body == null) return null;
  if (typeof body === "string") return redactBody(body);
  if (typeof FormData !== "undefined" && body instanceof FormData) {
    const entries = {};
    for (const [k, v] of body.entries()) entries[k] = typeof v === "string" ? v : "[FILE]";
    return JSON.stringify(redact(entries)).slice(0, 2000);
  }
  return redact(body);
}

// urlencoded 键值串脱敏（password=x&user=y 形态）。
function redactFormString(text) {
  return String(text).replace(
    /(^|[&;])([^=&;]+)=([^&;]*)/g,
    (m, p, k) => (SENSITIVE.test(k) ? `${p}${k}=${MASK}` : m),
  );
}

// S42 安全红线：URL query 中的凭据参数（?token=/api_key=）脱敏。
function redactUrl(u) {
  const s = String(u);
  try {
    const url = new URL(s, location.href);
    let changed = false;
    for (const [k] of url.searchParams) {
      if (SENSITIVE.test(k)) {
        url.searchParams.set(k, MASK);
        changed = true;
      }
    }
    return changed ? url.toString() : s;
  } catch {
    return redactFormString(s);
  }
}

function post(detail) {
  window.postMessage({ source: "skilllens-net", detail }, "*");
}

const origFetch = window.fetch;
window.fetch = async (...args) => {
  const started = performance.now();
  const resp = await origFetch(...args);
  try {
    const [input, init] = args;
    const url = typeof input === "string" ? input : input && input.url;
    const method = init?.method ?? "GET";
    const clone = resp.clone();
    const resBody = redactBody(await clone.text().catch(() => ""));
    post({
      method, url: redactUrl(url), status: resp.status, duration: Math.round(performance.now() - started),
      reqBody: redactReqBody(init?.body ?? null), resBody,
    });
  } catch { /* 观察失败不影响页面 */ }
  return resp;
};

const OrigOpen = XMLHttpRequest.prototype.open;
const OrigSend = XMLHttpRequest.prototype.send;
XMLHttpRequest.prototype.open = function (method, url, ...rest) {
  this._m = method; this._u = String(url);
  return OrigOpen.call(this, method, url, ...rest);
};
XMLHttpRequest.prototype.send = function (body) {
  this._t0 = performance.now();
  this.addEventListener("load", () => {
    // responseType 非 text 时访问 responseText 抛 InvalidStateError，须容错
    let resBody = "";
    try {
      resBody = redactBody(this.responseText);
    } catch { /* 保持空串 */ }
    post({
      method: this._m, url: redactUrl(this._u), status: this.status,
      duration: Math.round(performance.now() - (this._t0 ?? 0)),
      reqBody: redactReqBody(body), resBody,
    });
  });
  return OrigSend.call(this, body);
};
