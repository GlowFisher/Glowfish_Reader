"use strict";
/* ============================================================
 * Glowfish Reader 史料阅读器 · 一体化弹窗登录子系统
 *
 * 单一模态弹窗，内含三视图：登录 / 注册 / 找回密码。默认「手机密码登录」。
 * 三层解耦：
 *   · View 层     —— DOM 构建、视图切换、消息、验证码倒计时
 *   · Validate 层 —— 纯函数校验（手机号/密码/一致性/非空）
 *   · Api 层      —— 唯一 fetch 出口，后端对接点位集中于此
 *
 * 硬约束：仅模态浮层，不开独立系统窗口；未登录 Esc / 点遮罩不关闭；
 *         切换视图清空上一视图输入（状态隔离）。
 *
 * 加载顺序：须在 auth-guard.js 之前引入——本文件在此刻捕获原生 fetch，
 * 使弹窗自身的登录/校验请求（含预期内的 401 错误密码）不触发 auth-guard 的
 * 401→再弹窗逻辑。
 * ============================================================ */
(function () {
  // 原生 fetch 快照（早于 auth-guard 包装）
  const rawFetch = window.fetch.bind(window);

  const Api = window.GlowfishApi.account;

  // ======================= Validate 层 ========================
  // 纯函数，返回 {ok:boolean, msg:string}。前端体验层校验，后端须二次校验。
  const PHONE_RE = /^1[3-9]\d{9}$/;
  const PWD_RE = /^[A-Za-z0-9]{6,}$/;   // ≥6 位，数字/大小写字母
  const V = {
    phone: (v) => PHONE_RE.test((v || "").trim())
      ? { ok: true } : { ok: false, msg: "请输入正确的 11 位手机号" },
    password: (v) => PWD_RE.test(v || "")
      ? { ok: true } : { ok: false, msg: "密码至少 6 位，仅限数字与大小写字母" },
    match: (a, b) => a === b ? { ok: true } : { ok: false, msg: "两次输入的密码不一致" },
    required: (v, name) => (v || "").trim()
      ? { ok: true } : { ok: false, msg: "请填写" + name },
  };

  // ========================== View 层 =========================
  const CODE_TEXT = "获取验证码";
  const COOLDOWN = 60;
  let root = null, overlay = null, built = false;
  const timers = {};            // 各验证码按钮的倒计时 interval，按 scene 记

  const TEMPLATE = `
  <div class="gf-overlay" role="dialog" aria-modal="true" aria-label="账号登录">
    <div class="gf-card">
      <div class="gf-brand">
        <div class="gf-wordmark-line">
          <span class="gf-wordmark">Glowfish Reader</span>
          <span class="gf-brand-name">史料阅读器</span>
        </div>
        <p class="gf-title" data-title>登录页面</p>
      </div>

      <div class="gf-stack">
        <!-- 视图① 登录（默认） -->
        <form class="gf-view gf-active" data-view="login" autocomplete="on" novalidate>
          <label>手机号</label>
          <input data-f="phone" type="tel" inputmode="numeric" maxlength="11" autocomplete="username" aria-label="手机号" placeholder="请输入手机号">
          <label>密码</label>
          <input data-f="password" type="password" autocomplete="current-password" aria-label="密码" placeholder="请输入密码">
          <button class="gf-submit" type="submit">登 录</button>
        </form>

        <!-- 视图② 注册 -->
        <form class="gf-view" data-view="register" autocomplete="off" novalidate>
          <label>手机号码</label>
          <input data-f="phone" type="tel" inputmode="numeric" maxlength="11" aria-label="注册手机号码" placeholder="请输入手机号">
          <label>短信验证码</label>
          <div class="gf-row">
            <input data-f="code" type="text" inputmode="numeric" maxlength="6" aria-label="短信验证码" placeholder="6 位验证码">
            <button class="gf-code-btn" type="button" data-code="register">${CODE_TEXT}</button>
          </div>
          <label>设置密码</label>
          <input data-f="password" type="password" autocomplete="new-password" aria-label="设置密码" placeholder="6 位以上，数字/字母">
          <label>确认密码</label>
          <input data-f="password2" type="password" autocomplete="new-password" aria-label="确认密码" placeholder="再次输入密码">
          <button class="gf-submit" type="submit">注 册</button>
        </form>

        <!-- 视图③ 找回密码 -->
        <form class="gf-view" data-view="forgot" autocomplete="off" novalidate>
          <label>绑定手机号</label>
          <input data-f="phone" type="tel" inputmode="numeric" maxlength="11" aria-label="绑定手机号" placeholder="请输入注册手机号">
          <label>短信验证码</label>
          <div class="gf-row">
            <input data-f="code" type="text" inputmode="numeric" maxlength="6" aria-label="短信验证码" placeholder="6 位验证码">
            <button class="gf-code-btn" type="button" data-code="reset">${CODE_TEXT}</button>
          </div>
          <label>新密码</label>
          <input data-f="password" type="password" autocomplete="new-password" aria-label="新密码" placeholder="6 位以上，数字/字母">
          <label>确认新密码</label>
          <input data-f="password2" type="password" autocomplete="new-password" aria-label="确认新密码" placeholder="再次输入新密码">
          <button class="gf-submit" type="submit">重置密码</button>
        </form>
      </div>

      <div class="gf-msg" data-msg></div>

      <!-- 切换入口①：登录 → 注册/找回 -->
      <div class="gf-switch" data-switch="login">
        <button class="gf-link" type="button" data-go="register">前往注册</button>
        <button class="gf-link" type="button" data-go="forgot">忘记密码</button>
      </div>
      <!-- 切换入口②：注册 → 登录 -->
      <div class="gf-switch" data-switch="register" hidden>
        <button class="gf-link" type="button" data-go="login">已有账号，返回登录</button>
      </div>
      <!-- 切换入口③：找回 → 登录 -->
      <div class="gf-switch" data-switch="forgot" hidden>
        <button class="gf-link" type="button" data-go="login">返回登录</button>
      </div>

      <div class="gf-foot">账号仅用于授权登录，您的数据全程留存本地，不随账号上传。</div>
    </div>
  </div>`;

  const TITLES = { login: "登录页面", register: "注册新账号", forgot: "找回密码" };

  function q(sel) { return overlay.querySelector(sel); }
  function viewEl(name) { return q('.gf-view[data-view="' + name + '"]'); }

  function setMsg(text, ok) {
    const m = q("[data-msg]");
    m.textContent = text || "";
    m.className = "gf-msg " + (text ? (ok ? "gf-ok" : "gf-err") : "");
  }

  // 状态隔离：清空指定视图所有输入 + 复位其验证码倒计时
  function resetView(name) {
    viewEl(name).querySelectorAll("input").forEach((i) => { i.value = ""; });
    const btn = viewEl(name).querySelector("[data-code]");
    if (btn) clearCountdown(btn.dataset.code);
  }

  // 切换视图（三处入口统一走此函数）
  function switchView(name) {
    ["login", "register", "forgot"].forEach((v) => {
      viewEl(v).classList.toggle("gf-active", v === name);
      const sw = q('[data-switch="' + v + '"]');
      if (sw) sw.hidden = v !== name;
    });
    q("[data-title]").textContent = TITLES[name];
    setMsg("");
    resetView(name);                                  // 清空目标视图残留内容
    const first = viewEl(name).querySelector("input");
    if (first) setTimeout(() => first.focus(), 30);
  }

  // 验证码倒计时
  function clearCountdown(scene) {
    if (timers[scene]) { clearInterval(timers[scene]); delete timers[scene]; }
    const btn = q('[data-code="' + scene + '"]');
    if (btn) { btn.disabled = false; btn.textContent = CODE_TEXT; }
  }
  function startCountdown(scene) {
    const btn = q('[data-code="' + scene + '"]');
    let left = COOLDOWN;
    btn.disabled = true; btn.textContent = left + " 秒后重发";
    timers[scene] = setInterval(() => {
      left -= 1;
      if (left <= 0) { clearCountdown(scene); return; }
      btn.textContent = left + " 秒后重发";
    }, 1000);
  }

  async function onGetCode(scene) {
    const view = scene === "register" ? "register" : "forgot";
    const phone = viewEl(view).querySelector('[data-f="phone"]').value.trim();
    const chk = V.phone(phone);
    if (!chk.ok) return setMsg(chk.msg);
    const btn = q('[data-code="' + scene + '"]');
    btn.disabled = true;
    try {
      const r = await Api.sendSms(phone, scene);
      startCountdown(scene);
      setMsg(r && r.dev_code ? "验证码已发送（开发模式：" + r.dev_code + "）" : "验证码已发送", true);
    } catch (e) {
      btn.disabled = false;
      setMsg(e.message);
    }
  }

  // 提交：登录
  async function submitLogin(form) {
    const phone = form.querySelector('[data-f="phone"]').value.trim();
    const password = form.querySelector('[data-f="password"]').value;
    for (const c of [V.phone(phone), V.required(password, "密码")]) if (!c.ok) return setMsg(c.msg);
    await withBusy(form, async () => {
      await Api.login(phone, password);
      setMsg("登录成功，正在进入…", true);
      location.reload();                              // 重载即由 auth-guard 放行进入主界面
    });
  }

  // 提交：注册（成功回登录视图，不自动进入）
  async function submitRegister(form) {
    const f = (n) => form.querySelector('[data-f="' + n + '"]');
    const phone = f("phone").value.trim(), code = f("code").value.trim();
    const pwd = f("password").value, pwd2 = f("password2").value;
    for (const c of [V.phone(phone), V.required(code, "验证码"), V.password(pwd), V.match(pwd, pwd2)])
      if (!c.ok) return setMsg(c.msg);
    await withBusy(form, async () => {
      const r = await Api.register(phone, code, pwd);
      // 云模式：服务器注册即下发凭据（logged_in），直接进主界面，不必再登录一次。
      if (r && r.logged_in) {
        setMsg("注册成功，正在进入……", true);
        location.reload();
        return;
      }
      switchView("login");
      setMsg("注册成功，请用手机号登录", true);
    });
  }

  // 提交：找回密码（成功回登录视图）
  async function submitForgot(form) {
    const f = (n) => form.querySelector('[data-f="' + n + '"]');
    const phone = f("phone").value.trim(), code = f("code").value.trim();
    const pwd = f("password").value, pwd2 = f("password2").value;
    for (const c of [V.phone(phone), V.required(code, "验证码"), V.password(pwd), V.match(pwd, pwd2)])
      if (!c.ok) return setMsg(c.msg);
    await withBusy(form, async () => {
      await Api.resetPassword(phone, code, pwd);
      switchView("login");
      setMsg("密码已重置，请用新密码登录", true);
    });
  }

  // 提交期间禁用按钮，防重复提交
  async function withBusy(form, fn) {
    const btn = form.querySelector(".gf-submit");
    btn.disabled = true;
    try { await fn(); }
    catch (e) { setMsg(e.message); }
    finally { btn.disabled = false; }
  }

  function build() {
    root = document.getElementById("gf-login-modal-root");
    if (!root) { root = document.createElement("div"); root.id = "gf-login-modal-root"; document.body.appendChild(root); }
    root.innerHTML = TEMPLATE;
    overlay = root.querySelector(".gf-overlay");   // 用 root 取；此刻 overlay 尚未赋值，不能用 q()

    // 深色主题：与登录页一致，读 localStorage gf-theme
    try { if (localStorage.getItem("gf-theme") === "dark") overlay.classList.add("gf-dark"); } catch (e) {}

    // 视图切换入口（三处）
    overlay.querySelectorAll("[data-go]").forEach((b) => { b.onclick = () => switchView(b.dataset.go); });
    // 获取验证码
    overlay.querySelectorAll("[data-code]").forEach((b) => { b.onclick = () => onGetCode(b.dataset.code); });
    // 表单提交
    const handlers = { login: submitLogin, register: submitRegister, forgot: submitForgot };
    overlay.querySelectorAll(".gf-view").forEach((form) => {
      form.onsubmit = (e) => { e.preventDefault(); handlers[form.dataset.view](form); };
    });
    // 硬约束：点遮罩空白不关闭（未登录必须完成登录）
    overlay.onclick = (e) => { if (e.target === overlay) e.stopPropagation(); };
    built = true;
  }

  // ========================= 对外 API =========================
  const Modal = {
    open(opts) {
      if (!built) build();
      if (root.dataset.open === "1") return;          // 幂等：已开则不重置，避免误触重弹
      root.dataset.open = "1";
      overlay.style.display = "flex";
      document.body.style.overflow = "hidden";
      switchView("login");                            // 默认「手机密码登录」
      if (opts && opts.notice) setMsg(opts.notice);   // 到期/停用等提示随窗展示
    },
    close() {
      if (!built || root.dataset.open !== "1") return;
      root.dataset.open = "0";
      overlay.style.display = "none";
      document.body.style.overflow = "";
      Object.keys(timers).forEach(clearCountdown);
    },
    switchView: (name) => { if (built) switchView(name); },
  };
  window.GlowfishLoginModal = Modal;
})();
