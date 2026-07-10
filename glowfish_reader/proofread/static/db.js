"use strict";
/* GlowFish 史料阅读器 —— 本地持久化层 (IndexedDB)。
 * 定位：缓存/索引层。缓存每份 proof 供刷新/重启「瞬时恢复」；笔记本树、文档索引、版本快照亦存于此。
 * 后端磁盘 _work/ 仍是 proof.json + 原图的持久源与取图来源。全程本机浏览器，无任何云端/上传。
 *
 * Stores：
 *   notebooks  {id,name,tags[],archived,created,updated,order,documentIds[]}      —— 顶层笔记本
 *   documents  {id(=batch),notebookId,displayName,order,pageCount,thumb?,createdAt} —— 中层源史料索引
 *   proofs     {batch, proof, savedAt}                                            —— 整份 proof 缓存（含批注字段）
 *   snapshots  {id, batch, label, ts, proof}                                      —— 版本快照
 *   appstate   {key:'last', notebookId, batch, pageIdx, source}                   —— 上次打开位置
 */
const GF_DB_NAME = "glowfish-reader";
const GF_DB_VER = 1;
const GF_SAVE_DEBOUNCE_MS = 1500;   // 自动保存防抖
const GF_SNAPSHOT_KEEP = 30;        // 每个 batch 保留的版本快照上限（防 IndexedDB 无限增长）
let _gfDbPromise = null;

function gfDbOpen() {
  if (_gfDbPromise) return _gfDbPromise;
  _gfDbPromise = new Promise((resolve, reject) => {
    let req;
    try { req = indexedDB.open(GF_DB_NAME, GF_DB_VER); }
    catch (e) { reject(e); return; }
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      if (!db.objectStoreNames.contains("notebooks")) db.createObjectStore("notebooks", { keyPath: "id" });
      if (!db.objectStoreNames.contains("documents")) {
        const s = db.createObjectStore("documents", { keyPath: "id" });
        s.createIndex("notebookId", "notebookId", { unique: false });
      }
      if (!db.objectStoreNames.contains("proofs")) db.createObjectStore("proofs", { keyPath: "batch" });
      if (!db.objectStoreNames.contains("snapshots")) {
        const s = db.createObjectStore("snapshots", { keyPath: "id" });
        s.createIndex("batch", "batch", { unique: false });
      }
      if (!db.objectStoreNames.contains("appstate")) db.createObjectStore("appstate", { keyPath: "key" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
  return _gfDbPromise;
}

function _gfReq(r) {
  return new Promise((resolve, reject) => {
    r.onsuccess = () => resolve(r.result);
    r.onerror = () => reject(r.error);
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
  const os = await _gfStore(store, "readonly");
  return _gfReq(os.index(indexName).getAll(key));
}

// ===== 与编排层(app.js)对接的高层接口 =====

/** 把当前内存中的 proof 写入本地缓存，并记录「上次打开」位置（瞬时恢复用）。 */
async function gfCacheProof() {
  try {
    if (typeof proof === "undefined" || !proof || !proof.batch) return;
    await gfPut("proofs", { batch: proof.batch, proof, savedAt: Date.now() });
    await gfPut("appstate", {
      key: "last",
      notebookId: (typeof currentNotebookId !== "undefined" ? currentNotebookId : null),
      batch: proof.batch,
      pageIdx: (typeof pageIdx !== "undefined" ? pageIdx : 0),
      source: proof.source || proof.batch,
    });
  } catch (e) { /* 本地缓存失败不阻断使用 */ }
}

let _gfSaveTimer = null;
/** 自动保存：编辑过程中频繁调用，1.5s 防抖后并行写「本地缓存 + 后端磁盘」（均在本机，无云端）。 */
function gfScheduleSave() {
  clearTimeout(_gfSaveTimer);
  _gfSaveTimer = setTimeout(() => { gfCacheProof(); gfDiskSave(); }, GF_SAVE_DEBOUNCE_MS);
}

/** 按 batch 只保留最近 GF_SNAPSHOT_KEEP 条快照，多余的删除（失败静默，不影响保存）。 */
async function _gfPruneSnapshots(batch) {
  try {
    const all = await gfAllByIndex("snapshots", "batch", batch);
    all.sort((a, b) => (b.ts || 0) - (a.ts || 0));
    for (const s of all.slice(GF_SNAPSHOT_KEEP)) await gfDel("snapshots", s.id);
  } catch (e) { /* 清理失败不影响保存 */ }
}

/** 自动保存到后端磁盘 _work/<batch>/proof.json（durable backstop，失败静默）。 */
async function gfDiskSave() {
  try {
    if (typeof proof === "undefined" || !proof || !proof.batch) return;
    await api("/api/save", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ proof }) });
  } catch (e) { /* 自动保存失败不打扰用户 */ }
}

/** 快照保存：把当前状态存为一个带时间戳的版本快照（IndexedDB），并顺带落盘最新状态。 */
async function gfSnapshotSave() {
  if (typeof proof === "undefined" || !proof || !proof.batch) { if (typeof toast === "function") toast("无可保存内容"); return; }
  try {
    await gfDiskSave();
    await gfCacheProof();
    const ts = Date.now();
    const d = new Date(ts);
    const p2 = (x) => String(x).padStart(2, "0");
    const label = `${d.getFullYear()}-${p2(d.getMonth() + 1)}-${p2(d.getDate())} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
    await gfPut("snapshots", { id: proof.batch + "_" + ts, batch: proof.batch, label, ts,
      proof: JSON.parse(JSON.stringify(proof)) });
    await _gfPruneSnapshots(proof.batch);
    if (typeof toast === "function") toast("已保存");
  } catch (e) { if (typeof toast === "function") toast("快照失败：" + e.message); }
}

/** 启动时尝试从本地缓存恢复上次文档（无网络往返、无白屏）。返回是否恢复成功。 */
async function gfRestoreLast() {
  try {
    if (typeof proof !== "undefined" && proof) return false;     // 已有内容则不覆盖
    const last = await gfGet("appstate", "last");
    if (!last || !last.batch) return false;
    const rec = await gfGet("proofs", last.batch);
    if (!rec || !rec.proof) return false;
    applyLoaded({
      proof: rec.proof,
      low_conf: (typeof lowConf !== "undefined" ? lowConf : 0.85),
      source: rec.proof.source || last.source || last.batch,
    });
    if (last.pageIdx && last.pageIdx < proof.pages.length) { pageIdx = last.pageIdx; render(); }
    if (typeof toast === "function") toast("已从本地恢复上次进度");
    return true;
  } catch (e) { return false; }
}
