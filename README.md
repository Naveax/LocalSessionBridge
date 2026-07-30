# LocalSessionBridge

A local-only browser session bridge for your own accounts, test environments, and authorized automation.

LocalSessionBridge consists of:

- a Python broker bound to `127.0.0.1:17871`;
- Chromium/Brave and Firefox extensions;
- per-origin runtime permissions;
- automatic synchronization through `cookies.onChanged` and periodic checks;
- optional same-origin keep-alive requests;
- Windows current-user DPAPI encryption for persisted snapshots;
- a bearer-protected local API for retrieving a correctly filtered `Cookie` header.

> [!WARNING]
> Session cookies are credentials. Install this only on a computer you control, keep the local API token private, and register only accounts and systems you are authorized to access. The broker intentionally refuses LAN or internet binding.

## Quick start

Requirements:

- Windows 10/11
- Python 3.10+
- Brave/Chrome/Chromium or Firefox Developer Edition

```powershell
cd "$HOME\Downloads\LocalSessionBridge"
python .\dist\session-bridge-v1.0.0.pyz selftest --repeat 10 --report .\selftest-100.json
python .\dist\session-bridge-v1.0.0.pyz serve
```

The broker displays an eight-digit pairing code valid for ten minutes.

### Brave / Chrome / Chromium

1. Open `brave://extensions` or `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Select the `chromium-extension` directory.
5. Open the extension popup and pair it with the local broker.

### Firefox Developer Edition

1. Open `about:debugging#/runtime/this-firefox`.
2. Select **Load Temporary Add-on**.
3. Select `firefox-extension/manifest.json`.
4. Pair the extension with the broker.

Firefox temporary add-ons must be loaded again after restarting the browser. Permanent distribution requires Mozilla signing.

## Register a site

In the extension popup, enter:

```text
Name: example-account
URL: https://example.com/account
Cookie store ID: optional
Keep-alive URL: optional, same origin only
Keep-alive interval: 0 to disable, otherwise at least 5 minutes
```

The extension requests permission only for the selected origin. It then synchronizes matching cookies to the loopback broker.

## Retrieve a session

```powershell
python .\dist\session-bridge-v1.0.0.pyz list
python .\dist\session-bridge-v1.0.0.pyz get example-account --header-only
```

Path-specific filtering:

```powershell
python .\dist\session-bridge-v1.0.0.pyz get example-account `
  --header-only `
  --url "https://example.com/api/resource"
```

Local API example:

```http
GET /v1/sessions/example-account/cookie-header HTTP/1.1
Host: 127.0.0.1:17871
Authorization: Bearer <LOCAL_API_TOKEN>
```

Retrieve the local API token only on the same Windows account:

```powershell
python .\dist\session-bridge-v1.0.0.pyz token
```

## Automatic startup

From the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\INSTALL-AUTOSTART.ps1
```

Remove the scheduled task:

```powershell
.\UNINSTALL-AUTOSTART.ps1
```

Delete all encrypted local state:

```powershell
.\DELETE-ALL-LOCAL-DATA.ps1
```

## Security properties

- Loopback-only bind guard: `127.0.0.1`, `::1`, or `localhost`.
- Per-origin extension permission prompts.
- One-time extension pairing code.
- Separate random API and extension client tokens.
- Extension-origin binding during pairing and pushes.
- No cookie, header, request-body, or token values in HTTP logs.
- Windows current-user DPAPI for API tokens and cookie snapshots.
- Expired-cookie filtering, domain matching, path matching, and secure-cookie filtering.
- Keep-alive disabled by default and limited to the registered origin.

See [Security](SECURITY.md), [Architecture](docs/architecture.md), and [API](docs/api.md).

## Verification

The bundled v1.0.0 artifacts passed:

- 10 isolated self-test iterations;
- 10 checks per iteration;
- 100/100 total runtime checks;
- Python compilation;
- Chromium and Firefox manifest validation;
- JavaScript syntax validation;
- local HTTP pairing, authentication, push, retrieval, filtering, and persistence tests.

No external website was contacted during verification. Windows DPAPI and Task Scheduler operations run under the installing user's Windows account.

## Build release artifacts

```powershell
python .\scripts\build_release.py
python .\scripts\verify.py
```

Generated artifacts are written to `dist/`.

## Language

Turkish documentation: [README_TR.md](README_TR.md)

## License

MIT. See [LICENSE](LICENSE).
