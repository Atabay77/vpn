import os, sys, io, re, json, html, uuid, base64, asyncio, zipfile, shutil, fcntl, logging, datetime, time, socket, random, hashlib, warnings, unicodedata
import urllib.request, urllib.parse, urllib.error
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from telegram import Update, InlineKeyboardButton as _IKB, InlineKeyboardMarkup as KB

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

LANGC = {}   # uid -> "tr"/"ru" (her ekranda veritabanı okunmasın)
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

def build_text(title, announce, servers):
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
        announce, servers = "Abonelik süresi doldu. Admin ile iletişime geçin.", []
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
        used = {v.get("file_id") for v in db["subs"].values() if v.get("file_id")} | {db.get("tm_fid")} | source_fids(db)
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
            sync_file(svc, fid, "Empty", "Abonelik iptal edildi", [], exp=False)  # eski link sunucu vermesin
        save_db(db)
        return True


# ───────── KOD ÇEKME ─────────
PROTOS = ("vless://", "vmess://", "trojan://", "ss://", "hysteria://", "hysteria2://", "hy2://", "tuic://")

def fetch_codes(url):
    req = urllib.request.Request(url, headers={"User-Agent": "v2rayN/6.42"})
    with urllib.request.urlopen(req, timeout=15) as r:
        content = r.read().decode("utf-8", "ignore")
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
    "ru": ("🇷🇺", "Russia", ["⚡ Moscow Pulse", "🏰 Kremlin Bastion", "❄️ Siberian Frost", "🐻 Taiga Bear", "🌊 Neva Stream", "🚄 Volga Express",
                            "🛡️ Ural Shield", "💎 Baikal Crystal", "🔥 Red Square Core", "🦅 Arctic Falcon", "🌉 Petersburg Gate", "🌋 Kamchatka Storm"]),
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
    used = {v.get("file_id") for v in db["subs"].values()} | set(db["free_files"]) | source_fids(db)
    fid = find_free_file(svc, used)
    if not fid: raise RuntimeError("Drive'da kanal için boş dosya yok")
    _tm_write(svc, fid, data, TM_NAME)
    return fid

def load_exits():
    try:
        with open(EXIT_FILE, encoding="utf-8") as f: return json.load(f)
    except Exception: return {}

def tm_sync(db, sources, codes=None):
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
        new_keys = sorted(code_key(c) for c in (codes or []))
        if ch.get("sources") != sources or (codes and sorted(code_key(c) for c in ch.get("codes", [])) != new_keys):
            ch["sources"] = sources
            if codes: ch["codes"], ch["codes_ts"] = list(codes), int(time.time())
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
    good = sum(1 for v in res.values() if isinstance(v, (int, float)) and v > 0)
    stale = bool(ts) and time.time() - ts > TM_MAX_AGE
    if ch.get("status") == "not_tm" and int(ch.get("status_ts") or 0) >= ts:
        RUN["tm_line"] = f"⚠️ Telefon testi VPN'den çıkıyor ({ch.get('country', '?')}) → Happ'te Termux Bypass olmalı"
        if RUN.get("tm_warned") != ch.get("status_ts"):
            RUN["tm_warned"] = ch.get("status_ts"); vlog(RUN["tm_line"])
    elif stale:
        RUN["tm_line"] = f"📱 Telefon testi: {ago(ts)} (eski, kullanılmıyor)"
    elif ts:
        RUN["tm_line"] = f"📱 Telefon testi: {ago(ts)} · {good}/{len(res)} çalışıyor"
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
        vlog(f"📱 Telefon testi (TM): {good} çalışıyor, {len(res) - good} çalışmıyor, {ch.get('skipped', 0)} test edilmedi")
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
            except Exception as e2: return i, [], str(e2 or e)[:80], time.time() - t

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
            await notify_founders(app, f"❌ <b>Kontrol başarısız</b>\n{esc(r['error'])}")
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
    day = ""
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
        # her gün 03:00 otomatik yedek
        try:
            now = datetime.datetime.now(); d = now.strftime("%Y-%m-%d")
            if now.hour == 3 and day != d:
                day = d
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

