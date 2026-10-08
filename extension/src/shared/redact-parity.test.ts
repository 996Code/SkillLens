// @vitest-environment node
// 安全红线：脱敏词表在三处物理副本必须完全一致（TS 主表 / MAIN world 纯 JS /
// server 快照）。CRXJS 原样复制 injected/*.js，无法 import TS，只能靠本测试兜住漂移。
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { BASE_SENSITIVE_PATTERNS } from "./redact";

const netHookSrc = readFileSync(new URL("../injected/net-hook.js", import.meta.url), "utf8");
const executorSrc = readFileSync(new URL("../background/executor.ts", import.meta.url), "utf8");
const snapshotSrc = readFileSync(
  new URL("../../../server/app/replay/page_snapshot.py", import.meta.url), "utf8",
);

function quotedList(src: string, marker: string): string[] {
  const i = src.indexOf(marker);
  expect(i, `未找到 ${marker}`).toBeGreaterThanOrEqual(0);
  const body = src.slice(i, src.indexOf("]", i));
  return [...body.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
}

function regexWords(src: string, name: string): string[] {
  const m = src.match(new RegExp(`${name}\\s*=\\s*/([^/]+)/`));
  expect(m, `未找到 ${name} 正则`).not.toBeNull();
  return m![1].split("|");
}

const CHINESE = ["密码", "口令", "密钥", "令牌", "凭证", "验证码"];

describe("脱敏词表四处一致", () => {
  it("net-hook.js（录制路径）词集与 redact.ts 相等", () => {
    expect(regexWords(netHookSrc, "SENSITIVE").sort())
      .toEqual([...BASE_SENSITIVE_PATTERNS].sort());
  });
  it("executor.ts 页内快照 SENS 词集与 redact.ts 相等", () => {
    expect(regexWords(executorSrc, "const SENS").sort())
      .toEqual([...BASE_SENSITIVE_PATTERNS].sort());
  });
  it("server page_snapshot.py 词集与 redact.ts 相等", () => {
    expect(quotedList(snapshotSrc, "_BASE_SENSITIVE_PATTERNS").sort())
      .toEqual([...BASE_SENSITIVE_PATTERNS].sort());
  });
  it("中文 label 形态覆盖（njmind/若依/禅道等中文系统）", () => {
    for (const w of CHINESE) expect(BASE_SENSITIVE_PATTERNS).toContain(w);
  });
  it("词表无重复项", () => {
    expect(new Set(BASE_SENSITIVE_PATTERNS).size).toBe(BASE_SENSITIVE_PATTERNS.length);
  });
});
