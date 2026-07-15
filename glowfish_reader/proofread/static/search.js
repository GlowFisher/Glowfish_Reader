"use strict";
/* Glowfish Reader 史料阅读器 —— 右侧点校区关键词搜索（v2：单请求全库搜索）。
 * 简繁互通 + 忽略标点（后端 /api/library_search 用 opencc 归一，返回原文坐标区间）。
 * 结果列表点击 → 打开对应史料，跳到对应页对应段并选中/高亮。
 *
 * 改造：删除逐份加载循环，改为单次 POST /api/library_search；
 * 增加 AbortController 取消、超时保护、跳过文档提示、终态保证。 */
let searchHits = [];
let _searchTimer = null;
let _searchSeq = 0;
let _searchAbort = null;        // AbortController for the current search

const sEl = (id) => document.getElementById(id);
const searchEsc = (s) => String(s || "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

const SEARCH_TIMEOUT_MS = 30000;  // 30s client-side timeout

function searchToggle(force) {
  const p = sEl("searchPanel"); if (!p) return;
  const open = (force != null) ? force : p.classList.contains("hidden");
  p.classList.toggle("hidden", !open);
  if (open) { const i = sEl("searchInput"); i.focus(); i.select(); if (i.value.trim()) runSearch(); }
}

async function runSearch() {
  // Cancel any in-flight search
  if (_searchAbort) { _searchAbort.abort(); _searchAbort = null; }
  const seq = ++_searchSeq;

  const q = sEl("searchInput").value.trim();
  const results = sEl("searchResults"), count = sEl("searchCount");
  searchHits = [];

  // Guard: empty query
  if (!q) { results.innerHTML = ""; count.textContent = ""; return; }

  // Guard: wait for pending proof save to complete (ensures latest line.text is on disk)
  if (typeof gfAwaitSave === "function") {
    try { await gfAwaitSave(); } catch (e) {
      results.innerHTML = '<div class="sp-empty">当前修改尚未保存，无法保证搜索完整</div>';
      count.textContent = "";
      return;
    }
  }

  results.innerHTML = '<div class="sp-empty">检索中…</div>'; count.textContent = "";

  // Build AbortController + timeout
  const controller = new AbortController();
  _searchAbort = controller;
  const timeoutId = setTimeout(() => controller.abort(), SEARCH_TIMEOUT_MS);

  let resp;
  try {
    resp = await fetch("/api/library_search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q }),
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
  } catch (e) {
    clearTimeout(timeoutId);
    _searchAbort = null;
    if (seq !== _searchSeq) return;  // superseded
    if (e.name === "AbortError") {
      results.innerHTML = '<div class="sp-empty">检索超时或已取消</div>';
    } else {
      results.innerHTML = '<div class="sp-empty">搜索失败：' + searchEsc(e.message) + '</div>';
    }
    count.textContent = "";
    return;
  }
  _searchAbort = null;

  if (seq !== _searchSeq) return;  // superseded by newer search

  if (!resp.ok) {
    let errMsg = "搜索失败";
    try { const err = await resp.json(); errMsg = err.detail || errMsg; } catch (e) {}
    results.innerHTML = '<div class="sp-empty">' + searchEsc(errMsg) + '</div>';
    count.textContent = "";
    return;
  }

  let data;
  try { data = await resp.json(); } catch (e) {
    results.innerHTML = '<div class="sp-empty">搜索响应解析失败</div>';
    count.textContent = "";
    return;
  }

  // Merge hits
  searchHits = data.hits || [];
  const total = data.totalHits || searchHits.length;
  const skipped = data.skipped || [];
  const truncated = data.truncated || false;

  // Build status line
  let statusParts = [];
  if (total) statusParts.push("共 " + total + " 处");
  if (skipped.length) statusParts.push(skipped.length + " 篇文档无法检索");
  if (truncated) statusParts.push("结果已截断");
  count.textContent = statusParts.join(" · ");

  if (!searchHits.length) {
    results.innerHTML = '<div class="sp-empty">无匹配</div>';
    return;
  }

  // Render hit list
  results.innerHTML = "";
  searchHits.forEach((h) => {
    const text = h.text || "";
    const s = h.start, e = h.end;
    const a = Math.max(0, s - 12), b = Math.min(text.length, e + 12);
    const snip = (a > 0 ? "…" : "") + searchEsc(text.slice(a, s))
      + "<mark>" + searchEsc(text.slice(s, e)) + "</mark>"
      + searchEsc(text.slice(e, b)) + (b < text.length ? "…" : "");
    const row = document.createElement("div");
    row.className = "search-hit";
    row.title = h.docName;
    row.innerHTML = '<span class="sh-page"><span class="sh-doc-name">' + searchEsc(h.docName) + '</span>'
      + '<span class="sh-page-no"> · 第' + (h.pageIdx + 1) + '页</span></span>'
      + '<span class="sh-snip">' + snip + '</span>';
    row.addEventListener("click", () => gotoHit(h));
    results.appendChild(row);
  });
}

async function gotoHit(h) {
  const docId = h.batch || h.docId;
  if (!docId) {
    toast("搜索结果缺少文档标识，请重新搜索");
    return;
  }

  if (typeof proof === "undefined") return;

  // guard: save pending edits before opening another document
  if (typeof gfAwaitSave === "function") {
    try { await gfAwaitSave(); } catch (_) {}
  }

  if (!proof || proof.batch !== docId) {
    if (typeof nbOpenDoc !== "function") return;
    try { await nbOpenDoc(docId); } catch (e) {
      toast("无法打开搜索结果对应的史料");
      return;
    }
  }

  if (!proof || proof.batch !== docId) {
    toast("无法打开搜索结果对应的史料");
    return;
  }

  // locate page: prefer pageId match, fall back to pageIdx
  let targetPageIdx = h.pageIdx;
  if (h.pageId && proof.pages) {
    const byId = proof.pages.findIndex((p) => String(p.page_id) === String(h.pageId));
    if (byId >= 0) targetPageIdx = byId;
  }

  if (pageIdx !== targetPageIdx) { pageIdx = targetPageIdx; render(); }

  // verify line still exists
  if (h.lineId) {
    const lineExists = proof.pages[targetPageIdx]
      && proof.pages[targetPageIdx].lines
      && proof.pages[targetPageIdx].lines.some((l) => l.id === h.lineId && !l.deleted);
    if (!lineExists) {
      toast("搜索结果已过期，该文本已被修改或删除，请重新搜索");
      return;
    }
  }

  const mode = (typeof proofMode !== "undefined") ? proofMode : "row";
  if (mode === "page") {                       // 整页：换算命中在整页文本中的绝对偏移并选中
    const vo = (typeof visibleOrder === "function")
      ? visibleOrder() : page().order.filter((id) => { const l = lineById(id); return l && !l.deleted; });
    let abs = 0, found = false;
    for (const id of vo) {
      if (id === h.lineId) { abs += h.start; found = true; break; }
      const l = lineById(id); abs += (l ? (l.text || "").length : 0);
    }
    const el = sEl("pageText");
    if (el && found) {
      el.focus();
      if (typeof gfSelectAbs === "function") gfSelectAbs(el, abs, abs + (h.end - h.start));
    }
  } else {                                      // 逐行：定位行 + 选中区间 + 行高亮
    if (typeof focusLine === "function") focusLine(h.lineId, h.start);
    const esc = (window.CSS && CSS.escape) ? CSS.escape(h.lineId) : h.lineId;
    const rowEl = document.querySelector(`[data-id="${esc}"]`);
    if (rowEl) {
      rowEl.scrollIntoView({ block: "center", behavior: "smooth" });
      rowEl.classList.remove("search-flash"); void rowEl.offsetWidth; rowEl.classList.add("search-flash");
      selectInEditable(rowEl, h.start, h.end);
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
