# 1.44.3: APK paylamak (Google Drive bloklasa). Ulanylyşy: python3 apk_srv.py GIZLI_SOZ [port]  →  ýüklemek: http://IP:8091/up-GIZLI_SOZ , ýüklemek linki: http://IP:8091/<ady>.apk
import http.server, os, sys, urllib.parse
D = os.environ.get("APK_DIR", "/root/apk"); TOK = sys.argv[1]; PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8091
os.makedirs(D, exist_ok=True)
PAGE = ("<meta name=viewport content='width=device-width'><h3>APK yukle</h3><input type=file id=f><br><br><button onclick='u()'>Yukle</button><pre id=o></pre>"
        "<script>async function u(){const f=document.getElementById('f').files[0];if(!f)return;const o=document.getElementById('o');o.textContent='yuklenyar...';"
        "const r=await fetch(location.pathname+'?n='+encodeURIComponent(f.name),{method:'POST',body:f});o.textContent=await r.text();}</script>").encode()
class H(http.server.SimpleHTTPRequestHandler):
    def __init__(s, *a, **k): super().__init__(*a, directory=D, **k)
    def send(s, code, b, ct="text/plain; charset=utf-8"):
        s.send_response(code); s.send_header("Content-Type", ct); s.send_header("Content-Length", str(len(b))); s.end_headers(); s.wfile.write(b)
    def do_GET(s):
        p = urllib.parse.urlparse(s.path).path
        if p == "/up-" + TOK: return s.send(200, PAGE, "text/html; charset=utf-8")
        if not p.endswith(".apk"): return s.send(404, b"yok")
        return super().do_GET()
    def do_POST(s):
        u = urllib.parse.urlparse(s.path)
        if u.path != "/up-" + TOK: return s.send(403, b"rugsat yok")
        n = os.path.basename(urllib.parse.parse_qs(u.query).get("n", ["app.apk"])[0]).replace(" ", "_")
        if not n.lower().endswith(".apk"): return s.send(400, b"dine .apk")
        L = int(s.headers.get("Content-Length", 0)); tmp = os.path.join(D, n + ".part")
        with open(tmp, "wb") as f:
            while L > 0:
                c = s.rfile.read(min(L, 1 << 20))
                if not c: break
                f.write(c); L -= len(c)
        if L > 0: os.remove(tmp); return s.send(400, b"dolanok gelmedi, tazeden synanys")
        os.replace(tmp, os.path.join(D, n))
        s.send(200, f"OK - link:\nhttp://{s.headers.get('Host', '')}/{urllib.parse.quote(n)}".encode())
http.server.ThreadingHTTPServer(("", PORT), H).serve_forever()
