// popup 技能列表渲染纯函数（从 popup.ts 抽出以便直测）：
// 全量渲染不截断（288 技能时代 slice(0,20) 会把后排系统整组吞掉）+
// 系统分组 + 搜索过滤 + 401 自助指引文案。
export interface PopupSkill {
  id: number;
  name: string;
  system?: string | null;
  requires_confirmation?: boolean;
}

export function buildHint(errMsg: string): string {
  // 工作台登录本身不会把 token 配给插件（写入只发生在 executor.html?token=
  // 打开时）——401 时必须告诉用户可操作的恢复路径，而不是一句过期提示
  return `${errMsg}\n恢复：打开工作台技能页点「插件执行」生成 executor.html 链接，`
    + "或让工作台重新下发 token 后刷新本弹窗";
}

export function renderSkillsInto(
  root: HTMLElement,
  skills: PopupSkill[],
  query: string,
  onRun: (id: number) => void,
): void {
  root.replaceChildren();
  const q = query.trim().toLowerCase();
  if (!skills.length) {
    root.textContent = "无技能（先在工作台学习）";
    return;
  }
  const visible = q
    ? skills.filter((s) => `${s.system || "通用"} ${s.name}`.toLowerCase().includes(q))
    : skills;
  if (!visible.length) {
    root.textContent = "无匹配技能";
    return;
  }
  const groups = new Map<string, PopupSkill[]>();
  for (const s of visible) {
    const sys = s.system || "通用";
    if (!groups.has(sys)) groups.set(sys, []);
    groups.get(sys)!.push(s);
  }
  for (const [sys, items] of groups) {
    const h = document.createElement("div");
    h.textContent = sys;
    h.dataset.sysGroup = sys;
    h.style.cssText = "margin:8px 0 2px; font-size:11px; color:var(--muted); font-weight:600";
    root.append(h);
    for (const s of items) {
      const row = document.createElement("div");
      row.dataset.skillRow = String(s.id);
      row.style.cssText = "display:flex; align-items:center; gap:6px; padding:4px 0; border-bottom:1px solid var(--line)";
      const name = document.createElement("span");
      name.style.cssText = "flex:1; font-size:12px";
      name.textContent = `${s.name}${s.requires_confirmation ? " ✎" : ""}`;
      const btn = document.createElement("button");
      btn.textContent = "自动执行";
      btn.style.cssText = "font-size:12px; padding:2px 10px";
      btn.addEventListener("click", () => onRun(s.id));
      row.append(name, btn);
      root.append(row);
    }
  }
}
