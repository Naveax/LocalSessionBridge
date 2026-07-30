# Security policy

## Supported version

| Version | Supported |
|---|---|
| 1.0.x | Yes |

## Reporting a vulnerability

Do not publish vulnerabilities that could expose session cookies, API tokens, pairing tokens, or local encrypted snapshots.

Open a private GitHub security advisory for this repository. Include:

- affected version and operating system;
- browser and extension type;
- a minimal reproduction;
- whether the issue crosses the loopback, origin, client-token, API-token, or DPAPI boundary;
- logs with all credentials removed.

## Security boundaries

LocalSessionBridge is designed for accounts and systems controlled by the operator. Its intended boundary is one local Windows user and loopback clients explicitly given the API token.

The project does not claim to protect against:

- malware running as the same Windows user;
- a compromised browser profile or extension environment;
- an operator deliberately publishing the API token or cookie output;
- server-side invalidation of an authenticated session;
- browser or operating-system compromise.
