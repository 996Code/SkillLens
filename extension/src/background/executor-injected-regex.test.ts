// @vitest-environment node
// 安全网：注入到页面的 JS 写在 TS 模板字符串里，单反斜杠转义会被 TS 先吃掉一层
// （`/[*\s]/` → 页面收到 `/[*s]/`，空白归一化静默失效；`'\n'` → 页面收到真换行，
// 直接语法错误）。规则：expression 模板串内不允许出现单反斜杠转义，一律写 `\\`。
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const src = readFileSync(new URL("./executor.ts", import.meta.url), "utf8");

type Finding = { line: number; text: string };

/** 扫描所有 `expression: \`...\`` 模板串，返回其中的单反斜杠转义。 */
function singleBackslashInExpressions(source: string): Finding[] {
  const out: Finding[] = [];
  const re = /expression:\s*`/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(source)) !== null) {
    let i = m.index + m[0].length;
    while (i < source.length) {
      const c = source[i];
      if (c === "`") break;
      if (c === "\\" && source[i + 1] !== "\\") {
        out.push({
          line: source.slice(0, i).split("\n").length,
          text: source.slice(i, i + 12).split("\n")[0],
        });
        i += 2;
        continue;
      }
      if (c === "\\" && source[i + 1] === "\\") { i += 2; continue; }
      if (c === "$" && source[i + 1] === "{") {           // 插值原样跳过（TS 侧代码）
        let depth = 1; i += 2;
        while (i < source.length && depth > 0) {
          if (source[i] === "{") depth++;
          else if (source[i] === "}") depth--;
          i++;
        }
        continue;
      }
      i++;
    }
  }
  return out;
}

describe("注入表达式转义纪律", () => {
  it("扫描非空（防呆：expression 模板串确实被扫到）", () => {
    expect((src.match(/expression:\s*`/g) || []).length).toBeGreaterThanOrEqual(10);
  });
  it("不存在单反斜杠转义（\\s/\\d/\\n 必须写成 \\\\s 等）", () => {
    expect(singleBackslashInExpressions(src)).toEqual([]);
  });
  it("label 空白归一化用 [*\\\\s]（去星号+去空白）", () => {
    expect(src).toContain("label.replace(/[*\\\\s]/g, '')");
  });
});
