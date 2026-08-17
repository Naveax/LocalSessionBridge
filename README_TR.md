# Universal Local Session Bridge 1.0.0

Bu araç, kullanıcının tek tek izin verdiği URL origin'lerinin browser cookie
snapshotlarını yalnız `127.0.0.1:17871` üzerinde çalışan yerel brokera aktarır.

## Güvenlik modeli

- Broker LAN veya internette dinleyemez.
- Eklenti her site için browser izin penceresi gösterir.
- Cookie değerleri HTTP loglarına yazılmaz.
- Snapshotlar Windows kullanıcısına bağlı DPAPI ile şifrelenir.
- Broker API'si ayrı, rastgele token gerektirir.
- Eklenti bir defalık 8 haneli pair code ile eşleştirilir.
- Normal web origin'leri pair/push endpointlerinden reddedilir.
- Keep-alive varsayılan olarak kapalıdır; minimum 5 dakikadır.
- Tamamen biten oturum parola/MFA olmadan yeniden oluşturulamaz.

## 1. Broker

```powershell
cd "$HOME\Downloads\Universal-Local-Session-Bridge-v1.0.0"
python .\dist\session-bridge-v1.0.0.pyz selftest --repeat 10 --report .\selftest-100.json
python .\dist\session-bridge-v1.0.0.pyz serve
```

Broker konsolunda 8 haneli `Pair code` görünür.

## 2. Brave / Chrome

1. `brave://extensions` veya `chrome://extensions` aç.
2. **Developer mode** aç.
3. **Load unpacked** seç.
4. `chromium-extension` klasörünü seç.
5. Eklenti popup'ında broker URL, profil etiketi ve pair code gir.
6. **Eşleştir**.

## 3. Firefox Developer Edition

1. `about:debugging#/runtime/this-firefox` aç.
2. **Load Temporary Add-on** seç.
3. `firefox-extension/manifest.json` seç.

Geçici Firefox eklentisi browser kapanınca yeniden yüklenmelidir. Kalıcı
dağıtım için Mozilla imzası gerekir.

## 4. Site ekle

Örnek:

- Kayıt adı: `hubspot-a`
- URL: `https://app-na2.hubspot.com/contacts/...`
- Cookie store ID: normal profilde boş bırakılabilir
- Keep-alive URL: opsiyonel, aynı origin
- Keep-alive dakika: `0` kapalı; açık ise minimum `5`

**İzin iste ve ekle** düğmesine bas. Browser yalnız ilgili origin için izin ister.

### Site bazlı Aç / Kapat

Her kayıt artık bağımsız olarak açılıp kapatılabilir.

- **Açık** kayıtlar başlangıçta, cookie değişiminde ve dakikalık periyodik kontrolde otomatik eşitlenir.
- **Kapalı** kayıtlar otomatik eşitleme ve keep-alive çalıştırmaz.
- Tekrar **Aç** seçildiğinde kayıt hemen bir kez eşitlenir.
- **Tümünü aç**, **Tümünü kapat** ve **Tümünü eşitle** kontrolleri popup'ta bulunur.
- Eski kayıtlar `enabled` alanı taşımıyorsa geriye dönük uyumluluk için açık kabul edilir.

Kapatmak broker'daki son DPAPI şifreli snapshotı silmez. Snapshotı tamamen kaldırmak için CLI/API üzerinden session silme işlemi kullanılmalıdır.

### Görünen kayıt bilgileri

Popup her site için şunları gösterir:

- Kayıt adı ve READY / ERROR / KAPALI durumu
- URL
- Tarayıcı türü
- Tarayıcı/profil etiketi
- Cookie sayısı
- Son eşitleme zamanı
- Keep-alive durumu ve varsa son HTTP sonucu
- Son hata

Brave algılaması `navigator.brave` üzerinden yapılır; Chrome, Edge, Opera, Firefox ve genel Chromium için de ayrı etiket üretilir.

## 5. Cookie header al

Broker çalışırken:

```powershell
python .\dist\session-bridge-v1.0.0.pyz list
python .\dist\session-bridge-v1.0.0.pyz get hubspot-a --header-only
```

Belirli path için:

```powershell
python .\dist\session-bridge-v1.0.0.pyz get hubspot-a --header-only `
  --url "https://app-na2.hubspot.com/api/example"
```

Başka yerel araca API tokenı vermek için:

```powershell
$env:ULSB_API_TOKEN = python .\dist\session-bridge-v1.0.0.pyz token
```

Yerel API:

```text
GET http://127.0.0.1:17871/v1/sessions/hubspot-a/cookie-header
Authorization: Bearer <LOCAL_API_TOKEN>
```

## 6. Otomatik başlangıç

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\INSTALL-AUTOSTART.ps1
```

Kaldırma:

```powershell
.\UNINSTALL-AUTOSTART.ps1
```

Tüm şifreli yerel veriyi silme:

```powershell
.\DELETE-ALL-LOCAL-DATA.ps1
```

## Otomatik yenilenme

Eklenti:

- Yalnız **açık** kayıtları `cookies.onChanged` olayında tekrar eşitler.
- Yalnız **açık** kayıtları her dakika periyodik kontrol eder.
- Browser cookie rotasyonlarını açık kayıtlar için otomatik brokera gönderir.
- Keep-alive açıksa ve kayıt etkinse aynı-origin URL'ye credential dahil GET yapar.
- Sunucu oturumu geçersiz kılarsa yeniden login gerekir.

## API

- `GET /v1/health`
- `POST /v1/pair`
- `POST /v1/push`
- `GET /v1/sessions`
- `GET /v1/sessions/{name}`
- `GET /v1/sessions/{name}/cookie-header`
- `DELETE /v1/sessions/{name}`

## Sınırlar

- Partitioned cookie görünürlüğü browser'ın cookie store davranışına bağlıdır.
- Keep-alive sliding-session yenilenmesini garanti etmez.
- Browser kapalıyken yeni cookie üretilemez.
- Broker son DPAPI şifreli snapshotı sunar.
- Cookie header endpointi hassastır; API tokenını paylaşma.
