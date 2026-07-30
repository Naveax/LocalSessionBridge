# Architecture

```text
Browser extension
  ├─ user-approved origin permissions
  ├─ cookies.getAll({url, storeId})
  ├─ cookies.onChanged debounce
  ├─ one-minute periodic synchronization
  └─ optional same-origin keep-alive GET
              │
              │ loopback HTTP + paired client token
              ▼
Python broker — 127.0.0.1:17871
  ├─ extension-origin validation
  ├─ one-time pairing code
  ├─ API/client token separation
  ├─ cookie validation and limits
  ├─ Windows current-user DPAPI persistence
  └─ path/domain/secure/expiry filtering
              │
              │ bearer-protected loopback API
              ▼
Authorized local clients
```

## Pairing

The broker displays an eight-digit code valid for ten minutes. The extension supplies that code, a random client identifier, its extension origin, and a user-selected label. The broker stores only a SHA-256 hash of the generated client token.

Pairing rotates the code immediately after success.

## Synchronization

For each registered URL, the extension asks the browser for matching cookies. It sends the cookie objects to the local broker with the paired extension-client token. The broker validates limits and fields before persisting the snapshot.

## Persistence

On Windows, the API token and session snapshots are encrypted with current-user DPAPI. Copying the state directory to another Windows account does not make the secrets usable there.

## Retrieval

A local client must possess the separate broker API token. The broker reconstructs the `Cookie` header for the registered origin and requested path after applying expiry, secure, domain, and path rules.

## Deliberate exclusions

- No LAN or internet listener.
- No cloud synchronization.
- No browser cookie-database scraping.
- No password, MFA, or login automation.
- No silent all-sites access.
- No telemetry.
