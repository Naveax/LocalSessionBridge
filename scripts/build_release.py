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
    # Keep session cookies and only future-dated persistent cookies.
    source = replace_once(
        source,
        "            expiry = item.get(\"expirationDate\")\n            if isinstance(expiry, (int, float)):\n                expiry = float(expiry)\n                if expiry > now:\n                    expiries.append(expiry)\n            else:\n                expiry = None\n                session_count += 1\n            clean.append({\n",
        "            expiry = item.get(\"expirationDate\")\n            if isinstance(expiry, (int, float)):\n                expiry = float(expiry)\n                if expiry <= now:\n                    continue\n                expiries.append(expiry)\n            else:\n                expiry = None\n                session_count += 1\n            clean.append({\n",
        "expired cookie filtering",
    )

    # Keep both earliest and latest expiry for diagnostics, but overall session
    # viability is based on whether any valid credential remains. Session
    # cookies make the session READY; persistent-only sessions use latest_expiry.
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

    # Migration-safe registry semantics: if the same browser extension client
    # pushes the same full URL using a newer internal session ID, keep only the
    # newest ID. Different clients/browsers remain independent even for the
    # same URL.
    source = replace_once(
        source,
        "        with self.lock:\n            self.config[\"sessions\"][name] = metadata\n            self._save()\n        return dict(metadata)\n",
        "        stale_snapshot_files = []\n        with self.lock:\n            for old_name, old_item in list(self.config[\"sessions\"].items()):\n                if old_name == name or not isinstance(old_item, dict):\n                    continue\n                if str(old_item.get(\"client_id\", \"\")) != snapshot[\"client_id\"]:\n                    continue\n                try:\n                    same_url = normalize_url(str(old_item.get(\"url\", \"\"))) == url\n                except BridgeError:\n                    same_url = False\n                if not same_url:\n                    continue\n                old_file = str(old_item.get(\"snapshot_file\", \"\"))\n                if old_file:\n                    stale_snapshot_files.append(old_file)\n                self.config[\"sessions\"].pop(old_name, None)\n            self.config[\"sessions\"][name] = metadata\n            self._save()\n        for stale_file in stale_snapshot_files:\n            try:\n                (self.snapshots_dir / stale_file).unlink()\n            except FileNotFoundError:\n                pass\n        return dict(metadata)\n",
        "same-client same-url session pruning",
    )

    # Self-test the exact regression that previously allowed only one client
    # to consume the pair code.
    source = replace_once(
        source,
        "        client_token = json.loads(raw)[\"client_token\"]\n        passed.append(\"03-pair\")\n\n        payload = {\n",
        "        client_token = json.loads(raw)[\"client_token\"]\n        second_origin = \"chrome-extension://qrstuvwxyzabcdef\"\n        status2, raw2 = request(\n            port, \"POST\", \"/v1/pair\",\n            {\"code\": state.pair_code, \"client_id\": \"test-client-0002\", \"label\": \"Test 2\", \"browser\": \"Chromium\"},\n            ext_origin=second_origin,\n        )\n        if status2 != 200:\n            raise AssertionError(f\"second-pair={status2}:{raw2!r}\")\n        passed.append(\"03-pair-multi-client\")\n\n        payload = {\n",
        "multi-client selftest",
    )

    # Exercise migration cleanup and expiry semantics. The deliberately expired
    # cookie in the fixture must be discarded; two session cookies remain and
    # the resulting session must be READY.
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
