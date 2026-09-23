// vitest.config.ts 需加 environment: "jsdom"（见 Step 3）
import { describeElement } from "./describe-element";

function make(html: string): Element {
  const div = document.createElement("div");
  div.innerHTML = html.trim();
  return div.firstElementChild!;
}

describe("describeElement", () => {
  it("提取按钮的 role/label/text", () => {
    const el = make(`<button aria-label="提交审批">提交</button>`);
    const d = describeElement(el);
    expect(d).toMatchObject({ tag: "button", role: "button", label: "提交审批", text: "提交" });
  });

  it("无 aria-label 时回退到可见文本", () => {
    const el = make(`<button>保存草稿</button>`);
    expect(describeElement(el).label).toBe("保存草稿");
  });

  it("输入框取 placeholder 或关联 label", () => {
    const el = make(`<input placeholder="订单号" />`);
    expect(describeElement(el).label).toBe("订单号");
  });

  it("path 是简化的标签路径", () => {
    const el = make(`<div><span><button>ok</button></span></div>`).querySelector("button")!;
    expect(describeElement(el).path).toBe("div>span>button");
  });
});