async def post_init(app):
    await asyncio.to_thread(migrate_announce)
    if os.path.exists(UPDATE_NOTE):
        try:
            sha = open(UPDATE_NOTE).read().strip(); os.remove(UPDATE_NOTE)
            await notify_founders(app, f"🟢 <b>Bot yeni sürümle açıldı</b> <code>{esc(sha)}</code>")
        except Exception: pass
    try: BOT["un"] = (await app.bot.get_me()).username or ""
    except Exception as e: log.warning("get_me: %s", e)
    global CHECK_LOCK, WAKE
    CHECK_LOCK, WAKE = asyncio.Lock(), asyncio.Event()
    app.bot_data["mon"] = asyncio.create_task(monitor(app))
    app.bot_data["wd"] = asyncio.create_task(watchdog(app))
    try:
        from telegram import BotCommand
        await app.bot.set_my_commands([BotCommand("start", "Ana menü"), BotCommand("id", "Telegram ID'n")])
    except Exception as e: log.warning("commands: %s", e)


# ───────── MENÜLER ─────────
def menu_text(uid):
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
    lang_btn = B(L(uid, "🌐 Dil: Türkçe", "🌐 Язык: Русский"), "lang")
    if uid not in ADMINS:   # panel sahibi: kendi panelinde kod oluşturur
        return KB([[B(L(uid, "✨ Kod Oluştur", "✨ Создать код"), "create_key", "success"), B(L(uid, "👥 Kodlarım", "👥 Мои коды"), "my_keys", "primary")],
                   [B(L(uid, "👤 Profil", "👤 Профиль"), "u_prof"), B(L(uid, "🛒 Market", "🛒 Магазин"), "u_market")],
                   [B(L(uid, "🆘 Destek", "🆘 Поддержка"), "u_sup"), B(L(uid, "🐞 Hata Bildir", "🐞 Баг-репорт"), "u_bug")],
                   [lang_btn]])
    # kurucu: kullanıcıların gördüğü butonlar + tek bir Admin butonu (geri kalan her şey Admin'in içinde)
    return KB([[B(L(uid, "✨ Kod Oluştur", "✨ Создать код"), "u_free", "success"), B(L(uid, "👥 Kodlarım", "👥 Мои коды"), "my_keys")],
               [B(L(uid, "👤 Profil", "👤 Профиль"), "u_prof"), B(L(uid, "🛒 Market", "🛒 Магазин"), "u_market")],
               [B(L(uid, "🆘 Destek", "🆘 Поддержка"), "tickets"), B(L(uid, "🐞 Hata Bildir", "🐞 Баг-репорт"), "tickets_bug")],
               [lang_btn],
               [B("🟡 Admin", "admin", "primary")]])

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
        [B("📈 Rapor", "rep_today"), B("📊 İstatistik", "stats")],
        [B("📢 Kanallar", "chans"), B("🪙 CryptoBot", "cp")],
        [B("💳 TMT 🔜", "pay_set")],
        [B("📣 Herkese Mesaj", "bcast")],
        [B("👮 Alt Adminler", "sa_menu")],
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
            + L(uid, "🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>", "🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>") + f"\n<code>{esc(sub_link(fid) if fid else 'Drive dosyası yok')}</code>")

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
                await q.edit_message_text(log_text()[:4000], parse_mode="HTML", reply_markup=LOG_KB, disable_web_page_preview=True)
    except asyncio.CancelledError: pass
    except Exception as e: log.info("live log stopped: %s", e)   # flood/silinen mesaj -> sessizce dur
    finally:
        if LIVE.get(uid) is asyncio.current_task(): LIVE.pop(uid, None)

async def safe_edit(q, text, kb=None):
    try:
        await q.edit_message_text(text[:4000], parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
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
                f"🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>\n<code>{esc(sub_link(fid))}</code>",
                KB([[B("🎟 К коду", f"kv:{kid}", "primary"), B("◀️ Меню", "menu")]]))
    return (f"✅ <b>Kod oluşturuldu!</b>\n<blockquote>🎟 <b>{esc(name)}</b>\n⏳ Süre  <b>{left}</b></blockquote>\n"
            f"🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>\n<code>{esc(sub_link(fid))}</code>",
            KB([[B("🎟 Koda Git", f"kv:{kid}", "primary"), B("◀️ Menü", "menu")]]))

