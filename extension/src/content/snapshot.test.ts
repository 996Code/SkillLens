import { collectSnapshot } from "./snapshot";

// jsdom：参考 describe-element.test.ts 的 make 辅助风格
function make(html: string): HTMLElement {
  const div = document.createElement("div");
  div.innerHTML = html.trim();
  return div.firstElementChild as HTMLElement;
}

describe("collectSnapshot", () => {
  it("收集 input 的 label/value 与 table 行数", () => {
    const root = make(`
      <div>
        <input placeholder="请输入" value="hello" />
        <input aria-label="订单号" value="A123" />
        <table aria-label="明细表">
          <tbody>
            <tr><td>1</td></tr>
            <tr><td>2</td></tr>
          </tbody>
        </table>
      </div>
    `);
    document.body.appendChild(root);
    const snap = collectSnapshot(document, "before");
    expect(snap.phase).toBe("before");
    expect(typeof snap.ts).toBe("number");
    expect(snap.forms).toEqual([
      { label: "请输入", value: "hello" },
      { label: "订单号", value: "A123" },
    ]);
    expect(snap.tables).toEqual([{ label: "明细表", rows: 2 }]);
    expect(snap.overflow).toBeUndefined();
    root.remove();
  });

  it("超过 50 字段：截到 50 且 overflow=true", () => {
    const root = document.createElement("div");
    for (let i = 0; i < 60; i++) {
      const input = document.createElement("input");
      input.setAttribute("aria-label", `f${i}`);
      input.value = `v${i}`;
      root.appendChild(input);
    }
    document.body.appendChild(root);
    const snap = collectSnapshot(document, "after");
    expect(snap.forms.length).toBe(50);
    expect(snap.overflow).toBe(true);
    expect(snap.forms[49]).toEqual({ label: "f49", value: "v49" });
    root.remove();
  });

  it("密码框不出现在 forms（redact 红线）", () => {
    const root = make(`
      <div>
        <input type="password" aria-label="密码" value="s3cret" />
        <input aria-label="用户名" value="alice" />
      </div>
    `);
    document.body.appendChild(root);
    const snap = collectSnapshot(document, "before");
    expect(snap.forms).toEqual([{ label: "用户名", value: "alice" }]);
    root.remove();
  });

  it("超 1KB 的单字段值被截断到 1KB", () => {
    const root = document.createElement("div");
    const input = document.createElement("input");
    input.setAttribute("aria-label", "big");
    input.value = "x".repeat(2000);
    root.appendChild(input);
    document.body.appendChild(root);
    const snap = collectSnapshot(document, "before");
    expect(snap.forms[0].value.length).toBe(1024);
    expect(snap.forms[0].value).toBe("x".repeat(1024));
    root.remove();
  });
});

test("敏感 label 的字段值被脱敏（token/secret 类不走明文）", () => {
  document.body.innerHTML = `
    <input aria-label="API Token" value="sk-real-secret-should-not-leak" />
    <input aria-label="普通字段" value="normal-value" />`;
  const snap = collectSnapshot(document, "before");
  const token = snap.forms.find((f) => /token/i.test(f.label))!;
  const normal = snap.forms.find((f) => f.label === "普通字段")!;
  expect(token.value).not.toContain("sk-real-secret");
  expect(normal.value).toBe("normal-value");
});

// ---------- S12 N3 层1：toast 采集 ----------

describe("collectSnapshot toasts", () => {
  it("采集可见 .n-message/[class*=message] 文本；隐藏的不采；无 toast 不带键", () => {
    const root = make(`
      <div>
        <div class="n-message">保存成功</div>
        <div class="x-message">已发布</div>
        <div class="n-message" hidden>隐藏的不采</div>
      </div>
    `);
    document.body.appendChild(root);
    const snap = collectSnapshot(document, "after");
    expect(snap.toasts).toEqual(["保存成功", "已发布"]);
    root.remove();

    // 无 toast 的页面：快照不携带 toasts 键（体积红线：有值才带）
    const bare = make(`<div><input aria-label="a" value="b" /></div>`);
    document.body.appendChild(bare);
    const snap2 = collectSnapshot(document, "before");
    expect(snap2.toasts).toBeUndefined();
    bare.remove();
  });

  it("超过 3 条截断到 3；单条超 100 字符截断", () => {
    const root = document.createElement("div");
    for (let i = 0; i < 5; i++) {
      const t = document.createElement("div");
      t.className = "n-message";
      t.textContent = `toast${i}`;
      root.appendChild(t);
    }
    const long = document.createElement("div");
    long.className = "n-message";
    long.textContent = "长".repeat(200);
    root.appendChild(long);
    document.body.appendChild(root);
    const snap = collectSnapshot(document, "after");
    expect(snap.toasts).toEqual(["toast0", "toast1", "toast2"]);
    root.remove();

    const root2 = document.createElement("div");
    const long2 = document.createElement("div");
    long2.className = "n-message";
    long2.textContent = "x".repeat(200);
    root2.appendChild(long2);
    document.body.appendChild(root2);
    const snap2 = collectSnapshot(document, "after");
    expect(snap2.toasts).toEqual(["x".repeat(100)]);
    root2.remove();
  });

  it("含 token 等敏感词的 toast 整条丢弃（脱敏红线）", () => {
    const root = make(`
      <div>
        <div class="n-message">token 已刷新</div>
        <div class="n-message">保存成功</div>
      </div>
    `);
    document.body.appendChild(root);
    const snap = collectSnapshot(document, "after");
    expect(snap.toasts).toEqual(["保存成功"]);
    root.remove();
  });
});
