"use strict";
/* IndexedDB contains navigation metadata only. Page bodies remain in DocumentRepository. */
const GF_DB_NAME = "glowfish-reader";
const GF_DB_VER = 1;
const GF_SAVE_DEBOUNCE_MS = 1500;
let _gfDbPromise = null;

function gfDbOpen() {
  if (_gfDbPromise) return _gfDbPromise;
  _gfDbPromise = new Promise((resolve, reject) => {
    let req;
    try { req = indexedDB.open(GF_DB_NAME, GF_DB_VER); }
    catch (error) { reject(error); return; }
    req.onupgradeneeded = (event) => {
      const db = event.target.result;
      if (!db.objectStoreNames.contains("notebooks")) db.createObjectStore("notebooks", { keyPath: "id" });
      if (!db.objectStoreNames.contains("documents")) {
        const store = db.createObjectStore("documents", { keyPath: "id" });
        store.createIndex("notebookId", "notebookId", { unique: false });
      }
      if (!db.objectStoreNames.contains("appstate")) db.createObjectStore("appstate", { keyPath: "key" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return _gfDbPromise;
}

function _gfReq(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function _gfStore(store, mode) {
  const db = await gfDbOpen();
  return db.transaction(store, mode).objectStore(store);
}
async function gfPut(store, value) { return _gfReq((await _gfStore(store, "readwrite")).put(value)); }
async function gfGet(store, key) { return _gfReq((await _gfStore(store, "readonly")).get(key)); }
async function gfDel(store, key) { return _gfReq((await _gfStore(store, "readwrite")).delete(key)); }
async function gfAll(store) { return _gfReq((await _gfStore(store, "readonly")).getAll()); }
async function gfAllByIndex(store, indexName, key) {
  const objectStore = await _gfStore(store, "readonly");
  return _gfReq(objectStore.index(indexName).getAll(key));
}

async function gfCacheProof() {
  try {
    if (typeof proof === "undefined" || !proof || !proof.batch) return;
    await gfPut("appstate", {
      key: "last",
      notebookId: (typeof currentNotebookId !== "undefined" ? currentNotebookId : null),
      batch: proof.batch,
      pageIdx: (typeof pageIdx !== "undefined" ? pageIdx : 0),
      source: proof.source || proof.batch,
    });
  } catch (_) {}
}

let _gfPageSaveTimer = null;
let _gfPageSavePromise = Promise.resolve();
function gfScheduleSave() {
  clearTimeout(_gfPageSaveTimer);
  _gfPageSaveTimer = setTimeout(() => {
    _gfPageSaveTimer = null;
    _gfPageSavePromise = _gfPageSavePromise.then(async () => {
      await gfCacheProof();
      if (typeof gfPageSession !== "undefined" && gfPageSession) await gfPageSession.flushCurrent();
    }).catch(() => {});
  }, GF_SAVE_DEBOUNCE_MS);
}

async function gfDiskSave() {
  if (typeof gfPageSession !== "undefined" && gfPageSession) await gfPageSession.flushAll();
}

async function gfAwaitSave() {
  if (_gfPageSaveTimer) {
    clearTimeout(_gfPageSaveTimer);
    _gfPageSaveTimer = null;
  }
  await gfCacheProof();
  await _gfPageSavePromise;
  await gfDiskSave();
}

async function gfSnapshotSave() {
  if (typeof proof === "undefined" || !proof || !proof.batch) return;
  await gfAwaitSave();
  const task = await GlowfishApi.reader.checkpoint(proof.batch);
  if (!task || !task.job_id) throw new Error("checkpoint task was not created");
}

async function gfRestoreLast() {
  try {
    if (typeof proof !== "undefined" && proof) return false;
    const last = await gfGet("appstate", "last");
    if (!last || !last.batch || typeof gfOpenPagedDocument !== "function") return false;
    return await gfOpenPagedDocument(last.batch, last.pageIdx || 0);
  } catch (_) { return false; }
}