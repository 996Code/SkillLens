export type EventKind = "ui" | "action" | "network" | "console" | "navigation" | "snapshot";

export interface RawEvent {
  seq: number;
  page_id: string;
  ts: number;
  kind: EventKind;
  payload: Record<string, unknown>;
}

export const AGENT_URL = "http://127.0.0.1:8710/api/v1";

// UI 状态快照（Sprint 8 块B）：锚点动作前后各采一次，随窗口走既有事件通道上报。
// 体积红线：单字段值 ≤1KB、最多 50 字段（超出记 overflow）、labels ≤20 条、tables ≤10 张。
export interface Snapshot {
  phase: "before" | "after";
  ts: number;
  forms: { label: string; value: string }[];
  labels: { text: string }[];
  tables: { label: string; rows: number }[];
  overflow?: boolean;
  // S12 N3 层1：锚点后可见的 n-message/[class*=message] 提示文本（≤3 条×100 字符）。
  // 有值才带键（体积红线）；文本命中敏感词表的整条丢弃（脱敏红线）。
  toasts?: string[];
}

// content script -> service worker 的事件消息类型（MV3 中 CS 与 SW 不共享 IndexedDB，
// 事件须经消息转发到 SW 侧落库）
export const EVENT_MSG = "skilllens-event";
