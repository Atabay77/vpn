#!/usr/bin/env python3
"""Türkmen VPN habar serweri (ntfy.sh ýaly, ýöne öz VPS-iňizde).

  POST /<konu>                         — habar goýmak (beden: şifrlenen tekst)
  GET  /<konu>/json?poll=1&since=X     — habarlar (X: habar kimligi, «12h», «all»)
  GET  /health                         — barlag
  /v1/projects/*/databases/*/documents — 1.41: Google Firestore-yň REST meňzeşi (GET, :commit, :runQuery).
                                         Program we bot Firestore ýerine şu VPS-i ulanýar (okalyş çägi ýok).

1.42: UPSTREAM=IP:PORT bilen işledilse — «öňdäki VPS»: özünde hiç zat saklamaýar, ähli birikmeleri
baza VPS-e (botuň VPS-i) geçirýär. Öňdäki VPS-i her gün çalşyp bolýar — maglumat bazada galýar.

Habarlary okap bilmeýär: program we bot öz açarlary bilen şifrleýär. Diňe saklaýar we berýär.
Diňe Python 3 (goşmaça kitaphana gerek däl).
"""
import bisect, calendar, json, os, re, secrets, socket, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "8090"))
DATA = os.environ.get("DATA", "/var/lib/tvrelay")
TOPIC = re.compile(r"^[a-z0-9]{8,80}$")
# konunyň görnüşi: tvpn + 16 simwol, soň: m (bota), d (telefona), g (Global chat), p (surat)
# 1.40: admin paneli (~60 KB), bilet suratlary we hekaýalar sygar ýaly çäkler ulaldyldy
KIND = {"m": (3000, 7 * 86400, 192 * 1024), "d": (60, 7 * 86400, 256 * 1024), "g": (600, 2 * 86400, 8192), "p": (1, 10 ** 9, 96 * 1024)}
OTHER = (100, 86400, 8192)
# bir IP-den minutda (1.40: Türkmenistanda müňlerçe adam operatoryň bir IP-sinden çykýar; 1.42: öňdäki VPS-den hemmeler bir IP bolup gelýär)
RATE_GET, RATE_POST = 300000, 60000

lock = threading.Lock()
cond = threading.Condition(lock)         # 1.40.1: garaşýan soraglar (täze habar gelen badyna jogap)
topics = {}                              # konu → [habar]
seq = [0]
hits = {}                                # (ip, kind) → [minut, sany]
os.makedirs(DATA, exist_ok=True)
SIDFILE = os.path.join(DATA, "sid")


def sid():
    """1.42: bazanyň kimligi — bot öňdäki VPS-iň şu baza geçirýändigini barlaýar."""
    try: return open(SIDFILE).read().strip()
    except FileNotFoundError:
        v = secrets.token_hex(6)
        with open(SIDFILE, "w") as f: f.write(v)
        return v


def kind_of(t):
    return KIND.get(t[20], OTHER) if len(t) > 20 and t.startswith("tvpn") else OTHER


def load():
    for fn in os.listdir(DATA):
        if fn.endswith(".json") and TOPIC.match(fn[:-5]):
            try:
                with open(os.path.join(DATA, fn)) as f: topics[fn[:-5]] = json.load(f)
            except Exception: pass
    seq[0] = max([int(m["id"][1:]) for L in topics.values() for m in L] + [0])


def save(t):
    p = os.path.join(DATA, t + ".json")
    with open(p + ".tmp", "w") as f: json.dump(topics[t], f)
    os.replace(p + ".tmp", p)


def prune(t, now):
    keep, age, _ = kind_of(t)
    L = [m for m in topics.get(t, []) if now - m["time"] < age]
    topics[t] = L[-keep:]


