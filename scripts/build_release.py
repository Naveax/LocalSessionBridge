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


def main() -> int:
    DIST.mkdir(exist_ok=True)
    broker_source = (ROOT / "broker" / "session_bridge.py").read_text(encoding="utf-8")
    pyz = DIST / f"session-bridge-v{VERSION}.pyz"
    with zipfile.ZipFile(pyz, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr("__main__.py", broker_source)

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