async def on_num(c, uid, st, n, send, who=""):
    """send(text, kb): mesajı düzenler ya da yeni mesaj atar."""
    what = st["what"]
    if what.startswith("sa_") and uid not in ADMINS: return
    lo = 0 if what == "nk_days" and uid in ADMINS else 1
    hi = 500 if what in ("sa_limit", "sa_lim") else 3650
    if not (lo <= n <= hi):   # butonlarla birlikte tekrar sor
        ctx = {k: v for k, v in st.items() if k not in ("action", "what")}
        await send(*ask_num(uid, what, L(uid, f"⚠️ {lo} ile {hi} arasında bir sayı.\n", f"⚠️ Число от {lo} до {hi}.\n"), **ctx)); return
    if what == "nk_days":
        res, err = await asyncio.to_thread(create_vip, st["name"], uid, n or None)
        if res: audit(uid, f"create {res[0]} {st['name']} {n or '∞'}g")
        await send(*create_result(res, err, st["name"], uid))
        if res and uid not in ADMINS:
            await notify_founders(c.application, f"🔔 Alt admin <b>{esc(who)}</b> (<code>{uid}</code>) kod oluşturdu: <code>{esc(st['name'])}</code> · {n} gün")
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
        try: await c.bot.send_message(tid_, tr(lg, "gift", left=left_txt(load_db()["subs"][res[0]].get("expires"), lg == "ru"), link=esc(sub_link(res[1]))), parse_mode="HTML")
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
    await u.message.reply_text(menu_text(uid), parse_mode="HTML", reply_markup=main_kb(uid))

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
            t, kb = ask_num(uid, "nk_days", f"🎟 <b>{esc(name)}</b>\n", name=name)
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

FOUNDER_ONLY = {"usearch", "rep_today", "rep_yday", "tickets_bug", "t_cancel", "tickets", "cp_test", "cp", "cp_set", "cp_del", "ul_open", "stats", "chans", "ch_add", "pay_set", "bcast", "bcast_yes", "rollback", "rollback_yes", "auto_ann", "toggle_sys", "admin", "sources", "s_add", "logs", "upd_now", "get_zip", "sa_menu", "sa_add", "bulk_ann", "bulk_title", "bulk_yes"}
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
    if uid not in ADMINS and (a in FOUNDER_ONLY or a.startswith(("sv:", "se:", "sd:", "sa_del:", "sa_ext:", "sa_lim:", "kx:", "kxs:", "ul:", "chd:", "ord_ok:", "ord_no:", "t_rep:", "t_close:", "tv:", "ug:", "ux:", "uxc:", "ub:", "uv:"))):
        await q.answer(L(uid, "⛔ Erişim yok", "⛔ Нет доступа"), show_alert=True); return
    if a not in ("toggle_sys", "upd_now"):
        await q.answer()
    if a != "logs" and uid in LIVE:
        LIVE.pop(uid).cancel()
    try: db = load_db()
    except Exception as e:
        await safe_edit(q, f"❌ {esc(e)}", back("menu", "◀️ Menü")); return

    if uid not in ADMINS and ":" in a and a.split(":", 1)[0] in OWNED:
        s = db["subs"].get(a.split(":", 1)[1])
        if not s or s.get("owner_id") != uid:
            await safe_edit(q, L(uid, "⛔ Bu kod senin değil.", "⛔ Это не ваш код."), back("my_keys")); return

    if a == "menu":
        STATE.pop(uid, None)
        await safe_edit(q, menu_text(uid), main_kb(uid))

    elif a == "lang":
        nl = "tr" if is_ru(uid) else "ru"
        await asyncio.to_thread(touch_user, q.from_user)
        mutate(lambda d: d.setdefault("users", {}).setdefault(str(uid), {}).__setitem__("lang", nl))
        LANGC[uid] = nl
        await safe_edit(q, menu_text(uid), main_kb(uid))

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

    elif a.startswith("ub:"):
        tid_ = a.split(":", 1)[1]
        def f(d):
            e = d.get("users", {}).get(tid_)
            if not e: return None
            e["banned"] = not e.get("banned"); return e["banned"]
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

