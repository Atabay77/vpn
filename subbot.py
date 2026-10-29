import os, sys, io, re, json, html, uuid, base64, asyncio, types, zipfile, shutil, fcntl, logging, datetime, time, socket, random, hashlib, warnings, unicodedata, threading
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
TM_HINT_AGE = 48 * 3600   # test eskiyse bile bu kadar yeni sonuç, kod sıralamasında (çalışanlar önce) kullanılır

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

def _tm_create(svc, db, data, name=TM_NAME):
    """Önce adla var olanı bul, yoksa yeni dosya oluştur, o da olmazsa boş bir dosyayı kullan."""
    r = svc.files().list(q=f"name='{name}' and trashed=false", fields="files(id)", orderBy="modifiedTime desc", pageSize=1).execute()
    if r.get("files"): return r["files"][0]["id"]
    media = MediaIoBaseUpload(io.BytesIO(json.dumps(data).encode("utf-8")), mimetype="text/plain")
    try:
        return svc.files().create(body={"name": name, "mimeType": "text/plain"}, media_body=media, fields="id").execute()["id"]
    except Exception as e:
        log.warning("tm create: %s", e)
    used = used_fids(db) | set(db["free_files"])
    fid = find_free_file(svc, used)
    if not fid: raise RuntimeError("Drive'da kanal için boş dosya yok")
    _tm_write(svc, fid, data, name)
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
    if not ts: return set(), {}, False, load_exits()
    if stale:   # test eski: kurallar uygulanmaz ama son bilinen çalışan kodlar öne alınır (ülke başına ilk seçilen o olsun)
        hint = {k: v for k, v in res.items() if isinstance(v, (int, float)) and v > 0} if time.time() - ts < TM_HINT_AGE else {}
        return set(), hint, False, load_exits()
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
    was_stale = tm_fresh and not db.get("tm_fresh_w") and planned != listed   # liste test eskiyken yazıldı, şimdi güncel test var → hemen düzelt
    tm_changed = bool(bad_listed) or (bool(gained or exch) and add_due) or was_stale
    need = ip_need(db)
    if not force and old and len(new) < need and not tm_changed:
        RUN["last_msg"] = f"✅ {len(codes)} kod, {len(new)} yeni IP → değişiklik yok"
        vlog(f"ℹ️ {len(codes)} kod · {len(new)} yeni IP (eşik: en az {need}) → değişiklik yok")
        return None

    why = "⚡ Elle güncelleme" if force else (f"🚨 {len(new)} yeni IP bulundu" if (not old or len(new) >= need) else
                                            f"📱 Listedeki {len(bad_listed)} kod bozuldu/yavaşladı" if bad_listed else "📱 Telefon testi geldi → liste çalışan kodlarla yazılıyor" if was_stale else f"📱 {len(gained)} yeni çalışan kod eklenecek" if gained else "📱 Ülke bilgisi değişti")
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
        d["last_update"] = time.time(); d["tm_fresh_w"] = tm_fresh
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
        await notify_founders(app, head, KB([[B("📜 Loglar", callback_data="logs")]]), silent=True)   # sessiz bildirim
    alert = RUN.pop("tm_alert", None)
    if alert: await notify_founders(app, esc(alert), silent=True)
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
    """Botun bütün verisi: ayarlar, veritabanı, loglar, banner'lar, ülke önbellekleri, AI sohbet kayıtları."""
    buf = io.BytesIO(); n = 0
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in [DB_FILE, SA_FILE, ENV_FILE, VIP_LOG, AUDIT_LOG, USERS_LOG, GEO_FILE, EXIT_FILE, "/root/sohbet.txt", os.path.abspath(__file__), BANNER_FILE]:
            if os.path.exists(f): zf.write(f, os.path.basename(f)); n += 1
        if os.path.isdir(AI_DIR):   # 🤖 kullanıcıların AI sohbetleri
            for fn in sorted(os.listdir(AI_DIR)):
                fp = os.path.join(AI_DIR, fn)
                if os.path.isfile(fp) and fn.endswith(".json"): zf.write(fp, "ai_chats/" + fn); n += 1
    buf.seek(0); RUN["backup_n"] = n
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
                    try: await app.bot.send_document(chat_id=fid, document=io.BytesIO(data), filename=fn, caption=f"🗄 Günlük otomatik yedek · {RUN.get('backup_n', '?')} dosya")
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
    app.bot_data["aiw"] = asyncio.create_task(ai_usage_watch(app))
    app.bot_data["aim"] = asyncio.create_task(ai_log_watch(app))
    app.bot_data["px"] = asyncio.create_task(proxy_loop(app))
    if ADMINS: asyncio.create_task(pad_old_photos(app))
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
               [B(tr(lg, "b_ai"), "u_ai", "primary")],
               [B(tr(lg, "b_px"), "u_px")],
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
        [B("🤖 AI Yardımcı", "ai_adm"), B("📡 Proxy", "px_adm")],
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

async def notify_founders(app, text, kb=None, silent=False):
    for fid in ADMINS:
        try: await app.bot.send_message(chat_id=fid, text=text, parse_mode="HTML", disable_web_page_preview=True, reply_markup=kb, disable_notification=silent)
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
    if u.message and await ticket_cmd_ask(u): return   # açık talep: önce sor
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
            why = "" if txt.strip() == "-" else txt.strip()[:300]
            await u.message.reply_text(await reject_listing(c, uid, st["lid"], why), reply_markup=back("mk_admin"))

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

        elif act == "ai_set":
            try: await u.message.delete()   # anahtar sohbette kalmasın
            except Exception: pass
            key_ = txt.strip()
            try: await asyncio.to_thread(ai_call, "Kısa cevap ver.", [{"role": "user", "content": "ping"}], key_)
            except Exception as e:
                await u.message.reply_text(f"⚠️ Anahtar çalışmadı: <code>{esc(str(e)[:150])}</code>", parse_mode="HTML", reply_markup=back("ai_adm")); return
            await asyncio.to_thread(set_env, "AI_API_KEY", key_); RUN.pop("ai_err", None)
            audit(uid, "ai key set")
            t_, kb_ = await asyncio.to_thread(ai_view); await u.message.reply_text("✅ AI bağlandı.\n\n" + t_, parse_mode="HTML", reply_markup=kb_)

        elif act == "ai_nadd":
            if not txt: STATE[uid] = st; return
            mutate(lambda d: d.__setitem__("ai_notes", (d.get("ai_notes", []) + [{"t": txt[:800], "ts": time.time()}])[-AI_NOTES_MAX:]))
            audit(uid, "ai note add")
            await u.message.reply_text("✅ AI bu bilgiyi artık biliyor.", reply_markup=KB([[B("📝 AI Bilgileri", "ai_notes")]]))

        elif act in ("ai_lim", "ai_plim"):
            try: n_ = int(txt.strip())
            except Exception: n_ = -1
            if not 1 <= n_ <= 1000:
                STATE[uid] = st; await u.message.reply_text("⚠️ 1-1000 arası bir sayı yaz.", reply_markup=back("ai_adm")); return
            fld_ = "ai_limit" if act == "ai_lim" else "ai_pro_limit"
            mutate(lambda d: d.__setitem__(fld_, n_)); audit(uid, f"{fld_} {n_}")
            t_, kb_ = await asyncio.to_thread(ai_view); await u.message.reply_text("✅ Kaydedildi.\n\n" + t_, parse_mode="HTML", reply_markup=kb_)

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

FOUNDER_ONLY = {"px_adm", "px_now", "ban_menu", "ban_find", "hp", "hp_set", "hp_del", "hp_new", "ref_test", "mk_admin", "mk_price", "mk_oph", "mk_ods", "mk_odr", "bal_find", "usearch", "rep_today", "rep_yday", "tickets_bug", "t_cancel", "tickets", "cp_test", "cp", "cp_set", "cp_del", "ai_adm", "ai_set", "ai_lim", "ai_plim", "ai_del", "ai_use", "ai_tsup", "ai_tmon", "ai_notes", "ai_nadd", "ai_learnv", "ai_lclr", "ul_open", "stats", "chans", "ch_add", "pay_set", "bcast", "bcast_yes", "rollback", "rollback_yes", "auto_ann", "toggle_sys", "mk_rev", "ad_post", "ip_need", "ping_max", "admin", "sources", "s_add", "logs", "upd_now", "get_zip", "sa_menu", "sa_add", "bulk_ann", "bulk_title", "bulk_yes"}
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
    if uid not in ADMINS and (a in FOUNDER_ONLY or a.startswith(("sv:", "se:", "sd:", "sa_del:", "sa_ext:", "sa_lim:", "kx:", "kxs:", "ul:", "chd:", "ord_ok:", "ord_no:", "t_rep:", "t_close:", "t_ai:", "tv:", "ug:", "ux:", "uxc:", "ub:", "uv:", "ubal:", "mk_l:", "mk_ok:", "mk_rm:", "mk_ph:", "mk_real:", "mk_fake:", "mk_fakey:", "mk_rv:",  "mk_pok:", "mk_pno:", "mk_prj:", "mk_rjx:", "hl:", "hlp:", "ubn:", "bnd:", "bnq:", "ai_ndel:"))):
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

    elif a.startswith("mk_rjx:"):   # sebepsiz reddet
        STATE.pop(uid, None)
        await safe_edit(q, await reject_listing(c, uid, a.split(":", 1)[1], ""), back("mk_admin"))

    elif a.startswith("mk_prj:"):   # fotoğraf/ilan reddi: ceza yok, sebep yazılabilir
        lid = a.split(":", 1)[1]
        STATE[uid] = {"action": "mk_rej", "lid": lid}
        t, _ = prompt("❌ <b>İlanı reddet</b>", "Sebebini yaz, satıcıya gönderilir. Ya da aşağıdan sebepsiz reddet.\n<i>Ceza / engel yok.</i>", "mk_admin")
        await c.bot.send_message(uid, t, parse_mode="HTML", reply_markup=KB([[B("❌ Sebepsiz reddet", f"mk_rjx:{lid}", "danger")], [B("✖️ İptal", "mk_admin")]]))
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
            if not ban_: e.pop("ban_until", None); e.pop("nsfw_n", None)   # yanlış ban açıldı: 18+ sayacı da sıfırlanır
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
        lines_, n_ = [], 0
        for x in reversed(t.get("log", [])):
            ln = ("👤 " if x["r"] == "u" else "🛠 " if x["r"] == "adm" else "🤖 ") + esc(short(" ".join(x["c"].split()), 400))
            n_ += len(ln)
            if n_ > 2800: break
            lines_.append(ln)
        await safe_edit(q, f"{'🐞' if t.get('kind') == 'bug' else '🎫'} <b>#{tid}</b> · {esc(t.get('who'))}\n<i>{ago(t.get('ts'))} · {t.get('n', 0)} mesaj · " + ("🙋 admin istedi" if t.get("human") else "🤖 AI cevaplıyor") + "</i>"
                           + (("\n<blockquote expandable>" + "\n\n".join(reversed(lines_)) + "</blockquote>") if lines_ else ""),
                        KB([[B("✍️ Yanıtla", f"t_rep:{tid}", "primary"), B("🔒 Kapat", f"t_close:{tid}", "danger")]] + ([[B("🤖 AI'ye devret", f"t_ai:{tid}")]] if t.get("human") and ai_key() and db.get("ai_sup", True) else []) + [[B("◀️ Talepler", "tickets")]]))

    elif a.startswith("t_rep:"):   # mesaj medya olabilir: üzerine yazma, yeni mesaj gönder
        tid = a.split(":", 1)[1]
        STATE[uid] = {"action": "t_reply", "tid": tid}
        await c.bot.send_message(uid, f"✍️ <b>#{tid}</b> için cevabını yaz.\n<blockquote>Yazı, fotoğraf, video, dosya... ne gönderirsen kullanıcıya gider.</blockquote>",
                                 parse_mode="HTML", reply_markup=KB([[B("✖️ İptal", "t_cancel")]]))

    elif a.startswith("t_ai:"):   # 🤖 talebi AI'ye geri ver: kullanıcının cevapsız son mesajına hemen cevap verir
        tid = a.split(":", 1)[1]
        if not (ai_key() and load_db().get("ai_sup", True)): await q.answer("⚠️ Destek AI'si kapalı.", show_alert=True); return
        def f(d):
            t = d.get("tickets", {}).get(tid)
            if not t or t.get("status") != "open": return None
            t["human"] = False; t["curse_n"] = 0; t["notified"] = True
            lg_ = t.get("log", [])
            return t["uid"], (lg_[-1]["c"] if lg_ and lg_[-1]["r"] == "u" else None)
        r_ = mutate(f)
        if not r_: await c.bot.send_message(uid, f"ℹ️ Talep #{tid} kapalı."); return
        tuid, last_ = r_
        if STATE.get(uid, {}).get("tid") == tid: STATE.pop(uid, None)
        audit(uid, f"ticket {tid} → AI")
        try: await q.edit_message_reply_markup(None)
        except Exception: pass
        await c.bot.send_message(uid, f"🤖 Talep #{tid} AI'ye devredildi." + (" Son mesaja şimdi cevap veriyor." if last_ else " Kullanıcı yazınca AI cevaplar."))
        if last_:
            try: tu = await c.bot.get_chat(tuid)
            except Exception: tu = types.SimpleNamespace(id=tuid, username=None, full_name="?")
            fake = types.SimpleNamespace(text=last_, caption=None, **{k: None for k in ("photo", "video", "animation", "video_note", "voice", "audio", "document", "sticker")})
            asyncio.ensure_future(ai_support(c, tuid, tid, lang_of(load_db(), tuid), fake, tu))

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

    elif a in ("px_adm", "px_now"):
        if a == "px_now": PX["next"] = 0
        t_, kb_ = px_admin_view()
        if a == "px_now": t_ += "\n⏳ <b>Toplama başladı</b>, 2-3 dk içinde Yenile."
        await safe_edit(q, t_, kb_)

    elif a == "ai_adm":
        await safe_edit(q, *(await asyncio.to_thread(ai_view)))

    elif a == "ai_set":
        STATE[uid] = {"action": "ai_set"}
        await safe_edit(q, *prompt("🔑 <b>AI API anahtarı</b>", f"xKiro anahtarını gönder (sk-xt-…).\nAdres: <code>{esc(ai_base())}</code> · Model: <code>{esc(ai_model())}</code>\n<i>Mesajın güvenlik için hemen silinir.</i>", "ai_adm"))

    elif a == "ai_lim":
        STATE[uid] = {"action": "ai_lim"}
        await safe_edit(q, *prompt("🔢 <b>Günlük soru sınırı</b>", f"Kullanıcı başı günde kaç soru? (şu an {ai_limit()})", "ai_adm"))

    elif a in ("ai_tsup", "ai_tmon"):
        fld_ = "ai_sup" if a == "ai_tsup" else "ai_mon"
        mutate(lambda d: d.__setitem__(fld_, not d.get(fld_, True))); audit(uid, f"{fld_} toggle")
        await safe_edit(q, *(await asyncio.to_thread(ai_view)))

    elif a == "ai_notes" or a.startswith("ai_ndel:"):
        if a.startswith("ai_ndel:"):
            k_ = int(a.split(":")[1]); mutate(lambda d: d.get("ai_notes", []).pop(k_) if k_ < len(d.get("ai_notes", [])) else None)
        notes = load_db().get("ai_notes", [])
        body = "\n".join(f"{i + 1}. {esc(short(n_['t'], 150))}" for i, n_ in enumerate(notes)) or "Henüz bilgi yok."
        await safe_edit(q, f"📝 <b>AI Bilgileri</b>  <code>{len(notes)}</code>\n<blockquote expandable>{body}</blockquote>\n<i>Buraya yazdığın her bilgiyi AI (destek + yardımcı) kesin doğru kabul eder. Ör: \"Kodlar her gün 03:00'te yenilenir.\"</i>",
                        KB([[B("➕ Bilgi Ekle", "ai_nadd", "primary")]] + [[B(f"🗑 {i + 1}", f"ai_ndel:{i}") for i in range(k, min(k + 5, len(notes)))] for k in range(0, len(notes), 5)] + [[B("◀️ AI", "ai_adm")]]))

    elif a == "ai_nadd":
        STATE[uid] = {"action": "ai_nadd"}
        await safe_edit(q, *prompt("📝 <b>AI'ya bilgi ekle</b>", "AI'nın bilmesini istediğin bilgiyi yaz (bir mesaj = bir bilgi).", "ai_notes"))

    elif a == "ai_learnv" or a == "ai_lclr":
        if a == "ai_lclr": mutate(lambda d: d.__setitem__("ai_learn", []))
        ls = load_db().get("ai_learn", [])
        body = "\n\n".join(f"👤 {esc(short(x['q'], 120))}\n🛠 {esc(short(x['a'], 160))}" for x in ls[-15:]) or "Henüz yok. Destek taleplerine verdiğin cevaplardan öğrenir."
        await safe_edit(q, f"🎓 <b>AI'nın senden öğrendikleri</b>  <code>{len(ls)}</code>\n<blockquote expandable>{body}</blockquote>\n<i>Taleplere verdiğin her yazılı cevap buraya eklenir (son {AI_LEARN_MAX}).</i>",
                        KB([[B("🗑 Temizle", "ai_lclr", "danger")], [B("◀️ AI", "ai_adm")]]))

    elif a == "ai_use":
        await safe_edit(q, *(await asyncio.to_thread(ai_usage_view)))

    elif a == "ai_plim":
        STATE[uid] = {"action": "ai_plim"}
        await safe_edit(q, *prompt("💎 <b>Premium günlük sınır</b>", f"Abone başı sitenin her 5 saatlik penceresinde kaç soru? (şu an {ai_pro_limit()})", "ai_adm"))

    elif a == "ai_del":
        await asyncio.to_thread(set_env, "AI_API_KEY", ""); audit(uid, "ai key del")
        await safe_edit(q, *(await asyncio.to_thread(ai_view)))

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
        await safe_edit(q, *prompt("📣 <b>Herkese Mesaj</b>", "Bütün kullanıcılara gidecek mesajı gönder: yazı, fotoğraf ya da video (açıklamasıyla).", "admin"))

    elif a == "bcast_yes":
        st = STATE.pop(uid, None)
        if not st or st.get("action") != "bcast_ok":
            await safe_edit(q, "⚠️ Süre geçti, baştan başla.", back("admin")); return
        c.application.create_task(broadcast(c.application, st.get("text", ""), uid, st.get("copy")))
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

# ── 🤖 Yardımcı (AI): xKiro üzerinden Anthropic biçimi (/v1/messages) ──
AI_LIMIT = 20                    # kullanıcı başı günlük soru (kurucuya sınır yok); Admin → 🤖 AI'dan değişir
AI_HIST = {}                     # ("t", uid) -> son soru zamanı (art arda spam); sohbetler AI_DIR'de kalıcı
def ai_key(): return os.environ.get("AI_API_KEY", "")
def ai_base(): return (os.environ.get("AI_BASE_URL") or "https://api.xkiro.com").rstrip("/")
def ai_model(): return os.environ.get("AI_MODEL") or "anthropic/claude-opus-5.5"
def ai_limit(db=None):
    try: return int((db if db is not None else load_db()).get("ai_limit") or AI_LIMIT)
    except Exception: return AI_LIMIT

