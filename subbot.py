import os, sys, io, re, json, html, uuid, base64, asyncio, zipfile, shutil, fcntl, logging, datetime, time, socket, random, hashlib, warnings
import urllib.request, urllib.parse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from telegram import Update, InlineKeyboardButton as B, InlineKeyboardMarkup as KB
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
BACKUP_DIR = "/root/backups"
LINE = "──────────────"
PAGE = 16
CHECK_EVERY = 120      # saniye: iki kontrol arası bekleme
NEW_IP_LIMIT = 3       # bundan FAZLA yeni IP görülürse kodlar yenilenir
SUB_LIMIT = 10
SUB_DAYS = 7
DEFAULT_DB = {"subs": {}, "template": [], "sources": [], "free_files": [], "sub_admins": {}, "seen_ips": []}
STATE = {}
LIVE = {}
RUN = {"last_check": 0.0, "last_msg": "", "next": 0.0}


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

def name_of(s, kid): return s.get("title") or s.get("name") or kid

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
    creds = service_account.Credentials.from_service_account_file(SA_FILE)
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
        svc.files().update(fileId=fid, body={"name": f"{clean}.txt"}, media_body=media).execute()
        return True
    except Exception as e:
        log.warning("Drive write failed %s: %s", fid, e)
        return False

def push_all(items, servers):
    """items: [(fid, title, announce)] -> (ok, failed_titles). Paralel yazar."""
    def one(it):
        fid, title, ann = it
        try: return title, sync_file(new_service(), fid, title, ann, servers, exp=False)
        except Exception: return title, False
    ok, bad = 0, []
    with ThreadPoolExecutor(5) as ex:
        for title, good in ex.map(one, items):
            if good: ok += 1
            else: bad.append(title)
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

def create_vip(name, owner=None):
    svc = new_service()
    if not svc: return None, "drive-sa.json bulunamadı"
    with db_lock():
        db = load_db()
        if owner is not None and owner not in ADMINS and sum(1 for v in db["subs"].values() if v.get("owner_id") == owner) >= SUB_LIMIT:
            return None, f"Limit doldu ({SUB_LIMIT} kod). Yer açmak için birini sil."
        used = {v.get("file_id") for v in db["subs"].values() if v.get("file_id")}
        fid, from_free = None, False
        for f in db["free_files"]:
            if f not in used: fid, from_free = f, True; break
        if not fid: fid = find_free_file(svc, used)
        if not fid: return None, "Boş Drive dosyası yok!"
        if not sync_file(svc, fid, name, "", db["template"], exp=False):
            return None, "Drive'a yazılamadı (loglara bak)"
        if from_free: db["free_files"].remove(fid)
        kid = "vip_" + uuid.uuid4().hex[:8]
        db["subs"][kid] = {"name": name, "title": name, "file_id": fid, "announce": "", "owner_id": owner}
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

def code_host(link):
    try:
        raw = link.split("#", 1)[0].strip()
        proto, body = raw.split("://", 1)
        proto = proto.lower()
        if proto == "vmess":
            return str(json.loads(b64d(body))["add"]).strip("[]")
        if proto == "ss" and "@" not in body:
            body = b64d(body.split("?")[0].split("/")[0])
        hp = re.split(r"[/?]", body.rsplit("@", 1)[1] if "@" in body else body)[0]
        return hp.rsplit(":", 1)[0].strip("[]") or None
    except Exception:
        return None

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

def rename_all(codes, geo):
    """Rus IP -> her zaman 🇷🇺. Diğerleri -> rastgele bayrak (mümkün olduğunca tekrar etmeden). İsim her seferinde rastgele."""
    others = [c for c in COUNTRIES if c != "ru"]
    bag, used, out = [], set(), []
    for link in codes:
        if geo.get(code_host(link)) == "ru": cc = "ru"
        else:
            if not bag: bag = random.sample(others, len(others))
            cc = bag.pop()
        flag, cname, names = COUNTRIES[cc]
        free = [n for n in names if (cc, n) not in used] or names
        n = random.choice(free); used.add((cc, n))
        out.append(set_name(link, f"{flag} {cname} | {n}"))
    return out


