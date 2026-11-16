"""Sharing mods as one .zip file: Mod Studio's Export button writes one, the launcher's "Add a mod" reads one.

A shared zip holds one mod folder (mods/<name>/ with mod.json, tables/, catchdata/, story/). Adding one checks it before
anything is written: one mod.json, no paths outside the folder, only the file types mods use, and a size limit. A mod
with the same folder name is replaced, and the old copy kept in mods/_replaced/ (folders starting with _ are not loaded).
"""
import io
import json
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath

from . import mods

KINDS = (".json", ".txt", ".md")          # mods hold table rows, text and story files, never game art
MAX_BYTES = 50 * 2**20
NAME = re.compile(r"[A-Za-z0-9_\-]+")


class ShareError(Exception):
    """Something wrong with a mod file, in words for the player."""


def _files(folder):
    return [f for f in sorted(folder.rglob("*")) if f.is_file() and not any(p.startswith(".") or p == "__pycache__"
                                                                         for p in f.relative_to(folder).parts)]


def export_bytes(name):
    """The mod folder mods/<name>/ as a zip, with the folder itself inside so unpacking keeps it together."""
    folder = mods.MODS_DIR / name
    if not NAME.fullmatch(name or "") or not (folder / "mod.json").is_file():
        raise ShareError(f"There is no mod called {name}.")
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in _files(folder):
            z.write(f, f"{name}/{f.relative_to(folder).as_posix()}")
    return out.getvalue()


def file_name(name):
    meta = json.loads((mods.MODS_DIR / name / "mod.json").read_text("utf-8"))
    version = re.sub(r"[^A-Za-z0-9_.\-]", "", str(meta.get("version") or ""))
    return f"{name}-v{version}.zip" if version else f"{name}.zip"


def inspect(path):
    """What a mod zip holds: {"name", "meta", "files": {path inside the mod: bytes}, "skipped": [...]}. Raises ShareError."""
    try:
        z = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise ShareError("That file isn't a mod: it should be a .zip file, as Mod Studio's Export button makes.")
    with z:
        entries = [i for i in z.infolist() if not i.is_dir()]
        if sum(i.file_size for i in entries) > MAX_BYTES:
            raise ShareError(f"That file is too large for a mod (over {MAX_BYTES // 2**20} MB unpacked).")
        homes = [PurePosixPath(i.filename).parent for i in entries if PurePosixPath(i.filename).name == "mod.json"]
        if not homes:
            raise ShareError("That zip has no mod.json, so it isn't a mod.")
        if len(homes) > 1:
            raise ShareError(f"That zip holds {len(homes)} mods. Add them one zip at a time.")
        home = homes[0]
        files, skipped = {}, []
        for i in entries:
            p = PurePosixPath(i.filename.replace("\\", "/"))
            if p.is_absolute() or ".." in p.parts or ":" in i.filename:
                raise ShareError("That zip has files that would land outside its mod folder, so it was not added.")
            if home not in (p.parent, *p.parents):
                skipped.append(i.filename)
                continue
            rel = p.relative_to(home)
            if p.suffix.lower() not in KINDS or any(part.startswith(".") for part in rel.parts):
                skipped.append(i.filename)
                continue
            files[rel.as_posix()] = z.read(i)
    try:
        meta = json.loads(files["mod.json"].decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise ShareError("The mod's mod.json can't be read, so the mod is damaged or unfinished.")
    if not isinstance(meta, dict):
        raise ShareError("The mod's mod.json can't be read, so the mod is damaged or unfinished.")
    name = home.name if home.parts else str(meta.get("name") or "")
    name = "_".join(NAME.findall(name))
    if not name or name.startswith("_"):
        raise ShareError("The mod has no usable name. Ask its author to export it again from Mod Studio.")
    return {"name": name, "meta": meta, "files": files, "skipped": skipped}


def install(path, log=print):
    """Add the mod in a zip to mods/. Returns its folder name. If it clashes with another mod, it is added turned off."""
    found = inspect(path)
    name, target = found["name"], mods.MODS_DIR / found["name"]
    mods.MODS_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=mods.MODS_DIR, prefix="_adding_") as tmp:
        staged = Path(tmp) / name
        for rel, data in found["files"].items():
            f = staged / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(data)
        if target.exists():
            keep = mods.MODS_DIR / "_replaced" / f"{name}_{time.strftime('%Y%m%d_%H%M%S')}"
            keep.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(keep))
            log(f"Replaced the mod you had called {name}. The old copy is in mods/_replaced/{keep.name}.")
        shutil.move(str(staged), str(target))
    version = found["meta"].get("version")
    log(f"Added {name}" + (f" (version {version})" if version else "") + ".")
    if found["skipped"]:
        log(f"Left out {len(found['skipped'])} file(s) that mods don't use.")
    clash = conflict(name)
    if clash:
        mods.set_enabled(name, False)
        log(f"It is turned off for now: {clash}")
        log("To use it, turn the other mod off in Mod Studio, then turn this one on.")
    return name


def conflict(name):
    """Why this mod can't be used with the other mods that are on, in words, or None. A problem the other mods have
    without it is not counted against it."""
    def problem(mod_list):
        try:
            mods.build(mod_list, write=False, log=lambda *_: None)
        except mods.ModError as e:
            return str(e)
        except FileNotFoundError:
            return None                     # not set up yet: checked again when mods are built
        return None

    try:
        on = mods.discover(mods.MODS_DIR)
    except mods.ModError as e:
        return str(e)
    if not any(m["dir"].name == name for m in on):
        return None
    found = problem(on)
    if found and problem([m for m in on if m["dir"].name != name]) is None:
        return found
    return None
