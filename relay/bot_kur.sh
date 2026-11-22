#!/bin/bash
# 1.47: Telegram botuny täze VPS-e geçirmek — bir buýruk:
#   bash bot_kur.sh Backup_YYYY-MM-DD_HHMM.zip
# Ätiýaçlyk faýly (bot her 6 sagatda Telegram-da iberýär) şu VPS-e göçüriň (meselem: scp Backup_....zip root@TÄZE_IP:/root/).
# Bot açylanda köne VPS-däki bot özi durýar we ähli maglumatlar (baza, habar serweri) täze VPS-e geçýär.
set -e
Z="$1"
if [ ! -f "$Z" ]; then echo "Ulanyş: bash bot_kur.sh Backup_YYYY-MM-DD_HHMM.zip"; exit 1; fi
apt-get update -y >/dev/null && apt-get install -y python3 python3-pip unzip >/dev/null
PKGS='python-telegram-bot==21.6 google-api-python-client google-auth google-auth-httplib2'
pip3 install -q $PKGS 2>/dev/null || pip3 install -q --break-system-packages $PKGS
cd /root
unzip -o -q "$Z" subbot.py env.txt drive-sa.json banners.json 2>/dev/null || true
if [ ! -f /root/subbot.py ] || [ ! -f /root/env.txt ]; then echo "Ätiýaçlykda subbot.py ýa-da env.txt ýok"; exit 1; fi
rm -f /root/subbot.retired
cat > /etc/systemd/system/subbot.service <<UNIT
[Unit]
Description=Subbot (Telegram)
After=network-online.target
[Service]
WorkingDirectory=/root
ExecStart=/usr/bin/env python3 /root/subbot.py
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable subbot >/dev/null 2>&1
systemctl restart subbot
echo "✅ Bot işe başlady. 1-2 minutda köne VPS-däki bot durýar we maglumatlar şu ýere geçýär (Telegram-da habar geler)."
echo "   Ýagdaý: systemctl status subbot · loglar: journalctl -u subbot -f"
