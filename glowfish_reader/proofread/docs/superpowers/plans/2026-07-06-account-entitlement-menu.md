# Account Entitlement Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved lightweight top-right account menu that displays either trial or member expiry and keeps logout available.

**Architecture:** Extend `/api/me` with a small account entitlement object, sourced from app configuration or environment variables for this first version. Replace the existing inline `用户名 + 登出` chip with a compact account button and anchored popover rendered by `auth-guard.js`. Keep logout behavior unchanged.

**Tech Stack:** FastAPI Python backend, vanilla JavaScript frontend, CSS in the existing static style system, pytest for backend contract tests.

---

## File Structure

- Modify `glowfish_reader/proofread/appconfig.py`: add account entitlement configuration helpers.
- Modify `glowfish_reader/proofread/auth_api.py`: include entitlement data in `/api/me`.
- Create `glowfish_reader/proofread/test_auth_api_entitlement.py`: verify `/api/me` emits the two supported entitlement modes.
- Modify `glowfish_reader/proofread/static/index.html`: change the `userChip` markup to a compact account button and popover.
- Modify `glowfish_reader/proofread/static/auth-guard.js`: render account summary/status, open/close popover, preserve logout behavior.
- Modify `glowfish_reader/proofread/static/style.css`: style the account button and popover.

## Task 1: Backend Account Entitlement Contract

**Files:**
- Modify: `glowfish_reader/proofread/appconfig.py`
- Modify: `glowfish_reader/proofread/auth_api.py`
- Create: `glowfish_reader/proofread/test_auth_api_entitlement.py`

- [ ] **Step 1: Write backend tests for trial and member entitlement**

Create `glowfish_reader/proofread/test_auth_api_entitlement.py` with:

```python
import importlib
import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _client(monkeypatch, mode, expires_at):
    monkeypatch.setenv("SHUPAI_ACCOUNT_MODE", mode)
    monkeypatch.setenv("SHUPAI_ACCOUNT_EXPIRES_AT", expires_at)

    import appconfig
    import auth_api
    import userctx
    import server

    importlib.reload(appconfig)
    importlib.reload(auth_api)
    importlib.reload(userctx)
    importlib.reload(server)

    def fake_current_user():
        return {"id": 1, "username": "zhangsan", "display": "张三"}

    server.app.dependency_overrides[userctx.current_user] = fake_current_user
    return TestClient(server.app)


def test_me_includes_trial_entitlement(monkeypatch):
    client = _client(monkeypatch, "trial", "2026-08-31")
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["entitlement"] == {"mode": "trial", "expires_at": "2026-08-31"}


def test_me_includes_member_entitlement(monkeypatch):
    client = _client(monkeypatch, "member", "2026-08-31")
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["entitlement"] == {"mode": "member", "expires_at": "2026-08-31"}
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest proofread\test_auth_api_entitlement.py -q
```

Expected: fail because `/api/me` does not include `entitlement`.

- [ ] **Step 3: Add entitlement config helpers**

In `glowfish_reader/proofread/appconfig.py`, add:

```python
def get_account_entitlement():
    """Return account entitlement display config for multi-user account UI."""
    mode = (_env("SHUPAI_ACCOUNT_MODE") or _load_file().get("account_mode") or "trial").strip().lower()
    expires_at = (_env("SHUPAI_ACCOUNT_EXPIRES_AT") or _load_file().get("account_expires_at") or "2026-08-31").strip()
    if mode not in ("trial", "member") or not expires_at:
        return None
    return {"mode": mode, "expires_at": expires_at}
```

- [ ] **Step 4: Include entitlement in `/api/me`**

In `glowfish_reader/proofread/auth_api.py`, change:

```python
def _public(user):
    return {"username": user["username"], "display": user["display"]}
```

to:

```python
def _public(user):
    payload = {"username": user["username"], "display": user["display"]}
    entitlement = appconfig.get_account_entitlement()
    if entitlement:
        payload["entitlement"] = entitlement
    return payload
```

