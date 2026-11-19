"""Copy-only code patches for GameAssembly.dll.

  python tools/patch_gameassembly.py <offline copy>\GameAssembly.dll

config_url_http: SunBornUrlManager.GetConfigResUrl returns the HTTPS S3 base
("https://s3.us-east-2.amazonaws.com/sunborn-p1-us/") for the resource config, fetched in
the HotUpdate scene before any Lua hotfix loads. Its first instruction becomes
`jmp SunBornUrlManager.get_DOWNLOAD_URL_FORMAT`, an identical static no-arg getter that
returns "http://gfus-cdn.sunborngame.com/", so the offline proxy can answer the request.

net_reachable: with no network connection (Wi-Fi off), the login SDK refuses to start ("User Center failed to
initialize") because MTSDKBaseApi.NetU.IsNetNotReach (Windows' InternetGetConnectedState) says so, before it asks
the local server for its configs. It now always returns false.

unity_reachable: Application.internetReachability, which the client's downloads (ResCenter) check before fetching
from the local server, always returns ReachableViaLocalAreaNetwork (2).

res_check_button, res_delete_button: the loading screen's "Resource Verification" and "Delete Cache"
(HotUpdateController.CheckAllRes / DeleteResAndDownWhole) run before the Lua hotfixes load, so the client patch
(offline_res_check.lua) can't stop them there. Either would delete or download again the game files this copy
patches. They now return at once. forced_res_check: ResCenter.ForcceFullResCheck, the startup check after a
cut-short verification, also runs before Lua; it now answers no.

play.py applies them before each launch, so a copy set up before a patch was added gets it.

Each patch checks the original bytes first; already-patched bytes are left alone.
Refuses to touch files inside the Steam install.
"""
import struct
import sys
from pathlib import Path


# (name, rva, original bytes, patched bytes)
PATCHES = [
    ("config_url_http", 0x122A6F0,
     bytes.fromhex("4883ec2880"),                  # sub rsp,0x28 ; cmp byte ptr [rip+..],0
     bytes([0xE9]) + (0x122A990 - (0x122A6F0 + 5)).to_bytes(4, "little", signed=True)),
    ("net_reachable", 0x27E1220,
     bytes.fromhex("4883ec58"),                    # sub rsp,0x58
     bytes.fromhex("31c0c3")),                     # xor eax,eax ; ret
    ("unity_reachable", 0x2F804F0,
     bytes.fromhex("4883ec28488b"),                # sub rsp,0x28 ; mov rax,[rip+..]
     bytes.fromhex("b802000000c3")),               # mov eax,2 ; ret
    ("res_check_button", 0x184CB30,
     bytes.fromhex("40534883ec20"),                # push rbx ; sub rsp,0x20
     bytes.fromhex("c3")),                         # ret
    ("res_delete_button", 0x184CCC0,
     bytes.fromhex("40534883ec20"),
     bytes.fromhex("c3")),
    ("forced_res_check", 0x1E156B0,
     bytes.fromhex("40534883ec20"),
     bytes.fromhex("31c0c3")),                     # xor eax,eax ; ret
]


class PatchError(Exception):
    pass


def rva_to_offset(data, rva):
    """Map an RVA to a file offset via the PE section table (stdlib only)."""
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    opt_size = struct.unpack_from("<H", data, pe + 20)[0]
    sec = pe + 24 + opt_size
    for i in range(nsec):
        vsize, vaddr, rawsize, rawptr = struct.unpack_from("<IIII", data, sec + 40 * i + 8)
        if vaddr <= rva < vaddr + max(vsize, rawsize):
            return rva - vaddr + rawptr
    raise PatchError(f"rva {rva:#x} not in any section")


def apply(path, say=print):
    """Applies the patches to a copy's GameAssembly.dll; returns how many changed. Raises PatchError."""
    path = Path(path).resolve()
    if "steamapps" in (p.lower() for p in path.parts):
        raise PatchError(f"refusing to modify a file inside the Steam install: {path}")
    data = bytearray(path.read_bytes())
    offsets = [rva_to_offset(data, rva) for _, rva, _, _ in PATCHES]
    changed = 0
    for (name, rva, orig, new), off in zip(PATCHES, offsets):
        cur = bytes(data[off:off + len(new)])
        if cur == new:
            say(f"{name}: already applied @ file+{off:#x}")
        elif bytes(data[off:off + len(orig)]) == orig:
            data[off:off + len(new)] = new
            changed += 1
            say(f"{name}: {cur.hex()} -> {new.hex()} @ rva {rva:#x} / file+{off:#x}")
        else:
            raise PatchError(f"{name}: unexpected bytes {cur.hex()} @ file+{off:#x}; wrong game build? not modifying")
    if changed:
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    say(f"{path.name}: {changed} patch(es) applied")
    return changed


def main():
    try:
        apply(sys.argv[1])
    except PatchError as e:
        raise SystemExit(str(e))


if __name__ == "__main__":
    main()
