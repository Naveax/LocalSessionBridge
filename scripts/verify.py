#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
import py_compile
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BROKER = ROOT / "broker" / "session_bridge.py"
PYZ = ROOT / "dist" / "session-bridge-v1.0.0.pyz"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    checks: list[str] = []

    py_compile.compile(str(BROKER), doraise=True)
    checks.append("Python compilation")

    with tempfile.TemporaryDirectory(prefix="ulsb-verify-") as temp_dir:
        report = Path(temp_dir) / "selftest.json"
        result = subprocess.run(
            [sys.executable, str(PYZ), "selftest", "--repeat", "3", "--report", str(report)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        require(result.returncode == 0, result.stdout + result.stderr)
        report_data = json.loads(report.read_text(encoding="utf-8"))
        require(report_data["all_passed"] is True, "self-test report failed")
        for iteration in report_data["results"]:
            require("03-pair-multi-client" in iteration["passed"], "reusable pair-code regression test missing")
            require("05-push-dedupe-expiry" in iteration["passed"], "session pruning / expiry regression test missing")
    checks.append("Local runtime checks including multi-client pairing, pruning, and expiry semantics")

    forbidden_popup_ids = (
        'id="brokerUrl"',
        'id="profileLabel"',
        'id="siteName"',
        'id="siteUrl"',
        'id="storeId"',
        'id="keepaliveUrl"',
        'id="keepaliveMinutes"',
        'id="syncAllButton"',
        'id="enableAllButton"',
        'id="disableAllButton"',
    )

    for extension in ("chromium-extension", "firefox-extension"):
        manifest = json.loads((ROOT / extension / "manifest.json").read_text(encoding="utf-8"))
        require(manifest["manifest_version"] == 3, f"{extension}: manifest version")
        require("activeTab" in manifest["permissions"], f"{extension}: activeTab permission")
        require("cookies" in manifest["permissions"], f"{extension}: cookies permission")
        require(manifest["optional_host_permissions"] == ["http://*/*", "https://*/*"], f"{extension}: host permissions")

        popup_html = (ROOT / extension / "popup.html").read_text(encoding="utf-8")
        popup_js = (ROOT / extension / "popup.js").read_text(encoding="utf-8")
        background_js = (ROOT / extension / "background.js").read_text(encoding="utf-8")

        require('id="pairCode"' in popup_html, f"{extension}: pair code missing")
        require('id="currentSite"' in popup_html, f"{extension}: current-site add area missing")
        require('id="siteCount"' in popup_html, f"{extension}: site counter missing")
        require('id="sites"' in popup_html, f"{extension}: browser-local site list missing")

        require("const UI_VERSION = 3" in popup_js, f"{extension}: unlimited registry migration missing")
        require("function activeSiteInfo" in popup_js, f"{extension}: active page metadata discovery missing")
        require("function siteKey" in popup_js, f"{extension}: full URL site key missing")
        require("return siteKey(site.url) === wanted" in popup_js, f"{extension}: sites are not keyed by full URL")
        require('add.textContent = "Ekle"' in popup_js, f"{extension}: explicit add button missing")
        require("state.sites.push(site)" in popup_js, f"{extension}: multi-site append path missing")
        require("tarayıcıya özel liste" in popup_js, f"{extension}: browser-local registry marker missing")
        require('className = "site-name"' in popup_js, f"{extension}: automatic title UI missing")
        require('className = "site-url"' in popup_js, f"{extension}: URL UI missing")
        require("siteOrigin(site.url) === wanted" not in popup_js, f"{extension}: old one-site-per-origin bug returned")
        require('title: String(site.title || "")' in background_js, f"{extension}: title sync missing")

        for forbidden in forbidden_popup_ids:
            require(forbidden not in popup_html, f"{extension}: legacy popup field remains: {forbidden}")
    checks.append("Unlimited browser-local Title + URL registry contract")

    node = shutil.which("node")
    if node:
        for path in (
            ROOT / "chromium-extension" / "background.js",
            ROOT / "chromium-extension" / "popup.js",
            ROOT / "firefox-extension" / "background.js",
            ROOT / "firefox-extension" / "popup.js",
        ):
            result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True)
            require(result.returncode == 0, result.stderr)
        checks.append("JavaScript syntax")

    with zipfile.ZipFile(PYZ) as archive:
        require(archive.namelist() == ["__main__.py"], "PYZ structure")
        runtime_source = archive.read("__main__.py").decode("utf-8")
    require(runtime_source.count("self.state.rotate_pair_code()") == 1, "pair code is still consumed after pairing")
    require('title = str(payload.get("title", "")' in runtime_source, "broker title metadata missing")
    require('"title": title' in runtime_source, "broker title persistence missing")
    require("stale_snapshot_files = []" in runtime_source, "same-client same-url session pruning missing")
    require('str(old_item.get("client_id", "")) != snapshot["client_id"]' in runtime_source, "session pruning lost client isolation")
    require("if expiry <= now:" in runtime_source, "expired cookies are still retained")
    require('"latest_expiry": max(expiries) if expiries else None' in runtime_source, "latest expiry metadata missing")
    require("elif session_cookie_count > 0:" in runtime_source, "session-cookie readiness semantics missing")
    require('row["status"] = "EXPIRING_SOON"' in runtime_source, "persistent expiry status missing")
    checks.append("Reusable pairing, migration-safe pruning, and expiry-aware broker runtime")

    source = BROKER.read_text(encoding="utf-8")
    require('value not in {"127.0.0.1", "::1", "localhost"}' in source, "loopback guard missing")
    require('self.headers.get("Cookie"' not in source, "cookie logging path detected")
    checks.append("Security invariants")

    print(f"PASS: {len(checks)} verification groups")
    for check in checks:
        print(f"- {check}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
