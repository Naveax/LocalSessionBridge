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

The broker displays an eight-digit pairing code valid for ten minutes.

### Brave / Chrome / Chromium

1. Open `brave://extensions` or `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Select the `chromium-extension` directory.
5. Open the extension popup, enter only the pairing code, and select **Connect**.

### Firefox Developer Edition

1. Open `about:debugging#/runtime/this-firefox`.
2. Select **Load Temporary Add-on**.
3. Select `firefox-extension/manifest.json`.
4. Pair the extension with the broker.

## Site controls

The popup automatically detects the active HTTP/HTTPS tab. The page URL is the visible site identity; users no longer enter a separate record name, profile label, cookie store, keep-alive URL, or keep-alive interval.

Each site has a single explicit control:

- **On** requests permission for that origin, synchronizes its cookie snapshot, and enables automatic updates.
- **Off** stops automatic synchronization for that site.

The popup automatically displays the URL, browser, READY/ERROR/OFF state, cookie count, last synchronization time, and whether the row is the active tab.

An internal session identifier is derived automatically from the URL origin and extension client identity. It is not shown in the popup.

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

The script pulls `main`, rebuilds release artifacts, verifies Python/JavaScript and the simplified popup contract, restarts the broker, copies a fresh pairing code to the clipboard, and opens the Brave/Chrome extension pages.

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
- One-time extension pairing code.
- Separate random API and extension client tokens.
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
