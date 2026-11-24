# Çalışma notları (kullanıcının kalıcı istekleri)

## Dosya teslimi
- **APK her zaman GitHub `apk` dalından link olarak verilir** (sohbete dosya olarak GÖNDERME — Claude uygulaması
  dosyayı kendi içinde indiriyor, ilerleme görünmüyor):
  - `apk` dalı «orphan»: içinde sadece en son APK + `SHA256.txt` + `README.txt` durur. Yeni sürümde eski APK silinir,
    dal tek commit'e indirilir (force push serbest — bu dal sadece APK içindir). `claude/inceleme-aagn5q` dalına APK koyma (`*.apk` gitignore'da).
  - Yükledikten sonra linki curl ile indirip SHA-256'yı derlenen dosyayla karşılaştır.
  - Kullanıcıya iki şey ver:
    1. Telefonda indirme: `https://github.com/Atabay77/vpn/raw/apk/TurkmenVPN-<SÜRÜM>.apk`
    2. VPS'e doğrudan indirme (Termius, root):
       `curl -fL -o /home/_gdsh/TurkmenVPN-<SÜRÜM>.apk https://raw.githubusercontent.com/Atabay77/vpn/apk/TurkmenVPN-<SÜRÜM>.apk`
       (site — apk_srv — 90 sn sonra yeni sürümü verir; dosya adında sürüm olmalı)
- APK: bütün telefonlar için tek dosya (universal) ver, arm64'e ayırma.
- 5 MB'tan küçük dosyalar (subbot.py vb.) sohbete doğrudan dosya olarak gönderilir (bot «subbot» adlı dosyayı tanır).
- Programın abonelik linkindeki API anahtarı koda / depoya yazılmaz.

## Çözülmüş sorunlar — geri bozma (kullanıcı: «unutma»)
- **1–2 dakika sonra hiçbir şey açılmıyor, ama ms görünüyor ve sunucu kırmızı olmuyor** (1.47.20'de çözüldü, kullanıcı onayladı):
  sebep DNS'ti. `Cfg.full` DNS'i tek uzun DoH bağlantısıyla (`https://1.1.1.1/dns-query`) çözüyordu; bağlantı 1–2 dakikada
  sessizce kopuyor, Xray ölü bağlantıyı kullanmaya devam ediyordu. Sağlık kontrolü (`measureDelay`) adresi sunucuya çözdürdüğü için
  bunu görmüyordu. Çözüm: DNS sunucuları `tcp://1.1.1.1:53`, `tcp://8.8.8.8:53` (her sorgu yeni bağlantı), DoH sadece yedek.
  DNS'i tekrar tek DoH'a çevirme; `CfgTest.dnsTcpFirst` bunu korur.
- **Siteden inen APK «paket geçersiz / поврежден»** (çözüldü): Chrome dosyayı 3 parçaya bölüp paralel indiriyor, Türkmen internetinde
  orta parça kopunca 12 MB sıfır kalıyordu (boyut doğru görünür). Çözüm: `relay/apk_srv.py` tam (Range'siz) cevapta
  `Accept-Ranges` göndermez; Range isteklerine 206 verir (kaldığı yerden devam çalışır). Bunu geri ekleme.
