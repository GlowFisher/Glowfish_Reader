"use strict";
/* ============================================================================
 * 右侧点校文本编辑器（?app.js 编排层解耦：本文件只管「右栏怎么渲染/怎么交互」）?
 *
 * 改造段⑦：横排 / 竖排两套渲染逻辑分层隔离（renderHorizontal / renderVertical），
 *   共用语义内核（mergePrev / splitNext / insertPunct / delRow / togglePara）?
 * 改造段⑤：右栏 Ctrl/?滚轮缩放?.7~1.5）?
 * 改造段八（逐字标红）：每条维护 red[] 布尔掩码对齐 text —??OCR 低置信原始字标红?
 *   手动新增/修改字为黑；编辑用「保留前后缀红标、变更段置黑」的 diff 维护；合?拆分时红标随字搬运?
 * 改造段九（拆分可用性）：向?向左拆分永不禁用，末条拆分自动新建承接条目；向上/向右合并首条仍置灰?
 *
 * 依赖 app.js 全局：proof/page()/lineById()/lowConf/snapshot()/pushUndo()/highlightBox()/
 *   refreshStats()/settings/layoutImage()?
 * ========================================================================== */

let currentLayout = "horizontal";   // 顶部面板临时视图态（默认值来自设?text_layout?
let proofMode = "page";             // 校读模式：page 整页 / row 逐行（默认来自设?proof_mode?
let paneZoom = 1;                   // 右栏滚轮缩放倍率
let pendingDelId = null;            // 待删条目 id（二次确认用?
let manualSeq = 0;                  // 拆分新建条目?id 序号
const cssEsc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s) : s;

function visibleOrder() {           // 可见条目序（剔除已删，合?置灰按此判断首条?
  return page().order.filter((id) => { const l = lineById(id); return l && !l.deleted; });
}

