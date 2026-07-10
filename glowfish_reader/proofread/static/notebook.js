"use strict";
/* GlowFish 史料阅读器 —— 顶层 Notebook 知识库（导航 + 顶层状态机）。
 * 一个 Notebook = 一份独立研究课题，收纳多条中层「源史料」(=后端 batch / 一份 proof)。
 * 树结构存 IndexedDB(appstate.nbtree) 供瞬时首屏 + 后端 _work/notebooks.json 持久备份。
 * 打开文档 → 走 app.js 现有 applyLoaded；不改动中层画布/底层分段编辑。 */

let nbTree = { notebooks: [], documents: {} };
let currentNotebookId = null;     // db.js gfCacheProof 会读它（记录文档归属）
let nbActiveDocId = null;
let nbOpenState = {};             // notebookId -> 展开
let nbModalMode = "new", nbModalTarget = null;
let nbDelTarget = null;
let nbDrag = null;
let nbActivePop = null;
let nbAnnotTarget = null;          // 当前编辑批注的笔记本 id
let nbTipEl = null;                // 钢笔悬浮浮窗
let nbExportPickMode = false;
let nbExportSelectedPages = {};      // batch -> {page_id: true}
let nbExportPageCache = {};          // batch -> [{page_id,label}]
let nbExportLoadingDocs = {};
let nbDeletePickMode = false;
let nbDeleteSelectedDocs = {};        // batch -> true
let nbDeleteScopeDocs = {};           // batch -> true
let nbDocClickTimer = null;
const NB_PEN_SVG = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>';
const NB_TRASH_SVG = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M10 11v6M14 11v6"/></svg>';

