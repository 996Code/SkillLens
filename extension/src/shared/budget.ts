// AK2 三级预算传递（设计：docs/specs/2026-10-09-ak-exception-convergence-design.md §3.3）
// 业界依据：zcode 截图瞬态重试预算 2s < 父级 surface 3s 留余量（L14-17）；
// raceActionProbe 每次尝试只消费剩余预算（L749-756）——剩余制天然封顶，
// 治 30s 无界等待与重试风暴。
export class Budget {
  private deadline: number;

  constructor(totalMs: number) {
    this.deadline = Date.now() + totalMs;
  }

  /** 剩余毫秒（不可<0——耗尽即 0，调用方据此快败） */
  leftMs(): number {
    return Math.max(0, this.deadline - Date.now());
  }

  /** 是否已耗尽 */
  exhausted(): boolean {
    return Date.now() >= this.deadline;
  }

  /** 从剩余预算切一个子预算（fraction 比例，下限 floorMs 防止切出 0）。
   *  子预算到期时间不超过本预算（子 <= 父——zcode 余量原则）。 */
  slice(fraction: number, floorMs = 1000): Budget {
    const ms = Math.max(Math.floor(this.leftMs() * fraction), Math.min(floorMs, this.leftMs()));
    const b = new Budget(ms);
    // 子预算不得晚于父预算到期
    b.deadline = Math.min(b.deadline, this.deadline);
    return b;
  }

  /** 耗尽语义的错误消息（classify 四码判 timeout 的锚点） */
  timeoutError(what: string): Error {
    return new Error(`${what} 预算耗尽 budget exhausted`);
  }
}

/** run 总预算 → 每步预算 = 剩余/剩余步数（下限 stepFloorMs） */
export function stepBudget(run: Budget, remainingSteps: number, stepFloorMs = 5000): Budget {
  const n = Math.max(1, remainingSteps);
  const ms = Math.max(Math.floor(run.leftMs() / n), Math.min(stepFloorMs, run.leftMs()));
  const b = new Budget(ms);
  b.deadline = Math.min(b.deadline, run.deadline);
  return b;
}

/** 带预算的 race：预算耗尽即 reject（替代裸 setTimeout race 的无界等待） */
export async function withBudget<T>(p: Promise<T>, b: Budget, what: string): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      p,
      new Promise<never>((_, rej) => {
        const left = b.leftMs();
        if (left <= 0) { rej(b.timeoutError(what)); return; }
        timer = setTimeout(() => rej(b.timeoutError(what)), left);
      }),
    ]);
  } finally {
    if (timer) clearTimeout(timer);
  }
}
