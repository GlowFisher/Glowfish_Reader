"use strict";
/* GlowFish 史料阅读器 —— 顶层批注层 v2（视觉再设计 v2：划选即批）。
 * 批注全部内嵌进 proof，随自动保存写入 IndexedDB + 后端磁盘，不改底层分段编辑逻辑：
 *   page.page_annot    本页总批
 *   page.annots        划批 [{id, quote, occ, note}] —— quote + 第 occ 次出现锚定；
 *                      整页正文改动致找不到 → 列表保留并标「失锚」，不丢批注
 *   line.annot         存量段批（旧版数据，只读列出、点击定位）
 * 交互：整页点校中划拉选中文字 → 浮「＋批注」→ 落朱色划批标记；点标记/列表条目后在主面板编辑。 */
let annLineId = null;      // 逐行模式当前点选段（「拆回原始块」仍用）
let annCollapsed = true;
let gfPopAnnId = null;     // 当前打开批注小签的划批 id
let gfPill = null, gfPop = null;
let annPanelPos = null;
let annDragState = null;
const ANN_PANEL_MIN_W = 280, ANN_PANEL_MIN_H = 180;
const ANN_PANEL_MARGIN = 8;
const ANN_TRASH_SVG = '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m2 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6M10 11v6M14 11v6"/></svg>';

const annEl = (id) => document.getElementById(id);
const gfPageEl = () => document.getElementById("pageText");
const gfAnnots = () => { const pg = page(); if (!Array.isArray(pg.annots)) pg.annots = []; return pg.annots; };
function annFitTextarea(ta) {
  if (!ta) return;
  const max = ta.classList && ta.classList.contains("ann-note-edit") ? 130 : 160;
  ta.style.height = "1px";
  const next = Math.min(Math.max(ta.scrollHeight, 24), max);
  ta.style.height = next + "px";
}

/* ============ 整页版面渲染（editor.js renderPage 调用）：红掩码 + 划批标记 → innerHTML ============ */
function gfPageRedMask() {
  let mask = [];
  for (const id of visibleOrder()) { const l = lineById(id); ensureRed(l); mask = mask.concat(l.red); }
  return mask;
}
function gfResolveMarks(text) {          // 划批 → [{start,end,id}]；找不到第 occ 次出现 → 标 _lost
  const marks = [];
  for (const a of gfAnnots()) {
    if (!a.quote) { a._lost = true; continue; }
    let idx = -1, from = 0;
    for (let k = 0; k <= (a.occ | 0); k++) { idx = text.indexOf(a.quote, from); if (idx < 0) break; from = idx + 1; }
    a._lost = idx < 0;
    if (idx < 0) continue;
    const end = idx + a.quote.length;
    if (marks.some((m) => idx < m.end && end > m.start)) continue;   // 与已画标记重叠：本条不画（列表仍在）
    marks.push({ start: idx, end, id: a.id });
  }
  return marks;
}
function gfPageRender(div) {             // 按 (红, 标记) 分段包 span；无任何标记/红字时退化为纯文本
  const text = assemblePageText();
  const red = gfPageRedMask();
  const marks = gfResolveMarks(text);
  if (!marks.length && !red.some(Boolean)) { div.textContent = text; return; }
  const markAt = (i) => { for (const m of marks) if (i >= m.start && i < m.end) return m.id; return null; };
  let html = "", run = "", curR = false, curM = null;
  const flush = () => {
    if (!run) return;
    let seg = escHTML(run);
    if (curR) seg = '<span class="lc">' + seg + "</span>";
    if (curM) seg = '<span class="gf-hl' + (curM === gfPopAnnId ? " gf-hl-active" : "") +
      '" data-ann="' + curM + '">' + seg + "</span>";
    html += seg; run = "";
  };
  for (let i = 0; i < text.length; i++) {
    const r = !!red[i], m = markAt(i);
    if (r !== curR || m !== curM) { flush(); curR = r; curM = m; }
    run += text[i];
  }
  flush();
  div.innerHTML = html;
}

