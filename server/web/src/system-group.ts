import type { SkillListItem } from "./api";

// 系统分组共享 util（评审 #.GraphOverview/GraphWorkspace 双源漂移消除：
// 排序键 "njmind" vs "njmind 内网" 不一致——统一用完整系统序表）

const SYSTEM_ORDER = [
  "njmind 内网", "Odoo 销售", "Dolibarr 订单", "ERPNext 客户",
  "Snipe 资产", "禅道项目", "若依权限", "JeecG 表单", "Firefly 记账",
];

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