/* ---- 改造段八：red 掩码工具 ---- */
function ensureRed(l) {              // 懒初始化/对齐：低置信整条原始字标红，长度不符则按行分重置
  if (!Array.isArray(l.red) || l.red.length !== l.text.length) {
    const base = l.score < lowConf;
    l.red = Array.from(l.text, () => base);
  }
  return l.red;
}
function escHTML(s) { return s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
function redHTML(text, red) {        // 文本 + 红标 ?按红/黑分段包 span ?innerHTML
  let html = "", run = "", runRed = false;
  const flush = () => { if (run) { html += runRed ? `<span class="lc">${escHTML(run)}</span>` : escHTML(run); run = ""; } };
  for (let i = 0; i < text.length; i++) {
    const r = !!(red && red[i]);
    if (r !== runRed) { flush(); runRed = r; }
    run += text[i];
  }
  flush();
  return html;
}
function renderEditable(el, l) {     // 含红字→innerHTML ?span；纯黑→textContent（编辑无 DOM 负担?
  ensureRed(l);
  if (l.red.some(Boolean)) el.innerHTML = redHTML(l.text, l.red);
  else el.textContent = l.text;
}
function diffRed(l, newText) {       // 编辑后维?text+red：公共前后缀保留红标，中间变更段=新增=?
  ensureRed(l);
  const old = l.text, oldRed = l.red, minLen = Math.min(old.length, newText.length);
  let p = 0; while (p < minLen && old[p] === newText[p]) p++;
  let s = 0; while (s < old.length - p && s < newText.length - p &&
    old[old.length - 1 - s] === newText[newText.length - 1 - s]) s++;
  const nr = [];
  for (let i = 0; i < p; i++) nr.push(!!oldRed[i]);
  for (let i = 0, ins = newText.length - p - s; i < ins; i++) nr.push(false);
  for (let i = old.length - s; i < old.length; i++) nr.push(!!oldRed[i]);
  l.text = newText; l.red = nr;
}
function makeLine(text, red, score, from) {   // 拆分末条时新建承接条目（手动条目 draft 空、box 借用源条?
  return {
    id: "m_" + (manualSeq++) + "_" + Date.now(),
    text_ocr: "", text_draft: "", text, red: red.slice(),
    box: from && from.box ? from.box.slice() : [0, 0, 0, 0],
    score: score, para_break: false, deleted: false,
  };
}

/* ---- 光标工具（支持多文本节点：red span 拆成?node?--- */
function caretOffset(el) {
  const sel = window.getSelection();
  if (!sel.rangeCount || document.activeElement !== el) return null;
  const r = sel.getRangeAt(0).cloneRange();
  r.selectNodeContents(el); r.setEnd(sel.getRangeAt(0).endContainer, sel.getRangeAt(0).endOffset);
  return r.toString().length;
}
function setCaret(el, pos) {
  el.focus();
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
  const sel = window.getSelection(), r = document.createRange();
  let node = walker.nextNode(), remaining = pos;
  if (!node) { r.selectNodeContents(el); r.collapse(true); sel.removeAllRanges(); sel.addRange(r); return; }
  while (node) {
    const len = node.textContent.length;
    if (remaining <= len) { r.setStart(node, remaining); r.collapse(true); sel.removeAllRanges(); sel.addRange(r); return; }
    remaining -= len;
    const nxt = walker.nextNode();
    if (!nxt) { r.setStart(node, len); r.collapse(true); sel.removeAllRanges(); sel.addRange(r); return; }
    node = nxt;
  }
}
function focusLine(id, pos) {
  const s = `[data-id="${cssEsc(id)}"]`;
  const el = document.querySelector(`${s} .txt, ${s} .v-txt`);
  if (el) setCaret(el, pos);
}
function markActiveRow(id) {
  document.querySelectorAll(".row,.vcol").forEach((r) => r.classList.toggle("active", r.dataset.id === id));
}
function focusSibling(id, dir, off) {   // 纯净模式跨行/跨列：把光标移到相邻可见条目，尽量保留列偏移
  const vo = visibleOrder(), i = vo.indexOf(id);
  if (i < 0) return;                     // 当前条不在可见序（已删等）→ 不跳，避免误聚焦首条
  const j = i + dir;
  if (j < 0 || j >= vo.length) return;
  const tl = lineById(vo[j]);
  focusLine(vo[j], Math.min(off == null ? 0 : off, (tl && tl.text ? tl.text.length : 0)));
}

/* ---- 改造段⑦核心：以光标为分割边界的合?拆分（横竖共用；红标随字搬运?--- */
function mergePrev(id, el) {         // 光标前文字并入上一条末尾；无光?整条上并。首条已置灰不会触发
  const vo = visibleOrder(), i = vo.indexOf(id);
  if (i <= 0) return;
  const prev = lineById(vo[i - 1]), cur = lineById(id);
  ensureRed(prev); ensureRed(cur);
  const k = caretOffset(el);
  const cut = (k == null) ? cur.text.length : k;
  if (cut <= 0) return;
  resetTextUndoMerge();
  pushUndo();
  prev.text = prev.text + cur.text.slice(0, cut);
  prev.red = prev.red.concat(cur.red.slice(0, cut));
  cur.text = cur.text.slice(cut); cur.red = cur.red.slice(cut);
  renderEditor(); focusLine(id, 0); refreshStats();
}
function mergeWholeUp(id) {           // 纯净模式行首退格：整条并入上一条末尾、删除本条，光标落拼接点（mergePrev 在光?0 处会早返回故另写?
  const vo = visibleOrder(), i = vo.indexOf(id);
  if (i <= 0) return;
  const prev = lineById(vo[i - 1]), cur = lineById(id);
  ensureRed(prev); ensureRed(cur);
  resetTextUndoMerge();
  pushUndo();
  const at = prev.text.length;
  prev.text += cur.text; prev.red = prev.red.concat(cur.red);
  const pg = page();
  const li = pg.lines.findIndex((x) => x.id === id); if (li >= 0) pg.lines.splice(li, 1);
  const oi = pg.order.indexOf(id); if (oi >= 0) pg.order.splice(oi, 1);
  renderEditor();
  if (typeof layoutImage === "function") layoutImage();   // 同步移除画布对应标注?
  if (typeof annRefresh === "function") annRefresh();
  focusLine(prev.id, at); refreshStats();
}
function splitNext(id, el) {         // 改造段九：永不禁用；有下一条→拆其开头，末条→新建承接条?
  const cur = lineById(id); ensureRed(cur);
  const k = caretOffset(el);
  const cut = (k == null) ? 0 : k;                 // 无光?整条下拆
  if (cut >= cur.text.length) return;              // 光标已在末尾，无可拆文字（按钮仍可点，仅本次无操作）
  const vo = visibleOrder(), i = vo.indexOf(id);
  resetTextUndoMerge();
  pushUndo();
  const moveText = cur.text.slice(cut), moveRed = cur.red.slice(cut);
  cur.text = cur.text.slice(0, cut); cur.red = cur.red.slice(0, cut);
  if (i >= 0 && i < vo.length - 1) {               // 拆到下一条开?
    const next = lineById(vo[i + 1]); ensureRed(next);
    next.text = moveText + next.text; next.red = moveRed.concat(next.red);
  } else {                                         // 末条：新建条目承接光标后文字
    const nl = makeLine(moveText, moveRed, cur.score, cur);
    const pg = page(), oi = pg.order.indexOf(id);
    pg.lines.push(nl); pg.order.splice(oi + 1, 0, nl.id);
  }
  renderEditor(); focusLine(id, cur.text.length); refreshStats();
}

function splitNewLine(id, el) {     // 改造段⑩：新建下框拆分 —?光标后文字搬入「全新」承接条目，绝不动原有下?
  const cur = lineById(id); ensureRed(cur);
  const k = caretOffset(el);
  const cut = (k == null) ? cur.text.length : k;   // 无光?整条下移；光标在末尾=新建空条承接
  resetTextUndoMerge();
  pushUndo();
  const moveText = cur.text.slice(cut), moveRed = cur.red.slice(cut);
  cur.text = cur.text.slice(0, cut); cur.red = cur.red.slice(0, cut);
  const nl = makeLine(moveText, moveRed, cur.score, cur);   // 始终新建（区?splitNext 的「并入已有下条」）
  const pg = page(), oi = pg.order.indexOf(id);
  pg.lines.push(nl); pg.order.splice(oi + 1, 0, nl.id);     // 紧贴本行下方插入新条，不动其余任何条?
  renderEditor(); focusLine(nl.id, 0); refreshStats();      // 光标跳新行开?
}

function insertPunct(id, ch, el) {  // 标点按设置插光标?末尾，仅本条；手动标??
  const l = lineById(id); ensureRed(l);
  const k = caretOffset(el);
  const off = (settings.punct_pos === "end" || k == null) ? l.text.length : k;
  resetTextUndoMerge();
  pushUndo();
  l.text = l.text.slice(0, off) + ch + l.text.slice(off);
  l.red = l.red.slice(0, off).concat([false], l.red.slice(off));
  renderEditable(el, l); setCaret(el, off + 1); refreshStats();
}

function delRow(id) {
  if (settings.confirm_delete) { pendingDelId = id; $("#confirmModal").classList.remove("hidden"); }
  else doDelete(id);
}
function doDelete(id) {
  resetTextUndoMerge();
  pushUndo();
  const pg = page();                                   // 整条清除：文?置信?段落批注随对象一并删?
  const li = pg.lines.findIndex((x) => x.id === id);
  if (li >= 0) pg.lines.splice(li, 1);
  const oi = pg.order.indexOf(id);
  if (oi >= 0) pg.order.splice(oi, 1);
  renderEditor();
  if (typeof layoutImage === "function") layoutImage();   // 同步移除画布对应标注?
  if (typeof annRefresh === "function") annRefresh();     // 刷新批注面板（被删段的本段批注随之失效）
  refreshStats();
}
function togglePara(id) {
  resetTextUndoMerge();
  pushUndo(); lineById(id).para_break = !lineById(id).para_break;
  renderEditor(); refreshStats();
}

function op(kind, id, el) {
  if (kind === "merge") return mergePrev(id, el);
  if (kind === "split") return splitNext(id, el);
  if (kind === "splitnew") return splitNewLine(id, el);
  if (kind === "comma") return insertPunct(id, "，", el);
  if (kind === "period") return insertPunct(id, "。", el);
  if (kind === "del") return delRow(id);
  if (kind === "para") return togglePara(id);
}

/* ---- 文本框事件：IME 安全编辑 + 逐字红标维护 ---- */
function bindRowText(el, id) {
  let composing = false;
  el.addEventListener("focus", () => { highlightBox(id); markActiveRow(id); });
  el.addEventListener("compositionstart", () => { composing = true; });          // 中文输入法组词中不动 DOM
  el.addEventListener("compositionend", () => { composing = false; handleEdit(); });
  el.addEventListener("input", () => { if (!composing) handleEdit(); });
  // 纯净模式全键盘点校：仅在 pureMode 接管；IME 组词中、Ctrl/?组合一律放行（让撤销/保存等走原监听）
  el.addEventListener("keydown", (e) => {
    if (!pureMode || composing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "PageUp")   { e.preventDefault(); if (typeof pagePrev === "function") pagePrev(); return; }   // 翻原?编辑器内须显式拦?
    if (e.key === "PageDown") { e.preventDefault(); if (typeof pageNext === "function") pageNext(); return; }
    if (e.key === "Enter") { e.preventDefault(); splitNewLine(id, el); return; }                                // 光标处断为两行，后段入新?
    if (e.key === "Backspace" && caretOffset(el) === 0) { e.preventDefault(); mergeWholeUp(id); return; }        // 行首退?整条并入上一?
    if (e.key === "," || e.key === "，" || e.key === "." || e.key === "。") {
      const k = caretOffset(el), before = (k ? el.textContent[k - 1] : "") || "";   // 紧邻数字时放行半?避免误伤 2.5)，否则插全角并复?op()
      if (!/\d/.test(before)) { e.preventDefault(); op(e.key === "," || e.key === "，" ? "comma" : "period", id, el); return; }
    }
    const nav = currentLayout === "vertical"             // 竖排：←?跨列(右→??下一?、↑?列内；横排：↑↓ 跨行、←?行内
      ? { ArrowLeft: 1, ArrowRight: -1 } : { ArrowUp: -1, ArrowDown: 1 };
    if (e.key in nav) { e.preventDefault(); focusSibling(id, nav[e.key], caretOffset(el)); return; }
  });
  function handleEdit() {
    pushTextUndo("row:" + id);         // 整段编辑算一步撤销；首次输入时才快?惰性，省去每次聚焦的全量深拷贝)
    const l = lineById(id), newText = el.textContent;
    const hadRed = l.red && l.red.some(Boolean);
    diffRed(l, newText);
    if (hadRed || (l.red && l.red.some(Boolean))) {       // 仅含红字条目才重渲染 span（普通条目零 DOM 扰动?
      const off = caretOffset(el);
      el.innerHTML = redHTML(l.text, l.red);
      setCaret(el, off == null ? l.text.length : off);
    }
    refreshStats();
  }
}
function wireRowButtons(rowEl, id, el) {
  rowEl.querySelectorAll("button[data-op]").forEach((b) => {
    if (b.classList.contains("keep-focus")) b.addEventListener("mousedown", (e) => e.preventDefault()); // 保住光标
    b.onclick = (e) => { e.stopPropagation(); if (!b.disabled) op(b.dataset.op, id, el); };
  });
}
// ?竖排共用的行装配尾部：渲染文?+ 绑定编辑/按钮/拖拽 + 挂载（txtSel=横排 .txt / 竖排 .v-txt?
function mountRow(wrap, rowEl, txtSel, id, l) {
  const txt = rowEl.querySelector(txtSel);
  renderEditable(txt, l);
  bindRowText(txt, id); wireRowButtons(rowEl, id, txt); initRowDrag(rowEl, id);
  wrap.appendChild(rowEl);
}

// ====== 分支1：现代横排渲?======
function renderHorizontal() {
  const host = $("#editorBody");
  const wrap = document.createElement("div"); wrap.id = "lines";
  const pg = page(), vo = visibleOrder();
  pg.order.forEach((id, idx) => {
    const l = lineById(id); if (!l) return;
    const vi = vo.indexOf(id), del = !!l.deleted, low = l.score < lowConf;
    const noUp = del || vi <= 0;       // 合并：首条置灰　拆分：永不禁用（仅删除条禁用?
    const row = document.createElement("div");
    row.className = "row" + (l.para_break ? " para" : "") + (del ? " deleted" : "") + (low ? " low" : "");
    row.dataset.id = id;
    row.innerHTML = `
      <span class="idx">${idx + 1}</span>
      <div class="cell">
        <div class="txt" contenteditable="true" spellcheck="false"></div>
        <div class="below-ops">
          <button class="btn btn-micro keep-focus op-ico" data-op="merge" ${noUp ? "disabled" : ""} title="向上合并：光标前文字并入上一行末?>?/button>
          <button class="btn btn-micro keep-focus op-ico" data-op="split" ${del ? "disabled" : ""} title="向下拆分：光标后文字拆到下一行（末行自动新建?>?/button>
          <button class="btn btn-micro keep-focus op-ico op-slash" data-op="splitnew" ${del ? "disabled" : ""} title="新建下框拆分：将光标后文字移入全新点校框">/</button>
          <button class="btn btn-micro keep-focus" data-op="comma" title="Insert comma">，</button>
          <button class="btn btn-micro keep-focus" data-op="period" title="Insert period">。</button>
          <button class="btn btn-micro${del ? " danger" : ""}" data-op="del" title="${del ? "恢复本行" : "删除本行"}">🗑</button>
        </div>
      </div>
      <div class="right-ops">
        <span class="score ${low ? "low" : "ok"}">${l.score.toFixed(2)}</span>
        <button class="btn btn-micro${l.para_break ? " on" : ""}" data-op="para" title="划分自然段（导出分段边界?><span class="para-ico"></span></button>
      </div>`;
    mountRow(wrap, row, ".txt", id, l);
  });
  host.appendChild(wrap);
}

// ====== 分支2：古籍竖排渲染（右→左，独立 DOM?=====
function renderVertical() {
  const host = $("#editorBody");
  const wrap = document.createElement("div"); wrap.id = "vlines";
  const pg = page(), vo = visibleOrder();
  pg.order.forEach((id, idx) => {
    const l = lineById(id); if (!l) return;
    const vi = vo.indexOf(id), del = !!l.deleted, low = l.score < lowConf;
    const noRight = del || vi <= 0;
    const col = document.createElement("div");
    col.className = "vcol" + (l.para_break ? " para" : "") + (del ? " deleted" : "") + (low ? " low" : "");
    col.dataset.id = id;
    col.innerHTML = `
      <span class="vidx">${idx + 1}</span>
      <div class="vhead">
        <span class="score ${low ? "low" : "ok"}">${l.score.toFixed(2)}</span>
        <button class="btn btn-micro${l.para_break ? " on" : ""}" data-op="para" title="划分自然段（导出分段边界?><span class="para-ico"></span></button>
      </div>
      <div class="vbody">
        <div class="v-ops">
          <button class="btn btn-micro keep-focus op-ico" data-op="merge" ${noRight ? "disabled" : ""} title="向右合并：光标上方文字并入右侧竖条底?>?/button>
          <button class="btn btn-micro keep-focus op-ico" data-op="split" ${del ? "disabled" : ""} title="向左拆分：光标下方文字拆到左侧竖条（最左自动新建）">?/button>
          <button class="btn btn-micro keep-focus op-ico op-slash" data-op="splitnew" ${del ? "disabled" : ""} title="新建左框拆分：将光标后文字移入全新点校框">/</button>
          <button class="btn btn-micro keep-focus" data-op="comma" title="Insert comma">，</button>
          <button class="btn btn-micro keep-focus" data-op="period" title="Insert period">。</button>
          <button class="btn btn-micro${del ? " danger" : ""}" data-op="del" title="${del ? "恢复本条" : "删除本条"}">🗑</button>
        </div>
        <div class="v-txt" contenteditable="true" spellcheck="false"></div>
      </div>`;
    mountRow(wrap, col, ".v-txt", id, l);
  });
  host.appendChild(wrap);
}

// ====== 分支3：整页点校（合并全文为「无换行单一段落」，屏蔽手动换行；与逐行按字符边界实时互通）======
// 渲染：可见各?text 直接拼接（移除全部分行），全文输出为无分段单段?
// 回写：换行被屏蔽 ?行数恒定。用「新整页?vs 旧拼接串」的前后缀 diff 定位变更落在哪条?
//   只更新被改条目（跨条选删时首条吸收变更、中间条清空、尾条保留后缀），保证切回逐行能恢复原生分行?
function assemblePageText() {
  return visibleOrder().map((id) => lineById(id).text).join("");   // 移除换行：全文单?
}
function applyPageText(nv) {
  const vo = visibleOrder();
  const texts = vo.map((id) => lineById(id).text);
  const old = texts.join("");
  if (nv === old) return;
  const minL = Math.min(old.length, nv.length);
  let p = 0; while (p < minL && old[p] === nv[p]) p++;                       // 公共前缀长度
  let s = 0; while (s < old.length - p && s < nv.length - p &&
    old[old.length - 1 - s] === nv[nv.length - 1 - s]) s++;                  // 公共后缀长度
  const oldEnd = old.length - s;                                            // old 变更?[p, oldEnd)
  const newMid = nv.slice(p, nv.length - s);                                // 替换进来的新文字
  const ends = []; let acc = 0;                                             // ends[i] = ?i 条结束偏?
  for (const t of texts) { acc += t.length; ends.push(acc); }
  const startOf = (i) => (i === 0 ? 0 : ends[i - 1]);
  const lineAt = (pos) => { let i = 0; while (i < ends.length - 1 && pos >= ends[i]) i++; return i; };
  const ai = lineAt(p);                                                     // 变更起点所在条
  const bi = (oldEnd > p) ? lineAt(oldEnd - 1) : ai;                        // 变更终点所在条（纯插入?ai?
  for (let i = ai; i <= bi; i++) {
    const ls = startOf(i);
    let nt;
    if (i === ai && i === bi) nt = old.slice(ls, p) + newMid + old.slice(oldEnd, ends[i]);
    else if (i === ai)        nt = old.slice(ls, p) + newMid;               // 首条：保留前缀 + 全部新文?
    else if (i === bi)        nt = old.slice(oldEnd, ends[i]);              // 尾条：仅保留变更点后的后缀
    else                      nt = "";                                     // 跨条中间：清?
    diffRed(lineById(vo[i]), nt);                                          // 维护 red 掩码，切回逐行红标一?
  }
}
function renderPage() {
  // v2：contenteditable 版面（替?textarea）——可渲染低置信红?+ 划批标记（annotations.js gfPageRender），
  // 编辑语义不变：无换行单段、IME 安全、applyPageText 前后缀 diff 回写、整段编辑一步撤销?
  const host = $("#editorBody");
  const div = document.createElement("div");
  div.id = "pageText"; div.className = "page-text";
  div.contentEditable = "true"; div.spellcheck = false;
  host.appendChild(div);
  if (typeof gfPageRender === "function") gfPageRender(div);
  else div.textContent = assemblePageText();
  let composing = false;
  const commit = () => {
    const nv = div.textContent;
    pushTextUndo("page:" + page().page_id);
    const off = caretOffset(div);
    applyPageText(nv);
    if (typeof gfPageRender === "function") gfPageRender(div);   // 重渲染红?划批标记
    else if (div.textContent !== nv) div.textContent = nv;
    setCaret(div, off == null ? nv.length : Math.min(off, nv.length));
    refreshStats();
  };
  const pageKeydown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      if (composing) return;
      const off = caretOffset(div);
      const cur = div.textContent || "";
      const at = off == null ? cur.length : off;
      const nv = cur.slice(0, at) + "\n" + cur.slice(at);
      pushTextUndo("page:" + page().page_id);
      applyPageText(nv);
      if (typeof gfPageRender === "function") gfPageRender(div);
      else div.textContent = nv;
      setCaret(div, at + 1);
      refreshStats();
      return;
    }
    const active = document.activeElement;
    const inPageText = active === div || div.contains(active) || e.target === div || div.contains(e.target);
    if (!inPageText || composing || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "PageUp") {
      e.preventDefault(); e.stopPropagation();
      if (typeof pagePrev === "function") pagePrev();
      return;
    }
    if (e.key === "PageDown") {
      e.preventDefault(); e.stopPropagation();
      if (typeof pageNext === "function") pageNext();
    }
  };
  div.addEventListener("keydown", pageKeydown, true);        // 捕获阶段抢在 contenteditable 默认光标跳转前处?
  div.addEventListener("paste", (e) => {               // 粘贴去换行（多行粘贴 ?并为单段?
    e.preventDefault();
    const t = ((e.clipboardData || window.clipboardData).getData("text") || "").replace(/[\r\n]+/g, "");
    document.execCommand("insertText", false, t);
  });
  div.addEventListener("compositionstart", () => { composing = true; });
  div.addEventListener("compositionend", () => { composing = false; commit(); });
  div.addEventListener("input", () => { if (!composing) commit(); });
}

