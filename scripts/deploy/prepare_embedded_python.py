#!/usr/bin/env python3
"""
prepare_embedded_python.py - Download and configure embedded Python for Windows.

Run this ONCE on a Windows machine (or cross-compile) to create:
  app/python/   - Python 3.11 embeddable package with pip + site-packages

Usage (on Windows):
  python scripts/deploy/prepare_embedded_python.py

After running, the app/python/ directory will be self-contained.
The build_release.py will include it in the final package.

Note: This script is intended to run on the TARGET platform (Windows).
For cross-platform builds, run it on each platform separately.
"""

import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON_VERSION = "3.11.9"
PYTHON_URL = (
    f"https://www.python.org/ftp/python/{PYTHON_VERSION}/"
    f"python-{PYTHON_VERSION}-embed-amd64.zip"
)
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"

PYTHON_DIR = ROOT / "app" / "python"


def download(url: str, dest: Path) -> None:
    print(f"  Downloading {url} ...")
    urllib.request.urlretrieve(url, dest)
    print(f"  Saved: {dest} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")


def main() -> int:
    if sys.platform != "win32":
        print("WARNING: This script is designed for Windows.")
        print("Embedded Python packages are platform-specific.")
        print("Run this on a Windows machine for best results.")
        ans = input("Continue anyway? [y/N] ").strip().lower()
        if ans != "y":
            return 1

    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="pm-embed-py-"))

    try:
        # Step 1: Download embedded Python
        print(f"[1/4] Downloading Python {PYTHON_VERSION} embeddable ...")
        zip_path = tmp / "python-embed.zip"
        download(PYTHON_URL, zip_path)

        # Step 2: Extract
        print(f"[2/4] Extracting to {PYTHON_DIR} ...")
        if PYTHON_DIR.exists():
            shutil.rmtree(PYTHON_DIR)
        PYTHON_DIR.mkdir(parents=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(PYTHON_DIR)

        # Step 3: Enable pip (modify ._pth file)
        print("[3/4] Enabling pip support ...")
        pth_files = list(PYTHON_DIR.glob("*._pth"))
        for pth in pth_files:
            content = pth.read_text()
            # Uncomment "import site" to enable pip
            content = content.replace("#import site", "import site")
            # Add Lib/site-packages
            content += "\nLib\\site-packages\n"
            pth.write_text(content)
            print(f"  Updated: {pth.name}")

        # Step 4: Install pip
        print("[4/4] Installing pip ...")
        get_pip = tmp / "get-pip.py"
        download(GET_PIP_URL, get_pip)

        python_exe = PYTHON_DIR / "python.exe"
        if not python_exe.exists():
            python_exe = PYTHON_DIR / "python"  # macOS/Linux fallback

        subprocess.check_call([
            str(python_exe), str(get_pip),
            "--no-warn-script-location"
        ])

        # Install project dependencies
        print("\nInstalling project dependencies ...")
        pip = PYTHON_DIR / "Scripts" / "pip.exe"
        if not pip.exists():
            pip = str(python_exe) + " -m pip"
        else:
            pip = str(pip)

        req_files = []
        for rf in ["requirements.txt", "requirements-ui.txt"]:
            p = ROOT / rf
            if p.exists():
                req_files.extend(["-r", str(p)])

        if req_files:
            subprocess.check_call(f"{pip} install {' '.join(req_files)} --no-warn-script-location", shell=True)

        # Install Playwright browsers
        print("\nInstalling Playwright Chromium ...")
        subprocess.check_call(f"{pip} install playwright --no-warn-script-location", shell=True)
        subprocess.check_call(f"{str(python_exe)} -m playwright install chromium", shell=True)

        print(f"\nDone! Embedded Python ready at: {PYTHON_DIR}")
        print(f"Size: {sum(f.stat().st_size for f in PYTHON_DIR.rglob('*') if f.is_file()) / 1024 / 1024:.0f} MB")

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
