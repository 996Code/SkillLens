import { afterEach, describe, expect, it, vi } from "vitest";
import { createApp, h } from "vue";
import { createMemoryHistory, createRouter } from "vue-router";
import AuditView from "../src/views/AuditView.vue";

// S10.5 块M 审计页测试：①会话列表渲染 ②行点击链路下钻（kept=false 已过滤+reason）
// ③证据图 type 过滤交互 ④LLM 日志行展开摘要。
// 挂载方式同 views.spec.ts：createApp + memory router；fetch mock 按 URL 路由（DeltaReport.spec.ts 模式）。

const sessions = [
  { session_id: "sess-aaaa1111-bbbb", source: "real_traffic", note: "真实采集",
    created_at: "2026-09-25T10:00:00", event_count: 42, filtered_count: 2,
    semantic_action_count: 3 },
  { session_id: "sess-cccc2222-dddd", source: "demo", note: "演示会话",
    created_at: "2026-09-25T09:00:00", event_count: 10, filtered_count: 0,
    semantic_action_count: 1 },
];

const trace = {
  session: sessions[0],
  windows: [
    { window_seq: 0, anchor_type: "action", anchor_label: "提交", kept: true,
      filter_reason: "", api_count: 1, state_signal_count: 1, has_state_snapshot: true },
    { window_seq: 1, anchor_type: "action", anchor_label: "取消", kept: false,
      filter_reason: "orphan_click", api_count: 0, state_signal_count: 0,
      has_state_snapshot: false },
  ],
  semantic_actions: [
    { window_seq: 0, anchor_label: "提交", api_templates: ["/api/items/save"],
      state_before_forms: 2, state_after_forms: 3 },
  ],
  alignments: [{ id: 7, skeleton_steps: 3, bucket_count: 2 }],
  skills: [{ id: 5, name: "SaveForm", status: "learned", confidence: 0.9 }],
  replay_runs: [{ id: 9, status: "pass", mode: "execute",
    created_at: "2026-09-25T11:00:00" }],
};

const allEdges = [
  { src: "page-a", dst: "page-b", type: "contains", evidence_count: 5,
    first_seen: "2026-09-25T08:00:00", last_seen: "2026-09-25T10:00:00" },
  { src: "btn-save", dst: "/api/items/save", type: "calls", evidence_count: 3,
    first_seen: "2026-09-25T08:00:00", last_seen: "2026-09-25T10:00:00" },
];

const llmLogs = [
  { id: 2, purpose: "assert_gen", provider: "fake", model: "fake-model",
    prompt_tokens: 120, completion_tokens: 30, latency_ms: 800,
    created_at: "2026-09-25T10:01:00",
    prompt_head: "PROMPT-HEAD-2 为断言生成", response_head: "RESPONSE-HEAD-2 断言结果" },
  { id: 1, purpose: "skill_naming", provider: "fake", model: "fake-model",
    prompt_tokens: 100, completion_tokens: 20, latency_ms: 500,
    created_at: "2026-09-25T10:00:00",
    prompt_head: "PROMPT-HEAD-1 命名请求", response_head: "RESPONSE-HEAD-1 名称" },
];

/** 按 URL 路由的 fetch mock：证据边支持 ?type= 过滤（模拟后端行为）。 */
function mockAuditFetch() {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/v1/audit/sessions/")) {
      return new Response(JSON.stringify(trace), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/audit/sessions")) {
      return new Response(JSON.stringify(sessions), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/audit/evidence-edges")) {
      const type = url.match(/[?&]type=([^&]*)/)?.[1];
      const rows = type ? allEdges.filter((e) => e.type === type) : allEdges;
      return new Response(JSON.stringify(rows), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    if (url.includes("/api/v1/audit/llm-logs")) {
      return new Response(JSON.stringify(llmLogs), {
        status: 200, headers: { "content-type": "application/json" } });
    }
    return new Response("not found", { status: 404 });
  });
}

async function mountAudit(root: HTMLElement) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: "/graph/run/:runId", component: { render: () => null } },
      { path: "/", component: { render: () => null } },
      { path: "/graph/audit", component: { render: () => null } },
      { path: "/graph/skill/:id", component: { render: () => null } },
      { path: "/graph/skill/:id", component: { render: () => null } },
    ],
  });
  await router.push("/graph/audit");
  const app = createApp({ render: () => h(AuditView) });
  app.use(router);
  app.mount(root);
  return app;
}

const flush = () => new Promise((r) => setTimeout(r, 0));

