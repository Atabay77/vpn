"""Türkmenistan test programı (Termux).
Happ'te Termux "Bypass" olmalı ki testler VPN'siz, TM internetinden yapılsın.
Komutlar: tmtest start | stop | once | log | status
Çalışma: Drive'daki tmtest.txt'den abonelik linklerini okur, kodları çeker, Xray ile her koda
gerçekten bağlanıp ms ölçer, sonucu aynı dosyaya yazar. Bot sonucu okuyup çalışmayan kodları çıkarır."""
import os, sys, re, io, json, time, base64, signal, socket, subprocess, datetime, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor

H = os.path.expanduser("~")
SA = H + "/drive-sa.json"
LOG = H + "/tmtest.log"
PIDF = H + "/.tmtest.pid"
CFG = H + "/.tmtest_xray.json"
CHANNEL = "tmtest.txt"
INTERVAL = 10 * 60
TRIES, TRY_WAIT = 5, 60   # çalışmayan kod: 1 dk arayla toplam 5 deneme
API = "127.0.0.1:9095"
GEO_URL = "http://ip-api.com/json/?fields=status,countryCode"   # IP Info uygulamasının kullandığı veritabanı
TEST_URL = "https://www.cloudflare.com/cdn-cgi/trace"   # hem ms ölçer hem çıkış ülkesini söyler (loc=DE)
PROTOS = ("vless://", "vmess://", "trojan://", "ss://", "hysteria2://", "hy2://")


def log(msg):
    line = "[%s] %s" % (datetime.datetime.now().strftime("%m-%d %H:%M:%S"), msg)
    print(line, flush=True)
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 300000:
            keep = open(LOG, encoding="utf-8", errors="ignore").readlines()[-300:]
            open(LOG, "w", encoding="utf-8").writelines(keep)
        with open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")
    except Exception: pass


# ───────── Drive kanalı ─────────
def drive():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    import httplib2, google_auth_httplib2
    creds = service_account.Credentials.from_service_account_file(SA, scopes=["https://www.googleapis.com/auth/drive"])
    return build("drive", "v3", http=google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=30)), cache_discovery=False)

def channel_id(svc):
    """Botun oluşturduğu tmtest.txt dosyası (her seferinde adla bulunur, en son değişen)."""
    r = svc.files().list(q="name='%s' and trashed=false" % CHANNEL, fields="files(id,modifiedTime)", orderBy="modifiedTime desc", pageSize=5).execute(num_retries=2)
    files = r.get("files", [])
    if not files: raise RuntimeError("Drive'da %s yok (bot henüz oluşturmadı)" % CHANNEL)
    return files[0]["id"]

def read_channel(svc, fid):
    raw = svc.files().get_media(fileId=fid).execute(num_retries=2).decode("utf-8", "ignore").strip()
    return json.loads(raw) if raw.startswith("{") else {}

def write_channel(svc, fid, data):
    from googleapiclient.http import MediaIoBaseUpload
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    svc.files().update(fileId=fid, media_body=MediaIoBaseUpload(io.BytesIO(body), mimetype="text/plain")).execute(num_retries=2)


# ───────── kodlar (bot ile aynı anahtar) ─────────
def b64d(s):
    s = s.strip()
    return base64.urlsafe_b64decode(s.replace("+", "-").replace("/", "_") + "=" * (-len(s) % 4)).decode("utf-8", "ignore")

def code_key(link):
    raw = link.split("#", 1)[0].strip()
    if raw.lower().startswith("vmess://"):
        try:
            d = json.loads(b64d(raw[8:])); d.pop("ps", None)
            return "vmess://" + json.dumps(d, sort_keys=True)
        except Exception: pass
    return raw

