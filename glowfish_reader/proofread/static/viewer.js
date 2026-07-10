"use strict";
// 左栏底图视图：变换式平移缩放（放大有界 / 缩小自由）+ 可拖拽分界线。
// zoomCtl 在 #left 内绝对定位、不在 #imgWrap 里，故不随图缩放/平移、永久固定左上角。
let zoom = 1, panX = 0, panY = 0, panMoved = false;
let eraseMode = false; // 识别框模式内的临时橡皮擦：只删除普通识别框对应文本。
let regionSelectMode = false;
let baseW = 0, baseH = 0;
const ZMIN = 0.05, ZMAX = 10;
const WHEEL_ZOOM_STEP = 1.1;
const BTN_ZOOM_STEP = 1.25;
const PAN_MOVE_PX = 3;

function boxesVisible() {
  return regionSelectMode && typeof settings !== "undefined" && settings.show_boxes === true && !document.body.classList.contains("hide-boxes");
}

function syncBoxToggle() {
  const btn = $("#boxToggle");
  const erase = $("#boxErase");
  const on = boxesVisible();
  if (btn) {
    btn.classList.toggle("on", regionSelectMode);
    btn.setAttribute("aria-pressed", regionSelectMode ? "true" : "false");
    btn.title = regionSelectMode
      ? "退出框选识别模式"
      : "进入框选识别模式：直接在底图上拖出区域重新识别";
  }
  if (erase) {
    erase.hidden = !on;
    erase.classList.toggle("hidden", !on);
    if (!on) setEraseMode(false);
  }
}

function setEraseMode(on) {
  eraseMode = !!on && boxesVisible();
  document.body.classList.toggle("box-erase-mode", eraseMode);
  const btn = $("#boxErase");
  if (!btn) return;
  btn.classList.toggle("on", eraseMode);
  btn.setAttribute("aria-pressed", eraseMode ? "true" : "false");
  btn.title = eraseMode
    ? "退出擦除模式"
    : "橡皮擦：开启后点击识别框删除对应点校文本；再次点击退出擦除模式";
}