# ───────── KONTROL DÖNGÜSÜ ─────────
def check_cycle(force=False):
    """Bloklayan iş (thread'de çalışır). Güncelleme olursa sonuç dict döner, olmazsa None."""
    db = load_db()
    sources = list(db["sources"])
    RUN["last_check"] = time.time()
    if not sources:
        RUN["last_msg"] = "⚠️ Abonelik eklenmemiş"
        vlog("⚠️ Abonelik eklenmemiş. Admin → Abonelikler'den ekle.")
        return {"error": "Abonelik eklenmemiş."} if force else None
    vlog(f"🔍 Kontrol ediliyor ({len(sources)} abonelik)...")

    def one(i_url):
        i, url = i_url
        t = time.time()
        try: return i, fetch_codes(url), None, time.time() - t
        except Exception as e: return i, [], str(e)[:80], time.time() - t

    codes, keys = [], set()
    with ThreadPoolExecutor(max(1, min(8, len(sources)))) as ex:
        res = list(ex.map(one, enumerate(sources, 1)))
    for i, got, err, dt in res:
        if err: vlog(f"❌ Abonelik {i}: başarısız ({err})")
        else: vlog(f"✅ Abonelik {i}: {len(got)} kod ({dt:.1f} sn)")
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
    if not force and old and len(new) <= NEW_IP_LIMIT:
        RUN["last_msg"] = f"✅ {len(codes)} kod, {len(new)} yeni IP → değişiklik yok"
        vlog(f"ℹ️ {len(codes)} kod · {len(new)} yeni IP (eşik: {NEW_IP_LIMIT}'ten fazla) → değişiklik yok")
        return None

    vlog(("⚡ Elle güncelleme" if force else f"🚨 {len(new)} yeni IP bulundu") + f" → {len(codes)} kod yenileniyor...")
    geo = geo_lookup(list(ips))
    miss = [h for h in ips if h not in geo]
    if miss: vlog(f"⚠️ Ülkesi bulunamadı: {', '.join(miss[:5])}")
    renamed = rename_all(codes, geo)
    targets = [(s["file_id"], name_of(s, k), s.get("announce", "")) for k, s in db["subs"].items() if s.get("file_id") and not is_exp(s)]
    ok, bad = push_all(targets, renamed)
    vlog(f"{'✅' if not bad else '⚠️'} Drive: {ok}/{len(targets)} güncellendi" + (f" · başarısız: {', '.join(bad[:5])}" if bad else ""))

    def f(d):
        d["template"] = renamed
        d["last_update"] = time.time()
        if not bad: d["seen_ips"] = sorted(ips)   # hata varsa eski IP'ler kalsın, sonraki turda tekrar dener
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
        head = (f"🔄 <b>Kodlar güncellendi</b>{' (elle)' if r['force'] else ''}\n{LINE}\n"
                f"🆕 Yeni IP: {r['new']} · 📡 Kod: {len(r['codes'])}\n"
                f"💾 Drive: {r['ok']}/{r['total']} {'✅' if not r['bad'] else '⚠️'}")
        if r["bad"]: head += "\n❌ Başarısız: " + esc(", ".join(r["bad"][:10]))
        await notify_founders(app, head)
        chunk = ""
        for c in r["codes"]:
            item = f"<code>{esc(c)}</code>\n\n"
            if len(chunk) + len(item) > 3800:
                await notify_founders(app, chunk); chunk = ""
            chunk += item
        if chunk: await notify_founders(app, chunk)
    return r

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
                    hit, warn = [], []
                    for kid, s in db["subs"].items():
                        if is_exp(s) and not s.get("exp_done"):
                            s["exp_done"] = True
                            hit.append((s.get("file_id"), name_of(s, kid), s.get("owner_id")))
                    for sid, e in db.get("sub_admins", {}).items():
                        if 0 < float(e.get("expires", 0)) - time.time() < 86400 and not e.get("warned"):
                            e["warned"] = True; warn.append(sid)
                    return hit, warn
                hit, warn = mutate(f)
                if hit:
                    svc = new_service()
                    for fid, nm, _ in hit: sync_file(svc, fid, nm, "", [], exp=True)
                return hit, warn
            hit, warn = await asyncio.to_thread(job)
            for fid, nm, owner in hit:
                audit(0, f"expired {nm}")
                await notify_founders(app, f"⏳ Kodun süresi doldu, kapatıldı: <code>{esc(nm)}</code>")
                if owner and owner not in ADMINS:
                    try: await app.bot.send_message(chat_id=owner, text=f"⏳ Kodunun süresi doldu: {nm}")
                    except Exception: pass
            for sid in warn:
                await notify_founders(app, f"👮 Alt admin <code>{sid}</code> 24 saatten az kaldı.")
        except Exception: log.exception("watchdog expiry")
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

