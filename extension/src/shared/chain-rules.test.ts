// AH2 链规则解释器直测：${unique:} 唯一值生成、未知规则保留、同轮共享时间戳。
import { describe, expect, it } from "vitest";
import { resolveChainSteps, resolveRule, resolveStepOverrides } from "./chain-rules";

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
      { skill_id: 269, overrides: { "*表名称": "${unique:sl_}", "备注": "固定" } }, 99);
    expect(r["*表名称"]).toBe(`sl_${(99).toString(36)}`);
    expect(r["备注"]).toBe("固定");
    expect(resolveStepOverrides({ skill_id: 1, overrides: {} })).toEqual({});
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
});
