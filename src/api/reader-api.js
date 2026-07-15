(function (global) {
  "use strict";
  const http = global.GlowfishApi.http;
  global.GlowfishApi.reader = Object.freeze({
    open: (body) => http.post("/api/open", body),
    save: (body) => http.post("/api/save", body),
    load: (batch) => http.json(`/api/load?batch=${encodeURIComponent(batch)}`),
    notebooks: () => http.json("/api/notebooks"),
    searchRaw: (options) => http.raw("/api/library_search", options),
    noticesRaw: () => http.raw("/api/notices", { cache: "no-store" }),
    raw: http.raw
  });
})(window);
