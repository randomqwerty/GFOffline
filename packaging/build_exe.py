"""Build the release that needs no Python installed: dist/GF-Offline/ and its zip.

  pip install -r requirements.txt pyinstaller
  python packaging/build_exe.py

Use Python 3.10.1 or newer: a bug in 3.10.0 stops PyInstaller.
"""
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERSION = (REPO / "gfserver" / "version.py").read_text("utf-8").split('VERSION = "')[1].split('"')[0]   # the release tag, v<VERSION>
DIST = REPO / "dist"
APP = ["gfserver", "client_patch", "data", "mods", "tools", "launcher.pyw", "play.py", "run.py", "README.md", "requirements.txt"]


def main():
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(DIST), "--workpath", str(REPO / "build" / "pyinstaller"),
                    str(REPO / "packaging" / "gfoffline.spec")], check=True, cwd=REPO)
    out = DIST / "GF-Offline"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in APP:
        src = REPO / name
        if src.is_dir():
            shutil.copytree(src, out / name, ignore=ignore, dirs_exist_ok=True)
        else:
            shutil.copy2(src, out / name)
    archive = shutil.make_archive(str(DIST / f"GF-Offline-{VERSION}-win64"), "zip", DIST, "GF-Offline")
    print(f"built {out}\nzipped {archive}")


if __name__ == "__main__":
    main()
