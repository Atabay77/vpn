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
DEFAULT_DB = {"subs": {}, "template": [], "sources": [], "free_files": [], "sub_admins": {}, "seen_ips": []}
AUTO_ANN = {0: "🌙 Спокойной ночи — мы на связи", 6: "☕ Доброе утро! Всё уже работает", 8: "🛡 Мы следим за серверами круглосуточно"}   # saat (Aşkabat): duyuru
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

def left_txt(exp):
    if not exp: return "∞"
    d = float(exp) - time.time()
    if d <= 0: return "bitti"
    return f"{int(d // 86400)}g {int(d % 86400 // 3600)}s"

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

def sa_limit(db, uid):
    try: return int(db.get("sub_admins", {}).get(str(uid), {}).get("limit", SUB_LIMIT))
    except Exception: return SUB_LIMIT

def owned(db, uid): return sum(1 for v in db["subs"].values() if v.get("owner_id") == uid)

def create_vip(name, owner=None, days=None):
    svc = new_service()
    if not svc: return None, "drive-sa.json bulunamadı"
    with db_lock():
        db = load_db()
        if owner is not None and owner not in ADMINS and owned(db, owner) >= sa_limit(db, owner):
            return None, f"Limit doldu ({sa_limit(db, owner)} kod). Yer açmak için birini sil."
        used = {v.get("file_id") for v in db["subs"].values() if v.get("file_id")} | {db.get("tm_fid")} | source_fids(db)
        fid, from_free = None, False
        for f in db["free_files"]:
            if f not in used: fid, from_free = f, True; break
        if not fid: fid = find_free_file(svc, used)
        if not fid: return None, "Boş Drive dosyası yok!"
        if not sync_file(svc, fid, name, db.get("g_announce", ""), db["template"], exp=False):
            return None, "Drive'a yazılamadı (loglara bak)"
        if from_free: db["free_files"].remove(fid)
        kid = "vip_" + uuid.uuid4().hex[:8]
        db["subs"][kid] = {"name": name, "title": name, "file_id": fid, "announce": "", "owner_id": owner}
        if days: db["subs"][kid]["expires"] = time.time() + int(days) * 86400
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
        except Exception as e: return i, [], str(e)[:80], time.time() - t

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
        for f in [DB_FILE, SA_FILE, ENV_FILE, VIP_LOG, AUDIT_LOG, GEO_FILE, "/root/sohbet.txt", os.path.abspath(__file__)]:
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
            for fid, nm, owner in hit:
                audit(0, f"expired {nm}")
                await notify_founders(app, f"⏳ Kodun süresi doldu, kapatıldı: <code>{esc(nm)}</code>")
                if owner and owner not in ADMINS:
                    try: await app.bot.send_message(chat_id=owner, text=f"⏳ Kodunun süresi doldu: {nm}")
                    except Exception: pass
            for sid, nm in warn:
                await notify_founders(app, f"⏳ <b>Alt admin süresi bitiyor</b>\n<blockquote>👮 {esc(nm)} <code>{sid}</code>\n24 saatten az kaldı.</blockquote>",
                                      KB([[B("⏳ Uzat", f"sa_ext:{sid}", "primary")]]))
                try: await app.bot.send_message(chat_id=int(sid), text="⏳ Alt admin yetkinin bitmesine 24 saatten az kaldı.")
                except Exception: pass
            for sid, nm in ended:
                audit(0, f"sa_ended {sid}")
                await notify_founders(app, f"🔒 <b>Alt admin yetkileri alındı</b>\n<blockquote>👮 {esc(nm)} <code>{sid}</code>\nSüresi doldu. Oluşturduğu kodlar çalışmaya devam ediyor.</blockquote>",
                                      KB([[B("⏳ Uzat", f"sa_ext:{sid}", "success")]]))
                try: await app.bot.send_message(chat_id=int(sid), text="🔒 Alt admin yetkinin süresi doldu.")
                except Exception: pass
        except Exception: log.exception("watchdog expiry")
        # AUTO_ANN saatlerinde (Aşkabat) otomatik genel duyuru; bot o saatte kapalıysa açılınca yazar
        try:
            now = datetime.datetime.now(TM_TZ)
            past = [h for h in sorted(AUTO_ANN) if h <= now.hour]
            h, day = (past[-1], now.date()) if past else (max(AUTO_ANN), now.date() - datetime.timedelta(days=1))
            slot = f"{day:%Y-%m-%d} {h}"
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
        return ("✦ <b>VIP PANEL</b> ✦\n"
                f"<blockquote>🎟 Kodların  <b>{len(mine)}/{sa_limit(db, uid) if db else SUB_LIMIT}</b>\n"
                f"⏳ Yetki süresi  <b>{left_txt(e.get('expires'))}</b></blockquote>\n"
                "<i>Bir işlem seç</i> 👇")
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
            f"📡 <b>{n}</b> kod  ·  🔗 <b>{src}</b> abonelik  ·  👥 <b>{vip}</b> VIP")

