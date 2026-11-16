"""Units' chibis as still pictures: their Spine skeletons in the setup pose, drawn from the game's own files.

A unit's chibi is <code>.skel.bytes (Spine 2.1 binary) with <code>.atlas.txt and the atlas picture, in the
bundle the resource config names for it (a doll's character_<code>_spine; Strelet's character_mercenary_spine);
a costume's is character<code><skin>spine.ab. Coalition units use their <code>_ally skeleton where there is one.
Buildings have no skeleton: their icon (Pics/Icons/Enemy/<code>.png, else Pics/Icons/Mission/) is used. The skeleton's bones are
placed as set up (no animation), and every slot's attachment from the default skin is drawn in slot
order: regions as quads, meshes as textured triangles. Pictures are cached in build/chibis/.
"""
import io
import json
import math
import re
import struct
import threading
from pathlib import Path

from . import config

CACHE = config.ROOT / "build" / "chibis"
HEIGHT = 96
ICON_HEIGHT = 56
ICON_FOLDERS = ("/pics/icons/enemy/", "/pics/icons/mission/")      # buildings' pictures, first found
_lock = threading.Lock()
_index = {}


class _Reader:
    def __init__(self, data):
        self.b, self.i = data, 0

    def byte(self):
        self.i += 1
        return self.b[self.i - 1]

    def sbyte(self):
        v = self.byte()
        return v - 256 if v > 127 else v

    def boolean(self):
        return self.byte() != 0

    def varint(self):
        out, shift = 0, 0
        while True:
            b = self.byte()
            out |= (b & 0x7F) << shift
            if not b & 0x80:
                return out
            shift += 7

    def int32(self):
        self.i += 4
        return struct.unpack(">i", self.b[self.i - 4:self.i])[0]

    def float(self):
        self.i += 4
        return struct.unpack(">f", self.b[self.i - 4:self.i])[0]

    def string(self):
        n = self.varint()
        if n == 0:
            return None
        self.i += n - 1
        return self.b[self.i - n + 1:self.i].decode("utf-8", "replace")

    def floats(self):
        return [self.float() for _ in range(self.varint())]

    def shorts(self):
        n = self.varint()
        self.i += 2 * n
        return list(struct.unpack(f">{n}H", self.b[self.i - 2 * n:self.i]))

    def ints(self):
        return [self.varint() for _ in range(self.varint())]


def read_skeleton(data):
    """Spine 2.1 binary: bones, slots and the default skin's attachments."""
    r = _Reader(data)
    r.string()
    version = r.string() or ""
    if not version.startswith("2."):
        raise ValueError(f"Spine {version}")
    r.float(), r.float()
    nonessential = r.boolean()
    if nonessential:
        r.string()
    bones = []
    for _ in range(r.varint()):
        name, parent = r.string(), r.varint() - 1
        x, y, sx, sy, rot, _length = (r.float() for _ in range(6))
        flip_x, flip_y, inherit_scale, inherit_rot = (r.boolean() for _ in range(4))
        if nonessential:
            r.int32()
        bones.append({"name": name, "parent": parent, "x": x, "y": y, "sx": sx, "sy": sy, "rot": rot,
                      "flip_x": flip_x, "flip_y": flip_y, "inherit_scale": inherit_scale, "inherit_rot": inherit_rot})
    for _ in range(r.varint()):          # IK constraints: not used for the setup pose
        r.string()
        for _ in range(r.varint()):
            r.varint()
        r.varint(), r.float(), r.sbyte()
    slots = []
    for _ in range(r.varint()):
        name, bone = r.string(), r.varint()
        color = r.int32() & 0xFFFFFFFF
        attachment = r.string()
        r.boolean()
        slots.append({"name": name, "bone": bone, "alpha": (color & 0xFF) / 255, "attachment": attachment})
    skin = {}
    for _ in range(r.varint()):
        slot = r.varint()
        for _ in range(r.varint()):
            key = r.string()
            skin[(slot, key)] = _attachment(r, key, nonessential)
    return bones, slots, skin


def _attachment(r, key, nonessential):
    name = r.string() or key
    kind = r.byte()
    if kind == 0:
        path = r.string() or name
        x, y, sx, sy, rot, w, h = (r.float() for _ in range(7))
        r.int32()
        return {"type": "region", "path": path, "x": x, "y": y, "sx": sx, "sy": sy, "rot": rot, "w": w, "h": h}
    if kind == 1:
        r.floats()
        return None
    if kind in (2, 3):
        path = r.string() or name
        uvs, tris = r.floats(), r.shorts()
        if kind == 2:
            verts = r.floats()
            weights = None
        else:
            flat, weights = r.floats(), []
            i = 0
            while i < len(flat):
                n = int(flat[i])
                weights.append([(int(flat[i + 1 + 4 * k]), flat[i + 2 + 4 * k], flat[i + 3 + 4 * k], flat[i + 4 + 4 * k])
                                for k in range(n)])
                i += 1 + 4 * n
            verts = None
        r.int32()
        r.varint()
        if nonessential:
            r.ints(), r.float(), r.float()
        return {"type": "mesh", "path": path, "uvs": uvs, "tris": tris, "verts": verts, "weights": weights}
    raise ValueError(f"attachment type {kind}")


