"""Build the resource config the server hands out, declaring modded bundles as current.

  python tools/build_resconfig.py [modded bundle ...]     (default: every .ab in build/)

The client (ResCenter$$CompareOldNewData) compares each local bundle's file size with
sizeCompress/sizeOriginal in the config and re-downloads mismatches straight from the real
CDN (DownLoadThread uses System.Net, which ignores the game's proxy). A modded bundle
therefore has to be declared in the config with its new size, or it gets overwritten.

Also applies build/fallbacks.json (art_fallback.py): bundles nobody can serve are left out, and
the other version of their art answers for them.

Reads archive/resconfig.json + the archived config bundle; writes build/resconfig.txt.
Requires UnityPy.
"""
import json
import re
import sys
from pathlib import Path

import UnityPy

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gfserver import config  # noqa: E402

ARCHIVE = config.ARCHIVE_DIR
OUT = ROOT / "build" / "resconfig.txt"


def bundle_key(filename):
    # On disk: "<random prefix><assetBundleName without underscores>.ab"
    return Path(filename).stem.lower()


def main():
    meta = json.loads((ARCHIVE / "resconfig.json").read_text("utf-8"))
    mods = [Path(p) for p in sys.argv[1:]] or sorted((ROOT / "build").glob("*.ab"))
    env = UnityPy.load(str(ARCHIVE / meta["file"]))
    obj = next(o for o in env.objects if o.type.name == "MonoBehaviour")
    tree = obj.read_typetree()

    entries = tree["BaseAssetBundles"] + tree["AddAssetBundles"]
    # Extra asset paths a modded bundle now answers to (build_mods.py "art"). The
    # client finds a bundle by path in assetAllRes; hashCode is a unique id, not a hash.
    aliases_file = ROOT / "build" / "asset_aliases.json"
    aliases = json.loads(aliases_file.read_text("utf-8")) if aliases_file.exists() else []
    next_code = 2 + max(a["hashCode"] for sec in ("BaseAssetBundles", "AddAssetBundles")
                        for e in tree[sec] for a in e["assetAllRes"])
    for alias in aliases:
        e = next(e for e in entries if e["assetBundleName"] == alias["bundle"])
        folder, name = ("Assets/Resources/DaBao/" + alias["path"]).rsplit("/", 1)
        # spell the folder as the config does ("Assets/Resources/DaBao/Pics/Title"); the name as given
        sibling = next((a["pathKey"] for x in entries for a in x["assetAllRes"]
                        if a["pathKey"].lower().startswith(folder.lower() + "/")), folder + "/")
        path_key = sibling.rsplit("/", 1)[0] + "/" + name
        if any(a["pathKey"].lower() == path_key.lower() for a in e["assetAllRes"]):
            continue
        e["assetAllRes"].append({"pathKey": path_key, "resName": path_key.rsplit("/", 1)[1],
                                 "abName": alias["bundle"], "prefabName": "", "hashCode": next_code,
                                 "packing": 0, "hasCodes": []})
        next_code += 2
        print(f"{alias['bundle']}: + {path_key}")

    # bundles nobody can serve: out of the config, or answered by their other version (art_fallback.py)
    import art_fallback
    fallbacks = json.loads(art_fallback.FALLBACKS_FILE.read_text("utf-8")) if art_fallback.FALLBACKS_FILE.exists() else {}
    dropped = art_fallback.apply(tree, fallbacks)
    entries = tree["BaseAssetBundles"] + tree["AddAssetBundles"]
    if dropped:
        print(f"fallbacks: {len(dropped)} bundle(s) nobody can serve left out, "
              f"{sum(len(v) for v in (fallbacks.get('alias') or {}).values())} path(s) answered by their other version")

    for mod in mods:
        size = mod.stat().st_size
        key = bundle_key(mod.name)
        # the file is <resname>.ab; else its name ends in the bundle name without "_" and "-"
        # (character_56-1type_1905_he -> ...character561type1905he.ab)
        hits = [e for e in entries if e["resname"].lower() == key]
        if not hits:
            hits = [e for e in entries if key.endswith(re.sub(r"[^a-z0-9]", "", e["assetBundleName"].lower()))]
            hits = sorted(hits, key=lambda e: -len(e["assetBundleName"]))[:1]   # longest name wins
        if not hits:
            raise SystemExit(f"{mod.name}: no matching bundle entry in the config")
        e = hits[0]
        print(f"{e['assetBundleName']}: size {e['sizeCompress']}/{e['sizeOriginal']} -> {size}  ({mod.name})")
        e["sizeCompress"] = size
        e["sizeOriginal"] = size

    # Bundle/video downloads use System.Net (ignores the game's proxy) against resUrl, so point
    # resUrl at the offline server itself, which serves the archive (tools/archive_live.py).
    sys.path.insert(0, str(ROOT))
    from gfserver import config
    old_url = tree["resUrl"]
    tree["resUrl"] = config.PUBLIC_BASE.rstrip("/") + "/pc/"
    print(f"resUrl: {old_url} -> {tree['resUrl']}")

    obj.save_typetree(tree)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(env.file.save(packer="original"))

    # verify by reloading
    check = next(o for o in UnityPy.load(str(OUT)).objects if o.type.name == "MonoBehaviour").read_typetree()
    lists = ("BaseAssetBundles", "AddAssetBundles")
    sizes = {(s, e["assetBundleName"]): e["sizeCompress"] for s in lists for e in check[s]}
    first = next(o for o in UnityPy.load(str(ARCHIVE / meta["file"])).objects
                 if o.type.name == "MonoBehaviour").read_typetree()
    orig = {(s, e["assetBundleName"]): e["sizeCompress"] for s in lists for e in first[s]}
    orig = {k: v for k, v in orig.items() if k[1] not in dropped}
    changed = {k for k in orig if orig[k] != sizes[k]}
    assert set(sizes) == set(orig) and len(changed) == len(mods), changed
    assert check["resUrl"] == tree["resUrl"]
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes); {len(changed)} entr(y/ies) changed, "
          f"{len(orig) - len(changed)} unchanged")


if __name__ == "__main__":
    main()
