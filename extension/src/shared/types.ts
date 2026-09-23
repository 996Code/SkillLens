export type EventKind = "ui" | "action" | "network" | "console" | "navigation";

export interface RawEvent {
  seq: number;
  page_id: string;
  ts: number;
  kind: EventKind;
  payload: Record<string, unknown>;
}

export const AGENT_URL = "http://127.0.0.1:8710/api/v1";

// content script -> service worker 的事件消息类型（MV3 中 CS 与 SW 不共享 IndexedDB，
// 事件须经消息转发到 SW 侧落库）
export const EVENT_MSG = "skilllens-event";
