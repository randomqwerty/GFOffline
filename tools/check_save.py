"""What your next login does to your save for the mods that are on now (gfserver/mod_save.py):
what a mod that is off or gone gave you is put aside, and what was put aside comes back once
its mod is on again. Changes nothing itself; the server does it when you log in.

  python tools/check_save.py

Build mods runs it at the end; the launcher has it under "Your account".
"""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gfserver import config, mod_save  # noqa: E402


def saves(folder=None):
    folder = Path(folder or config.SAVE_DIR)
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.glob("*.json") if p.stem.isdigit())


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    found = saves()
    if not found:
        print("your save: none yet")
        return
    tables = mod_save.Tables()
    for p in found:
        try:
            state = json.loads(p.read_text("utf-8"))
        except ValueError:
            print(f"your save {p.stem}: can't be read")
            continue
        change = mod_save.reconcile(copy.deepcopy(state), tables)
        lines = mod_save.describe(change)
        waiting = len((state.get(mod_save.ASIDE) or {}).get("records") or []) - len(change["back"])
        if not lines:
            print(f"your save {p.stem}: fits the mods that are on"
                  + (f" ({waiting} entr{'y' if waiting == 1 else 'ies'} still put aside for mods that are off)" if waiting > 0 else ""))
        for line in lines:
            print(f"your save {p.stem}, at the next login: {line}")


if __name__ == "__main__":
    main()
