// @vitest-environment jsdom
// popup 技能列表纯函数（popup-render.ts）：288 技能时代 slice(0,20) 会把后排
// 系统（JeecG 等）整组吞掉——全量渲染+搜索过滤+401 自助指引。
import { describe, expect, it, vi } from "vitest";
import { buildHint, renderSkillsInto } from "./popup-render";

function makeSkill(i: number, system: string) {
  return { id: 1000 + i, name: `技能${i}`, system, requires_confirmation: false };
}

describe("popup 技能列表渲染（popup-render）", () => {
  it("全量渲染不截断：110 技能 3 系统全可见（JeecG 组不被前 20 吞掉）", () => {
    const root = document.createElement("div");
    const skills = [
      ...Array.from({ length: 60 }, (_, i) => makeSkill(i, "禅道项目")),
      ...Array.from({ length: 45 }, (_, i) => makeSkill(100 + i, "JeecG 表单")),
      ...Array.from({ length: 5 }, (_, i) => makeSkill(200 + i, "Odoo 销售")),
    ];
    renderSkillsInto(root, skills, "", () => {});
    expect(root.querySelectorAll("[data-skill-row]").length).toBe(110);
    expect(root.querySelectorAll("[data-sys-group]").length).toBe(3);
    expect(root.textContent).toContain("JeecG 表单");
  });

  it("搜索过滤：只留命中系统的技能；无命中给空态", () => {
    const root = document.createElement("div");
    const skills = [makeSkill(1, "JeecG 表单"), makeSkill(2, "Odoo 销售"), makeSkill(3, "JeecG 表单")];
    renderSkillsInto(root, skills, "jeecg", () => {});
    expect(root.querySelectorAll("[data-skill-row]").length).toBe(2);
    renderSkillsInto(root, skills, "不存在的关键词", () => {});
    expect(root.textContent).toContain("无匹配技能");
  });

  it("点击执行回调带 skill id（popup 接线层据此开 executor.html）", () => {
    const root = document.createElement("div");
    const onRun = vi.fn();
    renderSkillsInto(root, [makeSkill(7, "JeecG 表单")], "", onRun);
    (root.querySelector("[data-skill-row] button") as HTMLElement).click();
    expect(onRun).toHaveBeenCalledWith(1007);
  });

  it("空列表给引导文案；401 指引带可操作恢复路径", () => {
    const root = document.createElement("div");
    renderSkillsInto(root, [], "", () => {});
    expect(root.textContent).toContain("无技能");
    const hint = buildHint("未登录或会话过期（工作台登录后重试）");
    expect(hint).toContain("未登录");
    expect(hint).toContain("executor.html");
  });
});