def main_kb(uid):
    rows = [[B("✨ Kod Oluştur", "create_key", "success"), B("👥 Kodlarım", "my_keys", "primary")]]
    if uid in ADMINS:
        on = not os.path.exists(STOP_FLAG)
        rows += [[B("🔗 Abonelikler", "sources"), B("📜 Loglar", "logs")],
                 [B("📢 Toplu Duyuru", "bulk_ann"), B("🏷 Toplu Başlık", "bulk_title")],
                 [B("🛑 Durdur", "toggle_sys", "danger") if on else B("▶️ Başlat", "toggle_sys", "success"), B("⚙️ Admin", "admin")]]
    return KB(rows)

def admin_kb():
    try: on = load_db().get("auto_ann_on", True)
    except Exception: on = True
    return KB([
        [B("⚡ Şimdi Güncelle", "upd_now", "primary"), B("📦 Yedek", "get_zip")],
        [B(f"🕰 Oto. Duyuru: {'Açık' if on else 'Kapalı'}", "auto_ann", "success" if on else "danger")],
        [B("♻️ Önceki Sürüme Dön", "rollback")],
        [B("👮 Alt Adminler", "sa_menu")],
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

LOG_KB = KB([[B("🔄 Yenile", "logs", "primary"), B("◀️ Menü", "menu")]])

def code_card(s, kid, uid):
    fid = s.get("file_id", "")
    own = s.get("announce") or ""
    try: g = load_db().get("g_announce", "")
    except Exception: g = ""
    return (f"🎟 <b>{esc(short(btn_name(s, kid), 40))}</b>\n"
            f"<blockquote>🏷 Başlık  <code>{esc(name_of(s, kid))}</code>\n"
            f"📢 Duyuru  {('<i>' + esc(short(own, 120)) + '</i>  <code>özel</code>') if own else (('<i>' + esc(short(g, 120)) + '</i>  <code>genel</code>') if g else '—')}\n"
            f"⏳ Süre  <b>{left_txt(s.get('expires'))}</b>"
            + (f"\n👮 Sahibi  <code>{s.get('owner_id')}</code>" if uid in ADMINS and s.get("owner_id") and s.get("owner_id") not in ADMINS else "")
            + "</blockquote>\n"
            f"🔗 <b>Abonelik linki</b> <i>(dokun → kopyala)</i>\n<code>{esc(sub_link(fid) if fid else 'Drive dosyası yok')}</code>")

def code_kb(kid, uid):
    rows = [[B("🏷 Başlık", f"kt:{kid}"), B("🔘 Buton Adı", f"kn:{kid}")],
            [B("📢 Duyuru", f"ka:{kid}")] + ([B("⏳ Süre", f"kx:{kid}")] if uid in ADMINS else []),
            [B("🗑 Sil", f"kd:{kid}", "danger")],
            [B("◀️ Kodlarım", "my_keys")]]
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

def prompt(title, text, cancel_to):
    return f"{title}\n<blockquote>{text}</blockquote>", back(cancel_to, "✖️ İptal")

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
    STATE[uid] = {"action": "num", "what": what, **ctx}
    btns = [B(f"{v}{unit}", f"num:{v}", "primary" if v == vals[2] else None) for v in vals]
    rows = [btns[:3], btns[3:]]
    if what == "nk_days" and uid in ADMINS: rows.append([B("♾ Süresiz", "num:0", "success")])
    rows.append([B("✖️ İptal", "sa_menu" if what.startswith("sa_") else "menu")])
    return f"{title}\n<blockquote>{info}{q}\n<i>Butona bas ya da sayı yaz.</i></blockquote>", KB(rows)

def create_result(res, err, name):
    if not res: return f"⚠️ {esc(err)}", back("menu", "◀️ Menü")
    kid, fid = res
    return (f"✅ <b>Kod oluşturuldu!</b>\n<blockquote>🎟 <b>{esc(name)}</b>\n⏳ Süre  <b>{left_txt(load_db()['subs'].get(kid, {}).get('expires'))}</b></blockquote>\n"
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
        await send(*ask_num(uid, what, f"⚠️ {lo} ile {hi} arasında bir sayı.\n", **ctx)); return
    if what == "nk_days":
        res, err = await asyncio.to_thread(create_vip, st["name"], uid, n or None)
        if res: audit(uid, f"create {res[0]} {st['name']} {n or '∞'}g")
        await send(*create_result(res, err, st["name"]))
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
            try: await c.bot.send_message(chat_id=int(sid), text=f"✅ Alt admin yetkin {n} gün uzatıldı.")
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
    if not is_admin(uid):
        await u.message.reply_text(f"⛔ Erişim yok.\nID: {uid}")
        return
    STATE.pop(uid, None)
    if uid not in ADMINS:
        nm = u.effective_user.full_name or ""
        mutate(lambda d: d["sub_admins"].get(str(uid), {}).__setitem__("name", nm) if d["sub_admins"].get(str(uid), {}).get("name") != nm else None)
    await u.message.reply_text(menu_text(uid), parse_mode="HTML", reply_markup=main_kb(uid))

async def cmd_id(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(f"ID: {u.effective_user.id}")

async def msg_handler(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    if not is_admin(uid) or uid not in STATE: return
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
                await u.message.reply_text("⚠️ Sadece sayı yaz (ör. 7).")
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
                await u.message.reply_text("⚠️ Kod bulunamadı.", reply_markup=back("my_keys"))
                return
            if act == "bname":
                msg = "✅ Buton adı değişti. <i>(Abonelik başlığına dokunulmadı.)</i>"
            else:
                ok = await asyncio.to_thread(lambda: sync_file(new_service(), *r))
                msg = "✅ Kaydedildi ve Drive'a yazıldı." if ok else "⚠️ Kaydedildi ama Drive'a yazılamadı."
            await u.message.reply_text(msg, parse_mode="HTML", reply_markup=KB([[B("🎟 Koda Dön", f"kv:{kid}", "primary")]]))
    except Exception as e:
        log.exception("msg_handler")
        await u.message.reply_text(f"❌ Hata: {esc(str(e)[:300])}", parse_mode="HTML", reply_markup=back("menu", "◀️ Menü"))

FOUNDER_ONLY = {"rollback", "rollback_yes", "auto_ann", "toggle_sys", "admin", "sources", "s_add", "logs", "upd_now", "get_zip", "sa_menu", "sa_add", "bulk_ann", "bulk_title", "bulk_yes"}
OWNED = ("kv", "kt", "kn", "ka", "kd", "kdy")   # alt admin sadece kendi kodunda
def src_find(db, h): return next((s for s in db["sources"] if hashlib.md5(s.encode()).hexdigest()[:8] == h), None)

async def cb(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    uid = q.from_user.id
    if not is_admin(uid):
        await q.answer("⛔ Erişim yok", show_alert=True); return
    a = q.data
    if uid not in ADMINS and (a in FOUNDER_ONLY or a.startswith(("sv:", "se:", "sd:", "sa_del:", "sa_ext:", "sa_lim:", "kx:", "kxs:"))):
        await q.answer("⛔ Sadece kurucu", show_alert=True); return
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
            await safe_edit(q, "⛔ Bu kod senin değil.", back("my_keys")); return

    if a == "menu":
        STATE.pop(uid, None)
        await safe_edit(q, menu_text(uid), main_kb(uid))

    elif a.startswith("num:"):
        st = STATE.pop(uid, None)
        if not st or st.get("action") != "num":
            await safe_edit(q, "⚠️ Süre geçti, baştan başla.", back("menu", "◀️ Menü")); return
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
        await safe_edit(q, menu_text(uid), main_kb(uid))

    elif a == "admin":
        await safe_edit(q, "⚙️ <b>Admin</b>\n"
                        f"<blockquote>🔍 Kontrol her <b>{CHECK_EVERY // 60} dk</b>\n"
                        f"🚨 <b>{NEW_IP_LIMIT}</b>'ten fazla yeni IP → bütün kodlar yenilenir\n"
                        "📱 TM'de çalışmayan kodlar telefon testine göre çıkarılır\n"
                        "🕰 Otomatik duyuru (Aşkabat saati):\n" + "\n".join(f"   {h:02d}:00  {esc(t)}" for h, t in sorted(AUTO_ANN.items())) + "</blockquote>", admin_kb())

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
                        KB([[B("📜 Loglar", "logs", "primary"), B("◀️ Menü", "menu")]]))
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
                           "<code>-</code> gönderirsen her kodun başlığı kendi buton adı olur.\n<i>Buton adları değişmez.</i>", "menu")
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
        rows.append([B("✨ Yeni Kod", "create_key", "success"), B("◀️ Menü", "menu")])
        expd = sum(1 for _, v in items if is_exp(v))
        await safe_edit(q, f"👥 <b>Kodlarım</b>  <code>{len(items)}</code>\n"
                        f"<blockquote>Yönetmek için bir koda dokun." + (f"\n🔴 = süresi dolmuş ({expd})" if expd else "") + "</blockquote>", KB(rows))

    elif a.startswith("kv:"):
        kid = a.split(":", 1)[1]
        s = db["subs"].get(kid)
        if not s:
            await safe_edit(q, "⚠️ Kod bulunamadı.", back("my_keys")); return
        await safe_edit(q, code_card(s, kid, uid), code_kb(kid, uid))

    elif a.startswith(("kt:", "kn:", "ka:")):
        kind, kid = a.split(":", 1)
        s = db["subs"].get(kid, {})
        act = {"kt": "title", "kn": "bname", "ka": "announce"}[kind]
        STATE[uid] = {"action": act, "kid": kid}
        texts = {"title": ("🏷 <b>Abonelik Başlığı</b>", f"Şu an: <code>{esc(name_of(s, kid))}</code>\nYeni başlığı gönder (VPN uygulamasında görünür, emoji olur: <code>VIP 🇹🇲</code>)."),
                 "bname": ("🔘 <b>Buton Adı</b>", f"Şu an: <code>{esc(btn_name(s, kid))}</code>\nYeni adı gönder. <i>Sadece bu botta görünür, abonelik başlığı değişmez.</i>"),
                 "announce": ("📢 <b>Duyuru</b>", f"Şu an: {('<i>' + esc(short(s.get('announce'), 100)) + '</i>') if s.get('announce') else '—'}\nBu koda özel duyuruyu gönder. Silmek için <code>-</code> (o zaman genel duyuru görünür).")}
        t, kb = prompt(*texts[act], f"kv:{kid}")
        await safe_edit(q, t, kb)

    elif a.startswith("kd:"):
        kid = a.split(":", 1)[1]
        s = db["subs"].get(kid, {})
        await safe_edit(q, f"🗑 <b>Bu kod silinsin mi?</b>\n<blockquote>🎟 <b>{esc(short(btn_name(s, kid), 40))}</b>\nEski abonelik linki boşalır.</blockquote>",
                        KB([[B("🗑 Evet, sil", f"kdy:{kid}", "danger"), B("✖️ Vazgeç", f"kv:{kid}")]]))

    elif a.startswith("kdy:"):
        kid = a.split(":", 1)[1]
        nm = btn_name(db["subs"].get(kid, {}), kid)
        ok = await asyncio.to_thread(delete_vip, kid)
        if ok: audit(uid, f"delete {kid} {nm}")
        if ok and uid not in ADMINS:
            await notify_founders(c.application, f"🔔 Alt admin <b>{esc(q.from_user.full_name)}</b> (<code>{uid}</code>) kod sildi: <code>{esc(nm)}</code>")
        await safe_edit(q, "✅ Kod silindi." if ok else "⚠️ Kod bulunamadı.", back("my_keys", "◀️ Kodlarım"))

    elif a == "create_key":
        if uid not in ADMINS and owned(db, uid) >= sa_limit(db, uid):
            await safe_edit(q, f"⛔ <b>Limit doldu</b>\n<blockquote>En fazla {sa_limit(db, uid)} kod. Yer açmak için birini sil.</blockquote>", back("my_keys", "👥 Kodlarım")); return
        STATE[uid] = {"action": "new_key"}
        t, kb = prompt("✨ <b>Kod Oluştur</b>", "Kod için bir isim gönder.\n<i>Hem buton adı hem abonelik başlığı olur; sonra ayrı ayrı değiştirebilirsin. Ardından süre sorulacak.</i>", "menu")
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
        rows.append([B("◀️ Menü", "menu")])
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
    if isinstance(context.error, NetworkError) or time.time() - _ERR["t"] < 600: return
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
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("id", cmd_id))
    app.add_handler(CallbackQueryHandler(cb))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, msg_handler))
    app.add_handler(MessageHandler(filters.Document.ALL, doc_handler))
    app.add_error_handler(on_error)
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
