# 1.44.3: APK paylamak (Google Drive bloklasa). Ulanylyşy: python3 apk_srv.py [port]  →  ýüklemek: http://IP:8091/up , ýüklemek linki: http://IP:8091/<ady>.apk
# Açar sözsiz: bar faýlyň üstüne ýazmak bolmaýar (başga biri siziň APK-ňyzy çalşyp bilmez), iň köp 80 MB, iň köp 20 faýl.
import http.server, os, sys, urllib.parse
D = os.environ.get("APK_DIR", "/root/apk"); PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8091; UP = "/up"
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
        if p == UP: return s.send(200, PAGE, "text/html; charset=utf-8")
        if p == "/":   # ýükläp almak sahypasy (Gmail APK salgyly hatlary ret edýär — hatda şu sahypa)
            fs = sorted((x for x in os.listdir(D) if x.endswith(".apk")), key=lambda x: os.path.getmtime(os.path.join(D, x)), reverse=True)
            if not fs: return s.send(404, b"entek APK yok")
            n = urllib.parse.quote(fs[0])
            b = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Turkmen VPN</title>"
                 "<body style='margin:0;font-family:sans-serif;background:#0B1A2E;color:#F3E7D0;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center'>"
                 "<div style='padding:24px'><h2>Türkmen VPN</h2><p>" + fs[0].replace("<", "") + "</p>"
                 "<a href='/" + n + "' style='display:inline-block;padding:16px 28px;border-radius:14px;background:#E0B04A;color:#0B2117;font-weight:800;text-decoration:none;font-size:18px'>⬇ Ýükle / İndir</a>"
                 "<p style='font-size:13px;opacity:.75;margin-top:20px'>Ýüklenen faýly açyň we gurnaň. Telefon «näbelli çeşme» diýse, rugsat beriň.</p></div>").encode()
            return s.send(200, b, "text/html; charset=utf-8")
        if not p.endswith(".apk"): return s.send(404, b"yok")
        return super().do_GET()
    def do_POST(s):
        u = urllib.parse.urlparse(s.path)
        if u.path != UP: return s.send(404, b"yok")
        n = os.path.basename(urllib.parse.parse_qs(u.query).get("n", ["app.apk"])[0]).replace(" ", "_")
        if not n.lower().endswith(".apk"): return s.send(400, b"dine .apk")
        L = int(s.headers.get("Content-Length", 0))
        if os.path.exists(os.path.join(D, n)): return s.send(409, b"bu atda fayl bar - fayla basga at berin (mes. TurkmenVPN-1.44.4.apk)")
        if L <= 0 or L > 80 * 1024 * 1024: return s.send(400, b"fayl 80 MB-dan uly ya-da bos")
        if sum(1 for x in os.listdir(D) if x.endswith(".apk")) >= 20: return s.send(400, b"20 fayl doldy - kone APK-lary pozun: rm /root/apk/*.apk")
        tmp = os.path.join(D, n + ".part")
        with open(tmp, "wb") as f:
            while L > 0:
                c = s.rfile.read(min(L, 1 << 20))
                if not c: break
                f.write(c); L -= len(c)
        if L > 0: os.remove(tmp); return s.send(400, b"dolanok gelmedi, tazeden synanys")
        os.replace(tmp, os.path.join(D, n))
        s.send(200, f"OK - link:\nhttp://{s.headers.get('Host', '')}/{urllib.parse.quote(n)}".encode())
http.server.ThreadingHTTPServer(("", PORT), H).serve_forever()
