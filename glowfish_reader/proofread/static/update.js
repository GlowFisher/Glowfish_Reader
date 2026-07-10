"use strict";
/* 应用更新（仅桌面单机版启用）：开机后台检查 → 顶部横幅 → 下载进度 → sha256 校验后一键安装重启。
 * 自包含：样式/横幅/弹窗全部由本文件注入，仅复用 app.js 的全局 $ / api / toast。
 * 后端见 update_api.py / updater.py。素材永不上传；更新检查只向官方服务器发版本号。 */
(function () {
  const POLL_MS = 600;
  const CHECK_DELAY_MS = 4000;            // 开机延后检查，避让预热/选文件，且等 settings 载入
  let info = null;                        // 最近一次 /api/update/check 结果
  let pollTimer = null;

  function injectStyle() {
    if ($("#upd-style")) return;
    const css = `
      .upd-banner{position:fixed;left:0;right:0;top:0;z-index:9000;display:flex;align-items:center;
        gap:12px;padding:8px 16px;background:#1c3c66;color:#fff;font-size:14px;
        box-shadow:0 2px 8px rgba(0,0,0,.25)}
      .upd-banner .upd-msg{flex:1}
      .upd-banner.hidden{display:none}
      .upd-progress{height:8px;border-radius:5px;background:rgba(0,0,0,.12);overflow:hidden;margin:14px 0 4px}
      .upd-progress.hidden{display:none}
      .upd-bar{height:100%;width:0;background:#1c3c66;transition:width .25s ease}
      .upd-ver{color:var(--muted,#888);font-size:13px;margin-right:auto;align-self:center}`;
    const s = document.createElement("style");
    s.id = "upd-style"; s.textContent = css;
    document.head.appendChild(s);
  }

  function ensureBanner() {
    let b = $("#updateBanner");
    if (b) return b;
    b = document.createElement("div");
    b.id = "updateBanner"; b.className = "upd-banner hidden";
    b.innerHTML = `<span class="upd-msg"></span>
      <span class="upd-actions">
        <button class="btn btn-main" id="updNow">立即更新</button>
        <button class="btn btn-sec" id="updNotes">更新内容</button>
        <button class="btn btn-sec" id="updLater">稍后</button>
      </span>`;
    document.body.appendChild(b);
    $("#updNow").onclick = startUpdate;
    $("#updNotes").onclick = showNotes;
    $("#updLater").onclick = () => { if (!(info && info.mandatory)) b.classList.add("hidden"); };
    return b;
  }

  function ensureModal() {
    let m = $("#updateModal");
    if (m) return m;
    m = document.createElement("div");
    m.id = "updateModal"; m.className = "modal-mask hidden";
    m.innerHTML = `<div class="modal">
        <div class="modal-title" id="updTitle">应用更新</div>
        <div class="modal-body" id="updBody"></div>
        <div class="upd-progress hidden" id="updProgWrap"><div class="upd-bar" id="updBar"></div></div>
        <div class="modal-actions" id="updModalActions">
          <button class="btn btn-sec" id="updClose">关闭</button>
        </div>
      </div>`;
    document.body.appendChild(m);
    $("#updClose").onclick = () => { if (!(info && info.mandatory)) m.classList.add("hidden"); };
    return m;
  }

  function setBar(pct) { const el = $("#updBar"); if (el) el.style.width = Math.max(0, Math.min(100, pct)) + "%"; }

  function showBanner(r) {
    const b = ensureBanner();
    b.querySelector(".upd-msg").textContent = r.mandatory
      ? `【必须更新】新版本 v${r.latest} 修复关键问题，请立即更新`
      : `发现新版本 v${r.latest}（当前 v${r.current}）`;
    $("#updNow").textContent = "立即更新"; $("#updNow").onclick = startUpdate;   // 防模型横幅残留态
    $("#updNotes").style.display = "";
    $("#updLater").style.display = r.mandatory ? "none" : "";
    b.classList.remove("hidden");
  }

  function showNotes() {
    const m = ensureModal();
    $("#updTitle").textContent = `更新内容 · v${info ? info.latest : ""}`;
    $("#updBody").textContent = (info && info.notes) || "（本次更新暂无说明）";
    $("#updProgWrap").classList.add("hidden");
    resetModalActions();
    m.classList.remove("hidden");
  }

  function resetModalActions() {
    const acts = $("#updModalActions");
    acts.innerHTML = `<button class="btn btn-sec" id="updClose">关闭</button>`;
    $("#updClose").onclick = () => { if (!(info && info.mandatory)) $("#updateModal").classList.add("hidden"); };
  }

  async function startUpdate() {
    const m = ensureModal();
    $("#updTitle").textContent = `下载更新 · v${info ? info.latest : ""}`;
    $("#updBody").textContent = "正在下载…更新包来自官方服务器，您的史料数据始终留在本机。";
    $("#updProgWrap").classList.remove("hidden"); setBar(0);
    resetModalActions();
    m.classList.remove("hidden");
    try { await api("/api/update/download", { method: "POST" }); }
    catch (e) { $("#updBody").textContent = "启动下载失败：" + e.message; return; }
    poll();
  }

  function poll() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(async () => {
      let p;
      try { p = await api("/api/update/progress"); } catch (e) { poll(); return; }
      if (p.phase === "downloading") {
        const pct = p.total ? Math.floor(p.done / p.total * 100) : 0;
        setBar(pct); $("#updBody").textContent = `正在下载… ${pct}%`; poll();
      } else if (p.phase === "ready") {
        setBar(100);
        $("#updBody").textContent = "下载完成、校验通过。点「安装并重启」将关闭应用并自动升级；史料数据与授权不受影响。";
        showInstallActions();
      } else if (p.phase === "error") {
        $("#updBody").textContent = "更新失败：" +
          (p.error === "sha256_mismatch" ? "更新包校验不通过，请稍后重试。" : (p.error || "未知错误"));
        showRetryActions();
      } else { poll(); }                 // idle：尚未起步，继续等
    }, POLL_MS);
  }

  function showInstallActions() {
    const acts = $("#updModalActions");
    acts.innerHTML = `<button class="btn btn-main" id="updInstall">安装并重启</button>` +
      (info && info.mandatory ? "" : `<button class="btn btn-sec" id="updLaterR">稍后</button>`);
    $("#updInstall").onclick = async () => {
      $("#updInstall").disabled = true;
      $("#updBody").textContent = "正在启动安装程序，应用即将关闭并自动升级…";
      try { await api("/api/update/apply", { method: "POST" }); } catch (e) {}
      // apply 成功后桌面壳会关窗退出；安装器接管，无需前端再动作
    };
    const lr = $("#updLaterR"); if (lr) lr.onclick = () => $("#updateModal").classList.add("hidden");
  }

  function showRetryActions() {
    const acts = $("#updModalActions");
    acts.innerHTML = `<button class="btn btn-main" id="updRetry">重试</button>
      <button class="btn btn-sec" id="updCloseR">关闭</button>`;
    $("#updRetry").onclick = startUpdate;
    $("#updCloseR").onclick = () => { if (!(info && info.mandatory)) $("#updateModal").classList.add("hidden"); };
  }


  // 帮助面板（按 ?）注入：当前版本号 + 手动「检查更新」
  function injectHelpEntry() {
    const acts = document.querySelector("#shortcutModal .modal-actions");
    if (!acts || $("#updCheckBtn")) return;
    const ver = document.createElement("span"); ver.id = "updVer"; ver.className = "upd-ver";
    const btn = document.createElement("button");
    btn.id = "updCheckBtn"; btn.className = "btn btn-sec"; btn.textContent = "检查更新";
    btn.onclick = () => check(true);
    acts.insertBefore(ver, acts.firstChild);
    acts.insertBefore(btn, ver);
  }

  function setHelpVersion(v) { const el = $("#updVer"); if (el && v) el.textContent = `当前版本 v${v}`; }

  async function check(manual) {
    let r;
    try { r = await api("/api/update/check"); }
    catch (e) { if (manual) toast("检查更新失败：" + e.message); return; }
    info = r;
    setHelpVersion(r.current);
    if (r.has_update) showBanner(r);                       // 程序更新优先（升完下次启动再提模型）
    else if (manual) toast(`已是最新版本 v${r.current}`);
  }

  // ---- 初始化：仅桌面单机版启用 ----
  (async function init() {
    let me;
    try { me = await api("/api/me"); } catch (e) { return; }
    if (!me || me.single !== true) return;          // 多用户网页版不走应用内更新
    injectStyle();
    injectHelpEntry();
    setTimeout(() => {
      const auto = (typeof settings === "undefined") || settings.auto_check_update !== false;
      if (auto) check(false);                          // 关闭自动检查则不发请求；版本号待帮助面板手动「检查更新」时再填
    }, CHECK_DELAY_MS);
  })();
})();
