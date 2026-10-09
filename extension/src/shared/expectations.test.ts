import { describe, expect, it } from "vitest";
import { isLoginUrl, writeEffectFired, writeResponseCount } from "./expectations";

// AM 块：期望-观测对比纯函数（设计 docs/specs/2026-10-10-am-*.md §三）
describe("writeResponseCount / writeEffectFired（AM1 写效果水位）", () => {
  it("只认写响应——GET 噪声不抬高水位（服务端 write_response_count 同语义）", () => {
    const log = [
      { method: "GET", status: 200 },
      { method: "GET", status: 200 },
      { method: "GET", status: 304 },
    ];
    expect(writeResponseCount(log)).toBe(0);
    expect(writeEffectFired(log, 0)).toBe(false);
  });

  it("POST/PUT/PATCH 响应抬高水位——效果触发", () => {
    const log = [
      { method: "GET", status: 200 },
      { method: "POST", status: 200 },
      { method: "PATCH", status: 200 },
    ];
    expect(writeResponseCount(log)).toBe(2);
    expect(writeEffectFired(log, 0)).toBe(true);
  });

  it("点击前已有写响应（mark>0）时：无新写=静默失败（提交被拦截）", () => {
    const log = [{ method: "POST", status: 200 }];
    expect(writeEffectFired(log, 1)).toBe(false);
  });

  it("method 缺省按 GET——不误报", () => {
    expect(writeResponseCount([{}, { status: 500 }])).toBe(0);
  });

  it("小写 method 归一（networkLog 形态防御）", () => {
    expect(writeResponseCount([{ method: "post" }])).toBe(1);
  });
});

describe("isLoginUrl（AM2 登录守卫）", () => {
  it("run 2817 实证形态：JeecG 登录重定向", () => {
    expect(isLoginUrl("http://127.0.0.1:8095/login?redirect=/system/user")).toBe(true);
    expect(isLoginUrl("http://127.0.0.1:8095/login?redirect=/system/dict")).toBe(true);
  });

  it("各系统登录路径（词表与服务端 _LOGIN_URL_RE 同源）", () => {
    for (const u of [
      "http://t/user/login",
      "http://t/login.php",
      "http://t/index.php?m=user&f=login",
      "http://t/signin",
      "http://t/api/sign-in", // 不匹配——连字符形态不在词表（同服务端语义）
    ]) {
      // 与服务端正则行为一致：/signin 匹配，sign-in 不匹配
      expect(isLoginUrl(u)).toBe(!u.includes("sign-in"));
    }
  });

  it("业务页不误判", () => {
    for (const u of [
      "http://127.0.0.1:8069/web#action=107",
      "http://t/system/user",
      "http://t/desk/sales-order",
      "",
    ]) {
      expect(isLoginUrl(u)).toBe(false);
    }
  });
});
