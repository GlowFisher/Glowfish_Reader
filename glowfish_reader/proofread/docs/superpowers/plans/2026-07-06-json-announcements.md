# JSON Announcements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first-version announcement system using a hosted `notices.json` file, local backend filtering, and the existing top-right announcement modal.

**Architecture:** The official server hosts `notices.json`; `proofread/notice_api.py` fetches, normalizes, filters, caches, and exposes it through `/api/notices`; `static/notice.js` renders the notices, unread dot, local read state, and one-time force popups. The implementation follows the existing update system's quiet failure behavior.

**Tech Stack:** Python FastAPI router, existing `requests` dependency, existing version helpers in `updater.py`, browser JavaScript, `localStorage`, existing modal/button CSS.

---

## File Structure

- Create `proofread/notice_api.py`: remote URL resolution, JSON fetch, notice normalization, date/version filtering, short cache, FastAPI endpoint.
- Modify `proofread/server.py`: include the new notice router.
- Modify `proofread/static/notice.js`: fetch `/api/notices`, render notices, manage unread and popup-seen local state.
- Modify `proofread/static/style.css`: add unread red dot and notice item styles.
- Create `proofread/test_notice_api.py`: unit tests for URL resolution, filtering, malformed data, and API quiet failure.

## Tasks

### Task 1: Backend Notice API Tests

- [ ] Create `proofread/test_notice_api.py`.
- [ ] Add tests for `notice_url()` default behavior, `SHUPAI_NOTICE_URL`, and `SHUPAI_LICENSE_SERVER`.
- [ ] Add tests for minimal valid notice normalization.
- [ ] Run `python -m pytest proofread/test_notice_api.py -q` and confirm it fails because `notice_api` does not exist.

### Task 2: Backend Notice API Foundation

- [ ] Create `proofread/notice_api.py`.
- [ ] Add FastAPI `router = APIRouter()`.
- [ ] Add `_DEFAULT_SERVER = "https://license.glowfishreader.com"`.
- [ ] Implement `notice_url()` with priority `SHUPAI_NOTICE_URL`, then `SHUPAI_LICENSE_SERVER`, then default server.
- [ ] Implement `normalize_notice(raw)` requiring `id`, `title`, and `body`.
- [ ] Default invalid or missing `level` to `info`.
- [ ] Run `python -m pytest proofread/test_notice_api.py -q` and confirm the first tests pass.

### Task 3: Backend Filtering Tests

- [ ] Add tests for active date range filtering.
- [ ] Add tests for future notices being hidden.
- [ ] Add tests for expired notices being hidden.
- [ ] Add tests for `min_version` and `max_version`.
- [ ] Add tests that malformed notices are skipped while valid notices remain.
- [ ] Run `python -m pytest proofread/test_notice_api.py -q` and confirm failure because filtering is not implemented.

### Task 4: Backend Filtering Implementation

- [ ] Implement ISO datetime parsing that accepts `Z` and timezone offsets.
- [ ] Skip notices with invalid date strings.
- [ ] Reuse `updater.parse_version()` for version comparisons.
- [ ] Implement `filter_notices(raw_notices, current_version, now=None)`.
- [ ] Sort visible notices newest first by `published_at` or `starts_at`.
- [ ] Run `python -m pytest proofread/test_notice_api.py -q` and confirm filtering tests pass.

### Task 5: Backend Fetch, Cache, and Endpoint

- [ ] Add tests for remote fetch soft failure.
- [ ] Add tests for remote document filtering.
- [ ] Implement `fetch_remote_notices()` with `requests.get(notice_url(), timeout=6)`.
- [ ] Return `None` for non-200 responses, invalid JSON, exceptions, or non-object JSON.
- [ ] Implement `get_notices(use_cache=True)` returning `{ ok, current, notices }`.
- [ ] Cache the API result for 600 seconds.
- [ ] Add `@router.get("/api/notices")`.
- [ ] Register `notice_api.router` in `proofread/server.py`.
- [ ] Run `python -m pytest proofread/test_notice_api.py proofread/test_update_api.py proofread/test_updater.py -q`.

### Task 6: Frontend Notice Logic

- [ ] Replace the placeholder logic in `proofread/static/notice.js`.
- [ ] Fetch `/api/notices` with `cache: "no-store"`.
- [ ] Render an empty state when there are no notices.
- [ ] Render notice title, level label, body, date, and optional link.
- [ ] Store read notice IDs in `localStorage["gf-notice-read-ids"]`.
- [ ] Store popup-seen IDs in `localStorage["gf-notice-popup-seen-ids"]`.
- [ ] Add `has-notice` to `#noticeBtn` when any visible notice is unread.
- [ ] Mark visible notices read when the modal opens.
- [ ] Auto-open once for notices with `force_popup: true`.
- [ ] Check once 5 seconds after startup and then every 15 minutes.
- [ ] Run `node --check proofread/static/notice.js` if Node is available.

### Task 7: Frontend Styles

- [ ] Add `#noticeBtn.has-notice::after` red dot styling in `proofread/static/style.css`.
- [ ] Add scoped styles for `.notice-item`, `.notice-level`, `.notice-warning`, `.notice-critical`, `.notice-item-body`, `.notice-item-foot`, and `.notice-link`.
- [ ] Keep selectors scoped to announcement UI.

### Task 8: Verification

- [ ] Run `python -m pytest proofread/test_notice_api.py proofread/test_update_api.py proofread/test_updater.py -q`.
- [ ] Run a related smoke set including `proofread/test_auth_api_entitlement.py`.
- [ ] Manually test `/api/notices` with an empty or unreachable notice source.
- [ ] Manually test a valid local `notices.json` source by setting `SHUPAI_NOTICE_URL`.
- [ ] Confirm red dot, read state, empty state, and force-popup-once behavior.

### Task 9: Commit

- [ ] Review the diff and confirm only announcement-related files changed.
- [ ] Stage the implementation and docs.
- [ ] Commit with `feat: add json announcements`.

## Self-Review

- Spec coverage: backend URL, fetch, filtering, frontend render, red dot, force popup, styles, tests, and operations are covered by tasks.
- Placeholder scan: no unresolved placeholder requirements remain.
- Type consistency: backend fields match frontend field names: `id`, `title`, `body`, `level`, `force_popup`, `link_text`, `link_url`, `published_at`, `starts_at`.

