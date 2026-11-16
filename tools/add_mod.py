"""Add a mod someone shared: the launcher's "Add a mod" button, or

  python tools/add_mod.py <mod .zip>

The zip is one mod folder, as Mod Studio's Export button makes. It goes into mods/; a mod with the same name is replaced
(the old copy is kept in mods/_replaced/). If it clashes with a mod you have on, it is added turned off.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gfserver import mod_share  # noqa: E402


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        mod_share.install(sys.argv[1])
    except mod_share.ShareError as e:
        sys.exit(f"Not added: {e}")
    print("Build mods (on the Play tab or here) to put it into the game.")


if __name__ == "__main__":
    main()
