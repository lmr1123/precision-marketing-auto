#!/usr/bin/env python3
"""
Build a single-file Windows delivery zip for business users.
Usage:
  python scripts/windows/build_windows_release_zip.py
"""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "release"
STAGE_DIR = OUT_DIR / "windows-oneclick"
PACKAGE_ROOT = STAGE_DIR / "precision-marketing-auto-windows"
ZIP_PATH = OUT_DIR / "precision-marketing-auto-windows-oneclick.zip"


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def main() -> int:
    if STAGE_DIR.exists():
        shutil.rmtree(STAGE_DIR)
    STAGE_DIR.mkdir(parents=True, exist_ok=True)

    files_to_copy = [
        "precision-auto-playwright-batch.py",
        "requirements.txt",
        "requirements-ui.txt",
        "README.md",
        "progress.md",
        "data/plans.csv",
        "data/ui-test/plans-moments-local2.csv",
        "data/ui-test/plans-moments-images-sample.csv",
        "ui_app/server.py",
        "scripts/windows/windows_start_ui.bat",
        "scripts/windows/windows_update.bat",
        "scripts/windows/windows_install_or_update.ps1",
        "scripts/windows/install_or_update_from_github.bat",
        "scripts/windows/create_desktop_shortcut.ps1",
        "scripts/windows/build_windows_exe.bat",
        "scripts/windows/windows_ui_starter.py",
        "docs/字段逻辑说明.md",
        "docs/业务安装包与页面操作手册.md",
        "docs/screenshots/ui-home-light.png",
        "docs/screenshots/ui-advanced-light.png",
        "docs/screenshots/ui-advanced-dark.png",
        "docs/screenshots/ui-tasklist-light.png",
        "docs/screenshots/ui-material-modal-dark.png",
        "docs/screenshots/ui-log-modal-dark.png",
    ]

    for rel in files_to_copy:
        src = ROOT / rel
        if not src.exists():
            raise FileNotFoundError(f"Missing required file: {src}")
        copy_file(src, PACKAGE_ROOT / rel)

    quick_start = PACKAGE_ROOT / "WINDOWS_QUICK_START.txt"
    quick_start.write_text(
        "\n".join(
            [
                "精准营销自动化工具 - Windows 快速开始",
                "",
                "【本地启动】",
                "1) 双击：scripts\\windows\\windows_start_ui.bat",
                "2) 首次会自动安装依赖并打开：http://127.0.0.1:8790",
                "",
                "【更新版本】",
                "1) 双击：scripts\\windows\\windows_update.bat",
                "2) 或使用：scripts\\windows\\install_or_update_from_github.bat",
                "",
                "说明：",
                "- 需要本机安装 Python 3.11+",
                "- Chrome 需可访问企业内网/VPN",
                "- 朋友圈图片可在 UI 页面直接上传，无需手工改 CSV 路径",
                "- 支持自动创建桌面快捷方式（安装/更新脚本会自动处理）",
            ]
        ),
        encoding="utf-8",
    )

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fp in PACKAGE_ROOT.rglob("*"):
            if fp.is_file():
                zf.write(fp, fp.relative_to(STAGE_DIR))

    print(f"Built: {ZIP_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
