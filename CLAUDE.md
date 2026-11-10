# Çalışma notları (kullanıcının kalıcı istekleri)

## Dosya teslimi
- Kullanıcıya indirilecek dosya (APK vb.) verirken sohbete dosya olarak gönderme:
  Google Drive'a yükle (Google Drive bağlayıcısı), «bağlantıya sahip olan herkes okuyabilir» yap ve
  `https://www.googleapis.com/drive/v3/files/<DOSYA_ID>?key=<API_ANAHTARI>&alt=media` biçiminde doğrudan link ver.
  Türkmenistan'da drive.google.com açılmıyor / yavaş; googleapis.com VPN'siz ve daha hızlı iniyor.
- API anahtarı: programın abonelik linkindeki anahtar (botta «🔗 Programın dosya linki»). Koda / depoya yazma.
- APK: bütün telefonlar için tek dosya (universal) ver, arm64'e ayırma.
