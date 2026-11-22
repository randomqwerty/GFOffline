"""Build the enabled mods in mods/ into a data package the client downloads (see gfserver/mods.py).

  python tools/build_mods.py            build, then update the game copy (text bundle) if needed
  python tools/build_mods.py --check    only validate; writes nothing

Steps:
 1. merge mod rows into the pristine package (archive/stc/*.zip) -> build/mods/stc/, the
    stc_<data_version>.zip and manifest.json (stdlib only)
 2. text keys ("text" in mod.json): patch the assettexttable bundle -> build/<bundle>.ab
    (needs UnityPy), or remove a previously built one when no mod has text any more
 3. art: extra paths for existing images (mod "art", title art for mod chapters, mission icons for
    mod maps), added to the bundles holding them -> build/<bundle>.ab + build/asset_aliases.json
 4. story files (story/<file>.txt in a mod): replace the game's in the story bundle -> build/<bundle>.ab
 5. custom art (mod "custom_art"): copies of a doll's art bundles with the mod's pictures, under a new
    model code -> build/gfmodart*.ab + build/custom_art.json (tools/custom_art.py)
 6. game assets (mod "game_assets"): replaced or added pictures and music -> build/<bundle>.ab,
    build/gfmodasset*.ab, build/<name>.acb.bytes + build/game_assets.json (tools/game_assets.py)
 7. tools/build_resconfig.py (declares build/*.ab sizes and alias paths) and copy the bundles into
    the game copy

Restart the server afterwards; on the next login the client downloads the new package.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gfserver import config, mods  # noqa: E402

TEXT_BUNDLE_SUFFIX = "assettexttable.ab"
TEXTES_BUNDLE_SUFFIX = "assettextes.ab"         # profiles config: chapter list names
STORY_BUNDLE_SUFFIX = "assettextavg.ab"         # story files
STORY_DIR = "assets/resources/dabao/avgtxt/"
PROFILES_DIR = "assets/resources/dabao/profilesconfig/"
CHAPTER_FILE = PROFILES_DIR + "chapterconfig.txt"
TEXT_DIR = "assets/resources/dabao/table/"
GAME_PC = config.pc_dir(config.GAME_DIR)


def pristine_text_bundle(suffix=TEXT_BUNDLE_SUFFIX):
    hits = config.original_bundles("*" + suffix)
    if hits:
        return hits[0]
    raise mods.ModError(f"*{suffix} bundle not found: press Set up in the launcher")


def chapter_lines(chapters):
    """chapterconfig.txt lines for mod chapters: "N|normal|name|title|description" for each kind."""
    clean = lambda v: str(v or "").replace("|", "/").replace("\r", " ").replace("\n", " ").strip()
    out = []
    for ch in sorted(chapters, key=lambda c: int(c["number"])):
        n, name, desc = int(ch["number"]), clean(ch.get("name")) or f"Chapter {ch['number']}", clean(ch.get("description"))
        out += [f"{n}|{kind}|{name}|{name}|{desc}".encode("utf-8") for kind in ("normal", "Emergency", "Night")]
    return out


def edit_lines(raw, edits, name):
    """Replace whole lines of a config file; the file's line endings stay as they are."""
    lines = raw.split(b"\n")
    for e in edits:
        old, new = str(e["from"]).encode("utf-8"), str(e["to"]).encode("utf-8")
        hits = [i for i, l in enumerate(lines) if l.rstrip(b"\r") == old]
        if len(hits) != 1:
            raise mods.ModError(f"profile_edits {name}: expected the line {e['from']!r} once, found it {len(hits)} times")
        lines[hits[0]] = new + (b"\r" if lines[hits[0]].endswith(b"\r") else b"")
    return b"\n".join(lines)


