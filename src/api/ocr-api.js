(function (global) {
  "use strict";
  const http = global.GlowfishApi.http;
  global.GlowfishApi.ocr = Object.freeze({
    progress: () => http.json("/api/import_progress"),
    recoverable: () => http.json("/api/import_jobs/recoverable"),
    resume: (jobId) => http.post(`/api/import_jobs/${encodeURIComponent(jobId)}/resume`, {}),
    discard: (jobId) => http.json(`/api/import_jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" }),
    reocrRegion: (body) => http.post("/api/reocr_region", body),
    reocrBatch: (body) => http.post("/api/reocr_batch", body)
  });
})(window);
