// UI 批3：window.confirm 替换——Promise 化确认弹层（与 toast 同体系，
// 消灭原生弹窗的样式脱离+阻断渲染线程）。
import { ref } from "vue";

interface ConfirmReq {
  id: number;
  message: string;
  resolve: (ok: boolean) => void;
}

const req = ref<ConfirmReq | null>(null);
let seq = 1;

export function useConfirmReq() {
  return req;
}

export function askConfirm(message: string): Promise<boolean> {
  return new Promise((resolve) => {
    req.value = { id: seq++, message, resolve };
  });
}

export function answerConfirm(ok: boolean): void {
  if (req.value) {
    req.value.resolve(ok);
    req.value = null;
  }
}