def build_profiles_bundle(chapters, edits, src, out):
    """The profiles-config bundle with mod chapters' lines added to (or replaced in) the chapter list,
    and the mods' "profile_edits" applied ({file below profilesconfig/: [{"from": line, "to": line}]})."""
    import UnityPy
    env = UnityPy.load(src.read_bytes())
    container = {}
    for obj in env.objects:
        if obj.type.name == "AssetBundle":
            container = {p: ptr.asset.path_id for p, ptr in obj.read().m_Container}
    objs = {o.path_id: o for o in env.objects}
    if chapters:
        asset = objs[container[CHAPTER_FILE]].read()
        s = asset.m_Script
        raw = s.encode("utf-8", "surrogateescape") if isinstance(s, str) else bytes(s)
        lines = raw.split(b"\r\n")
        trailing = bool(lines) and lines[-1] == b""
        if trailing:
            lines.pop()
        mine = {str(int(c["number"])).encode() for c in chapters}
        lines = [l for l in lines if l.split(b"|", 1)[0] not in mine] + chapter_lines(chapters)
        asset.m_Script = (b"\r\n".join(lines) + (b"\r\n" if trailing else b"")).decode("utf-8", "surrogateescape")
        asset.save()
        print(f"  chapters: {', '.join(str(c['number']) + ' ' + str(c.get('name', '')) for c in chapters)}")
    for name, file_edits in edits.items():
        path = PROFILES_DIR + name.lower()
        if path not in container:
            raise mods.ModError(f"profile_edits: the client has no config file {name}")
        asset = objs[container[path]].read()
        s = asset.m_Script
        raw = s.encode("utf-8", "surrogateescape") if isinstance(s, str) else bytes(s)
        asset.m_Script = edit_lines(raw, file_edits, name).decode("utf-8", "surrogateescape")
        asset.save()
        print(f"  config: {name} {len(file_edits)} line(s)")
    out.write_bytes(env.file.save(packer="original"))


ALIASES_FILE = ROOT / "build" / "asset_aliases.json"
DABAO = "assets/resources/dabao/"
MISSION_ICONS = "Pics/Icons/Mission/"
NO_ICON = "unknown"                              # the game's own "?" mission icon


def asset_index():
    """Every asset path the client knows (lower case, from the archived resource config) ->
    (bundle name, bundle file name)."""
    import UnityPy
    meta = json.loads((config.ARCHIVE_DIR / "resconfig.json").read_text("utf-8"))
    tree = next(o for o in UnityPy.load(str(config.ARCHIVE_DIR / meta["file"])).objects
                if o.type.name == "MonoBehaviour").read_typetree()
    out = {}
    for sec in ("BaseAssetBundles", "AddAssetBundles"):
        for e in tree[sec]:
            for a in e["assetAllRes"]:
                out[a["pathKey"].lower()] = (e["assetBundleName"], e["resname"] + ".ab")
    return out


def _rel(path):
    """"Pics/Title/x.png" as written (the client's path lookups are case-sensitive)."""
    path = path.replace("\\", "/").lstrip("/")
    return path[len(DABAO):] if path.lower().startswith(DABAO) else path


def _full(path):
    """The lower-case container path inside a bundle."""
    return DABAO + _rel(path).lower()