def fetch_codes(url):
    req = urllib.request.Request(url, headers={"User-Agent": "v2rayN/6.42"})
    with urllib.request.urlopen(req, timeout=20) as r:
        content = r.read().decode("utf-8", "ignore")
    lines = content.splitlines()
    flat = "".join(content.split())
    for alt in (None, b"-_"):
        try: lines += base64.b64decode((flat + "=" * (-len(flat) % 4)).encode("ascii"), altchars=alt).decode("utf-8", "ignore").splitlines()
        except Exception: pass
    out = []
    for l in lines:
        l = l.strip()
        if l.lower().startswith(("vless://", "vmess://", "trojan://", "ss://", "hysteria://", "hysteria2://", "hy2://", "tuic://")) and l not in out:
            out.append(l)
    return out


# ───────── link -> Xray outbound ─────────
def _q(u):
    return {k: v[-1] for k, v in urllib.parse.parse_qs(u.query, keep_blank_values=True).items()}

def _hp(netloc):
    hp = netloc.rsplit("@", 1)[-1]
    if hp.startswith("["):
        h, _, p = hp[1:].partition("]")
        return h, int(re.split(r"[,:-]", p.lstrip(":"))[0])
    h, p = hp.rsplit(":", 1)
    return h, int(re.split(r"[,-]", p)[0])

def _pin(q):
    v = (q.get("pinSHA256") or q.get("pcs") or "").replace(":", "").strip()
    return v.lower() if re.fullmatch(r"[0-9a-fA-F]{64}", v) else ""

def _finalmask(q):
    if q.get("fm"):
        try:
            fm = json.loads(urllib.parse.unquote(q["fm"]))
            if fm: return fm
        except Exception: pass
    if q.get("obfs") == "salamander":
        return {"udp": [{"type": "salamander", "settings": {"password": q.get("obfs-password", "")}}]}
    return None

def _fragment(q, tag):
    """fragment=uzunluk,aralık,paketler (ör. 2,0-1,tlshello) -> Xray freedom fragment, dialerProxy ile."""
    v = urllib.parse.unquote(q.get("fragment") or "")
    parts = [x.strip() for x in v.split(",")]
    if len(parts) != 3: return None
    length, interval, packets = parts
    if not packets.replace("-", "").isalpha(): length, interval, packets = parts[1], parts[2], parts[0]   # paketler başta yazılmışsa
    return {"tag": tag + "-frag", "protocol": "freedom", "settings": {"fragment": {"packets": packets, "length": length, "interval": interval}}}

def _stream(q, sni_default):
    """Paylaşım linkindeki parametreler -> Xray streamSettings."""
    net = (q.get("type") or "tcp").lower()
    if net == "splithttp": net = "xhttp"
    if net == "h2": net = "http"
    host = q.get("host") or ""
    path = urllib.parse.unquote(q.get("path") or "/")
    st = {"network": "raw" if net in ("tcp", "raw") else net}
    if net in ("tcp", "raw"):
        if (q.get("headerType") or "none") == "http":
            st["rawSettings"] = {"header": {"type": "http", "request": {"path": [path], "headers": {"Host": [host] if host else []}}}}
    elif net == "ws": st["wsSettings"] = {"path": path, "host": host}
    elif net == "grpc": st["grpcSettings"] = {"serviceName": urllib.parse.unquote(q.get("serviceName") or ""), "multiMode": q.get("mode") == "multi"}
    elif net == "httpupgrade": st["httpupgradeSettings"] = {"path": path, "host": host}
    elif net == "xhttp":
        x = {"path": path, "host": host, "mode": q.get("mode") or "auto"}
        if q.get("extra"):
            try: x["extra"] = json.loads(urllib.parse.unquote(q["extra"]))
            except Exception: pass
        st["xhttpSettings"] = x
    elif net == "http": st["httpSettings"] = {"path": path, "host": [host] if host else []}
    elif net == "kcp": st["kcpSettings"] = {"header": {"type": q.get("headerType") or "none"}, "seed": q.get("seed") or ""}
    else: return None
    sec = (q.get("security") or "none").lower()
    sni = q.get("sni") or q.get("peer") or host or sni_default
    if sec == "tls":
        t = {"serverName": sni, "fingerprint": q.get("fp") or "chrome"}
        if q.get("alpn"): t["alpn"] = [a for a in urllib.parse.unquote(q["alpn"]).split(",") if a]
        pin = _pin(q)
        if pin: t["pinnedPeerCertSha256"] = pin
        st["security"] = "tls"; st["tlsSettings"] = t
    elif sec == "reality":
        st["security"] = "reality"
        st["realitySettings"] = {"serverName": sni, "fingerprint": q.get("fp") or "chrome", "publicKey": q.get("pbk", ""),
                                 "shortId": q.get("sid", ""), "spiderX": urllib.parse.unquote(q.get("spx") or "")}
        if q.get("pqv"): st["realitySettings"]["mldsa65Verify"] = q["pqv"]
    return st

