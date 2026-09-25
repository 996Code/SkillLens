import { describeElement } from "../shared/describe-element";
import { SENSITIVE_KEY_RE, redactValue } from "../shared/redact";
import type { Snapshot } from "../shared/types";

// 快照体积红线（计划 Global Constraints）：
// 单字段值 ≤1KB、最多 50 字段（超出记 overflow=true）、labels ≤20 条、tables ≤10 张。
const MAX_FIELDS = 50;
const MAX_VALUE_CHARS = 1024;
const MAX_LABELS = 20;
const MAX_LABEL_CHARS = 200;
const MAX_TABLES = 10;
// S12 N3 层1 toast 红线：≤3 条、每条 ≤100 字符
const MAX_TOASTS = 3;
const MAX_TOAST_CHARS = 100;

// forms：input/select/textarea 的 label 复用 describe-element 的语义描述
// （aria-label → placeholder → title → 关联 label 文本 → 累积文本），不发明新格式。
// 密码框整体跳过（redact 红线：宁可缺失也不落明文/掩码占位）。
export function collectSnapshot(doc: Document, phase: "before" | "after"): Snapshot {
  const forms: Snapshot["forms"] = [];
  let overflow = false;

  const fields = doc.querySelectorAll("input, select, textarea");
  fields.forEach((el) => {
    if (overflow) return;
    const input = el as HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;
    if (input.type === "password") return;
    if (forms.length >= MAX_FIELDS) {
      overflow = true;
      return;
    }
    forms.push({
      label: describeElement(input).label,
      // label 命中敏感词（token/secret/authorization…）时复用既有脱敏（redact 红线）
      value: String(redactValue(describeElement(input).label,
                                 input.value.slice(0, MAX_VALUE_CHARS))),
    });
  });

  const toasts = collectToasts(doc);
  return { phase, ts: Date.now(), forms, labels: collectLabels(doc), tables: collectTables(doc),
           ...(overflow ? { overflow: true } : {}),
           ...(toasts.length ? { toasts } : {}) };
}

// toasts（S12 N3 层1）：锚点后可见的 n-message/[class*=message] 提示文本。
// 可见性：offsetParent 非空（真机常规文档流）；但 jsdom 无布局 offsetParent 恒 null、
// 真机 position:fixed 的 toast（n-message 常见定位）offsetParent 也是 null——
// 故 offsetParent 为空时退回隐藏属性 + computed display 近似，不能只看 offsetParent。
// 脱敏红线：文本命中 SENSITIVE_KEY_RE（token/secret/authorization…）整条丢弃，
// 不做掩码占位（宁可缺失也不落敏感线索）。
function collectToasts(doc: Document): string[] {
  const out: string[] = [];
  doc.querySelectorAll(".n-message, [class*=message]").forEach((el) => {
    if (out.length >= MAX_TOASTS) return;
    const text = (el.textContent ?? "").trim().slice(0, MAX_TOAST_CHARS);
    if (!text || out.includes(text)) return; // 空文本/父子组件重复文本跳过
    if (SENSITIVE_KEY_RE.test(text)) return;
    const html = el as HTMLElement;
    if (html.offsetParent === null) {
      if (html.closest("[hidden]") || html.closest("[aria-hidden='true']")) return;
      if (doc.defaultView?.getComputedStyle(html).display === "none") return;
    }
    out.push(text);
  });
  return out;
}

// labels：状态标签类文本。选择器策略：[class*="tag"]/[class*="status"]/[class*="badge"]
// 命中常见 UI 库（antd/element-plus 等）的状态组件；但 class 命名无标准，
// 故补充兜底条件"可见且非空的短文本元素"不引入——这里维持选择器策略 + 通用过滤
// （jsdom 无布局，可见性以离屏/隐藏属性近似），只采 trim 后非空文本。
function collectLabels(doc: Document): Snapshot["labels"] {
  const out: Snapshot["labels"] = [];
  doc.querySelectorAll('[class*="tag"], [class*="status"], [class*="badge"]').forEach((el) => {
    if (out.length >= MAX_LABELS) return;
    if (el.closest("[hidden]") || el.closest("[aria-hidden='true']")) return;
    const text = (el.textContent ?? "").trim().slice(0, MAX_LABEL_CHARS);
    if (text) out.push({ text });
  });
  return out;
}

// tables：rows = tbody tr 数（无 tbody 则 tr 总数 - 1，即去掉表头行）；
// label 取 table 的 aria-label，缺失时取其前最近的标题类文本（h1-h6/caption/legend）。
function collectTables(doc: Document): Snapshot["tables"] {
  const out: Snapshot["tables"] = [];
  doc.querySelectorAll("table").forEach((table) => {
    if (out.length >= MAX_TABLES) return;
    const tbodies = table.querySelectorAll("tbody");
    let rows: number;
    if (tbodies.length > 0) {
      rows = 0;
      tbodies.forEach((tb) => {
        rows += tb.querySelectorAll("tr").length;
      });
    } else {
      rows = Math.max(table.querySelectorAll("tr").length - 1, 0);
    }
    out.push({ label: tableLabel(table), rows });
  });
  return out;
}

function tableLabel(table: HTMLTableElement): string {
  const aria = table.getAttribute("aria-label");
  if (aria) return aria;
  const caption = table.querySelector("caption");
  if (caption?.textContent?.trim()) return caption.textContent.trim();
  let cur: Element | null = table.previousElementSibling;
  while (cur) {
    if (/^h[1-6]$/i.test(cur.tagName)) {
      const t = (cur.textContent ?? "").trim();
      if (t) return t;
    }
    cur = cur.previousElementSibling;
  }
  return "";
}