/* ============ 划选浮签「＋批注」 ============ */
function gfHidePill() { if (gfPill) { gfPill.remove(); gfPill = null; } }
function gfSelInfo() {                   // 选区在整页版面内 → {start, text}（全局字符偏移）
  const el = gfPageEl(); if (!el) return null;
  const sel = window.getSelection();
  if (!sel.rangeCount || sel.isCollapsed) return null;
  const r = sel.getRangeAt(0);
  if (!el.contains(r.startContainer) || !el.contains(r.endContainer)) return null;
  const pre = r.cloneRange(); pre.selectNodeContents(el); pre.setEnd(r.startContainer, r.startOffset);
  const start = pre.toString().replace(/\n/g, "").length;
  const text = r.toString().replace(/\n/g, "");
  return text ? { start, text } : null;
}
function gfShowPill() {
  gfHidePill();
  const info = gfSelInfo(); if (!info) return;
  const rect = window.getSelection().getRangeAt(0).getBoundingClientRect();
  if (!rect || (!rect.width && !rect.height)) return;
  const b = document.createElement("button");
  b.className = "gf-selpill"; b.textContent = "＋ 批注"; b.title = "给选中文字加批注（只存本机）";
  b.style.left = Math.min(Math.max(8, rect.left + rect.width / 2 - 34), innerWidth - 90) + "px";
  b.style.top = Math.min(innerHeight - 44, rect.bottom + 8) + "px";
  b.addEventListener("mousedown", (e) => { e.preventDefault(); e.stopPropagation(); gfCreateAnnot(info); });
  document.body.appendChild(b); gfPill = b;
}
function gfCreateAnnot(info) {
  gfHidePill();
  const full = assemblePageText();
  let occ = 0;                            // 选区起点前同文出现次数 → 锚定第 occ 次出现
  for (let i = full.indexOf(info.text); i >= 0 && i < info.start; i = full.indexOf(info.text, i + 1)) occ++;
  resetTextUndoMerge();
  pushUndo();
  const a = { id: "a_" + Date.now() + "_" + Math.floor(Math.random() * 1e4), quote: info.text, occ, note: "" };
  gfAnnots().push(a);
  try { window.getSelection().removeAllRanges(); } catch (e) {}
  const el = gfPageEl(); if (el) gfPageRender(el);
  annTouch(); annRefresh();
  annFocusItem(a.id);
}

/* ============ 批注小签（看 / 改 / 删） ============ */
function gfClosePop() {
  gfPopAnnId = null;
  if (gfPop) { gfPop.remove(); gfPop = null; }
  const el = gfPageEl();
  if (el) el.querySelectorAll(".gf-hl-active").forEach((s) => s.classList.remove("gf-hl-active"));
  annListSync();
}
function gfOpenPop(annId) {
  // Legacy entry kept for compatibility: annotations now edit inside the main panel only.
  annFocusItem(annId);
}

/* ============ 批注面板：划批 + 存量段批 列表 + 本页总批 ============ */
function annListSync() {
  const list = annEl("annList"); if (!list) return;
  if (typeof proof === "undefined" || !proof || !proof.pages || !proof.pages.length) {   // 空态守卫（启动/删空）
    list.innerHTML = "";
    const c0 = annEl("annCnt"); if (c0) c0.textContent = "";
    return;
  }
  const pg = page(), items = [];
  for (const a of gfAnnots()) items.push({ kind: "hl", id: a.id, quote: a.quote, note: a.note, lost: !!a._lost });
  for (const id of pg.order) {
    const l = lineById(id);
    if (l && !l.deleted && l.annot) items.push({ kind: "line", id, quote: (l.text || "").slice(0, 14) || "\uFF08\u7A7A\u6BB5\uFF09", note: l.annot });
  }
  const cnt = annEl("annCnt"); if (cnt) cnt.textContent = items.length ? " " + items.length : "";
  list.innerHTML = "";
  if (!items.length) {
    const d = document.createElement("div"); d.className = "ann-empty-tip";
    d.textContent = "选中正文后添加批注";
    list.appendChild(d); return;
  }
  for (const it of items) {
    const d = document.createElement("div");
    d.className = "ann-item" + (it.kind === "hl" && it.id === gfPopAnnId ? " active" : "") + (it.lost ? " lost" : "");
    if (it.kind === "hl") d.dataset.ann = it.id;
    const q = document.createElement("span"); q.className = "ann-quote"; q.textContent = it.quote || "（空）";
    const k = document.createElement("span"); k.className = "ann-kind";
    k.textContent = it.kind === "hl" ? (it.lost ? "原文已改动，失锚" : "") : "段批（旧版）";
    d.appendChild(q);
    if (it.kind === "hl") {
      const ta = document.createElement("textarea");
      ta.rows = 1;
      ta.className = "ann-note-edit";
      ta.value = it.note || "";
      ta.placeholder = "填写该条批注…";
      ta.setAttribute("aria-label", "批注内容");
      requestAnimationFrame(() => annFitTextarea(ta));
      ta.addEventListener("input", () => {
        annFitTextarea(ta);
        const a = gfAnnots().find((x) => x.id === it.id);
        if (a) { pushTextUndo("annot:" + it.id); a.note = ta.value; annTouch(); }
      });
      ta.addEventListener("focus", () => annActivateItem(it.id, true, false));
      ta.addEventListener("click", (e) => e.stopPropagation());
      const ops = document.createElement("div"); ops.className = "ann-item-ops";
      const del = document.createElement("button");
      del.className = "btn btn-micro ann-del"; del.type = "button"; del.title = "删除批注"; del.setAttribute("aria-label", "删除批注"); del.innerHTML = ANN_TRASH_SVG;
      del.addEventListener("click", (e) => {
        e.preventDefault(); e.stopPropagation();
        resetTextUndoMerge();
        pushUndo();
        const arr = gfAnnots(), i = arr.findIndex((x) => x.id === it.id);
        if (i >= 0) arr.splice(i, 1);
        if (gfPopAnnId === it.id) gfPopAnnId = null;
        const el = gfPageEl(); if (el) gfPageRender(el);
        annTouch(); annRefresh();
      });
      ops.appendChild(del);
      d.appendChild(ta); d.appendChild(ops);
    } else {
      const n = document.createElement("span"); n.className = "ann-note" + (it.note ? "" : " empty");
      n.textContent = it.note || "";
      d.appendChild(n);
    }
    if (k.textContent) d.appendChild(k);
    d.onclick = () => annJump(it);
    list.appendChild(d);
  }
}

