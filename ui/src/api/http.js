(function (global) {
  "use strict";
  const nativeFetch = global.fetch.bind(global);

  async function raw(url, options) {
    return nativeFetch(url, options);
  }

  async function json(url, options) {
    const response = await nativeFetch(url, options);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || payload.reason || response.statusText);
    return payload;
  }

  async function post(url, body) {
    return json(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
  }

  global.GlowfishApi = global.GlowfishApi || {};
  global.GlowfishApi.http = Object.freeze({ raw, json, post, nativeFetch });
  global.api = json;
})(window);
