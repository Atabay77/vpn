import os, sys, io, re, json, html, uuid, base64, asyncio, zipfile, shutil, fcntl, logging, datetime, time, socket, random, hashlib, warnings, unicodedata, threading
import urllib.request, urllib.parse, urllib.error
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from telegram import Update, InlineKeyboardButton as _IKB, InlineKeyboardMarkup as KB, InputMediaPhoto

def B(text, callback_data=None, style=None, **kw):
    """Buton. style: "success" (yeşil), "primary" (mavi), "danger" (kırmızı) — eski Telegram'da yok sayılır."""
    if style: kw["api_kwargs"] = {"style": style}
    return _IKB(text, callback_data=callback_data, **kw)
from telegram.error import BadRequest
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
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
NEW_IP_LIMIT = 3       # bundan FAZLA yeni IP görülürse kodlar yenilenir
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

def rename_all(codes, geo, ms=None, fresh=False, exits=None):
    """Kuralar:
    - Rusya tek: birden fazla Rusya varsa en iyi ms'li kalır, her zaman 2. sırada.
    - Telefon testinde ms'i olanlar ms'e göre sıralanır; test edilmemişler en altta, rastgele bayrakla.
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
             + (f" · {dropped} elendi" if dropped else "") + (f" · {skipped} bayrak bitti" if skipped else "")]
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
    tm_changed = sorted(dead_tm) != sorted(db.get("tm_dead_pushed", [])) or RUN.pop("exits_changed", False)
    if not force and old and len(new) <= NEW_IP_LIMIT and not tm_changed:
        RUN["last_msg"] = f"✅ {len(codes)} kod, {len(new)} yeni IP → değişiklik yok"
        vlog(f"ℹ️ {len(codes)} kod · {len(new)} yeni IP (eşik: {NEW_IP_LIMIT}'ten fazla) → değişiklik yok")
        return None

    why = "⚡ Elle güncelleme" if force else (f"🚨 {len(new)} yeni IP bulundu" if (not old or len(new) > NEW_IP_LIMIT) else "📱 Telefon testi değişti")
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
    renamed, notes = rename_all(codes, geo, tm_ms, tm_fresh, tm_exits)
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
        for f in [DB_FILE, SA_FILE, ENV_FILE, VIP_LOG, AUDIT_LOG, USERS_LOG, GEO_FILE, "/root/sohbet.txt", os.path.abspath(__file__)]:
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
    line = tr(lang, "menu_bal", bal=fmt_u(e.get("bal", 0)), tmt=tmt_u(e.get("bal", 0)))
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
    tm = RUN["tm_line"].replace("📱 Telefon testi: ", "")
    return ("✦ <b>VPN PANEL</b> ✦\n"
            f"<blockquote>⚙️ Sistem  <b>{'🟢 Çalışıyor' if on else '🔴 Durduruldu'}</b>\n"
            f"🔍 Son kontrol  <i>{ago(RUN['last_check'])}</i>\n"
            f"🔄 Son güncelleme  <i>{ago(db.get('last_update') if db else None)}</i>\n"
            f"📱 Telefon testi  <i>{esc(tm)}</i></blockquote>\n"
            f"📡 <b>{n}</b> kod  ·  🔗 <b>{src}</b> abonelik  ·  👥 <b>{vip}</b> VIP  ·  🙋 <b>{len(db.get('users', {})) if db else '?'}</b> kullanıcı")

def main_kb(uid):
    kb = _main_kb(uid)
    try: extra = open_mkt_row(load_db(), uid, lang_of(None, uid))
    except Exception: extra = []
    return KB([list(r) for r in kb.inline_keyboard[:1]] + extra + [list(r) for r in kb.inline_keyboard[1:]]) if extra else kb

def _main_kb(uid):
    is_ru(uid); lang_btn = B({"ru": "🌐 Язык: Русский", "tk": "🌐 Dil: Türkmençe"}.get(LANGC.get(uid), "🌐 Dil: Türkçe"), "lang")
    if uid not in ADMINS:   # panel sahibi: kendi panelinde kod oluşturur
        return KB([[B(L(uid, "🏪 Pazar", "🏪 Биржа"), "u_mkt", "success")],
                   [B(L(uid, "✨ Kod Oluştur", "✨ Создать код"), "create_key"), B(L(uid, "👥 Kodlarım", "👥 Мои коды"), "my_keys", "primary")],
                   [B(L(uid, "👤 Profil", "👤 Профиль"), "u_prof"), B(L(uid, "🛒 Market", "🛒 Магазин"), "u_market")],
                   [B(L(uid, "🆘 Support", "🆘 Поддержка"), "u_sup"), B(L(uid, "🐞 Hata Bildir", "🐞 Баг-репорт"), "u_bug")],
                   [lang_btn]])
    # kurucu: kullanıcıların gördüğü butonlar + tek bir Admin butonu (geri kalan her şey Admin'in içinde)
    return KB([[B(L(uid, "🏪 Pazar", "🏪 Биржа"), "u_mkt", "success")],
               [B(L(uid, "✨ Kod Oluştur", "✨ Создать код"), "u_free"), B(L(uid, "👥 Kodlarım", "👥 Мои коды"), "my_keys")],
               [B(L(uid, "👤 Profil", "👤 Профиль"), "u_prof"), B(L(uid, "🛒 Market", "🛒 Магазин"), "u_market")],
               [B(L(uid, "🆘 Support", "🆘 Поддержка"), "tickets"), B(L(uid, "🐞 Hata Bildir", "🐞 Баг-репорт"), "tickets_bug")],
               [lang_btn],
               [B("🟡 Admin", "admin", "danger")]])

def admin_text():
    on = not os.path.exists(STOP_FLAG)
    return ("⚙️ <b>Admin</b>\n"
            f"<blockquote>⚙️ Sistem  <b>{'🟢 Çalışıyor' if on else '🔴 Durduruldu'}</b>\n"
            f"🔍 Kontrol her <b>{CHECK_EVERY // 60} dk</b>\n"
            f"🚨 <b>{NEW_IP_LIMIT}</b>'ten fazla yeni IP → bütün kodlar yenilenir\n"
            "📱 TM'de çalışmayan kodlar telefon testine göre çıkarılır\n"
            "🕰 Otomatik duyuru (Aşkabat saati):\n" + "\n".join(f"   {h:02d}:00  {esc(t)}" for h, t in sorted(AUTO_ANN.items())) + "</blockquote>")

def admin_kb():
    try: on = load_db().get("auto_ann_on", True)
    except Exception: on = True
    stop = os.path.exists(STOP_FLAG)
    return KB([
        [B("🛠 Admin Kod Oluştur", "create_key", "primary")],
        [B("🔗 Abonelikler", "sources"), B("📜 Loglar", "logs")],
        [B("🏷 Toplu Başlık", "bulk_title"), B(f"🎫 Destek ({sum(1 for t in load_db().get('tickets', {}).values() if t.get('status') == 'open')})", "tickets")],
        [B("⚡ Güncelle", "upd_now"), B("📦 Yedek", "get_zip")],
        [B("👥 Kullanıcı Logları", "ul_open")],
        [B("🔎 Kullanıcı Ara", "usearch")],
        [B("💰 Bakiye Ekle / Düş", "bal_find")],
        [B("🚫 Ban / Unban", "ban_menu")],
        [B("📈 Rapor", "rep_today"), B("📊 İstatistik", "stats")],
        [B("📢 Kanallar", "chans"), B("🪙 CryptoBot", "cp")],
        [B("🏪 Pazar", "mk_admin"), B("💳 TMT 🔜", "pay_set")],
        [B("📣 Herkese Mesaj", "bcast")],
        [B("👮 Alt Adminler", "sa_menu")],
        [B("🧪 Davet Testi", "ref_test")],
        [B("🔒 Happ Limitli Kod", "hp")],
        [B(f"🕰 Oto. Duyuru: {'Açık' if on else 'Kapalı'}", "auto_ann")],
        [B("♻️ Önceki Sürüme Dön", "rollback")],
        [B("▶️ Başlat", "toggle_sys", "success") if stop else B("🛑 Durdur", "toggle_sys", "danger")],
        [B("◀️ Menü", "menu")]])

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
            ([B("🔒 Happ Limit", f"hl:{kid}")] if uid in ADMINS else []) + [B(L(uid, "🗑 Sil", "🗑 Удалить"), f"kd:{kid}", "danger")],
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
                f"🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>\n<code>{esc(user_link(fid))}</code>",
                KB([[B("🎟 К коду", f"kv:{kid}", "primary"), B("◀️ Меню", "menu")]]))
    return (f"✅ <b>Kod oluşturuldu!</b>\n<blockquote>🎟 <b>{esc(name)}</b>\n⏳ Süre  <b>{left}</b></blockquote>\n"
            f"🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>\n<code>{esc(user_link(fid))}</code>",
            KB([[B("🎟 Koda Git", f"kv:{kid}", "primary"), B("◀️ Menü", "menu")]]))

async def on_num(c, uid, st, n, send, who=""):
    """send(text, kb): mesajı düzenler ya da yeni mesaj atar."""
    what = st["what"]
    if what.startswith("sa_") and uid not in ADMINS: return
    lo = 0 if what == "nk_days" and uid in ADMINS else 1
    hi = 500 if what in ("sa_limit", "sa_lim") else 100 if what == "hp_limit" else 3650
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

FOUNDER_ONLY = {"ban_menu", "ban_find", "hp", "hp_set", "hp_del", "hp_new", "ref_test", "mk_admin", "mk_price", "mk_oph", "mk_ods", "mk_odr", "bal_find", "usearch", "rep_today", "rep_yday", "tickets_bug", "t_cancel", "tickets", "cp_test", "cp", "cp_set", "cp_del", "ul_open", "stats", "chans", "ch_add", "pay_set", "bcast", "bcast_yes", "rollback", "rollback_yes", "auto_ann", "toggle_sys", "admin", "sources", "s_add", "logs", "upd_now", "get_zip", "sa_menu", "sa_add", "bulk_ann", "bulk_title", "bulk_yes"}
OWNED = ("kv", "kt", "kn", "ka", "kd", "kdy")   # alt admin sadece kendi kodunda
def src_find(db, h): return next((s for s in db["sources"] if hashlib.md5(s.encode()).hexdigest()[:8] == h), None)

async def cb(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    uid = q.from_user.id
    a = q.data
    if a.startswith("u_") or not is_admin(uid) or is_banned(uid): return await pub_cb(u, c)
    if uid not in ADMINS:
        miss = await missing_channels(c.bot, uid)
        if miss:
            await q.answer(); await safe_edit(q, *join_view(lang_of(load_db(), uid), miss)); return
    if uid not in ADMINS and (a in FOUNDER_ONLY or a.startswith(("sv:", "se:", "sd:", "sa_del:", "sa_ext:", "sa_lim:", "kx:", "kxs:", "ul:", "chd:", "ord_ok:", "ord_no:", "t_rep:", "t_close:", "tv:", "ug:", "ux:", "uxc:", "ub:", "uv:", "ubal:", "mk_l:", "mk_ok:", "mk_rm:", "mk_ph:", "mk_pok:", "mk_pno:", "mk_prj:", "hl:", "hlp:", "ubn:", "bnd:", "bnq:"))):
        await q.answer(L(uid, "⛔ Erişim yok", "⛔ Нет доступа"), show_alert=True); return
    if a not in ("toggle_sys", "upd_now"):
        await q.answer()
    if a != "logs" and uid in LIVE:
        LIVE.pop(uid).cancel()
    if a != "menu": q = await off_banner(c, q)   # banner'lı menüden başka ekrana: yazı mesajına geç
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
        await safe_edit(q, *tickets_view(a == "tickets_bug"))

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
        await safe_edit(q, admin_text(), admin_kb())

    elif a == "admin":
        STATE.pop(uid, None)
        await safe_edit(q, admin_text(), admin_kb())

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

    elif a == "auto_ann":
        on = mutate(lambda d: d.__setitem__("auto_ann_on", not d.get("auto_ann_on", True)) or d["auto_ann_on"])
        audit(uid, f"auto_ann {'on' if on else 'off'}")
        await safe_edit(q, "⚙️ <b>Admin</b>\n<blockquote>🕰 Otomatik duyuru " + ("<b>açık</b>: " + ", ".join(f"{h:02d}:00" for h in sorted(AUTO_ANN)) + "'da genel duyuru değişir." if on else "<b>kapalı</b>.") + "</blockquote>", admin_kb())

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
        await safe_edit(q, L(uid, "👥 <b>Kodlarım</b>", "👥 <b>Мои коды</b>") + f"  <code>{len(items)}</code>\n"
                        + "<blockquote>" + L(uid, "Yönetmek için bir koda dokun.", "Нажмите на код, чтобы управлять им.") + (L(uid, f"\n🔴 = süresi dolmuş ({expd})", f"\n🔴 = срок истёк ({expd})") if expd else "") + "</blockquote>", KB(rows))

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
         "ℹ️ Happ API'si sadece ücretli planda çalışıyor. Free planda: linki happ-proxy.com → Limited links'ten oluştur (10 adet), çıkan Install code'u bota yapıştır.</blockquote>\n"
         "<i>Kodlarım → kod → 🔒 Happ Limit → ✍️ Siteden Yapıştır.</i>")
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
             [B(tr(lang, "b_lang"), "u_lang")]])
    return t, kb

def home(uid):
    """Kurucu/panel sahibi -> kendi paneli, diğerleri -> kullanıcı menüsü."""
    return (menu_text(uid), main_kb(uid)) if is_admin(uid) else pub_menu(load_db(), uid)

def share_url(lang, uid):
    return "https://t.me/share/url?" + urllib.parse.urlencode({"url": ref_link(uid), "text": tr(lang, "share_text")})

async def credit_ref(c, uid):
    """Doğrulama + kanal şartı tamamlanınca daveti sayar (bir kez)."""
    def f(d):
        e = d["users"].get(str(uid), {})
        if e.get("ok"): return None
        e["ok"] = True; e.pop("cap", None)
        inv = d["users"].get(str(e.get("ref_by")))
        if not inv or uid in inv.setdefault("refs", []): return None
        inv["refs"].append(uid)
        return e.get("ref_by"), inv.get("lang", "tr"), avail_refs(inv), inv.get("name", "")
    r = mutate(f)
    if not r: return
    inv_id, ilang, av, iname = r
    db = load_db(); me = db["users"].get(str(uid), {})
    ulog("credit", f"🤝 Davet sayıldı: {iname} ({inv_id}) → {me.get('name')} ({uid}) · davet {av}/{REF_NEED}")
    try:
        await c.bot.send_message(inv_id, tr(ilang, "ref_new", name=esc(me.get("name") or uid), avail=min(av, REF_NEED), need=REF_NEED), parse_mode="HTML")
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
    if a not in ("u_menu", "u_mkt"): q = await off_banner(c, q)   # banner'lı menüden başka ekrana: yazı mesajına geç
    db = load_db(); lang = lang_of(db, uid)
    async def send(t, kb=None):
        if getattr(getattr(q, "message", None), "photo", None):   # fotoğraflı kartın metni düzenlenemez
            await c.bot.send_message(uid, t, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        else: await safe_edit(q, t, kb)
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
        await send(tr(lang, key, tid=tid), KB([[B(tr(lang, "b_tclose"), "u_tclose", "danger")], [B(tr(lang, "b_menu"), "u_menu")]]))

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
        kb = chk_kb(lang, lid); t = check_text(load_db(), lid, lang, CHK.get("last_ch"), mode)
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
        else: await edit_box(c.bot, uid, mid, is_photo, check_text(load_db(), lid, lang, ch, state), kb)
        ulog("m_check", f"🔍 Kontrol etti: {who(user)} · {db.get('market', {}).get(lid, {}).get('title', lid)}")

    elif a.startswith("u_mph:"):
        L_ = db.get("market", {}).get(a.split(":", 1)[1], {})
        if L_.get("photo") and L_.get("photo_ok", True):
            try: await c.bot.send_photo(uid, L_["photo"], caption=f"🏪 {L_.get('title', '')}"[:1000])
            except Exception: pass

    elif a.startswith("u_ms:"):
        lid = a.split(":", 1)[1]
        res, err = await asyncio.to_thread(mkt_start, uid, lid)
        if not res:
            if err.startswith("nobal:"):
                await send(tr(lang, "m_need", need=fmt_u(int(err.split(":")[1])), bal=fmt_u(load_db()["users"].get(str(uid), {}).get("bal", 0))),
                           KB([[B(tr(lang, "b_top"), "u_top", "success")], [B(tr(lang, "b_back_mkt"), f"u_ml:{lid}")]]))
            elif err == "already": await send(tr(lang, "m_already"), KB([[B(tr(lang, "b_mine"), "u_mine")], [B(tr(lang, "b_back_mkt"), "u_mkt")]]))
            elif err == "gone": await send(tr(lang, "m_gone"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]]))
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

    elif a.startswith("u_vip:"):
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
            if any(L.get("link") == st_["link"] and L.get("status") in ("pending", "live") for L in d.get("market", {}).values()): return "dup"
            if x.get("bal", 0) < MKT_FEE: return "nobal"
            x["bal"] -= MKT_FEE; d["mkt_fees"] = d.get("mkt_fees", 0) + MKT_FEE
            lid = uuid.uuid4().hex[:6]
            d.setdefault("market", {})[lid] = {"owner": uid, "title": st_["title"], "link": st_["link"], "photo": st_["photo"], "desc": st_.get("desc", ""),
                                               "price": st_["price"], "codes": st_["codes"], "codes_ts": time.time(), "status": "pending", "created": time.time(), "photo_ok": False}
            return lid
        r = mutate(f); new_lid = r if r not in ("nobal", "dup", "ban") else None
        if r == "nobal": await send(tr(lang, "sell_nobal"), KB([[B(tr(lang, "b_top"), "u_top", "success")], [B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        STATE.pop(uid, None)
        if r == "dup": await send(tr(lang, "sell_dup"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        if r == "ban": await send(tr(lang, "sell_banned", left="—"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        ulog("m_list", f"📤 Pazara ilan verdi: {who(user)} · {st_['title']} · {fmt_u(st_['price'])} USDT/dk")
        await send(tr(lang, "sell_sent"), KB([[B(tr(lang, "b_myl"), "u_myl")], [B(tr(lang, "b_back_mkt"), "u_mkt")]]))
        cap_ = (f"📤 <b>Yeni pazar ilanı</b> (incelemede)\n<blockquote>{esc(who(user))}\n🏷 {esc(st_['title'])} · {money_tmt(float(st_['price']) * 43200)} TMT/ay</blockquote>\n"
                "<i>⏳ Telefon testi bekleniyor. Fotoğrafı sen onaylayana kadar pazarda fotoğrafsız görünür.</i>")
        kb_ = photo_kb(new_lid)
        for fid_ in ADMINS:
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
        rows += [[B(f"🗑 {short(L['title'], 22)}", f"u_mld:{lid}", "danger")] for lid, L in mine_l if L["status"] in ("pending", "live")]
        await send(tr(lang, "myl") + "\n" + body, KB(rows + [[B(tr(lang, "b_back_mkt"), "u_mkt")]]))

    elif a.startswith("u_mld:"):
        lid = a.split(":", 1)[1]
        def f(d):
            L = d.get("market", {}).get(lid)
            if not L or L.get("owner") != uid or L.get("status") not in ("pending", "live"): return False
            L["status"] = "removed"; L["removed_ts"] = time.time(); L["removed_why"] = "seller"; return True
        if mutate(f): ulog("m_rm", f"🗑 Satıcı ilanını kaldırdı: {who(user)} · {lid}")
        await show_market(c, q, uid, lang)

    elif a == "u_top":
        STATE.pop(uid, None)
        await send(tr(lang, "top", bal=fmt_u(e.get("bal", 0))) + tr(lang, "top_sellers", sellers=" · ".join(USDT_SELLERS)),
                   KB([[B(f"{n} USDT", f"u_topa:{n}", "primary") for n in (1, 3, 5, 10)],
                       [B(f"{n * USDT_RATE} TMT", f"u_topa:{n}") for n in (1, 3, 5, 10)],   # aynı tutar, TMT karşılığıyla (ödeme yine CryptoBot)
                       [B(tr(lang, "b_other"), "u_topc")], [B(tr(lang, "b_menu"), "u_menu")]]))

    elif a.startswith("u_topa:"):
        await send(*topup_order(uid, user, lang, float(a.split(":", 1)[1])))

    elif a == "u_topc":
        STATE[uid] = {"action": "u_topamt"}
        await send(tr(lang, "top_ask"), KB([[B(tr(lang, "b_cancel"), "u_top")]]))

    elif a == "u_wd":
        amt = e.get("earn", 0)
        if amt < WITHDRAW_MIN: await send(tr(lang, "wd_min", earn=fmt_u(amt)), menu_btn); return
        def take(d):
            x = d["users"][str(uid)]
            if x.get("earn", 0) < amt: return False
            x["earn"] -= amt; return True
        if not mutate(take): return
        try:
            await asyncio.to_thread(crypto_call, "transfer", user_id=uid, asset="USDT", amount=fmt_u(amt), spend_id=f"wd-{uid}-{int(time.time())}", comment="VPN pazarı kazancı")
        except Exception as ex:
            mutate(lambda d: d["users"][str(uid)].__setitem__("earn", d["users"][str(uid)].get("earn", 0) + amt))
            await send(tr(lang, "wd_err", err=esc(str(ex)[:100])), menu_btn); return
        ulog("m_wd", f"💸 Kazanç çekti: {who(user)} · {fmt_u(amt)} USDT")
        await send(tr(lang, "wd_ok", usdt=fmt_u(amt)), menu_btn)

    elif a == "u_lang":
        await send(*lang_pick("u"))

    elif a.startswith("u_setlang:"):
        _, nl, to = a.split(":")
        if nl not in LANG_NAMES: return
        mutate(lambda d: d["users"].setdefault(str(uid), {}).__setitem__("lang", nl))
        LANGC[uid] = nl
        await show_home(c, uid, getattr(q, "message", None), to != "p", send)

    elif a == "u_free":
        if e.get("free_day") == tm_day():
            await send(tr(lang, "free_today"), menu_btn); return
        if avail_refs(e) < REF_NEED:
            await send(tr(lang, "free_need", need=REF_NEED, avail=max(0, avail_refs(e)), link=esc(ref_link(uid))),
                       KB([[B(tr(lang, "b_share"), url=share_url(lang, uid), style="success")]]
                          + ([[B(tr(lang, "b_trial"), "u_trial", "primary")]] if not e.get("trial_used") else []) + [[B(tr(lang, "b_menu"), "u_menu")]])); return
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

    elif a == "u_trial":
        def take(d):
            x = d["users"][str(uid)]
            if x.get("trial_used"): return False
            x["trial_used"] = time.time(); return True
        if not mutate(take): await send(tr(lang, "trial_used"), menu_btn); return
        res, err = await asyncio.to_thread(make_code_for, uid, f"{short(user.first_name or 'VPN', 20)} 🧪", TRIAL_HOURS / 24, "trial")
        if not res:
            mutate(lambda d: d["users"][str(uid)].pop("trial_used", None))
            await send(tr(lang, "no_slot"), menu_btn)
            await notify_founders(c.application, f"⚠️ <b>Deneme kodu verilemedi</b>\n<blockquote>{esc(who(user))}\n{esc(err)}</blockquote>")
            return
        ulog("trial", f"🧪 Deneme kodu aldı: {who(user)} · {res[0]} · {TRIAL_HOURS} saat")
        await send(tr(lang, "trial_ok", link=esc(await asyncio.to_thread(user_link, res[1]))), menu_btn)

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
        if not mine and not sess: await send(tr(lang, "mine_none"), menu_btn); return
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
        await send(t_, KB(link_rows + ext_rows + stop_rows + del_rows + [[B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_prof":
        inv = db["users"].get(str(e.get("ref_by")), {}) if e.get("ref_by") else {}
        t = tr(lang, "prof", id=uid, name=esc(user.full_name or "—"), un=("@" + esc(user.username)) if user.username else "—",
               joined=tm_fmt(e.get("joined", time.time())), now=tm_now().strftime("%d.%m.%Y %H:%M"),
               total=len(e.get("refs", [])), avail=max(0, avail_refs(e)), need=REF_NEED, free=e.get("free_n", 0),
               active=len(user_codes(db, uid)), buys=e.get("buys", 0), inviter=esc(inv.get("name") or tr(lang, "nobody")),
               link=esc(ref_link(uid)))
        t += tr(lang, "bal_line", bal=f"{e.get('bal', 0) / UM:.2f}", tmt=f"{e.get('bal', 0) * USDT_RATE / UM:.2f}") + (tr(lang, "earn_line", earn=fmt_u(e["earn"])) if e.get("earn") else "")
        await send(t, KB([[B(tr(lang, "b_share"), url=share_url(lang, uid), style="success")],
                          [B(tr(lang, "b_top"), "u_top", "primary")]] + ([[B(tr(lang, "b_wd"), "u_wd")]] if e.get("earn") else []) + [
                          [B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_market":
        STATE.pop(uid, None)
        await send(tr(lang, "market"), KB([[B(tr(lang, "b_c7"), "u_buy:c7")], [B(tr(lang, "b_c30"), "u_buy:c30")],
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
    rows = ([[B(tr(lang, "b_usdt", usdt=us), f"u_usdt:{oid}", "success")]] if has else []) + [[B(tr(lang, "b_cancel"), f"u_cancel:{oid}", "danger")]]
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

def crypto_view():
    tok = crypto_token()
    if tok:
        try: me = crypto_call("getMe"); st = f"🟢 Bağlı: <b>{esc(me.get('name'))}</b>"
        except Exception as e: st = f"🔴 Token çalışmıyor: <code>{esc(str(e)[:100])}</code>"
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
SUP_LIMIT_MB = {"photo": 5, "other": 10}
ERRS = {}                        # hata no -> bilgi (Admine Bildir butonu için)
ERR_SEEN = {}                    # uid -> son hata mesajı zamanı (aynı kişiye arka arkaya hata yağmasın)
from telegram.ext import ApplicationHandlerStop

T["tr"].update({
  "b_sup": "🆘 Support", "b_bug": "🐞 Hata Bildir", "b_tclose": "🔒 Talebi Kapat", "b_report": "📨 Admine Bildir",
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
    def f(d):
        t = d["tickets"][tid]
        if t.get("pending", 0) >= SUP_MAX: return None
        t["pending"] = t.get("pending", 0) + 1; t["n"] = t.get("n", 0) + 1; t["last"] = time.time()
        return True
    if not mutate(f):
        await m.reply_text(tr(lang, "sup_wait")); return
    kind = load_db().get("tickets", {}).get(tid, {}).get("kind")
    hdr = f"{'🐞 <b>Hata Raporu' if kind == 'bug' else '🎫 <b>Destek'} #{tid}</b> · {esc(who(user))}"
    kb = KB([[B("✍️ Yanıtla", f"t_rep:{tid}", "primary"), B("🔒 Kapat", f"t_close:{tid}", "danger")]])
    for fid in ADMINS:
        try: remember_tmsg(await copy_with_header(c.bot, fid, uid, m, hdr, kb), tid)
        except Exception as e: log.warning("destek iletilemedi: %s", e)
    await m.reply_text(tr(lang, "sup_sent"), reply_markup=KB([[B(tr(lang, "b_tclose"), "u_tclose", "danger")]]))

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
MKT_FEE = 100_000                # 0.1 USDT: satıcı ilan ücreti ve alıcı başlatma ücreti (bota kalır)
TOPUP_MIN = 1                    # en az bakiye yükleme (USDT)
WITHDRAW_MIN = 1 * UM            # en az kazanç çekme
MIN_COUNTRIES, MAX_DEAD = 4, 4   # başvuruda en az 4 gerçek ülke; 4'ten fazla çalışmayan (N/A) sunucu olmamalı
BAD_WINDOW = 30 * 60             # kural ihlali bu kadar sürerse ilan kaldırılır
BAN_DEAD_H = 3                   # N/A kuralı ihlalinde yasak (saat): yasakta kod verilmez, iade yok
VIP_FEE, VIP_HOURS = 200_000, 36 # 💎 VIP: 0.2 USDT -> 36 saat en üstte (bizim ilanın altında)
OWN_DESC = "✅ Botun resmi kodu\n🛡 7/24 kontrol altında: IP değişince otomatik yenilenir, çalışmayan sunucular otomatik çıkarılır."
SETTLE_EVERY = 86400             # alıcı durdurmazsa satıcıya günde bir ödeme
START_MINUTES = 60               # başlatmak için bakiye en az 60 dakikaya yetmeli
OWN_LID = "own"                  # bizim ilanımız (her zaman en üstte)
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
    """Alıcı bir ilanı başlatır: 0.1$ ücret, Drive dosyası, kodlar. Dönüş: ((sid, fid), "") ya da (None, sebep)."""
    svc = new_service()
    if not svc: return None, "drive"
    with db_lock():
        db = load_db(); ensure_own(db)
        L = db["market"].get(lid); e = db["users"].setdefault(str(uid), {})
        if not L or L.get("status") != "live": return None, "gone"
        if any(s["buyer"] == uid and s["lid"] == lid and s["status"] == "on" for s in db.get("msess", {}).values()): return None, "already"
        need = MKT_FEE + int(round(L["price"] * START_MINUTES))
        if e.get("bal", 0) < need: return None, f"nobal:{need}"
        codes = listing_codes(db, L)
        if not codes: return None, "nocodes"
        fid, from_free = alloc_file(svc, db)
        if not fid or not make_public(svc, fid): return None, "noslot"
        if not sync_file(svc, fid, L["title"], "🏪 " + ("Пазар" if lang_of(db, uid) == "ru" else "Pazar"), codes, exp=False): return None, "drive"
        if from_free: db["free_files"].remove(fid)
        e["bal"] = e.get("bal", 0) - MKT_FEE
        db["mkt_fees"] = db.get("mkt_fees", 0) + MKT_FEE
        sid = uuid.uuid4().hex[:8]
        now = time.time()
        db.setdefault("msess", {})[sid] = {"buyer": uid, "lid": lid, "fid": fid, "start": now, "last": now, "settle_ts": now,
                                          "acc": 0, "total": 0, "status": "on", "hash": hashlib.md5("\n".join(codes).encode()).hexdigest()}
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
            crypto_call("transfer", user_id=seller, asset="USDT", amount=fmt_u(amount), spend_id=spend_id[:64], comment=comment[:500])
            return "sent"
        except Exception as e:
            RUN["transfer_err"] = str(e)[:150]
    mutate(lambda d: d["users"].setdefault(str(seller), {}).__setitem__("earn", d["users"][str(seller)].get("earn", 0) + amount))
    return "bal"

# ── metinler ──
T["tr"].update({
  "b_mkt": "🏪 Pazar (dakika başı)", "b_sell": "Öz Kodyňyzy Satmak 🪪", "b_myl": "📦 İlanlarım", "b_rules": "📜 Kurallar",
  "b_start": "▶️ Başlat · 0.1$ + {p}/dk", "b_shot": "📷 Ekran Görüntüsü", "b_back_mkt": "◀️ Pazar", "b_stop": "⏹ Durdur",
  "b_top": "➕ Bakiye Yükle", "b_wd": "💸 Kazancı Çek", "b_other": "✏️ Başka tutar",
  "mkt": "🏪 <b>Pazar</b>\n<blockquote>Satıcıların VPN kodları. Dakika başı ödersin, istediğin an durdurursun.\nKodlar bot tarafından her dakika kontrol edilir.\n💰 Bakiyen  <b>{bal} USDT</b></blockquote>\n<i>Bir ilan seç</i> 👇",
  "mkt_empty": "<i>Şu an başka ilan yok.</i>",
  "ml": "🏪 <b>{title}</b>\n<blockquote>{own}👤 Satıcı  {seller}\n📡 Sunucu  <b>{total}</b>  ·  {protos}\n🇹🇲 TM testi  <b>{work}/{tested}</b> çalışıyor  ·  ❌ {dead}\n🌍 Gerçek ülke  <b>{ncc}</b>  {flags}\n🔌 Açık port (VPS)  {tcp}\n🕒 Son kontrol  {chk}\n✅ Son sağlam  {good}</blockquote>\n💲 <b>Fiyat</b>\n<blockquote>{calc}</blockquote>{desc}\n<i>Başlatınca 0.1$ başlatma ücreti alınır, sonra her dakika bakiyenden düşer.</i>",
  "ml_own": "⭐ Resmi ilan\n",
  "m_need": "⚠️ <b>Bakiye yetersiz</b>\n<blockquote>Başlatmak için en az <b>{need} USDT</b> gerekli (0.1$ + 60 dakika).\n💰 Bakiyen  <b>{bal} USDT</b></blockquote>",
  "m_started": "✅ <b>Kod başladı!</b>\n<blockquote>🏪 {title}\n💲 {p}  ·  💰 Bakiye {bal} USDT</blockquote>\n🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>\n<code>{link}</code>\n<i>Durdurmak için: 🎟 Kodlarım → ⏹ Durdur</i>",
  "m_already": "ℹ️ Bu ilan sende zaten açık. 🎟 Kodlarım'dan bakabilirsin.",
  "m_gone": "⚠️ Bu ilan artık yayında değil.",
  "m_stopped": "⏹ <b>Kod durduruldu</b>\n<blockquote>🏪 {title}\n⏱ Kullanım  {dur}\n💸 Toplam  {usdt} USDT</blockquote>{why}",
  "why_nobal": "<i>Bakiyen bittiği için durduruldu.</i>", "why_gone": "<i>İlan pazardan kaldırıldığı için durduruldu.</i>", "why_user": "",
  "m_low": "⚠️ Bakiyen azalıyor: pazardaki kodun yaklaşık <b>{m} dk</b> daha çalışır.",
  "mine_m": "<blockquote>🏪 <b>{title}</b>  ·  ⏱ {dur}  ·  💸 {usdt} USDT\n<code>{link}</code></blockquote>",
  "sell_banned": "⛔ Pazar yasağın var: <b>{left}</b> sonra tekrar ilan verebilirsin.",
  "sell_1": "➕ <b>Kodumu Sat · 1/5</b>\n<blockquote>Abonelik linkini gönder. <b>Limitsiz</b> olmalı (trafik ve cihaz).\nKurallar: en az 4 farklı gerçek ülke (bot ölçer, bayraklara bakılmaz), en fazla 3 çalışmayan sunucu.</blockquote>",
  "sell_badlink": "⚠️ Bu linkten kod alınamadı. Linki kontrol edip tekrar gönder.",
  "sell_dup": "⚠️ Bu link zaten pazarda.",
  "sell_2": "➕ <b>Kodumu Sat · 2/5</b>\n<blockquote>✅ Linkte <b>{n}</b> sunucu bulundu ({protos}).\nİlanın adını yaz (ör. <code>Fast VPN 🇩🇪</code>).</blockquote>",
  "sell_3": "➕ <b>Kodumu Sat · 3/5</b>\n<blockquote>Kodunun <b>ekran görüntüsünü</b> gönder (fotoğraf olarak).</blockquote>",
  "sell_need_photo": "⚠️ Ekran görüntüsünü fotoğraf olarak gönder.",
  "sell_4": "➕ <b>Kodumu Sat · 4/5</b>\n<blockquote>Açıklama yaz (hız, özellik, iletişim...). Atlamak için <code>-</code> gönder.</blockquote>",
  "sell_5": "➕ <b>Kodumu Sat · 5/5</b>\n<blockquote>Dakika başı fiyatını <b>USDT</b> olarak yaz.\nÖrnek: <code>0.0001</code> = günde 0.144 USDT · 30 günde 4.32 USDT</blockquote>",
  "sell_badprice": "⚠️ Geçerli bir fiyat yaz (0.00001 ile 0.01 USDT arası), ör. <code>0.0001</code>.",
  "sell_confirm": "🧾 <b>İlan özeti</b>\n<blockquote>🏷 {title}\n📡 {n} sunucu · {protos}\n📝 {desc}</blockquote>\n💲 <b>Fiyat hesaplayıcı</b>\n<blockquote>{calc}</blockquote>\n<i>Onaylarsan bakiyenden <b>0.1$</b> ilan ücreti alınır (iade edilmez). Bot kodlarını test eder; kurallara uyuyorsa birkaç dakika içinde yayına alınır.</i>",
  "b_sellok": "✅ Limitsiz olduğunu onaylıyorum · 0.1$ öde", "b_sellp": "✏️ Fiyatı değiştir",
  "sell_nobal": "⚠️ İlan ücreti için bakiyen yetersiz (0.1$). Önce bakiye yükle.",
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
  "rules": "📜 <b>Pazar kuralları</b>\n<blockquote><b>Satıcı</b>\n• Her ilan 0.1$ (iade edilmez).\n• Abonelik limitsiz olmalı; ekran görüntüsü zorunlu.\n• En az 4 farklı gerçek ülke (bot ölçer, bayraklara bakılmaz).\n• 3'ten fazla sunucu 30 dk çalışmazsa ilan kaldırılır + 3 saat yasak.\n• Gerçek ülke 30 dk 4'ün altına düşerse ilan kaldırılır + 6 saat yasak.\n• Link 30 dk açılmazsa ilan kaldırılır + 3 saat yasak.\n• Kazanç: alıcı durdurunca, uzun kullanımda her 24 saatte bir gönderilir.</blockquote>\n<blockquote><b>Alıcı</b>\n• Her başlatma 0.1$ (iade edilmez).\n• Dakika başı ücret bakiyenden düşer (kullansan da kullanmasan da).\n• İstediğin an durdurursun; bakiye bitince kod durur.\n• Bakiye en az 1$ yüklenir; yüklenen bakiye geri çekilmez.</blockquote>",
  "bal_line": "\n\n💰 <b>Bakiye</b> {bal} USDT ≈ {tmt} TMT" , "earn_line": "\n💼 <b>Çekilebilir kazanç</b>  {earn} USDT",
  "top": "➕ <b>Bakiye Yükle</b>\n<blockquote>CryptoBot ile USDT. En az 1 USDT.\n💰 Bakiyen  <b>{bal} USDT</b></blockquote>",
  "top_ask": "✏️ Kaç USDT yüklemek istiyorsun? (en az 1)", "top_bad": "⚠️ En az 1 USDT, sayı yaz (ör. 2.5).",
  "top_order": "🧾 <b>Bakiye yükleme · #{oid}</b>\n<blockquote>💵 <b>{usdt} USDT</b></blockquote>\n«💵 USDT ile öde»ye bas.",
  "it_top": "Bakiye yükleme · {usdt} USDT",
  "top_ok": "✅ <b>Bakiyene {usdt} USDT eklendi.</b>\n<blockquote>💰 Bakiye  <b>{bal} USDT</b></blockquote>",
  "wd_min": "ℹ️ Çekmek için en az 1 USDT kazanç gerekli. Şu an: {earn} USDT.",
  "wd_ok": "✅ <b>{usdt} USDT</b> CryptoBot hesabına gönderildi.",
  "wd_err": "⚠️ Gönderilemedi: {err}\n<i>@CryptoBot'u en az bir kez açmış olman gerekir. Sorun sürerse 🆘 Destek'e yaz.</i>",
})
T["ru"].update({
  "b_mkt": "🏪 Биржа (поминутно)", "b_sell": "➕ Продать код", "b_myl": "📦 Мои лоты", "b_rules": "📜 Правила",
  "b_start": "▶️ Запустить · 0.1$ + {p}/мин", "b_shot": "📷 Скриншот", "b_back_mkt": "◀️ Биржа", "b_stop": "⏹ Стоп",
  "b_top": "➕ Пополнить", "b_wd": "💸 Вывести доход", "b_other": "✏️ Другая сумма",
  "mkt": "🏪 <b>Биржа</b>\n<blockquote>VPN-коды продавцов. Оплата поминутно, остановить можно в любой момент.\nБот проверяет коды каждую минуту.\n💰 Баланс  <b>{bal} USDT</b></blockquote>\n<i>Выберите объявление</i> 👇",
  "mkt_empty": "<i>Других объявлений пока нет.</i>",
  "ml": "🏪 <b>{title}</b>\n<blockquote>{own}👤 Продавец  {seller}\n📡 Серверов  <b>{total}</b>  ·  {protos}\n🇹🇲 Тест в ТМ  <b>{work}/{tested}</b> работают  ·  ❌ {dead}\n🌍 Реальных стран  <b>{ncc}</b>  {flags}\n🔌 Открытые порты (VPS)  {tcp}\n🕒 Проверка  {chk}\n✅ Последний раз исправен  {good}</blockquote>\n💲 <b>Цена</b>\n<blockquote>{calc}</blockquote>{desc}\n<i>При запуске списывается 0.1$, затем оплата каждую минуту с баланса.</i>",
  "ml_own": "⭐ Официальное объявление\n",
  "m_need": "⚠️ <b>Недостаточно средств</b>\n<blockquote>Для запуска нужно минимум <b>{need} USDT</b> (0.1$ + 60 минут).\n💰 Баланс  <b>{bal} USDT</b></blockquote>",
  "m_started": "✅ <b>Код запущен!</b>\n<blockquote>🏪 {title}\n💲 {p}  ·  💰 Баланс {bal} USDT</blockquote>\n🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>\n<code>{link}</code>\n<i>Остановить: 🎟 Мои коды → ⏹ Стоп</i>",
  "m_already": "ℹ️ Это объявление у вас уже запущено. Смотрите в 🎟 Мои коды.",
  "m_gone": "⚠️ Это объявление больше не активно.",
  "m_stopped": "⏹ <b>Код остановлен</b>\n<blockquote>🏪 {title}\n⏱ Использование  {dur}\n💸 Итого  {usdt} USDT</blockquote>{why}",
  "why_nobal": "<i>Остановлен: закончился баланс.</i>", "why_gone": "<i>Остановлен: объявление снято с биржи.</i>", "why_user": "",
  "m_low": "⚠️ Баланс заканчивается: код с биржи проработает ещё примерно <b>{m} мин</b>.",
  "mine_m": "<blockquote>🏪 <b>{title}</b>  ·  ⏱ {dur}  ·  💸 {usdt} USDT\n<code>{link}</code></blockquote>",
  "sell_banned": "⛔ У вас бан на бирже: можно снова через <b>{left}</b>.",
  "sell_1": "➕ <b>Продать код · 1/5</b>\n<blockquote>Отправьте ссылку подписки. Она должна быть <b>безлимитной</b> (трафик и устройства).\nПравила: минимум 4 разные реальные страны (бот проверяет сам, флаги не учитываются), не больше 3 неработающих серверов.</blockquote>",
  "sell_badlink": "⚠️ По этой ссылке коды не получены. Проверьте и отправьте снова.",
  "sell_dup": "⚠️ Эта ссылка уже на бирже.",
  "sell_2": "➕ <b>Продать код · 2/5</b>\n<blockquote>✅ Найдено серверов: <b>{n}</b> ({protos}).\nНапишите название объявления (напр. <code>Fast VPN 🇩🇪</code>).</blockquote>",
  "sell_3": "➕ <b>Продать код · 3/5</b>\n<blockquote>Отправьте <b>скриншот</b> вашего кода (как фото).</blockquote>",
  "sell_need_photo": "⚠️ Отправьте скриншот как фото.",
  "sell_4": "➕ <b>Продать код · 4/5</b>\n<blockquote>Напишите описание (скорость, особенности, контакты...). Пропустить — <code>-</code>.</blockquote>",
  "sell_5": "➕ <b>Продать код · 5/5</b>\n<blockquote>Укажите цену за минуту в <b>USDT</b>.\nПример: <code>0.0001</code> = 0.144 USDT в день · 4.32 USDT за 30 дней</blockquote>",
  "sell_badprice": "⚠️ Укажите цену от 0.00001 до 0.01 USDT, напр. <code>0.0001</code>.",
  "sell_confirm": "🧾 <b>Итог объявления</b>\n<blockquote>🏷 {title}\n📡 {n} серверов · {protos}\n📝 {desc}</blockquote>\n💲 <b>Калькулятор цены</b>\n<blockquote>{calc}</blockquote>\n<i>При подтверждении с баланса спишется <b>0.1$</b> (не возвращается). Бот проверит коды; если всё по правилам — объявление появится через несколько минут.</i>",
  "b_sellok": "✅ Подтверждаю безлимит · оплатить 0.1$", "b_sellp": "✏️ Изменить цену",
  "sell_nobal": "⚠️ Недостаточно баланса для оплаты объявления (0.1$). Сначала пополните.",
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
  "rules": "📜 <b>Правила биржи</b>\n<blockquote><b>Продавец</b>\n• Каждое объявление 0.1$ (не возвращается).\n• Подписка должна быть безлимитной; скриншот обязателен.\n• Минимум 4 разные реальные страны (бот измеряет сам, флаги не учитываются).\n• Если больше 3 серверов не работают 30 мин — снятие + бан 3 ч.\n• Если реальных стран меньше 4 в течение 30 мин — снятие + бан 6 ч.\n• Если ссылка не открывается 30 мин — снятие + бан 3 ч.\n• Выплата: после остановки покупателем, при долгом использовании — каждые 24 ч.</blockquote>\n<blockquote><b>Покупатель</b>\n• Каждый запуск 0.1$ (не возвращается).\n• Поминутная оплата списывается с баланса (пользуетесь или нет).\n• Остановить можно в любой момент; при нулевом балансе код останавливается.\n• Пополнение от 1$; пополненный баланс не выводится.</blockquote>",
  "bal_line": "\n\n💰 <b>Баланс</b> {bal} USDT ≈ {tmt} TMT", "earn_line": "\n💼 <b>Доход к выводу</b>  {earn} USDT",
  "top": "➕ <b>Пополнение</b>\n<blockquote>USDT через CryptoBot. Минимум 1 USDT.\n💰 Баланс  <b>{bal} USDT</b></blockquote>",
  "top_ask": "✏️ Сколько USDT пополнить? (минимум 1)", "top_bad": "⚠️ Минимум 1 USDT, напишите число (напр. 2.5).",
  "top_order": "🧾 <b>Пополнение · #{oid}</b>\n<blockquote>💵 <b>{usdt} USDT</b></blockquote>\nНажмите «💵 Оплатить USDT».",
  "it_top": "Пополнение · {usdt} USDT",
  "top_ok": "✅ <b>На баланс зачислено {usdt} USDT.</b>\n<blockquote>💰 Баланс  <b>{bal} USDT</b></blockquote>",
  "wd_min": "ℹ️ Для вывода нужно минимум 1 USDT дохода. Сейчас: {earn} USDT.",
  "wd_ok": "✅ <b>{usdt} USDT</b> отправлено на ваш счёт в CryptoBot.",
  "wd_err": "⚠️ Не удалось отправить: {err}\n<i>Нужно хотя бы раз открыть @CryptoBot. Если не получается — напишите в 🆘 Поддержку.</i>",
})
for _k in ("st_pending", "st_live", "st_removed", "st_rejected"): T["ru"][_k] = T["tr"][_k]

T["tr"].update({
  "b_pazar": "🏪 Pazar", "b_start": "▶️ Başlat", "b_live": "📊 Canlı", "b_vip": "💎 VIP · 36 saat · 0.2$", "b_yes_stop": "✅ Evet, durdur", "b_no": "✖️ Vazgeç",
  "mkt_head": "🏪 <b>Pazar</b> 👇",
  "mkt_foot": "🏪 <b>Pazar</b>\n<blockquote>💰 Bakiyen  <b>{bal} USDT</b>\nBaşlatınca 0.1$, sonra dakika başı ödersin; istediğin an durdurursun.</blockquote>",
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
  "rules": "📜 <b>Pazar kuralları</b>\n<blockquote><b>Satıcı</b>\n• Her ilan 0.1$ (iade edilmez).\n• Abonelik limitsiz olmalı; ekran görüntüsü zorunlu.\n• Başvuruda en az 4 farklı gerçek ülke (bot ölçer, bayraklara bakılmaz).\n• 4'ten fazla sunucu 30 dk N/A kalırsa ilan 3 saat yasaklanır: yasakta kodların verilmez, iade yok. Yasak bitince ilan yeniden incelenir.\n• 💎 VIP: 0.2$ ile 36 saat en üstte.\n• Kazanç: alıcı durdurunca, uzun kullanımda her 24 saatte bir gönderilir.</blockquote>\n<blockquote><b>Alıcı</b>\n• Her başlatma 0.1$ (iade edilmez).\n• Dakika başı ücret bakiyenden düşer (kullansan da kullanmasan da).\n• İstediğin an durdurursun; bakiye bitince kod durur.\n• Bakiye en az 1$ yüklenir; yüklenen bakiye geri çekilmez.</blockquote>",
})
T["ru"].update({
  "b_pazar": "🏪 Биржа", "b_start": "▶️ Запустить", "b_live": "📊 Онлайн", "b_vip": "💎 VIP · 36 ч · 0.2$", "b_yes_stop": "✅ Да, остановить", "b_no": "✖️ Отмена",
  "mkt_head": "🏪 <b>Биржа</b> 👇",
  "mkt_foot": "🏪 <b>Биржа</b>\n<blockquote>💰 Баланс  <b>{bal} USDT</b>\nПри запуске 0.1$, затем поминутная оплата; остановить можно в любой момент.</blockquote>",
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
  "rules": "📜 <b>Правила биржи</b>\n<blockquote><b>Продавец</b>\n• Каждое объявление 0.1$ (не возвращается).\n• Подписка должна быть безлимитной; скриншот обязателен.\n• При подаче минимум 4 разные реальные страны (бот измеряет сам, флаги не учитываются).\n• Если больше 4 серверов N/A 30 мин — бан объявления на 3 ч: во время бана коды не выдаются, возврата нет. После бана — повторная проверка.\n• 💎 VIP: 0.2$ — 36 часов на самом верху.\n• Выплата: после остановки покупателем, при долгом использовании — каждые 24 ч.</blockquote>\n<blockquote><b>Покупатель</b>\n• Каждый запуск 0.1$ (не возвращается).\n• Поминутная оплата списывается с баланса (пользуетесь или нет).\n• Остановить можно в любой момент; при нулевом балансе код останавливается.\n• Пополнение от 1$; пополненный баланс не выводится.</blockquote>",
})

T["tr"].update({
  "card": "🏪 <b>{title}</b>{badge}\n{own}\n📡 <b>Sunucular</b>\n<blockquote>🖥 {total} sunucu · {protos}\n{tmline}{ccline}</blockquote>\n\n💰 <b>Fiyat</b>\n<blockquote>📅 30 gün  —  <b>{m_tmt} TMT</b>  <i>({m_usdt} $)</i>\n📆 1 gün  —  <b>{d_tmt} TMT</b>  <i>({d_usdt} $)</i>\n⏱ 1 saat  —  <b>{h_tmt} TMT</b></blockquote>\n<i>▶️ Başlatma 0.1$, sonra kullandığın dakika kadar ödersin · istediğin an durdurursun</i>{desc}",
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
  "card": "🏪 <b>{title}</b>{badge}\n{own}\n📡 <b>Серверы</b>\n<blockquote>🖥 {total} серверов · {protos}\n{tmline}{ccline}</blockquote>\n\n💰 <b>Цена</b>\n<blockquote>📅 30 дней  —  <b>{m_tmt} TMT</b>  <i>({m_usdt} $)</i>\n📆 1 день  —  <b>{d_tmt} TMT</b>  <i>({d_usdt} $)</i>\n⏱ 1 час  —  <b>{h_tmt} TMT</b></blockquote>\n<i>▶️ Запуск 0.1$, далее платите только за использованные минуты · остановить можно в любой момент</i>{desc}",
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
  "payline": "💡 <b>Pul doly alynmaýar</b> — töleg diňe ulanan minudyňyza / sagadyňyza görä alynýar.\n▶️ Başlanda bir gezek 0.1$ · islän wagtyňyz togtadyp bilersiňiz.",
  "mkt_bal": "\n\n💰 Bakiyen  <b>{bal} USDT</b>",
  "mkt_none": "\n<i>Şu an başka satıcı yok.</i>",
  "b_sellers": "👥 Satıcılar ({n}) ▶️",
  "chk_line_ok": "🎯", "chk_line_bad": "⚠️ gerçek: {f} {n}", "chk_line_real": "→ {f} {n}",
  "chk_head": "🔍 <b>{title}</b> · sunucu durumu\n<blockquote>{lines}</blockquote>\n✅ {work} çalışıyor · ❌ {dead} çalışmıyor · ⏳ {wait} bekliyor\n🎯 ülke doğru · ⚠️ ülke yanlış (gerçeği yanında)\n🕒 Son TM testi: {ago}",
  "chk_run": "\n\n⏳ <b>Kontrol ediliyor...</b>\n<i>Türkmenistan'dan yeni test yapılıyor (1–5 dk). Bu mesaj kendiliğinden güncellenecek.</i>",
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
  "payline": "💡 <b>Деньги не списываются сразу</b> — оплата только за использованные минуты / часы.\n▶️ При запуске один раз 0.1$ · остановить можно в любой момент.",
  "mkt_bal": "\n\n💰 Баланс  <b>{bal} USDT</b>",
  "mkt_none": "\n<i>Других продавцов пока нет.</i>",
  "b_sellers": "👥 Продавцы ({n}) ▶️",
  "chk_line_ok": "🎯", "chk_line_bad": "⚠️ на деле: {f} {n}", "chk_line_real": "→ {f} {n}",
  "chk_head": "🔍 <b>{title}</b> · состояние серверов\n<blockquote>{lines}</blockquote>\n✅ {work} работают · ❌ {dead} не работают · ⏳ {wait} ждут\n🎯 страна верна · ⚠️ страна неверна (настоящая рядом)\n🕒 Последний тест в TM: {ago}",
  "chk_run": "\n\n⏳ <b>Проверяется...</b>\n<i>Идёт новый тест из Туркменистана (1–5 мин). Это сообщение обновится само.</i>",
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
  "chk_run": "\n⏳ <b>Kontrol ediliyor...</b>\n<i>Türkmenistan'dan test yapılıyor (~1 dk). Sonuç bu kutuda görünecek.</i>",
  "chk_head2": "\n🔍 <b>Sunucular</b>\n<blockquote>{lines}</blockquote>\n✅ {work} çalışıyor · ❌ {dead} çalışmıyor · ⏳ {wait} bekliyor\n🎯 ülke doğru · ⚠️ ülke yanlış\n🕒 Son TM testi: {ago}",
  "chk_upd": "\n✅ <i>Güncellendi · {t}</i>",
  "chk_timeout": "\n⚠️ <i>Telefon testi şu an cevap vermiyor; yukarıda son bilinen durum.</i>",
  "payline": "💡 <b>Pul doly alynmaýar</b> — töleg diňe ulanan minudyňyza / sagadyňyza görä alynýar.\n▶️ Kody açanyňyzda bir gezek 0.1$. Islän wagtyňyz kody yzyna gowşuryp bilersiňiz — galan puluňyz balansyňyzda galýar (diňe ulanylan wagtyň puly alynýar).",
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
  "chk_run": "\n⏳ <b>Проверяется...</b>\n<i>Идёт тест из Туркменистана (~1 мин). Результат появится здесь.</i>",
  "chk_head2": "\n🔍 <b>Серверы</b>\n<blockquote>{lines}</blockquote>\n✅ {work} работают · ❌ {dead} не работают · ⏳ {wait} ждут\n🎯 страна верна · ⚠️ страна неверна\n🕒 Последний тест в TM: {ago}",
  "chk_upd": "\n✅ <i>Обновлено · {t}</i>",
  "chk_timeout": "\n⚠️ <i>Телефонный тест сейчас не отвечает; выше — последнее известное состояние.</i>",
  "payline": "💡 <b>Деньги не списываются сразу</b> — оплата только за использованные минуты / часы.\n▶️ При запуске один раз 0.1$. Код можно вернуть в любой момент — остаток останется на балансе (списывается только за использованное время).",
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
 "b_bug": "🐞 Ýalňyşlyk",
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
 "ml": "🏪 <b>{title}</b>\n<blockquote>{own}👤 Satyjy  {seller}\n📡 Serwer  <b>{total}</b>  ·  {protos}\n🇹🇲 TM barlagy  <b>{work}/{tested}</b> işleýär  ·  ❌ {dead}\n🌍 Hakyky ýurt  <b>{ncc}</b>  {flags}\n🔌 Açyk port (VPS)  {tcp}\n🕒 Soňky barlag  {chk}\n✅ Soňky işlän wagty  {good}</blockquote>\n💲 <b>Baha</b>\n<blockquote>{calc}</blockquote>{desc}\n<i>Başlanyňda 0.1$ başlangyç töleg alynýar, soň her minut balansyňdan tutulýar.</i>",
 "ml_own": "⭐ Resmi bildiriş\n",
 "m_need": "⚠️ <b>Balans ýetenok</b>\n<blockquote>Başlamak üçin iň az <b>{need} USDT</b> gerek (0.1$ + 60 minut).\n💰 Balansyň  <b>{bal} USDT</b></blockquote>",
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
 "sell_badlink": "⚠️ Bu linkden kod alyp bolmady. Linki barla-da, täzeden iber.",
 "sell_dup": "⚠️ Bu link eýýäm bazarda bar.",
 "sell_2": "➕ <b>Kodumy sat · 2/5</b>\n<blockquote>✅ Linkde <b>{n}</b> serwer tapyldy ({protos}).\nBildirişiň adyny ýaz (mysal: <code>Fast VPN 🇩🇪</code>).</blockquote>",
 "sell_3": "➕ <b>Kodumy sat · 3/5</b>\n<blockquote>Kodyňyň <b>skrinşotyny</b> iber (surat görnüşinde).</blockquote>",
 "sell_need_photo": "⚠️ Skrinşoty surat görnüşinde iber.",
 "sell_4": "➕ <b>Kodumy sat · 4/5</b>\n<blockquote>Düşündiriş ýaz (tizligi, aýratynlyklary, habarlaşmak üçin...). Geçmek üçin <code>-</code> iber.</blockquote>",
 "sell_badprice": "⚠️ 1 bilen 10000 arasynda san ýaz (aýlyk TMT), mysal: <code>100</code>.",
 "sell_confirm": "🧾 <b>Bildiriş barada gysgaça</b>\n<blockquote>🏷 {title}\n📡 {n} serwer · {protos}\n📝 {desc}</blockquote>\n💲 <b>Baha hasaplaýjy</b>\n<blockquote>{calc}</blockquote>\n<i>Tassyklasaň, balansyňdan <b>0.1$</b> bildiriş tölegi alynýar (yzyna gaýtarylmaýar). Bot kodlaryňy barlaýar; düzgünlere laýyk bolsa, birnäçe minutdan bazara çykýar.</i>",
 "b_sellok": "✅ Limitsiz, tassyklaýaryn · 0.1$ töle",
 "b_sellp": "✏️ Bahany üýtget",
 "sell_nobal": "⚠️ Bildiriş tölegi üçin balansyň ýetenok (0.1$). Ilki balansy doldur.",
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
 "rules": "📜 <b>Bazaryň düzgünleri</b>\n<blockquote><b>Satyjy</b>\n• Her bildiriş 0.1$ (yzyna gaýtarylmaýar).\n• Podpiska limitsiz bolmaly; skrinşot hökman.\n• Bildiriş berlende azyndan 4 dürli hakyky ýurt bolmaly (bot özi ölçeýär, baýdaklara seredilmeýär).\n• 4-den köp serwer 30 minut N/A bolsa, bildiriş 3 sagat bloklanýar: blok wagtynda kodlaryň berilmeýär, pul gaýtarylmaýar. Blok gutaranda bildiriş täzeden barlanýar.\n• 💎 VIP: 0.2$ töläp, 36 sagat iň ýokarda durýar.\n• Gazanç: alyjy kody yzyna gowşuranda, uzak ulanylsa her 24 sagatda bir gezek iberilýär.</blockquote>\n<blockquote><b>Alyjy</b>\n• Her gezek başlamak 0.1$ (yzyna gaýtarylmaýar).\n• Minutlyk töleg balansyňdan aýrylýar (ulansaň-da, ulanmasaň-da).\n• Islän wagtyň yzyna gowşurup bilersiň; balans gutarsa, kod özi yzyna gowşurylýar.\n• Balans azyndan 1$ doldurylýar; doldurylan balansy yzyna çekip bolmaýar.</blockquote>",
 "bal_line": "\n\n💰 <b>Balans</b> {bal} USDT ≈ {tmt} TMT",
 "earn_line": "\n💼 <b>Çekip boljak gazanç</b>  {earn} USDT",
 "top": "➕ <b>Balansy doldur</b>\n<blockquote>CryptoBot arkaly USDT. Azyndan 1 USDT.\n💰 Balansyň  <b>{bal} USDT</b></blockquote>",
 "top_ask": "✏️ Näçe USDT doldurmak isleýärsiň? (azyndan 1)",
 "top_bad": "⚠️ Azyndan 1 USDT, san ýaz (mysal: 2.5).",
 "top_order": "🧾 <b>Balansy doldurmak · #{oid}</b>\n<blockquote>💵 <b>{usdt} USDT</b></blockquote>\n«💵 USDT bilen töle» düwmesine bas.",
 "it_top": "Balansy doldurmak · {usdt} USDT",
 "top_ok": "✅ <b>Balansyňa {usdt} USDT goşuldy.</b>\n<blockquote>💰 Balans  <b>{bal} USDT</b></blockquote>",
 "wd_min": "ℹ️ Çekmek üçin azyndan 1 USDT gazanç gerek. Häzir: {earn} USDT.",
 "wd_ok": "✅ <b>{usdt} USDT</b> CryptoBot hasabyňa iberildi.",
 "wd_err": "⚠️ Iberip bolmady: {err}\n<i>@CryptoBot-y azyndan bir gezek açan bolmaly. Düzelmese 🆘 Goldaw-a ýaz.</i>",
 "b_pazar": "🏪 Bazar",
 "b_live": "📊 Göni",
 "b_vip": "💎 VIP · 36 sag. · 0.2$",
 "b_yes_stop": "✅ Hawa",
 "b_no": "✖️ Ýok",
 "mkt_head": "🏪 <b>Bazar</b> 👇",
 "mkt_foot": "🏪 <b>Bazar</b>\n<blockquote>💰 Balansyň  <b>{bal} USDT</b>\nBaşlanyňda 0.1$, soň her minut üçin tölärsiň; islän wagtyň yzyna gowşuryp bilersiň.</blockquote>",
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
 "payline": "💡 <b>Pul doly alynmaýar</b> — töleg diňe ulanan minudyňyza / sagadyňyza görä alynýar.\n▶️ Kody açanyňyzda bir gezek 0.1$. Islän wagtyňyz kody yzyna gowşuryp bilersiňiz — galan puluňyz balansyňyzda galýar (diňe ulanylan wagtyň puly alynýar).",
 "mkt_bal": "\n\n💰 Balansyň  <b>{bal} USDT</b>",
 "mkt_none": "\n<i>Häzir başga satyjy ýok.</i>",
 "b_sellers": "👥 Satyjylar ({n}) ▶️",
 "chk_line_ok": "🎯",
 "chk_line_bad": "⚠️ hakykatda: {f} {n}",
 "chk_line_real": "→ {f} {n}",
 "chk_run": "\n⏳ <b>Barlanýar...</b>\n<i>Türkmenistandan test edilýär (~1 min). Netije şu ýerde görüner.</i>",
 "chk_upd": "\n✅ <i>Täzelendi · {t}</i>",
 "b_recheck": "🔄 Täzele",
 "head_own": "🏆 <b>BOTUŇ RESMI KODY</b> 🏆",
 "card2": "{head}\n\n🏪 <b>{title}</b>\n\n💰 <b>Bahasy</b>\n<blockquote>{prices}</blockquote>\n\n<i>🔍 Serwerleri we ýurtlary görmek üçin «Barla» bas.</i>",
 "chk_head2": "\n🔍 <b>Serwerler</b>\n<blockquote>{lines}</blockquote>\n✅ {work} işleýär · ❌ {dead} işlemeýär · ⏳ {wait} garaşýar\n🎯 ýurt dogry · ⚠️ ýurt nädogry\n🕒 Soňky TM testi: {ago}",
 "b_mcheck": "🔍 Barla"
}

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

def photo_kb(lid):
    return KB([[B("✅ Foto uygun", f"mk_pok:{lid}", "success")], [B("❌ Reddet", f"mk_prj:{lid}"), B("🔞 Uygunsuz", f"mk_pno:{lid}", "danger")]])
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

def chk_kb(lang, lid):
    return KB([[B(tr(lang, "b_buy_m"), f"u_ms:{lid}", "success"), B(tr(lang, "b_recheck"), f"u_mck:{lid}:r", "primary")], [B(tr(lang, "b_back"), f"u_ml:{lid}")]])

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
    h = hashlib.sha256(_OWN_IMG_B64.encode()).hexdigest()[:12]
    c_ = load_db().get("own_img_fid") or {}
    return (c_["id"], None) if c_.get("h") == h else (base64.b64decode(_OWN_IMG_B64), h)

def remember_own(m, h):
    if not h: return
    try:
        fid = m.photo[-1].file_id
        mutate(lambda d: d.__setitem__("own_img_fid", {"h": h, "id": fid}))
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

async def banner_media(lang):
    b = _BANNERS.get(lang) or _BANNERS["tr"]
    h = hashlib.sha256(b.encode()).hexdigest()[:12]
    c_ = (load_db().get("banner_fid") or {}).get(lang) or {}
    return (c_["id"], None) if c_.get("h") == h and c_.get("bot") == BOT_ID else (base64.b64decode(b), h)

def remember_banner(m, lang, h):
    try:
        p = m.photo[-1]
        def f(d):
            if h: d.setdefault("banner_fid", {})[lang] = {"h": h, "id": p.file_id, "bot": BOT_ID}
            us = d.setdefault("banner_u", [])
            if p.file_unique_id not in us: us.append(p.file_unique_id); del us[:-30]
        mutate(f)
    except Exception: pass

def is_banner(msg):
    ph = getattr(msg, "photo", None)
    return bool(ph) and getattr(ph[-1], "file_unique_id", None) in (load_db().get("banner_u") or [])

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
    async def plain(t, kb):
        if send: await send(t, kb)
        else: await c.bot.send_message(uid, html_cut(t), parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    db = load_db(); lang = lang_of(db, uid)
    t, kb = pub_menu(db, uid) if pub or not is_admin(uid) else home(uid)
    if tg_len(t) > 1024:   # foto altına sığmıyor: banner'sız
        if is_banner(msg):
            try: await msg.delete()
            except Exception: pass
            send = None
        return await plain(t, kb)
    media, h = await banner_media(lang)
    if msg is not None and getattr(msg, "photo", None):
        try:
            m = await c.bot.edit_message_media(chat_id=uid, message_id=msg.message_id, media=InputMediaPhoto(media, caption=t, parse_mode="HTML"), reply_markup=kb)
            remember_banner(m, lang, h); return
        except BadRequest as ex:
            if "not modified" in str(ex).lower(): return
            log.info("menu edit: %s", ex)
        except Exception as ex: log.info("menu edit: %s", ex)
    if msg is not None:
        try: await msg.delete()
        except Exception: pass
    try:
        m = await c.bot.send_photo(uid, media, caption=t, parse_mode="HTML", reply_markup=kb); remember_banner(m, lang, h)
    except Exception as ex:
        log.warning("menu banner: %s", ex)
        await c.bot.send_message(uid, t, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)

async def show_market(c, q, uid, lang, i=0):
    """Pazar tek mesajda: fotoğraflı mesajsa yerinde değişir, değilse eski mesaj silinip yenisi gelir."""
    photo, cap, kb = market_page(load_db(), uid, lang, i)
    msg = getattr(q, "message", None) if q else None
    media, h = await photo_media(photo)
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
            except BadRequest as ex: log.warning("market foto: %s", ex)   # ör. eski botun fotoğrafı: kart fotoğrafsız gelsin
        await c.bot.send_message(uid, cap, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    except Exception as ex: log.warning("market: %s", ex)

def live_view(sid, lang):
    db = load_db(); s = db.get("msess", {}).get(sid)
    if not s: return "—", None
    L = db["market"].get(s["lid"], {}); ru = lang == "ru"
    kb_off = KB([[B(tr(lang, "b_mine"), "u_mine"), B(tr(lang, "b_menu"), "u_menu")]])
    if s.get("status") != "on": return tr(lang, "live_off", title=esc(L.get("title", "?"))), kb_off
    now = time.time(); price = float(L.get("price", 0))
    part = (now - s["last"]) / 60 * price          # son tam dakikadan bu yana (henüz kesilmemiş)
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
            elif L["status"] == "live":
                if fresh and st["tested"]:
                    if st["dead"] > MAX_DEAD: L.setdefault("dead_since", now)
                    else: L.pop("dead_since", None)
                if L.get("dead_since") and now - L["dead_since"] >= BAD_WINDOW:
                    L["status"] = "suspended"; L["until"] = now + BAN_DEAD_H * 3600; L.pop("dead_since", None)
                    e = db["users"].setdefault(str(L["owner"]), {}); e["mban"] = max(e.get("mban", 0), L["until"])
                    events.append(("removed", lid, "r_dead", BAN_DEAD_H))
                elif L.get("link_ok") and not L.get("dead_since"): L["last_good"] = now
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

def market_refresh_files():
    """İlanın kodları değiştiyse açık oturumların Drive dosyalarını günceller."""
    db = load_db(); jobs = []
    for sid, s in db.get("msess", {}).items():
        if s.get("status") != "on": continue
        L = db.get("market", {}).get(s["lid"])
        if not L: continue
        codes = listing_codes(db, L)
        h = hashlib.md5(("\n".join(codes) + f"#fmt{FILE_FMT}").encode()).hexdigest()
        if codes and h != s.get("hash"): jobs.append((sid, s["fid"], L["title"], codes, h))
    if not jobs: return
    svc = new_service()
    for sid, fid, title, codes, h in jobs:
        if sync_file(svc, fid, title, "🏪", codes, exp=False):
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
                    await edit_box(app.bot, uid, mid, is_photo, check_text(db, lid, lang, ch if mode == "refresh" else None, mode, el), chk_kb(lang, lid))
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
        link = next((w for w in txt.split() if w.startswith("http")), None)
        if not link: await say(tr(lang, "sell_badlink")); return
        try: codes = await asyncio.to_thread(fetch_codes, link)
        except Exception: codes = []
        if not codes: await say(tr(lang, "sell_badlink")); return
        if any(L.get("link") == link and L.get("status") in ("pending", "live") for L in load_db().get("market", {}).values()):
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
        st.update({"step": "desc", "photo": m.photo[-1].file_id})
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
        await say(tr(lang, "sell_confirm", title=esc(st["title"]), n=len(st["codes"]), protos=protos_txt(st["protos"]), desc=esc(st.get("desc") or "—"), calc=calc_text(p, lang == "ru"))
                  + tr(lang, "sell_bal", bal=fmt_u(load_db()["users"].get(str(uid), {}).get("bal", 0))),
                  KB([[B(tr(lang, "b_sellok"), "u_sellok", "success")], [B(tr(lang, "b_sellp"), "u_sellp")], [B(tr(lang, "b_cancel"), "u_mkt", "danger")]]))

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
         f"💰 Ücret geliri (0.1$'lar)  <b>{fmt_u(db.get('mkt_fees', 0))} USDT</b>\n"
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, doc_handler))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)

# Bizim ilanın varsayılan fotoğrafı (VIP 🇹🇲 Servers ekran görüntüsü). Admin -> 🏪 Pazar'dan başka foto yüklenirse o kullanılır.
_OWN_IMG_B64 = "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAYEBQYFBAYGBQYHBwYIChAKCgkJChQODwwQFxQYGBcUFhYaHSUfGhsjHBYWICwgIyYnKSopGR8tMC0oMCUoKSj/2wBDAQcHBwoIChMKChMoGhYaKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCgoKCj/wAARCAT+AoADASIAAhEBAxEB/8QAHQABAAICAwEBAAAAAAAAAAAAAAECBQYDBAcICf/EAF4QAAEDAwIDBAUHBQoLBAoABwEAAgMEBREGEgchMRNBUWEUIlJxkQgVMjNigaEjNEJysRYXJDdzgpKys9E1NjhTVFV0dZOUwUOitNIYJVaDhMLD4fDxJ0RXY2Sj0//EABsBAQEBAQEBAQEAAAAAAAAAAAABAgMEBQYH/8QAPREBAAICAAUCAwUGBAUEAwAAAAECAxEEEiExQQVREzJhBhQicaFSgZGx4fAVFsHRIzNCQ1M0NWLxY6Ky/9oADAMBAAIRAxEAPwDwNERfqHEU9ygKUBFC5qSmnrKmKnpIZJ6iVwZHFE0uc8nuAHMlBxIszdNLX+00hqrpZLlR0wIaZZ6Z7GAnoCSMLCqRMT2EomFConKhEQSoREE5TKhEFlChTlUEREBERAREQEREBERAREQEREBERAU5UIqLIqqcoJRQpUBERAREVBEREEREBERARERRERAREQQpUKUBERAREColERAREQFIUIglERAREQERMjOMjKAiIEAoiIGUUIg40UqFzBShXNR009ZVRU1HDJPUSuDI4omlznuPQADmSmx6/wAEuDbta0zrxf5Z6WyesyAQkNkqHA4JBIOGg8s45n3L0PhzwSuGj+KcN3NbTVVkpY5HQPdkTFzmloa5uMZGTzB5+C7vyZqDWNnt1xtmpLdUUdojxJRiqAa9r3E72tHXb38+h6dVsnGPitRcPYIKaKnFdealpfHTl+1rGdN7z1xnkAOZwemF8jLmy3yWx0ne3SIjW20cRbBJqjQ95ssD42T1lO5kTpM7Q/kWk+WQF4hpn5NrZLBUO1JdJIbzKD2DaQh0UB7t2Rl/njHl4rHaf+UrdWXJn7oLPRSUDnYeaMuZJGPEBxIdjw5Z8V9LW+4QXS0wXC1ysqKepiE0DwcNeCMj3LnPx+Gjl7bOkvz+1Xp+4aWv9XZ7vEI6umdh205a9p5tc094I5hYhbvxLs2tX3mvvusbRXQPnm2vqHR5hb3NY1wyNoAAH960hfZx25qxO2JERFtBERAREQEREBTlQiCUUJlUSiIgIiICIiAiIgIiICIiAiIgIiICnKhFRKlVRBZFGUUBSoTvQE70TKolFClEEUKUBERARQpRUKVClAREQECIEEoiICIioKQoClAREQEREBe46Fo6aT5M2taiSnhdOKl5EhYC4YEWOfXlkrw5e86C/wAl7W3+0SfsiXm4r5Y/OP5tQ8HPUqFJ6lQvSyIiIChSVCDjUohWAW68GLjR2nifp+tudRHTUkczg+aQ4azLHNBJ7hkjmtK70WL15qzX3H6MW250FzidJba2lq424BdTytkA95BXyL8qShqqbijJVTtd6PV0kTqdx6ENG1wHuPP+cPFenfJR0pDb9M1Wo/SWyVFzcYRFGfViZG4jDh7ROT5DHivWtZaRsusbX6Bf6JlTC07o3ZLXxO8WOHMH9vevi0vXhs0+Y7OneH58dOZ6L7l4C0NXb+E2noLg17JjE6UMeMFrHvc5o/okH71idP8AAbRVmubK009XXvjdvZHWzb42nu9UAB335XqckbXxOjOQ1wLTg45LpxfFVzRFalY08m+UNqSyfvYXy3NutC+vm7OOOmZM10hcJWkjaDkYAJ+5fGxW0cTtMRaP1xc7LT1LamGB4fHIPpbXjcGv+0AcH4961dfQ4XFGOn4Z3vqzM7ERF6WRERAREQEREBERAREQEREE5RQiCUTKKgiIgIiICIiAieKICIiAiIggop71CApyihUTlSqogsijKnKgIoRBKBEQEKKFUFKhEEqVClARERRSFCkICIiAiIgKVClAREVBejcMtV6M0/a6uDVekxeauSbfHUbWP2s2gbMOIxzBPLrnyXnKLF6RkjllXvH75XCr/wDpyP8AgQf+Zej6b1Xo6q4Q6gu9DpcU+n6aV7aq3dnGO3IDMnAO09W9fBfIC950F/ku62/2iT9kS8PEcNStYmJnvHlqJDxJ4VZ/i5H/AAIP/MsBrnW/D676YrKKwaIFvucob2NVsjZ2RBBJy05PLIx5ryY9SoXprwtKzvc/xlnYiIvQghREHEmURcxKKEQbjw64hXzQNdNNZnxSQTjE1LUAuiee52AQQ4eI9xW48LuJ9yl4uU111Xe5WUNYJIZw+Qtp4wWnYNvRrQ4Dn58z1K8eRcr4aX3uOsrt9n8WuJNhpeHt6+ZNR0Ml0lgMNM2kqWvk3u5ZG05GBk57sL520xxl1fp2wVNppaxlTFICIZ6sGWWmz12OJ5+QdkBecIueLhKUryz1WbOSomlqJ5JqiR8s0ji98j3FznOJySSepK40RelkREQERFQREQEREBERAREQEREBFAUoCZUIgtlFVEFkUZRUShUIgIiICIiApUIgIiICIiAiIgIiKhlSoRBKKFOUBERQEREEhSoClUEREQUhQpCAiIiiIiAFKhSgIiICIiAvUtK62tFt4Ian0vVOnF2rpnOga2Iljg4RjJd0GNp6ry1Fi9IvERP5rtJ6qERdEEREBERBxIERcwREQEREEZUqEQSijKlUEREDKIoKglFCIJRQhVEqMoiCVA6oiB0REQEREBERAREQEREDKlQiCUUKcqgiIgIiICIiAiIgIiICIiAiIgIiKgpyoRBKKFOUEooVlAREQECIFRKIiIIiIJCKFKKIiICIiAiIgIiICIiAiIqOJERcwREQEREEIoTvQEREE5TOVChBYooypzyVBERAREUBERAREQERFQREQEREBERAREQERFuuO1u0AiItfDiPmtH8/wCQKVCJrHHmRKKEym8ftIlERN09pURMplNU9wRT9yclOSJ7SIRMIpNZjuCIiygiIgIiICIiArZVVKolSqqcoJRQpUEoiICIioBSoClEEREBERARERRERAREQEREHEiIsAiIgIiIKlQrOVUBERAREQEREBTlQiCyKqnKolFClAREUBERAREQERFQREXWuKZjmt0gERFeelflj+P+3/2CIixa9rfNIIiLAIiICIiAmURBKKEyqJRMogKcqEVi0x2VPL3IQoRXcT3BFPI9UISa+xpCIiygiIgIiIJREQFIUIqL5RQiCUUZUqAFKhSEBERUEREQREQEREBERFEREHEiIsAiIgIiIIcqqzuiqgIiICIiAiIgIiICIiApyoRBKlVUoJRRlSqCIoVrSbTqolERdd1xdus/p/UERFytabTuQREUBERARdinoqmo+qhe4eOOSyUGn53c5pGMHgOZXSuK9u0G2FRbRFp+mb9ZJI8/BdqO00MfSAO/WOV2jhLz3TbTVC3ttJTN+jTxD+auQQxDpFH/AEQt/c59zmaApW/GKI9Y2H+aFR1JTO+lBGf5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KrFp+Ke1W1sYcLlJNGagZ+jFK4tZy8tuf5ycxtr1HR1NbKY6OnmnkAyWxsLiB9ypUQS08zoqiJ8UrfpMe0tI+4rZIqy3djc7ayae30stX2kFRGC8FrctDX45kd/LvK5HW6erraGK6zx1NBBSSTR1NO7LpomZO3ceec8ufRNm2pos+KSju1smqKGl9CqIJoo3MErnse2Q7QefMEH4qbs2zUtRcLd6LLG6nD446sSFznyN9pvTaTnp0V2MLVU01JI2OpjdG9zGvAPe1wyD94XCt41JbYoaVt2rI3TsdS08MMTHYAcYx67yOYHI4HeV0rRbaCottI6KiNxkeHeldlUbZ4TnkGR558sHPPKnMbaormOQRNlLHCNxLQ/HIkdQD94UOb+Uc1gceeACOZ58uXistqMinmpraw5bQxCN+O+U+tIficfzVR1aaz3KqibLTW+rlicMteyJxBHkVw1NDV0szIqmlnilfzax8ZDnd3Id6zOjJpRcpmCWTYKOow3ecD8me5RpeaVoutZ2j3VVLQPfC9ziSxxc1uRnvAJU2MRWW+sodvplJPTh/wBHtYy3PxXK+z3KOIyvt9Y2MDJcYXYx45wrRXGrFuraQ7p6eba5/abndmQeTwe492fNbbeWOp9WCsdfKekijML3R9s8yABjcjYBzz4eaTMwNCRdq6TRVNzq56ePs4ZJXPYzptaTkBdVaBERFEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREF4ZHwyslieWSMcHNc04II6FZip1NXTwzsDKSGSobtmmhgDJJAeoLh49+OqwiKaRlbdfKmipPReypammD+0ZHUwiQMd3lvgpp9QV8N5fdd8clY4EbpIw4AEY5Du5cgsSiagZeov0s8EkTqG1ND2lpcyja1wz3g9x811K241FY+ldOWZpomwx7W49VvTPiV00TQyXz1WfP3zxmP03tO1zs9XdjHRWoL5VUkEsBZT1FNJIZTDURB7A/2gO4rFomh27pcai51InqnNLmtDGNY0Naxo6NaB0C6T/oO9ysqyfVu9ysDrooUrojhRSoXMd2H6pnuV1SH6pnuV0URERRERAREQEREHetdyfQduwxRVFNUNDJoJc7XgHI5jmCD0IXbffdjaaKiooKWmgqG1Jja5zjI9vQuceeMcsBYZFNIyLbrI2S6u7Jh+cWOY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IAA6DkFxXOvFbTW6IRlhpKcQEk53esTny6pobZcZq+OltIpL7T0EfoEJ7F9QWHODzwAeq69nddJtKyPttUY6p9xJkkM7Yy8GPxcRnmsXU3S1VsVH6bQ1xlp6dlPmKoa1rg3vwWnxXSnuEL7K63RQPaz0s1DXPcCQ3btDTy6+amhtjDjU1LFUujfc4rdUMrXsAwZOzfgHHIuDcZKwOkS+giq7y2IyPpGNjhbt3Zlfy6eTQ4qYtQsFbS1k1M99UykkpZnh4Ha5YWtd06gEZ8cLqxXyopLRS0VuknpDG58k0kcmDK44A6dwAxhNSK6nom0V5mbC0immAnhyMeo8ZA+7JH3K9i/gtNX3M9YI+xh/lZMgH7m7j8FxXS7PudDRMq+0krKfe01D35L2E5APfkHPPzVKuriNpoqKn3YYXzTkjG6R3IY8QGgD7yr4HWoqypoZu1op5IJcbd7Dg48FserLvcTT26I11R2U9ujdK3fyeTnJPvWqrv3evFeKINjMfo9KynOTncW55/irMdR3tZf4Spf9hpv6gXetNW+WyUlLZ7nFbq6J7zNG9/ZekEn1SH9DgctpXUrbraK98ElZQ13bRwRwkx1DGtOxuM4LSuvHX22ejgguNDMXQAtZLTSNY57Sc4eCCCR49VPA4dROndd5zWUjaSp9USxtGAXYGXeHPry5c1jV373cTc68z9kImNYyKOMHdtY0YAJ7zjvXQVgERFVEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAVJvqX+5XVJvqX+5EdBQpRaZSiEouau9D9Uz3K6rA1xhYQ09FybHeyVVVRW2O9kpsd7JVVVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx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"

# Ana menü banner'ları (dile göre, JPEG)
_BANNERS = {
 "tr": "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Kjzz4vsm43cO8FPJGVIcjYCA8/eRleA03jmuKD7OmtANS62JSiEIIIJVavlAiN/gDDFEfxd15a5MgyIIbzzy6r9uWfogP1Iodh2VDPygZnVJ9DBYAG+MZpATqAZO24ixjhX47644CCADA5BCAIJROwBajwABAJSKLyhT64G5nGM96eZoWXrZGjmIg7ExsTuZw/rCLv1ED9VddzL0Ah37566uSCAIIIIIIIIII4qdcYoYIIIIayhXzalmxEP2sU9ju1aK3jUMWURPYAW6izy8qi5LxWa1a7uUQnr76pxChbCQosDi7IYfyo4VzvjzIgJTTyGlz6vHYjzZTmu+6xxCWGyT7u7nGj4d6mfhjHVJUVK16PURHGr7473vncpx/hV0mi7zr84jbPjqWQmdr1SzzxYj/wAA8JfINFoMhgh+0Tim13ctm0ViNncVhQZuWAIFShPg++u1q98HzHh4TMVaxbNXj6w+LACqQD0U9NM+sT3IhWT9vz+Bh8fqbO7x85r69HDAid4Zb1GozdjU5VtM++iEtK2/iKy4yGCW+6iqIVX+yCOa+C5U9pwywq64JlI1pi6wqYQhPcneMJyD8nStfDKFLd7dOVVeh9G92+O562lniV543g7siSeLO4j244JECK8p88JAC0bDEB+ANyNDIPNKwqDbC0yny/P7vBMZgbJDOUOpUq99+e+NkenQwCv8jQq8e97oxWLKQYfy++cp88rAkCoT+sZuB+8U6KnvbUzRWDzz/upAzLbvm7TU51ZH6d9/+++q/OFxWu+GOOe+++OlL0yWeeO+2q99898phASMTLkRuN/K3czP7999tNdl97+Y0LT9hj/DSqCcd999++++uhBO+++66++++++OBxGz2+++62W98D/8Bc8SoTrkN0LdEDzu6wsMOMPMw0P6jEVewhW2ZDck0999++++++++++u++++++++++u++++++ea99+DR909sMasTFwlYy0fkMTzzDPLTzzjGM1e6AP2PxBck9999/++++++++++2+++/++++++/8A/wD777777/3wsBX/AM999IsI1v0tAS2uf5EIMMIAR1O6wAN+n9hc+N9//wD/AP8A/8QAKhEBAAIBAgMIAwEBAQAAAAAAAQARITHwEEFRIDBhcYGhsdGRwfHhQFD/2gAIAQMBAT8QeLGPYOBxIQhwO9e4XhfC4uZcuXLl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",
 "tk": "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",
 "ru": "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",
}

if __name__ == "__main__":
    main()