afterEach(() => {
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

describe("AuditView", () => {
  it("renders session list with source badges and counts", async () => {
    vi.stubGlobal("fetch", mockAuditFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountAudit(root);
    await flush();
    await flush();

    // 会话 id 前 8 位 + 备注 + 计数上屏
    expect(root.textContent).toContain("sess-aaa");
    expect(root.textContent).toContain("sess-ccc");
    expect(root.textContent).toContain("真实采集");
    expect(root.textContent).toContain("42");
    expect(root.textContent).toContain("2"); // filtered_count
    // source 徽标：real_traffic 绿 / demo 灰
    const badges = Array.from(
      root.querySelectorAll("[data-testid='source-badge']"));
    expect(badges.length).toBe(2);
    expect(badges[0]?.textContent).toContain("真实流量");
    expect(badges[0]?.className).toContain("badge-real");
    expect(badges[1]?.textContent).toContain("演示");
    expect(badges[1]?.className).toContain("badge-demo");
    // 未选中会话时下钻区块不出现
    expect(root.querySelector("[data-testid='trace-block']")).toBeNull();
    // 证据边 + LLM 日志同屏（三区块单页）
    expect(root.textContent).toContain("page-a → page-b");
    expect(root.textContent).toContain("skill_naming");
  });

  it("renders trace on row click: filtered window shows reason", async () => {
    vi.stubGlobal("fetch", mockAuditFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountAudit(root);
    await flush();
    await flush();

    const rows = root.querySelectorAll("[data-testid='session-table'] tbody tr");
    expect(rows.length).toBe(2);
    (rows[0] as HTMLElement).click();
    await flush();
    await flush();

    const block = root.querySelector("[data-testid='trace-block']");
    expect(block).not.toBeNull();
    // 窗口决策：kept=true 保留 / kept=false 已过滤 + reason
    expect(block?.textContent).toContain("保留");
    expect(block?.textContent).toContain("已过滤");
    expect(block?.textContent).toContain("orphan_click");
    // 语义动作：锚点 + API 模板 chip + 前后快照 forms 计数
    expect(block?.textContent).toContain("提交");
    expect(block?.textContent).toContain("/api/items/save");
    expect(block?.textContent).toContain("前快照 forms 2");
    expect(block?.textContent).toContain("后快照 forms 3");
    // 对齐 / Skill 链接 / 回放历史
    expect(block?.textContent).toContain("骨架步数");
    const skillLink = block?.querySelector<HTMLAnchorElement>("a[href='/graph/skill/5']");
    expect(skillLink?.textContent).toContain("SaveForm");
    expect(block?.textContent).toContain("pass");
  });

  it("filters evidence edges by type via select", async () => {
    const fetchMock = mockAuditFetch();
    vi.stubGlobal("fetch", fetchMock);
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountAudit(root);
    await flush();
    await flush();

    // 初始：全部边（calls + contains）
    expect(root.textContent).toContain("btn-save → /api/items/save");
    expect(root.textContent).toContain("page-a → page-b");

    const select = root.querySelector<HTMLSelectElement>(
      ".edge-filter select");
    expect(select).not.toBeNull();
    select!.value = "calls";
    select!.dispatchEvent(new Event("change"));
    await flush();
    await flush();

    // 过滤后：只剩 calls 边，且请求带 type=calls
    const calls = (fetchMock as ReturnType<typeof vi.fn>).mock.calls
      .map((c) => String(c[0]))
      .filter((u) => u.includes("type=calls"));
    expect(calls.length).toBeGreaterThan(0);
    expect(root.textContent).toContain("btn-save → /api/items/save");
    expect(root.textContent).not.toContain("page-a → page-b");
  });

  it("expands llm log row to show prompt/response heads", async () => {
    vi.stubGlobal("fetch", mockAuditFetch());
    const root = document.createElement("div");
    document.body.appendChild(root);
    await mountAudit(root);
    await flush();
    await flush();

    // 初始不展开
    expect(root.querySelector("[data-testid='log-detail']")).toBeNull();
    const rows = root.querySelectorAll("[data-testid='llm-table'] tbody tr");
    expect(rows.length).toBeGreaterThanOrEqual(2);
    (rows[0] as HTMLElement).click(); // id=2 assert_gen（id 倒序在前）
    await flush();

    const detail = root.querySelector("[data-testid='log-detail']");
    expect(detail).not.toBeNull();
    expect(detail?.textContent).toContain("PROMPT-HEAD-2");
    expect(detail?.textContent).toContain("RESPONSE-HEAD-2");
    // 等宽摘要块存在
    expect(detail?.querySelectorAll("pre.code").length).toBe(2);
    // 再点一次收起
    (root.querySelector("[data-testid='llm-table'] tbody tr") as HTMLElement)
      .click();
    await flush();
    expect(root.querySelector("[data-testid='log-detail']")).toBeNull();
  });
});
