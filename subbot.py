import os, sys, io, re, json, html, uuid, base64, asyncio, zipfile, shutil, fcntl, logging, datetime, time, socket, random, hashlib, warnings, unicodedata
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

HAPP_DEFAULT_PROVIDER = "vAUH3NRg"   # happ-proxy.com Provider ID (gizli değil; Happ'ta "#hide-settings" bununla çalışır)

def build_text(title, announce, servers):
    prov = os.environ.get("HAPP_PROVIDER") or HAPP_DEFAULT_PROVIDER
    lines = ([f"#providerid {prov}"] if prov else []) + [f"#profile-title: {title}"]
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
    used = used_fids(db) | set(db["free_files"])
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
    """Bot kısa sürede çok kez yeniden açıldıysa kuruculara sebebiyle bildirir (saatte en fazla bir kez)."""
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
    global CHECK_LOCK, WAKE
    CHECK_LOCK, WAKE = asyncio.Lock(), asyncio.Event()
    app.bot_data["mon"] = asyncio.create_task(monitor(app))
    app.bot_data["wd"] = asyncio.create_task(watchdog(app))
    try: mutate(ensure_own)   # bizim ilan pazarda hep olsun
    except Exception: log.exception("market init")
    app.bot_data["mkt"] = asyncio.create_task(market_loop(app))
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

