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
  const db = await open();
  const all = await new Promise<{ id: number; event: RawEvent }[]>((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    const req = tx.objectStore(STORE).getAll();
    req.onsuccess = () => resolve(req.result as never);
    req.onerror = () => reject(req.error);
  });
  const out = all.slice(0, batch);
  const tx = db.transaction(STORE, "readwrite");
  const store = tx.objectStore(STORE);
  for (const row of out) store.delete(row.id);
  await new Promise<void>((r) => (tx.oncomplete = () => r()));
  db.close();
  return out;
}