def world(bones):
    """Each bone's world matrix (a, b, c, d, x, y) in the setup pose: point (px, py) -> (a px + b py + x, c px + d py + y)."""
    out = []
    for bone in bones:
        p = out[bone["parent"]] if bone["parent"] >= 0 else None
        if p:
            x = bone["x"] * p["a"] + bone["y"] * p["b"] + p["x"]
            y = bone["x"] * p["c"] + bone["y"] * p["d"] + p["y"]
            sx = p["sx"] * bone["sx"] if bone["inherit_scale"] else bone["sx"]
            sy = p["sy"] * bone["sy"] if bone["inherit_scale"] else bone["sy"]
            rot = p["rot"] + bone["rot"] if bone["inherit_rot"] else bone["rot"]
            fx, fy = p["fx"] != bone["flip_x"], p["fy"] != bone["flip_y"]
        else:
            x, y = (-bone["x"] if bone["flip_x"] else bone["x"]), (-bone["y"] if bone["flip_y"] else bone["y"])
            sx, sy, rot, fx, fy = bone["sx"], bone["sy"], bone["rot"], bone["flip_x"], bone["flip_y"]
        cos, sin = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        a, b, c, d = cos * sx, -sin * sy, sin * sx, cos * sy
        if fx:
            a, b = -a, -b
        if fy:
            c, d = -c, -d
        out.append({"a": a, "b": b, "c": c, "d": d, "x": x, "y": y, "sx": sx, "sy": sy, "rot": rot, "fx": fx, "fy": fy})
    return out


def read_atlas(text):
    """{region name: (x, y, w, h, rotated)} in the atlas picture."""
    out, name = {}, None
    for line in text.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" ") and ":" not in line:
            name = line.strip()
            out[name] = {}
        elif name and ":" in line:
            k, _, v = line.strip().partition(":")
            out[name][k] = v.strip()
    regions = {}
    for n, f in out.items():
        if "xy" in f and "size" in f:
            x, y = (int(v) for v in f["xy"].split(","))
            w, h = (int(v) for v in f["size"].split(","))
            regions[n] = (x, y, w, h, f.get("rotate") == "true")
    return regions


def _region_image(page, reg):
    x, y, w, h, rotated = reg
    if rotated:
        return page.crop((x, y, x + h, y + w)).rotate(-90, expand=True)
    return page.crop((x, y, x + w, y + h))


def _tri(out, src, s, d):
    """Paint the source triangle s (picture pixels) of src onto out at d (out pixels)."""
    from PIL import Image, ImageDraw
    (x0, y0), (x1, y1), (x2, y2) = d
    det = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    if abs(det) < 1e-6:
        return
    left, top = int(math.floor(min(x0, x1, x2))), int(math.floor(min(y0, y1, y2)))
    right, bottom = int(math.ceil(max(x0, x1, x2))) + 1, int(math.ceil(max(y0, y1, y2))) + 1
    if right <= left or bottom <= top:
        return
    # out pixel (px, py) -> barycentric -> source pixel
    (u0, v0), (u1, v1), (u2, v2) = s
    ia, ib = (y2 - y0) / det, -(x2 - x0) / det
    ic, id_ = -(y1 - y0) / det, (x1 - x0) / det
    # l1 = ia (px - x0) + ib (py - y0); l2 = ic (px - x0) + id (py - y0)
    a = (u1 - u0) * ia + (u2 - u0) * ic
    b = (u1 - u0) * ib + (u2 - u0) * id_
    c = (v1 - v0) * ia + (v2 - v0) * ic
    e = (v1 - v0) * ib + (v2 - v0) * id_
    ox, oy = left - x0, top - y0
    coeffs = (a, b, u0 + a * ox + b * oy, c, e, v0 + c * ox + e * oy)
    size = (right - left, bottom - top)
    patch = src.transform(size, Image.AFFINE, coeffs, resample=Image.BILINEAR)
    mask = Image.new("L", size, 0)
    corners = [(x0 - left, y0 - top), (x1 - left, y1 - top), (x2 - left, y2 - top)]
    ImageDraw.Draw(mask).polygon(corners, fill=255, outline=255)       # the outline closes seams between triangles
    alpha = patch.getchannel("A")
    from PIL import ImageChops
    patch.putalpha(ImageChops.multiply(alpha, mask))
    out.alpha_composite(patch, (left, top))


