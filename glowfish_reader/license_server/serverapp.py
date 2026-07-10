# -*- coding: utf-8 -*-
"""账号服务器 FastAPI 薄层。

账号登录、注册试用和网页后台。服务端仍只保存账号/权限/使用汇总，
不接收史料图片、OCR 文本、文件名或路径。
"""
import html
import os, secrets, time, sqlite3, urllib.parse
from collections import defaultdict, deque
from fastapi import FastAPI, Request, Response, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
import core, sign, sms

DB_PATH = os.environ.get("LICENSE_DB", "license.db")
SMS_SEND_COOLDOWN = int(os.environ.get("SMS_SEND_COOLDOWN", "60"))   # 同号发码冷却秒
SMS_DAILY_LIMIT = int(os.environ.get("SMS_DAILY_LIMIT", "5"))         # 同号单日发码上限
SMS_CODE_TTL = int(os.environ.get("SMS_CODE_TTL", "300"))            # 验证码有效秒
SERVER_PRIV = os.environ.get("SERVER_PRIV", "")
SERVER_PUB = sign.pub_from_priv(SERVER_PRIV) if SERVER_PRIV else ""
ADMIN_BOOTSTRAP_USER = os.environ.get("ADMIN_USER", "")
ADMIN_BOOTSTRAP_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
# 后台「重置密码」留空时使用的默认口令（须 ≥6 位，否则 core 会判 weak_password）
ADMIN_DEFAULT_PASSWORD = os.environ.get("ADMIN_DEFAULT_PASSWORD", "123456")
_ADMIN_RESET_MSG = {
    "weak_password": "重置失败：密码至少 6 位",
    "unknown_account": "重置失败：账号不存在",
}

# 限流（兜底，生产仍应置于 HTTPS 反向代理后）：每 IP 每窗口最多 N 次 POST
RATE_LIMIT = int(os.environ.get("LICENSE_RATE_LIMIT", "60"))
RATE_WINDOW = int(os.environ.get("LICENSE_RATE_WINDOW", "60"))
_hits = defaultdict(deque)


def _db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False); core.init_db(c); return c


app = FastAPI(title="Glowfish License Server")
_conn = _db()
if ADMIN_BOOTSTRAP_USER and ADMIN_BOOTSTRAP_PASSWORD and core.admin_count(_conn) == 0:
    core.admin_upsert(_conn, ADMIN_BOOTSTRAP_USER, ADMIN_BOOTSTRAP_PASSWORD, now=int(time.time()))


def _session_secs(body) -> int:
    # 客户端上报的本次会话秒数；钳制到 [0, 1 天] 防负值/恶意刷量污染统计
    try:
        v = int(body.get("session_seconds", 0) or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, min(v, 86400))


def _public_account(info):
    keys = ("user_id", "username", "display", "phone", "status", "tier", "expires_at",
            "trial_expires_at", "subscription_expires_at", "checked_at", "allowed")
    return {k: info.get(k) for k in keys if k in info}


def _make_account_cred(info):
    payload = {k: info[k] for k in ("session_id", "user_id", "username", "phone", "status",
                                    "tier", "expires_at", "checked_at") if k in info}
    payload["typ"] = "account"
    return sign.make_signed(payload, SERVER_PRIV)


def _json_error(reason, status_code=400, **extra):
    return JSONResponse({"ok": False, "reason": reason, **extra}, status_code=status_code)


def _client_ip(req: Request) -> str:
    xff = req.headers.get("x-forwarded-for")        # 仅在受信反代后才有意义
    if xff:
        return xff.split(",")[0].strip()
    return req.client.host if req.client else "?"


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.method == "POST":
        ip = _client_ip(request)
        now = time.time()
        dq = _hits[ip]
        while dq and dq[0] <= now - RATE_WINDOW:
            dq.popleft()
        if len(dq) >= RATE_LIMIT:
            return JSONResponse({"ok": False, "reason": "rate_limited"}, status_code=429)
        dq.append(now)
    return await call_next(request)


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/notices.json")
def serve_notices():
    from fastapi.responses import JSONResponse
    return JSONResponse(core._read_notices())


@app.post("/account/register")
async def account_register(req: Request):
    body = await req.json()
    now = int(time.time())
    r = core.create_account(_conn, body.get("username"), body.get("password"), now=now, trial_days=14)
    if not r.get("ok"):
        return r
    sess = core.create_account_session(
        _conn, r["user_id"], now=now, fingerprint=body.get("fingerprint", ""),
        app_version=body.get("app_version", ""))
    checked = core.check_account_session(
        _conn, sess["session_id"], now=now, fingerprint=body.get("fingerprint", ""),
        app_version=body.get("app_version", ""))
    if not checked.get("ok"):
        return checked      # 到期/停用：明确返回 reason，不签出缺 session_id 的残废凭据
    return {"ok": True, "cred": _make_account_cred(checked), "account": _public_account(checked)}


@app.post("/account/login")
async def account_login(req: Request):
    body = await req.json()
    now = int(time.time())
    r = core.verify_account_password(_conn, body.get("username"), body.get("password"), now=now)
    if not r.get("ok"):
        return r
    sess = core.create_account_session(
        _conn, r["user_id"], now=now, fingerprint=body.get("fingerprint", ""),
        app_version=body.get("app_version", ""))
    checked = core.check_account_session(
        _conn, sess["session_id"], now=now, fingerprint=body.get("fingerprint", ""),
        app_version=body.get("app_version", ""))
    if not checked.get("ok"):
        return checked      # 到期/停用：明确返回 reason，不签出缺 session_id 的残废凭据
    return {"ok": True, "cred": _make_account_cred(checked), "account": _public_account(checked)}


