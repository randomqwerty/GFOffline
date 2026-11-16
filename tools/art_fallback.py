"""Bundles the client would have to download but nobody can serve: no game copy, archive or
original install has them (the live CDN gone, or a setup that never fetched them). The client
stops play to download those ("CDN file not archived" on our side), so the build takes them out of
the resource config it serves, and where the other version of the same art is there, that bundle
answers for both.

  Doll art comes twice: character_<doll>_nom (the original art, used when the art setting is on)
  and character_<doll>_he (the edited art). Their assets differ only in the path: Pic/x.png and
  Dabao/.../X_big.prefab in _nom, Pic_HE/x.png and X_big_HE.prefab in _he. The client finds an
  asset's bundle by its path in the config (ResManager$$LoadObjectByAB -> LoadAsset(path)), and a
  bundle's container may list one asset under several paths (as build_mods.py's mod art does). So
  the bundle that is there gets the missing one's paths for the same assets, the config sends those
  paths to it, and the missing bundle's entry goes.
  A bundle with no other version is only taken out of the config: what it held shows as missing
  (an empty picture) instead of stopping the game.

Run by build_mods.py (so by Setup and Build mods); writes build/<bundle file>.ab for the bundles
it changes and build/fallbacks.json, which build_resconfig.py applies.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FALLBACKS_FILE = ROOT / "build" / "fallbacks.json"
PAIRS = (("_nom", "_he"), ("_he", "_nom"))


def other_version(name):
    """character_kp31_nom <-> character_kp31_he; None for a bundle with no second version."""
    for mine, theirs in PAIRS:
        if name.endswith(mine):
            return name[:-len(mine)] + theirs
    return None


def _swap(path, to_he):
    """The other version's container path candidates for an asset path (lower case)."""
    folder, _, name = path.rpartition("/")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    segs = folder.split("/")
    swap = lambda a, b: "/".join(b if s == a else s for s in segs)
    if to_he:
        folders = {folder, swap("pic", "pic_he")}
        stems = {stem + "_he", stem}
    else:
        folders = {folder, swap("pic_he", "pic")}
        stems = {stem[:-3] if stem.endswith("_he") else stem, stem}
    return [f"{f}/{s}{dot}{ext}" for f in sorted(folders) for s in sorted(stems)
            if f"{f}/{s}{dot}{ext}" != path]


def plan(entries, have):
    """entries: the config's bundle entries; have(entry): its file is there to serve.
    Returns {"drop": [bundle name], "alias": {stand-in bundle: [(missing path, stand-in path)]}};
    paths are the config's pathKeys. A stand-in path is only a candidate: build() keeps those the
    stand-in bundle really holds."""
    by_name = {e["assetBundleName"]: e for e in entries}
    out = {"drop": [], "alias": {}}
    for e in entries:
        if have(e):
            continue
        out["drop"].append(e["assetBundleName"])
        other = by_name.get(other_version(e["assetBundleName"]) or "")
        if other is None or not have(other):
            continue
        to_he = e["assetBundleName"].endswith("_nom")
        theirs = {a["pathKey"].lower(): a["pathKey"] for a in other["assetAllRes"]}
        pairs = []
        for a in e["assetAllRes"]:
            match = next((theirs[c] for c in _swap(a["pathKey"].lower(), to_he) if c in theirs), None)
            if match:
                pairs.append((a["pathKey"], match))
        if pairs:
            out["alias"].setdefault(other["assetBundleName"], []).extend(pairs)
    return out


def build_bundle(src, pairs, out):
    """src bundle + each missing path as a second container path of its stand-in asset -> out.
    Returns the (missing path, stand-in path) pairs it holds now."""
    import UnityPy
    env = UnityPy.load(Path(src).read_bytes())
    ab = next(o for o in env.objects if o.type.name == "AssetBundle")
    tree = ab.read_typetree()
    cont = tree["m_Container"]
    held = {p for p, _ in cont}
    added = []
    for new, old in pairs:
        if new.lower() in held:
            added.append([new, old])        # a copy built before
            continue
        infos = [dict(info) for p, info in cont if p == old.lower()]
        if not infos:
            continue
        cont += [(new.lower(), info) for info in infos]
        held.add(new.lower())
        added.append([new, old])
    tree["m_Container"] = sorted(cont, key=lambda c: c[0])
    ab.save_typetree(tree)
    Path(out).write_bytes(env.file.save(packer="original"))
    return added


def build(tree, find, out_dir, built=()):
    """tree: the resource config's typetree; find(file name): its path on disk or None (the original
    bundle first, where kept); built: bundle files this build already changed (mod art), whose built
    copy is the one to extend.
    Writes the stand-in bundles and FALLBACKS_FILE; returns {"drop", "alias", "files"}."""
    entries = tree["BaseAssetBundles"] + tree["AddAssetBundles"]
    by_name = {e["assetBundleName"]: e for e in entries}
    fname = lambda e: e["resname"] + ".ab"
    p = plan(entries, lambda e: find(fname(e)) is not None)
    result = {"drop": p["drop"], "alias": {}, "files": {}}
    for name, pairs in sorted(p["alias"].items()):
        e = by_name[name]
        src = Path(out_dir) / fname(e) if fname(e) in built else find(fname(e))
        added = build_bundle(src, pairs, Path(out_dir) / fname(e))
        if added:
            result["alias"][name] = added
            result["files"][fname(e)] = name
    FALLBACKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    FALLBACKS_FILE.write_text(json.dumps(result, indent=1), "utf-8")
    return result


def apply(tree, fallbacks):
    """build_resconfig.py: the missing bundles' entries out of the config, their paths into the
    stand-in bundles' entries: the same hashCode (other entries may name it), the stand-in's abName,
    and the stand-in asset's own dependencies (hasCodes), which are all still listed."""
    lists = ("BaseAssetBundles", "AddAssetBundles")
    drop = set(fallbacks.get("drop") or ())
    moved = {}
    for sec in lists:
        for e in tree[sec]:
            if e["assetBundleName"] in drop:
                for a in e["assetAllRes"]:
                    moved[a["pathKey"]] = a
    for sec in lists:
        tree[sec] = [e for e in tree[sec] if e["assetBundleName"] not in drop]
        for e in tree[sec]:
            own = {a["pathKey"]: a for a in e["assetAllRes"]}
            for new, old in (fallbacks.get("alias") or {}).get(e["assetBundleName"], ()):
                if new in moved and old in own:
                    e["assetAllRes"].append(dict(moved[new], abName=e["assetBundleName"],
                                                 hasCodes=list(own[old]["hasCodes"])))
    return drop
