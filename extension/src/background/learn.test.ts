// @vitest-environment jsdom
// AI1 自动学习编排：四步 API 序列、逐步报告、失败降级（error 落通知不吞）、
// 断言失败不阻断。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const store: Record<string, unknown> = {};
vi.stubGlobal("chrome", {
  storage: { local: {
    set: vi.fn(async (o: Record<string, unknown>) => Object.assign(store, o)),
    get: vi.fn(async (k: string) => store[k] ?? null),
  } },
});

vi.mock("./executor", () => ({
  api: vi.fn(),
  getToken: vi.fn(async () => "t"),
}));

const { api } = await import("./executor") as { api: ReturnType<typeof vi.fn> };
const { autoLearn } = await import("./learn");

beforeEach(() => {
  vi.clearAllMocks();
  Object.keys(store).forEach((k) => delete store[k]);
});
afterEach(() => {});

describe("autoLearn 停录自动学习", () => {
  it("四步顺序：process → align → induce → assertions，终态 done 带技能", async () => {
    api.mockImplementation(async (path: string) => {
      if (path.includes("/process")) return {};
      if (path === "/align") return { alignment_id: 7 };
      if (path.includes("/induce")) return { id: 42, name: "新增技能", status: "learned" };
      if (path.includes("/assertions")) return [];
      throw new Error("unexpected " + path);
    });
    const r = await autoLearn("sid-1");
    expect(r.status).toBe("done");
    expect(r.skillId).toBe(42);
    expect(r.skillName).toBe("新增技能");
    // 调用序列
    const paths = api.mock.calls.map((c) => String(c[0]));
    expect(paths[0]).toContain("/sessions/sid-1/process");
    expect(paths[1]).toBe("/align");
    expect(paths[2]).toBe("/alignments/7/induce");
    expect(paths[3]).toBe("/skills/42/assertions");
    // 通知落库
    expect((store.sl_last_learn as any).status).toBe("done");
  });

  it("断言生成失败不阻断（技能仍 done）", async () => {
    api.mockImplementation(async (path: string) => {
      if (path.includes("/assertions")) throw new Error("assertions 422");
      if (path === "/align") return { alignment_id: 1 };
      if (path.includes("/induce")) return { id: 9, name: "x" };
      return {};
    });
    const r = await autoLearn("sid-2");
    expect(r.status).toBe("done");
    expect(r.skillId).toBe(9);
  });

  it("align 失败：error 终态带步骤与信息（C3 可见不吞）", async () => {
    api.mockImplementation(async (path: string) => {
      if (path === "/align") throw new Error("HTTP 409: session not processed");
      return {};
    });
    const r = await autoLearn("sid-3");
    expect(r.status).toBe("error");
    expect(r.step).toBe("process");
    expect(r.error).toContain("409");
    expect((store.sl_last_learn as any).status).toBe("error");
  });

  it("induce 失败：技能信息缺、error 带 induce 语义", async () => {
    api.mockImplementation(async (path: string) => {
      if (path.includes("/induce")) throw new Error("LLM 网关超时");
      if (path === "/align") return { alignment_id: 3 };
      return {};
    });
    const r = await autoLearn("sid-4");
    expect(r.status).toBe("error");
    expect(r.step).toBe("align");
    expect(r.skillId).toBeUndefined();
  });
});
