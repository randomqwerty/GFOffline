"""Rebuild client_patch/*.lua into the game copy: the patch bundle, the resource config, then the copy into the game.

  python tools/build_patch.py

play.py calls ensure() before each start, which rebuilds only when client_patch/ or the server address changed since
the last build (STAMP in the game folder), so an updated install brings its new patch files into the game.

Needs UnityPy and the original bundle (kept by tools/setup_game.py, or in an archive). Refuses to write inside a Steam library.
"""
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import build_mods  # noqa: E402
from gfserver import config  # noqa: E402


STAMP = "gf_offline_patch.txt"


def stamp():
    """What the built patch depends on: every client_patch/*.lua and the server address it is filled in with."""
    h = hashlib.sha256(config.PUBLIC_BASE.encode("utf-8"))
    for f in sorted((ROOT / "client_patch").glob("*.lua")):
        h.update(f.name.encode("utf-8") + b"\x00" + f.read_bytes() + b"\x00")
    return h.hexdigest()


def _stamp_file():
    return config.GAME_DIR / STAMP


def up_to_date():
    try:
        return _stamp_file().read_text("utf-8").strip() == stamp()
    except OSError:
        return False


def ensure():
    """Rebuild unless the game copy already has this patch. True if it was rebuilt."""
    if up_to_date():
        return False
    main()
    return True


def main():
    found = config.original_bundles("*assettextlpatch.ab")
    if not found:
        sys.exit("The original patch bundle wasn't found: press Set up in the launcher")
    src = found[-1]
    for args in (["build_lpatch.py", str(src)], ["build_resconfig.py"]):
        subprocess.run([sys.executable, str(ROOT / "tools" / args[0]), *args[1:]], check=True, cwd=ROOT)
    build_mods.copy_into_game(ROOT / "build" / src.name, src.name)
    _stamp_file().write_text(stamp() + "\n", "utf-8")
    print("done; it applies the next time the game starts")


if __name__ == "__main__":
    main()