const NB_NAV_MIN_W = 170, NB_NAV_MAX_W = 460;   // 导航栏拖拽宽度区间
const nbId = () => "nb_" + Date.now().toString(36) + "_" + Math.random().toString(36).slice(2, 7);
// 拖拽落点判定：用 viewport 坐标算行中线，避免 e.offsetY 随命中子元素（名称/计数）漂移
const nbDragBefore = (e, rowEl) => { const r = rowEl.getBoundingClientRect(); return e.clientY < r.top + r.height / 2; };
const nbById = (id) => nbTree.notebooks.find((n) => n.id === id) || null;
const nbCur = () => nbById(currentNotebookId);
const nbMaxNbOrder = () => nbTree.notebooks.reduce((m, n) => Math.max(m, n.order || 0), -1);
const nbEsc = (s) => String(s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

function nbExportTreeDocIds() {
  return Object.keys(nbTree.documents || {}).sort((a, b) => {
    const da = nbTree.documents[a] || {}, db = nbTree.documents[b] || {};
    return String(da.notebookId || "").localeCompare(String(db.notebookId || "")) || (da.order || 0) - (db.order || 0);
  });
}
function nbExportDocIds() {
  const nb = nbCur();
  const ids = nb ? nbDeepDocIds(nb.id) : [];
  return ids.length ? ids : nbExportTreeDocIds();
}
function nbOpenNotebookAncestors(id) {
  let nb = nbById(id);
  while (nb) {
    nbOpenState[nb.id] = true;
    nb = nb.parentId ? nbById(nb.parentId) : null;
  }
}
function nbExportPageLabel(pg, idx) {
  const id = String((pg && pg.page_id) || "");
  const m = /_p(\d+)$/.exec(id);
  return m ? `第${m[1]}页` : `第${idx + 1}页`;
}
async function nbEnsureExportPages(docId) {
  if (nbExportPageCache[docId]) return nbExportPageCache[docId];
  if (nbExportLoadingDocs[docId]) return nbExportLoadingDocs[docId];
  nbExportLoadingDocs[docId] = (async () => {
    let pf = null;
    if (proof && proof.batch === docId) pf = proof;
    if (!pf) {
      try { const rec = await gfGet("proofs", docId); if (rec && rec.proof) pf = rec.proof; } catch (e) {}
    }
    if (!pf) {
      try { const loaded = await api("/api/load?batch=" + encodeURIComponent(docId)); pf = loaded && loaded.proof; } catch (e) {}
    }
    const pages = ((pf && pf.pages) || []).map((pg, i) => ({ page_id: pg.page_id, label: nbExportPageLabel(pg, i) }));
    nbExportPageCache[docId] = pages;
    delete nbExportLoadingDocs[docId];
    return pages;
  })();
  return nbExportLoadingDocs[docId];
}
function nbExportSelectedSet(docId) {
  if (!nbExportSelectedPages[docId]) nbExportSelectedPages[docId] = {};
  return nbExportSelectedPages[docId];
}
function nbExportSelectedCount() {
  return Object.values(nbExportSelectedPages).reduce((n, set) => n + Object.keys(set || {}).length, 0);
}
function nbExportSelectedPayload() {
  return Object.keys(nbExportSelectedPages).map((batch) => ({
    batch, page_ids: Object.keys(nbExportSelectedPages[batch] || {})
  })).filter((item) => item.page_ids.length);
}
function nbRenderExportPickBar() {
  const nav = document.getElementById("nbNav"); if (!nav) return;
  let bar = document.getElementById("nbExportPickBar");
  if (!nbExportPickMode) { if (bar) bar.remove(); return; }
  if (!bar) {
    bar = nbEl("div", { id: "nbExportPickBar", class: "nb-export-bar" }, [
      nbEl("span", { class: "nb-export-count" }),
      nbEl("button", { class: "btn btn-main nb-export-go", text: "导出选中", onclick: () => { if (typeof doExport === "function") doExport("selected_pages"); } }),
      nbEl("button", { class: "btn btn-sec nb-export-cancel", text: "取消", onclick: nbCancelExportPageSelect }),
    ]);
    const head = document.getElementById("nbHead");
    if (head && head.nextSibling) nav.insertBefore(bar, head.nextSibling); else nav.insertBefore(bar, nav.firstChild);
  }
  const count = nbExportSelectedCount();
  const label = bar.querySelector(".nb-export-count"); if (label) label.textContent = count ? `已选 ${count} 页` : "选择要导出的页面";
  const go = bar.querySelector(".nb-export-go"); if (go) go.disabled = !count;
}
async function nbPreloadExportPages() {
  for (const docId of nbExportDocIds()) {
    await nbEnsureExportPages(docId);
    if (nbExportPickMode) { renderTree(); nbRenderExportPickBar(); }
  }
}
function nbStartExportPageSelect() {
  const ids = nbExportDocIds();
  if (!ids.length) { toast("当前笔记本无史料"); return; }
  if (nbDeletePickMode) nbCancelDeleteDocSelect();
  nbExportPickMode = true;
  nbExportSelectedPages = {};
  ids.forEach((docId) => {
    const meta = nbTree.documents[docId];
    if (meta && meta.notebookId) nbOpenNotebookAncestors(meta.notebookId);
  });
  const nb = nbCur(); if (nb) nbOpenState[nb.id] = true;
  renderTree(); nbRenderExportPickBar(); nbPreloadExportPages();
  toast("请在左侧目录勾选要导出的文件");
}
function nbCancelExportPageSelect() {
  nbExportPickMode = false;
  nbExportSelectedPages = {};
  nbRenderExportPickBar(); renderTree();
}
function nbFinishExportPageSelect() { nbCancelExportPageSelect(); }
async function nbToggleExportDoc(docId, checked) {
  const pages = await nbEnsureExportPages(docId);
  if (checked) {
    const set = nbExportSelectedSet(docId);
    pages.forEach((pg) => { if (pg.page_id) set[pg.page_id] = true; });
  } else delete nbExportSelectedPages[docId];
  renderTree(); nbRenderExportPickBar();
}

function nbOpenNotebookDescendants(id) {
  nbOpenState[id] = true;
  nbChildrenOf(id).forEach((child) => nbOpenNotebookDescendants(child.id));
}
function nbDeleteSelectedCount() {
  return Object.keys(nbDeleteSelectedDocs || {}).length;
}
function nbRenderDeletePickBar() {
  const nav = document.getElementById("nbNav"); if (!nav) return;
  let bar = document.getElementById("nbDeletePickBar");
  if (!nbDeletePickMode) { if (bar) bar.remove(); return; }
  if (!bar) {
    bar = nbEl("div", { id: "nbDeletePickBar", class: "nb-export-bar nb-delete-bar" }, [
      nbEl("span", { class: "nb-export-count nb-delete-count" }),
      nbEl("button", { class: "btn danger nb-delete-go", text: "删除选中", onclick: nbConfirmDeleteSelectedDocs }),
      nbEl("button", { class: "btn btn-sec nb-export-cancel", text: "取消", onclick: nbCancelDeleteDocSelect }),
    ]);
    const head = document.getElementById("nbHead");
    if (head && head.nextSibling) nav.insertBefore(bar, head.nextSibling); else nav.insertBefore(bar, nav.firstChild);
  }
  const count = nbDeleteSelectedCount();
  const label = bar.querySelector(".nb-delete-count"); if (label) label.textContent = count ? `已选 ${count} 个文件` : "选择要删除的文件";
  const go = bar.querySelector(".nb-delete-go"); if (go) go.disabled = !count;
}
function nbStartDeleteDocSelect(folderId) {
  const ids = nbDeepDocIds(folderId);
  if (!ids.length) { toast("当前文件夹无史料"); return; }
  if (nbExportPickMode) nbCancelExportPageSelect();
  nbDeletePickMode = true;
  nbDeleteSelectedDocs = {};
  nbDeleteScopeDocs = {};
  ids.forEach((docId) => { nbDeleteScopeDocs[docId] = true; });
  nbOpenNotebookAncestors(folderId);
  nbOpenNotebookDescendants(folderId);
  renderTree(); nbRenderDeletePickBar();
  toast("请在左侧目录勾选要删除的文件");
}
function nbCancelDeleteDocSelect() {
  nbDeletePickMode = false;
  nbDeleteSelectedDocs = {};
  nbDeleteScopeDocs = {};
  nbRenderDeletePickBar(); renderTree();
}
function nbToggleDeleteDoc(docId, checked) {
  if (checked) nbDeleteSelectedDocs[docId] = true;
  else delete nbDeleteSelectedDocs[docId];
  nbRenderDeletePickBar();
}
function nbConfirmDeleteSelectedDocs() {
  const ids = Object.keys(nbDeleteSelectedDocs || {}).filter((id) => nbTree.documents[id]);
  if (!ids.length) { nbRenderDeletePickBar(); return; }
  nbDelTarget = { type: "docs", ids };
  document.getElementById("nbDelMsg").innerHTML =
    `确认彻底删除选中的 ${ids.length} 个史料文件？<br>原图、识别文本、批注将从本机磁盘与浏览器一并销毁，无法恢复。`;
  document.getElementById("nbDelModal").classList.remove("hidden");
}

function nbDocsOf(id) {
  const nb = nbById(id); if (!nb) return [];
  nb.documentIds = nb.documentIds || [];
  return nb.documentIds.map((d) => Object.assign({ id: d }, nbTree.documents[d]))
    .filter((d) => nbTree.documents[d.id]).sort((a, b) => (a.order || 0) - (b.order || 0));
}
function nbChildrenOf(parentId) {
  return nbTree.notebooks.filter((n) => (n.parentId || null) === (parentId || null))
    .sort((a, b) => (a.archived ? 1 : 0) - (b.archived ? 1 : 0) || (a.order || 0) - (b.order || 0));
}
function nbDeepDocIds(id) {
  const nb = nbById(id); if (!nb) return [];
  let out = (nb.documentIds || []).slice();
  nbChildrenOf(id).forEach((child) => { out = out.concat(nbDeepDocIds(child.id)); });
  return out;
}
function nbIsDescendant(id, possibleAncestor) {
  let cur = nbById(id);
  while (cur && cur.parentId) {
    if (cur.parentId === possibleAncestor) return true;
    cur = nbById(cur.parentId);
  }
  return false;
}
function nbDropMode(e, rowEl) {
  const r = rowEl.getBoundingClientRect();
  const y = (e.clientY - r.top) / Math.max(1, r.height);
  if (y < 0.25) return "before";
  if (y > 0.75) return "after";
  return "into";
}
function nbEnsureDefault() {
  let nb = nbTree.notebooks.find((n) => !n.archived) || nbTree.notebooks[0];
  if (!nb) {
    nb = { id: nbId(), name: "我的史料", tags: [], archived: false,
           created: Date.now(), updated: Date.now(), order: 0, documentIds: [] };
    nbTree.notebooks.push(nb);
  }
  return nb;
}

function nbEnsureImportFolders() {
  const nb = nbEnsureDefault();
  document.body.classList.remove("nb-empty");
  const w = document.getElementById("nbWelcome"); if (w) w.classList.add("hidden");
  return nb;
}
function nbImportDefaultFolderId() {
  const nb = nbCur() || nbEnsureImportFolders();
  return nb ? nb.id : null;
}
function nbImportFolderOptions() {
  nbEnsureImportFolders();
  const out = [];
  const seen = new Set();
  const walk = (parentId, depth, prefix) => {
    nbChildrenOf(parentId).forEach((nb) => {
      if (!nb || seen.has(nb.id)) return;
      seen.add(nb.id);
      const path = prefix ? prefix + " / " + nb.name : nb.name;
      out.push({ id: nb.id, name: nb.name, depth, path });
      walk(nb.id, depth + 1, path);
    });
  };
  walk(null, 0, "");
  nbTree.notebooks.forEach((nb) => {
    if (nb && !seen.has(nb.id)) {
      seen.add(nb.id);
      out.push({ id: nb.id, name: nb.name, depth: 0, path: nb.name });
    }
  });
  return out;
}
function nbRefreshImportTargets() {
  if (!document.getElementById("impTargetSelect")) return;
  if (typeof impRenderTargetFolders === "function") impRenderTargetFolders();
}
function nbCreateImportFolder(name) {
  name = String(name || "").trim();
  if (!name) return null;
  const order = nbChildrenOf(null).reduce((m, n) => Math.max(m, n.order || 0), -1) + 1;
  const nb = { id: nbId(), name, tags: [], parentId: null, archived: false,
    created: Date.now(), updated: Date.now(), order, documentIds: [] };
  nbTree.notebooks.push(nb);
  currentNotebookId = nb.id;
  nbOpenState[nb.id] = true;
  document.body.classList.remove("nb-empty");
  const w = document.getElementById("nbWelcome"); if (w) w.classList.add("hidden");
  nbSaveTree(); renderTree();
  return nb.id;
}
// ---------- DOM 构造小工具 ----------
function nbEl(tag, props, kids) {
  const e = document.createElement(tag);
  for (const k in (props || {})) {
    if (k === "class") e.className = props[k];
    else if (k === "text") e.textContent = props[k];
    else if (k === "html") e.innerHTML = props[k];
    else if (k.slice(0, 2) === "on") e.addEventListener(k.slice(2), props[k]);
    else if (props[k] != null) e.setAttribute(k, props[k]);
  }
  (kids || []).forEach((c) => c && e.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
  return e;
}

// ---------- 持久化 ----------
async function nbSaveTree() {
  try { await gfPut("appstate", { key: "nbtree", tree: nbTree }); } catch (e) {}
  try {
    await api("/api/notebooks", { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(nbTree) });
  } catch (e) {}
}
function nbMergeDisk(cache, disk) {
  const tree = { notebooks: (disk.notebooks || []).slice(),
                 documents: Object.assign({}, disk.documents || {}) };
  if (cache && cache.documents) {                  // 折入磁盘缺失但本地缓存有的文档（POST 竞态兜底）
    for (const id in cache.documents) {
      if (tree.documents[id]) continue;
      const meta = cache.documents[id];
      const nb = tree.notebooks.find((n) => n.id === meta.notebookId) || tree.notebooks[0];
      if (nb) { tree.documents[id] = meta; if (!nb.documentIds.includes(id)) nb.documentIds.push(id); }
    }
  }
  return tree;
}

// ---------- 渲染 ----------
function renderTree() {
  const root = document.getElementById("nbTree");
  if (!root) return;
  const hasNb = nbTree.notebooks.length > 0;
  document.body.classList.toggle("nb-empty", !hasNb);
  const w = document.getElementById("nbWelcome");
  if (w) w.classList.toggle("hidden", hasNb);
  root.innerHTML = "";
  const nbs = nbChildrenOf(null);
  nbs.forEach((nb) => root.appendChild(nbItemEl(nb, 0)));
}

function nbItemEl(nb, depth) {
  const open = !!nbOpenState[nb.id];
  const docs = nbDocsOf(nb.id), children = nbChildrenOf(nb.id);
  const row = nbEl("div", { class: "nb-row" }, [
    nbEl("span", { class: "nb-caret", text: "▶" }),
    nbEl("span", { class: "nb-name", text: nb.name, title: nb.name }),
    nbEl("span", { class: "nb-count", text: docs.length ? String(docs.length) : "" }),
    // 钢笔批注图标：永久固定显示（有/无批注均显示）；hover 弹白框浮窗展示全部批注，点击编辑
    nbEl("button", { class: "btn nb-pen-btn" + (nb.annot ? " has" : ""), title: "笔记本批注", html: NB_PEN_SVG,
      onclick: (e) => { e.stopPropagation(); nbOpenAnnot(nb.id); },
      onmouseenter: (e) => nbShowTip(e.currentTarget, nbById(nb.id) && nbById(nb.id).annot),
      onmouseleave: () => nbHideTip() }),
    nbEl("button", { class: "btn nb-menu-btn", text: "⋯", title: "笔记本操作",
      onclick: (e) => { e.stopPropagation(); nbMenu(e.currentTarget, nb); } }),
  ]);
  row.addEventListener("click", () => { nbOpenState[nb.id] = !open; renderTree(); });
  const item = nbEl("div", { class: "nb-item" + (open ? " open" : "") + (nb.archived ? " archived" : "") }, [row]);
  item.style.setProperty("--nb-depth", String(depth || 0));
  item.dataset.nb = nb.id;
  // 笔记本本身可拖拽重排；同时作为「拖史料入本」的放置目标
  row.draggable = true;
  row.addEventListener("dragstart", (e) => { e.stopPropagation(); nbDrag = { kind: "nb", id: nb.id }; item.classList.add("nb-drag-src"); e.dataTransfer.effectAllowed = "move"; });
  row.addEventListener("dragend", () => { item.classList.remove("nb-drag-src"); nbClearDrop(); nbDrag = null; });
  row.addEventListener("dragover", (e) => {
    if (!nbDrag) return; e.preventDefault(); nbClearDrop();
    if (nbDrag.kind === "doc") item.classList.add("nb-drop-into");
    else if (nbDrag.kind === "nb" && nbDrag.id !== nb.id && !nbIsDescendant(nb.id, nbDrag.id)) {
      const mode = nbDropMode(e, row);
      item.classList.add(mode === "before" ? "nb-drop-before" : mode === "after" ? "nb-drop-after" : "nb-drop-into");
    }
  });
  row.addEventListener("drop", (e) => {
    if (!nbDrag) return; e.preventDefault();
    if (nbDrag.kind === "doc") nbMoveDoc(nbDrag.docId, nb.id, null, false);
    else if (nbDrag.kind === "nb" && nbDrag.id !== nb.id && !nbIsDescendant(nb.id, nbDrag.id)) nbMoveFolder(nbDrag.id, nb.id, nbDropMode(e, row));
    nbClearDrop();
  });
  // v2：导航不再显示笔记本标签（手写/印刷等体裁标记）；标签数据与新建/重命名弹窗字段保留
  if (open) {
    const dwrap = nbEl("div", { class: "nb-docs" });
    children.forEach((child) => dwrap.appendChild(nbItemEl(child, (depth || 0) + 1)));
    if (!docs.length && !children.length) dwrap.appendChild(nbEl("div", { class: "nb-empty", text: "（空，点顶部「导入」添加史料）" }));
    docs.forEach((d) => {
      dwrap.appendChild(nbDocEl(nb, d));
    });
    item.appendChild(dwrap);
  }
  return item;
}

function nbDocEl(nb, d) {
  const thumb = nbEl("img", { class: "nb-doc-thumb", alt: "" });
  if (d.firstPage) thumb.src = `/img/${encodeURIComponent(d.id)}/${encodeURIComponent(d.firstPage)}?t=thumb`;
  thumb.addEventListener("error", () => { thumb.style.visibility = "hidden"; });
  const name = d.displayName || d.id;
  const nameInput = nbEl("input", { class: "nb-doc-name", value: name, title: name, readonly: true, autocomplete: "off", spellcheck: "false" });
  nameInput.addEventListener("dblclick", (e) => {
    e.preventDefault(); e.stopPropagation();
    if (nbDocClickTimer) { clearTimeout(nbDocClickTimer); nbDocClickTimer = null; }
    nbStartDocNameEdit(nameInput, d.id);
  });
  const kids = [
    thumb,
    nbEl("div", { class: "nb-doc-meta" }, [
      nameInput,
      nbEl("div", { class: "nb-doc-sub", text: (d.pageCount || 0) + " 页" }),
    ]),
  ];
  if (nbExportPickMode) {
    const pages = nbExportPageCache[d.id] || [];
    const selected = nbExportSelectedPages[d.id] || {};
    const box = nbEl("input", { type: "checkbox", class: "nb-export-doc-check", title: "选择此文件全部页面" });
    const selectedCount = Object.keys(selected).length;
    box.checked = !!pages.length && selectedCount === pages.length;
    box.indeterminate = selectedCount > 0 && (!pages.length || selectedCount < pages.length);
    box.addEventListener("click", (e) => e.stopPropagation());
    box.addEventListener("change", (e) => { e.stopPropagation(); nbToggleExportDoc(d.id, box.checked); });
    kids.push(nbEl("label", { class: "nb-export-doc-wrap", title: "选择此文件全部页面" }, [box]));
  }
  const canPickDelete = nbDeletePickMode && !!nbDeleteScopeDocs[d.id];
  if (canPickDelete) {
    const box = nbEl("input", { type: "checkbox", class: "nb-export-doc-check nb-pick-doc-check", title: "选择此文件删除" });
    box.checked = !!nbDeleteSelectedDocs[d.id];
    box.addEventListener("click", (e) => e.stopPropagation());
    box.addEventListener("change", (e) => { e.stopPropagation(); nbToggleDeleteDoc(d.id, box.checked); });
    kids.push(nbEl("label", { class: "nb-export-doc-wrap nb-pick-doc-wrap", title: "选择此文件删除" }, [box]));
  }
  if (!nbExportPickMode && !nbDeletePickMode) {
    kids.push(nbEl("button", { class: "btn nb-doc-del", title: "删除该史料（原图/分段/批注一并销毁）", html: NB_TRASH_SVG,
      onclick: (e) => { e.stopPropagation(); nbAskDelete("doc", d.id, d.displayName || d.id); } }));
  }
  const row = nbEl("div", { class: "nb-doc" + (d.id === nbActiveDocId ? " active" : "") }, kids);
  row.dataset.doc = d.id;
  row.addEventListener("click", (e) => {
    if (e.target.closest(".nb-doc-name")) {
      if (nbDocClickTimer) clearTimeout(nbDocClickTimer);
      nbDocClickTimer = setTimeout(() => nbOpenDoc(d.id), 220);
      return;
    }
    if (nbDocClickTimer) { clearTimeout(nbDocClickTimer); nbDocClickTimer = null; }
    nbOpenDoc(d.id);
  });
  row.draggable = true;
  row.addEventListener("dragstart", (e) => { e.stopPropagation(); nbDrag = { kind: "doc", docId: d.id, fromNb: nb.id }; row.classList.add("nb-drag-src"); e.dataTransfer.effectAllowed = "move"; });
  row.addEventListener("dragend", () => { row.classList.remove("nb-drag-src"); nbClearDrop(); nbDrag = null; });
  row.addEventListener("dragover", (e) => { if (!nbDrag || nbDrag.kind !== "doc") return; e.preventDefault(); nbClearDrop(); row.classList.add(nbDragBefore(e, row) ? "nb-drop-before" : "nb-drop-after"); });
  row.addEventListener("drop", (e) => { if (!nbDrag || nbDrag.kind !== "doc") return; e.preventDefault(); const before = nbDragBefore(e, row); nbClearDrop(); nbMoveDoc(nbDrag.docId, nb.id, d.id, before); });
  return row;
}
function nbClearDrop() {
  document.querySelectorAll(".nb-drop-before,.nb-drop-after,.nb-drop-into")
    .forEach((e) => e.classList.remove("nb-drop-before", "nb-drop-after", "nb-drop-into"));
}

// ---------- popover 菜单 ----------
function nbClosePop() { if (nbActivePop) { nbActivePop.remove(); nbActivePop = null; document.removeEventListener("click", nbClosePop); } }
function nbPopover(anchor, items) {
  nbClosePop();
  const pop = nbEl("div", { class: "popover nb-pop" });
  items.forEach((it) => {
    if (it.sep) { pop.appendChild(nbEl("div", { class: "nb-pop-sep" })); return; }
    pop.appendChild(nbEl("button", { text: it.label, class: it.danger ? "danger-item" : "",
      onclick: (e) => { e.stopPropagation(); nbClosePop(); it.onClick && it.onClick(); } }));
  });
  document.body.appendChild(pop);
  const r = anchor && typeof anchor.getBoundingClientRect === "function"
    ? anchor.getBoundingClientRect() : { left: anchor.x || 0, bottom: anchor.y || 0 };
  pop.style.left = Math.max(8, Math.min(r.left, window.innerWidth - pop.offsetWidth - 8)) + "px";
  pop.style.top = Math.max(8, Math.min((r.bottom || r.y || 0) + 4, window.innerHeight - pop.offsetHeight - 8)) + "px";
  nbActivePop = pop;
  setTimeout(() => document.addEventListener("click", nbClosePop), 0);
}
function nbMenu(anchor, nb) {
  nbPopover(anchor, [
    { label: "新建子文件夹", onClick: () => nbOpenModal("newChild", nb.id) },
    { label: "重命名", onClick: () => nbOpenModal("rename", nb.id) },
    { sep: true },
    { label: "批量删除", danger: true, onClick: () => nbStartDeleteDocSelect(nb.id) },
    { label: "删除文件夹", danger: true, onClick: () => nbAskDelete("nb", nb.id, nb.name, nbDeepDocIds(nb.id).length) },
  ]);
}
async function nbRenameDoc(docId, name) {
  const meta = nbTree.documents[docId];
  if (!meta) return false;
  name = String(name || "").trim();
  if (!name) { toast("请输入文件名称"); return false; }
  meta.displayName = name;
  if (typeof proof !== "undefined" && proof && proof.batch === docId) {
    proof.source = name;
    try { await api("/api/save", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ proof }) }); } catch (e) {}
    try { if (typeof gfCacheProof === "function") await gfCacheProof(); } catch (e) {}
  }
  await nbSaveTree();
  renderTree();
  return true;
}
function nbStartDocNameEdit(input, docId) {
  const meta = nbTree.documents[docId];
  if (!meta || input.classList.contains("editing")) return;
  const oldName = meta.displayName || docId;
  input.dataset.oldName = oldName;
  input.value = oldName;
  input.removeAttribute("readonly");
  input.classList.add("editing");
  let done = false;
  const finish = async (save) => {
    if (done) return;
    done = true;
    const next = input.value.trim();
    input.setAttribute("readonly", "true");
    input.classList.remove("editing");
    if (save) {
      if (!next) { input.value = oldName; input.title = oldName; toast("请输入文件名称"); return; }
      input.value = next;
      input.title = next;
      await nbRenameDoc(docId, next);
      return;
    }
    input.value = oldName;
    input.title = oldName;
  };
  input.addEventListener("click", nbDocEditStop, true);
  input.addEventListener("dblclick", nbDocEditStop, true);
  input.addEventListener("mousedown", nbDocEditStop, true);
  input.addEventListener("keydown", nbDocEditKeydown);
  input.addEventListener("blur", nbDocEditBlur, { once: true });
  function cleanup() {
    input.removeEventListener("click", nbDocEditStop, true);
    input.removeEventListener("dblclick", nbDocEditStop, true);
    input.removeEventListener("mousedown", nbDocEditStop, true);
    input.removeEventListener("keydown", nbDocEditKeydown);
  }
  function nbDocEditStop(e) { e.stopPropagation(); }
  function nbDocEditKeydown(e) {
    e.stopPropagation();
    if (e.key === "Enter") { e.preventDefault(); cleanup(); finish(true); input.blur(); }
    else if (e.key === "Escape") { e.preventDefault(); input.value = oldName; cleanup(); finish(false); input.blur(); }
  }
  function nbDocEditBlur() { cleanup(); finish(true); }
  input.focus();
  input.select();
}

