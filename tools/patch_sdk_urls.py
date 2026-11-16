"""Point the account SDK at plain-HTTP URLs so the offline proxy can answer it.

  python tools/patch_sdk_urls.py <offline copy>\GirlsFrontLine_Data\resources.assets

The SDK reads its endpoints from the TextAsset "init_params_json" in resources.assets and
initialises (passport/steamGetConfigs) at launch, before any Lua hotfix is loaded. Over
HTTPS the proxy can only refuse it; over HTTP it can answer.

The edit is length-preserving ("https://host/", -> "http://host/",<space>), so no offsets
or length prefixes change. Idempotent. Refuses to touch files inside the Steam install.
"""
import sys
from pathlib import Path

HOSTS = [b"gf-passport.sunborngame.com", b"gf-webpay-us-api.sunborngame.com", b"gf.sunborngame.com"]


def main():
    path = Path(sys.argv[1]).resolve()
    if "steamapps" in (p.lower() for p in path.parts):
        raise SystemExit(f"refusing to modify a file inside the Steam install: {path}")
    data = bytearray(path.read_bytes())
    # TextAsset layout: name (len-prefixed, 4-aligned), then m_Script as uint32 length + bytes.
    name = data.find(b"init_params_json")
    if name < 0:
        raise SystemExit("init_params_json not found")
    pos = (name + len(b"init_params_json") + 3) & ~3
    length = int.from_bytes(data[pos:pos + 4], "little")
    start, end = pos + 4, pos + 4 + length
    if data[start:start + 1] != b"{" or b'"SDK_ACCOUNT_BASE_URL"' not in data[start:end]:
        raise SystemExit("unexpected init_params_json layout; not modifying")
    changed = already = 0
    for host in HOSTS:
        old = b'"https://' + host + b'/",'
        new = b'"http://' + host + b'/", '
        assert len(old) == len(new)
        n = data.count(old, start, end)
        already += data.count(new, start, end)
        while (i := data.find(old, start, end)) >= 0:
            data[i:i + len(old)] = new
            changed += 1
        if n:
            print(f"  {host.decode()}: {n} url(s) -> http")
    if changed:
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    block = bytes(data[start:end]).decode("utf-8")
    assert "https://" not in block, block
    print(f"{path.name}: {changed} changed, {already} already http, size unchanged ({len(data)} bytes)")


if __name__ == "__main__":
    main()
