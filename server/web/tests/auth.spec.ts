import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import LoginView from "../src/views/LoginView.vue";
import { clearSession, getToken, login } from "../src/api";

// S21 块 S 前端认证测试：
// ①登录成功存 token+user；②登录失败显示错误不存会话；
// ③路由守卫：无 token 访问受保护页 → /login；有 token 放行；
// ④401 响应清会话并跳登录（authedFetch 统一出口）。

function jsonResp(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status, headers: { "content-type": "application/json" },
  });
}

async function mountLogin(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/login", component: LoginView },
      { path: "/skills", component: { render: () => h("div") } },
    ],
  });
  await router.push("/login");
  const app = createApp({ render: () => h(LoginView) });
  app.use(router);
  app.mount(root);
  return { app, router };
}

function setInput(el: HTMLInputElement, v: string): void {
  el.value = v;
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
  localStorage.clear();
});

describe("S21 login flow", () => {
  it("stores token and user on success", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResp({
      token: "tok-1", user: { id: 1, username: "alice", role: "reviewer" },
    })));
    const user = await login("alice", "pw");
    expect(user.username).toBe("alice");
    expect(getToken()).toBe("tok-1");
    expect(localStorage.getItem("sl_user")).toContain("reviewer");
  });

  it("shows error and keeps no session on 401", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResp({ detail: "x" }, 401)));
    const root = document.createElement("div");
    document.body.appendChild(root);
    const { router } = await mountLogin(root);
    await flush();

    setInput(root.querySelector("[data-testid='login-username']") as HTMLInputElement, "alice");
    setInput(root.querySelector("[data-testid='login-password']") as HTMLInputElement, "bad");
    (root.querySelector("[data-testid='login-submit']") as Element).click();
    await flush();
    await flush();

    expect(root.querySelector("[data-testid='login-error']")?.textContent)
      .toContain("用户名或密码错误");
    expect(getToken()).toBeNull();
    expect(router.currentRoute.value.path).toBe("/login");
  });

  it("navigates to /dashboard after successful login", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResp({
      token: "tok-2", user: { id: 2, username: "bob", role: "admin" },
    })));
    const root = document.createElement("div");
    document.body.appendChild(root);
    const { router } = await mountLogin(root);
    await flush();

    setInput(root.querySelector("[data-testid='login-username']") as HTMLInputElement, "bob");
    setInput(root.querySelector("[data-testid='login-password']") as HTMLInputElement, "pw");
    (root.querySelector("[data-testid='login-submit']") as Element).click();
    await flush();
    await flush();

    expect(router.currentRoute.value.path).toBe("/dashboard");
    expect(getToken()).toBe("tok-2");
  });
});

describe("S21 authedFetch 401 handling", () => {
  it("clears session and redirects to /login on 401", async () => {
    localStorage.setItem("sl_token", "expired");
    localStorage.setItem("sl_user", '{"id":1,"username":"a","role":"viewer"}');
    const assign = vi.fn();
    vi.stubGlobal("window", Object.assign(window, { location: { assign } }));
    vi.stubGlobal("fetch", vi.fn(async () => new Response("x", { status: 401 })));

    const { getSkills } = await import("../src/api");
    await getSkills().catch(() => undefined);

    expect(getToken()).toBeNull();
    expect(assign).toHaveBeenCalledWith("/login");
  });
});

describe("S21 router guard", () => {
  it("redirects to /login without token and allows with token", async () => {
    const { default: router } = await import("../src/router");
    const push = (path: string) => router.push(path);

    clearSession();
    await push("/dashboard");
    expect(router.currentRoute.value.path).toBe("/login");

    localStorage.setItem("sl_token", "tok-3");
    await push("/dashboard");
    expect(router.currentRoute.value.path).toBe("/dashboard");

    // 登录页本身永远可达
    clearSession();
    await push("/login");
    expect(router.currentRoute.value.path).toBe("/login");
  });
});