// 文件夹拖拽移动：上下边缘为同级排序，中间为移入目标文件夹。
function nbMoveFolder(dragId, targetId, mode) {
  const drag = nbById(dragId), target = nbById(targetId);
  if (!drag || !target || drag.id === target.id || nbIsDescendant(target.id, drag.id)) return;
  if (mode === "into") {
    drag.parentId = target.id;
    drag.order = nbChildrenOf(target.id).reduce((m, n) => Math.max(m, n.order || 0), -1) + 1;
    nbOpenState[target.id] = true;
  } else {
    const parentId = target.parentId || null;
    const siblings = nbChildrenOf(parentId).filter((n) => n.id !== drag.id);
    const ti = siblings.findIndex((n) => n.id === target.id);
    const at = ti < 0 ? siblings.length : (mode === "before" ? ti : ti + 1);
    drag.parentId = parentId;
    siblings.splice(at, 0, drag);
    siblings.forEach((n, i) => { n.order = i; });
  }
  nbSaveTree(); renderTree(); nbRefreshImportTargets();
}

// ---------- 笔记本全局批注（钢笔图标） ----------
function nbOpenAnnot(id) {
  const nb = nbById(id); if (!nb) return;
  nbHideTip();
  nbAnnotTarget = id;
  document.getElementById("nbAnnotTitle").textContent = "笔记本批注 · " + nb.name;
  document.getElementById("nbAnnotText").value = nb.annot || "";
  document.getElementById("nbAnnotModal").classList.remove("hidden");
  setTimeout(() => document.getElementById("nbAnnotText").focus(), 30);
}
function nbAnnotSubmit() {
  const nb = nbById(nbAnnotTarget);
  if (nb) { nb.annot = document.getElementById("nbAnnotText").value; nb.updated = Date.now(); nbSaveTree(); }
  document.getElementById("nbAnnotModal").classList.add("hidden");
  nbAnnotTarget = null; renderTree();
}
function nbShowTip(anchor, text) {
  nbHideTip();
  const t = (text || "").trim();
  nbTipEl = nbEl("div", { class: "nb-tip", text: t || "（暂无批注，点钢笔添加）" });
  document.body.appendChild(nbTipEl);
  const r = anchor.getBoundingClientRect();
  nbTipEl.style.left = Math.min(r.left, window.innerWidth - nbTipEl.offsetWidth - 10) + "px";
  nbTipEl.style.top = (r.bottom + 5) + "px";
}
function nbHideTip() { if (nbTipEl) { nbTipEl.remove(); nbTipEl = null; } }

