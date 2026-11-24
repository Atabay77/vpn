# Türkmenistan'da VPN'siz açılan adresler (test: 24.11.2026, kullanıcının telefonu, Termux, https)

Sadece ana alan adı test edildi; alt alan adları (ör. `x.onrender.com`) ayrıca denenmeli. Engeller değişebilir — önemli işten önce tekrar test et.
103 adresten 23'ü açıldı. Test komutu: bu dosyanın sonunda.

| Kategori | Açılan (süre) |
|---|---|
| Dosya / APK | www.googleapis.com (0,79) · storage.googleapis.com (0,86) · gitlab.com (0,79) · disk.yandex.ru (0,70) · mega.nz (0,86) · onedrive.live.com (0,91) · dl.dropboxusercontent.com (1,10) · 0x0.st (1,08) · cloud.mail.ru (1,50) |
| Site / hosting | firebaseapp.com (0,96) · sites.google.com (1,52) · surge.sh (1,97) |
| Sunucu / bulut | amazonaws.com (0,85) · onrender.com (1,22) · oracle.com (1,20) · cloud.google.com (6,0 — yavaş) |
| CDN | fastly.com (0,61) |
| Mesaj | fcm.googleapis.com (0,60) · firestore.googleapis.com (0,85) |
| Not / metin | paste.ee (1,67) · write.as (3,31) |
| Rus | yandex.ru (1,51) · dzen.ru (1,97) |
| Kısa link | da.gd (0,65) · 1url.cz (0,69) · u.to (0,97) — `da.gd/tmvpn2` → sites.google.com/view/turkmen-vpn |

## Açılmayan önemli olanlar
github.com, raw.githubusercontent.com (GitHub `apk` dalı linkleri TM'de VPN'siz açılmaz — VPS'e indirme için sorun yok),
ntfy.sh, api.telegram.org, t.me, drive.google.com, docs.google.com, dropbox.com, cdn.jsdelivr.net, workers.dev, pages.dev, vercel.app,
netlify.app, github.io, web.app, deno.dev, bütün DoH (dns.google, cloudflare-dns.com, 1.1.1.1 …), ip-api.com, ipinfo.io, vk.com, ok.ru, mail.ru,
bit.ly, tinyurl.com, clck.ru, is.gd … ve turkmenvpn.ru (alan adı engelli).

## Kullanım fikirleri
- APK yedek indirme: storage.googleapis.com (GCS herkese açık bucket), gitlab.com (repo raw), disk.yandex.ru, dl.dropboxusercontent.com.
- İndirme sayfası: sites.google.com (şu an), firebaseapp.com (Firebase Hosting), surge.sh.
- Ön VPS engellenirse: onrender.com (ücretsiz web servisi — aktarıcı), Oracle / AWS sunucuları (IP'si ayrıca test edilmeli).
- Bildirim: fcm/firestore açık; ntfy.sh kapalı (telemetri ön VPS üzerinden gitmeli).

## Test komutu (Termux, VPN kapalı)
`printf '%s\n' kat:alanadi ... | xargs -P 12 -I{} sh -c '...curl -s -o /dev/null -m 6 -w "%{http_code} %{time_total}" https://$h...'` — sohbette verilen tam komut; `~/s.txt`'e yazar.
