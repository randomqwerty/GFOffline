"""Get the game ready for offline play. Run from the launcher's Set up button, or:

  python tools/setup_game.py [--source <game folder>] [--game <copy folder>] [--archive <archive folder>]

--source defaults to the last one used, then the Steam install. --game defaults to the last one used, then game/ here. It can be
the same folder as --source, to patch that folder instead of copying it, unless that's in a Steam library. --archive uses a folder
from tools/archive_live.py instead of downloading the resource config. Safe to run again.

The source folder is only read. Its tables and bundles are what the server works from. The copy holds real copies of
the files that get patched or run (about 280 MB) and hard links to the rest, so it takes little space when it is on the same
NTFS drive as the source; anywhere else the rest is copied too. After a Steam update, set up again.
The one thing the game doesn't keep on disk is its resource config (about 2 MB): that comes from the live service once, into archive/, unless --archive has it.
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from gfserver import config, install  # noqa: E402

KEPT_BUNDLES = ("*assettextlpatch.ab", "*assettexttable.ab", "*assettextes.ab", "*assettextavg.ab")
STEAM_APP_ID = "3887700"          # keeps Steamworks from relaunching the Steam install


def step(text):
    print(f"\n{text}", flush=True)


def tool(*args):
    subprocess.run([sys.executable, str(ROOT / "tools" / args[0]), *args[1:]], check=True, cwd=ROOT)


def parse_folders(args):
    saved = install.load()
    source = args.source or saved.get("source") or install.find_steam_game()
    if not source:
        sys.exit("Couldn't find the game in a Steam library. Choose the game folder and try again.")
    source = Path(source).resolve()
    game = Path(args.game or saved.get("game") or ROOT / "game").resolve()
    problem = install.source_problem(source)
    if problem:
        sys.exit(problem)
    if game != source and (source in game.parents or game in source.parents):
        sys.exit("The copy folder can't be inside the game folder, or hold it.")
    if install.in_steam_library(game):
        sys.exit(f"The copy can't go in a Steam library, because Steam's files are never changed: {game}")
    return source, game


def keep_originals(source):
    """What later builds start from, kept from the source in case the game overwrites its own."""
    pc = config.pc_dir(source)
    config.PRISTINE_DIR.mkdir(parents=True, exist_ok=True)
    if not config.BASE_PACKAGE.is_file():
        shutil.copyfile(pc / "stc" / "stc_data.dat", config.BASE_PACKAGE)
    for pattern in KEPT_BUNDLES:
        for f in pc.glob(pattern):
            if not (config.PRISTINE_DIR / f.name).is_file():
                shutil.copyfile(f, config.PRISTINE_DIR / f.name)


def check_files(source):
    """Warn about bundles the config lists that the folder doesn't have: the game would ask the server for them and get nothing."""
    import UnityPy
    meta = config._archived("resconfig.json")
    tree = next(o.read_typetree() for o in UnityPy.load(str(config.ARCHIVE_DIR / meta["file"])).objects if o.type.name == "MonoBehaviour")
    have = {p.name.lower() for p in config.pc_dir(source).iterdir()}
    missing = sum((e["resname"] + ".ab").lower() not in have for e in tree["BaseAssetBundles"] + tree["AddAssetBundles"])
    if missing:
        print(f"WARNING: {missing} game files aren't in that folder. Start the game from Steam once and let it finish downloading, then set up again.")


DATA = Path("GirlsFrontLine_Data")
RES = DATA / "StreamingAssets" / "Res"
# Real copies: the programs next to the exe (GameAssembly.dll is patched, and anything that writes beside the exe must not
# reach the game's own files) and the patched resources.assets. Everything else in the data folder is linked.
COPIED_DATA = ("resources.assets",)


def _size(files):
    return sum(f.stat().st_size for f in files if f.is_file())


def _top_files(folder):
    return [f for f in folder.iterdir() if f.is_file()] if folder.is_dir() else []


def _linked_files(source):
    return [f for f in (source / DATA).rglob("*") if f.is_file() and f.suffix != ".tmp"
            and not (f.parent == source / DATA and f.name in COPIED_DATA)]