// ---------- 文档移动/重排 ----------
function nbMoveDoc(docId, toNb, beforeDocId, before) {
  const meta = nbTree.documents[docId]; if (!meta) return;
  const from = nbById(meta.notebookId);
  if (from) from.documentIds = from.documentIds.filter((x) => x !== docId);
  const to = nbById(toNb); if (!to) return;
  to.documentIds = to.documentIds.filter((x) => x !== docId);
  let idx = to.documentIds.length;
  if (beforeDocId) { const at = to.documentIds.indexOf(beforeDocId); if (at >= 0) idx = before ? at : at + 1; }
  to.documentIds.splice(idx, 0, docId);
  meta.notebookId = toNb;
  to.documentIds.forEach((id, i) => { if (nbTree.documents[id]) nbTree.documents[id].order = i; });
  nbOpenState[toNb] = true;
  if (nbActiveDocId === docId) currentNotebookId = toNb;
  nbSaveTree(); renderTree();
}

// ---------- 打开文档 ----------
async function nbOpenDoc(id, gotoLast) {
  if (proof && proof.batch === id) {
    nbActiveDocId = id; renderTree();
    if (gotoLast && proof.pages.length) { pageIdx = proof.pages.length - 1; render(); }
    return;
  }
  let loaded = null, diskErr = null;
  try { loaded = await api("/api/load?batch=" + encodeURIComponent(id)); }
  catch (e) { diskErr = e; }
  if (loaded && loaded.proof) {
    applyLoaded(loaded);
  } else {
    let rec = null;
    try { rec = await gfGet("proofs", id); } catch (e) {}
    if (rec && rec.proof) {
      applyLoaded({ proof: rec.proof, low_conf: (typeof lowConf !== "undefined" ? lowConf : 0.85), source: rec.proof.source || id });
      if (diskErr) toast("已从本地缓存打开；原图目录可能缺失");
    } else {
      toast("打开失败：" + (diskErr ? diskErr.message : "文档不存在")); return;
    }
  }
  if (gotoLast && proof && proof.pages.length) { pageIdx = proof.pages.length - 1; render(); }
}