def to_outbound(link, tag):
    """Desteklenmeyen/bozuk kod için None döner (test edilmeden kalır)."""
    try:
        proto = link.split("://", 1)[0].lower()
        if proto == "vmess":
            d = json.loads(b64d(link[8:].split("#", 1)[0]))
            q = {"type": d.get("net") or "tcp", "host": d.get("host", ""), "path": d.get("path", ""), "headerType": d.get("type") or "none",
                 "security": "tls" if str(d.get("tls", "")).lower() == "tls" else "none", "sni": d.get("sni", ""), "alpn": d.get("alpn", ""),
                 "fp": d.get("fp", ""), "serviceName": d.get("path", "")}
            st = _stream(q, str(d["add"]))
            if st is None: return None
            return [{"tag": tag, "protocol": "vmess", "streamSettings": st, "settings": {"vnext": [{"address": str(d["add"]), "port": int(d["port"]),
                    "users": [{"id": d["id"], "alterId": int(d.get("aid") or 0), "security": d.get("scy") or "auto"}]}]}}]
        u = urllib.parse.urlsplit(link.split("#", 1)[0])
        q = _q(u)
        if proto == "ss":
            netloc = u.netloc
            if "@" not in netloc: netloc = b64d(urllib.parse.unquote(netloc))
            userinfo = urllib.parse.unquote(netloc.rpartition("@")[0])
            h, p = _hp(netloc)
            if ":" not in userinfo: userinfo = b64d(userinfo)
            method, _, pw = userinfo.partition(":")
            if q.get("plugin"): return None
            return [{"tag": tag, "protocol": "shadowsocks", "settings": {"servers": [{"address": h, "port": p, "method": method, "password": pw}]}}]
        h, p = _hp(u.netloc)
        user = urllib.parse.unquote(u.netloc.rsplit("@", 1)[0]) if "@" in u.netloc else ""
        if proto in ("hysteria2", "hy2"):
            if q.get("obfs") and q.get("obfs") != "salamander": return None
            t = {"serverName": q.get("sni") or h, "alpn": urllib.parse.unquote(q.get("alpn") or "h3").split(",")}
            pin = _pin(q)
            if pin: t["pinnedPeerCertSha256"] = pin
            st = {"network": "hysteria", "hysteriaSettings": {"version": 2, "auth": user}, "security": "tls", "tlsSettings": t}
            fm = _finalmask(q)
            if fm: st["finalmask"] = fm
            return [{"tag": tag, "protocol": "hysteria", "settings": {"version": 2, "address": h, "port": p}, "streamSettings": st}]
        st = _stream(q, h)
        if st is None: return None
        if proto == "vless":
            usr = {"id": user, "encryption": q.get("encryption") or "none"}
            if q.get("flow"): usr["flow"] = q["flow"]
            ob = {"tag": tag, "protocol": "vless", "streamSettings": st, "settings": {"vnext": [{"address": h, "port": p, "users": [usr]}]}}
            fr = _fragment(q, tag)
            if fr:
                st["sockopt"] = {"dialerProxy": fr["tag"]}
                return [ob, fr]
            return [ob]
        if proto == "trojan":
            if "security" not in q: st["security"] = "tls"; st["tlsSettings"] = {"serverName": q.get("sni") or h, "fingerprint": q.get("fp") or "chrome"}
            return [{"tag": tag, "protocol": "trojan", "streamSettings": st, "settings": {"servers": [{"address": h, "port": p, "password": user}]}}]
        return None
    except Exception:
        return None


