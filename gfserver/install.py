"""Where the game is: finding the Steam install, and the folders chosen in the launcher (install.json).

  source   the game as installed, only ever read. Usually Steam's, or any other folder holding the game.
  game     the copy that gets patched and played. It may be the source folder too, unless that is a Steam library.
  archive  optional: a folder made by tools/archive_live.py, used in place of downloading the resource config.
"""
import json
import re
from pathlib import Path

from . import config

GAME_EXE = "GirlsFrontLine.exe"


def load():
    return config.install_settings()


def save(**values):
    data = {**config.install_settings(), **{k: str(v) if isinstance(v, Path) else v for k, v in values.items()}}
    config.INSTALL_FILE.write_text(json.dumps(data, indent=1), "utf-8")
    return data


def in_steam_library(path):
    return "steamapps" in (p.lower() for p in Path(path).resolve().parts)


def _steam_roots():
    try:
        import winreg
    except ImportError:
        return []
    roots = []
    for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
        try:
            with winreg.OpenKey(hive, key) as k:
                roots.append(Path(winreg.QueryValueEx(k, value)[0]))
        except OSError:
            pass
    return roots


def steam_libraries():
    """Every Steam library folder: Steam's own, and those listed in its libraryfolders.vdf."""
    found = []
    for root in _steam_roots():
        found.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        try:
            found += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text("utf-8", "replace"))]
        except OSError:
            pass
    return list(dict.fromkeys(found))


def find_steam_game():
    """The game's folder in a Steam library, or None."""
    for lib in steam_libraries():
        common = lib / "steamapps" / "common"
        try:
            hits = sorted(p for p in common.iterdir() if (p / GAME_EXE).is_file())
        except OSError:
            continue
        if hits:
            return hits[0]
    return None


def source_problem(source):
    """Why this folder can't be used as the game, in the player's words, or None."""
    source = Path(source)
    if not (source / GAME_EXE).is_file():
        return f"{GAME_EXE} isn't in that folder."
    if not (config.pc_dir(source) / "stc" / "stc_data.dat").is_file():
        return "The game's data isn't in that folder yet. Start the game from Steam once and let it finish downloading, then try again."
    return None


def ready():
    """Has setup finished for the folders in install.json?"""
    return bool(load().get("ready")) and (config.GAME_DIR / GAME_EXE).is_file()
