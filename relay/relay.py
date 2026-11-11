#!/usr/bin/env python3
"""Türkmen VPN habar serweri (ntfy.sh ýaly, ýöne öz VPS-iňizde).

  POST /<konu>                         — habar goýmak (beden: şifrlenen tekst)
  GET  /<konu>/json?poll=1&since=X     — habarlar (X: habar kimligi, «12h», «all»)
  GET  /health                         — barlag

Habarlary okap bilmeýär: program we bot öz açarlary bilen şifrleýär. Diňe saklaýar we berýär.
Diňe Python 3 (goşmaça kitaphana gerek däl).
"""
import json, os, re, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "8090"))
DATA = os.environ.get("DATA", "/var/lib/tvrelay")
TOPIC = re.compile(r"^[a-z0-9]{8,80}$")
# konunyň görnüşi: tvpn + 16 simwol, soň: m (bota), d (telefona), g (Global chat), p (surat)
KIND = {"m": (3000, 7 * 86400, 8192), "d": (60, 7 * 86400, 8192), "g": (400, 3 * 86400, 4096), "p": (1, 10 ** 9, 96 * 1024)}
OTHER = (100, 86400, 8192)
RATE_GET, RATE_POST = 900, 300          # bir IP-den minutda (köp adam bir VPN serweriniň IP-sinden gelýär)

lock = threading.Lock()
topics = {}                              # konu → [habar]
seq = [0]
hits = {}                                # (ip, kind) → [minut, sany]
os.makedirs(DATA, exist_ok=True)


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


class H(BaseHTTPRequestHandler):
    server_version = "tvrelay/1"
    def log_message(self, *a): pass

    def ip(self): return self.client_address[0]

    def send(self, code, body=b"", ctype="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path); parts = u.path.strip("/").split("/")
        if u.path in ("/", "/health"): return self.send(200, b"ok")
        if not rate(self.ip(), "g", RATE_GET): return self.send(429, b"kop")
        if len(parts) != 2 or parts[1] != "json" or not TOPIC.match(parts[0]): return self.send(404, b"yok")
        t = parts[0]; since = (parse_qs(u.query).get("since") or ["12h"])[0]; now = int(time.time())
        with lock:
            prune(t, now); L = list(topics.get(t, []))
        if since == "all": out = L
        elif re.fullmatch(r"r\d+", since): n = int(since[1:]); out = [m for m in L if int(m["id"][1:]) > n]
        else:
            mm = re.fullmatch(r"(\d+)([smhd])", since)
            sec = int(mm.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[mm.group(2)] if mm else 43200
            out = [m for m in L if now - m["time"] <= sec]
        body = "".join(json.dumps(dict(m, event="message", topic=t)) + "\n" for m in out).encode()
        self.send(200, body, "application/x-ndjson")

    def do_POST(self):
        u = urlparse(self.path); t = u.path.strip("/")
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
        self.send(200, json.dumps(m).encode(), "application/json")


if __name__ == "__main__":
    load()
    print("tvrelay %d portda" % PORT, flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
