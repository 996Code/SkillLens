import type { SkillListItem } from "./api";

// 系统分组共享 util（评审 #.GraphOverview/GraphWorkspace 双源漂移消除：
// 排序键 "njmind" vs "njmind 内网" 不一致——统一用完整系统序表）

export const SYSTEM_ORDER = [
  "njmind 内网", "Odoo 销售", "Dolibarr 订单", "ERPNext 客户",
  "Snipe 资产", "禅道项目", "若依权限", "JeecG 表单", "Firefly 记账",
];

// 系统分组点的固定配色（评审：GraphOverview 里 [data-sys="njmind"] 等选择器
// 与实际系统全名不匹配全成死规则——映射收口到这里，模板内联绑定）
export const SYSTEM_COLORS: Record<string, string> = {
  "njmind 内网": "#3b82f6",
  "Odoo 销售": "#8b5cf6",
  "Dolibarr 订单": "#f59e0b",
  "ERPNext 客户": "#10b981",
  "其他": "#9ca3af",
};

export const DEFAULT_SYSTEM_COLOR = "#6b7280";

export function systemColor(system: string): string {
  return SYSTEM_COLORS[system] ?? DEFAULT_SYSTEM_COLOR;
}

export function groupBySystem(
  skills: SkillListItem[],
  filter: (s: SkillListItem) => boolean = () => true,
): [string, SkillListItem[]][] {
  const groups = new Map<string, SkillListItem[]>();
  for (const s of skills) {
    if (!filter(s)) continue;
    const sys = s.system || "其他";
    if (!groups.has(sys)) groups.set(sys, []);
    groups.get(sys)!.push(s);
  }
  return [...groups.entries()].sort((a, b) => {
    const ai = SYSTEM_ORDER.indexOf(a[0]), bi = SYSTEM_ORDER.indexOf(b[0]);
    const av = ai === -1 ? 99 : ai, bv = bi === -1 ? 99 : bi;
    if (av !== bv) return av - bv;
    return a[0].localeCompare(b[0]);
  });
}
