"""Build a modded copy of the luapatch AssetBundle with client_patch/*.lua appended to PatchList.

  python tools/build_lpatch.py <original *assettextlpatch.ab> [output.ab]

Never writes to the input path. Requires UnityPy (pip install UnityPy).

Scripts in the bundle are TextAssets XOR'd with a repeating key
(LuaUtility$$GetLuaBytesFromResource). PatchList is executed by
HotFixController.LoadHotFix from LoginController.Awake, so code appended to it runs
before the SDK login.
"""
import sys
from pathlib import Path

import UnityPy

KEY = b"lvbb3zfc3faa8mq1rx0r0gl61b4338fa"
PATCHLIST = "assets/resources/dabao/luapatch/patchlist.lua.txt"
BEGIN, END = "-- >>> gf-offline begin", "-- <<< gf-offline end"
PATCH_DIR = Path(__file__).resolve().parent.parent / "client_patch"
DEFAULT_OUT = Path(__file__).resolve().parent.parent / "build"


def xor(data):
    return bytes(b ^ KEY[i % len(KEY)] for i, b in enumerate(data))


def script_bytes(asset):
    s = asset.m_Script
    return s.encode("utf-8", "surrogateescape") if isinstance(s, str) else bytes(s)


def local_base():
    """The offline server's base URL ("http://127.0.0.1:8080/"), from gfserver.config."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from gfserver import config
    return config.PUBLIC_BASE.rstrip("/") + "/"


def fill(text):
    return text.replace("{{LOCAL_BASE}}", local_base())


def inject(plain, patches):
    text = plain.decode("utf-8")
    if BEGIN in text:  # rebuild from a previously modded bundle: replace our block
        text = text[:text.index(BEGIN)].rstrip("\n") + "\n" + text[text.index(END) + len(END):].lstrip("\n")
    block = "\n".join(f"-- {p.name}\n{fill(p.read_text('utf-8')).rstrip()}" for p in patches)
    return (text.rstrip("\n") + f"\n\n{BEGIN}\n{block}\n{END}\n").encode("utf-8")


def find_patchlist(env):
    for obj in env.objects:
        if obj.type.name == "AssetBundle":
            for path, ptr in obj.read().m_Container:
                if path == PATCHLIST:
                    return ptr.asset.path_id
    raise SystemExit(f"{PATCHLIST} not found in bundle")


def main():
    src = Path(sys.argv[1]).resolve()
    out = Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else DEFAULT_OUT / src.name
    if out == src:
        raise SystemExit("refusing to overwrite the input bundle")
    patches = sorted(PATCH_DIR.glob("*.lua"))
    if not patches:
        raise SystemExit(f"no patches in {PATCH_DIR}")

    env = UnityPy.load(src.read_bytes())
    pid = find_patchlist(env)
    obj = next(o for o in env.objects if o.path_id == pid)
    asset = obj.read()
    new_plain = inject(xor(script_bytes(asset)), patches)
    asset.m_Script = xor(new_plain).decode("utf-8", "surrogateescape")
    asset.save()

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(env.file.save(packer="original"))

    # verify: reload, decrypt, and check the block and every other asset survived
    check = UnityPy.load(out.read_bytes())
    texts = {o.path_id: script_bytes(o.read()) for o in check.objects if o.type.name == "TextAsset"}
    orig = {o.path_id: script_bytes(o.read()) for o in UnityPy.load(src.read_bytes()).objects if o.type.name == "TextAsset"}
    got = xor(texts[pid]).decode("utf-8")
    assert got.endswith(f"{END}\n") and all(fill(p.read_text("utf-8")).strip() in got for p in patches)
    assert "{{" not in got[got.index(BEGIN):], "unfilled placeholder in patches"
    assert set(texts) == set(orig) and all(texts[k] == orig[k] for k in orig if k != pid)
    print(f"wrote {out} ({out.stat().st_size} bytes); PatchList +{len(new_plain) - len(xor(orig[pid]))} bytes; "
          f"{len(orig) - 1} other scripts unchanged; patches: {', '.join(p.name for p in patches)}")


if __name__ == "__main__":
    main()
