"use strict";
/* 登录闸（须作为首个脚本加载）：
 * 1) 包裹 window.fetch——任意请求遇 401 即跳登录页（会话过期/未登录统一处理）；
 * 2) 启动即校验 /api/me，未登录跳登录页；已登录则填顶栏用户区并接线登出。
 * 注：原生 cookie(sid) 为 httponly，JS 不可读，登录态完全以服务端会话为准。 */
(function () {
  const LOGIN = "/login.html";
  const _fetch = window.fetch.bind(window);
  let redirecting = false;
  const toLogin = (notice) => {
    // 主路径：在主界面上层弹出登录模态（不跳独立页、不开系统窗口）；
    // notice 为需要在登录窗展示的提示（如「使用期限已到期…」）
    if (window.GlowfishLoginModal) { window.GlowfishLoginModal.open(notice ? { notice } : undefined); return; }
    // 兜底：弹窗组件未加载成功时，退回独立登录页
    if (redirecting) return;
    redirecting = true; location.href = LOGIN;
  };

  window.fetch = async function (input, init) {
    const resp = await _fetch(input, init);
    if (resp.status === 401) toLogin();
    return resp;
  };

  function clearLocalCache() {
    return new Promise((resolve) => {
      try {
        const req = indexedDB.deleteDatabase("glowfish-reader");
        req.onsuccess = req.onerror = req.onblocked = () => resolve();
        setTimeout(resolve, 1500);
      } catch (e) { resolve(); }
    });
  }

  // 到期时间有两种形态：本机试用给的是 "2026-08-31" 日期串，云账号给的是 Unix 秒级时间戳。
  // 直接拼接会把时间戳原样显示成「试用有效期至 1784737921」。
  function formatExpiry(v) {
    if (typeof v === "number" || /^\d{9,11}$/.test(String(v))) {
      const d = new Date(Number(v) * 1000);
      if (isNaN(d.getTime())) return String(v);
      const p = (n) => String(n).padStart(2, "0");
      return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
    }
    return String(v);
  }

  function entitlementLabel(ent) {
    if (!ent || !ent.mode || !ent.expires_at) return "";
    if (ent.mode === "trial") return "试用有效期至 " + formatExpiry(ent.expires_at);
    if (ent.mode === "member") return "会员有效期至 " + formatExpiry(ent.expires_at);
    return "";
  }

  function setAccountMenuOpen(open) {
    const btn = document.getElementById("accountBtn");
    const menu = document.getElementById("accountMenu");
    if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (menu) menu.classList.toggle("hidden", !open);
  }

  function renderAccount(me) {
    const displayName = me.display || me.username || "本机用户";
    const box = document.getElementById("accountBox");
    const menuName = document.getElementById("accountMenuName");
    const menuStatus = document.getElementById("accountMenuStatus");
    const accountBtn = document.getElementById("accountBtn");
    const accountMenu = document.getElementById("accountMenu");
    const out = document.getElementById("logoutBtn");
    const label = entitlementLabel(me.entitlement);

    if (menuName) menuName.textContent = displayName;
    if (menuStatus) {
      menuStatus.textContent = label;
      menuStatus.classList.toggle("hidden", !label);
    }
    if (box) box.classList.remove("hidden");
    if (accountBtn && accountMenu) {
      accountBtn.onclick = (e) => {
        e.stopPropagation();
        setAccountMenuOpen(accountMenu.classList.contains("hidden"));
      };
      accountMenu.onclick = (e) => e.stopPropagation();
      document.addEventListener("click", () => setAccountMenuOpen(false));
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape") setAccountMenuOpen(false);
      });
    }
    if (out) out.onclick = async () => {
      setAccountMenuOpen(false);
      try { await _fetch("/api/logout", { method: "POST" }); } catch (e) {}
      try { localStorage.removeItem("gf_user"); await clearLocalCache(); } catch (e) {}
      location.reload();   // 重载后 /api/me 返 401 → toLogin() 弹出登录模态，同时清空登出前的账号 UI
    };
  }

  async function init() {
    let me;
    try {
      const r = await _fetch("/api/me");
      if (!r.ok) return toLogin();
      me = await r.json();
    } catch (e) { return toLogin(); }

    // single 模式下 /api/me 仅在「云账号未登录」时返 single:true——此时同样弹登录闸，
    // 不再豁免（登录成功后 account_user() 有值，/api/me 改返 single:false 放行）。
    // 数据目录不受影响：current_user 在 single 模式恒为本机用户 uid=local。
    if (me.single) {
      document.body.dataset.mode = "single";
      return toLogin(me.notice);
    }

    if (!me.single) {
      try {
        const last = localStorage.getItem("gf_user");
        if (last && last !== me.username) {
          localStorage.setItem("gf_user", me.username);
          await clearLocalCache();
          location.reload();
          return;
        }
        localStorage.setItem("gf_user", me.username);
      } catch (e) {}
    }

    renderAccount(me);
  }
  init();
})();