@app.post("/account/register/phone")
async def account_register_phone(req: Request):
    body = await req.json()
    now = int(time.time())
    r = core.register_phone_account(
        _conn, body.get("phone"), body.get("code"), body.get("password"), now=now, trial_days=14)
    if not r.get("ok"):
        return r
    sess = core.create_account_session(
        _conn, r["user_id"], now=now, fingerprint=body.get("fingerprint", ""),
        app_version=body.get("app_version", ""))
    checked = core.check_account_session(
        _conn, sess["session_id"], now=now, fingerprint=body.get("fingerprint", ""),
        app_version=body.get("app_version", ""))
    if not checked.get("ok"):
        return checked      # 到期/停用：明确返回 reason，不签出缺 session_id 的残废凭据
    return {"ok": True, "session_id": sess["session_id"],
            "cred": _make_account_cred(checked), "account": _public_account(checked)}


@app.post("/account/login/password")
async def account_login_password(req: Request):
    body = await req.json()
    now = int(time.time())
    login = body.get("login") or body.get("username") or body.get("phone")
    r = core.verify_account_password(_conn, login, body.get("password"), now=now)
    if not r.get("ok"):
        return r
    sess = core.create_account_session(
        _conn, r["user_id"], now=now, fingerprint=body.get("fingerprint", ""),
        app_version=body.get("app_version", ""))
    checked = core.check_account_session(
        _conn, sess["session_id"], now=now, fingerprint=body.get("fingerprint", ""),
        app_version=body.get("app_version", ""))
    if not checked.get("ok"):
        return checked      # 到期/停用：明确返回 reason，不签出缺 session_id 的残废凭据
    return {"ok": True, "session_id": sess["session_id"],
            "cred": _make_account_cred(checked), "account": _public_account(checked)}


@app.post("/account/check")
async def account_check(req: Request):
    body = await req.json()
    now = int(time.time())
    r = core.check_account_session(
        _conn, body.get("session_id", ""), now=now, session_seconds=_session_secs(body),
        fingerprint=body.get("fingerprint", ""), app_version=body.get("app_version", ""),
        count_login=bool(body.get("count_login")))      # 仅客户端冷启动首个核对置真＝自动登录计一次
    if not r.get("ok"):
        return r
    return {"ok": True, "cred": _make_account_cred(r), "account": _public_account(r)}


@app.post("/account/logout")
async def account_logout(req: Request):
    body = await req.json()
    return core.revoke_account_session(_conn, body.get("session_id", ""))


@app.post("/account/usage")
async def account_usage(req: Request):
    body = await req.json()
    counts = body.get("counts") if isinstance(body.get("counts"), dict) else {}
    return core.record_account_usage(_conn, body.get("session_id", ""), now=int(time.time()), counts=counts)


@app.post("/account/sms/send")
async def account_sms_send(req: Request):
    body = await req.json()
    phone = (body.get("phone") or "").strip()
    now = int(time.time())
    ok, reason, retry_after = core.sms_can_send(
        _conn, phone, now, cooldown=SMS_SEND_COOLDOWN, daily_limit=SMS_DAILY_LIMIT)
    if not ok:
        return _json_error(reason, status_code=429 if reason in ("cooldown", "daily_limit") else 400,
                           retry_after=retry_after)
    code = f"{secrets.randbelow(1_000_000):06d}"
    sent = sms.send_code(phone, code)
    if not sent.get("ok"):
        return _json_error(sent.get("reason") or "sms_failed", status_code=502)
    core.sms_issue(_conn, phone, code, now, ttl=SMS_CODE_TTL)
    return {"ok": True, "ttl": SMS_CODE_TTL, "cooldown": SMS_SEND_COOLDOWN}


@app.post("/account/password/reset")
async def account_password_reset(req: Request):
    body = await req.json()
    now = int(time.time())
    r = core.reset_account_password(
        _conn, body.get("phone"), body.get("code"), body.get("password"), now=now)
    if not r.get("ok"):
        return r
    return {"ok": True}


@app.post("/account/login/phone")
async def account_login_phone(req: Request):
    body = await req.json()
    phone = (body.get("phone") or "").strip()
    now = int(time.time())
    v = core.sms_verify(_conn, phone, body.get("code", ""), now=now)
    if not v.get("ok"):
        return v
    r = core.login_or_register_phone(_conn, phone, now=now, trial_days=14)
    if not r.get("ok"):
        return r
    sess = core.create_account_session(
        _conn, r["user_id"], now=now, fingerprint=body.get("fingerprint", ""),
        app_version=body.get("app_version", ""))
    checked = core.check_account_session(
        _conn, sess["session_id"], now=now, fingerprint=body.get("fingerprint", ""),
        app_version=body.get("app_version", ""))
    if not checked.get("ok"):
        return checked      # 到期/停用：明确返回 reason，不签出缺 session_id 的残废凭据
    return {"ok": True, "session_id": sess["session_id"],
            "cred": _make_account_cred(checked), "account": _public_account(checked)}


def _admin_user(sid):
    return core.get_admin_session(_conn, sid, now=int(time.time()))