// ====== 渲染分派 + 排版/校读模式切换 + 右栏缩放 ======
function renderEditor() {
  if (!proof) return;
  const host = $("#editorBody");
  host.innerHTML = "";
  host.dataset.layout = currentLayout;
  host.dataset.proofMode = proofMode;
  host.dataset.font = settings.text_font;
  host.style.setProperty("--txt-size", (settings.text_size || 16) + "px");
  if (proofMode === "page") renderPage();
  else if (currentLayout === "vertical") renderVertical();
  else renderHorizontal();
  applyPaneZoom();
}

function syncProofModeButtons() {
  const r = $("#pmRow"), p = $("#pmPage");
  if (r) r.classList.toggle("on", proofMode === "row");
  if (p) p.classList.toggle("on", proofMode === "page");
}
function setProofMode(mode) {
  if (mode === proofMode) return;
  proofMode = mode;
  if (typeof sessionProofMode !== "undefined") sessionProofMode = mode;
  if (typeof sessionModesTouched !== "undefined") sessionModesTouched = true;
  syncProofModeButtons();
  if (proof) renderEditor();
}

function syncLayoutButtons() {
  const b = $("#layoutBtn");                              // 工具栏单?toggle：显示当前排版，点击切换
  if (b) b.textContent = currentLayout === "vertical" ? "竖排" : "横排";
}
function setLayout(layout) {
  if (layout === currentLayout) return;
  currentLayout = layout;
  if (typeof sessionLayout !== "undefined") sessionLayout = layout;
  if (typeof sessionModesTouched !== "undefined") sessionModesTouched = true;
  syncLayoutButtons();
  if (proof) renderEditor();
}

