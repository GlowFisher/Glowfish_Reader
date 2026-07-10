"use strict";
/* GlowFish 史料阅读器 —— 右侧点校区关键词搜索。
 * 放大镜（设置左侧）下拉面板：搜「全部笔记的全部史料」，简繁互通 + 忽略标点（后端 /api/proof_search 用 opencc 归一，
 * 返回原文坐标区间）。结果列表点击 → 打开对应史料，跳到对应页对应段并选中/高亮；逐行、整页两模式通用。
 * 复用 app.js(proof/pageIdx/page/lineById/render/api)、editor.js(proofMode/visibleOrder/focusLine)、notebook.js(nbTree/nbOpenDoc)。 */
let searchHits = [];
let _searchTimer = null;
let _searchSeq = 0;

const sEl = (id) => document.getElementById(id);
const searchEsc = (s) => String(s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

function searchToggle(force) {
  const p = sEl("searchPanel"); if (!p) return;
  const open = (force != null) ? force : p.classList.contains("hidden");
  p.classList.toggle("hidden", !open);
  if (open) { const i = sEl("searchInput"); i.focus(); i.select(); if (i.value.trim()) runSearch(); }
}

function searchDocIds() {
  if (typeof nbTree !== "undefined" && nbTree && nbTree.documents) return Object.keys(nbTree.documents);
  if (typeof proof !== "undefined" && proof && proof.batch) return [proof.batch];
  return [];
}

async function searchLoadProof(docId) {
  if (typeof proof !== "undefined" && proof && proof.batch === docId) return proof;
  try {
    if (typeof gfGet === "function") {
      const rec = await gfGet("proofs", docId);
      if (rec && rec.proof) return rec.proof;
    }
  } catch (e) {}
  const loaded = await api("/api/load?batch=" + encodeURIComponent(docId));
  return loaded && loaded.proof;
}

function searchDocName(docId, pf) {
  const meta = (typeof nbTree !== "undefined" && nbTree && nbTree.documents) ? nbTree.documents[docId] : null;
  return (meta && meta.displayName) || (pf && pf.source) || docId;
}

function searchGatherProof(pf, docId) {
  const entries = [];
  if (!pf) return entries;
  const docName = searchDocName(docId, pf);
  (pf.pages || []).forEach((pg, pi) => {
    (pg.order || []).forEach((id) => {
      const l = (pg.lines || []).find((x) => x.id === id);
      if (l && !l.deleted) entries.push({ docId, docName, pageIdx: pi, lineId: id, text: l.text || "" });
    });
  });
  return entries;
}

async function runSearch() {
  const seq = ++_searchSeq;
  const q = sEl("searchInput").value.trim();
  const results = sEl("searchResults"), count = sEl("searchCount");
  searchHits = [];
  if (!q) { results.innerHTML = ""; count.textContent = ""; return; }
  const docIds = searchDocIds();
  if (!docIds.length) { results.innerHTML = '<div class="sp-empty">暂无可检索史料</div>'; count.textContent = ""; return; }
  results.innerHTML = '<div class="sp-empty">检索中…</div>'; count.textContent = "";

  const entries = [];
  for (const docId of docIds) {
    try { entries.push(...searchGatherProof(await searchLoadProof(docId), docId)); }
    catch (e) {}
  }
  if (seq !== _searchSeq) return;
  if (!entries.length) { results.innerHTML = '<div class="sp-empty">暂无可检索文本</div>'; return; }

  let hits;
  try {
    const r = await api("/api/proof_search", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, items: entries.map((e) => ({ text: e.text })) }) });
    hits = r.hits || [];
  } catch (e) { results.innerHTML = '<div class="sp-empty">搜索失败：' + searchEsc(e.message) + '</div>'; count.textContent = ""; return; }
  if (seq !== _searchSeq) return;

  entries.forEach((e, k) => (hits[k] || []).forEach(([s, en]) => searchHits.push({
    docId: e.docId, docName: e.docName, pageIdx: e.pageIdx, lineId: e.lineId, text: e.text, s, e: en
  })));
  count.textContent = searchHits.length ? ("共 " + searchHits.length + " 处") : "";
  if (!searchHits.length) { results.innerHTML = '<div class="sp-empty">无匹配</div>'; return; }
  results.innerHTML = "";
  searchHits.forEach((h) => {
    const a = Math.max(0, h.s - 12), b = Math.min(h.text.length, h.e + 12);
    const snip = (a > 0 ? "…" : "") + searchEsc(h.text.slice(a, h.s))
      + "<mark>" + searchEsc(h.text.slice(h.s, h.e)) + "</mark>"
      + searchEsc(h.text.slice(h.e, b)) + (b < h.text.length ? "…" : "");
    const row = document.createElement("div");
    row.className = "search-hit";
    row.innerHTML = '<span class="sh-page">' + searchEsc(h.docName) + ' · 第' + (h.pageIdx + 1) + '页</span><span class="sh-snip">' + snip + '</span>';
    row.addEventListener("click", () => gotoHit(h));
    results.appendChild(row);
  });
}

