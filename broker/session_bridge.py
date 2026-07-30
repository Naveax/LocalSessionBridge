#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import hmac
import http.server
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

VERSION = "1.0.0"
DEFAULT_PORT = 17871
MAX_BODY = 2 * 1024 * 1024
PAIR_TTL = 600
EXTENSION_PREFIXES = ("chrome-extension://", "moz-extension://")


class BridgeError(RuntimeError):
    pass


def iso(ts: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or time.time()))


def default_data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share"))
    return base / "UniversalLocalSessionBridge"


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        try:
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def normalize_url(raw: str) -> str:
    parsed = urllib.parse.urlsplit(str(raw).strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise BridgeError("URL yalnız geçerli http/https olabilir.")
    if parsed.username or parsed.password:
        raise BridgeError("URL kullanıcı adı/parola içeremez.")
    return urllib.parse.urlunsplit(parsed._replace(path=parsed.path or "/", fragment=""))


def origin(url: str) -> str:
    parsed = urllib.parse.urlsplit(normalize_url(url))
    port = parsed.port
    default = (parsed.scheme == "https" and port == 443) or (parsed.scheme == "http" and port == 80)
    host = parsed.hostname or ""
    return f"{parsed.scheme}://{host if not port or default else f'{host}:{port}'}"


def validate_loopback(host: str) -> str:
    value = host.strip().lower()
    if value not in {"127.0.0.1", "::1", "localhost"}:
        raise BridgeError("Broker yalnız loopback üzerinde çalışabilir.")
    return "127.0.0.1" if value == "localhost" else value


def _blob(raw: bytes):
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(raw)
    return DATA_BLOB, buffer, DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))