def wanted_art(found, chapters, index):
    """{new path (as the client asks for it): existing image (container path)} that the build adds:
    - each mod's "art" entries;
    - Pics/Title/chapter<N>_base for a mod chapter without one: the campaign screen opens on the
      newest chapter and crashes without it, so it shows the newest original chapter's image;
    - Pics/Icons/Mission/<boss code>: a map's mission-select icon is its boss team leader's
      enemy-type code. A map's map_rules "icon" picks the image; a boss code without an icon gets
      the "unknown" one."""
    art = {}
    for m in found:
        for new, old in (m.get("art") or {}).items():
            if _full(old) not in index:
                raise mods.ModError(f"{m['name']}: art {new!r}: {old!r} is not an image the client has")
            art[_rel(new)] = _full(old)
    titles = sorted(int(p.rsplit("chapter", 1)[1][:-9]) for p in index
                    if re.fullmatch(DABAO + r"pics/title/chapter\d+_base\.png", p))
    for ch in chapters:
        path = f"Pics/Title/chapter{int(ch['number'])}_base.png"
        if _full(path) not in index:
            art.setdefault(path, _full(f"Pics/Title/chapter{titles[-1]}_base.png"))
    from gfserver import stc
    missions = {r["id"]: r for r in stc.table("mission")}
    teams = {r["id"]: r for r in stc.table("enemy_team")}
    types = {r["id"]: r for r in stc.table("enemy_character_type")}
    icons = {}
    for m in found:
        for row in m["tables"].get("mission", []):
            mid = int(row["id"])
            rules = m["map_rules"].get(str(mid)) or {}
            mission = missions.get(mid)
            if mission is None:
                continue
            team = teams.get(int((str(mission["boss_team_id"]).split(",")[0] or 0)))
            code = (types.get(int((team or {}).get("enemy_leader") or 0)) or {}).get("code")
            if not code:
                continue
            path = f"{MISSION_ICONS}{code}.png"
            have = _full(path) in index
            pick = rules.get("icon")
            if pick:
                src = _full(f"{MISSION_ICONS}{pick}.png")
                if src not in index:
                    raise mods.ModError(f"{m['name']}: map {mid} icon {pick!r} is not a mission icon")
                if have and _full(path) != src:
                    print(f"  WARNING map {mid}: its boss ({code}) already has an icon of its own, so the icon "
                          f"{pick!r} can't be used; pick a boss team whose leader has none")
                    continue
                if icons.get(path, src) != src:
                    print(f"  WARNING map {mid}: maps with the boss {code} share one icon; using {icons[path]!r}")
                    continue
                icons[path] = src
            elif not have:
                icons.setdefault(path, _full(f"{MISSION_ICONS}{NO_ICON}.png"))
    for path, src in icons.items():
        art.setdefault(path, src)
    return art


def build_art(art, index, out_dir):
    """Give existing images a second path: an AssetBundle's container may list several paths for
    one asset, so the new path is added to the bundle holding the image (pristine copy from
    archive/cdn/pc) and declared in the resource config. Returns {bundle file: [new paths]}."""
    import UnityPy
    by_bundle = {}
    for new, old in sorted(art.items()):
        if _full(new) in index:
            raise mods.ModError(f"art {new!r}: the client already has an image there")
        by_bundle.setdefault(index[old], []).append((new, old))
    built = {}
    for (bundle, fname), pairs in by_bundle.items():
        found = config.original_bundles(fname)
        if not found:
            raise mods.ModError(f"{fname} (bundle {bundle}) not found: press Set up in the launcher")
        src = found[0]
        env = UnityPy.load(src.read_bytes())
        ab = next(o for o in env.objects if o.type.name == "AssetBundle")
        tree = ab.read_typetree()
        cont = tree["m_Container"]
        for new, old in pairs:
            infos = [dict(info) for p, info in cont if p == old]
            if not infos:
                raise mods.ModError(f"{old!r} is not inside {fname}")
            cont += [(_full(new), info) for info in infos]
        tree["m_Container"] = sorted(cont, key=lambda c: c[0])
        ab.save_typetree(tree)
        (out_dir / fname).write_bytes(env.file.save(packer="original"))
        built[fname] = {"bundle": bundle, "paths": [n for n, _ in pairs]}
        for new, old in pairs:
            print(f"  art: {new} = {old[len(DABAO):]}")
    return built


def text_value(v):
    # table text files are one "key,value" per line; line breaks are written as //n and commas
    # as //c (the original files do the same: "ZAGALA//cHaruka Tomatsu//c")
    return str(v).replace("\r\n", "\n").replace("\n", "//n").replace(",", "//c")


