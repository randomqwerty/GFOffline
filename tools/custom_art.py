"""Custom art for mod T-Dolls: a new model code whose bundles are copies of an existing doll's, with
the modder's pictures in them.

  mod.json "custom_art": {"<new code>": {"from": "<code of the doll it copies>", "skin": <skin id, 0 or none: default look>,
                                         "images": {"<slot>": "art/<new code>/<slot>.png"}}}

Slots (SLOTS): portrait, damaged, card (the list pictures; made from the portrait when missing),
chibi (battle sprite sheet), dorm (dorm sprite sheet). A doll uses the art through its model, the gun
row's "code" = new code. Pictures are stored at the template's size (fit() converts uploads).

How the client finds a doll's art: by path, from its code (Assets/Characters/<code>/Pic_HE/pic_<code>.png,
Assets/Resources/DaBao/Pics/Guns/<code>/<code>_big_HE.prefab, Assets/Characters/<code>/Spine/<code>...).
build() copies each bundle of the source doll and of its skins (character_<from>[_<skin>], _he, _nom, _spine):
the client finds a skin's art as <code>_<skin>, so a new code needs copies of every skin. The pictures go
into the variant "skin" picks; the others keep the source's art. Each copy has:
  - its container paths renamed to the new code (R<code> for the dorm set);
  - the slot pictures in place of the textures, every texture stored inside the file (no .resS);
  - its own bundle name and CAB name: Unity refuses a bundle whose files are already loaded.
Only the pictures change: the sprites, prefabs, skeleton and animations stay the source doll's, so a
chibi sheet must keep the template's layout.
The chibi prefabs (battle, dorm, enemy side) are not in the doll's bundles but in the shared resource_spine
(Assets/Resources/DaBao/Spine/<code>.prefab, R_<code>.prefab; a skin's in resource_spine_add), and the chibi
head icons in resource_icon_spinehead: clone_prefabs() writes a bundle of just those (SHARED), renamed,
pointing at the copies. Without them the client shows its stand-in chibi.
New codes are Own<gun id>, never containing "Mod": the client treats such codes as Neural Upgrade art
(CommonPicLoader.Builder$$CheckSmallImage adds "_mod"; LoadSmallPic drops "Mod" from skin paths).
The copies are listed in build/custom_art.json; add_entries() declares them in the resource config
(build_resconfig.py, and art_fallback.py, which answers a _nom copy the build could not make with the _he copy).
"""
import hashlib
import io
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIST_FILE = ROOT / "build" / "custom_art.json"
PREFIX = "gfmodart"                     # file names of built copies: PREFIX + bundle name without "_" and "-"
SUFFIXES = ("", "_he", "_nom", "_spine")
SLOTS = ("portrait", "damaged", "card", "chibi", "dorm")
SHEETS = ("chibi", "dorm")
# shared bundles holding a doll's pieces by path: {bundle: (folder, suffix of the copy's bundle name)}.
# The chibi prefabs (battle, dorm, enemy side) are in resource_spine, a skin's in resource_spine_add; the chibi
# head icons in lists are in resource_icon_spinehead.
SHARED = {"resource_spine": ("assets/resources/dabao/spine/", "prefab"),
          "resource_spine_add": ("assets/resources/dabao/spine/", "prefab_add"),
          "resource_icon_spinehead": ("assets/resources/dabao/pics/icons/spinehead/", "head")}
CODE = re.compile(r"[A-Za-z][A-Za-z0-9]{1,31}")
_tree = {}


class ArtError(ValueError):
    pass


def new_code(gun_id):
    """Not "Mod<id>": the client drops "Mod" from codes in picture paths (gfserver/mods.py OLD_ART_CODE)."""
    return f"Own{int(gun_id)}"


def _config_tree():
    """The archived resource config's typetree (read once)."""
    if "tree" not in _tree:
        import UnityPy
        import sys
        sys.path.insert(0, str(ROOT))
        from gfserver import config
        meta = json.loads((config.ARCHIVE_DIR / "resconfig.json").read_text("utf-8"))
        _tree["tree"] = next(o for o in UnityPy.load(str(config.ARCHIVE_DIR / meta["file"])).objects
                             if o.type.name == "MonoBehaviour").read_typetree()
    return _tree["tree"]


