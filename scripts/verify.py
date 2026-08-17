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
    checks.append("30 local runtime checks including multi-client pairing")

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
        require('id="sites"' in popup_html, f"{extension}: site list missing")
        require("activeSiteInfo" in popup_js, f"{extension}: active page metadata discovery missing")
        require('className = "site-name"' in popup_js, f"{extension}: automatic title UI missing")
        require('className = "site-url"' in popup_js, f"{extension}: URL UI missing")
        require('title: String(site.title || "")' in background_js, f"{extension}: title sync missing")
        for forbidden in forbidden_popup_ids:
            require(forbidden not in popup_html, f"{extension}: legacy popup field remains: {forbidden}")
    checks.append("Simplified Title + URL extension UI contract")

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
    checks.append("Reusable pairing and title-aware broker runtime")

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
