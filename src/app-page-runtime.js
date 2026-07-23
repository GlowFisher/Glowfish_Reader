"use strict";
/* Compatibility bridge: legacy renderer sees only the active page body. */
let gfPageSession = null;
let _gfOpenToken = 0;
let _gfMoveToken = 0;
let _gfMoveBusy = false;
const _gfBusyReasons = new Set();

function gfSetDocumentBusy(reason, isBusy) {
  if (isBusy) _gfBusyReasons.add(reason);
  else _gfBusyReasons.delete(reason);
  const busy = _gfBusyReasons.size > 0;
  document.body.classList.toggle("gf-document-loading", busy);
  for (const id of ["prevPage", "nextPage", "scriptBtn", "saveBtn"]) {
    const control = document.querySelector("#" + id);
    if (control) control.disabled = busy;
  }
}

function _gfInvalidatePageMoves() {
  _gfMoveToken++;
  _gfMoveBusy = false;
  gfSetDocumentBusy("page", false);
}

function _gfActivatePage(item, session = gfPageSession) {
  if (!session || session !== gfPageSession) return false;
  const meta = session.documentMeta;
  pageIdx = session.pageIdx;
  proof = { ...meta, pages: meta.pages.map((descriptor) => ({ ...descriptor })) };
  proof.pages[pageIdx] = item.page;
  batch = session.activeBatch;
  imgVer = Date.now();
  undoStack = []; redoStack = []; updateHist();
  updateScriptBtn();
  currentLayout = settings.text_layout || "horizontal";
  proofMode = settings.proof_mode || "page";
  syncLayoutButtons();
  if (typeof syncProofModeButtons === "function") syncProofModeButtons();
  for (const id of ["canvasNav", "layoutBtn", "scriptBtn", "hist", "statPage", "statDelta"])
    document.querySelector("#" + id).classList.remove("hidden");
  render();
  if (typeof gfCacheProof === "function") gfCacheProof();
  if (typeof nbOnDocLoaded === "function") nbOnDocLoaded();
  return true;
}

async function gfOpenPagedDocument(batchName, requestedPage = 0) {
  const token = ++_gfOpenToken;
  _gfInvalidatePageMoves();
  gfSetDocumentBusy("open", true);
  const session = new GlowfishPageSession(GlowfishApi.reader);
  try {
    const item = await session.open(batchName, requestedPage);
    if (token !== _gfOpenToken) return false;
    gfPageSession = session;
    return _gfActivatePage(item, session);
  } finally {
    if (token === _gfOpenToken) gfSetDocumentBusy("open", false);
  }
}

async function applyLoaded(data) {
  const batchName = data && (data.batch || (data.proof && data.proof.batch));
  if (!batchName) throw new Error("missing batch");
  lowConf = data.low_conf || lowConf;
  return gfOpenPagedDocument(batchName, 0);
}

async function _gfMovePage(nextIndex) {
  if (!gfPageSession || _gfMoveBusy) return false;
  const session = gfPageSession;
  const token = ++_gfMoveToken;
  _gfMoveBusy = true;
  gfSetDocumentBusy("page", true);
  try {
    const item = await session.goto(nextIndex);
    if (token !== _gfMoveToken || session !== gfPageSession) return false;
    return _gfActivatePage(item, session);
  } catch (error) {
    if (token === _gfMoveToken && session === gfPageSession)
      toast("\u9875\u9762\u4fdd\u5b58\u6216\u52a0\u8f7d\u5931\u8d25\uff1a" + error.message);
    return false;
  } finally {
    if (token === _gfMoveToken) {
      _gfMoveBusy = false;
      gfSetDocumentBusy("page", false);
    }
  }
}

async function pageNext() {
  if (!proof) return;
  if (pageIdx < proof.pages.length - 1) return _gfMovePage(pageIdx + 1);
  const ids = (typeof nbDocIds === "function") ? nbDocIds() : [];
  const index = ids.indexOf(proof.batch);
  if (index >= 0 && index < ids.length - 1 && typeof nbOpenDoc === "function") return nbOpenDoc(ids[index + 1]);
}

async function pagePrev() {
  if (!proof) return;
  if (pageIdx > 0) return _gfMovePage(pageIdx - 1);
  const ids = (typeof nbDocIds === "function") ? nbDocIds() : [];
  const index = ids.indexOf(proof.batch);
  if (index > 0 && typeof nbOpenDoc === "function") return nbOpenDoc(ids[index - 1], true);
}

function gfMarkCurrentPageDirty() {
  if (gfPageSession) gfPageSession.markDirty();
}

/* Document-wide script conversion is a server-side page job, never a proof upload. */
async function toggleScript() {
  if (!proof || !gfPageSession) return;
  const session = gfPageSession;
  const target = proof.script === "s" ? "t" : "s";
  toast(target === "t" ? "Converting to traditional..." : "Converting to simplified...");
  gfSetDocumentBusy("convert", true);
  try {
    await session.flushAll();
    if (session !== gfPageSession) return;
    await api("/api/convert", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batch: session.activeBatch, to: target }) });
    if (session !== gfPageSession) return;
    await gfOpenPagedDocument(session.activeBatch, pageIdx);
  } catch (error) {
    toast("Conversion failed: " + error.message);
  } finally {
    gfSetDocumentBusy("convert", false);
  }
}

/* Paging and script conversion controls are owned by this runtime. */
if (typeof bindClick === "function") {
  bindClick("prevPage", pagePrev);
  bindClick("nextPage", pageNext);
  bindClick("scriptBtn", toggleScript);
}
