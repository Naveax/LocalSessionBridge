# Contributing

1. Keep the broker loopback-only.
2. Do not add remote synchronization, cloud storage, telemetry, silent host permissions, credential export, or browser-profile database scraping.
3. Do not log cookies, authorization headers, pairing tokens, API tokens, or request bodies.
4. Keep all active site permissions user initiated and origin scoped.
5. Add or update self-tests for authentication, origin validation, cookie filtering, persistence, and hard limits.
6. Run:

```bash
python broker/session_bridge.py selftest --repeat 10
python scripts/verify.py
```

Use focused commits and explain security-boundary changes in the pull request description.
