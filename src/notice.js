"use strict";
/* Glowfish Reader announcement modal.
 * Fetches a remote-hosted notice feed through the local backend and keeps read
 * state local to this browser profile. Announcement content is rendered as text.
 */

const GF_NOTICE_READ_KEY = "gf-notice-read-ids";
const GF_NOTICE_POPUP_KEY = "gf-notice-popup-seen-ids";
const GF_NOTICE_REFRESH_MS = 15 * 60 * 1000;
const GF_NOTICE_STARTUP_DELAY_MS = 5000;

let gfNoticeItems = [];
let gfNoticeLoading = false;
let gfNoticeInitialized = false;

function gfReadNoticeSet(key) {
  try {
    const raw = localStorage.getItem(key);
    const values = raw ? JSON.parse(raw) : [];
    return new Set(Array.isArray(values) ? values.filter(Boolean).map(String) : []);
  } catch (_) {
    return new Set();
  }
}

function gfWriteNoticeSet(key, values) {
  try {
    localStorage.setItem(key, JSON.stringify(Array.from(values)));
  } catch (_) {
    // Private browsing or storage quota issues should not break the app.
  }
}

function gfNoticeEl(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined && text !== null) el.textContent = String(text);
  return el;
}

function gfNoticeDate(notice) {
  const value = notice.published_at || notice.starts_at || "";
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(0, 10);
  return date.toLocaleDateString();
}

function gfRenderNoticeEmpty(message) {
  const body = document.getElementById("noticeBody");
  if (!body) return;
  body.innerHTML = "";
  body.appendChild(gfNoticeEl("p", "muted", message || "暂无公告"));
}

function gfRenderNotices() {
  const body = document.getElementById("noticeBody");
  if (!body) return;
  body.innerHTML = "";

  if (!gfNoticeItems.length) {
    body.appendChild(gfNoticeEl("p", "muted", "暂无公告"));
    return;
  }

  const read = gfReadNoticeSet(GF_NOTICE_READ_KEY);
  const list = gfNoticeEl("div", "notice-list");
  gfNoticeItems.forEach((notice) => {
    const item = gfNoticeEl("article", `notice-item notice-${notice.level || "info"}`);
    if (!read.has(String(notice.id))) item.classList.add("is-unread");

    const head = gfNoticeEl("div", "notice-item-head");
    head.appendChild(gfNoticeEl("span", `notice-level notice-level-${notice.level || "info"}`, notice.level || "info"));
    head.appendChild(gfNoticeEl("h3", "notice-title", notice.title || "公告"));
    item.appendChild(head);

    item.appendChild(gfNoticeEl("p", "notice-item-body", notice.body || ""));

    const foot = gfNoticeEl("div", "notice-item-foot");
    const dateText = gfNoticeDate(notice);
    if (dateText) foot.appendChild(gfNoticeEl("span", "notice-date", dateText));
    if (notice.link_text && notice.link_url) {
      const link = gfNoticeEl("a", "notice-link", notice.link_text);
      link.href = notice.link_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      foot.appendChild(link);
    }
    if (foot.childNodes.length) item.appendChild(foot);
    list.appendChild(item);
  });
  body.appendChild(list);
}

function gfUpdateNoticeBadge() {
  const btn = document.getElementById("noticeBtn");
  if (!btn) return;
  const read = gfReadNoticeSet(GF_NOTICE_READ_KEY);
  const hasUnread = gfNoticeItems.some((notice) => !read.has(String(notice.id)));
  btn.classList.toggle("has-notice", hasUnread);
}

function gfMarkVisibleNoticesRead() {
  if (!gfNoticeItems.length) return;
  const read = gfReadNoticeSet(GF_NOTICE_READ_KEY);
  gfNoticeItems.forEach((notice) => read.add(String(notice.id)));
  gfWriteNoticeSet(GF_NOTICE_READ_KEY, read);
  gfUpdateNoticeBadge();
  gfRenderNotices();
}

function gfOpenNoticeModal(markRead) {
  const modal = document.getElementById("noticeModal");
  if (!modal) return;
  modal.classList.remove("hidden");
  if (markRead) gfMarkVisibleNoticesRead();
}

function gfMaybeAutoOpenNotice() {
  const seen = gfReadNoticeSet(GF_NOTICE_POPUP_KEY);
  const popupNotice = gfNoticeItems.find((notice) => notice.force_popup && !seen.has(String(notice.id)));
  if (!popupNotice) return;
  seen.add(String(popupNotice.id));
  gfWriteNoticeSet(GF_NOTICE_POPUP_KEY, seen);
  gfOpenNoticeModal(false);
}

async function gfLoadNotices(options = {}) {
  if (gfNoticeLoading) return gfNoticeItems;
  gfNoticeLoading = true;
  try {
    const resp = await GlowfishApi.reader.noticesRaw();
    const data = await resp.json();
    gfNoticeItems = Array.isArray(data.notices) ? data.notices : [];
    gfRenderNotices();
    gfUpdateNoticeBadge();
    if (options.autoPopup) gfMaybeAutoOpenNotice();
  } catch (_) {
    gfRenderNoticeEmpty("暂无公告");
    gfNoticeItems = [];
    gfUpdateNoticeBadge();
  } finally {
    gfNoticeLoading = false;
  }
  return gfNoticeItems;
}

function initNotice() {
  if (gfNoticeInitialized) return;
  gfNoticeInitialized = true;
  const btn = document.getElementById("noticeBtn");
  const modal = document.getElementById("noticeModal");
  const close = document.getElementById("noticeClose");
  if (!btn || !modal) return;

  btn.onclick = async () => {
    await gfLoadNotices();
    gfOpenNoticeModal(true);
  };
  if (close) close.onclick = () => modal.classList.add("hidden");
  modal.addEventListener("mousedown", (e) => { if (e.target === modal) modal.classList.add("hidden"); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") modal.classList.add("hidden"); });

  window.setTimeout(() => gfLoadNotices({ autoPopup: true }), GF_NOTICE_STARTUP_DELAY_MS);
  window.setInterval(() => gfLoadNotices({ autoPopup: true }), GF_NOTICE_REFRESH_MS);
}

initNotice();
