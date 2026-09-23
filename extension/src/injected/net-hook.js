// MAIN world 网络观察脚本（fetch / XHR 包装）。
// 注意：CRXJS 对 web_accessible_resources 条目按原样复制（不做 TS→JS 转换），
// 因此本文件必须是纯 JavaScript（不可含 TS 注解），路径与 manifest/capture.ts 引用一致。
const MASK = "[REDACTED]";
const SENSITIVE = /password|passwd|secret|token|authorization|cookie/i;

function redact(obj) {
  if (obj && typeof obj === "object" && !Array.isArray(obj)) {
    return Object.fromEntries(
      Object.entries(obj).map(([k, v]) => [k, SENSITIVE.test(k) ? MASK : redact(v)]),
    );
  }
  return obj;
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
    const resBody = await clone.text().catch(() => "");
    post({
      method, url, status: resp.status, duration: Math.round(performance.now() - started),
      reqBody: redact(init?.body ?? null), resBody: resBody.slice(0, 2000),
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
    post({
      method: this._m, url: this._u, status: this.status,
      duration: Math.round(performance.now() - (this._t0 ?? 0)),
      reqBody: redact(body), resBody: String(this.responseText ?? "").slice(0, 2000),
    });
  });
  return OrigSend.call(this, body);
};
