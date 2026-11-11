#!/bin/sh
# Türkmen VPN habar serweri: VPS-de bir buýruk bilen gurmak / täzelemek
#   curl -fsSL https://raw.githubusercontent.com/Atabay77/vpn/claude/inceleme-aagn5q/relay/kur.sh | sh
set -e
PORT=${PORT:-8090}
command -v python3 >/dev/null 2>&1 || { (apt-get update -y && apt-get install -y python3) || yum install -y python3 || dnf install -y python3; }
mkdir -p /opt/tvrelay /var/lib/tvrelay
curl -fsSL https://raw.githubusercontent.com/Atabay77/vpn/claude/inceleme-aagn5q/relay/relay.py -o /opt/tvrelay/relay.py
cat > /etc/systemd/system/tvrelay.service <<UNIT
[Unit]
Description=Turkmen VPN habar serweri
After=network.target

[Service]
Environment=PORT=$PORT
Environment=DATA=/var/lib/tvrelay
ExecStart=/usr/bin/env python3 /opt/tvrelay/relay.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable tvrelay >/dev/null 2>&1
systemctl restart tvrelay
(command -v ufw >/dev/null 2>&1 && ufw allow $PORT/tcp >/dev/null 2>&1) || true
(command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --permanent --add-port=$PORT/tcp >/dev/null 2>&1 && firewall-cmd --reload >/dev/null 2>&1) || true
iptables -C INPUT -p tcp --dport $PORT -j ACCEPT 2>/dev/null || iptables -I INPUT -p tcp --dport $PORT -j ACCEPT 2>/dev/null || true
sleep 2
if curl -fsS http://127.0.0.1:$PORT/health >/dev/null; then
  IP=$(curl -fsS -4 https://api.ipify.org 2>/dev/null || hostname -I | awk '{print $1}')
  echo ""
  echo "✅ Habar serweri işleýär."
  echo "Bota şu salgyny ýazyň:  http://$IP:$PORT"
else
  echo "❌ Başlamady:"; journalctl -u tvrelay -n 20 --no-pager
fi
