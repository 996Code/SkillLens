import { inputKey } from "./input-key";

function makeEl(attrs: Record<string, string>): HTMLInputElement {
  const el = document.createElement("input");
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, v);
  return el;
}

describe("inputKey", () => {
  it("有 name 时优先用 name", () => {
    const el = makeEl({ name: "username", id: "user", placeholder: "用户名" });
    expect(inputKey(el)).toBe("username");
  });

  it("无 name 有 id 时用 id", () => {
    const el = makeEl({ id: "user", placeholder: "用户名" });
    expect(inputKey(el)).toBe("user");
  });

  it("只有 placeholder 时用 placeholder", () => {
    const el = makeEl({ placeholder: "请输入姓名" });
    expect(inputKey(el)).toBe("请输入姓名");
  });

  it("只有 aria-label 时用 aria-label", () => {
    const el = makeEl({ "aria-label": "搜索" });
    expect(inputKey(el)).toBe("搜索");
  });

  it("全空返回 null", () => {
    const el = makeEl({});
    expect(inputKey(el)).toBeNull();
  });

  it("textarea 同样适用回退链", () => {
    const ta = document.createElement("textarea");
    ta.id = "desc";
    expect(inputKey(ta)).toBe("desc");
  });
});
