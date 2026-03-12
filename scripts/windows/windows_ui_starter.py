import os
import subprocess
import sys
import webbrowser
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    python_exe = repo_root / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        print("Missing .venv\\Scripts\\python.exe. Please run windows_start_ui.bat once first.")
        input("Press Enter to exit...")
        return 1

    os.chdir(repo_root)
    url = "http://127.0.0.1:8790"
    try:
        webbrowser.open(url)
    except Exception:
        pass

    cmd = [
        str(python_exe),
        "-m",
        "uvicorn",
        "ui_app.server:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8790",
    ]
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