function annActivateItem(annId, scrollMark, refreshList = true) {
  if (gfPop) { gfPop.remove(); gfPop = null; }
  gfPopAnnId = annId;
  const el = gfPageEl();
  if (el) {
    el.querySelectorAll(".gf-hl-active").forEach((s) => s.classList.remove("gf-hl-active"));
    const m = el.querySelector('.gf-hl[data-ann="' + annId + '"]');
    if (m) {
      m.classList.add("gf-hl-active");
      if (scrollMark) m.scrollIntoView({ block: "center", behavior: "smooth" });
    }
  }
  if (refreshList) annListSync();
}
function annFocusItem(annId) {
  if (annCollapsed) {
    annCollapsed = false;
    const panel = annEl("annotPanel");
    if (panel) panel.classList.remove("ann-collapsed");
    annApplyPanelPosition();
  }
  annActivateItem(annId, true, true);
  const list = annEl("annList"); if (!list) return;
  const item = list.querySelector('.ann-item[data-ann="' + annId + '"]');
  const ta = item && item.querySelector(".ann-note-edit");
  if (ta) ta.focus();
}
function gfSelectAbs(el, s, e) {         // 在整页版面（多文本节点）里选中 [s,e)
  try {
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
    const range = document.createRange();
    let node = walker.nextNode(), pos = 0, state = 0;
    while (node) {
      const len = node.textContent.length;
      if (state === 0 && s <= pos + len) { range.setStart(node, s - pos); state = 1; }
      if (state === 1 && e <= pos + len) { range.setEnd(node, e - pos); state = 2; break; }
      pos += len; node = walker.nextNode();
    }
    if (state === 2) {
      const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(range);
      const rct = range.getBoundingClientRect();
      if (rct && rct.height) {
        const par = range.startContainer.parentElement;
        if (par && par.scrollIntoView) par.scrollIntoView({ block: "center", behavior: "smooth" });
      }
    }
  } catch (err) {}
}
function annJump(it) {
  if (it.kind === "hl") {
    annActivateItem(it.id, true);
  } else if (typeof proofMode !== "undefined" && proofMode === "row") {
    if (typeof activateRow === "function") activateRow(it.id);
  } else {                                // 整页态定位存量段批：选中该行文本所在区间
    const el = gfPageEl(); if (!el) return;
    const vo = visibleOrder(); let abs = 0;
    for (const id of vo) {
      const l = lineById(id);
      if (id === it.id) { gfSelectAbs(el, abs, abs + ((l && l.text) || "").length); return; }
      abs += ((l && l.text) || "").length;
    }
  }
}


/** 页面/文档切换时刷新面板（不覆盖正在输入的总批框）。 */
function annRefresh() {
  const panel = annEl("annotPanel");
  if (!panel) return;
  const has = !!(typeof proof !== "undefined" && proof && proof.pages && proof.pages.length);
  panel.classList.toggle("hidden", !has);
  gfHidePill();
  if (!has) { gfClosePop(); return; }
  panel.classList.toggle("ann-collapsed", annCollapsed);
  annApplyPanelPosition();
  const pg = page(), pa = annEl("annPage");
  if (pa) {
    pa.rows = 1;
    if (document.activeElement !== pa) pa.value = (pg && pg.page_annot) || "";
    requestAnimationFrame(() => annFitTextarea(pa));
  }
  if (gfPopAnnId && !gfAnnots().some((a) => a.id === gfPopAnnId)) gfClosePop();
  annListSync();
  annSplitBackSync();
}

