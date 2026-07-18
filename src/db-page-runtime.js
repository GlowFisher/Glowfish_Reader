"use strict";
/* Page architecture persistence overrides. Keep IndexedDB metadata-only without a version bump. */
async function gfCacheProof() {
  try {
    if (!proof || !proof.batch) return;
    await gfPut("appstate", {
      key: "last",
      notebookId: (typeof currentNotebookId !== "undefined" ? currentNotebookId : null),
      batch: proof.batch,
      pageIdx,
      source: proof.source || proof.batch,
    });
  } catch (_) {}
}

async function gfClearLegacyLongDocCaches() {
  try {
    const db = await gfDbOpen();
    for (const name of ["proofs", "snapshots"]) {
      if (db.objectStoreNames.contains(name)) {
        await _gfReq(db.transaction(name, "readwrite").objectStore(name).clear());
      }
    }
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
      if (gfPageSession) await gfPageSession.flushCurrent();
    }).catch(() => {});
  }, GF_SAVE_DEBOUNCE_MS);
}

async function gfDiskSave() {
  if (gfPageSession) {
    await gfPageSession.flushAll();
    return;
  }
}

async function gfAwaitSave() {
  if (_gfPageSaveTimer) {
    clearTimeout(_gfPageSaveTimer);
    _gfPageSaveTimer = null;
  }
  await gfCacheProof();
  await gfDiskSave();
}

async function gfSnapshotSave() {
  if (!proof || !proof.batch) return;
  await gfAwaitSave();
  if (GlowfishApi && GlowfishApi.reader) await GlowfishApi.reader.checkpoint(proof.batch);
  if (typeof toast === "function") toast("已保存");
}

async function gfRestoreLast() {
  try {
    if (proof) return false;
    const last = await gfGet("appstate", "last");
    if (!last || !last.batch || typeof gfOpenPagedDocument !== "function") return false;
    return await gfOpenPagedDocument(last.batch, last.pageIdx || 0);
  } catch (_) { return false; }
}

gfClearLegacyLongDocCaches();

async function gfWatchDocumentTask(jobId, onProgress) {
  for (;;) {
    const status = await GlowfishApi.reader.taskStatus(jobId);
    if (typeof onProgress === "function") onProgress(status);
    if (["done", "failed", "cancelled"].includes(status.state)) return status;
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
}

gfSnapshotSave = async function () {
  if (!proof || !proof.batch) return;
  await gfAwaitSave();
  const task = await GlowfishApi.reader.checkpoint(proof.batch);
  if (!task || !task.job_id) throw new Error("checkpoint task was not created");
  if (typeof toast === "function") toast("Saving compatibility snapshot in background...");
  gfWatchDocumentTask(task.job_id).then((status) => {
    if (typeof toast !== "function") return;
    toast(status.state === "done" ? "Saved" : "Snapshot failed: " + (status.error || status.state));
  }).catch(() => { if (typeof toast === "function") toast("Snapshot status unavailable"); });
};
