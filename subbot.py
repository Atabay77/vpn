import os, sys, io, re, json, html, uuid, base64, asyncio, zipfile, shutil, fcntl, logging, datetime, time, socket, random, hashlib, warnings, unicodedata, threading
import urllib.request, urllib.parse, urllib.error
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from telegram import Update, InlineKeyboardButton as _IKB, InlineKeyboardMarkup as KB, InputMediaPhoto, InlineQueryResultCachedPhoto

def B(text, callback_data=None, style=None, **kw):
    """Buton. style: "success" (yeşil), "primary" (mavi), "danger" (kırmızı) — eski Telegram'da yok sayılır."""
    if style: kw["api_kwargs"] = {"style": style}
    return _IKB(text, callback_data=callback_data, **kw)
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, InlineQueryHandler, filters, ContextTypes
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("subbot")

DB_FILE = "/root/subbot.json"
ENV_FILE = "/root/env.txt"
SA_FILE = "/root/drive-sa.json"
STOP_FLAG = "/root/STOP.flag"
LOCK_FILE = "/root/subbot.lock"
VIP_LOG = "/root/vip.log"
AUDIT_LOG = "/root/audit.log"
GEO_FILE = "/root/geo_cache.json"
EXIT_FILE = "/root/exit_cache.json"   # telefonun ÖLÇTÜĞÜ gerçek çıkış ülkeleri (kod anahtarı -> ülke)
BACKUP_DIR = "/root/backups"
LINE = "──────────────"
PAGE = 6               # Kodlarım: sayfa başına kod
CHECK_EVERY = 120      # saniye: iki kontrol arası bekleme
NEW_IP_LIMIT = 1       # varsayılan: bundan FAZLA yeni IP görülürse kodlar yenilenir (Admin → 🚨 IP Eşiği ile değişir)
SUB_LIMIT = 10         # alt admin için varsayılan kod limiti (eklerken değiştirilebilir)
SUB_DAYS = 7
DEFAULT_DB = {"subs": {}, "template": [], "sources": [], "free_files": [], "sub_admins": {}, "seen_ips": [], "users": {}, "orders": {}, "channels": []}
AUTO_ANN = {0: "🌙 Спокойной ночи — мы на связи", 6: "☕ Доброе утро! Всё уже работает", 8: "Поддержка 24/7 — мы всегда готовы помочь."}   # saat (Aşkabat): duyuru
try:
    from zoneinfo import ZoneInfo
    TM_TZ = ZoneInfo("Asia/Ashgabat")
except Exception:
    TM_TZ = datetime.timezone(datetime.timedelta(hours=5))
STATE = {}
LIVE = {}
RUN = {"last_check": 0.0, "last_msg": "", "next": 0.0, "src": {}, "tm_ts": 0, "tm_line": "📱 Telefon testi: henüz yok", "tm_err": ""}


# ───────── ENV & ADMIN ─────────
def load_env():
    if not os.path.exists(ENV_FILE): return
    with open(ENV_FILE, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if "=" in ln and not ln.startswith("#"):
                k, v = ln.split("=", 1)
                v = v.strip().strip("\"'")
                if v: os.environ[k.strip()] = v

load_env()

def get_admins():
    ids = set()
    for k in ("ADMIN_IDS", "ADMIN_ID"):
        for x in re.split(r"[,\s]+", os.environ.get(k, "")):
            x = x.strip("\"'")
            if x.isdigit(): ids.add(int(x))
    return ids

ADMINS = get_admins()

def is_admin(uid):
    if uid in ADMINS: return True
    try:
        e = load_db().get("sub_admins", {}).get(str(uid))
        return bool(e) and float(e.get("expires", 0)) > time.time()
    except Exception: return False


# ───────── DB (locked, atomic) ─────────
@contextmanager
def db_lock():
    fp = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fp, fcntl.LOCK_EX)
        yield
    finally:
        try: fcntl.flock(fp, fcntl.LOCK_UN)
        finally: fp.close()

def load_db():
    if not os.path.exists(DB_FILE):
        return json.loads(json.dumps(DEFAULT_DB))
    try:
        with open(DB_FILE, encoding="utf-8") as f: db = json.load(f)
        if not isinstance(db, dict): raise ValueError("root is not an object")
    except Exception as e:
        bak = DB_FILE + ".broken-" + datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        shutil.copy(DB_FILE, bak)
        raise RuntimeError(f"subbot.json bozuk, kopyası: {bak} ({e})")
    for k, v in DEFAULT_DB.items():
        db.setdefault(k, json.loads(json.dumps(v)))
    return db

def save_db(db):
    tmp = DB_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(db, f, indent=4, ensure_ascii=False)
    os.replace(tmp, DB_FILE)

def mutate(fn):
    with db_lock():
        db = load_db()
        r = fn(db)
        save_db(db)
        return r


# ───────── logs ─────────
def vlog(msg):
    try:
        if os.path.exists(VIP_LOG) and os.path.getsize(VIP_LOG) > 500000:
            with open(VIP_LOG, encoding="utf-8", errors="ignore") as f: keep = f.readlines()[-1500:]
            with open(VIP_LOG, "w", encoding="utf-8") as f: f.writelines(keep)
        with open(VIP_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.datetime.now():%m-%d %H:%M:%S}] {msg}\n")
    except Exception: pass

def audit(uid, text):
    try:
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} [{uid}] {text}\n")
    except Exception: pass

def tail(path, n=25, maxb=20000):
    if not os.path.exists(path): return []
    with open(path, "rb") as f:
        f.seek(0, 2); size = f.tell(); f.seek(max(0, size - maxb))
        data = f.read().decode("utf-8", "ignore")
    return data.splitlines()[-n:]


# ───────── helpers ─────────
def is_exp(s):
    try: return bool(s.get("expires")) and float(s["expires"]) <= time.time()
    except Exception: return False

def left_txt(exp, ru=False):
    if not exp: return "∞"
    d = float(exp) - time.time()
    if d <= 0: return "истёк" if ru else "bitti"
    return f"{int(d // 86400)}{'д' if ru else 'g'} {int(d % 86400 // 3600)}{'ч' if ru else 's'}"

LANGC = {}   # uid -> "tr"/"tk"/"ru" (her ekranda veritabanı okunmasın)
def is_ru(uid):
    if uid not in LANGC:
        try: LANGC[uid] = load_db().get("users", {}).get(str(uid), {}).get("lang") or "tr"
        except Exception: return False
    return LANGC[uid] == "ru"
def L(uid, t, r): return r if is_ru(uid) else t   # kullanıcı/panel sahibi ekranları: Türkçe / Rusça

def name_of(s, kid): return s.get("title") or s.get("name") or kid      # abonelik başlığı (VPN uygulamasında)
def btn_name(s, kid): return s.get("name") or s.get("title") or kid     # buton adı (sadece botta)

def short(s, n=22):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"

def esc(s): return html.escape(str(s), quote=False)

def ago(ts):
    if not ts: return "hiç"
    d = int(time.time() - ts)
    if d < 90: return f"{d} sn önce"
    if d < 5400: return f"{d // 60} dk önce"
    if d < 172800: return f"{d // 3600} saat önce"
    return f"{d // 86400} gün önce"

def grid(buttons, cols=2):
    return [buttons[i:i + cols] for i in range(0, len(buttons), cols)]

def back(to="menu", label="◀️ Geri"):
    return KB([[B(label, callback_data=to)]])

def src_label(s):
    m = re.search(r"files/([\w-]{8,})", s) or re.search(r"[?&]id=([\w-]{8,})", s)
    if m: return "Drive …" + m.group(1)[:10]
    return re.sub(r"^https?://", "", s).split("/")[0][:24]


# ───────── DRIVE ─────────
def new_service():
    if not os.path.exists(SA_FILE): return None
    creds = service_account.Credentials.from_service_account_file(SA_FILE, scopes=["https://www.googleapis.com/auth/drive"])
    try:
        import httplib2, google_auth_httplib2
        # 30 sn zaman aşımı: takılan bir Drive bağlantısı botu sonsuza kadar bekletmesin
        http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=30))
        return build("drive", "v3", http=http, cache_discovery=False)
    except ImportError:
        return build("drive", "v3", credentials=creds, cache_discovery=False)

def sub_link(fid):
    return f"https://www.googleapis.com/drive/v3/files/{fid}?key={os.environ.get('API_KEY', '')}&alt=media"

FILE_FMT = 3   # abonelik dosyası biçimi değişince (ör. #providerid kaldırıldı) dosyalar bir kez yeniden yazılır

CODE_OFF_MSG = "Kodyňyz öçürildi, Admin bilen habarlaşyň"   # silinen / süresi dolan / durdurulan kodun Happ duyurusu

def rewrite_off_files():
    """Bir kez: daha önce silinmiş / süresi dolmuş kodların boş dosyalarına yeni duyuru metni (CODE_OFF_MSG)."""
    try:
        svc = new_service(); used = used_fids(load_db()); n, tok = 0, None
        while True:
            r = svc.files().list(q="name='Empty.txt' and trashed=false", fields="nextPageToken,files(id)", pageSize=200, pageToken=tok).execute()
            for f in r.get("files", []):
                if f["id"] not in used and sync_file(svc, f["id"], "Empty", CODE_OFF_MSG, [], exp=False): n += 1
            tok = r.get("nextPageToken")
            if not tok: break
        mutate(lambda d: d.__setitem__("off_msg", CODE_OFF_MSG))
        vlog(f"📝 Kapalı kod duyurusu güncellendi: {n} dosya")
    except Exception as e: log.warning("rewrite off files: %s", e)

def build_text(title, announce, servers):
    # Not: "#providerid" yazılmaz — Happ'ta aktif olmayan Provider ID varken "#hide-settings" çalışmıyor.
    lines = [f"#profile-title: {title}"]
    ann = " ".join(str(announce or "").split())  # çok satırlı duyuru Happ'i bozuyor
    if ann: lines.append(f"#announce: {ann}")
    lines += ["#hide-settings: true", "#profile-update-interval: 1"] + list(servers)
    return base64.b64encode("\n".join(lines).encode("utf-8"))

def expired_fids():
    try: return {s.get("file_id") for s in load_db()["subs"].values() if s.get("file_id") and is_exp(s)}
    except Exception: return set()

def sync_file(svc, fid, title, announce, servers, exp=None):
    if not svc or not fid: return False
    if (exp if exp is not None else fid in expired_fids()):
        announce, servers = CODE_OFF_MSG, []
    try:
        clean = re.sub(r"[^\w\s\-\.\(\)]", "", str(title)).strip() or "VIP"
        media = MediaIoBaseUpload(io.BytesIO(build_text(title, announce, servers)), mimetype="text/plain")
        svc.files().update(fileId=fid, body={"name": f"{clean}.txt"}, media_body=media).execute(num_retries=2)  # kopan SSL bağlantısında 2 kez tekrar dener
        return True
    except Exception as e:
        log.warning("Drive write failed %s: %s", fid, e)
        return False

def push_all(items, servers):
    """items: [(fid, title, announce)] -> (ok, failed_titles).
    Tek Drive bağlantısıyla sırayla yazar (paralel bağlantılar küçük VPS'i kilitliyordu)."""
    vlog(f"💾 Drive'a yazılıyor ({len(items)} dosya)...")
    t0 = time.time()
    svc = new_service()
    ok, bad = 0, []
    for fid, title, ann in items:
        if sync_file(svc, fid, title, ann, servers, exp=False): ok += 1
        else: bad.append(title); vlog(f"❌ Drive yazılamadı: {title}")
    vlog(f"   {time.time() - t0:.0f} sn sürdü")
    return ok, bad

def find_free_file(svc, used):
    try:
        r = svc.files().list(q="mimeType='text/plain' and trashed=false", fields="files(id,name)", pageSize=100).execute()
    except Exception as e:
        log.warning("Drive list failed: %s", e)
        return None
    for f in r.get("files", []):
        if f["id"] not in used: return f["id"]
    return None

POOL_FOLDER = "1rJmVKo7yLn4lPfBWnPaFUq_wn4xaMHQK"   # boş kod dosyaları havuzu (Drive klasörü, servis hesabı yazabilir)

def pool_files(svc):
    out, tok = [], None
    while True:
        r = svc.files().list(q=f"'{POOL_FOLDER}' in parents and trashed=false and mimeType='text/plain'",
                             fields="nextPageToken,files(id)", pageSize=200, pageToken=tok).execute(num_retries=2)
        out += [f["id"] for f in r.get("files", [])]
        tok = r.get("nextPageToken")
        if not tok: return out

def make_public(svc, fid):
    """Abonelik linki (API anahtarıyla) sadece herkese açık dosyada çalışır. Dönüş: dosya herkese açık mı."""
    try:
        svc.permissions().create(fileId=fid, body={"type": "anyone", "role": "reader"}).execute(num_retries=2)
        return True
    except Exception as e:
        err = str(e)[:150]
    try:   # paylaşma izni olmayabilir ama dosya zaten açık olabilir (eski kod dosyaları)
        ps = svc.permissions().list(fileId=fid, fields="permissions(type)").execute(num_retries=2).get("permissions", [])
        if any(p_.get("type") == "anyone" for p_ in ps): return True
    except Exception: pass
    vlog(f"⚠️ Dosya herkese açık yapılamadı ({fid[:10]}…): {err}")
    return False

def sa_limit(db, uid):
    try: return int(db.get("sub_admins", {}).get(str(uid), {}).get("limit", SUB_LIMIT))
    except Exception: return SUB_LIMIT

def owned(db, uid): return sum(1 for v in db["subs"].values() if v.get("owner_id") == uid and not v.get("pub"))   # ücretsiz/satın alınan kodlar panel limitine sayılmaz

def create_vip(name, owner=None, days=None, check_limit=True, extra=None):
    svc = new_service()
    if not svc: return None, "drive-sa.json bulunamadı"
    with db_lock():
        db = load_db()
        if check_limit and owner is not None and owner not in ADMINS and owned(db, owner) >= sa_limit(db, owner):
            return None, f"Limit doldu ({sa_limit(db, owner)} kod). Yer açmak için birini sil."
        used = used_fids(db)
        fid, from_free = None, False
        for f in db["free_files"]:
            if f not in used: fid, from_free = f, True; break
        if not fid:
            try: fid = next((f for f in pool_files(svc) if f not in used), None)
            except Exception as e: vlog(f"⚠️ Kod havuzu okunamadı: {str(e)[:120]}")
        if not fid: fid = find_free_file(svc, used)
        if not fid: return None, "Boş Drive dosyası yok!"
        if not make_public(svc, fid):   # herkese açık değilse VPN uygulaması 404 alır: bozuk link verme
            return None, "Drive dosyası herkese açık yapılamadı (Loglar'a bak)"
        if not sync_file(svc, fid, name, db.get("g_announce", ""), db["template"], exp=False):
            return None, "Drive'a yazılamadı (loglara bak)"
        if from_free: db["free_files"].remove(fid)
        kid = "vip_" + uuid.uuid4().hex[:8]
        db["subs"][kid] = {"name": name, "title": name, "file_id": fid, "announce": "", "owner_id": owner}
        if days: db["subs"][kid]["expires"] = time.time() + float(days) * 86400   # kesirli gün: deneme kodu 3 saat
        if extra: db["subs"][kid].update(extra)
        save_db(db)
        return (kid, fid), ""

def delete_vip(kid):
    svc = new_service()
    with db_lock():
        db = load_db()
        s = db["subs"].pop(kid, None)
        if not s: return False
        fid = s.get("file_id")
        if fid:
            if fid not in db["free_files"]: db["free_files"].append(fid)
            sync_file(svc, fid, "Empty", CODE_OFF_MSG, [], exp=False)  # eski link sunucu vermesin
        save_db(db)
        return True


# ───────── KOD ÇEKME ─────────
PROTOS = ("vless://", "vmess://", "trojan://", "ss://", "hysteria://", "hysteria2://", "hy2://", "tuic://")

DRIVE_ID_RE = re.compile(r"(?:googleapis\.com/drive/v3/files/|drive\.google\.com/(?:uc\?(?:export=download&)?id=|file/d/))([-\w]{20,})")

def http_reason(e):
    """HTTP hatasının kısa sebebi (Google'ın JSON hatasındaki reason/message). Anahtar gizlenir."""
    try: body = e.read().decode("utf-8", "ignore")
    except Exception: return ""
    try:
        j = json.loads(body).get("error", {})
        why = (j.get("errors") or [{}])[0].get("reason") or j.get("status") or ""
        txt = f"{why} {j.get('message') or ''}"
    except Exception:   # JSON değil (ör. Google'ın "olağandışı trafik" sayfası): başlığı / ilk kelimeler
        m = re.search(r"<title>(.*?)</title>", body, re.I | re.S)
        txt = m.group(1) if m else re.sub(r"<[^>]+>", " ", body)
    return re.sub(r"key=[^&\s\"]+", "key=***", " ".join(txt.split()))[:120]

def fetch_codes(url):
    req = urllib.request.Request(url, headers={"User-Agent": "v2rayN/6.42"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            content = r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        why = http_reason(e)
        m = DRIVE_ID_RE.search(url)
        if e.code not in (403, 429) or not m: raise RuntimeError(f"HTTP {e.code} {why}".strip())
        # Google API anahtarıyla indirme reddedildi (kota / IP sınırı): dosyayı servis hesabıyla indir
        try: content = new_service().files().get_media(fileId=m.group(1)).execute(num_retries=1).decode("utf-8", "ignore")
        except Exception as e2: raise RuntimeError(f"HTTP {e.code} {why} · servis hesabıyla da olmadı: {str(e2)[:60]}".strip())
        RUN["src_via_sa"] = f"HTTP {e.code} {why}".strip()
    lines = content.splitlines()
    flat = "".join(content.split())
    for alt in (None, b"-_"):
        try:
            dec = base64.b64decode((flat + "=" * (-len(flat) % 4)).encode("ascii"), altchars=alt).decode("utf-8", "ignore")
            lines += dec.splitlines()
        except Exception: pass
    out = []
    for l in lines:
        l = l.strip()
        if l.lower().startswith(PROTOS) and l not in out: out.append(l)
    return out

def sub_limits(url):
    """Abonelik sınırları (panelin 'subscription-userinfo' başlığı): {'total': bayt, 'expire': unix}. Bilinmiyorsa {}."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "v2rayN/6.42"})
        with urllib.request.urlopen(req, timeout=15) as r:
            h = r.headers.get("subscription-userinfo") or r.headers.get("Subscription-Userinfo") or ""
    except Exception: return {}
    out = {}
    for part in h.split(";"):
        k, _, v = part.strip().partition("=")
        try: out[k.strip().lower()] = int(float(v.strip()))
        except Exception: pass
    return out

def b64d(s):
    s = s.strip()
    return base64.urlsafe_b64decode(s.replace("+", "-").replace("/", "_") + "=" * (-len(s) % 4)).decode("utf-8", "ignore")

def code_hostport(link):
    try:
        raw = link.split("#", 1)[0].strip()
        proto, body = raw.split("://", 1)
        proto = proto.lower()
        if proto == "vmess":
            d = json.loads(b64d(body))
            return str(d["add"]).strip("[]"), int(d["port"])
        if proto == "ss" and "@" not in body:
            body = b64d(body.split("?")[0].split("/")[0])
        hp = re.split(r"[/?]", body.rsplit("@", 1)[1] if "@" in body else body)[0]
        h, port = hp.rsplit(":", 1)
        return (h.strip("[]") or None), int(port)
    except Exception:
        return None, None

def code_host(link): return code_hostport(link)[0]

UDP_PROTOS = ("hysteria", "hysteria2", "hy2", "tuic")

def tcp_alive(h, p):
    for _ in range(2):
        try:
            socket.create_connection((h, p), 3).close()
            return True
        except Exception: pass
    return False

def dead_filter(codes):
    """VPS'ten hızlı ölü testi: TCP protokollerinde port açık mı. Tamamen kapalı sunucular atılır.
    UDP (hysteria) bu yolla test edilemez, olduğu gibi kalır. Türkmenistan'daki engeli göremez."""
    tcp = [c for c in codes if c.split("://", 1)[0].lower() not in UDP_PROTOS]
    hps = {c: code_hostport(c) for c in tcp}
    uniq = sorted({hp for hp in hps.values() if hp[0] and hp[1]})
    t0 = time.time()
    with ThreadPoolExecutor(32) as ex:
        alive = dict(zip(uniq, ex.map(lambda hp: tcp_alive(*hp), uniq)))
    if uniq and not any(alive.values()):
        vlog("⚠️ Ölü test: hiçbir sunucu cevap vermedi (VPS ağı sorunu olabilir), test atlandı")
        return codes
    dead = [c for c in tcp if not alive.get(hps[c], False)]
    vlog(f"🧪 Ölü test ({time.time() - t0:.0f} sn): {len(tcp) - len(dead)}/{len(tcp)} TCP sunucu açık, "
         f"{len(dead)} kapalı atıldı · {len(codes) - len(tcp)} UDP test edilmedi")
    return [c for c in codes if c not in set(dead)]

def code_key(link):
    raw = link.split("#", 1)[0].strip()
    if raw.lower().startswith("vmess://"):
        try:
            d = json.loads(b64d(raw[8:])); d.pop("ps", None)
            return "vmess://" + json.dumps(d, sort_keys=True)
        except Exception: pass
    return raw

def set_name(link, name):
    if link.lower().startswith("vmess://"):
        try:
            d = json.loads(b64d(link[8:].split("#", 1)[0])); d["ps"] = name
            return "vmess://" + base64.b64encode(json.dumps(d, ensure_ascii=False).encode("utf-8")).decode()
        except Exception: pass
    return link.split("#", 1)[0] + "#" + name


# ───────── ÜLKE & İSİM ─────────
COUNTRIES = {
    "ru": ("🇷🇺", "Russia", ["🎮 PUBG Arena", "🍗 Chicken Dinner", "🪂 Pochinki Drop", "🎯 Headshot Pro", "🔫 Erangel Sniper", "🏜️ Miramar Rush",
                            "🪖 Level 3 Helmet", "🚗 Dacia Drive", "💥 Clutch King", "🕹️ Low Ping Gaming", "🏆 Esports Hub", "🗺️ Sanhok Zone"]),   # Rusya: oyun / PUBG isimleri
    "de": ("🇩🇪", "Germany", ["🏎️ Autobahn Express", "⚡ Cyber Autobahn", "🛡️ Berlin Aegis", "🏰 Bavaria Citadel", "🌲 Black Forest", "⚙️ Precision Core",
                             "🚄 Frankfurt Rail", "🦅 Rhine Eagle", "🔩 Munich Forge", "🌉 Hamburg Harbor", "💠 Cologne Matrix", "🏁 Nürburg Ring"]),
    "nl": ("🇳🇱", "Netherlands", ["🚲 Amsterdam Pulse", "🌷 Tulip Gateway", "🌊 Dutch Harbor", "⚡ Rotterdam Core", "🧡 Orange Express", "🌬️ Windmill Flow",
                                 "🛶 Canal Runner", "🧀 Gouda Vault", "🏛️ Hague Shield", "⚓ North Sea Link", "💎 Utrecht Prism", "🌀 Delta Stream"]),
    "fr": ("🇫🇷", "France", ["🗼 Eiffel Relay", "🍷 Bordeaux Flow", "🎨 Louvre Matrix", "🦁 Lyon Fortress", "⚡ Seine Pulse", "🏰 Versailles Guard",
                            "🌅 Riviera Wave", "🥐 Paris Express", "🏔️ Alps Summit", "⚜️ Royal Lily", "🛡️ Normandy Shield", "🚀 Marseille Jet"]),
    "gb": ("🇬🇧", "United Kingdom", ["👑 Royal Edge", "🕰️ Big Ben Tower", "☕ London Fog Link", "🛡️ Windsor Shield", "🚀 Oxford Stream", "🏰 Tower Bridge",
                                    "🌧️ Thames Flow", "🦁 Lionheart Core", "⚔️ Camelot Blade", "🎡 London Eye", "🏴 Highland Storm", "🚇 Tube Express"]),
    "fi": ("🇫🇮", "Finland", ["🌌 Aurora Borealis", "🦌 Lapland Runner", "❄️ Nordic Frost", "🌲 Taiga Pulse", "🧊 Helsinki Ice", "🌊 Baltic Wave",
                             "🦉 Arctic Owl", "⚡ Saimaa Spark", "🏔️ Polar Peak", "🔥 Sauna Core", "🛷 Snow Sled", "💠 Suomi Crystal"]),
    "se": ("🇸🇪", "Sweden", ["⚔️ Viking Shield", "🛡️ Stockholm Aegis", "❄️ Nordic Storm", "🌊 Fjord Stream", "👑 Royal Vasa", "⚡ Thor Hammer",
                            "🦌 Elk Runner", "🌲 Pine Pulse", "🚢 Longship Link", "🌌 Midnight Sun", "🔷 Gothenburg Core", "🏔️ Kebne Summit"]),
    "pl": ("🇵🇱", "Poland", ["🗡️ Hussar Shield", "🏰 Baltic Stream", "🦅 White Eagle", "⚡ Warsaw Pulse", "🏛️ Krakow Vault", "🌊 Vistula Flow",
                            "🛡️ Wawel Guard", "🚄 Gdansk Express", "🌲 Tatra Peak", "🔥 Silesia Forge", "💠 Amber Core", "⚔️ Grunwald Blade"]),
    "ch": ("🇨🇭", "Switzerland", ["🏔️ Alpine Vault", "⌚ Swiss Precision", "🏦 Zurich Core", "❄️ Matterhorn Peak", "🛡️ Geneva Shield", "🧀 Emmental Link",
                                 "🚠 Glacier Express", "💎 Lucerne Crystal", "🌊 Lake Pulse", "🔐 Bern Bastion", "⚡ Jungfrau Spark", "🦅 Alpine Eagle"]),
    "tr": ("🇹🇷", "Türkiye", ["🎬 VIP Cinema", "⚡ Bosphorus Pulse", "🦅 Anatolian Falcon", "🔥 Ottoman Guard", "🌊 Aegean Wave", "🦁 Anatolian Lion",
                             "🕌 Galata Tower", "🏹 Seljuk Arrow", "🌙 Crescent Link", "⛵ Antalya Breeze", "🏰 Topkapi Vault", "🎈 Cappadocia Sky"]),
    "us": ("🇺🇸", "United States", ["⚡ Manhattan Pulse", "🚀 Apollo Route", "🗽 Liberty Matrix", "🦅 Eagle Shield", "🌴 Miami Cyber", "🌉 Golden Gate",
                                   "🎰 Vegas Jackpot", "🤠 Texas Ranger", "🛰️ NASA Orbit", "🏙️ Chicago Core", "🌵 Arizona Storm", "💻 Silicon Valley"]),
    "ca": ("🇨🇦", "Canada", ["🍁 Maple Edge", "❄️ Toronto Frost", "🚀 Arctic Link", "🛡️ Ottawa Shield", "⚡ Zenith Edge", "🐻 Grizzly Core",
                            "🏔️ Rocky Summit", "🌊 Niagara Flow", "🦫 Beaver Vault", "🏒 Hockey Express", "🌲 Yukon Pulse", "🌌 Northern Lights"]),
    "jp": ("🇯🇵", "Japan", ["🗻 Fuji Summit", "🌸 Sakura Stream", "⚡ Tokyo Pulse", "🐉 Dragon Core", "🏯 Osaka Castle", "🚄 Shinkansen",
                           "⛩️ Kyoto Gate", "🎴 Samurai Blade", "🌊 Kanagawa Wave", "🍣 Ginza Express", "🌙 Ninja Shadow", "🎌 Rising Sun"]),
    "sg": ("🇸🇬", "Singapore", ["🦁 Merlion Core", "🌃 Marina Bay", "⚡ Lion City Pulse", "🌴 Sentosa Breeze", "🚀 Changi Jet", "💎 Orchard Prism",
                               "🌉 Helix Bridge", "🛡️ Raffles Shield", "🌺 Orchid Link", "🏙️ Skyline Matrix", "🌊 Straits Flow", "🔷 Jurong Grid"]),
}

def flag_of(cc): return "".join(chr(0x1F1E6 + ord(ch) - 97) for ch in cc)

# Bayrak tekrar etmesin diye geniş havuz (Rusya hariç her ülke bir güncellemede en fazla 1 kez kullanılır)
MORE_COUNTRIES = {
    "at": ("Austria", ["🎻 Vienna Waltz", "🏔️ Tyrol Summit", "🏰 Hofburg Vault", "☕ Melange Link", "⛷️ Alpine Glide", "🎼 Mozart Stream", "🦅 Danube Eagle", "❄️ Innsbruck Frost", "🛡️ Salzburg Shield", "💎 Graz Crystal"]),
    "be": ("Belgium", ["🍫 Brussels Praline", "🏛️ Atomium Core", "🍺 Abbey Link", "⚔️ Flanders Guard", "🌉 Antwerp Bridge", "💎 Diamond Hub", "🚲 Ghent Pulse", "🏰 Bruges Citadel", "⚡ Benelux Spark", "🦁 Leuven Lion"]),
    "it": ("Italy", ["🏛️ Colosseum Core", "🍕 Napoli Express", "🛶 Venice Gondola", "🏎️ Monza Racer", "🗼 Pisa Tower", "🌋 Etna Storm", "⚔️ Roman Legion", "🍷 Tuscany Flow", "🎭 Milano Mask", "🌊 Amalfi Wave"]),
    "es": ("Spain", ["🐂 Madrid Torero", "💃 Flamenco Pulse", "🏰 Alhambra Vault", "⚽ Camp Nou Link", "🌞 Costa Sol", "⛪ Sagrada Core", "🌊 Ibiza Wave", "🗡️ Toledo Blade", "🍊 Valencia Express", "🦅 Iberian Eagle"]),
    "pt": ("Portugal", ["⚓ Lisbon Harbor", "🌊 Nazaré Giant", "🏰 Porto Fortress", "🚋 Tram 28", "🧭 Navigator Link", "🍷 Douro Flow", "☀️ Algarve Sun", "🐓 Barcelos Spirit", "🛡️ Belém Tower", "💠 Azulejo Grid"]),
    "no": ("Norway", ["🌌 Oslo Aurora", "⛰️ Fjord Edge", "🛶 Viking Raider", "❄️ Svalbard Ice", "🐋 Lofoten Whale", "⚡ Odin Spark", "🏔️ Troll Peak", "🌊 Bergen Tide", "🦌 Reindeer Run", "🛡️ Nordic Aegis"]),
    "dk": ("Denmark", ["🧜 Little Mermaid", "🏰 Kronborg Keep", "🚲 Copenhagen Ride", "⚔️ Dane Axe", "🧱 Lego Block", "🌊 Baltic Breeze", "👑 Royal Dane", "⚡ Viking Pulse", "🌉 Øresund Bridge", "🛡️ Jutland Shield"]),
    "ie": ("Ireland", ["☘️ Shamrock Link", "🏰 Dublin Castle", "🌊 Atlantic Edge", "🎻 Celtic Tune", "🍀 Lucky Clover", "⛰️ Cliffs of Moher", "🐑 Galway Green", "⚡ Emerald Pulse", "🛡️ Celtic Shield", "🌈 Leprechaun Gold"]),
    "cz": ("Czechia", ["🏰 Prague Castle", "🌉 Charles Bridge", "🍺 Pilsner Core", "🕰️ Astro Clock", "⚔️ Bohemian Blade", "💎 Bohemia Crystal", "🌲 Šumava Pulse", "⚡ Brno Spark", "🦁 Czech Lion", "🎻 Vltava Flow"]),
    "hu": ("Hungary", ["🏛️ Budapest Parliament", "🌉 Chain Bridge", "♨️ Thermal Bath", "🐎 Hussar Ride", "🌶️ Paprika Pulse", "🏰 Buda Castle", "🌊 Danube Pearl", "⚔️ Magyar Saber", "🎻 Rhapsody Link", "🦅 Turul Eagle"]),
    "ro": ("Romania", ["🧛 Dracula Castle", "⛰️ Carpathian Peak", "🌊 Black Sea Wave", "🏰 Bran Fortress", "🦅 Danube Delta", "⚡ Bucharest Pulse", "🌲 Transylvania Mist", "🛡️ Dacian Shield", "🎻 Doina Stream", "💎 Salt Mine Crystal"]),
    "bg": ("Bulgaria", ["🌹 Rose Valley", "⛰️ Rila Summit", "🌊 Varna Coast", "🏰 Tsarevets Keep", "⚡ Sofia Pulse", "🦁 Balkan Lion", "🛡️ Thracian Shield", "🍯 Golden Sands", "🎻 Kaval Flow", "🌲 Pirin Pine"]),
    "gr": ("Greece", ["🏛️ Acropolis Core", "⚡ Zeus Bolt", "🌊 Aegean Blue", "🏺 Olympus Vault", "🦉 Athena Owl", "⛵ Santorini Sail", "🛡️ Spartan Shield", "🔱 Poseidon Trident", "🏃 Marathon Run", "🌅 Mykonos Sunset"]),
    "ee": ("Estonia", ["🏰 Tallinn Tower", "💻 E-Nation Grid", "🌲 Baltic Forest", "❄️ Saaremaa Frost", "🌊 Gulf Stream", "⚡ Tartu Spark", "🛡️ Toompea Guard", "🦌 Lahemaa Run", "🌌 Northern Glow", "🔷 Tallinn Core"]),
    "lv": ("Latvia", ["🏰 Riga Spire", "🌊 Jurmala Shore", "🌲 Gauja Forest", "⚡ Daugava Pulse", "🛡️ Baltic Guard", "🎻 Song Festival", "❄️ Kurzeme Frost", "💎 Amber Riga", "🦅 Latgale Eagle", "🌉 Vanšu Bridge"]),
    "lt": ("Lithuania", ["🏰 Trakai Castle", "🌊 Curonian Spit", "💎 Amber Coast", "⚔️ Vytis Knight", "⚡ Vilnius Pulse", "🌲 Aukštaitija Pine", "🛡️ Gediminas Tower", "🏀 Hoop Arena", "🦅 Neris Eagle", "🌙 Užupis Moon"]),
    "is": ("Iceland", ["🌋 Volcano Core", "🧊 Glacier Link", "🌌 Reykjavik Aurora", "♨️ Geyser Burst", "🐋 North Atlantic", "⚡ Thor Spark", "🛶 Saga Viking", "🏔️ Vatnajökull", "🌊 Blue Lagoon", "🐦 Puffin Flight"]),
    "lu": ("Luxembourg", ["🏰 Vianden Castle", "🏦 Grand Duchy Vault", "🌉 Adolphe Bridge", "⚡ Kirchberg Pulse", "🛡️ Bock Casemates", "🌲 Mullerthal Trail", "👑 Grand Duke", "💠 Euro Core", "🍷 Moselle Flow", "🦁 Red Lion"]),
    "au": ("Australia", ["🦘 Kangaroo Jump", "🏄 Bondi Wave", "🐨 Koala Core", "🌅 Sydney Opera", "🪃 Boomerang Link", "🏜️ Outback Storm", "🐊 Croc Shield", "🐠 Great Reef", "⚡ Melbourne Pulse", "🦅 Wedge Eagle"]),
    "nz": ("New Zealand", ["🥝 Kiwi Link", "⛰️ Middle Earth", "🐑 Canterbury Plains", "🌋 Taupo Fire", "🏉 Haka Force", "🌊 Tasman Wave", "🦜 Kea Flight", "🌲 Fiordland", "⚡ Auckland Pulse", "🛶 Waka Voyager"]),
    "kr": ("South Korea", ["🎤 K-Pop Stage", "🏯 Gyeongbok Palace", "⚡ Seoul Pulse", "🌸 Jeju Blossom", "🥋 Taekwondo Core", "🌊 Busan Harbor", "🎮 Esports Arena", "🐯 Tiger Shield", "🏔️ Seorak Peak", "🚄 KTX Express"]),
    "hk": ("Hong Kong", ["🌃 Victoria Harbour", "🏙️ Kowloon Neon", "⛴️ Star Ferry", "🐉 Dragon Gate", "⚡ Central Pulse", "🌊 Repulse Bay", "🏔️ Peak Tower", "🥟 Dim Sum Link", "🛡️ Harbour Shield", "🎆 Neon Lights"]),
    "in": ("India", ["🐅 Bengal Tiger", "🕌 Taj Mahal", "🌶️ Masala Pulse", "🐘 Elephant Core", "🏏 Cricket Arena", "🌊 Goa Wave", "⛰️ Himalaya Peak", "🦚 Peacock Link", "⚡ Mumbai Express", "🛕 Lotus Temple"]),
    "ae": ("UAE", ["🏙️ Burj Khalifa", "🐪 Desert Falcon", "🌴 Palm Jumeirah", "💎 Dubai Gold", "⚡ Abu Dhabi Pulse", "🏎️ Yas Racer", "🌅 Arabian Sunset", "🛡️ Emirates Shield", "🕌 Grand Mosque", "🚀 Hope Probe"]),
    "br": ("Brazil", ["⚽ Samba Striker", "🌴 Copacabana", "🦜 Amazon Parrot", "🎭 Rio Carnival", "🗿 Cristo Core", "🌊 Iguazu Falls", "☕ Café Express", "🐆 Jaguar Run", "⚡ São Paulo Pulse", "🌞 Bahia Sun"]),
    "ar": ("Argentina", ["⚽ Tango Striker", "🐎 Gaucho Ride", "🏔️ Aconcagua Peak", "🧊 Patagonia Ice", "🥩 Asado Core", "💃 Tango Pulse", "🌊 Iguazú Mist", "🦙 Andes Link", "⚡ Buenos Aires", "☀️ Sol de Mayo"]),
    "mx": ("Mexico", ["🌮 Taco Express", "🗿 Aztec Core", "🌵 Cactus Storm", "🎺 Mariachi Link", "🏛️ Maya Pyramid", "🌊 Cancún Wave", "💀 Día Spirit", "🦅 Golden Eagle", "⚡ CDMX Pulse", "🌶️ Jalapeño Fire"]),
    "cl": ("Chile", ["🗿 Moai Guard", "🏔️ Andes Summit", "🍷 Valle Wine", "🌌 Atacama Stars", "🌊 Pacific Edge", "🧊 Torres Ice", "🦅 Condor Flight", "⚡ Santiago Pulse", "🌋 Villarrica Fire", "🛶 Chiloé Voyager"]),
    "za": ("South Africa", ["🦁 Safari King", "🏔️ Table Mountain", "🐘 Kruger Core", "💎 Kimberley Gem", "🌊 Cape Wave", "🦓 Zebra Link", "⚡ Joburg Pulse", "🌅 Garden Route", "🛡️ Zulu Shield", "🐧 Boulders Beach"]),
    "eg": ("Egypt", ["🔺 Pyramid Core", "🐫 Sahara Caravan", "🌊 Nile Flow", "👑 Pharaoh Gate", "🦅 Horus Eye", "🏛️ Luxor Temple", "⚡ Cairo Pulse", "🐈 Bastet Guard", "🌅 Red Sea Sun", "🗝️ Ankh Key"]),
    "kz": ("Kazakhstan", ["🦅 Steppe Eagle", "🏔️ Tian Shan", "🐎 Nomad Rider", "🚀 Baikonur Launch", "🍎 Almaty Apple", "🌌 Astana Lights", "🌊 Caspian Shore", "⚡ Steppe Pulse", "🛡️ Golden Warrior", "❄️ Shymbulak Snow"]),
    "ge": ("Georgia", ["🍷 Kakheti Wine", "🏔️ Kazbegi Peak", "🏰 Tbilisi Fortress", "⚔️ Tamar Shield", "🌊 Batumi Wave", "⛪ Svaneti Tower", "⚡ Rustaveli Pulse", "🦅 Caucasus Eagle", "🥟 Khinkali Core", "🌉 Peace Bridge"]),
    "am": ("Armenia", ["⛰️ Ararat Summit", "⛪ Etchmiadzin", "🍑 Apricot Link", "🌊 Sevan Lake", "🏰 Garni Temple", "⚡ Yerevan Pulse", "🦅 Highland Eagle", "🎻 Duduk Stream", "🛡️ Erebuni Guard", "🌌 Karahunj Stars"]),
    "az": ("Azerbaijan", ["🔥 Flame Towers", "🌊 Caspian Pearl", "🏰 Maiden Tower", "⚡ Baku Pulse", "🎻 Mugham Stream", "🛡️ Shirvan Shield", "🏔️ Shahdag Peak", "🌋 Mud Volcano", "🦅 Gabala Eagle", "💎 Black Gold"]),
    "id": ("Indonesia", ["🌋 Bromo Fire", "🏝️ Bali Island", "🐉 Komodo Dragon", "🌊 Java Wave", "🛕 Borobudur", "🌴 Lombok Breeze", "⚡ Jakarta Pulse", "🦅 Garuda Wing", "☕ Sumatra Brew", "🐒 Ubud Forest"]),
    "my": ("Malaysia", ["🏙️ Petronas Twin", "🌴 Langkawi Isle", "🐅 Malayan Tiger", "🌊 Penang Wave", "⚡ KL Pulse", "🦅 Kinabalu Eagle", "🌺 Hibiscus Link", "🍜 Laksa Express", "🛡️ Melaka Fort", "🌧️ Rainforest Core"]),
    "th": ("Thailand", ["🐘 Siam Elephant", "🛕 Golden Temple", "🏝️ Phuket Isle", "🥊 Muay Thai", "🌶️ Tom Yum Pulse", "🌊 Krabi Wave", "⚡ Bangkok Pulse", "🦅 Garuda Thai", "🛶 Floating Market", "🌺 Bangkok Orchid"]),
    "vn": ("Vietnam", ["🐉 Ha Long Dragon", "🏮 Hoi An Lantern", "🍜 Pho Express", "🌾 Rice Terrace", "🛵 Saigon Rider", "🌊 Mekong Flow", "⚡ Hanoi Pulse", "🏔️ Fansipan Peak", "🛡️ Imperial Hue", "🎋 Bamboo Core"]),
    "ph": ("Philippines", ["🏝️ Palawan Isle", "🌋 Mayon Fire", "🦅 Mindanao Eagle", "🌊 Boracay Wave", "⚡ Manila Pulse", "🥭 Mango Express", "🌅 Sunset Bay", "🐠 Tubbataha Reef", "🛶 Banca Voyager", "🍫 Chocolate Hills"]),
    "rs": ("Serbia", ["🏰 Belgrade Fortress", "🌊 Danube Gate", "🎺 Guča Trumpet", "⚡ Novi Sad Pulse", "🛡️ Kalemegdan", "🏔️ Zlatibor Peak", "🦅 Double Eagle", "🎻 Kolo Stream", "🌲 Tara Forest", "⛪ Sava Temple"]),
    "hr": ("Croatia", ["🌊 Adriatic Wave", "🏰 Dubrovnik Wall", "⛵ Split Sail", "💧 Plitvice Falls", "⚡ Zagreb Pulse", "🏝️ Hvar Isle", "🛡️ Checkered Shield", "🦁 Diocletian", "🌅 Zadar Sunset", "🐟 Dalmatian Coast"]),
    "sk": ("Slovakia", ["🏰 Bratislava Castle", "⛰️ Tatra Summit", "🌊 Slovak Danube", "⚡ Košice Pulse", "🛡️ Devín Guard", "🌲 Paradise Forest", "🎻 Fujara Flow", "❄️ Jasná Snow", "🦅 Carpathian Eagle", "💎 Spiš Crystal"]),
    "si": ("Slovenia", ["🏞️ Lake Bled", "🐉 Ljubljana Dragon", "⛰️ Triglav Peak", "🕳️ Postojna Cave", "🌊 Piran Wave", "⚡ Alpine Pulse", "🍷 Vipava Wine", "🐎 Lipizzan Ride", "🛡️ Predjama Castle", "🌲 Julian Forest"]),
    "ma": ("Morocco", ["🕌 Hassan Tower", "🐫 Sahara Dune", "🎨 Chefchaouen Blue", "🌴 Marrakech Palm", "⚡ Casablanca Pulse", "🏔️ Atlas Summit", "🌊 Essaouira Wind", "🛡️ Kasbah Shield", "🍵 Mint Tea Link", "🦁 Atlas Lion"]),
    "qa": ("Qatar", ["🏙️ Doha Skyline", "🐪 Desert Pearl", "⚽ Lusail Arena", "🌊 Corniche Wave", "💎 Pearl Qatar", "⚡ Doha Pulse", "🦅 Falcon Souq", "🌅 Gulf Sunset", "🛡️ Al Zubarah", "🕌 Katara Core"]),
}
for _cc, (_n, _l) in MORE_COUNTRIES.items(): COUNTRIES[_cc] = (flag_of(_cc), _n, _l)

def geo_lookup(hosts):
    try:
        with open(GEO_FILE, encoding="utf-8") as f: cache = json.load(f)
    except Exception: cache = {}
    todo = [h for h in set(hosts) if h not in cache]

    def one(h):
        try: ip = socket.gethostbyname(h)
        except Exception: ip = h
        for url in (f"https://ipwho.is/{ip}?fields=success,country_code,country",
                    f"http://ip-api.com/json/{ip}?fields=status,countryCode,country"):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=6) as r: j = json.loads(r.read().decode())
                cc = j.get("country_code") or j.get("countryCode")
                if cc: return h, [cc.lower(), j.get("country", "")]
            except Exception: pass
        return h, None

    if todo:
        with ThreadPoolExecutor(8) as ex:
            for h, v in ex.map(one, todo):
                if v: cache[h] = v
        try:
            with open(GEO_FILE, "w", encoding="utf-8") as f: json.dump(cache, f)
        except Exception: pass
    return {h: cache[h][0] for h in hosts if h in cache}

def orig_name(link):
    if link.lower().startswith("vmess://"):
        try: return str(json.loads(b64d(link[8:].split("#", 1)[0])).get("ps", ""))
        except Exception: return ""
    return urllib.parse.unquote(link.split("#", 1)[1]) if "#" in link else ""

RU_WORDS = ("russia", "россия", "moscow", "москва", "saint petersburg", "санкт")

def exit_country(link, geo):
    """Çıkış ülkesi. Sunucular aracı (relay) olduğu için giriş IP'si yanıltır;
    asıl çıkış ülkesi kaynağın orijinal ismindeki bayraktadır. Bayrak yoksa ülke adı, o da yoksa IP konumu."""
    nm = unicodedata.normalize("NFKC", orig_name(link))
    m = re.search(r"[\U0001F1E6-\U0001F1FF]{2}", nm)
    if m: return "".join(chr(ord(ch) - 0x1F1E6 + 97) for ch in m.group(0)), "isim"
    low = nm.lower()
    if any(w in low for w in RU_WORDS): return "ru", "isim"
    return geo.get(code_host(link)), "ip"

def eff_ann(db, s):
    """Kodun duyurusu: koda özel duyuru varsa o, yoksa genel duyuru (toplu / otomatik)."""
    return s.get("announce") or db.get("g_announce", "")

REAL_SEP, RAND_SEP = " · ", " | "   # gerçek ülke bayrağı "·", rastgele bayrak "|" (sadece kurucu bilir)
PING_MAX = 1500                        # varsayılan ping sınırı (ms, telefon ölçümü); Admin → ⏱ Ping Sınırı ile değişir
SLOW_OUT = 1.25                        # listedeki kod ancak sınırın %25 üstüne çıkınca atılır (gidip gelmesin)
TM_ADD_EVERY = 3600                    # yeni çalışan kodlar listeye en çok saatte bir eklenir
PING_KEEP = 3                          # sınırın altında bundan az kod kalırsa en hızlı bu kadar kod tutulur
REAL_MIN = 6                           # bu kadar farklı gerçek ülke varsa sadece onlar kalır

def _emoji(n): return n.split(" ", 1)[0]

def _pick_name(cc, used_names, used_emojis):
    """Aynı isim ve aynı emoji bir listede iki kez kullanılmaz (mümkün olduğu sürece)."""
    names = COUNTRIES[cc][2]
    for ok in (lambda n: n not in used_names and _emoji(n) not in used_emojis, lambda n: n not in used_names, lambda n: True):
        free = [n for n in names if ok(n)]
        if free:
            n = random.choice(free); used_names.add(n); used_emojis.add(_emoji(n))
            return n

def ping_max(db=None):
    try: return int((db if db is not None else load_db()).get("ping_max") or PING_MAX)
    except Exception: return PING_MAX

def rename_all(codes, geo, ms=None, fresh=False, exits=None, cap=None, listed=()):
    """Kuralar:
    - Rusya tek: birden fazla Rusya varsa en iyi ms'li kalır, her zaman 2. sırada.
    - Telefon testinde ms'i olanlar ms'e göre sıralanır (düşük ping önce).
    - Telefon testi yeniyse ve çalışan kod varsa test edilmemiş kodlar EKLENMEZ (az olsun, hepsi çalışsın).
      Hiç ölçülmüş kod yoksa (test yok/eski) eskisi gibi hepsi kalır.
    - En üstte gerçek ülkeler (her ülkeden en hızlısı, gerçek bayrakla). 6+ farklı gerçek ülke varsa
      sadece onlar kalır; azsa geri kalan kodlar onların altına rastgele bayrakla eklenir.
    - Hiçbir bayrak (Rusya dahil) iki kez kullanılmaz; isim/emoji de tekrar etmez.
    Dönüş: (yeni kodlar, log satırları)."""
    ms, exits = ms or {}, exits or {}
    info = []
    for i, c in enumerate(codes):
        k = code_key(c)
        # Gerçek ülke = telefonun bağlanıp ÖLÇTÜĞÜ çıkış ülkesi. Sağlayıcının isimdeki bayrağı yanlış olabiliyor,
        # o yüzden isme sadece hiç ölçüm yokken bakılır.
        ex = exits.get(k) if exits else exit_country(c, geo)[0]
        info.append({"c": c, "ex": ex if ex in COUNTRIES else None, "ms": ms.get(k), "tested": (not fresh) or k in ms, "i": i})
    order = lambda x: (x["ms"] is None, x["ms"] or 0, x["i"])
    tested = sorted([x for x in info if x["tested"]], key=order)
    untested = [x for x in info if not x["tested"]]
    skip_u = slow = 0
    if fresh and tested and untested:
        skip_u = len(untested); untested = []
    if fresh and cap and tested:   # ping sınırı: yavaş kodlar Happ'te n/a görünüyor
        lim = lambda x: cap * SLOW_OUT if code_key(x["c"]) in listed else cap   # listedeki kod sınırı biraz aşınca hemen atılmaz
        fast = [x for x in tested if x["ms"] is not None and x["ms"] <= lim(x)]
        keep = fast if len(fast) >= PING_KEEP else tested[:PING_KEEP]
        slow = len(tested) - len(keep); tested = keep
    ru_all = [x for x in tested if x["ex"] == "ru"] + [x for x in untested if x["ex"] == "ru"]
    ru = ru_all[0] if ru_all else None
    real, seen, others = [], {"ru"}, []
    for x in tested:
        if x["ex"] == "ru": continue
        if x["ex"] and x["ex"] not in seen: seen.add(x["ex"]); real.append(x)
        else: others.append(x)
    rest_u = [x for x in untested if x["ex"] != "ru"]
    dropped = len(ru_all) - (1 if ru else 0)
    if len(real) >= REAL_MIN: dropped += len(others); others = []
    bag = [c for c in COUNTRIES if c not in seen]; random.shuffle(bag)
    plan = [(x, x["ex"], True) for x in real]
    skipped = 0
    for x in others + rest_u:
        if bag: plan.append((x, bag.pop(), False))
        else: skipped += 1
    if ru: plan.insert(min(1, len(plan)), (ru, "ru", True))
    used_names, used_emojis, out = set(), set(), []
    for x, cc, is_real in plan:
        flag, cname, _ = COUNTRIES[cc]
        out.append(set_name(x["c"], f"{flag} {cname}{REAL_SEP if is_real else RAND_SEP}{_pick_name(cc, used_names, used_emojis)}"))
    notes = [f"🧩 Liste: {len(real)} gerçek ülke · Rusya {'2. sırada' if ru else 'yok'} · {len(plan) - len(real) - (1 if ru else 0)} rastgele"
             + (f" · {dropped} elendi" if dropped else "") + (f" · {skip_u} test edilmemiş kod eklenmedi" if skip_u else "") + (f" · {slow} yavaş kod (>{cap} ms) eklenmedi" if slow else "") + (f" · {skipped} bayrak bitti" if skipped else "")]
    return out, notes


# ───────── TELEFON TESTİ (Türkmenistan) ─────────
# Telefon (Termux, VPN dışı) Drive'daki tmtest.txt'den abonelikleri okur, kodları TM internetinden
# Xray ile test eder ve sonucu aynı dosyaya yazar. Bot burada okuyup TM'de çalışmayan kodları çıkarır.
TM_NAME = "tmtest.txt"
TM_MAX_AGE = 6 * 3600     # bundan eski telefon sonucu yok sayılır
TM_ALERT = 30 * 60        # bu kadar süre sonuç gelmezse kurucuya bir kez hatırlatma

def source_fids(db):
    out = set()
    for u in list(db.get("sources", [])) + list(db.get("source_subs", [])):
        m = re.search(r"files/([\w-]{10,})", u)
        if m: out.add(m.group(1))
    return out

def _tm_write(svc, fid, data, name=None):
    media = MediaIoBaseUpload(io.BytesIO(json.dumps(data, ensure_ascii=False).encode("utf-8")), mimetype="text/plain")
    body = {"name": name} if name else {}
    svc.files().update(fileId=fid, body=body, media_body=media).execute(num_retries=2)

def _tm_create(svc, db, data):
    """Önce adla var olanı bul, yoksa yeni dosya oluştur, o da olmazsa boş bir dosyayı kullan."""
    r = svc.files().list(q=f"name='{TM_NAME}' and trashed=false", fields="files(id)", orderBy="modifiedTime desc", pageSize=1).execute()
    if r.get("files"): return r["files"][0]["id"]
    media = MediaIoBaseUpload(io.BytesIO(json.dumps(data).encode("utf-8")), mimetype="text/plain")
    try:
        return svc.files().create(body={"name": TM_NAME, "mimeType": "text/plain"}, media_body=media, fields="id").execute()["id"]
    except Exception as e:
        log.warning("tm create: %s", e)
    used = used_fids(db) | set(db["free_files"])
    fid = find_free_file(svc, used)
    if not fid: raise RuntimeError("Drive'da kanal için boş dosya yok")
    _tm_write(svc, fid, data, TM_NAME)
    return fid

def load_exits():
    try:
        with open(EXIT_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

CH_WLOCK = threading.Lock()   # telefon kanalını oku-değiştir-yaz: aynı anda iki yazan birbirinin değişikliğini silmesin

def tm_sync(db, sources, codes=None):
    with CH_WLOCK: return _tm_sync(db, sources, codes)

def _tm_sync(db, sources, codes=None):
    """Kanal dosyasını hazır tutar, telefonun son sonucunu okur. Dönüş: TM'de çalışmayan kod anahtarları."""
    try:
        svc = new_service()
        fid, ch = db.get("tm_fid"), None
        if fid:
            try:
                raw = svc.files().get_media(fileId=fid).execute().decode("utf-8", "ignore").strip()
                ch = json.loads(raw) if raw.startswith("{") else {}
            except Exception as e:
                if "404" not in str(e) and "notFound" not in str(e): raise
                fid = None
        if not fid:
            fid = _tm_create(svc, db, {"sources": sources})
            mutate(lambda d: d.__setitem__("tm_fid", fid))
            vlog(f"📱 Telefon testi kanalı hazır (Drive: {TM_NAME})")
            ch = {}
        # Kodları telefona bot verir (telefon Google'dan abonelik okuyunca 403 alabiliyor)
        codes_all = list(codes or [])
        if codes:   # pazardaki satıcı kodları da telefonda test edilsin
            ks = {code_key(c) for c in codes_all}
            codes_all += [c for c in market_codes(db) if code_key(c) not in ks]
        new_keys = sorted(code_key(c) for c in codes_all)
        if ch.get("sources") != sources or (codes and sorted(code_key(c) for c in ch.get("codes", [])) != new_keys):
            ch["sources"] = sources
            if codes: ch["codes"], ch["codes_ts"] = codes_all, int(time.time())
            _tm_write(svc, fid, ch)
        RUN["tm_err"] = ""
    except Exception as e:
        msg = str(e)[:120]
        if msg != RUN["tm_err"]: vlog(f"⚠️ Telefon testi okunamadı: {msg}")
        RUN["tm_err"] = msg
        RUN["tm_line"] = "📱 Telefon testi: okunamadı"
        return set(), {}, False, load_exits()
    ver = ch.get("tmtest_ver")
    if ver and ver != RUN.get("tm_ver"):
        if RUN.get("tm_ver"): vlog(f"📲 Telefon programı güncellendi ({ver})")
        RUN["tm_ver"] = ver
    ts, res = int(ch.get("ts") or 0), ch.get("results") or {}
    mk_keys = {code_key(c) for c in market_codes(db)}
    ours = {k: v for k, v in res.items() if k not in mk_keys}   # menüdeki sayı sadece bizim kodlar (pazar kodları ayrı)
    good = sum(1 for v in ours.values() if isinstance(v, (int, float)) and v > 0)
    stale = bool(ts) and time.time() - ts > TM_MAX_AGE
    if ch.get("status") == "not_tm" and int(ch.get("status_ts") or 0) >= ts:
        RUN["tm_line"] = f"⚠️ Telefon testi VPN'den çıkıyor ({ch.get('country', '?')}) → Happ'te Termux Bypass olmalı"
        if RUN.get("tm_warned") != ch.get("status_ts"):
            RUN["tm_warned"] = ch.get("status_ts"); vlog(RUN["tm_line"])
    elif stale:
        RUN["tm_line"] = f"📱 Telefon testi: {ago(ts)} (eski, kullanılmıyor)"
    elif ts:
        RUN["tm_line"] = f"📱 Telefon testi: {ago(ts)} · {good}/{len(ours)} çalışıyor"
        RUN["tm_v"] = (ts, good, len(ours))
    else:
        RUN["tm_line"] = "📱 Telefon testi: henüz sonuç yok (tmtest start)"
    if ch.get("exits"):
        cache = load_exits()
        if any(cache.get(k) != v for k, v in ch["exits"].items()):
            cache.update(ch["exits"])
            RUN["exits_changed"] = True   # ülke bilgisi değişti -> bayraklar yeniden yazılsın
            try:
                with open(EXIT_FILE, "w", encoding="utf-8") as f: json.dump(cache, f)
            except Exception: pass
    if ts and ts != RUN["tm_ts"]:
        RUN["tm_ts"] = ts
        vlog(f"📱 Telefon testi (TM): {good} çalışıyor, {len(ours) - good} çalışmıyor, {ch.get('skipped', 0)} test edilmedi" + (f" · pazar: {len(res) - len(ours)} kod" if len(res) > len(ours) else ""))
    if ts and time.time() - ts > TM_ALERT and RUN.get("tm_alerted") != ts:
        RUN["tm_alerted"] = ts
        RUN["tm_alert"] = f"📱 Telefon testinden sonuç gelmiyor (son sonuç: {ago(ts)}). Termux'u aç, test kendiliğinden başlar."
    if not ts or stale: return set(), {}, False, load_exits()
    return ({k for k, v in res.items() if isinstance(v, (int, float)) and v < 0},
            {k: v for k, v in res.items() if isinstance(v, (int, float)) and v > 0}, True, load_exits())


# ───────── KONTROL DÖNGÜSÜ ─────────
def check_cycle(force=False):
    """Bloklayan iş (thread'de çalışır). Güncelleme olursa sonuç dict döner, olmazsa None."""
    db = load_db()
    sources = list(db["sources"])
    RUN["last_check"] = time.time()
    if not sources:
        RUN["last_msg"] = "⚠️ Abonelik eklenmemiş"
        vlog("⚠️ Abonelik eklenmemiş. 🔗 Abonelikler'den ekle.")
        return {"error": "Abonelik eklenmemiş."} if force else None
    vlog(f"🔍 Kontrol ediliyor ({len(sources)} abonelik)...")

    def one(i_url):
        i, url = i_url
        t = time.time()
        try: return i, fetch_codes(url), None, time.time() - t
        except urllib.error.HTTPError as e:   # Google'ın sebebini de yaz (ör. rateLimitExceeded)
            try: why = json.loads(e.read().decode("utf-8", "ignore"))["error"]["errors"][0].get("reason", "")
            except Exception: why = ""
            return i, [], f"HTTP {e.code}" + (f" {why}" if why else ""), time.time() - t
        except Exception as e:   # zaman aşımı vb.: 2 sn sonra bir kez daha dene
            time.sleep(2)
            try: return i, fetch_codes(url), None, time.time() - t
            except Exception as e2: return i, [], str(e2 or e)[:140], time.time() - t

    codes, keys = [], set()
    with ThreadPoolExecutor(max(1, min(8, len(sources)))) as ex:
        res = list(ex.map(one, enumerate(sources, 1)))
    for i, got, err, dt in res:
        if err: vlog(f"❌ Abonelik {i}: başarısız ({err})")
        else: vlog(f"✅ Abonelik {i}: {len(got)} kod ({dt:.1f} sn)")
        RUN["src"][sources[i - 1]] = f"❌ {err}" if err else f"✅ {len(got)} kod"
        for c in got:
            k = code_key(c)
            if k not in keys: keys.add(k); codes.append(c)
    via = RUN.pop("src_via_sa", None)
    if via: vlog(f"⚠️ Google indirmeyi reddetti ({via}) → abonelik servis hesabıyla okundu")
    if not codes:
        RUN["last_msg"] = "❌ Hiç kod alınamadı"
        vlog("❌ Hiç kod alınamadı, Drive'a dokunulmadı.")
        return {"error": "Hiç kod alınamadı."}
    # bir abonelik anlık okunamadıysa eksik listeyle Drive'ı bozma (sonra "yeni IP" sanıp tekrar yazıyordu)
    failed = [str(i) for i, _, err, _ in res if err]
    if failed and not force:
        RUN["src_fail"] = RUN.get("src_fail", 0) + 1
        if RUN["src_fail"] < 3:
            RUN["last_msg"] = f"⏸ Abonelik {', '.join(failed)} okunamadı → değişiklik yok"
            vlog(f"⏸ Abonelik {', '.join(failed)} okunamadı → bu tur değişiklik yapılmadı, eski kodlar kalıyor ({RUN['src_fail']}/3)")
            return None
        vlog(f"⚠️ Abonelik {', '.join(failed)} 3 kontroldür okunamıyor → okunabilen aboneliklerle devam")
    else:
        RUN["src_fail"] = 0

    ips = {h for h in (code_host(c) for c in codes) if h}
    old = set(db.get("seen_ips", []))
    new = ips - old
    dead_tm, tm_ms, tm_fresh, tm_exits = tm_sync(db, sources, codes)
    dead_tm &= {code_key(c) for c in codes}
    cap = ping_max(db)
    # Liste gidip gelmesin: listedeki kod bozulunca/çok yavaşlayınca hemen yazılır; yeni çalışan kodlar en çok saatte bir eklenir.
    listed = {code_key(c) for c in db.get("template", [])}
    ours = {code_key(c) for c in codes}
    planned = {code_key(c) for c in rename_all([c for c in codes if code_key(c) not in dead_tm], {}, tm_ms, tm_fresh, tm_exits, cap, listed)[0]}   # yazılsaydı liste bu olurdu
    bad_listed = [k for k in listed if k not in ours or k in dead_tm or (k not in planned and tm_fresh and k in tm_ms and tm_ms[k] > cap * SLOW_OUT)]
    gained = sorted(planned - listed)
    add_due = time.time() - db.get("tm_add_ts", 0) >= TM_ADD_EVERY
    exch = RUN.pop("exits_changed", False)
    if exch and not add_due: RUN["exits_changed"] = True   # ülke değişikliği de saatlik eklemeyle yazılır
    tm_changed = bool(bad_listed) or (bool(gained or exch) and add_due)
    need = ip_need(db)
    if not force and old and len(new) < need and not tm_changed:
        RUN["last_msg"] = f"✅ {len(codes)} kod, {len(new)} yeni IP → değişiklik yok"
        vlog(f"ℹ️ {len(codes)} kod · {len(new)} yeni IP (eşik: en az {need}) → değişiklik yok")
        return None

    why = "⚡ Elle güncelleme" if force else (f"🚨 {len(new)} yeni IP bulundu" if (not old or len(new) >= need) else
                                            f"📱 Listedeki {len(bad_listed)} kod bozuldu/yavaşladı" if bad_listed else f"📱 {len(gained)} yeni çalışan kod eklenecek" if gained else "📱 Ülke bilgisi değişti")
    vlog(f"{why} → {len(codes)} kod yenileniyor...")
    if dead_tm:
        keep = [c for c in codes if code_key(c) not in dead_tm]
        if keep:
            vlog(f"📱 TM'de çalışmayan {len(dead_tm)} kod çıkarıldı")
            codes = keep
        else:
            vlog("⚠️ Telefon testine göre hiçbir kod çalışmıyor; test yok sayıldı")
    codes = dead_filter(codes)
    need_ip = [] if tm_exits else [code_host(c) for c in codes if exit_country(c, {})[0] is None]   # ölçüm yoksa: isminde ülke olmayanlar
    geo = geo_lookup([h for h in need_ip if h]) if need_ip else {}
    renamed, notes = rename_all(codes, geo, tm_ms, tm_fresh, tm_exits, cap, listed)
    for n in notes: vlog(n)
    targets = [(s["file_id"], name_of(s, k), eff_ann(db, s)) for k, s in db["subs"].items() if s.get("file_id") and not is_exp(s)]
    ok, bad = push_all(targets, renamed)
    vlog(f"{'✅' if not bad else '⚠️'} Drive: {ok}/{len(targets)} güncellendi" + (f" · başarısız: {', '.join(bad[:5])}" if bad else ""))

    def f(d):
        d["template"] = renamed
        d["last_update"] = time.time()
        if not bad:   # hata varsa eskileri kalsın, sonraki turda tekrar dener
            d["seen_ips"] = sorted(ips)
            d["tm_dead_pushed"] = sorted(dead_tm)
            d["tm_add_ts"] = time.time()
    mutate(f)
    RUN["last_msg"] = f"🔄 Güncellendi: {len(renamed)} kod → {ok}/{len(targets)} Drive"
    return {"new": len(new), "codes": renamed, "ok": ok, "total": len(targets), "bad": bad, "force": force}

CHECK_LOCK = None   # post_init içinde oluşturulur (eski Python sürümleri için)
WAKE = None
FAIL = {"t": 0.0}

async def run_check(app, force=False):
    async with CHECK_LOCK:
        try: r = await asyncio.to_thread(check_cycle, force)
        except Exception as e:
            log.exception("check"); vlog(f"❌ Hata: {e}")
            r = {"error": str(e)[:200]}
    if r and "error" in r:
        if force or time.time() - FAIL["t"] > 3600:   # otomatik hatalar saatte en fazla 1 bildirim
            FAIL["t"] = time.time()
            await notify_founders(app, f"❌ <b>Abonelik kontrolü başarısız</b>\n{esc(r['error'])}\n<i>Abonelik linklerinden kod okunamadı; Drive'daki kodlara dokunulmadı.</i>")
    elif r:
        # kodlar sohbete yazılmaz; ayrıntı 📜 Loglar'da
        head = (f"🔄 Kodlar güncellendi{' (elle)' if r['force'] else ''}: {len(r['codes'])} kod · "
                f"Drive {r['ok']}/{r['total']} {'✅' if not r['bad'] else '⚠️'}")
        await notify_founders(app, head, KB([[B("📜 Loglar", callback_data="logs")]]))
    alert = RUN.pop("tm_alert", None)
    if alert: await notify_founders(app, esc(alert))
    return r

def start_refresh(app, why):
    """Abonelik listesi değişince beklemeden zorla güncelle (sürmekte olan kontrol bitince başlar)."""
    vlog(f"🔁 {why} → kodlar yeniden yazılacak")
    RUN["src"] = {}
    asyncio.create_task(run_check(app, force=True))

async def monitor(app):
    await asyncio.sleep(5)
    vlog("▶️ Bot başladı, kontrol sistemi hazır.")
    while True:
        if not os.path.exists(STOP_FLAG):
            await run_check(app)
        RUN["next"] = time.time() + CHECK_EVERY
        try: await asyncio.wait_for(WAKE.wait(), CHECK_EVERY)
        except asyncio.TimeoutError: pass
        WAKE.clear()


# ───────── SÜRE / YEDEK ─────────
def make_backup():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in [DB_FILE, SA_FILE, ENV_FILE, VIP_LOG, AUDIT_LOG, USERS_LOG, GEO_FILE, "/root/sohbet.txt", os.path.abspath(__file__), BANNER_FILE]:
            if os.path.exists(f): zf.write(f, os.path.basename(f))
    buf.seek(0)
    return buf

async def watchdog(app):
    while True:
        await asyncio.sleep(60)
        # süresi dolan kodların Drive dosyası boşaltılır
        try:
            def job():
                def f(db):
                    hit, warn, ended = [], [], []
                    for kid, s in db["subs"].items():
                        if s.get("pub") and is_exp(s): continue   # kullanıcı kodu: aşağıda silinir
                        if is_exp(s) and not s.get("exp_done"):
                            s["exp_done"] = True
                            hit.append((s.get("file_id"), name_of(s, kid), s.get("owner_id")))
                    for sid, e in db.get("sub_admins", {}).items():
                        left = float(e.get("expires", 0)) - time.time()
                        if 0 < left < 86400 and not e.get("warned"):
                            e["warned"] = True; warn.append((sid, e.get("name") or sid))
                        if left <= 0 and not e.get("ended"):
                            e["ended"] = True; ended.append((sid, e.get("name") or sid))
                    return hit, warn, ended
                hit, warn, ended = mutate(f)
                if hit:
                    svc = new_service()
                    for fid, nm, _ in hit: sync_file(svc, fid, nm, "", [], exp=True)
                return hit, warn, ended
            hit, warn, ended = await asyncio.to_thread(job)
            gone = [(k, dict(s)) for k, s in load_db()["subs"].items() if s.get("pub") and is_exp(s)]
            for kid, s in gone:
                if await asyncio.to_thread(delete_vip, kid):
                    ow = s.get("owner_id"); e = load_db().get("users", {}).get(str(ow), {})
                    kind_tr = {"free": "ücretsiz", "trial": "deneme", "gift": "hediye"}.get(s["pub"], "satın alınan")
                    ulog("del", f"🗑 Kod silindi (süre doldu): {e.get('name', '?')} ({ow}) · {kid} · {kind_tr}")
                    lg = e.get("lang", "tr")
                    try:
                        if s["pub"] == "trial": await app.bot.send_message(ow, tr(lg, "trial_end"), reply_markup=KB([[B(tr(lg, "b_market"), "u_market", "success")]]))
                        else: await app.bot.send_message(ow, tr(lg, "expired", name=name_of(s, kid)))
                    except Exception: pass
            # satın alınan / hediye kodlar: bitmesine 24 saat kala hatırlat (bir kez)
            due = [k for k, s in load_db()["subs"].items() if s.get("pub") in ("paid", "gift") and s.get("expires") and not s.get("reminded") and 0 < float(s["expires"]) - time.time() < 86400]
            if due:
                def rf(d):
                    out = []
                    for k in due:
                        s = d["subs"].get(k)
                        if s and not s.get("reminded"): s["reminded"] = True; out.append((k, dict(s)))
                    return out
                for kid, s in mutate(rf):
                    ow = s.get("owner_id"); lg = lang_of(load_db(), ow)
                    try: await app.bot.send_message(ow, tr(lg, "remind", name=esc(name_of(s, kid)), left=left_txt(s.get("expires"), lg == "ru")), parse_mode="HTML",
                                                    reply_markup=KB([[B(tr(lg, "b_ext"), f"u_ext:{kid}", "success")]]))
                    except Exception: pass
            for fid, nm, owner in hit:
                audit(0, f"expired {nm}")
                await notify_founders(app, f"⏳ Kodun süresi doldu, kapatıldı: <code>{esc(nm)}</code>")
                if owner and owner not in ADMINS:
                    try: await app.bot.send_message(chat_id=owner, text=L(owner, f"⏳ Kodunun süresi doldu: {nm}", f"⏳ Срок кода истёк: {nm}"))
                    except Exception: pass
            for sid, nm in warn:
                await notify_founders(app, f"⏳ <b>Alt admin süresi bitiyor</b>\n<blockquote>👮 {esc(nm)} <code>{sid}</code>\n24 saatten az kaldı.</blockquote>",
                                      KB([[B("⏳ Uzat", f"sa_ext:{sid}", "primary")]]))
                try: await app.bot.send_message(chat_id=int(sid), text=L(int(sid), "⏳ Panelinin bitmesine 24 saatten az kaldı. Market'ten uzatabilirsin.", "⏳ До окончания панели меньше 24 часов. Продлить можно в Магазине."))
                except Exception: pass
            for sid, nm in ended:
                audit(0, f"sa_ended {sid}")
                await notify_founders(app, f"🔒 <b>Alt admin yetkileri alındı</b>\n<blockquote>👮 {esc(nm)} <code>{sid}</code>\nSüresi doldu. Oluşturduğu kodlar çalışmaya devam ediyor.</blockquote>",
                                      KB([[B("⏳ Uzat", f"sa_ext:{sid}", "success")]]))
                try: await app.bot.send_message(chat_id=int(sid), text=L(int(sid), "🔒 Panelinin süresi doldu. Oluşturduğun kodlar çalışmaya devam ediyor.", "🔒 Срок панели истёк. Созданные коды продолжают работать."))
                except Exception: pass
        except Exception: log.exception("watchdog expiry")
        try: await check_invoices(app)   # USDT ödemeleri
        except Exception: log.exception("check_invoices")
        # AUTO_ANN saatlerinde (Aşkabat) otomatik genel duyuru; bot o saatte kapalıysa açılınca yazar
        try:
            now = datetime.datetime.now(TM_TZ)
            past = [h for h in sorted(AUTO_ANN) if h <= now.hour]
            h, day = (past[-1], now.date()) if past else (max(AUTO_ANN), now.date() - datetime.timedelta(days=1))
            slot = f"{day:%Y-%m-%d} {h} {AUTO_ANN[h]}"   # metin değişirse aynı gün de yeniden yazılır
            db0 = load_db()
            if db0.get("auto_ann_on", True) and db0.get("auto_ann_last") != slot:
                text = AUTO_ANN[h]
                def ajob():
                    def f(d):
                        d["auto_ann_last"], d["g_announce"] = slot, text
                        return [(x["file_id"], name_of(x, k), eff_ann(d, x)) for k, x in d["subs"].items() if x.get("file_id") and not is_exp(x)], list(d["template"])
                    items, tpl = mutate(f)
                    return push_all(items, tpl), len(items)
                async with CHECK_LOCK:
                    (ok, bad), n = await asyncio.to_thread(ajob)
                vlog(f"🕰 Otomatik duyuru ({now:%H:%M}): {text} → Drive {ok}/{n}")
        except Exception: log.exception("auto announce")
        # her sabah günlük rapor (dünün özeti)
        try:
            now = tm_now()
            if now.hour >= REPORT_HOUR and load_db().get("report_last") != now.strftime("%Y-%m-%d"):
                mutate(lambda d: d.__setitem__("report_last", now.strftime("%Y-%m-%d")))
                a0, a1, lbl = day_bounds(-1)
                await notify_founders(app, await asyncio.to_thread(report_text, a0, a1, f"Günlük rapor · {lbl}"))
        except Exception: log.exception("daily report")
        # her gün 03:00 otomatik yedek (gün diske yazılır: bot yeniden açılsa da günde bir kez)
        try:
            now = datetime.datetime.now(); d = now.strftime("%Y-%m-%d")
            if now.hour == 3 and load_db().get("backup_last") != d:
                mutate(lambda x: x.__setitem__("backup_last", d))
                data = (await asyncio.to_thread(make_backup)).getvalue()
                fn = f"Backup_{now:%Y-%m-%d_%H%M}.zip"
                os.makedirs(BACKUP_DIR, exist_ok=True)
                try: os.chmod(BACKUP_DIR, 0o700)
                except Exception: pass
                with open(os.path.join(BACKUP_DIR, fn), "wb") as f: f.write(data)
                for old in sorted(os.listdir(BACKUP_DIR))[:-7]:
                    try: os.remove(os.path.join(BACKUP_DIR, old))
                    except Exception: pass
                for fid in ADMINS:
                    try: await app.bot.send_document(chat_id=fid, document=io.BytesIO(data), filename=fn, caption="🗄 Günlük otomatik yedek")
                    except Exception as e: log.warning("auto-backup send: %s", e)
        except Exception: log.exception("watchdog backup")

def migrate_announce():
    """Bir kerelik: eski toplu duyuru her koda ayrı yazılmıştı. Hepsi aynıysa genel duyuruya taşınır,
    farklı olanlar koda özel duyuru olarak kalır."""
    def f(d):
        if "g_announce" in d: return None
        anns = {s.get("announce", "") for s in d["subs"].values()}
        moved = None
        if len(anns) == 1 and next(iter(anns)):
            moved = next(iter(anns))
            for s in d["subs"].values(): s["announce"] = ""
        d["g_announce"] = moved or ""
        return moved
    try:
        moved = mutate(f)
        if moved: vlog(f"📢 Ortak duyuru genel duyuruya taşındı: {short(moved, 50)}")
    except Exception: log.exception("migrate announce")

STARTS_FILE = "/root/.subbot_starts"

def crash_info():
    """Son çökme satırları (systemd günlüğünden). Token gizlenir."""
    import subprocess
    try: out = subprocess.run(["journalctl", "-u", "subbot", "-n", "200", "--no-pager", "-o", "cat"], capture_output=True, text=True, timeout=15).stdout
    except Exception as e: return f"(günlük okunamadı: {e})"
    lines = out.splitlines()
    idx = [i for i, l in enumerate(lines) if "Traceback" in l or "Killed" in l or "oom" in l.lower() or "MemoryError" in l or "status=" in l]
    pick = lines[idx[-1]:idx[-1] + 25] if idx else lines[-15:]
    txt = "\n".join(pick)[-1500:]
    tok = os.environ.get("BOT_TOKEN", "")
    if tok: txt = txt.replace(tok, "***")
    return re.sub(r"bot\d+:[\w-]+", "bot***", txt)

async def check_restart_loop(app):
    """Bot kısa sürede çok kez yeniden açıldıysa kuruculara sebebiyle bildirir (saatte en fazla bir kez).
    Güncelleme / geri alma ile yapılan planlı yeniden açılışlar sayılmaz."""
    if os.path.exists(UPDATE_NOTE): return
    now = time.time()
    try:
        with open(STARTS_FILE) as f: st = json.load(f)
    except Exception: st = {}
    starts = [t for t in st.get("starts", []) if now - t < 3600] + [now]
    st["starts"] = starts
    recent = sum(1 for t in starts if now - t < 600)
    alert = recent >= 3 and now - st.get("alert", 0) > 3600
    if alert: st["alert"] = now
    try:
        with open(STARTS_FILE, "w") as f: json.dump(st, f)
    except Exception: pass
    if alert:
        info = await asyncio.to_thread(crash_info)
        vlog(f"🔁 Bot 10 dakikada {recent} kez yeniden açıldı")
        await notify_founders(app, f"🔁 <b>Bot 10 dakikada {recent} kez yeniden açıldı</b>\n<i>Son 1 saatte {len(starts)} açılış. Çökme sebebi:</i>\n<pre>{esc(info)}</pre>")

async def post_init(app):
    await asyncio.to_thread(migrate_announce)
    try: await check_restart_loop(app)
    except Exception: log.exception("restart loop check")
    if os.path.exists(UPDATE_NOTE):
        try:
            sha = open(UPDATE_NOTE).read().strip(); os.remove(UPDATE_NOTE)
            await notify_founders(app, f"🟢 <b>Bot yeni sürümle açıldı</b> <code>{esc(sha)}</code>")
        except Exception: pass
    try: BOT["un"] = (await app.bot.get_me()).username or ""
    except Exception as e: log.warning("get_me: %s", e)
    asyncio.create_task(ad_photo_id(app.bot))   # reklam fotoğrafı önceden yüklensin (inline cevap hızlı olsun)
    try:
        sw = mutate(switch_bot)
        if sw:
            vlog(f"🔁 Bot değişti ({sw[0]} → {BOT_ID}): {sw[1]} ilan fotoğrafı silindi (eski botun fotoğrafları yenisinde açılmaz)")
            await notify_founders(app, f"🔁 <b>Yeni bota geçildi</b> (@{esc(BOT['un'])})\n<blockquote>📷 Eski botun fotoğrafları yenisinde açılmadığı için {sw[1]} ilan fotoğrafı kaldırıldı; ilanlar fotoğrafsız görünür.\n📢 Zorunlu kanallarda bu botu admin yapmayı unutma.</blockquote>")
    except Exception: log.exception("bot switch")
    global CHECK_LOCK, WAKE
    CHECK_LOCK, WAKE = asyncio.Lock(), asyncio.Event()
    app.bot_data["mon"] = asyncio.create_task(monitor(app))
    app.bot_data["wd"] = asyncio.create_task(watchdog(app))
    try: mutate(ensure_own)   # bizim ilan pazarda hep olsun
    except Exception: log.exception("market init")
    app.bot_data["mkt"] = asyncio.create_task(market_loop(app))
    if load_db().get("off_msg") != CODE_OFF_MSG: asyncio.create_task(asyncio.to_thread(rewrite_off_files))
    if load_db().get("file_fmt") != FILE_FMT:   # dosya biçimi değişti: bütün abonelik dosyaları bir kez yeniden yazılsın
        mutate(lambda d: d.__setitem__("file_fmt", FILE_FMT)); start_refresh(app, "Abonelik dosyası biçimi güncellendi")
    try:
        from telegram import BotCommand
        await app.bot.set_my_commands([BotCommand("start", "Ana menü"), BotCommand("id", "Telegram ID'n")])
    except Exception as e: log.warning("commands: %s", e)


# ───────── MENÜLER ─────────
def open_sessions(db, uid):
    return [(sid, x) for sid, x in db.get("msess", {}).items() if x.get("buyer") == uid and x.get("status") == "on"]

def open_mkt_text(db, uid, lang):
    """Ana menü: açık pazar kodu varsa dakikalık ücret ve harcama (unutulan kod para yemesin)."""
    ss = open_sessions(db, uid)
    if not ss: return ""
    pm = sum(float(db["market"].get(x["lid"], {}).get("price", 0)) for _, x in ss)
    spent = sum(x.get("total", 0) for _, x in ss)
    return tr(lang, "open_line", n=len(ss), pm=money_tmt(pm, 4), spent=money_tmt(spent))

def open_mkt_row(db, uid, lang):
    n = len(open_sessions(db, uid))
    return [[B(tr(lang, "b_open", n=n), "u_mine", "success")]] if n else []

def with_bal(t, e, lang):
    """Ana menü kutusuna bakiye satırı (kutunun son satırı olarak)."""
    line = tr(lang, "menu_bal", bal=f"{e.get('bal', 0) / UM:.2f}", tmt=f"{e.get('bal', 0) * USDT_RATE / UM:.2f}")
    i = t.rfind("</blockquote>")
    return t[:i] + line + t[i:] if i >= 0 else t + line

def menu_text(uid):
    try: db = load_db()
    except Exception: db = None
    if not db: return _menu_text(uid)
    lang = lang_of(db, uid)
    return with_bal(_menu_text(uid), db.get("users", {}).get(str(uid), {}), lang) + open_mkt_text(db, uid, lang)

def _menu_text(uid):
    try: db = load_db()
    except Exception: db = None
    if uid not in ADMINS:
        mine = [v for v in (db["subs"].values() if db else []) if v.get("owner_id") == uid]
        e = (db.get("sub_admins", {}) if db else {}).get(str(uid), {})
        ru = is_ru(uid)
        return ("✦ <b>VIP PANEL</b> ✦\n"
                f"<blockquote>🎟 {'Ваши коды' if ru else 'Kodların'}  <b>{len([v for v in mine if not v.get('pub')])}/{sa_limit(db, uid) if db else SUB_LIMIT}</b>\n"
                f"⏳ {'Срок панели' if ru else 'Panel süresi'}  <b>{left_txt(e.get('expires'), ru)}</b></blockquote>\n"
                + ("<i>Выберите действие</i> 👇" if ru else "<i>Bir işlem seç</i> 👇"))
    n = len(db["template"]) if db else "?"
    src = len(db["sources"]) if db else "?"
    vip = len(db["subs"]) if db else "?"
    on = not os.path.exists(STOP_FLAG)
    lg = alang(uid); tv = RUN.get("tm_v")
    tm = f"{ago_l(tv[0], lg)} · ✅ {tv[1]}/{tv[2]}" if tv and RUN["tm_line"].startswith("📱 Telefon testi: ") and "·" in RUN["tm_line"] else RUN["tm_line"].replace("📱 Telefon testi: ", "")
    return ("✦ <b>VPN PANEL</b> ✦\n"
            f"<blockquote>{at(lg, 'sys')}  <b>{at(lg, 'on') if on else at(lg, 'off')}</b>\n"
            f"{at(lg, 'lastchk')}  <i>{ago_l(RUN['last_check'], lg)}</i>\n"
            f"{at(lg, 'lastupd')}  <i>{ago_l(db.get('last_update') if db else None, lg)}</i>\n"
            f"{at(lg, 'tm')}  <i>{esc(tm)}</i></blockquote>\n"
            + at(lg, "stat", n=n, s=src, v=vip, u=len(db.get('users', {})) if db else '?'))

def main_kb(uid):
    kb = _main_kb(uid)
    try: extra = open_mkt_row(load_db(), uid, lang_of(None, uid))
    except Exception: extra = []
    return KB([list(r) for r in kb.inline_keyboard[:1]] + extra + [list(r) for r in kb.inline_keyboard[1:]]) if extra else kb

def _main_kb(uid):
    is_ru(uid); lang_btn = B(tr(LANGC.get(uid) if LANGC.get(uid) in T else "tr", "b_set"), "u_set")
    if uid not in ADMINS:   # panel sahibi: kendi panelinde kod oluşturur
        return KB([[B(L(uid, "🏪 Pazar", "🏪 Биржа"), "u_mkt", "success")],
                   [B(L(uid, "✨ Kod Oluştur", "✨ Создать код"), "create_key"), B(L(uid, "👥 Kodlarım", "👥 Мои коды"), "my_keys", "primary")],
                   [B(L(uid, "👤 Profil", "👤 Профиль"), "u_prof"), B(L(uid, "🛒 Market", "🛒 Магазин"), "u_market")],
                   [B(L(uid, "🆘 Support", "🆘 Поддержка"), "u_sup"), B(L(uid, "🐞 Hata Bildir", "🐞 Баг-репорт"), "u_bug")],
                   [lang_btn]])
    # kurucu: kullanıcıların gördüğü butonlar (seçili dilde) + 📥 İlanlar + tek bir Admin butonu
    lg = alang(uid)
    try: n_rev = len(review_list(load_db()))
    except Exception: n_rev = 0
    return KB([[B(tr(lg, "b_pazar"), "u_mkt", "success")],
               [B(tr(lg, "b_free"), "u_free"), B(tr(lg, "b_mine"), "my_keys")],
               [B(tr(lg, "b_prof"), "u_prof"), B(tr(lg, "b_market"), "u_market")],
               [B(tr(lg, "b_sup"), "tickets"), B(tr(lg, "b_bug"), "tickets_bug")],
               [lang_btn],
               [B(at(lg, "rev", n=n_rev), "mk_rev", "primary" if n_rev else None)],
               [B("🟡 Admin", "admin", "danger")]])

def ip_need(db=None):
    """Kaç yeni IP görülünce bütün kodlar yenilenir (kurucu Admin'den değiştirir)."""
    try: return int((db if db is not None else load_db()).get("ip_need") or NEW_IP_LIMIT + 1)
    except Exception: return NEW_IP_LIMIT + 1

# ── Kurucu ekranları: seçili dile göre (tr / tk / ru) ──
AT = {
 "tr": {"sys": "⚙️ Sistem", "on": "🟢 Çalışıyor", "off": "🔴 Durduruldu", "every": "🔍 Kontrol her <b>{m} dk</b>", "ipline": "🚨 En az <b>{n}</b> yeni IP → bütün kodlar yenilenir",
        "tmline": "📱 TM'de çalışmayan kodlar telefon testine göre çıkarılır", "annline": "🕰 Otomatik duyuru (Aşkabat saati):",
        "create_key": "🛠 Admin Kod Oluştur", "sources": "🔗 Abonelikler", "logs": "📜 Loglar", "bulk_title": "🏷 Toplu Başlık", "tickets": "🎫 Destek ({n})",
        "upd": "⚡ Güncelle", "zip": "📦 Yedek", "ul": "👥 Kullanıcı Logları", "usearch": "🔎 Kullanıcı Ara", "bal": "💰 Bakiye Ekle / Düş", "rep": "📈 Rapor", "stats": "📊 İstatistik",
        "chans": "📢 Kanallar", "mk": "🏪 Pazar", "bcast": "📣 Herkese Mesaj", "ad": "📢 Reklam Postu", "sa": "👮 Alt Adminler", "ref": "🧪 Davet Testi", "hp": "🔒 Happ Limitli Kod",
        "autoann": "🕰 Oto. Duyuru: {s}", "aon": "Açık", "aoff": "Kapalı", "ipb": "🚨 IP Eşiği: en az {n} yeni IP", "ping": "⏱ Ping Sınırı: {n} ms", "rollback": "♻️ Önceki Sürüme Dön",
        "start": "▶️ Başlat", "stop": "🛑 Durdur", "menu": "◀️ Menü", "rev": "📥 İlanlar ({n})",
        "lastchk": "🔍 Son kontrol", "lastupd": "🔄 Son güncelleme", "tm": "📱 Telefon testi", "stat": "📡 <b>{n}</b> kod  ·  🔗 <b>{s}</b> abonelik\n👥 <b>{v}</b> VIP  ·  🙋 <b>{u}</b> kullanıcı",
        "rev_t": "📥 <b>İnceleme bekleyen ilanlar</b>  <code>{n}</code>\n<blockquote>Bir ilana dokun: fotoğraf, gerçek ping ve onay butonları gelir.</blockquote>",
        "rev_none": "📥 <b>İnceleme bekleyen ilan yok</b> ✅",
        "rv_cap": "📥 <b>{title}</b>\n<blockquote>👤 {who}\n💲 {m} TMT/ay · 📡 {n} sunucu\n🧪 TM testi {w}/{t} · 🌍 {c} ülke\n⏳ {wait} bekliyor{ph}</blockquote>",
        "rv_ph": "\n📷 Fotoğraf onay bekliyor", "back_rev": "◀️ İlanlar", "ok_hand": "✅ Elle onayla",
        "p_ok": "✅ Foto uygun", "p_rej": "❌ Reddet", "p_no": "🔞 Uygunsuz", "p_real": "📊 Gerçek ping", "p_fake": "🤥 Yalan ping", "mn": "{m} dk", "hr": "{h} sa {m} dk"},
 "tk": {"sys": "⚙️ Ulgam", "on": "🟢 Işleýär", "off": "🔴 Saklandy", "every": "🔍 Barlag her <b>{m} min</b>", "ipline": "🚨 Iň az <b>{n}</b> täze IP → ähli kodlar täzelenýär",
        "tmline": "📱 TM-de işlemeýän kodlar telefon testi boýunça aýrylýar", "annline": "🕰 Awtomatik habar (Aşgabat wagty):",
        "create_key": "🛠 Admin kod döret", "sources": "🔗 Podpiskalar", "logs": "📜 Loglar", "bulk_title": "🏷 Umumy at", "tickets": "🎫 Goldaw ({n})",
        "upd": "⚡ Täzele", "zip": "📦 Ätiýaçlyk", "ul": "👥 Ulanyjy loglary", "usearch": "🔎 Ulanyjy gözle", "bal": "💰 Balans goş / aýyr", "rep": "📈 Hasabat", "stats": "📊 Statistika",
        "chans": "📢 Kanallar", "mk": "🏪 Bazar", "bcast": "📣 Hemmelere habar", "ad": "📢 Reklama posty", "sa": "👮 Kömekçi adminler", "ref": "🧪 Çagyryş testi", "hp": "🔒 Happ limitli kod",
        "autoann": "🕰 Awto habar: {s}", "aon": "Açyk", "aoff": "Ýapyk", "ipb": "🚨 IP çägi: iň az {n} täze IP", "ping": "⏱ Ping çägi: {n} ms", "rollback": "♻️ Öňki wersiýa gaýt",
        "start": "▶️ Başlat", "stop": "🛑 Sakla", "menu": "◀️ Menýu", "rev": "📥 Bildirişler ({n})",
        "lastchk": "🔍 Soňky barlag", "lastupd": "🔄 Soňky täzelenme", "tm": "📱 Telefon testi", "stat": "📡 <b>{n}</b> kod  ·  🔗 <b>{s}</b> podpiska\n👥 <b>{v}</b> VIP  ·  🙋 <b>{u}</b> ulanyjy",
        "rev_t": "📥 <b>Barlag garaşýan bildirişler</b>  <code>{n}</code>\n<blockquote>Bildirişe basyň: surat, hakyky ping we tassyklama düwmeleri geler.</blockquote>",
        "rev_none": "📥 <b>Garaşýan bildiriş ýok</b> ✅",
        "rv_cap": "📥 <b>{title}</b>\n<blockquote>👤 {who}\n💲 {m} TMT/aý · 📡 {n} serwer\n🧪 TM testi {w}/{t} · 🌍 {c} ýurt\n⏳ {wait} garaşýar{ph}</blockquote>",
        "rv_ph": "\n📷 Surat tassyklama garaşýar", "back_rev": "◀️ Bildirişler", "ok_hand": "✅ Elde tassykla",
        "p_ok": "✅ Surat dogry", "p_rej": "❌ Ret et", "p_no": "🔞 Ýaramaz", "p_real": "📊 Hakyky ping", "p_fake": "🤥 Ýalan ping", "mn": "{m} min", "hr": "{h} sag {m} min"},
 "ru": {"sys": "⚙️ Система", "on": "🟢 Работает", "off": "🔴 Остановлена", "every": "🔍 Проверка каждые <b>{m} мин</b>", "ipline": "🚨 От <b>{n}</b> новых IP → все коды обновляются",
        "tmline": "📱 Коды, не работающие в ТМ, убираются по тесту телефона", "annline": "🕰 Автообъявление (время Ашхабада):",
        "create_key": "🛠 Создать код (админ)", "sources": "🔗 Подписки", "logs": "📜 Логи", "bulk_title": "🏷 Заголовок", "tickets": "🎫 Тикеты ({n})",
        "upd": "⚡ Обновить", "zip": "📦 Бэкап", "ul": "👥 Логи пользователей", "usearch": "🔎 Найти пользователя", "bal": "💰 Баланс + / −", "rep": "📈 Отчёт", "stats": "📊 Статистика",
        "chans": "📢 Каналы", "mk": "🏪 Биржа", "bcast": "📣 Рассылка всем", "ad": "📢 Рекламный пост", "sa": "👮 Помощники", "ref": "🧪 Тест приглашения", "hp": "🔒 Happ код с лимитом",
        "autoann": "🕰 Автообъявл.: {s}", "aon": "Вкл", "aoff": "Выкл", "ipb": "🚨 Порог IP: от {n} новых", "ping": "⏱ Лимит пинга: {n} мс", "rollback": "♻️ Откатить версию",
        "start": "▶️ Запустить", "stop": "🛑 Остановить", "menu": "◀️ Меню", "rev": "📥 Объявления ({n})",
        "lastchk": "🔍 Последняя проверка", "lastupd": "🔄 Последнее обновление", "tm": "📱 Тест телефона", "stat": "📡 <b>{n}</b> кодов  ·  🔗 <b>{s}</b> подписок\n👥 <b>{v}</b> VIP  ·  🙋 <b>{u}</b> польз.",
        "rev_t": "📥 <b>Объявления на проверке</b>  <code>{n}</code>\n<blockquote>Нажмите на объявление: фото, реальный пинг и кнопки решения.</blockquote>",
        "rev_none": "📥 <b>Нет объявлений на проверке</b> ✅",
        "rv_cap": "📥 <b>{title}</b>\n<blockquote>👤 {who}\n💲 {m} TMT/мес · 📡 {n} серверов\n🧪 Тест ТМ {w}/{t} · 🌍 {c} стран\n⏳ ждёт {wait}{ph}</blockquote>",
        "rv_ph": "\n📷 Фото ждёт проверки", "back_rev": "◀️ Объявления", "ok_hand": "✅ Одобрить вручную",
        "p_ok": "✅ Фото ок", "p_rej": "❌ Отклонить", "p_no": "🔞 Неприлично", "p_real": "📊 Реальный пинг", "p_fake": "🤥 Фейк пинг", "mn": "{m} мин", "hr": "{h} ч {m} мин"}}

def alang(uid):
    try: lg = lang_of(load_db(), uid)
    except Exception: lg = "tr"
    return lg if lg in AT else "tr"

def at(uid_or_lang, key, **kw):
    lg = uid_or_lang if isinstance(uid_or_lang, str) else alang(uid_or_lang)
    s_ = AT.get(lg, AT["tr"]).get(key) or AT["tr"][key]
    return s_.format(**kw) if kw else s_

def wait_txt(lg, sec):
    m_ = int(max(0, sec) // 60)
    return at(lg, "mn", m=m_) if m_ < 60 else at(lg, "hr", h=m_ // 60, m=m_ % 60)

def review_list(db):
    """İnceleme bekleyenler: test bekleyen ilanlar + fotoğrafı onaylanmamış ilanlar (eskiden yeniye)."""
    out = [(lid, L) for lid, L in db.get("market", {}).items() if not L.get("own") and
           (L.get("status") == "pending" or (L.get("status") == "live" and L.get("photo") and not L.get("photo_ok", True)))]
    return sorted(out, key=lambda x: x[1].get("created", 0))

def admin_text(uid=None):
    on = not os.path.exists(STOP_FLAG); a_ = lambda k, **kw: at(uid if uid else "tr", k, **kw)
    return ("⚙️ <b>Admin</b>\n"
            f"<blockquote>{a_('sys')}  <b>{a_('on') if on else a_('off')}</b>\n"
            f"{a_('every', m=CHECK_EVERY // 60)}\n"
            f"{a_('ipline', n=ip_need())}\n"
            f"{a_('tmline')}\n"
            f"{a_('annline')}\n" + "\n".join(f"   {h:02d}:00  {esc(t)}" for h, t in sorted(AUTO_ANN.items())) + "</blockquote>")

def admin_kb(uid=None):
    try: on = load_db().get("auto_ann_on", True)
    except Exception: on = True
    stop = os.path.exists(STOP_FLAG); a_ = lambda k, **kw: at(uid if uid else "tr", k, **kw)
    return KB([
        [B(a_("create_key"), "create_key", "primary")],
        [B(a_("sources"), "sources"), B(a_("logs"), "logs")],
        [B(a_("bulk_title"), "bulk_title"), B(a_("tickets", n=sum(1 for t in load_db().get('tickets', {}).values() if t.get('status') == 'open')), "tickets")],
        [B(a_("upd"), "upd_now"), B(a_("zip"), "get_zip")],
        [B(a_("ul"), "ul_open")],
        [B(a_("usearch"), "usearch")],
        [B(a_("bal"), "bal_find")],
        [B("🚫 Ban / Unban", "ban_menu")],
        [B(a_("rep"), "rep_today"), B(a_("stats"), "stats")],
        [B(a_("chans"), "chans"), B("🪙 CryptoBot", "cp")],
        [B(a_("mk"), "mk_admin"), B("💳 TMT 🔜", "pay_set")],
        [B(a_("bcast"), "bcast")],
        [B(a_("ad"), "ad_post")],
        [B(a_("sa"), "sa_menu")],
        [B(a_("ref"), "ref_test")],
        [B(a_("hp"), "hp")],
        [B(a_("autoann", s=a_("aon") if on else a_("aoff")), "auto_ann")],
        [B(a_("ipb", n=ip_need()), "ip_need")],
        [B(a_("ping", n=ping_max()), "ping_max")],
        [B(a_("rollback"), "rollback")],
        [B(a_("start"), "toggle_sys", "success") if stop else B(a_("stop"), "toggle_sys", "danger")],
        [B(a_("menu"), "menu")]])

def log_text():
    on = not os.path.exists(STOP_FLAG)
    nxt = int(RUN["next"] - time.time()) if on and RUN["next"] else None
    st = ("🟢 Çalışıyor" + (f" · sonraki kontrol {max(0, nxt)} sn" if nxt is not None else "")) if on else "🔴 Durduruldu"
    lines = [short(l, 70) for l in tail(VIP_LOG, 35)]
    body = ('<pre><code class="language-log">' + esc("\n".join(lines)) + "</code></pre>") if lines else "<i>Log yok.</i>"
    return ("📜 <b>Loglar</b>\n"
            f"<blockquote>{st}\n{esc(RUN['last_msg']) or '—'}\n{esc(RUN['tm_line'])}</blockquote>\n"
            f"{body}\n<i>⟳ {datetime.datetime.now():%H:%M:%S}</i>")

LOG_KB = KB([[B("🔄 Yenile", "logs", "primary"), B("◀️ Admin", "admin")]])

def code_card(s, kid, uid):
    fid = s.get("file_id", "")
    own = s.get("announce") or ""
    try: g = load_db().get("g_announce", "")
    except Exception: g = ""
    ru = is_ru(uid)
    return (f"🎟 <b>{esc(short(btn_name(s, kid), 40))}</b>\n"
            f"<blockquote>🏷 {'Заголовок' if ru else 'Başlık'}  <code>{esc(name_of(s, kid))}</code>\n"
            f"📢 {'Объявление' if ru else 'Duyuru'}  {('<i>' + esc(short(own, 120)) + '</i>  <code>' + ('своё' if ru else 'özel') + '</code>') if own else (('<i>' + esc(short(g, 120)) + '</i>  <code>' + ('общее' if ru else 'genel') + '</code>') if g else '—')}\n"
            f"⏳ {'Срок' if ru else 'Süre'}  <b>{left_txt(s.get('expires'), ru)}</b>"
            + (f"\n👮 Sahibi  <code>{s.get('owner_id')}</code>" if uid in ADMINS and s.get("owner_id") and s.get("owner_id") not in ADMINS else "")
            + "</blockquote>\n"
            + L(uid, "🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>", "🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>") + f"\n<code>{esc(user_link(fid) if fid else 'Drive dosyası yok')}</code>"
            + (f"\n<i>Düz link (sadece sen):</i> <code>{esc(sub_link(fid))}</code>" if fid and uid in ADMINS else "")

            + (f"\n\n🔒 <b>Happ limitli link</b> · 📱 {str(s['happ']['limit']) + ' cihaz' if s['happ'].get('limit') else 'limit sitede'}\n<code>{esc(s['happ']['link'])}</code>" if s.get("happ") and uid in ADMINS else ""))

def code_kb(kid, uid):
    rows = [[B(L(uid, "🏷 Başlık", "🏷 Заголовок"), f"kt:{kid}"), B(L(uid, "🔘 Buton Adı", "🔘 Имя кнопки"), f"kn:{kid}")],
            [B(L(uid, "📢 Duyuru", "📢 Объявление"), f"ka:{kid}")] + ([B("⏳ Süre", f"kx:{kid}")] if uid in ADMINS else []),
            [B(L(uid, "🗑 Sil", "🗑 Удалить"), f"kd:{kid}", "danger")],
            [B(L(uid, "◀️ Kodlarım", "◀️ Мои коды"), "my_keys")]]
    return KB(rows)

async def live_log(q, uid):
    """Log mesajını 3 dakika boyunca canlı tutar. Sadece log DEĞİŞİNCE düzenler
    (her 5 sn düzenlemek Telegram'ın flood limitine takılıp botu dakikalarca kilitliyordu)."""
    last = "\n".join(tail(VIP_LOG, 35))
    try:
        for _ in range(30):
            await asyncio.sleep(6)
            cur = "\n".join(tail(VIP_LOG, 35))
            if cur != last:
                last = cur
                await q.edit_message_text(html_cut(log_text()), parse_mode="HTML", reply_markup=LOG_KB, disable_web_page_preview=True)
    except asyncio.CancelledError: pass
    except Exception as e: log.info("live log stopped: %s", e)   # flood/silinen mesaj -> sessizce dur
    finally:
        if LIVE.get(uid) is asyncio.current_task(): LIVE.pop(uid, None)

def html_cut(t, n=4000):
    """Telegram sınırı için kısaltır; açık kalan HTML etiketlerini kapatır."""
    if len(t) <= n: return t
    t = t[:n - 60]
    if "<" in t[t.rfind(">") + 1:]: t = t[:t.rfind("<")]   # yarım etiket
    stack = []
    for m in re.finditer(r"<(/?)([a-z\-]+)[^>]*>", t):
        if m.group(1): stack and stack[-1] == m.group(2) and stack.pop()
        else: stack.append(m.group(2))
    return t + "…" + "".join(f"</{x}>" for x in reversed(stack))

def _w(t):
    """Telegram'da yaklaşık görünür genişlik (emoji ~2 harf)."""
    return sum(0 if ch in "\ufe0f\u200d" else 2 if ord(ch) >= 0x2190 else 1 for ch in t)

def fit_kb(t, kb):
    """Butonlar mesaj balonundan genişse (taşma) ilk satırın sonuna görünmez boşluk ekler."""
    try: rows = kb.inline_keyboard if kb else ()
    except Exception: return t
    need = max((sum(_w(b.text) + 4 for b in r) for r in rows), default=0)
    plain = html.unescape(re.sub(r"<[^>]+>", "", t)).split("\n")
    have = max((_w(x) + (3 if "<blockquote" in t else 0) for x in plain), default=0)
    if have >= need: return t
    first, sep, rest = t.partition("\n")
    add = min(need, 34) - _w(html.unescape(re.sub(r"<[^>]+>", "", first)))
    return first + "\u2800" * max(0, add) + sep + rest if add > 0 else t

async def safe_edit(q, text, kb=None):
    try:
        await q.edit_message_text(html_cut(text), parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    except BadRequest as e:
        if "not modified" not in str(e).lower(): log.warning("edit: %s", e)

async def notify_founders(app, text, kb=None):
    for fid in ADMINS:
        try: await app.bot.send_message(chat_id=fid, text=text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb)
        except Exception as e: log.warning("notify: %s", e)

def prompt(title, text, cancel_to, uid=None):
    return f"{title}\n<blockquote>{text}</blockquote>", back(cancel_to, L(uid, "✖️ İptal", "✖️ Отмена") if uid else "✖️ İptal")

DAYS = [1, 3, 7, 15, 30]
NUM_ASK = {   # ne soruluyor: (başlık, soru, hazır butonlar, birim)
    "nk_days":  ("⏳ <b>Kod süresi</b>", "Kod kaç gün geçerli olsun?", DAYS, "g"),
    "sa_days":  ("⏳ <b>Alt admin süresi</b>", "Kaç gün alt admin kalsın?", DAYS, "g"),
    "sa_limit": ("🎟 <b>Kod limiti</b>", "En fazla kaç kod oluşturabilsin?", [1, 3, 5, 10, 20], ""),
    "sa_ext":   ("⏳ <b>Süre uzat</b>", "Kaç gün uzatılsın?", DAYS, "g"),
    "sa_lim":   ("🎟 <b>Kod limiti</b>", "Yeni limit kaç olsun?", [1, 3, 5, 10, 20], ""),
    "ping_max": ("⏱ <b>Ping sınırı</b>", "Telefon testinde en fazla kaç ms ping'li kodlar listeye girsin? (300–6000)\nDaha yavaşlar Happ'te çoğu zaman n/a görünür.", [800, 1000, 1500, 2000, 3000], " ms"),
    "ip_need":  ("🚨 <b>Yeni IP eşiği</b>", "Kaç yeni IP görülünce bütün kodlar yenilensin? (1–50)", [1, 2, 3, 4, 5], ""),
    "hp_limit": ("🔒 <b>Cihaz limiti</b>", "Bu kod en fazla kaç cihaza kurulabilsin? (1–100)", [1, 2, 3, 5, 10], "📱"),
}

def ask_num(uid, what, info="", **ctx):
    """Sayı sorar: hazır butonlar + elle yazma. Cevap on_num'a gider."""
    title, q, vals, unit = NUM_ASK[what]
    hint = "Butona bas ya da sayı yaz."
    if what == "nk_days" and is_ru(uid):
        title, q, unit, hint = "⏳ <b>Срок кода</b>", "Сколько дней будет действовать код?", "д", "Нажмите кнопку или напишите число."
    STATE[uid] = {"action": "num", "what": what, **ctx}
    btns = [B(f"{v}{unit}", f"num:{v}", "primary" if v == vals[2] else None) for v in vals]
    rows = [btns[:3], btns[3:]]
    if what == "nk_days" and uid in ADMINS: rows.append([B("♾ Süresiz", "num:0", "success")])
    rows.append([B(L(uid, "✖️ İptal", "✖️ Отмена"), "sa_menu" if what.startswith("sa_") else ("admin" if uid in ADMINS else "menu"))])
    return f"{title}\n<blockquote>{info}{q}\n<i>{hint}</i></blockquote>", KB(rows)

def create_result(res, err, name, uid=None):
    ru = bool(uid) and is_ru(uid)
    if not res:
        if ru: err = re.sub(r"^Limit doldu \((\d+) kod\).*", r"Лимит исчерпан (\1 кодов). Удалите один, чтобы освободить место.", err).replace("Boş Drive dosyası yok!", "Нет свободного места для кода.").replace("Drive'a yazılamadı (loglara bak)", "Не удалось записать на Drive.")
        return f"⚠️ {esc(err)}", back("menu", "◀️ Меню" if ru else "◀️ Menü")
    kid, fid = res
    left = left_txt(load_db()['subs'].get(kid, {}).get('expires'), ru)
    if ru:
        return (f"✅ <b>Код создан!</b>\n<blockquote>🎟 <b>{esc(name)}</b>\n⏳ Срок  <b>{left}</b></blockquote>\n"
                f"🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>\n<code>{esc(user_link(fid))}</code>"
                + (f"\n\n🔓 <b>Открытая ссылка</b> <i>(только вы)</i>\n<code>{esc(sub_link(fid))}</code>" if uid in ADMINS else ""),
                KB([[B("🎟 К коду", f"kv:{kid}", "primary"), B("◀️ Меню", "menu")]]))
    return (f"✅ <b>Kod oluşturuldu!</b>\n<blockquote>🎟 <b>{esc(name)}</b>\n⏳ Süre  <b>{left}</b></blockquote>\n"
            f"🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>\n<code>{esc(user_link(fid))}</code>"
            + (f"\n\n🔓 <b>Açık link</b> <i>(sadece sen)</i>\n<code>{esc(sub_link(fid))}</code>" if uid in ADMINS else ""),
            KB([[B("🎟 Koda Git", f"kv:{kid}", "primary"), B("◀️ Menü", "menu")]]))

async def on_num(c, uid, st, n, send, who=""):
    """send(text, kb): mesajı düzenler ya da yeni mesaj atar."""
    what = st["what"]
    if (what.startswith("sa_") or what in ("ip_need", "ping_max")) and uid not in ADMINS: return
    lo = 0 if what == "nk_days" and uid in ADMINS else 300 if what == "ping_max" else 1
    hi = 500 if what in ("sa_limit", "sa_lim") else 100 if what == "hp_limit" else 50 if what == "ip_need" else 6000 if what == "ping_max" else 3650
    if not (lo <= n <= hi):   # butonlarla birlikte tekrar sor
        ctx = {k: v for k, v in st.items() if k not in ("action", "what")}
        await send(*ask_num(uid, what, L(uid, f"⚠️ {lo} ile {hi} arasında bir sayı.\n", f"⚠️ Число от {lo} до {hi}.\n"), **ctx)); return
    if what == "nk_days":
        res, err = await asyncio.to_thread(create_vip, st["name"], uid, n or None)
        if res: audit(uid, f"create {res[0]} {st['name']} {n or '∞'}g")
        if res and st.get("happ"):   # limitli kod: süreden sonra cihaz limiti (API yoksa siteden yapıştırma)
            if all(happ_creds()): await send(*ask_num(uid, "hp_limit", f"✅ <b>{esc(st['name'])}</b> oluşturuldu.\n", kid=res[0]))
            else: await send(*happ_paste_prompt(uid, res[0]))
            return
        if res: await asyncio.to_thread(user_link, res[1])   # şifreli link önceden
        await send(*create_result(res, err, st["name"], uid))
        if res and uid not in ADMINS:
            await notify_founders(c.application, f"🔔 Alt admin <b>{esc(who)}</b> (<code>{uid}</code>) kod oluşturdu: <code>{esc(st['name'])}</code> · {n} gün")
    elif what == "ping_max":
        mutate(lambda d: d.__setitem__("ping_max", n)); audit(uid, f"ping_max {n}")
        start_refresh(c.application, f"⏱ Ping sınırı {n} ms oldu")
        await send(f"✅ <b>Ping sınırı kaydedildi</b>\n<blockquote>Telefon testinde <b>{n} ms</b>'den yavaş kodlar listeye girmez (en az {PING_KEEP} kod hep kalır). Kodlar şimdi yeniden yazılıyor.</blockquote>\n\n" + admin_text(uid), admin_kb(uid))
    elif what == "ip_need":
        mutate(lambda d: d.__setitem__("ip_need", n)); audit(uid, f"ip_need {n}"); vlog(f"🚨 IP eşiği değişti: en az {n} yeni IP")
        await send("✅ <b>IP eşiği kaydedildi</b>\n<blockquote>En az <b>" + str(n) + "</b> yeni IP görülünce bütün kodlar yenilenir.</blockquote>\n\n" + admin_text(uid), admin_kb(uid))
    elif what == "hp_limit" and uid in ADMINS:
        kid = st["kid"]
        try: link, enc = await asyncio.to_thread(happ_make, kid, n)
        except RuntimeError as e:
            await send(f"⚠️ <b>Happ limitli link oluşturulamadı</b>\n<blockquote>{esc(str(e))}</blockquote>" + ("\n<i>Happ API'si Free planda kapalı. Linki happ-proxy.com'da oluşturup Install code'u «✍️ Siteden Yapıştır» ile ekle.</i>" if "subscription" in str(e).lower() else ""),
                       KB([[B("✍️ Siteden Yapıştır", f"hlp:{kid}", "primary")], [B("🎟 Koda Git", f"kv:{kid}"), B("◀️ Admin", "admin")]])); return
        audit(uid, f"happ limit {kid} {n}")
        await send(f"✅ <b>Limitli link hazır</b>\n<blockquote>📱 En fazla <b>{n}</b> cihaz" + ("" if enc else "\n⚠️ Şifrelenemedi: kullanıcı limiti linkten silebilir.") + "</blockquote>\n"
                   f"🔗 <b>Happ linki</b> <i>(dokun → kopyala)</i>\n<code>{esc(link)}</code>", KB([[B("🎟 Koda Git", f"kv:{kid}", "primary"), B("◀️ Admin", "admin")]]))
    elif what == "sa_days":
        t, kb = ask_num(uid, "sa_limit", f"👮 <code>{st['nid']}</code> · ⏳ {n} gün\n", nid=st["nid"], days=n)
        await send(t, kb)
    elif what == "sa_limit":
        nid, days = st["nid"], st["days"]
        def f(d):
            e = d.setdefault("sub_admins", {}).get(str(nid), {})
            old = bool(e)
            e.update({"expires": time.time() + days * 86400, "limit": n, "added": e.get("added", time.time())})
            e.pop("warned", None); e.pop("ended", None)
            d["sub_admins"][str(nid)] = e
            return old
        old = mutate(f)
        audit(uid, f"sa_add {nid} {days}g limit={n}")
        await send(f"✅ <b>Alt admin {'güncellendi' if old else 'eklendi'}</b>\n<blockquote>👮 <code>{nid}</code>\n⏳ {days} gün  ·  🎟 en fazla {n} kod</blockquote>", back("sa_menu"))
    elif what == "gift_days" and uid in ADMINS:
        tid_ = st["target"]
        e = load_db().get("users", {}).get(str(tid_), {})
        res, err = await asyncio.to_thread(make_code_for, tid_, f"{short(e.get('name') or 'VPN', 20)} 🎁", n, "gift")
        if not res: await send(f"⚠️ {esc(err)}", back("admin")); return
        ulog("gift", f"🎁 Admin kod verdi: {e.get('name')} ({tid_}) · {n} gün")
        audit(uid, f"gift {tid_} {n}g")
        lg = lang_of(load_db(), tid_)
        try: await c.bot.send_message(tid_, tr(lg, "gift", left=left_txt(load_db()["subs"][res[0]].get("expires"), lg == "ru"), link=esc(user_link(res[1]))), parse_mode="HTML")
        except Exception: pass
        await send(f"✅ <b>{n} günlük kod verildi</b> ve kullanıcıya gönderildi.", KB([[B("👤 Kullanıcıya Dön", f"uv:{tid_}")]]))
    elif what == "add_days" and uid in ADMINS:
        s_ = await asyncio.to_thread(extend_code, st["kid"], n)
        if not s_: await send("⚠️ Kod bulunamadı.", back("admin")); return
        ow = s_.get("owner_id"); lg = lang_of(load_db(), ow)
        ulog("add", f"⏳ Admin süre ekledi: {name_of(s_, st['kid'])} · +{n} gün")
        audit(uid, f"add_days {st['kid']} {n}")
        if ow and ow not in ADMINS:
            try: await c.bot.send_message(ow, tr(lg, "added", name=name_of(s_, st["kid"]), left=left_txt(s_.get("expires"), lg == "ru")))
            except Exception: pass
        await send(f"✅ +{n} gün eklendi. Kalan: <b>{left_txt(s_.get('expires'))}</b>", KB([[B("👤 Kullanıcıya Dön", f"uv:{ow}")]] if ow else [[B("◀️ Admin", "admin")]]))
    elif what in ("sa_ext", "sa_lim"):
        sid = st["sid"]
        def f(d):
            e = d.get("sub_admins", {}).get(sid)
            if not e: return None
            if what == "sa_ext":
                e["expires"] = max(time.time(), float(e.get("expires", 0))) + n * 86400
                e.pop("warned", None); e.pop("ended", None)
            else: e["limit"] = n
            return e
        e = mutate(f)
        audit(uid, f"{what} {sid} {n}")
        if not e: await send("⚠️ Alt admin bulunamadı.", back("sa_menu")); return
        msg = f"✅ Süre uzatıldı, yetkiler açık. Kalan: <b>{left_txt(e['expires'])}</b>" if what == "sa_ext" else f"✅ Limit: <b>{n}</b> kod"
        await send(msg, back("sa_menu"))
        if what == "sa_ext":
            try: await c.bot.send_message(chat_id=int(sid), text=L(int(sid), f"✅ Panelin {n} gün uzatıldı.", f"✅ Ваша панель продлена на {n} дн."))
            except Exception: pass

def bulk_apply(field, val):
    """Bütün kodların duyurusunu/başlığını değiştirir ve Drive'a yazar. val None ise başlık = buton adı."""
    def f(db):
        items = []
        for kid, s in db["subs"].items():
            if field == "title": s["title"] = val if val is not None else btn_name(s, kid)
            else: s["announce"] = ""                       # toplu duyuru: koda özel duyurular temizlenir
            if s.get("file_id") and not is_exp(s): items.append((s["file_id"], name_of(s, kid), s))
        if field == "announce": db["g_announce"] = val
        items = [(fid, t, eff_ann(db, x)) for fid, t, x in items]
        return items, list(db["template"])
    items, tpl = mutate(f)
    return push_all(items, tpl), len(items)


# ───────── HANDLERS ─────────
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    if not is_admin(uid) or is_banned(uid): return await pub_start(u, c)
    STATE.pop(uid, None)
    if uid not in ADMINS:
        await asyncio.to_thread(touch_user, u.effective_user)
        miss = await missing_channels(c.bot, uid)
        if miss:
            t, kb = join_view(lang_of(load_db(), uid), miss)
            await u.message.reply_text(t, parse_mode="HTML", reply_markup=kb); return
    if uid not in ADMINS:
        nm = u.effective_user.full_name or ""
        mutate(lambda d: d["sub_admins"].get(str(uid), {}).__setitem__("name", nm) if d["sub_admins"].get(str(uid), {}).get("name") != nm else None)
    await show_home(c, uid)

async def cmd_id(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(f"ID: {u.effective_user.id}")

async def msg_handler(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    if not is_admin(uid) or is_banned(uid) or (uid not in ADMINS and STATE.get(uid, {}).get("action") == "u_panel"): return await pub_msg(u, c)
    if uid not in STATE: return
    txt = (u.message.text or "").strip()
    st = STATE.pop(uid)
    act = st.get("action")
    try:
        if act == "new_key":
            name = txt[:60]
            if not name: return
            t, kb = ask_num(uid, "nk_days", f"🎟 <b>{esc(name)}</b>\n", name=name, **({"happ": True} if st.get("happ") else {}))
            await u.message.reply_text(t, parse_mode="HTML", reply_markup=kb)

        elif act == "num":
            m = re.fullmatch(r"\s*(\d{1,4})\s*", txt)
            if not m:
                STATE[uid] = st
                await u.message.reply_text(L(uid, "⚠️ Sadece sayı yaz (ör. 7).", "⚠️ Напишите только число (напр. 7)."))
                return
            async def send(t, kb): await u.message.reply_text(t, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
            await on_num(c, uid, st, int(m.group(1)), send, u.effective_user.full_name)

        elif act == "sa_add":
            if not txt.isdigit():
                await u.message.reply_text("⚠️ Sayısal Telegram ID gönder.", reply_markup=back("sa_menu"))
                return
            nid = int(txt)
            if nid in ADMINS:
                await u.message.reply_text("ℹ️ Bu ID zaten kurucu.", reply_markup=back("sa_menu"))
                return
            t, kb = ask_num(uid, "sa_days", f"👮 <code>{nid}</code>\n", nid=nid)
            await u.message.reply_text(t, parse_mode="HTML", reply_markup=kb)

        elif act == "src_add":
            lines = [x.strip() for x in txt.split() if x.strip().startswith("http")]
            if not lines:
                await u.message.reply_text("⚠️ Geçerli link yok.", reply_markup=back("sources"))
                return
            def f(db):
                n = 0
                for l in lines:
                    if l not in db["sources"]: db["sources"].append(l); n += 1
                return n
            n = mutate(f)
            audit(uid, f"src_add n={n}")
            if n: start_refresh(c.application, "abonelik eklendi")
            await u.message.reply_text(f"✅ {n} abonelik eklendi." + (" Bütün aboneliklerin kodları şimdi yeniden yazılıyor, bitince bildirim gelecek." if n else ""), reply_markup=back("sources"))

        elif act == "src_edit":
            new = next((x for x in txt.split() if x.startswith("http")), None)
            if not new:
                await u.message.reply_text("⚠️ Geçerli link yok.", reply_markup=back("sources"))
                return
            def f(db):
                for i, s0 in enumerate(db["sources"]):
                    if hashlib.md5(s0.encode()).hexdigest()[:8] == st["h"]:
                        db["sources"][i] = new; return True
                return False
            ok = mutate(f)
            if ok:
                audit(uid, "src_edit")
                start_refresh(c.application, "abonelik değiştirildi")
            await u.message.reply_text("✅ Abonelik değiştirildi. Kodlar şimdi yeni abonelikten çekilip yazılıyor, bitince bildirim gelecek." if ok else "⚠️ Abonelik bulunamadı.", reply_markup=back("sources"))

        elif act in ("bulk_ann", "bulk_title"):
            if act == "bulk_title" and txt != "-" and not txt: return
            val = txt[:60] if act == "bulk_title" else txt
            show = ("<i>(her kodun başlığı kendi buton adı olur)</i>" if txt == "-" else f"<code>{esc(val)}</code>") if act == "bulk_title" \
                else ("<i>(bütün duyurular silinir)</i>" if txt == "-" else f"<i>{esc(val)}</i>")
            STATE[uid] = {"action": "confirm", "what": act, "val": None if txt == "-" and act == "bulk_title" else ("" if txt == "-" else val)}
            n = len(load_db()["subs"])
            await u.message.reply_text(
                f"{'📢' if act == 'bulk_ann' else '🏷'} <b>Onay</b>\n<blockquote>{show}</blockquote>\n"
                f"<b>{n}</b> kodun hepsine uygulanacak ve Drive'a yazılacak.",
                parse_mode="HTML", reply_markup=KB([[B("✅ Uygula", "bulk_yes", "success"), B("✖️ İptal", "menu", "danger")]]))

        elif act == "ch_add":
            fo = getattr(u.message, "forward_origin", None)
            msg = await add_channel(c, txt, getattr(fo, "chat", None))
            await u.message.reply_text(msg, parse_mode="HTML", reply_markup=back("chans"))

        elif act == "mk_price":
            try: v = float(txt.replace(",", ".").lower().replace("tmt", "").strip())
            except Exception: v = 0
            if not (1 <= v <= 10000):
                STATE[uid] = st; await u.message.reply_text("⚠️ 1 ile 10000 arası bir sayı yaz (aylık TMT, ör. 100)."); return
            pr = price_from_month_tmt(v)
            mutate(lambda d: ensure_own(d)[OWN_LID].__setitem__("price", pr))
            audit(uid, f"own_price {v} TMT/ay")
            t, kb = mkt_admin_view(); await u.message.reply_text("✅ Fiyat kaydedildi.\n\n" + t, parse_mode="HTML", reply_markup=kb)

        elif act == "own_desc":
            mutate(lambda d: ensure_own(d)[OWN_LID].__setitem__("desc", txt[:600]))
            audit(uid, "own_desc")
            t, kb = mkt_admin_view(); await u.message.reply_text("✅ Açıklama kaydedildi.\n\n" + t, parse_mode="HTML", reply_markup=kb)

        elif act == "bal_adj":
            mode = st.get("mode", "+")
            try: v = int(round(float(txt.replace(",", ".").replace("$", "").lower().replace("usdt", "").strip()) * UM))
            except Exception: v = -1
            if v < 0 or (v == 0 and mode != "=") or v > 100_000 * UM:
                STATE[uid] = st; await u.message.reply_text("⚠️ Pozitif bir sayı yaz, ör. 2 ya da 0.5"); return
            tid_ = st["target"]
            def f(d):
                e = d["users"].setdefault(str(tid_), {}); old = e.get("bal", 0)
                e["bal"] = old + v if mode == "+" else max(0, old - v) if mode == "-" else v
                return old, e["bal"]
            old, nb = mutate(f)
            ulog("m_bal", f"💰 Admin bakiye {'ekledi' if mode == '+' else 'düştü' if mode == '-' else 'ayarladı'}: {tid_} · {fmt_u(old)} → {fmt_u(nb)} USDT")
            audit(uid, f"bal_adj {tid_} {mode}{v} {old}->{nb}")
            t, kb = user_view(tid_); await u.message.reply_text(f"✅ Yeni bakiye: {fmt_u(nb)} USDT\n\n" + t, parse_mode="HTML", reply_markup=kb)

        elif act == "u_search":
            found = find_users(txt)
            if not found:
                STATE[uid] = {"action": "u_search"}
                await u.message.reply_text("⚠️ Bulunamadı. Başka bir ID / @kullanıcıadı / isim dene.", reply_markup=back("admin")); return
            if len(found) == 1:
                t, kb = user_view(found[0])
                await u.message.reply_text(t, parse_mode="HTML", reply_markup=kb); return
            us = load_db()["users"]
            await u.message.reply_text(f"🔎 <b>{len(found)} sonuç</b>", parse_mode="HTML",
                                       reply_markup=KB([[B(f"{short(us[k].get('name') or k, 20)} · {k}", f"uv:{k}")] for k in found] + [[B("◀️ Admin", "admin")]]))

        elif act == "ban_find":
            found = [k for k in find_users(txt) if int(k) not in ADMINS]
            if not found:
                STATE[uid] = st; await u.message.reply_text("⚠️ Bulunamadı. Başka bir ID / @kullanıcıadı / isim dene.", reply_markup=back("ban_menu")); return
            us = load_db()["users"]
            await u.message.reply_text("🚫 <b>Kimi banlayalım?</b>", parse_mode="HTML",
                                       reply_markup=KB([[B(f"{short(us[k].get('name') or k, 20)} · {k}", f"bnq:{k}")] for k in found[:10]] + [[B("◀️ Geri", "ban_menu")]]))

        elif act == "mk_rej":
            lid = st["lid"]; why = "" if txt.strip() == "-" else txt.strip()[:300]
            def f(d):
                L = d.get("market", {}).get(lid)
                if not L or L.get("own") or L.get("status") not in ("pending", "live", "suspended"): return None
                L["status"] = "rejected"; L["removed_ts"] = time.time(); L["removed_why"] = "admin"
                return L.get("owner"), L.get("title")
            r = mutate(f)
            if not r: await u.message.reply_text("⚠️ İlan bulunamadı ya da zaten kapalı.", reply_markup=back("mk_admin")); return
            audit(uid, f"mk_reject {lid}")
            ulog("m_rej", f"❌ Admin ilanı reddetti: {r[1]} · satıcı {r[0]}" + (f" · {why}" if why else ""))
            lg = lang_of(load_db(), r[0])
            try: await c.bot.send_message(r[0], tr(lg, "m_rejected", title=esc(r[1] or "?"), why=esc(why) if why else tr(lg, "rj_admin")), parse_mode="HTML")
            except Exception: pass
            await u.message.reply_text("✅ İlan reddedildi, satıcıya bildirildi.", reply_markup=back("mk_admin"))

        elif act == "hp_paste":
            kid = st["kid"]
            try: link, enc = await asyncio.to_thread(happ_attach, kid, txt)
            except RuntimeError as e:
                STATE[uid] = st; await u.message.reply_text(f"⚠️ {esc(str(e))} Install code'u (ör. <code>6P0hVao1fG5e</code>) tekrar yapıştır.", parse_mode="HTML", reply_markup=back(f"kv:{kid}")); return
            audit(uid, f"happ paste {kid}")
            await u.message.reply_text("✅ <b>Limitli link hazır</b>" + ("" if enc else "\n⚠️ Şifrelenemedi: kullanıcı limiti linkten silebilir.") +
                                       f"\n🔗 <b>Happ linki</b> <i>(dokun → kopyala)</i>\n<code>{esc(link)}</code>", parse_mode="HTML",
                                       reply_markup=KB([[B("🎟 Koda Git", f"kv:{kid}", "primary"), B("◀️ Admin", "admin")]]))

        elif act == "hp_set":
            try: await u.message.delete()   # anahtar sohbette kalmasın
            except Exception: pass
            m_ = re.fullmatch(r"\s*([A-Za-z0-9]{8})\s+([-_A-Za-z0-9]{32})\s*", txt)
            if not m_:
                STATE[uid] = st; await u.message.reply_text("⚠️ Biçim: <code>Provider_ID Auth_key</code> (8 + 32 karakter, arada boşluk).", parse_mode="HTML", reply_markup=back("hp")); return
            prov, key = m_.groups()
            try: await asyncio.to_thread(happ_call, "list-install", prov, key, id=1); note = ""
            except RuntimeError as e:
                if "auth" in str(e).lower():
                    await u.message.reply_text("⚠️ Happ bu bilgileri kabul etmedi (Auth error).", reply_markup=back("hp")); return
                note = f"\n⚠️ Happ: <code>{esc(str(e))}</code>"
            await asyncio.to_thread(set_env, "HAPP_PROVIDER", prov); await asyncio.to_thread(set_env, "HAPP_AUTH", key)
            audit(uid, "happ set")
            t, kb = happ_view(); await u.message.reply_text("✅ Happ hesabı bağlandı." + note + "\n\n" + t, parse_mode="HTML", reply_markup=kb)

        elif act == "cp_set":
            try: await u.message.delete()   # token sohbette kalmasın
            except Exception: pass
            tok = txt.strip()
            try: me = await asyncio.to_thread(crypto_call, "getMe", tok)
            except Exception as e:
                await u.message.reply_text(f"⚠️ Token çalışmadı: <code>{esc(str(e)[:150])}</code>", parse_mode="HTML", reply_markup=back("cp")); return
            await asyncio.to_thread(set_env, "CRYPTO_PAY_TOKEN", tok)
            audit(uid, "crypto token set")
            await u.message.reply_text(f"✅ CryptoBot bağlandı: <b>{esc(me.get('name'))}</b>\nKullanıcılar artık USDT ile ödeyebilir.", parse_mode="HTML", reply_markup=back("admin"))

        elif act == "pay_set":
            v = "" if txt == "-" else txt[:500]
            mutate(lambda d: d.__setitem__("pay_info", v))
            audit(uid, "pay_info")
            await u.message.reply_text("✅ Ödeme bilgisi kaydedildi." if v else "✅ Ödeme bilgisi silindi.", reply_markup=back("admin"))

        elif act == "bcast":
            if not txt: return
            STATE[uid] = {"action": "bcast_ok", "text": txt[:3500]}
            n = sum(1 for k in load_db().get("users", {}) if int(k) not in ADMINS)
            await u.message.reply_text(f"📣 <b>Onay</b>\n<blockquote>{esc(short(txt, 600))}</blockquote>\n<b>{n}</b> kullanıcıya gönderilecek.", parse_mode="HTML",
                                       reply_markup=KB([[B("✅ Gönder", "bcast_yes", "success"), B("✖️ İptal", "admin", "danger")]]))

        elif act in ("title", "bname", "announce"):
            kid = st["kid"]
            val = txt[:60] if act != "announce" else ("" if txt == "-" else txt)
            def f(db):
                s = db["subs"].get(kid)
                if not s: return None
                if act == "title": s["title"] = val
                elif act == "bname": s["name"] = val
                else: s["announce"] = val
                return s.get("file_id"), name_of(s, kid), eff_ann(db, s), list(db["template"])
            r = mutate(f)
            if not r:
                await u.message.reply_text(L(uid, "⚠️ Kod bulunamadı.", "⚠️ Код не найден."), reply_markup=back("my_keys"))
                return
            if act == "bname":
                msg = L(uid, "✅ Buton adı değişti. <i>(Abonelik başlığına dokunulmadı.)</i>", "✅ Имя кнопки изменено. <i>(Заголовок подписки не менялся.)</i>")
            else:
                ok = await asyncio.to_thread(lambda: sync_file(new_service(), *r))
                msg = L(uid, "✅ Kaydedildi ve Drive'a yazıldı.", "✅ Сохранено.") if ok else L(uid, "⚠️ Kaydedildi ama Drive'a yazılamadı.", "⚠️ Сохранено, но не удалось записать на Drive.")
            await u.message.reply_text(msg, parse_mode="HTML", reply_markup=KB([[B(L(uid, "🎟 Koda Dön", "🎟 К коду"), f"kv:{kid}", "primary")]]))
    except Exception as e:
        log.exception("msg_handler")
        await send_error(c, uid, f"mesaj:{act}", e)

FOUNDER_ONLY = {"ban_menu", "ban_find", "hp", "hp_set", "hp_del", "hp_new", "ref_test", "mk_admin", "mk_price", "mk_oph", "mk_ods", "mk_odr", "bal_find", "usearch", "rep_today", "rep_yday", "tickets_bug", "t_cancel", "tickets", "cp_test", "cp", "cp_set", "cp_del", "ul_open", "stats", "chans", "ch_add", "pay_set", "bcast", "bcast_yes", "rollback", "rollback_yes", "auto_ann", "toggle_sys", "mk_rev", "ad_post", "ip_need", "ping_max", "admin", "sources", "s_add", "logs", "upd_now", "get_zip", "sa_menu", "sa_add", "bulk_ann", "bulk_title", "bulk_yes"}
OWNED = ("kv", "kt", "kn", "ka", "kd", "kdy")   # alt admin sadece kendi kodunda
def src_find(db, h): return next((s for s in db["sources"] if hashlib.md5(s.encode()).hexdigest()[:8] == h), None)

async def cb(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    uid = q.from_user.id
    a = q.data
    if a and a.startswith("ad:"): return await ad_cb(q, a.split(":", 1)[1])   # reklam postundaki dil butonu (herkes, başka sohbetlerde de)
    if a.startswith("u_") or not is_admin(uid) or is_banned(uid): return await pub_cb(u, c)
    if uid not in ADMINS:
        miss = await missing_channels(c.bot, uid)
        if miss:
            await q.answer(); await safe_edit(q, *join_view(lang_of(load_db(), uid), miss)); return
    if uid not in ADMINS and (a in FOUNDER_ONLY or a.startswith(("sv:", "se:", "sd:", "sa_del:", "sa_ext:", "sa_lim:", "kx:", "kxs:", "ul:", "chd:", "ord_ok:", "ord_no:", "t_rep:", "t_close:", "tv:", "ug:", "ux:", "uxc:", "ub:", "uv:", "ubal:", "mk_l:", "mk_ok:", "mk_rm:", "mk_ph:", "mk_real:", "mk_fake:", "mk_fakey:", "mk_rv:",  "mk_pok:", "mk_pno:", "mk_prj:", "hl:", "hlp:", "ubn:", "bnd:", "bnq:"))):
        await q.answer(L(uid, "⛔ Erişim yok", "⛔ Нет доступа"), show_alert=True); return
    if a not in ("toggle_sys", "upd_now"):
        await q.answer()
    if a != "logs" and uid in LIVE:
        LIVE.pop(uid).cancel()
    if a not in ("menu", "tickets", "tickets_bug") and not a.startswith("my_keys"): q = await off_banner(c, q)   # banner'lı menüden başka ekrana: yazı mesajına geç
    try: db = load_db()
    except Exception as e:
        await safe_edit(q, f"❌ {esc(e)}", back("menu", "◀️ Menü")); return

    if uid not in ADMINS and ":" in a and a.split(":", 1)[0] in OWNED:
        s = db["subs"].get(a.split(":", 1)[1])
        if not s or s.get("owner_id") != uid:
            await safe_edit(q, L(uid, "⛔ Bu kod senin değil.", "⛔ Это не ваш код."), back("my_keys")); return

    if a == "menu":
        STATE.pop(uid, None)
        await show_home(c, uid, getattr(q, "message", None), send=lambda t, kb: safe_edit(q, t, kb))

    elif a == "lang":
        await safe_edit(q, *lang_pick("p"))

    elif a == "ul_open" or a.startswith("ul:"):
        await safe_edit(q, *ulog_view(None if a == "ul_open" else int(a.split(":", 1)[1])))

    elif a == "stats":
        await safe_edit(q, await asyncio.to_thread(stats_text), KB([[B("🔄 Yenile", "stats", "primary"), B("◀️ Admin", "admin")]]))

    elif a == "chans":
        await safe_edit(q, *channels_view())

    elif a == "ch_add":
        STATE[uid] = {"action": "ch_add"}
        await safe_edit(q, *prompt("📢 <b>Kanal Ekle</b>", "1) Botu kanala <b>admin</b> olarak ekle.\n2) Kanalın <code>@kullanıcıadı</code>'nı yaz ya da kanaldan bir mesajı buraya ilet.", "chans"))

    elif a.startswith("chd:"):
        i = int(a.split(":", 1)[1])
        def f(d):
            chs = d.get("channels", [])
            return chs.pop(i) if 0 <= i < len(chs) else None
        ch = mutate(f); JOINED.clear()
        if ch: audit(uid, f"channel_del {ch['id']}")
        await safe_edit(q, *channels_view())

    elif a == "mk_admin":
        await safe_edit(q, *mkt_admin_view())

    elif a == "hp":
        await safe_edit(q, *happ_view())

    elif a == "hp_set":
        STATE[uid] = {"action": "hp_set"}
        await safe_edit(q, *prompt("🔑 <b>Happ Bilgileri</b>", "happ-proxy.com → Profil sayfasındaki <b>Provider ID</b> ve <b>Auth key</b>'i aralarında boşluk bırakarak tek mesajda yaz:\n<code>Provider_ID Auth_key</code>\n<i>Mesajın hemen silinir.</i>", "hp"))

    elif a == "hp_del":
        await asyncio.to_thread(set_env, "HAPP_PROVIDER", ""); await asyncio.to_thread(set_env, "HAPP_AUTH", "")
        audit(uid, "happ del"); await safe_edit(q, *happ_view())

    elif a == "hp_new":
        STATE[uid] = {"action": "new_key", "happ": True}
        await safe_edit(q, *prompt("🔒 <b>Limitli Kod Oluştur</b>", "Kod için bir isim gönder. Sonra süre, en son cihaz limiti sorulacak.", "hp"))

    elif a.startswith("hl:"):
        kid = a.split(":", 1)[1]
        if not all(happ_creds()): await safe_edit(q, *happ_paste_prompt(uid, kid)); return
        t, kb = ask_num(uid, "hp_limit", f"🎟 <b>{esc(short(btn_name(db['subs'].get(kid, {}), kid), 40))}</b>\n", kid=kid)
        kb = KB(kb.inline_keyboard[:-1] + ((B("✍️ Siteden Yapıştır", f"hlp:{kid}"),),) + kb.inline_keyboard[-1:])
        await safe_edit(q, t, kb)

    elif a.startswith("hlp:"):
        await safe_edit(q, *happ_paste_prompt(uid, a.split(":", 1)[1]))

    elif a == "ref_test":   # davetle gelen kullanıcının gördüğü soruyu dene
        await safe_edit(q, *captcha_view(lang_of(load_db(), uid), uid, test=True))

    elif a == "mk_price":
        STATE[uid] = {"action": "mk_price"}
        await safe_edit(q, *prompt("💲 <b>Bizim ilanın fiyatı</b>", "Aylık fiyatı TMT olarak yaz (ör. <code>100</code>). Bot dakika başı USDT'yi kendisi hesaplar.", "mk_admin"))

    elif a == "mk_oph":
        STATE[uid] = {"action": "own_photo"}
        await safe_edit(q, *prompt("📷 <b>Bizim ilan fotoğrafı</b>", "Pazardaki kartta görünecek fotoğrafı gönder.", "mk_admin"))

    elif a == "mk_ods":
        STATE[uid] = {"action": "own_desc"}
        await safe_edit(q, *prompt("📝 <b>Bizim ilan açıklaması</b>", "Kartta görünecek açıklamayı yaz. (\"Botun resmi kodu · 7/24 kontrol altında\" satırı her zaman ayrıca görünür.)", "mk_admin"))

    elif a == "mk_odr":
        mutate(lambda d: ensure_own(d)[OWN_LID].update({"desc": OWN_DESC, "photo": None}))
        await safe_edit(q, *mkt_admin_view())

    elif a.startswith("mk_l:"):
        await safe_edit(q, *mkt_admin_detail(a.split(":", 1)[1]))

    elif a.startswith(("mk_pok:", "mk_pno:")):   # satıcı fotoğrafı: onay / uygunsuz (+18 vb.)
        lid = a.split(":", 1)[1]; ok_ = a.startswith("mk_pok:")
        def f(d):
            L = d.get("market", {}).get(lid)
            if not L or L.get("own"): return None
            if ok_: L["photo_ok"] = True; return L.get("owner"), L.get("title"), None
            L["photo"], L["photo_ok"] = None, False
            was = L.get("status")
            if was in ("pending", "live", "suspended"): L["status"] = "removed"; L["removed_ts"] = time.time(); L["removed_why"] = "photo"
            e = d["users"].setdefault(str(L.get("owner")), {}); e["ban_until"] = max(e.get("ban_until", 0), time.time() + PHOTO_BAN_H * 3600)
            return L.get("owner"), L.get("title"), was
        r = mutate(f)
        if not r: await q.answer("⚠️ İlan bulunamadı.", show_alert=True); return
        audit(uid, f"{'photo_ok' if ok_ else 'photo_bad'} {lid}")
        if ok_: await q.answer("✅ Fotoğraf onaylandı, pazarda görünecek.")
        else:
            ulog("m_admin", f"🔞 Uygunsuz fotoğraf: ilan kaldırıldı + {PHOTO_BAN_H} saat bot engeli · {r[1]} · satıcı {r[0]}")
            lg = lang_of(load_db(), r[0])
            try: await c.bot.send_message(r[0], tr(lg, "m_photo_bad", title=esc(r[1] or "?"), h=PHOTO_BAN_H), parse_mode="HTML")
            except Exception: pass
            await q.answer(f"🔞 İlan kaldırıldı, satıcı {PHOTO_BAN_H} saat botu kullanamaz.", show_alert=True)
        try: await q.edit_message_reply_markup(None)
        except Exception: pass

    elif a == "mk_rev":   # 📥 inceleme bekleyen ilanlar
        lg = alang(uid); now_ = time.time(); lst = review_list(db)
        rows = [[B(f"⏳ {wait_txt(lg, now_ - L.get('created', now_))} · {short(L.get('title', '?'), 14)} · {money_tmt(float(L.get('price', 0)) * 43200)} TMT"
                   + (" · 📷" if L.get("photo") and not L.get("photo_ok", True) else ""), f"mk_rv:{lid}")] for lid, L in lst[:20]]
        await safe_edit(q, at(lg, "rev_t", n=len(lst)) if lst else at(lg, "rev_none"), KB(rows + [[B(at(lg, "menu"), "menu")]]))

    elif a.startswith("mk_rv:"):   # tek ilan: fotoğraf + bilgiler + karar butonları
        lid = a.split(":", 1)[1]; L_ = db.get("market", {}).get(lid); lg = alang(uid)
        if not L_: return
        o_ = db["users"].get(str(L_.get("owner")), {}); st_ = L_.get("st") or {}
        who_ = esc(o_.get("name") or "?") + (f" (@{esc(o_['un'])})" if o_.get("un") else "") + f" · <code>{L_.get('owner')}</code>"
        cap_ = at(lg, "rv_cap", title=esc(short(L_.get("title", "?"), 40)), who=who_, m=money_tmt(float(L_.get("price", 0)) * 43200), n=len(L_.get("codes", [])),
                  w=st_.get("work", 0), t=st_.get("tested", 0), c=len(st_.get("cc", [])), wait=wait_txt(lg, time.time() - L_.get("created", time.time())),
                  ph=at(lg, "rv_ph") if L_.get("photo") and not L_.get("photo_ok", True) else "")
        extra = ([[B(at(lg, "ok_hand"), f"mk_ok:{lid}", "success")]] if L_.get("status") == "pending" else []) + [[B(at(lg, "back_rev"), "mk_rev")]]
        kb_ = photo_kb(lid, lg, extra)
        try:
            if L_.get("photo"): await c.bot.send_photo(uid, L_["photo"], caption=cap_, parse_mode="HTML", reply_markup=kb_)
            else: await c.bot.send_message(uid, cap_, parse_mode="HTML", reply_markup=kb_)
        except Exception: await c.bot.send_message(uid, cap_, parse_mode="HTML", reply_markup=kb_)

    elif a.startswith("mk_real:"):   # sadece kurucuya: telefonun gerçek ölçümü
        lid = a.split(":", 1)[1]
        await c.bot.send_message(uid, "📊 <b>Gerçek ölçüm</b> <i>(sadece sen görürsün)</i>\n\n" + await real_report(lid, "tr"), parse_mode="HTML")

    elif a.startswith("mk_fake:"):   # yalan ping: önce onay
        lid = a.split(":", 1)[1]; L_ = db.get("market", {}).get(lid, {}); e_ = db["users"].get(str(L_.get("owner")), {})
        await c.bot.send_message(uid, f"🤥 <b>Yalan ping olarak reddedilsin mi?</b>\n<blockquote>🏷 {esc(L_.get('title', '?'))}\nSatıcının önceki yalan ping sayısı: <b>{e_.get('fake_n', 0)}</b>"
                                 + (" · bir sonraki ilanı zaten 2 kat" if e_.get("fee_x2") else "") + "</blockquote>\n<i>Satıcıya gerçek ping ve ülkeleriyle ayrıntılı red mesajı gider. 2. kez olursa bir sonraki ilanı 2 kat ücretli olur.</i>",
                                 parse_mode="HTML", reply_markup=KB([[B("🤥 Evet, yalan ping", f"mk_fakey:{lid}", "danger")], [B("✖️ Vazgeç", "mk_admin")]]))

    elif a.startswith("mk_fakey:"):
        lid = a.split(":", 1)[1]
        def f(d):
            L = d.get("market", {}).get(lid)
            if not L or L.get("own") or L.get("status") not in ("pending", "live"): return None
            L["status"] = "rejected"; L["removed_ts"] = time.time(); L["removed_why"] = "fake_ping"; L["photo"], L["photo_ok"] = None, False
            e = d["users"].setdefault(str(L.get("owner")), {})
            e["fake_n"] = e.get("fake_n", 0) + 1; x2 = False
            if e["fake_n"] >= 2: e["fee_x2"] = True; e["fake_n"] = 0; x2 = True   # her 2 yalan pingte bir sonraki ilan 2 kat
            return L.get("owner"), L.get("title"), x2
        r = mutate(f)
        if not r: await safe_edit(q, "⚠️ İlan bulunamadı ya da zaten kapalı.", back("mk_admin")); return
        ow, title_, x2 = r; lg = lang_of(load_db(), ow)
        audit(uid, f"fake_ping {lid}"); ulog("m_admin", f"🤥 Yalan ping: ilan reddedildi · {title_} · satıcı {ow}" + (" · sonraki ilan 2 kat" if x2 else ""))
        rep_ = await real_report(lid, lg)
        warn = tr(lg, "fake_x2", fee=fmt_u(MKT_FEE * 2)) if x2 else tr(lg, "fake_warn")
        try: await c.bot.send_message(ow, tr(lg, "fake_rej", title=esc(title_ or "?")) + "\n\n" + rep_ + "\n\n" + warn, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as ex_: log.info("fake msg: %s", ex_)
        await safe_edit(q, f"🤥 <b>Yalan ping: ilan reddedildi</b>\n<blockquote>🏷 {esc(title_ or '?')}\nSatıcıya gerçek ping ve ülkeleriyle mesaj gitti." + ("\n⚠️ 2. kez: bir sonraki ilanı 2 kat ücretli." if x2 else "\nTekrar ederse bir sonraki ilanı 2 kat ücretli olacak.") + "</blockquote>", back("mk_admin"))

    elif a.startswith("mk_prj:"):   # fotoğraf/ilan reddi: ceza yok, sebep yazılabilir
        lid = a.split(":", 1)[1]
        STATE[uid] = {"action": "mk_rej", "lid": lid}
        t, kb = prompt("❌ <b>İlanı reddet</b>", "Sebebini yaz, satıcıya gönderilir. Sebep yazmadan reddetmek için <code>-</code> gönder.\n<i>Ceza / engel yok.</i>", "mk_admin")
        await c.bot.send_message(uid, t, parse_mode="HTML", reply_markup=kb)
        try: await q.edit_message_reply_markup(None)
        except Exception: pass

    elif a.startswith("mk_ph:"):
        L_ = db.get("market", {}).get(a.split(":", 1)[1], {})
        if L_.get("photo"):
            try: await c.bot.send_photo(uid, L_["photo"], caption=f"🏪 {L_.get('title', '')}"[:1000])
            except Exception: pass

    elif a.startswith(("mk_ok:", "mk_rm:")):
        lid = a.split(":", 1)[1]; ok_ = a.startswith("mk_ok:")
        def f(d):
            L = d.get("market", {}).get(lid)
            if not L or L.get("own"): return None
            if ok_ and L["status"] == "pending": L["status"] = "live"; L["live_ts"] = L["last_good"] = time.time(); return L.get("owner"), L["title"]
            if not ok_ and L["status"] in ("pending", "live"): L["status"] = "removed"; L["removed_ts"] = time.time(); L["removed_why"] = "admin"; return L.get("owner"), L["title"]
            return None
        r = mutate(f)
        if r:
            audit(uid, f"{'mk_ok' if ok_ else 'mk_rm'} {lid}")
            ulog("m_admin", f"{'✅ Admin ilanı onayladı' if ok_ else '🗑 Admin ilanı kaldırdı'}: {r[1]} · satıcı {r[0]}")
            if ok_:
                lg = lang_of(load_db(), r[0]); st_ = load_db()["market"][lid].get("st") or {}
                try: await c.bot.send_message(r[0], tr(lg, "m_approved", title=esc(r[1]), ncc=len(st_.get("cc", [])), work=st_.get("work", 0), tested=st_.get("tested", 0)), parse_mode="HTML")
                except Exception: pass
        await safe_edit(q, *mkt_admin_view())

    elif a.startswith("ubal:"):
        _, mode, tid_ = a.split(":", 2)
        STATE[uid] = {"action": "bal_adj", "target": int(tid_), "mode": mode}
        head = {"+": "➕ <b>Bakiye Ekle</b>", "-": "➖ <b>Bakiye Düş</b>", "=": "✏️ <b>Bakiyeyi Ayarla</b>"}[mode]
        ask = {"+": "Eklenecek tutarı", "-": "Düşülecek tutarı", "=": "Yeni bakiyeyi"}[mode]
        cur = load_db()["users"].get(tid_, {}).get("bal", 0)
        await safe_edit(q, *prompt(head, f"Şu anki bakiye: <b>{fmt_u(cur)} USDT</b>\n{ask} USDT olarak yaz (ör. <code>2</code> ya da <code>0.5</code>).", f"uv:{tid_}"))

    elif a == "bal_find":
        STATE[uid] = {"action": "u_search"}
        await safe_edit(q, *prompt("💰 <b>Bakiye</b>", "Bakiyesini değiştireceğin kullanıcının Telegram ID'si, @kullanıcıadı ya da ismini yaz.", "admin"))

    elif a in ("rep_today", "rep_yday"):
        a0, a1, lbl = day_bounds(0 if a == "rep_today" else -1)
        t = await asyncio.to_thread(report_text, a0, a1, ("Bugün · " if a == "rep_today" else "Dün · ") + lbl)
        await safe_edit(q, t, KB([[B("📅 Dün" if a == "rep_today" else "📅 Bugün", "rep_yday" if a == "rep_today" else "rep_today"), B("◀️ Admin", "admin")]]))

    elif a == "usearch":
        STATE[uid] = {"action": "u_search"}
        await safe_edit(q, *prompt("🔎 <b>Kullanıcı Ara</b>", "Telegram ID, @kullanıcıadı ya da isim yaz.", "admin"))

    elif a.startswith("uv:"):
        await safe_edit(q, *user_view(a.split(":", 1)[1]))

    elif a.startswith("ug:"):
        tid_ = int(a.split(":", 1)[1])
        await safe_edit(q, *ask_num(uid, "gift_days", f"👤 <code>{tid_}</code>\n", target=tid_))

    elif a.startswith("ux:"):
        tid_ = int(a.split(":", 1)[1])
        codes = user_codes(db, tid_)
        if not codes: await safe_edit(q, "ℹ️ Aktif kodu yok. <b>🎁 Kod Ver</b> ile yeni kod verebilirsin.", KB([[B("◀️ Geri", f"uv:{tid_}")]])); return
        await safe_edit(q, "⏳ <b>Hangi koda süre eklensin?</b>", KB([[B(f"⏳ {short(name_of(s_, k), 18)} · {left_txt(s_.get('expires'))}", f"uxc:{k}")] for k, s_ in codes[:10]] + [[B("◀️ Geri", f"uv:{tid_}")]]))

    elif a.startswith("uxc:"):
        kid = a.split(":", 1)[1]
        await safe_edit(q, *ask_num(uid, "add_days", f"🎟 <b>{esc(name_of(db['subs'].get(kid, {}), kid))}</b>\n", kid=kid))

    elif a == "ban_menu":
        await safe_edit(q, *ban_view())

    elif a == "ban_find":
        STATE[uid] = {"action": "ban_find"}
        await safe_edit(q, *prompt("🚫 <b>Kullanıcı Banla</b>", "Telegram ID, @kullanıcıadı ya da isim yaz.", "ban_menu"))

    elif a.startswith("bnq:"):   # banlamadan önce sor
        tid_ = a.split(":", 1)[1]; e_ = db.get("users", {}).get(tid_, {})
        await safe_edit(q, f"🚫 <b>Banlansın mı?</b>\n<blockquote>👤 {esc(e_.get('name') or '?')} <code>{tid_}</code>\nBotu hiç kullanamaz (açık pazar kodları da durur).</blockquote>",
                        KB([[B("🚫 Evet, banla", f"bnd:{tid_}", "danger")], [B("✖️ Vazgeç", "ban_menu")]]))

    elif a.startswith(("bnd:", "ubn:")):
        tid_ = a.split(":", 1)[1]; ban_ = a.startswith("bnd:")
        if ban_ and int(tid_) in ADMINS: await q.answer("⚠️ Kurucu banlanamaz.", show_alert=True); return
        def f(d):
            e = d.get("users", {}).get(tid_)
            if e is None: return None
            e["banned"] = ban_
            if not ban_: e.pop("ban_until", None)
            return e.get("name") or tid_
        nm_ = mutate(f)
        if nm_ is not None:
            ulog("ban", f"{'🚫 Engellendi' if ban_ else '✅ Engel kaldırıldı'}: {nm_} ({tid_})"); audit(uid, f"{'ban' if ban_ else 'unban'} {tid_}")
            if ban_:   # açık pazar kodları durur (para düşmeye devam etmesin)
                for sid_, x_ in list(load_db().get("msess", {}).items()):
                    if str(x_.get("buyer")) == tid_ and x_.get("status") == "on": await stop_session(c.application, sid_, "user")
            try: await q.answer("🚫 Banlandı" if ban_ else "✅ Ban kaldırıldı")
            except Exception: pass
        await safe_edit(q, *ban_view())

    elif a.startswith("ub:"):
        tid_ = a.split(":", 1)[1]
        def f(d):
            e = d.get("users", {}).get(tid_)
            if not e: return None
            e["banned"] = not (e.get("banned") or e.get("ban_until", 0) > time.time())
            if not e["banned"]: e.pop("ban_until", None)
            return e["banned"]
        st_ = mutate(f)
        if st_ is not None:
            ulog("ban", f"{'🚫 Engellendi' if st_ else '✅ Engel kaldırıldı'}: {load_db()['users'][tid_].get('name')} ({tid_})")
            audit(uid, f"{'ban' if st_ else 'unban'} {tid_}")
        await safe_edit(q, *user_view(tid_))

    elif a in ("tickets", "tickets_bug"):
        await show_banner(c, uid, getattr(q, "message", None), "bug" if a == "tickets_bug" else "sup", *tickets_view(a == "tickets_bug"), send=lambda t, kb: safe_edit(q, t, kb))

    elif a.startswith("tv:"):
        tid = a.split(":", 1)[1]; t = db.get("tickets", {}).get(tid)
        if not t: await safe_edit(q, "⚠️ Talep bulunamadı.", back("tickets")); return
        await safe_edit(q, f"🎫 <b>Destek #{tid}</b>\n<blockquote>👤 {esc(t.get('who'))}\n📅 Açıldı  {ago(t.get('ts'))}\n💬 Mesaj  <b>{t.get('n', 0)}</b>\n"
                           + ("🔴 Cevap bekliyor" if t.get("pending") else "🟢 Cevaplandı") + "</blockquote>\n<i>Kullanıcının mesajları sana ayrı ayrı geldi; birine Telegram'da yanıt vererek de cevaplayabilirsin.</i>",
                        KB([[B("✍️ Yanıtla", f"t_rep:{tid}", "primary"), B("🔒 Kapat", f"t_close:{tid}", "danger")], [B("◀️ Talepler", "tickets")]]))

    elif a.startswith("t_rep:"):   # mesaj medya olabilir: üzerine yazma, yeni mesaj gönder
        tid = a.split(":", 1)[1]
        STATE[uid] = {"action": "t_reply", "tid": tid}
        await c.bot.send_message(uid, f"✍️ <b>#{tid}</b> için cevabını yaz.\n<blockquote>Yazı, fotoğraf, video, dosya... ne gönderirsen kullanıcıya gider.</blockquote>",
                                 parse_mode="HTML", reply_markup=KB([[B("✖️ İptal", "t_cancel")]]))

    elif a == "t_cancel":
        STATE.pop(uid, None)
        await safe_edit(q, "✖️ Cevap iptal edildi.")

    elif a.startswith("t_close:"):
        tid = a.split(":", 1)[1]
        ok = await close_ticket(c, tid, True)
        try: await q.edit_message_reply_markup(None)
        except Exception: pass
        await c.bot.send_message(uid, f"🔒 Talep #{tid} kapatıldı." if ok else f"ℹ️ Talep #{tid} zaten kapalı.")

    elif a == "cp":
        await safe_edit(q, *(await asyncio.to_thread(crypto_view)))

    elif a == "cp_test":
        try:
            inv = await asyncio.to_thread(crypto_call, "createInvoice", asset="USDT", amount="0.1", description="Test ödemesi (bot)", payload="test", expires_in=3600, allow_comments="false")
        except Exception as e:
            await safe_edit(q, f"⚠️ Test faturası oluşturulamadı: <code>{esc(str(e)[:150])}</code>", back("cp")); return
        mutate(lambda d: d.__setitem__("cp_test", {"inv": inv["invoice_id"], "url": inv.get("bot_invoice_url") or inv.get("pay_url"), "ts": time.time(), "by": uid}))
        await safe_edit(q, "🧪 <b>Test Ödemesi</b>\n<blockquote>0.1 USDT'lik gerçek bir fatura açıldı. Öde → para kendi CryptoBot uygulamana gelir.\nBot ödemeyi en geç 1 dakikada görür ve sana «✅ Test ödemesi geldi» yazar.</blockquote>",
                        KB([[B("💸 Testi Öde", url=inv.get("bot_invoice_url") or inv.get("pay_url"), style="success")], [B("◀️ CryptoBot", "cp")]]))

    elif a == "cp_set":
        STATE[uid] = {"action": "cp_set"}
        await safe_edit(q, *prompt("🔑 <b>CryptoBot Token</b>", "@CryptoBot → Crypto Pay → Create App → <b>API Token</b>'ı kopyala ve buraya gönder.\n<i>Mesajın güvenlik için hemen silinir.</i>", "cp"))

    elif a == "cp_del":
        await asyncio.to_thread(set_env, "CRYPTO_PAY_TOKEN", "")
        audit(uid, "crypto token removed")
        await safe_edit(q, *(await asyncio.to_thread(crypto_view)))

    elif a == "pay_set":
        STATE[uid] = {"action": "pay_set"}
        cur = db.get("pay_info") or "—"
        await safe_edit(q, *prompt("💳 <b>Ödeme Bilgisi</b>", f"Şu an:\n<i>{esc(cur)}</i>\n\nKullanıcıların sipariş verirken göreceği ödeme bilgisini yaz (ör. telefon numarası, kime ödeme yapılacağı).\nSilmek için <code>-</code> gönder.", "admin"))

    elif a == "bcast":
        STATE[uid] = {"action": "bcast"}
        await safe_edit(q, *prompt("📣 <b>Herkese Mesaj</b>", "Bütün kullanıcılara gidecek mesajı yaz.", "admin"))

    elif a == "bcast_yes":
        st = STATE.pop(uid, None)
        if not st or st.get("action") != "bcast_ok":
            await safe_edit(q, "⚠️ Süre geçti, baştan başla.", back("admin")); return
        c.application.create_task(broadcast(c.application, st["text"], uid))
        await safe_edit(q, "📣 Gönderiliyor... Bitince bildirim gelecek.", back("admin"))

    elif a.startswith(("ord_ok:", "ord_no:")):
        msg = await fulfill_order(c, a.split(":", 1)[1], a.startswith("ord_ok:"), uid)
        try: await q.edit_message_reply_markup(None)
        except Exception: pass
        await c.bot.send_message(uid, msg, parse_mode="HTML", disable_web_page_preview=True)

    elif a.startswith("num:"):
        st = STATE.pop(uid, None)
        if not st or st.get("action") != "num":
            await safe_edit(q, L(uid, "⚠️ Süre geçti, baştan başla.", "⚠️ Время вышло, начните заново."), back("menu", L(uid, "◀️ Menü", "◀️ Меню"))); return
        async def send(t, kb): await safe_edit(q, t, kb)
        await on_num(c, uid, st, int(a.split(":", 1)[1]), send, q.from_user.full_name)

    elif a == "toggle_sys":
        audit(uid, "toggle_sys")
        if os.path.exists(STOP_FLAG):
            os.remove(STOP_FLAG); vlog("▶️ Sistem başlatıldı.")
            WAKE.set()
            await q.answer("✅ Başlatıldı, kontrol hemen başlıyor.", show_alert=True)
        else:
            with open(STOP_FLAG, "w") as f: f.write("stop")
            vlog("🛑 Sistem durduruldu.")
            await q.answer("🛑 Durduruldu.", show_alert=True)
        await safe_edit(q, admin_text(uid), admin_kb(uid))

    elif a == "admin":
        STATE.pop(uid, None)
        await safe_edit(q, admin_text(uid), admin_kb(uid))

    elif a == "rollback":
        if not os.path.exists(SELF + ".eski"):
            await safe_edit(q, "⚠️ Önceki sürüm yok.", back("admin")); return
        await safe_edit(q, f"♻️ <b>Önceki sürüme dönülsün mü?</b>\n<blockquote>Şu an: <code>{sha16(SELF)}</code>\nÖnceki: <code>{sha16(SELF + '.eski')}</code></blockquote>",
                        KB([[B("♻️ Evet, dön", "rollback_yes", "danger"), B("✖️ Vazgeç", "admin")]]))

    elif a == "rollback_yes":
        if not os.path.exists(SELF + ".eski"):
            await safe_edit(q, "⚠️ Önceki sürüm yok.", back("admin")); return
        cur = SELF + ".yeni_geri"
        shutil.copy(SELF, cur); shutil.copy(SELF + ".eski", SELF); shutil.copy(cur, SELF + ".eski")
        sha = sha16(SELF)
        audit(uid, f"rollback {sha}"); vlog(f"♻️ Önceki sürüme dönüldü ({sha})")
        with open(UPDATE_NOTE, "w") as nf: nf.write(sha + " (geri alındı)")
        await safe_edit(q, f"♻️ <b>Önceki sürüme dönüldü</b> <code>{sha}</code>\n<i>Bot yeniden açılıyor...</i>")
        asyncio.get_running_loop().call_later(2, restart_self)

    elif a == "ip_need":
        await safe_edit(q, *ask_num(uid, "ip_need", f"Şu an: <b>en az {ip_need()}</b> yeni IP\n"))

    elif a == "ping_max":
        await safe_edit(q, *ask_num(uid, "ping_max", f"Şu an: <b>{ping_max()} ms</b>\n"))

    elif a == "ad_post":
        await send_ad(c, uid, "tk")
        await safe_edit(q, "📢 <b>Reklam postu</b>\n<blockquote>Post aşağıda. İstediğin kanala ilet (forward) ya da kanal sahibine gönder.\n\nKanalda dil butonu çalışsın istersen: kanala yazı yazarken <code>@" + esc(BOT.get("un") or "bot") + "</code> yaz, çıkan reklamı seç (BotFather'da /setinline açık olmalı).</blockquote>", back("admin"))

    elif a == "auto_ann":
        on = mutate(lambda d: d.__setitem__("auto_ann_on", not d.get("auto_ann_on", True)) or d["auto_ann_on"])
        audit(uid, f"auto_ann {'on' if on else 'off'}")
        await safe_edit(q, "⚙️ <b>Admin</b>\n<blockquote>🕰 Otomatik duyuru " + ("<b>açık</b>: " + ", ".join(f"{h:02d}:00" for h in sorted(AUTO_ANN)) + "'da genel duyuru değişir." if on else "<b>kapalı</b>.") + "</blockquote>", admin_kb(uid))

    elif a == "upd_now":
        if CHECK_LOCK.locked():
            await q.answer("⏳ Şu an kontrol yapılıyor, biraz bekle.", show_alert=True); return
        await q.answer()
        await safe_edit(q, "⚡ <b>Güncelleniyor...</b>\n<blockquote>Bitince bildirim gelecek. Canlı izlemek için 📜 Loglar.</blockquote>",
                        KB([[B("📜 Loglar", "logs", "primary"), B("◀️ Admin", "admin")]]))
        audit(uid, "upd_now")
        asyncio.create_task(run_check(c.application, force=True))

    elif a == "logs":
        if uid in LIVE: LIVE.pop(uid).cancel()
        await safe_edit(q, log_text(), LOG_KB)
        LIVE[uid] = asyncio.create_task(live_log(q, uid))

    elif a in ("bulk_ann", "bulk_title"):
        STATE[uid] = {"action": a}
        if a == "bulk_ann":
            t, kb = prompt("📢 <b>Toplu Duyuru</b>", "Bütün kodlara yazılacak duyuruyu gönder.\nHepsinden silmek için <code>-</code> gönder.", "menu")
        else:
            t, kb = prompt("🏷 <b>Toplu Başlık</b>", "Bütün kodların <b>abonelik başlığı</b> (VPN uygulamasında görünen ad) bu olacak.\n"
                           "<code>-</code> gönderirsen her kodun başlığı kendi buton adı olur.\n<i>Buton adları değişmez.</i>", "admin")
        await safe_edit(q, t, kb)

    elif a == "bulk_yes":
        st = STATE.pop(uid, None)
        if not st or st.get("action") != "confirm":
            await safe_edit(q, "⚠️ Onay süresi geçti, baştan başla.", back("menu", "◀️ Menü")); return
        field = "title" if st["what"] == "bulk_title" else "announce"
        await safe_edit(q, "⏳ <b>Drive'a yazılıyor...</b>")
        async with CHECK_LOCK:   # botun güncellemesiyle aynı anda Drive'a yazmasın
            (ok, bad), n = await asyncio.to_thread(bulk_apply, field, st["val"])
        audit(uid, f"bulk_{field} ok={ok} bad={len(bad)}")
        await safe_edit(q, f"✅ <b>{'Toplu duyuru' if field == 'announce' else 'Toplu başlık'} uygulandı</b>\n"
                        f"<blockquote>💾 Drive  <b>{ok}/{n}</b>" + (f"\n❌ Başarısız  {esc(', '.join(bad[:8]))}" if bad else "") + "</blockquote>",
                        back("menu", "◀️ Menü"))

    elif a == "my_keys" or a.startswith("my_keys:"):
        page = int(a.split(":")[1]) if ":" in a else 0
        items = [(k, v) for k, v in db["subs"].items() if uid in ADMINS or v.get("owner_id") == uid]
        pages = max(1, (len(items) + PAGE - 1) // PAGE)
        page = max(0, min(page, pages - 1))
        rows = grid([B(("🔴 " if is_exp(v) else "") + short(btn_name(v, k), 16), f"kv:{k}") for k, v in items[page * PAGE:(page + 1) * PAGE]], 2)
        if pages > 1:
            nav = []
            if page > 0: nav.append(B("◀️", f"my_keys:{page - 1}"))
            nav.append(B(f"{page + 1}/{pages}", f"my_keys:{page}"))
            if page < pages - 1: nav.append(B("▶️", f"my_keys:{page + 1}"))
            rows.append(nav)
        rows.append([B(L(uid, "✨ Yeni Kod", "✨ Новый код"), "create_key", "success"), B(L(uid, "◀️ Menü", "◀️ Меню"), "menu")])
        expd = sum(1 for _, v in items if is_exp(v))
        await show_banner(c, uid, getattr(q, "message", None), "mine", L(uid, "👥 <b>Kodlarım</b>", "👥 <b>Мои коды</b>") + f"  <code>{len(items)}</code>\n"
                          + "<blockquote>" + L(uid, "Yönetmek için bir koda dokun.", "Нажмите на код, чтобы управлять им.") + (L(uid, f"\n🔴 = süresi dolmuş ({expd})", f"\n🔴 = срок истёк ({expd})") if expd else "") + "</blockquote>",
                          KB(rows), send=lambda t, kb: safe_edit(q, t, kb))

    elif a.startswith("kv:"):
        kid = a.split(":", 1)[1]
        s = db["subs"].get(kid)
        if not s:
            await safe_edit(q, L(uid, "⚠️ Kod bulunamadı.", "⚠️ Код не найден."), back("my_keys")); return
        await asyncio.to_thread(user_link, s.get("file_id"))   # şifreli link önceden hazır olsun
        await safe_edit(q, code_card(s, kid, uid), code_kb(kid, uid))

    elif a.startswith(("kt:", "kn:", "ka:")):
        kind, kid = a.split(":", 1)
        s = db["subs"].get(kid, {})
        act = {"kt": "title", "kn": "bname", "ka": "announce"}[kind]
        STATE[uid] = {"action": act, "kid": kid}
        cur_ann = ('<i>' + esc(short(s.get('announce'), 100)) + '</i>') if s.get('announce') else '—'
        texts = {"title": ("🏷 <b>Abonelik Başlığı</b>", f"Şu an: <code>{esc(name_of(s, kid))}</code>\nYeni başlığı gönder (VPN uygulamasında görünür, emoji olur: <code>VIP 🇹🇲</code>)."),
                 "bname": ("🔘 <b>Buton Adı</b>", f"Şu an: <code>{esc(btn_name(s, kid))}</code>\nYeni adı gönder. <i>Sadece bu botta görünür, abonelik başlığı değişmez.</i>"),
                 "announce": ("📢 <b>Duyuru</b>", f"Şu an: {cur_ann}\nBu koda özel duyuruyu gönder. Silmek için <code>-</code> (o zaman genel duyuru görünür).")}
        if is_ru(uid):
            texts = {"title": ("🏷 <b>Заголовок подписки</b>", f"Сейчас: <code>{esc(name_of(s, kid))}</code>\nОтправьте новый заголовок (виден в VPN-приложении, можно с эмодзи: <code>VIP 🇹🇲</code>)."),
                     "bname": ("🔘 <b>Имя кнопки</b>", f"Сейчас: <code>{esc(btn_name(s, kid))}</code>\nОтправьте новое имя. <i>Видно только в этом боте, заголовок подписки не меняется.</i>"),
                     "announce": ("📢 <b>Объявление</b>", f"Сейчас: {cur_ann}\nОтправьте объявление для этого кода. Чтобы удалить — <code>-</code> (тогда будет общее объявление).")}
        t, kb = prompt(*texts[act], f"kv:{kid}", uid)
        await safe_edit(q, t, kb)

    elif a.startswith("kd:"):
        kid = a.split(":", 1)[1]
        s = db["subs"].get(kid, {})
        await safe_edit(q, L(uid, "🗑 <b>Bu kod silinsin mi?</b>", "🗑 <b>Удалить этот код?</b>") + f"\n<blockquote>🎟 <b>{esc(short(btn_name(s, kid), 40))}</b>\n" + L(uid, "Eski abonelik linki boşalır.", "Старая ссылка подписки перестанет работать.") + "</blockquote>",
                        KB([[B(L(uid, "🗑 Evet, sil", "🗑 Да, удалить"), f"kdy:{kid}", "danger"), B(L(uid, "✖️ Vazgeç", "✖️ Отмена"), f"kv:{kid}")]]))

    elif a.startswith("kdy:"):
        kid = a.split(":", 1)[1]
        nm = btn_name(db["subs"].get(kid, {}), kid)
        ok = await asyncio.to_thread(delete_vip, kid)
        if ok: audit(uid, f"delete {kid} {nm}")
        if ok and uid not in ADMINS:
            await notify_founders(c.application, f"🔔 Alt admin <b>{esc(q.from_user.full_name)}</b> (<code>{uid}</code>) kod sildi: <code>{esc(nm)}</code>")
        await safe_edit(q, L(uid, "✅ Kod silindi.", "✅ Код удалён.") if ok else L(uid, "⚠️ Kod bulunamadı.", "⚠️ Код не найден."), back("my_keys", L(uid, "◀️ Kodlarım", "◀️ Мои коды")))

    elif a == "create_key":
        if uid not in ADMINS and owned(db, uid) >= sa_limit(db, uid):
            await safe_edit(q, L(uid, f"⛔ <b>Limit doldu</b>\n<blockquote>En fazla {sa_limit(db, uid)} kod. Yer açmak için birini sil.</blockquote>",
                                 f"⛔ <b>Лимит исчерпан</b>\n<blockquote>Максимум {sa_limit(db, uid)} кодов. Удалите один, чтобы освободить место.</blockquote>"), back("my_keys", L(uid, "👥 Kodlarım", "👥 Мои коды"))); return
        STATE[uid] = {"action": "new_key"}
        t, kb = prompt(L(uid, "✨ <b>Kod Oluştur</b>", "✨ <b>Создать код</b>"),
                       L(uid, "Kod için bir isim gönder.\n<i>Hem buton adı hem abonelik başlığı olur; sonra ayrı ayrı değiştirebilirsin. Ardından süre sorulacak.</i>",
                         "Отправьте название кода.\n<i>Оно станет и именем кнопки, и заголовком подписки; потом можно изменить отдельно. Затем спросим срок.</i>"), "admin" if uid in ADMINS else "menu", uid)
        await safe_edit(q, t, kb)

    elif a.startswith("kx:"):
        kid = a.split(":", 1)[1]
        s = db["subs"].get(kid)
        if not s:
            await safe_edit(q, "⚠️ Kod bulunamadı.", back("my_keys")); return
        await safe_edit(q, f"⏳ <b>Süre</b>\n<blockquote>🎟 <b>{esc(short(btn_name(s, kid), 40))}</b>\nKalan  <b>{left_txt(s.get('expires'))}</b></blockquote>", KB([
            [B("+7g", f"kxs:{kid}:7"), B("+30g", f"kxs:{kid}:30", "primary"), B("+90g", f"kxs:{kid}:90")],
            [B("♾ Sınırsız", f"kxs:{kid}:0", "success"), B("⛔ Şimdi bitir", f"kxs:{kid}:-1", "danger")],
            [B("◀️ Geri", f"kv:{kid}")]]))

    elif a.startswith("kxs:"):
        _, kid, d = a.split(":")
        d = int(d)
        def fx(db2):
            s = db2["subs"].get(kid)
            if not s: return None
            now = time.time()
            if d == 0: s.pop("expires", None)
            elif d < 0: s["expires"] = now - 1
            else: s["expires"] = max(now, float(s.get("expires") or 0)) + d * 86400
            s["exp_done"] = is_exp(s)
            return s.get("file_id"), name_of(s, kid), eff_ann(db2, s), list(db2["template"]), s.get("expires")
        r = mutate(fx)
        if not r:
            await safe_edit(q, "⚠️ Kod bulunamadı.", back("my_keys")); return
        ok = await asyncio.to_thread(lambda: sync_file(new_service(), r[0], r[1], r[2], r[3], exp=is_exp({"expires": r[4]})))
        audit(uid, f"duration {kid} {d}")
        await safe_edit(q, f"✅ <b>Süre güncellendi</b>\n<blockquote>Kalan  <b>{left_txt(r[4])}</b>" + ("" if ok else "\n⚠️ Drive'a yazılamadı.") + "</blockquote>",
                        KB([[B("🎟 Koda Dön", f"kv:{kid}", "primary")]]))

    elif a == "sources":
        src = db["sources"]
        rows = [[B(f"{i}. {src_label(s)} · {RUN['src'].get(s, '…')[:14]}", "sv:" + hashlib.md5(s.encode()).hexdigest()[:8])] for i, s in enumerate(src, 1)]
        rows.append([B("➕ Abonelik Ekle", "s_add", "success")])
        rows.append([B("◀️ Admin", "admin")])
        await safe_edit(q, f"🔗 <b>Abonelikler</b>  <code>{len(src)}</code>\n<blockquote>Kodlar bu aboneliklerden çekilir.\nDeğiştirmek veya silmek için birine dokun.</blockquote>", KB(rows))

    elif a.startswith("sv:"):
        h = a.split(":", 1)[1]
        s = src_find(db, h)
        if not s:
            await safe_edit(q, "⚠️ Bulunamadı.", back("sources")); return
        await safe_edit(q, f"🔗 <b>Abonelik</b>\n<blockquote>Son kontrol  {esc(RUN['src'].get(s, 'henüz yok'))}</blockquote>\n<code>{esc(s)}</code>",
                        KB([[B("✏️ Değiştir", f"se:{h}", "primary"), B("🗑 Sil", f"sd:{h}", "danger")], [B("◀️ Geri", "sources")]]))

    elif a.startswith("se:"):
        STATE[uid] = {"action": "src_edit", "h": a.split(":", 1)[1]}
        t, kb = prompt("✏️ <b>Abonelik değiştir</b>", "Yeni abonelik linkini gönder.", "sources")
        await safe_edit(q, t, kb)

    elif a.startswith("sd:"):
        h = a.split(":", 1)[1]
        def f(d):
            for s in d["sources"]:
                if hashlib.md5(s.encode()).hexdigest()[:8] == h:
                    d["sources"].remove(s); return True
            return False
        ok = mutate(f)
        if ok:
            audit(uid, "src_del")
            start_refresh(c.application, "abonelik silindi")
        await safe_edit(q, "✅ Abonelik silindi. Kalan aboneliklerin kodları şimdi yeniden yazılıyor." if ok else "⚠️ Bulunamadı.", back("sources"))

    elif a == "s_add":
        STATE[uid] = {"action": "src_add"}
        t, kb = prompt("➕ <b>Abonelik ekle</b>", "Abonelik linklerini gönder (her satıra bir tane).", "sources")
        await safe_edit(q, t, kb)

    elif a == "get_zip":
        buf = await asyncio.to_thread(make_backup)
        await c.bot.send_document(chat_id=uid, document=buf, filename=f"Backup_{datetime.datetime.now():%Y-%m-%d_%H%M}.zip")

    elif a == "sa_menu":
        rows, lines = [], []
        for sid, e in db.get("sub_admins", {}).items():
            nm = e.get("name") or sid
            on = float(e.get("expires", 0)) > time.time()
            lines.append(f"{'🟢' if on else '🔒'} <b>{esc(short(nm, 20))}</b> <code>{sid}</code>\n     ⏳ {left_txt(e.get('expires'))}  ·  🎟 {sum(1 for v in db['subs'].values() if str(v.get('owner_id')) == sid)}/{sa_limit(db, sid)}")
            rows.append([B(f"⏳ {short(nm, 10)}", f"sa_ext:{sid}", "primary"), B("🎟 Limit", f"sa_lim:{sid}"), B("🗑", f"sa_del:{sid}", "danger")])
        rows.append([B("➕ Alt Admin Ekle", "sa_add", "success")])
        rows.append([B("◀️ Admin", "admin")])
        await safe_edit(q, "👮 <b>Alt Adminler</b>\n<blockquote>" + ("\n".join(lines) or "Alt admin yok.") + "</blockquote>\n<i>⏳ uzat · 🎟 kod limiti · 🗑 sil</i>", KB(rows))

    elif a == "sa_add":
        STATE[uid] = {"action": "sa_add"}
        t, kb = prompt("➕ <b>Alt admin ekle</b>", "Kişinin sayısal Telegram ID'sini gönder.\nSonra süre ve kod limiti sorulacak.\n<i>ID'sini bota /start yazarak görebilir.</i>", "sa_menu")
        await safe_edit(q, t, kb)

    elif a.startswith(("sa_ext:", "sa_lim:")):
        kind, sid = a.split(":", 1)
        e = db.get("sub_admins", {}).get(sid)
        if not e:
            await safe_edit(q, "⚠️ Alt admin bulunamadı.", back("sa_menu")); return
        info = f"👮 <b>{esc(e.get('name') or sid)}</b> <code>{sid}</code>\n" + (f"Kalan: {left_txt(e.get('expires'))}\n" if kind == "sa_ext" else f"Şu an: {sa_limit(db, sid)} kod\n")
        t, kb = ask_num(uid, "sa_ext" if kind == "sa_ext" else "sa_lim", info, sid=sid)
        await safe_edit(q, t, kb)

    elif a.startswith("sa_del:"):
        sid = a.split(":", 1)[1]
        mutate(lambda d: d.get("sub_admins", {}).pop(sid, None))
        audit(uid, f"sa_del {sid}")
        await safe_edit(q, f"✅ Alt admin <code>{esc(sid)}</code> silindi.\n<blockquote>Oluşturduğu kodlar çalışmaya devam eder.</blockquote>", back("sa_menu"))

# ───────── HERKESE AÇIK KISIM (kullanıcılar, davet, market, kanallar) ─────────
REF_NEED = 3            # 1 ücretsiz kod için gereken yeni davet
FREE_DAYS = 1           # ücretsiz kod süresi (gün)
PRICES = {"c7": (7, 30), "c30": (30, 100)}   # ürün: (gün, TMT)
PANEL_PRICE, PANEL_MIN, PANEL_DAYS = 20, 20, 30
USERS_LOG = "/root/users.log"
ULOG_PAGE = 10
BOT = {"un": ""}        # botun kullanıcı adı (post_init'te dolar)
JOINED = {}             # kanal üyelik önbelleği: uid -> zaman

T = {
 "tr": {
  "menu": "✦ <b>VPN</b> ✦\n<blockquote>👥 Davet  <b>{avail}/{need}</b>\n🎟 Aktif kod  <b>{codes}</b></blockquote>\n<i>Bir işlem seç</i> 👇",
  "b_free": "✨ Kod Oluştur", "b_mine": "🎟 Kodlarım", "b_prof": "👤 Profil", "b_market": "🛒 Market",
  "b_lang": "🌐 Dil: Türkçe", "b_menu": "◀️ Menü", "b_share": "📤 Arkadaşlarına Gönder", "b_check": "✅ Kontrol Et",
  "b_paid": "✅ TMT ödedim", "b_cancel": "✖️ İptal", "b_back": "◀️ Geri",
  "free_need": "🎁 <b>Ücretsiz Kod</b>\n<blockquote>Her kod için <b>{need}</b> yeni arkadaşını davet et.\nŞu an  <b>{avail}/{need}</b></blockquote>\n🔗 <b>Davet linkin</b> <i>(dokun → kopyala)</i>\n<code>{link}</code>",
  "free_today": "⏳ <b>Bugünkü ücretsiz kodunu aldın.</b>\n<blockquote>Yarın tekrar alabilirsin (Aşkabat saatiyle 00:00'dan sonra).</blockquote>",
  "free_ok": "✅ <b>Kodun hazır!</b>\n<blockquote>⏳ Süre  <b>{left}</b>\n📲 Linki kopyala, VPN uygulamana (Happ) abonelik olarak ekle.</blockquote>\n🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>\n<code>{link}</code>",
  "no_slot": "⚠️ Şu an boş kod yeri yok. Biraz sonra tekrar dene.",
  "mine_none": "🎟 <b>Kodlarım</b>\n<blockquote>Aktif kodun yok.</blockquote>",
  "mine": "🎟 <b>Kodlarım</b>",
  "mine_item": "<blockquote>🎟 <b>{name}</b>  ·  ⏳ {left}\n<code>{link}</code></blockquote>",
  "prof": "👤 <b>Profil</b>\n<blockquote>🪪 ID  <code>{id}</code>\n👤 İsim  {name}\n🔗 Kullanıcı adı  {un}\n🌐 Dil  Türkçe\n📅 Katılma  {joined}\n🕒 Şu an  {now}</blockquote>\n"
          "<blockquote>👥 Davet ettiklerin  <b>{total}</b>\n✅ Kullanılabilir davet  <b>{avail}/{need}</b>\n🎁 Alınan ücretsiz kod  <b>{free}</b>\n🎟 Aktif kod  <b>{active}</b>\n🛒 Satın alma  <b>{buys}</b>\n🙋 Seni davet eden  {inviter}</blockquote>\n"
          "🔗 <b>Davet linkin</b> <i>(dokun → kopyala)</i>\n<code>{link}</code>",
  "share_text": "Ücretsiz VPN kodu al 👇",
  "market": "🛒 <b>Market</b>\n<blockquote>🎟 Kod · 7 gün  —  <b>30 TMT</b> · 1.5 USDT\n🎟 Kod · 30 gün  —  <b>100 TMT</b> · 5 USDT\n🖥 Panel  —  kullanıcı başı <b>20 TMT</b> · 1 USDT <i>(en az 20)</i></blockquote>\n💵 USDT ile ödeme (CryptoBot) otomatik onaylanır.\n💳 TMT ile ödeme yakında 🔜\n<i>Satın almak istediğini seç</i> 👇",
  "b_c7": "🎟 Kod 7 gün · 30 TMT", "b_c30": "🎟 Kod 30 gün · 100 TMT", "b_panel": "🖥 Panel · 20 TMT/kullanıcı",
  "panel_ask": "🖥 <b>Panel</b>\n<blockquote>Kendi kullanıcıların için kod oluşturup yönetebileceğin panel.\nKullanıcı başı <b>20 TMT</b> · en az <b>20</b> kullanıcı · <b>30 gün</b></blockquote>\nKaç kullanıcı? Butona bas ya da sayı yaz:",
  "panel_min": "⚠️ En az 20 kullanıcı.",
  "it_c7": "🎟 Kod · 7 gün", "it_c30": "🎟 Kod · 30 gün", "it_panel": "🖥 Panel · {n} kullanıcı · 30 gün",
  "order": "🧾 <b>Sipariş #{oid}</b>\n<blockquote>{item}\n💰 Tutar  <b>{price} TMT</b>  ·  <b>{usdt} USDT</b></blockquote>\n{usdt_line}💳 <b>TMT ile ödeme</b>\n<blockquote>{pay}</blockquote>\n<i>TMT ile ödediysen «✅ TMT ödedim»e bas, admin onaylayınca kodun gelir.</i>",
  "usdt_line": "💵 <b>USDT ile ödeme</b> <i>(CryptoBot, otomatik onay)</i> → aşağıdaki butona bas.\n\n",
  "b_usdt": "💵 USDT ile öde ({usdt} USDT)", "b_pay": "💸 CryptoBot'ta Öde", "b_chk": "🔄 Ödemeyi Kontrol Et",
  "inv": "💵 <b>USDT ile ödeme · #{oid}</b>\n<blockquote>{item}\n💰 <b>{usdt} USDT</b>\n⏳ 1 saat geçerli</blockquote>\n«💸 CryptoBot'ta Öde»ye bas ve ödemeyi yap. Ödeme gelince kodun <b>otomatik</b> gönderilir.",
  "inv_wait": "Ödeme henüz gelmedi. Ödediysen 1 dakika sonra tekrar bak.",
  "inv_err": "⚠️ USDT faturası oluşturulamadı. Biraz sonra tekrar dene ya da TMT ile öde.",
  "pay_default": "Ödeme bilgisi için admin ile iletişime geç.",
  "order_sent": "⏳ <b>Sipariş #{oid} admine iletildi.</b>\n<blockquote>Onaylanınca buraya bildirim gelecek.</blockquote>",
  "order_old": "ℹ️ Bu sipariş zaten işlemde.",
  "order_ok_code": "✅ <b>Sipariş #{oid} onaylandı!</b>\n<blockquote>⏳ Süre  <b>{left}</b></blockquote>\n🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>\n<code>{link}</code>",
  "order_ok_panel": "✅ <b>Sipariş #{oid} onaylandı!</b>\n<blockquote>🖥 Panelin hazır: <b>{n}</b> kullanıcı · <b>{days}</b> gün</blockquote>\nPaneli açmak için /start yaz.",
  "order_no": "❌ <b>Sipariş #{oid} onaylanmadı.</b>\n<blockquote>Bir sorun varsa admin ile iletişime geç.</blockquote>",
  "cap": "🤖 <b>Doğrulama</b>\n<blockquote>Bot olmadığını doğrula:  <b>{a} {op} {b} = ?</b></blockquote>",
  "cap_wrong": "❌ Yanlış, tekrar dene.",
  "join": "📢 <b>Botu kullanmak için kanala abone ol</b>\n<blockquote>Abone olduktan sonra «✅ Kontrol Et»e bas.</blockquote>",
  "join_no": "Henüz abone olmadın.",
  "ref_new": "🎉 <b>{name}</b> davetinle katıldı!\n<blockquote>Davet  <b>{avail}/{need}</b></blockquote>",
  "ref_ready": "🎁 Davetler tamam! Ücretsiz kodunu alabilirsin.",
  "expired": "⏳ Kodunun süresi doldu ve silindi: {name}",
  "nobody": "—",
 },
 "ru": {
  "menu": "✦ <b>VPN</b> ✦\n<blockquote>👥 Приглашения  <b>{avail}/{need}</b>\n🎟 Активные коды  <b>{codes}</b></blockquote>\n<i>Выберите действие</i> 👇",
  "b_free": "✨ Создать код", "b_mine": "🎟 Мои коды", "b_prof": "👤 Профиль", "b_market": "🛒 Магазин",
  "b_lang": "🌐 Язык: Русский", "b_menu": "◀️ Меню", "b_share": "📤 Отправить друзьям", "b_check": "✅ Проверить",
  "b_paid": "✅ Оплатил в TMT", "b_cancel": "✖️ Отмена", "b_back": "◀️ Назад",
  "free_need": "🎁 <b>Бесплатный код</b>\n<blockquote>За каждый код пригласите <b>{need}</b> новых друзей.\nСейчас  <b>{avail}/{need}</b></blockquote>\n🔗 <b>Ваша ссылка</b> <i>(нажмите → скопировать)</i>\n<code>{link}</code>",
  "free_today": "⏳ <b>Сегодняшний бесплатный код уже получен.</b>\n<blockquote>Завтра можно снова (после 00:00 по Ашхабаду).</blockquote>",
  "free_ok": "✅ <b>Ваш код готов!</b>\n<blockquote>⏳ Срок  <b>{left}</b>\n📲 Скопируйте ссылку и добавьте её как подписку в VPN-приложение (Happ).</blockquote>\n🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>\n<code>{link}</code>",
  "no_slot": "⚠️ Сейчас нет свободных мест. Попробуйте чуть позже.",
  "mine_none": "🎟 <b>Мои коды</b>\n<blockquote>Активных кодов нет.</blockquote>",
  "mine": "🎟 <b>Мои коды</b>",
  "mine_item": "<blockquote>🎟 <b>{name}</b>  ·  ⏳ {left}\n<code>{link}</code></blockquote>",
  "prof": "👤 <b>Профиль</b>\n<blockquote>🪪 ID  <code>{id}</code>\n👤 Имя  {name}\n🔗 Юзернейм  {un}\n🌐 Язык  Русский\n📅 С нами с  {joined}\n🕒 Сейчас  {now}</blockquote>\n"
          "<blockquote>👥 Вы пригласили  <b>{total}</b>\n✅ Доступно приглашений  <b>{avail}/{need}</b>\n🎁 Получено бесплатных кодов  <b>{free}</b>\n🎟 Активные коды  <b>{active}</b>\n🛒 Покупки  <b>{buys}</b>\n🙋 Вас пригласил  {inviter}</blockquote>\n"
          "🔗 <b>Ваша ссылка</b> <i>(нажмите → скопировать)</i>\n<code>{link}</code>",
  "share_text": "Получи бесплатный VPN-код 👇",
  "market": "🛒 <b>Магазин</b>\n<blockquote>🎟 Код · 7 дней  —  <b>30 TMT</b> · 1.5 USDT\n🎟 Код · 30 дней  —  <b>100 TMT</b> · 5 USDT\n🖥 Панель  —  <b>20 TMT</b> · 1 USDT за пользователя <i>(от 20)</i></blockquote>\n💵 Оплата в USDT (CryptoBot) подтверждается автоматически.\n💳 Оплата в TMT скоро 🔜\n<i>Выберите, что хотите купить</i> 👇",
  "b_c7": "🎟 Код 7 дней · 30 TMT", "b_c30": "🎟 Код 30 дней · 100 TMT", "b_panel": "🖥 Панель · 20 TMT/польз.",
  "panel_ask": "🖥 <b>Панель</b>\n<blockquote>Панель, где вы сами создаёте и управляете кодами для своих пользователей.\n<b>20 TMT</b> за пользователя · от <b>20</b> пользователей · <b>30 дней</b></blockquote>\nСколько пользователей? Нажмите кнопку или напишите число:",
  "panel_min": "⚠️ Минимум 20 пользователей.",
  "it_c7": "🎟 Код · 7 дней", "it_c30": "🎟 Код · 30 дней", "it_panel": "🖥 Панель · {n} польз. · 30 дней",
  "order": "🧾 <b>Заказ #{oid}</b>\n<blockquote>{item}\n💰 Сумма  <b>{price} TMT</b>  ·  <b>{usdt} USDT</b></blockquote>\n{usdt_line}💳 <b>Оплата в TMT</b>\n<blockquote>{pay}</blockquote>\n<i>Если оплатили в TMT, нажмите «✅ Оплатил в TMT» — после подтверждения админом придёт код.</i>",
  "usdt_line": "💵 <b>Оплата в USDT</b> <i>(CryptoBot, автоматически)</i> → нажмите кнопку ниже.\n\n",
  "b_usdt": "💵 Оплатить USDT ({usdt} USDT)", "b_pay": "💸 Оплатить в CryptoBot", "b_chk": "🔄 Проверить оплату",
  "inv": "💵 <b>Оплата в USDT · #{oid}</b>\n<blockquote>{item}\n💰 <b>{usdt} USDT</b>\n⏳ Действует 1 час</blockquote>\nНажмите «💸 Оплатить в CryptoBot» и оплатите. После оплаты код придёт <b>автоматически</b>.",
  "inv_wait": "Оплата ещё не поступила. Если вы оплатили, проверьте через минуту.",
  "inv_err": "⚠️ Не удалось создать счёт в USDT. Попробуйте позже или оплатите в TMT.",
  "pay_default": "Для оплаты свяжитесь с администратором.",
  "order_sent": "⏳ <b>Заказ #{oid} отправлен администратору.</b>\n<blockquote>После подтверждения придёт уведомление.</blockquote>",
  "order_old": "ℹ️ Этот заказ уже обрабатывается.",
  "order_ok_code": "✅ <b>Заказ #{oid} подтверждён!</b>\n<blockquote>⏳ Срок  <b>{left}</b></blockquote>\n🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>\n<code>{link}</code>",
  "order_ok_panel": "✅ <b>Заказ #{oid} подтверждён!</b>\n<blockquote>🖥 Панель готова: <b>{n}</b> польз. · <b>{days}</b> дней</blockquote>\nЧтобы открыть панель, напишите /start.",
  "order_no": "❌ <b>Заказ #{oid} не подтверждён.</b>\n<blockquote>Если есть вопросы, свяжитесь с администратором.</blockquote>",
  "cap": "🤖 <b>Проверка</b>\n<blockquote>Подтвердите, что вы не бот:  <b>{a} {op} {b} = ?</b></blockquote>",
  "cap_wrong": "❌ Неверно, попробуйте ещё раз.",
  "join": "📢 <b>Чтобы пользоваться ботом, подпишитесь на канал</b>\n<blockquote>После подписки нажмите «✅ Проверить».</blockquote>",
  "join_no": "Вы ещё не подписались.",
  "ref_new": "🎉 <b>{name}</b> присоединился по вашей ссылке!\n<blockquote>Приглашения  <b>{avail}/{need}</b></blockquote>",
  "ref_ready": "🎁 Приглашений достаточно! Можете получить бесплатный код.",
  "expired": "⏳ Срок вашего кода истёк, он удалён: {name}",
  "nobody": "—",
 },
}

USDT_RATE = 20          # 1 USDT = 20 TMT
CRYPTO_API = "https://pay.crypt.bot/api/"
def tmt_to_um(tmt): return int(round(tmt / USDT_RATE * UM))   # TMT → bakiye birimi
def usdt_of(tmt): return f"{tmt / USDT_RATE:.2f}".rstrip("0").rstrip(".")
def crypto_token(): return os.environ.get("CRYPTO_PAY_TOKEN", "")

def crypto_call(method, token=None, **params):
    """Crypto Pay API (@CryptoBot). Hata olursa RuntimeError."""
    url = CRYPTO_API + method + ("?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}) if params else "")
    req = urllib.request.Request(url, headers={"Crypto-Pay-API-Token": token or crypto_token(), "User-Agent": "subbot/1.0 (+telegram bot)"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: j = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: j = json.loads(e.read().decode("utf-8"))
        except Exception: raise RuntimeError(f"HTTP {e.code}")
    if not j.get("ok"): raise RuntimeError(str(j.get("error"))[:200])
    return j["result"]

def crypto_transfer(**kw):
    """CryptoBot transferi; yorum kabul edilmezse (CANNOT_ATTACH_COMMENT) yorumsuz tekrar dener."""
    try: return crypto_call("transfer", **kw)
    except RuntimeError as e:
        if "CANNOT_ATTACH_COMMENT" not in str(e) or not kw.get("comment"): raise
        kw.pop("comment"); return crypto_call("transfer", **kw)

# ── Happ limitli link (happ-proxy.com): kod en fazla N cihaza kurulabilir ──
HAPP_API = "https://api.happ-proxy.com/api/"
HAPP_CRYPT = "https://crypto.happ.su/api-v2.php"

def happ_creds(): return os.environ.get("HAPP_PROVIDER", ""), os.environ.get("HAPP_AUTH", "")

def happ_call(method, prov=None, key=None, **params):
    """happ-proxy API. Hata olursa RuntimeError (Happ'ın mesajıyla). Auth key loglara yazılmaz."""
    p0, k0 = happ_creds()
    q = {"provider_code": prov or p0, "auth_key": key or k0, **{k: v for k, v in params.items() if v is not None}}
    req = urllib.request.Request(HAPP_API + method + "?" + urllib.parse.urlencode(q), headers={"accept": "application/json", "User-Agent": "subbot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r: j = json.loads(r.read().decode("utf-8"))
    except Exception as e: raise RuntimeError(f"Happ'a ulaşılamadı: {type(e).__name__}")
    if j.get("rc") != 1: raise RuntimeError(str(j.get("msg") or j)[:200])
    return j

def happ_encrypt(url):
    """Linki happ://crypt5/ olarak şifreler (kullanıcı installid'yi silemesin). Olmazsa None."""
    req = urllib.request.Request(HAPP_CRYPT, data=json.dumps({"url": url}).encode(), headers={"Content-Type": "application/json", "User-Agent": "subbot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=6) as r: return json.loads(r.read().decode("utf-8")).get("encrypted_link") or None
    except Exception as e:
        log.warning("happ encrypt: %s", type(e).__name__); return None

ENC = {}
def user_link(fid):
    """Kullanıcıya verilen link: Happ'ın şifreli linki (happ://crypt5/…) — Happ'ta sunucu ayarları görünmez.
    Her dosya bir kez şifrelenir, sonuç kalıcı önbellekte (sonraki gösterimlerde ağ isteği yok). Olmazsa düz link."""
    if not fid: return ""
    if fid in ENC: return ENC[fid]
    try: c_ = load_db().get("enc_links", {}).get(fid)
    except Exception: c_ = None
    if not c_:
        c_ = happ_encrypt(sub_link(fid))
        if c_:
            try: mutate(lambda d: d.setdefault("enc_links", {}).__setitem__(fid, c_))
            except Exception: pass
    if c_: ENC[fid] = c_
    return c_ or sub_link(fid)

def happ_make(kid, limit):
    """Koda limitli Happ linki üretir. Dönüş: (link, şifreli mi) ya da RuntimeError."""
    db = load_db(); s = db["subs"].get(kid)
    if not s or not s.get("file_id"): raise RuntimeError("Kod bulunamadı.")
    j = happ_call("add-install", install_limit=limit, note=short(name_of(s, kid), 200))
    plain = sub_link(s["file_id"]) + "#" + urllib.parse.quote(name_of(s, kid)) + "?installid=" + j["install_code"]
    enc = happ_encrypt(plain)
    mutate(lambda d: d["subs"].get(kid, {}).__setitem__("happ", {"code": j["install_code"], "id": j.get("id"), "limit": limit, "link": enc or plain, "enc": bool(enc), "ts": time.time()}))
    return enc or plain, bool(enc)

def happ_attach(kid, txt):
    """happ-proxy.com sitesinde oluşturulan limitli linki koda bağlar (Free plan: API kapalı, site açık).
    Kabul: 12 haneli install code, '...installid=XXX' içeren link ya da sitenin verdiği happ://crypt linki."""
    db = load_db(); s = db["subs"].get(kid)
    if not s or not s.get("file_id"): raise RuntimeError("Kod bulunamadı.")
    t = txt.strip()
    m = re.search(r"installid=([A-Za-z0-9]{6,32})", t, re.I) or re.fullmatch(r"([A-Za-z0-9]{6,32})", t)
    if m:
        code = m.group(1)
        plain = sub_link(s["file_id"]) + "#" + urllib.parse.quote(name_of(s, kid)) + "?installid=" + code
        enc = happ_encrypt(plain); link = enc or plain
    elif re.fullmatch(r"happ://crypt\d?/\S+", t): code, enc, link = None, True, t
    else: raise RuntimeError("Install code ya da link tanınmadı.")
    mutate(lambda d: d["subs"].get(kid, {}).__setitem__("happ", {"code": code, "limit": None, "link": link, "enc": bool(enc), "ts": time.time(), "site": True}))
    return link, bool(enc)

def happ_view():
    p, k = happ_creds()
    t = ("🔒 <b>Happ Limitli Kod</b>\n<blockquote>Kod en fazla seçtiğin sayıda cihaza kurulabilir (1–100). Link şifrelenir, kullanıcı limiti silemez.\n"
         f"🔑 Happ hesabı  <b>{('bağlı · ' + esc(p)) if p and k else 'bağlı değil'}</b>\n"
         "ℹ️ Happ API'si sadece ücretli planda çalışıyor. Free planda: linki happ-proxy.com → Limited links'ten oluştur (10 adet), çıkan Install code'u bota yapıştır.</blockquote>")
    rows = [[B("✨ Limitli Kod Oluştur", "hp_new", "primary")], [B("🔑 Happ Bilgileri", "hp_set")]] + \
           ([[B("🗑 Bağlantıyı Kaldır", "hp_del", "danger")]] if p else []) + [[B("◀️ Admin", "admin")]]
    return t, KB(rows)

def happ_paste_prompt(uid, kid):
    STATE[uid] = {"action": "hp_paste", "kid": kid}
    s = load_db()["subs"].get(kid, {})
    return prompt("✍️ <b>Happ limitli link (siteden)</b>",
                  "1) happ-proxy.com → <b>Limited links</b> → yeni link oluştur, cihaz limitini seç.\n"
                  "2) Çıkan <b>Install code</b>'u (ya da linkin tamamını) buraya yapıştır.\n"
                  f"<i>Bot bunu bu kodun aboneliğine bağlar ve şifreler:</i>\n🎟 <b>{esc(short(btn_name(s, kid), 40))}</b>", f"kv:{kid}")

def set_env(key, val):
    """env.txt'de bir satırı değiştirir/ekler/siler (val boşsa siler)."""
    lines = open(ENV_FILE, encoding="utf-8").read().splitlines() if os.path.exists(ENV_FILE) else []
    lines = [l for l in lines if not l.strip().startswith(key + "=")]
    if val: lines.append(f"{key}={val}")
    with open(ENV_FILE + ".tmp", "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
    os.replace(ENV_FILE + ".tmp", ENV_FILE)
    if val: os.environ[key] = val
    else: os.environ.pop(key, None)

def lang_of(db, uid):   # tek kaynak: LANGC (menüler arasında tutarsızlık olmasın)
    is_ru(uid)   # LANGC'yi doldurur
    return LANGC.get(uid) if LANGC.get(uid) in ("tr", "tk", "ru") else "tr"
LANG_NAMES = {"tr": "🇹🇷 Türkçe", "tk": "🇹🇲 Türkmençe", "ru": "🇷🇺 Русский"}

def lang_pick(back_to):
    return ("🌐 <b>Dil seç · Dil saýlaň · Выберите язык</b>",
            KB([[B(LANG_NAMES[x], f"u_setlang:{x}:{back_to}")] for x in ("tk", "tr", "ru")]))
def tr(lang, key, **kw):
    s = T.get(lang, T["tr"]).get(key) or T["tr"][key]
    return s.format(**kw) if kw else s

def who(user):
    """Log için: 'Ad (@kullanıcı, id)'"""
    un = f"@{user.username}, " if getattr(user, "username", None) else ""
    return f"{user.full_name or '?'} ({un}{user.id})"

def ulog(kind, text):
    try:
        if os.path.exists(USERS_LOG) and os.path.getsize(USERS_LOG) > 3_000_000:   # çok büyürse en eskiler gider
            with open(USERS_LOG, encoding="utf-8", errors="ignore") as f: keep = f.readlines()[-15000:]
            with open(USERS_LOG, "w", encoding="utf-8") as f: f.writelines(keep)
        with open(USERS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "k": kind, "x": text}, ensure_ascii=False) + "\n")
    except Exception: pass

def ulog_lines():
    try:
        with open(USERS_LOG, encoding="utf-8", errors="ignore") as f:
            out = []
            for ln in f:
                try: out.append(json.loads(ln))
                except Exception: pass
            return out
    except Exception: return []

def tm_now(): return datetime.datetime.now(TM_TZ)
def tm_fmt(ts): return datetime.datetime.fromtimestamp(ts, TM_TZ).strftime("%d.%m.%Y %H:%M")
def tm_day(): return tm_now().strftime("%Y-%m-%d")

def ref_link(uid): return f"https://t.me/{BOT['un']}?start=r{uid}" if BOT["un"] else "—"

def user_codes(db, uid):
    return [(k, s) for k, s in db["subs"].items() if s.get("owner_id") == uid and not is_exp(s)]

def avail_refs(u): return len(u.get("refs", [])) - int(u.get("spent", 0))

def touch_user(user, ref=None):
    """Kullanıcıyı kaydeder/günceller. Dönüş: (yeni_mi, kayıt)."""
    uid, key = user.id, str(user.id)
    nm, un = getattr(user, "full_name", "") or "", getattr(user, "username", "") or ""
    cur = load_db().get("users", {}).get(key)
    if cur and cur.get("name") == nm and cur.get("un") == un: return False, cur   # değişiklik yok: diske yazma
    def f(db):
        us = db.setdefault("users", {})
        e = us.get(key)
        new = e is None
        if new:
            e = {"joined": time.time(), "lang": "tr", "refs": [], "spent": 0, "free_n": 0, "buys": 0}
            if ref and ref != uid and str(ref) in us: e["ref_by"] = ref; e["ok"] = False   # davetle geldi: doğrulama bekliyor
            else: e["ok"] = True
            us[key] = e
        e["name"], e["un"] = nm, un
        return new, json.loads(json.dumps(e))
    return mutate(f)

# ── kanal şartı ──
async def missing_channels(bot, uid):
    """Abone olunmamış kanallar. Kurucular muaf. Bot üyeliği kontrol edemezse kullanıcıyı kilitlemez."""
    if uid in ADMINS: return []
    chans = load_db().get("channels", [])
    if not chans or time.time() - JOINED.get(uid, 0) < 300: return []
    miss = []
    for ch in chans:
        try:
            m = await bot.get_chat_member(ch["id"], uid)
            ok = m.status in ("member", "administrator", "creator") or (m.status == "restricted" and getattr(m, "is_member", False))
            if not ok: miss.append(ch)
        except BadRequest as e:
            if "user not found" in str(e).lower() or "participant" in str(e).lower(): miss.append(ch)
            else: log.warning("kanal kontrolü %s: %s", ch.get("title"), e)
        except Exception as e: log.warning("kanal kontrolü %s: %s", ch.get("title"), e)
    if not miss: JOINED[uid] = time.time()
    return miss

def join_view(lang, miss):
    rows = [[B(f"📢 {short(ch.get('title') or 'Kanal', 30)}", url=ch["link"])] for ch in miss if ch.get("link")]
    rows.append([B(tr(lang, "b_check"), "u_check", "success")])
    return tr(lang, "join"), KB(rows)

# ── doğrulama (sadece davetle gelenler) ──
def captcha_view(lang, uid, test=False):
    """Davetle gelene soru: alıcı mı, satıcı mı? (butona basmak = bot değil)"""
    def f(d):
        e = d["users"].setdefault(str(uid), {}); e["cap"] = "role"
        if test: e["cap_test"] = True
    mutate(f)
    return tr(lang, "cap"), KB([[B(tr(lang, "b_cap_buy"), "u_cap:buyer")], [B(tr(lang, "b_cap_sell"), "u_cap:seller")]])

# ── ana menü ──
def pub_menu(db, uid):
    lang = lang_of(db, uid)
    e = db.get("users", {}).get(str(uid), {})
    t = with_bal(tr(lang, "menu", avail=max(0, avail_refs(e)), need=REF_NEED, codes=len(user_codes(db, uid))), e, lang) + open_mkt_text(db, uid, lang)
    kb = KB([[B(tr(lang, "b_pazar"), "u_mkt", "success")]] + open_mkt_row(db, uid, lang) + [
             [B(tr(lang, "b_free"), "u_free"), B(tr(lang, "b_mine"), "u_mine", "primary")],
             [B(tr(lang, "b_prof"), "u_prof"), B(tr(lang, "b_market"), "u_market")],
             [B(tr(lang, "b_sup"), "u_sup"), B(tr(lang, "b_bug"), "u_bug")],
             [B(tr(lang, "b_set"), "u_set")]])
    return t, kb

def home(uid):
    """Kurucu/panel sahibi -> kendi paneli, diğerleri -> kullanıcı menüsü."""
    return (menu_text(uid), main_kb(uid)) if is_admin(uid) else pub_menu(load_db(), uid)

async def credit_ref(c, uid):
    """Doğrulama + kanal şartı tamamlanınca daveti sayar (bir kez)."""
    def f(d):
        e = d["users"].get(str(uid), {})
        if e.get("ok"): return None
        e["ok"] = True; e.pop("cap", None)
        inv = d["users"].get(str(e.get("ref_by")))
        if not inv or uid in inv.setdefault("refs", []): return None
        inv["refs"].append(uid); inv["bonus"] = inv.get("bonus", 0) + REF_BONUS
        return e.get("ref_by"), inv.get("lang", "tr"), avail_refs(inv), inv.get("name", "")
    r = mutate(f)
    if not r: return
    inv_id, ilang, av, iname = r
    db = load_db(); me = db["users"].get(str(uid), {})
    ulog("credit", f"🤝 Davet sayıldı: {iname} ({inv_id}) → {me.get('name')} ({uid}) · davet {av}/{REF_NEED}")
    try:
        await c.bot.send_message(inv_id, tr(ilang, "ref_new", name=esc(me.get("name") or uid), avail=min(av, REF_NEED), need=REF_NEED) + "\n" + tr(ilang, "ref_bonus"), parse_mode="HTML")
        if av == REF_NEED: await c.bot.send_message(inv_id, tr(ilang, "ref_ready"))
    except Exception: pass

async def pub_gate(c, uid, lang, send):
    """Kullanıcı ilerleyebilir mi? Doğrulama ve kanal ekranını gösterir. True = devam."""
    e = load_db().get("users", {}).get(str(uid), {})
    if not e.get("ok") and e.get("ref_by") and not e.get("cap_ok"):   # davetle geldi, doğrulamadı
        await send(*captcha_view(lang, uid)); return False
    miss = await missing_channels(c.bot, uid)
    if miss:
        await send(*join_view(lang, miss)); return False
    if not e.get("ok"): await credit_ref(c, uid)
    return True

async def pub_start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    user = u.effective_user
    if is_banned(user.id):
        await u.message.reply_text(tr(lang_of(load_db(), user.id), "banned")); return
    arg = (c.args[0] if getattr(c, "args", None) else "") or ""
    ref = int(arg[1:]) if re.fullmatch(r"r\d{3,15}", arg) else None
    new, e = await asyncio.to_thread(touch_user, user, ref)
    if new:
        inv = load_db()["users"].get(str(e.get("ref_by")), {}) if e.get("ref_by") else {}
        ulog("join", f"🆕 Katıldı: {who(user)}" + (f" · davet eden: {inv.get('name')} ({e['ref_by']})" if e.get("ref_by") else ""))
    STATE.pop(user.id, None)
    lang = e.get("lang", "tr")
    async def send(t, kb): await u.message.reply_text(t, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    if not await pub_gate(c, user.id, lang, send): return
    await show_home(c, user.id, pub=True)

def make_code_for(uid, name, days, kind):
    """Kullanıcıya kod (Drive dosyası) verir. Dönüş: ((kid, fid), hata)."""
    return create_vip(name, uid, days, check_limit=False, extra={"pub": kind})

async def pub_cb(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    user = q.from_user; uid = user.id
    a = q.data
    if is_banned(uid):
        await q.answer(tr(lang_of(load_db(), uid), "banned"), show_alert=True); return
    await asyncio.to_thread(touch_user, user)
    if a not in BANNER_ACTIONS and not a.startswith("u_setlang:"): q = await off_banner(c, q)   # banner'lı ekrandan başka ekrana: yazı mesajına geç
    db = load_db(); lang = lang_of(db, uid)
    async def send(t, kb=None):
        msg_ = getattr(q, "message", None)
        if getattr(msg_, "photo", None):   # fotoğraflı kartın metni düzenlenemez
            if is_banner(msg_):
                try: await msg_.delete()
                except Exception: pass
            await c.bot.send_message(uid, fit_kb(t, kb), parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        else: await safe_edit(q, fit_kb(t, kb), kb)
    async def bsend(kind, t, kb): await show_banner(c, uid, getattr(q, "message", None), kind, t, kb, send)
    menu_btn = KB([[B(tr(lang, "b_menu"), "u_menu")]])
    if not a.startswith("u_live:") and uid in LIVE: LIVE.pop(uid).cancel()

    if a.startswith("u_rep:"):   # hata mesajındaki "Admine Bildir"
        x = ERRS.pop(a.split(":", 1)[1], None)
        await q.answer(tr(lang, "reported"), show_alert=True)
        if x:
            await notify_founders(c.application, f"📨 <b>Kullanıcı hata bildirdi</b>\n<blockquote>👤 {esc(who(user))}\n📍 {esc(x['where'])}\n❗ <code>{esc(x['err'])}</code></blockquote>")
            ulog("err", f"📨 Hata bildirdi: {who(user)} · {x['where']}")
        try: await q.edit_message_reply_markup(None)
        except Exception: pass
        return

    if a.startswith("u_cap:"):
        e = db["users"].get(str(uid), {}); role = a.split(":", 1)[1]
        if role not in ("buyer", "seller"):   # eski matematik sorusunun butonu
            await q.answer(); await send(*captcha_view(lang, uid)); return
        if e.get("cap_test"):   # kurucunun davet testi: sadece akışı görür, sayım yok
            mutate(lambda d: (d["users"][str(uid)].pop("cap", None), d["users"][str(uid)].pop("cap_test", None)))
            await q.answer("✅"); ulog("verify", f"🧪 Davet testi: {who(user)} · {'satıcı' if role == 'seller' else 'alıcı'}")
            await show_home(c, uid, getattr(q, "message", None), send=send); return
        if e.get("ok") or "cap" not in e:
            await q.answer(); await show_home(c, uid, getattr(q, "message", None), True, send); return
        await q.answer("✅")
        mutate(lambda d: (d["users"][str(uid)].pop("cap", None), d["users"][str(uid)].update({"cap_ok": True, "role": role})))
        ulog("verify", f"{'🏪 Satıcı olarak geldi' if role == 'seller' else '🛒 Alıcı olarak geldi'}: {who(user)}")
        if not await pub_gate(c, uid, lang, send): return
        await show_home(c, uid, getattr(q, "message", None), True, send); return

    if a == "u_check":
        JOINED.pop(uid, None)
        miss = await missing_channels(c.bot, uid)
        if miss:
            await q.answer(tr(lang, "join_no"), show_alert=True); return
        await q.answer("✅")
        if not await pub_gate(c, uid, lang, send): return
        await show_home(c, uid, getattr(q, "message", None), send=send); return

    await q.answer()
    if not await pub_gate(c, uid, lang, send): return
    db = load_db(); e = db["users"].get(str(uid), {})

    if a == "u_menu":
        STATE.pop(uid, None)
        await show_home(c, uid, getattr(q, "message", None), send=send)

    elif a in ("u_sup", "u_bug"):
        kind = "bug" if a == "u_bug" else "sup"
        def f(d):
            x = d["users"].setdefault(str(uid), {})
            tid = open_ticket(d, uid)
            if tid: return tid, False
            tid = uuid.uuid4().hex[:5].upper()
            d.setdefault("tickets", {})[tid] = {"uid": uid, "status": "open", "ts": time.time(), "pending": 0, "n": 0, "who": who(user), "kind": kind}
            x["ticket"] = tid
            return tid, True
        tid, new = mutate(f)
        if new: ulog("t_open", f"{'🐞 Hata raporu' if kind == 'bug' else '🆘 Destek talebi'} açtı: {who(user)} · #{tid}")
        key = ("bug_new" if kind == "bug" else "sup_new") if new else "sup_open"
        await bsend(kind, tr(lang, key, tid=tid) + "\n" + tr(lang, "sup_rate"), KB([[B(tr(lang, "b_twrite"), "u_tw", "primary")], [B(tr(lang, "b_tclose"), "u_tclose", "danger")], [B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_tw":   # ✍️ Yaz: sıradaki tek mesaj (yazı / foto / video) talebe gider
        tid = open_ticket(load_db(), uid)
        if not tid: await send(tr(lang, "sup_closed", tid="—"), KB([[B(tr(lang, "b_menu"), "u_menu")]])); return
        STATE[uid] = {"action": "t_write", "tid": tid}
        await send(tr(lang, "sup_ask") + "\n" + tr(lang, "sup_rate"), KB([[B(tr(lang, "b_cancel"), "u_twx")]]))

    elif a == "u_twx":
        STATE.pop(uid, None)
        await show_home(c, uid, getattr(q, "message", None), send=send)

    elif a == "u_tclose":
        tid = open_ticket(load_db(), uid)
        if tid: await close_ticket(c, tid, False)
        await send(tr(lang, "sup_closed", tid=tid or "—"), KB([[B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_mkt":
        STATE.pop(uid, None)
        await show_market(c, q, uid, lang)

    elif a.startswith("u_mp:"):   # pazarda sonraki / önceki ilan
        await show_market(c, q, uid, lang, int(a.split(":", 1)[1]))

    elif a.startswith("u_ml:"):
        lid = a.split(":", 1)[1]; order = mkt_order(load_db())
        if lid not in order: await send(tr(lang, "m_gone"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        await show_market(c, q, uid, lang, order.index(lid))

    elif a.startswith("u_mck:"):   # anlık kontrol (kullanıcı 5 dk'da bir, kurucu sınırsız); ":r" = 🔄 Tazele (her zaman yeni test)
        lid, force = a.split(":")[1], a.endswith(":r"); now = time.time()
        left = CHK_EVERY - (now - CHK["user"].get(uid, 0))
        if uid not in ADMINS and left > 0:
            await q.answer(tr(lang, "chk_wait", m=int(left // 60) + 1), show_alert=True); return
        CHK["user"][uid] = now
        mode = "refresh" if force and CHK.get("last_ch") else "run"   # Yenile: eski sonuç hemen görünür, yeni test arkadan
        kb = chk_kb(lang, lid, False); t = check_text(load_db(), lid, lang, CHK.get("last_ch"), mode)
        msg = getattr(q, "message", None)
        if msg is not None:   # aynı kutu hemen "Kontrol ediliyor..." olur
            is_photo = bool(getattr(msg, "photo", None)); mid = msg.message_id
            if not await edit_box(c.bot, uid, mid, is_photo, t, kb):
                is_photo = False; mid = (await c.bot.send_message(uid, t, parse_mode="HTML", reply_markup=kb)).message_id
        else: is_photo = False; mid = (await c.bot.send_message(uid, t, parse_mode="HTML", reply_markup=kb)).message_id
        ch = await chk_run(_read_channel, load_db()); ts = ch.get("ts") or 0
        if ch: RUN["phone_old"] = not ch.get("quick_ok"); CHK["last_ch"] = ch   # telefon hızlı kontrolü bilmiyor: tam test (birkaç dk)
        if ts and now - ts < CHK_FRESH and not force: state = "fresh"   # telefon az önce test etti: tekrar test yok
        elif not ts or now - max(ts, ch.get("quick_ts") or 0) > PHONE_OFF: state = "off"   # telefon uzun süredir sonuç göndermiyor: boşuna bekletme
        elif CHK["wait"].get(lid) and CHK["qid"]: qid, state = CHK["qid"], "run"   # bu ilan zaten test ediliyor
        else:
            _, qid = await chk_run(request_phone_test, load_db(), set(CHK["wait"]) | {lid})   # abonelik kontrolünü beklemez
            if qid:
                CHK["qid"], CHK["req"], state = qid, now, "run"
                vlog(f"🔍 Hızlı kontrol telefona gönderildi: {db.get('market', {}).get(lid, {}).get('title', lid)}" + (" · ⚠️ telefon programı eski (tmtest.py'yi bota gönder)" if RUN.get("phone_old") else ""))
                if RUN.get("phone_old") or mode == "refresh": await edit_box(c.bot, uid, mid, is_photo, check_text(load_db(), lid, lang, ch, mode), kb)
            else: state = "timeout"
        if state == "run":
            CHK["wait"].setdefault(lid, {})[uid] = (lang, mid, is_photo, qid, now, mode)
            if not CHK.get("poll") or CHK["poll"].done(): CHK["poll"] = asyncio.create_task(chk_poll(c.application))
        else: await edit_box(c.bot, uid, mid, is_photo, check_text(load_db(), lid, lang, ch, state), chk_kb(lang, lid))
        ulog("m_check", f"🔍 Kontrol etti: {who(user)} · {db.get('market', {}).get(lid, {}).get('title', lid)}")

    elif a.startswith("u_mph:"):
        L_ = db.get("market", {}).get(a.split(":", 1)[1], {})
        if L_.get("photo") and L_.get("photo_ok", True):
            try: await c.bot.send_photo(uid, L_["photo"], caption=f"🏪 {L_.get('title', '')}"[:1000])
            except Exception: pass

    elif a.startswith("u_ms:"):   # önce sor: emin misin?
        lid = a.split(":", 1)[1]; L_ = db.get("market", {}).get(lid)
        if not L_ or L_.get("status") != "live": await send(tr(lang, "m_gone"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        if L_.get("owner") == uid and uid not in ADMINS: await send(tr(lang, "m_own"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        t_ = tr(lang, "ms_q", title=esc(short(L_["title"], 40)), fee=fmt_u(MKT_FEE), pm=money_tmt(float(L_["price"]), 4), ph=money_tmt(float(L_["price"]) * PREPAY_MIN), bal=fmt_u(e.get("bal", 0)))
        kb_ = KB([[B(tr(lang, "b_msy"), f"u_msy:{lid}", "success")], [B(tr(lang, "b_msn"), f"u_ml:{lid}")]])
        msg = getattr(q, "message", None)
        if msg is None or not await edit_box(c.bot, uid, msg.message_id, bool(getattr(msg, "photo", None)), t_, kb_): await c.bot.send_message(uid, t_, parse_mode="HTML", reply_markup=kb_)

    elif a.startswith("u_msy:"):
        lid = a.split(":", 1)[1]
        res, err = await asyncio.to_thread(mkt_start, uid, lid)
        if not res:
            if err.startswith("nobal:"):
                await send(tr(lang, "m_need", need=fmt_u(int(err.split(":")[1])), bal=fmt_u(load_db()["users"].get(str(uid), {}).get("bal", 0))),
                           KB([[B(tr(lang, "b_top"), "u_top", "success")], [B(tr(lang, "b_back_mkt"), f"u_ml:{lid}")]]))
            elif err == "already": await send(tr(lang, "m_already"), KB([[B(tr(lang, "b_mine"), "u_mine")], [B(tr(lang, "b_back_mkt"), "u_mkt")]]))
            elif err == "limit": await send(tr(lang, "m_limit", n=MAX_STARTS_DAY), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]]))
            elif err == "gone": await send(tr(lang, "m_gone"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]]))
            elif err == "own": await send(tr(lang, "m_own"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]]))
            else:
                await send(tr(lang, "no_slot"), menu_btn)
                await notify_founders(c.application, f"⚠️ <b>Pazar kodu başlatılamadı</b>\n<blockquote>{esc(who(user))}\n{esc(err)}</blockquote>")
            return
        sid, fid = res
        d2 = load_db(); L_ = d2["market"][lid]
        ulog("m_start", f"▶️ Pazar kodu başladı: {who(user)} · {L_['title']} · {fmt_u(L_['price'])} USDT/dk")
        await send(tr(lang, "m_started", title=esc(L_["title"]), p=money2(float(L_["price"]) * 43200, True) + " TMT/30", bal=fmt_u(d2["users"][str(uid)].get("bal", 0)), link=esc(await asyncio.to_thread(user_link, fid))),
                   KB([[B(tr(lang, "b_mine"), "u_mine", "primary"), B(tr(lang, "b_live"), f"u_live:{sid}")], [B(tr(lang, "b_menu"), "u_menu")]]))

    elif a.startswith("u_msq:"):   # durdurmadan önce sor (yanlışlıkla durmasın)
        sid = a.split(":", 1)[1]; s_ = db.get("msess", {}).get(sid)
        if not s_ or s_["buyer"] != uid or s_["status"] != "on": await show_market(c, q, uid, lang); return
        await send(tr(lang, "stop_q", title=esc(db["market"].get(s_["lid"], {}).get("title", "?")), dur=dur_txt(time.time() - s_["start"], lang == "ru"), usdt=fmt_u(s_["total"])),
                   KB([[B(tr(lang, "b_yes_stop"), f"u_msx:{sid}", "danger")], [B(tr(lang, "b_no"), "u_mine")]]))

    elif a.startswith("u_live:"):
        sid = a.split(":", 1)[1]; s_ = db.get("msess", {}).get(sid)
        if not s_ or s_["buyer"] != uid: return
        if uid in LIVE: LIVE.pop(uid).cancel()
        await send(*live_view(sid, lang))
        if s_["status"] == "on" and not getattr(getattr(q, "message", None), "photo", None):
            LIVE[uid] = asyncio.create_task(live_loop(q, uid, sid, lang))

    elif a.startswith("u_vip:"):   # önce sor: emin misin?
        lid = a.split(":", 1)[1]; L_ = db.get("market", {}).get(lid)
        if not L_ or L_.get("owner") != uid or L_.get("status") != "live": await send(tr(lang, "vip_notlive"), KB([[B(tr(lang, "b_myl"), "u_myl")]])); return
        await send(tr(lang, "vip_q", title=esc(short(L_["title"], 40)), h=VIP_HOURS, fee=fmt_u(VIP_FEE), bal=fmt_u(e.get("bal", 0))),
                   KB([[B(tr(lang, "b_yes_vip"), f"u_vipy:{lid}", "success")], [B(tr(lang, "b_no"), "u_myl")]]))

    elif a.startswith("u_vipy:"):
        lid = a.split(":", 1)[1]
        def f(d):
            L = d.get("market", {}).get(lid); x = d["users"].setdefault(str(uid), {})
            if not L or L.get("owner") != uid or L.get("status") != "live": return "notlive"
            if x.get("bal", 0) < VIP_FEE: return "nobal"
            x["bal"] -= VIP_FEE; d["mkt_fees"] = d.get("mkt_fees", 0) + VIP_FEE
            L["vip_until"] = max(time.time(), L.get("vip_until", 0)) + VIP_HOURS * 3600
            return L["vip_until"]
        r = mutate(f)
        if r == "nobal": await send(tr(lang, "vip_nobal"), KB([[B(tr(lang, "b_top"), "u_top", "success")], [B(tr(lang, "b_myl"), "u_myl")]])); return
        if r == "notlive": await send(tr(lang, "vip_notlive"), KB([[B(tr(lang, "b_myl"), "u_myl")]])); return
        L_ = load_db()["market"][lid]
        ulog("m_vip", f"💎 VIP aldı: {who(user)} · {L_['title']} · {VIP_HOURS} saat")
        await send(tr(lang, "vip_ok", title=esc(L_["title"]), left=dur_txt(r - time.time(), lang == "ru")), KB([[B(tr(lang, "b_myl"), "u_myl"), B(tr(lang, "b_back_mkt"), "u_mkt")]]))

    elif a.startswith("u_msx:"):
        sid = a.split(":", 1)[1]
        s_ = db.get("msess", {}).get(sid)
        if not s_ or s_["buyer"] != uid: return
        await stop_session(c.application, sid, "user")
        await show_market(c, q, uid, lang)

    elif a == "u_mrules":
        await send(tr(lang, "rules"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]]))

    elif a == "u_sell":
        if e.get("mban", 0) > time.time():
            await send(tr(lang, "sell_banned", left=dur_txt(e["mban"] - time.time(), lang == "ru")), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        STATE[uid] = {"action": "u_sell", "step": "link"}
        await send(tr(lang, "sell_1"), KB([[B(tr(lang, "b_cancel"), "u_mkt")]]))

    elif a == "u_sellp":
        st_ = STATE.get(uid)
        if st_ and st_.get("action") == "u_sell" and st_.get("price"):
            st_["step"] = "price"
            await send(tr(lang, "sell_5"), KB([[B(tr(lang, "b_cancel"), "u_mkt")]]))

    elif a == "u_sellok":
        st_ = STATE.get(uid)
        if not st_ or st_.get("action") != "u_sell" or st_.get("step") != "confirm":
            await show_market(c, q, uid, lang); return
        def f(d):
            x = d["users"].setdefault(str(uid), {})
            if x.get("mban", 0) > time.time(): return "ban"
            if uid not in ADMINS and any(L.get("link") == st_["link"] and L.get("status") in ("pending", "live") for L in d.get("market", {}).values()): return "dup"   # kurucu aynı linki tekrar koyabilir
            fee_ = seller_fee(x)
            if x.get("bal", 0) < fee_: return "nobal"
            x["bal"] -= fee_; d["mkt_fees"] = d.get("mkt_fees", 0) + fee_; x.pop("fee_x2", None)   # 2 kat ödendi: sonra yine normal
            lid = uuid.uuid4().hex[:6]
            d.setdefault("market", {})[lid] = {"owner": uid, "title": st_["title"], "link": st_["link"], "photo": st_["photo"], "desc": st_.get("desc", ""),
                                               "price": st_["price"], "codes": st_["codes"], "codes_ts": time.time(), "status": "pending", "created": time.time(), "photo_ok": False}
            return lid
        r = mutate(f); new_lid = r if r not in ("nobal", "dup", "ban") else None
        if r == "nobal": await send(tr(lang, "sell_nobal").replace("0.05$", fmt_u(seller_fee(load_db()["users"].get(str(uid), {}))) + "$"), KB([[B(tr(lang, "b_top"), "u_top", "success")], [B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        STATE.pop(uid, None)
        if r == "dup": await send(tr(lang, "sell_dup"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        if r == "ban": await send(tr(lang, "sell_banned", left="—"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        ulog("m_list", f"📤 Pazara ilan verdi: {who(user)} · {st_['title']} · {fmt_u(st_['price'])} USDT/dk")
        await send(tr(lang, "sell_sent"), KB([[B(tr(lang, "b_myl"), "u_myl")], [B(tr(lang, "b_back_mkt"), "u_mkt")]]))
        cap_ = (f"📤 <b>Yeni pazar ilanı</b> (incelemede)\n<blockquote>{esc(who(user))}\n🏷 {esc(st_['title'])} · {money_tmt(float(st_['price']) * 43200)} TMT/ay</blockquote>\n"
                "<i>⏳ Telefon testi bekleniyor. Fotoğrafı sen onaylayana kadar pazarda fotoğrafsız görünür.</i>")
        for fid_ in ADMINS:
            kb_ = photo_kb(new_lid, alang(fid_))
            try: await c.bot.send_photo(fid_, st_["photo"], caption=cap_, parse_mode="HTML", reply_markup=kb_)
            except Exception:
                try: await c.bot.send_message(fid_, cap_, parse_mode="HTML", reply_markup=kb_)
                except Exception: pass

    elif a == "u_myl":
        mine_l = sorted([(lid, L) for lid, L in db.get("market", {}).items() if L.get("owner") == uid and L.get("status") in ("pending", "live", "suspended")], key=lambda x: -x[1].get("created", 0))[:10]   # kaldırılan / reddedilen ilanlar görünmez
        if not mine_l: await send(tr(lang, "myl_none"), KB([[B(tr(lang, "b_sell"), "u_sell", "primary")], [B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        ss = db.get("msess", {}).values()
        def extra(L):
            st_ = L.get("st") or {}
            if L["status"] == "pending": return tr(lang, "myl_pend", ago=ago(L.get("pushed_ts")), a=st_.get("tested", 0), b=st_.get("total", len(L.get("codes", []))))
            if L["status"] == "suspended": return tr(lang, "myl_susp", left=dur_txt(max(0, L.get("until", 0) - time.time()), lang == "ru"))
            return ""
        body = "\n".join(tr(lang, "myl_item", st=tr(lang, "st_" + L["status"]), title=esc(L["title"]), vip=tr(lang, "vip_badge") if L.get("vip_until", 0) > time.time() else "",
                            m=money2(float(L["price"]) * 43200, True), n=sum(1 for x in ss if x["lid"] == lid and x["status"] == "on"),
                            earned=fmt_u(sum(x["total"] for x in ss if x["lid"] == lid)), extra=extra(L)) for lid, L in mine_l)
        rows = [[B(f"💎 VIP · {short(L['title'], 18)}", f"u_vip:{lid}", "primary")] for lid, L in mine_l if L["status"] == "live"]
        rows += [[B(tr(lang, "b_mlh", t=short(L['title'], 18)), f"u_mlh:{lid}")] for lid, L in mine_l]
        rows += [[B(f"🗑 {short(L['title'], 22)}", f"u_mld:{lid}", "danger")] for lid, L in mine_l if L["status"] in ("pending", "live")]
        await send(tr(lang, "myl") + "\n" + body, KB(rows + [[B(tr(lang, "b_back_mkt"), "u_mkt")]]))

    elif a.startswith("u_mlh:"):   # ilanın kullanım geçmişi (sadece ilan sahibi)
        lid = a.split(":", 1)[1]; L = db.get("market", {}).get(lid)
        if not L or L.get("owner") != uid: return
        tf = lambda t: datetime.datetime.fromtimestamp(t, TM_TZ).strftime("%d.%m %H:%M")
        ss = sorted([x for x in db.get("msess", {}).values() if x.get("lid") == lid], key=lambda x: -x["start"])[:15]
        lines = "\n".join(f"{'🟢' if x.get('status') == 'on' else '⚪'} {tf(x['start'])} → {tf(x['end']) if x.get('end') else tr(lang, 'mlh_now')}"
                          f" · {dur_txt((x.get('end') or time.time()) - x['start'], lang == 'ru')} · 💰 {fmt_u(x.get('total', 0))} USDT · 👤 …{str(x['buyer'])[-3:]}" for x in ss) or tr(lang, "mlh_none")
        await send(tr(lang, "mlh", title=esc(short(L["title"], 30)), lines=lines), KB([[B(tr(lang, "b_myl"), "u_myl")], [B(tr(lang, "b_back_mkt"), "u_mkt")]]))

    elif a.startswith("u_mld:"):   # önce sor: emin misin?
        lid = a.split(":", 1)[1]; L_ = db.get("market", {}).get(lid)
        if not L_ or L_.get("owner") != uid or L_.get("status") not in ("pending", "live"): await show_market(c, q, uid, lang); return
        n_ = sum(1 for x in db.get("msess", {}).values() if x["lid"] == lid and x["status"] == "on")
        await send(tr(lang, "mld_q", title=esc(short(L_["title"], 40)), n=n_),
                   KB([[B(tr(lang, "b_yes_mld"), f"u_mldy:{lid}", "danger")], [B(tr(lang, "b_no"), "u_myl")]]))

    elif a.startswith("u_mldy:"):
        lid = a.split(":", 1)[1]
        def f(d):
            L = d.get("market", {}).get(lid)
            if not L or L.get("owner") != uid or L.get("status") not in ("pending", "live"): return False
            L["status"] = "removed"; L["removed_ts"] = time.time(); L["removed_why"] = "seller"; return True
        if mutate(f): ulog("m_rm", f"🗑 Satıcı ilanını kaldırdı: {who(user)} · {lid}")
        await show_market(c, q, uid, lang)

    elif a == "u_top":
        STATE.pop(uid, None)
        await bsend("top", tr(lang, "top", bal=fmt_u(e.get("bal", 0))) + tr(lang, "top_sellers", sellers=" · ".join(USDT_SELLERS)),
                   KB([[B(f"{n} USDT", f"u_topa:{n}", "primary") for n in (1, 3, 5, 10)],
                       [B(f"{n * USDT_RATE} TMT", f"u_topa:{n}") for n in (1, 3, 5, 10)],   # aynı tutar, TMT karşılığıyla (ödeme yine CryptoBot)
                       [B(tr(lang, "b_other"), "u_topc")], [B(tr(lang, "b_menu"), "u_menu")]]))

    elif a.startswith("u_topa:"):
        await send(*topup_order(uid, user, lang, float(a.split(":", 1)[1])))

    elif a == "u_topc":
        STATE[uid] = {"action": "u_topamt"}
        await send(tr(lang, "top_ask"), KB([[B(tr(lang, "b_cancel"), "u_top")]]))

    elif a == "u_wd":
        adm_ = uid in ADMINS   # kurucu: bakiyedeki para da kazanç sayılır
        amt = e.get("earn", 0) + (e.get("bal", 0) if adm_ else 0)
        if amt < wd_min(uid): await send(tr(lang, "wd_min", earn=fmt_u(amt), min=fmt_u(wd_min(uid))), menu_btn); return
        def take(d):
            x = d["users"][str(uid)]
            ea, ba = x.get("earn", 0), (x.get("bal", 0) if adm_ else 0)
            if ea + ba < amt: return False
            from_e = min(ea, amt); x["earn"] = ea - from_e
            if amt > from_e: x["bal"] = ba - (amt - from_e)
            return (from_e, amt - from_e)
        took = mutate(take)
        if not took: return
        try:
            await asyncio.to_thread(crypto_transfer, user_id=uid, asset="USDT", amount=fmt_u(amt), spend_id=f"wd-{uid}-{int(time.time())}", comment="VPN pazarı kazancı")
        except Exception as ex:
            def back(d):
                x = d["users"][str(uid)]; x["earn"] = x.get("earn", 0) + took[0]
                if took[1]: x["bal"] = x.get("bal", 0) + took[1]
            mutate(back)
            if "INSUFFICIENT_FUNDS" in str(ex):
                av = await asyncio.to_thread(app_usdt)
                await notify_founders(c.application, f"⚠️ <b>Çekim yapılamadı: CryptoBot uygulama bakiyesi yetersiz</b>\n<blockquote>{esc(who(user))} · istenen {fmt_u(amt)} USDT\n💼 Uygulamada {av if av is not None else '?'} USDT</blockquote>\n<i>@CryptoBot → Crypto Pay → My Apps → uygulama → bakiye yükle.</i>")
                await send(tr(lang, "wd_nofund", usdt=fmt_u(amt)), menu_btn); return
            await send(tr(lang, "wd_err", err=esc(str(ex)[:100])), menu_btn); return
        ulog("m_wd", f"💸 Kazanç çekti: {who(user)} · {fmt_u(amt)} USDT")
        await send(tr(lang, "wd_ok", usdt=fmt_u(amt)), menu_btn)

    elif a == "u_lang":
        await send(*lang_pick("u"))

    elif a == "u_set":
        to = "p" if is_admin(uid) else "u"
        await bsend("set", tr(lang, "set_t", lname=LANG_NAMES.get(lang, lang), id=uid),
                    KB([[B(("✅ " if x == lang else "") + LANG_NAMES[x], f"u_setlang:{x}:{to}")] for x in ("tk", "tr", "ru")] + [[B(tr(lang, "b_menu"), "u_menu")]]))

    elif a.startswith("u_setlang:"):
        _, nl, to = a.split(":")
        if nl not in LANG_NAMES: return
        mutate(lambda d: d["users"].setdefault(str(uid), {}).__setitem__("lang", nl))
        LANGC[uid] = nl
        await show_home(c, uid, getattr(q, "message", None), to != "p", send)

    elif a == "u_free":
        if e.get("free_day") == tm_day():
            await bsend("free", tr(lang, "free_today"), menu_btn); return
        if avail_refs(e) < REF_NEED:
            await bsend("free", tr(lang, "free_need", need=REF_NEED, avail=max(0, avail_refs(e)), link=esc(ref_link(uid))),
                       KB([[B(tr(lang, "b_share"), switch_inline_query="", style="success")]]
                          + [[B(tr(lang, "b_menu"), "u_menu")]])); return
        # yer ayır (aynı anda iki kez basılırsa iki kod çıkmasın)
        def take(d):
            x = d["users"][str(uid)]
            if x.get("free_day") == tm_day() or avail_refs(x) < REF_NEED: return False
            x["free_day"] = tm_day(); x["spent"] = int(x.get("spent", 0)) + REF_NEED
            return True
        if not mutate(take):
            await send(tr(lang, "free_today"), menu_btn); return
        res, err = await asyncio.to_thread(make_code_for, uid, f"{short(user.first_name or 'VPN', 20)} 🎁", FREE_DAYS, "free")
        if not res:
            def undo(d):
                x = d["users"][str(uid)]; x.pop("free_day", None); x["spent"] = max(0, int(x.get("spent", 0)) - REF_NEED)
            mutate(undo)
            await send(tr(lang, "no_slot"), menu_btn)
            await notify_founders(c.application, f"⚠️ <b>Ücretsiz kod verilemedi</b>\n<blockquote>{esc(who(user))}\n{esc(err)}</blockquote>")
            return
        kid, fid = res
        mutate(lambda d: d["users"][str(uid)].__setitem__("free_n", int(d["users"][str(uid)].get("free_n", 0)) + 1))
        ulog("free", f"🎁 Ücretsiz kod aldı: {who(user)} · {kid} · {FREE_DAYS} gün")
        await send(tr(lang, "free_ok", left=left_txt(load_db()["subs"][kid].get("expires"), lang == "ru"), link=esc(await asyncio.to_thread(user_link, fid))), menu_btn)

    elif a == "u_trial":   # deneme kodu kaldırıldı (eski mesajlardaki buton menüye döner)
        await show_home(c, uid, getattr(q, "message", None), True, send)

    elif a.startswith("u_ext:"):
        kid = a.split(":", 1)[1]; s_ = db["subs"].get(kid)
        if not s_ or s_.get("owner_id") != uid: await send(tr(lang, "mine_none"), menu_btn); return
        await send(*ext_view(lang, kid, s_))

    elif a.startswith("u_xb:"):
        _, kid, item = a.split(":")
        s_ = db["subs"].get(kid)
        if not s_ or s_.get("owner_id") != uid or item not in PRICES: await send(tr(lang, "mine_none"), menu_btn); return
        await send(*new_order(uid, user, lang, item, ext=kid))

    elif a.startswith(("u_lnk:", "u_lnm:")):   # tek kodun linki ayrı mesajda (kopyalamak için)
        k = a.split(":", 1)[1]
        if a.startswith("u_lnk:"): s_ = db["subs"].get(k); fid_, nm_ = (s_ or {}).get("file_id"), name_of(s_ or {}, k); ok_ = s_ and s_.get("owner_id") == uid
        else: x_ = db.get("msess", {}).get(k, {}); fid_, nm_ = x_.get("fid"), db["market"].get(x_.get("lid"), {}).get("title", "?"); ok_ = x_.get("buyer") == uid
        if not ok_ or not fid_: return
        lnk = await asyncio.to_thread(user_link, fid_)
        await c.bot.send_message(uid, f"🎟 <b>{esc(short(nm_, 40))}</b>\n<code>{esc(lnk)}</code>", parse_mode="HTML")

    elif a.startswith("u_kdq:"):   # kodu silmeden önce sor
        kid = a.split(":", 1)[1]; s_ = db["subs"].get(kid)
        if not s_ or s_.get("owner_id") != uid: await send(tr(lang, "mine_none"), menu_btn); return
        await send(tr(lang, "del_q", name=esc(short(name_of(s_, kid), 30))), KB([[B(tr(lang, "b_yes_del"), f"u_kdy:{kid}", "danger")], [B(tr(lang, "b_no"), "u_mine")]]))

    elif a.startswith("u_kdy:"):
        kid = a.split(":", 1)[1]; s_ = db["subs"].get(kid)
        if s_ and s_.get("owner_id") == uid:
            if await asyncio.to_thread(delete_vip, kid):
                try: await q.answer(tr(lang, "deleted"))
                except Exception: pass
                ulog("del", f"🗑 Kodunu sildi: {who(user)} · {name_of(s_, kid)}")
        a = "u_mine"; db = load_db()

    if a == "u_mine":
        mine = user_codes(db, uid)
        sess = [(sid, x) for sid, x in db.get("msess", {}).items() if x["buyer"] == uid and x["status"] == "on"]
        await asyncio.to_thread(lambda: [user_link(f) for f in [s.get("file_id") for _, s in mine[:8]] + [x["fid"] for _, x in sess[:5]]])   # şifreli linkler önceden (bot beklemesin)
        if not mine and not sess: await bsend("mine", tr(lang, "mine_none"), menu_btn); return
        body = "\n".join(tr(lang, "mine_item", name=esc(short(name_of(s, k), 30)), left=left_txt(s.get("expires"), lang == "ru"), link=esc(user_link(s.get("file_id", "")))) for k, s in mine[:8])
        body2 = "\n".join(tr(lang, "mine_m", title=esc(short(db["market"].get(x["lid"], {}).get("title", "?"), 26)), dur=dur_txt(time.time() - x["start"], lang == "ru"),
                             usdt=fmt_u(x["total"]), link=esc(user_link(x["fid"]))) for sid, x in sess[:5])
        ext_rows = [[B(f"{tr(lang, 'b_ext')} · {short(name_of(s_, k), 18)}", f"u_ext:{k}")] for k, s_ in mine[:8] if s_.get("pub") in ("paid", "gift")]
        stop_rows = []
        for sid, x in sess[:5]:
            nm_ = short(db["market"].get(x["lid"], {}).get("title", "?"), 14)
            if len(sess) == 1: stop_rows += [[B(tr(lang, "b_live"), f"u_live:{sid}", "primary"), B(tr(lang, "b_stop"), f"u_msq:{sid}", "danger")]]
            else: stop_rows += [[B(f"📊 {short(nm_, 9)}", f"u_live:{sid}", "primary"), B(f"⏹ {short(nm_, 9)}", f"u_msq:{sid}", "danger")]]   # birden çok kod: adıyla
        del_rows = [[B(f"🗑 {short(name_of(s_, k), 18)}", f"u_kdq:{k}")] for k, s_ in mine[:8]]
        t_ = tr(lang, "mine") + "\n" + "\n".join(x for x in (body, body2) if x); link_rows = []
        if len(t_) > 3900:   # şifreli linkler uzun: liste linksiz, her link butonla ayrı mesajda
            hint = tr(lang, "link_below")
            body = "\n".join(tr(lang, "mine_item", name=esc(short(name_of(s, k), 30)), left=left_txt(s.get("expires"), lang == "ru"), link=hint) for k, s in mine[:8])
            body2 = "\n".join(tr(lang, "mine_m", title=esc(short(db["market"].get(x["lid"], {}).get("title", "?"), 26)), dur=dur_txt(time.time() - x["start"], lang == "ru"),
                                 usdt=fmt_u(x["total"]), link=hint) for sid, x in sess[:5])
            t_ = tr(lang, "mine") + "\n" + "\n".join(x for x in (body, body2) if x)
            link_rows = [[B(f"🔗 {short(name_of(s_, k), 20)}", f"u_lnk:{k}")] for k, s_ in mine[:8]] + \
                        [[B(f"🔗 {short(db['market'].get(x['lid'], {}).get('title', '?'), 20)}", f"u_lnm:{sid}")] for sid, x in sess[:5]]
        await bsend("mine", t_, KB(link_rows + ext_rows + stop_rows + del_rows + [[B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_prof":
        inv = db["users"].get(str(e.get("ref_by")), {}) if e.get("ref_by") else {}
        t = tr(lang, "prof", id=uid, name=esc(user.full_name or "—"), un=("@" + esc(user.username)) if user.username else "—",
               joined=tm_fmt(e.get("joined", time.time())), now=tm_now().strftime("%d.%m.%Y %H:%M"),
               total=len(e.get("refs", [])), avail=max(0, avail_refs(e)), need=REF_NEED, free=e.get("free_n", 0),
               active=len(user_codes(db, uid)), buys=e.get("buys", 0), inviter=esc(inv.get("name") or tr(lang, "nobody")),
               link=esc(ref_link(uid)))
        t += tr(lang, "bal_line", bal=f"{e.get('bal', 0) / UM:.2f}", tmt=f"{e.get('bal', 0) * USDT_RATE / UM:.2f}") + tr(lang, "bonus_line", b=f"{e.get('bonus', 0) * USDT_RATE / UM:.2f}") + (tr(lang, "earn_line", earn=(f"{e['earn'] / UM:.2f}" if e["earn"] >= UM // 100 else f"{e['earn'] / UM:.4f}")) if e.get("earn") else "")
        await bsend("prof", t, KB([[B(tr(lang, "b_share"), switch_inline_query="", style="success")],
                          [B(tr(lang, "b_myad"), "u_myad", "success")], [B(tr(lang, "b_top"), "u_top", "primary")]] + ([[B(tr(lang, "b_wd"), "u_wd", "primary")]] if e.get("earn") or (uid in ADMINS and e.get("bal")) else []) + [
                          [B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_myad":   # kullanıcının kendi davet linkiyle reklam postu (30 dakikada bir yenisi)
        v_ = 0
        steps = tr(lang, "myad_wait").split("|")
        pm_ = await c.bot.send_message(uid, steps[0], parse_mode="HTML")
        for st_ in steps[1:]:
            await asyncio.sleep(0.9)
            try: await pm_.edit_text(st_, parse_mode="HTML")
            except Exception: pass
        await asyncio.sleep(0.3)
        try: await pm_.delete()
        except Exception: pass
        try: await send_ad(c, uid, "ru" if lang == "ru" else "tk", uid, v_)
        except Exception as ex_: log.warning("myad: %s", ex_)
        await c.bot.send_message(uid, tr(lang, "myad_done", un=esc(BOT.get("un") or "SuBDrive_bot"), link=esc(ref_link(uid))), parse_mode="HTML",
                                 disable_web_page_preview=True, reply_markup=KB([[B(tr(lang, "b_prof"), "u_prof"), B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_market":
        STATE.pop(uid, None)
        await bsend("market", tr(lang, "market"), KB([[B(tr(lang, "b_c7"), "u_buy:c7")], [B(tr(lang, "b_c30"), "u_buy:c30")],
                                           [B(tr(lang, "b_panel"), "u_buy:panel")], [B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_buy:panel":
        STATE[uid] = {"action": "u_panel"}
        await send(tr(lang, "panel_ask"), KB([[B(str(n), f"u_pn:{n}", "primary" if n == 20 else None) for n in (20, 30, 50, 100)],
                                               [B(tr(lang, "b_back"), "u_market")]]))

    elif a.startswith("u_buy:") or a.startswith("u_pn:"):
        STATE.pop(uid, None)
        item = a.split(":", 1)[1] if a.startswith("u_buy:") else "panel"
        n = int(a.split(":", 1)[1]) if a.startswith("u_pn:") else 0
        await send(*new_order(uid, user, lang, item, n))

    elif a.startswith("u_paid:"):
        oid = a.split(":", 1)[1]
        def f(d):
            o = d.get("orders", {}).get(oid)
            if not o or o["uid"] != uid or o["status"] != "new": return None
            o["status"] = "paid"; o["paid_ts"] = time.time()
            return dict(o)
        o = mutate(f)
        if not o: await send(tr(lang, "order_old"), menu_btn); return
        ulog("paid", f"💳 Ödedim dedi: {who(user)} · #{oid} · {item_tr(o)} · {o['price']} TMT")
        await send(tr(lang, "order_sent", oid=oid), menu_btn)
        await notify_founders(c.application,
            f"🧾 <b>Yeni sipariş #{oid}</b>\n<blockquote>👤 {esc(who(user))}\n📦 {esc(item_tr(o))}\n💰 <b>{o['price']} TMT</b></blockquote>\n<i>Parayı aldıysan onayla; kod/panel otomatik verilir.</i>",
            KB([[B("✅ Onayla", f"ord_ok:{oid}", "success"), B("❌ Reddet", f"ord_no:{oid}", "danger")]]))

    elif a.startswith("u_usdt:"):
        oid = a.split(":", 1)[1]
        o = db.get("orders", {}).get(oid)
        if not o or o["uid"] != uid or o["status"] not in ("new", "paid"): await send(tr(lang, "order_old"), menu_btn); return
        us = usdt_of(o["price"])
        if not o.get("inv") or time.time() - o.get("inv_ts", 0) > 3500:   # yoksa ya da süresi dolmak üzereyse yeni fatura
            try:
                inv = await asyncio.to_thread(crypto_call, "createInvoice", asset="USDT", amount=us, description=f"#{oid} {item_tr(o)}"[:1000],
                                              payload=oid, expires_in=3600, allow_comments="false")
            except Exception as ex:
                log.warning("createInvoice: %s", ex); await send(tr(lang, "inv_err"), menu_btn); return
            def f(d):
                x = d["orders"][oid]; x["inv"], x["inv_url"], x["inv_ts"] = inv["invoice_id"], inv.get("bot_invoice_url") or inv.get("pay_url"), time.time()
                return dict(x)
            o = mutate(f)
            ulog("inv", f"💵 USDT faturası: {who(user)} · #{oid} · {us} USDT")
        it = tr(lang, "it_panel", n=o["n"]) if o["item"] == "panel" else (tr(lang, "it_top", usdt=us) if o["item"] == "topup" else tr(lang, "it_" + o["item"]))
        await send(tr(lang, "inv", oid=oid, item=esc(it), usdt=us),
                   KB([[B(tr(lang, "b_pay"), url=o["inv_url"], style="success")], [B(tr(lang, "b_chk"), f"u_chk:{oid}", "primary")]]
                      + ([[B("🟡 🧪 Ödendi say (test)", f"u_tpaid:{oid}", "primary")]] if uid in ADMINS else []) + [[B(tr(lang, "b_menu"), "u_menu")]]))

    elif a.startswith("u_pbal:") or a.startswith("u_pbon:"):   # 💰 bakiyeyle / 🎁 bonusla öde
        oid = a.split(":", 1)[1]; wal = "bonus" if a.startswith("u_pbon:") else "bal"
        def f(d):
            o_ = d.get("orders", {}).get(oid); x = d["users"].setdefault(str(uid), {})
            if not o_ or o_["uid"] != uid or o_["status"] != "new" or o_["item"] == "topup": return "old"
            if wal == "bonus" and o_["item"] not in PRICES: return "old"   # bonus sadece kod (7/30 gün) alımında
            cost = tmt_to_um(o_["price"])
            if x.get(wal, 0) < cost: return ("nobal", cost, x.get(wal, 0))
            x[wal] = x.get(wal, 0) - cost
            o_["status"] = "paid"; o_["via"] = wal; o_["bal_cost"] = cost
            return ("ok", cost)
        r_ = mutate(f)
        if r_ == "old": await send(tr(lang, "order_old"), menu_btn); return
        if r_[0] == "nobal":
            if wal == "bonus":
                await send(tr(lang, "pbon_need", need=f"{r_[1] * USDT_RATE / UM:.2f}", b=f"{r_[2] * USDT_RATE / UM:.2f}"), KB([[B(tr(lang, "b_menu"), "u_menu")]])); return
            await send(tr(lang, "pbal_need", need=fmt_u(r_[1]), bal=fmt_u(r_[2])),
                       KB([[B(tr(lang, "b_top"), "u_top", "success")], [B(tr(lang, "b_menu"), "u_menu")]])); return
        ulog("paid", f"{'🎁 Bonusla' if wal == 'bonus' else '💰 Bakiyeyle'} ödedi: {who(user)} · #{oid} · {fmt_u(r_[1])} USDT")
        msg = await fulfill_order(c.application, oid, True, uid)
        if load_db().get("orders", {}).get(oid, {}).get("status") != "done":   # teslim olmadı → para geri
            def back(d):
                x = d["users"][str(uid)]; x[wal] = x.get(wal, 0) + r_[1]; d["orders"][oid]["status"] = "cancel"
            mutate(back)
            await send(tr(lang, "pbal_fail"), menu_btn)
            await notify_founders(c.application, f"⚠️ <b>Bakiyeyle alım teslim edilemedi</b> (para iade edildi)\n<blockquote>{esc(who(user))} · #{oid}\n{msg}</blockquote>")

    elif a.startswith("u_tpaid:"):   # sadece kurucu: ödeme yapmadan teslimi dener, satışa sayılmaz
        if uid not in ADMINS: return
        oid = a.split(":", 1)[1]
        def f(d):
            x = d.get("orders", {}).get(oid)
            if not x or x["status"] not in ("new", "paid"): return False
            x["status"] = "paid"; x["via"] = "test"; x["test"] = True; return True
        if not mutate(f): await send(tr(lang, "order_old"), menu_btn); return
        ulog("test", f"🧪 Test ödemesi (ödendi sayıldı): {who(user)} · #{oid}")
        msg = await fulfill_order(c.application, oid, True, uid)
        await send(f"🧪 <b>Test</b>\n<blockquote>{msg}</blockquote>\n<i>Kod/panel teslim mesajı ayrıca geldi. Bu sipariş satışlara sayılmaz.</i>", menu_btn)

    elif a.startswith("u_chk:"):
        oid = a.split(":", 1)[1]
        o = db.get("orders", {}).get(oid)
        if not o or o["uid"] != uid: return
        if o["status"] in ("done", "busy"): await send(tr(lang, "order_old"), menu_btn); return
        if not await check_invoices(c.application, [oid]):
            await q.answer(tr(lang, "inv_wait"), show_alert=True)

    elif a.startswith("u_cancel:"):
        oid = a.split(":", 1)[1]
        mutate(lambda d: d.get("orders", {}).get(oid, {}).__setitem__("status", "cancel") if d.get("orders", {}).get(oid, {}).get("status") == "new" else None)
        await show_home(c, uid, getattr(q, "message", None), True, send)

def item_tr(o):
    if o["item"] == "topup": return f"Bakiye yükleme · {usdt_of(o['price'])} USDT"
    if o["item"] == "panel": return f"Panel · {o['n']} kullanıcı · {PANEL_DAYS} gün"
    if o.get("ext"): return f"Uzatma · {PRICES[o['item']][0]} gün"
    return f"Kod · {PRICES[o['item']][0]} gün"

def new_order(uid, user, lang, item, n=0, ext=None):
    if item == "panel":
        if n < PANEL_MIN: return tr(lang, "panel_min"), KB([[B(tr(lang, "b_back"), "u_buy:panel")]])
        price, it = n * PANEL_PRICE, tr(lang, "it_panel", n=n)
    elif item in PRICES and ext:
        price = PRICES[item][1]
        it = tr(lang, "it_ext", days=PRICES[item][0], name=name_of(load_db()["subs"].get(ext, {}), ext))
    elif item in PRICES: price, it = PRICES[item][1], tr(lang, "it_" + item)
    else: return pub_menu(load_db(), uid)
    oid = uuid.uuid4().hex[:6].upper()
    o = {"uid": uid, "item": item, "n": n, "price": price, "ts": time.time(), "status": "new", "who": who(user)}
    if ext: o["ext"] = ext
    def f(d): d.setdefault("orders", {})[oid] = o
    mutate(f)
    ulog("order", f"🧾 Sipariş açtı: {who(user)} · #{oid} · {item_tr(o)} · {price} TMT")
    us = usdt_of(price); has = bool(crypto_token())
    rows = [[B(tr(lang, "b_pbal", usdt=fmt_u(tmt_to_um(price))), f"u_pbal:{oid}", "success")]] + \
           ([[B(tr(lang, "b_pbon", tmt=price), f"u_pbon:{oid}", "success")]] if item in PRICES else []) + \
           ([[B(tr(lang, "b_usdt", usdt=us), f"u_usdt:{oid}", "success")]] if has else []) + [[B(tr(lang, "b_cancel"), f"u_cancel:{oid}", "danger")]]
    # TMT ile ödeme henüz açık değil ("yakında"); açılınca eski TMT akışı (u_paid -> admin onayı) kullanılabilir
    t = (f"🧾 <b>{'Заказ' if lang == 'ru' else 'Sipariş'} #{oid}</b>\n<blockquote>{esc(it)}\n💰 {'Сумма' if lang == 'ru' else 'Tutar'}  <b>{price} TMT</b>  ·  <b>{us} USDT</b></blockquote>\n"
         + (tr(lang, "usdt_line") if has else tr(lang, "pay_off")) + tr(lang, "tmt_soon"))
    return t, KB(rows)

async def pub_msg(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """Kullanıcının yazdığı mesaj: şimdilik sadece panel kullanıcı sayısı."""
    uid = u.effective_user.id
    if is_banned(uid): return
    st = STATE.get(uid)
    db = load_db(); lang = lang_of(db, uid)
    async def send(t, kb): await u.message.reply_text(t, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    if not st or st.get("action") != "u_panel":
        if str(uid) not in db.get("users", {}): return await pub_start(u, c)
        if not await pub_gate(c, uid, lang, send): return
        await show_home(c, uid, pub=True); return
    m = re.fullmatch(r"\s*(\d{1,4})\s*", u.message.text or "")
    if not m: await u.message.reply_text(tr(lang, "panel_min")); return
    STATE.pop(uid, None)
    await send(*new_order(uid, u.effective_user, lang, "panel", int(m.group(1))))

async def fulfill_order(c, oid, approve, admin_uid):
    """Kurucu onayladı/reddetti. Dönüş: kurucuya gösterilecek metin."""
    def f(d):
        o = d.get("orders", {}).get(oid)
        if not o or o["status"] not in ("new", "paid"): return None
        o["status"] = "busy" if approve else "rejected"
        return dict(o)
    o = mutate(f)
    if not o: return "ℹ️ Bu sipariş zaten işlendi."
    uid = o["uid"]; db = load_db(); lang = lang_of(db, uid)
    if not approve:
        ulog("rej", f"❌ Sipariş reddedildi: {o.get('who')} · #{oid}")
        audit(admin_uid, f"order_no {oid}")
        try: await c.bot.send_message(uid, tr(lang, "order_no", oid=oid), parse_mode="HTML")
        except Exception: pass
        return f"❌ Sipariş #{oid} reddedildi."
    if o["item"] == "topup":
        amt = int(round(o["price"] / USDT_RATE * UM))
        def p(d):
            x = d.setdefault("users", {}).setdefault(str(uid), {}); x["bal"] = x.get("bal", 0) + amt
            d["orders"][oid]["status"] = "done"; d["orders"][oid]["done_ts"] = time.time()
            return x["bal"]
        bal = mutate(p)
        msg = tr(lang, "top_ok", usdt=fmt_u(amt), bal=fmt_u(bal))
    elif o["item"] == "panel":
        def p(d):
            e = d.setdefault("sub_admins", {}).get(str(uid), {})
            active = float(e.get("expires", 0)) > time.time()
            e["limit"] = (int(e.get("limit", 0)) if active else 0) + o["n"]
            e["expires"] = max(time.time(), float(e.get("expires", 0))) + PANEL_DAYS * 86400
            e.setdefault("added", time.time()); e["name"] = d.get("users", {}).get(str(uid), {}).get("name", "")
            e.pop("warned", None); e.pop("ended", None)
            d["sub_admins"][str(uid)] = e
            d["orders"][oid]["status"] = "done"; d["orders"][oid]["done_ts"] = time.time()
            d.setdefault("users", {}).setdefault(str(uid), {})["buys"] = int(d["users"][str(uid)].get("buys", 0)) + 1
            return e
        e = mutate(p)
        msg = tr(lang, "order_ok_panel", oid=oid, n=e["limit"], days=PANEL_DAYS)
    elif o.get("ext") and db["subs"].get(o["ext"], {}).get("owner_id") == uid:   # aynı kodu uzat (link değişmez)
        s_ = await asyncio.to_thread(extend_code, o["ext"], PRICES[o["item"]][0])
        def p(d):
            d["orders"][oid]["status"] = "done"; d["orders"][oid]["done_ts"] = time.time()
            d.setdefault("users", {}).setdefault(str(uid), {})["buys"] = int(d["users"][str(uid)].get("buys", 0)) + 1
        mutate(p)
        msg = tr(lang, "order_ok_ext", oid=oid, name=esc(name_of(s_, o["ext"])), left=left_txt(s_.get("expires"), lang == "ru"))
    else:
        days = PRICES[o["item"]][0]
        nm = db.get("users", {}).get(str(uid), {}).get("name") or str(uid)
        res, err = await asyncio.to_thread(make_code_for, uid, f"{short(nm, 20)} 💎", days, "paid")
        if not res:
            mutate(lambda d: d["orders"][oid].__setitem__("status", "paid"))   # tekrar onaylanabilsin
            return f"⚠️ Kod oluşturulamadı: {esc(err)}\nSipariş bekliyor, sonra tekrar onayla."
        kid, fid = res
        def p(d):
            d["orders"][oid]["status"] = "done"; d["orders"][oid]["kid"] = kid; d["orders"][oid]["done_ts"] = time.time()
            d.setdefault("users", {}).setdefault(str(uid), {})["buys"] = int(d["users"][str(uid)].get("buys", 0)) + 1
        mutate(p)
        msg = tr(lang, "order_ok_code", oid=oid, left=left_txt(load_db()["subs"][kid].get("expires"), lang == "ru"), link=esc(user_link(fid)))
    ulog("ok", f"✅ Sipariş onaylandı: {o.get('who')} · #{oid} · {item_tr(o)} · {o['price']} TMT")
    audit(admin_uid, f"order_ok {oid}")
    try: await c.bot.send_message(uid, msg, parse_mode="HTML", disable_web_page_preview=True)
    except Exception: pass
    return f"✅ Sipariş #{oid} onaylandı ve kullanıcıya gönderildi."

async def check_invoices(app, only=None):
    """Bekleyen USDT faturalarını CryptoBot'ta kontrol eder; ödenenleri otomatik teslim eder. Dönüş: teslim edilen sayısı."""
    if not crypto_token(): return 0
    db = load_db()
    tst = db.get("cp_test")
    if tst and only is None:   # kurucunun test faturası
        try:
            items = (await asyncio.to_thread(crypto_call, "getInvoices", invoice_ids=str(tst["inv"]))).get("items", [])
            stt = items[0].get("status") if items else "expired"
            if stt == "paid":
                mutate(lambda d: d.pop("cp_test", None))
                await notify_founders(app, "✅ <b>Test ödemesi geldi</b> (0.1 USDT)\n<blockquote>CryptoBot bağlantısı ve otomatik ödeme kontrolü çalışıyor.</blockquote>")
            elif stt == "expired" or time.time() - tst.get("ts", 0) > 3700:
                mutate(lambda d: d.pop("cp_test", None))
        except Exception as e: log.warning("test invoice: %s", e)
    pend = {oid: o for oid, o in db.get("orders", {}).items() if o.get("inv") and o["status"] in ("new", "paid") and (only is None or oid in only)}
    pend = {k: o for k, o in pend.items() if time.time() - o.get("inv_ts", 0) < 2 * 86400}
    if not pend: return 0
    try:
        res = await asyncio.to_thread(crypto_call, "getInvoices", invoice_ids=",".join(str(o["inv"]) for o in pend.values()), count=1000)
    except Exception as e:
        log.warning("getInvoices: %s", e); return 0
    paid = {int(x["invoice_id"]) for x in res.get("items", []) if x.get("status") == "paid"}
    n = 0
    for oid, o in pend.items():
        if int(o["inv"]) not in paid: continue
        def f(d):
            x = d["orders"].get(oid)
            if x and x["status"] in ("new", "paid"): x["status"] = "paid"; x["via"] = "usdt"; return True
        if not mutate(f): continue
        ulog("usdt", f"💵 USDT ödendi: {o.get('who')} · #{oid} · {usdt_of(o['price'])} USDT")
        msg = await fulfill_order(app, oid, True, 0)
        await notify_founders(app, f"💵 <b>USDT ödemesi alındı</b> #{oid}\n<blockquote>👤 {esc(o.get('who'))}\n📦 {esc(item_tr(o))}\n💰 {usdt_of(o['price'])} USDT</blockquote>\n{msg}")
        n += 1
    return n

def app_usdt():
    """CryptoBot uygulamasındaki kullanılabilir USDT (yazı). Bilinmiyorsa None."""
    try:
        for b in crypto_call("getBalance"):
            if b.get("currency_code") == "USDT": return b.get("available")
        return "0"
    except Exception: return None

def crypto_view():
    tok = crypto_token()
    if tok:
        try: me = crypto_call("getMe"); st = f"🟢 Bağlı: <b>{esc(me.get('name'))}</b>"
        except Exception as e: st = f"🔴 Token çalışmıyor: <code>{esc(str(e)[:100])}</code>"
        else:
            av = app_usdt()
            if av is not None: st += f"\n💼 Uygulama bakiyesi  <b>{av} USDT</b>\n<i>Kullanıcı çekimleri bu bakiyeden ödenir.</i>"
    else: st = "⚪️ Bağlı değil — USDT butonu kullanıcılara görünmüyor."
    t = ("🪙 <b>CryptoBot (USDT)</b>\n<blockquote>" + st + f"\n💱 1 USDT = {USDT_RATE} TMT</blockquote>\n"
         "<i>Token almak: @CryptoBot → Crypto Pay → Create App → API Token.</i>")
    tst = load_db().get("cp_test") or {}
    if tst: t += f"\n🧪 Test ödemesi bekleniyor ({ago(tst.get('ts'))} açıldı)."
    rows = ([[B("🧪 Test Ödemesi (0.1 USDT)", "cp_test", "success")]] if tok else []) + ([[B("💸 Testi Öde", url=tst["url"])]] if tok and tst.get("url") else []) + \
           [[B("🔑 Token Gir", "cp_set", "primary")]] + ([[B("🗑 Bağlantıyı Kaldır", "cp_del", "danger")]] if tok else []) + [[B("◀️ Admin", "admin")]]
    return t, KB(rows)

# ── kurucu ekranları ──
def ulog_view(page=None):
    lines = ulog_lines()
    pages = max(1, (len(lines) + ULOG_PAGE - 1) // ULOG_PAGE)
    page = pages - 1 if page is None else max(0, min(page, pages - 1))
    chunk = lines[page * ULOG_PAGE:(page + 1) * ULOG_PAGE]
    body = "\n".join(f"<code>{datetime.datetime.fromtimestamp(x['t'], TM_TZ):%d.%m %H:%M}</code> {esc(x.get('x', ''))}" for x in chunk) or "<i>Henüz kayıt yok.</i>"
    t = f"👥 <b>Kullanıcı Logları</b>  <code>{len(lines)}</code>\n<blockquote expandable>{body}</blockquote>"
    nav = [B("⏮", "ul:0"), B("◀️", f"ul:{max(0, page - 1)}"), B(f"{page + 1}/{pages}", f"ul:{page}"),
           B("▶️", f"ul:{min(pages - 1, page + 1)}"), B("⏭", f"ul:{pages - 1}")]
    return t, KB([nav, [B("◀️ Admin", "admin")]])

def pool_count():
    try:
        svc = new_service(); db = load_db()
        return len((set(pool_files(svc)) | set(db["free_files"])) - used_fids(db))
    except Exception: return "?"

def stats_text():
    db = load_db(); us = db.get("users", {})
    today = tm_now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    pub = [s for s in db["subs"].values() if s.get("pub") and not is_exp(s)]
    orders = db.get("orders", {}).values()
    paid = sum(o["price"] for o in orders if o["status"] == "done" and not o.get("test") and o.get("item") != "topup")
    return ("📊 <b>İstatistik</b>\n<blockquote>"
            f"👥 Kullanıcı  <b>{len(us)}</b>  ·  bugün <b>{sum(1 for e in us.values() if e.get('joined', 0) >= today)}</b>\n"
            f"🤝 Sayılan davet  <b>{sum(len(e.get('refs', [])) for e in us.values())}</b>\n"
            f"🎁 Aktif ücretsiz kod  <b>{sum(1 for s in pub if s['pub'] == 'free')}</b>\n"
            f"💎 Aktif satılmış kod  <b>{sum(1 for s in pub if s['pub'] == 'paid')}</b>\n"
            f"🖥 Aktif panel  <b>{sum(1 for e in db.get('sub_admins', {}).values() if float(e.get('expires', 0)) > time.time())}</b>\n"
            f"🧾 Bekleyen sipariş  <b>{sum(1 for o in orders if o['status'] == 'paid')}</b>\n"
            f"💰 Onaylanan satış  <b>{paid} TMT</b>\n"
            f"📂 Boş kod yeri (Drive)  <b>{pool_count()}</b></blockquote>")

def channels_view():
    chans = load_db().get("channels", [])
    body = "\n".join(f"📢 {esc(ch.get('title'))}  <code>{ch['id']}</code>" for ch in chans) or "Kanal yok — herkes botu kullanabilir."
    rows = [[B(f"🗑 {short(ch.get('title') or ch['id'], 28)}", f"chd:{i}", "danger")] for i, ch in enumerate(chans)]
    rows += [[B("➕ Kanal Ekle", "ch_add", "success")], [B("◀️ Admin", "admin")]]
    return ("📢 <b>Zorunlu Kanallar</b>\n<blockquote>" + body + "</blockquote>\n"
            "<i>Kurucular dışında herkes bu kanallara abone olmadan botu kullanamaz. Bot kanalda admin olmalı.</i>"), KB(rows)

async def add_channel(c, txt, fwd_chat=None):
    """@kullanıcıadı, -100… ID ya da kanaldan iletilen mesaj. Dönüş: mesaj."""
    try:
        chat = fwd_chat or await c.bot.get_chat(txt.strip() if txt.strip().startswith(("@", "-")) else "@" + txt.strip().lstrip("@").split("/")[-1])
        me = await c.bot.get_me()
        m = await c.bot.get_chat_member(chat.id, me.id)
        if m.status not in ("administrator", "creator"):
            return "⚠️ Bot bu kanalda admin değil. Önce botu kanala admin olarak ekle."
        link = f"https://t.me/{chat.username}" if chat.username else (getattr(chat, "invite_link", None) or await c.bot.export_chat_invite_link(chat.id))
    except Exception as e:
        return f"⚠️ Kanal bulunamadı ya da erişilemedi: {esc(str(e)[:150])}"
    def f(d):
        chs = d.setdefault("channels", [])
        if any(x["id"] == chat.id for x in chs): return False
        chs.append({"id": chat.id, "title": chat.title or str(chat.id), "link": link}); return True
    ok = mutate(f)
    JOINED.clear()
    return f"✅ Kanal eklendi: <b>{esc(chat.title)}</b>" if ok else "ℹ️ Bu kanal zaten ekli."

async def broadcast(app, text, admin_uid):
    ids = [int(k) for k in load_db().get("users", {}) if int(k) not in ADMINS]
    ok = bad = 0
    for i in ids:
        try: await app.bot.send_message(i, text, disable_web_page_preview=True); ok += 1
        except Exception: bad += 1
        await asyncio.sleep(0.05)   # Telegram sınırı: saniyede ~30 mesaj
    audit(admin_uid, f"broadcast ok={ok} bad={bad}")
    await notify_founders(app, f"📣 <b>Herkese mesaj gönderildi</b>\n<blockquote>✅ {ok}  ·  ❌ {bad} <i>(botu engelleyenler)</i></blockquote>")


# ───────── DESTEK (talep) + HATA BİLDİRİMİ ─────────
SUP_MAX = 3                      # admin cevap vermeden kullanıcının gönderebileceği mesaj sayısı
SUP_EVERY = 60                   # destek / bug: kullanıcı 60 saniyede tek mesaj gönderebilir
SUP_LIMIT_MB = {"photo": 5, "other": 10}
ERRS = {}                        # hata no -> bilgi (Admine Bildir butonu için)
ERR_SEEN = {}                    # uid -> son hata mesajı zamanı (aynı kişiye arka arkaya hata yağmasın)
from telegram.ext import ApplicationHandlerStop

T["tr"].update({
  "b_sup": "🆘 Support", "b_bug": "🐞 Bug Bildir", "b_tclose": "🔒 Talebi Kapat", "b_report": "📨 Admine Bildir",
  "bug_new": "🐞 <b>Hata Bildir · #{tid}</b>\n<blockquote>Bulduğun hatayı anlat. Ekran görüntüsü ya da video ekleyebilirsin.\n📷 Fotoğraf en fazla 5 MB · 🎬 Video/dosya en fazla 10 MB</blockquote>\n<i>Admin cevap verince burada görürsün; sen de cevap yazabilirsin.</i>",
  "sup_new": "🆘 <b>Destek · #{tid}</b>\n<blockquote>Sorununu yaz. Fotoğraf, video ya da dosya da gönderebilirsin.\n📷 Fotoğraf en fazla 5 MB · 🎬 Video/dosya en fazla 10 MB</blockquote>\n<i>Admin cevap verince burada görürsün; sen de cevap yazabilirsin. Talep kapanana kadar konuşma devam eder.</i>",
  "sup_open": "🆘 <b>Destek · #{tid}</b>\n<blockquote>Talebin açık. Mesaj yazabilirsin; admin cevap verince burada görürsün.</blockquote>",
  "sup_sent": "✅ İletildi. Admin cevabını bekle.",
  "sup_wait": "⏳ Önce admin cevabını bekle (cevapsız en fazla 3 mesaj).",
  "sup_big": "⚠️ Dosya çok büyük. Fotoğraf en fazla 5 MB, video/dosya en fazla 10 MB.",
  "sup_reply": "💬 <b>Destek cevabı</b> · #{tid}",
  "sup_closed_admin": "🔒 Destek talebin #{tid} kapatıldı. Yeni bir sorun olursa 🆘 Destek'e bas.",
  "sup_closed": "🔒 Talep #{tid} kapatıldı.",
  "err": "⚠️ <b>Bir hata oluştu.</b>\n<blockquote>İşlem tamamlanamadı. Tekrar dene; sorun sürerse admine bildir.</blockquote>",
  "reported": "✅ Admine bildirildi, teşekkürler.",
  "tmt_soon": "💳 <b>TMT ile ödeme</b> — <i>yakında 🔜</i>",
  "pay_off": "⚠️ Online ödeme şu an kapalı.\n\n",
})
T["ru"].update({
  "b_sup": "🆘 Поддержка", "b_bug": "🐞 Баг-репорт", "b_tclose": "🔒 Закрыть обращение", "b_report": "📨 Сообщить админу",
  "bug_new": "🐞 <b>Баг-репорт · #{tid}</b>\n<blockquote>Опишите найденную ошибку. Можно добавить скриншот или видео.\n📷 Фото до 5 МБ · 🎬 Видео/файл до 10 МБ</blockquote>\n<i>Ответ администратора придёт сюда, вы сможете ответить.</i>",
  "sup_new": "🆘 <b>Поддержка · #{tid}</b>\n<blockquote>Опишите проблему. Можно отправить фото, видео или файл.\n📷 Фото до 5 МБ · 🎬 Видео/файл до 10 МБ</blockquote>\n<i>Ответ администратора придёт сюда, вы сможете ответить. Переписка идёт, пока обращение не закрыто.</i>",
  "sup_open": "🆘 <b>Поддержка · #{tid}</b>\n<blockquote>Обращение открыто. Пишите сообщение — ответ администратора придёт сюда.</blockquote>",
  "sup_sent": "✅ Отправлено. Ждите ответа администратора.",
  "sup_wait": "⏳ Сначала дождитесь ответа администратора (не больше 3 сообщений без ответа).",
  "sup_big": "⚠️ Файл слишком большой. Фото до 5 МБ, видео/файл до 10 МБ.",
  "sup_reply": "💬 <b>Ответ поддержки</b> · #{tid}",
  "sup_closed_admin": "🔒 Ваше обращение #{tid} закрыто. Если появится новая проблема — нажмите 🆘 Поддержка.",
  "sup_closed": "🔒 Обращение #{tid} закрыто.",
  "err": "⚠️ <b>Произошла ошибка.</b>\n<blockquote>Действие не выполнено. Попробуйте ещё раз; если не получится — сообщите админу.</blockquote>",
  "reported": "✅ Админ уведомлён, спасибо.",
  "tmt_soon": "💳 <b>Оплата в TMT</b> — <i>скоро 🔜</i>",
  "pay_off": "⚠️ Онлайн-оплата сейчас недоступна.\n\n",
})

def open_ticket(db, uid):
    tid = db.get("users", {}).get(str(uid), {}).get("ticket")
    return tid if tid and db.get("tickets", {}).get(tid, {}).get("status") == "open" else None

def media_size(m):
    """(bayt, sınır MB). Yazı ise 0."""
    if m.photo: return (m.photo[-1].file_size or 0), SUP_LIMIT_MB["photo"]
    for a in (m.video, m.document, m.audio, m.voice, m.animation, m.video_note):
        if a: return (a.file_size or 0), SUP_LIMIT_MB["other"]
    return 0, SUP_LIMIT_MB["other"]

def remember_tmsg(mid, tid):
    def f(d):
        tm = d.setdefault("tmsg", {})
        tm[str(mid)] = tid
        if len(tm) > 2000:
            for k in list(tm)[:500]: tm.pop(k, None)
    mutate(f)

async def copy_with_header(bot, to, from_chat, m, header, kb):
    """Yazıyı başlıkla birlikte gönderir; medyayı başlık açıklama olacak şekilde kopyalar. Dönüş: gönderilen mesaj no."""
    if m.text:
        r = await bot.send_message(to, header + "\n\n" + esc(m.text), parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        return r.message_id
    if m.sticker or m.video_note or m.dice or m.location or m.contact or m.poll:   # açıklama alamayan türler
        await bot.send_message(to, header, parse_mode="HTML")
        r = await bot.copy_message(to, from_chat, m.message_id, reply_markup=kb)
        return r.message_id
    cap = header + (("\n\n" + esc(m.caption)) if m.caption else "")
    r = await bot.copy_message(to, from_chat, m.message_id, caption=cap[:1024], parse_mode="HTML", reply_markup=kb)
    return r.message_id

async def user_to_ticket(c, u, tid):
    m, user = u.message, u.effective_user
    uid = user.id; lang = lang_of(load_db(), uid)
    size, lim = media_size(m)
    if size > lim * 1024 * 1024:
        await m.reply_text(tr(lang, "sup_big")); return
    mg = getattr(m, "media_group_id", None); now = time.time()
    def f(d):
        t = d["tickets"][tid]
        if mg and t.get("mg") == mg and now - t.get("last_user", 0) < 60:   # aynı albümün devamı
            t["last"] = now; return "album"
        if now - t.get("last_user", 0) < SUP_EVERY: return int(SUP_EVERY - (now - t.get("last_user", 0))) + 1
        if t.get("pending", 0) >= SUP_MAX: return None
        t["pending"] = t.get("pending", 0) + 1; t["n"] = t.get("n", 0) + 1; t["last"] = now; t["last_user"] = now; t["mg"] = mg
        return True
    r_ = mutate(f)
    if r_ is None:
        await m.reply_text(tr(lang, "sup_wait")); return
    if isinstance(r_, int) and r_ is not True:
        await m.reply_text(tr(lang, "sup_slow", s=r_)); return
    kind = load_db().get("tickets", {}).get(tid, {}).get("kind")
    hdr = f"{'🐞 <b>Hata Raporu' if kind == 'bug' else '🎫 <b>Destek'} #{tid}</b> · {esc(who(user))}"
    kb = KB([[B("✍️ Yanıtla", f"t_rep:{tid}", "primary"), B("🔒 Kapat", f"t_close:{tid}", "danger")]])
    for fid in ADMINS:
        try: remember_tmsg(await copy_with_header(c.bot, fid, uid, m, hdr, kb), tid)
        except Exception as e: log.warning("destek iletilemedi: %s", e)
    if r_ == "album": return
    await m.reply_text(tr(lang, "sup_sent") + "\n" + tr(lang, "sup_rate"), parse_mode="HTML", reply_markup=KB([[B(tr(lang, "b_twrite"), "u_tw", "primary")], [B(tr(lang, "b_tclose"), "u_tclose", "danger")]]))

async def admin_reply(c, admin_uid, tid, m):
    t = load_db().get("tickets", {}).get(tid)
    if not t or t.get("status") != "open":
        await m.reply_text(f"ℹ️ Talep #{tid} kapalı."); return
    uid = t["uid"]; lang = lang_of(load_db(), uid)
    try:
        await copy_with_header(c.bot, uid, admin_uid, m, tr(lang, "sup_reply", tid=tid), KB([[B(tr(lang, "b_tclose"), "u_tclose", "danger")]]))
    except Exception as e:
        await m.reply_text(f"⚠️ Gönderilemedi: {esc(str(e)[:150])}", parse_mode="HTML"); return
    def f(d):
        x = d["tickets"][tid]; x["pending"] = 0; x["last"] = time.time(); x["n"] = x.get("n", 0) + 1
    mutate(f)
    await m.reply_text(f"✅ Cevap gönderildi · #{tid}", reply_markup=KB([[B("🔒 Talebi Kapat", f"t_close:{tid}", "danger")]]))

async def close_ticket(c, tid, by_admin):
    def f(d):
        t = d.get("tickets", {}).get(tid)
        if not t or t.get("status") != "open": return None
        t["status"] = "closed"; t["closed"] = time.time()
        d.get("users", {}).get(str(t["uid"]), {}).pop("ticket", None)
        return dict(t)
    t = mutate(f)
    if not t: return False
    ulog("t_close", f"🔒 Destek #{tid} kapatıldı ({'admin' if by_admin else 'kullanıcı'}): {t.get('who')}")
    if by_admin:
        try: await c.bot.send_message(t["uid"], tr(lang_of(load_db(), t["uid"]), "sup_closed_admin", tid=tid))
        except Exception: pass
    else:
        await notify_founders(c.application if hasattr(c, "application") else c, f"🔒 Kullanıcı destek talebini kapattı · #{tid}\n<blockquote>{esc(t.get('who'))}</blockquote>")
    return True

async def support_router(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """Her mesajdan ÖNCE çalışır: açık destek talebi ya da kurucu cevabı varsa mesajı oraya yönlendirir."""
    m = u.message
    if not m or not u.effective_user or m.chat.type != "private": return
    uid = u.effective_user.id
    st0 = STATE.get(uid) or {}
    if st0.get("action") in ("u_sell", "u_topamt"):   # pazar: ilan adımları / yükleme tutarı (yazı ya da fotoğraf)
        if not is_banned(uid): await market_input(c, u, st0)
        raise ApplicationHandlerStop
    if uid in ADMINS:
        st = STATE.get(uid) or {}
        if st.get("action") == "own_photo":
            if not m.photo: await m.reply_text("⚠️ Fotoğraf gönder."); raise ApplicationHandlerStop
            STATE.pop(uid, None); fid_ = m.photo[-1].file_id
            mutate(lambda d: ensure_own(d)[OWN_LID].__setitem__("photo", fid_))
            audit(uid, "own_photo")
            t, kb = mkt_admin_view(); await m.reply_text("✅ Fotoğraf kaydedildi.\n\n" + t, parse_mode="HTML", reply_markup=kb)
            raise ApplicationHandlerStop
        tid = st.get("tid") if st.get("action") == "t_reply" else None
        if not tid and m.reply_to_message:
            tid = load_db().get("tmsg", {}).get(str(m.reply_to_message.message_id))
        if not tid: return
        if st.get("action") == "t_reply": STATE.pop(uid, None)
        await admin_reply(c, uid, tid, m)
        raise ApplicationHandlerStop
    if st0.get("action") == "t_write":   # ✍️ Yaz'a bastı: bu mesaj talebe gider
        STATE.pop(uid, None)
        if is_banned(uid): raise ApplicationHandlerStop
        tid = open_ticket(load_db(), uid) or st0.get("tid")
        if open_ticket(load_db(), uid): await user_to_ticket(c, u, tid)
        raise ApplicationHandlerStop
    if uid in STATE or is_banned(uid): return    # başka bir işlem bekleniyor (ör. panel kullanıcı sayısı) / engelli
    tid = open_ticket(load_db(), uid)
    if not tid: return
    await user_to_ticket(c, u, tid)
    raise ApplicationHandlerStop

def tickets_view(only_bug=False):
    db = load_db()
    op = [(k, t) for k, t in db.get("tickets", {}).items() if t.get("status") == "open"]
    op.sort(key=lambda x: -x[1].get("last", x[1].get("ts", 0)))
    if only_bug: op = [x for x in op if x[1].get("kind") == "bug"]
    ic = lambda t: "🐞" if t.get("kind") == "bug" else "🎫"
    body = "\n".join(f"{'🔴' if t.get('pending') else '🟢'}{ic(t)} <b>#{k}</b> · {esc(short(t.get('who', '?'), 40))} · {ago(t.get('last', t.get('ts')))}" for k, t in op[:20]) or "Açık talep yok."
    rows = [[B(f"{'🔴' if t.get('pending') else '🟢'}{ic(t)} #{k} · {short(t.get('who', '?'), 16)}", f"tv:{k}")] for k, t in op[:20]] + [[B("◀️ Menü", "menu"), B("⚙️ Admin", "admin")]]
    return f"{'🐞 <b>Hata Raporları' if only_bug else '🎫 <b>Destek Talepleri'}</b>  <code>{len(op)}</code>\n<blockquote>{body}</blockquote>\n<i>🔴 = cevap bekliyor · 🐞 = hata raporu</i>", KB(rows)

async def send_error(c, uid, where, err):
    """Kullanıcıya hata mesajı + 'Admine Bildir' butonu."""
    if time.time() - ERR_SEEN.get(uid, 0) < 20: return
    ERR_SEEN[uid] = time.time()
    eid = uuid.uuid4().hex[:6]
    ERRS[eid] = {"uid": uid, "where": str(where)[:120], "err": str(err)[:400], "t": time.time()}
    if len(ERRS) > 300:
        for k in list(ERRS)[:100]: ERRS.pop(k, None)
    lang = lang_of(load_db(), uid)
    try: await c.bot.send_message(uid, tr(lang, "err"), parse_mode="HTML", reply_markup=KB([[B(tr(lang, "b_report"), f"u_rep:{eid}", "danger")]]))
    except Exception: pass

# ───────── DENEME KODU · SÜRE HATIRLATMA · GÜNLÜK RAPOR · KULLANICI ARA / ENGELLE ─────────
TRIAL_HOURS = 3
REPORT_HOUR = 9          # günlük rapor saati (Aşkabat)

T["tr"].update({
  "b_trial": "🎁 3 saatlik deneme al",
  "trial_ok": "🎁 <b>Deneme kodun hazır!</b>\n<blockquote>⏳ 3 saat geçerli\n📲 Linki kopyala, VPN uygulamana (Happ) abonelik olarak ekle.</blockquote>\n🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>\n<code>{link}</code>",
  "trial_used": "ℹ️ Deneme kodunu daha önce kullandın.",
  "trial_end": "⏳ Deneme süren bitti. Beğendiysen 🛒 Market'ten kod alabilirsin.",
  "remind": "⏳ <b>Kodun yarın bitiyor</b>\n<blockquote>🎟 {name}\n⏳ Kalan  <b>{left}</b></blockquote>\nUzatırsan link aynı kalır, hiçbir şey değiştirmen gerekmez.",
  "b_ext": "🔄 Uzat",
  "ext_ask": "🔄 <b>Kodu uzat</b>\n<blockquote>🎟 {name}\n⏳ Kalan  <b>{left}</b></blockquote>\nNe kadar uzatılsın?",
  "it_ext": "🔄 Uzatma · {days} gün · {name}",
  "order_ok_ext": "✅ <b>Sipariş #{oid} onaylandı!</b>\n<blockquote>🎟 {name} uzatıldı\n⏳ Kalan  <b>{left}</b></blockquote>\nLink aynı, bir şey yapmana gerek yok.",
  "banned": "⛔ Bu botu kullanman engellendi.",
  "gift": "🎁 <b>Admin sana kod verdi!</b>\n<blockquote>⏳ Süre  <b>{left}</b></blockquote>\n🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>\n<code>{link}</code>",
  "added": "⏳ Kodunun süresi uzatıldı: {name} · kalan {left}",
})
T["ru"].update({
  "b_trial": "🎁 Пробный на 3 часа",
  "trial_ok": "🎁 <b>Пробный код готов!</b>\n<blockquote>⏳ Действует 3 часа\n📲 Скопируйте ссылку и добавьте её как подписку в VPN-приложение (Happ).</blockquote>\n🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>\n<code>{link}</code>",
  "trial_used": "ℹ️ Пробный код вы уже использовали.",
  "trial_end": "⏳ Пробный период закончился. Если понравилось — код можно купить в 🛒 Магазине.",
  "remind": "⏳ <b>Ваш код заканчивается завтра</b>\n<blockquote>🎟 {name}\n⏳ Осталось  <b>{left}</b></blockquote>\nПри продлении ссылка останется прежней, ничего менять не нужно.",
  "b_ext": "🔄 Продлить",
  "ext_ask": "🔄 <b>Продлить код</b>\n<blockquote>🎟 {name}\n⏳ Осталось  <b>{left}</b></blockquote>\nНа сколько продлить?",
  "it_ext": "🔄 Продление · {days} дн. · {name}",
  "order_ok_ext": "✅ <b>Заказ #{oid} подтверждён!</b>\n<blockquote>🎟 {name} продлён\n⏳ Осталось  <b>{left}</b></blockquote>\nСсылка та же, ничего делать не нужно.",
  "banned": "⛔ Вам закрыт доступ к этому боту.",
  "gift": "🎁 <b>Администратор выдал вам код!</b>\n<blockquote>⏳ Срок  <b>{left}</b></blockquote>\n🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>\n<code>{link}</code>",
  "added": "⏳ Срок вашего кода продлён: {name} · осталось {left}",
})
NUM_ASK.update({
    "gift_days": ("🎁 <b>Kod ver</b>", "Kaç günlük kod verilsin?", DAYS, "g"),
    "add_days":  ("⏳ <b>Süre ekle</b>", "Kaç gün eklensin?", DAYS, "g"),
})

def is_banned(uid):
    if uid in ADMINS: return False
    try:
        e = load_db().get("users", {}).get(str(uid), {})
        return bool(e.get("banned")) or e.get("ban_until", 0) > time.time()   # ban_until: süreli engel (ör. uygunsuz fotoğraf)
    except Exception: return False

def ext_view(lang, kid, s):
    rows = [[B(tr(lang, "b_c7"), f"u_xb:{kid}:c7", "primary")], [B(tr(lang, "b_c30"), f"u_xb:{kid}:c30", "primary")], [B(tr(lang, "b_menu"), "u_menu")]]
    return tr(lang, "ext_ask", name=esc(name_of(s, kid)), left=left_txt(s.get("expires"), lang == "ru")), KB(rows)

def extend_code(kid, days):
    """Kodun süresini uzatır (bitmişse şimdiden başlar). Dönüş: kod kaydı ya da None."""
    def f(d):
        s = d["subs"].get(kid)
        if not s: return None
        s["expires"] = max(time.time(), float(s.get("expires") or time.time())) + days * 86400
        s.pop("reminded", None); s.pop("exp_done", None)
        return dict(s)
    return mutate(f)

# ── günlük rapor ──
def report_text(start, end, title):
    db = load_db()
    lines = [x for x in ulog_lines() if start <= x.get("t", 0) < end]
    k = lambda kind: sum(1 for x in lines if x.get("k") == kind)
    done_all = [o for o in db.get("orders", {}).values() if o.get("status") == "done" and not o.get("test") and start <= o.get("done_ts", 0) < end]
    done = [o for o in done_all if o.get("item") != "topup"]
    tops = sum(o["price"] for o in done_all if o.get("item") == "topup") / USDT_RATE
    tmt = sum(o["price"] for o in done)
    usdt = sum(o["price"] for o in done if o.get("via") == "usdt") / USDT_RATE
    pub = [s for s in db["subs"].values() if s.get("pub") and not is_exp(s)]
    op = sum(1 for t in db.get("tickets", {}).values() if t.get("status") == "open")
    return (f"📈 <b>{title}</b>\n<blockquote>"
            f"🆕 Yeni kullanıcı  <b>{k('join')}</b>\n"
            f"🤝 Sayılan davet  <b>{k('credit')}</b>\n"
            f"🎁 Ücretsiz kod  <b>{k('free')}</b>  ·  🧪 Deneme  <b>{k('trial')}</b>\n"
            f"💰 Satış  <b>{len(done)}</b>  ·  <b>{tmt} TMT</b>  ·  💵 <b>{usdt:g} USDT</b>\n"
            f"💳 Bakiye yükleme  <b>{tops:g} USDT</b>\n"
            f"🏪 Pazar  ilan <b>{k('m_list')}</b> · başlatma <b>{k('m_start')}</b> · ödeme <b>{k('m_pay') + k('m_stop')}</b>\n"
            f"🆘 Açılan talep  <b>{k('t_open')}</b>  ·  📨 Hata bildirimi  <b>{k('err')}</b></blockquote>\n"
            f"<blockquote>👥 Toplam kullanıcı  <b>{len(db.get('users', {}))}</b>\n"
            f"🎟 Aktif kullanıcı kodu  <b>{len(pub)}</b>\n"
            f"📡 Çalışan sunucu kodu  <b>{len(db.get('template', []))}</b>\n"
            f"{esc(RUN.get('tm_line', ''))}\n"
            f"🎫 Açık talep  <b>{op}</b>\n"
            f"📂 Boş kod yeri  <b>{pool_count()}</b></blockquote>")

def day_bounds(offset=0):
    d0 = tm_now().replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=offset)
    return d0.timestamp(), (d0 + datetime.timedelta(days=1)).timestamp(), d0.strftime("%d.%m.%Y")

# ── kullanıcı ara ──
def find_users(q):
    q = q.strip().lstrip("@").lower()
    us = load_db().get("users", {})
    if q.isdigit() and q in us: return [q]
    exact = [k for k, e in us.items() if (e.get("un") or "").lower() == q]
    if exact: return exact
    return [k for k, e in us.items() if q and (q in (e.get("name") or "").lower() or q in (e.get("un") or "").lower())][:10]

def ban_view():
    """Admin → 🚫 Ban / Unban: banlılar listesi (kalıcı + süreli) ve yeni ban."""
    db = load_db(); now = time.time()
    bl = [(k, e) for k, e in db.get("users", {}).items() if e.get("banned") or e.get("ban_until", 0) > now]
    lines = "\n".join(f"🚫 {esc(short(e.get('name') or '?', 22))} <code>{k}</code> · " + ("kalıcı" if e.get("banned") else f"{dur_txt(e['ban_until'] - now)} kaldı") for k, e in bl[:30]) or "Banlı kullanıcı yok."
    rows = [[B("🚫 Kullanıcı Banla", "ban_find", "danger")]] + [[B(f"✅ Unban · {short(e.get('name') or k, 16)}", f"ubn:{k}")] for k, e in bl[:30]] + [[B("◀️ Admin", "admin")]]
    return f"🚫 <b>Ban / Unban</b>  <code>{len(bl)}</code>\n<blockquote>{lines}</blockquote>", KB(rows)

def user_view(tid):
    db = load_db(); e = db.get("users", {}).get(str(tid))
    if not e: return "⚠️ Kullanıcı bulunamadı.", back("admin")
    tid = int(tid)
    inv = db["users"].get(str(e.get("ref_by")), {}).get("name") if e.get("ref_by") else None
    codes = user_codes(db, tid)
    orders = [o for o in db.get("orders", {}).values() if o["uid"] == tid]
    sa = db.get("sub_admins", {}).get(str(tid))
    t = (f"👤 <b>{esc(e.get('name') or '—')}</b>\n<blockquote>"
         f"🪪 ID  <code>{tid}</code>\n🔗 {('@' + esc(e['un'])) if e.get('un') else '—'}\n"
         f"📅 Katılma  {tm_fmt(e.get('joined', time.time()))}\n🌐 Dil  {e.get('lang', 'tr')}\n"
         f"🙋 Davet eden  {esc(inv) if inv else '—'}\n"
         f"🤝 Davet  <b>{len(e.get('refs', []))}</b> · kullanılabilir <b>{max(0, avail_refs(e))}</b>\n"
         f"🎁 Ücretsiz kod  <b>{e.get('free_n', 0)}</b> · 🧪 Deneme  <b>{'kullandı' if e.get('trial_used') else 'yok'}</b>\n"
         f"🛒 Sipariş  <b>{len(orders)}</b> · tamamlanan <b>{sum(1 for o in orders if o['status'] == 'done')}</b>\n"
         + (f"🖥 Panel  <b>{left_txt(sa.get('expires'))}</b> · limit {sa.get('limit')}\n" if sa else "")
         + f"💰 Bakiye  <b>{fmt_u(e.get('bal', 0))} USDT</b>" + (f" · 💼 Kazanç <b>{fmt_u(e['earn'])}</b>" if e.get("earn") else "") + "\n"
         + (f"🏪 Pazar yasağı  {dur_txt(e['mban'] - time.time())}\n" if e.get("mban", 0) > time.time() else "")
         + ({"buyer": "🛒 Alıcı olarak geldi\n", "seller": "🏪 Satıcı olarak geldi\n"}.get(e.get("role"), ""))
         + ("🚫 <b>ENGELLİ</b>\n" if e.get("banned") else "")
         + "</blockquote>\n"
         + ("\n".join(f"🎟 {esc(short(name_of(s, k), 26))} · ⏳ {left_txt(s.get('expires'))}" for k, s in codes) or "<i>Aktif kodu yok.</i>"))
    kb = KB([[B("🎁 Kod Ver", f"ug:{tid}", "success"), B("⏳ Süre Ekle", f"ux:{tid}")],
             [B("➕ Bakiye Ekle", f"ubal:+:{tid}"), B("➖ Bakiye Düş", f"ubal:-:{tid}")],
             [B("✏️ Bakiyeyi Ayarla", f"ubal:=:{tid}")],
             [B("✅ Engeli Kaldır", f"ub:{tid}") if e.get("banned") else B("🚫 Engelle", f"ub:{tid}", "danger")],
             [B("🔎 Başka Ara", "usearch"), B("◀️ Admin", "admin")]])
    return t, kb

# ───────── PAZAR: VPN satıcıları, dakika başı ödeme (bakiye + CryptoBot) ─────────
UM = 1_000_000                   # 1 USDT = 1.000.000 mikro (kuruş hatası olmasın diye tam sayı)
PREPAY_MIN = 300                 # başlatınca ilk 5 saat peşin alınır (hemen iade edip IP toplamaya karşı)
MAX_STARTS_DAY = 3               # bir alıcı AYNI ilanı (başka ilanlar serbest) 24 saatte en fazla bu kadar başlatabilir
MKT_FEE = 50_000                 # 0.05 USDT: satıcı ilan ücreti ve alıcı başlatma ücreti (bota kalır)
TOPUP_MIN = 0.1                  # en az bakiye yükleme (USDT)
WITHDRAW_MIN = UM                # en az kazanç çekme: 1 USDT (CryptoBot 1$ altını göndermiyor)
WITHDRAW_MIN_ADMIN = UM          # kurucu da 1 USDT
def wd_min(uid): return WITHDRAW_MIN_ADMIN if uid in ADMINS else WITHDRAW_MIN
MIN_COUNTRIES, MAX_DEAD = 4, 4   # başvuruda en az 4 gerçek ülke; 4'ten fazla çalışmayan (N/A) sunucu olmamalı
BAD_WINDOW = 30 * 60             # kural ihlali bu kadar sürerse ilan kaldırılır
BAN_DEAD_H = 3                   # N/A kuralı ihlalinde yasak (saat): yasakta kod verilmez, iade yok
VIP_FEE, VIP_HOURS = 200_000, 36 # 💎 VIP: 0.2 USDT -> 36 saat en üstte (bizim ilanın altında)
OWN_DESC = "✅ Botun resmi kodu\n🛡 7/24 kontrol altında: IP değişince otomatik yenilenir, çalışmayan sunucular otomatik çıkarılır."
SETTLE_EVERY = 86400             # alıcı durdurmazsa satıcıya günde bir ödeme
START_MINUTES = 60               # başlatmak için bakiye en az 60 dakikaya yetmeli
OWN_LID = "own"                  # bizim ilanımız (her zaman en üstte)
REF_BONUS = UM // 80             # her sayılan davet: 0.25 TMT bonus (= 0.0125 USDT); çekilemez, sadece 🛒 Market'te kod (c7/c30) almakta harcanır
OWN_PRICE = 100                  # bizim fiyat: 0.0001 USDT/dk (≈ 4.3 USDT / 30 gün)
TM_FRESH = 40 * 60               # telefon sonucu bundan eskiyse kurallar uygulanmaz
MKT = {"lock": None}

def fmt_u(m):
    s = f"{m / UM:.6f}".rstrip("0").rstrip(".")
    return s or "0"
def tmt_u(m):
    s = f"{m * USDT_RATE / UM:.4f}".rstrip("0").rstrip(".")
    return s or "0"
def dur_txt(sec, ru=False):
    m = int(sec // 60); h, m = divmod(m, 60); d, h = divmod(h, 24)
    parts = ([f"{d}{'д' if ru else 'g'}"] if d else []) + ([f"{h}{'ч' if ru else 's'}"] if h else []) + [f"{m}{'м' if ru else 'dk'}"]
    return " ".join(parts)

def money2(m, tmt=False):
    v = m * (USDT_RATE if tmt else 1) / UM
    t = f"{v:.2f}" if v >= 1 or tmt else f"{v:.4f}"
    return t.rstrip("0").rstrip(".") or "0"   # 100.00 -> 100, 5.50 -> 5.5

def calc_text(price, ru=False):
    rows = [(60, "1 час" if ru else "1 saat"), (1440, "1 день" if ru else "1 gün"), (43200, "30 дней" if ru else "30 gün")]
    return "\n".join(f"⏱ {lbl}  —  <b>{money2(price * n, True)} TMT</b>  ·  {money2(price * n)} USDT" for n, lbl in rows)

def month_tmt(price): return round(price * 43200 * USDT_RATE / UM)
def price_from_month_tmt(tmt): return tmt / USDT_RATE * UM / 43200   # aylık TMT -> mikro USDT / dakika

def parse_usdt(txt):
    try:
        v = float(txt.replace(",", ".").replace("$", "").replace("usdt", "").strip())
        return int(round(v * UM)) if v > 0 else None
    except Exception: return None

def proto_of(c):
    p = c.split("://", 1)[0].lower()
    return {"hy2": "hysteria", "hysteria2": "hysteria", "ss": "ss"}.get(p, p)

def used_fids(db):
    """Şu an bir koda/oturuma bağlı Drive dosyaları (boş dosya seçerken bunlar alınmaz)."""
    u = {v.get("file_id") for v in db["subs"].values() if v.get("file_id")} | {db.get("tm_fid")} | source_fids(db)
    u |= {s.get("fid") for s in db.get("msess", {}).values() if s.get("status") == "on"}
    return u

def ensure_own(db):
    m = db.setdefault("market", {})
    if OWN_LID not in m:
        m[OWN_LID] = {"own": True, "status": "live", "price": OWN_PRICE, "title": "VIP 🇹🇲 Servers", "owner": None, "created": time.time()}
    o = m[OWN_LID]
    if o.get("title", "").startswith("⭐ "): o["title"] = o["title"][2:]   # eski adın yıldızı kalksın
    o.setdefault("desc", OWN_DESC)
    return m

def market_codes(db):
    """Telefonun test edeceği satıcı kodları (yayında + incelemede)."""
    out, seen = [], set()
    for lid, L in db.get("market", {}).items():
        if L.get("own") or L.get("status") not in ("pending", "live"): continue
        for c in L.get("codes", []):
            k = code_key(c)
            if k not in seen: seen.add(k); out.append(c)
    return out

def listing_codes(db, L):
    return list(db.get("template", [])) if L.get("own") else list(L.get("codes", []))

def listing_stats(db, L, res=None, exits=None, ts=0):
    """Telefon sonuçlarından: kaç sunucu çalışıyor, kaç gerçek ülke (bayrağa bakılmaz, ölçülen çıkış ülkesi)."""
    codes = listing_codes(db, L)
    keys = [code_key(c) for c in codes]
    res = res or {}; exits = exits or {}
    tested = [k for k in keys if isinstance(res.get(k), (int, float))]
    work = [k for k in tested if res[k] > 0]
    dead = [k for k in tested if res[k] < 0]
    cache = load_exits()
    cc = sorted({(exits.get(k) or cache.get(k) or "").lower() for k in work} - {"", "?"})
    protos = {}
    for c in codes: protos[proto_of(c)] = protos.get(proto_of(c), 0) + 1
    return {"total": len(codes), "tested": len(tested), "work": len(work), "dead": len(dead), "cc": cc, "protos": protos, "ts": ts}

def tcp_open_count(codes):
    tcp = [c for c in codes if c.split("://", 1)[0].lower() not in UDP_PROTOS]
    hps = sorted({hp for hp in (code_hostport(c) for c in tcp) if hp[0] and hp[1]})[:200]
    if not hps: return 0, 0
    with ThreadPoolExecutor(32) as ex: ok = sum(ex.map(lambda hp: tcp_alive(*hp), hps))
    return ok, len(hps)

def alloc_file(svc, db):
    """Kod havuzundan boş, herkese açık bir Drive dosyası (db_lock içinde çağrılır). Dönüş: (fid, free_files'tan mı)."""
    used = used_fids(db)
    for f in db["free_files"]:
        if f not in used: return f, True
    fid = None
    try: fid = next((f for f in pool_files(svc) if f not in used), None)
    except Exception as e: vlog(f"⚠️ Kod havuzu okunamadı: {str(e)[:120]}")
    if not fid: fid = find_free_file(svc, used)
    return fid, False

def mkt_start(uid, lid):
    """Alıcı bir ilanı başlatır: 0.05$ ücret, Drive dosyası, kodlar. Dönüş: ((sid, fid), "") ya da (None, sebep)."""
    svc = new_service()
    if not svc: return None, "drive"
    with db_lock():
        db = load_db(); ensure_own(db)
        L = db["market"].get(lid); e = db["users"].setdefault(str(uid), {})
        if not L or L.get("status") != "live": return None, "gone"
        if L.get("owner") == uid and uid not in ADMINS: return None, "own"   # kendi ilanını alıp bakiyeyi kazanca çeviremesin
        if any(s["buyer"] == uid and s["lid"] == lid and s["status"] == "on" for s in db.get("msess", {}).values()): return None, "already"
        if sum(1 for s in db.get("msess", {}).values() if s["buyer"] == uid and s["lid"] == lid and s["start"] > time.time() - 86400) >= MAX_STARTS_DAY:
            return None, "limit"   # aynı ilanı sık başlat-durdur (IP toplama) engeli
        need = MKT_FEE + int(round(L["price"] * max(START_MINUTES, PREPAY_MIN)))
        if e.get("bal", 0) < need: return None, f"nobal:{need}"
        codes = listing_codes(db, L)
        if not codes: return None, "nocodes"
        fid, from_free = alloc_file(svc, db)
        if not fid or not make_public(svc, fid): return None, "noslot"
        if not sync_file(svc, fid, L["title"], mkt_ann(lang_of(db, uid)), codes, exp=False): return None, "drive"
        if from_free: db["free_files"].remove(fid)
        e["bal"] = e.get("bal", 0) - MKT_FEE
        db["mkt_fees"] = db.get("mkt_fees", 0) + MKT_FEE
        sid = uuid.uuid4().hex[:8]
        now = time.time()
        pre = int(round(L["price"] * PREPAY_MIN)); e["bal"] -= pre   # ilk saat peşin (iade edilmez); dakika başı ödeme 1 saat sonra başlar
        db.setdefault("msess", {})[sid] = {"buyer": uid, "lid": lid, "fid": fid, "start": now, "last": now + PREPAY_MIN * 60, "settle_ts": now,
                                          "acc": pre, "total": pre, "status": "on", "hash": hashlib.md5("\n".join(codes).encode()).hexdigest()}
        save_db(db)
        return (sid, fid), ""

def charge(db, sid, now):
    """Tek oturum: geçen tam dakikaların ücretini alıcı bakiyesinden keser. Bakiye yetmediyse False."""
    s = db["msess"][sid]
    L = db.get("market", {}).get(s["lid"]); e = db["users"].setdefault(str(s["buyer"]), {})
    if not L: return False
    price = float(L["price"]); mins = int((now - s["last"]) // 60)
    if mins <= 0: return True
    can = int(min(mins, e.get("bal", 0) // price)) if price else mins
    cost = int(round(can * price))
    e["bal"] = e.get("bal", 0) - cost; s["acc"] += cost; s["total"] += cost; s["last"] += can * 60
    return can == mins

def bill(db, now):
    """Her dakika: aktif oturumların ücreti alıcı bakiyesinden düşer. Dönüş: (durdurulacaklar, uyarılacaklar, günlük ödemeler)."""
    stop, warn, settle = [], [], []
    for sid, s in db.get("msess", {}).items():
        if s.get("status") != "on": continue
        L = db.get("market", {}).get(s["lid"])
        if not L or L.get("status") != "live": stop.append((sid, "gone")); continue
        if not charge(db, sid, now): stop.append((sid, "nobal")); continue
        price = float(L["price"]); bal = db["users"][str(s["buyer"])].get("bal", 0)
        left_min = int(bal // price) if price else 10**9
        if left_min < 60 and not s.get("warned"): s["warned"] = True; warn.append((sid, s["buyer"], left_min))
        if left_min >= 60: s.pop("warned", None)
        if now - s.get("settle_ts", s["start"]) >= SETTLE_EVERY and s["acc"] > 0:
            settle.append((sid, s["acc"], int(now - s["settle_ts"]))); s["acc"] = 0; s["settle_ts"] = now
    return stop, warn, settle

def mkt_stop(sid, reason):
    """Oturumu kapatır: son dakikalar kesilir, dosya boşaltılır. Dönüş: ödeme bilgisi ya da None."""
    with db_lock():
        db = load_db(); s = db.get("msess", {}).get(sid)
        if not s or s.get("status") != "on": return None
        now = time.time()
        charge(db, sid, now)   # son tam dakikalar (bakiye yettiği kadar)
        s["status"] = "off"; s["end"] = now; s["reason"] = reason
        payout, s["acc"] = s["acc"], 0
        if s["fid"] not in db["free_files"]: db["free_files"].append(s["fid"])
        L = db.get("market", {}).get(s["lid"], {})
        if L.get("own"): db["mkt_own_rev"] = db.get("mkt_own_rev", 0) + payout
        info = {"sid": sid, "buyer": s["buyer"], "lid": s["lid"], "owner": L.get("owner"), "own": bool(L.get("own")), "title": L.get("title", "?"),
                "payout": payout, "span": int(now - s.get("settle_ts", s["start"])), "dur": int(now - s["start"]), "total": s["total"], "reason": reason}
        save_db(db)
    try: sync_file(new_service(), s["fid"], "Empty", CODE_OFF_MSG, [], exp=False)
    except Exception: pass
    return info

TRANSFER_MIN = UM   # 1 USDT

def pay_seller(seller, amount, spend_id, comment):
    """Satıcının kazancını CryptoBot'a gönderir; olmazsa bot içi çekilebilir bakiyeye ekler. Dönüş: 'sent' | 'bal'."""
    if amount <= 0: return "none"
    if crypto_token() and amount >= TRANSFER_MIN:   # CryptoBot 1$'ın altını göndermiyor (AMOUNT_TOO_SMALL)
        try:
            crypto_transfer(user_id=seller, asset="USDT", amount=fmt_u(amount), spend_id=spend_id[:64], comment=comment[:500])
            return "sent"
        except Exception as e:
            RUN["transfer_err"] = str(e)[:150]
    mutate(lambda d: d["users"].setdefault(str(seller), {}).__setitem__("earn", d["users"][str(seller)].get("earn", 0) + amount))
    return "bal"

# ── metinler ──
T["tr"].update({
  "b_mkt": "🏪 Pazar (dakika başı)", "b_sell": "Öz Kodyňyzy Satmak 🪪", "b_myl": "📦 İlanlarım", "b_rules": "📜 Kurallar",
  "b_start": "▶️ Başlat · 0.05$ + {p}/dk", "b_shot": "📷 Ekran Görüntüsü", "b_back_mkt": "◀️ Pazar", "b_stop": "⏹ Durdur",
  "b_top": "➕ Bakiye Yükle", "b_wd": "💸 Kazancı Çek", "b_other": "✏️ Başka tutar",
  "mkt": "🏪 <b>Pazar</b>\n<blockquote>Satıcıların VPN kodları. Dakika başı ödersin, istediğin an durdurursun.\nKodlar bot tarafından her dakika kontrol edilir.\n💰 Bakiyen  <b>{bal} USDT</b></blockquote>\n<i>Bir ilan seç</i> 👇",
  "mkt_empty": "<i>Şu an başka ilan yok.</i>",
  "ml": "🏪 <b>{title}</b>\n<blockquote>{own}👤 Satıcı  {seller}\n📡 Sunucu  <b>{total}</b>  ·  {protos}\n🇹🇲 TM testi  <b>{work}/{tested}</b> çalışıyor  ·  ❌ {dead}\n🌍 Gerçek ülke  <b>{ncc}</b>  {flags}\n🔌 Açık port (VPS)  {tcp}\n🕒 Son kontrol  {chk}\n✅ Son sağlam  {good}</blockquote>\n💲 <b>Fiyat</b>\n<blockquote>{calc}</blockquote>{desc}\n<i>Başlatınca 0.05$ başlatma ücreti alınır, sonra her dakika bakiyenden düşer.</i>",
  "ml_own": "⭐ Resmi ilan\n",
  "m_need": "⚠️ <b>Bakiye yetersiz</b>\n<blockquote>Başlatmak için en az <b>{need} USDT</b> gerekli (0.05$ + 5 saat).\n💰 Bakiyen  <b>{bal} USDT</b></blockquote>",
  "m_started": "✅ <b>Kod başladı!</b>\n<blockquote>🏪 {title}\n💲 {p}  ·  💰 Bakiye {bal} USDT</blockquote>\n🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>\n<code>{link}</code>\n<i>Durdurmak için: 🎟 Kodlarım → ⏹ Durdur</i>",
  "m_already": "ℹ️ Bu ilan sende zaten açık. 🎟 Kodlarım'dan bakabilirsin.",
  "m_gone": "⚠️ Bu ilan artık yayında değil.",
  "m_stopped": "⏹ <b>Kod durduruldu</b>\n<blockquote>🏪 {title}\n⏱ Kullanım  {dur}\n💸 Toplam  {usdt} USDT</blockquote>{why}",
  "why_nobal": "<i>Bakiyen bittiği için durduruldu.</i>", "why_gone": "<i>İlan pazardan kaldırıldığı için durduruldu.</i>", "why_user": "",
  "m_low": "⚠️ Bakiyen azalıyor: pazardaki kodun yaklaşık <b>{m} dk</b> daha çalışır.",
  "mine_m": "<blockquote>🏪 <b>{title}</b>  ·  ⏱ {dur}  ·  💸 {usdt} USDT\n<code>{link}</code></blockquote>",
  "sell_banned": "⛔ Pazar yasağın var: <b>{left}</b> sonra tekrar ilan verebilirsin.",
  "sell_1": "➕ <b>Kodumu Sat · 1/5</b>\n<blockquote>Abonelik linkini gönder. <b>Limitsiz</b> olmalı (trafik ve cihaz).\nKurallar: en az 4 farklı gerçek ülke (bot ölçer, bayraklara bakılmaz), en fazla 3 çalışmayan sunucu.</blockquote>",
  "sell_badlink": "⚠️ Bu linkten kod alınamadı. Linki kontrol edip tekrar gönder.\n<i>Happ şifreli (happ://crypt…) ya da kapalı linkler kabul edilmiyor; açık abonelik linkini gönder.</i>",
  "sell_dup": "⚠️ Bu link zaten pazarda.",
  "sell_2": "➕ <b>Kodumu Sat · 2/5</b>\n<blockquote>✅ Linkte <b>{n}</b> sunucu bulundu ({protos}).\nİlanın adını yaz (ör. <code>Fast VPN 🇩🇪</code>).</blockquote>",
  "sell_3": "➕ <b>Kodumu Sat · 3/5</b>\n<blockquote>Kodunun <b>ekran görüntüsünü</b> gönder (fotoğraf olarak).</blockquote>",
  "sell_need_photo": "⚠️ Ekran görüntüsünü fotoğraf olarak gönder.",
  "sell_4": "➕ <b>Kodumu Sat · 4/5</b>\n<blockquote>Açıklama yaz (hız, özellik, iletişim...). Atlamak için <code>-</code> gönder.</blockquote>",
  "sell_5": "➕ <b>Kodumu Sat · 5/5</b>\n<blockquote>Dakika başı fiyatını <b>USDT</b> olarak yaz.\nÖrnek: <code>0.0001</code> = günde 0.144 USDT · 30 günde 4.32 USDT</blockquote>",
  "sell_badprice": "⚠️ Geçerli bir fiyat yaz (0.00001 ile 0.01 USDT arası), ör. <code>0.0001</code>.",
  "sell_confirm": "🧾 <b>İlan özeti</b>\n<blockquote>🏷 {title}\n📡 {n} sunucu · {protos}\n📝 {desc}</blockquote>\n💲 <b>Fiyat hesaplayıcı</b>\n<blockquote>{calc}</blockquote>\n<i>Onaylarsan bakiyenden <b>0.05$</b> ilan ücreti alınır (iade edilmez). Bot kodlarını test eder; kurallara uyuyorsa birkaç dakika içinde yayına alınır.</i>",
  "b_sellok": "✅ Limitsiz olduğunu onaylıyorum · 0.05$ öde", "b_sellp": "✏️ Fiyatı değiştir",
  "sell_nobal": "⚠️ İlan ücreti için bakiyen yetersiz (0.05$). Önce bakiye yükle.",
  "sell_sent": "⏳ <b>İlanın incelemede</b>\n<blockquote>Bot kodlarını Türkmenistan'dan test ediyor. Uygunsa birkaç dakika içinde yayına alınır, sana haber gelir.</blockquote>",
  "m_approved": "✅ <b>İlanın yayında!</b>\n<blockquote>🏪 {title}\n🌍 {ncc} gerçek ülke · ✅ {work}/{tested} sunucu çalışıyor</blockquote>",
  "m_rejected": "❌ <b>İlanın kabul edilmedi</b>\n<blockquote>🏪 {title}\n{why}</blockquote>",
  "m_removed": "⛔ <b>İlanın pazardan kaldırıldı</b>\n<blockquote>🏪 {title}\n{why}</blockquote>\n⏳ {h} saat pazar yasağın var.",
  "r_dead": "3'ten fazla sunucu 30 dakika boyunca çalışmadı.", "r_lowc": "Gerçek ülke sayısı 30 dakika boyunca 4'ün altında kaldı.",
  "r_link": "Abonelik linki 30 dakika boyunca açılmadı.", "rj_lowc": "En az 4 farklı gerçek ülke yok (ölçülen: {n}).",
  "rj_dead": "{n} sunucu çalışmıyor (en fazla 4 olabilir).", "rj_link": "Abonelik linki açılmadı.",
  "m_paid_sent": "🎉 <b>Tebrikler!</b>\n<blockquote>🏪 {title}\n⏱ Alıcı kodunu {dur} kullandı\n💰 Ödemen  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💸 CryptoBot hesabına gönderildi.",
  "m_paid_bal": "🎉 <b>Tebrikler!</b>\n<blockquote>🏪 {title}\n⏱ Alıcı kodunu {dur} kullandı\n💰 Ödemen  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💼 Bot bakiyene eklendi. Profil → 💸 Kazancı Çek.",
  "myl": "📦 <b>İlanlarım</b>", "myl_none": "📦 <b>İlanlarım</b>\n<blockquote>İlanın yok.</blockquote>",
  "myl_item": "<blockquote>{st} <b>{title}</b>\n💲 {p} USDT/dk · 👥 {n} alıcı · 💰 {earned} USDT kazanç</blockquote>",
  "st_pending": "⏳", "st_live": "🟢", "st_removed": "⛔", "st_rejected": "❌",
  "rules": "📜 <b>Pazar kuralları</b>\n\n🏪 <b><u>SATICI</u></b>\n<blockquote>• Her ilan 0.05$ (iade edilmez).\n• Abonelik limitsiz olmalı; ekran görüntüsü zorunlu.\n• Başvuruda en az 4 farklı gerçek ülke (bot ölçer, bayraklara bakılmaz).\n• 💎 VIP: 0.2$ ile 36 saat en üstte.\n• Kazanç: alıcı durdurunca, uzun kullanımda her 24 saatte bir gönderilir.\n• 🔒 Kodların sadece satın alan kişinin dosyasına yazılır, durdurunca silinir. Her kullanım İlanlarım → 📜 Kullanım geçmişi'nde görünür.</blockquote>\n\n🛒 <b><u>ALICI</u></b>\n<blockquote>• Her başlatma 0.05$ + ilk 5 saat peşin (iade edilmez).\n• Aynı ilan 24 saatte en fazla 3 kez başlatılır.\n• Dakika başı ücret bakiyenden düşer (kullansan da kullanmasan da).\n• İstediğin an durdurursun; bakiye bitince kod durur.\n• Bakiye en az 1$ yüklenir; yüklenen bakiye geri çekilmez.</blockquote>",
  "bal_line": "\n\n💰 <b>Bakiye</b> {bal} USDT ≈ {tmt} TMT" , "earn_line": "\n💼 <b>Çekilebilir kazanç</b>  {earn} USDT",
  "top": "➕ <b>Bakiye Yükle</b>\n<blockquote>CryptoBot ile USDT. En az 1 USDT.\n💰 Bakiyen  <b>{bal} USDT</b></blockquote>",
  "top_ask": "✏️ Kaç USDT yüklemek istiyorsun? (en az 0.1)", "top_bad": "⚠️ En az 0.1 USDT, sayı yaz (ör. 2.5).",
  "top_order": "🧾 <b>Bakiye yükleme · #{oid}</b>\n<blockquote>💵 <b>{usdt} USDT</b></blockquote>\n«💵 USDT ile öde»ye bas.",
  "it_top": "Bakiye yükleme · {usdt} USDT",
  "top_ok": "✅ <b>Bakiyene {usdt} USDT eklendi.</b>\n<blockquote>💰 Bakiye  <b>{bal} USDT</b></blockquote>",
  "wd_min": "ℹ️ Çekmek için en az {min} USDT kazanç gerekli. Şu an: {earn} USDT.",
  "wd_ok": "✅ <b>{usdt} USDT</b> CryptoBot hesabına gönderildi.",
  "wd_err": "⚠️ Gönderilemedi: {err}\n<i>@CryptoBot'u en az bir kez açmış olman gerekir. Sorun sürerse 🆘 Destek'e yaz.</i>",
})
T["ru"].update({
  "b_mkt": "🏪 Биржа (поминутно)", "b_sell": "➕ Продать код", "b_myl": "📦 Мои лоты", "b_rules": "📜 Правила",
  "b_start": "▶️ Запустить · 0.05$ + {p}/мин", "b_shot": "📷 Скриншот", "b_back_mkt": "◀️ Биржа", "b_stop": "⏹ Стоп",
  "b_top": "➕ Пополнить", "b_wd": "💸 Вывести доход", "b_other": "✏️ Другая сумма",
  "mkt": "🏪 <b>Биржа</b>\n<blockquote>VPN-коды продавцов. Оплата поминутно, остановить можно в любой момент.\nБот проверяет коды каждую минуту.\n💰 Баланс  <b>{bal} USDT</b></blockquote>\n<i>Выберите объявление</i> 👇",
  "mkt_empty": "<i>Других объявлений пока нет.</i>",
  "ml": "🏪 <b>{title}</b>\n<blockquote>{own}👤 Продавец  {seller}\n📡 Серверов  <b>{total}</b>  ·  {protos}\n🇹🇲 Тест в ТМ  <b>{work}/{tested}</b> работают  ·  ❌ {dead}\n🌍 Реальных стран  <b>{ncc}</b>  {flags}\n🔌 Открытые порты (VPS)  {tcp}\n🕒 Проверка  {chk}\n✅ Последний раз исправен  {good}</blockquote>\n💲 <b>Цена</b>\n<blockquote>{calc}</blockquote>{desc}\n<i>При запуске списывается 0.05$, затем оплата каждую минуту с баланса.</i>",
  "ml_own": "⭐ Официальное объявление\n",
  "m_need": "⚠️ <b>Недостаточно средств</b>\n<blockquote>Для запуска нужно минимум <b>{need} USDT</b> (0.05$ + 5 часов).\n💰 Баланс  <b>{bal} USDT</b></blockquote>",
  "m_started": "✅ <b>Код запущен!</b>\n<blockquote>🏪 {title}\n💲 {p}  ·  💰 Баланс {bal} USDT</blockquote>\n🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>\n<code>{link}</code>\n<i>Остановить: 🎟 Мои коды → ⏹ Стоп</i>",
  "m_already": "ℹ️ Это объявление у вас уже запущено. Смотрите в 🎟 Мои коды.",
  "m_gone": "⚠️ Это объявление больше не активно.",
  "m_stopped": "⏹ <b>Код остановлен</b>\n<blockquote>🏪 {title}\n⏱ Использование  {dur}\n💸 Итого  {usdt} USDT</blockquote>{why}",
  "why_nobal": "<i>Остановлен: закончился баланс.</i>", "why_gone": "<i>Остановлен: объявление снято с биржи.</i>", "why_user": "",
  "m_low": "⚠️ Баланс заканчивается: код с биржи проработает ещё примерно <b>{m} мин</b>.",
  "mine_m": "<blockquote>🏪 <b>{title}</b>  ·  ⏱ {dur}  ·  💸 {usdt} USDT\n<code>{link}</code></blockquote>",
  "sell_banned": "⛔ У вас бан на бирже: можно снова через <b>{left}</b>.",
  "sell_1": "➕ <b>Продать код · 1/5</b>\n<blockquote>Отправьте ссылку подписки. Она должна быть <b>безлимитной</b> (трафик и устройства).\nПравила: минимум 4 разные реальные страны (бот проверяет сам, флаги не учитываются), не больше 3 неработающих серверов.</blockquote>",
  "sell_badlink": "⚠️ По этой ссылке коды не получены. Проверьте и отправьте снова.\n<i>Зашифрованные (happ://crypt…) и закрытые ссылки не принимаются — нужна открытая ссылка подписки.</i>",
  "sell_dup": "⚠️ Эта ссылка уже на бирже.",
  "sell_2": "➕ <b>Продать код · 2/5</b>\n<blockquote>✅ Найдено серверов: <b>{n}</b> ({protos}).\nНапишите название объявления (напр. <code>Fast VPN 🇩🇪</code>).</blockquote>",
  "sell_3": "➕ <b>Продать код · 3/5</b>\n<blockquote>Отправьте <b>скриншот</b> вашего кода (как фото).</blockquote>",
  "sell_need_photo": "⚠️ Отправьте скриншот как фото.",
  "sell_4": "➕ <b>Продать код · 4/5</b>\n<blockquote>Напишите описание (скорость, особенности, контакты...). Пропустить — <code>-</code>.</blockquote>",
  "sell_5": "➕ <b>Продать код · 5/5</b>\n<blockquote>Укажите цену за минуту в <b>USDT</b>.\nПример: <code>0.0001</code> = 0.144 USDT в день · 4.32 USDT за 30 дней</blockquote>",
  "sell_badprice": "⚠️ Укажите цену от 0.00001 до 0.01 USDT, напр. <code>0.0001</code>.",
  "sell_confirm": "🧾 <b>Итог объявления</b>\n<blockquote>🏷 {title}\n📡 {n} серверов · {protos}\n📝 {desc}</blockquote>\n💲 <b>Калькулятор цены</b>\n<blockquote>{calc}</blockquote>\n<i>При подтверждении с баланса спишется <b>0.05$</b> (не возвращается). Бот проверит коды; если всё по правилам — объявление появится через несколько минут.</i>",
  "b_sellok": "✅ Подтверждаю безлимит · оплатить 0.05$", "b_sellp": "✏️ Изменить цену",
  "sell_nobal": "⚠️ Недостаточно баланса для оплаты объявления (0.05$). Сначала пополните.",
  "sell_sent": "⏳ <b>Объявление на проверке</b>\n<blockquote>Бот проверяет коды из Туркменистана. Если всё в порядке — опубликует через несколько минут и сообщит вам.</blockquote>",
  "m_approved": "✅ <b>Объявление опубликовано!</b>\n<blockquote>🏪 {title}\n🌍 {ncc} реальных стран · ✅ {work}/{tested} серверов работают</blockquote>",
  "m_rejected": "❌ <b>Объявление не принято</b>\n<blockquote>🏪 {title}\n{why}</blockquote>",
  "m_removed": "⛔ <b>Объявление снято с биржи</b>\n<blockquote>🏪 {title}\n{why}</blockquote>\n⏳ Бан на бирже: {h} ч.",
  "r_dead": "Больше 3 серверов не работали 30 минут.", "r_lowc": "Реальных стран меньше 4 в течение 30 минут.",
  "r_link": "Ссылка подписки не открывалась 30 минут.", "rj_lowc": "Нет минимум 4 разных реальных стран (измерено: {n}).",
  "rj_dead": "Не работают {n} серверов (максимум 4).", "rj_link": "Ссылка подписки не открылась.",
  "m_paid_sent": "🎉 <b>Поздравляем!</b>\n<blockquote>🏪 {title}\n⏱ Покупатель использовал ваш код {dur}\n💰 Выплата  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💸 Отправлено на ваш счёт в CryptoBot.",
  "m_paid_bal": "🎉 <b>Поздравляем!</b>\n<blockquote>🏪 {title}\n⏱ Покупатель использовал ваш код {dur}\n💰 Выплата  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💼 Зачислено на ваш баланс в боте. Профиль → 💸 Вывести доход.",
  "myl": "📦 <b>Мои объявления</b>", "myl_none": "📦 <b>Мои объявления</b>\n<blockquote>Объявлений нет.</blockquote>",
  "myl_item": "<blockquote>{st} <b>{title}</b>\n💲 {p} USDT/мин · 👥 {n} покуп. · 💰 {earned} USDT доход</blockquote>",
  "rules": "📜 <b>Правила биржи</b>\n\n🏪 <b><u>ПРОДАВЕЦ</u></b>\n<blockquote>• Каждое объявление 0.05$ (не возвращается).\n• Подписка должна быть безлимитной; скриншот обязателен.\n• При подаче минимум 4 разные реальные страны (бот измеряет сам, флаги не учитываются).\n• 💎 VIP: 0.2$ — 36 часов на самом верху.\n• Выплата: после остановки покупателем, при долгом использовании — каждые 24 ч.\n• 🔒 Ваши коды записываются только в файл купившего и удаляются после остановки. Каждое использование видно в Мои объявления → 📜 История.</blockquote>\n\n🛒 <b><u>ПОКУПАТЕЛЬ</u></b>\n<blockquote>• Каждый запуск 0.05$ + первые 5 часов сразу (не возвращается).\n• Одно объявление — не больше 3 запусков за 24 ч.\n• Поминутная оплата списывается с баланса (пользуетесь или нет).\n• Остановить можно в любой момент; при нулевом балансе код останавливается.\n• Пополнение от 1$; пополненный баланс не выводится.</blockquote>",
  "bal_line": "\n\n💰 <b>Баланс</b> {bal} USDT ≈ {tmt} TMT", "earn_line": "\n💼 <b>Доход к выводу</b>  {earn} USDT",
  "top": "➕ <b>Пополнение</b>\n<blockquote>USDT через CryptoBot. Минимум 1 USDT.\n💰 Баланс  <b>{bal} USDT</b></blockquote>",
  "top_ask": "✏️ Сколько USDT пополнить? (минимум 0.1)", "top_bad": "⚠️ Минимум 0.1 USDT, напишите число (напр. 2.5).",
  "top_order": "🧾 <b>Пополнение · #{oid}</b>\n<blockquote>💵 <b>{usdt} USDT</b></blockquote>\nНажмите «💵 Оплатить USDT».",
  "it_top": "Пополнение · {usdt} USDT",
  "top_ok": "✅ <b>На баланс зачислено {usdt} USDT.</b>\n<blockquote>💰 Баланс  <b>{bal} USDT</b></blockquote>",
  "wd_min": "ℹ️ Для вывода нужно минимум {min} USDT дохода. Сейчас: {earn} USDT.",
  "wd_ok": "✅ <b>{usdt} USDT</b> отправлено на ваш счёт в CryptoBot.",
  "wd_err": "⚠️ Не удалось отправить: {err}\n<i>Нужно хотя бы раз открыть @CryptoBot. Если не получается — напишите в 🆘 Поддержку.</i>",
})
for _k in ("st_pending", "st_live", "st_removed", "st_rejected"): T["ru"][_k] = T["tr"][_k]

T["tr"].update({
  "b_pazar": "🏪 Pazar", "b_start": "▶️ Başlat", "b_live": "📊 Canlı", "b_vip": "💎 VIP · 36 saat · 0.2$", "b_yes_stop": "✅ Evet, durdur", "b_no": "✖️ Vazgeç",
  "mkt_head": "🏪 <b>Pazar</b> 👇",
  "mkt_foot": "🏪 <b>Pazar</b>\n<blockquote>💰 Bakiyen  <b>{bal} USDT</b>\nBaşlatınca 0.05$, sonra dakika başı ödersin; istediğin an durdurursun.</blockquote>",
  "card": "🏪 <b>{title}</b>{badge}\n{own}<blockquote>📡 {total} sunucu · {protos}\n🇹🇲 {work}/{tested} çalışıyor · 🌍 {ncc} ülke {flags}\n🕒 Kontrol {chk}</blockquote>\n💲 <b>{m_tmt} TMT / 30 gün</b> ({m_usdt} USDT) · 1 gün {d_tmt} TMT{desc}",
  "card_own": "🏅 <b>Botun resmi kodu</b>\n🛡 7/24 kontrol altında · 🇹🇲 Türkmenistan'dan sürekli test edilir\n⚡ IP değişince kod kendini yeniler, çalışmayan sunucu otomatik çıkarılır\n", "vip_badge": "  💎 VIP",
  "sell_5": "➕ <b>Kodumu Sat · 5/5</b>\n<blockquote>Aylık (30 gün) fiyatın kaç <b>TMT</b>? Sadece sayı yaz, ör. <code>100</code>\nBot dakika başı ücreti ve USDT karşılığını kendisi hesaplar.</blockquote>",
  "sell_badprice": "⚠️ 1 ile 10000 arası bir sayı yaz (aylık TMT), ör. <code>100</code>.",
  "stop_q": "⏹ <b>Durdurulsun mu?</b>\n<blockquote>🏪 {title}\n⏱ {dur} · 💸 {usdt} USDT</blockquote>",
  "live": "📊 <b>Canlı</b> · {title}\n<blockquote>⏱ Süre  {dur}\n💸 Harcanan  <b>{spent}$</b>\n💰 Bakiye  <b>{bal}$</b>\n⏳ Kalan  ≈ {left}\n💲 {m_tmt} TMT / 30 gün</blockquote>\n<i>⟳ Her 10 saniyede güncellenir · {t}</i>",
  "live_off": "📊 <b>{title}</b>\n<blockquote>Bu kod durduruldu.</blockquote>",
  "vip_ok": "💎 <b>İlanın VIP!</b>\n<blockquote>🏪 {title}\n⏳ {left} boyunca pazarın en üstünde.</blockquote>",
  "vip_nobal": "⚠️ VIP için bakiyen yetersiz (0.2$).", "vip_notlive": "⚠️ Sadece yayındaki ilan VIP olabilir.",
  "m_rereview": "🔄 Yasak bitti: «{title}» ilanın yeniden inceleniyor. Uygunsa birkaç dakika içinde tekrar yayında olur.",
  "rj_untested": "Telefon testi bu kodları ölçemedi (protokol desteklenmiyor olabilir).",
  "r_dead": "4'ten fazla sunucu 30 dakika boyunca N/A kaldı.",
  "m_removed": "⛔ <b>İlanın {h} saat yasaklandı</b>\n<blockquote>🏪 {title}\n{why}</blockquote>\n<i>Yasak süresince kodların verilmez, iade yapılmaz. Yasak bitince ilan kendiliğinden yeniden incelenir.</i>",
  "myl_item": "<blockquote>{st} <b>{title}</b>{vip}\n💲 {m} TMT/30 gün · 👥 {n} alıcı · 💰 {earned} USDT{extra}</blockquote>",
  "myl_pend": "\n⏳ Teste gönderildi {ago} · test {a}/{b}", "myl_susp": "\n⛔ Yasak bitişi: {left} sonra", "st_suspended": "⛔",
  "rules": "📜 <b>Pazar kuralları</b>\n\n🏪 <b><u>SATICI</u></b>\n<blockquote>• Her ilan 0.05$ (iade edilmez).\n• Abonelik limitsiz olmalı; ekran görüntüsü zorunlu.\n• Başvuruda en az 4 farklı gerçek ülke (bot ölçer, bayraklara bakılmaz).\n• 💎 VIP: 0.2$ ile 36 saat en üstte.\n• Kazanç: alıcı durdurunca, uzun kullanımda her 24 saatte bir gönderilir.\n• 🔒 Kodların sadece satın alan kişinin dosyasına yazılır, durdurunca silinir. Her kullanım İlanlarım → 📜 Kullanım geçmişi'nde görünür.</blockquote>\n\n🛒 <b><u>ALICI</u></b>\n<blockquote>• Her başlatma 0.05$ + ilk 5 saat peşin (iade edilmez).\n• Aynı ilan 24 saatte en fazla 3 kez başlatılır.\n• Dakika başı ücret bakiyenden düşer (kullansan da kullanmasan da).\n• İstediğin an durdurursun; bakiye bitince kod durur.\n• Bakiye en az 1$ yüklenir; yüklenen bakiye geri çekilmez.</blockquote>",
})
T["ru"].update({
  "b_pazar": "🏪 Биржа", "b_start": "▶️ Запустить", "b_live": "📊 Онлайн", "b_vip": "💎 VIP · 36 ч · 0.2$", "b_yes_stop": "✅ Да, остановить", "b_no": "✖️ Отмена",
  "mkt_head": "🏪 <b>Биржа</b> 👇",
  "mkt_foot": "🏪 <b>Биржа</b>\n<blockquote>💰 Баланс  <b>{bal} USDT</b>\nПри запуске 0.05$, затем поминутная оплата; остановить можно в любой момент.</blockquote>",
  "card": "🏪 <b>{title}</b>{badge}\n{own}<blockquote>📡 {total} серверов · {protos}\n🇹🇲 {work}/{tested} работают · 🌍 {ncc} стран {flags}\n🕒 Проверка {chk}</blockquote>\n💲 <b>{m_tmt} TMT / 30 дней</b> ({m_usdt} USDT) · 1 день {d_tmt} TMT{desc}",
  "card_own": "🏅 <b>Официальный код бота</b>\n🛡 Под контролем 24/7 · 🇹🇲 постоянно проверяется из Туркменистана\n⚡ При смене IP код обновляется сам, неработающие серверы убираются автоматически\n", "vip_badge": "  💎 VIP",
  "sell_5": "➕ <b>Продать код · 5/5</b>\n<blockquote>Сколько <b>TMT</b> стоит месяц (30 дней)? Только число, напр. <code>100</code>\nБот сам посчитает поминутную цену и сумму в USDT.</blockquote>",
  "sell_badprice": "⚠️ Число от 1 до 10000 (TMT в месяц), напр. <code>100</code>.",
  "stop_q": "⏹ <b>Остановить?</b>\n<blockquote>🏪 {title}\n⏱ {dur} · 💸 {usdt} USDT</blockquote>",
  "live": "📊 <b>Онлайн</b> · {title}\n<blockquote>⏱ Время  {dur}\n💸 Потрачено  <b>{spent}$</b>\n💰 Баланс  <b>{bal}$</b>\n⏳ Осталось  ≈ {left}\n💲 {m_tmt} TMT / 30 дней</blockquote>\n<i>⟳ Обновляется каждые 10 секунд · {t}</i>",
  "live_off": "📊 <b>{title}</b>\n<blockquote>Этот код остановлен.</blockquote>",
  "vip_ok": "💎 <b>Объявление VIP!</b>\n<blockquote>🏪 {title}\n⏳ {left} — на самом верху биржи.</blockquote>",
  "vip_nobal": "⚠️ Недостаточно баланса для VIP (0.2$).", "vip_notlive": "⚠️ VIP доступен только для опубликованного объявления.",
  "m_rereview": "🔄 Бан закончился: объявление «{title}» снова на проверке. Если всё в порядке — через несколько минут опубликуется.",
  "rj_untested": "Тест не смог измерить эти коды (возможно, протокол не поддерживается).",
  "r_dead": "Больше 4 серверов были N/A в течение 30 минут.",
  "m_removed": "⛔ <b>Объявление заблокировано на {h} ч</b>\n<blockquote>🏪 {title}\n{why}</blockquote>\n<i>Во время бана коды не выдаются, возврата нет. После бана объявление автоматически проверяется снова.</i>",
  "myl_item": "<blockquote>{st} <b>{title}</b>{vip}\n💲 {m} TMT/30 дн · 👥 {n} покуп. · 💰 {earned} USDT{extra}</blockquote>",
  "myl_pend": "\n⏳ Отправлено на тест {ago} · проверено {a}/{b}", "myl_susp": "\n⛔ Бан закончится через {left}", "st_suspended": "⛔",
  "rules": "📜 <b>Правила биржи</b>\n\n🏪 <b><u>ПРОДАВЕЦ</u></b>\n<blockquote>• Каждое объявление 0.05$ (не возвращается).\n• Подписка должна быть безлимитной; скриншот обязателен.\n• При подаче минимум 4 разные реальные страны (бот измеряет сам, флаги не учитываются).\n• 💎 VIP: 0.2$ — 36 часов на самом верху.\n• Выплата: после остановки покупателем, при долгом использовании — каждые 24 ч.\n• 🔒 Ваши коды записываются только в файл купившего и удаляются после остановки. Каждое использование видно в Мои объявления → 📜 История.</blockquote>\n\n🛒 <b><u>ПОКУПАТЕЛЬ</u></b>\n<blockquote>• Каждый запуск 0.05$ + первые 5 часов сразу (не возвращается).\n• Одно объявление — не больше 3 запусков за 24 ч.\n• Поминутная оплата списывается с баланса (пользуетесь или нет).\n• Остановить можно в любой момент; при нулевом балансе код останавливается.\n• Пополнение от 1$; пополненный баланс не выводится.</blockquote>",
})

T["tr"].update({
  "card": "🏪 <b>{title}</b>{badge}\n{own}\n📡 <b>Sunucular</b>\n<blockquote>🖥 {total} sunucu · {protos}\n{tmline}{ccline}</blockquote>\n\n💰 <b>Fiyat</b>\n<blockquote>📅 30 gün  —  <b>{m_tmt} TMT</b>  <i>({m_usdt} $)</i>\n📆 1 gün  —  <b>{d_tmt} TMT</b>  <i>({d_usdt} $)</i>\n⏱ 1 saat  —  <b>{h_tmt} TMT</b></blockquote>\n<i>▶️ Başlatma 0.05$, sonra kullandığın dakika kadar ödersin · istediğin an durdurursun</i>{desc}",
  "card_own": "\n🏆 <b>RESMİ KOD — BOTUN KENDİ SUNUCULARI</b> 🏆\n<blockquote>🛡 7/24 kontrol altında\n🇹🇲 Türkmenistan'dan sürekli test edilir\n⚡ IP değişince kendini yeniler\n🧹 Çalışmayan sunucu otomatik çıkarılır</blockquote>\n",
  "tm_ok": "🇹🇲 TM testi: ✅ <b>{work}</b> çalışıyor · ❌ {dead}\n🕒 Son test: {ago}",
  "tm_wait": "🇹🇲 TM testi: ⏳ yeni sunucular test ediliyor",
  "cc_line": "\n🌍 {n} ülke  {flags}",
  "b_mcheck": "🔍 Kontrol Et",
  "chk_wait": "⏳ 5 dakikada bir kontrol edebilirsin. {m} dk sonra tekrar dene.",
  "chk_head": "🔍 <b>{title}</b> · sunucu durumu\n<blockquote>{lines}</blockquote>\n✅ {work} çalışıyor · ❌ {dead} çalışmıyor · ⏳ {wait} test bekliyor\n🕒 Son TM testi: {ago}",
  "chk_req": "\n\n📱 <i>Türkmenistan'dan yeni test başlatıldı. Sonuç gelince (1–5 dk) sana gönderilecek.</i>",
  "chk_busy": "\n\n📱 <i>Türkmenistan'dan test zaten sürüyor. Sonuç gelince sana gönderilecek.</i>",
  "chk_done": "🆕 <b>Yeni TM test sonucu</b>\n\n",
  "chk_timeout": "⚠️ Telefon testi şu an cevap vermiyor. Son bilinen durum yukarıdaki gibi.",
  "never": "henüz yok",
})
T["ru"].update({
  "card": "🏪 <b>{title}</b>{badge}\n{own}\n📡 <b>Серверы</b>\n<blockquote>🖥 {total} серверов · {protos}\n{tmline}{ccline}</blockquote>\n\n💰 <b>Цена</b>\n<blockquote>📅 30 дней  —  <b>{m_tmt} TMT</b>  <i>({m_usdt} $)</i>\n📆 1 день  —  <b>{d_tmt} TMT</b>  <i>({d_usdt} $)</i>\n⏱ 1 час  —  <b>{h_tmt} TMT</b></blockquote>\n<i>▶️ Запуск 0.05$, далее платите только за использованные минуты · остановить можно в любой момент</i>{desc}",
  "card_own": "\n🏆 <b>ОФИЦИАЛЬНЫЙ КОД — СЕРВЕРЫ САМОГО БОТА</b> 🏆\n<blockquote>🛡 Под контролем 24/7\n🇹🇲 Постоянно проверяется из Туркменистана\n⚡ При смене IP обновляется сам\n🧹 Неработающие серверы убираются автоматически</blockquote>\n",
  "tm_ok": "🇹🇲 Тест в TM: ✅ <b>{work}</b> работают · ❌ {dead}\n🕒 Последний тест: {ago}",
  "tm_wait": "🇹🇲 Тест в TM: ⏳ новые серверы проверяются",
  "cc_line": "\n🌍 {n} стран  {flags}",
  "b_mcheck": "🔍 Проверить",
  "chk_wait": "⏳ Проверять можно раз в 5 минут. Попробуйте через {m} мин.",
  "chk_head": "🔍 <b>{title}</b> · состояние серверов\n<blockquote>{lines}</blockquote>\n✅ {work} работают · ❌ {dead} не работают · ⏳ {wait} ждут теста\n🕒 Последний тест в TM: {ago}",
  "chk_req": "\n\n📱 <i>Запущен новый тест из Туркменистана. Результат придёт сюда (1–5 мин).</i>",
  "chk_busy": "\n\n📱 <i>Тест из Туркменистана уже идёт. Результат придёт сюда.</i>",
  "chk_done": "🆕 <b>Новый результат теста в TM</b>\n\n",
  "chk_timeout": "⚠️ Телефонный тест сейчас не отвечает. Последнее известное состояние — выше.",
  "never": "ещё нет",
})

def ago_l(ts, lang):
    if not ts: return tr(lang, "never")
    d = time.time() - ts
    if lang == "tk":
        if d < 60: return "1 minutdan az öň"
        m = int(d // 60); h, m = divmod(m, 60); g, h = divmod(h, 24)
        return " ".join(([f"{g} gün"] if g else []) + ([f"{h} sag"] if h else []) + [f"{m} min"]) + " öň"
    if d < 60: return "<1 мин назад" if lang == "ru" else "1 dk'dan az önce"
    return dur_txt(d, lang == "ru") + (" назад" if lang == "ru" else " önce")

T["tr"].update({
  "cap": "👋 <b>Hoş geldin!</b>\n<blockquote>VPN satın almak için mi geldin, yoksa VPN satıcısı mısın?</blockquote>",
  "b_cap_buy": "🛒 VPN almak istiyorum", "b_cap_sell": "🏪 VPN satıcısıyım",
  "card": "🏪 <b>{title}</b>\n{own}\n📡 <b>Sunucular</b>\n<blockquote>🖥 {total} sunucu · {protos}\n{tmline}{ccline}</blockquote>\n\n💰 <b>Fiyat</b>\n<blockquote>{prices}</blockquote>\n\n{payline}{desc}",
  "card_seller": "{head}\n\n🏪 <b>{title}</b>\n\n💰 <b>Fiyat</b>\n<blockquote>{prices}</blockquote>\n\n<i>🔍 Sunucuları ve ülkeleri görmek için «Kontrol Et»e bas.</i>",
  "head_vip": "💎💎 <b>VIP SATICI</b> 💎💎", "head_std": "🏷 <b>Satıcı ilanı</b>",
  "prices": "⏱ 1 dakika  —  <b>{mi} TMT</b>\n🕐 1 saat  —  <b>{h} TMT</b>\n📅 1 hafta  —  <b>{w} TMT</b>\n🗓 1 ay  —  <b>{m} TMT</b>",
  "payline": "💡 <b>Pul doly alynmaýar</b> — töleg diňe ulanan minudyňyza / sagadyňyza görä alynýar.\n▶️ Başlanda bir gezek 0.05$ · islän wagtyňyz togtadyp bilersiňiz.",
  "mkt_bal": "\n\n💰 Bakiyen  <b>{bal} USDT</b>",
  "mkt_none": "\n<i>Şu an başka satıcı yok.</i>",
  "b_sellers": "👥 Satıcılar ({n}) ▶️",
  "chk_line_ok": "🎯", "chk_line_bad": "⚠️ gerçek: {f} {n}", "chk_line_real": "→ {f} {n}",
  "chk_head": "🔍 <b>{title}</b> · sunucu durumu\n<blockquote>{lines}</blockquote>\n✅ {work} çalışıyor · ❌ {dead} çalışmıyor · ⏳ {wait} bekliyor\n🎯 ülke doğru · ⚠️ ülke yanlış (gerçeği yanında)\n🕒 Son TM testi: {ago}",
  "chk_run": "\n⏳ <b>Kodların Türkmenistan'da çalışıp çalışmadığı kontrol ediliyor...</b>\n<i>(~1 dk) Sonuç bu kutuda görünecek.</i>",
  "chk_upd": "\n\n✅ <i>Güncellendi · {t}</i>",
  "chk_timeout": "\n\n⚠️ <i>Telefon testi şu an cevap vermiyor; yukarıdaki son bilinen durum.</i>",
  "b_recheck": "🔄 Yenile",
})
T["ru"].update({
  "cap": "👋 <b>Добро пожаловать!</b>\n<blockquote>Вы пришли купить VPN или вы продавец VPN?</blockquote>",
  "b_cap_buy": "🛒 Хочу купить VPN", "b_cap_sell": "🏪 Я продавец VPN",
  "card": "🏪 <b>{title}</b>\n{own}\n📡 <b>Серверы</b>\n<blockquote>🖥 {total} серверов · {protos}\n{tmline}{ccline}</blockquote>\n\n💰 <b>Цена</b>\n<blockquote>{prices}</blockquote>\n\n{payline}{desc}",
  "card_seller": "{head}\n\n🏪 <b>{title}</b>\n\n💰 <b>Цена</b>\n<blockquote>{prices}</blockquote>\n\n<i>🔍 Чтобы увидеть серверы и страны, нажмите «Проверить».</i>",
  "head_vip": "💎💎 <b>VIP ПРОДАВЕЦ</b> 💎💎", "head_std": "🏷 <b>Объявление продавца</b>",
  "prices": "⏱ 1 минута  —  <b>{mi} TMT</b>\n🕐 1 час  —  <b>{h} TMT</b>\n📅 1 неделя  —  <b>{w} TMT</b>\n🗓 1 месяц  —  <b>{m} TMT</b>",
  "payline": "💡 <b>Деньги не списываются сразу</b> — оплата только за использованные минуты / часы.\n▶️ При запуске один раз 0.05$ · остановить можно в любой момент.",
  "mkt_bal": "\n\n💰 Баланс  <b>{bal} USDT</b>",
  "mkt_none": "\n<i>Других продавцов пока нет.</i>",
  "b_sellers": "👥 Продавцы ({n}) ▶️",
  "chk_line_ok": "🎯", "chk_line_bad": "⚠️ на деле: {f} {n}", "chk_line_real": "→ {f} {n}",
  "chk_head": "🔍 <b>{title}</b> · состояние серверов\n<blockquote>{lines}</blockquote>\n✅ {work} работают · ❌ {dead} не работают · ⏳ {wait} ждут\n🎯 страна верна · ⚠️ страна неверна (настоящая рядом)\n🕒 Последний тест в TM: {ago}",
  "chk_run": "\n⏳ <b>Проверяем, работают ли коды в Туркменистане...</b>\n<i>(~1 мин) Результат появится здесь.</i>",
  "chk_upd": "\n\n✅ <i>Обновлено · {t}</i>",
  "chk_timeout": "\n\n⚠️ <i>Телефонный тест сейчас не отвечает; выше — последнее известное состояние.</i>",
  "b_recheck": "🔄 Обновить",
})

T["tr"].update({
  "b_buy_m": "🛒 Satın Al", "chk_refresh": "\n⏳ <i>Yeni test yapılıyor (~1 dk), sonuç gelince bu kutu güncellenecek.</i>",
  "top_sellers": "\n💱 <b>CryptoBot ile ödeyemiyor musun?</b>\n<i>Bu satıcılardan TMT karşılığında CryptoBot için USDT alabilirsin:</i>\n{sellers}",
  "link_below": "🔗 linki almak için aşağıdaki butona bas",
  "del_q": "🗑 <b>Bu kod silinsin mi?</b>\n<blockquote>🎟 {name}\nAbonelik linki artık çalışmaz.</blockquote>", "b_yes_del": "🗑 Evet, sil", "deleted": "🗑 Kod silindi",
  "menu_bal": "\n💰 Bakiye  <b>{bal} USDT</b>  <i>≈ {tmt} TMT</i>",
  "sell_1": "➕ <b>Kodumu Sat · 1/5</b>\n<blockquote>🔗 Abonelik linkini gönder\n<b>(GB limiti ya da süre sınırı olmamalı!)</b></blockquote>",
  "m_photo_bad": "🔞 <b>İlanın kaldırıldı</b>\n<blockquote>🏪 {title}\nFotoğraf uygunsuz bulundu.</blockquote>\n⛔ {h} saat botu kullanamazsın. Ücret iade edilmez.",
  "rj_admin": "Admin tarafından reddedildi.",
  "open_line": "\n\n🟢 <b>Açık pazar kodun: {n}</b>\n<i>Dakikada {pm} TMT düşüyor · şimdiye kadar {spent} TMT.\nKullanmıyorsan 🎟 Kodlarım → ⏹ Durdur.</i>",
  "b_open": "🟢 Açık kodlarım ({n})",
  "m_remind": "⏰ <b>Pazar kodun hâlâ açık</b>\n<blockquote>🏪 {title}\n⏱ {dur} · 💸 {spent} TMT\n💰 Bakiye {bal} USDT</blockquote>\n<i>Kullanmıyorsan durdur; yoksa dakika başı para düşmeye devam eder.</i>",
  "chk_el": "\n⌛ Geçen süre: <b>{m} dk</b>",
  "chk_old": "\n📱 <i>Telefon tam test yapıyor, birkaç dakika sürebilir.</i>",
  "chk_off": "\n📱 <i>Telefon testi şu an çalışmıyor; yukarıda son bilinen durum.</i>",
  "sell_5": "➕ <b>Kodumu Sat · 5/5</b>\n<blockquote>Bir aylık kodu kaç <b>TMT</b>'ye satıyorsun? <i>(ör. 100)</i></blockquote>",
  "sell_bal": "\n💰 Bakiyen  <b>{bal} USDT</b>",
  "head_own": "🏆 <b>BOTUN RESMİ KODU</b> 🏆", "head_vip": "💎 <b>VIP Sunucu</b>", "head_std": "🏷 <b>Standart Sunucu</b>",
  "card2": "{head}\n\n🏪 <b>{title}</b>\n\n💰 <b>Fiyat</b>\n<blockquote>{prices}</blockquote>\n\n<i>🔍 Sunucular ve ülkeler için «Kontrol Et»e bas.</i>",
  "card_own": "<blockquote>🛡 7/24 kontrol altında\n🇹🇲 Türkmenistan'dan sürekli test edilir\n⚡ IP değişince kendini yeniler\n🧹 Çalışmayan sunucu otomatik çıkarılır</blockquote>\n",
  "chk_run": "\n⏳ <b>Kodların Türkmenistan'da çalışıp çalışmadığı kontrol ediliyor...</b>\n<i>(~1 dk) Sonuç bu kutuda görünecek.</i>",
  "chk_head2": "\n🔍 <b>Sunucular</b>\n<blockquote>{lines}</blockquote>\n✅ {work} çalışıyor · ❌ {dead} çalışmıyor · ⏳ {wait} bekliyor\n🎯 ülke doğru · ⚠️ ülke yanlış\n🕒 Son TM testi: {ago}",
  "chk_upd": "\n✅ <i>Güncellendi · {t}</i>",
  "chk_timeout": "\n⚠️ <i>Telefon testi şu an cevap vermiyor; yukarıda son bilinen durum.</i>",
  "payline": "💡 <b>Pul doly alynmaýar</b> — töleg diňe ulanan minudyňyza / sagadyňyza görä alynýar.\n▶️ Kody açanyňyzda bir gezek 0.05$. Islän wagtyňyz kody yzyna gowşuryp bilersiňiz — galan puluňyz balansyňyzda galýar (diňe ulanylan wagtyň puly alynýar).",
  "b_back": "◀️ Geri",
})
T["ru"].update({
  "b_buy_m": "🛒 Купить", "chk_refresh": "\n⏳ <i>Идёт новый тест (~1 мин), результат обновится здесь.</i>",
  "top_sellers": "\n💱 <b>Не получается оплатить через CryptoBot?</b>\n<i>У этих продавцов можно купить USDT для CryptoBot за TMT:</i>\n{sellers}",
  "link_below": "🔗 ссылка — кнопкой ниже",
  "del_q": "🗑 <b>Удалить этот код?</b>\n<blockquote>🎟 {name}\nСсылка подписки перестанет работать.</blockquote>", "b_yes_del": "🗑 Да, удалить", "deleted": "🗑 Код удалён",
  "menu_bal": "\n💰 Баланс  <b>{bal} USDT</b>  <i>≈ {tmt} TMT</i>",
  "sell_1": "➕ <b>Продать код · 1/5</b>\n<blockquote>🔗 Отправьте ссылку подписки\n<b>(без лимита ГБ и без ограничения срока!)</b></blockquote>",
  "m_photo_bad": "🔞 <b>Объявление удалено</b>\n<blockquote>🏪 {title}\nФото признано неприемлемым.</blockquote>\n⛔ {h} ч вы не можете пользоваться ботом. Плата не возвращается.",
  "rj_admin": "Отклонено администратором.",
  "open_line": "\n\n🟢 <b>Открытых кодов с биржи: {n}</b>\n<i>Списывается {pm} TMT в минуту · всего {spent} TMT.\nЕсли не пользуетесь: 🎟 Мои коды → ⏹ Стоп.</i>",
  "b_open": "🟢 Открытые коды ({n})",
  "m_remind": "⏰ <b>Код с биржи всё ещё открыт</b>\n<blockquote>🏪 {title}\n⏱ {dur} · 💸 {spent} TMT\n💰 Баланс {bal} USDT</blockquote>\n<i>Если не пользуетесь — остановите, иначе списание каждую минуту продолжится.</i>",
  "chk_el": "\n⌛ Прошло: <b>{m} мин</b>",
  "chk_old": "\n📱 <i>Телефон делает полный тест, это может занять несколько минут.</i>",
  "chk_off": "\n📱 <i>Телефонный тест сейчас не работает; выше — последнее известное состояние.</i>",
  "sell_5": "➕ <b>Продать код · 5/5</b>\n<blockquote>За сколько <b>TMT</b> продаёшь код на месяц? <i>(напр. 100)</i></blockquote>",
  "sell_bal": "\n💰 Баланс  <b>{bal} USDT</b>",
  "head_own": "🏆 <b>ОФИЦИАЛЬНЫЙ КОД БОТА</b> 🏆", "head_vip": "💎 <b>VIP сервер</b>", "head_std": "🏷 <b>Стандартный сервер</b>",
  "card2": "{head}\n\n🏪 <b>{title}</b>\n\n💰 <b>Цена</b>\n<blockquote>{prices}</blockquote>\n\n<i>🔍 Серверы и страны — кнопка «Проверить».</i>",
  "card_own": "<blockquote>🛡 Под контролем 24/7\n🇹🇲 Постоянно проверяется из Туркменистана\n⚡ При смене IP обновляется сам\n🧹 Неработающие серверы убираются автоматически</blockquote>\n",
  "chk_run": "\n⏳ <b>Проверяем, работают ли коды в Туркменистане...</b>\n<i>(~1 мин) Результат появится здесь.</i>",
  "chk_head2": "\n🔍 <b>Серверы</b>\n<blockquote>{lines}</blockquote>\n✅ {work} работают · ❌ {dead} не работают · ⏳ {wait} ждут\n🎯 страна верна · ⚠️ страна неверна\n🕒 Последний тест в TM: {ago}",
  "chk_upd": "\n✅ <i>Обновлено · {t}</i>",
  "chk_timeout": "\n⚠️ <i>Телефонный тест сейчас не отвечает; выше — последнее известное состояние.</i>",
  "payline": "💡 <b>Деньги не списываются сразу</b> — оплата только за использованные минуты / часы.\n▶️ При запуске один раз 0.05$. Код можно вернуть в любой момент — остаток останется на балансе (списывается только за использованное время).",
  "b_back": "◀️ Назад",
})

# Türkmençe (eksik anahtar olursa Türkçesi görünür)
T["tk"] = {
 "b_buy_m": "🛒 Satyn al", "chk_refresh": "\n⏳ <i>Täze test edilýär (~1 min), netije gelende şu ýer täzelener.</i>",
 "top_sellers": "\n💱 <b>CryptoBot bilen töläp bilmeýärsiňizmi?</b>\n<i>Şu satyjylardan TMT-a CryptoBot üçin USDT satyn alyp bilersiňiz:</i>\n{sellers}",
 "link_below": "🔗 linki almak üçin aşakdaky knopka bas",
 "del_q": "🗑 <b>Bu kod pozulsynmy?</b>\n<blockquote>🎟 {name}\nPodpiska linki indi işlemez.</blockquote>", "b_yes_del": "🗑 Hawa, poz", "deleted": "🗑 Kod pozuldy",
 "menu_bal": "\n💰 Balans  <b>{bal} USDT</b>  <i>≈ {tmt} TMT</i>",
 "sell_1": "➕ <b>Kodumy sat · 1/5</b>\n<blockquote>🔗 Podpiska linkini iber\n<b>(GB limiti ýa-da möhlet çägi bolmaly däl!)</b></blockquote>",
 "m_photo_bad": "🔞 <b>Bildirişiň aýryldy</b>\n<blockquote>🏪 {title}\nSurat ýerliksiz diýlip tapyldy.</blockquote>\n⛔ {h} sagat boty ulanyp bilmersiň. Töleg yzyna gaýtarylmaýar.",
 "rj_admin": "Admin tarapyndan ret edildi.",
 "open_line": "\n\n🟢 <b>Açyk bazar kodyň: {n}</b>\n<i>Her minutda {pm} TMT alynýar · şu wagta çenli {spent} TMT.\nUlanmaýan bolsaň 🎟 Kodlarym → ⏹ Yzyna gowşur.</i>",
 "b_open": "🟢 Açyk kodlarym ({n})",
 "m_remind": "⏰ <b>Bazar kodyň henizem açyk</b>\n<blockquote>🏪 {title}\n⏱ {dur} · 💸 {spent} TMT\n💰 Balans {bal} USDT</blockquote>\n<i>Ulanmaýan bolsaň yzyna gowşur, ýogsa her minutda pul alynmagy dowam edýär.</i>",
 "chk_el": "\n⌛ Geçen wagt: <b>{m} min</b>",
 "chk_old": "\n📱 <i>Telefon doly test edýär, birnäçe minut alyp biler.</i>",
 "chk_off": "\n📱 <i>Telefon testi häzir işlänok; ýokarda soňky belli ýagdaý.</i>",
 "sell_5": "➕ <b>Kodumy sat · 5/5</b>\n<blockquote>Bir aýlyk kody näçe <b>TMT</b>-a satýaň? <i>(mysal: 100)</i></blockquote>",
 "sell_bal": "\n💰 Balansyň  <b>{bal} USDT</b>",
 "menu": "✦ <b>VPN</b> ✦\n<blockquote>👥 Çakylyk  <b>{avail}/{need}</b>\n🎟 Işleýän kod  <b>{codes}</b></blockquote>\n<i>Birini saýla</i> 👇",
 "b_free": "✨ Kod döret",
 "b_mine": "🎟 Kodlarym",
 "b_prof": "👤 Profil",
 "b_market": "🛒 Market",
 "b_lang": "🌐 Dil: Türkmençe",
 "b_menu": "◀️ Menýu",
 "b_share": "📤 Dostlaryňa iber",
 "b_check": "🔍 Barla",
 "b_paid": "✅ TMT töledim",
 "b_cancel": "✖️ Ýatyr",
 "b_back": "◀️ Yza",
 "free_need": "🎁 <b>Mugt kod</b>\n<blockquote>Her kod üçin <b>{need}</b> sany täze dostuňy çagyr.\nHäzir  <b>{avail}/{need}</b></blockquote>\n🔗 <b>Çakylyk linkiň</b> <i>(bas → kopiýala)</i>\n<code>{link}</code>",
 "free_today": "⏳ <b>Şu günki mugt kodyňy aldyň.</b>\n<blockquote>Ertir ýene alyp bilersiň (Aşgabat wagty bilen 00:00-dan soň).</blockquote>",
 "free_ok": "✅ <b>Kodyň taýýar!</b>\n<blockquote>⏳ Möhlet  <b>{left}</b>\n📲 Linki kopiýala-da, VPN programmaňa (Happ) podpiska edip goş.</blockquote>\n🔗 <b>Podpiska linki</b> <i>(bas → kopiýala)</i>\n<code>{link}</code>",
 "no_slot": "⚠️ Häzir boş kod ýeri ýok. Biraz soňrak ýene synanyş.",
 "mine_none": "🎟 <b>Kodlarym</b>\n<blockquote>Işleýän kodyň ýok.</blockquote>",
 "mine": "🎟 <b>Kodlarym</b>",
 "mine_item": "<blockquote>🎟 <b>{name}</b>  ·  ⏳ {left}\n<code>{link}</code></blockquote>",
 "prof": "👤 <b>Profil</b>\n<blockquote>🪪 ID  <code>{id}</code>\n👤 Adyň  {name}\n🔗 Ulanyjy ady  {un}\n🌐 Dil  Türkmençe\n📅 Goşulan güni  {joined}\n🕒 Häzir  {now}</blockquote>\n<blockquote>👥 Çagyranlaryň  <b>{total}</b>\n✅ Ulanyp boljak çakylyk  <b>{avail}/{need}</b>\n🎁 Alan mugt kodlaryň  <b>{free}</b>\n🎟 Işleýän kod  <b>{active}</b>\n🛒 Satyn alanlaryň  <b>{buys}</b>\n🙋 Seni çagyran  {inviter}</blockquote>\n🔗 <b>Çakylyk linkiň</b> <i>(bas → kopiýala)</i>\n<code>{link}</code>",
 "share_text": "Mugt VPN kody al 👇",
 "market": "🛒 <b>Market</b>\n<blockquote>🎟 Kod · 7 gün  —  <b>30 TMT</b> · 1.5 USDT\n🎟 Kod · 30 gün  —  <b>100 TMT</b> · 5 USDT\n🖥 Panel  —  her ulanyjy üçin <b>20 TMT</b> · 1 USDT <i>(iň az 20)</i></blockquote>\n💵 USDT bilen töleg (CryptoBot) awtomatik tassyklanýar.\n💳 TMT bilen töleg ýakyn wagtda 🔜\n<i>Näme satyn aljagyňy saýla</i> 👇",
 "b_c7": "🎟 Kod 7 gün · 30 TMT",
 "b_c30": "🎟 Kod 30 gün · 100 TMT",
 "b_panel": "🖥 Panel · 20 TMT/ulanyjy",
 "panel_ask": "🖥 <b>Panel</b>\n<blockquote>Öz ulanyjylaryň üçin kod döredip, olary dolandyryp bilýän paneliň.\nHer ulanyjy üçin <b>20 TMT</b> · iň az <b>20</b> ulanyjy · <b>30 gün</b></blockquote>\nNäçe ulanyjy? Knopka bas ýa-da san ýaz:",
 "panel_min": "⚠️ Iň az 20 ulanyjy.",
 "it_c7": "🎟 Kod · 7 gün",
 "it_c30": "🎟 Kod · 30 gün",
 "it_panel": "🖥 Panel · {n} ulanyjy · 30 gün",
 "order": "🧾 <b>Sargyt #{oid}</b>\n<blockquote>{item}\n💰 Bahasy  <b>{price} TMT</b>  ·  <b>{usdt} USDT</b></blockquote>\n{usdt_line}💳 <b>TMT bilen töleg</b>\n<blockquote>{pay}</blockquote>\n<i>TMT bilen töleseň «✅ TMT töledim» knopkasyna bas, admin tassyklandan soň kodyň geler.</i>",
 "usdt_line": "💵 <b>USDT bilen töleg</b> <i>(CryptoBot, awtomatik tassyklanýar)</i> → aşakdaky knopka bas.\n\n",
 "b_usdt": "💵 USDT-de töle ({usdt} USDT)",
 "b_pay": "💸 CryptoBotda töle",
 "b_chk": "🔄 Tölegi barla",
 "inv": "💵 <b>USDT bilen töleg · #{oid}</b>\n<blockquote>{item}\n💰 <b>{usdt} USDT</b>\n⏳ 1 sagat işleýär</blockquote>\n«💸 CryptoBotda töle» knopkasyna bas-da, töle. Töleg gelende kodyň <b>awtomatik</b> iberiler.",
 "inv_wait": "Töleg entek gelmedi. Tölän bolsaň, 1 minutdan soň ýene barla.",
 "inv_err": "⚠️ USDT töleg hasaby döredip bolmady. Biraz soňrak ýene synanyş ýa-da TMT bilen töle.",
 "pay_default": "Töleg barada bilmek üçin admin bilen habarlaş.",
 "order_sent": "⏳ <b>Sargyt #{oid} admine iberildi.</b>\n<blockquote>Tassyklanandan soň şu ýere habar geler.</blockquote>",
 "order_old": "ℹ️ Bu sargyt eýýäm barlanýar.",
 "order_ok_code": "✅ <b>Sargyt #{oid} tassyklandy!</b>\n<blockquote>⏳ Möhlet  <b>{left}</b></blockquote>\n🔗 <b>Podpiska linki</b> <i>(bas → kopiýala)</i>\n<code>{link}</code>",
 "order_ok_panel": "✅ <b>Sargyt #{oid} tassyklandy!</b>\n<blockquote>🖥 Paneliň taýýar: <b>{n}</b> ulanyjy · <b>{days}</b> gün</blockquote>\nPaneli açmak üçin /start ýaz.",
 "order_no": "❌ <b>Sargyt #{oid} tassyklanmady.</b>\n<blockquote>Bir mesele bar bolsa, admin bilen habarlaş.</blockquote>",
 "cap": "👋 <b>Hoş geldiň!</b>\n<blockquote>VPN satyn almaga geldiňmi, ýa-da özüň VPN satyjysyňmy?</blockquote>",
 "cap_wrong": "❌ Ýalňyş, ýene synanyş.",
 "join": "📢 <b>Boty ulanmak üçin kanala podpiska bol</b>\n<blockquote>Podpiska bolandan soň «✅ Barla» bas.</blockquote>",
 "join_no": "Sen entek podpiska bolmadyň.",
 "ref_new": "🎉 <b>{name}</b> seniň çakylygyň bilen goşuldy!\n<blockquote>Çakylyk  <b>{avail}/{need}</b></blockquote>",
 "ref_ready": "🎁 Çakylyklar doldy! Mugt kodyňy alyp bilersiň.",
 "expired": "⏳ Kodyňyň möhleti gutardy, ol pozuldy: {name}",
 "nobody": "—",
 "b_sup": "🆘 Support",
 "b_bug": "🐞 Bug bildir",
 "b_tclose": "🔒 Soragy ýap",
 "b_report": "📨 Admine ýaz",
 "bug_new": "🐞 <b>Ýalňyşlyk ýaz · #{tid}</b>\n<blockquote>Tapan ýalňyşlygyňy düşündirip ýaz. Skrinşot ýa-da wideo goşup bilersiň.\n📷 Surat iň köp 5 MB · 🎬 Wideo/faýl iň köp 10 MB</blockquote>\n<i>Admin jogap berse, şu ýerde görersiň; sen hem jogap ýazyp bilersiň.</i>",
 "sup_new": "🆘 <b>Goldaw · #{tid}</b>\n<blockquote>Meseläňi ýaz. Surat, wideo ýa-da faýl hem iberip bilersiň.\n📷 Surat iň köp 5 MB · 🎬 Wideo/faýl iň köp 10 MB</blockquote>\n<i>Admin jogap berse, şu ýerde görersiň; sen hem jogap ýazyp bilersiň. Sorag ýapylýança gürrüňdeşlik dowam edýär.</i>",
 "sup_open": "🆘 <b>Goldaw · #{tid}</b>\n<blockquote>Soragyň açyk. Habar ýazyp bilersiň; admin jogap berse, şu ýerde görersiň.</blockquote>",
 "sup_sent": "✅ Iberildi. Adminiň jogabyna garaş.",
 "sup_wait": "⏳ Ilki adminiň jogabyna garaş (jogapsyz iň köp 3 habar).",
 "sup_big": "⚠️ Faýl gaty uly. Surat iň köp 5 MB, wideo/faýl iň köp 10 MB.",
 "sup_reply": "💬 <b>Goldawyň jogaby</b> · #{tid}",
 "sup_closed_admin": "🔒 Goldaw soragyň #{tid} ýapyldy. Täze mesele çyksa, 🆘 Goldaw düwmesine bas.",
 "sup_closed": "🔒 Sorag #{tid} ýapyldy.",
 "err": "⚠️ <b>Ýalňyşlyk çykdy.</b>\n<blockquote>Edip bolmady. Gaýtadan synanyş; düzelmese, admine ýaz.</blockquote>",
 "reported": "✅ Admine habar berildi, sag bol.",
 "tmt_soon": "💳 <b>TMT bilen töleg</b> — <i>ýakynda 🔜</i>",
 "pay_off": "⚠️ Onlaýn töleg häzir işlänok.\n\n",
 "b_trial": "🎁 3 sagatlyk synag",
 "trial_ok": "🎁 <b>Synag kodyň taýýar!</b>\n<blockquote>⏳ 3 sagat işleýär\n📲 Linki göçür-de, VPN programmaňa (Happ) podpiska edip goş.</blockquote>\n🔗 <b>Podpiska linki</b> <i>(bas → göçür)</i>\n<code>{link}</code>",
 "trial_used": "ℹ️ Synag koduny öň ulanypsyň.",
 "trial_end": "⏳ Synag möhletiň gutardy. Halan bolsaň, 🛒 Marketden kod alyp bilersiň.",
 "remind": "⏳ <b>Kodyň ertir gutarýar</b>\n<blockquote>🎟 {name}\n⏳ Galan  <b>{left}</b></blockquote>\nUzatsaň, link şol bolşy ýaly galýar, hiç zat üýtgetmeli däl.",
 "b_ext": "🔄 Uzat",
 "ext_ask": "🔄 <b>Kody uzat</b>\n<blockquote>🎟 {name}\n⏳ Galan  <b>{left}</b></blockquote>\nNäçe wagt uzadylsyn?",
 "it_ext": "🔄 Uzatmak · {days} gün · {name}",
 "order_ok_ext": "✅ <b>Sargyt #{oid} tassyklandy!</b>\n<blockquote>🎟 {name} uzadyldy\n⏳ Galan  <b>{left}</b></blockquote>\nLink şol bir, hiç zat etmeli däl.",
 "banned": "⛔ Sen bu botda bloklandyň.",
 "gift": "🎁 <b>Admin saňa kod berdi!</b>\n<blockquote>⏳ Möhlet  <b>{left}</b></blockquote>\n🔗 <b>Podpiska linki</b> <i>(bas → göçür)</i>\n<code>{link}</code>",
 "added": "⏳ Kodyňyň möhleti uzadyldy: {name} · galan {left}",
 "b_mkt": "🏪 Bazar (minutlaýyn)",
 "b_sell": "Öz Kodyňyzy Satmak 🪪",
 "b_myl": "📦 Satuwym",
 "b_rules": "📜 Düzgün",
 "b_start": "▶️ Başla",
 "b_shot": "📷 Skrinşot",
 "b_back_mkt": "◀️ Bazar",
 "b_stop": "⏹ Yzyna gowşur",
 "b_top": "➕ Doldur",
 "b_wd": "💸 Gazanjy çek",
 "b_other": "✏️ Başga summa",
 "mkt": "🏪 <b>Bazar</b>\n<blockquote>Satyjylaryň VPN kodlary. Minutlaýyn tölersiň, islän wagtyň yzyna gowşuryp bilersiň.\nKodlary bot her minut barlaýar.\n💰 Balansyň  <b>{bal} USDT</b></blockquote>\n<i>Bir bildiriş saýla</i> 👇",
 "mkt_empty": "<i>Häzir başga bildiriş ýok.</i>",
 "ml": "🏪 <b>{title}</b>\n<blockquote>{own}👤 Satyjy  {seller}\n📡 Serwer  <b>{total}</b>  ·  {protos}\n🇹🇲 TM barlagy  <b>{work}/{tested}</b> işleýär  ·  ❌ {dead}\n🌍 Hakyky ýurt  <b>{ncc}</b>  {flags}\n🔌 Açyk port (VPS)  {tcp}\n🕒 Soňky barlag  {chk}\n✅ Soňky işlän wagty  {good}</blockquote>\n💲 <b>Baha</b>\n<blockquote>{calc}</blockquote>{desc}\n<i>Başlanyňda 0.05$ başlangyç töleg alynýar, soň her minut balansyňdan tutulýar.</i>",
 "ml_own": "⭐ Resmi bildiriş\n",
 "m_need": "⚠️ <b>Balans ýetenok</b>\n<blockquote>Başlamak üçin iň az <b>{need} USDT</b> gerek (0.05$ + 5 sagat).\n💰 Balansyň  <b>{bal} USDT</b></blockquote>",
 "m_started": "✅ <b>Kod başlady!</b>\n<blockquote>🏪 {title}\n💲 {p}  ·  💰 Balans {bal} USDT</blockquote>\n🔗 <b>Podpiska linki</b> <i>(bas → göçür)</i>\n<code>{link}</code>\n<i>Yzyna gowşurmak üçin: 🎟 Kodlarym → ⏹ Yzyna gowşur</i>",
 "m_already": "ℹ️ Bu bildiriş sende eýýäm açyk. 🎟 Kodlarym bölüminden görüp bilersiň.",
 "m_gone": "⚠️ Bu bildiriş indi ýok.",
 "m_stopped": "⏹ <b>Kod yzyna gowşuryldy</b>\n<blockquote>🏪 {title}\n⏱ Ulanylan wagt  {dur}\n💸 Jemi  {usdt} USDT</blockquote>{why}",
 "why_nobal": "<i>Balansyň gutardy, şonuň üçin yzyna gowşuryldy.</i>",
 "why_gone": "<i>Bildiriş bazardan aýryldy, şonuň üçin yzyna gowşuryldy.</i>",
 "why_user": "",
 "m_low": "⚠️ Balansyň azalýar: bazardan alan kodyň takmynan ýene <b>{m} minut</b> işlär.",
 "mine_m": "<blockquote>🏪 <b>{title}</b>  ·  ⏱ {dur}  ·  💸 {usdt} USDT\n<code>{link}</code></blockquote>",
 "sell_banned": "⛔ Bazarda bloklandyň: <b>{left}</b> soň täzeden bildiriş goýup bilersiň.",
 "sell_badlink": "⚠️ Bu linkden kod alyp bolmady. Linki barla-da, täzeden iber.\n<i>Happ-yň şifrlenen (happ://crypt…) ýa-da ýapyk linkleri kabul edilmeýär — açyk podpiska linkini iberiň.</i>",
 "sell_dup": "⚠️ Bu link eýýäm bazarda bar.",
 "sell_2": "➕ <b>Kodumy sat · 2/5</b>\n<blockquote>✅ Linkde <b>{n}</b> serwer tapyldy ({protos}).\nBildirişiň adyny ýaz (mysal: <code>Fast VPN 🇩🇪</code>).</blockquote>",
 "sell_3": "➕ <b>Kodumy sat · 3/5</b>\n<blockquote>Kodyňyň <b>skrinşotyny</b> iber (surat görnüşinde).</blockquote>",
 "sell_need_photo": "⚠️ Skrinşoty surat görnüşinde iber.",
 "sell_4": "➕ <b>Kodumy sat · 4/5</b>\n<blockquote>Düşündiriş ýaz (tizligi, aýratynlyklary, habarlaşmak üçin...). Geçmek üçin <code>-</code> iber.</blockquote>",
 "sell_badprice": "⚠️ 1 bilen 10000 arasynda san ýaz (aýlyk TMT), mysal: <code>100</code>.",
 "sell_confirm": "🧾 <b>Bildiriş barada gysgaça</b>\n<blockquote>🏷 {title}\n📡 {n} serwer · {protos}\n📝 {desc}</blockquote>\n💲 <b>Baha hasaplaýjy</b>\n<blockquote>{calc}</blockquote>\n<i>Tassyklasaň, balansyňdan <b>0.05$</b> bildiriş tölegi alynýar (yzyna gaýtarylmaýar). Bot kodlaryňy barlaýar; düzgünlere laýyk bolsa, birnäçe minutdan bazara çykýar.</i>",
 "b_sellok": "✅ Limitsiz, tassyklaýaryn · 0.05$ töle",
 "b_sellp": "✏️ Bahany üýtget",
 "sell_nobal": "⚠️ Bildiriş tölegi üçin balansyň ýetenok (0.05$). Ilki balansy doldur.",
 "sell_sent": "⏳ <b>Bildirişiň barlagda</b>\n<blockquote>Bot kodlaryňy Türkmenistandan barlaýar. Hemme zat düzgün bolsa, birnäçe minutdan bazara çykar, saňa habar geler.</blockquote>",
 "m_approved": "✅ <b>Bildirişiň bazara çykdy!</b>\n<blockquote>🏪 {title}\n🌍 {ncc} hakyky ýurt · ✅ {work}/{tested} serwer işleýär</blockquote>",
 "m_rejected": "❌ <b>Bildirişiň kabul edilmedi</b>\n<blockquote>🏪 {title}\n{why}</blockquote>",
 "m_removed": "⛔ <b>Bildirişiň {h} sagatlyk bloklandy</b>\n<blockquote>🏪 {title}\n{why}</blockquote>\n<i>Blok wagtynda kodlaryň berilmeýär, pul yzyna gaýtarylmaýar. Blok gutarandan soň bildiriş özi täzeden barlanýar.</i>",
 "r_dead": "4-den köp serwer 30 minutyň dowamynda N/A boldy.",
 "r_lowc": "Hakyky ýurtlaryň sany 30 minutyň dowamynda 4-den az boldy.",
 "r_link": "Podpiska linki 30 minutyň dowamynda açylmady.",
 "rj_lowc": "Azyndan 4 dürli hakyky ýurt ýok (tapylany: {n}).",
 "rj_dead": "{n} serwer işlemeýär (iň köp 4 bolup biler).",
 "rj_link": "Podpiska linki açylmady.",
 "m_paid_sent": "🎉 <b>Gutlaýarys!</b>\n<blockquote>🏪 {title}\n⏱ Alyjy kodyňy {dur} ulandy\n💰 Gazanjyň  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💸 CryptoBot hasabyňa iberildi.",
 "m_paid_bal": "🎉 <b>Gutlaýarys!</b>\n<blockquote>🏪 {title}\n⏱ Alyjy kodyňy {dur} ulandy\n💰 Gazanjyň  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💼 Botdaky balansyňa goşuldy. Profil → 💸 Gazanjy çek.",
 "myl": "📦 <b>Bildirişlerim</b>",
 "myl_none": "📦 <b>Bildirişlerim</b>\n<blockquote>Bildirişiň ýok.</blockquote>",
 "myl_item": "<blockquote>{st} <b>{title}</b>{vip}\n💲 {m} TMT/30 gün · 👥 {n} alyjy · 💰 {earned} USDT{extra}</blockquote>",
 "st_pending": "⏳",
 "st_live": "🟢",
 "st_removed": "⛔",
 "st_rejected": "❌",
 "rules": "📜 <b>Bazaryň düzgünleri</b>\n\n🏪 <b><u>SATYJY</u></b>\n<blockquote>• Her bildiriş 0.05$ (yzyna gaýtarylmaýar).\n• Podpiska limitsiz bolmaly; skrinşot hökman.\n• Bildiriş berlende azyndan 4 dürli hakyky ýurt bolmaly (bot özi ölçeýär, baýdaklara seredilmeýär).\n• 💎 VIP: 0.2$ töläp, 36 sagat iň ýokarda durýar.\n• Gazanç: alyjy kody yzyna gowşuranda, uzak ulanylsa her 24 sagatda bir gezek iberilýär.\n• 🔒 Kodlaryňyz diňe satyn alan adamyň faýlyna ýazylýar, yzyna gowşurylanda pozulýar. Her ulanylyşy Bildirişlerim → 📜 Ulanyş taryhy bölüminde görünýär.</blockquote>\n\n🛒 <b><u>ALYJY</u></b>\n<blockquote>• Her gezek başlamak 0.05$ + ilkinji 5 sagat öňünden (yzyna gaýtarylmaýar).\n• Bir bildiriş 24 sagatda iň köp 3 gezek başladylýar.\n• Minutlyk töleg balansyňdan aýrylýar (ulansaň-da, ulanmasaň-da).\n• Islän wagtyň yzyna gowşurup bilersiň; balans gutarsa, kod özi yzyna gowşurylýar.\n• Balans azyndan 1$ doldurylýar; doldurylan balansy yzyna çekip bolmaýar.</blockquote>",
 "bal_line": "\n\n💰 <b>Balans</b> {bal} USDT ≈ {tmt} TMT",
 "earn_line": "\n💼 <b>Çekip boljak gazanç</b>  {earn} USDT",
 "top": "➕ <b>Balansy doldur</b>\n<blockquote>CryptoBot arkaly USDT. Azyndan 1 USDT.\n💰 Balansyň  <b>{bal} USDT</b></blockquote>",
 "top_ask": "✏️ Näçe USDT doldurmak isleýärsiň? (azyndan 0.1)",
 "top_bad": "⚠️ Azyndan 0.1 USDT, san ýaz (mysal: 2.5).",
 "top_order": "🧾 <b>Balansy doldurmak · #{oid}</b>\n<blockquote>💵 <b>{usdt} USDT</b></blockquote>\n«💵 USDT bilen töle» düwmesine bas.",
 "it_top": "Balansy doldurmak · {usdt} USDT",
 "top_ok": "✅ <b>Balansyňa {usdt} USDT goşuldy.</b>\n<blockquote>💰 Balans  <b>{bal} USDT</b></blockquote>",
 "wd_min": "ℹ️ Çekmek üçin azyndan {min} USDT gazanç gerek. Häzir: {earn} USDT.",
 "wd_ok": "✅ <b>{usdt} USDT</b> CryptoBot hasabyňa iberildi.",
 "wd_err": "⚠️ Iberip bolmady: {err}\n<i>@CryptoBot-y azyndan bir gezek açan bolmaly. Düzelmese 🆘 Goldaw-a ýaz.</i>",
 "b_pazar": "🏪 Bazar",
 "b_live": "📊 Göni",
 "b_vip": "💎 VIP · 36 sag. · 0.2$",
 "b_yes_stop": "✅ Hawa",
 "b_no": "✖️ Ýok",
 "mkt_head": "🏪 <b>Bazar</b> 👇",
 "mkt_foot": "🏪 <b>Bazar</b>\n<blockquote>💰 Balansyň  <b>{bal} USDT</b>\nBaşlanyňda 0.05$, soň her minut üçin tölärsiň; islän wagtyň yzyna gowşuryp bilersiň.</blockquote>",
 "card": "🏪 <b>{title}</b>\n{own}\n📡 <b>Serwerler</b>\n<blockquote>🖥 {total} serwer · {protos}\n{tmline}{ccline}</blockquote>\n\n💰 <b>Bahasy</b>\n<blockquote>{prices}</blockquote>\n\n{payline}{desc}",
 "card_own": "<blockquote>🛡 7/24 gözegçilik astynda\n🇹🇲 Türkmenistandan yzygiderli barlanýar\n⚡ IP üýtgände özi täzelenýär\n🧹 Işlemeýän serwer awtomatik aýrylýar</blockquote>\n",
 "vip_badge": "  💎 VIP",
 "stop_q": "⏹ <b>Yzyna gowşurulsynmy?</b>\n<blockquote>🏪 {title}\n⏱ {dur} · 💸 {usdt} USDT</blockquote>",
 "live": "📊 <b>Göni</b> · {title}\n<blockquote>⏱ Wagt  {dur}\n💸 Harçlanan  <b>{spent}$</b>\n💰 Balans  <b>{bal}$</b>\n⏳ Galan  ≈ {left}\n💲 {m_tmt} TMT / 30 gün</blockquote>\n<i>⟳ Her 10 sekuntda täzelenýär · {t}</i>",
 "live_off": "📊 <b>{title}</b>\n<blockquote>Bu kod yzyna gowşuruldy.</blockquote>",
 "vip_ok": "💎 <b>Bildirişiň VIP boldy!</b>\n<blockquote>🏪 {title}\n⏳ {left} dowamynda bazaryň iň ýokarsynda.</blockquote>",
 "vip_nobal": "⚠️ VIP üçin balansyň ýetmeýär (0.2$).",
 "vip_notlive": "⚠️ Diňe bazarda görünýän bildiriş VIP bolup biler.",
 "m_rereview": "🔄 Blok gutardy: «{title}» bildirişiň täzeden barlanýar. Hemme zat dogry bolsa, birnäçe minutdan ýene bazarda çykar.",
 "rj_untested": "Telefon testi bu kodlary ölçäp bilmedi (protokol goldanmaýan bolmagy mümkin).",
 "myl_pend": "\n⏳ Teste iberildi {ago} · test {a}/{b}",
 "myl_susp": "\n⛔ Blok gutarýança: {left}",
 "st_suspended": "⛔",
 "tm_ok": "🇹🇲 TM testi: ✅ <b>{work}</b> işleýär · ❌ {dead}\n🕒 Soňky test: {ago}",
 "tm_wait": "🇹🇲 TM testi: ⏳ täze serwerler barlanýar",
 "cc_line": "\n🌍 {n} ýurt  {flags}",
 "chk_wait": "⏳ 5 minutda bir gezek barlap bolýar. {m} min soň täzeden synanyş.",
 "chk_head": "🔍 <b>{title}</b> · serwerleriň ýagdaýy\n<blockquote>{lines}</blockquote>\n✅ {work} işleýär · ❌ {dead} işlemeýär · ⏳ {wait} garaşýar\n🎯 ýurt dogry · ⚠️ ýurt nädogry (hakykysy ýanynda)\n🕒 Soňky TM testi: {ago}",
 "chk_req": "\n\n📱 <i>Türkmenistandan täze test başlady. Netijesi gelende (1–5 min) saňa iberiler.</i>",
 "chk_busy": "\n\n📱 <i>Türkmenistandan test eýýäm gidip dur. Netijesi gelende saňa iberiler.</i>",
 "chk_done": "🆕 <b>Täze TM test netijesi</b>\n\n",
 "chk_timeout": "\n⚠️ <i>Telefon testi häzir jogap bermeýär; ýokarda soňky belli ýagdaý.</i>",
 "never": "entek ýok",
 "b_cap_buy": "🛒 VPN almak isleýärin",
 "b_cap_sell": "🏪 Men VPN satyjy",
 "card_seller": "{head}\n\n🏪 <b>{title}</b>\n\n💰 <b>Bahasy</b>\n<blockquote>{prices}</blockquote>\n\n<i>🔍 Serwerleri we ýurtlary görmek üçin «Barla» düwmä bas.</i>",
 "head_vip": "💎 <b>VIP serwer</b>",
 "head_std": "🏷 <b>Standart serwer</b>",
 "prices": "⏱ 1 minut  —  <b>{mi} TMT</b>\n🕐 1 sagat  —  <b>{h} TMT</b>\n📅 1 hepde  —  <b>{w} TMT</b>\n🗓 1 aý  —  <b>{m} TMT</b>",
 "payline": "💡 <b>Pul doly alynmaýar</b> — töleg diňe ulanan minudyňyza / sagadyňyza görä alynýar.\n▶️ Kody açanyňyzda bir gezek 0.05$. Islän wagtyňyz kody yzyna gowşuryp bilersiňiz — galan puluňyz balansyňyzda galýar (diňe ulanylan wagtyň puly alynýar).",
 "mkt_bal": "\n\n💰 Balansyň  <b>{bal} USDT</b>",
 "mkt_none": "\n<i>Häzir başga satyjy ýok.</i>",
 "b_sellers": "👥 Satyjylar ({n}) ▶️",
 "chk_line_ok": "🎯",
 "chk_line_bad": "⚠️ hakykatda: {f} {n}",
 "chk_line_real": "→ {f} {n}",
 "chk_run": "\n⏳ <b>Türkmenistanda kodlaryň işläp-işlemeýändigi barlanýar...</b>\n<i>(~1 min) Netije şu ýerde görüner.</i>",
 "chk_upd": "\n✅ <i>Täzelendi · {t}</i>",
 "b_recheck": "🔄 Täzele",
 "head_own": "🏆 <b>BOTUŇ RESMI KODY</b> 🏆",
 "card2": "{head}\n\n🏪 <b>{title}</b>\n\n💰 <b>Bahasy</b>\n<blockquote>{prices}</blockquote>\n\n<i>🔍 Serwerleri we ýurtlary görmek üçin «Barla» bas.</i>",
 "chk_head2": "\n🔍 <b>Serwerler</b>\n<blockquote>{lines}</blockquote>\n✅ {work} işleýär · ❌ {dead} işlemeýär · ⏳ {wait} garaşýar\n🎯 ýurt dogry · ⚠️ ýurt nädogry\n🕒 Soňky TM testi: {ago}",
 "b_mcheck": "🔍 Barla"
}

# 📜 İlan kullanım geçmişi (satıcı, kodlarının sadece satın alanlarca kullanıldığını kendi panelinden karşılaştırabilsin)
T["tr"].update({"b_mlh": "📜 Kullanım geçmişi · {t}", "mlh_none": "Henüz kimse kullanmadı.", "mlh_now": "şu an açık",
    "mlh": "📜 <b>Kullanım geçmişi</b> · {title}\n<blockquote>{lines}</blockquote>\n<i>🔒 Kodların sadece bu saatlerde, satın alan kişinin dosyasına yazıldı; durdurulunca dosya boşaltılır. Botun kendi kodlarına ya da başka bir dosyaya eklenmez.\n🔎 Sağlayıcının panelindeki bağlantı/trafik saatlerini bu listeyle karşılaştırabilirsin; liste dışında kullanım görürsen Support'a yaz.\nNot: bot kodlarını ~10 dakikada bir Türkmenistan'dan birkaç saniye test eder (çok az trafik).</i>"})
T["tk"].update({"b_mlh": "📜 Ulanyş taryhy · {t}", "mlh_none": "Entek hiç kim ulanmady.", "mlh_now": "häzir açyk",
    "mlh": "📜 <b>Ulanyş taryhy</b> · {title}\n<blockquote>{lines}</blockquote>\n<i>🔒 Kodlaryňyz diňe şu wagtlarda, satyn alan adamyň faýlyna ýazyldy; yzyna gowşurylanda faýl boşadylýar. Botuň öz kodlaryna ýa-da başga faýla goşulmaýar.\n🔎 Üpjün edijiňiziň panelindäki birikme/trafik wagtlaryny şu sanaw bilen deňeşdirip bilersiňiz; sanawdan daşary ulanyş görseňiz Support-a ýazyň.\nBellik: bot kodlaryňyzy ~10 minutda bir gezek Türkmenistandan birnäçe sekunt test edýär (örän az trafik).</i>"})
T["ru"].update({"b_mlh": "📜 История · {t}", "mlh_none": "Пока никто не пользовался.", "mlh_now": "сейчас открыт",
    "mlh": "📜 <b>История использования</b> · {title}\n<blockquote>{lines}</blockquote>\n<i>🔒 Ваши коды записывались только в эти часы и только в файл купившего; после остановки файл очищается. В собственные коды бота и другие файлы они не попадают.\n🔎 Сравните со временем подключений/трафика в панели вашего провайдера; если видите использование вне этого списка — напишите в поддержку.\nПримечание: бот примерно раз в 10 минут на несколько секунд проверяет коды из Туркменистана (очень мало трафика).</i>"})

# 🎨 Kendi reklamım (profil)
T["tr"].update({"b_myad": "🎨 Kendi reklamımı hazırla",
    "myad_wait": "🎨 <b>Reklamın hazırlanıyor...</b>\n▱▱▱▱▱ 0%|🎨 <b>Reklamın hazırlanıyor...</b>\n▰▰▱▱▱ 40%\n<i>Davet linkin ekleniyor</i>|🎨 <b>Reklamın hazırlanıyor...</b>\n▰▰▰▰▱ 80%\n<i>Banner ve yazı birleştiriliyor</i>|✅ <b>Hazır!</b>\n▰▰▰▰▰ 100%",
    "myad_done": "✅ <b>Reklamın hazır!</b>\n<blockquote>Yukarıdaki reklam <b>senin davet linkinle</b> oluşturuldu — rahatça kullan. İstediğin kanala ya da gruba ilet.\n\n💡 Ya da reklam yapacağın yerde yazı kutusuna <code>@{un}</code> yaz — reklamın kendiliğinden çıkar.\n\n🔗 Davet linkin: {link}</blockquote>"})
T["tk"].update({"b_myad": "🎨 Öz reklamamy taýýarla",
    "myad_wait": "🎨 <b>Reklamaňyz taýýarlanýar...</b>\n▱▱▱▱▱ 0%|🎨 <b>Reklamaňyz taýýarlanýar...</b>\n▰▰▱▱▱ 40%\n<i>Çagyryş linkiňiz goşulýar</i>|🎨 <b>Reklamaňyz taýýarlanýar...</b>\n▰▰▰▰▱ 80%\n<i>Banner we tekst birleşdirilýär</i>|✅ <b>Taýýar!</b>\n▰▰▰▰▰ 100%",
    "myad_done": "✅ <b>Reklamaňyz taýýar!</b>\n<blockquote>Ýokardaky reklama <b>siziň çagyryş linkiňiz bilen</b> döredildi — rahat ulanyň. Islän kanalyňyza ýa-da toparyňyza iberiň.\n\n💡 Ýa-da reklama berjek ýeriňizde ýazuw meýdançasyna <code>@{un}</code> ýazyň — reklamaňyz özi çykar.\n\n🔗 Çagyryş linkiňiz: {link}</blockquote>"})
T["ru"].update({"b_myad": "🎨 Создать свою рекламу",
    "myad_wait": "🎨 <b>Ваша реклама создаётся...</b>\n▱▱▱▱▱ 0%|🎨 <b>Ваша реклама создаётся...</b>\n▰▰▱▱▱ 40%\n<i>Добавляем вашу реферальную ссылку</i>|🎨 <b>Ваша реклама создаётся...</b>\n▰▰▰▰▱ 80%\n<i>Собираем баннер и текст</i>|✅ <b>Готово!</b>\n▰▰▰▰▰ 100%",
    "myad_done": "✅ <b>Ваша реклама готова!</b>\n<blockquote>Реклама выше создана <b>с вашей реферальной ссылкой</b> — используйте смело. Перешлите в любой канал или группу.\n\n💡 Или там, где даёте рекламу, напишите в поле ввода <code>@{un}</code> — ваша реклама появится сама.\n\n🔗 Ваша ссылка: {link}</blockquote>"})

# günlük başlatma sınırı (aynı ilan)
T["tr"]["wd_nofund"] = "⏳ <b>Çekim şu an yapılamadı.</b>\n<blockquote>Ödeme hesabında geçici olarak yeterli para yok. <b>{usdt} USDT</b> kazancın yerinde duruyor, kaybolmadı.\nAdmine bildirildi — biraz sonra tekrar dene.</blockquote>"
T["tk"]["wd_nofund"] = "⏳ <b>Häzir çekip bolmady.</b>\n<blockquote>Töleg hasabynda wagtlaýyn ýeterlik pul ýok. <b>{usdt} USDT</b> gazanjyňyz ýerinde dur, ýitmedi.\nAdmine habar berildi — birazdan gaýtadan synanyşyň.</blockquote>"
T["ru"]["wd_nofund"] = "⏳ <b>Вывод сейчас невозможен.</b>\n<blockquote>На платёжном счёте временно недостаточно средств. Ваши <b>{usdt} USDT</b> на месте.\nАдмин уведомлён — попробуйте чуть позже.</blockquote>"
T["tr"].update({"b_pbon": "🎁 Bonustan öde ({tmt} TMT)",
  "pbon_need": "⚠️ <b>Bonus yetersiz</b>\n<blockquote>Gerekli  <b>{need} TMT</b>\n🎁 Bonusun  <b>{b} TMT</b></blockquote>\n<i>👥 Çağırdığın her dost için 0.25 TMT bonus alırsın.</i>"})
T["tk"].update({"b_pbon": "🎁 Bonusdan töle ({tmt} TMT)",
  "pbon_need": "⚠️ <b>Bonus ýeterlik däl</b>\n<blockquote>Gerek  <b>{need} TMT</b>\n🎁 Bonusyňyz  <b>{b} TMT</b></blockquote>\n<i>👥 Çagyran her dostuňyz üçin 0.25 TMT bonus alýarsyňyz.</i>"})
T["ru"].update({"b_pbon": "🎁 Оплатить бонусом ({tmt} TMT)",
  "pbon_need": "⚠️ <b>Недостаточно бонусов</b>\n<blockquote>Нужно  <b>{need} TMT</b>\n🎁 Бонус  <b>{b} TMT</b></blockquote>\n<i>👥 За каждого приглашённого друга — 0.25 TMT бонуса.</i>"})
T["tr"].update({"b_pbal": "💰 Bakiyeden öde ({usdt} USDT)",
  "pbal_need": "⚠️ <b>Bakiye yetersiz</b>\n<blockquote>Gerekli  <b>{need} USDT</b>\n💰 Bakiyen  <b>{bal} USDT</b></blockquote>",
  "pbal_fail": "⚠️ Şu an teslim edilemedi. Paran bakiyene geri yüklendi, admine bildirildi."})
T["tk"].update({"b_pbal": "💰 Balansdan töle ({usdt} USDT)",
  "pbal_need": "⚠️ <b>Balans ýeterlik däl</b>\n<blockquote>Gerek  <b>{need} USDT</b>\n💰 Balansyňyz  <b>{bal} USDT</b></blockquote>",
  "pbal_fail": "⚠️ Häzir berip bolmady. Puluňyz balansyňyza gaýtaryldy, admine habar berildi."})
T["ru"].update({"b_pbal": "💰 Оплатить с баланса ({usdt} USDT)",
  "pbal_need": "⚠️ <b>Недостаточно средств</b>\n<blockquote>Нужно  <b>{need} USDT</b>\n💰 Баланс  <b>{bal} USDT</b></blockquote>",
  "pbal_fail": "⚠️ Сейчас выдать не удалось. Деньги возвращены на баланс, админ уведомлён."})
T["tr"].update({"bonus_line": "\n🎁 <b>Bonus</b>  {b} TMT\n<i>👥 Çağırdığın her dost için 0.25 TMT bonus alırsın.</i>",
  "ref_bonus": "🎁 +0.25 TMT bonus hesabına eklendi."})
T["tk"].update({"bonus_line": "\n🎁 <b>Bonus</b>  {b} TMT\n<i>👥 Çagyran her dostuňyz üçin 0.25 TMT bonus alýarsyňyz.</i>",
  "ref_bonus": "🎁 +0.25 TMT bonus hasabyňyza goşuldy."})
T["ru"].update({"bonus_line": "\n🎁 <b>Бонус</b>  {b} TMT\n<i>👥 За каждого приглашённого друга — 0.25 TMT бонуса.</i>",
  "ref_bonus": "🎁 +0.25 TMT зачислено на бонусный счёт."})
T["tr"].update({"vip_q": "💎 <b>İlan VIP yapılsın mı?</b>\n<blockquote>🏪 {title}\n⏳ {h} saat pazarın en üstünde\n💵 Ücret  <b>{fee} USDT</b> (iade edilmez)\n💰 Bakiyen  <b>{bal} USDT</b></blockquote>",
  "b_yes_vip": "✅ Evet, VIP yap", "mld_q": "🗑 <b>İlan silinsin mi?</b>\n<blockquote>🏪 {title}\n👥 Şu an kullanan  <b>{n}</b>\nİlan pazardan kalkar, geri alınamaz.</blockquote>", "b_yes_mld": "🗑 Evet, sil"})
T["tk"].update({"vip_q": "💎 <b>Bildiriş VIP edilsinmi?</b>\n<blockquote>🏪 {title}\n⏳ {h} sagat bazaryň iň ýokarsynda\n💵 Tölegi  <b>{fee} USDT</b> (yzyna gaýtarylmaýar)\n💰 Balansyňyz  <b>{bal} USDT</b></blockquote>",
  "b_yes_vip": "✅ Hawa, VIP et", "mld_q": "🗑 <b>Bildiriş pozulsynmy?</b>\n<blockquote>🏪 {title}\n👥 Häzir ulanýan  <b>{n}</b>\nBildiriş bazardan aýrylýar, yzyna gaýtaryp bolmaýar.</blockquote>", "b_yes_mld": "🗑 Hawa, poz"})
T["ru"].update({"vip_q": "💎 <b>Сделать объявление VIP?</b>\n<blockquote>🏪 {title}\n⏳ {h} ч на самом верху биржи\n💵 Стоимость  <b>{fee} USDT</b> (не возвращается)\n💰 Баланс  <b>{bal} USDT</b></blockquote>",
  "b_yes_vip": "✅ Да, сделать VIP", "mld_q": "🗑 <b>Удалить объявление?</b>\n<blockquote>🏪 {title}\n👥 Сейчас пользуются  <b>{n}</b>\nОбъявление уйдёт с биржи, отменить нельзя.</blockquote>", "b_yes_mld": "🗑 Да, удалить"})
T["tr"]["m_own"] = "⚠️ <b>Kendi ilanını satın alamazsın.</b>"
T["tk"]["m_own"] = "⚠️ <b>Öz bildirişiňizi satyn alyp bilmeýärsiňiz.</b>"
T["ru"]["m_own"] = "⚠️ <b>Нельзя купить своё собственное объявление.</b>"
T["tr"]["m_limit"] = "⚠️ <b>Bu ilanı bugün {n} kez başlattın.</b>\n<blockquote>Aynı ilan 24 saatte en fazla {n} kez başlatılabilir. Diğer ilanları kullanabilirsin.</blockquote>"
T["tk"]["m_limit"] = "⚠️ <b>Bu bildirişi şu gün {n} gezek başlatdyňyz.</b>\n<blockquote>Bir bildiriş 24 sagatda iň köp {n} gezek başladylyp bilner. Beýleki bildirişleri ulanyp bilersiňiz.</blockquote>"
T["ru"]["m_limit"] = "⚠️ <b>Вы уже запускали это объявление {n} раза за сутки.</b>\n<blockquote>Одно объявление можно запускать не больше {n} раз за 24 часа. Другие объявления доступны.</blockquote>"

# 🤥 Yalan ping reddi
T["tr"].update({"fake_rej": "🤥 <b>İlanın reddedildi: yalan ping görüntüsü</b>\n<blockquote>🏷 {title}\nGönderdiğin ekran görüntüsündeki ping'ler gerçek değil (TCP ping). Happ'te <b>Proxy GET</b> ile ping ölçüp yeniden gönder.</blockquote>\n📊 <b>İşte kodunun gerçek ping'leri ve gerçek ülkeleri:</b>",
    "fake_warn": "⚠️ <i>Bu tekrarlanırsa bir sonraki ilanın için 2 kat ücret alınır.</i>",
    "fake_x2": "⚠️ <b>Bu ikinci kez oldu: bir sonraki ilanın {fee}$ (2 kat) olacak.</b> Ödedikten sonra ücret yine normale döner.",
    "fee_x2_note": "\n⚠️ <b>Yalan ping cezası:</b> bu ilan 2 kat ücretli."})
T["tk"].update({"fake_rej": "🤥 <b>Bildirişiňiz ret edildi: ýalan ping suraty</b>\n<blockquote>🏷 {title}\nUgradan suratyňyzdaky pingler hakyky däl (TCP ping). Happ-da <b>Proxy GET</b> bilen ping barlap, täzeden ugradyň.</blockquote>\n📊 <b>Ine siziň çyn pingleriňiz we kodyňyzyň berýän çyn ýurtlary:</b>",
    "fake_warn": "⚠️ <i>Bu gaýtalansa, indiki bildirişiňiz üçin töleg 2 esse alnar.</i>",
    "fake_x2": "⚠️ <b>Bu ikinji gezek boldy: indiki bildirişiňiz {fee}$ (2 esse) bolar.</b> Töländen soň töleg ýene adaty bolar.",
    "fee_x2_note": "\n⚠️ <b>Ýalan ping jerimesi:</b> bu bildiriş 2 esse tölegli."})
T["ru"].update({"fake_rej": "🤥 <b>Объявление отклонено: фальшивый пинг на скриншоте</b>\n<blockquote>🏷 {title}\nПинги на вашем скриншоте ненастоящие (TCP ping). Проверьте пинг в Happ через <b>Proxy GET</b> и отправьте заново.</blockquote>\n📊 <b>Вот реальные пинги и реальные страны вашего кода:</b>",
    "fake_warn": "⚠️ <i>Если это повторится, за следующее объявление будет взята двойная плата.</i>",
    "fake_x2": "⚠️ <b>Это уже второй раз: следующее объявление будет стоить {fee}$ (в 2 раза больше).</b> После оплаты цена снова обычная.",
    "fee_x2_note": "\n⚠️ <b>Штраф за фальшивый пинг:</b> это объявление в 2 раза дороже."})

# Destek / Bug: ✍️ Yaz butonu + 60 sn sınırı
T["tr"].update({"b_twrite": "✍️ Yaz", "sup_ask": "✍️ <b>Mesajını gönder</b>\n<blockquote>Yazı, fotoğraf ya da video — fark etmez.</blockquote>",
  "sup_rate": "<i>⏱ 60 saniyede tek mesaj gönderebilirsin — hepsini tek mesajda yaz.</i>",
  "sup_slow": "⏳ 60 saniyede tek mesaj gönderebilirsin. {s} sn sonra tekrar dene — hepsini tek mesajda yaz."})
T["tk"].update({"b_twrite": "✍️ Ýaz", "sup_ask": "✍️ <b>Habaryňy iber</b>\n<blockquote>Tekst, surat ýa-da wideo — tapawudy ýok.</blockquote>",
  "sup_rate": "<i>⏱ 60 sekuntda diňe 1 habar iberip bilersiňiz — hemmesini bir habarda ýazyň.</i>",
  "sup_slow": "⏳ 60 sekuntda diňe 1 habar iberip bilersiňiz. {s} sek soň gaýtadan synanyşyň — hemmesini bir habarda ýazyň."})
T["ru"].update({"b_twrite": "✍️ Написать", "sup_ask": "✍️ <b>Отправьте сообщение</b>\n<blockquote>Текст, фото или видео — неважно.</blockquote>",
  "sup_rate": "<i>⏱ Можно отправить 1 сообщение в 60 секунд — пишите всё одним сообщением.</i>",
  "sup_slow": "⏳ Можно отправить 1 сообщение в 60 секунд. Попробуйте через {s} сек — пишите всё одним сообщением."})

# Sınırlı abonelik uyarısı (satış)
T["tr"]["sell_limited"] = "⚠️ <b>Bu abonelik sınırlı</b>\n<blockquote>{lim}\nPazara sadece <b>GB ve süre sınırı olmayan</b> abonelik konabilir.</blockquote>"
T["tk"]["sell_limited"] = "⚠️ <b>Bu podpiskanyň çägi bar</b>\n<blockquote>{lim}\nBazara diňe <b>GB we möhlet çägi bolmadyk</b> podpiska goýup bolýar.</blockquote>"
T["ru"]["sell_limited"] = "⚠️ <b>У подписки есть ограничения</b>\n<blockquote>{lim}\nНа биржу можно выставить только подписку <b>без лимита ГБ и срока</b>.</blockquote>"

# Happ şifreli link uyarısı (satış)
T["tr"]["sell_happ"] = "⚠️ <b>Happ şifreli linkleri kabul edilmiyor</b>\n<blockquote>happ://crypt… gibi şifreli ya da kapalı linklerin içindeki kodlar okunamaz.\nAçık abonelik linkini gönder (<code>https://</code> ile başlayan).</blockquote>"
T["tk"]["sell_happ"] = "⚠️ <b>Happ-yň şifrlenen linkleri kabul edilmeýär</b>\n<blockquote>happ://crypt… ýaly şifrlenen ýa-da ýapyk linklerdäki kodlary okap bolanok.\nAçyk podpiska linkini iberiň (<code>https://</code> bilen başlaýan).</blockquote>"
T["ru"]["sell_happ"] = "⚠️ <b>Зашифрованные ссылки Happ не принимаются</b>\n<blockquote>Коды внутри зашифрованных или закрытых ссылок (happ://crypt…) прочитать нельзя.\nОтправьте открытую ссылку подписки (начинается с <code>https://</code>).</blockquote>"

# 🛒 Satın Al onayı
T["tr"].update({"b_msy": "✅ Evet, satın al", "b_msn": "✖️ Vazgeç",
    "ms_q": "🛒 <b>Satın almak istediğine emin misin?</b>\n<blockquote>🏪 {title}\n💵 Başlatma ücreti  <b>{fee}$</b> (iade edilmez)\n⏳ İlk 5 saat peşin  <b>{ph} TMT</b> (iade edilmez)\n⏱ Sonra her dakika  <b>{pm} TMT</b> bakiyenden düşer\n💰 Bakiyen  <b>{bal} USDT</b></blockquote>\n<i>İstediğin an durdurabilirsin.</i>"})
T["tk"].update({"b_msy": "✅ Hawa, satyn al", "b_msn": "✖️ Ýatyr",
    "ms_q": "🛒 <b>Hakykatdan hem satyn almak isleýärsiňizmi?</b>\n<blockquote>🏪 {title}\n💵 Başlamak tölegi  <b>{fee}$</b> (yzyna gaýtarylmaýar)\n⏳ Ilkinji 5 sagat öňünden  <b>{ph} TMT</b> (yzyna gaýtarylmaýar)\n⏱ Soňra her minutda  <b>{pm} TMT</b> balansyňyzdan aýrylýar\n💰 Balansyňyz  <b>{bal} USDT</b></blockquote>\n<i>Islän wagtyňyz kody yzyna gowşuryp bilersiňiz.</i>"})
T["ru"].update({"b_msy": "✅ Да, купить", "b_msn": "✖️ Отмена",
    "ms_q": "🛒 <b>Вы уверены, что хотите купить?</b>\n<blockquote>🏪 {title}\n💵 Плата за запуск  <b>{fee}$</b> (не возвращается)\n⏳ Первые 5 часов сразу  <b>{ph} TMT</b> (не возвращается)\n⏱ Затем каждую минуту  <b>{pm} TMT</b> списывается с баланса\n💰 Баланс  <b>{bal} USDT</b></blockquote>\n<i>Остановить можно в любой момент.</i>"})

# ⚙️ Ayarlar ekranı (dil seçimi burada)
T["tr"].update({"b_set": "⚙️ Ayarlar", "set_t": "⚙️ <b>Ayarlar</b>\n<blockquote>🌐 Dil  <b>{lname}</b>\n🆔 ID  <code>{id}</code></blockquote>\n<i>Dili değiştirmek için aşağıdan seç.</i>"})
T["tk"].update({"b_set": "⚙️ Sazlamalar", "set_t": "⚙️ <b>Sazlamalar</b>\n<blockquote>🌐 Dil  <b>{lname}</b>\n🆔 ID  <code>{id}</code></blockquote>\n<i>Dili üýtgetmek üçin aşakdan saýlaň.</i>"})
T["ru"].update({"b_set": "⚙️ Настройки", "set_t": "⚙️ <b>Настройки</b>\n<blockquote>🌐 Язык  <b>{lname}</b>\n🆔 ID  <code>{id}</code></blockquote>\n<i>Выберите язык ниже.</i>"})

def money_tmt(micro, d=2):
    v = micro * USDT_RATE / UM
    return f"{v:.{d}f}".rstrip("0").rstrip(".") or "0"

def card_head(L, lang):
    return tr(lang, "head_own" if L.get("own") else "head_vip" if L.get("vip_until", 0) > time.time() else "head_std")

def card_caption(db, L, lang):
    """Pazar kartı: sadece tür başlığı + ad + fiyat. Sunucular «Kontrol Et» ile aynı kutuda açılır."""
    p = float(L["price"])
    prices = tr(lang, "prices", mi=money_tmt(p, 4), h=money_tmt(p * 60), w=money_tmt(p * 10080), m=money_tmt(p * 43200))
    return tr(lang, "card2", head=card_head(L, lang), title=esc(short(L["title"], 40)), prices=prices, payline=tr(lang, "payline"))

CHK = {"user": {}, "req": 0, "wait": {}, "qid": 0, "poll": None}
CHK_EXEC = ThreadPoolExecutor(2, thread_name_prefix="chk")   # kontrol okumaları diğer işlerin (Drive yazımı vb.) arkasında beklemesin

async def chk_run(fn, *a):
    return await asyncio.get_running_loop().run_in_executor(CHK_EXEC, fn, *a)   # kullanıcı başına son kontrol, telefona son test isteği, sonucu bekleyenler
CHK_EVERY = 300

def code_label(c):
    if c.lower().startswith("vmess://"):
        try: return json.loads(b64d(c[8:].split("#", 1)[0])).get("ps") or "vmess"
        except Exception: return "vmess"
    return urllib.parse.unquote(c.split("#", 1)[1]) if "#" in c else (code_host(c) or "?")

PHOTO_BAN_H = 6   # uygunsuz fotoğraf: bot engeli (saat)

def photo_kb(lid, lg="tr", extra=()):
    return KB([[B(at(lg, "p_ok"), f"mk_pok:{lid}", "success")], [B(at(lg, "p_rej"), f"mk_prj:{lid}"), B(at(lg, "p_no"), f"mk_pno:{lid}", "danger")],
               [B(at(lg, "p_real"), f"mk_real:{lid}", "primary"), B(at(lg, "p_fake"), f"mk_fake:{lid}", "danger")]] + [list(r) for r in extra])

def seller_fee(e):
    """İlan ücreti: yalan ping cezası varsa bir sonraki ilan 2 kat."""
    return MKT_FEE * (2 if e.get("fee_x2") else 1)

async def real_report(lid, lang="tr"):
    """Telefonun ölçtüğü gerçek ping / gerçek ülke (Proxy GET ile, satıcının ekran görüntüsünden bağımsız)."""
    db = load_db()
    try: ch = await asyncio.to_thread(_read_channel, db)
    except Exception: ch = CHK.get("last_ch") or {}
    return check_text(db, lid, lang, ch or {}, "done")
CHK_FRESH = 300   # son TM testi bundan yeniyse yeniden test istenmez, sonuç hemen gösterilir
CHK_WAIT = 600    # telefon bu kadar sürede sonuç göndermezse son bilinen durum gösterilir
PHONE_OFF = 1800  # telefonun son sonucu bundan eskiyse telefon kapalı sayılır (test istenmez)

def check_text(db, lid, lang, ch=None, state="done", el=0):
    """Kontrol Et kutusu. state: run (test sürüyor) / done (yeni sonuç) / fresh (son test zaten yeni) / timeout."""
    L = db.get("market", {}).get(lid)
    if not L: return tr(lang, "m_gone")
    top = card_head(L, lang) + f"\n\n🏪 <b>{esc(short(L['title'], 40))}</b>\n"
    if state == "run": return top + tr(lang, "chk_run") + (tr(lang, "chk_old") if RUN.get("phone_old") else "") + (tr(lang, "chk_el", m=el) if el else "")
    if L.get("own"):
        top += tr(lang, "card_own")
        if L.get("desc") and L["desc"] != OWN_DESC: top += "📝 " + esc(short(L["desc"], 200)) + "\n"
    res = (ch or {}).get("results") or {}
    exits = dict(load_exits()); exits.update((ch or {}).get("exits") or {})
    cname = lambda cc: COUNTRIES[cc][1] if cc in COUNTRIES else cc.upper()
    lines, w, dd, wt = [], 0, 0, 0
    for c in listing_codes(db, L):
        k = code_key(c); v = res.get(k); lab = code_label(c)
        if isinstance(v, (int, float)) and v > 0: w += 1; ic = f"✅ {int(v)}ms"
        elif isinstance(v, (int, float)): dd += 1; ic = "❌"
        else: wt += 1; ic = "⏳"
        fm = re.search(r"[\U0001F1E6-\U0001F1FF]{2}", lab)
        said = "".join(chr(ord(x) - 0x1F1E6 + 97) for x in fm.group(0)) if fm else None
        real = (exits.get(k) or "").lower() if isinstance(v, (int, float)) and v > 0 else ""
        real = real if len(real) == 2 and real != "??" else ""
        if said: name = f"{flag_of(said)} {cname(said)}"
        else: name = esc(short(lab, 16))
        if real and said: acc = " " + (tr(lang, "chk_line_ok") if real == said else tr(lang, "chk_line_bad", f=flag_of(real), n=cname(real)))
        elif real: acc = " " + tr(lang, "chk_line_real", f=flag_of(real), n=cname(real))
        else: acc = ""
        lines.append(f"{ic} · {name}{acc}")
    foot = {"done": tr(lang, "chk_upd", t=datetime.datetime.now(TM_TZ).strftime("%H:%M")), "timeout": tr(lang, "chk_timeout"), "off": tr(lang, "chk_off"),
            "refresh": tr(lang, "chk_refresh") + (tr(lang, "chk_el", m=el) if el else "")}.get(state, "")
    for n in (len(lines), 15, 10, 5):   # foto altı yazı en çok 1024 karakter
        more = f"\n… +{len(lines) - n}" if len(lines) > n else ""
        t = top + tr(lang, "chk_head2", lines="\n".join(lines[:n]) + more or "—", work=w, dead=dd, wait=wt, ago=ago_l((ch or {}).get("ts"), lang)) + foot
        if len(t) <= 1024: return t
    return t[:1020]

def chk_kb(lang, lid, refresh=True):
    """Kontrol kutusu butonları. Test sürerken 🔄 Tazele gösterilmez (sonuç gelince çıkar)."""
    top = [B(tr(lang, "b_buy_m"), f"u_ms:{lid}", "success")] + ([B(tr(lang, "b_recheck"), f"u_mck:{lid}:r", "primary")] if refresh else [])
    return KB([top, [B(tr(lang, "b_back"), f"u_ml:{lid}")]])

async def edit_box(bot, uid, mid, is_photo, t, kb):
    """Pazar kutusunu yerinde günceller (fotoğraflıysa altındaki yazı)."""
    try:
        if is_photo: await bot.edit_message_caption(chat_id=uid, message_id=mid, caption=t, parse_mode="HTML", reply_markup=kb)
        else: await bot.edit_message_text(t, chat_id=uid, message_id=mid, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        return True
    except BadRequest as e: return "not modified" in str(e).lower()
    except Exception as e: log.info("box edit: %s", e); return False

def request_phone_test(db, lids):
    with CH_WLOCK: return _request_phone_test(db, lids)

def _request_phone_test(db, lids):
    """Telefona hızlı kontrol isteği: sadece bu ilanların kodları, tekrar denemeden (~30 sn).
    Eski telefon programı hızlı kontrolü bilmiyorsa tam test başlatılır (codes_ts değişir)."""
    ch = _read_channel(db)
    if not ch or not db.get("tm_fid"): return ch, 0
    q0 = ch.get("quick") or {}
    codes = list(q0.get("codes", [])) if q0.get("id") and q0["id"] != ch.get("quick_done") else []   # bitmemiş istek (ör. ilan incelemesi) silinmesin
    seen = {code_key(c) for c in codes}
    for lid in lids:
        L = db.get("market", {}).get(lid)
        for c in (listing_codes(db, L) if L else []):
            if code_key(c) not in seen: seen.add(code_key(c)); codes.append(c)
    qid = int(time.time() * 1000)
    ch["quick"] = {"id": qid, "codes": codes[:120]}
    if not ch.get("quick_ok"): ch["codes_ts"] = int(time.time())
    _tm_write(new_service(), db["tm_fid"], ch)
    return ch, qid

def mkt_order(db):
    """Pazar sırası: bizim ilan, VIP'ler (en yeni VIP önce), sonra diğerleri."""
    ensure_own(db); now = time.time()
    lst = [(lid, L) for lid, L in db["market"].items() if L.get("status") == "live"]
    own = [x for x in lst if x[1].get("own")]
    vip = sorted([x for x in lst if not x[1].get("own") and x[1].get("vip_until", 0) > now], key=lambda x: -x[1]["vip_until"])
    rest = sorted([x for x in lst if not x[1].get("own") and x[1].get("vip_until", 0) <= now], key=lambda x: (-(x[1].get("st") or {}).get("work", 0), x[1]["price"]))
    return [lid for lid, _ in own + vip + rest]

def market_page(db, uid, lang, i=0):
    """Pazarın tek kutusu: i. ilan (fotoğraf + yazı) + gezinme + pazar butonları."""
    order = mkt_order(db); n = len(order)
    i = max(0, min(i, n - 1)); lid = order[i]; L = db["market"][lid]
    e = db["users"].get(str(uid), {})
    cap = card_caption(db, L, lang) + tr(lang, "mkt_bal", bal=fmt_u(e.get("bal", 0))) + (tr(lang, "mkt_none") if n == 1 else "")
    if uid in ADMINS and not L.get("own") and L.get("owner"):   # satıcı bilgisi sadece kuruculara
        o = db["users"].get(str(L["owner"]), {})
        un = f" · @{esc(o['un'])}" if o.get("un") else ""
        cap += f"\n\n👤 <b>Satıcı:</b> <a href=\"tg://user?id={L['owner']}\">{esc(short(o.get('name') or 'Profil', 30))}</a>{un}\n🆔 <code>{L['owner']}</code>"
    rows = [[B(tr(lang, "b_buy_m"), f"u_ms:{lid}", "success"), B(tr(lang, "b_mcheck"), f"u_mck:{lid}", "primary")]]
    if n > 1:
        if i == 0: rows.append([B(tr(lang, "b_sellers", n=n - 1), "u_mp:1")])
        else: rows.append([B("◀️", f"u_mp:{i - 1}"), B(f"{i}/{n - 1}", f"u_mp:{i}"), B("▶️", f"u_mp:{(i + 1) % n}")])
    rows += [[B(tr(lang, "b_sell"), "u_sell", "danger")], [B(tr(lang, "b_myl"), "u_myl")],
             [B(tr(lang, "b_top"), "u_top")],
             [B(tr(lang, "b_rules"), "u_mrules"), B(tr(lang, "b_menu"), "u_menu")]]
    return card_photo(L), cap, KB(rows)

OWN_IMG = "own_default"   # bizim ilanın varsayılan fotoğrafı (dosyanın sonunda gömülü)

def card_photo(L):
    if L.get("own"): return L.get("photo") or OWN_IMG
    return L.get("photo") if L.get("photo_ok", True) else None   # kurucu onaylamadan satıcı fotoğrafı gösterilmez

async def photo_media(photo):
    """Bizim varsayılan foto: Telegram'daki kopyası varsa o, yoksa gömülü dosya."""
    if photo != OWN_IMG: return photo, None
    c_ = load_db().get("own_img_fid") or {}
    if not _OWN_IMG_B64: return (c_["id"], None) if c_.get("id") and c_.get("bot") == BOT_ID else (None, None)
    h = hashlib.sha256(_OWN_IMG_B64.encode()).hexdigest()[:12]
    return (c_["id"], None) if c_.get("h") == h and c_.get("bot") == BOT_ID else (base64.b64decode(_OWN_IMG_B64), h)

def remember_own(m, h):
    if not h: return
    try:
        fid = m.photo[-1].file_id
        mutate(lambda d: d.__setitem__("own_img_fid", {"h": h, "id": fid, "bot": BOT_ID}))
    except Exception: pass

def switch_bot(d):
    """Token başka bota geçtiyse: eski bota ait Telegram fotoğraf kimlikleri yenisinde çalışmaz, temizlenir. Dönüş: (eski_id, silinen) ya da None."""
    old = d.get("bot_id"); d["bot_id"] = BOT_ID
    if not old or old == BOT_ID: return None
    n = 0
    for L in d.get("market", {}).values():
        if L.get("photo"):
            L["photo"] = None; n += 1
            if not L.get("own"): L["photo_ok"] = False
    for k in ("own_img_fid", "banner_fid", "banner_u"): d.pop(k, None)
    return old, n

# ── ana menü banner'ı (dile göre; fotoğraflar dosyanın sonunda gömülü) ──
BOT_ID = os.environ.get("BOT_TOKEN", "").split(":")[0]   # file_id bota özel: token başka bota geçerse yeniden yüklenir

def tg_len(t):
    """Telegram'ın saydığı uzunluk (etiketsiz, UTF-16)."""
    return len(html.unescape(re.sub(r"<[^>]+>", "", t)).encode("utf-16-le")) // 2

async def banner_media(kind, lang):
    """(media, hash): Telegram'daki kopya varsa file_id, yoksa banners.json'daki görsel. Görsel hiç yoksa (None, None)."""
    kb_ = _BANNERS.get(kind) or {}
    b = kb_.get(lang) or kb_.get("tr")
    c_ = (load_db().get("banner_fid") or {}).get(f"{kind}:{lang}") or {}
    if not b: return (c_["id"], None) if c_.get("id") and c_.get("bot") == BOT_ID else (None, None)
    h = hashlib.sha256(b.encode()).hexdigest()[:12]
    return (c_["id"], None) if c_.get("h") == h and c_.get("bot") == BOT_ID else (base64.b64decode(b), h)

def remember_banner(m, key, h):
    try:
        p = m.photo[-1]
        def f(d):
            if h: d.setdefault("banner_fid", {})[key] = {"h": h, "id": p.file_id, "bot": BOT_ID}
            us = d.setdefault("banner_u", [])
            if p.file_unique_id not in us: us.append(p.file_unique_id); del us[:-30]
        mutate(f)
    except Exception: pass

def is_banner(msg):
    ph = getattr(msg, "photo", None)
    return bool(ph) and getattr(ph[-1], "file_unique_id", None) in (load_db().get("banner_u") or [])

BANNER_ACTIONS = {"u_menu", "u_mkt", "u_top", "u_free", "u_prof", "u_mine", "u_sup", "u_bug", "u_market", "u_set", "u_myad"}   # kendi banner'ı olan ekranlar

class QProxy:
    """Banner'lı menüden bir ekrana geçerken foto silinir, yerine yazı mesajı açılır; kodun geri kalanı bu mesajı düzenler."""
    def __init__(s, q, m): s._q, s.message = q, m
    def __getattr__(s, k): return getattr(s._q, k)
    async def edit_message_text(s, *a, **k): return await s.message.edit_text(*a, **k)
    async def edit_message_reply_markup(s, *a, **k): return await s.message.edit_reply_markup(*a, **k)

async def off_banner(c, q):
    msg = getattr(q, "message", None)
    if not is_banner(msg): return q
    try: await msg.delete()
    except Exception: pass
    return QProxy(q, await c.bot.send_message(q.from_user.id, "⏳"))

async def show_home(c, uid, msg=None, pub=False, send=None):
    """Ana menü: dile göre banner + altında menü yazısı (kullanıcı menüsü ya da kurucu/alt admin paneli)."""
    db = load_db()
    t, kb = pub_menu(db, uid) if pub or not is_admin(uid) else home(uid)
    await show_banner(c, uid, msg, "home", t, kb, send)

async def show_banner(c, uid, msg, kind, t, kb, send=None):
    """Ekranı banner fotoğrafıyla gösterir (yazı altında). Yazı foto altına sığmazsa (1024) banner'sız düz mesaj."""
    async def plain(t, kb):
        if send: await send(t, kb)
        else: await c.bot.send_message(uid, html_cut(t), parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    lang = lang_of(load_db(), uid)
    if tg_len(t) > 1024:   # foto altına sığmıyor: banner'sız
        if is_banner(msg):
            try: await msg.delete()
            except Exception: pass
            send = None
        return await plain(t, kb)
    media, h = await banner_media(kind, lang); key = f"{kind}:{lang}"
    if media is None:   # görsel yok (banners.json eksik): düz yazı
        if is_banner(msg):
            try: await msg.delete()
            except Exception: pass
            send = None
        return await plain(t, kb)
    if msg is not None and getattr(msg, "photo", None):
        try:
            m = await c.bot.edit_message_media(chat_id=uid, message_id=msg.message_id, media=InputMediaPhoto(media, caption=t, parse_mode="HTML"), reply_markup=kb)
            remember_banner(m, key, h); return
        except BadRequest as ex:
            if "not modified" in str(ex).lower(): return
            log.info("menu edit: %s", ex)
        except Exception as ex: log.info("menu edit: %s", ex)
    if msg is not None:
        try: await msg.delete()
        except Exception: pass
    try:
        m = await c.bot.send_photo(uid, media, caption=t, parse_mode="HTML", reply_markup=kb); remember_banner(m, key, h)
    except Exception as ex:
        log.warning("banner %s: %s", kind, ex)
        await c.bot.send_message(uid, t, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)

def forget_photo(fid):
    """Bu botun açamadığı Telegram fotoğrafını ilanlardan siler. Dönüş: silindi mi."""
    def f(d):
        n = 0
        for L in d.get("market", {}).values():
            if L.get("photo") == fid:
                L["photo"] = None; n += 1
                if not L.get("own"): L["photo_ok"] = False
        return n
    n = mutate(f)
    if n: vlog(f"📷 Açılamayan ilan fotoğrafı kaldırıldı ({n} ilan) — eski botun fotoğrafı olabilir")
    return bool(n)

async def show_market(c, q, uid, lang, i=0):
    """Pazar tek mesajda: fotoğraflı mesajsa yerinde değişir, değilse eski mesaj silinip yenisi gelir."""
    photo, cap, kb = market_page(load_db(), uid, lang, i)
    msg = getattr(q, "message", None) if q else None
    media, h = await photo_media(photo)
    if media is None: photo = None   # görsel yok: kart fotoğrafsız
    if msg is not None and getattr(msg, "photo", None) and photo:
        try:
            m = await c.bot.edit_message_media(chat_id=uid, message_id=msg.message_id, media=InputMediaPhoto(media, caption=cap, parse_mode="HTML"), reply_markup=kb)
            remember_own(m, h); return
        except BadRequest as ex:
            if "not modified" in str(ex).lower(): return
            log.info("market edit: %s", ex)
        except Exception as ex: log.info("market edit: %s", ex)
    if msg is not None:
        try: await msg.delete()
        except Exception: pass
    try:
        if photo:
            try: m = await c.bot.send_photo(uid, media, caption=cap, parse_mode="HTML", reply_markup=kb); remember_own(m, h); return
            except BadRequest as ex:   # ör. eski botun fotoğrafı: bu bot açamıyor → kayıttan silinir
                log.warning("market foto: %s", ex)
                if photo != OWN_IMG and forget_photo(photo):
                    return await show_market(c, None, uid, lang, i)   # bizim ilan varsayılan fotoğrafla, satıcı ilanı fotoğrafsız
        await c.bot.send_message(uid, cap, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    except Exception as ex: log.warning("market: %s", ex)

def live_view(sid, lang):
    db = load_db(); s = db.get("msess", {}).get(sid)
    if not s: return "—", None
    L = db["market"].get(s["lid"], {}); ru = lang == "ru"
    kb_off = KB([[B(tr(lang, "b_mine"), "u_mine"), B(tr(lang, "b_menu"), "u_menu")]])
    if s.get("status") != "on": return tr(lang, "live_off", title=esc(L.get("title", "?"))), kb_off
    now = time.time(); price = float(L.get("price", 0))
    part = max(0.0, (now - s["last"]) / 60 * price)   # son tam dakikadan bu yana (henüz kesilmemiş; peşin saat içinde 0)
    bal = max(0.0, db["users"].get(str(s["buyer"]), {}).get("bal", 0) - part)
    t = tr(lang, "live", title=esc(L.get("title", "?")), dur=dur_txt(now - s["start"], ru), spent=f"{(s['total'] + part) / UM:.4f}", bal=f"{bal / UM:.4f}",
           left=dur_txt(bal / price * 60, ru) if price else "∞", m_tmt=money2(price * 43200, True), t=datetime.datetime.now(TM_TZ).strftime("%H:%M:%S"))
    return t, KB([[B("🔄", f"u_live:{sid}"), B(tr(lang, "b_stop"), f"u_msq:{sid}", "danger")], [B(tr(lang, "b_mine"), "u_mine")]])

async def live_loop(q, uid, sid, lang):
    """Canlı harcama: 5 dakika boyunca her 10 saniyede günceller."""
    try:
        for _ in range(30):
            await asyncio.sleep(10)
            t, kb = live_view(sid, lang)
            await q.edit_message_text(t, parse_mode="HTML", reply_markup=kb)
            if load_db().get("msess", {}).get(sid, {}).get("status") != "on": break
    except asyncio.CancelledError: pass
    except Exception as e: log.info("live money stopped: %s", e)
    finally:
        if LIVE.get(uid) is asyncio.current_task(): LIVE.pop(uid, None)

def protos_txt(p):
    names = {"hysteria": "Hysteria", "vless": "VLESS", "vmess": "VMess", "trojan": "Trojan", "ss": "SS", "tuic": "TUIC"}
    return " · ".join(f"{names.get(k, k)} {v}" for k, v in sorted(p.items(), key=lambda x: -x[1])) or "—"

# ── her dakika: linkler, telefon sonuçları, kurallar ──
def _read_channel(db):
    if not db.get("tm_fid"): return {}
    try:
        raw = new_service().files().get_media(fileId=db["tm_fid"]).execute(num_retries=2).decode("utf-8", "ignore").strip()
        return json.loads(raw) if raw.startswith("{") else {}
    except Exception as e:
        log.warning("market channel: %s", e); return {}

def market_scan():
    """Bloklayan iş. Satıcı linklerini çeker, telefon sonuçlarıyla istatistik çıkarır, kuralları uygular. Dönüş: olaylar."""
    now = time.time()
    db = load_db()
    lids = [lid for lid, L in db.get("market", {}).items() if not L.get("own") and L.get("status") in ("pending", "live")]
    back = [lid for lid, L in db.get("market", {}).items() if L.get("status") == "suspended" and L.get("until", 0) <= now]
    fetched = {}
    if lids:
        def one(lid):
            try: return lid, fetch_codes(db["market"][lid]["link"]), None
            except Exception as e: return lid, [], str(e)[:80]
        with ThreadPoolExecutor(min(8, len(lids))) as ex:
            for lid, codes, err in ex.map(one, lids): fetched[lid] = (codes, err)
    tcp = {lid: tcp_open_count(c) for lid, (c, err) in fetched.items() if c}
    ch = _read_channel(db)
    res, exits, ts = ch.get("results") or {}, ch.get("exits") or {}, int(ch.get("ts") or 0)
    qd = ch.get("quick_done") or 0
    fresh = bool(ts) and now - ts < TM_FRESH
    events = []
    with db_lock():
        db = load_db(); ensure_own(db)
        m = db["market"]
        for lid, (codes, err) in fetched.items():
            L = m.get(lid)
            if not L or L.get("status") not in ("pending", "live"): continue
            L["last_fetch"] = now
            if err or not codes: L["link_ok"] = False; L.setdefault("linkfail_since", now)
            else:
                L["link_ok"] = True; L.pop("linkfail_since", None); L["tcp"] = tcp.get(lid)
                if [code_key(c) for c in codes] != [code_key(c) for c in L.get("codes", [])]: L["codes"] = codes; L["codes_ts"] = now
            st = listing_stats(db, L, res, exits, ts); L["st"] = st
            if L["status"] == "pending":
                full = fresh and ts > L.get("pushed_ts", 1e18)
                quick = bool(L.get("qid")) and qd >= L["qid"]   # telefon bu ilanın hızlı kontrolünü bitirdi
                after = full or quick
                mark = ts if full else qd
                good = len(st["cc"]) >= MIN_COUNTRIES and st["dead"] <= MAX_DEAD
                if quick and not full and st["tested"] > 0 and not good:   # hızlı test tek deneme: kötü sonuç için tam testi bekle
                    after = False
                if after and st["tested"] > 0:
                    if good:
                        L["status"] = "live"; L["live_ts"] = L["last_good"] = now; events.append(("approved", lid, "", 0))
                    else:
                        L["status"] = "rejected"
                        events.append(("rejected", lid, "rj_lowc" if len(st["cc"]) < MIN_COUNTRIES else "rj_dead", len(st["cc"]) if len(st["cc"]) < MIN_COUNTRIES else st["dead"]))
                elif after and mark != L.get("zero_ts"):   # telefon test etti ama bu ilanın hiçbir kodunu ölçemedi
                    L["zero_ts"] = mark; L["zero_n"] = L.get("zero_n", 0) + 1
                    if L["zero_n"] >= 2: L["status"] = "rejected"; events.append(("rejected", lid, "rj_untested", 0))
                elif now - L.get("pushed_ts", now) > 900 and not L.get("slow_warned"):
                    L["slow_warned"] = True; events.append(("slow", lid, "", 0))
            elif L["status"] == "live":   # yayındaki ilan çalışmayan sunucu yüzünden kaldırılmaz (alıcı istediği an durdurabilir)
                L.pop("dead_since", None)
                if L.get("link_ok"): L["last_good"] = now
        for lid in back:   # yasak bitti: ilan kendiliğinden yeniden incelenir (yeni ücret yok)
            L = m.get(lid)
            if L and L.get("status") == "suspended":
                L["status"] = "pending"; L["codes_ts"] = now; L.pop("zero_n", None); L.pop("slow_warned", None); L.pop("qid", None)
                events.append(("rereview", lid, "", 0))
        own = m[OWN_LID]; own["st"] = listing_stats(db, own, res, exits, ts); own["last_fetch"] = now
        if not own.get("dead_since") and (own["st"]["work"] or not fresh): own["last_good"] = now
        save_db(db)
    return events

def market_push_phone():
    with CH_WLOCK: return _market_push_phone()

def _market_push_phone():
    """Satıcı kodlarını telefon test kanalına ekler (bizim kodlar korunur)."""
    db = load_db()
    mk = market_codes(db); mkeys = [code_key(c) for c in mk]
    if not db.get("tm_fid"): return
    ch = _read_channel(db)
    if not ch: return   # kanal okunamadı: yazma (yoksa bizim kodlar silinirdi)
    old = set(db.get("mkt_pushed", []))
    ours = [c for c in ch.get("codes", []) if code_key(c) not in old]
    seen = {code_key(c) for c in ours}
    new = ours + [c for c in mk if code_key(c) not in seen]
    now = time.time(); write = False
    if sorted(code_key(c) for c in new) != sorted(code_key(c) for c in ch.get("codes", [])):
        ch["codes"], ch["codes_ts"] = new, int(now); write = True
    # incelemedeki yeni ilanlar: telefon tam turu beklemeden sadece bu kodları hemen test etsin (hızlı kontrol)
    need = [lid for lid, L in db.get("market", {}).items() if not L.get("own") and L.get("status") == "pending" and L.get("q_ts", 0) < L.get("codes_ts", L.get("created", 0))]
    qid = 0
    if need:
        q0 = ch.get("quick") or {}
        codes = list(q0.get("codes", [])) if q0.get("id") and q0["id"] != ch.get("quick_done") else []   # bekleyen kontrol isteği silinmesin
        seen = {code_key(c) for c in codes}
        for lid in need:
            for c in db["market"][lid].get("codes", []):
                if code_key(c) not in seen: seen.add(code_key(c)); codes.append(c)
        qid = int(now * 1000); ch["quick"] = {"id": qid, "codes": codes[:120]}; write = True
        if CHK["wait"]: CHK["qid"] = qid   # Kontrol Et bekleyenleri de bu istekle sonuçlanır
    if write: _tm_write(new_service(), db["tm_fid"], ch)
    def f(d):
        d["mkt_pushed"] = sorted(set(mkeys))
        for lid in need:
            L = d.get("market", {}).get(lid)
            if L: L["qid"], L["q_ts"] = qid, now
        for L in d.get("market", {}).values():
            if not L.get("own") and L.get("status") in ("pending", "live") and L.get("pushed_ts", 0) < L.get("codes_ts", L.get("created", 0)):
                L["pushed_ts"] = now
                if L["status"] == "pending": vlog(f"🏪 Pazar: «{L.get('title')}» telefona teste gönderildi ({len(L.get('codes', []))} kod)")
    mutate(f)

def market_bill():
    with db_lock():
        db = load_db(); now = time.time()
        stop, warn, settle = bill(db, now)
        info = []
        for sid, amount, span in settle:
            s = db["msess"][sid]; L = db["market"].get(s["lid"], {})
            if L.get("own"): db["mkt_own_rev"] = db.get("mkt_own_rev", 0) + amount
            else: info.append({"sid": sid, "owner": L.get("owner"), "title": L.get("title"), "payout": amount, "span": span})
        save_db(db)
    return stop, warn, info

# ── 📢 Reklam postu: banner + yazı + 🇹🇲/🇷🇺 butonları (basınca yazı o dile döner) ──
# Satırlar telefonda tek satıra sığacak kadar kısa. uid verilirse son satır + "Bota gir" o kişinin davet linki olur.
AD_TXT = {
 "tk": [
  ("🛡 <b>DRIVE BOT · VPN BAZARY</b> 🌐\n\n"
   "<blockquote>❌ Pul töläp kod alyp bilmediňizmi?\n❌ Alan kodyňyz işlemedimi?\n❌ Baýdak bir ýurt, serwer başga ýurtmy?</blockquote>\n"
   "<b>Drive Bot-da beýle zat ýok ✅</b>\n\n"
   "🛒 <b><u>SATYN ALÝANLAR ÜÇIN</u></b>\n"
   "<blockquote>📡 Serwerler TM-den barlanýar\n🎯 Diňe <b>hakyky ýurtlar</b> görkezilýär\n🔍 Almazdan öň «Barla» bilen görüň\n↩️ Islän wagtyňyz yzyna gowşuryň</blockquote>\n\n"
   "🪪 <b><u>SATÝANLAR ÜÇIN</u></b>\n"
   "<blockquote>💰 Bahany özüňiz goýýarsyňyz\n💸 Pul CryptoBot-a özi gelýär\n🤖 Satyşy bot özi ýöredýär\n📢 Reklama — bary-ýogy <b>0.05$</b></blockquote>\n\n"
   "👇 <i>Başlamak üçin</i>\n{link}")],
 "ru": [
  ("🛡 <b>DRIVE BOT · БИРЖА VPN</b> 🌐\n\n"
   "<blockquote>❌ Заплатили, а код не получили?\n❌ Купленный код не работает?\n❌ Флаг одной страны, а сервер в другой?</blockquote>\n"
   "<b>В Drive Bot такого нет ✅</b>\n\n"
   "🛒 <b><u>ПОКУПАТЕЛЯМ</u></b>\n"
   "<blockquote>📡 Серверы проверяются из ТМ\n🎯 Показываем <b>только реальные страны</b>\n🔍 Проверка перед покупкой\n↩️ Остановить можно в любой момент</blockquote>\n\n"
   "🪪 <b><u>ПРОДАВЦАМ</u></b>\n"
   "<blockquote>💰 Цену ставите сами\n💸 Доход сам приходит в CryptoBot\n🤖 Продажу ведёт бот\n📢 Размещение — всего <b>0.05$</b></blockquote>\n\n"
   "👇 <i>Начать</i>\n{link}")]}

def ad_link(uid=None):
    un = BOT.get("un") or "SuBDrive_bot"
    return f"https://t.me/{un}?start=r{uid}" if uid else f"https://t.me/{un}?start=ad"

def ad_text(lang, uid=None, v=0):
    un = BOT.get("un") or "SuBDrive_bot"
    link = f"🤖 {ad_link(uid)}" if uid else f"🤖 Telegram: @{un}"
    vs = AD_TXT.get(lang, AD_TXT["tk"])
    return vs[v % len(vs)].replace("{link}", link)

def ad_kb(lang, uid=None, v=0):
    sfx = f":{uid or 0}:{v}"
    return KB([[B(("✅ " if lang == "tk" else "") + "🇹🇲 Türkmençe", f"ad:tk{sfx}"), B(("✅ " if lang == "ru" else "") + "🇷🇺 Русский", f"ad:ru{sfx}")],
               [B("🤖 Bota gir" if lang == "tk" else "🤖 Перейти в бот", url=ad_link(uid))]])

async def ad_photo_id(bot):
    """Reklam fotoğrafının bu bottaki file_id'si (yoksa bir kurucuya yükleyip alır)."""
    media, h = await banner_media("ad", "tr")
    if not h or media is None: return media
    for fid in ADMINS:
        try:
            m = await bot.send_photo(fid, media, disable_notification=True)
            remember_banner(m, "ad:tr", h)
            try: await m.delete()
            except Exception: pass
            return m.photo[-1].file_id
        except Exception as e: log.info("ad photo: %s", e)
    return None

async def send_ad(c, chat, lang="tk", uid=None, v=0):
    media, h = await banner_media("ad", "tr")
    if media is None: await c.bot.send_message(chat, ad_text(lang, uid, v), parse_mode="HTML", reply_markup=ad_kb(lang, uid, v), disable_web_page_preview=True); return
    m = await c.bot.send_photo(chat, media, caption=ad_text(lang, uid, v), parse_mode="HTML", reply_markup=ad_kb(lang, uid, v))
    remember_banner(m, "ad:tr", h)

async def ad_cb(q, data):
    p_ = data.split(":"); lang = p_[0]
    if lang not in AD_TXT: return
    uid = int(p_[1]) if len(p_) > 1 and p_[1].isdigit() and p_[1] != "0" else None
    v = int(p_[2]) if len(p_) > 2 and p_[2].isdigit() else 0
    try:
        await q.edit_message_caption(caption=ad_text(lang, uid, v), parse_mode="HTML", reply_markup=ad_kb(lang, uid, v))
        await q.answer()
    except BadRequest as e:
        if "not modified" in str(e).lower(): await q.answer(); return
        await q.answer(("Начните: " if lang == "ru" else "Başlamak üçin: ") + ad_link(uid), show_alert=True)   # iletilmiş kopya düzenlenemez
    except Exception as e:
        log.info("ad cb: %s", e)
        try: await q.answer()
        except Exception: pass

async def inline_ad(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """@bot yazınca reklam postu; yazan kişinin davet linkiyle (kanalda dil butonları çalışır)."""
    try:
        fid = await ad_photo_id(c.bot)
        if not fid: vlog("⚠️ Inline reklam: fotoğraf yüklenemedi"); await u.inline_query.answer([], cache_time=10); return
        await _inline_ad(u, fid)
    except Exception as e:
        vlog(f"⚠️ Inline reklam hatası: {str(e)[:150]}"); log.exception("inline ad")

async def _inline_ad(u, fid):
    uid = u.inline_query.from_user.id
    e_ = load_db().get("users", {}).get(str(uid))
    ref = uid if e_ else None   # botu kullanan kişi: kendi davet linki
    v = 0
    # tek sonuç: Türkmençe post; Rusça için posttaki 🇷🇺 butonu
    res = [InlineQueryResultCachedPhoto(id=f"ad{v}", photo_file_id=fid, title="📢 Reklama", caption=ad_text("tk", ref, v), parse_mode="HTML", reply_markup=ad_kb("tk", ref, v))]
    await u.inline_query.answer(res, cache_time=30, is_personal=True)

def mkt_ann(lang):
    """Satın alınan pazar kodunun Happ duyurusu (tek satır)."""
    un = "@" + (BOT.get("un") or "SuBDrive_bot")
    return {"ru": f"🤖 Telegram: {un} · поддержка 24/7", "tk": f"🤖 Telegram: {un} · 7/24 goldaw"}.get(lang, f"🤖 Telegram: {un} · 7/24 destek")

def market_refresh_files():
    """İlanın kodları değiştiyse açık oturumların Drive dosyalarını günceller."""
    db = load_db(); jobs = []
    for sid, s in db.get("msess", {}).items():
        if s.get("status") != "on": continue
        L = db.get("market", {}).get(s["lid"])
        if not L: continue
        codes = listing_codes(db, L)
        ann = mkt_ann(lang_of(db, s["buyer"]))
        h = hashlib.md5(("\n".join(codes) + f"#fmt{FILE_FMT}#{ann}").encode()).hexdigest()   # duyuru değişince de yeniden yazılır
        if codes and h != s.get("hash"): jobs.append((sid, s["fid"], L["title"], codes, h, ann))
    if not jobs: return
    svc = new_service()
    for sid, fid, title, codes, h, ann in jobs:
        if sync_file(svc, fid, title, ann, codes, exp=False):
            mutate(lambda d: d["msess"][sid].__setitem__("hash", h))

async def notify_payout(app, info):
    """Satıcıya ödeme + tebrik mesajı."""
    if info.get("own") or not info.get("owner") or info["payout"] <= 0: return
    r = await asyncio.to_thread(pay_seller, info["owner"], info["payout"], f"{info['sid']}-{int(time.time())}", f"VPN pazarı: {info['title']}")
    lg = lang_of(load_db(), info["owner"])
    try:
        await app.bot.send_message(info["owner"], tr(lg, "m_paid_sent" if r == "sent" else "m_paid_bal", title=esc(info["title"]), dur=dur_txt(info["span"], lg == "ru"),
                                                     usdt=fmt_u(info["payout"]), tmt=tmt_u(info["payout"])), parse_mode="HTML")
    except Exception: pass
    if r == "bal" and RUN.get("transfer_err") and RUN.get("transfer_warned") != RUN["transfer_err"]:
        RUN["transfer_warned"] = RUN["transfer_err"]
        await notify_founders(app, f"⚠️ <b>CryptoBot transferi yapılamadı</b>\n<blockquote>{esc(RUN['transfer_err'])}</blockquote>\n<i>Satıcının kazancı bot bakiyesine eklendi. CryptoBot → Crypto Pay → uygulaman → transferlere izin ver.</i>")

async def stop_session(app, sid, reason):
    info = await asyncio.to_thread(mkt_stop, sid, reason)
    if not info: return None
    lg = lang_of(load_db(), info["buyer"])
    why = tr(lg, {"nobal": "why_nobal", "gone": "why_gone"}.get(reason, "why_user"))
    try:
        await app.bot.send_message(info["buyer"], tr(lg, "m_stopped", title=esc(info["title"]), dur=dur_txt(info["dur"], lg == "ru"), usdt=fmt_u(info["total"]), why=("\n" + why) if why else ""),
                                   parse_mode="HTML", reply_markup=KB([[B(tr(lg, "b_top"), "u_top")]]) if reason == "nobal" else None)
    except Exception: pass
    ulog("m_stop", f"⏹ Pazar kodu durdu ({reason}): {info['title']} · alıcı {info['buyer']} · {dur_txt(info['dur'])} · {fmt_u(info['total'])} USDT")
    await notify_payout(app, info)
    return info

async def check_waiters(app):
    """Bir tur: telefonun hızlı kontrol sonucu geldiyse aynı kutuya yazar; gelmediyse geçen süreyi gösterir, 10 dk'da son durumu."""
    if not CHK["wait"]: return
    now = time.time(); db = load_db()
    ch = await chk_run(_read_channel, db)
    if ch: CHK["last_ch"] = ch
    qd, ts = ch.get("quick_done") or 0, ch.get("ts") or 0
    for lid in list(CHK["wait"]):
        for uid, (lang, mid, is_photo, qid, t0, mode) in list(CHK["wait"][lid].items()):
            done = qd >= qid or ts > t0
            if done or now - t0 >= CHK_WAIT:
                CHK["wait"][lid].pop(uid, None)
                if CHK.get("logged") != qid:
                    CHK["logged"] = qid
                    vlog(f"⚡ Hızlı kontrol sonucu geldi ({int(now - t0)} sn)" if done else f"⚠️ Hızlı kontrol: telefon {CHK_WAIT // 60} dk içinde cevap vermedi")
                t = check_text(db, lid, lang, ch, "done" if done else "timeout")
                if not await edit_box(app.bot, uid, mid, is_photo, t, chk_kb(lang, lid)):
                    try: await app.bot.send_message(uid, t, parse_mode="HTML", reply_markup=chk_kb(lang, lid))
                    except Exception: pass
            else:
                el = int((now - t0) // 60)
                if el >= 1 and CHK.setdefault("el", {}).get((uid, mid)) != el:   # dakikada bir "geçen süre"
                    CHK["el"][(uid, mid)] = el
                    await edit_box(app.bot, uid, mid, is_photo, check_text(db, lid, lang, ch if mode == "refresh" else None, mode, el), chk_kb(lang, lid, False))
        if not CHK["wait"][lid]: CHK["wait"].pop(lid, None)

async def chk_poll(app):
    """Bekleyen kontrol varken 10 sn'de bir telefonun sonucuna bakar."""
    try:
        while CHK["wait"]:
            await asyncio.sleep(10)
            try: await check_waiters(app)
            except Exception as e: log.warning("check poll: %s", e)
    finally: CHK.get("el", {}).clear()

REMIND_EVERY = 12 * 3600

async def remind_open(app):
    """Uzun süredir açık pazar kodu: alıcıya hatırlat (para dakika başı düşmeye devam ediyor)."""
    now = time.time()
    def f(d):
        out = []
        for sid, x in d.get("msess", {}).items():
            if x.get("status") == "on" and now - x.get("remind_ts", x["start"]) >= REMIND_EVERY:
                x["remind_ts"] = now; out.append((sid, x["buyer"], x["lid"], now - x["start"], x.get("total", 0)))
        return out
    for sid, buyer, lid, dur, total in mutate(f):
        db = load_db(); lg = lang_of(db, buyer)
        try:
            await app.bot.send_message(buyer, tr(lg, "m_remind", title=esc(db["market"].get(lid, {}).get("title", "?")), dur=dur_txt(dur, lg == "ru"),
                                                 spent=money_tmt(total), bal=fmt_u(db["users"].get(str(buyer), {}).get("bal", 0))),
                                       parse_mode="HTML", reply_markup=KB([[B(tr(lg, "b_stop"), f"u_msq:{sid}", "danger"), B(tr(lg, "b_mine"), "u_mine")]]))
        except Exception: pass

async def market_tick(app):
    if MKT["lock"] is None: MKT["lock"] = asyncio.Lock()
    async with MKT["lock"]:
        events = await asyncio.to_thread(market_scan)
        await asyncio.to_thread(market_push_phone)   # kanal yazımı CH_WLOCK ile korunur
        await remind_open(app)
        db = load_db()
        for kind, lid, why, n in events:
            L = db["market"].get(lid, {}); ow = L.get("owner"); lg = lang_of(db, ow) if ow else "tr"; st = L.get("st") or {}
            try:
                if kind != "slow": vlog(f"🏪 Pazar: «{L.get('title')}» → {kind} {why} · TM {st.get('work', 0)}/{st.get('tested', 0)} · {len(st.get('cc', []))} ülke")
                if kind in ("approved", "rejected"):   # kurucuya gerçek ping/ülke (satıcı görmez)
                    try: await notify_founders(app, "📊 <b>Gerçek ölçüm</b> <i>(sadece sen görürsün)</i>\n\n" + await real_report(lid, "tr"))
                    except Exception: pass
                if kind == "approved":
                    ulog("m_live", f"🟢 İlan yayında: {L.get('title')} · satıcı {ow}")
                    await notify_founders(app, f"🟢 <b>Pazar ilanı yayında</b>\n<blockquote>{esc(L.get('title'))} · 🌍 {len(st.get('cc', []))} ülke · ✅ {st.get('work', 0)}/{st.get('tested', 0)}</blockquote>")
                    await app.bot.send_message(ow, tr(lg, "m_approved", title=esc(L["title"]), ncc=len(st.get("cc", [])), work=st.get("work", 0), tested=st.get("tested", 0)), parse_mode="HTML")
                elif kind == "rereview":
                    await app.bot.send_message(ow, tr(lg, "m_rereview", title=esc(L["title"])), parse_mode="HTML")
                elif kind == "rejected":
                    ulog("m_rej", f"❌ İlan reddedildi: {L.get('title')} · satıcı {ow} · {why}")
                    await notify_founders(app, f"❌ <b>Pazar ilanı reddedildi</b>\n<blockquote>{esc(L.get('title'))}\n{esc(tr('tr', why, n=n))}</blockquote>")
                    await app.bot.send_message(ow, tr(lg, "m_rejected", title=esc(L["title"]), why=tr(lg, why, n=n)), parse_mode="HTML")
                elif kind == "removed":
                    ulog("m_rm", f"⛔ İlan {n} saat yasaklandı: {L.get('title')} · satıcı {ow} · {why}")
                    await app.bot.send_message(ow, tr(lg, "m_removed", title=esc(L["title"]), why=tr(lg, why), h=n), parse_mode="HTML")
                elif kind == "slow":
                    await notify_founders(app, f"⏳ <b>Pazar ilanı 15 dakikadır incelemede</b>\n<blockquote>{esc(L.get('title'))}\nTelefon bu kodlar için henüz sonuç göndermedi (test edilen {st.get('tested', 0)}/{st.get('total', 0)}).\n{esc(RUN.get('tm_line', ''))}</blockquote>\n<i>Termux'un açık olduğunu kontrol et ya da Admin → 🏪 Pazar'dan elle onayla.</i>")
            except Exception: pass
        stop, warn, settle = await asyncio.to_thread(market_bill)
        for sid, reason in stop: await stop_session(app, sid, reason)
        for sid, buyer, left_min in warn:
            lg = lang_of(load_db(), buyer)
            try: await app.bot.send_message(buyer, tr(lg, "m_low", m=left_min), parse_mode="HTML", reply_markup=KB([[B(tr(lg, "b_top"), "u_top", "success")]]))
            except Exception: pass
        for info in settle:
            ulog("m_pay", f"💸 Günlük satıcı ödemesi: {info['title']} · {fmt_u(info['payout'])} USDT")
            await notify_payout(app, info)
        await asyncio.to_thread(market_refresh_files)

async def market_loop(app):
    while True:
        await asyncio.sleep(60)
        try: await market_tick(app)
        except Exception: log.exception("market tick")

# ── yükleme / ilan girişi (mesajla gelenler) ──
USDT_SELLERS = ["@iam_Romeo", "@BoT34m1", "@tanyshmy", "@telekeci"]   # TMT karşılığında CryptoBot için USDT satanlar

def topup_order(uid, user, lang, usdt):
    usdt = round(float(usdt), 2)
    oid = uuid.uuid4().hex[:6].upper()
    o = {"uid": uid, "item": "topup", "usdt": usdt, "n": 0, "price": usdt * USDT_RATE, "ts": time.time(), "status": "new", "who": who(user)}
    mutate(lambda d: d.setdefault("orders", {}).__setitem__(oid, o))
    ulog("order", f"🧾 Bakiye yükleme açtı: {who(user)} · #{oid} · {usdt} USDT")
    rows = ([[B(tr(lang, "b_usdt", usdt=usdt_of(o["price"])), f"u_usdt:{oid}", "success")]] if crypto_token() else []) + [[B(tr(lang, "b_cancel"), f"u_cancel:{oid}", "danger")]]
    return tr(lang, "top_order", oid=oid, usdt=usdt_of(o["price"])) + ("" if crypto_token() else "\n" + tr(lang, "pay_off")), KB(rows)

PAD_MAX_RATIO = 1.25   # yükseklik / genişlik bundan fazlaysa yanlara boşluk eklenir (Telegram uzun fotoğrafı kırpar)

def pad_photo(data):
    """Uzun (dikey) ekran görüntüsünü bulanık arka planlı geniş bir tuvale ortalar → sohbette hep tam görünür. Gerek yoksa None."""
    from PIL import Image, ImageFilter
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    if h / w <= PAD_MAX_RATIO: return None
    W = int(h / PAD_MAX_RATIO)
    bg = im.resize((W, h)).filter(ImageFilter.GaussianBlur(40)).point(lambda v: int(v * 0.45))
    bg.paste(im, ((W - w) // 2, 0))
    out = io.BytesIO(); bg.save(out, "JPEG", quality=88); return out.getvalue()

async def full_view_photo(c, uid, fid):
    """Fotoğraf kırpılacak kadar uzunsa düzeltilmiş halini yükler; yeni file_id döner (gerekmezse None)."""
    f = await c.bot.get_file(fid)
    data = bytes(await f.download_as_bytearray())
    new = await asyncio.to_thread(pad_photo, data)
    if not new: return None
    m_ = await c.bot.send_photo(uid, new, disable_notification=True)
    try: await m_.delete()
    except Exception: pass
    return m_.photo[-1].file_id

async def market_input(c, u, st):
    """Satıcı ilan adımları ve özel yükleme tutarı (yazı ya da fotoğraf)."""
    m, user = u.message, u.effective_user
    uid = user.id; lang = lang_of(load_db(), uid); txt = (m.text or "").strip()
    cancel = KB([[B(tr(lang, "b_cancel"), "u_mkt")]])
    async def say(t, kb=None): await m.reply_text(t, parse_mode="HTML", reply_markup=kb or cancel, disable_web_page_preview=True)
    if st["action"] == "u_topamt":
        try: v = float(txt.replace(",", ".").replace("$", "").strip())
        except Exception: v = 0
        if v < TOPUP_MIN: await say(tr(lang, "top_bad"), KB([[B(tr(lang, "b_cancel"), "u_top")]])); return
        STATE.pop(uid, None)
        await say(*topup_order(uid, user, lang, v)); return
    step = st.get("step")
    if step == "link":
        if "happ://" in txt.lower() or "crypt" in txt.lower():   # Happ şifreli link: içindeki kodlar okunamaz
            await say(tr(lang, "sell_happ")); return
        link = next((w for w in txt.split() if w.startswith("http")), None)
        if not link: await say(tr(lang, "sell_badlink")); return
        try: codes = await asyncio.to_thread(fetch_codes, link)
        except Exception: codes = []
        if not codes: await say(tr(lang, "sell_badlink")); return
        lim = await asyncio.to_thread(sub_limits, link)   # GB ya da süre sınırı varsa kabul edilmez
        gb = lim.get("total", 0); exp = lim.get("expire", 0)
        if gb > 0 or exp > time.time():
            parts = ([f"📦 {gb / 1024 ** 3:.0f} GB"] if gb > 0 else []) + ([f"⏳ {datetime.datetime.fromtimestamp(exp, TM_TZ).strftime('%d.%m.%Y')}"] if exp > time.time() else [])
            await say(tr(lang, "sell_limited", lim=" · ".join(parts))); return
        if uid not in ADMINS and any(L.get("link") == link and L.get("status") in ("pending", "live") for L in load_db().get("market", {}).values()):
            STATE.pop(uid, None); await say(tr(lang, "sell_dup"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        protos = {}
        for c_ in codes: protos[proto_of(c_)] = protos.get(proto_of(c_), 0) + 1
        st.update({"step": "name", "link": link, "codes": codes, "protos": protos})
        await say(tr(lang, "sell_2", n=len(codes), protos=protos_txt(protos)))
    elif step == "name":
        if not txt: return
        st.update({"step": "photo", "title": txt[:40]})
        await say(tr(lang, "sell_3"))
    elif step == "photo":
        if not m.photo: await say(tr(lang, "sell_need_photo")); return
        fid_ = m.photo[-1].file_id
        try: fid_ = await full_view_photo(c, uid, fid_) or fid_
        except Exception as ex_: log.info("photo pad: %s", ex_)
        st.update({"step": "desc", "photo": fid_})
        await say(tr(lang, "sell_4"))
    elif step == "desc":
        st.update({"step": "price", "desc": "" if txt == "-" else txt[:300]})
        await say(tr(lang, "sell_5"))
    elif step == "price":
        try: v = float(txt.replace(",", ".").lower().replace("tmt", "").strip())
        except Exception: v = 0
        if not (1 <= v <= 10000): await say(tr(lang, "sell_badprice")); return
        p = price_from_month_tmt(v)
        st.update({"step": "confirm", "price": p})
        e_ = load_db()["users"].get(str(uid), {}); fee_s = fmt_u(seller_fee(e_)) + "$"
        await say((tr(lang, "sell_confirm", title=esc(st["title"]), n=len(st["codes"]), protos=protos_txt(st["protos"]), desc=esc(st.get("desc") or "—"), calc=calc_text(p, lang == "ru"))
                   + (tr(lang, "fee_x2_note") if e_.get("fee_x2") else "")).replace("0.05$", fee_s)
                  + tr(lang, "sell_bal", bal=fmt_u(e_.get("bal", 0))),
                  KB([[B(tr(lang, "b_sellok").replace("0.05$", fee_s), "u_sellok", "success")], [B(tr(lang, "b_sellp"), "u_sellp")], [B(tr(lang, "b_cancel"), "u_mkt", "danger")]]))

# ── kurucu ekranları ──
def mkt_admin_view():
    db = load_db(); ensure_own(db)
    m = db["market"]; own = m[OWN_LID]
    act = [s for s in db.get("msess", {}).values() if s.get("status") == "on"]
    rows = [[B(f"💲 Bizim fiyat: {money2(float(own['price']) * 43200, True)} TMT/ay", "mk_price", "primary")],
            [B("📷 Bizim ilan fotoğrafı" + (" ✅" if own.get("photo") else ""), "mk_oph")],
            [B("📝 Bizim ilan açıklaması", "mk_ods")]]
    if own.get("photo") or own.get("desc") != OWN_DESC: rows.append([B("↩️ Foto/açıklamayı sıfırla", "mk_odr")])
    for lid, L in sorted(m.items(), key=lambda x: x[1].get("created", 0), reverse=True):
        if L.get("own") or L.get("status") not in ("pending", "live", "suspended"): continue
        rows.append([B(f"{T['tr']['st_' + L['status']]} {short(L['title'], 18)} · {money2(float(L['price']) * 43200, True)} TMT", f"mk_l:{lid}")])
    rows.append([B("◀️ Admin", "admin")])
    t = ("🏪 <b>Pazar</b>\n<blockquote>"
         f"🟢 Yayında  <b>{sum(1 for L in m.values() if L.get('status') == 'live' and not L.get('own'))}</b>  ·  ⏳ İncelemede  <b>{sum(1 for L in m.values() if L.get('status') == 'pending')}</b>\n"
         f"▶️ Açık oturum  <b>{len(act)}</b>\n"
         f"💰 Ücret geliri (0.05$'lar)  <b>{fmt_u(db.get('mkt_fees', 0))} USDT</b>\n"
         f"⭐ Bizim ilan kullanım geliri  <b>{fmt_u(db.get('mkt_own_rev', 0))} USDT</b>\n"
         f"⛔ Yasaklı  <b>{sum(1 for L in m.values() if L.get('status') == 'suspended')}</b>\n"
         f"⭐ Bizim fiyat  <b>{money2(float(own['price']) * 43200, True)} TMT/ay</b>\n{calc_text(own['price'])}</blockquote>")
    return t, KB(rows)

def mkt_admin_detail(lid):
    db = load_db(); L = db.get("market", {}).get(lid)
    if not L: return "⚠️ İlan bulunamadı.", back("mk_admin")
    st = L.get("st") or {}
    ow = db["users"].get(str(L.get("owner")), {})
    t = (f"🏪 <b>{esc(L['title'])}</b>  {T['tr']['st_' + L['status']]}\n<blockquote>"
         f"👤 {esc(ow.get('name') or '?')} <code>{L.get('owner')}</code>\n"
         f"📡 {st.get('total', len(L.get('codes', [])))} sunucu · {protos_txt(st.get('protos', {}))}\n"
         f"🇹🇲 {st.get('work', 0)}/{st.get('tested', 0)} çalışıyor · ❌ {st.get('dead', 0)} · 🌍 {len(st.get('cc', []))} ülke\n"
         f"💲 {money2(float(L['price']) * 43200, True)} TMT/ay\n📝 {esc(L.get('desc') or '—')}</blockquote>\n🔗 <code>{esc(L.get('link', ''))}</code>")
    rows = ([[B("✅ Elle Onayla", f"mk_ok:{lid}", "success")]] if L["status"] == "pending" else []) + \
           (list(photo_kb(lid).inline_keyboard) if L.get("photo") and not L.get("photo_ok", True) else []) + \
           [[B("🗑 Kaldır", f"mk_rm:{lid}", "danger"), B("📷 Görüntü", f"mk_ph:{lid}")], [B("👤 Satıcı", f"uv:{L.get('owner')}"), B("◀️ Pazar", "mk_admin")]]
    return t, KB(rows)

# ───────── KENDİNİ GÜNCELLEME (dosyayı bota atınca; sadece kurucular) ─────────
SELF = os.path.abspath(__file__)
UPDATE_NOTE = "/root/.subbot_update_note"

def sha16(path):
    with open(path, "rb") as f: return hashlib.sha256(f.read()).hexdigest()[:16]

def check_new_bot(path):
    """Yeni bot dosyasını değiştirmeden ÖNCE dener: derleme + ayrı süreçte açılış testi (--selftest)."""
    import py_compile, subprocess
    try: py_compile.compile(path, doraise=True)
    except Exception as e: return False, f"Sözdizimi hatası: {str(e)[:300]}"
    try:
        r = subprocess.run([sys.executable, path, "--selftest"], capture_output=True, text=True, timeout=90, cwd=os.path.dirname(SELF))
    except Exception as e: return False, f"Açılış testi çalışmadı: {e}"
    if r.returncode != 0 or "SELFTEST OK" not in r.stdout:
        return False, "Açılış testi başarısız:\n" + (r.stderr or r.stdout)[-600:]
    return True, ""

def restart_self():
    """Aynı süreçte yeni dosyayla yeniden başlar (systemd için PID değişmez)."""
    os.execv(sys.executable, [sys.executable, SELF])

def send_tmtest_to_phone(code_text):
    """Telefon programını Drive kanalına koyar; telefon 1 dk içinde alıp kendini günceller."""
    db = load_db()
    if not db.get("tm_fid"): raise RuntimeError("Telefon kanalı henüz yok")
    svc = new_service()
    raw = svc.files().get_media(fileId=db["tm_fid"]).execute(num_retries=2).decode("utf-8", "ignore").strip()
    ch = json.loads(raw) if raw.startswith("{") else {}
    ch["tmtest_code"] = code_text
    ch["tmtest_sha"] = hashlib.sha256(code_text.encode("utf-8")).hexdigest()[:16]
    _tm_write(svc, db["tm_fid"], ch)
    return ch["tmtest_sha"]

async def doc_handler(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    d = u.message.document
    if uid not in ADMINS or not d: return
    fn = (d.file_name or "").lower()
    if fn.startswith("sohbet"):
        f = await c.bot.get_file(d.file_id)
        await f.download_to_drive("/root/sohbet.txt")
        await u.message.reply_text("✅ sohbet.txt kaydedildi (/root/sohbet.txt)")

    elif fn.startswith("subbot") and fn.endswith(".py"):
        m = await u.message.reply_text("⏳ Yeni bot sürümü deneniyor...")
        tmp = os.path.join(os.path.dirname(SELF), "subbot_upload.py")
        f = await c.bot.get_file(d.file_id)
        await f.download_to_drive(tmp)
        ok, why = await asyncio.to_thread(check_new_bot, tmp)
        if not ok:
            try: os.remove(tmp)
            except Exception: pass
            await m.edit_text(f"❌ <b>Kurulmadı</b> — bot eski sürümle çalışmaya devam ediyor.\n<pre>{esc(why)}</pre>", parse_mode="HTML"); return
        sha = sha16(tmp)
        shutil.copy(SELF, SELF + ".eski")
        os.replace(tmp, SELF)
        audit(uid, f"self-update {sha}"); vlog(f"⬆️ Bot güncellendi ({sha}), yeniden başlıyor")
        with open(UPDATE_NOTE, "w") as nf: nf.write(sha)
        await m.edit_text(f"✅ <b>Yeni sürüm kuruldu</b> <code>{sha}</code>\n<i>Bot birkaç saniye içinde yeniden açılıyor...</i>", parse_mode="HTML")
        asyncio.get_running_loop().call_later(2, restart_self)

    elif fn.startswith("banners") and fn.endswith(".json"):   # görsel paketi (ana menü/ekran banner'ları)
        f = await c.bot.get_file(d.file_id)
        data = bytes(await f.download_as_bytearray())
        try:
            j_ = json.loads(data.decode("utf-8")); assert isinstance(j_, dict) and j_
        except Exception as e:
            await u.message.reply_text(f"❌ banners.json bozuk: {esc(str(e)[:150])}", parse_mode="HTML"); return
        with open(BANNER_FILE + ".tmp", "wb") as bf: bf.write(data)
        os.replace(BANNER_FILE + ".tmp", BANNER_FILE)
        n_ = load_banners(); audit(uid, "banners upload")
        await u.message.reply_text(f"✅ Görseller yüklendi: {n_} ekran" + (" + pazar fotoğrafı" if _OWN_IMG_B64 else ""))

    elif fn.startswith("tmtest") and fn.endswith(".py"):
        f = await c.bot.get_file(d.file_id)
        data = bytes(await f.download_as_bytearray())
        try:
            text = data.decode("utf-8")
            compile(text, "tmtest.py", "exec")
        except Exception as e:
            await u.message.reply_text(f"❌ tmtest.py bozuk, gönderilmedi: {esc(str(e)[:200])}", parse_mode="HTML"); return
        try:
            async with CHECK_LOCK:   # kontrol döngüsü aynı anda kanala yazıp bunu silmesin
                sha = await asyncio.to_thread(send_tmtest_to_phone, text)
        except Exception as e:
            await u.message.reply_text(f"❌ Telefona gönderilemedi: {esc(str(e)[:200])}", parse_mode="HTML"); return
        audit(uid, f"tmtest push {sha}"); vlog(f"📲 Telefon programı kanala kondu ({sha}), telefon 1 dk içinde güncellenir")
        await u.message.reply_text(f"✅ <b>Telefona gönderildi</b> <code>{sha}</code>\n<i>Telefon 1 dakika içinde kendini güncelleyip yeniden başlar (Termux açık olmalı).</i>", parse_mode="HTML")

_ERR = {"t": 0.0}

async def on_error(update, context):
    log.error("Error: %s", context.error, exc_info=context.error)
    from telegram.error import NetworkError, RetryAfter
    if isinstance(context.error, RetryAfter):
        vlog(f"⚠️ Telegram flood limiti: {context.error.retry_after} sn bekleniyor")
        return
    if isinstance(context.error, NetworkError): return
    try:
        if isinstance(update, Update) and update.effective_user and update.effective_chat and update.effective_chat.type == "private":
            where = update.callback_query.data if update.callback_query else ((update.message.text or "medya")[:60] if update.message else "?")
            await send_error(context, update.effective_user.id, where, context.error)
    except Exception: log.exception("send_error")
    if time.time() - _ERR["t"] < 600: return
    _ERR["t"] = time.time()
    try: await notify_founders(context.application, f"❗ <b>Bot hatası</b>\n<code>{esc(str(context.error)[:300])}</code>")
    except Exception: pass

def main():
    if "--selftest" in sys.argv:   # güncelleme öncesi deneme: dosya hatasız yükleniyor mu
        print("SELFTEST OK"); return
    token = os.environ.get("BOT_TOKEN", "")
    if not token: raise SystemExit("BOT_TOKEN bulunamadı (/root/env.txt)")
    if not ADMINS: log.warning("ADMIN_IDS yok: kimse giriş yapamaz.")
    app = ApplicationBuilder().token(token).concurrent_updates(True).post_init(post_init).build()
    app.add_handler(MessageHandler(filters.UpdateType.MESSAGE & ~filters.COMMAND, support_router), group=-1)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(InlineQueryHandler(inline_ad))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, doc_handler))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)

# ── Görseller ayrı dosyada (/root/banners.json): bot dosyası küçük kalsın ──
BANNER_FILE = os.environ.get("BANNER_FILE", "/root/banners.json")
_BANNERS, _OWN_IMG_B64 = {}, ""

def _banners_from_old():
    """Bir kez: görseller eski sürümün içinde gömülüyse (subbot.py.eski) oradan çıkarılıp dosyaya yazılır."""
    import ast
    for path in (SELF + ".eski", SELF):
        try: tree = ast.parse(open(path, encoding="utf-8").read())
        except Exception: continue
        got = {}
        for n in tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ("_BANNERS", "_OWN_IMG_B64"):
                try: got[n.targets[0].id] = ast.literal_eval(n.value)
                except Exception: pass
        if isinstance(got.get("_BANNERS"), dict) and got["_BANNERS"]:
            d = dict(got["_BANNERS"])
            if got.get("_OWN_IMG_B64"): d["own"] = {"tr": got["_OWN_IMG_B64"]}
            return d
    return None

def load_banners():
    global _BANNERS, _OWN_IMG_B64
    d = None
    try:
        with open(BANNER_FILE, encoding="utf-8") as f: d = json.load(f)
    except Exception:
        d = _banners_from_old()
        if d:
            try:
                with open(BANNER_FILE + ".tmp", "w", encoding="utf-8") as f: json.dump(d, f)
                os.replace(BANNER_FILE + ".tmp", BANNER_FILE)
            except Exception as e: log.warning("banners kaydedilemedi: %s", e)
    d = d or {}
    _OWN_IMG_B64 = (d.get("own") or {}).get("tr", "")
    _BANNERS = {k: v for k, v in d.items() if k != "own" and isinstance(v, dict)}
    return len(_BANNERS)

load_banners()

if __name__ == "__main__":
    main()