def dpapi_protect(raw: bytes) -> bytes:
    if os.name != "nt":
        raise BridgeError("DPAPI yalnız Windows'ta kullanılabilir.")
    DATA_BLOB, buffer, source = _blob(raw)
    target = DATA_BLOB()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    if not crypt32.CryptProtectData(ctypes.byref(source), "ULSB", None, None, None, 0x1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(target.pbData)


def dpapi_unprotect(raw: bytes) -> bytes:
    if os.name != "nt":
        raise BridgeError("DPAPI yalnız Windows'ta kullanılabilir.")
    DATA_BLOB, buffer, source = _blob(raw)
    target = DATA_BLOB()
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0x1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(target.pbData)


class Protector:
    def __init__(self, test_plaintext: bool = False):
        self.test_plaintext = test_plaintext

    def protect(self, value: str) -> str:
        raw = value.encode("utf-8")
        if os.name == "nt" and not self.test_plaintext:
            return "dpapi:" + base64.b64encode(dpapi_protect(raw)).decode()
        if self.test_plaintext:
            return "test:" + base64.b64encode(raw).decode()
        raise BridgeError("Windows dışında kalıcı secret saklama kapalıdır.")

    def unprotect(self, value: str) -> str:
        if value.startswith("dpapi:"):
            return dpapi_unprotect(base64.b64decode(value[6:])).decode()
        if value.startswith("test:") and self.test_plaintext:
            return base64.b64decode(value[5:]).decode()
        raise BridgeError("Secret bu Windows kullanıcısına ait değil veya format desteklenmiyor.")


class Store:
    def __init__(self, data_dir: Path, test_plaintext: bool = False):
        self.data_dir = Path(data_dir)
        self.config_path = self.data_dir / "config.json"
        self.snapshots_dir = self.data_dir / "snapshots"
        self.protector = Protector(test_plaintext)
        self.lock = threading.RLock()
        self.config = self._load()

    def _load(self) -> dict[str, Any]:
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            data = json.loads(self.config_path.read_text(encoding="utf-8-sig"))
            data.setdefault("clients", {})
            data.setdefault("sessions", {})
            return data
        data = {
            "version": 1,
            "created_at": iso(),
            "api_token": self.protector.protect(secrets.token_urlsafe(32)),
            "clients": {},
            "sessions": {},
        }
        self._save(data)
        return data

    def _save(self, data: dict[str, Any] | None = None) -> None:
        atomic_write(self.config_path, json.dumps(data or self.config, ensure_ascii=False, indent=2, sort_keys=True))

    def api_token(self) -> str:
        return self.protector.unprotect(self.config["api_token"])

    def rotate_api_token(self) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.config["api_token"] = self.protector.protect(token)
            self._save()
        return token

    def register_client(self, client_id: str, label: str, browser: str, ext_origin: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{8,160}", client_id):
            raise BridgeError("client_id geçersiz.")
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.config["clients"][client_id] = {
                "label": label[:120],
                "browser": browser[:80],
                "origin": ext_origin,
                "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                "created_at": iso(),
                "last_seen": iso(),
            }
            self._save()
        return token

    def authenticate_client(self, client_id: str, token: str, ext_origin: str) -> dict[str, Any] | None:
        with self.lock:
            client = self.config.get("clients", {}).get(client_id)
            if not isinstance(client, dict):
                return None
            if not hmac.compare_digest(client.get("token_hash", ""), hashlib.sha256(token.encode()).hexdigest()):
                return None
            if ext_origin and client.get("origin") and not hmac.compare_digest(ext_origin, client["origin"]):
                return None
            client["last_seen"] = iso()
            self._save()
            return dict(client)

    def snapshot_path(self, name: str) -> Path:
        return self.snapshots_dir / (hashlib.sha256(name.encode()).hexdigest() + ".snapshot")

    def put_session(self, payload: dict[str, Any], client: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", name):
            raise BridgeError("Session adı geçersiz.")
        url = normalize_url(str(payload.get("url", "")))
        cookies = payload.get("cookies")
        if not isinstance(cookies, list) or len(cookies) > 4096:
            raise BridgeError("cookies dizisi geçersiz veya çok büyük.")

        clean = []
        expiries = []
        session_count = 0
        now = time.time()
        for item in cookies:
            if not isinstance(item, dict):
                continue
            cookie_name = str(item.get("name", ""))
            value = str(item.get("value", ""))
            if not cookie_name or any(ch in cookie_name for ch in "\r\n;") or any(ch in value for ch in "\r\n"):
                continue
            if len(cookie_name) > 1024 or len(value) > 16384:
                continue
            expiry = item.get("expirationDate")
            if isinstance(expiry, (int, float)):
                expiry = float(expiry)
                if expiry > now:
                    expiries.append(expiry)
            else:
                expiry = None
                session_count += 1
            clean.append({
                "name": cookie_name,
                "value": value,
                "domain": str(item.get("domain", "")),
                "path": str(item.get("path", "/") or "/"),
                "secure": bool(item.get("secure", False)),
                "httpOnly": bool(item.get("httpOnly", False)),
                "sameSite": str(item.get("sameSite", ""))[:40],
                "expirationDate": expiry,
                "storeId": str(item.get("storeId", payload.get("store_id", "")))[:120],
                "partitionKey": item.get("partitionKey"),
            })

        keepalive_url = str(payload.get("keepalive_url", "") or "")
        if keepalive_url:
            keepalive_url = normalize_url(keepalive_url)
            if origin(keepalive_url) != origin(url):
                raise BridgeError("Keep-alive aynı origin üzerinde olmalı.")
        keepalive_minutes = int(payload.get("keepalive_minutes", 0) or 0)
        if keepalive_minutes != 0 and keepalive_minutes < 5:
            raise BridgeError("Keep-alive minimum 5 dakika.")

        snapshot = {
            "name": name,
            "url": url,
            "client_id": str(payload.get("client_id", "")),
            "browser": str(payload.get("browser", client.get("browser", "")))[:80],
            "store_id": str(payload.get("store_id", ""))[:120],
            "updated_at": iso(),
            "cookies": clean,
        }
        encoded = self.protector.protect(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")))
        snapshot_path = self.snapshot_path(name)
        atomic_write(snapshot_path, encoded)
        metadata = {
            "name": name,
            "url": url,
            "client_id": snapshot["client_id"],
            "client_label": str(client.get("label", "")),
            "browser": snapshot["browser"],
            "store_id": snapshot["store_id"],
            "updated_at": snapshot["updated_at"],
            "cookie_count": len(clean),
            "session_cookie_count": session_count,
            "earliest_expiry": min(expiries) if expiries else None,
            "snapshot_file": snapshot_path.name,
            "keepalive_url": keepalive_url,
            "keepalive_minutes": keepalive_minutes,
            "last_keepalive_status": payload.get("last_keepalive_status"),
        }
        with self.lock:
            self.config["sessions"][name] = metadata
            self._save()
        return dict(metadata)

    def list_sessions(self) -> list[dict[str, Any]]:
        output = []
        with self.lock:
            for name, item in sorted(self.config.get("sessions", {}).items()):
                row = dict(item)
                expiry = row.get("earliest_expiry")
                if row.get("cookie_count", 0) == 0:
                    row["status"] = "EMPTY"
                elif expiry and float(expiry) <= time.time():
                    row["status"] = "EXPIRED"
                elif expiry and float(expiry) <= time.time() + 3600:
                    row["status"] = "EXPIRING_SOON"
                else:
                    row["status"] = "READY"
                output.append(row)
        return output

    def get_metadata(self, name: str) -> dict[str, Any]:
        item = self.config.get("sessions", {}).get(name)
        if not isinstance(item, dict):
            raise BridgeError("Session bulunamadı.")
        return dict(item)

    def get_snapshot(self, name: str) -> dict[str, Any]:
        item = self.get_metadata(name)
        path = self.snapshots_dir / item["snapshot_file"]
        if not path.exists():
            raise BridgeError("Şifreli snapshot bulunamadı.")
        data = json.loads(self.protector.unprotect(path.read_text(encoding="utf-8")))
        if not isinstance(data, dict):
            raise BridgeError("Snapshot bozuk.")
        return data

    def delete_session(self, name: str) -> bool:
        with self.lock:
            item = self.config.get("sessions", {}).pop(name, None)
            if not item:
                return False
            self._save()
        try:
            (self.snapshots_dir / item["snapshot_file"]).unlink()
        except FileNotFoundError:
            pass
        return True


def domain_matches(host: str, cookie_domain: str) -> bool:
    domain = cookie_domain.lstrip(".").lower()
    host = host.lower()
    return bool(domain) and (host == domain or host.endswith("." + domain))


def path_matches(request_path: str, cookie_path: str) -> bool:
    request_path = request_path or "/"
    cookie_path = cookie_path or "/"
    if request_path == cookie_path:
        return True
    if not request_path.startswith(cookie_path):
        return False
    return cookie_path.endswith("/") or (
        len(request_path) > len(cookie_path) and request_path[len(cookie_path)] == "/"
    )


def build_cookie_header(snapshot: dict[str, Any], target_url: str | None = None) -> str:
    registered = normalize_url(snapshot["url"])
    target = normalize_url(target_url or registered)
    if origin(registered) != origin(target):
        raise BridgeError("Cookie header yalnız kayıtlı origin için üretilebilir.")
    parsed = urllib.parse.urlsplit(target)
    selected = []
    for cookie in snapshot.get("cookies", []):
        expiry = cookie.get("expirationDate")
        if isinstance(expiry, (int, float)) and float(expiry) <= time.time():
            continue
        if cookie.get("secure") and parsed.scheme != "https":
            continue
        if not domain_matches(parsed.hostname or "", str(cookie.get("domain", ""))):
            continue
        if not path_matches(parsed.path or "/", str(cookie.get("path", "/"))):
            continue
        selected.append(cookie)
    selected.sort(key=lambda item: (-len(str(item.get("path", "/"))), str(item.get("name", ""))))
    return "; ".join(f"{item['name']}={item['value']}" for item in selected)


def json_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class BrokerState:
    def __init__(self, store: Store):
        self.store = store
        self.lock = threading.RLock()
        self.rotate_pair_code()

    def rotate_pair_code(self) -> str:
        with self.lock:
            self.pair_code = f"{secrets.randbelow(100_000_000):08d}"
            self.pair_expires = time.time() + PAIR_TTL
            return self.pair_code

    def check_pair_code(self, code: str) -> bool:
        with self.lock:
            return time.time() <= self.pair_expires and hmac.compare_digest(str(code), self.pair_code)

class BrokerHandler(http.server.BaseHTTPRequestHandler):
    state: BrokerState
    server_version = "ULSB/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        # Cookie, header, body ve token loglanmaz.
        safe_path = self.path.split("?", 1)[0]
        sys.stderr.write(f"[{iso()}] {self.client_address[0]} {self.command} {safe_path} {fmt % args}\n")

    def _origin(self) -> str:
        explicit = str(self.headers.get("X-ULSB-Extension-Origin", "")).strip()
        if any(explicit.startswith(prefix) for prefix in EXTENSION_PREFIXES):
            return explicit
        return str(self.headers.get("Origin", "")).strip()

    def _is_extension_origin(self) -> bool:
        return any(self._origin().startswith(prefix) for prefix in EXTENSION_PREFIXES)

    def _cors(self) -> None:
        ext_origin = self._origin()
        if any(ext_origin.startswith(prefix) for prefix in EXTENSION_PREFIXES):
            self.send_header("Access-Control-Allow-Origin", ext_origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-ULSB-Client-ID, X-ULSB-Extension-Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")

    def _send_json(self, status: int, value: Any) -> None:
        body = json_bytes(value)
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int, value: str) -> None:
        body = value.encode("utf-8")
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise BridgeError("Content-Length geçersiz.") from exc
        if length < 0 or length > MAX_BODY:
            raise BridgeError("Request body sınırı aşıldı.")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception as exc:
            raise BridgeError("JSON body geçersiz.") from exc
        if not isinstance(value, dict):
            raise BridgeError("JSON root nesne olmalı.")
        return value

    def _bearer(self) -> str:
        raw = str(self.headers.get("Authorization", ""))
        return raw[7:].strip() if raw.startswith("Bearer ") else ""

    def _api_auth(self) -> bool:
        token = self._bearer()
        return bool(token) and hmac.compare_digest(token, self.state.store.api_token())

    def _client_auth(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        client_id = str(self.headers.get("X-ULSB-Client-ID", "") or payload.get("client_id", ""))
        return self.state.store.authenticate_client(client_id, self._bearer(), self._origin())

    def do_OPTIONS(self) -> None:
        if not self._is_extension_origin():
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(204)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = parsed.path
        if path == "/v1/health":
            self._send_json(200, {
                "ok": True,
                "version": VERSION,
                "loopback": True,
                "sessions": len(self.state.store.list_sessions()),
            })
            return
        if not self._api_auth():
            self._send_json(401, {"error": "unauthorized"})
            return
        if path == "/v1/pair-code":
            self._send_json(200, {"code": self.state.pair_code, "expires_at": iso(self.state.pair_expires)})
            return
        if path == "/v1/sessions":
            self._send_json(200, {"sessions": self.state.store.list_sessions()})
            return
        match = re.fullmatch(r"/v1/sessions/([A-Za-z0-9._-]{1,100})(/cookie-header)?", path)
        if match:
            try:
                name = match.group(1)
                if match.group(2):
                    query = urllib.parse.parse_qs(parsed.query)
                    target = query.get("url", [None])[0]
                    self._send_text(200, build_cookie_header(self.state.store.get_snapshot(name), target))
                else:
                    self._send_json(200, self.state.store.get_metadata(name))
            except BridgeError as exc:
                self._send_json(404, {"error": str(exc)})
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        path = urllib.parse.urlsplit(self.path).path
        try:
            payload = self._read_json()
            if path == "/v1/pair":
                if not self._is_extension_origin():
                    self._send_json(403, {"error": "extension_origin_required"})
                    return
                if not self.state.check_pair_code(str(payload.get("code", ""))):
                    self._send_json(403, {"error": "pair_code_invalid_or_expired"})
                    return
                client_id = str(payload.get("client_id", ""))
                token = self.state.store.register_client(
                    client_id,
                    str(payload.get("label", "")),
                    str(payload.get("browser", "")),
                    self._origin(),
                )
                self.state.rotate_pair_code()
                self._send_json(200, {
                    "client_token": token,
                    "client_id": client_id,
                    "paired_at": iso(),
                })
                return
            if path == "/v1/push":
                if not self._is_extension_origin():
                    self._send_json(403, {"error": "extension_origin_required"})
                    return
                client = self._client_auth(payload)
                if client is None:
                    self._send_json(401, {"error": "client_unauthorized"})
                    return
                stored = self.state.store.put_session(payload, client)
                self._send_json(200, {
                    "ok": True,
                    "name": stored["name"],
                    "cookie_count": stored["cookie_count"],
                    "updated_at": stored["updated_at"],
                })
                return
            if not self._api_auth():
                self._send_json(401, {"error": "unauthorized"})
                return
            if path == "/v1/rotate-pair-code":
                code = self.state.rotate_pair_code()
                self._send_json(200, {"code": code, "expires_at": iso(self.state.pair_expires)})
                return
            self._send_json(404, {"error": "not_found"})
        except BridgeError as exc:
            self._send_json(400, {"error": str(exc)})
        except Exception:
            self._send_json(500, {"error": "internal_error"})

    def do_DELETE(self) -> None:
        if not self._api_auth():
            self._send_json(401, {"error": "unauthorized"})
            return
        match = re.fullmatch(r"/v1/sessions/([A-Za-z0-9._-]{1,100})", urllib.parse.urlsplit(self.path).path)
        if not match:
            self._send_json(404, {"error": "not_found"})
            return
        self._send_json(200, {"removed": self.state.store.delete_session(match.group(1))})


class LoopbackServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start_server(store: Store, host: str, port: int, quiet: bool = False) -> None:
    host = validate_loopback(host)
    state = BrokerState(store)

    class Handler(BrokerHandler):
        pass

    Handler.state = state
    server = LoopbackServer((host, port), Handler)
    if not quiet:
        print(f"Universal Local Session Bridge {VERSION}")
        print(f"Broker: http://{host}:{server.server_address[1]}")
        print(f"Pair code: {state.pair_code} (10 dakika)")
        print(f"Data: {store.data_dir}")
        print("Cookie/token değerleri loglanmaz. Ctrl+C ile durdur.")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def request(
    port: int,
    method: str,
    path: str,
    body: dict[str, Any] | None = None,
    token: str = "",
    ext_origin: str = "",
    client_id: str = "",
) -> tuple[int, bytes]:
    headers: dict[str, str] = {}
    data = None
    if body is not None:
        data = json_bytes(body)
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if ext_origin:
        headers["Origin"] = ext_origin
    if client_id:
        headers["X-ULSB-Client-ID"] = client_id
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        method=method,
        data=data,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_server(data_dir: Path):
    store = Store(data_dir, test_plaintext=True)
    state = BrokerState(store)

    class Handler(BrokerHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

    Handler.state = state
    server = LoopbackServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread, store, state

def selftest_once() -> list[str]:
    passed = []
    with tempfile.TemporaryDirectory(prefix="ulsb-test-") as td:
        server, thread, store, state = test_server(Path(td))
        port = server.server_address[1]
        api_token = store.api_token()
        ext_origin = "chrome-extension://abcdefghijklmnop"
        client_id = "test-client-0001"

        if len(api_token) >= 40:
            passed.append("01-api-token")
        else:
            raise AssertionError("api-token")

        status, _ = request(
            port, "POST", "/v1/pair",
            {"code": "00000000", "client_id": client_id, "label": "Test", "browser": "Chromium"},
            ext_origin=ext_origin,
        )
        if status == 403:
            passed.append("02-wrong-pair-rejected")
        else:
            raise AssertionError(f"wrong-pair={status}")

        status, raw = request(
            port, "POST", "/v1/pair",
            {"code": state.pair_code, "client_id": client_id, "label": "Test", "browser": "Chromium"},
            ext_origin=ext_origin,
        )
        if status != 200:
            raise AssertionError(f"pair={status}:{raw!r}")
        client_token = json.loads(raw)["client_token"]
        passed.append("03-pair")

        payload = {
            "client_id": client_id,
            "name": "example-session",
            "url": "https://example.test/account/deep",
            "browser": "Chromium",
            "store_id": "0",
            "cookies": [
                {"name": "root", "value": "R", "domain": ".example.test", "path": "/", "secure": True},
                {"name": "deep", "value": "D", "domain": "example.test", "path": "/account", "secure": True},
                {
                    "name": "expired", "value": "X", "domain": "example.test", "path": "/",
                    "secure": True, "expirationDate": time.time() - 5
                },
            ],
        }
        status, _ = request(
            port, "POST", "/v1/push", payload,
            ext_origin=ext_origin, client_id=client_id,
        )
        if status == 401:
            passed.append("04-push-auth-required")
        else:
            raise AssertionError(f"push-noauth={status}")

        status, raw = request(
            port, "POST", "/v1/push", payload,
            token=client_token, ext_origin=ext_origin, client_id=client_id,
        )
        if status == 200 and json.loads(raw)["cookie_count"] == 3:
            passed.append("05-push")
        else:
            raise AssertionError(f"push={status}:{raw!r}")

        status, _ = request(port, "GET", "/v1/sessions")
        if status == 401:
            passed.append("06-api-auth-required")
        else:
            raise AssertionError(f"api-noauth={status}")

        status, raw = request(
            port, "GET", "/v1/sessions/example-session/cookie-header",
            token=api_token,
        )
        if status == 200 and raw.decode() == "deep=D; root=R":
            passed.append("07-cookie-order-filter")
        else:
            raise AssertionError(f"header={status}:{raw!r}")

        status, _ = request(
            port, "POST", "/v1/pair",
            {"code": state.pair_code, "client_id": "web-client-0001", "label": "Bad", "browser": "Web"},
            ext_origin="https://evil.example",
        )
        if status == 403:
            passed.append("08-web-origin-rejected")
        else:
            raise AssertionError(f"web-origin={status}")

        try:
            validate_loopback("0.0.0.0")
            raise AssertionError("remote-bind accepted")
        except BridgeError:
            passed.append("09-loopback-only")

        restored = Store(Path(td), test_plaintext=True)
        if build_cookie_header(restored.get_snapshot("example-session")) == "deep=D; root=R":
            passed.append("10-snapshot-roundtrip")
        else:
            raise AssertionError("snapshot-roundtrip")

        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return passed


def run_selftest(repeat: int, report: Path | None) -> int:
    results = []
    for index in range(repeat):
        passed = selftest_once()
        results.append({"iteration": index + 1, "passed": passed})
        print(f"Self-test {index + 1}/{repeat}: {len(passed)}/10 passed")
    payload = {
        "version": VERSION,
        "iterations": repeat,
        "total_checks": repeat * 10,
        "all_passed": True,
        "results": results,
    }
    if report:
        atomic_write(report, json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"All {repeat * 10} checks passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Universal Local Session Bridge")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--quiet", action="store_true")

    test = sub.add_parser("selftest")
    test.add_argument("--repeat", type=int, default=10)
    test.add_argument("--report", type=Path)

    sub.add_parser("doctor")
    sub.add_parser("pair-code")
    sub.add_parser("list")
    sub.add_parser("token")
    sub.add_parser("rotate-api-token")

    get_cmd = sub.add_parser("get")
    get_cmd.add_argument("name")
    get_cmd.add_argument("--header-only", action="store_true")
    get_cmd.add_argument("--url", default="")

    delete_cmd = sub.add_parser("delete")
    delete_cmd.add_argument("name")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "selftest":
        if args.repeat < 1 or args.repeat > 100:
            raise BridgeError("repeat 1-100 arasında olmalı.")
        return run_selftest(args.repeat, args.report)

    store = Store(args.data_dir)
    if args.command == "serve":
        start_server(store, args.host, args.port, args.quiet)
        return 0
    if args.command == "token":
        print(store.api_token())
        return 0
    if args.command == "rotate-api-token":
        print(store.rotate_api_token())
        return 0

    token = store.api_token()
    if args.command == "doctor":
        print(f"Universal Local Session Bridge {VERSION}")
        print(f"Data: {args.data_dir}")
        try:
            status, raw = request(args.port, "GET", "/v1/health", token=token)
            print(f"Broker: {'READY' if status == 200 else 'ERROR'}")
            if status == 200:
                print(json.dumps(json.loads(raw), ensure_ascii=False, indent=2))
                return 0
        except Exception as exc:
            print(f"Broker: OFFLINE ({exc})")
        print(r"Başlat: python .\session-bridge.pyz serve")
        return 1

    if args.command == "pair-code":
        status, raw = request(args.port, "GET", "/v1/pair-code", token=token)
        if status != 200:
            raise BridgeError(raw.decode("utf-8", "replace"))
        print(json.loads(raw)["code"])
        return 0

    if args.command == "list":
        status, raw = request(args.port, "GET", "/v1/sessions", token=token)
        if status != 200:
            raise BridgeError(raw.decode("utf-8", "replace"))
        sessions = json.loads(raw).get("sessions", [])
        if not sessions:
            print("Session yok.")
            return 0
        print("NAME                     STATUS          COOKIES  BROWSER              UPDATED")
        for item in sessions:
            print(
                f"{item['name'][:24]:24} {item['status'][:14]:14} "
                f"{int(item.get('cookie_count', 0)):7}  "
                f"{str(item.get('browser', ''))[:20]:20} {item.get('updated_at', '')}"
            )
        return 0

    if args.command == "get":
        path = f"/v1/sessions/{urllib.parse.quote(args.name)}"
        if args.header_only:
            path += "/cookie-header"
            if args.url:
                path += "?" + urllib.parse.urlencode({"url": args.url})
        status, raw = request(args.port, "GET", path, token=token)
        if status != 200:
            raise BridgeError(raw.decode("utf-8", "replace"))
        print(raw.decode("utf-8"))
        return 0

    if args.command == "delete":
        status, raw = request(
            args.port, "DELETE",
            f"/v1/sessions/{urllib.parse.quote(args.name)}",
            token=token,
        )
        if status != 200:
            raise BridgeError(raw.decode("utf-8", "replace"))
        print(raw.decode("utf-8"))
        return 0

    raise BridgeError("Bilinmeyen komut.")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BridgeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
