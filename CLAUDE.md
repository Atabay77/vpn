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