def build_text_bundle(texts, src, out):
    import UnityPy
    env = UnityPy.load(src.read_bytes())
    container = {}
    for obj in env.objects:
        if obj.type.name == "AssetBundle":
            container = {p: ptr.asset.path_id for p, ptr in obj.read().m_Container}
    objs = {o.path_id: o for o in env.objects}
    by_file = {}
    for key, value in texts.items():
        if "-" not in key:
            raise mods.ModError(f"text key {key!r}: expected <table>-<number>, e.g. gun-19000001")
        path = TEXT_DIR + key.rsplit("-", 1)[0] + ".txt"
        if path not in container:
            raise mods.ModError(f"text key {key!r}: the client has no text file {path}")
        by_file.setdefault(path, {})[key] = text_value(value)
    for path, entries in by_file.items():
        asset = objs[container[path]].read()
        s = asset.m_Script
        # edited as bytes: some files are not valid UTF-8 throughout, and other lines stay as they are
        raw = s.encode("utf-8", "surrogateescape") if isinstance(s, str) else bytes(s)
        lines = raw.split(b"\r\n")
        trailing = bool(lines) and lines[-1] == b""
        if trailing:
            lines.pop()
        pos = {l.split(b",", 1)[0]: i for i, l in enumerate(lines)}
        for key, value in entries.items():
            line = f"{key},{value}".encode("utf-8")
            if key.encode() in pos:
                lines[pos[key.encode()]] = line
            else:
                lines.append(line)
        new = b"\r\n".join(lines) + (b"\r\n" if trailing else b"")
        asset.m_Script = new.decode("utf-8", "surrogateescape")
        asset.save()
        print(f"  text: {path.rsplit('/', 1)[1]} {len(entries)} key(s)")
    out.write_bytes(env.file.save(packer="original"))


def story_container(env):
    """{file name in lower case: (the bundle's own path, its object)} for the story bundle."""
    objs = {o.path_id: o for o in env.objects}
    out = {}
    for obj in env.objects:
        if obj.type.name == "AssetBundle":
            for p, ptr in obj.read().m_Container:
                if p.startswith(STORY_DIR):
                    out[p[len(STORY_DIR):]] = objs[ptr.asset.path_id]
    return out


def read_story(names=None, src=None):
    """{file name in lower case: bytes} of the game's own story files (all of them, or just the names given)."""
    import UnityPy
    env = UnityPy.load((src or pristine_text_bundle(STORY_BUNDLE_SUFFIX)).read_bytes())
    out = {}
    for name, obj in story_container(env).items():
        if names is None or name in names:
            s = obj.read().m_Script
            out[name] = s.encode("utf-8", "surrogateescape") if isinstance(s, str) else bytes(s)
    return out


def build_story_bundle(found, src, out):
    """The story bundle with each mod's story/<file>.txt in place of the game's file of that name; a later mod's file wins."""
    import UnityPy
    env = UnityPy.load(src.read_bytes())
    container = story_container(env)
    files = {}
    for m in found:
        for name in m.get("story") or {}:
            if name.lower() not in container:
                raise mods.ModError(f"{m['name']}: story/{name}: the game has no story file with that name")
            files[name.lower()] = (m["name"], name, (m["dir"] / "story" / name).read_bytes())
    originals = read_story(set(files), src)
    for key, (mod_name, name, raw) in sorted(files.items()):
        for p in mods.story_problems(raw, originals[key]):
            print(f"  WARNING {mod_name}: story/{name}: {p}")
        asset = container[key].read()
        asset.m_Script = raw.decode("utf-8", "surrogateescape")
        asset.save()
    print(f"  story: {len(files)} file(s)")
    out.write_bytes(env.file.save(packer="original"))


def copy_into_game(src, name, ours=False):
    """ours: a bundle only the build makes (custom art), never kept as an original."""
    if "steamapps" in (p.lower() for p in GAME_PC.parts):
        raise SystemExit(f"refusing to write inside a Steam library: {GAME_PC}")
    dst = GAME_PC / name
    if not ours and dst.exists() and not config.original_bundles(name):     # playing from the source folder: keep what's overwritten
        config.PRISTINE_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(dst, config.PRISTINE_DIR / name)
    if not dst.exists() or dst.read_bytes() != src.read_bytes():
        tmp = dst.with_name(dst.name + ".tmp")      # replaced, never written into: dst may be a hard link to the source's file
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
        print(f"  game copy: {name} updated")


