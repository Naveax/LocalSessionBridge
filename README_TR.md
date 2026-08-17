# Universal Local Session Bridge 1.0.0

Bu araç, kullanıcının açıkça izin verdiği web sitelerinin browser cookie snapshotlarını yalnız `127.0.0.1:17871` üzerinde çalışan yerel brokera aktarır.

## Güvenlik modeli

- Broker LAN veya internette dinleyemez.
- Eklenti site iznini browser izin penceresiyle ister.
- Cookie değerleri HTTP loglarına yazılmaz.
- Snapshotlar Windows kullanıcısına bağlı DPAPI ile şifrelenir.
- Broker API'si ayrı, rastgele token gerektirir.
- Broker 8 haneli bir pair code üretir. Kod 10 dakika boyunca geçerlidir ve bu süre içinde sınırsız sayıda yerel browser/extension instance eşleştirebilir.
- Pair code broker yeniden başlatılırsa, süresi dolarsa veya manuel rotate edilirse değişir.
- Normal web origin'leri pair/push endpointlerinden reddedilir.
- Tamamen biten oturum parola/MFA olmadan yeniden oluşturulamaz.

## 1. Broker

```powershell
cd "$HOME\Downloads\LocalSessionBridge"
python .\dist\session-bridge-v1.0.0.pyz serve
```

Mevcut pair code'u görmek için:

```powershell
python .\dist\session-bridge-v1.0.0.pyz pair-code
```

Aynı 8 haneli kodu geçerlilik süresi içinde Brave, Chrome, Firefox veya başka yerel extension instance'larında kullanabilirsin.

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

Eklenti aktif sekmenin HTTP/HTTPS bilgisini otomatik algılar.

Her site kartında:

- Sayfanın browser tarafından bildirilen **Title** değeri ana ad olarak görünür.
- URL hemen altında görünür.
- Tarayıcı türü otomatik görünür.
- READY / ERROR / KAPALI durumu otomatik görünür.
- Cookie sayısı ve son eşitleme zamanı otomatik görünür.
- Aktif sekmeyse `bu sekme` bilgisi görünür.
- Kullanıcının yapacağı tek site işlemi **Aç / Kapat** seçimidir.

**Aç** seçildiğinde ilgili origin için browser izni istenir, cookie snapshot brokera gönderilir ve otomatik eşitleme etkinleşir.

**Kapat** seçildiğinde o site için otomatik eşitleme durur. Broker'daki son şifreli snapshot otomatik silinmez.

Açık siteler cookie değişiminde, browser başlangıcında ve dakikalık periyodik kontrolde otomatik eşitlenir.

Session için gereken dahili kimlik site origin'i + extension client kimliğinden otomatik üretilir. Bu teknik kimlik normal popup arayüzünde gösterilmez.

Title bilgisi de URL ile birlikte broker metadata'sına aktarılır. Dahili session kimliği güvenli ve kararlı kalırken insan tarafından görülen isim sitenin gerçek Title değeridir.

## 5. Cookie header al

Broker çalışırken:

```powershell
python .\dist\session-bridge-v1.0.0.pyz list
```

Yerel API ve CLI dahili session kimliğini kullanır. Cookie header yalnız kayıtlı origin için üretilebilir.

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
- title-aware ve yeniden kullanılabilir pair-code davranışına sahip broker runtime'ını derler,
- Chromium ve Firefox extension artifactlerini oluşturur,
- Python, JavaScript ve runtime self-testlerini çalıştırır,
- aynı pair code ile ikinci extension client'ın da bağlanabildiğini test eder,
- broker'ı yeniden başlatır,
- 8 haneli pair code'u panoya kopyalar,
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

- Pair code sınırsız sayıda yerel eşleşme kabul eder ancak yalnız 10 dakikalık TTL boyunca geçerlidir.
- Partitioned cookie görünürlüğü browser'ın cookie store davranışına bağlıdır.
- Browser kapalıyken yeni cookie üretilemez.
- Broker son DPAPI şifreli snapshotı sunar.
- Cookie header endpointi hassastır; API tokenını paylaşma.