def set_env(key, val):
    """env.txt'de bir satırı değiştirir/ekler/siler (val boşsa siler)."""
    lines = open(ENV_FILE, encoding="utf-8").read().splitlines() if os.path.exists(ENV_FILE) else []
    lines = [l for l in lines if not l.strip().startswith(key + "=")]
    if val: lines.append(f"{key}={val}")
    with open(ENV_FILE + ".tmp", "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
    os.replace(ENV_FILE + ".tmp", ENV_FILE)
    if val: os.environ[key] = val
    else: os.environ.pop(key, None)

def lang_of(db, uid): return "ru" if is_ru(uid) else "tr"   # tek kaynak: LANGC (menüler arasında tutarsızlık olmasın)
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
def new_captcha(uid):
    a, b = random.randint(2, 9), random.randint(2, 9)
    op = random.choice(["+", "×"])
    ans = a + b if op == "+" else a * b
    opts = {ans}
    while len(opts) < 4: opts.add(max(1, ans + random.randint(-6, 6)))
    opts = list(opts); random.shuffle(opts)
    mutate(lambda d: d["users"].get(str(uid), {}).__setitem__("cap", ans))
    return a, op, b, opts

def captcha_view(lang, uid):
    a, op, b, opts = new_captcha(uid)
    return tr(lang, "cap", a=a, op=op, b=b), KB([[B(str(o), f"u_cap:{o}") for o in opts]])

# ── ana menü ──
def pub_menu(db, uid):
    lang = lang_of(db, uid)
    e = db.get("users", {}).get(str(uid), {})
    t = tr(lang, "menu", avail=max(0, avail_refs(e)), need=REF_NEED, codes=len(user_codes(db, uid)))
    kb = KB([[B(tr(lang, "b_free"), "u_free", "success"), B(tr(lang, "b_mine"), "u_mine", "primary")],
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
    await send(*pub_menu(load_db(), user.id))

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
    db = load_db(); lang = lang_of(db, uid)
    async def send(t, kb=None): await safe_edit(q, t, kb)
    menu_btn = KB([[B(tr(lang, "b_menu"), "u_menu")]])

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
        e = db["users"].get(str(uid), {})
        if e.get("ok") or "cap" not in e:
            await q.answer(); await send(*pub_menu(db, uid)); return
        if str(e.get("cap")) != a.split(":", 1)[1]:
            await q.answer(tr(lang, "cap_wrong"), show_alert=True)
            ulog("cap_bad", f"🤖 Yanlış cevap: {who(user)}")
            await send(*captcha_view(lang, uid)); return
        await q.answer("✅")
        mutate(lambda d: (d["users"][str(uid)].pop("cap", None), d["users"][str(uid)].__setitem__("cap_ok", True)))
        ulog("verify", f"✅ Doğrulamayı geçti: {who(user)}")
        if not await pub_gate(c, uid, lang, send): return
        await send(*pub_menu(load_db(), uid)); return

    if a == "u_check":
        JOINED.pop(uid, None)
        miss = await missing_channels(c.bot, uid)
        if miss:
            await q.answer(tr(lang, "join_no"), show_alert=True); return
        await q.answer("✅")
        if not await pub_gate(c, uid, lang, send): return
        await send(*home(uid)); return

    await q.answer()
    if not await pub_gate(c, uid, lang, send): return
    db = load_db(); e = db["users"].get(str(uid), {})

    if a == "u_menu":
        STATE.pop(uid, None)
        await send(*home(uid))

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

    elif a == "u_lang":
        nl = "ru" if lang == "tr" else "tr"
        mutate(lambda d: d["users"][str(uid)].__setitem__("lang", nl))
        LANGC[uid] = nl
        await send(*pub_menu(load_db(), uid))

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
        await send(tr(lang, "free_ok", left=left_txt(load_db()["subs"][kid].get("expires"), lang == "ru"), link=esc(sub_link(fid))), menu_btn)

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
        await send(tr(lang, "trial_ok", link=esc(sub_link(res[1]))), menu_btn)

    elif a.startswith("u_ext:"):
        kid = a.split(":", 1)[1]; s_ = db["subs"].get(kid)
        if not s_ or s_.get("owner_id") != uid: await send(tr(lang, "mine_none"), menu_btn); return
        await send(*ext_view(lang, kid, s_))

    elif a.startswith("u_xb:"):
        _, kid, item = a.split(":")
        s_ = db["subs"].get(kid)
        if not s_ or s_.get("owner_id") != uid or item not in PRICES: await send(tr(lang, "mine_none"), menu_btn); return
        await send(*new_order(uid, user, lang, item, ext=kid))

    elif a == "u_mine":
        mine = user_codes(db, uid)
        if not mine: await send(tr(lang, "mine_none"), menu_btn); return
        body = "\n".join(tr(lang, "mine_item", name=esc(short(name_of(s, k), 30)), left=left_txt(s.get("expires"), lang == "ru"), link=esc(sub_link(s.get("file_id", "")))) for k, s in mine[:8])
        ext_rows = [[B(f"{tr(lang, 'b_ext')} · {short(name_of(s_, k), 18)}", f"u_ext:{k}")] for k, s_ in mine[:8] if s_.get("pub") in ("paid", "gift")]
        await send(tr(lang, "mine") + "\n" + body, KB(ext_rows + [[B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_prof":
        inv = db["users"].get(str(e.get("ref_by")), {}) if e.get("ref_by") else {}
        t = tr(lang, "prof", id=uid, name=esc(user.full_name or "—"), un=("@" + esc(user.username)) if user.username else "—",
               joined=tm_fmt(e.get("joined", time.time())), now=tm_now().strftime("%d.%m.%Y %H:%M"),
               total=len(e.get("refs", [])), avail=max(0, avail_refs(e)), need=REF_NEED, free=e.get("free_n", 0),
               active=len(user_codes(db, uid)), buys=e.get("buys", 0), inviter=esc(inv.get("name") or tr(lang, "nobody")),
               link=esc(ref_link(uid)))
        await send(t, KB([[B(tr(lang, "b_share"), url=share_url(lang, uid), style="success")], [B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_market":
        STATE.pop(uid, None)
        await send(tr(lang, "market"), KB([[B(tr(lang, "b_c7"), "u_buy:c7", "primary")], [B(tr(lang, "b_c30"), "u_buy:c30", "primary")],
                                           [B(tr(lang, "b_panel"), "u_buy:panel", "success")], [B(tr(lang, "b_menu"), "u_menu")]]))

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
        it = tr(lang, "it_panel", n=o["n"]) if o["item"] == "panel" else tr(lang, "it_" + o["item"])
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
        await send(*pub_menu(load_db(), uid))

def item_tr(o):
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
        await send(*pub_menu(db, uid)); return
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
    if o["item"] == "panel":
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
        msg = tr(lang, "order_ok_code", oid=oid, left=left_txt(load_db()["subs"][kid].get("expires"), lang == "ru"), link=esc(sub_link(fid)))
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
        used = {v.get("file_id") for v in db["subs"].values()}
        return len((set(pool_files(svc)) | set(db["free_files"])) - used)
    except Exception: return "?"

def stats_text():
    db = load_db(); us = db.get("users", {})
    today = tm_now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    pub = [s for s in db["subs"].values() if s.get("pub") and not is_exp(s)]
    orders = db.get("orders", {}).values()
    paid = sum(o["price"] for o in orders if o["status"] == "done" and not o.get("test"))
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
  "b_sup": "🆘 Destek", "b_bug": "🐞 Hata Bildir", "b_tclose": "🔒 Talebi Kapat", "b_report": "📨 Admine Bildir",
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
    if uid in ADMINS:
        st = STATE.get(uid) or {}
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
    try: return bool(load_db().get("users", {}).get(str(uid), {}).get("banned"))
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
    done = [o for o in db.get("orders", {}).values() if o.get("status") == "done" and not o.get("test") and start <= o.get("done_ts", 0) < end]
    tmt = sum(o["price"] for o in done)
    usdt = sum(o["price"] for o in done if o.get("via") == "usdt") / USDT_RATE
    pub = [s for s in db["subs"].values() if s.get("pub") and not is_exp(s)]
    op = sum(1 for t in db.get("tickets", {}).values() if t.get("status") == "open")
    return (f"📈 <b>{title}</b>\n<blockquote>"
            f"🆕 Yeni kullanıcı  <b>{k('join')}</b>\n"
            f"🤝 Sayılan davet  <b>{k('credit')}</b>\n"
            f"🎁 Ücretsiz kod  <b>{k('free')}</b>  ·  🧪 Deneme  <b>{k('trial')}</b>\n"
            f"💰 Satış  <b>{len(done)}</b>  ·  <b>{tmt} TMT</b>  ·  💵 <b>{usdt:g} USDT</b>\n"
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
         + ("🚫 <b>ENGELLİ</b>\n" if e.get("banned") else "")
         + "</blockquote>\n"
         + ("\n".join(f"🎟 {esc(short(name_of(s, k), 26))} · ⏳ {left_txt(s.get('expires'))}" for k, s in codes) or "<i>Aktif kodu yok.</i>"))
    kb = KB([[B("🎁 Kod Ver", f"ug:{tid}", "success"), B("⏳ Süre Ekle", f"ux:{tid}")],
             [B("✅ Engeli Kaldır", f"ub:{tid}") if e.get("banned") else B("🚫 Engelle", f"ub:{tid}", "danger")],
             [B("🔎 Başka Ara", "usearch"), B("◀️ Admin", "admin")]])
    return t, kb

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

if __name__ == "__main__":
    main()
