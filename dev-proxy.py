#!/usr/bin/env python3
"""
Glowfish Reader 开发代理 —— mock 必要 API 端点，绕过登录/授权校验，支持文件上传。
用法：
  1) 保持 http.server 8801 在跑（python -m http.server 8801 --bind 127.0.0.1）
  2) 新终端运行本脚本：  python dev-proxy.py
  3) 浏览器打开 http://127.0.0.1:8802/  即可直接使用应用
"""
import io, json, os, re, secrets, socketserver, tempfile, time, urllib.error, urllib.request, http.server
from pathlib import Path
from email.parser import BytesParser
from email.policy import default

TARGET = "http://127.0.0.1:8801"
PORT = 8802
# Temp dir for uploaded files (persists for the proxy session)
UPLOAD_DIR = Path(tempfile.mkdtemp(prefix="glowfish_dev_uploads_"))
UPLOADS = {}  # token -> {items: [...], dir: Path, created_at: float}


class DevProxy(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[dev-proxy] {args[0]} {args[1]} {args[2]}")

    # ── JSON response helper ──────────────────────────────────
    def _json(self, status, body):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(body, ensure_ascii=False).encode("utf-8"))

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, PATCH, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    # ── Read body ─────────────────────────────────────────────
    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length) if length > 0 else b""

    # ── Proxy static requests to http.server ──────────────────
    def _proxy(self, method):
        url = TARGET + self.path
        data = self._read_body() if method in ("POST", "PUT", "PATCH", "DELETE") else None
        req = urllib.request.Request(url, data=data or None,
            headers={k: v for k, v in self.headers.items() if k.lower() not in ("host", "content-length")},
            method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=10)
            self.send_response(resp.status)
            for k, v in resp.headers.items():
                if k.lower() not in ("transfer-encoding", "content-encoding", "content-length"):
                    self.send_header(k, v)
            body = resp.read()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except urllib.error.HTTPError as e:
            self.send_response(e.code)
            b = e.read()
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Content-Type", e.headers.get("Content-Type", "text/html"))
            self.end_headers()
            self.wfile.write(b)
        except Exception as e:
            self._json(502, {"error": str(e)})

    # ═══════════ ROUTE DISPATCH ═══════════════════════════════

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    # ── GET ───────────────────────────────────────────────────
    def do_GET(self):
        path = self.path.split("?")[0]
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)

        if path == "/api/me":
            return self._json(200, {"username": "local", "display": "本机用户", "single": True})
        if path == "/api/license/status":
            return self._json(200, {"state": "trial", "allowed": True, "reason": None})
        if path == "/api/license/fingerprint":
            return self._json(200, {"fingerprint": "dev-fingerprint"})
        if path == "/health":
            return self._json(200, {"ok": True})
        if path == "/api/import_progress":
            return self._json(200, {"phase": "idle", "engine": "dev"})
        if path == "/api/notebooks":
            # Return empty notebook list; user can create their own via the UI
            return self._json(200, {"notebooks": []})
        if path == "/api/thumb":
            return self._handle_thumb(qs)

        self._proxy("GET")

    # ── POST ──────────────────────────────────────────────────
    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/login":
            return self._json(200, {"ok": True, "user": {"username": "local", "display": "本机用户"}})
        if path == "/api/login/password":
            return self._json(200, {"ok": True, "session_id": "dev-session",
                "account": {"username": "local", "display": "本机用户", "status": "trial"}})
        if path == "/api/logout":
            return self._json(200, {"ok": True})
        if path == "/api/sms/send":
            return self._json(200, {"ok": True, "dev_code": "123456"})
        if path == "/api/register":
            return self._json(200, {"ok": True, "user": {"username": "dev"}})
        if path == "/api/register/phone":
            return self._json(200, {"ok": True, "session_id": "dev-session",
                "account": {"username": "local", "display": "本机用户", "status": "trial"}})
        if path == "/api/password/reset":
            return self._json(200, {"ok": True})
        if path == "/api/account/check":
            return self._json(200, {"ok": True})
        if path == "/api/upload":
            return self._handle_upload()
        if path == "/api/open":
            return self._handle_open()

        self._proxy("POST")

    # ── PUT ───────────────────────────────────────────────────
    def do_PUT(self):
        path = self.path.split("?")[0]
        # Notebook save/settings endpoints — mock ok
        if "/api/" in path:
            return self._json(200, {"ok": True})
        self._proxy("PUT")

    # ── DELETE ────────────────────────────────────────────────
    def do_DELETE(self):
        path = self.path.split("?")[0]
        if "/api/" in path:
            return self._json(200, {"ok": True})
        self._proxy("DELETE")

    # ═══════════ UPLOAD HANDLER ═══════════════════════════════
    def _handle_upload(self):
        """Accept multipart file upload, save to temp dir, return mock token + items."""
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return self._json(400, {"detail": "Expected multipart/form-data"})

        raw = self._read_body()
        if not raw:
            return self._json(400, {"detail": "Empty request body"})

        # Parse boundary
        m = re.search(r'boundary=(?:"([^"]+)"|([^;]+))', ctype)
        if not m:
            return self._json(400, {"detail": "No boundary in Content-Type"})
        boundary = (m.group(1) or m.group(2)).encode("utf-8")

        files = []
        mtimes_json = "[]"

        # Simple multipart parser
        for part in raw.split(b"--" + boundary):
            if part.strip() in (b"", b"--"):
                continue
            # Split headers from body
            # strip leading \r\n (after boundary line)
            part_stripped = part.lstrip(b"\r\n")
            head_end = part_stripped.find(b"\r\n\r\n")
            if head_end < 0:
                continue
            header_bytes = part_stripped[:head_end]
            body = part_stripped[head_end + 4:]
            body = body.rstrip(b"\r\n--")  # strip trailing boundary marker

            # Parse headers
            msg = BytesParser(policy=default).parsebytes(header_bytes + b"\r\n\r\n")
            disp = msg.get("Content-Disposition", "")
            name_match = re.search(r'name="([^"]*)"', disp)
            filename_match = re.search(r'filename="([^"]*)"', disp)
            field_name = name_match.group(1) if name_match else ""
            filename = filename_match.group(1) if filename_match else ""

            if field_name == "mtimes":
                mtimes_json = body.decode("utf-8", errors="replace")
            elif filename:
                files.append(dict(body=body, name=filename))

        try:
            mtimes = json.loads(mtimes_json)
        except Exception:
            mtimes = []

        token = secrets.token_hex(8)
        tok_dir = UPLOAD_DIR / token
        tok_dir.mkdir(parents=True, exist_ok=True)
        items = []
        for i, f in enumerate(files):
            name = f["name"]
            ext = Path(name).suffix.lower()
            if ext not in (".jpg", ".jpeg", ".png", ".pdf"):
                continue
            dst = tok_dir / name
            dst.write_bytes(f["body"])
            mt = mtimes[i] / 1000.0 if i < len(mtimes) else 0
            it = {"rel": name, "name": name, "mtime": mt,
                  "type": "pdf" if ext == ".pdf" else "image"}
            if it["type"] == "pdf":
                # Try to get page count from PDF header
                it["pages"] = 1
                if f["body"].startswith(b"%PDF"):
                    import struct
                    # Count pages via cross-reference table or just guess
                    try:
                        # Quick PDF page count from /Type /Page entries
                        it["pages"] = max(1, f["body"].count(b"/Type") - f["body"].count(b"/Type/Catalog"))
                    except Exception:
                        it["pages"] = 1
            items.append(it)

        if not items:
            return self._json(400, {"detail": "No supported image or PDF files found"})

        UPLOADS[token] = {"items": items, "dir": tok_dir, "created_at": time.time()}
        return self._json(200, {"token": token, "items": items})

    # ═══════════ THUMBNAIL HANDLER ═══════════════════════════
    def _handle_thumb(self, qs):
        token = (qs.get("token") or [""])[0]
        rel = (qs.get("rel") or [""])[0]
        page = int((qs.get("page") or ["0"])[0])

        upload = UPLOADS.get(token)
        if upload:
            fp = upload["dir"] / rel
            if fp.is_file():
                try:
                    from PIL import Image, ImageOps
                    if fp.suffix.lower() == ".pdf":
                        # Generate simple placeholder for PDF
                        img = Image.new("RGB", (120, 160), (200, 200, 200))
                    else:
                        img = ImageOps.exif_transpose(Image.open(fp)).convert("RGB")
                        img.thumbnail((160, 160))
                    buf = io.BytesIO()
                    img.save(buf, "JPEG", quality=75)
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(buf.getvalue())))
                    self._cors()
                    self.end_headers()
                    self.wfile.write(buf.getvalue())
                    return
                except Exception:
                    pass

        # Fallback: generate placeholder thumbnail
        img = self._make_placeholder()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(img)))
        self._cors()
        self.end_headers()
        self.wfile.write(img)

    @staticmethod
    def _make_placeholder():
        """Generate a small placeholder JPEG (colored square with text area)."""
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (120, 120), (180, 190, 200))
            d = ImageDraw.Draw(img)
            d.rectangle([2, 2, 117, 117], outline=(140, 150, 160), width=1)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=60)
            return buf.getvalue()
        except ImportError:
            # Minimal JPEG (grey 1x1 pixel)
            return b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\" $!'\x1c\"1(%\x1c\x12\x1c\x1382:2'-5'42\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x1e\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xc4\x00=\x10\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00\x08\x00\xff\xd9"

    # ═══════════ OPEN HANDLER ═══════════════════════════════
    def _handle_open(self):
        """Process uploaded files — return a minimal proof structure."""
        raw = self._read_body()
        try:
            body = json.loads(raw)
        except Exception:
            return self._json(400, {"detail": "Invalid JSON"})

        token = body.get("token", "")
        items = body.get("items", [])
        name = body.get("name", "导入")

        if not token or not items:
            return self._json(400, {"detail": "No source items selected"})

        upload = UPLOADS.get(token)
        if not upload:
            return self._json(400, {"detail": "Upload token expired or invalid"})

        # Build minimal proof — one page per item
        pages = []
        for idx, it in enumerate(items):
            rel = it.get("rel", f"file_{idx}")
            ext = Path(rel).suffix.lower()
            page_id = Path(rel).stem
            pages.append({
                "page_id": page_id,
                "image": rel,
                "image_dir": str(upload["dir"]),
                "lines": [
                    {"id": f"{page_id}_l1", "text": f"[{rel}]",
                     "x": 50, "y": 50, "w": 200, "h": 20, "score": 0.95}
                ],
                "order": [f"{page_id}_l1"],
            })

        proof = {
            "name": name,
            "batch": Path(rel if items else "import").stem if items else "import",
            "source": name,
            "engine": "dev",
            "image_dir": str(upload["dir"]),
            "pages": pages,
        }

        return self._json(200, proof)


if __name__ == "__main__":
    import urllib.parse  # noqa: F811
    print(f"✨ Glowfish Reader 开发代理启动于 http://127.0.0.1:{PORT}/")
    print(f"   静态文件代理到 {TARGET}")
    print(f"   上传临时目录: {UPLOAD_DIR}")
    print(f"   API 端点已 mock，任意手机号+密码均可登录，支持文件上传导入")
    print(f"   按 Ctrl+C 停止")
    with socketserver.TCPServer(("127.0.0.1", PORT), DevProxy) as httpd:
        httpd.serve_forever()