// 导入完成可只登记进左栏，不强行切走当前正在浏览的旧史料。
function nbRegisterProofDoc(pf, activate, targetNotebookId) {
  if (!pf || !pf.batch) return;
  const id = pf.batch;
  const targetNb = nbById(targetNotebookId) || nbCur() || nbEnsureDefault();
  if (!nbTree.documents[id]) {
    const nb = targetNb;
    const ord = nb.documentIds.reduce((m, x) => Math.max(m, (nbTree.documents[x] || {}).order || 0), -1) + 1;
    nbTree.documents[id] = { notebookId: nb.id, displayName: pf.source || id, order: ord,
      pageCount: (pf.pages || []).length, firstPage: (pf.pages || [])[0] && pf.pages[0].page_id,
      createdAt: Date.now() };
    if (!nb.documentIds.includes(id)) nb.documentIds.push(id);
    nbOpenState[nb.id] = true;
  } else {
    const meta = nbTree.documents[id];
    if (targetNotebookId && targetNb && meta.notebookId !== targetNb.id) {
      const oldNb = nbById(meta.notebookId);
      if (oldNb) oldNb.documentIds = (oldNb.documentIds || []).filter((x) => x !== id);
      targetNb.documentIds = (targetNb.documentIds || []).filter((x) => x !== id);
      targetNb.documentIds.push(id);
      meta.notebookId = targetNb.id;
      meta.order = targetNb.documentIds.length - 1;
      nbOpenState[targetNb.id] = true;
    }
    meta.pageCount = (pf.pages || []).length;
    meta.displayName = pf.source || meta.displayName || id;
    if (!meta.firstPage && pf.pages && pf.pages[0]) meta.firstPage = pf.pages[0].page_id;
  }
  if (activate) {
    const meta = nbTree.documents[id];
    currentNotebookId = meta.notebookId; nbOpenState[meta.notebookId] = true; nbActiveDocId = id;
  }
  document.body.classList.remove("nb-empty");
  const w = document.getElementById("nbWelcome"); if (w) w.classList.add("hidden");
  nbSaveTree(); renderTree();
}
// applyLoaded 之后由 app.js 调用：新导入→登记到当前笔记本；既有→标记激活
function nbOnDocLoaded() {
  if (!proof || !proof.batch) return;
  nbRegisterProofDoc(proof, true);
}

