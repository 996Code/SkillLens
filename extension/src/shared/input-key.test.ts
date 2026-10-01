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

  it("S42：Element Plus el-id-* 框架 id 跳过，回退 placeholder", () => {
    const el = makeEl({ id: "el-id-4647-65", placeholder: "请输入岗位名称" });
    expect(inputKey(el)).toBe("请输入岗位名称");
  });

  it("textarea 同样适用回退链", () => {
    const ta = document.createElement("textarea");
    ta.id = "desc";
    expect(inputKey(ta)).toBe("desc");
  });
});

test("框架自动生成 id 被跳过（rc_select_N/ant-/纯数字）", () => {
  const rc = document.createElement("input");
  rc.id = "rc_select_0";
  rc.setAttribute("placeholder", "请输入搜索关键词");
  expect(inputKey(rc)).toBe("请输入搜索关键词");

  const ant = document.createElement("input");
  ant.id = "ant_input_3";
  ant.setAttribute("aria-label", "用户名");
  expect(inputKey(ant)).toBe("用户名");

  const numeric = document.createElement("input");
  numeric.id = "123";
  expect(inputKey(numeric)).toBeNull();

  const normal = document.createElement("input");
  normal.id = "orderName";
  expect(inputKey(normal)).toBe("orderName");
});

// S36：Frappe（ERPNext）模态输入框只有 data-fieldname（无 name/id/placeholder/aria）
test("data-fieldname 兜底为输入键", () => {
  const el = document.createElement("input");
  el.setAttribute("data-fieldname", "customer_name");
  expect(inputKey(el)).toBe("customer_name");
});

test("有 name 时 data-fieldname 不抢先", () => {
  const el = document.createElement("input");
  el.name = "phone";
  el.setAttribute("data-fieldname", "phone_field");
  expect(inputKey(el)).toBe("phone");
});

// S43-4：select2 弹层搜索输入——无 name/id/placeholder，宿主 hidden
// select 的 name 是唯一稳定信号（回放按 name 开下拉后输入）
describe("inputKey select2 弹层输入兜底", () => {
  it("select2 搜索输入取宿主 select 的 name", () => {
    const div = document.createElement("div");
    div.innerHTML = `
      <select name="model_id" class="select2-hidden-accessible"></select>
      <span class="select2-container">
        <span class="select2-dropdown">
          <span class="select2-search select2-search--dropdown">
            <input class="select2-search__field" type="search" autocomplete="off">
          </span>
        </span>
      </span>`;
    document.body.appendChild(div);
    const search = div.querySelector(".select2-search__field") as HTMLInputElement;
    search.value = "ThinkPad";
    search.dispatchEvent(new Event("input", { bubbles: true }));
    expect(inputKey(search)).toBe("model_id");
    document.body.removeChild(div);
  });

  it("非 select2 输入不受影响", () => {
    const el = document.createElement("input");
    el.name = "title";
    expect(inputKey(el)).toBe("title");
  });
});

  it("body 挂载弹层（Snipe-IT 老版 select2）经 open 容器反查宿主", () => {
    const div = document.createElement("div");
    div.innerHTML = `
      <form>
        <select name="model_id" class="select2-hidden-accessible"></select>
        <span class="select2-container select2-container--open"></span>
      </form>
      <body-mount>
        <span class="select2-container select2-container--open">
          <input class="select2-search__field" type="search">
        </span>
      </body-mount>`;
    document.body.appendChild(div);
    const search = div.querySelector(".select2-search__field") as HTMLInputElement;
    // 搜索字段所在容器前邻不是 select（body 挂载）→ 走 open 容器兜底
    expect(inputKey(search)).toBe("model_id");
    document.body.removeChild(div);
  });