async def post_init(app):
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
    if uid not in ADMINS:
        return f"🏠 <b>VIP PANEL</b>\n{LINE}\nBir işlem seç:"
    try: db = load_db(); n, src, vip = len(db["template"]), len(db["sources"]), len(db["subs"]); lu = db.get("last_update")
    except Exception: n = src = vip = "?"; lu = None
    on = not os.path.exists(STOP_FLAG)
    return (f"🏠 <b>VPN PANEL</b>\n{LINE}\n"
            f"⚙️ Sistem: {'🟢 Çalışıyor' if on else '🔴 Durduruldu'}\n"
            f"🔍 Son kontrol: {ago(RUN['last_check'])}\n"
            f"🔄 Son güncelleme: {ago(lu)}\n"
            f"📡 Kod: {n} · 🔗 Abonelik: {src} · 👥 VIP: {vip}\n{LINE}")

def main_kb(uid):
    rows = [[B("✨ Kod Oluştur", callback_data="create_key"), B("👥 Kodlarım", callback_data="my_keys")]]
    if uid in ADMINS:
        on = not os.path.exists(STOP_FLAG)
        rows.append([B("🛑 Durdur" if on else "▶️ Başlat", callback_data="toggle_sys"), B("⚙️ Admin", callback_data="admin")])
    return KB(rows)

def admin_kb():
    return KB([
        [B("🔗 Abonelikler", callback_data="sources"), B("📜 Canlı Log", callback_data="logs")],
        [B("⚡ Şimdi Güncelle", callback_data="upd_now"), B("📦 Yedek", callback_data="get_zip")],
        [B("👮 Alt Adminler", callback_data="sa_menu")],
        [B("◀️ Menü", callback_data="menu")]])

def log_text():
    on = not os.path.exists(STOP_FLAG)
    nxt = int(RUN["next"] - time.time()) if on and RUN["next"] else None
    st = "🟢 Çalışıyor" + (f" · sonraki kontrol {max(0, nxt)} sn" if nxt is not None else "") if on else "🔴 Durduruldu"
    lines = [short(l, 60) for l in tail(VIP_LOG, 22)]
    body = ("<pre>" + esc("\n".join(lines)) + "</pre>") if lines else "Log yok."
    return f"📜 <b>Canlı Log</b>\n{LINE}\n{st}\n{esc(RUN['last_msg'])}\n{body}\n<i>Güncellendi: {datetime.datetime.now():%H:%M:%S}</i>"

LOG_KB = KB([[B("🔄 Yenile", callback_data="logs"), B("◀️ Admin", callback_data="admin")]])

async def live_log(q, uid):
    """Log mesajını 5 dakika boyunca her 5 saniyede bir yeniler."""
    last = ""
    try:
        for _ in range(60):
            await asyncio.sleep(5)
            t = log_text()
            if t.split("<i>")[0] != last.split("<i>")[0]:
                last = t
                await safe_edit(q, t, LOG_KB)
    except asyncio.CancelledError: pass
    except Exception: pass

