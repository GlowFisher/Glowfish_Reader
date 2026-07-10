# JSON Announcements Design

## Goal

Add a first-version announcement system for GlowFish Reader that lets operators publish notices by editing a hosted JSON file. Users see unread notices through the existing top-right announcement button, and critical notices can open automatically once.

This version intentionally avoids an operations dashboard, WebSocket push, analytics, rich text editing, user segmentation, or image announcements.

## Product Scope

The first version supports:

- fetching notices from an official remote JSON file
- exposing filtered notices through the local backend
- rendering notices in the existing announcement modal
- showing a red unread dot on the top-right announcement button
- marking notices read locally
- opening important notices automatically once
- filtering notices by active date range and app version
- failing quietly when offline or when the remote file is invalid

The first version does not support:

- an admin publishing UI
- per-account targeting
- click or read analytics
- server-side read state
- true realtime push through WebSocket, SSE, or native notifications
- markdown, HTML, images, or embedded media in notice bodies

## User Experience

The top-right announcement button keeps its current position and icon.

States:

- no notices: normal icon, modal shows the existing empty state
- notices all read: normal icon, modal shows the notice list
- one or more unread notices: icon shows a small red dot
- notice with `force_popup: true`: modal opens once after startup or refresh, then records that the user has seen that popup

Opening the modal marks currently visible notices as read. Closing behavior remains unchanged: close button, backdrop click, and Esc all close the modal.

## Remote JSON Contract

Default remote URL:

```text
https://license.glowfishreader.com/notices.json
```

The URL should be configurable for tests and deployment overrides through `SHUPAI_NOTICE_URL`. If `SHUPAI_NOTICE_URL` is not set, derive it from `SHUPAI_LICENSE_SERVER` when present; otherwise use the built-in default server.

Remote file shape:

```json
{
  "schema": 1,
  "updated_at": "2026-07-06T12:00:00+08:00",
  "notices": [
    {
      "id": "2026-07-06-maintenance",
      "title": "服务器维护通知",
      "body": "今晚 23:00-23:30 授权服务将进行维护，期间可能短暂影响登录和激活。",
      "level": "info",
      "starts_at": "2026-07-06T00:00:00+08:00",
      "ends_at": "2026-07-08T00:00:00+08:00",
      "min_version": "1.0.0",
      "max_version": "",
      "force_popup": false,
      "link_text": "",
      "link_url": ""
    }
  ]
}
```

Supported levels:

- `info`: normal announcement
- `warning`: higher visibility announcement
- `critical`: important announcement; the UI may style it more strongly

Required notice fields:

- `id`
- `title`
- `body`

Optional fields:

- `level`, default `info`
- `starts_at`, default active immediately
- `ends_at`, default no expiry
- `min_version`, default no lower bound
- `max_version`, default no upper bound
- `force_popup`, default false
- `link_text`, default empty
- `link_url`, default empty

Bad notices are skipped individually. A bad remote document returns no notices rather than interrupting the app.

## Local Backend

Create a focused backend module:

```text
proofread/notice_api.py
```

Responsibilities:

- compute the remote notice URL
- fetch JSON using short timeouts and soft failure behavior
- cache the last successful filtered result for a short interval
- normalize notice fields
- filter by date range
- filter by current app version
- expose `GET /api/notices`

The API should return HTTP 200 even when offline:

```json
{
  "ok": false,
  "current": "1.0.3",
  "notices": []
}
```

This matches the existing update system's quiet failure style.

## Frontend

Modify:

```text
proofread/static/notice.js
```

Responsibilities:

- fetch `/api/notices`
- render notice cards into `#noticeBody`
- preserve the current empty state when no notices exist
- maintain read notice IDs in `localStorage["gf-notice-read-ids"]`
- maintain popup-seen notice IDs in `localStorage["gf-notice-popup-seen-ids"]`
- add or remove an unread badge class on `#noticeBtn`
- startup check after a short delay
- periodic refresh while the app is open
- refresh immediately when the announcement button is clicked
- auto-open once for visible notices where `force_popup` is true

Suggested timing:

- startup check delay: 5000 ms
- refresh interval: 15 minutes

No user historical material, OCR content, annotations, or notebooks are sent.

## Styling

Modify existing CSS only where necessary, likely:

```text
proofread/static/style.css
```

Required styles:

- unread red dot on `#noticeBtn`
- compact notice list items
- level label styling for `info`, `warning`, and `critical`
- optional link button styling that matches existing `.btn`

The UI should remain restrained and consistent with the existing toolbar and modal system.

## Operations

Publishing process:

1. Edit `notices.json`.
2. Validate it as JSON.
3. Upload it to the official server.
4. To update a notice without re-notifying users, keep the same `id`.
5. To notify users again, publish a new notice with a new `id`.
6. To retire a notice, remove it or set `ends_at` to a past time.

Recommended server-side safeguards:

- keep a backup of the previous `notices.json`
- validate JSON before replacing the live file
- serve with `Content-Type: application/json`
- use HTTPS only

## Testing

Backend tests:

- default notice URL is derived correctly
- `SHUPAI_NOTICE_URL` overrides the default URL
- invalid or missing remote data returns no notices
- expired notices are filtered out
- future notices are filtered out
- version bounds are respected
- bad notice entries are skipped while valid notices remain

Frontend manual checks:

- empty response shows the empty state
- unread notices show a red dot
- opening the modal marks visible notices read
- `force_popup` opens once and does not repeat after close
- refresh failure does not break the modal
- link button appears only when both `link_text` and `link_url` are present

## Rollout

1. Ship app code that supports notices while the server returns an empty notice list.
2. Publish a harmless test notice with a short expiry.
3. Confirm users see the red dot and modal content.
4. Publish operational notices as needed.
