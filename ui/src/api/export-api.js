(function (global) {
  "use strict";
  const http = global.GlowfishApi.http;
  global.GlowfishApi.export = Object.freeze({
    download: (body) => http.raw("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    })
  });
})(window);