# Seçilebilir modeller (her sağlayıcının en iyisi). Açıklamalar model ailelerinin genel bilinen güçlü yanları.
AI_MODELS = {
 "opus":     ("Claude Opus 5.5", "anthropic/claude-opus-5.5", {"tr": "kod yazma, uzun ve dikkatli düşünme", "tk": "kod ýazmak, uzyn we içgin pikirlenmek", "ru": "код, сложные и длинные задачи"}),
 "gpt":      ("GPT-6.1 Sol", "openai/gpt-6.1-sol", {"tr": "genel sohbet, yazı, matematik", "tk": "umumy söhbet, tekst, matematika", "ru": "общение, тексты, математика"}),
 "gemini":   ("Gemini 3.8 Flash", "google/gemini-3.8-flash", {"tr": "çok hızlı, uzun metin okuma ve özetleme", "tk": "örän çalt, uzyn tekst okamak we gysgaltmak", "ru": "очень быстрый, длинные тексты и пересказ"}),
 "grok":     ("Grok 4.7", "x-ai/grok-4.7", {"tr": "rahat, esprili sohbet, kısa net cevap", "tk": "erkin, degişmeli söhbet, gysga jogap", "ru": "свободный остроумный стиль, кратко"}),
 "kimi":     ("Kimi K3 Agent", "moonshotai/kimi-k3-agent", {"tr": "çok adımlı işler, plan, kod", "tk": "köp ädimli işler, meýilnama, kod", "ru": "многошаговые задачи, планы, код"}),
 "mistral":  ("Mistral Large 4", "mistralai/mistral-large-4-0", {"tr": "hızlı, çeviri ve yazı", "tk": "çalt, terjime we tekst", "ru": "быстрый, перевод и тексты"}),
 "mimo":     ("MiMo v2.6 Pro", "xiaomi/mimo-v2.6-pro", {"tr": "matematik ve mantık, hızlı", "tk": "matematika we logika, çalt", "ru": "математика и логика, быстрый"}),
 "nemotron": ("Nemotron 3 Ultra", "nvidia/nemotron-3-ultra", {"tr": "teknik sorular, akıl yürütme", "tk": "tehniki soraglar, pikir ýöretmek", "ru": "технические вопросы, рассуждения"}),
 # 🆓 ücretsiz modeller (sitede Free): herkese günde AI_FREE_DAY soru, Premium gerekmez
 "fqmax":    ("Qwen3.8 Max", "qwen/qwen3.8-max:free", {"tr": "genel sorular, kod, ayrıntılı cevap", "tk": "umumy soraglar, kod, giňişleýin jogap", "ru": "общие вопросы, код, подробные ответы"}),
 "fqflash":  ("Qwen3.8 Omni Flash", "qwen/qwen3.8-omni-flash:free", {"tr": "çok hızlı, kısa cevap", "tk": "örän çalt, gysga jogap", "ru": "очень быстрый, кратко"}),
 "fmistral": ("Mistral Large 3", "mistralai/mistral-large-2512", {"tr": "yazı ve çeviri", "tk": "tekst we terjime", "ru": "тексты и перевод"}),
 "fcmd":     ("Command A+", "cohere/command-a-plus", {"tr": "uzun metin ve özetleme", "tk": "uzyn tekst we gysgaltmak", "ru": "длинные тексты и пересказ"}),
}
AI_FREEM = {"fqmax", "fqflash", "fmistral", "fcmd"}   # renksiz butonlar, ❓ Bot barada'nın altında
AI_FREE_DAY = 100                                      # ücretsiz modeller: kişi başı günde 100 soru (toplam)
AI_TIER = {"opus": "danger", "gpt": "danger", "kimi": "primary", "grok": "primary", "gemini": "primary", "mistral": "success", "mimo": "success", "nemotron": "success"}   # 🔴 en güçlü · 🔵 güçlü · 🟢 hızlı/hafif
AIPRO_USDT, AIPRO_DAYS = 5, 30           # 💎 AI Premium: aylık 5$ (CryptoBot / bakiye)
AI_FREE_N, AI_FREE_WIN = 3, 2 * 86400    # abone olmayana: 2 günde 3 soru (bütün modeller toplam)
AI_PRO_LIMIT = 50                        # aboneye sitenin 5 saatlik limit penceresi başına (Admin'den değişir)
AI_VISION = {"opus", "gpt", "gemini", "grok", "kimi", "mimo"}   # fotoğraf görebilen modeller (Mistral, Nemotron göremiyor)
AI_WIN = {"end": 0, "ts": 0, "usage": None}
def ai_window():
    """Sitenin (xKiro) 5 saatlik harcama penceresinin bitişi; abone hakları bununla birlikte sıfırlanır."""
    now = time.time()
    if now - AI_WIN["ts"] > 300 or now >= AI_WIN["end"]:
        AI_WIN["ts"] = now
        try:
            u = _xk("/v1/usage", timeout=10); AI_WIN["usage"] = u
            w = next((x for x in u.get("windows", []) if x.get("kind") == "short"), None)
            if w:
                end = now + int(w.get("resets_in_sec") or w.get("window_sec") or 18000)
                idle = float(w.get("spent_usd") or 0) == 0
                if now >= AI_WIN["end"] or (not idle and abs(end - AI_WIN["end"]) > 600): AI_WIN["end"] = end
        except Exception as e: log.info("usage: %s", e)
    if now >= AI_WIN["end"]: AI_WIN["end"] = (int(now // 18000) + 1) * 18000   # bilgi yoksa sabit 5 saatlik dilimler
    return int(AI_WIN["end"])
def ai_pro_limit(db=None):
    try: return int((db if db is not None else load_db()).get("ai_pro_limit") or AI_PRO_LIMIT)
    except Exception: return AI_PRO_LIMIT
def ai_free_left(x):
    fr = [t for t in x.get("ai_free", []) if t > time.time() - AI_FREE_WIN]
    return max(0, AI_FREE_N - len(fr)), (min(fr) + AI_FREE_WIN if len(fr) >= AI_FREE_N else None)
def ai_is_pro(x): return x.get("ai_pro_until", 0) > time.time()

def ai_pro_used(x, win): return x.get("ai_pn", 0) if x.get("ai_pwin") == win else 0

def ai_fm_used(x):
    return x.get("ai_fn", 0) if x.get("ai_fday") == tm_day() else 0

def ai_take(d, uid, win=0, mk=None):
    """Modelli soru hakkı düşer. Dönüş: 'admin' | 'pro' | 'free' | 'lock' | 'plim' | 'fm' | 'flim'."""
    x = d["users"].setdefault(str(uid), {})
    if uid in ADMINS: return "admin"
    if mk in AI_FREEM:   # 🆓 ücretsiz model: günlük sınır
        if ai_fm_used(x) >= AI_FREE_DAY: return "flim"
        x["ai_fday"], x["ai_fn"] = tm_day(), ai_fm_used(x) + 1; return "fm"
    if ai_is_pro(x):
        if x.get("ai_pwin") != win: x["ai_pwin"], x["ai_pn"] = win, 0
        if x["ai_pn"] >= ai_pro_limit(d): return "plim"
        x["ai_pn"] += 1; return "pro"
    if ai_free_left(x)[0] <= 0: return "lock"
    x["ai_free"] = [t for t in x.get("ai_free", []) if t > time.time() - AI_FREE_WIN] + [time.time()]; return "free"

def ai_give_back(d, uid, kind):
    x = d["users"].setdefault(str(uid), {})
    if kind == "pro": x["ai_pn"] = max(0, x.get("ai_pn", 1) - 1)
    elif kind == "fm": x["ai_fn"] = max(0, x.get("ai_fn", 1) - 1)
    elif kind == "free" and x.get("ai_free"): x["ai_free"].pop()

IMG_TOOL = {"name": "generate_image", "description": "Create an image. Call ONLY when the user explicitly asks you to create/draw/generate a picture or photo. Write a detailed English prompt.",
            "input_schema": {"type": "object", "properties": {"prompt": {"type": "string", "description": "Detailed English description of the image"}}, "required": ["prompt"]}}

def ai_system_model(lang, name, mid, can_img=False, vision=False):
    lname = {"tk": "Türkmen dili", "ru": "русский"}.get(lang, "Türkçe")
    return f"""Sen {name} modelisin (kimlik: {mid}). Hangi model olduğun sorulursa bunu söyle.
Her konuda yardım edersin: genel sorular, kod yazma, hata ayıklama, ödev/ders, metin yazma, çeviri, fikir.
- Kullanıcının yazdığı dilde cevap ver (varsayılan: {lname}).
- Doğru ol; emin olmadığın bilgiyi uydurma, emin değilsen söyle.
{"- Kullanıcı açıkça resim/fotoğraf oluşturmanı isterse generate_image aracını ayrıntılı İngilizce prompt ile çağır; başka hiçbir durumda çağırma. Video ve ses oluşturamazsın." if can_img else "- Fotoğraf, video veya ses oluşturamazsın; istenirse bu sohbette sadece yazıyla yardım edebildiğini söyle."}
{"- Kullanıcının gönderdiği fotoğrafları görebilir ve ayrıntılı analiz edebilirsin." if vision else "- Fotoğraf göremezsin; fotoğraf gönderilirse fotoğraf görebilen bir model seçmesini söyle."}
- Kod istenirse çalışır ve eksiksiz kod ver, ``` kod bloklarını kullan. Gereksiz uzatma.
- Biçim Telegram içindir: sadece ``` kod blokları, `satır içi kod` ve **kalın** kullan; başlık (#) veya tablo kullanma."""

AI_DIR = os.environ.get("AI_DIR", "/root/ai_chats")   # her kullanıcının sohbetleri: <uid>.json
AI_CTX_CHARS = 120_000           # bir isteğe gönderilen geçmiş üst sınırı (~30 bin token); daha eskisi kayıtta durur
AI_MAX_CHATS, AI_MAX_MSGS = 50, 400
AI_FLOCK = threading.Lock()
def _aif(uid): return os.path.join(AI_DIR, f"{int(uid)}.json")
def ai_load(uid):
    try:
        with open(_aif(uid), encoding="utf-8") as f: return json.load(f)
    except Exception: return {"chats": {}, "cur": {}}
def ai_save(uid, data):
    os.makedirs(AI_DIR, exist_ok=True)
    with open(_aif(uid) + ".tmp", "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False)
    os.replace(_aif(uid) + ".tmp", _aif(uid))
def ai_cur(uid, mk):
    d = ai_load(uid); cid = d.get("cur", {}).get(mk)
    return cid if cid in d.get("chats", {}) else None
def ai_context(uid, cid, max_chars=AI_CTX_CHARS):
    """Sohbetin mesajları (en yeniden geriye, sınıra kadar) → API biçimi."""
    ch = ai_load(uid).get("chats", {}).get(cid) if cid else None
    out, n = [], 0
    for x in reversed((ch or {}).get("msgs", [])):
        n += len(x["c"])
        if n > max_chars and out: break
        out.append({"role": x["r"], "content": x["c"]})
    out.reverse()
    while out and out[0]["role"] != "user": out.pop(0)   # API ilk mesajı kullanıcıdan ister
    return out
def ai_append(uid, mk, cid, q, ans):
    """Soru + cevabı kaydeder (sohbet yoksa açar). Dönüş: sohbet no."""
    with AI_FLOCK:
        d = ai_load(uid); chats = d.setdefault("chats", {}); now = time.time()
        if not cid or cid not in chats:
            cid = uuid.uuid4().hex[:8]
            chats[cid] = {"m": mk, "t": " ".join(q.split())[:40], "ts": now, "msgs": []}
        ch = chats[cid]; ch["u"] = now
        ch["msgs"] += [{"r": "user", "c": q, "ts": now}, {"r": "assistant", "c": ans, "ts": now}]
        ch["msgs"] = ch["msgs"][-AI_MAX_MSGS:]
        d.setdefault("cur", {})[mk] = cid
        for old in sorted(chats, key=lambda k: chats[k].get("u", 0))[:-AI_MAX_CHATS]: chats.pop(old, None)
        ai_save(uid, d)
    return cid

IMG_MODEL = "openai/gpt-image-2.5"
def _xk(path, body=None, timeout=60):
    req = urllib.request.Request(ai_base() + path, data=json.dumps(body).encode("utf-8") if body is not None else None,
                                 headers={"Authorization": "Bearer " + ai_key(), "content-type": "application/json", "User-Agent": "subbot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception: msg = ""
        raise RuntimeError(f"HTTP {e.code} {msg}"[:200])
def img_fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "subbot/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r: return r.read()

def ai_call(system, msgs, key=None, max_tokens=4000, timeout=120, model=None):
    """Tek istek. Dönüş: cevap yazısı. Hata: RuntimeError."""
    j = ai_req(system, msgs, key, max_tokens, timeout, model)
    txt = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text").strip()
    if not txt: raise RuntimeError("boş cevap")
    return txt

def ai_req(system, msgs, key=None, max_tokens=4000, timeout=120, model=None, tools=None):
    """Ham /v1/messages cevabı (içerik blokları: text / tool_use)."""
    body = {"model": model or ai_model(), "max_tokens": max_tokens, "system": system, "messages": msgs}
    if tools: body["tools"] = tools
    req = urllib.request.Request(ai_base() + "/v1/messages", data=json.dumps(body).encode("utf-8"),
                                 headers={"x-api-key": key or ai_key(), "anthropic-version": "2023-06-01", "content-type": "application/json", "User-Agent": "subbot/1.0"})   # varsayılan Python UA'sını Cloudflare engelliyor (1010)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: j = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try: msg = json.loads(e.read().decode("utf-8")).get("error", {}).get("message", "")
        except Exception: msg = ""
        raise RuntimeError(f"HTTP {e.code} {msg}"[:200])
    return j

async def gen_image(prompt_):
    """Fotoğraf oluşturur (geçici hata olursa bir kez daha dener). Dönüş: (png bayt, iş no). Hata: RuntimeError('blocked' / sebep)."""
    last = "?"
    for _ in range(2):
        job = await asyncio.to_thread(_xk, "/v1/images/generations", {"model": IMG_MODEL, "prompt": prompt_[:3000], "n": 1, "size": "1024x1024"})
        jid, t0, w, res = job.get("id"), time.time(), 2, job
        while res.get("status") == "processing" and time.time() - t0 < 300:
            await asyncio.sleep(w); w = min(10, w * 1.5)
            res = await asyncio.to_thread(_xk, f"/v1/images/generations/{jid}")
        if res.get("status") == "succeeded" and res.get("data"):
            return await asyncio.to_thread(img_fetch, res["data"][0]["url"]), jid
        if res.get("status") == "blocked": raise RuntimeError("blocked")
        err = res.get("error"); last = (err.get("message") if isinstance(err, dict) else err) or res.get("status") or "?"
    raise RuntimeError(str(last))

def _plain(t):
    return html.unescape(re.sub(r"<[^>]+>", "", t))

# Botun yenilikleri: her güncellemede en üste eklenir; AI (yardımcı + destek) bunları bilir.
CHANGELOG = [
 ("30.10", "🤖 Kömekçi: 4 ücretsiz model (Qwen3.8 Max, Qwen3.8 Omni Flash, Mistral Large 3, Command A+), herkese günde 100 soru, Premium gerekmez."),
 ("29.10", "📡 Telegram Proxy: Türkmenistan'dan test edilmiş, çalışan Telegram proxy'leri ücretsiz (menüde). Kapanınca yenileri gelir."),
 ("29.10", "Pazar: 18+ / uygunsuz fotoğraflı ilan anında reddedilir ve son uyarı verilir; tekrarlayan otomatik banlanır."),
 ("29.10", "Pazar: ilan fotoğrafını AI otomatik kontrol eder (gerçek testle uyuşmazsa fotoğraf gösterilmez); 5'ten fazla çalışmayan sunucusu olan ilan reddedilir."),
 ("29.10", "İlan fotoğrafları (uzun ekran görüntüleri) kırpılmadan tam görünür."),
 ("29.10", "Bazar/Pazar ilan kartı yeni sade tasarım: hizalı fiyat tablosu, ayraçlar."),
 ("28.10", "Destekte cevapları bot sahibi adına veren asistan; kullanıcının eski talepleri hatırlanır."),
 ("28.10", "Destek: ✍️ Ýaz'a bir kez basılır, talep kapanana kadar yazılabilir; mesajlar arası 5 sn."),
 ("28.10", "🤖 Kömekçi: 8 yapay zekâ modeli (Claude Opus, GPT, Gemini, Grok, Kimi, Mistral, MiMo, Nemotron); 2 günde 3 ücretsiz soru, 💎 Premium 5$/ay (her 5 saatte 50 soru); fotoğraf analizi; 📜 sohbet geçmişi."),
 ("28.10", "Market'te 💰 Bakiyeden öde ve 🎁 Bonusdan töle (7/30 günlük kod); davet başına 0.25 TMT bonus."),
 ("28.10", "Bakiye yükleme en az 0.1 USDT; kazanç çekme en az 1 USDT."),
 ("27.10", "Pazar: Satın Al / VIP / ilan silme önce onay sorar; kendi ilanını satın alamazsın; ilan fotoğrafları tam görünür."),
]
AI_NOTES_MAX = 40

def ai_extra(db=None):
    """Yenilikler + sahibinin elle eklediği bilgiler (AI bunları kesin bilgi sayar)."""
    db = db if db is not None else load_db()
    out = "YENİLİKLER (en yeni üstte):\n" + "\n".join(f"- {d}: {t}" for d, t in CHANGELOG[:12])
    notes = db.get("ai_notes", [])
    if notes: out += "\n\nSAHİBİNİN EKLEDİĞİ BİLGİLER (kesin doğru kabul et):\n" + "\n".join(f"- {n_['t']}" for n_ in notes[-AI_NOTES_MAX:])
    return out

def ai_system(lang):
    """Botun GERÇEK bilgileri (koddaki değerlerden) + kurallar. Model sadece bunlara dayanır."""
    b = lambda k: re.sub(r"\s*\([^()]*\{\w+\}[^()]*\)|\{\w+\}", "", T[lang].get(k) or T["tr"].get(k, k)).strip()
    lname = {"tk": "Türkmen dili (Turkmen)", "ru": "русский (Russian)"}.get(lang, "Türkçe (Turkish)")
    tmt = lambda um: f"{um * USDT_RATE / UM:.2f}".rstrip("0").rstrip(".")
    facts = f"""BOT: @{BOT.get('un') or 'SuBDrive_bot'} — Türkmenistan için VPN kodları (Happ uygulamasında abonelik linki olarak çalışır).
KUR: 1 USDT = {USDT_RATE} TMT. Ödemeler CryptoBot (USDT) ile, otomatik onaylanır. TMT ile ödeme henüz yok (yakında).
USDT almak için (TMT karşılığı) satıcılar: {', '.join(USDT_SELLERS)}.

ANA MENÜ BUTONLARI: {b('b_pazar')} · {b('b_free')} · {b('b_mine')} · {b('b_prof')} · {b('b_market')} · {b('b_sup')} · {b('b_bug')} · {b('b_ai')} · {b('b_set')}

ÜCRETSİZ KOD ({b('b_free')}): {REF_NEED} yeni arkadaş davet edince {FREE_DAYS} günlük ücretsiz kod. Günde en fazla 1 ücretsiz kod. Davet linki Profil'de; "{b('b_share')}" butonu bannerli reklamı seçilen sohbete gönderir (kendi davet linkiyle). Davet edilen kişi doğrulamayı geçince sayılır.
DAVET BONUSU: her sayılan davet için {tmt(REF_BONUS)} TMT bonus. Bonus Market'te 7/30 günlük kod alırken "{b('b_pbon')}" butonuyla kullanılır.

MARKET ({b('b_market')}) — botun kendi kodları:
{_plain(b('market'))}
PANEL: kendi kullanıcıların için kod oluşturup yönetebileceğin panel. Kullanıcı başı {PANEL_PRICE} TMT, en az {PANEL_MIN} kullanıcı, {PANEL_DAYS} gün geçerli. Süre bitmeden tekrar alınırsa kullanıcı sayısı eklenir ve süre {PANEL_DAYS} gün uzar. Onaydan sonra /start yazınca panel açılır. Bonus panelde kullanılmaz.
Kodların protokolleri sunuculara göre değişir (VLESS, Hysteria, Shadowsocks vb.); hepsi Happ'te abonelik linkiyle çalışır.
Sipariş ekranında: "{b('b_pbal')}" (profil bakiyesiyle, hemen teslim), "{b('b_usdt')}" (CryptoBot faturası), kod siparişlerinde "{b('b_pbon')}".

BAKİYE: Profil → "{b('b_top')}". Hazır tutarlar 1/3/5/10 USDT ya da başka tutar (en az {TOPUP_MIN} USDT). Ödeme CryptoBot'ta yapılır, bot ödemeyi kendisi görür.

PAZAR ({b('b_pazar')}) — satıcıların kodları, dakika başı ödeme:
{_plain(b('rules'))}
Alıcı: ilanı seç → "Satın Al" → onay. Başlatma {fmt_u(MKT_FEE)}$ + ilk {PREPAY_MIN // 60} saat peşin (iade edilmez), sonra her dakika bakiyeden düşer. Durdurmak: {b('b_mine')} → ⏹. Aynı ilan 24 saatte en fazla {MAX_STARTS_DAY} kez başlatılır. Bakiye bitince kod durur.
Satıcı: Pazar → "{b('b_sell')}" (5 adım: abonelik linki, başlık, ekran görüntüsü, açıklama, fiyat). İlan ücreti {fmt_u(MKT_FEE)}$. Abonelik GB ve süre sınırsız olmalı. Kendi ilanını satın alamazsın. İlanlar telefonla Türkmenistan'dan test edilir ve admin onaylar. 💎 VIP: {fmt_u(VIP_FEE)}$ ile {VIP_HOURS} saat en üstte. İlanlarım → kullanım geçmişi, VIP, sil (sorulur).
KAZANÇ ÇEKME: Profil → "{b('b_wd')}", en az {fmt_u(WITHDRAW_MIN)} USDT, CryptoBot hesabına gider (@CryptoBot'u en az bir kez açmış olmak gerekir). Kazanç alıcı durdurunca ya da her 24 saatte satıcıya geçer. Yüklenen bakiye çekilemez, sadece satış kazancı çekilir.

KODLARIM ({b('b_mine')}): aktif kodlar ve abonelik linkleri. Kullanım: linki kopyala → Happ uygulaması → sağ üstteki + → panodan ekle (ya da linke dokun). Kodlar düzenli kontrol edilir; Happ'te aboneliği yenile (↻) ile güncel sunucular gelir.
DESTEK: {b('b_sup')} ya da {b('b_bug')} → "✍️" butonu (bir kez) → yazı/fotoğraf/video gönder, talep kapanana kadar yazılabilir. 5 saniyede tek mesaj, hepsini tek mesajda yaz. Admin cevabı aynı sohbete gelir.
DİL: {b('b_set')} → Türkçe / Türkmençe / Rusça."""
    return f"""Sen @{BOT.get('un') or 'SuBDrive_bot'} Telegram botunun yardımcısısın. Kullanıcıların bot hakkındaki sorularını cevaplarsın.

KURALLAR:
- Cevabı HER ZAMAN şu dilde yaz: {lname}. Kullanıcı başka dilde yazarsa onun dilinde cevap ver.
- SADECE aşağıdaki BİLGİLER'e dayan. Orada olmayan bir şeyi (fiyat, süre, özellik, tarih, kişi) asla uydurma veya tahmin etme. Emin değilsen bunu açıkça söyle ve kullanıcıyı "{b('b_sup')}" butonuna yönlendir.
- Butonları tam adlarıyla, adım adım anlat.
- Kısa ve net yaz (en fazla ~10 satır). Düz metin ve emoji kullan; HTML, Markdown, ** veya # kullanma.
- Admin paneli, sunucu altyapısı, kodların kaynağı, test sistemi, diğer kullanıcılar veya gizli bilgiler hakkında bilgi verme.
- Bot dışı konularda (genel sohbet, ödev vb.) kibarca sadece bot konusunda yardım ettiğini söyle.
- Hesap/ödeme sorunu, para kaybı, bozuk kod gibi kişisel durumlarda çözümü tahmin etme; {b('b_sup')}'a yazmasını söyle.

BİLGİLER:
{facts}

{ai_extra()}"""

def md_tg(t):
    """Model cevabı (```kod```, `kod`, **kalın**) → Telegram HTML parçaları (her biri ≤ ~3800 karakter)."""
    parts, out, cur = re.split(r"```[\w+#.-]*\n?(.*?)```", t, flags=re.S), [], ""
    def text_html(x):
        x = esc(x)
        x = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", x)
        return re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", x)
    def push(piece):
        nonlocal cur
        if len(cur) + len(piece) > 3800 and cur: out.append(cur); cur = ""
        cur += piece
    for i, x in enumerate(parts):
        if i % 2:   # kod bloğu
            lines, buf = x.rstrip("\n").split("\n"), ""
            for ln in lines:
                if buf and len(esc(buf)) + len(esc(ln)) > 3600: push("<pre>" + esc(buf.rstrip("\n")) + "</pre>"); buf = ""
                buf += ln + "\n"
            if buf: push("<pre>" + esc(buf.rstrip("\n")) + "</pre>")
        else:
            for para in re.split(r"(\n)", x):
                while len(para) > 2500: push(text_html(para[:2500])); para = para[2500:]
                push(text_html(para))
    if cur.strip(): out.append(cur)
    return out or ["…"]

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
    kb = KB([[B(tr(lang, "b_pazar"), "u_mkt", "success")], [B(tr(lang, "b_ai"), "u_ai", "primary")]] + open_mkt_row(db, uid, lang) + [[B(tr(lang, "b_px"), "u_px")],
             [B(tr(lang, "b_free"), "u_free"), B(tr(lang, "b_mine"), "u_mine")],
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

async def ticket_cmd_ask(u):
    """Açık talep varken komut yazıldı: önce talebi kapatmak isteyip istemediği sorulur. Soruldu ise True."""
    uid = u.effective_user.id
    if uid in ADMINS or is_banned(uid): return False
    db_ = load_db(); tid = open_ticket(db_, uid)
    if not tid: return False
    lang_ = lang_of(db_, uid)
    await u.message.reply_text(tr(lang_, "sup_cmd_q", tid=tid), parse_mode="HTML",
                               reply_markup=KB([[B(tr(lang_, "b_tclose_yes"), "u_tclose", "danger")], [B(tr(lang_, "b_tkeep"), "u_tw", "primary")]]))
    return True

async def other_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    if u.message and u.effective_user and u.message.chat.type == "private": await ticket_cmd_ask(u)

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
        await bsend(kind, tr(lang, key, tid=tid), KB([[B(tr(lang, "b_twrite"), "u_tw", "primary")], [B(tr(lang, "b_tclose"), "u_tclose", "danger")], [B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_tw":   # ✍️ Yaz: bir kez basınca talep kapanana kadar yazılanlar talebe gider
        tid = open_ticket(load_db(), uid)
        if not tid: await send(tr(lang, "sup_closed", tid="—"), KB([[B(tr(lang, "b_menu"), "u_menu")]])); return
        STATE.pop(uid, None); mutate(lambda d: d["tickets"][tid].__setitem__("armed", True))
        await send(tr(lang, "sup_ask"), KB([[B(tr(lang, "b_cancel"), "u_twx")]]))

    elif a == "u_twx":   # ✍️ iptal: yazma kapanır (talep açık kalır)
        tid_ = open_ticket(load_db(), uid)
        if tid_: mutate(lambda d: d["tickets"][tid_].pop("armed", None))
        STATE.pop(uid, None)
        await show_home(c, uid, getattr(q, "message", None), send=send)

    elif a == "u_px":   # 📡 Türkmenistan'da test edilmiş Telegram proxy'leri
        await send(*px_user_view(lang))

    elif a == "u_ai":   # 🤖 ekranı: ❓ bot yardımcısı (ücretsiz) + modeller (💎 abonelik / 2 günde 3 ücretsiz soru)
        if not ai_key(): await send(tr(lang, "ai_off"), menu_btn); return
        STATE.pop(uid, None)
        own_, pro_ = uid in ADMINS, ai_is_pro(e); left_, when_ = ai_free_left(e)
        if own_: st_l = tr(lang, "ai_st_own")
        elif pro_:
            win_ = await asyncio.to_thread(ai_window)
            st_l = tr(lang, "ai_st_pro", until=tm_fmt(e["ai_pro_until"]), n=max(0, ai_pro_limit(db) - ai_pro_used(e, win_)), lim=ai_pro_limit(db), r=tm_fmt(win_)[-5:])
        else: st_l = tr(lang, "ai_st_free", n=left_, w=(tm_fmt(when_) if when_ else "—"))
        lock = not (own_ or pro_) and left_ <= 0
        dot = {"danger": "🔴", "primary": "🔵", "success": "🟢"}
        body = tr(lang, "ai_legend") + "\n" + "\n".join(f"{dot.get(AI_TIER.get(k_), '⚪️')} <b>{n_}</b> — {d_.get(lang, d_['tr'])}" + (" · 📷" if k_ in AI_VISION else "") for k_, (n_, _, d_) in AI_MODELS.items() if k_ not in AI_FREEM)
        body += "\n\n" + tr(lang, "ai_fm_t", n=AI_FREE_DAY) + "\n" + "\n".join(f"⚪️ <b>{n_}</b> — {d_.get(lang, d_['tr'])}" for k_, (n_, _, d_) in AI_MODELS.items() if k_ in AI_FREEM)
        mb = [B(("🔒 " if lock else "") + n_, f"u_aim:{k_}", AI_TIER.get(k_)) for k_, (n_, _, _) in AI_MODELS.items() if k_ not in AI_FREEM]
        fb = [B(n_, f"u_aim:{k_}") for k_, (n_, _, _) in AI_MODELS.items() if k_ in AI_FREEM]   # 🆓 renksiz
        rows = [mb[i:i + 2] for i in range(0, len(mb), 2)] + [[B(tr(lang, "b_ai_bot"), "u_aib")]] + [fb[i:i + 2] for i in range(0, len(fb), 2)]
        rows.append([B(tr(lang, "b_ai_hist"), "u_aih")])
        if not (own_ or pro_): rows.append([B(tr(lang, "b_aipro", usdt=AIPRO_USDT), "u_aipro", "primary")])
        await send(tr(lang, "ai_menu", st=st_l, body=body), KB(rows + [[B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_aib":   # ❓ bot hakkında (ücretsiz, günlük sınırlı)
        if not ai_key(): await send(tr(lang, "ai_off"), menu_btn); return
        STATE[uid] = {"action": "ai"}
        left = "∞" if uid in ADMINS else max(0, ai_limit(db) - (e.get("ai_n", 0) if e.get("ai_day") == tm_day() else 0))
        await send(tr(lang, "ai_hi", n=left), KB([[B(tr(lang, "b_ai_models"), "u_ai")], [B(tr(lang, "b_ai_end"), "u_aix")]]))

    elif a.startswith("u_aim:"):   # model seç
        k_ = a.split(":", 1)[1]; M_ = AI_MODELS.get(k_)
        if not M_ or not ai_key(): await send(tr(lang, "ai_off"), menu_btn); return
        if k_ not in AI_FREEM and not (uid in ADMINS or ai_is_pro(e)) and ai_free_left(e)[0] <= 0:
            await send(tr(lang, "aipro_info", usdt=AIPRO_USDT, days=AIPRO_DAYS, n=ai_pro_limit(db), f=AI_FREE_N),
                       KB([[B(tr(lang, "b_aipro_buy", usdt=AIPRO_USDT), "u_buy:aipro", "success")], [B(tr(lang, "b_ai_models"), "u_ai")]])); return
        cid_ = ai_cur(uid, k_)
        STATE[uid] = {"action": "ai", "model": k_, "cid": cid_}
        left_ = "∞" if uid in ADMINS else f"{max(0, AI_FREE_DAY - ai_fm_used(e))}/{AI_FREE_DAY}" if k_ in AI_FREEM else (f"{max(0, ai_pro_limit(db) - ai_pro_used(e, await asyncio.to_thread(ai_window)))}/{ai_pro_limit(db)}" if ai_is_pro(e) else f"{ai_free_left(e)[0]}/{AI_FREE_N}")
        ttl_ = (ai_load(uid)["chats"][cid_]["t"] if cid_ else "")
        await send(tr(lang, "ai_pick", name=M_[0], d=M_[2].get(lang, M_[2]["tr"]) + (" · 📷" if k_ in AI_VISION else ""), n=left_) + (("\n" + tr(lang, "ai_cont", t=esc(ttl_))) if cid_ else ""),
                   KB([[B("🧹 " + tr(lang, "b_ai_new"), f"u_ain:{k_}"), B(tr(lang, "b_ai_hist"), "u_aih")], [B(tr(lang, "b_ai_models"), "u_ai"), B(tr(lang, "b_ai_end"), "u_aix")]]))

    elif a.startswith("u_ain:"):   # 🧹 yeni sohbet (eskisi Geçmiş'te kalır)
        k_ = a.split(":", 1)[1]; M_ = AI_MODELS.get(k_)
        if not M_: return
        STATE[uid] = {"action": "ai", "model": k_, "cid": None}
        await send(tr(lang, "ai_new_ok", name=M_[0]), KB([[B(tr(lang, "b_ai_hist"), "u_aih"), B(tr(lang, "b_ai_models"), "u_ai")], [B(tr(lang, "b_ai_end"), "u_aix")]]))

    elif a == "u_aih":   # 📜 geçmiş sohbetler
        STATE.pop(uid, None)
        ch_ = ai_load(uid).get("chats", {})
        lst = sorted(ch_.items(), key=lambda x: -x[1].get("u", 0))[:15]
        nm = lambda m_: AI_MODELS[m_][0].split()[-2] if m_ in AI_MODELS else "❓"
        rows = [[B(f"{'🧠' if v.get('m') in AI_MODELS else '❓'} {nm(v.get('m'))} · {short(v.get('t') or '…', 22)} · {datetime.datetime.fromtimestamp(v.get('u', 0), TM_TZ):%d.%m}", f"u_aic:{k}")] for k, v in lst]
        await send(tr(lang, "ai_hist_t", n=len(ch_)) if lst else tr(lang, "ai_hist_none"), KB(rows + [[B(tr(lang, "b_ai_models"), "u_ai")]]))

    elif a.startswith("u_aic:"):   # bir sohbetin yazışmaları
        cid_ = a.split(":", 1)[1]; v = ai_load(uid).get("chats", {}).get(cid_)
        if not v: await send(tr(lang, "ai_hist_none"), KB([[B(tr(lang, "b_ai_hist"), "u_aih")]])); return
        lines, n_ = [], 0
        for x in reversed(v.get("msgs", [])):
            ln = ("👤 " if x["r"] == "user" else "🤖 ") + esc(short(" ".join(x["c"].split()), 300))
            n_ += len(ln)
            if n_ > 3000: break
            lines.append(ln)
        mname = AI_MODELS[v["m"]][0] if v.get("m") in AI_MODELS else tr(lang, "b_ai_bot")
        await send(f"📜 <b>{esc(v.get('t') or '…')}</b>\n<i>{esc(mname)} · {len(v.get('msgs', [])) // 2} {tr(lang, 'ai_q')}</i>\n<blockquote expandable>" + "\n\n".join(reversed(lines)) + "</blockquote>",
                   KB([[B(tr(lang, "b_ai_go"), f"u_aig:{cid_}", "success")], [B(tr(lang, "b_ai_del"), f"u_aid:{cid_}", "danger"), B(tr(lang, "b_ai_hist"), "u_aih")]]))

    elif a.startswith("u_aig:"):   # ▶️ sohbete devam
        cid_ = a.split(":", 1)[1]; v = ai_load(uid).get("chats", {}).get(cid_)
        if not v or not ai_key(): return
        mk_ = v.get("m")
        if mk_ in AI_MODELS and mk_ not in AI_FREEM and not (uid in ADMINS or ai_is_pro(e)) and ai_free_left(e)[0] <= 0:
            await send(tr(lang, "aipro_info", usdt=AIPRO_USDT, days=AIPRO_DAYS, n=ai_pro_limit(db), f=AI_FREE_N),
                       KB([[B(tr(lang, "b_aipro_buy", usdt=AIPRO_USDT), "u_buy:aipro", "success")], [B(tr(lang, "b_ai_hist"), "u_aih")]])); return
        STATE[uid] = {"action": "ai", "model": mk_ if mk_ in AI_MODELS else None, "cid": cid_}
        await send(tr(lang, "ai_cont", t=esc(v.get("t") or "…")) + "\n<i>" + tr(lang, "ai_text") + "</i>", KB([[B(tr(lang, "b_ai_hist"), "u_aih"), B(tr(lang, "b_ai_end"), "u_aix")]]))

    elif a.startswith("u_aid:"):   # 🗑 sil: önce sor
        cid_ = a.split(":", 1)[1]
        await send(tr(lang, "ai_del_q"), KB([[B(tr(lang, "b_ai_del"), f"u_aidy:{cid_}", "danger")], [B(tr(lang, "b_no"), f"u_aic:{cid_}")]]))

    elif a.startswith("u_aidy:"):
        cid_ = a.split(":", 1)[1]
        def rm_():
            with AI_FLOCK:
                d_ = ai_load(uid); d_.get("chats", {}).pop(cid_, None)
                d_["cur"] = {k: v for k, v in d_.get("cur", {}).items() if v != cid_}; ai_save(uid, d_)
        await asyncio.to_thread(rm_)
        await send(tr(lang, "ai_deleted"), KB([[B(tr(lang, "b_ai_hist"), "u_aih"), B(tr(lang, "b_ai_models"), "u_ai")]]))

    elif a == "u_aipro":
        await send(tr(lang, "aipro_info", usdt=AIPRO_USDT, days=AIPRO_DAYS, n=ai_pro_limit(db), f=AI_FREE_N),
                   KB([[B(tr(lang, "b_aipro_buy", usdt=AIPRO_USDT), "u_buy:aipro", "success")], [B(tr(lang, "b_ai_models"), "u_ai")]]))

    elif a == "u_aix":
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
                                               "price": st_["price"], "codes": st_["codes"], "codes_ts": time.time(), "status": "pending", "created": time.time(), "photo_ok": False, "pad_ok": True}
            return lid
        r = mutate(f); new_lid = r if r not in ("nobal", "dup", "ban") else None
        if r == "nobal": await send(tr(lang, "sell_nobal").replace("0.05$", fmt_u(seller_fee(load_db()["users"].get(str(uid), {}))) + "$"), KB([[B(tr(lang, "b_top"), "u_top", "success")], [B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        STATE.pop(uid, None)
        if r == "dup": await send(tr(lang, "sell_dup"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        if r == "ban": await send(tr(lang, "sell_banned", left="—"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        ulog("m_list", f"📤 Pazara ilan verdi: {who(user)} · {st_['title']} · {fmt_u(st_['price'])} USDT/dk")
        await send(tr(lang, "sell_sent"), KB([[B(tr(lang, "b_myl"), "u_myl")], [B(tr(lang, "b_back_mkt"), "u_mkt")]]))
        cap_ = (f"📤 <b>Yeni pazar ilanı</b> (incelemede)\n<blockquote>{esc(who(user))}\n🏷 {esc(st_['title'])} · {money_tmt(float(st_['price']) * 43200)} TMT/ay</blockquote>\n"
                "<i>⏳ Telefon testi bekleniyor. 🤖 AI fotoğrafı kontrol ediyor; onaylanana kadar pazarda fotoğrafsız görünür.</i>")
        asyncio.ensure_future(ai_photo_precheck(c.application, new_lid))
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
    if o["item"] == "aipro": return f"AI Premium · {AIPRO_DAYS} gün"
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
    elif item == "aipro": price, it = AIPRO_USDT * USDT_RATE, tr(lang, "it_aipro")
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
    elif o["item"] == "aipro":   # 💎 AI Premium: süre eklenir
        def p(d):
            x = d.setdefault("users", {}).setdefault(str(uid), {})
            x["ai_pro_until"] = max(time.time(), x.get("ai_pro_until", 0)) + AIPRO_DAYS * 86400
            d["orders"][oid]["status"] = "done"; d["orders"][oid]["done_ts"] = time.time()
            return x["ai_pro_until"]
        msg = tr(lang, "aipro_ok", until=tm_fmt(mutate(p)), n=ai_pro_limit())
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

def ai_view():
    on = bool(ai_key())
    db = load_db(); today = sum(x.get("ai_n", 0) for x in db.get("users", {}).values() if x.get("ai_day") == tm_day())
    if on:
        try: ai_window()
        except Exception: pass
    us = AI_WIN.get("usage") or {}
    site = "\n".join(f"🌐 Site {'5 saat' if w.get('kind') == 'short' else '7 gün'}  <b>${float(w.get('spent_usd', 0)):.2f} / ${float(w.get('cap_usd', 0)):.0f}</b> · yenilenme {datetime.datetime.fromtimestamp(time.time() + int(w.get('resets_in_sec', 0)), TM_TZ):%d.%m %H:%M}" for w in us.get("windows", []))
    t = ("🤖 <b>AI Yardımcı</b>\n<blockquote>" + ("🟢 Bağlı" if on else "⚪️ Bağlı değil — kullanıcılar butonu görür ama kapalı der") +
         f"\n🌐 <code>{esc(ai_base())}</code>\n🧠 Bot yardımcısı: <code>{esc(ai_model())}</code> · {len(AI_MODELS)} model seçilebilir\n🔢 Bot yardımcısı  <b>{ai_limit(db)}</b> soru/gün\n💎 Premium  <b>{AIPRO_USDT}$</b>/{AIPRO_DAYS} gün · <b>{ai_pro_limit(db)}</b> soru / site 5 saati · abone <b>{sum(1 for x in db.get('users', {}).values() if ai_is_pro(x))}</b>\n🎁 Ücretsiz: 2 günde {AI_FREE_N} soru\n📊 Bugün bot yardımcısı  <b>{today}</b> soru" + (("\n" + site) if site else "") + "</blockquote>"
         + (f"\n⚠️ Son hata: <code>{esc(RUN.get('ai_err', ''))}</code>" if RUN.get("ai_err") else ""))
    sup_on, mon_on = db.get("ai_sup", True), db.get("ai_mon", True)
    t += f"\n🎫 Support'a AI ilk cevap: <b>{'açık' if sup_on else 'kapalı'}</b>\n🛡 Log izleme (Haiku, 5 dk): <b>{'açık' if mon_on else 'kapalı'}</b>" + (f" · son: {esc(RUN['ai_mon_last'])}" if RUN.get("ai_mon_last") else "")
    return t, KB([[B("📊 Site Kullanımı", "ai_use", "success")],
                  [B(f"🎫 Support AI: {'🟢' if sup_on else '🔴'}", "ai_tsup"), B(f"🛡 Log izleme: {'🟢' if mon_on else '🔴'}", "ai_tmon")],
                  [B(f"📝 AI Bilgileri ({len(db.get('ai_notes', []))})", "ai_notes"), B(f"🎓 Öğrendikleri ({len(db.get('ai_learn', []))})", "ai_learnv")],
                  [B("🔑 Anahtar Gir", "ai_set", "primary")], [B("🔢 Bot Yardımcısı Sınırı", "ai_lim")], [B("💎 Premium Sınır (5 saat)", "ai_plim")]] + ([[B("🗑 Anahtarı Kaldır", "ai_del", "danger")]] if on else []) + [[B("◀️ Admin", "admin")]])

def _bar(p): n = max(0, min(10, round(p * 10))); return "▰" * n + "▱" * (10 - n)

def ai_usage_view():
    AI_WIN["ts"] = 0
    try: ai_window()
    except Exception: pass
    u = AI_WIN.get("usage")
    if not u: return "📊 <b>Site kullanımı</b>\n<blockquote>⚠️ Siteden bilgi alınamadı.</blockquote>", KB([[B("🔄 Yenile", "ai_use")], [B("◀️ AI", "ai_adm")]])
    lines = []
    for w in u.get("windows", []):
        sp, cap = float(w.get("spent_usd", 0)), float(w.get("cap_usd", 0)) or 1
        rs = datetime.datetime.fromtimestamp(time.time() + int(w.get("resets_in_sec", 0)), TM_TZ)
        lines.append(f"{'⏱ 5 saat' if w.get('kind') == 'short' else '📅 7 gün'}  <b>${sp:.2f} / ${cap:.0f}</b>  ({sp / cap:.0%})\n{_bar(sp / cap)}\n↻ {rs:%d.%m %H:%M}")
    ft = u.get("free_tokens") or {}
    if ft: lines.append(f"🆓 Ücretsiz modeller  <b>{int(ft.get('used_today', 0)):,} / {int(ft.get('limit_per_day', 0)):,}</b> token (bugün)")
    wl = u.get("wallet") or {}
    lines.append(f"👛 Cüzdan  <b>${float(wl.get('balance_usd', 0)):.2f}</b> · Plan <b>{esc(str(u.get('plan', '?')).upper())}</b>")
    t = "📊 <b>Site kullanımı (xKiro)</b>\n<blockquote>" + "\n\n".join(lines) + f"</blockquote>\n<i>Limitin %{int(AI_ALERT_AT * 100)}'ine gelince sana uyarı gelir.</i>"
    return t, KB([[B("🔄 Yenile", "ai_use", "primary")], [B("◀️ AI", "ai_adm")]])

AI_MON_MODEL = "anthropic/claude-haiku-5.5"   # log izleme: ucuz model
AI_MON_EVERY = 300
AI_MON_RULES = """Sen bir Telegram VPN pazar botunun log denetçisisin. Bot: kullanıcılar VPN kodu alır/satar, bakiye yükler (CryptoBot USDT), satıcılar kazanç çeker, davetle ücretsiz kod alınır, destek talepleri açılır.
Sana son dakikalardaki kullanıcı logları ve sistem hataları gelecek. Sahibinin HEMEN müdahale etmesi gereken bir durum var mı bak:
- ödeme/çekim/transfer hataları, yetersiz bakiye, para tutarsızlığı
- aynı kişinin kısa sürede anormal sayıda işlemi (spam, sistem istismarı, sahte davet çiftliği, çok sayıda yeni hesap)
- tekrarlayan bot hataları, Drive/abonelik/telefon testi çökmesi, hiç kod alınamaması
- şikâyet/öfke içeren destek talepleri, olası dolandırıcılık
Normal işlemler (tek tük sipariş, kod alma, tek bir başarılı çekim, rutin kontroller) için UYARI VERME. Emin değilsen uyarma.
SADECE şu JSON'u döndür: {"alert": true/false, "level": "low/medium/high", "summary": "Türkçe, kısa, ne oldu ve ne yapılmalı (en fazla 4 satır)"}"""
MON = {"vpos": None}

async def ai_log_watch(app):
    """5 dakikada bir: son kontrolden beri yeni kullanıcı logu + sistem hatası varsa Haiku'ya sorar; şüpheli ise kuruculara yazar."""
    while True:
        await asyncio.sleep(AI_MON_EVERY)
        try:
            if not ai_key() or not load_db().get("ai_mon", True): continue
            since = load_db().get("ai_mon_ts") or time.time() - AI_MON_EVERY
            new_u = [x for x in ulog_lines() if x.get("t", 0) > since][-200:]
            new_v = []
            try:
                size = os.path.getsize(VIP_LOG)
                if MON["vpos"] is None or size < MON["vpos"]: MON["vpos"] = size   # ilk turda geçmişi okuma
                with open(VIP_LOG, encoding="utf-8", errors="ignore") as f_:
                    f_.seek(MON["vpos"]); new_v = [l.strip() for l in f_ if ("❌" in l or "⚠️" in l)][-60:]
                MON["vpos"] = size
            except Exception: pass
            now = time.time()
            mutate(lambda d: d.__setitem__("ai_mon_ts", now))
            if not new_u and not new_v: continue   # yeni bir şey yok: istek atılmaz
            txt_ = "KULLANICI LOGLARI:\n" + "\n".join(f"[{datetime.datetime.fromtimestamp(x['t'], TM_TZ):%H:%M:%S}] {x.get('x', '')[:300]}" for x in new_u) + \
                   ("\n\nSİSTEM HATALARI:\n" + "\n".join(l[:300] for l in new_v) if new_v else "")
            raw = await asyncio.to_thread(ai_call, AI_MON_RULES, [{"role": "user", "content": txt_[:30000]}], None, 1500, 120, AI_MON_MODEL)
            mj = re.search(r"\{.*\}", raw, re.S); j = json.loads(mj.group(0)) if mj else {}
            RUN["ai_mon_last"] = f"{datetime.datetime.now(TM_TZ):%H:%M} · {len(new_u)} log, {len(new_v)} hata → {'⚠️ uyarı' if j.get('alert') else 'normal'}"
            if j.get("alert"):
                lv = {"high": "🔴", "medium": "🟠"}.get(j.get("level"), "🟡")
                await notify_founders(app, f"{lv} <b>AI log uyarısı</b>\n<blockquote>{esc(str(j.get('summary', ''))[:900])}</blockquote>", KB([[B("👥 Kullanıcı Logları", "ul_open"), B("📜 Loglar", "logs")]]))
        except Exception as e: log.info("ai log watch: %s", e); RUN["ai_mon_last"] = f"hata: {str(e)[:80]}"

AI_ALERT_AT = 0.8
async def ai_usage_watch(app):
    """5 dakikada bir site limitine bakar; %80'i geçen pencere için kuruculara bir kez uyarı."""
    while True:
        await asyncio.sleep(300)
        if not ai_key(): continue
        try:
            await asyncio.to_thread(ai_window)
            for w in (AI_WIN.get("usage") or {}).get("windows", []):
                sp, cap = float(w.get("spent_usd", 0)), float(w.get("cap_usd", 0))
                if not cap or sp / cap < AI_ALERT_AT: continue
                end = int((time.time() + int(w.get("resets_in_sec", 0))) // 1800)   # aynı pencere için tekrar gönderme
                if load_db().get("ai_alert", {}).get(w.get("kind")) == end: continue
                mutate(lambda d: d.setdefault("ai_alert", {}).__setitem__(w.get("kind"), end))
                rs = datetime.datetime.fromtimestamp(time.time() + int(w.get("resets_in_sec", 0)), TM_TZ)
                await notify_founders(app, f"⚠️ <b>AI site limiti %{sp / cap:.0%} doldu</b>\n<blockquote>{'⏱ 5 saatlik' if w.get('kind') == 'short' else '📅 7 günlük'} pencere: <b>${sp:.2f} / ${cap:.0f}</b>\n↻ Yenilenme {rs:%d.%m %H:%M}</blockquote>\n<i>Dolarsa yenilenene kadar AI cevap veremez.</i>",
                                      KB([[B("📊 Kullanım", "ai_use")]]))
        except Exception as e: log.info("ai usage watch: %s", e)

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

async def broadcast(app, text, admin_uid, copy=None):
    """copy={"chat", "mid"}: fotoğraf/video (açıklamasıyla) olduğu gibi kopyalanır."""
    ids = [int(k) for k in load_db().get("users", {}) if int(k) not in ADMINS]
    ok = bad = 0
    for i in ids:
        try:
            if copy: await app.bot.copy_message(i, copy["chat"], copy["mid"])
            else: await app.bot.send_message(i, text, disable_web_page_preview=True)
            ok += 1
        except Exception: bad += 1
        await asyncio.sleep(0.05)   # Telegram sınırı: saniyede ~30 mesaj
    audit(admin_uid, f"broadcast ok={ok} bad={bad}")
    await notify_founders(app, f"📣 <b>Herkese mesaj gönderildi</b>\n<blockquote>✅ {ok}  ·  ❌ {bad} <i>(botu engelleyenler)</i></blockquote>")


# ───────── DESTEK (talep) + HATA BİLDİRİMİ ─────────
SUP_MAX = 3                      # admin cevap vermeden kullanıcının gönderebileceği mesaj sayısı
SUP_EVERY = 5                    # destek / bug: kullanıcı 5 saniyede tek mesaj gönderebilir
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

def tlog(d, tid, r, c_):
    """Talep yazışması (admin talep ekranında görür). r: u (kullanıcı) / ai / adm."""
    t = d.get("tickets", {}).get(tid)
    if t is not None: t["log"] = (t.get("log", []) + [{"r": r, "c": c_[:2000], "ts": time.time()}])[-200:]

def media_tag(m):
    if m.photo: return "[📷 fotoğraf] "
    if m.video or m.animation or m.video_note: return "[🎬 video] "
    if m.voice or m.audio: return "[🎤 ses] "
    if m.document: return "[📎 dosya] "
    if m.sticker: return "[sticker] "
    return ""

async def forward_ticket(c, m, user, tid, kind):
    hdr = f"{'🐞 <b>Hata Raporu' if kind == 'bug' else '🎫 <b>Destek'} #{tid}</b> · {esc(who(user))}"
    ai_on = bool(ai_key()) and load_db().get("ai_sup", True)
    kb = KB([[B("✍️ Yanıtla", f"t_rep:{tid}", "primary"), B("🔒 Kapat", f"t_close:{tid}", "danger")]] + ([[B("🤖 AI'ye devret", f"t_ai:{tid}")]] if ai_on else []))
    for fid in ADMINS:
        try: remember_tmsg(await copy_with_header(c.bot, fid, user.id, m, hdr, kb), tid)
        except Exception as e: log.warning("destek iletilemedi: %s", e)

async def user_to_ticket(c, u, tid):
    m, user = u.message, u.effective_user
    uid = user.id; lang = lang_of(load_db(), uid)
    size, lim = media_size(m)
    if size > lim * 1024 * 1024:
        await m.reply_text(tr(lang, "sup_big")); return
    mg = getattr(m, "media_group_id", None); now = time.time()
    ai_on = bool(ai_key()) and load_db().get("ai_sup", True)
    def f(d):
        t = d["tickets"][tid]
        if mg and t.get("mg") == mg and now - t.get("last_user", 0) < 60:   # aynı albümün devamı
            t["last"] = now; return "album"
        if now - t.get("last_user", 0) < SUP_EVERY: return int(SUP_EVERY - (now - t.get("last_user", 0))) + 1
        if t.get("pending", 0) >= SUP_MAX and (t.get("human") or not ai_on): return None
        t["pending"] = t.get("pending", 0) + 1; t["n"] = t.get("n", 0) + 1; t["last"] = now; t["last_user"] = now; t["mg"] = mg
        tlog(d, tid, "u", media_tag(m) + (m.text or m.caption or ""))
        return True
    r_ = mutate(f)
    if r_ is None:
        await m.reply_text(tr(lang, "sup_wait")); return
    if isinstance(r_, int) and r_ is not True:
        await m.reply_text(tr(lang, "sup_slow", s=r_)); return
    t = load_db().get("tickets", {}).get(tid, {}); kind = t.get("kind")
    if ai_on and not t.get("human"):   # AI cevaplar; kurucuya sadece "yeni mesaj var" (talep başına bir kez)
        if r_ == "album": return
        if not t.get("notified"):
            mutate(lambda d: d["tickets"][tid].__setitem__("notified", True))
            await notify_founders(c.application, f"🆕 <b>Yeni {'bug bildirimi' if kind == 'bug' else 'support mesajı'}</b> · #{tid}\n<blockquote>{esc(who(user))}</blockquote>\n<i>AI cevaplıyor; admine bağlanmak isterse yazışmanın tamamı sana gelir.</i>",
                                  KB([[B("👁 Yazışmayı gör", f"tv:{tid}")]]))
        asyncio.ensure_future(ai_support(c, uid, tid, lang, m, user))
        return
    await forward_ticket(c, m, user, tid, kind)
    if r_ == "album": return
    await m.reply_text(tr(lang, "sup_sent"), parse_mode="HTML", reply_markup=KB([[B(tr(lang, "b_twrite"), "u_tw", "primary")], [B(tr(lang, "b_tclose"), "u_tclose", "danger")]]))

AI_SUP_RULES = """Destek talebine BOTUN SAHİBİ olarak, birinci ağızdan cevap veriyorsun. Bot senin ("bot meňki", "bot benim"). Kullanıcıya bir arkadaş gibi rahat ve dobra yaz.
NASIL YAZACAKSIN:
- Kitap dili değil, halkın konuştuğu günlük dil. Türkmence için örnekler: "bilmeýärin" değil "bilemok"; "edýärin" değil "edýän"; "Size nähili kömek edip bilerin?" yerine "näme kömek gerek?"; "bu bot kimiň?" → "meň bodym".
- Aynı kalıpları tekrar tekrar kullanma; her cevabı farklı ve doğal kur. "aýdyber arkaýyn" samimi bir sözdür: çok nadir kullan (bir yazışmada en fazla bir kez), küfür eden/kaba yazan birine ASLA kullanma. Türkçe ve Rusça da günlük konuşma dili.
- Dil hataları yapma: Türkçede "sen naber" YANLIŞ, doğrusu "senden naber" (ya da "sende naber"). Türkmençede "sen nähili" değil "sen nähili / özüň nähili" gibi doğal kalıplar.
- Türkmen argosu: "zaýa" / "zaya" (ör. "naýli zaýa", "zaýa") KÜFÜRDÜR, curse=true say ve küfür gibi karşılık ver.
- ASLA emoji kullanma (sadece buton adlarındaki emojiler kalabilir). Varsayılan kısa.
- Mesajın dili belirsizse (Türkçe ve Türkmence birbirine çok benzer: "sen bot mi?", "naber" vb.) yukarıda söylenen varsayılan dili kullan. Gerekirse (adım adım anlatım) uzun yaz.
- Kullanıcının üslubuna uy: kibar ise kibar, samimi ise samimi; küfürlü/kaba yazıyorsa sen de aynı rahatlıkta argo ve küfürle cevap verebilirsin. Irk, din, milliyet, cinsiyet hakareti ve tehdit asla yok.
- Kendiliğinden bot/yapay zekâ olduğundan bahsetme. Ama kullanıcı bot olup olmadığını sorarsa uzatmadan, ters ve dobra bir şekilde kabul et ve konuyu bota çevir. Örnek (tk): "Hawa hawa, bot men. Soragyň barmy ýa ýok?" / (tr): "Evet evet, botum. Sorun var mı yok mu?" / (ru): "Да-да, бот. Вопрос есть или нет?" Sadece gerçekten bunu sorarsa söyle; küfür, sitem veya başka soruları bu soru sanma.
- "sen kim / kimsiň / кто ты" gibi sadece kim olduğunu sorarsa (bot olup olmadığını değil): kısaca botun supportu olduğunu söyle, açıklama yapma, "adından cevap veren kömekçi/asistan" gibi ifadeler KULLANMA. Ör. tk: "Bodyň supporty. Näme gerek?" / tr: "Botun supportuyum. Ne lazım?"
- Küfür, hakaret veya argo içeren mesajı "bot musun" sorusu SANMA; mesajda "ai", "bot" gibi kelimeler küfürle birlikte geçse bile önce küfür olarak değerlendir. curse=true SADECE sana yönelik hakaret/düşmanca küfür varsa (ör. "sikdir", "anaňy…"); "naber lan yarram" gibi samimi argo selamlaşma curse DEĞİLDİR.
- curse=true ise: TEK kısa ve kaba cümleyle karşılık ver, o kadar (ör. tk: "Özüň sikdir." / "Ýitir." / tr: "Siktir git." ). "dost", "brat", "dogan" gibi samimi hitap YOK, açıklama YOK, yardım teklifi YOK, konuyu bota çevirme YOK. Anneye/aileye yönelik ya da cinsel içerikli hakaret de YOK.
- Her soruyu cevapla. BİLGİLER'e, YENİLİKLER'e, SAHİBİNİN EKLEDİĞİ BİLGİLER'e ve SAHİBİNİN ÖNCEKİ CEVAPLARI'na dayan; bilmediğin şeyi uydurma. Asla söz verme (iade, telafi, süre uzatma vb.).
- Kullanıcının ÖNCEKİ TALEPLERİ'ni hatırla ve gerekiyorsa ona göre konuş.
- Ödeme kontrolü, iade, bozuk kodun düzeltilmesi gibi elle bakılması gereken durumlarda gerekli bilgiyi iste ve "istersen özüm seredeýin" gibi kendin bakacağını teklif et.
- Kullanıcı açıkça admine / insana / sahibine bağlanmak isterse ya da bakmanı kabul ederse handoff=true yap ve tek cümleyle birazdan kendin bakacağını söyle.
SADECE şu JSON'u döndür: {"handoff": true/false, "curse": true/false, "answer": "kullanıcıya gidecek mesaj"}"""
SUP_CURSE_MAX = 3   # üst üste bu kadar küfür → cevap verilmez, talep sahibine gider
AI_LEARN_MAX = 40
SUP_MODEL = "anthropic/claude-fable-5"   # destek: en doğal yazan model (meşgulse varsayılan modele düşer)

def sup_memory(db, uid, tid):
    """Kullanıcının önceki talepleri + sahibinin örnek cevapları (destek AI'sına bağlam)."""
    prev = [t for k, t in db.get("tickets", {}).items() if t.get("uid") == uid and k != tid and t.get("log")]
    prev.sort(key=lambda t: t.get("ts", 0))
    lines, n = [], 0
    for t in reversed(prev[-5:]):
        blk = [f"[{datetime.datetime.fromtimestamp(t.get('ts', 0), TM_TZ):%d.%m}] " + " | ".join(("K: " if x["r"] == "u" else "S: ") + " ".join(x["c"].split())[:200] for x in t["log"][-8:])]
        n += len(blk[0])
        if n > 3000: break
        lines += blk
    out = ("KULLANICININ ÖNCEKİ TALEPLERİ (K=kullanıcı, S=sen):\n" + "\n".join(reversed(lines))) if lines else ""
    learn = db.get("ai_learn", [])[-AI_LEARN_MAX:]
    if learn: out += "\n\nSAHİBİNİN ÖNCEKİ CEVAPLARI (aynı bilgi ve üslupla cevap ver):\n" + "\n".join(f"S: {x['q'][:200]}\nC: {x['a'][:300]}" for x in learn)
    return out

async def ai_support(c, uid, tid, lang, m, user):
    """Destek mesajına AI cevap verir (insan gibi). Kullanıcı admin isterse talep admine geçer ve bütün yazışma kurucuya gider.
    "yazıyor…" gösterilmez (bot olduğu belli olmasın)."""
    try:
        t0 = load_db().get("tickets", {}).get(tid) or {}
        kind = t0.get("kind")
        msgs = []
        for x in t0.get("log", [])[-31:-1]:   # son yazışma (şimdiki mesaj hariç)
            role = "user" if x["r"] == "u" else "assistant"
            c_ = ("[Admin] " if x["r"] == "adm" else "") + x["c"]
            if msgs and msgs[-1]["role"] == role: msgs[-1]["content"] += "\n" + c_
            else: msgs.append({"role": role, "content": c_})
        while msgs and msgs[0]["role"] != "user": msgs.pop(0)
        q_ = ("[Hata raporu] " if kind == "bug" else "") + media_tag(m) + (m.text or m.caption or "")
        cur = q_[:3000] or "[mesaj]"
        if m.photo:
            try:
                f_ = await c.bot.get_file(m.photo[-1].file_id); raw = bytes(await f_.download_as_bytearray())
                cur = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(raw).decode()}}, {"type": "text", "text": q_[:3000]}]
            except Exception as e: log.info("sup photo: %s", e)
        if msgs and msgs[-1]["role"] == "user":
            msgs[-1] = {"role": "user", "content": ([{"type": "text", "text": msgs[-1]["content"]}] + cur) if isinstance(cur, list) else msgs[-1]["content"] + "\n" + cur}
        else: msgs.append({"role": "user", "content": cur})
        mem = sup_memory(load_db(), uid, tid)
        sys_ = ai_system(lang) + "\n\n" + AI_SUP_RULES + (("\n\n" + mem) if mem else "")
        try: raw_ = await asyncio.to_thread(ai_call, sys_, msgs, None, 4000, 120, SUP_MODEL)
        except Exception as e1:
            log.info("sup model %s: %s → varsayılan model", SUP_MODEL, e1)
            raw_ = await asyncio.to_thread(ai_call, sys_, msgs)
        mj = re.search(r"\{.*\}", raw_, re.S)
        try: j = json.loads(mj.group(0)) if mj else {"handoff": False, "answer": raw_}
        except Exception: j = {"handoff": False, "answer": raw_}
        ans = (j.get("answer") or "").strip(); hand = bool(j.get("handoff"))
        curse = bool(j.get("curse"))
        def cf(d):
            t = d.get("tickets", {}).get(tid)
            if not t: return 0
            t["curse_n"] = (t.get("curse_n", 0) + 1) if curse else 0
            return t["curse_n"]
        cn = mutate(cf)
        if cn >= SUP_CURSE_MAX: ans, hand = "", True   # üst üste küfür: cevap yok, sahibine
        if not ans and not hand: raise RuntimeError("boş cevap")
        def f(d):
            t = d.get("tickets", {}).get(tid)
            if not t: return
            if ans: tlog(d, tid, "ai", ans)
            t["pending"] = 0
            if hand: t["human"] = True; t["pending"] = 1
        mutate(f)
        if ans:
            await c.bot.send_message(uid, esc(ans)[:4000], parse_mode="HTML", reply_markup=KB([[B(tr(lang, "b_tclose"), "u_tclose")]]))
        if hand: await send_handoff(c, tid, user, curse=cn >= SUP_CURSE_MAX)
    except Exception as e:
        log.warning("ai support: %s", e); RUN["ai_err"] = f"support: {str(e)[:120]}"
        # AI cevap veremedi: talep admine geçer (kullanıcı cevapsız kalmasın)
        mutate(lambda d: d.get("tickets", {}).get(tid, {}).__setitem__("human", True))
        try: await c.bot.send_message(uid, tr(lang, "sup_sent"))
        except Exception: pass
        await send_handoff(c, tid, user, err=True)

async def send_handoff(c, tid, user, err=False, curse=False):
    """Kurucuya: admine bağlanmak isteyen kullanıcının bütün yazışması."""
    t = load_db().get("tickets", {}).get(tid) or {}
    lines = [("👤 " if x["r"] == "u" else "🛠 " if x["r"] == "adm" else "🤖 ") + esc(x["c"]) for x in t.get("log", [])]
    body, n = [], 0
    for ln in reversed(lines):
        n += len(ln)
        if n > 3300: break
        body.append(ln)
    head = f"🙋 <b>{'AI cevap veremedi' if err else f'Üst üste {SUP_CURSE_MAX} kez küfür etti — AI cevap vermiyor' if curse else 'Admine bağlanmak istiyor'}</b> · #{tid}\n<i>{esc(who(user))}</i>\n"
    kb = KB([[B("✍️ Yanıtla", f"t_rep:{tid}", "primary"), B("🔒 Kapat", f"t_close:{tid}", "danger")], [B("🤖 AI'ye devret", f"t_ai:{tid}")]])
    for fid in ADMINS:
        try:
            r_ = await c.bot.send_message(fid, head + "<blockquote expandable>" + "\n\n".join(reversed(body)) + "</blockquote>", parse_mode="HTML", reply_markup=kb)
            remember_tmsg(r_.message_id, tid)
        except Exception as e: log.warning("handoff: %s", e)

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
        last_q = next((y["c"] for y in reversed(x.get("log", [])) if y["r"] == "u"), "")
        tlog(d, tid, "adm", media_tag(m) + (m.text or m.caption or ""))
        if (m.text or m.caption) and last_q:   # AI sahibinin cevaplarından öğrenir
            d["ai_learn"] = (d.get("ai_learn", []) + [{"q": last_q[:400], "a": (m.text or m.caption)[:600], "ts": time.time()}])[-AI_LEARN_MAX:]
    mutate(f)
    ai_on = bool(ai_key()) and load_db().get("ai_sup", True)
    await m.reply_text(f"✅ Cevap gönderildi · #{tid}", reply_markup=KB([[B("🔒 Talebi Kapat", f"t_close:{tid}", "danger")]] + ([[B("🤖 AI'ye devret", f"t_ai:{tid}")]] if ai_on else [])))

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
    elif t.get("human") or not (ai_key() and load_db().get("ai_sup", True)):   # AI'nın tek başına yürüttüğü talepler için haber yok
        await notify_founders(c.application if hasattr(c, "application") else c, f"🔒 Kullanıcı destek talebini kapattı · #{tid}\n<blockquote>{esc(t.get('who'))}</blockquote>")
    return True

async def ai_answer(c, u):
    m = u.message; uid = u.effective_user.id; db0 = load_db(); lang = lang_of(db0, uid)
    own = uid in ADMINS; st_ = STATE.get(uid) or {}; mk = st_.get("model"); M = AI_MODELS.get(mk) if mk else None
    if M: kb = KB([[B("🧹 " + tr(lang, "b_ai_new"), f"u_ain:{mk}"), B(tr(lang, "b_ai_hist"), "u_aih")], [B(tr(lang, "b_ai_models"), "u_ai"), B(tr(lang, "b_ai_end"), "u_aix")]])
    else: kb = KB([[B(tr(lang, "b_ai_models"), "u_ai")], [B(tr(lang, "b_ai_end"), "u_aix"), B(tr(lang, "b_sup"), "u_sup")]])
    q = (m.text or m.caption or "").strip(); photo = bool(m.photo)
    if photo and not M: await m.reply_text(tr(lang, "ai_text"), reply_markup=kb); return
    if photo and mk not in AI_VISION:
        await m.reply_text(tr(lang, "ai_novision", name=M[0], v=", ".join(AI_MODELS[k][0] for k in AI_MODELS if k in AI_VISION)), reply_markup=kb); return
    if not q and not photo: await m.reply_text(tr(lang, "ai_text"), reply_markup=kb); return
    if time.time() - AI_HIST.get(("t", uid), 0) < 3: return   # art arda spam
    AI_HIST[("t", uid)] = time.time()
    if M:
        win = await asyncio.to_thread(ai_window) if not own else 0
        kind = mutate(lambda d: ai_take(d, uid, win, mk))
        if kind == "flim": await m.reply_text(tr(lang, "ai_flim", n=AI_FREE_DAY), reply_markup=kb); return
        if kind == "lock":
            await m.reply_text(tr(lang, "aipro_info", usdt=AIPRO_USDT, days=AIPRO_DAYS, n=ai_pro_limit(), f=AI_FREE_N), parse_mode="HTML",
                               reply_markup=KB([[B(tr(lang, "b_aipro_buy", usdt=AIPRO_USDT), "u_buy:aipro", "success")], [B(tr(lang, "b_ai_models"), "u_ai")]])); return
        if kind == "plim": await m.reply_text(tr(lang, "ai_plim", n=ai_pro_limit(), r=tm_fmt(win)[-5:]), reply_markup=kb); return
    else:
        lim = ai_limit()
        def f(d):
            x = d["users"].setdefault(str(uid), {})
            if x.get("ai_day") != tm_day(): x["ai_day"], x["ai_n"] = tm_day(), 0
            if not own and x["ai_n"] >= lim: return False
            x["ai_n"] += 1; return True
        if not mutate(f): await m.reply_text(tr(lang, "ai_lim", n=lim), reply_markup=kb); return
        kind = "bot"
    qmax = 20000 if (own or M) else 2000
    cid = st_.get("cid") if "cid" in st_ else ai_cur(uid, mk or "bot")
    hist = ai_context(uid, cid, AI_CTX_CHARS if (own or M) else 8000) if cid else []
    if photo:
        try:
            f_ = await c.bot.get_file(m.photo[-1].file_id); raw = bytes(await f_.download_as_bytearray())
        except Exception as ex:
            if M: mutate(lambda d: ai_give_back(d, uid, kind))
            await m.reply_text(tr(lang, "ai_err"), reply_markup=kb); return
        q = q or tr(lang, "ai_img_q")
        cur = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(raw).decode()}}, {"type": "text", "text": q[:qmax]}]
        q_save = "[📷] " + q[:qmax]
    else: cur, q_save = q[:qmax], q[:qmax]
    msgs = hist + [{"role": "user", "content": cur}]
    can_img = own and bool(M) and mk != "mistral" and mk not in AI_FREEM   # sohbetten fotoğraf oluşturma: sadece kurucu
    async def typing():
        while True:
            try: await c.bot.send_chat_action(uid, "typing")
            except Exception: pass
            await asyncio.sleep(4)
    tt = asyncio.ensure_future(typing())
    try:
        img_p = None
        if M:
            j_ = await asyncio.to_thread(ai_req, ai_system_model(lang, M[0], M[1], can_img, mk in AI_VISION), msgs, None, 16000 if own else 8000, 300, M[1], [IMG_TOOL] if can_img else None)
            ans = "".join(b.get("text", "") for b in j_.get("content", []) if b.get("type") == "text").strip()
            img_p = next((b.get("input", {}).get("prompt") for b in j_.get("content", []) if b.get("type") == "tool_use" and b.get("name") == "generate_image"), None)
            if not ans and not img_p: raise RuntimeError("boş cevap")
        else: ans = await asyncio.to_thread(ai_call, ai_system(lang), msgs)
    except Exception as ex:
        tt.cancel()
        if kind == "bot": mutate(lambda d: d["users"][str(uid)].__setitem__("ai_n", max(0, d["users"][str(uid)].get("ai_n", 1) - 1)))   # hata sayılmaz
        else: mutate(lambda d: ai_give_back(d, uid, kind))
        log.warning("ai %s: %s", M[1] if M else "bot", ex); RUN["ai_err"] = f"{M[0] if M else 'bot'}: {str(ex)[:130]}"
        busy = M and any(x in str(ex) for x in ("503", "429", "capacity", "overloaded"))
        await m.reply_text(tr(lang, "ai_busy", name=M[0]) if busy else tr(lang, "ai_err"), reply_markup=kb); return
    tt.cancel()
    if img_p:   # model fotoğraf oluşturmaya karar verdi (kurucu)
        if ans:
            for ch_ in md_tg(ans): await m.reply_text(ch_, parse_mode="HTML", disable_web_page_preview=True)
        wait = await m.reply_text(tr(lang, "img_wait"))
        try:
            data, jid = await gen_image(img_p)
            await c.bot.send_photo(uid, data, caption=f"🎨 <i>{esc(IMG_MODEL.split('/')[-1])} ile çizildi</i>\n" + esc(short(img_p, 900)), parse_mode="HTML")
            await c.bot.send_document(uid, data, filename=f"{jid}.png", reply_markup=kb)   # sıkıştırılmamış asıl dosya
            note = f"[🎨 Fotoğraf oluşturuldu: {img_p}]"
        except Exception as ex:
            log.warning("img: %s", ex); RUN["ai_err"] = f"img: {str(ex)[:130]}"
            await m.reply_text(tr(lang, "img_blocked") if str(ex) == "blocked" else tr(lang, "img_err", e=esc(str(ex)[:150])), parse_mode="HTML", reply_markup=kb)
            note = f"[🎨 Fotoğraf oluşturulamadı: {img_p}]"
        try: await wait.delete()
        except Exception: pass
        cid = await asyncio.to_thread(ai_append, uid, mk, cid, q_save, (ans + "\n" + note).strip())
        if (STATE.get(uid) or {}).get("action") == "ai": STATE[uid]["cid"] = cid
        return
    cid = await asyncio.to_thread(ai_append, uid, mk or "bot", cid, q_save, ans)
    if (STATE.get(uid) or {}).get("action") == "ai": STATE[uid]["cid"] = cid
    if not M:
        await m.reply_text("🤖 " + esc(ans)[:3900], parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True); return
    chunks = md_tg(ans)
    for i_, ch_ in enumerate(chunks):
        last = i_ == len(chunks) - 1
        try: await m.reply_text((f"🧠 <i>{esc(M[0])}</i>\n" if i_ == 0 else "") + ch_, parse_mode="HTML", reply_markup=kb if last else None, disable_web_page_preview=True)
        except BadRequest: await m.reply_text(_plain(ch_)[:4000], reply_markup=kb if last else None)   # biçim bozuksa düz yazı

async def support_router(u: Update, c: ContextTypes.DEFAULT_TYPE):
    """Her mesajdan ÖNCE çalışır: açık destek talebi ya da kurucu cevabı varsa mesajı oraya yönlendirir."""
    m = u.message
    if not m or not u.effective_user or m.chat.type != "private": return
    uid = u.effective_user.id
    st0 = STATE.get(uid) or {}
    if st0.get("action") == "ai":   # 🤖 Yardımcı
        if not is_banned(uid): await ai_answer(c, u)
        raise ApplicationHandlerStop
    if st0.get("action") in ("u_sell", "u_topamt"):   # pazar: ilan adımları / yükleme tutarı (yazı ya da fotoğraf)
        if not is_banned(uid): await market_input(c, u, st0)
        raise ApplicationHandlerStop
    if uid in ADMINS:
        st = STATE.get(uid) or {}
        if st.get("action") == "bcast" and not m.text:   # 📣 herkese mesaj: fotoğraf / video (+ açıklama)
            if not (m.photo or m.video or m.animation or m.document or m.voice or m.audio):
                await m.reply_text("⚠️ Yazı, fotoğraf ya da video gönder."); raise ApplicationHandlerStop
            STATE[uid] = {"action": "bcast_ok", "copy": {"chat": uid, "mid": m.message_id}}
            n = sum(1 for k in load_db().get("users", {}) if int(k) not in ADMINS)
            await m.reply_text(f"📣 <b>Onay</b>\n<blockquote>Yukarıdaki {'fotoğraf' if m.photo else 'medya'}{' + açıklama' if m.caption else ''} olduğu gibi gidecek.</blockquote>\n<b>{n}</b> kullanıcıya gönderilecek.",
                               parse_mode="HTML", reply_markup=KB([[B("✅ Gönder", "bcast_yes", "success"), B("✖️ İptal", "admin", "danger")]]))
            raise ApplicationHandlerStop
        if st.get("action") == "own_photo":
            if not m.photo: await m.reply_text("⚠️ Fotoğraf gönder."); raise ApplicationHandlerStop
            STATE.pop(uid, None); fid_ = m.photo[-1].file_id
            try: fid_ = await full_view_photo(c, uid, fid_) or fid_   # uzun ekran görüntüsü kırpılmasın
            except Exception as ex_: log.info("own photo pad: %s", ex_)
            mutate(lambda d: ensure_own(d)[OWN_LID].update(photo=fid_, pad_ok=True))
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
    if uid in STATE or is_banned(uid): return    # başka bir işlem bekleniyor (ör. panel kullanıcı sayısı) / engelli
    db_ = load_db(); tid = open_ticket(db_, uid)
    if not tid: return
    if not db_["tickets"][tid].get("armed"):   # ✍️ Yaz'a henüz basılmadı: talebe gitmez, hatırlatılır
        lang_ = lang_of(db_, uid)
        await m.reply_text(tr(lang_, "sup_press", tid=tid), parse_mode="HTML", reply_markup=KB([[B(tr(lang_, "b_twrite"), "u_tw", "primary")], [B(tr(lang_, "b_tclose"), "u_tclose", "danger")]]))
        raise ApplicationHandlerStop
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
MIN_COUNTRIES, MAX_DEAD = 4, 5   # başvuruda en az 4 gerçek ülke; 5'ten fazla çalışmayan (N/A) sunucu varsa ret
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
    u = {v.get("file_id") for v in db["subs"].values() if v.get("file_id")} | {db.get("tm_fid"), db.get("px_fid")} | source_fids(db)
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
  "rj_dead": "{n} sunucu çalışmıyor (en fazla 5 olabilir).", "rj_link": "Abonelik linki açılmadı.",
  "m_paid_sent": "🎉 <b>Tebrikler!</b>\n<blockquote>🏪 {title}\n⏱ Alıcı kodunu {dur} kullandı\n💰 Ödemen  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💸 CryptoBot hesabına gönderildi.",
  "m_paid_bal": "🎉 <b>Tebrikler!</b>\n<blockquote>🏪 {title}\n⏱ Alıcı kodunu {dur} kullandı\n💰 Ödemen  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💼 Bot bakiyene eklendi. Profil → 💸 Kazancı Çek.",
  "myl": "📦 <b>İlanlarım</b>", "myl_none": "📦 <b>İlanlarım</b>\n<blockquote>İlanın yok.</blockquote>",
  "myl_item": "<blockquote>{st} <b>{title}</b>\n💲 {p} USDT/dk · 👥 {n} alıcı · 💰 {earned} USDT kazanç</blockquote>",
  "st_pending": "⏳", "st_live": "🟢", "st_removed": "⛔", "st_rejected": "❌",
  "rules": "📜 <b>Pazar kuralları</b>\n\n🏪 <b><u>SATICI</u></b>\n<blockquote>• Her ilan 0.05$ (iade edilmez).\n• Abonelik limitsiz olmalı; ekran görüntüsü zorunlu.\n• Başvuruda en az 4 farklı gerçek ülke (bot ölçer, bayraklara bakılmaz).\n• 💎 VIP: 0.2$ ile 36 saat en üstte.\n• Kazanç: alıcı durdurunca, uzun kullanımda her 24 saatte bir gönderilir.\n• 🔒 Kodların sadece satın alan kişinin dosyasına yazılır, durdurunca silinir. Her kullanım İlanlarım → 📜 Kullanım geçmişi'nde görünür.</blockquote>\n\n🛒 <b><u>ALICI</u></b>\n<blockquote>• Her başlatma 0.05$ + ilk 5 saat peşin (iade edilmez).\n• Aynı ilan 24 saatte en fazla 3 kez başlatılır.\n• Dakika başı ücret bakiyenden düşer (kullansan da kullanmasan da).\n• İstediğin an durdurursun; bakiye bitince kod durur.\n• Bakiye en az 0.1$ yüklenir; yüklenen bakiye geri çekilmez.</blockquote>",
  "bal_line": "\n\n💰 <b>Bakiye</b> {bal} USDT ≈ {tmt} TMT" , "earn_line": "\n💼 <b>Çekilebilir kazanç</b>  {earn} USDT",
  "top": "➕ <b>Bakiye Yükle</b>\n<blockquote>CryptoBot ile USDT. En az 0.1 USDT.\n💰 Bakiyen  <b>{bal} USDT</b></blockquote>",
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
  "rj_dead": "Не работают {n} серверов (максимум 5).", "rj_link": "Ссылка подписки не открылась.",
  "m_paid_sent": "🎉 <b>Поздравляем!</b>\n<blockquote>🏪 {title}\n⏱ Покупатель использовал ваш код {dur}\n💰 Выплата  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💸 Отправлено на ваш счёт в CryptoBot.",
  "m_paid_bal": "🎉 <b>Поздравляем!</b>\n<blockquote>🏪 {title}\n⏱ Покупатель использовал ваш код {dur}\n💰 Выплата  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💼 Зачислено на ваш баланс в боте. Профиль → 💸 Вывести доход.",
  "myl": "📦 <b>Мои объявления</b>", "myl_none": "📦 <b>Мои объявления</b>\n<blockquote>Объявлений нет.</blockquote>",
  "myl_item": "<blockquote>{st} <b>{title}</b>\n💲 {p} USDT/мин · 👥 {n} покуп. · 💰 {earned} USDT доход</blockquote>",
  "rules": "📜 <b>Правила биржи</b>\n\n🏪 <b><u>ПРОДАВЕЦ</u></b>\n<blockquote>• Каждое объявление 0.05$ (не возвращается).\n• Подписка должна быть безлимитной; скриншот обязателен.\n• При подаче минимум 4 разные реальные страны (бот измеряет сам, флаги не учитываются).\n• 💎 VIP: 0.2$ — 36 часов на самом верху.\n• Выплата: после остановки покупателем, при долгом использовании — каждые 24 ч.\n• 🔒 Ваши коды записываются только в файл купившего и удаляются после остановки. Каждое использование видно в Мои объявления → 📜 История.</blockquote>\n\n🛒 <b><u>ПОКУПАТЕЛЬ</u></b>\n<blockquote>• Каждый запуск 0.05$ + первые 5 часов сразу (не возвращается).\n• Одно объявление — не больше 3 запусков за 24 ч.\n• Поминутная оплата списывается с баланса (пользуетесь или нет).\n• Остановить можно в любой момент; при нулевом балансе код останавливается.\n• Пополнение от 0.1$; пополненный баланс не выводится.</blockquote>",
  "bal_line": "\n\n💰 <b>Баланс</b> {bal} USDT ≈ {tmt} TMT", "earn_line": "\n💼 <b>Доход к выводу</b>  {earn} USDT",
  "top": "➕ <b>Пополнение</b>\n<blockquote>USDT через CryptoBot. Минимум 0.1 USDT.\n💰 Баланс  <b>{bal} USDT</b></blockquote>",
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
  "rules": "📜 <b>Pazar kuralları</b>\n\n🏪 <b><u>SATICI</u></b>\n<blockquote>• Her ilan 0.05$ (iade edilmez).\n• Abonelik limitsiz olmalı; ekran görüntüsü zorunlu.\n• Başvuruda en az 4 farklı gerçek ülke (bot ölçer, bayraklara bakılmaz).\n• 💎 VIP: 0.2$ ile 36 saat en üstte.\n• Kazanç: alıcı durdurunca, uzun kullanımda her 24 saatte bir gönderilir.\n• 🔒 Kodların sadece satın alan kişinin dosyasına yazılır, durdurunca silinir. Her kullanım İlanlarım → 📜 Kullanım geçmişi'nde görünür.</blockquote>\n\n🛒 <b><u>ALICI</u></b>\n<blockquote>• Her başlatma 0.05$ + ilk 5 saat peşin (iade edilmez).\n• Aynı ilan 24 saatte en fazla 3 kez başlatılır.\n• Dakika başı ücret bakiyenden düşer (kullansan da kullanmasan da).\n• İstediğin an durdurursun; bakiye bitince kod durur.\n• Bakiye en az 0.1$ yüklenir; yüklenen bakiye geri çekilmez.</blockquote>",
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
  "rules": "📜 <b>Правила биржи</b>\n\n🏪 <b><u>ПРОДАВЕЦ</u></b>\n<blockquote>• Каждое объявление 0.05$ (не возвращается).\n• Подписка должна быть безлимитной; скриншот обязателен.\n• При подаче минимум 4 разные реальные страны (бот измеряет сам, флаги не учитываются).\n• 💎 VIP: 0.2$ — 36 часов на самом верху.\n• Выплата: после остановки покупателем, при долгом использовании — каждые 24 ч.\n• 🔒 Ваши коды записываются только в файл купившего и удаляются после остановки. Каждое использование видно в Мои объявления → 📜 История.</blockquote>\n\n🛒 <b><u>ПОКУПАТЕЛЬ</u></b>\n<blockquote>• Каждый запуск 0.05$ + первые 5 часов сразу (не возвращается).\n• Одно объявление — не больше 3 запусков за 24 ч.\n• Поминутная оплата списывается с баланса (пользуетесь или нет).\n• Остановить можно в любой момент; при нулевом балансе код останавливается.\n• Пополнение от 0.1$; пополненный баланс не выводится.</blockquote>",
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
 "rj_dead": "{n} serwer işlemeýär (iň köp 5 bolup biler).",
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
 "rules": "📜 <b>Bazaryň düzgünleri</b>\n\n🏪 <b><u>SATYJY</u></b>\n<blockquote>• Her bildiriş 0.05$ (yzyna gaýtarylmaýar).\n• Podpiska limitsiz bolmaly; skrinşot hökman.\n• Bildiriş berlende azyndan 4 dürli hakyky ýurt bolmaly (bot özi ölçeýär, baýdaklara seredilmeýär).\n• 💎 VIP: 0.2$ töläp, 36 sagat iň ýokarda durýar.\n• Gazanç: alyjy kody yzyna gowşuranda, uzak ulanylsa her 24 sagatda bir gezek iberilýär.\n• 🔒 Kodlaryňyz diňe satyn alan adamyň faýlyna ýazylýar, yzyna gowşurylanda pozulýar. Her ulanylyşy Bildirişlerim → 📜 Ulanyş taryhy bölüminde görünýär.</blockquote>\n\n🛒 <b><u>ALYJY</u></b>\n<blockquote>• Her gezek başlamak 0.05$ + ilkinji 5 sagat öňünden (yzyna gaýtarylmaýar).\n• Bir bildiriş 24 sagatda iň köp 3 gezek başladylýar.\n• Minutlyk töleg balansyňdan aýrylýar (ulansaň-da, ulanmasaň-da).\n• Islän wagtyň yzyna gowşurup bilersiň; balans gutarsa, kod özi yzyna gowşurylýar.\n• Balans azyndan 0.1$ doldurylýar; doldurylan balansy yzyna çekip bolmaýar.</blockquote>",
 "bal_line": "\n\n💰 <b>Balans</b> {bal} USDT ≈ {tmt} TMT",
 "earn_line": "\n💼 <b>Çekip boljak gazanç</b>  {earn} USDT",
 "top": "➕ <b>Balansy doldur</b>\n<blockquote>CryptoBot arkaly USDT. Azyndan 0.1 USDT.\n💰 Balansyň  <b>{bal} USDT</b></blockquote>",
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

# 🃏 İlan kartı: sade-premium tasarım (Fable 5 önerisi A)
T["tk"].update({"head_own": "🏆 <b>BOTUŇ RESMI KODY</b>", "head_vip": "💎 <b>VIP SERWER</b>", "head_std": "🏷 <b>STANDART SERWER</b>",
  "card2": "{head}\n━━━━━━━━━━━━━━\n<b>{title}</b>\n\n<b>Bahalar</b>\n<blockquote>{prices}</blockquote>\n<i>Serwerleri we ýurtlary görmek üçin «Barla» bas.</i>",
  "prices": "<code>1 minut</code>   <b>{mi} TMT</b>\n<code>1 sagat</code>   <b>{h} TMT</b>\n<code>1 hepde</code>   <b>{w} TMT</b>\n<code>1 aý   </code>   <b>{m} TMT</b>",
  "mkt_bal": "\n━━━━━━━━━━━━━━\n👛 Balansyň: <b>{bal} USDT</b>", "mkt_none": "\n<i>Häzirlikçe başga satyjy ýok.</i>"})
T["tr"].update({"head_own": "🏆 <b>BOTUN RESMİ KODU</b>", "head_vip": "💎 <b>VIP SUNUCU</b>", "head_std": "🏷 <b>STANDART SUNUCU</b>",
  "card2": "{head}\n━━━━━━━━━━━━━━\n<b>{title}</b>\n\n<b>Fiyatlar</b>\n<blockquote>{prices}</blockquote>\n<i>Sunucular ve ülkeler için «Kontrol Et»e bas.</i>",
  "prices": "<code>1 dakika</code>   <b>{mi} TMT</b>\n<code>1 saat  </code>   <b>{h} TMT</b>\n<code>1 hafta </code>   <b>{w} TMT</b>\n<code>1 ay    </code>   <b>{m} TMT</b>",
  "mkt_bal": "\n━━━━━━━━━━━━━━\n👛 Bakiyen: <b>{bal} USDT</b>", "mkt_none": "\n<i>Şimdilik başka satıcı yok.</i>"})
T["ru"].update({"head_own": "🏆 <b>ОФИЦИАЛЬНЫЙ КОД БОТА</b>", "head_vip": "💎 <b>VIP СЕРВЕР</b>", "head_std": "🏷 <b>СТАНДАРТНЫЙ СЕРВЕР</b>",
  "card2": "{head}\n━━━━━━━━━━━━━━\n<b>{title}</b>\n\n<b>Цены</b>\n<blockquote>{prices}</blockquote>\n<i>Серверы и страны — кнопка «Проверить».</i>",
  "prices": "<code>1 минута</code>   <b>{mi} TMT</b>\n<code>1 час   </code>   <b>{h} TMT</b>\n<code>1 неделя</code>   <b>{w} TMT</b>\n<code>1 месяц </code>   <b>{m} TMT</b>",
  "mkt_bal": "\n━━━━━━━━━━━━━━\n👛 Баланс: <b>{bal} USDT</b>", "mkt_none": "\n<i>Других продавцов пока нет.</i>"})

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
T["tr"].update({"b_ai_bot": "❓ Bot hakkında soru (ücretsiz)", "b_ai_models": "🧠 Modeller", "b_aipro": "💎 Premium · {usdt}$/ay", "b_aipro_buy": "💎 Satın al · {usdt}$", "it_aipro": "💎 AI Premium · 30 gün",
  "ai_menu": "🤖 <b>Yapay Zekâ</b>\n<blockquote>{st}</blockquote>\n<blockquote expandable>{body}</blockquote>\n<i>❓ Bot hakkındaki sorular ücretsiz. Modellerle her konuda sorabilirsin (kod, ders, çeviri…). Fotoğraf/video oluşturulmaz.</i>",
  "ai_st_own": "👑 Kurucu · sınırsız", "ai_st_pro": "💎 Premium · {until}'e kadar\nKalan soru <b>{n}/{lim}</b> · yenilenme {r}", "ai_st_free": "🎁 Ücretsiz: 2 günde 3 soru · kalan <b>{n}</b> · yenilenme {w}",
  "ai_pick": "🧠 <b>{name}</b>\n<blockquote>{d}\nKalan soru  <b>{n}</b></blockquote>\n<i>Sorunu yaz</i> 👇",
  "aipro_info": "💎 <b>AI Premium</b>\n<blockquote>Bütün modeller: Claude Opus, GPT, Gemini, Grok, Kimi…\nHer 5 saatte <b>{n}</b> soru · {days} gün\nÜcret  <b>{usdt}$</b> / ay (CryptoBot ya da bakiye)</blockquote>\n<i>Abone olmadan 2 günde {f} soru ücretsiz.</i>",
  "aipro_ok": "✅ <b>💎 AI Premium aktif!</b>\n<blockquote>{until}'e kadar · her 5 saatte {n} soru</blockquote>\n🤖 butonundan modeli seç.",
  "ai_busy": "⚠️ {name} şu an meşgul. Başka model seç ya da biraz sonra dene. (Hakkın düşülmedi.)"})
T["tk"].update({"b_ai_bot": "❓ Bot barada sorag (mugt)", "b_ai_models": "🧠 Modeller", "b_aipro": "💎 Premium · {usdt}$/aý", "b_aipro_buy": "💎 Satyn al · {usdt}$", "it_aipro": "💎 AI Premium · 30 gün",
  "ai_menu": "🤖 <b>Emeli aň</b>\n<blockquote>{st}</blockquote>\n<blockquote expandable>{body}</blockquote>\n<i>❓ Bot barada soraglar mugt. Modellerden islendik zat barada sorap bilersiň (kod, sapak, terjime…). Surat/wideo döredilmeýär.</i>",
  "ai_st_own": "👑 Esasy admin · çäksiz", "ai_st_pro": "💎 Premium · {until} çenli\nGalan sorag <b>{n}/{lim}</b> · täzelenýär {r}", "ai_st_free": "🎁 Mugt: 2 günde 3 sorag · galan <b>{n}</b> · täzelenýär {w}",
  "ai_pick": "🧠 <b>{name}</b>\n<blockquote>{d}\nGalan sorag  <b>{n}</b></blockquote>\n<i>Soragyňy ýaz</i> 👇",
  "aipro_info": "💎 <b>AI Premium</b>\n<blockquote>Ähli modeller: Claude Opus, GPT, Gemini, Grok, Kimi…\nHer 5 sagatda <b>{n}</b> sorag · {days} gün\nBahasy  <b>{usdt}$</b> / aý (CryptoBot ýa-da balans)</blockquote>\n<i>Abuna bolmazdan 2 günde {f} sorag mugt.</i>",
  "aipro_ok": "✅ <b>💎 AI Premium işjeň!</b>\n<blockquote>{until} çenli · her 5 sagatda {n} sorag</blockquote>\n🤖 düwmesinden model saýla.",
  "ai_busy": "⚠️ {name} häzir meşgul. Başga model saýla ýa-da birazdan synan. (Hakyň aýrylmady.)"})
T["ru"].update({"b_ai_bot": "❓ Вопрос о боте (бесплатно)", "b_ai_models": "🧠 Модели", "b_aipro": "💎 Premium · {usdt}$/мес", "b_aipro_buy": "💎 Купить · {usdt}$", "it_aipro": "💎 AI Premium · 30 дней",
  "ai_menu": "🤖 <b>Искусственный интеллект</b>\n<blockquote>{st}</blockquote>\n<blockquote expandable>{body}</blockquote>\n<i>❓ Вопросы о боте бесплатны. Моделям можно задавать любые вопросы (код, учёба, перевод…). Фото/видео не создаются.</i>",
  "ai_st_own": "👑 Основатель · без лимита", "ai_st_pro": "💎 Premium · до {until}\nОсталось <b>{n}/{lim}</b> · обновление в {r}", "ai_st_free": "🎁 Бесплатно: 3 вопроса за 2 дня · осталось <b>{n}</b> · обновление {w}",
  "ai_pick": "🧠 <b>{name}</b>\n<blockquote>{d}\nОсталось вопросов  <b>{n}</b></blockquote>\n<i>Напишите вопрос</i> 👇",
  "aipro_info": "💎 <b>AI Premium</b>\n<blockquote>Все модели: Claude Opus, GPT, Gemini, Grok, Kimi…\n<b>{n}</b> вопросов каждые 5 часов · {days} дней\nЦена  <b>{usdt}$</b> / мес (CryptoBot или баланс)</blockquote>\n<i>Без подписки — {f} вопроса за 2 дня бесплатно.</i>",
  "aipro_ok": "✅ <b>💎 AI Premium активен!</b>\n<blockquote>до {until} · {n} вопросов каждые 5 часов</blockquote>\nВыберите модель через 🤖.",
  "ai_busy": "⚠️ {name} сейчас занят. Выберите другую модель или попробуйте позже. (Вопрос не засчитан.)"})
T["tr"].update({"ai_fm_t": "🆓 <b>Ücretsiz modeller</b> · günde {n} soru", "ai_flim": "⏳ Ücretsiz modellerde bugünkü {n} soru hakkın bitti. Yarın tekrar sorabilirsin."})
T["tk"].update({"ai_fm_t": "🆓 <b>Mugt modeller</b> · günde {n} sorag", "ai_flim": "⏳ Mugt modellerde şu günki {n} sorag hakyň gutardy. Ertir gaýtadan sorap bilersiň."})
T["ru"].update({"ai_fm_t": "🆓 <b>Бесплатные модели</b> · {n} вопросов в день", "ai_flim": "⏳ Лимит {n} вопросов в день для бесплатных моделей исчерпан. Спросите завтра."})
T["tr"].update({"ai_legend": '🔴 en güçlü · 🔵 güçlü · 🟢 hızlı/hafif · 📷 fotoğraf görür', "ai_img_q": 'Bu fotoğrafı ayrıntılı analiz et.', "img_blocked": '⚠️ Bu istek uygunsuz bulunduğu için fotoğraf oluşturulmadı. Farklı yazıp tekrar dene.', "ai_plim": "⏳ Bu dönemdeki {n} soru hakkın bitti. {r}'de yenilenir.", "ai_novision": '📷 {name} fotoğraf göremez. Fotoğraf için şunlardan birini seç: {v}', "b_ai_new": "Yeni sohbet", "b_ai_hist": "📜 Geçmiş", "b_ai_go": "▶️ Sohbete devam et", "b_ai_del": "🗑 Sil", "ai_q": "soru",
  "ai_cont": "📜 Sohbete devam: <b>{t}</b> (önceki yazışmalar hatırlanıyor)", "ai_new_ok": "🧹 <b>Yeni sohbet</b> · {name}\n<i>Eski sohbet 📜 Geçmiş'te duruyor. Sorunu yaz</i> 👇",
  "ai_hist_t": "📜 <b>Geçmiş sohbetler</b>  <code>{n}</code>\n<i>Birini seç: yazışmaları gör, devam et ya da sil.</i>", "ai_hist_none": "📜 Henüz kayıtlı sohbet yok.",
  "ai_del_q": "🗑 <b>Bu sohbet silinsin mi?</b>\n<i>Yazışmalar geri gelmez.</i>", "ai_deleted": "🗑 Sohbet silindi.",
  "img_wait": "⏳ Fotoğraf oluşturuluyor (yaklaşık 1 dakika)…", "img_err": "⚠️ Fotoğraf oluşturulamadı: <code>{e}</code>\n<i>Sitede geçici bir hata olabilir; biraz sonra tekrar dene.</i>"})
T["tk"].update({"ai_legend": '🔴 iň güýçli · 🔵 güýçli · 🟢 çalt/ýeňil · 📷 surat görýär', "ai_img_q": 'Bu suraty jikme-jik seljer.', "img_blocked": '⚠️ Bu haýyş laýyk däl diýlip tapyldy, surat döredilmedi. Başgaça ýazyp gaýtadan synan.', "ai_plim": '⏳ Bu döwürdäki {n} sorag hakyň gutardy. {r}-da täzelenýär.', "ai_novision": '📷 {name} surat görüp bilmeýär. Surat üçin şulardan birini saýla: {v}', "b_ai_new": "Täze söhbet", "b_ai_hist": "📜 Taryh", "b_ai_go": "▶️ Söhbeti dowam et", "b_ai_del": "🗑 Poz", "ai_q": "sorag",
  "ai_cont": "📜 Söhbet dowam edýär: <b>{t}</b> (öňki ýazyşmalar ýatda)", "ai_new_ok": "🧹 <b>Täze söhbet</b> · {name}\n<i>Köne söhbet 📜 Taryh-da dur. Soragyňy ýaz</i> 👇",
  "ai_hist_t": "📜 <b>Öňki söhbetler</b>  <code>{n}</code>\n<i>Birini saýla: ýazyşmalary gör, dowam et ýa-da poz.</i>", "ai_hist_none": "📜 Entek ýazylan söhbet ýok.",
  "ai_del_q": "🗑 <b>Bu söhbet pozulsynmy?</b>\n<i>Ýazyşmalar yzyna gelmez.</i>", "ai_deleted": "🗑 Söhbet pozuldy.",
  "img_wait": "⏳ Surat döredilýär (takmynan 1 minut)…", "img_err": "⚠️ Surat döredip bolmady: <code>{e}</code>\n<i>Saýtda wagtlaýyn ýalňyşlyk bolup biler; birazdan gaýtadan synan.</i>"})
T["ru"].update({"ai_legend": '🔴 самые сильные · 🔵 сильные · 🟢 быстрые/лёгкие · 📷 видит фото', "ai_img_q": 'Подробно проанализируй это фото.', "img_blocked": '⚠️ Запрос признан неприемлемым, фото не создано. Переформулируйте.', "ai_plim": '⏳ Лимит {n} вопросов на этот период исчерпан. Обновится в {r}.', "ai_novision": '📷 {name} не видит фото. Для фото выберите: {v}', "b_ai_new": "Новый чат", "b_ai_hist": "📜 История", "b_ai_go": "▶️ Продолжить чат", "b_ai_del": "🗑 Удалить", "ai_q": "вопр.",
  "ai_cont": "📜 Продолжаем чат: <b>{t}</b> (прошлая переписка учитывается)", "ai_new_ok": "🧹 <b>Новый чат</b> · {name}\n<i>Старый чат остался в 📜 Истории. Напишите вопрос</i> 👇",
  "ai_hist_t": "📜 <b>Прошлые чаты</b>  <code>{n}</code>\n<i>Выберите: посмотреть, продолжить или удалить.</i>", "ai_hist_none": "📜 Сохранённых чатов пока нет.",
  "ai_del_q": "🗑 <b>Удалить этот чат?</b>\n<i>Переписку не вернуть.</i>", "ai_deleted": "🗑 Чат удалён.",
  "img_wait": "⏳ Фото создаётся (около минуты)…", "img_err": "⚠️ Не удалось создать фото: <code>{e}</code>\n<i>Возможен временный сбой на сайте; попробуйте чуть позже.</i>"})
T["tr"].update({"b_px": "📡 Telegram Proxy", "b_px_re": "🔄 Yenile",
  "px_t": "📡 <b>Telegram Proxy</b>\n<blockquote>Türkmenistan'dan test edildi, şu an çalışıyor.\n🕒 Son test: {ago}</blockquote>\n<i>Birine bas → Telegram'da bağlan. Çalışmazsa 🔄 Yenile.</i>",
  "px_none": "📡 Şu an test edilmiş çalışan proxy yok. Biraz sonra tekrar bak."})
T["tr"].update({"b_ai": "🤖 Yardımcı", "b_ai_end": "◀️ Menü",
  "ai_hi": "🤖 <b>Yardımcı</b>\n<blockquote>Bot hakkında sorunu yaz: fiyatlar, Pazar, kod alma, Happ'e ekleme, bakiye, kazanç çekme…\n🔢 Bugün kalan soru  <b>{n}</b></blockquote>\n<i>Sorunu mesaj olarak gönder</i> 👇",
  "ai_off": "🤖 Yardımcı şu an kapalı. 🆘 Support'a yazabilirsin.", "ai_text": "✍️ Sorunu yazı olarak gönder.",
  "ai_lim": "⏳ Bugünkü {n} soru hakkın bitti. Yarın tekrar sorabilir ya da 🆘 Support'a yazabilirsin.",
  "ai_err": "⚠️ Yardımcı şu an cevap veremedi, biraz sonra tekrar dene ya da 🆘 Support'a yaz. (Hakkın düşülmedi.)"})
T["tk"].update({"b_px": "📡 Telegram Proksi", "b_px_re": "🔄 Täzele",
  "px_t": "📡 <b>Telegram Proksi</b>\n<blockquote>Türkmenistandan barlandy, häzir işleýär.\n🕒 Soňky barlag: {ago}</blockquote>\n<i>Birine bas → Telegramda birikdir. Işlemese 🔄 Täzele.</i>",
  "px_none": "📡 Häzir barlanan işleýän proksi ýok. Birazdan gaýtadan seret."})
T["tk"].update({"b_ai": "🤖 Kömekçi", "b_ai_end": "◀️ Menýu",
  "ai_hi": "🤖 <b>Kömekçi</b>\n<blockquote>Bot barada soragyňy ýaz: bahalar, Bazar, kod almak, Happ-a goşmak, balans, gazanç çekmek…\n🔢 Şu gün galan sorag  <b>{n}</b></blockquote>\n<i>Soragyňy habar edip iber</i> 👇",
  "ai_off": "🤖 Kömekçi häzir ýapyk. 🆘 Goldaw-a ýazyp bilersiň.", "ai_text": "✍️ Soragyňy tekst görnüşinde iber.",
  "ai_lim": "⏳ Şu günki {n} sorag hakyň gutardy. Ertir gaýtadan sorap ýa-da 🆘 Goldaw-a ýazyp bilersiň.",
  "ai_err": "⚠️ Kömekçi häzir jogap berip bilmedi, birazdan gaýtadan synan ýa-da 🆘 Goldaw-a ýaz. (Hakyň aýrylmady.)"})
T["ru"].update({"b_px": "📡 Telegram Прокси", "b_px_re": "🔄 Обновить",
  "px_t": "📡 <b>Telegram Прокси</b>\n<blockquote>Проверены из Туркменистана, сейчас работают.\n🕒 Последняя проверка: {ago}</blockquote>\n<i>Нажмите на любой → подключите в Telegram. Не работает — 🔄 Обновить.</i>",
  "px_none": "📡 Сейчас нет проверенных рабочих прокси. Загляните чуть позже."})
T["ru"].update({"b_ai": "🤖 Помощник", "b_ai_end": "◀️ Меню",
  "ai_hi": "🤖 <b>Помощник</b>\n<blockquote>Задайте вопрос о боте: цены, Биржа, покупка кода, добавление в Happ, баланс, вывод…\n🔢 Осталось вопросов сегодня  <b>{n}</b></blockquote>\n<i>Отправьте вопрос сообщением</i> 👇",
  "ai_off": "🤖 Помощник сейчас выключен. Напишите в 🆘 Поддержку.", "ai_text": "✍️ Отправьте вопрос текстом.",
  "ai_lim": "⏳ Лимит {n} вопросов на сегодня исчерпан. Спросите завтра или напишите в 🆘 Поддержку.",
  "ai_err": "⚠️ Помощник сейчас не ответил, попробуйте позже или напишите в 🆘 Поддержку. (Вопрос не засчитан.)"})
T["tr"]["m_nsfw_warn"] = "⛔ <b>İlanın reddedildi</b>\n<blockquote>🏪 {title}\nSebep: 18+ / uygunsuz fotoğraf.</blockquote>\n⚠️ <b>Son uyarı:</b> tekrarlarsan bottan kalıcı olarak banlanırsın."
T["tk"]["m_nsfw_warn"] = "⛔ <b>Bildirişiň ret edildi</b>\n<blockquote>🏪 {title}\nSebäp: 18+ / ýerliksiz surat.</blockquote>\n⚠️ <b>Soňky duýduryş:</b> gaýtalasaň, botdan hemişelik ban alarsyň."
T["ru"]["m_nsfw_warn"] = "⛔ <b>Объявление отклонено</b>\n<blockquote>🏪 {title}\nПричина: 18+ / неприемлемое фото.</blockquote>\n⚠️ <b>Последнее предупреждение:</b> при повторе — вечный бан."
T["tr"]["m_nsfw_ban"] = "🚫 <b>Banlandın</b>\n<blockquote>İkinci kez 18+ / uygunsuz fotoğraf gönderdin.</blockquote>"
T["tk"]["m_nsfw_ban"] = "🚫 <b>Ban aldyň</b>\n<blockquote>Ikinji gezek 18+ / ýerliksiz surat iberdiň.</blockquote>"
T["ru"]["m_nsfw_ban"] = "🚫 <b>Вы заблокированы</b>\n<blockquote>Повторно отправлено 18+ / неприемлемое фото.</blockquote>"
T["tr"]["m_photo_ai"] = "📷 <b>İlanının fotoğrafı gösterilmeyecek</b>\n<blockquote>🏪 {title}\n{why}</blockquote>\n<i>İlanın yayında, sadece fotoğrafsız görünüyor. Gerçek ekran görüntüsüyle yeni ilan verebilirsin.</i>"
T["tk"]["m_photo_ai"] = "📷 <b>Bildirişiňiň suraty görkezilmez</b>\n<blockquote>🏪 {title}\n{why}</blockquote>\n<i>Bildirişiň bazarda, diňe suratsyz görünýär. Hakyky skrinşot bilen täze bildiriş goýup bilersiň.</i>"
T["ru"]["m_photo_ai"] = "📷 <b>Фото вашего объявления не будет показано</b>\n<blockquote>🏪 {title}\n{why}</blockquote>\n<i>Объявление на бирже, но без фото. Можно подать новое с настоящим скриншотом.</i>"
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
T["tr"].update({"sup_press": '✍️ Talebine (#{tid}) yazmak için önce <b>✍️ Yaz</b> butonuna bas. Bir kez basman yeterli, sonra talep kapanana kadar yazabilirsin.', "sup_cmd_q": '📩 <b>Açık destek talebin var (#{tid}).</b>\nKapatılsın mı?', "b_tclose_yes": '🔒 Evet, kapat', "b_tkeep": '✍️ Hayır, yazmaya devam', "b_twrite": "✍️ Yaz", "sup_ask": "✍️ <b>Mesajını gönder</b>\n<blockquote>Yazı, fotoğraf ya da video — fark etmez.</blockquote>",
  "sup_slow": "⏳ Biraz bekle, {s} sn sonra tekrar yaz."})
T["tk"].update({"sup_press": '✍️ Soragyňa (#{tid}) ýazmak üçin ilki <b>✍️ Ýaz</b> düwmesine bas. Bir gezek basmak ýeterlik, soňra sorag ýapylýança ýazyp bilersiň.', "sup_cmd_q": '📩 <b>Açyk goldaw soragyň bar (#{tid}).</b>\nÝapylsynmy?', "b_tclose_yes": '🔒 Hawa, ýap', "b_tkeep": '✍️ Ýok, ýazmagy dowam et', "b_twrite": "✍️ Ýaz", "sup_ask": "✍️ <b>Habaryňy iber</b>\n<blockquote>Tekst, surat ýa-da wideo — tapawudy ýok.</blockquote>",
  "sup_slow": "⏳ Azajyk garaş, {s} sek soň gaýtadan ýaz."})
T["ru"].update({"sup_press": '✍️ Чтобы написать в обращение (#{tid}), сначала нажмите <b>✍️ Написать</b>. Достаточно один раз — потом можно писать, пока обращение открыто.', "sup_cmd_q": '📩 <b>У вас открыто обращение (#{tid}).</b>\nЗакрыть его?', "b_tclose_yes": '🔒 Да, закрыть', "b_tkeep": '✍️ Нет, продолжить', "b_twrite": "✍️ Написать", "sup_ask": "✍️ <b>Отправьте сообщение</b>\n<blockquote>Текст, фото или видео — неважно.</blockquote>",
  "sup_slow": "⏳ Подождите {s} сек и напишите снова."})

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
T["tr"].update({"b_set": "🌐 Dil · 🇹🇲 🇹🇷 🇷🇺", "set_t": "⚙️ <b>Ayarlar</b>\n<blockquote>🌐 Dil  <b>{lname}</b>\n🆔 ID  <code>{id}</code></blockquote>\n<i>Dili değiştirmek için aşağıdan seç.</i>"})
T["tk"].update({"b_set": "🌐 Dil · 🇹🇲 🇹🇷 🇷🇺", "set_t": "⚙️ <b>Sazlamalar</b>\n<blockquote>🌐 Dil  <b>{lname}</b>\n🆔 ID  <code>{id}</code></blockquote>\n<i>Dili üýtgetmek üçin aşakdan saýlaň.</i>"})
T["ru"].update({"b_set": "🌐 Язык · 🇹🇲 🇹🇷 🇷🇺", "set_t": "⚙️ <b>Настройки</b>\n<blockquote>🌐 Язык  <b>{lname}</b>\n🆔 ID  <code>{id}</code></blockquote>\n<i>Выберите язык ниже.</i>"})

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

AI_PHOTO_MODEL = "anthropic/claude-opus-5.5"
AI_PHOTO_RULES = """Bir VPN pazarında satıcının ilanına koyduğu ekran görüntüsünü denetliyorsun. Yanında botun Türkmenistan'dan GERÇEKTEN ölçtüğü sonuçlar var.
Kontrol et:
1) vpn: Görüntü gerçekten bir VPN uygulamasının (Happ, v2rayNG, Hiddify vb.) sunucu/abonelik ekranı mı?
2) bad: Uygunsuz içerik var mı (çıplaklık, şiddet, hakaret, başka ürün reklamı, iletişim bilgisi/telefon/kanal linki ile müşteri kaçırma)?
3) misleading: Görüntüdeki iddia gerçek ölçümle belirgin şekilde çelişiyor mu? (ör. görüntüde 10+ ülke ama gerçekte 4; görüntüde hepsi düşük ping ama gerçekte çoğu çalışmıyor). Küçük farklar, isim/bayrak farkı, ping'in biraz farklı olması çelişki DEĞİLDİR. Emin değilsen false.
SADECE JSON döndür: {"vpn": true/false, "bad": true/false, "misleading": true/false, "reason": "Türkçe tek cümle"}"""

AI_PHOTO_PRE = """Bir VPN pazarında satıcının ilanına koyduğu fotoğrafı denetliyorsun.
bad: Uygunsuz içerik var mı? (çıplaklık/cinsel içerik, şiddet, kan, hakaret, nefret, uyuşturucu, başka ürün reklamı, telefon/kanal linkiyle müşteri kaçırma)
vpn: Görüntü bir VPN uygulamasının sunucu/abonelik ekranı mı?
SADECE JSON döndür: {"bad": true/false, "vpn": true/false, "reason": "Türkçe tek cümle"}"""

async def reject_listing(c, admin_uid, lid, why):
    """Kurucu ilanı reddeder (ceza yok). Dönüş: kurucuya gösterilecek yazı."""
    def f(d):
        L = d.get("market", {}).get(lid)
        if not L or L.get("own") or L.get("status") not in ("pending", "live", "suspended"): return None
        L["status"] = "rejected"; L["removed_ts"] = time.time(); L["removed_why"] = "admin"
        return L.get("owner"), L.get("title")
    r = mutate(f)
    if not r: return "⚠️ İlan bulunamadı ya da zaten kapalı."
    audit(admin_uid, f"mk_reject {lid}")
    ulog("m_rej", f"❌ Admin ilanı reddetti: {r[1]} · satıcı {r[0]}" + (f" · {why}" if why else ""))
    lg = lang_of(load_db(), r[0])
    try: await c.bot.send_message(r[0], tr(lg, "m_rejected", title=esc(r[1] or "?"), why=esc(why) if why else tr(lg, "rj_admin")), parse_mode="HTML")
    except Exception: pass
    return "✅ İlan reddedildi, satıcıya bildirildi."

async def ai_photo_precheck(app, lid):
    """İlan gelir gelmez: uygunsuz fotoğraf hemen kaldırılır (telefon testini beklemez)."""
    if not ai_key(): return
    L = load_db().get("market", {}).get(lid)
    if not L or not L.get("photo"): return
    try:
        f_ = await app.bot.get_file(L["photo"]); raw = bytes(await f_.download_as_bytearray())
        msgs = [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(raw).decode()}},
                                              {"type": "text", "text": "Bu fotoğrafı denetle."}]}]
        out = await asyncio.to_thread(ai_call, AI_PHOTO_PRE, msgs, None, 800, 120, AI_PHOTO_MODEL)
        mj = re.search(r"\{.*\}", out, re.S); j = json.loads(mj.group(0)) if mj else {}
    except Exception as e:
        log.warning("ai photo pre: %s", e); RUN["ai_err"] = f"photo pre: {str(e)[:120]}"; return
    if not j.get("bad"): return   # VPN ekranı mı / gerçekle uyumlu mu: telefon testinden sonra bakılır
    why = str(j.get("reason") or "")[:300]
    def f(d):
        x = d.get("market", {}).get(lid)
        if not x: return None
        ow = x.get("owner"); founder = ow in ADMINS   # kurucu test ediyor olabilir: ret/uyarı/ban YOK
        x["photo"], x["photo_ok"] = None, False; x["ai_photo"] = {"ok": False, "bad": True, "why": why, "ts": time.time()}
        n = 0
        if not founder:
            if x.get("status") in ("pending", "live", "suspended"): x["status"] = "rejected"; x["removed_ts"] = time.time(); x["removed_why"] = "nsfw"
            e = d["users"].setdefault(str(ow), {}); e["nsfw_n"] = e.get("nsfw_n", 0) + 1; n = e["nsfw_n"]
            if n >= 2: e["banned"] = True   # ikinci kez: kalıcı ban (kurucu tek tuşla açabilir)
        return ow, x.get("title"), founder, n
    r_ = mutate(f)
    if not r_: return
    ow, title, founder, n = r_
    if founder:
        await notify_founders(app, f"🧪 <b>Test: AI uygunsuz fotoğrafı yakaladı</b>\n<blockquote>{esc(title)}\n{esc(why)}</blockquote>\n<i>Senin ilanın olduğu için ret / uyarı / ban uygulanmadı, sadece fotoğraf kaldırıldı.</i>")
        return
    lg = lang_of(load_db(), ow)
    if n >= 2:
        ulog("ban", f"🚫 AI otomatik ban (2. kez 18+ fotoğraf): {title} · satıcı {ow}")
        for sid_, x_ in list(load_db().get("msess", {}).items()):   # açık pazar kodları durur
            if x_.get("buyer") == ow and x_.get("status") == "on": await stop_session(app, sid_, "user")
        try: await app.bot.send_message(ow, tr(lg, "m_nsfw_ban"), parse_mode="HTML")
        except Exception: pass
        nm = load_db().get("users", {}).get(str(ow), {}).get("name") or ow
        await notify_founders(app, f"🚫 <b>Banlandı: {esc(str(nm))}</b> <code>{ow}</code>\n<blockquote>2. kez 18+ / uygunsuz fotoğraf gönderdi.\nSon ilan: {esc(title)}\n{esc(why)}</blockquote>\n<i>Yanlışlık varsa buradan aç.</i>",
                              KB([[B("✅ Banı kaldır", f"ubn:{ow}", "success")]]))
        return
    ulog("m_rej", f"🔞 AI uygunsuz fotoğraf: ilan reddedildi (1. uyarı) · {title} · satıcı {ow}")
    try: await app.bot.send_message(ow, tr(lg, "m_nsfw_warn", title=esc(title)), parse_mode="HTML")
    except Exception: pass
    await notify_founders(app, f"🔞 <b>AI uygunsuz fotoğraf: ilan reddedildi</b> (1. uyarı)\n<blockquote>{esc(title)} · satıcı <code>{ow}</code>\n{esc(why)}</blockquote>\n<i>Tekrarlarsa otomatik ban.</i>",
                          KB([[B("🚫 Şimdi banla", f"bnq:{ow}", "danger")]]))

async def ai_photo_check(app, lid):
    """İlan yayına girince: AI fotoğrafı onaylar ya da gizler (kurucu her zaman geri alabilir)."""
    if not ai_key(): return
    L = load_db().get("market", {}).get(lid)
    if not L or L.get("own") or not L.get("photo") or L.get("photo_ok"): return
    try:
        f_ = await app.bot.get_file(L["photo"]); raw = bytes(await f_.download_as_bytearray())
        real = _plain(await real_report(lid, "tr"))
        msgs = [{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": base64.b64encode(raw).decode()}},
                                              {"type": "text", "text": f"İlan: {L.get('title', '')}\nGERÇEK ÖLÇÜM:\n{real[:3000]}"}]}]
        out = await asyncio.to_thread(ai_call, AI_PHOTO_RULES, msgs, None, 1500, 120, AI_PHOTO_MODEL)
        mj = re.search(r"\{.*\}", out, re.S); j = json.loads(mj.group(0)) if mj else {}
    except Exception as e:
        log.warning("ai photo: %s", e); RUN["ai_err"] = f"photo: {str(e)[:120]}"; return   # karar yok → eskisi gibi kurucu onayı bekler
    ok = bool(j.get("vpn")) and not j.get("bad") and not j.get("misleading")
    why = str(j.get("reason") or "")[:300]
    def f(d):
        x = d.get("market", {}).get(lid)
        if not x or x.get("photo_ok"): return None
        x["photo_ok"] = ok; x["ai_photo"] = {"ok": ok, "why": why, "ts": time.time()}
        return x.get("owner"), x.get("title")
    r_ = mutate(f)
    if not r_: return
    ow, title = r_
    ulog("m_ai_photo", f"🤖 AI fotoğraf {'onayladı' if ok else 'gizledi'}: {title} · {why}")
    if ok:
        await notify_founders(app, f"🤖✅ <b>AI fotoğrafı onayladı</b>\n<blockquote>{esc(title)}\n{esc(why)}</blockquote>", silent=True)
        return
    lg = lang_of(load_db(), ow)
    try: await app.bot.send_message(ow, tr(lg, "m_photo_ai", title=esc(title), why=esc(why)), parse_mode="HTML")
    except Exception: pass
    cap = f"🤖❌ <b>AI fotoğrafı gizledi</b> (ilan yayında, fotoğrafsız)\n<blockquote>{esc(title)}\n{esc(why)}</blockquote>\n<i>Yanlışsa ✅ Foto uygun'a bas.</i>"
    for fid_ in ADMINS:
        try: await app.bot.send_photo(fid_, L["photo"], caption=cap, parse_mode="HTML", reply_markup=photo_kb(lid, alang(fid_)))
        except Exception:
            try: await app.bot.send_message(fid_, cap, parse_mode="HTML", reply_markup=photo_kb(lid, alang(fid_)))
            except Exception: pass

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
 "tk": ['🛡 <b>DRIVE BOT · VPN BAZARY</b> 🌐\n\n<blockquote>❌ Telegram açylmaýarmy?\n❌ Proksi gözläp ýadadyňyzmy?\n❌ Alan VPN kodyňyz işlemedimi?</blockquote>\n<b>Drive Bot-da beýle zat ýok ✅</b>\n\n📡 <b><u>MUGT TELEGRAM PROKSI</u></b>\n<blockquote>🔄 Her 5 minutda TM-den barlanýar\n✅ Diňe häzir işleýänler berilýär\n👆 Bir basyşda birikdirilýär\n♻️ Ýapylsa — botdan täzesini alyň</blockquote>\n\n🛒 <b><u>KOD SATYN ALÝANLAR ÜÇIN</u></b>\n<blockquote>📡 Serwerler TM-den barlanýar\n🎯 Diňe <b>hakyky ýurtlar</b>\n⏱ Minut, sagat, hepde, aý\n⏹ Islän wagtyňyz yzyna gowşuryň</blockquote>\n\n🪪 <b><u>KOD SATÝANLAR ÜÇIN</u></b>\n<blockquote>💰 Bahany özüňiz goýýarsyňyz\n💸 Pul CryptoBot-a özi gelýär\n🤖 Satyşy bot özi ýöredýär\n📢 Bildiriş — bary-ýogy <b>0.05$</b></blockquote>\n\n🤖 <b><u>KÖMEKÇI — EMELI AŇ</u></b>\n<blockquote>💬 Bot hakda soraglara mugt jogap\n🧠 8 AI: Claude, GPT, Gemini, Grok\n🆓 2 günde 3 sorag mugt\n⭐ Premium — aýda 5$</blockquote>\n\n🎁 <b><u>DOSTUŇYZY ÇAGYRYŇ</u></b>\n<blockquote>👥 Her dost üçin <b>0.25 TMT</b> bonus\n🛒 Market-de kod almaga ulanyň</blockquote>\n\n👇 <i>Başlamak üçin</i>\n{link}'],
 "ru": ['🛡 <b>DRIVE BOT · БИРЖА VPN</b> 🌐\n\n<blockquote>❌ Не открывается Telegram?\n❌ Устали искать прокси?\n❌ Купленный код не работает?</blockquote>\n<b>В Drive Bot такого нет ✅</b>\n\n📡 <b><u>БЕСПЛАТНЫЕ ПРОКСИ TG</u></b>\n<blockquote>🔄 Проверка из TM каждые 5 мин\n✅ Только работающие сейчас\n👆 Подключение в одно касание\n♻️ Отключился — возьмите новый</blockquote>\n\n🛒 <b><u>ПОКУПАТЕЛЯМ КОДОВ</u></b>\n<blockquote>📡 Серверы проверяются из TM\n🎯 Только <b>реальные страны</b>\n⏱ Минута, час, неделя, месяц\n⏹ Остановите в любой момент</blockquote>\n\n🪪 <b><u>ПРОДАВЦАМ КОДОВ</u></b>\n<blockquote>💰 Цену ставите сами\n💸 Деньги сами идут в CryptoBot\n🤖 Продажи ведёт бот\n📢 Объявление — всего <b>0.05$</b></blockquote>\n\n🤖 <b><u>ПОМОЩНИК — ИИ</u></b>\n<blockquote>💬 Бесплатно ответит о боте\n🧠 8 ИИ: Claude, GPT, Gemini, Grok\n🆓 3 вопроса бесплатно за 2 дня\n⭐ Premium — 5$ в месяц</blockquote>\n\n🎁 <b><u>ПРИГЛАСИ ДРУГА</u></b>\n<blockquote>👥 За каждого друга <b>0.25 TMT</b>\n🛒 Тратьте на коды в Маркете</blockquote>\n\n👇 <i>Начать</i>\n{link}']}

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
                    asyncio.ensure_future(ai_photo_check(app, lid))   # 🤖 fotoğraf otomatik kontrol
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

# ───────── 📡 Telegram proxy: açık kanallardan toplanır, Türkmenistan'daki telefonda gerçek el sıkışmayla test edilir ─────────
PX_SEEDS = ["ProxyMTProto", "Proxy_MTM", "TelMTProto", "MTProtoProxies", "proxymtprotoir", "Myporoxy", "iRoProxy", "MTP_roto",
            "ProxyMTProto_tel", "Proxy_Qavi", "NetAccount", "MProxy_ir", "Mtproto_Proxy", "vpnandproxyfree", "proxy_kafee", "hack_proxy",
            "SecureMTProto", "BLACK_SERWERS"]
PX_LISTS = ["https://raw.githubusercontent.com/SoliSpirit/mtproto/master/all_proxies.txt"]   # GitHub'daki toplu liste
PX_EVERY, PX_MAX_CH, PX_POOL, PX_SHOW, PX_FRESH = 30 * 60, 60, 400, 8, 6 * 3600
PX_NAME = "tmproxy.txt"   # telefonla ayrı kanal (ana kanal 15 sn'de bir okunuyor; büyük liste oraya konmaz)
PX_RE = re.compile(r"(?:tg://proxy|https?://t\.me/proxy)\?[^\"'<>\s]+")
PX_SKIP = {"proxy", "share", "joinchat", "addlist", "socks", "iv", "addstickers", "boost", "contact"}
PX = {"next": 0, "tried": {}}

def px_norm(link):
    """Proxy linki → tek biçim (https://t.me/proxy?server=&port=&secret=). Bozuksa None."""
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(html.unescape(link).replace("+", "%2B")).query)
        h, pt, sec = qs["server"][0].strip().lower(), int(qs["port"][0]), qs["secret"][0].strip()
        if not re.fullmatch(r"[a-z0-9.\-]{3,253}", h) or not 0 < pt < 65536 or not re.fullmatch(r"[\w\-+/=]{16,300}", sec): return None
        return f"https://t.me/proxy?server={h}&port={pt}&secret={urllib.parse.quote(sec, safe='')}"
    except Exception: return None

def _px_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r: return html.unescape(r.read(3000000).decode("utf-8", "ignore"))

def _px_page(name):
    """Açık kanalın web önizlemesi (t.me/s/…): proxy linkleri + anılan kanallar. Açılmazsa links=None."""
    try:
        t = _px_get("https://t.me/s/" + name)
        return name, PX_RE.findall(t), {x.lower() for x in re.findall(r"t\.me/([A-Za-z]\w{4,31})", t)}
    except Exception: return name, None, set()

def px_collect(db):
    """Bloklayan iş. Kanallardan + listeden proxy toplar, yeni kanal keşfeder. Dönüş: (havuz, kanallar)."""
    chans = {k: dict(v) for k, v in (db.get("px", {}).get("chans") or {}).items()}
    low = {k.lower() for k in chans}
    for x in PX_SEEDS:   # başlangıç kanalları hep listede (sonradan eklenenler de çalışan bota geçer)
        if x.lower() not in low: chans[x] = {"n": 0, "z": 0}
    found, ment = [], {}
    with ThreadPoolExecutor(8) as ex: res = list(ex.map(_px_page, list(chans)))
    known = {k.lower() for k in chans}
    for name, links, mm in res:
        if links is None: continue   # sayfa açılmadı: sayılmaz
        n = len({px_norm(l) for l in links} - {None})
        chans[name] = {**chans[name], "n": n, "z": 0 if n else chans[name].get("z", 0) + 1}
        found += links
        if n:
            for m_ in mm - known - PX_SKIP: ment[m_] = ment.get(m_, 0) + 1
    # 🔎 keşif: proxy kanallarında anılan yeni kanallar (günde bir kez denenir; ≥3 proxy varsa eklenir)
    now = time.time()
    cand = [k for k in sorted(ment, key=lambda k: -ment[k]) if now - PX["tried"].get(k, 0) > 86400][:15]
    if cand and len(chans) < PX_MAX_CH:
        for k in cand: PX["tried"][k] = now
        with ThreadPoolExecutor(8) as ex: res2 = list(ex.map(_px_page, cand))
        for name, links, _ in res2:
            n = len({px_norm(l) for l in (links or [])} - {None})
            if n >= 3 and len(chans) < PX_MAX_CH:
                chans[name] = {"n": n, "z": 0, "new": int(now)}; found += links
                vlog(f"📡 Yeni proxy kanalı bulundu: @{name} ({n} proxy)")
    chans = {k: v for k, v in chans.items() if v.get("z", 0) < 6}   # 6 tarama (3 saat) üst üste boş: çıkarılır
    for u in PX_LISTS:
        try: found += PX_RE.findall(_px_get(u))
        except Exception as e: log.info("px list: %s", e)
    return list(dict.fromkeys(x for x in map(px_norm, found) if x))[:PX_POOL], chans   # önce kanallar (taze), sonra liste

def px_channel(fn=None):
    """Telefonla proxy kanalı (Drive: tmproxy.txt). fn(ch) True dönerse yazılır. Dönüş: kanal içeriği."""
    svc = new_service(); db = load_db(); fid = db.get("px_fid"); ch = None
    if fid:
        try:
            raw = svc.files().get_media(fileId=fid).execute(num_retries=2).decode("utf-8", "ignore").strip()
            ch = json.loads(raw) if raw.startswith("{") else {}
        except Exception as e:
            if "404" not in str(e) and "notFound" not in str(e): raise
            fid = None
    if not fid:
        if fn is None: return {}
        fid = _tm_create(svc, db, {}, PX_NAME); mutate(lambda d: d.__setitem__("px_fid", fid)); ch = {}
    if fn and fn(ch): _tm_write(svc, fid, ch)
    return ch

def px_tick():
    """Bloklayan iş (2 dk'da bir): 30 dk'da bir toplar → telefona verir; telefonun sonucunu okur."""
    now = time.time()
    if now >= PX["next"]:
        PX["next"] = now + PX_EVERY
        pool, chans = px_collect(load_db())
        mutate(lambda d: d.setdefault("px", {}).update(chans=chans, pool_n=len(pool), col_ts=int(now)))
        if pool:
            def put(ch):
                if ch.get("px_list") == pool: return False
                ch["px_list"], ch["px_ts"] = pool, int(now); return True
            px_channel(put)
    ch = px_channel()
    r, ts = ch.get("px_res") or {}, ch.get("px_res_ts") or 0
    if ts and ts != load_db().get("px", {}).get("ok_ts"):
        ok = sorted(([l, ms] for l, ms in r.items() if isinstance(ms, int) and ms > 0), key=lambda x: x[1])[:30]
        mutate(lambda d: d.setdefault("px", {}).update(ok=ok, ok_ts=ts, tested=len(r), good=sum(1 for v in r.values() if isinstance(v, int) and v > 0)))

async def proxy_loop(app):
    await asyncio.sleep(20)
    while True:
        try: await asyncio.to_thread(px_tick)
        except Exception as e: log.warning("proxy tick: %s", e)
        await asyncio.sleep(120)

def px_user_view(lang):
    px = load_db().get("px", {}); ok = px.get("ok") or []
    back_ = [[B(tr(lang, "b_px_re"), "u_px", "primary")], [B(tr(lang, "b_menu"), "u_menu")]]
    if not ok or time.time() - px.get("ok_ts", 0) > PX_FRESH: return tr(lang, "px_none"), KB(back_)
    rows = [[B(f"⚡ Proxy {i + 1} · {ms} ms", url=l)] for i, (l, ms) in enumerate(ok[:PX_SHOW])]
    return tr(lang, "px_t", ago=ago_l(px["ok_ts"], lang)), KB(rows + back_)

def px_admin_view():
    px = load_db().get("px", {}); chs = px.get("chans", {})
    body = "\n".join(f"{'🆕' if v.get('new') else '•'} @{esc(k)} · {v.get('n', 0)}" for k, v in sorted(chs.items(), key=lambda x: -x[1].get("n", 0))) or "—"
    t = (f"📡 <b>Telegram Proxy</b>\n<blockquote>📥 Toplanan: <b>{px.get('pool_n', 0)}</b> · {ago(px.get('col_ts'))}\n"
         f"📱 TM testi: <b>{px.get('good', 0)}</b>/{px.get('tested', 0)} çalışıyor · {ago(px.get('ok_ts'))}\n📢 Kanal: {len(chs)}</blockquote>\n"
         f"<blockquote expandable>{body}</blockquote>\n"
         "<i>Kanallar 30 dk'da bir taranır; proxy kanallarında anılan yeni kanallar kendiliğinden eklenir, 3 saat boş kalan çıkarılır. "
         "Telefon 5 dk'da bir hepsine gerçekten bağlanmayı dener (tmtest güncel olmalı).</i>")
    return t, KB([[B("🔄 Şimdi topla", "px_now", "primary")], [B("◀️ Admin", "admin")]])

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

async def pad_old_photos(app):
    """Bir kez: eski ilan fotoğrafları (resmi ilan dahil) kırpılmadan tam görünecek şekilde yeniden yüklenir."""
    await asyncio.sleep(20)
    try: import PIL   # noqa
    except ImportError:
        vlog("⚠️ İlan fotoğrafları tam görünsün diye VPS'te Pillow gerekli: pip install pillow"); return
    todo = [(lid, L["photo"]) for lid, L in load_db().get("market", {}).items() if L.get("photo") and not L.get("pad_ok")]
    n = 0
    for lid, fid in todo:
        new = None
        try: new = await full_view_photo(app, next(iter(ADMINS)), fid)
        except Exception as e: log.info("pad old %s: %s", lid, e)
        def f(d):
            L = d.get("market", {}).get(lid)
            if L and L.get("photo") == fid:
                if new: L["photo"] = new
                L["pad_ok"] = True
        mutate(f); n += bool(new)
        await asyncio.sleep(1)
    if n: vlog(f"🖼 {n} ilan fotoğrafı tam görünecek şekilde düzeltildi")

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
    app.add_handler(MessageHandler(filters.COMMAND, other_cmd))
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
