export type EventKind = "ui" | "action" | "network" | "console" | "navigation";

export interface RawEvent {
  seq: number;
  ts: number;
  kind: EventKind;
  payload: Record<string, unknown>;
}

export const AGENT_URL = "http://127.0.0.1:8710/api/v1";