def _bundle_on_disk(fname):
    """A bundle file to serve or build from: the original (kept by setup, archived or installed),
    else the game copy's."""
    found = config.original_bundles(fname)
    if found:
        return found[0]
    return GAME_PC / fname if (GAME_PC / fname).is_file() else None


def build_fallbacks(art_files, custom_files=()):
    """art_fallback.py: bundles nobody can serve leave the resource config; their other version
    answers for them. Returns the bundle files to copy into the game (changed now or before)."""
    import UnityPy
    import art_fallback
    import custom_art
    before = json.loads(art_fallback.FALLBACKS_FILE.read_text("utf-8")) if art_fallback.FALLBACKS_FILE.exists() else {}
    meta = json.loads((config.ARCHIVE_DIR / "resconfig.json").read_text("utf-8"))
    tree = next(o for o in UnityPy.load(str(config.ARCHIVE_DIR / meta["file"])).objects
                if o.type.name == "MonoBehaviour").read_typetree()
    custom_art.add_entries(tree)
    import game_assets
    game_assets.add_entries(tree)
    find = lambda f: ROOT / "build" / f if f in custom_files else _bundle_on_disk(f)
    result = art_fallback.build(tree, find, ROOT / "build", built=set(art_files) | set(custom_files))
    stale = set(before.get("files") or {}) - set(result["files"]) - set(art_files)
    for fname in stale:                 # no longer needed: back to the original bundle
        (ROOT / "build" / fname).unlink(missing_ok=True)
    alone = len(result["drop"]) - len(result["alias"])
    if result["drop"]:
        print(f"  missing bundles: {len(result['drop'])}; {len(result['alias'])} answered by their other "
              f"version, {alone} left out (shown empty)")
    return set(result["files"]) | stale


def build_custom_art(found):
    """Custom art copies (tools/custom_art.py); a copy no longer made leaves build/ and the game copy.
    Returns {file name: bundle name} of the copies made."""
    import custom_art
    before = {e["file"] for e in custom_art.listed()}
    try:
        made = custom_art.build(custom_art.collect(found), ROOT / "build")
    except custom_art.ArtError as e:
        raise mods.ModError(str(e))
    for fname in before - set(made):
        if fname.startswith(custom_art.PREFIX):
            (ROOT / "build" / fname).unlink(missing_ok=True)
            if "steamapps" not in (p.lower() for p in GAME_PC.parts):
                (GAME_PC / fname).unlink(missing_ok=True)
    return made


def build_game_assets(found, art_files):
    """Replaced and added pictures and music (tools/game_assets.py). What an earlier build made and this one
    doesn't leaves build/: an added file leaves the game copy too, a replaced one is restored there.
    Returns (result of game_assets.build, {file: "restore" or "remove"} for the game copy)."""
    import game_assets
    before = game_assets.listed()
    try:
        made = game_assets.build(game_assets.collect(found), ROOT / "build", built=art_files)
    except (game_assets.AssetError, game_assets.cri.CriError) as e:
        raise mods.ModError(str(e))
    gone = {}
    for fname in set(before.get("replaced") or ()) - set(made["replaced"]) - set(art_files):
        (ROOT / "build" / fname).unlink(missing_ok=True)
        gone[fname] = "restore"
    for item in before.get("new") or ():
        if item["file"] not in made["new"]:
            (ROOT / "build" / item["file"]).unlink(missing_ok=True)
            gone[item["file"]] = "remove"
    for s in before.get("sounds") or ():
        if s["file"] not in made["sounds"]:
            (ROOT / "build" / s["file"]).unlink(missing_ok=True)
            (ROOT / "build" / s["dat"]).unlink(missing_ok=True)
            gone[s["file"]] = "remove" if s["new"] else "restore"
    return made, gone


