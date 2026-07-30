# Loopback API

Default base URL:

```text
http://127.0.0.1:17871
```

All responses use `Cache-Control: no-store`.

## Public health

### `GET /v1/health`

Returns version, loopback state, and session count. No secrets are returned.

## Extension endpoints

### `POST /v1/pair`

Requires an extension origin and a valid one-time pair code.

### `POST /v1/push`

Requires:

```http
Authorization: Bearer <EXTENSION_CLIENT_TOKEN>
X-ULSB-Client-ID: <CLIENT_ID>
X-ULSB-Extension-Origin: chrome-extension://... or moz-extension://...
```

The browser `Origin` header is also accepted when supplied by the extension runtime.

## Local-client endpoints

These require:

```http
Authorization: Bearer <LOCAL_API_TOKEN>
```

### `GET /v1/pair-code`

Returns the current pair code and expiry.

### `GET /v1/sessions`

Returns metadata only; no cookie values.

### `GET /v1/sessions/{name}`

Returns metadata for one session.

### `GET /v1/sessions/{name}/cookie-header`

Returns a plain-text cookie header. An optional `url` query parameter selects a path within the registered origin:

```text
/v1/sessions/example/cookie-header?url=https%3A%2F%2Fexample.com%2Fapi
```

Cross-origin target URLs are rejected.

### `DELETE /v1/sessions/{name}`

Deletes metadata and the encrypted snapshot.