async function gotoHit(h) {
  if (typeof proof === "undefined") return;
  if (!proof || proof.batch !== h.docId) {
    if (typeof nbOpenDoc === "function") await nbOpenDoc(h.docId);
    else return;
  }
  if (!proof || proof.batch !== h.docId) return;
  if (pageIdx !== h.pageIdx) { pageIdx = h.pageIdx; render(); }
  const mode = (typeof proofMode !== "undefined") ? proofMode : "row";
  if (mode === "page") {                       // 整页：换算命中在整页文本中的绝对偏移并选中
    const vo = (typeof visibleOrder === "function")
      ? visibleOrder() : page().order.filter((id) => { const l = lineById(id); return l && !l.deleted; });
    let abs = 0, found = false;
    for (const id of vo) {
      if (id === h.lineId) { abs += h.s; found = true; break; }
      const l = lineById(id); abs += (l ? (l.text || "").length : 0);   // 整页为无换行拼接
    }
    const el = sEl("pageText");
    if (el && found) {                          // v2：整页是 contenteditable div → 树 walker 选区 + 滚动到命中
      el.focus();
      if (typeof gfSelectAbs === "function") gfSelectAbs(el, abs, abs + (h.e - h.s));
    }
  } else {                                      // 逐行：定位行 + 选中区间 + 行高亮
    if (typeof focusLine === "function") focusLine(h.lineId, h.s);
    const esc = (window.CSS && CSS.escape) ? CSS.escape(h.lineId) : h.lineId;
    const rowEl = document.querySelector(`[data-id="${esc}"]`);
    if (rowEl) {
      rowEl.scrollIntoView({ block: "center", behavior: "smooth" });
      rowEl.classList.remove("search-flash"); void rowEl.offsetWidth; rowEl.classList.add("search-flash");
      selectInEditable(rowEl, h.s, h.e);
    }
  }
}

// 在 contenteditable(.txt/.v-txt，可能含红标多文本节点)里选中 [s,e) 区间
function selectInEditable(rowEl, s, e) {
  const el = rowEl.querySelector(".txt, .v-txt"); if (!el) return;
  try {
    el.focus();
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
    const range = document.createRange();
    let node = walker.nextNode(), pos = 0, state = 0;
    while (node) {
      const len = node.textContent.length;
      if (state === 0 && s <= pos + len) { range.setStart(node, s - pos); state = 1; }
      if (state === 1 && e <= pos + len) { range.setEnd(node, e - pos); state = 2; break; }
      pos += len; node = walker.nextNode();
    }
    if (state === 2) { const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range); }
  } catch (err) { /* 选区失败不影响跳转 */ }
}

function initSearch() {
  const btn = sEl("searchBtn");
  if (btn) btn.addEventListener("click", (e) => { e.stopPropagation(); searchToggle(); });
  const inp = sEl("searchInput");
  if (inp) {
    inp.addEventListener("input", () => { clearTimeout(_searchTimer); _searchTimer = setTimeout(runSearch, 250); });
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { clearTimeout(_searchTimer); runSearch(); }
      else if (e.key === "Escape") searchToggle(false);
    });
  }
  document.addEventListener("click", (e) => {     // 点面板外关闭
    const p = sEl("searchPanel"); if (!p || p.classList.contains("hidden")) return;
    const b = sEl("searchBtn");
    if (!p.contains(e.target) && !(b && b.contains(e.target))) searchToggle(false);
  });
}

initSearch();