def _sections(tree):
    return ("BaseAssetBundles", "AddAssetBundles")


def source_entries(tree, code):
    """[(section, entry)] of a doll's art bundles in the config."""
    names = {f"character_{code.lower()}{s}" for s in SUFFIXES}
    return [(sec, e) for sec in _sections(tree) for e in tree[sec] if e["assetBundleName"].lower() in names]


def model_entries(tree, src):
    """[(section, entry)] of a doll's art bundles and those of its skins (character_<code>_<skin id>...)."""
    pat = re.compile(rf"character_{re.escape(src.lower())}(_\d+)?({'|'.join(s for s in SUFFIXES if s)})?")
    return [(sec, e) for sec in _sections(tree) for e in tree[sec] if pat.fullmatch(e["assetBundleName"].lower())]


def variant_of(entry, src):
    """The skin id a bundle of the doll's belongs to; 0 for its default look."""
    m = re.match(rf"character_{re.escape(src.lower())}_(\d+)", entry["assetBundleName"].lower())
    return int(m.group(1)) if m else 0


def skins(tree, src):
    """The skin ids the doll has art bundles for."""
    return sorted({v for _, e in model_entries(tree, src) if (v := variant_of(e, src))})


def look_code(src, skin):
    """The code a variant's textures are named after: AR15, or AR15_532 for skin 532."""
    return f"{src}_{int(skin)}" if int(skin or 0) else src


def rename(text, src, new):
    """A path or asset name with the source code replaced by the new one (also R<code>, the dorm set)."""
    return re.sub(rf"(?<![A-Za-z0-9])([Rr]?){re.escape(src)}(?![A-Za-z0-9])", lambda m: m.group(1) + new, text, flags=re.I)


def bundle_name(entry, src, new):
    return "character_" + new.lower() + entry["assetBundleName"][len("character_" + src):]


def file_of(name):
    return PREFIX + re.sub(r"[^a-z0-9]", "", name.lower()) + ".ab"


def _find_original(fname):
    import sys
    sys.path.insert(0, str(ROOT))
    from gfserver import config
    hits = config.original_bundles(fname)
    if hits:
        return hits[0]
    game = config.pc_dir(config.GAME_DIR) / fname
    return game if game.is_file() else None


# ---------------------------------------------------------------------------- textures

def texture_slot(tex_name, src):
    """The slot a texture of the source doll's bundles takes its picture from, or None."""
    n, s = tex_name.lower(), src.lower()
    return {f"pic_{s}": "portrait", f"pic_{s}_d": "damaged", f"pic_{s}_n": "card", f"pic_{s}_n_mod": "card",
            s: "chibi", "r" + s: "dorm"}.get(n)


def templates(src, find=_find_original, tree=None):
    """{slot: PIL image} of the source doll's own pictures (the _he version first, as the client shows by default)."""
    tree = tree or _config_tree()
    order = {"_he": 0, "": 1, "_nom": 2, "_spine": 3}
    entries = sorted(source_entries(tree, src), key=lambda se: order.get(se[1]["assetBundleName"].lower()[len("character_" + src):], 9))
    out = {}
    import UnityPy
    for _, e in entries:
        path = find(e["resname"] + ".ab")
        if path is None:
            continue
        for obj in UnityPy.load(str(path)).objects:
            if obj.type.name == "Texture2D":
                tex = obj.read()
                slot = texture_slot(tex.m_Name, src)
                if slot and slot not in out and not tex.m_Name.lower().endswith("_n_mod"):
                    out[slot] = tex.image.convert("RGBA")
    return out


