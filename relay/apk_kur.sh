#!/bin/sh
# 1.47.17: APK paýlaýjy (apk_srv.py) — systemd hyzmaty, 8091 port (Caddy turkmenvpn.ru → 8091). Täzelemek hem şu buýruk:
#   curl -fsSL https://raw.githubusercontent.com/Atabay77/vpn/claude/inceleme-aagn5q/relay/apk_kur.sh | sh
set -e
mkdir -p /opt/tvapk /root/apk
curl -fsSL https://raw.githubusercontent.com/Atabay77/vpn/claude/inceleme-aagn5q/relay/apk_srv.py -o /opt/tvapk/apk_srv.py
pkill -f "apk_srv.py" 2>/dev/null || true   # öň elde (nohup / screen) işledilen köne nusga
sleep 1
cat > /etc/systemd/system/tvapk.service <<'UNIT'
[Unit]
Description=Turkmen VPN APK paylayjy
After=network.target

[Service]
ExecStart=/usr/bin/env python3 /opt/tvapk/apk_srv.py 8091
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable tvapk >/dev/null 2>&1
systemctl restart tvapk
sleep 2
echo ""
if curl -fsSI http://127.0.0.1:8091/TurkmenVPN.apk 2>/dev/null | grep -i "filename"; then
  echo "✅ APK paýlaýjy işleýär — ýokardaky faýl häzir berilýär."
else
  echo "⚠️ APK tapylmady: faýly /root/apk ýa-da /home/<ulanyjy> içine goýuň (adynda wersiýa bolsun: TurkmenVPN-1.47.17.apk)."
fi