function toggleEraseMode() {
  setEraseMode(!eraseMode);
}
function setRegionSelectMode(on) {
  regionSelectMode = !!on && !!proof;
  document.body.classList.toggle("region-select-mode", regionSelectMode);
  if (typeof settings !== "undefined") {
    settings.show_boxes = regionSelectMode;
  }
  document.body.classList.toggle("hide-boxes", !regionSelectMode);
  if (!regionSelectMode || eraseMode) setEraseMode(false);
  syncBoxToggle();
}
function toggleRegionSelectMode() {
  if (typeof settings === "undefined") return;
  setRegionSelectMode(!regionSelectMode);
  api("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ show_boxes: settings.show_boxes }) }).catch(() => {});
}
function positionBoxes() {
  const pg = page(), box = $("#boxes");
  box.innerHTML = "";
  const s = baseW / (pg.width || 1);
  const bodyLines = (pg.lines || []).map((l) => ({ line: l, noise: false }));
  const noiseLines = (pg.noise_lines || []).map((l) => ({ line: l, noise: true }));
  for (const item of bodyLines.concat(noiseLines)) {
    const l = item.line;
    if (!item.noise && l.deleted) continue;
    const [x1, y1, x2, y2] = l.box;
    const d = document.createElement("div");
    d.className = "box" + (l.score < lowConf ? " low" : "") + (item.noise ? " noise" : "");
    d.style.left = x1 * s + "px"; d.style.top = y1 * s + "px";
    d.style.width = (x2 - x1) * s + "px"; d.style.height = (y2 - y1) * s + "px";
    d.dataset.id = l.id;
    d.title = item.noise ? ("噪声候选：" + (l.filter_reason || "noise")) : "";
    d.onclick = () => {
      if (panMoved) { panMoved = false; return; }
      // eraseMode 是 regionSelectMode 内的子模式（见 setEraseMode），必须先判它，
      // 否则下面的 regionSelectMode 提前 return 会让擦除分支永远走不到。
      if (eraseMode && !item.noise) { doDelete(l.id); return; }
      if (regionSelectMode) return;
      if (item.noise) return;
      activateRow(l.id);
    };
    box.appendChild(d);
  }
}

function clampPan() {
  if (typeof settings !== "undefined" && settings.pan_bound === false) return;
  const left = $("#left"), cw = left.clientWidth, ch = left.clientHeight;
  const sw = baseW * zoom, sh = baseH * zoom;
  if (sw >= cw) panX = Math.min(0, Math.max(cw - sw, panX));
  if (sh >= ch) panY = Math.min(0, Math.max(ch - sh, panY));
}
function applyTransform() {
  clampPan();
  $("#imgWrap").style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  $("#zoomPct").textContent = Math.round(zoom * 100) + "%";
}
function layoutImage() {
  const left = $("#left"), img = $("#pageImg"), wrap = $("#imgWrap");
  wrap.style.width = left.clientWidth + "px";
  baseW = wrap.offsetWidth;
  baseH = img.clientHeight || baseW * ((page().height || 1) / (page().width || 1));
  positionBoxes();
  applyTransform();
}
function zoomAtPoint(cx, cy, nz) {
  const contentX = (cx - panX) / zoom, contentY = (cy - panY) / zoom;
  zoom = nz; panX = cx - contentX * zoom; panY = cy - contentY * zoom;
  applyTransform();
}
function setZoom(z) {
  z = Math.min(ZMAX, Math.max(ZMIN, z));
  const left = $("#left");
  zoomAtPoint(left.clientWidth / 2, left.clientHeight / 2, z);
}
function resetZoom() { zoom = 1; panX = 0; panY = 0; applyTransform(); }

function setRegionOcrBusy(isBusy) {
  const el = $("#regionOcrStatus");
  if (!el) return;
  el.classList.toggle("hidden", !isBusy);
}

function imagePointFromClient(e) {
  const r = $("#left").getBoundingClientRect();
  const s = baseW / (page().width || 1);
  return [((e.clientX - r.left - panX) / zoom) / s, ((e.clientY - r.top - panY) / zoom) / s];
}

async function submitRegionOcr(box) {
  const pg = page();
  setRegionOcrBusy(true);
  await new Promise((resolve) => requestAnimationFrame(resolve));
  try {
    const res = await api("/api/reocr_region", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ batch: proof.batch, page_id: pg.page_id, box }) });
    const lines = res.lines || [];
    if (!lines.length) return toast("框选区域未识别到文字");
    resetTextUndoMerge();
    pushUndo();
    const maxNum = (pg.lines || []).reduce((m, l) => {
      const n = Number(String(l.id || "").split("__").pop()); return Number.isFinite(n) ? Math.max(m, n) : m;
    }, -1);
    lines.forEach((line, idx) => {
      const text = String(line.text || "").trim();
      if (!text) return;
      pg.lines.push({ id: `${pg.page_id}__${maxNum + idx + 1}`, text_ocr: text, text_draft: text, text,
        box: line.box, score: line.score || 0.9, source: line.source || "manual_region", para_break: false, deleted: false });
    });
    pg.order = pg.lines.filter((l) => !l.deleted).sort((a, b) => {
      const ax = (a.box[0] + a.box[2]) / 2, bx = (b.box[0] + b.box[2]) / 2;
      const ay = (a.box[1] + a.box[3]) / 2, by = (b.box[1] + b.box[3]) / 2;
      return bx - ax || ay - by;
    }).map((l) => l.id);
    render(); refreshStats(); toast(`已追加 ${lines.length} 条识别结果`);
  } catch (e) { toast("框选重识别失败：" + e.message); }
  finally {
    setRegionOcrBusy(false);
    setRegionSelectMode(false);
  }
}

