# Universal Local Session Bridge 1.0.0

Bu araç, kullanıcının açıkça izin verdiği web sitelerinin browser cookie snapshotlarını yalnız `127.0.0.1:17871` üzerinde çalışan yerel brokera aktarır.

## Güvenlik modeli

- Broker LAN veya internette dinleyemez.
- Eklenti site iznini kullanıcıdan browser izin penceresiyle ister.
- Cookie değerleri HTTP loglarına yazılmaz.
- Snapshotlar Windows kullanıcısına bağlı DPAPI ile şifrelenir.
- Broker API'si ayrı, rastgele token gerektirir.
- Eklenti bir defalık 8 haneli pair code ile eşleştirilir.
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

Broker URL'si, tarayıcı etiketi, profil etiketi, kayıt adı, cookie store ve keep-alive alanları kullanıcıdan istenmez.

## 3. Firefox Developer Edition

1. `about:debugging#/runtime/this-firefox` aç.
2. **Load Temporary Add-on** seç.
3. `firefox-extension/manifest.json` seç.
4. Eklenti popup'ına pair code'u girip bağlan.

## 4. Site kullanımı

Eklenti aktif sekmenin HTTP/HTTPS URL'sini otomatik algılar.

Popup'ta site adı olarak doğrudan URL görünür. Kullanıcıdan ayrıca bir kayıt adı istenmez.

Her site için yalnız iki temel durum vardır:

- **Aç**: ilgili origin için browser iznini ister, cookie snapshotını brokera gönderir ve otomatik eşitlemeyi etkinleştirir.
- **Kapat**: o site için otomatik eşitlemeyi durdurur.

Açık siteler cookie değişiminde, browser başlangıcında ve dakikalık periyodik kontrolde otomatik eşitlenir. Kapalı siteler eşitlenmez.

Popup otomatik olarak şunları gösterir:

- URL
- Tarayıcı türü
- READY / ERROR / KAPALI durumu
- Cookie sayısı
- Son eşitleme zamanı
- Aktif sekme bilgisi

Session için gereken dahili kimlik URL + browser extension client kimliğinden otomatik üretilir ve kullanıcı arayüzünde gösterilmez.

## 5. Cookie header al

Broker çalışırken:

```powershell
python .\dist\session-bridge-v1.0.0.pyz list
```

Yerel API ve CLI hâlâ dahili session kimliğini kullanır. Cookie header yalnız kayıtlı origin için üretilebilir.

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

- Partitioned cookie görünürlüğü browser'ın cookie store davranışına bağlıdır.
- Browser kapalıyken yeni cookie üretilemez.
- Broker son DPAPI şifreli snapshotı sunar.
- Cookie header endpointi hassastır; API tokenını paylaşma.