def main():
    check_only = "--check" in sys.argv
    found = mods.discover()
    print(f"mods: {', '.join(m['name'] for m in found) or '(none)'}")
    if check_only:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            man = mods.build(found, out_dir=Path(tmp))
    else:
        man = mods.build(found)
    for p in man["problems"]:
        print(f"  WARNING {p}")
    print(f"data_version {man['data_version']} ({'modded' if found else 'original'})")
    if check_only:
        return

    texts = {}
    for m in found:
        texts.update(m["text"])
    src = pristine_text_bundle()
    built = ROOT / "build" / src.name
    if texts:
        build_text_bundle(texts, src, built)
    elif built.exists():
        built.unlink()
        print("  text: no mod text; original bundle restored")
    chapters = [m["chapter"] for m in found if (m.get("chapter") or {}).get("number")]
    edits = {}
    for m in found:
        for name, file_edits in m["profile_edits"].items():
            edits.setdefault(name, []).extend(file_edits)
    csrc = pristine_text_bundle(TEXTES_BUNDLE_SUFFIX)
    cbuilt = ROOT / "build" / csrc.name
    if chapters or edits:
        build_profiles_bundle(chapters, edits, csrc, cbuilt)
    elif cbuilt.exists():
        cbuilt.unlink()
        print("  chapters and config: none; original profiles config restored")
    ssrc = pristine_text_bundle(STORY_BUNDLE_SUFFIX)
    sbuilt = ROOT / "build" / ssrc.name
    if any(m.get("story") for m in found):
        build_story_bundle(found, ssrc, sbuilt)
    elif sbuilt.exists():
        sbuilt.unlink()
        print("  story: none; original story files restored")
    index = asset_index()
    for b in man.get("banners") or []:
        if _full(b["pic"] + ".png") not in index:
            print(f"  WARNING banner for event {b['event']}: {b['pic']} is not an image the client has")
    art = build_art(wanted_art(found, chapters, index), index, ROOT / "build")
    before = json.loads(ALIASES_FILE.read_text("utf-8")) if ALIASES_FILE.exists() else []
    stale = {e["file"] for e in before if isinstance(e, dict) and "file" in e} - set(art)
    for fname in stale:                 # no longer aliased: back to the original bundle
        (ROOT / "build" / fname).unlink(missing_ok=True)
    aliases = [{"path": p, "bundle": b["bundle"], "file": f} for f, b in art.items() for p in b["paths"]]
    if aliases:
        ALIASES_FILE.write_text(json.dumps(aliases, indent=1), "utf-8")
    else:
        ALIASES_FILE.unlink(missing_ok=True)
    custom = build_custom_art(found)
    assets, gone = build_game_assets(found, set(art))
    fallback_files = build_fallbacks(set(art) | set(assets["replaced"]), set(custom) | set(assets["new"]))
    subprocess.run([sys.executable, str(ROOT / "tools" / "build_resconfig.py")], check=True)
    copy_into_game(built if built.exists() else src, src.name)
    copy_into_game(cbuilt if cbuilt.exists() else csrc, csrc.name)
    copy_into_game(sbuilt if sbuilt.exists() else ssrc, ssrc.name)
    for fname in custom:
        copy_into_game(ROOT / "build" / fname, fname, ours=True)
    for fname in set(assets["new"]) | {f for f, new in assets["sounds"].items() if new}:
        copy_into_game(ROOT / "build" / fname, fname, ours=True)
    for fname in {f for f, new in assets["sounds"].items() if not new}:
        copy_into_game(ROOT / "build" / fname, fname)
    restore = {f for f, how in gone.items() if how == "restore"}
    for fname in (set(art) | stale | fallback_files | set(assets["replaced"]) | restore) - set(custom):
        built_file = ROOT / "build" / fname
        copy_into_game(built_file if built_file.exists() else config.original_bundles(fname)[0], fname)
    for fname in (f for f, how in gone.items() if how == "remove"):
        if "steamapps" not in (p.lower() for p in GAME_PC.parts):
            (GAME_PC / fname).unlink(missing_ok=True)
    subprocess.run([sys.executable, str(ROOT / "tools" / "check_save.py")], check=False)   # the new tables: a fresh process
    print("done; restart the server, then log in to download the new data package")


if __name__ == "__main__":
    try:
        main()
    except mods.ModError as e:
        sys.exit(f"mod error: {e}")
