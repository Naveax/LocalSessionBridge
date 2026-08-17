# Universal Local Session Bridge 1.0.0

Bu araç, kullanıcının açıkça izin verdiği web sitelerinin browser cookie snapshotlarını yalnız `127.0.0.1:17871` üzerinde çalışan yerel brokera aktarır.

## Güvenlik modeli

- Broker LAN veya internette dinleyemez.
- Eklenti site iznini kullanıcıdan browser izin penceresiyle ister.
- Cookie değerleri HTTP loglarına yazılmaz.
- Snapshotlar Windows kullanıcısına bağlı DPAPI ile şifrelenir.
- Broker API'si ayrı, rastgele token gerektirir.
- 8 haneli pair code 10 dakika geçerlidir ve bu süre içinde sınırsız sayıda yerel extension instance eşleştirilebilir.
- Normal web origin'leri pair/push endpointlerinden reddedilir.
- Tamamen biten oturum parola/MFA olmadan yeniden oluşturulamaz.

## 1. Broker

```powershell
cd "$HOME\Downloads\LocalSessionBridge"
python .\dist\session-bridge-v1.0.0.pyz serve
```

Broker 10 dakika geçerli 8 haneli bir pair code üretir.

## 2. Brave / Chrome

1. `brave://extensions` veya `chrome://extensions` aç.
2. **Developer mode** aç.
3. **Load unpacked** seç.
4. `chromium-extension` klasörünü seç.
5. Eklenti popup'ına yalnız pair code'u girip **Bağla** seç.

Aynı pair code 10 dakikalık pencere içinde Brave, Chrome ve diğer yerel profillerde tekrar kullanılabilir. Her browser/profile ayrı client kimliği ve ayrı extension local storage kullanır.

Broker URL'si, profil etiketi, kayıt adı, cookie store ve keep-alive alanları kullanıcıdan istenmez.

## 3. Firefox Developer Edition

1. `about:debugging#/runtime/this-firefox` aç.
2. **Load Temporary Add-on** seç.
3. `firefox-extension/manifest.json` seç.
4. Eklenti popup'ına pair code'u girip bağlan.

## 4. Site kullanımı

Eklenti aktif sekmenin HTTP/HTTPS URL'sini ve browser'ın verdiği sayfa `Title` bilgisini otomatik algılar.

Aktif sekmede site henüz kayıtlı değilse **Ekle** düğmesi görünür. Eklendikten sonra aynı satır **Aç / Kapat** kontrolüne dönüşür.

Her kayıt otomatik olarak şunları gösterir:

- Sayfanın gerçek Title bilgisi
- Tam kayıt URL'si
- Tarayıcı türü
- READY / ERROR / KAPALI durumu
- Cookie sayısı
- Son eşitleme zamanı
- Aktif sekme bilgisi

### Sınırsız site kaydı

LocalSessionBridge uygulama seviyesinde bir site sayısı sınırı koymaz. Yeni bir URL açıp **Ekle** seçerek aynı browser/profile içinde art arda yeni kayıtlar eklenebilir.

Kayıtlar artık origin ile değil normalize edilmiş tam URL ile eşleştirilir. Örneğin:

```text
https://app.basecamp.com/6259481/projects/48506183
https://app.basecamp.com/6259488/projects/48506260
```

aynı `app.basecamp.com` origin'inde olsalar bile iki ayrı kayıt olarak tutulur.

Aynı origin için browser host izni ortak olabilir, fakat her URL ayrı LocalSessionBridge kaydı ve ayrı dahili session kimliği alır.

### Tarayıcı izolasyonu

Popup yalnız o browser/profile extension instance'ının `storage.local` içindeki siteleri gösterir. Brave'e eklenen kayıt Chrome'un popup listesine, Chrome'a eklenen kayıt Brave'in popup listesine taşınmaz.

Broker ise tüm bağlı clientların şifreli snapshotlarını yerel olarak tutabilir. Aynı URL iki farklı browser'da eklenirse dahili session kimliği browser client kimliğini de içerdiği için snapshotlar birbirini ezmez.

## 5. Dahili session kimliği

Kullanıcı manuel session adı girmez. Dahili kimlik otomatik olarak browser client kimliği + tam URL'den üretilir. Popup'ta bu teknik kimlik yerine Title + URL gösterilir.

Broker çalışırken kayıtları görmek için:

```powershell
python .\dist\session-bridge-v1.0.0.pyz list
```

Cookie header almak için yerel CLI/API dahili session kimliğini kullanır:

```powershell
python .\dist\session-bridge-v1.0.0.pyz get <session-id> --header-only `
  --url "https://example.com/api/resource"
```

Yerel API tokenı:

```powershell
python .\dist\session-bridge-v1.0.0.pyz token
```

## 6. Güncelle / derle / doğrula / başlat

Repo kökünde:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\UPDATE-AND-START.ps1
```

Bu script:

- GitHub `main` branch'ini günceller,
- release artifactlerini yeniden oluşturur,
- Python ve JavaScript doğrulamalarını çalıştırır,
- broker'ı yeniden başlatır,
- fresh pair code üretip panoya kopyalar,
- Brave ve Chrome extension sayfalarını açar.

Doğrulama ayrıca aynı pair code ile birden fazla client eşleşmesini, açık **Ekle** kontrolünü, browser-local site listesini ve tam-URL tabanlı çoklu kayıt davranışını kontrol eder.

Extension sayfasında güncellemeden sonra bir kez **Reload** gerekir.

## Otomatik başlangıç

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

## API

- `GET /v1/health`
- `POST /v1/pair`
- `POST /v1/push`
- `GET /v1/sessions`
- `GET /v1/sessions/{name}`
- `GET /v1/sessions/{name}/cookie-header`
- `DELETE /v1/sessions/{name}`

## Sınırlar

- Uygulama site sayısı için yapay bir limit koymaz; gerçek üst sınır browser extension storage ve sistem kaynaklarıdır.
- Partitioned cookie görünürlüğü browser'ın cookie store davranışına bağlıdır.
- Browser kapalıyken yeni cookie üretilemez.
- Broker son DPAPI şifreli snapshotı sunar.
- Cookie header endpointi hassastır; API tokenını paylaşma.