SUPERSAMPLE = 4


def render(skel, atlas_text, page, height=HEIGHT):
    """The setup pose as an RGBA picture height pixels tall, or None when nothing could be drawn.
    Drawn at SUPERSAMPLE times the size, then shrunk."""
    from PIL import Image
    final, height = height, height * SUPERSAMPLE
    bones, slots, skin = read_skeleton(skel)
    mats = world(bones)
    regions = read_atlas(atlas_text)
    page = page.convert("RGBA")
    parts = []                      # (alpha, [(source tri, world tri)])
    for i, slot in enumerate(slots):
        att = skin.get((i, slot["attachment"])) if slot["attachment"] else None
        reg = regions.get(att["path"]) if att else None
        if not att or reg is None:
            continue
        m = mats[slot["bone"]]
        tx = lambda px, py, m=m: (m["a"] * px + m["b"] * py + m["x"], m["c"] * px + m["d"] * py + m["y"])
        x, y, w, h, rotated = reg
        if att["type"] == "region":
            cos, sin = math.cos(math.radians(att["rot"])), math.sin(math.radians(att["rot"]))
            hw, hh = att["w"] / 2 * att["sx"], att["h"] / 2 * att["sy"]
            local = lambda px, py: (att["x"] + px * cos - py * sin, att["y"] + px * sin + py * cos)
            bl, br, tr, tl = (tx(*local(px, py)) for px, py in ((-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)))
            sbl, sbr, str_, stl = (0, h), (w, h), (w, 0), (0, 0)
            img = _region_image(page, reg)
            parts.append((slot["alpha"], img, [((sbl, sbr, str_), (bl, br, tr)), ((sbl, str_, stl), (bl, tr, tl))]))
            continue
        uvs = att["uvs"]
        if att["weights"] is None:
            pts = [tx(att["verts"][k], att["verts"][k + 1]) for k in range(0, len(att["verts"]), 2)]
        else:
            pts = []
            for ws in att["weights"]:
                px = sum((vx * mats[bi]["a"] + vy * mats[bi]["b"] + mats[bi]["x"]) * wt for bi, vx, vy, wt in ws)
                py = sum((vx * mats[bi]["c"] + vy * mats[bi]["d"] + mats[bi]["y"]) * wt for bi, vx, vy, wt in ws)
                pts.append((px, py))
        src = [(uvs[k] * w, uvs[k + 1] * h) for k in range(0, len(uvs), 2)]      # 2.1: within the region
        tris = [((src[t[0]], src[t[1]], src[t[2]]), (pts[t[0]], pts[t[1]], pts[t[2]]))
                for t in (att["tris"][k:k + 3] for k in range(0, len(att["tris"]) - 2, 3)) if max(t) < len(pts)]
        parts.append((slot["alpha"], _region_image(page, reg), tris))
    corners = [p for _, _, tris in parts for _, d in tris for p in d]
    if not corners:
        return None
    min_x, max_x = min(p[0] for p in corners), max(p[0] for p in corners)
    min_y, max_y = min(p[1] for p in corners), max(p[1] for p in corners)
    pad = 2 * SUPERSAMPLE
    scale = (height - 2 * pad) / max(1.0, max_y - min_y)
    size = (max(1, int((max_x - min_x) * scale) + 2 * pad), height)
    out = Image.new("RGBA", size, (0, 0, 0, 0))
    at = lambda p: (pad + (p[0] - min_x) * scale, pad + (max_y - p[1]) * scale)       # y up -> picture y down
    for alpha, img, tris in parts:
        if alpha <= 0:
            continue
        for s, d in tris:
            _tri(out, img, s, tuple(at(p) for p in d))
    return out.resize((max(1, out.width // SUPERSAMPLE), final), Image.LANCZOS)


def _bundles():
    """{bundle file name without its random prefix and ".ab", lower case: path} of the game's bundles."""
    if "files" not in _index:
        folder = config.pc_dir(config.GAME_DIR)
        found = {}
        for f in folder.glob("*.ab") if folder.is_dir() else ():
            m = re.search(r"(character[a-z0-9]+|resource[a-z0-9]+)\.ab$", f.name.lower())
            if m:
                found.setdefault(m.group(1), f)
        _index["files"] = found
    return _index["files"]


def _assets():
    """{asset path, lower case: bundle name} from the resource config setup built (build/resconfig.txt); kept in
    build/chibis/assets.json, made again when the config changes."""
    if "assets" in _index:
        return _index["assets"]
    src, saved = config.ROOT / "build" / "resconfig.txt", CACHE / "assets.json"
    out = {}
    try:
        stamp = src.stat().st_mtime
        cached = json.loads(saved.read_text("utf-8")) if saved.is_file() else {}
        if cached.get("stamp") == stamp:
            out = cached["assets"]
        else:
            import UnityPy
            env = UnityPy.load(str(src))
            tree = next(o for o in env.objects if o.type.name == "MonoBehaviour").read_typetree()
            for sec in ("BaseAssetBundles", "AddAssetBundles"):
                for e in tree[sec]:
                    for a in e["assetAllRes"]:
                        key = a["pathKey"].lower()
                        if key.endswith((".skel.bytes", ".atlas.txt")) or any(f in key for f in ICON_FOLDERS):
                            out[key] = e["assetBundleName"]
            CACHE.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps({"stamp": stamp, "assets": out}), "utf-8")
    except Exception:
        out = {}
    _index["assets"] = out
    _index["skels"] = {}
    for path, bundle in out.items():
        if path.endswith(".skel.bytes"):
            _index["skels"].setdefault(path.rsplit("/", 1)[1][:-len(".skel.bytes")], bundle)
    _index["icons"] = {}
    for folder in reversed(ICON_FOLDERS):            # the first folder wins
        for path, bundle in out.items():
            if folder in path and path.endswith(".png"):
                _index["icons"][path.rsplit("/", 1)[1][:-4]] = bundle
    return out


def _file(bundle):
    return _bundles().get(re.sub(r"[_\-]", "", bundle.lower()))


def _load(path):
    import UnityPy
    env = UnityPy.load(str(path))
    files = {}
    for name, obj in env.container.items():
        key = name.rsplit("/", 1)[-1].lower()
        if key not in files or obj.type.name == "Texture2D":      # a picture's path names its Sprite too
            files[key] = obj
    return files


def _skeleton(files, stem):
    skel, atlas, page = files.get(f"{stem}.skel.bytes"), files.get(f"{stem}.atlas.txt"), files.get(f"{stem}.png")
    if skel is None or atlas is None or page is None:
        return None
    data, text = skel.read().m_Script, atlas.read().m_Script
    data = data.encode("utf-8", "surrogateescape") if isinstance(data, str) else bytes(data)
    text = text if isinstance(text, str) else bytes(text).decode("utf-8", "replace")
    return render(data, text, page.read().image)


def _from_bundle(path):
    """The battle chibi in a doll's costume bundle: of the skeletons there, the one with a dorm twin r<name> (else
    the shortest name)."""
    files = _load(path)
    stems = {n[:-len(".skel.bytes")] for n in files if n.endswith(".skel.bytes")}
    for stem in sorted((s for s in stems if "r" + s in stems), key=len) or sorted(stems, key=len):
        img = _skeleton(files, stem)
        if img is not None:
            return img
    return None


def _icon(bundle, name, height=ICON_HEIGHT):
    from PIL import Image
    path = _file(bundle)
    obj = _load(path).get(f"{name}.png") if path else None
    if obj is None or obj.type.name != "Texture2D":
        return None
    img = obj.read().image.convert("RGBA")
    box = img.getbbox()
    img = img.crop(box) if box else img
    return img.resize((max(1, round(img.width * height / img.height)), height), Image.LANCZOS)


def _make(kind, code, skin):
    """The picture for (kind, code, skin), or None."""
    _assets()
    skels = _index.get("skels") or {}
    if kind == "building":
        for name in (code,):
            bundle = (_index.get("icons") or {}).get(name)
            if bundle:
                return _icon(bundle, name)
        return None
    if kind == "gun" and int(skin or 0):
        path = _bundles().get(f"character{code}{int(skin)}spine")
        img = _from_bundle(path) if path else None
        if img is not None:
            return img
    stems = {"sangvis": [f"{code}_ally", code]}.get(kind, [code])
    for stem in stems:
        path = _file(skels[stem]) if stem in skels else _bundles().get(f"character{stem}spine")
        if path is not None:
            img = _skeleton(_load(path), stem)
            if img is not None:
                return img
    return None


KINDS = ("gun", "sangvis", "squad", "enemy", "building")


def png(code, skin=0, kind="gun"):
    """PNG bytes of a unit's picture on the map, or None: a doll's (gun code, e.g. "M4A1"; skin id for its
    costume, else the doll's own), Coalition unit's, HOC's or enemy's chibi, or a building's map icon."""
    code = str(code or "").lower()
    if kind not in KINDS or not re.fullmatch(r"[a-z0-9_\-]+", code):
        return None
    name = f"{kind}_{code}_{int(skin or 0)}"
    with _lock:
        cached = CACHE / f"{name}.png"
        if not cached.is_file():
            try:
                img = _make(kind, code, skin)
            except Exception:
                img = None
            data = b""
            if img is not None:
                buf = io.BytesIO()
                img.save(buf, "PNG")
                data = buf.getvalue()
            CACHE.mkdir(parents=True, exist_ok=True)
            cached.write_bytes(data)       # empty: tried, nothing to show
        return cached.read_bytes() or None
