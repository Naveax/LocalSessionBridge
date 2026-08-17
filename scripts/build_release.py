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

    # Self-test the exact regression that previously allowed only one client
    # to consume the pair code.
    source = replace_once(
        source,
        "        client_token = json.loads(raw)[\"client_token\"]\n        passed.append(\"03-pair\")\n\n        payload = {\n",
        "        client_token = json.loads(raw)[\"client_token\"]\n        second_origin = \"chrome-extension://qrstuvwxyzabcdef\"\n        status2, raw2 = request(\n            port, \"POST\", \"/v1/pair\",\n            {\"code\": state.pair_code, \"client_id\": \"test-client-0002\", \"label\": \"Test 2\", \"browser\": \"Chromium\"},\n            ext_origin=second_origin,\n        )\n        if status2 != 200:\n            raise AssertionError(f\"second-pair={status2}:{raw2!r}\")\n        passed.append(\"03-pair-multi-client\")\n\n        payload = {\n",
        "multi-client selftest",
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