// ---------- 新建/重命名弹窗 ----------
function nbOpenModal(mode, target) {
  nbModalMode = mode; nbModalTarget = target || null;
  const name = document.getElementById("nbModalName"), tags = document.getElementById("nbModalTags");
  document.getElementById("nbModalTitle").textContent = (mode === "rename") ? "编辑文件夹" : "新建文件夹";
  if (mode === "new" || mode === "newChild") { name.value = ""; tags.value = ""; }
  else { const nb = nbById(target); name.value = nb ? nb.name : ""; tags.value = nb ? (nb.tags || []).join("，") : ""; }
  document.getElementById("nbModal").classList.remove("hidden");
  setTimeout(() => name.focus(), 30);
}
function nbModalSubmit() {
  const name = document.getElementById("nbModalName").value.trim();
  const tags = document.getElementById("nbModalTags").value.split(/[，,]/).map((s) => s.trim()).filter(Boolean);
  if (!name) { toast("请输入名称"); return; }
  if (nbModalMode === "new" || nbModalMode === "newChild") {
    const parentId = nbModalMode === "newChild" ? nbModalTarget : null;
    const order = nbChildrenOf(parentId).reduce((m, n) => Math.max(m, n.order || 0), -1) + 1;
    const nb = { id: nbId(), name, tags, parentId, archived: false, created: Date.now(), updated: Date.now(), order, documentIds: [] };
    nbTree.notebooks.push(nb); currentNotebookId = nb.id; nbOpenState[nb.id] = true;
  } else {
    const nb = nbById(nbModalTarget); if (nb) { nb.name = name; nb.tags = tags; nb.updated = Date.now(); }
  }
  document.getElementById("nbModal").classList.add("hidden");
  nbSaveTree(); renderTree(); nbRefreshImportTargets();
}