# ───────── test ─────────
XRAY = H + "/xray"
BASE_PORT = 21000

def build_config(groups):
    """groups: her kod için [ana outbound, (fragment outbound)]. Her kod kendi yerel HTTP portundan çıkar."""
    ins, rules, outs = [], [], []
    for i, g in enumerate(groups):
        tag = g[0]["tag"]
        ins.append({"tag": "in-" + tag, "listen": "127.0.0.1", "port": BASE_PORT + i, "protocol": "http"})
        rules.append({"type": "field", "inboundTag": ["in-" + tag], "outboundTag": tag})
        outs += g
    return {"log": {"loglevel": "none"}, "inbounds": ins, "outbounds": outs + [{"tag": "direct", "protocol": "freedom"}],
            "routing": {"rules": rules}}

def xray_check(cfg):
    open(CFG, "w").write(json.dumps(cfg))
    r = subprocess.run([XRAY, "run", "-test", "-c", CFG], capture_output=True, text=True, timeout=60)
    return r.returncode == 0, (r.stdout + r.stderr).strip()[-300:]

def _endpoint(g):
    st = g[0].get("settings", {})
    srv = (st.get("vnext") or st.get("servers") or [st])[0]
    return srv.get("address"), srv.get("port")

def run_tests(groups):
    """Her kodun ms'ini döner (-1 = çalışmıyor). Xray aynı adres:port'a giden bağlantıları paylaşabildiği
    için aynı adresi kullanan kodlar ayrı turlarda (ayrı Xray süreçlerinde) test edilir."""
    seen, rounds = {}, []
    for i, g in enumerate(groups):
        r = seen.get(_endpoint(g), 0); seen[_endpoint(g)] = r + 1
        while len(rounds) <= r: rounds.append([])
        rounds[r].append(i)
    out = [None] * len(groups)   # None = test edilemedi (Xray kabul etmedi)
    for rn, idx in enumerate(rounds, 1):
        log("   tur %d/%d: %d kod test ediliyor..." % (rn, len(rounds), len(idx)))
        cur = [groups[i] for i in idx]
        if not xray_check(build_config(cur))[0]:   # biri bozuksa tek tek ayıkla
            good = [i for i in idx if xray_check(build_config([groups[i]]))[0]]
            idx, cur = good, [groups[i] for i in good]
            if not cur: continue
            ok, err = xray_check(build_config(cur))
            if not ok: raise RuntimeError("Xray ayarı geçersiz: %s" % err)
        p = subprocess.Popen([XRAY, "run", "-c", CFG], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(50):
                try: socket.create_connection(("127.0.0.1", BASE_PORT), 1).close(); break
                except Exception: time.sleep(0.2)
            with ThreadPoolExecutor(32) as ex:
                for i, r in zip(idx, ex.map(delay, [BASE_PORT + j for j in range(len(cur))])): out[i] = r
        finally:
            p.terminate()
            try: p.wait(5)
            except Exception: p.kill()
    return out

def delay(port):
    """Kod üzerinden Cloudflare trace açar. Dönüş: (ms, çıkış ülkesi) — çalışmıyorsa (-1, None)."""
    op = urllib.request.build_opener(urllib.request.ProxyHandler({"http": "http://127.0.0.1:%d" % port, "https": "http://127.0.0.1:%d" % port}))
    best, cc = -1, None
    for _ in range(2):
        t = time.time()
        try:
            with op.open(TEST_URL, timeout=6) as r:
                body = r.read(2000).decode("utf-8", "ignore")
                if r.status == 200:
                    ms = int((time.time() - t) * 1000)
                    best = ms if best < 0 else min(best, ms)
                    m = re.search(r"^loc=([A-Z]{2})$", body, re.M)
                    if m: cc = m.group(1).lower()
        except Exception: pass
    if best > 0:
        # Ülke: IP Info uygulamasıyla aynı veritabanı (ip-api.com). Cevap vermezse Cloudflare'in ülkesi kalır.
        try:
            with op.open(GEO_URL, timeout=6) as r:
                j = json.loads(r.read(500).decode("utf-8", "ignore"))
                if j.get("status") == "success" and j.get("countryCode"): cc = j["countryCode"].lower()
        except Exception: pass
    return best, cc

def country():
    """IP kontrol siteleri TM'de çoğunlukla engelli: açılmazsa '?' döner (= doğrudan TM bağlantısı sayılır)."""
    try:
        with urllib.request.urlopen("https://ipwho.is/?fields=country_code,country", timeout=10) as r:
            j = json.loads(r.read().decode())
            return j.get("country_code", "?"), j.get("country", "?")
    except Exception as e:
        return "?", str(e)[:60]

def cycle():
    cc, cname = country()
    if cc == "?":
        log("ℹ️ IP kontrol sitesi açılmadı (TM'de engelli) → VPN'siz bağlantı varsayıldı")
    try:
        svc = drive()
        fid = channel_id(svc)
        ch = read_channel(svc, fid)
    except Exception as e:
        log("❌ Drive'a ulaşılamadı: %s" % str(e)[:150]); return
    log("📂 Drive OK, %s" % ("bottan %d kod" % len(ch["codes"]) if ch.get("codes") else "%d abonelik okunuyor..." % len(ch.get("sources", []))))
    if cc not in ("TM", "?"):
        log("⚠️ Termux TM'den çıkmıyor (%s). Happ → Per-app Proxy → Bypass + Termux, VPN'i yeniden bağla." % cname)
        ch.update({"status": "not_tm", "status_ts": int(time.time()), "country": cname})
        write_channel(svc, fid, ch)
        return
    codes, keys = [], set()
    if ch.get("codes"):   # bot kodları kanala yazıyor; Google'a gitmeye gerek yok
        for c in ch["codes"]:
            k = code_key(c)
            if k not in keys: keys.add(k); codes.append(c)
    else:
        for u in ch.get("sources", []):
            try:
                for c in fetch_codes(u):
                    k = code_key(c)
                    if k not in keys: keys.add(k); codes.append(c)
            except Exception as e:
                log("❌ Abonelik okunamadı: %s" % str(e)[:80])
    if not codes:
        log("❌ Kod yok, test yapılmadı"); return
    obs, keys_of = [], []
    for i, c in enumerate(codes):
        ob = to_outbound(c, "c%d" % i)
        if ob: obs.append(ob); keys_of.append(code_key(c))
    log("📥 %d kod çekildi, test başlıyor..." % len(codes))
    t0 = time.time()
    try: res_list = run_tests(obs)
    except RuntimeError as e:
        log("❌ %s" % e); return
    for attempt in range(2, TRIES + 1):   # çalışmayanlar 1 dk arayla tekrar denenir; TRIES denemenin hiçbirinde geçemezse çalışmıyor sayılır
        bad = [i for i, r in enumerate(res_list) if r is not None and r[0] < 0]
        if not bad: break
        log("🔁 %d kod çalışmadı, 1 dk sonra tekrar denenecek (%d/%d)" % (len(bad), attempt, TRIES))
        time.sleep(TRY_WAIT)
        try: again = run_tests([obs[i] for i in bad])
        except RuntimeError as e:
            log("❌ %s" % e); break
        for i, r in zip(bad, again):
            if r is not None and r[0] > 0: res_list[i] = r
    results = {k: r[0] for k, r in zip(keys_of, res_list) if r is not None}
    exits = {k: r[1] for k, r in zip(keys_of, res_list) if r is not None and r[1]}   # gerçek çıkış ülkesi (ölçülen)
    good = sum(1 for v in results.values() if v > 0)
    try: ch = read_channel(svc, fid)   # test sürerken bot kanala yazmış olabilir (kodlar, güncelleme): onları silme
    except Exception: pass
    ch.update({"tmtest_ver": my_sha(), "results": results, "exits": exits, "ts": int(time.time()), "status": "ok", "status_ts": int(time.time()),
               "country": cname, "tested": len(results), "good": good, "skipped": len(codes) - len(results)})
    write_channel(svc, fid, ch)
    log("✅ %d kod test edildi (%d sn): %d çalışıyor, %d çalışmıyor, %d desteklenmiyor (test edilmedi)"
        % (len(results), time.time() - t0, good, len(results) - good, len(codes) - len(results)))


SELF = os.path.abspath(__file__)

def my_sha():
    import hashlib
    with open(SELF, "rb") as f: return hashlib.sha256(f.read()).hexdigest()[:16]

def self_update(ch):
    """Bot kanala yeni tmtest.py koyduysa: kontrol et, yaz, yeniden başla."""
    code, sha = ch.get("tmtest_code"), ch.get("tmtest_sha")
    if not code or not sha or sha == my_sha(): return
    try: done = open(SELF + ".kurulan").read().strip()
    except Exception: done = ""
    if sha == done: return   # bu sürüm zaten bir kez kuruldu (sonradan elle başka sürüm kurulduysa ezme)
    try: compile(code, "tmtest.py", "exec")
    except Exception as e:
        log("❌ Gelen güncelleme bozuk, kurulmadı: %s" % str(e)[:100]); return
    import shutil
    shutil.copy(SELF, SELF + ".eski")
    with open(SELF + ".tmp", "w", encoding="utf-8") as f: f.write(code)
    os.replace(SELF + ".tmp", SELF)
    with open(SELF + ".kurulan", "w") as f: f.write(sha)
    log("⬆️ Telefon programı güncellendi (%s), yeniden başlıyor" % sha)
    os.execv(sys.executable, [sys.executable, "-u", SELF, "_loop"])

def codes_sig():
    """Kanaldaki kod listesinin imzası (değişti mi diye bakmak için). Hata olursa None.
    Ayrıca bot yeni program koyduysa kendini günceller."""
    try:
        ch = read_channel(drive_cached(), channel_id(drive_cached()))
        self_update(ch)
        return ch.get("codes_ts") or 0
    except Exception:
        _SVC.clear()   # bağlantı koptuysa bir dahakine yenisini kur
        return None

_SVC = {}
def drive_cached():
    if "s" not in _SVC: _SVC["s"] = drive()
    return _SVC["s"]

def loop():
    open(PIDF, "w").write(str(os.getpid()))
    log("▶️ Test başladı: her %d dk, kodlar değişince hemen" % (INTERVAL // 60))
    last_run, last_sig = 0, None
    while True:
        sig = codes_sig()
        if time.time() - last_run >= INTERVAL or (sig is not None and last_sig is not None and sig != last_sig):
            if last_sig is not None and sig != last_sig: log("🔁 Kodlar değişti → hemen test")
            try: cycle()
            except Exception as e: log("❌ Hata: %s" % str(e)[:200])
            last_run = time.time()
        if sig is not None: last_sig = sig
        time.sleep(60)

def running():
    """Kayıtlı PID gerçekten tmtest mi? (yeniden başlatmadan sonra aynı numara başka programa geçebilir)"""
    try:
        pid = int(open(PIDF).read())
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return pid if b"tmtest" in f.read() else None
    except Exception: return None

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "_loop": loop()
    elif cmd == "once":
        try: cycle()
        except Exception as e: log("❌ Hata: %s" % str(e)[:200])
    elif cmd == "start":
        if running(): print("Zaten çalışıyor (pid %s)" % running()); return
        subprocess.run(["termux-wake-lock"], stderr=subprocess.DEVNULL)
        subprocess.Popen([sys.executable, "-u", os.path.abspath(__file__), "_loop"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1); print("✅ Test başladı. Log: tmtest log")
    elif cmd == "stop":
        p = running()
        if p: os.kill(p, signal.SIGTERM); print("🛑 Durdu")
        else: print("Çalışmıyor")
        subprocess.run(["termux-wake-unlock"], stderr=subprocess.DEVNULL)
    elif cmd == "log":
        os.system("tail -n 25 %s" % LOG)
    else:
        p = running(); print("🟢 Çalışıyor (pid %s)" % p if p else "🔴 Çalışmıyor")

if __name__ == "__main__":
    main()