(() => {
  const left = $("#left");
  left.addEventListener("wheel", (e) => {
    if (!proof) return;
    e.preventDefault();
    const nz = Math.min(ZMAX, Math.max(ZMIN, zoom * (e.deltaY < 0 ? WHEEL_ZOOM_STEP : 1 / WHEEL_ZOOM_STEP)));
    if (nz === zoom) return;
    const r = left.getBoundingClientRect();
    zoomAtPoint(e.clientX - r.left, e.clientY - r.top, nz);
  }, { passive: false });

  let panning = false, selecting = false, selEl = null, psx, psy, p0x, p0y, selStart = null;
  left.addEventListener("mousedown", (e) => {
    if (e.button !== 0 || !proof || e.target.closest("#zoomCtl")) return;
    if (eraseMode && e.altKey) { e.preventDefault(); return; }
    if (regionSelectMode && !eraseMode) {
      selecting = true; panMoved = false; psx = e.clientX; psy = e.clientY; selStart = imagePointFromClient(e);
      selEl = document.createElement("div"); selEl.className = "region-sel"; $("#imgWrap").appendChild(selEl);
      e.preventDefault(); return;
    }
    panning = true; panMoved = false; psx = e.clientX; psy = e.clientY; p0x = panX; p0y = panY;
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (selecting && selEl) {
      const r = $("#left").getBoundingClientRect();
      const x = Math.min(e.clientX, psx) - r.left - panX;
      const y = Math.min(e.clientY, psy) - r.top - panY;
      selEl.style.left = (x / zoom) + "px"; selEl.style.top = (y / zoom) + "px";
      selEl.style.width = (Math.abs(e.clientX - psx) / zoom) + "px";
      selEl.style.height = (Math.abs(e.clientY - psy) / zoom) + "px";
      return;
    }
    if (!panning) return;
    const dx = e.clientX - psx, dy = e.clientY - psy;
    if (Math.abs(dx) + Math.abs(dy) > PAN_MOVE_PX) { panMoved = true; left.classList.add("panning"); }
    panX = p0x + dx; panY = p0y + dy; applyTransform();
  });
  window.addEventListener("mouseup", (e) => {
    if (selecting) {
      const end = imagePointFromClient(e), start = selStart || end;
      if (selEl) selEl.remove(); selEl = null; selecting = false;
      const box = [Math.min(start[0], end[0]), Math.min(start[1], end[1]), Math.max(start[0], end[0]), Math.max(start[1], end[1])];
      if (Math.abs(box[2] - box[0]) > 8 && Math.abs(box[3] - box[1]) > 8) submitRegionOcr(box);
    }
    panning = false; left.classList.remove("panning");
  });

  $("#zoomReset").onclick = resetZoom;
  $("#zoomIn").onclick = () => setZoom(zoom * BTN_ZOOM_STEP);
  $("#zoomOut").onclick = () => setZoom(zoom / BTN_ZOOM_STEP);
  if ($("#boxToggle")) { $("#boxToggle").onclick = toggleRegionSelectMode; syncBoxToggle(); }
  if ($("#boxErase")) $("#boxErase").onclick = toggleEraseMode;

  const divider = $("#divider"), main = $("#main"), leftPane = $("#left");
  let resizing = false;
  divider.addEventListener("mousedown", (e) => { resizing = true; e.preventDefault(); document.body.style.cursor = "col-resize"; });
  window.addEventListener("mousemove", (e) => {
    if (!resizing) return;
    const r = main.getBoundingClientRect();
    const w = Math.min(r.width * 0.7, Math.max(r.width * 0.3, e.clientX - r.left));
    leftPane.style.flex = `0 0 ${w}px`;
    if (proof) layoutImage();
  });
  window.addEventListener("mouseup", () => { if (resizing) { resizing = false; document.body.style.cursor = ""; } });
  window.addEventListener("resize", () => { if (proof) layoutImage(); });
  syncBoxToggle();
})();

