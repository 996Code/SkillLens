import { describe, expect, it } from "vitest";
import { assertExpect } from "../src/run-format";

// 评审#3：SkillGraphView 本地 payloadSummary 与共享 assertExpect 双源漂移
// （field_change 一支带 api_template 一支不带）——合并后以本 spec 为规格：
// field_change/state_signal 带 api_template 时渲染括号后缀，缺失时安全降级。

describe("assertExpect（断言期望摘要，双源合并后唯一实现）", () => {
  it("api_status：template → expect_status", () => {
    expect(assertExpect({
      kind: "api_status",
      payload: { api_template: "/a/save", expect_status: 200 },
    })).toBe("/a/save → 200");
  });

  it("state_signal：field=expect（api_template）", () => {
    expect(assertExpect({
      kind: "state_signal",
      payload: { field: "status", expect_value: "SUCCESS", api_template: "/a/query" },
    })).toBe("status=SUCCESS（/a/query）");
  });

  it("state_signal 缺 api_template：降级不带括号后缀", () => {
    expect(assertExpect({
      kind: "state_signal",
      payload: { field: "status", expect_value: "SUCCESS" },
    })).toBe("status=SUCCESS");
  });

  it("ui_text：label: before → after", () => {
    expect(assertExpect({
      kind: "ui_text",
      payload: { label: "状态", before: "草稿", after: "已提交" },
    })).toBe("状态: 草稿 → 已提交");
  });

  it("field_change 带 api_template：更信息量的一支为统一行为", () => {
    expect(assertExpect({
      kind: "field_change",
      payload: { field: "x", before: "a", after: "b", api_template: "/a/save" },
    })).toBe("x: a → b（/a/save）");
  });

  it("field_change 缺 api_template：降级不带括号后缀", () => {
    expect(assertExpect({
      kind: "field_change",
      payload: { field: "x", before: "a", after: "b" },
    })).toBe("x: a → b");
  });

  it("未知 kind：payload JSON 兜底", () => {
    expect(assertExpect({ kind: "mystery", payload: { a: 1 } })).toBe('{"a":1}');
  });

  it("空 payload / payload 为 null 不抛异常", () => {
    expect(assertExpect({ payload: {} })).toBe("{}");
    expect(() => assertExpect({ kind: "field_change", payload: null })).not.toThrow();
    expect(() => assertExpect({})).not.toThrow();
  });
});
