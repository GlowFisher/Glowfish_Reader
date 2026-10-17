"use strict";
/* Remove legacy body caches without a database version bump. */
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

gfClearLegacyLongDocCaches();

async function gfWatchDocumentTask(jobId, onProgress) {
  // 30 分钟硬性超时（400ms 轮询 ≈ 4500 次），防止后端任务卡在非终态导致无限轮询
  const DEADLINE = Date.now() + 30 * 60 * 1000;
  for (;;) {
    let status;
    try {
      status = await GlowfishApi.reader.taskStatus(jobId);
    } catch (err) {
      throw new Error("任务状态查询失败：" + (err && err.message ? err.message : "网络错误"));
    }
    if (typeof onProgress === "function") onProgress(status);
    if (["done", "failed", "cancelled"].includes(status.state)) return status;
    if (Date.now() > DEADLINE) {
      throw new Error("任务执行超时（超过 30 分钟），请检查后重试");
    }
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