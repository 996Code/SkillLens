import type { RawEvent } from "../shared/types";

const DB_NAME = "skilllens";
const STORE = "events";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => req.result.createObjectStore(STORE, { keyPath: "id", autoIncrement: true });
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export async function putEvent(event: RawEvent): Promise<void> {
  const db = await open();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).add({ event });
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

export async function takeEvents(batch: number): Promise<{ id: number; event: RawEvent }[]> {
  // 游标限读（评审 #17）：getAll 全表扫描——缓冲堆积时每 6s 一次全量读。
  // openCursor 逐条取 batch 条即止，删除同事务内完成。
  const db = await open();
  const out: { id: number; event: RawEvent }[] = [];
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    const req = tx.objectStore(STORE).openCursor();
    req.onsuccess = () => {
      const cur = req.result;
      if (!cur || out.length >= batch) { resolve(); return; }
      out.push({ id: cur.key as number, event: cur.value.event });
      cur.delete();
      cur.continue();
    };
    req.onerror = () => reject(req.error);
  });
  db.close();
  return out;
}