// ---------- 删除（彻底销毁） ----------
function nbAskDelete(type, id, name, count) {
  nbDelTarget = { type, id };
  document.getElementById("nbDelMsg").innerHTML = type === "nb"
    ? `确认彻底删除笔记本「${nbEsc(name)}」及其 ${count} 份史料？<br>原图、识别文本、批注将从本机磁盘与浏览器一并销毁，无法恢复。`
    : `确认彻底删除史料「${nbEsc(name)}」？<br>原图、识别文本、批注将从本机一并销毁，无法恢复。`;
  document.getElementById("nbDelModal").classList.remove("hidden");
}
async function nbDoDelete() {
  document.getElementById("nbDelModal").classList.add("hidden");
  const tg = nbDelTarget; nbDelTarget = null; if (!tg) return;
  if (tg.type === "doc") { await nbDestroyDoc(tg.id); }
  else if (tg.type === "docs") {
    for (const docId of tg.ids || []) await nbDestroyDoc(docId);
    nbDeletePickMode = false;
    nbDeleteSelectedDocs = {};
    nbDeleteScopeDocs = {};
    nbRenderDeletePickBar();
  }
  else {
    const nb = nbById(tg.id); if (!nb) return;
    for (const docId of nbDeepDocIds(tg.id)) await nbDestroyDoc(docId, true);
    const doomed = [tg.id];
    for (let i = 0; i < doomed.length; i++) nbChildrenOf(doomed[i]).forEach((n) => doomed.push(n.id));
    nbTree.notebooks = nbTree.notebooks.filter((n) => !doomed.includes(n.id));
    if (currentNotebookId === tg.id) currentNotebookId = null;
  }
  nbSaveTree(); renderTree();
}
async function nbDestroyDoc(id, skipTree) {
  try { await api("/api/delete_batch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ batch: id }) }); } catch (e) {}
  try { await gfDel("proofs", id); } catch (e) {}
  if (!skipTree) {
    const meta = nbTree.documents[id];
    if (meta) { const nb = nbById(meta.notebookId); if (nb) nb.documentIds = nb.documentIds.filter((x) => x !== id); }
  }
  delete nbTree.documents[id];
  if (nbActiveDocId === id) { nbActiveDocId = null; nbCloseActive(); }
}
function nbCloseActive() {
  proof = null; batch = null; pageIdx = 0;
  const set = (id, fn) => { const e = document.getElementById(id); if (e) fn(e); };
  set("editorBody", (e) => (e.innerHTML = ""));
  set("pageImg", (e) => e.removeAttribute("src"));
  set("boxes", (e) => (e.innerHTML = ""));
  ["canvasNav", "layoutBtn", "scriptBtn", "hist", "statPage", "statDelta"]
    .forEach((id) => set(id, (e) => e.classList.add("hidden")));   // 保存/导入/导出 永久固定，不隐藏
  set("srcName", (e) => (e.textContent = "点击导入史料…"));
  if (typeof annRefresh === "function") annRefresh();   // 关闭文档后隐藏批注面板
  if (typeof gfUpdateBlank === "function") gfUpdateBlank();   // 切到空白占位
}

// ---------- 复制副本 ----------
async function nbDuplicate(nb) {
  toast("正在复制副本…");
  const copy = { id: nbId(), name: nb.name + " 副本", tags: (nb.tags || []).slice(), archived: false,
                 created: Date.now(), updated: Date.now(), order: nbMaxNbOrder() + 1, documentIds: [] };
  nbTree.notebooks.push(copy);
  let ord = 0;
  for (const docId of nb.documentIds) {
    try {
      const r = await api("/api/copy_batch", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ batch: docId }) });
      const src = nbTree.documents[docId] || {};
      nbTree.documents[r.batch] = { notebookId: copy.id, displayName: src.displayName || r.batch, order: ord++,
        pageCount: (r.proof.pages || []).length, firstPage: (r.proof.pages || [])[0] && r.proof.pages[0].page_id, createdAt: Date.now() };
      copy.documentIds.push(r.batch);
      try { await gfPut("proofs", { batch: r.batch, proof: r.proof, savedAt: Date.now() }); } catch (e) {}
    } catch (e) {}
  }
  nbOpenState[copy.id] = true;
  nbSaveTree(); renderTree(); toast("已复制副本");
}

