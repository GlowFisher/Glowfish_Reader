(function (global) {
  "use strict";
  const http = global.GlowfishApi.http;
  global.GlowfishApi.ocr = Object.freeze({
    progress: () => http.json("/api/import_progress"),
    reocrRegion: (body) => http.post("/api/reocr_region", body),
    reocrBatch: (body) => http.post("/api/reocr_batch", body)
  });
})(window);