def cut_out(img):
    """A picture with a plain background (a photo backdrop, a white or flat colour) as RGBA with that
    background transparent; pictures that already have transparency, or a busy background, are kept."""
    from PIL import Image, ImageDraw, ImageFilter, ImageStat
    img = img.convert("RGBA")
    if img.getchannel("A").getextrema()[0] < 250:
        return img
    rgb = img.convert("RGB")
    w, h = rgb.size
    step = max(1, (w + h) // 200)
    edge = [(x, y) for x in range(0, w, step) for y in (0, h - 1)] + [(x, y) for y in range(0, h, step) for x in (0, w - 1)]
    cols = [rgb.getpixel(p) for p in edge]
    med = tuple(sorted(c[i] for c in cols)[len(cols) // 2] for i in range(3))
    near = lambda c, t: max(abs(a - b) for a, b in zip(c, t)) <= t_
    t_ = 40
    seeds = [p for p, c in zip(edge, cols) if near(c, med)]
    if len(seeds) < 0.7 * len(edge):
        return img                      # no plain background around it
    marker = (med[0] ^ 0x55, med[1] ^ 0xAA, med[2] ^ 0x33)
    work = rgb.copy()
    for p in seeds:
        if work.getpixel(p) != marker:
            ImageDraw.floodfill(work, p, marker, thresh=t_)
    bg = Image.eval(Image.merge("RGB", [work.getchannel(i).point(lambda v, m=marker[i]: 255 if v == m else 0) for i in range(3)])
                    .convert("L"), lambda v: 255 if v == 255 else 0)
    alpha = Image.eval(bg, lambda v: 255 - v).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1))
    if ImageStat.Stat(alpha).mean[0] < 255 * 0.03:
        return img                      # nothing left: the picture was all background
    out = img.copy()
    out.putalpha(alpha)
    return out


def frame(img, template):
    """A figure placed where the template's figure stands: the same height and feet line, centred on it."""
    from PIL import Image
    w, h = template.size
    tbox = template.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox() or (0, 0, w, h)
    box = img.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox() or (0, 0, img.width, img.height)
    fig = img.crop(box)
    th = tbox[3] - tbox[1]
    scale = min(th / fig.height, w * 0.98 / fig.width)
    r = fig.resize((max(1, round(fig.width * scale)), max(1, round(fig.height * scale))), Image.LANCZOS)
    cx = (tbox[0] + tbox[2]) // 2
    x = min(max(0, cx - r.width // 2), w - r.width)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(r, (x, tbox[3] - r.height), r)
    return out


def fit(slot, img, template):
    """An uploaded picture converted for its slot. template: the source doll's picture (or just its size).
    Portraits: a plain background is removed and the figure framed as the template's. The list picture
    is filled (cropped). A sprite sheet must have the template's proportions: it is the template painted over."""
    from PIL import Image
    size = template if isinstance(template, tuple) else template.size
    w, h = size
    img = img.convert("RGBA")
    if slot in SHEETS:
        if abs(img.width / img.height - w / h) > 0.03 * (w / h):
            raise ArtError(f"The {slot} sheet has to keep the template's layout ({w} x {h} or the same proportions); "
                           f"this picture is {img.width} x {img.height}. Paint over the template and upload that.")
        return img.resize((w, h), Image.LANCZOS)
    if slot == "card":
        scale = max(w / img.width, h / img.height)
        r = img.resize((max(w, round(img.width * scale)), max(h, round(img.height * scale))), Image.LANCZOS)
        x, y = (r.width - w) // 2, (r.height - h) // 2
        return r.crop((x, y, x + w, y + h))
    img = cut_out(img)
    if not isinstance(template, tuple):
        return frame(img, template.convert("RGBA"))
    scale = min(w / img.width, h / img.height)
    r = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    out.paste(r, ((w - r.width) // 2, (h - r.height) // 2))
    return out


def _spine_files(src, find=_find_original, tree=None):
    """{file name, lower case: object} of the source doll's _spine bundle, or {}."""
    import UnityPy
    tree = tree or _config_tree()
    for _, e in source_entries(tree, src):
        if e["assetBundleName"].lower().endswith("_spine"):
            path = find(e["resname"] + ".ab")
            if path is None:
                return {}
            files = {}
            for name, obj in UnityPy.load(str(path)).container.items():
                key = name.rsplit("/", 1)[-1].lower()
                if key not in files or obj.type.name == "Texture2D":
                    files[key] = obj
            return files
    return {}


def _skeleton(files, stem):
    skel, atlas = files.get(f"{stem}.skel.bytes"), files.get(f"{stem}.atlas.txt")
    if skel is None or atlas is None:
        return None
    data, text = skel.read().m_Script, atlas.read().m_Script
    data = data.encode("utf-8", "surrogateescape") if isinstance(data, str) else bytes(data)
    text = text if isinstance(text, str) else bytes(text).decode("utf-8", "replace")
    return data, text


def make_card(portrait, damaged, size):
    """List picture made from the portraits: two halves (normal, damaged), each the upper part of the figure."""
    from PIL import Image
    w, h = size
    out = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    half = w // 2
    for i, img in enumerate((portrait, damaged or portrait)):
        bg = Image.linear_gradient("L").resize((half, h)).point(lambda v: 40 + v // 5)
        part = Image.merge("RGBA", (bg.point(lambda v: v * 3 // 4), bg.point(lambda v: v * 4 // 5), bg, Image.new("L", (half, h), 255)))
        box = img.getbbox() or (0, 0, img.width, img.height)
        ch = max(1, int((box[3] - box[1]) * 0.55))
        cw = max(1, int(ch * half / h))
        cx = (box[0] + box[2]) // 2
        crop = img.crop((cx - cw // 2, box[1], cx - cw // 2 + cw, box[1] + ch)).resize((half, h), Image.LANCZOS)
        part.alpha_composite(crop)
        out.paste(part, (i * half, 0))
    return out


# ---------------------------------------------------------------------------- mods

def collect(found):
    """{new code: {"from", "mod", "images": {slot: file}}} of the enabled mods (a later mod's entry wins)."""
    out = {}
    for m in found:
        for code, spec in (m.get("custom_art") or {}).items():
            if not CODE.fullmatch(str(code)):
                raise ArtError(f"{m['name']}: custom art {code!r}: a model code is letters and digits")
            spec = spec or {}
            images = {}
            for slot, rel in (spec.get("images") or {}).items():
                if slot not in SLOTS:
                    raise ArtError(f"{m['name']}: custom art {code}: unknown picture {slot!r}")
                f = (Path(m["dir"]) / rel).resolve()
                if Path(m["dir"]).resolve() not in f.parents or not f.is_file():
                    raise ArtError(f"{m['name']}: custom art {code}: the {slot} picture {rel} is missing")
                images[slot] = f
            out[str(code)] = {"from": str(spec.get("from") or ""), "mod": m["name"], "images": images,
                              "skin": int(spec.get("skin") or 0)}
    return out


def _pictures(spec, sizes):
    """{slot: PIL image at the texture's size} for one custom art entry; sizes: {slot: (w, h)} of the textures."""
    from PIL import Image
    pics = {}
    for slot, f in spec["images"].items():
        img = Image.open(f).convert("RGBA")
        if slot in sizes and img.size != sizes[slot]:
            img = fit(slot, img, sizes[slot])
        pics[slot] = img
    if "damaged" not in pics and "portrait" in pics:
        pics["damaged"] = pics["portrait"]
    if "card" in sizes and "card" not in pics and "portrait" in pics:
        pics["card"] = make_card(pics["portrait"], pics.get("damaged"), sizes["card"])
    return pics


def _cab(name):
    return "CAB-" + hashlib.md5(name.encode()).hexdigest()


def _cab_files(env, cab):
    """The bundle's files under the new CAB name, without .resS (every texture is inside the file)."""
    return {cab + key[key.index("."):] if "." in key else cab: f for key, f in env.file.files.items()
            if not key.lower().endswith(".ress")}


def clone_bundle(data, src, new, name, spec, cabs=None, look=None):
    """The bytes of a copy of a source bundle for the new code (see the module notes).
    cabs: {old CAB: new CAB} (lower case) is filled in, for clone_prefabs. look: the code the bundle's
    textures are named after (a skin's: AR15_532), default src."""
    look = look or src
    import UnityPy
    env = UnityPy.load(data)
    ab = next(o for o in env.objects if o.type.name == "AssetBundle")
    tree = ab.read_typetree()
    tree["m_Container"] = sorted(((rename(p, src, new).lower(), info) for p, info in tree["m_Container"]), key=lambda c: c[0])
    tree["m_Name"] = tree["m_AssetBundleName"] = name
    ab.save_typetree(tree)
    texes = [o for o in env.objects if o.type.name == "Texture2D"]
    sizes = {}
    for o in texes:
        t = o.read()
        slot = texture_slot(t.m_Name, look)
        if slot:
            sizes.setdefault(slot, (t.m_Width, t.m_Height))
    pics = _pictures(spec, sizes)
    for o in texes:
        t = o.read()
        pic = pics.get(texture_slot(t.m_Name, look))
        if pic is not None:
            t.set_image(pic.resize((t.m_Width, t.m_Height)) if pic.size != (t.m_Width, t.m_Height) else pic,
                        target_format=t.m_TextureFormat, mipmap_count=max(1, int(t.m_MipCount or 1)))
        elif t.m_StreamData is not None and t.m_StreamData.path:
            t.image_data = bytes(t.get_image_data())
            t.m_StreamData.path, t.m_StreamData.offset, t.m_StreamData.size = "", 0, 0
        t.save()
    cab = _cab(name)
    if cabs is not None:
        for key in env.file.files:
            if "." not in key:
                cabs[key.lower()] = cab.lower()
    env.file.files = _cab_files(env, cab)
    return env.file.save(packer="original")


def prefab_paths(entry, src, folder=SHARED["resource_spine"][0]):
    """The pathKeys of the source doll's pieces (its skins' too) in a shared bundle's entry."""
    return [a["pathKey"] for a in entry["assetAllRes"] if a["pathKey"].lower().startswith(folder)
            and rename(a["pathKey"], src, "Own0") != a["pathKey"]]


def _refs(node, out):
    if isinstance(node, dict):
        if "m_FileID" in node and "m_PathID" in node:
            out.append((node["m_FileID"], node["m_PathID"]))
        for v in node.values():
            _refs(v, out)
    elif isinstance(node, list):
        for v in node:
            _refs(v, out)


def clone_prefabs(data, src, new, name, paths, cabs, bundles):
    """The bytes of a bundle with only the given prefabs of resource_spine (and the objects they use), renamed
    to the new code. References to the source doll's bundles go to the copies: cabs {old CAB: new CAB},
    bundles {old bundle name: new}. None when none of the paths is in it."""
    import UnityPy
    env = UnityPy.load(data)
    sf = next(f for k, f in env.file.files.items() if "." not in k)
    ab_obj = next(o for o in env.objects if o.type.name == "AssetBundle")
    tree = ab_obj.read_typetree()
    want = {p.lower() for p in paths}
    keep, container, preload = {ab_obj.path_id}, [], []
    for path, info in tree["m_Container"]:
        if path not in want:
            continue
        seen, ext, todo = set(), set(), [info["asset"]["m_PathID"]]
        while todo:
            pid = todo.pop()
            if pid in seen or pid not in sf.objects:
                continue
            seen.add(pid)
            out = []
            _refs(sf.objects[pid].read_typetree(), out)
            for f, q in out:
                if f == 0:
                    todo.append(q)
                elif q:
                    ext.add((f, q))
        keep |= seen
        deps = [{"m_FileID": 0, "m_PathID": q} for q in sorted(seen)] + [{"m_FileID": f, "m_PathID": q} for f, q in sorted(ext)]
        container.append((rename(path, src, new).lower(), dict(info, preloadIndex=len(preload), preloadSize=len(deps))))
        preload += deps
    if not container:
        return None
    tree["m_Container"] = sorted(container, key=lambda c: c[0])
    tree["m_PreloadTable"] = preload
    tree["m_Name"] = tree["m_AssetBundleName"] = name
    tree["m_Dependencies"] = [bundles.get(d, d) for d in tree["m_Dependencies"]]
    ab_obj.save_typetree(tree)
    for pid in [p for p in sf.objects if p not in keep]:
        del sf.objects[pid]
    for o in list(sf.objects.values()):          # textures inside the file: the .resS is not copied
        if o.type.name == "Texture2D":
            t = o.read()
            if t.m_StreamData is not None and t.m_StreamData.path:
                t.image_data = bytes(t.get_image_data())
                t.m_StreamData.path, t.m_StreamData.offset, t.m_StreamData.size = "", 0, 0
                t.save()
    for ext in sf.externals:
        ext.path = "/".join(cabs.get(x.lower(), x) for x in ext.path.split("/"))
    env.file.files = _cab_files(env, _cab(name))
    return env.file.save(packer="original")


def _clone_model(code, src, spec, entries, tree, find, out_dir, listing, written):
    """Copies of one source model's bundles (its skins' too) and of its pieces in the shared bundles,
    under the new code. The pictures go into the variant spec["skin"] picks (0: the default look);
    the other variants keep the source's art. Returns how many of its default look's bundles were on
    this computer."""
    made, cabs, bundles = 0, {}, {}
    skin = int(spec.get("skin") or 0)
    plain = dict(spec, images={})
    for sec, e in entries:
        name = bundle_name(e, src, code)
        fname = file_of(name)
        path = find(e["resname"] + ".ab")
        v = variant_of(e, src)
        if path is not None:
            (Path(out_dir) / fname).write_bytes(clone_bundle(Path(path).read_bytes(), src, code, name,
                                                             spec if v == skin else plain, cabs, look_code(src, v)))
            written[fname] = name
            bundles[e["assetBundleName"]] = name
            made += v == 0
        listing.append({"code": code, "from": src, "source": e["assetBundleName"], "bundle": name,
                        "file": fname, "section": sec, "built": path is not None})
    for shared, (folder, suffix) in SHARED.items() if made else ():
        pf = next(((sec, e) for sec in _sections(tree) for e in tree[sec] if e["assetBundleName"] == shared), None)
        paths = prefab_paths(pf[1], src, folder) if pf else []
        path = find(pf[1]["resname"] + ".ab") if paths else None
        name = f"character_{code.lower()}_{suffix}"
        data = clone_prefabs(Path(path).read_bytes(), src, code, name, paths, cabs, bundles) if path else None
        if data:
            fname = file_of(name)
            (Path(out_dir) / fname).write_bytes(data)
            written[fname] = name
            listing.append({"code": code, "from": src, "source": shared, "bundle": name, "file": fname,
                            "section": pf[0], "built": True, "paths": paths})
    return made


def build(custom, out_dir, find=_find_original, tree=None, log=print):
    """Write the bundle copies for every custom art entry into out_dir and the list file next to them.
    A source doll with a Neural Upgrade model (<from>Mod) has it copied too, as <code>Mod with its own
    pictures: the client names a doll's upgraded art after its code. Returns {file name: bundle name}."""
    tree = tree or _config_tree()
    known = {e["assetBundleName"].lower() for sec in _sections(tree) for e in tree[sec]}
    listing, written = [], {}
    for code, spec in sorted(custom.items()):
        src = spec["from"]
        entries = model_entries(tree, src) if src else []
        if not entries:
            raise ArtError(f"{spec['mod']}: custom art {code}: {src or '(none)'} is not a T-Doll model the game has")
        if any(f"character_{code.lower()}{s}" in known for s in SUFFIXES):
            raise ArtError(f"{spec['mod']}: custom art {code}: the game already has a model called {code}")
        if not _clone_model(code, src, spec, entries, tree, find, out_dir, listing, written):
            raise ArtError(f"{spec['mod']}: custom art {code}: the art of {src} is not on this computer (press Set up in the launcher)")
        nu = model_entries(tree, src + "Mod")
        if nu and f"{code}Mod" not in custom and not any(f"character_{code.lower()}mod{s}" in known for s in SUFFIXES):
            _clone_model(f"{code}Mod", src + "Mod", {"from": src + "Mod", "mod": spec["mod"], "images": {}, "skin": 0},
                         nu, tree, find, out_dir, listing, written)
        look = f"skin {spec['skin']}" if spec.get("skin") else "default look"
        log(f"  custom art: {code} (from {src}, {look}): {', '.join(sorted(spec['images'])) or 'no pictures'}")
    LIST_FILE.parent.mkdir(parents=True, exist_ok=True)
    if listing:
        LIST_FILE.write_text(json.dumps(listing, indent=1), "utf-8")
    else:
        LIST_FILE.unlink(missing_ok=True)
    return written


def listed():
    try:
        return json.loads(LIST_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return []


def add_entries(tree, listing=None, out_dir=None):
    """Put the copies' entries into a resource config typetree: the source's entry with the new names, paths
    and hashCodes (ids inside the copy remapped, others such as the shared shader kept). A copy the build
    could not make (a _nom bundle not on this computer) is added too: art_fallback.py answers it with the
    other version. Sizes are 0 until build_resconfig.py sets them from the file. Returns the entries added."""
    listing = listed() if listing is None else listing
    if not listing:
        return []
    by_name = {e["assetBundleName"]: (sec, e) for sec in _sections(tree) for e in tree[sec]}
    have = {e["assetBundleName"] for sec in _sections(tree) for e in tree[sec]}
    code = 2 + max(a["hashCode"] for sec in _sections(tree) for e in tree[sec] for a in e["assetAllRes"])
    todo = [x for x in listing if x["bundle"] not in have and x["source"] in by_name]
    remaps = {}                         # per new code, across its copies: the prefab copy depends on the _spine copy
    for item in todo:
        remap = remaps.setdefault(item["code"], {})
        for a in _kept(by_name[item["source"]][1], item):
            remap[a["hashCode"]] = code
            code += 2
    added = []
    for item in todo:
        sec, src_e = by_name[item["source"]]
        remap = remaps[item["code"]]
        e = json.loads(json.dumps(dict(src_e, assetAllRes=_kept(src_e, item))))
        e["assetBundleName"] = item["bundle"]
        e["resname"] = item["file"][:-3]
        e["sizeOriginal"] = e["sizeCompress"] = 0
        f = Path(out_dir or ROOT / "build") / item["file"]
        if f.is_file():
            raw = f.read_bytes()
            sha = hashlib.sha1(raw).hexdigest().upper()
            e["fileHash"] = "-".join(sha[i:i + 2] for i in range(0, len(sha), 2))
            e["fileHashs"] = [e["fileHash"]]
            e["hashString"] = hashlib.md5(raw).hexdigest()
        for a in e["assetAllRes"]:
            a["pathKey"] = rename(a["pathKey"], item["from"], item["code"])
            a["resName"] = rename(a["resName"], item["from"], item["code"])
            a["abName"] = item["bundle"]
            a["hashCode"] = remap[a["hashCode"]]
            a["hasCodes"] = [remap.get(c, c) for c in a["hasCodes"]]
        tree[sec].append(e)
        have.add(item["bundle"])
        added.append(e)
    return added


def _kept(entry, item):
    """The source entry's assets a copy holds: all, or only the listed paths (the prefab copy)."""
    want = set(item.get("paths") or ())
    return [a for a in entry["assetAllRes"] if not want or a["pathKey"] in want]


# ---------------------------------------------------------------------------- previews

def chibi_preview(src, sheet, find=_find_original, tree=None):
    """A still of the source doll's battle chibi drawn with a repainted sheet (PIL image), or None."""
    import sys
    sys.path.insert(0, str(ROOT))
    from gfserver import chibi
    sk = _skeleton(_spine_files(src, find, tree), src.lower())
    return chibi.render(sk[0], sk[1], sheet) if sk else None


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    return buf.getvalue()
