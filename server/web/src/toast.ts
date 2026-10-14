// 全局 toast（UI 优化批1）：消灭静默吞错——失败可见、成功可确认。
// 极简实现：模块级订阅 + DOM 容器（GraphWorkspace 挂载一次）。
import { ref } from "vue";

export interface ToastMsg {
  id: number;
  kind: "ok" | "err";
  text: string;
}

const toasts = ref<ToastMsg[]>([]);
let seq = 1;

export function useToasts() {
  return toasts;
}

function push(kind: ToastMsg["kind"], text: string, ms = 3200): void {
  const id = seq++;
  toasts.value.push({ id, kind, text });
  setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id);
  }, ms);
}

export function toastOk(text: string): void {
  push("ok", text);
}

export function toastErr(text: string): void {
  push("err", text, 5000);
}
