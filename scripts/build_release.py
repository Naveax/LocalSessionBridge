#!/usr/bin/env python3
from __future__ import annotations

import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
VERSION = "1.0.0"


def zip_directory(source: Path, destination: Path) -> None:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"Broker runtime patch failed for {label}: expected 1 match, got {count}")
    return source.replace(old, new, 1)


def build_broker_runtime(source: str) -> str:
    # A pair code remains valid for its TTL and may pair any number of local
    # extension instances. Manual rotation and broker restart still replace it.
    source = replace_once(
        source,
        "                self.state.rotate_pair_code()\n                self._send_json(200, {\n",
        "                self._send_json(200, {\n",
        "reusable pair code",
    )

    # Persist the browser-provided document title together with URL metadata.
    source = replace_once(
        source,
        "        url = normalize_url(str(payload.get(\"url\", \"\")))\n        cookies = payload.get(\"cookies\")\n",
        "        url = normalize_url(str(payload.get(\"url\", \"\")))\n        title = str(payload.get(\"title\", \"\") or \"\").strip()[:300]\n        cookies = payload.get(\"cookies\")\n",
        "title input",
    )
    source = replace_once(
        source,
        "        snapshot = {\n            \"name\": name,\n            \"url\": url,\n            \"client_id\": str(payload.get(\"client_id\", \"\")),\n",
        "        snapshot = {\n            \"name\": name,\n            \"title\": title,\n            \"url\": url,\n            \"client_id\": str(payload.get(\"client_id\", \"\")),\n",
        "snapshot title",
    )
    source = replace_once(
        source,
        "        metadata = {\n            \"name\": name,\n            \"url\": url,\n            \"client_id\": snapshot[\"client_id\"],\n",
        "        metadata = {\n            \"name\": name,\n            \"title\": title,\n            \"url\": url,\n            \"client_id\": snapshot[\"client_id\"],\n",
        "metadata title",
    )

    # Expired persistent cookies must never be stored as usable credentials.
    source = replace_once(
        source,
        "            expiry = item.get(\"expirationDate\")\n            if isinstance(expiry, (int, float)):\n                expiry = float(expiry)\n                if expiry > now:\n                    expiries.append(expiry)\n            else:\n                expiry = None\n                session_count += 1\n            clean.append({\n",
        "            expiry = item.get(\"expirationDate\")\n            if isinstance(expiry, (int, float)):\n                expiry = float(expiry)\n                if expiry <= now:\n                    continue\n                expiries.append(expiry)\n            else:\n                expiry = None\n                session_count += 1\n            clean.append({\n",
        "expired cookie filtering",
    )

    source = replace_once(
        source,
        "            \"earliest_expiry\": min(expiries) if expiries else None,\n            \"snapshot_file\": snapshot_path.name,\n",
        "            \"earliest_expiry\": min(expiries) if expiries else None,\n            \"latest_expiry\": max(expiries) if expiries else None,\n            \"snapshot_file\": snapshot_path.name,\n",
        "latest expiry metadata",
    )
    source = replace_once(
        source,
        "                expiry = row.get(\"earliest_expiry\")\n                if row.get(\"cookie_count\", 0) == 0:\n                    row[\"status\"] = \"EMPTY\"\n                elif expiry and float(expiry) <= time.time():\n                    row[\"status\"] = \"EXPIRED\"\n                elif expiry and float(expiry) <= time.time() + 3600:\n                    row[\"status\"] = \"EXPIRING_SOON\"\n                else:\n                    row[\"status\"] = \"READY\"\n",
        "                now = time.time()\n                cookie_count = int(row.get(\"cookie_count\", 0) or 0)\n                session_cookie_count = int(row.get(\"session_cookie_count\", 0) or 0)\n                latest_expiry = row.get(\"latest_expiry\")\n                if latest_expiry is None:\n                    latest_expiry = row.get(\"earliest_expiry\")\n                if cookie_count == 0:\n                    row[\"status\"] = \"EMPTY\"\n                elif session_cookie_count > 0:\n                    row[\"status\"] = \"READY\"\n                elif latest_expiry is not None and float(latest_expiry) <= now:\n                    row[\"status\"] = \"EXPIRED\"\n                elif latest_expiry is not None and float(latest_expiry) <= now + 3600:\n                    row[\"status\"] = \"EXPIRING_SOON\"\n                else:\n                    row[\"status\"] = \"READY\"\n",
        "session status semantics",
    )

    # Migration-safe registry semantics.
    source = replace_once(
        source,
        "        with self.lock:\n            self.config[\"sessions\"][name] = metadata\n            self._save()\n        return dict(metadata)\n",
        "        stale_snapshot_files = []\n        with self.lock:\n            for old_name, old_item in list(self.config[\"sessions\"].items()):\n                if old_name == name or not isinstance(old_item, dict):\n                    continue\n                if str(old_item.get(\"client_id\", \"\")) != snapshot[\"client_id\"]:\n                    continue\n                try:\n                    same_url = normalize_url(str(old_item.get(\"url\", \"\"))) == url\n                except BridgeError:\n                    same_url = False\n                if not same_url:\n                    continue\n                old_file = str(old_item.get(\"snapshot_file\", \"\"))\n                if old_file:\n                    stale_snapshot_files.append(old_file)\n                self.config[\"sessions\"].pop(old_name, None)\n            self.config[\"sessions\"][name] = metadata\n            self._save()\n        for stale_file in stale_snapshot_files:\n            try:\n                (self.snapshots_dir / stale_file).unlink()\n            except FileNotFoundError:\n                pass\n        return dict(metadata)\n",
        "same-client same-url session pruning",
    )

    # In-memory read-only browser-native probe queue. Jobs are submitted by the
    # local API-token holder and may only target origins already registered by
    # the selected extension client. The extension can only claim/complete its
    # own jobs. No arbitrary script or mutation verb is accepted.
    source = replace_once(
        source,
        "    def check_pair_code(self, code: str) -> bool:\n        with self.lock:\n            return time.time() <= self.pair_expires and hmac.compare_digest(str(code), self.pair_code)\n\nclass BrokerHandler",
        "    def check_pair_code(self, code: str) -> bool:\n        with self.lock:\n            return time.time() <= self.pair_expires and hmac.compare_digest(str(code), self.pair_code)\n\n    def _probe_jobs(self) -> dict[str, Any]:\n        if not hasattr(self, \"probe_jobs\"):\n            self.probe_jobs = {}\n        return self.probe_jobs\n\n    def create_probe_job(self, payload: dict[str, Any]) -> dict[str, Any]:\n        client_id = str(payload.get(\"client_id\", \"\"))\n        if client_id not in self.store.config.get(\"clients\", {}):\n            raise BridgeError(\"Probe client bulunamadı.\")\n        kind = str(payload.get(\"kind\", \"probe\"))\n        if kind not in {\"probe\", \"discover_todo\"}:\n            raise BridgeError(\"Probe kind desteklenmiyor.\")\n        url = normalize_url(str(payload.get(\"url\", \"\")))\n        allowed_origins = {\n            origin(str(item.get(\"url\", \"\")))\n            for item in self.store.config.get(\"sessions\", {}).values()\n            if isinstance(item, dict) and str(item.get(\"client_id\", \"\")) == client_id\n        }\n        if origin(url) not in allowed_origins:\n            raise BridgeError(\"Probe URL client için kayıtlı bir origin üzerinde değil.\")\n        markers = payload.get(\"markers\", [])\n        if not isinstance(markers, list) or len(markers) > 16:\n            raise BridgeError(\"Probe markers geçersiz.\")\n        clean_markers = [str(value)[:300] for value in markers if str(value)]\n        preferred = str(payload.get(\"preferred_marker\", \"\"))[:300]\n        job_id = secrets.token_hex(12)\n        job = {\n            \"job_id\": job_id,\n            \"client_id\": client_id,\n            \"kind\": kind,\n            \"url\": url,\n            \"markers\": clean_markers,\n            \"preferred_marker\": preferred,\n            \"status\": \"PENDING\",\n            \"created_at\": iso(),\n            \"result\": None,\n        }\n        with self.lock:\n            self._probe_jobs()[job_id] = job\n        return dict(job)\n\n    def claim_probe_job(self, client_id: str) -> dict[str, Any] | None:\n        with self.lock:\n            for job in self._probe_jobs().values():\n                if job.get(\"client_id\") == client_id and job.get(\"status\") == \"PENDING\":\n                    job[\"status\"] = \"RUNNING\"\n                    job[\"claimed_at\"] = iso()\n                    return {key: value for key, value in job.items() if key != \"result\"}\n        return None\n\n    def complete_probe_job(self, client_id: str, payload: dict[str, Any]) -> dict[str, Any]:\n        job_id = str(payload.get(\"job_id\", \"\"))\n        result = payload.get(\"result\")\n        if not isinstance(result, dict):\n            raise BridgeError(\"Probe result nesne olmalı.\")\n        if len(json_bytes(result)) > 512 * 1024:\n            raise BridgeError(\"Probe result çok büyük.\")\n        with self.lock:\n            job = self._probe_jobs().get(job_id)\n            if not isinstance(job, dict) or job.get(\"client_id\") != client_id:\n                raise BridgeError(\"Probe job bulunamadı.\")\n            job[\"result\"] = result\n            job[\"status\"] = \"DONE\"\n            job[\"completed_at\"] = iso()\n            return dict(job)\n\n    def get_probe_job(self, job_id: str) -> dict[str, Any]:\n        with self.lock:\n            job = self._probe_jobs().get(job_id)\n            if not isinstance(job, dict):\n                raise BridgeError(\"Probe job bulunamadı.\")\n            return dict(job)\n\nclass BrokerHandler",
        "browser native probe queue state",
    )

    # Extension-authenticated job polling must happen before API-token auth.
    source = replace_once(
        source,
        "        if not self._api_auth():\n            self._send_json(401, {\"error\": \"unauthorized\"})\n            return\n        if path == \"/v1/pair-code\":\n",
        "        if path == \"/v1/probe-jobs/next\":\n            if not self._is_extension_origin():\n                self._send_json(403, {\"error\": \"extension_origin_required\"})\n                return\n            client = self._client_auth({})\n            if client is None:\n                self._send_json(401, {\"error\": \"client_unauthorized\"})\n                return\n            client_id = str(self.headers.get(\"X-ULSB-Client-ID\", \"\"))\n            self._send_json(200, {\"job\": self.state.claim_probe_job(client_id)})\n            return\n        if not self._api_auth():\n            self._send_json(401, {\"error\": \"unauthorized\"})\n            return\n        match_job = re.fullmatch(r\"/v1/probe-jobs/([0-9a-f]{24})\", path)\n        if match_job:\n            try:\n                self._send_json(200, self.state.get_probe_job(match_job.group(1)))\n            except BridgeError as exc:\n                self._send_json(404, {\"error\": str(exc)})\n            return\n        if path == \"/v1/pair-code\":\n",
        "probe job GET routes",
    )

    source = replace_once(
        source,
        "            if path == \"/v1/push\":\n                if not self._is_extension_origin():\n                    self._send_json(403, {\"error\": \"extension_origin_required\"})\n                    return\n                client = self._client_auth(payload)\n                if client is None:\n                    self._send_json(401, {\"error\": \"client_unauthorized\"})\n                    return\n                stored = self.state.store.put_session(payload, client)\n                self._send_json(200, {\n                    \"ok\": True,\n                    \"name\": stored[\"name\"],\n                    \"cookie_count\": stored[\"cookie_count\"],\n                    \"updated_at\": stored[\"updated_at\"],\n                })\n                return\n            if not self._api_auth():\n",
        "            if path == \"/v1/push\":\n                if not self._is_extension_origin():\n                    self._send_json(403, {\"error\": \"extension_origin_required\"})\n                    return\n                client = self._client_auth(payload)\n                if client is None:\n                    self._send_json(401, {\"error\": \"client_unauthorized\"})\n                    return\n                stored = self.state.store.put_session(payload, client)\n                self._send_json(200, {\n                    \"ok\": True,\n                    \"name\": stored[\"name\"],\n                    \"cookie_count\": stored[\"cookie_count\"],\n                    \"updated_at\": stored[\"updated_at\"],\n                })\n                return\n            if path == \"/v1/probe-jobs/result\":\n                if not self._is_extension_origin():\n                    self._send_json(403, {\"error\": \"extension_origin_required\"})\n                    return\n                client = self._client_auth(payload)\n                if client is None:\n                    self._send_json(401, {\"error\": \"client_unauthorized\"})\n                    return\n                client_id = str(self.headers.get(\"X-ULSB-Client-ID\", \"\") or payload.get(\"client_id\", \"\"))\n                completed = self.state.complete_probe_job(client_id, payload)\n                self._send_json(200, {\"ok\": True, \"job_id\": completed[\"job_id\"]})\n                return\n            if not self._api_auth():\n",
        "probe job result POST route",
    )

    source = replace_once(
        source,
        "            if path == \"/v1/rotate-pair-code\":\n                code = self.state.rotate_pair_code()\n                self._send_json(200, {\"code\": code, \"expires_at\": iso(self.state.pair_expires)})\n                return\n            self._send_json(404, {\"error\": \"not_found\"})\n",
        "            if path == \"/v1/rotate-pair-code\":\n                code = self.state.rotate_pair_code()\n                self._send_json(200, {\"code\": code, \"expires_at\": iso(self.state.pair_expires)})\n                return\n            if path == \"/v1/probe-jobs\":\n                job = self.state.create_probe_job(payload)\n                self._send_json(200, {\"job_id\": job[\"job_id\"], \"status\": job[\"status\"]})\n                return\n            self._send_json(404, {\"error\": \"not_found\"})\n",
        "probe job submit POST route",
    )

    # Self-test the exact regression that previously allowed only one client.
    source = replace_once(
        source,
        "        client_token = json.loads(raw)[\"client_token\"]\n        passed.append(\"03-pair\")\n\n        payload = {\n",
        "        client_token = json.loads(raw)[\"client_token\"]\n        second_origin = \"chrome-extension://qrstuvwxyzabcdef\"\n        status2, raw2 = request(\n            port, \"POST\", \"/v1/pair\",\n            {\"code\": state.pair_code, \"client_id\": \"test-client-0002\", \"label\": \"Test 2\", \"browser\": \"Chromium\"},\n            ext_origin=second_origin,\n        )\n        if status2 != 200:\n            raise AssertionError(f\"second-pair={status2}:{raw2!r}\")\n        passed.append(\"03-pair-multi-client\")\n\n        payload = {\n",
        "multi-client selftest",
    )

    source = replace_once(
        source,
        "        if status == 200 and json.loads(raw)[\"cookie_count\"] == 3:\n            passed.append(\"05-push\")\n        else:\n            raise AssertionError(f\"push={status}:{raw!r}\")\n\n        status, _ = request(port, \"GET\", \"/v1/sessions\")\n",
        "        if status != 200 or json.loads(raw)[\"cookie_count\"] != 2:\n            raise AssertionError(f\"push={status}:{raw!r}\")\n        first_rows = store.list_sessions()\n        first = next((item for item in first_rows if item.get(\"name\") == \"example-session\"), None)\n        if not first or first.get(\"status\") != \"READY\" or int(first.get(\"session_cookie_count\", 0)) != 2:\n            raise AssertionError(f\"expiry-status={first!r}\")\n        legacy_payload = dict(payload)\n        legacy_payload[\"name\"] = \"legacy-session\"\n        legacy_status, legacy_raw = request(\n            port, \"POST\", \"/v1/push\", legacy_payload,\n            token=client_token, ext_origin=ext_origin, client_id=client_id,\n        )\n        if legacy_status != 200:\n            raise AssertionError(f\"legacy-push={legacy_status}:{legacy_raw!r}\")\n        current_status, current_raw = request(\n            port, \"POST\", \"/v1/push\", payload,\n            token=client_token, ext_origin=ext_origin, client_id=client_id,\n        )\n        if current_status != 200:\n            raise AssertionError(f\"current-repush={current_status}:{current_raw!r}\")\n        names = {item[\"name\"] for item in store.list_sessions()}\n        if \"example-session\" not in names or \"legacy-session\" in names:\n            raise AssertionError(f\"session-prune={sorted(names)}\")\n        passed.append(\"05-push-dedupe-expiry\")\n\n        status, _ = request(port, \"GET\", \"/v1/sessions\")\n",
        "session pruning and expiry selftest",
    )

    source = replace_once(
        source,
        "        print(f\"Pair code: {state.pair_code} (10 dakika)\")\n",
        "        print(f\"Pair code: {state.pair_code} (10 dakika, sınırsız yerel eşleşme)\")\n",
        "pair code status text",
    )

    return source


def main() -> int:
    DIST.mkdir(exist_ok=True)
    broker_source = (ROOT / "broker" / "session_bridge.py").read_text(encoding="utf-8")
    broker_runtime = build_broker_runtime(broker_source)

    pyz = DIST / f"session-bridge-v{VERSION}.pyz"
    with zipfile.ZipFile(pyz, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("__main__.py", broker_runtime)

    zip_directory(ROOT / "chromium-extension", DIST / f"chromium-extension-v{VERSION}.zip")
    zip_directory(ROOT / "firefox-extension", DIST / f"firefox-extension-v{VERSION}.zip")

    artifacts = [
        pyz,
        DIST / f"chromium-extension-v{VERSION}.zip",
        DIST / f"firefox-extension-v{VERSION}.zip",
    ]
    sums = "\n".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}" for path in artifacts) + "\n"
    (DIST / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")
    for path in artifacts:
        print(path.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