def menu_text(uid):
    try: db = load_db()
    except Exception: db = None
    return _menu_text(uid) + (open_mkt_text(db, uid, lang_of(db, uid)) if db else "")

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
                   [B(L(uid, "🆘 Destek", "🆘 Поддержка"), "u_sup"), B(L(uid, "🐞 Hata Bildir", "🐞 Баг-репорт"), "u_bug")],
                   [lang_btn]])
    # kurucu: kullanıcıların gördüğü butonlar + tek bir Admin butonu (geri kalan her şey Admin'in içinde)
    return KB([[B(L(uid, "🏪 Pazar", "🏪 Биржа"), "u_mkt", "success")],
               [B(L(uid, "✨ Kod Oluştur", "✨ Создать код"), "u_free"), B(L(uid, "👥 Kodlarım", "👥 Мои коды"), "my_keys")],
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
        [B("💰 Bakiye Ekle / Düş", "bal_find")],
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
            + L(uid, "🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>", "🔗 <b>Ссылка подписки</b> <i>(нажмите → скопировать)</i>") + f"\n<code>{esc(sub_link(fid) if fid else 'Drive dosyası yok')}</code>"
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

FOUNDER_ONLY = {"hp", "hp_set", "hp_del", "hp_new", "ref_test", "mk_admin", "mk_price", "mk_oph", "mk_ods", "mk_odr", "bal_find", "usearch", "rep_today", "rep_yday", "tickets_bug", "t_cancel", "tickets", "cp_test", "cp", "cp_set", "cp_del", "ul_open", "stats", "chans", "ch_add", "pay_set", "bcast", "bcast_yes", "rollback", "rollback_yes", "auto_ann", "toggle_sys", "admin", "sources", "s_add", "logs", "upd_now", "get_zip", "sa_menu", "sa_add", "bulk_ann", "bulk_title", "bulk_yes"}
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
    if uid not in ADMINS and (a in FOUNDER_ONLY or a.startswith(("sv:", "se:", "sd:", "sa_del:", "sa_ext:", "sa_lim:", "kx:", "kxs:", "ul:", "chd:", "ord_ok:", "ord_no:", "t_rep:", "t_close:", "tv:", "ug:", "ux:", "uxc:", "ub:", "uv:", "ubal:", "mk_l:", "mk_ok:", "mk_rm:", "mk_ph:", "hl:", "hlp:"))):
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
        with urllib.request.urlopen(req, timeout=20) as r: return json.loads(r.read().decode("utf-8")).get("encrypted_link") or None
    except Exception as e:
        log.warning("happ encrypt: %s", type(e).__name__); return None

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
    t = tr(lang, "menu", avail=max(0, avail_refs(e)), need=REF_NEED, codes=len(user_codes(db, uid))) + open_mkt_text(db, uid, lang)
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
            await send(*home(uid)); return
        if e.get("ok") or "cap" not in e:
            await q.answer(); await send(*pub_menu(db, uid)); return
        await q.answer("✅")
        mutate(lambda d: (d["users"][str(uid)].pop("cap", None), d["users"][str(uid)].update({"cap_ok": True, "role": role})))
        ulog("verify", f"{'🏪 Satıcı olarak geldi' if role == 'seller' else '🛒 Alıcı olarak geldi'}: {who(user)}")
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

    elif a == "u_mkt":
        STATE.pop(uid, None)
        await show_market(c, q, uid, lang)

    elif a.startswith("u_mp:"):   # pazarda sonraki / önceki ilan
        await show_market(c, q, uid, lang, int(a.split(":", 1)[1]))

    elif a.startswith("u_ml:"):
        lid = a.split(":", 1)[1]; order = mkt_order(load_db())
        if lid not in order: await send(tr(lang, "m_gone"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        await show_market(c, q, uid, lang, order.index(lid))

    elif a.startswith("u_mck:"):   # anlık kontrol (kullanıcı 5 dk'da bir, kurucu sınırsız)
        lid = a.split(":", 1)[1]; now = time.time()
        left = CHK_EVERY - (now - CHK["user"].get(uid, 0))
        if uid not in ADMINS and left > 0:
            await q.answer(tr(lang, "chk_wait", m=int(left // 60) + 1), show_alert=True); return
        CHK["user"][uid] = now
        kb = chk_kb(lang, lid); t = check_text(load_db(), lid, lang, None, "run")
        msg = getattr(q, "message", None)
        if msg is not None:   # aynı kutu hemen "Kontrol ediliyor..." olur
            is_photo = bool(getattr(msg, "photo", None)); mid = msg.message_id
            if not await edit_box(c.bot, uid, mid, is_photo, t, kb):
                is_photo = False; mid = (await c.bot.send_message(uid, t, parse_mode="HTML", reply_markup=kb)).message_id
        else: is_photo = False; mid = (await c.bot.send_message(uid, t, parse_mode="HTML", reply_markup=kb)).message_id
        ch = await asyncio.to_thread(_read_channel, load_db()); ts = ch.get("ts") or 0
        if ts and now - ts < CHK_FRESH: state = "fresh"   # telefon az önce test etti: tekrar test yok
        elif not ts or now - ts > PHONE_OFF: state = "off"   # telefon uzun süredir sonuç göndermiyor: boşuna bekletme
        elif CHK["wait"].get(lid) and CHK["qid"]: qid, state = CHK["qid"], "run"   # bu ilan zaten test ediliyor
        else:
            async with CHECK_LOCK: _, qid = await asyncio.to_thread(request_phone_test, load_db(), set(CHK["wait"]) | {lid})
            if qid: CHK["qid"], CHK["req"], state = qid, now, "run"
            else: state = "timeout"
        if state == "run":
            CHK["wait"].setdefault(lid, {})[uid] = (lang, mid, is_photo, qid, now)
            if not CHK.get("poll") or CHK["poll"].done(): CHK["poll"] = asyncio.create_task(chk_poll(c.application))
        else: await edit_box(c.bot, uid, mid, is_photo, check_text(load_db(), lid, lang, ch, state), kb)
        ulog("m_check", f"🔍 Kontrol etti: {who(user)} · {db.get('market', {}).get(lid, {}).get('title', lid)}")

    elif a.startswith("u_mph:"):
        L_ = db.get("market", {}).get(a.split(":", 1)[1], {})
        if L_.get("photo"):
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
        await send(tr(lang, "m_started", title=esc(L_["title"]), p=money2(float(L_["price"]) * 43200, True) + " TMT/30", bal=fmt_u(d2["users"][str(uid)].get("bal", 0)), link=esc(sub_link(fid))),
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
                                               "price": st_["price"], "codes": st_["codes"], "codes_ts": time.time(), "status": "pending", "created": time.time()}
            return "ok"
        r = mutate(f)
        if r == "nobal": await send(tr(lang, "sell_nobal"), KB([[B(tr(lang, "b_top"), "u_top", "success")], [B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        STATE.pop(uid, None)
        if r == "dup": await send(tr(lang, "sell_dup"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        if r == "ban": await send(tr(lang, "sell_banned", left="—"), KB([[B(tr(lang, "b_back_mkt"), "u_mkt")]])); return
        ulog("m_list", f"📤 Pazara ilan verdi: {who(user)} · {st_['title']} · {fmt_u(st_['price'])} USDT/dk")
        await send(tr(lang, "sell_sent"), KB([[B(tr(lang, "b_myl"), "u_myl")], [B(tr(lang, "b_back_mkt"), "u_mkt")]]))
        await notify_founders(c.application, f"📤 <b>Yeni pazar ilanı</b> (incelemede)\n<blockquote>{esc(who(user))}\n🏷 {esc(st_['title'])} · {money_tmt(float(st_['price']) * 43200)} TMT/ay</blockquote>\n<i>⏳ Telefon testi bekleniyor; sonuç gelince bildirilecek.</i>")

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
        await send(tr(lang, "top", bal=fmt_u(e.get("bal", 0))),
                   KB([[B(f"{n} USDT", f"u_topa:{n}", "primary") for n in (1, 3, 5, 10)], [B(tr(lang, "b_other"), "u_topc")], [B(tr(lang, "b_menu"), "u_menu")]]))

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
        await send(*(home(uid) if to == "p" else pub_menu(load_db(), uid)))

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
        sess = [(sid, x) for sid, x in db.get("msess", {}).items() if x["buyer"] == uid and x["status"] == "on"]
        if not mine and not sess: await send(tr(lang, "mine_none"), menu_btn); return
        body = "\n".join(tr(lang, "mine_item", name=esc(short(name_of(s, k), 30)), left=left_txt(s.get("expires"), lang == "ru"), link=esc(sub_link(s.get("file_id", "")))) for k, s in mine[:8])
        body2 = "\n".join(tr(lang, "mine_m", title=esc(short(db["market"].get(x["lid"], {}).get("title", "?"), 26)), dur=dur_txt(time.time() - x["start"], lang == "ru"),
                             usdt=fmt_u(x["total"]), link=esc(sub_link(x["fid"]))) for sid, x in sess[:5])
        ext_rows = [[B(f"{tr(lang, 'b_ext')} · {short(name_of(s_, k), 18)}", f"u_ext:{k}")] for k, s_ in mine[:8] if s_.get("pub") in ("paid", "gift")]
        stop_rows = []
        for sid, x in sess[:5]:
            nm_ = short(db["market"].get(x["lid"], {}).get("title", "?"), 14)
            stop_rows += [[B(f"{tr(lang, 'b_live')} · {nm_}", f"u_live:{sid}", "primary")], [B(f"{tr(lang, 'b_stop')} · {nm_}", f"u_msq:{sid}", "danger")]]
        await send(tr(lang, "mine") + "\n" + "\n".join(x for x in (body, body2) if x), KB(ext_rows + stop_rows + [[B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_prof":
        inv = db["users"].get(str(e.get("ref_by")), {}) if e.get("ref_by") else {}
        t = tr(lang, "prof", id=uid, name=esc(user.full_name or "—"), un=("@" + esc(user.username)) if user.username else "—",
               joined=tm_fmt(e.get("joined", time.time())), now=tm_now().strftime("%d.%m.%Y %H:%M"),
               total=len(e.get("refs", [])), avail=max(0, avail_refs(e)), need=REF_NEED, free=e.get("free_n", 0),
               active=len(user_codes(db, uid)), buys=e.get("buys", 0), inviter=esc(inv.get("name") or tr(lang, "nobody")),
               link=esc(ref_link(uid)))
        t += tr(lang, "bal_line", bal=fmt_u(e.get("bal", 0)), tmt=tmt_u(e.get("bal", 0))) + (tr(lang, "earn_line", earn=fmt_u(e["earn"])) if e.get("earn") else "")
        await send(t, KB([[B(tr(lang, "b_share"), url=share_url(lang, uid), style="success")],
                          [B(tr(lang, "b_top"), "u_top", "primary")]] + ([[B(tr(lang, "b_wd"), "u_wd")]] if e.get("earn") else []) + [
                          [B(tr(lang, "b_menu"), "u_menu")]]))

    elif a == "u_market":
        STATE.pop(uid, None)
        await send(tr(lang, "market"), KB([[B(tr(lang, "b_mkt"), "u_mkt", "success")], [B(tr(lang, "b_c7"), "u_buy:c7", "primary")], [B(tr(lang, "b_c30"), "u_buy:c30", "primary")],
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
        await send(*pub_menu(load_db(), uid))

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
    try: sync_file(new_service(), s["fid"], "Empty", "Abonelik durduruldu", [], exp=False)
    except Exception: pass
    return info

def pay_seller(seller, amount, spend_id, comment):
    """Satıcının kazancını CryptoBot'a gönderir; olmazsa bot içi çekilebilir bakiyeye ekler. Dönüş: 'sent' | 'bal'."""
    if amount <= 0: return "none"
    if crypto_token():
        try:
            crypto_call("transfer", user_id=seller, asset="USDT", amount=fmt_u(amount), spend_id=spend_id[:64], comment=comment[:500])
            return "sent"
        except Exception as e:
            RUN["transfer_err"] = str(e)[:150]
    mutate(lambda d: d["users"].setdefault(str(seller), {}).__setitem__("earn", d["users"][str(seller)].get("earn", 0) + amount))
    return "bal"

# ── metinler ──
T["tr"].update({
  "b_mkt": "🏪 Pazar (dakika başı)", "b_sell": "➕ Kodumu Sat", "b_myl": "📦 İlanlarım", "b_rules": "📜 Kurallar",
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
  "rj_dead": "{n} sunucu çalışmıyor (en fazla 3 olabilir).", "rj_link": "Abonelik linki açılmadı.",
  "m_paid_sent": "🎉 <b>Tebrikler!</b>\n<blockquote>🏪 {title}\n⏱ Alıcı kodunu {dur} kullandı\n💰 Ödemen  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💸 CryptoBot hesabına gönderildi.",
  "m_paid_bal": "🎉 <b>Tebrikler!</b>\n<blockquote>🏪 {title}\n⏱ Alıcı kodunu {dur} kullandı\n💰 Ödemen  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💼 Bot bakiyene eklendi. Profil → 💸 Kazancı Çek.",
  "myl": "📦 <b>İlanlarım</b>", "myl_none": "📦 <b>İlanlarım</b>\n<blockquote>İlanın yok.</blockquote>",
  "myl_item": "<blockquote>{st} <b>{title}</b>\n💲 {p} USDT/dk · 👥 {n} alıcı · 💰 {earned} USDT kazanç</blockquote>",
  "st_pending": "⏳", "st_live": "🟢", "st_removed": "⛔", "st_rejected": "❌",
  "rules": "📜 <b>Pazar kuralları</b>\n<blockquote><b>Satıcı</b>\n• Her ilan 0.1$ (iade edilmez).\n• Abonelik limitsiz olmalı; ekran görüntüsü zorunlu.\n• En az 4 farklı gerçek ülke (bot ölçer, bayraklara bakılmaz).\n• 3'ten fazla sunucu 30 dk çalışmazsa ilan kaldırılır + 3 saat yasak.\n• Gerçek ülke 30 dk 4'ün altına düşerse ilan kaldırılır + 6 saat yasak.\n• Link 30 dk açılmazsa ilan kaldırılır + 3 saat yasak.\n• Kazanç: alıcı durdurunca, uzun kullanımda her 24 saatte bir gönderilir.</blockquote>\n<blockquote><b>Alıcı</b>\n• Her başlatma 0.1$ (iade edilmez).\n• Dakika başı ücret bakiyenden düşer (kullansan da kullanmasan da).\n• İstediğin an durdurursun; bakiye bitince kod durur.\n• Bakiye en az 1$ yüklenir; yüklenen bakiye geri çekilmez.</blockquote>",
  "bal_line": "\n\n💰 <b>Bakiye</b>  {bal} USDT (≈{tmt} TMT)" , "earn_line": "\n💼 <b>Çekilebilir kazanç</b>  {earn} USDT",
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
  "rj_dead": "Не работают {n} серверов (максимум 3).", "rj_link": "Ссылка подписки не открылась.",
  "m_paid_sent": "🎉 <b>Поздравляем!</b>\n<blockquote>🏪 {title}\n⏱ Покупатель использовал ваш код {dur}\n💰 Выплата  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💸 Отправлено на ваш счёт в CryptoBot.",
  "m_paid_bal": "🎉 <b>Поздравляем!</b>\n<blockquote>🏪 {title}\n⏱ Покупатель использовал ваш код {dur}\n💰 Выплата  <b>{usdt} USDT</b> (≈{tmt} TMT)</blockquote>\n💼 Зачислено на ваш баланс в боте. Профиль → 💸 Вывести доход.",
  "myl": "📦 <b>Мои объявления</b>", "myl_none": "📦 <b>Мои объявления</b>\n<blockquote>Объявлений нет.</blockquote>",
  "myl_item": "<blockquote>{st} <b>{title}</b>\n💲 {p} USDT/мин · 👥 {n} покуп. · 💰 {earned} USDT доход</blockquote>",
  "rules": "📜 <b>Правила биржи</b>\n<blockquote><b>Продавец</b>\n• Каждое объявление 0.1$ (не возвращается).\n• Подписка должна быть безлимитной; скриншот обязателен.\n• Минимум 4 разные реальные страны (бот измеряет сам, флаги не учитываются).\n• Если больше 3 серверов не работают 30 мин — снятие + бан 3 ч.\n• Если реальных стран меньше 4 в течение 30 мин — снятие + бан 6 ч.\n• Если ссылка не открывается 30 мин — снятие + бан 3 ч.\n• Выплата: после остановки покупателем, при долгом использовании — каждые 24 ч.</blockquote>\n<blockquote><b>Покупатель</b>\n• Каждый запуск 0.1$ (не возвращается).\n• Поминутная оплата списывается с баланса (пользуетесь или нет).\n• Остановить можно в любой момент; при нулевом балансе код останавливается.\n• Пополнение от 1$; пополненный баланс не выводится.</blockquote>",
  "bal_line": "\n\n💰 <b>Баланс</b>  {bal} USDT (≈{tmt} TMT)", "earn_line": "\n💼 <b>Доход к выводу</b>  {earn} USDT",
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
  "open_line": "\n\n🟢 <b>Açık pazar kodun: {n}</b>\n<i>Dakikada {pm} TMT düşüyor · şimdiye kadar {spent} TMT.\nKullanmıyorsan 🎟 Kodlarım → ⏹ Durdur.</i>",
  "b_open": "🟢 Açık kodlarım ({n})",
  "m_remind": "⏰ <b>Pazar kodun hâlâ açık</b>\n<blockquote>🏪 {title}\n⏱ {dur} · 💸 {spent} TMT\n💰 Bakiye {bal} USDT</blockquote>\n<i>Kullanmıyorsan durdur; yoksa dakika başı para düşmeye devam eder.</i>",
  "chk_el": "\n⌛ Geçen süre: <b>{m} dk</b>",
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
  "open_line": "\n\n🟢 <b>Открытых кодов с биржи: {n}</b>\n<i>Списывается {pm} TMT в минуту · всего {spent} TMT.\nЕсли не пользуетесь: 🎟 Мои коды → ⏹ Стоп.</i>",
  "b_open": "🟢 Открытые коды ({n})",
  "m_remind": "⏰ <b>Код с биржи всё ещё открыт</b>\n<blockquote>🏪 {title}\n⏱ {dur} · 💸 {spent} TMT\n💰 Баланс {bal} USDT</blockquote>\n<i>Если не пользуетесь — остановите, иначе списание каждую минуту продолжится.</i>",
  "chk_el": "\n⌛ Прошло: <b>{m} мин</b>",
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
 "open_line": "\n\n🟢 <b>Açyk bazar kodyň: {n}</b>\n<i>Her minutda {pm} TMT alynýar · şu wagta çenli {spent} TMT.\nUlanmaýan bolsaň 🎟 Kodlarym → ⏹ Yzyna gowşur.</i>",
 "b_open": "🟢 Açyk kodlarym ({n})",
 "m_remind": "⏰ <b>Bazar kodyň henizem açyk</b>\n<blockquote>🏪 {title}\n⏱ {dur} · 💸 {spent} TMT\n💰 Balans {bal} USDT</blockquote>\n<i>Ulanmaýan bolsaň yzyna gowşur, ýogsa her minutda pul alynmagy dowam edýär.</i>",
 "chk_el": "\n⌛ Geçen wagt: <b>{m} min</b>",
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
 "b_sup": "🆘 Goldaw",
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
 "b_sell": "➕ Kodumy sat",
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
 "sell_1": "➕ <b>Kodumy sat · 1/5</b>\n<blockquote>Podpiska linkini iber. <b>Limitsiz</b> bolmaly (trafik we enjam).\nDüzgünler: azyndan 4 dürli hakyky ýurt (bot özi barlaýar, baýdaklara seredilmeýär), iň köp 3 sany işlemeýän serwer.</blockquote>",
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
 "rj_dead": "{n} serwer işlemeýär (iň köp 3 bolup biler).",
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
 "bal_line": "\n\n💰 <b>Balans</b>  {bal} USDT (≈{tmt} TMT)",
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

CHK = {"user": {}, "req": 0, "wait": {}, "qid": 0, "poll": None}   # kullanıcı başına son kontrol, telefona son test isteği, sonucu bekleyenler
CHK_EVERY = 300

def code_label(c):
    if c.lower().startswith("vmess://"):
        try: return json.loads(b64d(c[8:].split("#", 1)[0])).get("ps") or "vmess"
        except Exception: return "vmess"
    return urllib.parse.unquote(c.split("#", 1)[1]) if "#" in c else (code_host(c) or "?")

CHK_FRESH = 300   # son TM testi bundan yeniyse yeniden test istenmez, sonuç hemen gösterilir
CHK_WAIT = 600    # telefon bu kadar sürede sonuç göndermezse son bilinen durum gösterilir
PHONE_OFF = 1800  # telefonun son sonucu bundan eskiyse telefon kapalı sayılır (test istenmez)

def check_text(db, lid, lang, ch=None, state="done", el=0):
    """Kontrol Et kutusu. state: run (test sürüyor) / done (yeni sonuç) / fresh (son test zaten yeni) / timeout."""
    L = db.get("market", {}).get(lid)
    if not L: return tr(lang, "m_gone")
    top = card_head(L, lang) + f"\n\n🏪 <b>{esc(short(L['title'], 40))}</b>\n"
    if state == "run": return top + tr(lang, "chk_run") + (tr(lang, "chk_el", m=el) if el else "")
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
    foot = {"done": tr(lang, "chk_upd", t=datetime.datetime.now(TM_TZ).strftime("%H:%M")), "timeout": tr(lang, "chk_timeout"), "off": tr(lang, "chk_off")}.get(state, "")
    for n in (len(lines), 15, 10, 5):   # foto altı yazı en çok 1024 karakter
        more = f"\n… +{len(lines) - n}" if len(lines) > n else ""
        t = top + tr(lang, "chk_head2", lines="\n".join(lines[:n]) + more or "—", work=w, dead=dd, wait=wt, ago=ago_l((ch or {}).get("ts"), lang)) + foot
        if len(t) <= 1024: return t
    return t[:1020]

def chk_kb(lang, lid):
    return KB([[B(tr(lang, "b_start"), f"u_ms:{lid}", "success"), B(tr(lang, "b_recheck"), f"u_mck:{lid}")], [B(tr(lang, "b_back"), f"u_ml:{lid}")]])

async def edit_box(bot, uid, mid, is_photo, t, kb):
    """Pazar kutusunu yerinde günceller (fotoğraflıysa altındaki yazı)."""
    try:
        if is_photo: await bot.edit_message_caption(chat_id=uid, message_id=mid, caption=t, parse_mode="HTML", reply_markup=kb)
        else: await bot.edit_message_text(t, chat_id=uid, message_id=mid, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        return True
    except BadRequest as e: return "not modified" in str(e).lower()
    except Exception as e: log.info("box edit: %s", e); return False

def request_phone_test(db, lids):
    """Telefona hızlı kontrol isteği: sadece bu ilanların kodları, tekrar denemeden (~30 sn).
    Eski telefon programı hızlı kontrolü bilmiyorsa tam test başlatılır (codes_ts değişir)."""
    ch = _read_channel(db)
    if not ch or not db.get("tm_fid"): return ch, 0
    codes, seen = [], set()
    for lid in lids:
        L = db.get("market", {}).get(lid)
        for c in (listing_codes(db, L) if L else []):
            if code_key(c) not in seen: seen.add(code_key(c)); codes.append(c)
    qid = int(time.time() * 1000)
    ch["quick"] = {"id": qid, "codes": codes[:80]}
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
    rows = [[B(tr(lang, "b_start"), f"u_ms:{lid}", "success"), B(tr(lang, "b_mcheck"), f"u_mck:{lid}")]]
    if n > 1:
        if i == 0: rows.append([B(tr(lang, "b_sellers", n=n - 1), "u_mp:1", "primary")])
        else: rows.append([B("◀️", f"u_mp:{i - 1}"), B(f"{i}/{n - 1}", f"u_mp:{i}"), B("▶️", f"u_mp:{(i + 1) % n}")])
    rows += [[B(tr(lang, "b_sell"), "u_sell", "primary"), B(tr(lang, "b_myl"), "u_myl")],
             [B(tr(lang, "b_top"), "u_top")],
             [B(tr(lang, "b_rules"), "u_mrules"), B(tr(lang, "b_menu"), "u_menu")]]
    return card_photo(L), cap, KB(rows)

OWN_IMG = "own_default"   # bizim ilanın varsayılan fotoğrafı (dosyanın sonunda gömülü)

def card_photo(L):
    return L.get("photo") or (OWN_IMG if L.get("own") else None)

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
            m = await c.bot.send_photo(uid, media, caption=cap, parse_mode="HTML", reply_markup=kb); remember_own(m, h)
        else: await c.bot.send_message(uid, cap, parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
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
                after = fresh and ts > L.get("pushed_ts", 1e18)
                if after and st["tested"] > 0:
                    if len(st["cc"]) >= MIN_COUNTRIES and st["dead"] <= MAX_DEAD:
                        L["status"] = "live"; L["live_ts"] = L["last_good"] = now; events.append(("approved", lid, "", 0))
                    else:
                        L["status"] = "rejected"
                        events.append(("rejected", lid, "rj_lowc" if len(st["cc"]) < MIN_COUNTRIES else "rj_dead", len(st["cc"]) if len(st["cc"]) < MIN_COUNTRIES else st["dead"]))
                elif after and ts != L.get("zero_ts"):   # telefon test etti ama bu ilanın hiçbir kodunu ölçemedi
                    L["zero_ts"] = ts; L["zero_n"] = L.get("zero_n", 0) + 1
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
                L["status"] = "pending"; L["codes_ts"] = now; L.pop("zero_n", None); L.pop("slow_warned", None)
                events.append(("rereview", lid, "", 0))
        own = m[OWN_LID]; own["st"] = listing_stats(db, own, res, exits, ts); own["last_fetch"] = now
        if not own.get("dead_since") and (own["st"]["work"] or not fresh): own["last_good"] = now
        save_db(db)
    return events

def market_push_phone():
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
    now = time.time()
    if sorted(code_key(c) for c in new) != sorted(code_key(c) for c in ch.get("codes", [])):
        ch["codes"], ch["codes_ts"] = new, int(now)
        _tm_write(new_service(), db["tm_fid"], ch)
    def f(d):
        d["mkt_pushed"] = sorted(set(mkeys))
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
        h = hashlib.md5("\n".join(codes).encode()).hexdigest()
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
    ch = await asyncio.to_thread(_read_channel, db)
    qd, ts = ch.get("quick_done") or 0, ch.get("ts") or 0
    for lid in list(CHK["wait"]):
        for uid, (lang, mid, is_photo, qid, t0) in list(CHK["wait"][lid].items()):
            done = qd >= qid or ts > t0
            if done or now - t0 >= CHK_WAIT:
                CHK["wait"][lid].pop(uid, None)
                t = check_text(db, lid, lang, ch, "done" if done else "timeout")
                if not await edit_box(app.bot, uid, mid, is_photo, t, chk_kb(lang, lid)):
                    try: await app.bot.send_message(uid, t, parse_mode="HTML", reply_markup=chk_kb(lang, lid))
                    except Exception: pass
            else:
                el = int((now - t0) // 60)
                if el >= 1 and CHK.setdefault("el", {}).get((uid, mid)) != el:   # dakikada bir "geçen süre"
                    CHK["el"][(uid, mid)] = el
                    await edit_box(app.bot, uid, mid, is_photo, check_text(db, lid, lang, None, "run", el), chk_kb(lang, lid))
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
        async with CHECK_LOCK:   # test kanalına botun kontrolüyle aynı anda yazılmasın
            await asyncio.to_thread(market_push_phone)
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
_OWN_IMG_B64 = "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+Qtp4wWnYNvRrQ4Dn58z1K8eRcr4aX3uOsrt9n8WuJNhpeHt6+ZNR0Ml0lgMNM2kqWvk3u5ZG05GBk57sL520xxl1fp2wVNppaxlTFICIZ6sGWWmz12OJ5+QdkBecIueLhKUryz1WbOSomlqJ5JqiR8s0ji98j3FznOJySSepK40RelkREQERFQREQEREBERAREQEREBFAUoCZUIgtlFVEFkUZRUShUIgIiICIiApUIgIiICIiAiIgIiKhlSoRBKKFOUBERQEREEhSoClUEREQUhQpCAiIiiIiAFKhSgIiICIiAvUtK62tFt4Ian0vVOnF2rpnOga2Iljg4RjJd0GNp6ry1Fi9IvERP5rtJ6qERdEEREBERBxIERcwREQEREEZUqEQSijKlUEREDKIoKglFCIJRQhVEqMoiCVA6oiB0REQEREBERAREQEREDKlQiCUUKcqgiIgIiICIiAiIgIiICIiAiIgIiKgpyoRBKKFOUEooVlAREQECIFRKIiIIiIJCKFKKIiICIiAiIgIiICIiAiIqOJERcwREQEREEIoTvQEREE5TOVChBYooypzyVBERAREUBERAREQERFQREQEREBERAREQERFuuO1u0AiItfDiPmtH8/wCQKVCJrHHmRKKEym8ftIlERN09pURMplNU9wRT9yclOSJ7SIRMIpNZjuCIiygiIgIiICIiArZVVKolSqqcoJRQpUEoiICIioBSoClEEREBERARERRERAREQEREHEiIsAiIgIiIKlQrOVUBERAREQEREBTlQiCyKqnKolFClAREUBERAREQERFQREXWuKZjmt0gERFeelflj+P+3/2CIixa9rfNIIiLAIiICIiAmURBKKEyqJRMogKcqEVi0x2VPL3IQoRXcT3BFPI9UISa+xpCIiygiIgIiIJREQFIUIqL5RQiCUUZUqAFKhSEBERUEREQREQEREBERFEREHEiIsAiIgIiIIcqqzuiqgIiICIiAiIgIiICIiApyoRBKlVUoJRRlSqCIoVrSbTqolERdd1xdus/p/UERFytabTuQREUBERARdinoqmo+qhe4eOOSyUGn53c5pGMHgOZXSuK9u0G2FRbRFp+mb9ZJI8/BdqO00MfSAO/WOV2jhLz3TbTVC3ttJTN+jTxD+auQQxDpFH/AEQt/c59zmaApW/GKI9Y2H+aFR1JTO+lBGf5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KrFp+Ke1W1sYcLlJNGagZ+jFK4tZy8tuf5ycxtr1HR1NbKY6OnmnkAyWxsLiB9ypUQS08zoqiJ8UrfpMe0tI+4rZIqy3djc7ayae30stX2kFRGC8FrctDX45kd/LvK5HW6erraGK6zx1NBBSSTR1NO7LpomZO3ceec8ufRNm2pos+KSju1smqKGl9CqIJoo3MErnse2Q7QefMEH4qbs2zUtRcLd6LLG6nD446sSFznyN9pvTaTnp0V2MLVU01JI2OpjdG9zGvAPe1wyD94XCt41JbYoaVt2rI3TsdS08MMTHYAcYx67yOYHI4HeV0rRbaCottI6KiNxkeHeldlUbZ4TnkGR558sHPPKnMbaormOQRNlLHCNxLQ/HIkdQD94UOb+Uc1gceeACOZ58uXistqMinmpraw5bQxCN+O+U+tIficfzVR1aaz3KqibLTW+rlicMteyJxBHkVw1NDV0szIqmlnilfzax8ZDnd3Id6zOjJpRcpmCWTYKOow3ecD8me5RpeaVoutZ2j3VVLQPfC9ziSxxc1uRnvAJU2MRWW+sodvplJPTh/wBHtYy3PxXK+z3KOIyvt9Y2MDJcYXYx45wrRXGrFuraQ7p6eba5/abndmQeTwe492fNbbeWOp9WCsdfKekijML3R9s8yABjcjYBzz4eaTMwNCRdq6TRVNzq56ePs4ZJXPYzptaTkBdVaBERFEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREF4ZHwyslieWSMcHNc04II6FZip1NXTwzsDKSGSobtmmhgDJJAeoLh49+OqwiKaRlbdfKmipPReypammD+0ZHUwiQMd3lvgpp9QV8N5fdd8clY4EbpIw4AEY5Du5cgsSiagZeov0s8EkTqG1ND2lpcyja1wz3g9x811K241FY+ldOWZpomwx7W49VvTPiV00TQyXz1WfP3zxmP03tO1zs9XdjHRWoL5VUkEsBZT1FNJIZTDURB7A/2gO4rFomh27pcai51InqnNLmtDGNY0Naxo6NaB0C6T/oO9ysqyfVu9ysDrooUrojhRSoXMd2H6pnuV1SH6pnuV0URERRERAREQEREHetdyfQduwxRVFNUNDJoJc7XgHI5jmCD0IXbffdjaaKiooKWmgqG1Jja5zjI9vQuceeMcsBYZFNIyLbrI2S6u7Jh+cWOY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IAA6DkFxXOvFbTW6IRlhpKcQEk53esTny6pobZcZq+OltIpL7T0EfoEJ7F9QWHODzwAeq69nddJtKyPttUY6p9xJkkM7Yy8GPxcRnmsXU3S1VsVH6bQ1xlp6dlPmKoa1rg3vwWnxXSnuEL7K63RQPaz0s1DXPcCQ3btDTy6+amhtjDjU1LFUujfc4rdUMrXsAwZOzfgHHIuDcZKwOkS+giq7y2IyPpGNjhbt3Zlfy6eTQ4qYtQsFbS1k1M99UykkpZnh4Ha5YWtd06gEZ8cLqxXyopLRS0VuknpDG58k0kcmDK44A6dwAxhNSK6nom0V5mbC0immAnhyMeo8ZA+7JH3K9i/gtNX3M9YI+xh/lZMgH7m7j8FxXS7PudDRMq+0krKfe01D35L2E5APfkHPPzVKuriNpoqKn3YYXzTkjG6R3IY8QGgD7yr4HWoqypoZu1op5IJcbd7Dg48FserLvcTT26I11R2U9ujdK3fyeTnJPvWqrv3evFeKINjMfo9KynOTncW55/irMdR3tZf4Spf9hpv6gXetNW+WyUlLZ7nFbq6J7zNG9/ZekEn1SH9DgctpXUrbraK98ElZQ13bRwRwkx1DGtOxuM4LSuvHX22ejgguNDMXQAtZLTSNY57Sc4eCCCR49VPA4dROndd5zWUjaSp9USxtGAXYGXeHPry5c1jV373cTc68z9kImNYyKOMHdtY0YAJ7zjvXQVgERFVEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAREQEREBERAVJvqX+5XVJvqX+5EdBQpRaZSiEouau9D9Uz3K6rA1xhYQ09FybHeyVVVRW2O9kpsd7JVVVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx3slBVFbY72Smx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"

if __name__ == "__main__":
    main()
