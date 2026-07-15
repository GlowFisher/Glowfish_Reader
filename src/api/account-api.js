(function (global) {
  "use strict";
  const http = global.GlowfishApi.http;
  global.GlowfishApi.account = Object.freeze({
    login: (phone, password) => http.post("/api/login", { phone, password }),
    register: (phone, code, password) => http.post("/api/register", { phone, code, password }),
    sendSms: (phone, scene) => http.post("/api/sms/send", { phone, scene }),
    resetPassword: (phone, code, password) => http.post("/api/password/reset", { phone, code, password }),
    me: () => http.json("/api/me"),
    meRaw: () => http.raw("/api/me"),
    logout: () => http.post("/api/logout", {})
  });
})(window);