def _admin_login_html(msg=""):
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Glowfish 后台登录</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{min-height:100vh;display:grid;place-items:center;background:#fbf7ec;color:#29241b;
  font-family:"Microsoft YaHei",system-ui,sans-serif;-webkit-font-smoothing:antialiased}}
.card{{width:400px;max-width:94vw;position:relative;background:#fbf7ec;border:2px solid #4a4030;
  outline:1px solid #4a4030;outline-offset:2px;box-shadow:8px 8px 0 rgba(74,64,48,.18);padding:32px 34px 28px}}
.card::before,.card::after{{content:"";position:absolute;left:22px;right:22px;height:1px;background:rgba(168,58,38,.30)}}
.card::before{{top:13px}}.card::after{{bottom:13px}}
.brand{{text-align:center;margin-bottom:6px;padding:8px 0 16px;
  border-bottom:2px solid #4a4030;box-shadow:0 3px 0 -1px #fbf7ec,0 4px 0 -1px #4a4030}}
.brand h1{{font-weight:900;font-size:22px;letter-spacing:.35px;margin-bottom:4px}}
.brand p{{font-size:12px;color:#6f6552;letter-spacing:.8px}}
label{{display:block;font-size:12.5px;color:#6f6552;margin:14px 0 6px;letter-spacing:.4px}}
input{{width:100%;padding:10px 12px;border:1px solid #ddd2ba;border-radius:0;background:#fffdf6;
  font-size:14px;color:#29241b;outline:none;font-family:inherit;transition:border-color .14s ease}}
input:focus{{border-color:#a83a26;box-shadow:0 0 0 1px #a83a26}}
input::placeholder{{color:#bbb5a2}}
button{{width:100%;margin-top:20px;padding:11px 0;border:1px solid #a83a26;border-radius:0;
  background:#a83a26;color:#fff;font-size:14.5px;font-weight:700;cursor:pointer;letter-spacing:4px;
  font-family:inherit;transition:background .14s ease,transform .08s ease}}
button:hover{{background:#8c2f1e}}
button:active{{transform:translateY(1px)}}
.msg{{min-height:18px;color:#b5654d;font-size:12.5px;text-align:center;margin-top:14px}}
</style></head><body><form class="card" method="post" action="/admin/login">
<div class="brand"><h1>Glowfish 账号后台</h1><p>史料阅读器 · 用户管理</p></div>
<label>管理员账号</label>
<input name="username" autocomplete="username" placeholder="请输入管理员账号">
<label>密码</label>
<input name="password" type="password" autocomplete="current-password" placeholder="请输入密码">
<button type="submit">登 录</button>
<div class="msg">{html.escape(msg) if msg else ""}</div>
</form></body></html>"""


def _admin_shell(body):
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Glowfish 账号后台</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
:root{{--paper:#fbf7ec;--paper-2:#fffdf6;--paper-3:#f1ead9;--ink:#29241b;--muted:#6f6552;
  --rule:#d9ccb3;--rule-soft:#eadfcc;--brand:#a83a26;--brand-dark:#8c2f1e;
  --success:#2d6a4f;--warning:#8b6914;--danger:#b5654d;--disabled:#6f6552}}
body{{background:var(--paper);color:var(--ink);font-family:"Microsoft YaHei",system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  -webkit-font-smoothing:antialiased;min-height:100vh}}
.topbar{{position:sticky;top:0;z-index:10;background:var(--brand-dark);color:#fff;border-bottom:1px solid rgba(74,64,48,.45);
  box-shadow:0 2px 8px rgba(74,64,48,.12)}}
.topbar-inner{{max-width:1280px;margin:0 auto;min-height:56px;padding:0 24px;display:flex;align-items:center;gap:18px}}
.brand-home{{display:flex;align-items:baseline;gap:8px;color:#fff;text-decoration:none;flex:1}}
.brand-home strong{{font-size:18px;letter-spacing:.01em}}
.brand-home span{{font-size:13px;opacity:.74;font-weight:700}}
.topnav{{display:flex;align-items:center;gap:8px}}
.topnav a{{color:#fff;text-decoration:none;font-size:13px;font-weight:800;padding:8px 14px;border:1px solid rgba(255,255,255,.24);
  transition:background .16s ease,border-color .16s ease,transform .08s ease}}
.topnav a:hover,.topnav a[aria-current="page"]{{background:rgba(255,255,255,.13);border-color:rgba(255,255,255,.48)}}
.topnav a:active{{transform:translateY(1px)}}
main{{max-width:1280px;margin:0 auto;padding:28px 24px 54px}}
a{{color:var(--brand);text-decoration:none;font-weight:700;text-underline-offset:3px}}
a:hover{{color:var(--brand-dark);text-decoration:underline}}
.page-head{{display:flex;align-items:flex-end;justify-content:space-between;gap:18px;margin:4px 0 20px}}
.page-title h2{{font-size:24px;line-height:1.25;font-weight:900;letter-spacing:.01em;text-wrap:balance}}
.page-title p{{margin-top:6px;color:var(--muted);font-size:13px;line-height:1.65}}
.panel{{background:var(--paper-2);border:1px solid var(--rule);box-shadow:0 1px 0 rgba(255,255,255,.72);padding:18px 20px;margin-bottom:18px}}
.panel-title{{display:flex;align-items:center;justify-content:space-between;gap:14px;margin-bottom:14px}}
.panel-title h3,.panel-title h2{{font-size:16px;line-height:1.35;font-weight:900;margin:0}}
.panel-note,.muted{{color:var(--muted);font-size:12.5px;line-height:1.6}}
.stat-grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin-bottom:18px}}
.stat-card{{background:var(--paper-2);border:1px solid var(--rule);padding:18px 20px;min-height:96px;display:flex;justify-content:space-between;gap:16px;align-items:flex-start}}
.stat-card .label{{display:block;color:var(--muted);font-size:12.5px;font-weight:700;margin-bottom:8px}}
.stat-card .value{{font-size:34px;line-height:1;font-weight:900;letter-spacing:-.02em}}
.stat-card .hint{{font-size:12px;color:var(--muted);line-height:1.6;text-align:right;max-width:116px}}
.toolbar-panel{{padding:16px}}
.search-form{{display:flex;gap:10px;align-items:center}}
input,select,textarea{{border:1px solid var(--rule);background:#fffefa;color:var(--ink);outline:none;font-family:inherit;
  font-size:13.5px;transition:border-color .16s ease,box-shadow .16s ease,background .16s ease}}
input,select{{height:38px;padding:0 11px}}
textarea{{padding:10px 11px;line-height:1.65;resize:vertical}}
input:focus,select:focus,textarea:focus{{border-color:var(--brand);box-shadow:0 0 0 3px rgba(168,58,38,.12);background:#fff}}
input::placeholder,textarea::placeholder{{color:#8c826e}}
.search-input{{flex:1;min-width:160px}}
.button,button{{display:inline-flex;align-items:center;justify-content:center;gap:6px;min-height:36px;border:1px solid var(--rule);
  background:var(--paper-3);color:var(--ink);padding:0 14px;cursor:pointer;font:800 13px/1 inherit;
  text-decoration:none;white-space:nowrap;transition:background .16s ease,color .16s ease,border-color .16s ease,transform .08s ease,box-shadow .16s ease}}
.button:hover,button:hover{{background:#e7dfc9;border-color:var(--brand);text-decoration:none;color:var(--ink)}}
.button:active,button:active{{transform:translateY(1px)}}
.button.primary,button.primary{{background:var(--brand);color:#fff;border-color:var(--brand)}}
.button.primary:hover,button.primary:hover{{background:var(--brand-dark);color:#fff;box-shadow:0 6px 14px rgba(140,47,30,.16)}}
.button.danger,button.danger{{background:#fff4f0;color:#9b2f1f;border-color:#e5c4ba}}
.button.danger:hover,button.danger:hover{{background:#f9ddd5;border-color:#c95038;color:#8c2f1e}}
.button.success,button.success{{background:#eef7ef;color:var(--success);border-color:#b7d9c4}}
.button.success:hover,button.success:hover{{background:#dcefe0;border-color:var(--success);color:#1f513d}}
.button.subtle{{background:transparent;color:var(--brand);border-color:#dfb8ae}}
.button.subtle:hover{{background:#fff4f0;color:var(--brand-dark)}}
.table-panel{{padding:0;overflow:hidden}}
.table-panel .panel-title{{padding:16px 18px 0;margin-bottom:12px}}
.table-wrap{{overflow:auto;padding:0 18px 18px}}
table{{width:100%;border-collapse:separate;border-spacing:0;min-width:880px}}
th{{position:sticky;top:0;background:var(--brand-dark);color:#fff;font-size:12.5px;font-weight:800;padding:11px 12px;text-align:left;z-index:1}}
td{{padding:12px;font-size:13.5px;border-bottom:1px solid var(--rule-soft);vertical-align:middle;background:rgba(255,253,246,.62)}}
tbody tr:nth-child(even) td{{background:rgba(241,234,217,.72)}}
tbody tr:hover td{{background:#fff8ea}}
.mono{{font-variant-numeric:tabular-nums}}
.user-name{{font-weight:900}}
.tag{{display:inline-flex;align-items:center;min-height:24px;padding:0 10px;font-size:12px;font-weight:900;letter-spacing:.02em}}
.tag.trial{{background:#e9f7ee;color:var(--success)}}
.tag.member{{background:#fff1bf;color:var(--warning)}}
.tag.expired{{background:#eee7d8;color:var(--disabled)}}
.tag.disabled{{background:#fff1f0;color:#a83a26}}
.tag.info{{background:#eef3f4;color:#365a67}}
.tag.warning{{background:#fff1bf;color:var(--warning)}}
.tag.critical{{background:#fff1f0;color:#a83a26}}
.empty-state{{padding:34px 18px!important;text-align:center;color:var(--muted);background:var(--paper-2)!important}}
.breadcrumb{{margin-bottom:16px;font-size:13px}}
.detail-card{{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:18px;align-items:start}}
.detail-meta{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:16px}}
.meta-item{{background:var(--paper);border:1px solid var(--rule-soft);padding:11px 12px}}
.meta-item span{{display:block;color:var(--muted);font-size:12px;margin-bottom:5px}}
.meta-item strong{{font-size:14px}}
.action-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:16px}}
.action-box{{border:1px solid var(--rule-soft);background:var(--paper);padding:12px}}
.action-box label{{display:block;font-size:12px;font-weight:800;color:var(--muted);margin-bottom:7px}}
.inline{{display:inline-flex;align-items:center;gap:8px}}
.metric-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:14px}}
.metric{{background:var(--paper);border:1px solid var(--rule-soft);border-top:2px solid var(--rule-soft);padding:13px 14px}}
.metric .label{{font-size:12px;color:var(--muted);font-weight:700;display:block;margin-bottom:6px}}
.metric .value{{display:block;font-size:22px;font-weight:900;color:var(--ink);word-break:break-word}}
.metric.warn{{border-top-color:var(--danger)}}
.metric.warn .value{{color:var(--danger)}}
.usage-foot{{margin-top:14px;padding-top:12px;border-top:1px solid var(--rule-soft);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}}
table.compact{{min-width:480px}}
.notice-form{{display:grid;gap:14px}}
.form-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:14px}}
.form-field label,.checkbox-line{{display:block;font-size:12.5px;font-weight:800;color:var(--muted);margin-bottom:7px}}
.form-field input,.form-field select,.form-field textarea{{width:100%}}
.checkbox-line{{display:flex;align-items:center;gap:8px;margin:4px 0 0;color:var(--ink)}}
.checkbox-line input{{width:16px;height:16px;padding:0}}
.alert{{border-color:#e5c4ba;background:#fff4f0;color:#8c2f1e}}
code{{font-family:"Cascadia Mono","SFMono-Regular",Consolas,monospace;font-size:12px;color:#574d3d}}
@media(max-width:760px){{.topbar-inner{{padding:10px 14px;align-items:flex-start;flex-direction:column;gap:10px}}.brand-home{{width:100%}}.topnav{{width:100%;overflow:auto}}
  main{{padding:20px 14px 40px}}.page-head,.detail-card{{display:block}}.stat-grid{{grid-template-columns:1fr}}.search-form{{flex-direction:column;align-items:stretch}}
  .button,button{{width:100%}}.panel{{padding:16px}}.table-panel{{padding:0}}.table-wrap{{padding:0 12px 14px}}}}
@media(prefers-reduced-motion:reduce){{*,*::before,*::after{{transition:none!important;scroll-behavior:auto!important}}}}
</style></head><body><header class="topbar"><div class="topbar-inner"><a class="brand-home" href="/admin"><strong>Glowfish</strong><span>管理后台</span></a>
<nav class="topnav" aria-label="后台导航"><a href="/admin" data-nav="/admin">用户</a><a href="/admin/notices" data-nav="/admin/notices">公告</a><a href="/admin/logout">退出</a></nav></div></header>
<main>{body}</main>
<script>
(function(){{const path=window.location.pathname;document.querySelectorAll("[data-nav]").forEach(function(a){{const nav=a.getAttribute("data-nav");const active=(nav==="/admin"&&(path==="/admin"||path.startsWith("/admin/users/")))||(nav==="/admin/notices"&&path.startsWith("/admin/notices"));if(active)a.setAttribute("aria-current","page");}});
document.querySelectorAll("form[data-pending]").forEach(function(form){{form.addEventListener("submit",function(){{const btn=form.querySelector("button[type=submit]");if(btn){{btn.disabled=true;btn.dataset.originalText=btn.textContent;btn.textContent=btn.dataset.loadingText||"处理中";}}}});}});
}})();
</script></body></html>"""


def _fmt_ts(ts):
    if not ts:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(int(ts)))


def _fmt_duration(seconds):
    seconds = int(seconds or 0)
    h, m = divmod(seconds // 60, 60)
    if h:
        return f"{h}时{m}分"
    if m:
        return f"{m}分钟"
    return f"{seconds}秒"


_STATUS_LABELS = {"disabled": "禁用", "trial": "试用", "member": "会员", "expired": "过期"}


def _status_label(status):
    return _STATUS_LABELS.get(status, status)


@app.get("/admin", response_class=HTMLResponse)
def admin_index(sid: str = Cookie(default=None), q: str = ""):
    if not _admin_user(sid):
        return HTMLResponse(_admin_login_html())
    rows = core.admin_list_accounts(_conn, now=int(time.time()), q=q)
    stats = core.admin_stats(_conn, now=int(time.time()))
    trs = []
    for u in rows:
        usage = u.get("usage", {})
        status = html.escape(u["status"])
        uid = u['user_id']
        trs.append(f"""<tr>
<td class="mono">{uid}</td>
<td><span class="user-name">{html.escape(u['username'])}</span></td>
<td class="mono">{html.escape(u.get('phone') or '-')}</td>
<td><span class="tag {status}">{_status_label(u['status'])}</span></td>
<td class="mono">{_fmt_ts(u.get('expires_at'))}</td>
<td class="mono">{_fmt_ts(u.get('last_login_at'))}</td>
<td class="mono">{usage.get('check_count',0)}</td><td class="mono">{usage.get('ocr_count',0)}</td><td class="mono">{usage.get('export_count',0)}</td>
<td><a href="/admin/users/{uid}" class="button subtle">管理</a></td>
</tr>""")
    stats_html = f"""<div class="stat-grid">
<div class="stat-card"><div><span class="label">总用户</span><span class="value mono">{stats['total']}</span></div><p class="hint">全部注册账号</p></div>
<div class="stat-card"><div><span class="label">有效账号</span><span class="value mono">{stats['active']}</span></div><p class="hint">试用或会员可用</p></div>
<div class="stat-card"><div><span class="label">已封禁</span><span class="value mono">{stats['disabled']}</span></div><p class="hint">不可登录账号</p></div>
</div>"""
    q_hint = f"当前筛选：{html.escape(q)}" if q else "支持用户名、显示名、手机号模糊搜索"
    body = f"""<div class="page-head"><div class="page-title"><h2>用户管理</h2><p>查看账号状态、使用汇总，并进入详情处理续期、封禁和密码重置。</p></div></div>
{stats_html}
<div class="panel toolbar-panel"><form class="search-form" method="get" action="/admin">
<input class="search-input" name="q" value="{html.escape(q)}" placeholder="搜索用户名或手机号" aria-label="搜索用户名或手机号">
<button class="primary" type="submit">搜索</button>
<a class="button" href="/admin">清除</a>
</form><p class="panel-note" style="margin-top:10px">{q_hint}</p></div>
<div class="panel table-panel"><div class="panel-title"><div><h3>账号列表</h3><p class="panel-note">最多显示最近 200 个账号。</p></div></div>
<div class="table-wrap"><table><thead><tr><th>ID</th><th>用户</th><th>手机号</th><th>状态</th><th>到期</th><th>最后登录</th><th>校验</th><th>OCR</th><th>导出</th><th>操作</th></tr></thead>
<tbody>{''.join(trs) or '<tr><td colspan="10" class="empty-state">没有匹配的账号，换个关键词再试。</td></tr>'}</tbody></table></div></div>"""
    return HTMLResponse(_admin_shell(body))


@app.post("/admin/login")
async def admin_login(req: Request):
    form = await req.form()
    r = core.verify_admin_password(_conn, form.get("username", ""), form.get("password", ""))
    if not r.get("ok"):
        return HTMLResponse(_admin_login_html("账号或密码错误"), status_code=401)
    sid = core.create_admin_session(_conn, r["username"], now=int(time.time()))
    resp = RedirectResponse("/admin", status_code=303)
    resp.set_cookie("sid", sid, httponly=True, samesite="lax", path="/")
    return resp


@app.get("/admin/logout")
def admin_logout(sid: str = Cookie(default=None)):
    core.delete_admin_session(_conn, sid)
    resp = RedirectResponse("/admin", status_code=303)
    resp.delete_cookie("sid", path="/")
    return resp


@app.get("/admin/users/{user_id}", response_class=HTMLResponse)
def admin_user_detail(user_id: int, msg: str = "", sid: str = Cookie(default=None)):
    if not _admin_user(sid):
        return HTMLResponse(_admin_login_html())
    u = core.admin_get_account(_conn, user_id, now=int(time.time()))
    if not u.get("user_id"):
        return HTMLResponse(_admin_shell("<div class='panel'>用户不存在</div>"), status_code=404)
    usage = u.get("usage", {})
    status = html.escape(u["status"])
    disabled = u.get("disabled")
    reg_way = "手机号" if u.get("phone") else "用户名"
    error_count = usage.get("error_count", 0)
    metrics = "".join(
        f"<div class='metric{' warn' if warn else ''}'><span class='label'>{k}</span><span class='value mono'>{v}</span></div>"
        for k, v, warn in [
            ("登录", usage.get("login_count", 0), False),
            ("导入", usage.get("import_count", 0), False),
            ("OCR", usage.get("ocr_count", 0), False),
            ("导出", usage.get("export_count", 0), False),
            ("错误", error_count, error_count > 0),
            ("使用时长", _fmt_duration(usage.get("usage_seconds", 0)), False),
        ])
    sessions = "".join(
        f"<tr><td class='mono'>{_fmt_ts(s['issued_at'])}</td>"
        f"<td>{html.escape(s.get('app_version') or '-')}</td><td><code>{html.escape((s.get('fingerprint') or '-')[:16])}</code></td></tr>"
        for s in u.get("sessions", []))
    banner = (f"<div class='panel alert'>{html.escape(msg)}</div>"
              if msg else "")
    body = f"""<div class="breadcrumb"><a href="/admin">返回用户列表</a></div>
{banner}
<div class="page-head"><div class="page-title"><h2>{html.escape(u['username'])}</h2><p>账号详情、会员状态和最近设备校验记录。</p></div><span class="tag {status}">{_status_label(u['status'])}</span></div>
<div class="panel detail-card">
<div>
<div class="panel-title"><div><h3>账号信息</h3><p class="panel-note">这些信息来自账号服务，不包含任何史料内容。</p></div></div>
<div class="detail-meta">
<div class="meta-item"><span>手机号</span><strong class="mono">{html.escape(u.get('phone') or '-')}</strong></div>
<div class="meta-item"><span>注册方式</span><strong>{reg_way}</strong></div>
<div class="meta-item"><span>使用到期</span><strong class="mono">{_fmt_ts(u.get('expires_at'))}</strong></div>
</div>
</div>
<div class="panel-note">用户 ID<br><strong class="mono" style="font-size:20px;color:var(--ink)">{user_id}</strong></div>
</div>
<div class="panel"><div class="panel-title"><div><h3>运营操作</h3><p class="panel-note">提交后会立即影响下次客户端校验。</p></div></div>
<div class="action-grid">
<form class="action-box" method="post" action="/admin/users/{user_id}/renew" data-pending="true">
  <label for="renew-days">使用期限</label><div class="inline"><input id="renew-days" name="days" value="30" size="5" style="width:84px" placeholder="天数"><button class="primary" type="submit">应用</button></div>
</form>
<form class="action-box" method="post" action="/admin/users/{user_id}/reset-trial" data-pending="true" onsubmit="return confirm('确认将该账号重置为试用 7 天？将清空现有会员到期时间。')">
  <label>使用到期</label><button class="subtle" type="submit">重置为试用 7 天</button>
</form>
<form class="action-box" method="post" action="/admin/users/{user_id}/toggle-membership" data-pending="true">
  <label>会员状态</label><button class="{'danger' if u['status'] == 'member' else 'success'}" type="submit">{'取消会员' if u['status'] == 'member' else '升级会员'}</button>
</form>
<form class="action-box" method="post" action="/admin/users/{user_id}/disable" data-pending="true">
  <label>账号状态</label><button class="{'success' if disabled else 'danger'}" type="submit">{'解封账号' if disabled else '封禁账号'}</button>
</form>
<form class="action-box" method="post" action="/admin/users/{user_id}/reset-password" data-pending="true">
  <label for="reset-password">重置密码</label><div class="inline"><input id="reset-password" name="password" value="{ADMIN_DEFAULT_PASSWORD}" placeholder="留空使用默认" style="width:138px"><button type="submit">重置</button></div>
</form>
</div></div>
<div class="panel"><div class="panel-title"><div><h3>使用汇总</h3><p class="panel-note">客户端上报的功能使用计数。</p></div></div><div class="metric-grid">{metrics}</div>
<div class="usage-foot"><span class="panel-note">最后活跃</span><span class="mono">{_fmt_ts(usage.get('last_event_at', 0))}</span></div></div>
<div class="panel table-panel"><div class="panel-title"><div><h3>最近会话</h3><p class="panel-note">最多显示最近 20 条设备会话。</p></div></div><div class="table-wrap"><table class="compact"><thead><tr><th>登录</th><th>版本</th><th>设备摘要</th></tr></thead>
<tbody>{sessions or '<tr><td colspan="3" class="empty-state">暂无会话记录。</td></tr>'}</tbody></table></div></div>"""
    return HTMLResponse(_admin_shell(body))


@app.post("/admin/users/{user_id}/renew")
async def admin_renew(user_id: int, req: Request, sid: str = Cookie(default=None)):
    if not _admin_user(sid):
        return RedirectResponse("/admin", status_code=303)
    form = await req.form()
    admin = _admin_user(sid) or {"username": "system"}
    core.admin_extend_active_expiry(_conn, user_id, days=form.get("days", 30),
                                    now=int(time.time()), admin=admin["username"])
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@app.post("/admin/users/{user_id}/reset-trial")
def admin_reset_trial(user_id: int, sid: str = Cookie(default=None)):
    if not _admin_user(sid):
        return RedirectResponse("/admin", status_code=303)
    admin = _admin_user(sid) or {"username": "system"}
    core.admin_reset_to_trial(_conn, user_id, now=int(time.time()), admin=admin["username"])
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@app.post("/admin/users/{user_id}/toggle-membership")
def admin_toggle_membership(user_id: int, sid: str = Cookie(default=None)):
    if not _admin_user(sid):
        return RedirectResponse("/admin", status_code=303)
    admin = _admin_user(sid) or {"username": "system"}
    u = core.admin_get_account(_conn, user_id, now=int(time.time()))
    core.admin_set_membership(_conn, user_id, u.get("status") != "member",
                              now=int(time.time()), admin=admin["username"])
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@app.post("/admin/users/{user_id}/disable")
def admin_disable(user_id: int, sid: str = Cookie(default=None)):
    if not _admin_user(sid):
        return RedirectResponse("/admin", status_code=303)
    u = core.admin_get_account(_conn, user_id, now=int(time.time()))
    core.admin_set_disabled(_conn, user_id, not u.get("disabled"), now=int(time.time()))
    return RedirectResponse(f"/admin/users/{user_id}", status_code=303)


@app.post("/admin/users/{user_id}/reset-password")
async def admin_reset_password(user_id: int, req: Request, sid: str = Cookie(default=None)):
    """重置密码。留空 → 重置为默认口令 ADMIN_DEFAULT_PASSWORD。

    ⚠core.admin_reset_password 对 <6 位密码只返回 {ok:False,reason:weak_password} 而不抛异常。
    早先此处丢弃返回值直接 303，于是「留空提交」表现为静默无操作：页面回到详情、账号仍显示
    「正常」，管理员以为改好了，用户却永远登不进（密码根本没变）。失败必须回显。"""
    if not _admin_user(sid):
        return RedirectResponse("/admin", status_code=303)
    form = await req.form()
    admin = _admin_user(sid) or {"username": "system"}
    password = (form.get("password") or "").strip() or ADMIN_DEFAULT_PASSWORD
    r = core.admin_reset_password(_conn, user_id, password,
                                  now=int(time.time()), admin=admin["username"])
    if not r.get("ok"):
        msg = urllib.parse.quote(_ADMIN_RESET_MSG.get(r.get("reason"), "重置失败：%s" % r.get("reason")))
        return RedirectResponse(f"/admin/users/{user_id}?msg={msg}", status_code=303)
    msg = urllib.parse.quote("密码已重置。")
    return RedirectResponse(f"/admin/users/{user_id}?msg={msg}", status_code=303)


# ---- Notice management ----

def _notice_form(n=None):
    n = n or {}
    return f"""<div class="panel">
<div class="panel-title"><div><h2>{'编辑公告' if n.get('id') else '新建公告'}</h2><p class="panel-note">公告会写入 notices.json，供客户端读取展示。</p></div></div>
<form class="notice-form" method="post" action="/admin/notices/save" data-pending="true">
<input type="hidden" name="id" value="{html.escape(n.get('id',''))}">
<div class="form-field"><label for="notice-title">标题</label><input id="notice-title" name="title" value="{html.escape(n.get('title',''))}" required></div>
<div class="form-field"><label for="notice-body">正文</label><textarea id="notice-body" name="body" rows="5" required>{html.escape(n.get('body',''))}</textarea></div>
<div class="form-grid">
<div class="form-field"><label for="notice-level">等级</label><select id="notice-level" name="level">
<option value="info" {'selected' if n.get('level')=='info' else ''}>info 普通</option>
<option value="warning" {'selected' if n.get('level')=='warning' else ''}>warning 警告</option>
<option value="critical" {'selected' if n.get('level')=='critical' else ''}>critical 重要</option>
</select></div>
<div class="form-field"><label for="notice-start">开始时间（可选）</label><input id="notice-start" name="starts_at" value="{html.escape(n.get('starts_at',''))}" placeholder="2026-07-01T00:00:00+08:00"></div>
<div class="form-field"><label for="notice-end">结束时间（可选）</label><input id="notice-end" name="ends_at" value="{html.escape(n.get('ends_at',''))}" placeholder="2026-07-10T00:00:00+08:00"></div>
</div>
<div class="form-grid">
<div class="form-field"><label for="notice-link-text">外链文字（可选）</label><input id="notice-link-text" name="link_text" value="{html.escape(n.get('link_text',''))}"></div>
<div class="form-field"><label for="notice-link-url">外链地址（可选）</label><input id="notice-link-url" name="link_url" value="{html.escape(n.get('link_url',''))}"></div>
</div>
<label class="checkbox-line"><input type="checkbox" name="force_popup" value="1" {'checked' if n.get('force_popup') else ''}> 强制弹窗（用户打开 App 时自动弹出一次）</label>
<div class="inline" style="margin-top:4px">
<button class="primary" type="submit">{'保存修改' if n.get('id') else '发布公告'}</button>
<a class="button" href="/admin/notices">取消</a>
</div>
</form></div>"""


@app.get("/admin/notices", response_class=HTMLResponse)
def admin_notices(sid: str = Cookie(default=None), edit: str = ""):
    if not _admin_user(sid):
        return HTMLResponse(_admin_login_html())
    if edit:
        if edit != "new":
            n = core.notice_get(edit)
            if not n:
                return HTMLResponse(_admin_shell("<div class='panel'>公告不存在</div>"), status_code=404)
        else:
            n = {}
        return HTMLResponse(_admin_shell(f'<div class="breadcrumb"><a href="/admin/notices">返回公告列表</a></div>{_notice_form(n)}'))
    notices = core.notice_list()
    rows = []
    for n in notices:
        nid = html.escape(n.get("id", ""))
        level = html.escape(n.get("level", "info"))
        title = html.escape(n.get("title", ""))
        starts = n.get("starts_at", "")[:16] if n.get("starts_at") else "-"
        ends = n.get("ends_at", "")[:16] if n.get("ends_at") else "永久"
        force = "是" if n.get("force_popup") else "否"
        rows.append(f"""<tr>
<td><strong>{title}</strong></td>
<td><span class="tag {level}">{level}</span></td>
<td class="mono">{starts}</td><td class="mono">{ends}</td><td>{force}</td>
<td>
<a class="button subtle" href="/admin/notices?edit={nid}">编辑</a>
<form class="inline" method="post" action="/admin/notices/{nid}/delete" data-pending="true" onsubmit="return confirm('确认删除该公告？')">
<button class="danger">删除</button></form>
</td></tr>""")
    body = f"""<div class="page-head"><div class="page-title"><h2>公告管理</h2><p>管理客户端公告、强制弹窗和可选外链。</p></div><a class="button primary" href="/admin/notices?edit=new">新建公告</a></div>
<div class="panel table-panel"><div class="panel-title"><div><h3>公告列表</h3><p class="panel-note">按保存时间靠前展示。</p></div></div>
<div class="table-wrap"><table><thead><tr><th>标题</th><th>等级</th><th>开始</th><th>结束</th><th>强制弹窗</th><th>操作</th></tr></thead>
<tbody>{''.join(rows) or '<tr><td colspan="6" class="empty-state">暂无公告，可以新建一条。</td></tr>'}</tbody></table></div></div>"""
    return HTMLResponse(_admin_shell(body))


@app.post("/admin/notices/save")
async def admin_notice_save(req: Request, sid: str = Cookie(default=None)):
    if not _admin_user(sid):
        return RedirectResponse("/admin", status_code=303)
    form = await req.form()
    nid = (form.get("id") or "").strip()
    if not nid:
        nid = f"notice-{int(time.time())}"
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime(int(time.time())))
    notice = {
        "id": nid,
        "title": (form.get("title") or "").strip(),
        "body": (form.get("body") or "").strip(),
        "level": (form.get("level") or "info").strip(),
        "starts_at": (form.get("starts_at") or "").strip(),
        "ends_at": (form.get("ends_at") or "").strip(),
        "force_popup": form.get("force_popup") == "1",
        "link_text": (form.get("link_text") or "").strip(),
        "link_url": (form.get("link_url") or "").strip(),
    }
    core.notice_save(notice, now_iso)
    return RedirectResponse("/admin/notices", status_code=303)


@app.post("/admin/notices/{notice_id}/delete")
def admin_notice_delete(notice_id: str, sid: str = Cookie(default=None)):
    if not _admin_user(sid):
        return RedirectResponse("/admin", status_code=303)
    core.notice_delete(notice_id)
    return RedirectResponse("/admin/notices", status_code=303)
