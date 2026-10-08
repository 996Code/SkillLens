// AI1 录制闭环：停录后自动学习（process → align → induce → assertions），
// 技能直接进空间——测试工程师不再跳工作台走四步手工流水线。
// 编排在 SW（fire-and-forget，不阻塞 stopRecording 响应）；每步失败落
// sl_last_learn.error 供 popup 通知（C3 可见不吞）。
export {};

import { api, getToken } from "./executor";
import { AGENT_URL } from "../shared/types";

export interface LearnResult {
  sessionId: string;
  status: "learning" | "done" | "error";
  skillId?: number;
  skillName?: string;
  step?: string;
  error?: string;
  ts: number;
}

// 写通知（popup 打开时消费；覆盖式——只关心最近一次）
export async function reportLearn(r: LearnResult): Promise<void> {
  await chrome.storage.local.set({ sl_last_learn: r });
}

// 学习三步 + 断言生成。任何一步失败：报告 error 并停（半成品技能比
// 报错更误导——align 成功 induce 失败时 alignment 留在库里可人工续）。
export async function autoLearn(sessionId: string): Promise<LearnResult> {
  const t0 = Date.now();
  let r: LearnResult = { sessionId, status: "learning", ts: t0 };
  await reportLearn(r);
  try {
    // ① process：事件 → 窗口 → 语义动作（确定性管道）
    await api(`/sessions/${sessionId}/process`, { method: "POST" });
    r = { ...r, step: "process" };
    await reportLearn(r);

    // ② align：单会话对齐（骨架=该会话窗口序列）
    const al = await api("/align", {
      method: "POST", body: JSON.stringify({ session_ids: [sessionId] }),
    });
    r = { ...r, step: "align" };
    await reportLearn(r);

    // ③ induce：LLM 命名 + 确定性回查（宪法 C1：LLM 只命名）
    const sk = await api(`/alignments/${al.alignment_id}/induce`, { method: "POST" });
    r = { ...r, step: "induce", skillId: sk.id, skillName: sk.name, status: "done" };

    // ④ 断言生成（开箱可执行：技能带断言才有 pass/fail 判定）
    try {
      await api(`/skills/${sk.id}/assertions`, { method: "POST" });
    } catch { /* 断言失败不阻断——技能已可用，工作台可补 */ }

    await reportLearn(r);
    return r;
  } catch (e: any) {
    const err = { ...r, status: "error" as const, error: String(e?.message || e) };
    await reportLearn(err);
    return err;
  }
}
