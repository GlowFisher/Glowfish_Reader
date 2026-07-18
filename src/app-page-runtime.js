"use strict";
/* Compatibility bridge: legacy renderer sees only the active page body. */
let gfPageSession = null;
let _gfOpenToken = 0;

function _gfActivatePage(item) {
  const meta = gfPageSession.documentMeta;
  pageIdx = gfPageSession.pageIdx;
  proof = { ...meta, pages: meta.pages.map((descriptor) => ({ ...descriptor })) };
  proof.pages[pageIdx] = item.page;
  batch = gfPageSession.activeBatch;
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
}

async function gfOpenPagedDocument(batchName, requestedPage = 0) {
  const token = ++_gfOpenToken;
  const session = new GlowfishPageSession(GlowfishApi.reader);
  const item = await session.open(batchName, requestedPage);
  if (token !== _gfOpenToken) return false;
  gfPageSession = session;
  _gfActivatePage(item);
  return true;
}

async function applyLoaded(data) {
  const batchName = data && (data.batch || (data.proof && data.proof.batch));
  if (!batchName) throw new Error("missing batch");
  lowConf = data.low_conf || lowConf;
  return gfOpenPagedDocument(batchName, 0);
}

async function _gfMovePage(nextIndex) {
  if (!gfPageSession) return;
  try {
    const item = await gfPageSession.goto(nextIndex);
    _gfActivatePage(item);
  } catch (error) {
    toast("页面保存或加载失败：" + error.message);
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
