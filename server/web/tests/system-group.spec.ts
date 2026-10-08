import { describe, expect, it } from "vitest";
import {
  DEFAULT_SYSTEM_COLOR,
  SYSTEM_COLORS,
  SYSTEM_ORDER,
  groupBySystem,
  systemColor,
} from "../src/system-group";
import type { SkillListItem } from "../src/api";

// 评审#7：system-group 此前零测试。GraphOverview 的 [data-sys="njmind"] 等
// 死选择器（实际系统值是全名）收口为 systemColor()——本 spec 为规格。

function skill(id: number, system: string, status = "learned"): SkillListItem {
  return { id, name: `s${id}`, status, system } as SkillListItem;
}

describe("SYSTEM_ORDER", () => {
  it("覆盖 9 个目标系统且顺序固定（njmind 首位）", () => {
    expect(SYSTEM_ORDER.length).toBe(9);
    expect(SYSTEM_ORDER[0]).toBe("njmind 内网");
    expect(SYSTEM_ORDER.indexOf("njmind 内网"))
      .toBeLessThan(SYSTEM_ORDER.indexOf("Odoo 销售"));
    expect(SYSTEM_ORDER.indexOf("Odoo 销售"))
      .toBeLessThan(SYSTEM_ORDER.indexOf("Firefly 记账"));
  });
});

describe("groupBySystem", () => {
  it("按系统分组并按 SYSTEM_ORDER 排序", () => {
    const groups = groupBySystem([
      skill(1, "Odoo 销售"), skill(2, "njmind 内网"), skill(3, "Odoo 销售"),
    ]);
    expect(groups.map(([sys]) => sys)).toEqual(["njmind 内网", "Odoo 销售"]);
    expect(groups[0][1].map((s) => s.id)).toEqual([2]);
    expect(groups[1][1].map((s) => s.id)).toEqual([1, 3]); // 组内保持原序
  });

  it("空 system 归入「其他」", () => {
    const groups = groupBySystem([skill(1, "")]);
    expect(groups[0][0]).toBe("其他");
  });

  it("不在 SYSTEM_ORDER 的系统排最后并按名称排序", () => {
    const groups = groupBySystem([
      skill(1, "Zeta 系统"), skill(2, "Alpha 系统"), skill(3, "njmind 内网"),
    ]);
    expect(groups.map(([sys]) => sys))
      .toEqual(["njmind 内网", "Alpha 系统", "Zeta 系统"]);
  });

  it("filter 参数在分组前过滤", () => {
    const groups = groupBySystem(
      [skill(1, "Odoo 销售", "learned"), skill(2, "Odoo 销售", "candidate")],
      (s) => s.status === "learned",
    );
    expect(groups.length).toBe(1);
    expect(groups[0][1].map((s) => s.id)).toEqual([1]);
  });
});

describe("systemColor", () => {
  it("已知系统返回固定色（与 SYSTEM_COLORS 一致）", () => {
    expect(systemColor("njmind 内网")).toBe("#3b82f6");
    expect(systemColor("Odoo 销售")).toBe(SYSTEM_COLORS["Odoo 销售"]);
    expect(systemColor("其他")).toBe(SYSTEM_COLORS["其他"]);
  });

  it("未列系统回退默认灰", () => {
    expect(systemColor("禅道项目")).toBe(DEFAULT_SYSTEM_COLOR);
  });

  it("空字符串回退默认灰", () => {
    expect(systemColor("")).toBe(DEFAULT_SYSTEM_COLOR);
  });
});