async def safe_edit(q, text, kb=None):
    try:
        await q.edit_message_text(text[:4000], parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
    except BadRequest as e:
        if "not modified" not in str(e).lower(): log.warning("edit: %s", e)

async def notify_founders(app, text):
    for fid in ADMINS:
        try: await app.bot.send_message(chat_id=fid, text=text, parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e: log.warning("notify: %s", e)


# ───────── HANDLERS ─────────
async def start(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    if not is_admin(uid):
        await u.message.reply_text(f"⛔ Erişim yok.\nID: {uid}")
        return
    STATE.pop(uid, None)
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
            m = await u.message.reply_text("⏳ Drive dosyası atanıyor...")
            res, err = await asyncio.to_thread(create_vip, name, uid)
            if res:
                kid, fid = res
                audit(uid, f"create {kid} {name}")
                out = (f"✅ <b>Kod oluşturuldu!</b>\n{LINE}\n👤 <code>{esc(name)}</code>\n\n"
                       f"🔗 Abonelik linki\n<code>{esc(sub_link(fid))}</code>")
            else:
                out = f"⚠️ {esc(err)}"
            await m.edit_text(out, parse_mode="HTML", reply_markup=back("menu", "◀️ Menü"), disable_web_page_preview=True)
            if res and uid not in ADMINS:
                await notify_founders(c.application, f"🔔 Alt admin <b>{esc(u.effective_user.full_name)}</b> (<code>{uid}</code>) kod oluşturdu: <code>{esc(name)}</code>")

        elif act == "sa_add":
            if not txt.isdigit():
                await u.message.reply_text("⚠️ Sayısal Telegram ID gönder.", reply_markup=back("sa_menu"))
                return
            nid = int(txt)
            if nid in ADMINS:
                await u.message.reply_text("ℹ️ Bu ID zaten kurucu.", reply_markup=back("sa_menu"))
                return
            exp = time.time() + SUB_DAYS * 86400
            mutate(lambda d: d.setdefault("sub_admins", {}).__setitem__(str(nid), {"expires": exp, "added": time.time()}))
            audit(uid, f"sa_add {nid}")
            await u.message.reply_text(f"✅ Alt admin <code>{nid}</code> eklendi ({SUB_DAYS} gün).", parse_mode="HTML", reply_markup=back("sa_menu"))

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
            await u.message.reply_text(f"✅ {n} abonelik eklendi. Sonraki kontrolde kullanılacak.", reply_markup=back("sources"))

        elif act in ("rename", "announce"):
            kid = st["kid"]
            val = txt[:60] if act == "rename" else ("" if txt == "-" else txt)
            def f(db):
                s = db["subs"].get(kid)
                if not s: return None
                if act == "rename": s["name"] = s["title"] = val
                else: s["announce"] = val
                return s.get("file_id"), name_of(s, kid), s.get("announce", ""), list(db["template"])
            r = mutate(f)
            if not r:
                await u.message.reply_text("⚠️ Kod bulunamadı.", reply_markup=back("my_keys"))
                return
            ok = await asyncio.to_thread(lambda: sync_file(new_service(), *r))
            await u.message.reply_text("✅ Kaydedildi ve Drive'a yazıldı." if ok else "⚠️ Kaydedildi ama Drive'a yazılamadı.", reply_markup=back(f"kv:{kid}"))
    except Exception as e:
        log.exception("msg_handler")
        await u.message.reply_text(f"❌ Hata: {esc(str(e)[:300])}", parse_mode="HTML", reply_markup=back("menu", "◀️ Menü"))

FOUNDER_ONLY = {"toggle_sys", "admin", "sources", "s_add", "logs", "upd_now", "get_zip", "sa_menu", "sa_add"}

async def cb(u: Update, c: ContextTypes.DEFAULT_TYPE):
    q = u.callback_query
    uid = q.from_user.id
    if not is_admin(uid):
        await q.answer("⛔ Erişim yok", show_alert=True); return
    a = q.data
    if uid not in ADMINS and (a in FOUNDER_ONLY or a.startswith(("sd:", "sa_del:", "kx:", "kxs:"))):
        await q.answer("⛔ Sadece kurucu", show_alert=True); return
    if a not in ("toggle_sys", "upd_now"):
        await q.answer()
    if a != "logs" and uid in LIVE:
        LIVE.pop(uid).cancel()
    try: db = load_db()
    except Exception as e:
        await safe_edit(q, f"❌ {esc(e)}", back("menu", "◀️ Menü")); return

    if uid not in ADMINS and ":" in a and a.split(":", 1)[0] in ("kv", "kn", "ka", "kd", "kdy"):
        s = db["subs"].get(a.split(":", 1)[1])
        if not s or s.get("owner_id") != uid:
            await safe_edit(q, "⛔ Bu kod senin değil.", back("my_keys")); return

    if a == "menu":
        STATE.pop(uid, None)
        await safe_edit(q, menu_text(uid), main_kb(uid))

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
        await safe_edit(q, f"⚙️ <b>Admin</b>\n{LINE}\nKontrol her {CHECK_EVERY // 60} dakikada bir yapılır. {NEW_IP_LIMIT}'ten fazla yeni IP görülürse bütün kodlar yenilenip tüm Drive aboneliklerine yazılır.", admin_kb())

    elif a == "upd_now":
        if CHECK_LOCK.locked():
            await q.answer("⏳ Şu an kontrol yapılıyor, biraz bekle.", show_alert=True); return
        await q.answer()
        await safe_edit(q, "⚡ <b>Güncelleniyor...</b> Bitince bildirim gelecek.\n\nCanlı izlemek için 📜 Canlı Log.", KB([[B("📜 Canlı Log", callback_data="logs"), B("◀️ Admin", callback_data="admin")]]))
        audit(uid, "upd_now")
        asyncio.create_task(run_check(c.application, force=True))

    elif a == "logs":
        if uid in LIVE: LIVE.pop(uid).cancel()
        await safe_edit(q, log_text(), LOG_KB)
        LIVE[uid] = asyncio.create_task(live_log(q, uid))

    elif a == "my_keys" or a.startswith("my_keys:"):
        page = int(a.split(":")[1]) if ":" in a else 0
        items = [(k, v) for k, v in db["subs"].items() if uid in ADMINS or v.get("owner_id") == uid]
        pages = max(1, (len(items) + PAGE - 1) // PAGE)
        page = max(0, min(page, pages - 1))
        rows = grid([B(("🔴 " if is_exp(v) else "") + short(name_of(v, k), 14), callback_data=f"kv:{k}") for k, v in items[page * PAGE:(page + 1) * PAGE]], 2)
        if pages > 1:
            nav = []
            if page > 0: nav.append(B("◀️", callback_data=f"my_keys:{page - 1}"))
            nav.append(B(f"{page + 1}/{pages}", callback_data=f"my_keys:{page}"))
            if page < pages - 1: nav.append(B("▶️", callback_data=f"my_keys:{page + 1}"))
            rows.append(nav)
        rows.append([B("◀️ Menü", callback_data="menu")])
        await safe_edit(q, f"👥 <b>Kodlarım ({len(items)})</b>\n{LINE}\nYönetmek için birine dokun.", KB(rows))

    elif a.startswith("kv:"):
        kid = a.split(":", 1)[1]
        s = db["subs"].get(kid)
        if not s:
            await safe_edit(q, "⚠️ Kod bulunamadı.", back("my_keys")); return
        fid = s.get("file_id", "")
        txt = (f"👤 <b>{esc(short(name_of(s, kid), 40))}</b>\n{LINE}\n"
               f"📢 Duyuru: <code>{esc(short(s.get('announce') or 'yok', 120))}</code>\n"
               f"⏳ Süre: <b>{left_txt(s.get('expires'))}</b>\n\n"
               f"🔗 Abonelik linki\n<code>{esc(sub_link(fid) if fid else 'Drive dosyası yok')}</code>")
        rows = [[B("✏️ İsim", callback_data=f"kn:{kid}"), B("📢 Duyuru", callback_data=f"ka:{kid}")]]
        rows.append(([B("⏳ Süre", callback_data=f"kx:{kid}")] if uid in ADMINS else []) + [B("🗑 Sil", callback_data=f"kd:{kid}")])
        rows.append([B("◀️ Geri", callback_data="my_keys")])
        await safe_edit(q, txt, KB(rows))

    elif a.startswith("kn:"):
        kid = a.split(":", 1)[1]
        STATE[uid] = {"action": "rename", "kid": kid}
        await safe_edit(q, f"✏️ <b>Yeni isim</b>\n{LINE}\nYeni ismi gönder (VPN uygulamasında görünür).", back(f"kv:{kid}", "İptal"))

    elif a.startswith("ka:"):
        kid = a.split(":", 1)[1]
        STATE[uid] = {"action": "announce", "kid": kid}
        await safe_edit(q, f"📢 <b>Duyuru</b>\n{LINE}\nDuyuru metnini gönder.\nKaldırmak için <code>-</code> gönder.", back(f"kv:{kid}", "İptal"))

    elif a.startswith("kd:"):
        kid = a.split(":", 1)[1]
        s = db["subs"].get(kid, {})
        await safe_edit(q, f"⚠️ <b>Bu kod silinsin mi?</b>\n<code>{esc(short(name_of(s, kid), 40))}</code>\n\nEski abonelik linki boşalır.",
                        KB([[B("✅ Evet", callback_data=f"kdy:{kid}"), B("❌ Hayır", callback_data=f"kv:{kid}")]]))

    elif a.startswith("kdy:"):
        kid = a.split(":", 1)[1]
        nm = name_of(db["subs"].get(kid, {}), kid)
        ok = await asyncio.to_thread(delete_vip, kid)
        if ok: audit(uid, f"delete {kid} {nm}")
        if ok and uid not in ADMINS:
            await notify_founders(c.application, f"🔔 Alt admin <b>{esc(q.from_user.full_name)}</b> (<code>{uid}</code>) kod sildi: <code>{esc(nm)}</code>")
        await safe_edit(q, "✅ Kod silindi." if ok else "⚠️ Kod bulunamadı.", back("my_keys"))

    elif a == "create_key":
        if uid not in ADMINS and sum(1 for v in db["subs"].values() if v.get("owner_id") == uid) >= SUB_LIMIT:
            await safe_edit(q, f"⛔ Limit doldu: {SUB_LIMIT} kod.", back("my_keys", "👥 Kodlarım")); return
        STATE[uid] = {"action": "new_key"}
        await safe_edit(q, f"✨ <b>Kod Oluştur</b>\n{LINE}\nKod için bir isim gönder (VPN uygulamasında görünür).", back("menu", "İptal"))

    elif a.startswith("kx:"):
        kid = a.split(":", 1)[1]
        s = db["subs"].get(kid)
        if not s:
            await safe_edit(q, "⚠️ Kod bulunamadı.", back("my_keys")); return
        await safe_edit(q, f"⏳ <b>Süre</b>\n{LINE}\n<code>{esc(short(name_of(s, kid), 40))}</code>\nKalan: <b>{left_txt(s.get('expires'))}</b>", KB([
            [B("+7g", callback_data=f"kxs:{kid}:7"), B("+30g", callback_data=f"kxs:{kid}:30"), B("+90g", callback_data=f"kxs:{kid}:90")],
            [B("♾ Sınırsız", callback_data=f"kxs:{kid}:0"), B("⛔ Şimdi bitir", callback_data=f"kxs:{kid}:-1")],
            [B("◀️ Geri", callback_data=f"kv:{kid}")]]))

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
            return s.get("file_id"), name_of(s, kid), s.get("announce", ""), list(db2["template"]), s.get("expires")
        r = mutate(fx)
        if not r:
            await safe_edit(q, "⚠️ Kod bulunamadı.", back("my_keys")); return
        ok = await asyncio.to_thread(lambda: sync_file(new_service(), r[0], r[1], r[2], r[3], exp=is_exp({"expires": r[4]})))
        audit(uid, f"duration {kid} {d}")
        await safe_edit(q, f"✅ Güncellendi. Kalan: <b>{left_txt(r[4])}</b>" + ("" if ok else "\n⚠️ Drive'a yazılamadı."), back(f"kv:{kid}"))

    elif a == "sources":
        src = db["sources"]
        rows = [[B(f"🗑 {i}. {src_label(s)}", callback_data="sd:" + hashlib.md5(s.encode()).hexdigest()[:8])] for i, s in enumerate(src, 1)]
        rows.append([B("➕ Abonelik Ekle", callback_data="s_add")])
        rows.append([B("◀️ Admin", callback_data="admin")])
        await safe_edit(q, f"🔗 <b>Abonelikler ({len(src)})</b>\n{LINE}\nKodlar bu aboneliklerden çekilir. Silmek için 🗑'a dokun.", KB(rows))

    elif a.startswith("sd:"):
        h = a.split(":", 1)[1]
        def f(d):
            for s in d["sources"]:
                if hashlib.md5(s.encode()).hexdigest()[:8] == h:
                    d["sources"].remove(s); return True
            return False
        ok = mutate(f)
        if ok: audit(uid, "src_del")
        await safe_edit(q, "✅ Abonelik silindi." if ok else "⚠️ Bulunamadı.", back("sources"))

    elif a == "s_add":
        STATE[uid] = {"action": "src_add"}
        await safe_edit(q, f"➕ <b>Abonelik ekle</b>\n{LINE}\nAbonelik linklerini gönder (her satıra bir tane).", back("sources", "İptal"))

    elif a == "get_zip":
        buf = await asyncio.to_thread(make_backup)
        await c.bot.send_document(chat_id=uid, document=buf, filename=f"Backup_{datetime.datetime.now():%Y-%m-%d_%H%M}.zip")

    elif a == "sa_menu":
        now = time.time()
        rows, lines = [], []
        for sid, e in db.get("sub_admins", {}).items():
            left = float(e.get("expires", 0)) - now
            n = sum(1 for v in db["subs"].values() if str(v.get("owner_id")) == sid)
            lines.append(f"• <code>{sid}</code> · {left_txt(e.get('expires'))} · {n}/{SUB_LIMIT} kod")
            rows.append([B(f"🗑 {sid}", callback_data=f"sa_del:{sid}")])
        rows.append([B("➕ Alt Admin Ekle", callback_data="sa_add")])
        rows.append([B("◀️ Admin", callback_data="admin")])
        await safe_edit(q, f"👮 <b>Alt Adminler</b>\n{LINE}\n" + ("\n".join(lines) or "Alt admin yok."), KB(rows))

    elif a == "sa_add":
        STATE[uid] = {"action": "sa_add"}
        await safe_edit(q, f"➕ <b>Alt admin ekle</b>\n{LINE}\nKişinin sayısal Telegram ID'sini gönder.\nSüre: {SUB_DAYS} gün, en fazla {SUB_LIMIT} kod.\n(ID'sini bota /start yazarak görebilir.)", back("sa_menu", "İptal"))

    elif a.startswith("sa_del:"):
        sid = a.split(":", 1)[1]
        mutate(lambda d: d.get("sub_admins", {}).pop(sid, None))
        audit(uid, f"sa_del {sid}")
        await safe_edit(q, f"✅ Alt admin <code>{esc(sid)}</code> silindi.", back("sa_menu"))

async def doc_handler(u: Update, c: ContextTypes.DEFAULT_TYPE):
    uid = u.effective_user.id
    d = u.message.document
    if uid not in ADMINS or not d or (d.file_name or "").lower()[:6] != "sohbet": return
    f = await c.bot.get_file(d.file_id)
    await f.download_to_drive("/root/sohbet.txt")
    await u.message.reply_text("✅ sohbet.txt kaydedildi (/root/sohbet.txt)")

_ERR = {"t": 0.0}

async def on_error(update, context):
    log.error("Error: %s", context.error, exc_info=context.error)
    from telegram.error import NetworkError
    if isinstance(context.error, NetworkError) or time.time() - _ERR["t"] < 600: return
    _ERR["t"] = time.time()
    try: await notify_founders(context.application, f"❗ <b>Bot hatası</b>\n<code>{esc(str(context.error)[:300])}</code>")
    except Exception: pass

def main():
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