/** 「拆回原始块」按钮随逐行模式当前点选段显隐（沿用旧逻辑，改自 annSyncLine）。 */
function annApplyPanelPosition() {
  const panel = annEl("annotPanel"); if (!panel) return;
  if (annCollapsed || !annPanelPos) {
    panel.style.removeProperty("left"); panel.style.removeProperty("top"); panel.style.removeProperty("right"); panel.style.removeProperty("bottom");
    panel.style.removeProperty("width"); panel.style.removeProperty("height");
    return;
  }
  panel.style.left = annPanelPos.x + "px";
  panel.style.top = annPanelPos.y + "px";
  panel.style.right = "auto";
  panel.style.bottom = "auto";
  if (annPanelPos.w) panel.style.width = annPanelPos.w + "px";
  if (annPanelPos.h) panel.style.height = annPanelPos.h + "px";
}
function annHitResizeZone(e, r) {
  const edge = 9;
  const left = e.clientX - r.left <= edge;
  const right = r.right - e.clientX <= edge;
  const top = e.clientY - r.top <= edge;
  const bottom = r.bottom - e.clientY <= edge;
  if (!(left || right || top || bottom)) return "";
  return (top ? "n" : bottom ? "s" : "") + (left ? "w" : right ? "e" : "");
}
function annClampPanelBox(box) {
  const margin = ANN_PANEL_MARGIN;
  let w = Math.min(Math.max(ANN_PANEL_MIN_W, box.w), innerWidth - margin * 2);
  let h = Math.min(Math.max(ANN_PANEL_MIN_H, box.h), innerHeight - margin * 2);
  let x = Math.min(Math.max(margin, box.x), innerWidth - w - margin);
  let y = Math.min(Math.max(margin, box.y), innerHeight - h - margin);
  return { x, y, w, h };
}
function annPanelCursorMove(e) {
  const panel = annEl("annotPanel");
  if (!panel || annCollapsed || annDragState) return;
  if (e.target.closest && e.target.closest("button, textarea, input, select, .ann-list")) { panel.style.cursor = ""; return; }
  const dir = annHitResizeZone(e, panel.getBoundingClientRect());
  panel.style.cursor = dir ? dir + "-resize" : "";
}
function annMaybeStartDrag(e) {
  const panel = annEl("annotPanel");
  if (!panel || annCollapsed || e.button !== 0) return;
  if (e.target.closest && e.target.closest("button, textarea, input, select, .ann-list")) return;
  const r = panel.getBoundingClientRect();
  const resizeDir = annHitResizeZone(e, r);
  const onBar = e.target.closest && e.target.closest("#annBar");
  if (!resizeDir && !onBar) return;
  annDragState = {
    mode: resizeDir ? "resize" : "move",
    dir: resizeDir,
    startX: e.clientX, startY: e.clientY,
    left: r.left, top: r.top, width: r.width, height: r.height,
  };
  panel.classList.toggle("ann-resizing", !!resizeDir);
  panel.classList.toggle("ann-dragging", !resizeDir);
  e.preventDefault();
}
function annDragMove(e) {
  if (!annDragState) return;
  const dx = e.clientX - annDragState.startX;
  const dy = e.clientY - annDragState.startY;
  if (annDragState.mode === "resize") {
    let box = { x: annDragState.left, y: annDragState.top, w: annDragState.width, h: annDragState.height };
    if (annDragState.dir.includes("e")) box.w = annDragState.width + dx;
    if (annDragState.dir.includes("s")) box.h = annDragState.height + dy;
    if (annDragState.dir.includes("w")) { box.x = annDragState.left + dx; box.w = annDragState.width - dx; }
    if (annDragState.dir.includes("n")) { box.y = annDragState.top + dy; box.h = annDragState.height - dy; }
    annPanelPos = annClampPanelBox(box);
  } else {
    annPanelPos = annClampPanelBox({
      x: annDragState.left + dx,
      y: annDragState.top + dy,
      w: annDragState.width,
      h: annDragState.height,
    });
  }
  annApplyPanelPosition();
}
function annDragEnd() {
  if (!annDragState) return;
  annDragState = null;
  const panel = annEl("annotPanel");
  if (panel) panel.classList.remove("ann-dragging", "ann-resizing");
}