def rate(ip, k, lim):
    m = int(time.time() // 60)
    with lock:
        h = hits.get((ip, k))
        if not h or h[0] != m: h = hits[(ip, k)] = [m, 0]
        h[1] += 1
        if len(hits) > 50000: hits.clear()
        return h[1] <= lim


# ───────────── 1.41: Firestore REST meňzeşi (Google-syz) ─────────────
# Resminama: «kolleksiýa/id» ýa-da «kolleksiýa/id/i/id»; meýdanlar: b (şifrli tekst) + t (serweriň wagty).
# Program (API açary bilen) — Firestore düzgünleri ýaly çäkli; bot (Bearer açar) — hemme zat.
FSDIR = os.path.join(DATA, "fs")
SEG = re.compile(r"^[\w\-]{1,100}$")
SMALL = 16384                            # şundan kiçi resminamalar ýatda hem saklanýar
fslock = threading.Lock()
fs_meta = {}                             # ýol → t (mikrosekunt)
fs_small = {}                            # ýol → b (kiçiler)
fs_idx = {}                              # kolleksiýa → [(t, id)] (t boýunça tertipli)
fs_last = [0]
BOTKEY = [os.environ.get("BOTKEY", "")]
KEYFILE = os.path.join(DATA, "botkey")
# Firestore düzgünleri (subbot.py FS_RULES): kolleksiýa → (okap bolýar, täze resminama çägi, üýtgedip bolýar)
RULE1 = {"m": (False, 9000, False), "g": (True, 5000, False), "gi": (True, 160000, False),
         "p": (True, 120000, True), "q": (True, 600000, True), "n": (True, 0, False)}
RULE3 = {"d": (True, 0, False), "x": (True, 200000, False), "r": (True, 3000, False)}
# köne resminamalar (gün): Global chat we suratlar 10, bota habarlar 3, telefona 30; DM otaglarynda iň köp 1000 habar
KEEP_DAYS = {"g": 10, "gi": 10, "m": 3, "d": 30, "r": 30}
ROOM_MAX = 1000


def fs_rule(path):
    s = path.split("/")
    if len(s) == 2: return RULE1.get(s[0])
    if len(s) == 4 and s[2] == "i": return RULE3.get(s[0])
    return None


def fs_ok_path(path):
    s = path.split("/")
    return len(s) in (2, 4) and all(SEG.match(x) for x in s)


def fs_now():
    t = int(time.time() * 1e6)
    if t <= fs_last[0]: t = fs_last[0] + 1
    fs_last[0] = t
    return t


def ts_str(t): return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t // 1000000)) + ".%06dZ" % (t % 1000000)


def ts_parse(s):
    m = re.match(r"^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?(?:Z|[+-]00:00)?$", str(s or ""))
    if not m: return None
    sec = calendar.timegm(tuple(int(x) for x in m.groups()[:6]) + (0, 0, 0))
    return sec * 1000000 + int((m.group(7) or "")[:6].ljust(6, "0"))


def fs_file(path): return os.path.join(FSDIR, path.replace("/", "~"))


def fs_idx_put(path, t):
    coll, did = path.rsplit("/", 1)
    L = fs_idx.setdefault(coll, [])
    old = fs_meta.get(path)
    if old is not None:
        i = bisect.bisect_left(L, (old, did))
        if i < len(L) and L[i] == (old, did): L.pop(i)
    bisect.insort(L, (t, did)); fs_meta[path] = t


def fs_idx_del(path):
    old = fs_meta.pop(path, None)
    if old is None: return
    coll, did = path.rsplit("/", 1)
    L = fs_idx.get(coll) or []
    i = bisect.bisect_left(L, (old, did))
    if i < len(L) and L[i] == (old, did): L.pop(i)
    if not L: fs_idx.pop(coll, None)
    fs_small.pop(path, None)


def fs_put(path, b):
    t = fs_now()
    fn = fs_file(path)
    with open(fn + ".tmp", "w", encoding="utf-8") as f: f.write("%d\n%s" % (t, b))
    os.replace(fn + ".tmp", fn)
    fs_idx_put(path, t)
    if len(b) <= SMALL: fs_small[path] = b
    else: fs_small.pop(path, None)
    return t


def fs_rm(path):
    fs_idx_del(path)
    try: os.remove(fs_file(path))
    except FileNotFoundError: pass


def fs_body(path):
    b = fs_small.get(path)
    if b is not None: return b
    try:
        with open(fs_file(path), encoding="utf-8") as f: f.readline(); return f.read()
    except FileNotFoundError: return None


def fs_load():
    os.makedirs(FSDIR, exist_ok=True)
    try: BOTKEY[0] = BOTKEY[0] or open(KEYFILE).read().strip()
    except FileNotFoundError: pass
    for fn in os.listdir(FSDIR):
        if fn.endswith(".tmp"): continue
        path = fn.replace("~", "/")
        if not fs_ok_path(path): continue
        try:
            with open(os.path.join(FSDIR, fn), encoding="utf-8") as f:
                t = int(f.readline().strip())
                if os.path.getsize(os.path.join(FSDIR, fn)) <= SMALL + 32: fs_small[path] = f.read()
        except Exception: continue
        fs_idx_put(path, t); fs_last[0] = max(fs_last[0], t)


def fs_prune():
    """Köne resminamalar: diske we ýada ýer galsyn."""
    now = int(time.time() * 1e6)
    with fslock:
        for coll, L in list(fs_idx.items()):
            top = coll.split("/")[0]
            if top in KEEP_DAYS:
                lim = now - KEEP_DAYS[top] * 86400 * 1000000
                for t, did in [x for x in L if x[0] < lim]: fs_rm(coll + "/" + did)
            elif top == "x" and len(L) > ROOM_MAX:
                for t, did in list(L[:len(L) - ROOM_MAX]): fs_rm(coll + "/" + did)


def fs_pruner():
    while True:
        time.sleep(1800)
        try: fs_prune()
        except Exception as e: print("prune:", e, flush=True)


def fs_doc(root, path, t, b):
    ts = ts_str(t)
    return {"name": root + "/" + path, "fields": {"b": {"stringValue": b}, "t": {"timestampValue": ts}}, "createTime": ts, "updateTime": ts}


def fs_err(code, status, msg):
    return code, {"error": {"code": code, "message": msg, "status": status}}


def fs_who(h):
    """«bot» (Bearer açar), «app» (programyň ýoly) ýa-da None (nädogry bot açary)."""
    a = h.headers.get("Authorization") or ""
    if a.startswith("Bearer "):
        k = a[7:].strip()
        with fslock:
            if not BOTKEY[0] and len(k) >= 24:   # ilkinji gelen bot açary (TOFU) — soň diňe şol
                BOTKEY[0] = k
                with open(KEYFILE, "w") as f: f.write(k)
                os.chmod(KEYFILE, 0o600)
        return "bot" if BOTKEY[0] and k == BOTKEY[0] else None
    return "app"


def fs_handle(h, method, path, body):
    """Dönüş: (kod, JSON)."""
    m = re.match(r"^/v1/(projects/[^/]+/databases/[^/]+/documents)(/[^:]*)?(?::(commit|runQuery))?$", path)
    if not m: return fs_err(404, "NOT_FOUND", "yok")
    root, rest, op = m.group(1), (m.group(2) or "").strip("/"), m.group(3)
    who = fs_who(h)
    if who is None: return fs_err(403, "PERMISSION_DENIED", "Missing or insufficient permissions.")
    if method == "GET" and not op:
        if not fs_ok_path(rest): return fs_err(400, "INVALID_ARGUMENT", "ýol")
        r = fs_rule(rest)
        if who != "bot" and not (r and r[0]): return fs_err(403, "PERMISSION_DENIED", "Missing or insufficient permissions.")
        with fslock:
            t = fs_meta.get(rest); b = fs_body(rest) if t is not None else None
        if b is None: return fs_err(404, "NOT_FOUND", "Document not found.")
        return 200, fs_doc(root, rest, t, b)
    if method != "POST": return fs_err(405, "INVALID_ARGUMENT", "usul")
    if op == "commit":
        ws = (body or {}).get("writes") or []
        if not ws or len(ws) > 500: return fs_err(400, "INVALID_ARGUMENT", "writes")
        plan = []
        with fslock:
            for w in ws:
                if "delete" in w:
                    p = str(w["delete"]).split("/documents/", 1)[-1]
                    if who != "bot": return fs_err(403, "PERMISSION_DENIED", "Missing or insufficient permissions.")
                    if not fs_ok_path(p): return fs_err(400, "INVALID_ARGUMENT", "ýol")
                    plan.append(("del", p, None)); continue
                u = w.get("update") or {}
                p = str(u.get("name") or "").split("/documents/", 1)[-1]
                b = ((u.get("fields") or {}).get("b") or {}).get("stringValue")
                if not fs_ok_path(p) or not isinstance(b, str): return fs_err(400, "INVALID_ARGUMENT", "ýol / b")
                exists = p in fs_meta or any(x[1] == p for x in plan if x[0] == "put")
                if (w.get("currentDocument") or {}).get("exists") is False and exists:
                    return fs_err(409, "ALREADY_EXISTS", "Document already exists: " + p)
                if who != "bot":
                    r = fs_rule(p)
                    lim = r[1] if r else 0
                    allowed = bool(r) and ((r[2] and exists) or (not exists and lim > 0)) and b.startswith("v1.") and len(b) < lim
                    if not allowed: return fs_err(403, "PERMISSION_DENIED", "Missing or insufficient permissions.")
                plan.append(("put", p, b))
            res = []
            for kind, p, b in plan:
                if kind == "del": fs_rm(p); res.append({})
                else: res.append({"updateTime": ts_str(fs_put(p, b))})
        return 200, {"writeResults": res, "commitTime": ts_str(fs_now())}
    if op == "runQuery":
        q = (body or {}).get("structuredQuery") or {}
        try:
            coll = q["from"][0]["collectionId"]
            desc = ((q.get("orderBy") or [{}])[0].get("direction") == "DESCENDING")
            lim = max(1, min(1000, int(q.get("limit") or 100)))
        except Exception: return fs_err(400, "INVALID_ARGUMENT", "sorag")
        cpath = (rest + "/" if rest else "") + coll
        if not SEG.match(coll) or not fs_ok_path(cpath + "/x"): return fs_err(400, "INVALID_ARGUMENT", "kolleksiýa")
        r = fs_rule(cpath + "/x")
        if who != "bot" and not (r and r[0]): return fs_err(403, "PERMISSION_DENIED", "Missing or insufficient permissions.")
        after = None
        ff = (q.get("where") or {}).get("fieldFilter")
        if ff:
            if (ff.get("field") or {}).get("fieldPath") != "t" or ff.get("op") != "GREATER_THAN": return fs_err(400, "INVALID_ARGUMENT", "where")
            after = ts_parse((ff.get("value") or {}).get("timestampValue"))
            if after is None: return fs_err(400, "INVALID_ARGUMENT", "wagt")
        with fslock:
            L = fs_idx.get(cpath) or []
            i = bisect.bisect_right(L, (after, "\U0010ffff")) if after is not None else 0
            sel = L[i:]
            sel = sel[::-1][:lim] if desc else sel[:lim]
            out = [{"document": fs_doc(root, cpath + "/" + did, t, fs_body(cpath + "/" + did) or ""), "readTime": ts_str(int(time.time() * 1e6))} for t, did in sel]
        return 200, (out or [{"readTime": ts_str(int(time.time() * 1e6))}])
    return fs_err(404, "NOT_FOUND", "yok")


SID = ""


class H(BaseHTTPRequestHandler):
    server_version = "tvrelay/1"
    def log_message(self, *a): pass

    def ip(self): return self.client_address[0]

    def send(self, code, body=b"", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers(); self.wfile.write(body)

    def fs(self, method):
        if not rate(self.ip(), "f" + method[0], RATE_GET if method == "GET" else RATE_POST): return self.send(429, b"kop")
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2 * 1024 * 1024: return self.send(413, b"uly")
        try: body = json.loads(self.rfile.read(n) or b"{}") if n else None
        except Exception: return self.send(400, b"json")
        try: code, obj = fs_handle(self, method, urlparse(self.path).path, body)
        except Exception as e: code, obj = fs_err(500, "INTERNAL", str(e)[:200])
        self.send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path); parts = u.path.strip("/").split("/")
        if u.path in ("/", "/health"): return self.send(200, ("ok 1.42 fs " + SID).encode())   # 1.40: wersiýa; 1.41: «fs» — Firestore meňzeşi; 1.42: bazanyň kimligi
        if u.path.startswith("/v1/"): return self.fs("GET")
        if not rate(self.ip(), "g", RATE_GET): return self.send(429, b"kop")
        if len(parts) != 2 or parts[1] != "json" or not TOPIC.match(parts[0]): return self.send(404, b"yok")
        q = parse_qs(u.query); t = parts[0]; since = (q.get("since") or ["12h"])[0]; now = int(time.time())
        # 1.40.1: «wait=N» (≤30 sn) — täze habar ýok bolsa şonça garaşýar, gelen badyna berýär (gijikme ýok, sorag az)
        w = (q.get("wait") or ["0"])[0]; wait = min(30, int(w)) if w.isdigit() else 0
        end = time.time() + wait
        with cond:
            while True:
                prune(t, int(time.time())); L = list(topics.get(t, []))
                if since == "all": out = L
                elif re.fullmatch(r"r\d+", since): n = int(since[1:]); out = [m for m in L if int(m["id"][1:]) > n]
                else:
                    mm = re.fullmatch(r"(\d+)([smhd])", since)
                    sec = int(mm.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[mm.group(2)] if mm else 43200
                    out = [m for m in L if now - m["time"] <= sec]
                left = end - time.time()
                if out or left <= 0 or not re.fullmatch(r"r\d+", since): break
                cond.wait(left)
        body = "".join(json.dumps(dict(m, event="message", topic=t)) + "\n" for m in out).encode()
        self.send(200, body, "application/x-ndjson")

    def do_POST(self):
        u = urlparse(self.path); t = u.path.strip("/")
        if u.path.startswith("/v1/"): return self.fs("POST")
        if not TOPIC.match(t): return self.send(404, b"yok")
        if not rate(self.ip(), "p", RATE_POST): return self.send(429, b"kop")
        _, _, mx = kind_of(t)
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0 or n > mx: return self.send(413, b"uly")
        body = self.rfile.read(n).decode("utf-8", "ignore")
        if not body.startswith("v1."): return self.send(400, b"bad")
        now = int(time.time())
        with lock:
            if t not in topics and len(topics) > 200000: return self.send(507, b"doly")
            seq[0] += 1
            m = {"id": "r%d" % seq[0], "time": now, "message": body}
            topics.setdefault(t, []).append(m); prune(t, now); save(t)
            cond.notify_all()
        self.send(200, json.dumps(m).encode(), "application/json")


# ───────────── 1.42: öňdäki VPS — TCP geçiriji (garaşýan soraglar, uly suratlar — hemmesi şol durşuna) ─────────────
def fwd_pipe(a, b, st):
    try:
        while True:
            d = a.recv(65536)
            if not d: break
            b.sendall(d)
    except Exception: pass
    try: b.shutdown(socket.SHUT_WR)      # ýarym ýapmak: beýleki ugur jogaby gutarýança dowam edýär
    except Exception: pass
    with st[0]:
        st[1] -= 1; last = st[1] == 0
    if last:
        for x in (a, b):
            try: x.close()
            except Exception: pass


def fwd_conn(c, host, port):
    try:
        u = socket.create_connection((host, port), timeout=10)
    except Exception:
        try: c.close()
        except Exception: pass
        return
    for x in (c, u):
        x.settimeout(300)                # 5 minut hiç zat gelmese — ýapylýar (ölen birikmeler galmasyn)
        try: x.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        except Exception: pass
    st = [threading.Lock(), 2]
    threading.Thread(target=fwd_pipe, args=(c, u, st), daemon=True).start()
    fwd_pipe(u, c, st)


def fwd_main(up):
    host, _, port = up.replace("http://", "").strip("/").rpartition(":")
    host, port = (host or up), int(port or 8090)
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", PORT)); srv.listen(1024)
    print("tvrelay öňdäki VPS: %d → %s:%d" % (PORT, host, port), flush=True)
    while True:
        try: c, _ = srv.accept()
        except Exception: continue
        threading.Thread(target=fwd_conn, args=(c, host, port), daemon=True).start()


if __name__ == "__main__" and os.environ.get("UPSTREAM"):
    fwd_main(os.environ["UPSTREAM"])
elif __name__ == "__main__":
    SID = sid()
    load(); fs_load()
    threading.Thread(target=fs_pruner, daemon=True).start()
    print("tvrelay %d portda" % PORT, flush=True)
    ThreadingHTTPServer.request_queue_size = 1024   # köp telefon birden birikýär (garaşýan soraglar)
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H); srv.daemon_threads = True
    srv.serve_forever()
