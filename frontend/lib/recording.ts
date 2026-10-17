const DB = "lecture-studio-recordings";
export async function database(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const r = indexedDB.open(DB, 1);
    r.onupgradeneeded = () =>
      r.result.createObjectStore("chunks", { keyPath: "key" });
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
  });
}
export async function saveChunk(session: string, index: number, blob: Blob) {
  const db = await database();
  return new Promise<void>((resolve, reject) => {
    const tx = db.transaction("chunks", "readwrite");
    tx.objectStore("chunks").put({
      key: `${session}:${String(index).padStart(8, "0")}`,
      session,
      index,
      blob,
    });
    tx.oncomplete = () => {
      db.close();
      resolve();
    };
    tx.onerror = () => reject(tx.error);
  });
}
export async function recoveries(): Promise<string[]> {
  const db = await database();
  return new Promise((resolve, reject) => {
    const r = db.transaction("chunks").objectStore("chunks").getAll();
    r.onsuccess = () => {
      db.close();
      resolve([...new Set(r.result.map((x) => x.session))] as string[]);
    };
    r.onerror = () => reject(r.error);
  });
}
export async function recordingBlob(session: string) {
  const db = await database();
  return new Promise<Blob>((resolve, reject) => {
    const r = db.transaction("chunks").objectStore("chunks").getAll();
    r.onsuccess = () => {
      db.close();
      const all = r.result
        .filter((x) => x.session === session)
        .sort((a, b) => a.index - b.index);
      resolve(
        new Blob(
          all.map((x) => x.blob),
          { type: all[0]?.blob.type || "video/webm" },
        ),
      );
    };
    r.onerror = () => reject(r.error);
  });
}
export async function clearRecording(session: string) {
  const db = await database();
  return new Promise<void>((resolve, reject) => {
    const tx = db.transaction("chunks", "readwrite");
    const r = tx.objectStore("chunks").openCursor();
    r.onsuccess = () => {
      const c = r.result;
      if (c) {
        if (c.value.session === session) c.delete();
        c.continue();
      }
    };
    tx.oncomplete = () => {
      db.close();
      resolve();
    };
    tx.onerror = () => reject(tx.error);
  });
}
export function download(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 60000);
}