/** Split-back button visibility follows the current row selection. */
function annSplitBackSync() {
  const sb = annEl("annSplitBack"); if (!sb) return;
  const l = annLineId ? lineById(annLineId) : null;
  const agg = l && l.member_texts && l.member_texts.length > 1;
  sb.classList.toggle("hidden", !agg);
  if (agg) sb.textContent = `拆回 ${l.member_texts.length} 块`;
}

/** 把一个由 OCR 碎行自动聚合的段，按 member_boxes/member_texts 拆回原始多块（兜底纠错）。 */
function splitBackLine(id) {
  if (typeof proof === "undefined" || !proof) return;
  const pg = page(), l = lineById(id);
  if (!l || !l.member_texts || l.member_texts.length < 2) return;
  if (typeof resetTextUndoMerge === "function") resetTextUndoMerge();
  if (typeof pushUndo === "function") pushUndo();
  const members = l.member_texts.map((t, k) => ({
    id: id + "_m" + k, text_ocr: t, text_draft: t, text: t,
    box: (l.member_boxes && l.member_boxes[k]) ? l.member_boxes[k].slice() : l.box.slice(),
    score: l.score, para_break: false, deleted: false,
  }));
  const li = pg.lines.findIndex((x) => x.id === id);
  if (li >= 0) pg.lines.splice(li, 1, ...members); else pg.lines.push(...members);
  const oi = pg.order.indexOf(id);
  if (oi >= 0) pg.order.splice(oi, 1, ...members.map((m) => m.id));
  else members.forEach((m) => pg.order.push(m.id));
  annLineId = null;
  render();
  if (typeof toast === "function") toast("已拆回 " + members.length + " 块");
}

function annTouch() { if (typeof gfScheduleSave === "function") gfScheduleSave(); }

function initAnnot() {
  const pa = annEl("annPage");
  if (pa) { pa.rows = 1; pa.addEventListener("input", () => { annFitTextarea(pa); const pg = proof && page(); if (pg) { pushTextUndo("page_annot:" + pg.page_id); pg.page_annot = pa.value; annTouch(); } }); }
  const body = annEl("editorBody");
  if (body) {
    // 逐行模式：点选某段 → 记录当前段（拆回原始块用）
    body.addEventListener("focusin", (e) => {
      const row = e.target.closest && e.target.closest("[data-id]");
      if (row && row.dataset.id) { annLineId = row.dataset.id; annSplitBackSync(); }
    });
    // 整页模式：点划批标记 → 在主批注面板中定位
    body.addEventListener("click", (e) => {
      const hl = e.target.closest && e.target.closest(".gf-hl");
      if (hl && hl.dataset.ann) { e.preventDefault(); annFocusItem(hl.dataset.ann); }
    });
  }
  // 划拉选中 → 浮「＋批注」（mouseup 后选区已定；点浮签/小签自身不触发）
  document.addEventListener("mouseup", (e) => {
    if (e.target.closest && e.target.closest(".gf-selpill")) return;
    setTimeout(gfShowPill, 0);
  });
  // 兼容旧小签状态：若旧弹层存在，点外部时清理
  document.addEventListener("mousedown", (e) => {
    if (!gfPop) return;
    if (e.target.closest && e.target.closest(".gf-hl, .ann-item")) return;
    gfClosePop();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { gfClosePop(); gfHidePill(); } });
  const tog = annEl("annToggle");
  if (tog) tog.addEventListener("click", (e) => {
    e.stopPropagation();
    annCollapsed = !annCollapsed;
    if (annCollapsed) annPanelPos = null;
    annRefresh();
  });
  const panel = annEl("annotPanel");
  if (panel) panel.addEventListener("click", () => {
    if (annCollapsed) { annCollapsed = false; annRefresh(); }
  });
  if (panel) panel.addEventListener("mousedown", annMaybeStartDrag);
  if (panel) panel.addEventListener("mousemove", annPanelCursorMove);
  if (panel) panel.addEventListener("mouseleave", () => { if (!annDragState) panel.style.cursor = ""; });
  document.addEventListener("mousemove", annDragMove);
  document.addEventListener("mouseup", annDragEnd);
  const sb = annEl("annSplitBack");
  if (sb) sb.addEventListener("click", () => { if (annLineId) splitBackLine(annLineId); });
}

initAnnot();
// 启动兜底：本文件晚于 app.js/db.js 加载，若本地缓存瞬时恢复跑在前面（render 时 annRefresh 尚未定义被跳过），
// 这里补一次刷新，保证批注面板随已恢复的文档立即显示。
annRefresh();
