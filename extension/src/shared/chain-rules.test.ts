// AH2 链规则解释器直测：${unique:} 唯一值生成、未知规则保留、同轮共享时间戳。
// AI2：${stepN.字段} 跨步绑定（写请求体 JSON/urlencoded 提取）。
import { describe, expect, it } from "vitest";
import {
  extractField, extractStepValue, resolveChainSteps, resolveRule,
  resolveStepOverrides, resolveValue,
} from "./chain-rules";

describe("chain-rules 规则解释器", () => {
  it("${unique:前缀} → 前缀+时间戳 base36", () => {
    const v = resolveRule("${unique:sl_form_}", 1730000000000);
    expect(v).toBe(`sl_form_${(1730000000000).toString(36)}`);
    expect(v.startsWith("sl_form_")).toBe(true);
  });

  it("空前缀合法（纯时间戳）", () => {
    expect(resolveRule("${unique:}", 123)).toBe((123).toString(36));
  });

  it("未知规则保留原文（P2 ${stepN.} 落地前不误伤）", () => {
    expect(resolveRule("${step1.表名}", 1)).toBe("${step1.表名}");
    expect(resolveRule("普通值", 1)).toBe("普通值");
  });

  it("步骤 overrides 逐值解析；无 overrides 空对象", () => {
    const r = resolveStepOverrides(
      { skill_id: 269, overrides: { "*表名称": "${unique:sl_}", "备注": "固定" } }, undefined, 99);
    expect(r["*表名称"]).toBe(`sl_${(99).toString(36)}`);
    expect(r["备注"]).toBe("固定");
    expect(resolveStepOverrides({ skill_id: 1, overrides: {} }, undefined, 1)).toEqual({});
  });

  it("整链解析：同轮共享时间戳（可对账），跨轮不同", () => {
    const steps = [
      { skill_id: 269, overrides: { a: "${unique:x_}" } },
      { skill_id: 118, overrides: { b: "${unique:y_}" } },
    ];
    const r1 = resolveChainSteps(steps, 1000);
    const r2 = resolveChainSteps(steps, 2000);
    expect(r1[0].overrides.a).toBe(`x_${(1000).toString(36)}`);
    expect(r1[1].overrides.b).toBe(`y_${(1000).toString(36)}`); // 同轮同戳
    expect(r1[0].overrides.a).not.toBe(r2[0].overrides.a);       // 跨轮不同
    expect(r1.map((s) => s.skill_id)).toEqual([269, 118]);
  });

  it("AI2 extractField：JSON 串值/数值/urlencoded 三形态", () => {
    expect(extractField('{"tableName":"sl_form_x1","code":200}', "tableName")).toBe("sl_form_x1");
    expect(extractField('{"count":42}', "count")).toBe("42");
    expect(extractField("tableName=sl_form_x2&code=200", "tableName")).toBe("sl_form_x2");
    expect(extractField('{"a":1}', "b")).toBeNull();
    expect(extractField(undefined, "a")).toBeNull();
  });

  it("AI2 跨步绑定：${step1.tableName} 从步骤1写请求提取（末条优先）", () => {
    const ctx = [
      [{ url: "http://x/addAll", reqBody: '{"tableName":"sl_form_a"}' },
       { url: "http://x/addAll", reqBody: '{"tableName":"sl_form_b"}' }],
      [{ url: "http://x/other", reqBody: '{"k":"v"}' }],
    ] as any[];
    expect(extractStepValue(ctx, "${step1.tableName}")).toBe("sl_form_b"); // 终态
    expect(extractStepValue(ctx, "${step2.k}")).toBe("v");
    expect(extractStepValue(ctx, "${step3.x}")).toBeNull();  // 越界
    expect(extractStepValue(ctx, "${step1.nothing}")).toBeNull();
  });

  it("AI2 resolveValue：绑定命中替换、未命中保留原文（防静默错值）、无 ctx 走 unique", () => {
    const ctx = [[{ reqBody: '{"tableName":"sl_t9"}' }]] as any[];
    expect(resolveValue("${step1.tableName}", ctx)).toBe("sl_t9");
    expect(resolveValue("${step1.miss}", ctx)).toBe("${step1.miss}"); // 可见于日志
    expect(resolveValue("${step1.tableName}")).toBe("${step1.tableName}"); // 无 ctx 不炸
    expect(resolveValue("${unique:p_}", undefined, 50)).toBe(`p_${(50).toString(36)}`);
    expect(resolveValue("普通值", ctx)).toBe("普通值");
  });

  it("AI2 逐步解析：第二步带 ctx 用第一步产出", () => {
    const ctx = [[{ reqBody: 'name=sl_form_q&desc=x' }]] as any[];
    const r = resolveStepOverrides(
      { skill_id: 271, overrides: { 表名: "${step1.name}" } }, ctx);
    expect(r["表名"]).toBe("sl_form_q");
  });
});
