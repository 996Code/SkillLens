import { assignSession } from "./assign-session";
import type { RawEvent } from "./types";

function ev(sid: string): RawEvent {
  return { seq: 1, page_id: "p1", ts: 0, kind: "action", payload: { __session_id: sid } };
}

describe("assignSession", () => {
  it("空 sid + 活跃 session → 回填", () => {
    const { assigned, deferred } = assignSession([ev("")], "abc");
    expect(assigned[0].payload.__session_id).toBe("abc");
    expect(deferred).toHaveLength(0);
  });

  it("空 sid + 无 session → 留缓冲", () => {
    const { assigned, deferred } = assignSession([ev("")], null);
    expect(assigned).toHaveLength(0);
    expect(deferred).toHaveLength(1);
  });

  it("已有 sid 的原样通过", () => {
    const { assigned } = assignSession([ev("xyz")], "abc");
    expect(assigned[0].payload.__session_id).toBe("xyz");
  });
});
