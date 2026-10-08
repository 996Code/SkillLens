// AI1 学习页：独立标签页承载学习进程（页面上下文 fetch 生命周期稳定——
// SW fire-and-forget 被 CDP 托管浏览器静默吞的教训），完成 2.5s 自动关。
export {};

import { autoLearn } from "./background/learn";

const params = new URLSearchParams(location.search);
const sid = params.get("sid") || "";
const title = document.getElementById("title")!;
const meta = document.getElementById("meta")!;
const logEl = document.getElementById("log")!;

function log(msg: string): void {
  const t = new Date().toTimeString().slice(0, 8);
  logEl.textContent += `[${t}] ${msg}\n`;
  logEl.scrollTop = logEl.scrollHeight;
}

if (!sid) {
  title.textContent = "缺少会话参数";
  meta.textContent = "";
} else {
  const steps: Record<string, string> = {
    process: "事件已切窗（process）",
    align: "骨架已对齐（align）",
    induce: "命名中（induce，LLM）",
  };
  const poll = setInterval(() => {
    void chrome.storage.local.get("sl_last_learn").then(({ sl_last_learn: r }) => {
      if (r?.step && steps[r.step]) log(steps[r.step]);
    });
  }, 2000);

  const result = await autoLearn(sid);
  clearInterval(poll);
  if (result.status === "done") {
    title.textContent = `学习完成：${result.skillName ?? "新技能"}`;
    title.className = "t ok";
    meta.textContent = `技能 #${result.skillId} 已可执行（弹窗/空间可见）`;
  } else {
    title.textContent = "自动学习失败";
    title.className = "t err";
    meta.textContent = `${result.error ?? ""}——可到工作台手动处理`;
  }
  setTimeout(() => window.close(), 2500);
}
