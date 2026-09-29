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

  // S35：input[type=submit] 的 value 是唯一人读标签（Dolibarr 等经典表单）
  it("提交按钮 input 的 value 兜底为 label", () => {
    const el = make(`<input type="submit" name="save" value="创建第三方" />`);
    expect(describeElement(el).label).toBe("创建第三方");
  });

  // S35：无任何可访问名的图标按钮（Dolibarr 搜索键）——name 属性兜底
  it("无文本图标按钮的 name 属性兜底为 label", () => {
    const el = make(`<button type="submit" name="button_search_x"><i class="fa"></i></button>`);
    expect(describeElement(el).label).toBe("button_search_x");
  });

  it("有文本时 name 属性不抢先", () => {
    const el = make(`<button name="btn1">保存</button>`);
    expect(describeElement(el).label).toBe("保存");
  });

  // S36：Frappe（ERPNext）模态输入框只有 data-fieldname，无 placeholder/name/aria
  it("data-fieldname 兜底为 label", () => {
    const el = make(`<input data-fieldname="customer_name" />`);
    expect(describeElement(el).label).toBe("customer_name");
  });
});

// S36 多信号：labels 收集全部信号（去重有序）；ordinal 为同类兄弟序号
describe("describeElement 多信号", () => {
  it("labels 含全部可用信号且 label 取首个", () => {
    const el = make(`<input name="phone" placeholder="电话" data-fieldname="phone_f" />`);
    const d = describeElement(el);
    expect(d.label).toBe("电话");
    expect(d.labels).toEqual(["电话", "phone_f", "phone"]);
  });

  it("无任何属性时 labels 含文本", () => {
    const el = make(`<button>保存</button>`);
    expect(describeElement(el).labels).toEqual(["保存"]);
  });

  it("ordinal 是同类兄弟序号（1-based）", () => {
    const div = make(`<div><button>甲</button><span>x</span><button>乙</button></div>`);
    const btns = div.querySelectorAll("button");
    expect(describeElement(btns[0]).ordinal).toBe(1);
    expect(describeElement(btns[1]).ordinal).toBe(2);
  });

  it("框架自动生成 id 不进 labels", () => {
    const el = make(`<input id="rc_select_0" />`);
    expect(describeElement(el).labels).toEqual([]);
  });
});
