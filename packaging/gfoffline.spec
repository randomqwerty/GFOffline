# PyInstaller spec for the release: two programs sharing one Python (see frozen_main.py). Run through build_exe.py.
import ast
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

HERE = Path(SPECPATH)
REPO = HERE.parent
APP_FILES = [REPO / "launcher.pyw", REPO / "play.py", REPO / "run.py", *(REPO / "gfserver").glob("*.py"),
             *(REPO / "tools").glob("*.py"), *(REPO / "tools" / "modstudio").glob("*.py")]
# The app itself stays plain files next to the programs, so PyInstaller can't see what it imports: list that here.
LOCAL = {p.stem for p in APP_FILES} | {"gfserver"}


def imported_modules():
    found = set()
    for path in APP_FILES:
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if isinstance(node, ast.Import):
                found |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
                found.add(node.module)
                found |= {f"{node.module}.{a.name}" for a in node.names}       # "from tkinter import ttk" is a module
    return sorted(m for m in found if m.split(".")[0] not in LOCAL)


datas, binaries, hidden = [], [], imported_modules()
for package in ("UnityPy", "texture2ddecoder", "etcpak", "archspec", "fmod_toolkit", "astc_encoder", "Crypto"):
    try:
        d, b, h = collect_all(package)
    except Exception:
        continue
    datas += d
    binaries += b
    hidden += h

a = Analysis([str(HERE / "frozen_main.py")], pathex=[], binaries=binaries, datas=datas, hiddenimports=hidden,
             excludes=["pytest", "IPython", "matplotlib", "scipy", "pandas", "capstone"], noarchive=False)
pyz = PYZ(a.pure)
launcher = EXE(pyz, a.scripts, [], exclude_binaries=True, name="GF Offline", console=False, upx=False)
runner = EXE(pyz, a.scripts, [], exclude_binaries=True, name="gfpython", console=True, upx=False)
COLLECT(launcher, runner, a.binaries, a.datas, strip=False, upx=False, name="GF-Offline")
