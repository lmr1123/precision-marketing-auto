#!/usr/bin/env python3
"""
build_release.py - Build the app/data deployment package.

Usage:
  python scripts/deploy/build_release.py [--platform win|mac|all] [--version 1.0.0]

Output:
  release/PrecisionMarketingAuto-v{version}-win.zip
  release/PrecisionMarketingAuto-v{version}-mac.zip

Package structure:
  PrecisionMarketingAuto/
  ├── start.bat  (or start.command for Mac)
  ├── app/
  │   ├── VERSION.txt
  │   ├── precision-auto-playwright-batch.py
  │   ├── ui_app/
  │   ├── browser_extension/
  │   ├── scripts/deploy/
  │   ├── data/plans.csv
  │   ├── requirements.txt
  │   └── requirements-ui.txt
  └── data/
      └── .gitkeep
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RELEASE_DIR = ROOT / "release"
RUNTIME_CACHE_DIR = RELEASE_DIR / "win-runtime-cache"
WIN_PYTHON_VERSION = "3.11.9"
WIN_PYTHON_ZIP_NAME = f"python-{WIN_PYTHON_VERSION}-embed-amd64.zip"
WIN_PYTHON_URL = f"https://www.python.org/ftp/python/{WIN_PYTHON_VERSION}/{WIN_PYTHON_ZIP_NAME}"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
RUNTIME_VERSION = f"win-python-{WIN_PYTHON_VERSION}-wheelhouse-v2"

# Files to include in app/ (relative to ROOT)
APP_FILES = [
    "precision-auto-playwright-batch.py",
    "requirements.txt",
    "requirements-ui.txt",
    "data/plans.csv",
    "ui_app/server.py",
    "ui_app/text_plan_parser.py",
    "browser_extension/review_assistant/manifest.json",
    "browser_extension/review_assistant/service_worker.js",
    "browser_extension/review_assistant/content_script.js",
    "browser_extension/review_assistant/sidepanel.html",
    "browser_extension/review_assistant/sidepanel.js",
    "browser_extension/review_assistant/sidepanel.css",
]

# Deploy scripts (from scripts/deploy/ into app/scripts/deploy/)
DEPLOY_SCRIPTS = [
    "auto_update.ps1",
    "auto_update.sh",
    "start.bat",
    "start.command",
]


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_dir(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def download_if_missing(url: str, dst: Path) -> None:
    if dst.exists() and dst.stat().st_size > 0:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    print(f"  Downloading {url} ...")
    urllib.request.urlretrieve(url, dst)


def prepare_win_runtime_assets() -> Path:
    """Prepare Windows runtime bootstrap assets on the build machine.

    The package keeps runtime/ outside app/ so app auto-updates do not delete it.
    We include the Python embeddable zip and a Windows wheelhouse; first launch
    extracts and installs locally without reaching the internet.
    """
    runtime_dir = RUNTIME_CACHE_DIR
    wheelhouse = runtime_dir / "wheelhouse"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    wheelhouse.mkdir(parents=True, exist_ok=True)

    download_if_missing(WIN_PYTHON_URL, runtime_dir / WIN_PYTHON_ZIP_NAME)
    download_if_missing(GET_PIP_URL, runtime_dir / "get-pip.py")

    marker = runtime_dir / f".wheelhouse_ready_{RUNTIME_VERSION}"
    if not marker.exists():
        print("  Preparing Windows offline wheelhouse ...")
        for old_marker in runtime_dir.glob(".wheelhouse_ready_*"):
            old_marker.unlink(missing_ok=True)
        for old_wheel in wheelhouse.glob("*.whl"):
            old_wheel.unlink()
        cmd = [
            sys.executable,
            "-m",
            "pip",
            "download",
            "--dest",
            str(wheelhouse),
            "--only-binary=:all:",
            "--platform",
            "win_amd64",
            "--python-version",
            "3.11",
            "--implementation",
            "cp",
            "--abi",
            "cp311",
            "-r",
            str(ROOT / "requirements.txt"),
            "-r",
            str(ROOT / "requirements-ui.txt"),
            "colorama",
            "pip",
            "setuptools",
            "wheel",
        ]
        subprocess.check_call(cmd)
        marker.write_text("ok\n", encoding="utf-8")

    (runtime_dir / "RUNTIME_VERSION.txt").write_text(RUNTIME_VERSION + "\n", encoding="utf-8")
    return runtime_dir


def get_version(args_version: str | None) -> str:
    version_file = ROOT / "VERSION.txt"
    if args_version:
        ver = args_version
    elif version_file.exists():
        ver = version_file.read_text().strip()
    else:
        ver = "1.0.0"
    # Write back so it's tracked
    version_file.write_text(ver + "\n")
    return ver


def build_package(platform: str, version: str, include_win_runtime: bool = False) -> Path:
    """Build a platform-specific zip package."""
    pkg_name = f"PrecisionMarketingAuto-v{version}"
    stage_dir = RELEASE_DIR / f"stage-{platform}"
    pkg_root = stage_dir / pkg_name

    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True)

    # --- app/ directory ---
    app_dir = pkg_root / "app"
    app_dir.mkdir(parents=True)

    # VERSION.txt
    (app_dir / "VERSION.txt").write_text(version + "\n")

    # Source files
    for rel in APP_FILES:
        src = ROOT / rel
        if not src.exists():
            print(f"  WARNING: Skipping missing file: {rel}")
            continue
        copy_file(src, app_dir / rel)

    # Deploy scripts into app/scripts/deploy/
    deploy_src = ROOT / "scripts" / "deploy"
    for script_name in DEPLOY_SCRIPTS:
        src = deploy_src / script_name
        if src.exists():
            copy_file(src, app_dir / "scripts" / "deploy" / script_name)

    # Copy ui_app templates if they exist
    templates_dir = ROOT / "ui_app" / "templates"
    if templates_dir.exists():
        copy_dir(templates_dir, app_dir / "ui_app" / "templates")

    # --- data/ directory (empty, just a placeholder) ---
    data_dir = pkg_root / "data"
    data_dir.mkdir(parents=True)
    (data_dir / ".gitkeep").write_text("")

    # --- Runtime directory (Windows strong one-click package) ---
    if platform == "win" and include_win_runtime:
        runtime_src = prepare_win_runtime_assets()
        runtime_dst = pkg_root / "runtime"
        runtime_dst.mkdir(parents=True, exist_ok=True)
        for rel in [WIN_PYTHON_ZIP_NAME, "get-pip.py", "RUNTIME_VERSION.txt"]:
            copy_file(runtime_src / rel, runtime_dst / rel)
        copy_dir(runtime_src / "wheelhouse", runtime_dst / "wheelhouse")

    # --- Platform launcher ---
    if platform == "win":
        copy_file(deploy_src / "start.bat", pkg_root / "start.bat")
    else:
        copy_file(deploy_src / "start.command", pkg_root / "start.command")
        # Make executable in zip
        (pkg_root / "start.command").chmod(0o755)
        (app_dir / "scripts" / "deploy" / "auto_update.sh").chmod(0o755)

    # --- Create zip ---
    zip_path = RELEASE_DIR / f"PrecisionMarketingAuto-v{version}-{platform}.zip"
    if zip_path.exists():
        zip_path.unlink()

    print(f"  Creating {zip_path.name} ...")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fp in sorted(pkg_root.rglob("*")):
            if fp.is_file():
                arcname = fp.relative_to(stage_dir)
                zf.write(fp, arcname)

    # Cleanup staging
    shutil.rmtree(stage_dir)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"  Built: {zip_path} ({size_mb:.1f} MB)")
    return zip_path


def generate_latest_json(version: str, packages: dict[str, Path]) -> None:
    """Generate latest.json for Tencent Cloud deployment."""
    # 部署地址：获取域名后改为 "https://pm-auto.dslyy.com"
    base_url = os.getenv("PM_BASE_URL", "http://49.232.195.165")
    latest = {
        "version": version,
        "changelog": f"Release v{version}",
        "runtime_version": RUNTIME_VERSION,
    }
    # Windows package URL (primary)
    if "win" in packages:
        latest["url"] = f"{base_url}/releases/{packages['win'].name}"
        latest["url_win"] = f"{base_url}/releases/{packages['win'].name}"
    if "mac" in packages:
        latest["url_mac"] = f"{base_url}/releases/{packages['mac'].name}"

    json_path = RELEASE_DIR / "latest.json"
    json_path.write_text(json.dumps(latest, indent=2, ensure_ascii=False) + "\n")
    print(f"  Generated: {json_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deployment package")
    parser.add_argument("--platform", choices=["win", "mac", "all"], default="all")
    parser.add_argument("--version", default=None, help="Version string (e.g. 1.0.1)")
    parser.add_argument(
        "--no-win-runtime",
        action="store_true",
        help="Build Windows package without bundled runtime assets (debug/lightweight only)",
    )
    args = parser.parse_args()

    RELEASE_DIR.mkdir(exist_ok=True)
    version = get_version(args.version)
    print(f"Building PrecisionMarketingAuto v{version}")

    platforms = ["win", "mac"] if args.platform == "all" else [args.platform]
    packages = {}

    for plat in platforms:
        print(f"\n[{plat.upper()}] Building package ...")
        packages[plat] = build_package(
            plat,
            version,
            include_win_runtime=(plat == "win" and not args.no_win_runtime),
        )

    print(f"\nGenerating latest.json ...")
    generate_latest_json(version, packages)

    print("\nDone. Upload the .zip and latest.json to your Tencent Cloud server.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