// 改造段⑤：右栏 Ctrl/?滚轮缩放（普通滚轮保留滚动；竖排 Shift+滚轮原生左右平移?
function applyPaneZoom() { $("#editorBody").style.zoom = paneZoom; }
function showPaneBadge() {
  const b = $("#paneZoomBadge"); b.textContent = "右栏缩放 " + Math.round(paneZoom * 100) + "%";
  b.classList.add("show"); clearTimeout(showPaneBadge._t);
  showPaneBadge._t = setTimeout(() => b.classList.remove("show"), 1000);
}
function initEditor() {       // ?app.js ?$ 等全局就绪后调?
  $("#layoutBtn").onclick = () => setLayout(currentLayout === "vertical" ? "horizontal" : "vertical");
  const pr = $("#pmRow"), pp = $("#pmPage");      // 校读栏顶部：逐行 / 整页 切换
  if (pr) pr.onclick = () => setProofMode("row");
  if (pp) pp.onclick = () => setProofMode("page");
  if (typeof initSessionModes === "function") initSessionModes(false);
  proofMode = (typeof sessionProofMode !== "undefined" ? sessionProofMode : settings.proof_mode) || "page";
  currentLayout = (typeof sessionLayout !== "undefined" ? sessionLayout : settings.text_layout) || "horizontal";
  syncProofModeButtons();
  syncLayoutButtons();
  $("#right").addEventListener("wheel", (e) => {
    if (!e.ctrlKey && !e.metaKey) return;
    e.preventDefault();
    const nz = Math.min(1.5, Math.max(0.7, paneZoom + (e.deltaY < 0 ? 0.05 : -0.05)));
    if (nz === paneZoom) return;
    paneZoom = nz; applyPaneZoom(); showPaneBadge();
  }, { passive: false });
}