// ---------- 导航宽度拖拽 ----------
function nbInitResize() {
  const bar = document.getElementById("nbResize"), nav = document.getElementById("nbNav");
  if (!bar || !nav) return;
  let drag = false;
  bar.addEventListener("mousedown", (e) => { drag = true; e.preventDefault(); document.body.style.cursor = "col-resize"; });
  window.addEventListener("mousemove", (e) => { if (!drag) return; const w = Math.max(NB_NAV_MIN_W, Math.min(NB_NAV_MAX_W, e.clientX)); nav.style.flexBasis = w + "px"; });
  window.addEventListener("mouseup", () => { if (drag) { drag = false; document.body.style.cursor = ""; } });
}

// ---------- 初始化 ----------
function nbShowSkeleton() {
  const root = document.getElementById("nbTree");
  if (!root) return;
  root.innerHTML = '<div class="gf-skel-row"></div><div class="gf-skel-row sub"></div>'
    + '<div class="gf-skel-row sub"></div><div class="gf-skel-row"></div>';
}

async function initNotebooks() {
  nbShowSkeleton();   // 宣纸骨架屏占位，数据就绪后由 renderTree 替换
  try { const cached = await gfGet("appstate", "nbtree"); if (cached && cached.tree) { nbTree = cached.tree; renderTree(); } } catch (e) {}
  try { const disk = await api("/api/notebooks"); if (disk && Array.isArray(disk.notebooks)) nbTree = nbMergeDisk(nbTree, disk); } catch (e) {}
  try { const last = await gfGet("appstate", "last"); if (last && last.batch) { nbActiveDocId = last.batch; currentNotebookId = last.notebookId || (nbTree.documents[last.batch] || {}).notebookId || null; } } catch (e) {}
  if (currentNotebookId) nbOpenState[currentNotebookId] = true;
  else if (nbTree.notebooks[0]) nbOpenState[nbTree.notebooks[0].id] = true;
  renderTree();
  nbRefreshImportTargets();
  await nbSaveTree();
}

function initNotebookUI() {
  const bind = (id, ev, fn) => { const e = document.getElementById(id); if (e) e.addEventListener(ev, fn); };
  bind("nbNewBtn", "click", () => nbOpenModal("new"));
  bind("nbWelcomeNew", "click", () => nbOpenModal("new"));
  bind("nbModalOk", "click", nbModalSubmit);
  bind("nbModalCancel", "click", () => document.getElementById("nbModal").classList.add("hidden"));
  bind("nbModalName", "keydown", (e) => { if (e.key === "Enter") nbModalSubmit(); });
  bind("nbDelConfirm", "click", nbDoDelete);
  bind("nbDelCancel", "click", () => { nbDelTarget = null; document.getElementById("nbDelModal").classList.add("hidden"); });
  bind("nbAnnotOk", "click", nbAnnotSubmit);
  bind("nbAnnotCancel", "click", () => { nbAnnotTarget = null; document.getElementById("nbAnnotModal").classList.add("hidden"); });
  nbInitResize();
  initNotebooks();
}

initNotebookUI();



