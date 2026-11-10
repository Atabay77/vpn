# Çalışma notları (kullanıcının kalıcı istekleri)

## Dosya teslimi
- Kullanıcıya indirilecek dosya (APK vb.) verirken sohbete dosya olarak gönderme:
  Google Drive'a yükle (Google Drive bağlayıcısı), «bağlantıya sahip olan herkes okuyabilir» yap ve
  `https://www.googleapis.com/drive/v3/files/<DOSYA_ID>?key=<API_ANAHTARI>&alt=media` biçiminde doğrudan link ver.
  Türkmenistan'da drive.google.com açılmıyor / yavaş; googleapis.com VPN'siz ve daha hızlı iniyor.
- API anahtarı: programın abonelik linkindeki anahtar (botta «🔗 Programın dosya linki»). Koda / depoya yazma.
- APK: bütün telefonlar için tek dosya (universal) ver, arm64'e ayırma.
- 5 MB'tan küçük dosyalar (subbot.py vb.) sohbete doğrudan dosya olarak gönderilir; googleapis'ten inince dosya adı Drive kimliği oluyor ve bot «subbot» adlı dosyayı tanımıyor.
- Drive bağlayıcısı buradan en fazla 10 MB yükleyebiliyor: APK (~25 MB) de şimdilik sohbete dosya olarak gönderilir.