- [ ] **Step 5: Run backend tests and verify pass**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest proofread\test_auth_api_entitlement.py -q
```

Expected: 2 passed.

## Task 2: Frontend Account Menu

**Files:**
- Modify: `glowfish_reader/proofread/static/index.html`
- Modify: `glowfish_reader/proofread/static/auth-guard.js`
- Modify: `glowfish_reader/proofread/static/style.css`

- [ ] **Step 1: Update account markup**

Replace the existing `userChip` contents in `index.html` with:

```html
<span id="userChip" class="hidden user-chip">
  <button id="accountBtn" class="btn btn-sec account-btn" title="账号状态" aria-haspopup="menu" aria-expanded="false">
    <span id="accountSummary"></span>
    <svg class="gf-caret" viewBox="0 0 16 16" width="10" height="10" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6l4 4 4-4"/></svg>
  </button>
  <div id="accountMenu" class="popover account-menu hidden" role="menu" aria-label="账号">
    <div class="account-menu-name" id="accountMenuName"></div>
    <div class="account-menu-status" id="accountMenuStatus"></div>
    <button id="logoutBtn" class="account-menu-logout" role="menuitem">退出登录</button>
  </div>
</span>
```

- [ ] **Step 2: Update auth rendering and popover behavior**

In `auth-guard.js`, replace the current `userName` fill and `logoutBtn` binding block with helpers that:

```javascript
function entitlementLabel(ent) {
  if (!ent || !ent.mode || !ent.expires_at) return "";
  if (ent.mode === "trial") return "试用有效期至 " + ent.expires_at;
  if (ent.mode === "member") return "会员有效期至 " + ent.expires_at;
  return "";
}

function entitlementShort(ent) {
  if (!ent || !ent.mode) return "";
  if (ent.mode === "trial") return "试用";
  if (ent.mode === "member") return "会员";
  return "";
}
```

Then render:

```javascript
const displayName = me.display || me.username;
const summary = document.getElementById("accountSummary");
const menuName = document.getElementById("accountMenuName");
const menuStatus = document.getElementById("accountMenuStatus");
const accountBtn = document.getElementById("accountBtn");
const accountMenu = document.getElementById("accountMenu");
const short = entitlementShort(me.entitlement);
if (summary) summary.textContent = short ? displayName + " · " + short : displayName;
if (menuName) menuName.textContent = displayName;
if (menuStatus) {
  const label = entitlementLabel(me.entitlement);
  menuStatus.textContent = label;
  menuStatus.classList.toggle("hidden", !label);
}
```

Add click, outside-click, and Esc close behavior around `accountBtn` / `accountMenu`, and keep the existing `/api/logout`, `gf_user` removal, local cache clearing, and login redirect.

- [ ] **Step 3: Style the menu**

Add CSS in `style.css`:

```css
.user-chip { position: relative; display: inline-flex; align-items: center; }
.account-btn { max-width: 180px; padding: 7px 10px; gap: 5px; }
#accountSummary { display: inline-block; max-width: 142px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.account-menu { right: 0; top: calc(100% + 7px); min-width: 190px; padding: 10px; gap: 8px; z-index: 60; }
.account-menu-name { font-size: 14px; font-weight: 700; color: var(--ink); }
.account-menu-status { font-size: 12.5px; color: #555; padding-bottom: 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
.account-menu-logout { width: 100%; }
```

- [ ] **Step 4: Smoke-check static references**

Run:

```powershell
rg -n "userName|accountSummary|accountMenu|logoutBtn|accountBtn" proofread\static\index.html proofread\static\auth-guard.js proofread\static\style.css
```

Expected: no `userName` reference remains; account elements and `logoutBtn` are present.

## Task 3: Verification

**Files:**
- Verify changed files only.

- [ ] **Step 1: Run backend contract tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest proofread\test_auth_api_entitlement.py -q
```

Expected: pass.

- [ ] **Step 2: Run focused existing auth-adjacent smoke**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest proofread\licensing\tests\test_license_api.py -q
```

Expected: pass, or report pre-existing environment limitations if server startup dependencies are unavailable.

- [ ] **Step 3: Review diff**

Run:

```powershell
git diff -- proofread\appconfig.py proofread\auth_api.py proofread\test_auth_api_entitlement.py proofread\static\index.html proofread\static\auth-guard.js proofread\static\style.css
```

Expected: only account entitlement/API/menu changes.

## Self-Review

- Spec coverage: backend provides `mode + expires_at`; UI renders trial/member effective-until text; logout remains; missing entitlement falls back to name-only.
- Placeholder scan: no placeholder implementation steps remain.
- Type consistency: `entitlement.mode` and `entitlement.expires_at` are used consistently across tests, backend, and frontend.

