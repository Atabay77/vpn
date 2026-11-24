# 1.44.3: APK paylamak (Google Drive bloklasa). Ulanylyşy: python3 apk_srv.py [port]  →  ýüklemek: http://IP:8091/up , ýüklemek linki: http://IP:8091/<ady>.apk
# Açar sözsiz: bar faýlyň üstüne ýazmak bolmaýar (başga biri siziň APK-ňyzy çalşyp bilmez), iň köp 80 MB, iň köp 20 faýl.
import http.server, os, sys, urllib.parse, re, time, glob
D = os.environ.get("APK_DIR", "/root/apk"); PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8091; UP = "/up"
os.makedirs(D, exist_ok=True)
LATEST = ("/turkmenvpn.apk", "/latest.apk")   # 1.45.4: hemişe iň täze APK (link üýtgemeýär)
def dirs():
    """1.47.17: /root/apk, /root we her ulanyjynyň öý bukjasy (Termius / SFTP bilen _gdsh ýaly ulanyjy ýükleýär)."""
    more = os.environ.get("APK_MORE", "/root").split(":") + sorted(glob.glob("/home/*")) + sorted(glob.glob("/home/*/Downloads"))
    out = [D]
    for x in more:
        if x and os.path.isdir(x) and os.path.abspath(x) not in [os.path.abspath(y) for y in out]: out.append(x)
    return out
def apks():
    out = {}
    for d_ in dirs():
        try: names = os.listdir(d_)
        except Exception: continue
        for x in names:
            f = os.path.join(d_, x)
            if x.lower().endswith(".apk") and os.path.isfile(f) and x not in out: out[x] = f
    return out
def vkey(name):
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", name)
    return tuple(int(g or 0) for g in m.groups()) if m else ()
def newest():
    """1.47.17: iň täze — faýl adyndaky wersiýa boýunça (SFTP köne senäni saklap bilýär); ýaňy ýazylýan (90 s) faýl alynmaýar (ýarym ýüklenen bolmasyn)."""
    now = time.time(); a = {}
    for n, f in apks().items():
        try: st = os.stat(f)
        except Exception: continue
        if now - st.st_ctime < 90 or st.st_size < 1_000_000: continue
        a[n] = (vkey(n), st.st_mtime, f)
    if not a: return (None, None)
    n = max(a, key=lambda k: (a[k][0], a[k][1]))
    return (n, a[n][2])
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
            nm_, _ = newest()
            if not nm_: return s.send(404, b"entek APK yok")
            fs = [nm_]; n = urllib.parse.quote(nm_)
            b = ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'><title>Turkmen VPN</title>"
                 "<body style='margin:0;font-family:sans-serif;background:#0B1A2E;color:#F3E7D0;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center'>"
                 "<div style='padding:24px'><h2>Türkmen VPN</h2><p>" + fs[0].replace("<", "") + "</p>"
                 "<a href='/" + n + "' style='display:inline-block;padding:16px 28px;border-radius:14px;background:#E0B04A;color:#0B2117;font-weight:800;text-decoration:none;font-size:18px'>⬇ Ýükle / İndir</a>"
                 "<p style='font-size:13px;opacity:.75;margin-top:20px'>Ýüklenen faýly açyň we gurnaň. Telefon «näbelli çeşme» diýse, rugsat beriň.</p></div>").encode()
            return s.send(200, b, "text/html; charset=utf-8")
        if not p.endswith(".apk"): return s.send(404, b"yok")
        return s.serve_apk(p, True)
    def do_HEAD(s):
        p = urllib.parse.urlparse(s.path).path
        if not p.endswith(".apk"): return s.send(404, b"")
        return s.serve_apk(p, False)
    def serve_apk(s, p, body):
        """1.45.2: kesilen ýükleme galan ýerinden dowam edýär (Range / If-Range, ETag, Last-Modified) — Chrome we programma."""
        if p.lower() in LATEST: f = newest()[1]
        else: f = apks().get(os.path.basename(urllib.parse.unquote(p)))
        if not f or not os.path.isfile(f): return s.send(404, b"yok")
        st = os.stat(f); size = st.st_size
        etag = '"%x-%x"' % (size, int(st.st_mtime)); lm = s.date_time_string(int(st.st_mtime))
        a, b = 0, size - 1; part = False; y = ""
        rg = s.headers.get("Range", ""); ir = s.headers.get("If-Range", "")
        if rg.startswith("bytes=") and (not ir or ir in (etag, lm)):
            try:
                x, y = rg[6:].split(",")[0].strip().split("-")
                if x: a = int(x); b = int(y) if y else size - 1
                else: a = max(0, size - int(y))   # soňky N baýt
                b = min(b, size - 1); part = True
            except Exception: a, b, part = 0, size - 1, False
            # 1.47.17: programma faýly doly ýükläp, soňky pursatda baglanyşyk kesilse «bytes=SIZE-» soraýar — 416 bersek köne programmalar
            # 6 gezek synanyşyp ýüklemäni «bolmady» sanaýar we 0%-dan başlaýar. Doly bolsa: boş 206 (programma «gutardy» diýýär);
            # başga (uly) faýlyň bölegi bolsa: 200 bilen doly faýl (programma başdan ýazýar, bozuk APK bolmaýar).
            if part and a == size and not y:
                s.send_response(206); s.send_header("Content-Type", "application/vnd.android.package-archive"); s.send_header("Accept-Ranges", "bytes")
                s.send_header("ETag", etag); s.send_header("Content-Range", "bytes */%d" % size); s.send_header("Content-Length", "0"); s.end_headers(); return
            if part and a >= size: a, b, part = 0, size - 1, False
        s.send_response(206 if part else 200)
        s.send_header("Content-Type", "application/vnd.android.package-archive")
        # 1.47.19: doly (Range-siz) jogapda «Accept-Ranges» ýok — Chrome faýly 3 bölege bölüp parallel ýüklemesin (Türkmen internetinde bir bölek
        # kesilip, ortasy 12 MB nol galýardy → «paket nädogry»). Kesilen ýükleme Range bilen dowam edýär (206) — programma we brauzer.
        if part: s.send_header("Accept-Ranges", "bytes")
        s.send_header("ETag", etag); s.send_header("Last-Modified", lm)
        s.send_header("Content-Disposition", 'attachment; filename="%s"' % os.path.basename(f))
        s.send_header("Content-Length", str(b - a + 1))
        if part: s.send_header("Content-Range", "bytes %d-%d/%d" % (a, b, size))
        s.end_headers()
        if not body: return
        with open(f, "rb") as fh:
            fh.seek(a); left = b - a + 1
            try:
                while left > 0:
                    c = fh.read(min(left, 256 * 1024))
                    if not c: break
                    s.wfile.write(c); left -= len(c)
            except (BrokenPipeError, ConnectionResetError): pass
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