def _robocopy(source, game, *extra):
    # not /MIR: battle logs and options in the copy stay
    code = subprocess.run(["robocopy", str(source), str(game), "/R:1", "/W:1", "/NFL", "/NDL", "/NP", "/NJH", "/NJS",
                           *extra]).returncode
    if code >= 8:
        sys.exit(f"Copying failed (robocopy code {code}).")


def _check_space(needed, game):
    free = shutil.disk_usage(game).free
    if needed > free:
        sys.exit(f"Not enough disk space: the copy needs {needed / 2**30:.1f} GB more and {free / 2**30:.1f} GB is free on that drive.")


def link_files(source, game, files):
    """Hard-link each file into the copy: it shows in both folders and takes no extra space. Returns False when the drive
    can't (a different drive from the game, or not NTFS). Nothing writes through a link: the game swaps in downloads by
    deleting and moving, and setup and the mod tools replace a file rather than writing into it."""
    linked = 0
    for f in files:
        dst = game / f.relative_to(source)
        if dst.is_file() and os.path.samefile(f, dst):
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(dst.name + ".link.tmp")
        tmp.unlink(missing_ok=True)
        try:
            os.link(f, tmp)
        except OSError:
            if linked:
                raise
            return False
        os.replace(tmp, dst)
        linked += 1
    return True


def copy_game(source, game):
    game.mkdir(parents=True, exist_ok=True)
    copied = _top_files(source) + [source / DATA / n for n in COPIED_DATA]
    _check_space(_size(copied) - _size(_top_files(game) + [game / DATA / n for n in COPIED_DATA]), game)
    print(f"Copying the files that get patched or run ({_size(copied) / 2**20:.0f} MB).", flush=True)
    for f in copied:            # robocopy writes into a file, so none of these may be a link to the source's own
        dst = game / f.relative_to(source)
        if dst.is_file() and os.path.samefile(f, dst):
            dst.unlink()
    _robocopy(source, game, "/LEV:1", "/XF", "*.tmp")
    _robocopy(source / DATA, game / DATA, *COPIED_DATA)
    linked = _linked_files(source)
    print(f"Linking the other {len(linked)} files ({_size(linked) / 2**30:.1f} GB), which takes no extra space. (Explorer still counts them in the folder's size; the drive's free space is what shows the saving.)", flush=True)
    if link_files(source, game, linked):
        return
    print("This drive can't link to the game's files, so they're copied instead. Put the copy on the same drive as the game "
          "(an NTFS drive) to save that space.", flush=True)
    _check_space(_size(linked) - _size(game / f.relative_to(source) for f in linked), game)
    _robocopy(source / DATA, game / DATA, "/E", "/XF", "*.tmp", *COPIED_DATA)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source")
    ap.add_argument("--game")
    ap.add_argument("--archive")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    source, game = parse_folders(args)
    print(f"Game files: {source}\nOffline copy: {game}", flush=True)
    values = {"source": source, "game": game, "ready": False}
    if args.archive:
        values["archive"] = str(Path(args.archive).resolve())
    install.save(**values)
    config.reload_install()

    step("1/5 Keeping the original tables and patch files")
    keep_originals(source)

    step("2/5 Resource config")
    if config._archived("resconfig.json") and (config.ARCHIVE_DIR / config._archived("resconfig.json")["file"]).is_file():
        print(f"Already have it, in {config.ARCHIVE_DIR}")
    else:
        try:
            tool("archive_live.py", "--config-only")
        except subprocess.CalledProcessError:
            sys.exit("Couldn't get the resource config from the live service. If it has closed, choose a folder made by \"Archive the live service\".")
    check_files(source)

    step("3/5 Making the offline copy")
    if game == source:
        print("Using the game folder as it is")
    else:
        copy_game(source, game)

    step("4/5 Patching the copy")
    tool("patch_sdk_urls.py", str(game / "GirlsFrontLine_Data" / "resources.assets"))
    tool("patch_gameassembly.py", str(game / "GameAssembly.dll"))
    (game / "steam_appid.txt").write_text(STEAM_APP_ID, "ascii")
    tool("build_patch.py")

    step("5/5 Mods")
    tool("build_mods.py")

    install.save(ready=True)
    print("\nAll set. Press Play.")


if __name__ == "__main__":
    main()
