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

  // S34：图标按钮（Odoo 等框架点击命中的是内部 <i>/<svg> 图标）——
  // 上溯到最近可操作祖先（button/a），取其 aria-label
  it("图标元素上溯到按钮祖先取 aria-label", () => {
    const el = make(`<button aria-label="Save manually"><i class="fa fa-save"></i></button>`)
      .querySelector("i")!;
    const d = describeElement(el);
    expect(d).toMatchObject({ tag: "button", role: "button", label: "Save manually" });
  });

  it("图标元素祖先按钮无 aria-label 时回退文本", () => {
    const el = make(`<button><i class="fa"></i>保存</button>`)
      .querySelector("i")!;
    expect(describeElement(el).label).toBe("保存");
  });

  it("无可操作祖先时保持原元素描述", () => {
    const el = make(`<div><i class="icon"></i></div>`).querySelector("i")!;
    const d = describeElement(el);
    expect(d.tag).toBe("i");
  });

  it("上溯层级封顶（3 层内无可操作祖先则不溯）", () => {
    const el = make(
      `<button aria-label="far"><span><span><span><i class="x"></i></span></span></span></button>`,
    ).querySelector("i")!;
    expect(describeElement(el).tag).toBe("i");
  });
});
