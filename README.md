# LocalSessionBridge

A local-only browser session bridge for your own accounts, test environments, and authorized automation.

LocalSessionBridge consists of:

- a Python broker bound to `127.0.0.1:17871`;
- Chromium/Brave and Firefox extensions;
- per-origin runtime permissions;
- automatic synchronization through `cookies.onChanged` and periodic checks;
- Windows current-user DPAPI encryption for persisted snapshots;
- a bearer-protected local API for retrieving a correctly filtered `Cookie` header.

> [!WARNING]
> Session cookies are credentials. Install this only on a computer you control, keep the local API token private, and enable only accounts and systems you are authorized to access. The broker intentionally refuses LAN or internet binding.

## Quick start

Requirements:

- Windows 10/11
- Python 3.10+
- Brave/Chrome/Chromium or Firefox Developer Edition

```powershell
cd "$HOME\Downloads\LocalSessionBridge"
python .\dist\session-bridge-v1.0.0.pyz serve
```

The broker displays an eight-digit pairing code valid for ten minutes. The same code may pair any number of local browser/extension instances while that TTL remains valid. Restarting the broker, expiry, or manual rotation replaces the code.

### Brave / Chrome / Chromium

1. Open `brave://extensions` or `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Select the `chromium-extension` directory.
5. Open the extension popup, enter only the pairing code, and select **Connect**.

Each browser/profile keeps its own extension-local site registry and client identity.

### Firefox Developer Edition

1. Open `about:debugging#/runtime/this-firefox`.
2. Select **Load Temporary Add-on**.
3. Select `firefox-extension/manifest.json`.
4. Pair the extension with the broker.

## Site registry

The popup automatically detects the active HTTP/HTTPS tab and reads the browser-provided page **Title** and URL.

If the active URL is not yet registered in that browser/profile, the popup shows an explicit **Add** button. Once registered, the row becomes **On / Off**.

There is no application-level site-count limit. Open another URL and select **Add** again to append another entry to that browser/profile's local registry.

Sites are keyed by normalized full URL, not by origin. Therefore two pages such as:

```text
https://app.basecamp.com/6259481/projects/48506183
https://app.basecamp.com/6259488/projects/48506260
```

remain separate LocalSessionBridge entries even though both use the same `app.basecamp.com` origin.

The origin permission may be shared by the browser, but LocalSessionBridge still gives each saved URL its own internal session identifier.

Each row automatically displays:

- browser-provided page Title;
- URL;
- browser type;
- READY / ERROR / OFF state;
- cookie count;
- last synchronization time;
- active-tab state.

The popup reads only that browser/profile extension instance's `storage.local`. Brave entries do not populate Chrome's popup list, and Chrome entries do not populate Brave's popup list.

The broker can still hold encrypted snapshots from every paired client. Internal session identifiers include both the extension client identity and normalized full URL, so the same URL registered in two different browsers does not overwrite itself.

## Retrieve a session

```powershell
python .\dist\session-bridge-v1.0.0.pyz list
```

The local CLI/API still uses the internal session identifier when retrieving a cookie header:

```powershell
python .\dist\session-bridge-v1.0.0.pyz get <session-id> `
  --header-only `
  --url "https://example.com/api/resource"
```

Retrieve the local API token only on the same Windows account:

```powershell
python .\dist\session-bridge-v1.0.0.pyz token
```

## Update, build, verify, and start

From the repository root:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\UPDATE-AND-START.ps1
```

The script pulls `main`, builds the reusable-pair-code and title-aware broker runtime, rebuilds browser extension artifacts, runs Python/JavaScript/runtime verification, restarts the broker, copies the pairing code to the clipboard, and opens the Brave/Chrome extension pages.

Verification locks the multi-client pairing behavior, the explicit Add control, browser-local site storage, and full-URL site matching so the previous one-site-per-origin bug cannot silently return.

Reload the unpacked extension once after an update.

## Automatic startup

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
- Ten-minute pairing code reusable by unlimited local extension instances during its TTL.
- Separate random API and extension client tokens after pairing.
- Extension-origin binding during pairing and pushes.
- No cookie, header, request-body, or token values in HTTP logs.
- Windows current-user DPAPI for API tokens and cookie snapshots.
- Expired-cookie filtering, domain matching, path matching, and secure-cookie filtering.

See [Security](SECURITY.md), [Architecture](docs/architecture.md), and [API](docs/api.md).

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
