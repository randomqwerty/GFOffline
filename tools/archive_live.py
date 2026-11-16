"""Archive the live service's downloadable data, so the offline server works after shutdown.

  python tools/archive_live.py [--skip-content | --config-only] [--no-local-copy] [--workers N] [--limit N]

Safe to re-run at any time: everything is versioned and incremental, so a re-run only
fetches what changed since the last one, and old versions are kept. If the live service
is unreachable the existing archive is left untouched.

Captured (into server/archive/):
  index_version.json + history/     live Index/version (client/ab/data versions)
  transit/serverlist_*.xml          live server list (public)
  resconfig/<name>.txt + resconfig.json   resource config bundle (index of all content)
  stc/stc_<data_version><md5>.zip + stc.json   static data package (.stc tables, catchdata)
  cdn/pc/<resname>.ab               every asset bundle (BaseAssetBundles + AddAssetBundles)
  cdn/pc/<resname>.dat              every bytesData file (video/audio, as served)
  cdn/image/                        ImageConfig.txt and the images it lists
  manifest.json                     what the last run captured, and any failures

Bundles already present in the offline game copy with the expected size are copied
instead of downloaded (--no-local-copy downloads everything). Needs UnityPy and
pycryptodome (pip install UnityPy pycryptodome).
"""
import argparse
import base64
import concurrent.futures as cf
import hashlib
import json
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from gfserver import config  # noqa: E402

ARCHIVE = config.ARCHIVE_DIR
GAME_PC = config.pc_dir(config.GAME_DIR)

GAME_HOST = "http://gf-game.sunborngame.com/index.php/1001/"
TRANSIT = "http://gf-transit.sunborngame.com/index.php"
CDN = "http://gfus-cdn.sunborngame.com/"
CONFIG_BASE = "https://s3.us-east-2.amazonaws.com/sunborn-p1-us/"
DES_KEY = base64.b64decode("kxwL8X2+fgM=")                    # ResSecretData$$EncryptString
DES_IV = base64.b64decode("M9lp+7j2Jdwqr+Yj1h+A")[:8]

OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # direct, never via the game proxy
STAMP = time.strftime("%Y%m%d-%H%M%S")


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def fetch(url, data=None, timeout=60):
    req = urllib.request.Request(url, data=data)
    with OPENER.open(req, timeout=timeout) as r:
        return r.read()


def head_ok(url):
    try:
        with OPENER.open(urllib.request.Request(url, method="HEAD"), timeout=30) as r:
            return r.status == 200
    except (urllib.error.URLError, OSError):
        return False


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), "utf-8")


# ---- versions -------------------------------------------------------------

def archive_versions():
    form = urllib.parse.urlencode({"req_id": f"{int(time.time())}00001"}).encode()
    ver = json.loads(fetch(GAME_HOST + "Index/version", form))
    rec = {"fetched_at": int(time.time()), "url": GAME_HOST + "Index/version", "response": ver}
    prev = json.loads((ARCHIVE / "index_version.json").read_text("utf-8")).get("response", {}) \
        if (ARCHIVE / "index_version.json").exists() else {}
    write_json(ARCHIVE / "history" / f"index_version_{STAMP}.json", rec)
    write_json(ARCHIVE / "index_version.json", rec)
    changed = {k: (prev.get(k), ver.get(k)) for k in ("client_version", "ab_version", "data_version")
               if prev.get(k) != ver.get(k)}
    log(f"live versions: client {ver['client_version']}, ab {ver['ab_version']}, data {ver['data_version']}"
        + (f"  (changed: {sorted(changed)})" if changed else "  (unchanged)"))
    try:
        xml = fetch(TRANSIT, urllib.parse.urlencode(
            {"c": "game", "a": "newserverList", "channel": "en_mica", "platformChannelId": "pc"}).encode())
        (ARCHIVE / "transit").mkdir(parents=True, exist_ok=True)
        (ARCHIVE / "transit" / f"serverlist_{STAMP}.xml").write_bytes(xml)
        (ARCHIVE / "transit" / "serverlist.xml").write_bytes(xml)
    except (urllib.error.URLError, OSError) as e:
        log(f"server list not archived: {e}")
    return ver


# ---- resource config ------------------------------------------------------

def config_name(plain):
    from Crypto.Cipher import DES
    from Crypto.Util.Padding import pad
    enc = DES.new(DES_KEY, DES.MODE_CBC, DES_IV).encrypt(pad(plain.encode(), 8))
    return re.sub(r"[^a-zA-Z0-9 -]", "", base64.b64encode(enc).decode())


def archive_resconfig(ver):
    cv, ab = int(ver["client_version"]), str(ver["ab_version"])
    # The live file is "{X}_{ab}_PCResConfigData2018" with X = floor(cv/100)*10 (3080 for
    # 30810, verified against the CDN); nearby candidates are tried in case that changes.
    candidates = dict.fromkeys([cv // 100 * 10, round(cv / 10), cv // 10, cv // 100 * 10 + 10])
    for x in candidates:
        plain = f"{x}_{ab}_PCResConfigData2018"
        name = config_name(plain) + ".txt"
        target = ARCHIVE / "resconfig" / name
        if target.exists():
            log(f"resource config {plain}: already archived")
            break
        if head_ok(CONFIG_BASE + name):
            data = fetch(CONFIG_BASE + name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            log(f"resource config {plain}: archived ({len(data)} bytes)")
            break
    else:
        raise RuntimeError(f"no resource config found for client {cv}, ab {ab}")
    write_json(ARCHIVE / "resconfig.json", {
        "fetched_at": int(time.time()), "url": CONFIG_BASE + name, "file": f"resconfig/{name}",
        "plain_name": plain, "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "size": target.stat().st_size})
    return target


def read_resconfig(path):
    import UnityPy
    env = UnityPy.load(str(path))
    return next(o.read_typetree() for o in env.objects if o.type.name == "MonoBehaviour")


# ---- stc data package -----------------------------------------------------

def archive_stc(ver):
    dv = str(ver["data_version"])
    name = f"stc_{dv}{hashlib.md5(dv.encode()).hexdigest()}.zip"
    target = ARCHIVE / "stc" / name
    if target.exists():
        log(f"stc package {dv}: already archived")
    else:
        data = fetch(CDN + "data/" + name, timeout=300)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        log(f"stc package {dv}: archived ({len(data)} bytes)")
    write_json(ARCHIVE / "stc.json", {"data_version": dv, "file": f"stc/{name}", "url": CDN + "data/" + name,
                                      "size": target.stat().st_size})


# ---- content (bundles + bytesData) ----------------------------------------

def content_jobs(cfg):
    base = cfg["resUrl"]
    for key in ("BaseAssetBundles", "AddAssetBundles", "passivityAssetBundles"):
        for e in cfg.get(key) or []:
            yield {"name": f"{e['resname']}.ab", "url": f"{base}{e['resname']}.ab",
                   "size": int(e["sizeCompress"]), "local": f"{e['resname']}.ab"}
    for e in cfg.get("bytesData") or []:
        yield {"name": f"{e['resname']}.dat", "url": f"{base}{e['resname']}.dat",
               "size": int(e["sizeCompress"]), "local": None}   # stored decompressed in the game


def get_one(job, use_local):
    target = ARCHIVE / "cdn" / "pc" / job["name"]
    if target.exists() and target.stat().st_size == job["size"]:
        return "have", 0
    local = GAME_PC / job["local"] if job["local"] else None
    if use_local and local and local.exists() and local.stat().st_size == job["size"]:
        shutil.copy2(local, target)
        return "copied", job["size"]
    tmp = target.with_suffix(target.suffix + ".part")
    for attempt in range(3):
        try:
            with OPENER.open(job["url"], timeout=120) as r, open(tmp, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)
            if tmp.stat().st_size != job["size"]:
                raise IOError(f"size {tmp.stat().st_size} != expected {job['size']}")
            tmp.replace(target)
            return "downloaded", job["size"]
        except (urllib.error.URLError, OSError) as e:
            err = e
            time.sleep(2 * (attempt + 1))
    tmp.unlink(missing_ok=True)
    return f"failed: {err}", 0


def archive_content(cfg, use_local, workers, limit):
    (ARCHIVE / "cdn" / "pc").mkdir(parents=True, exist_ok=True)
    jobs = list(content_jobs(cfg))[:limit] if limit else list(content_jobs(cfg))
    need = sum(j["size"] for j in jobs)
    free = shutil.disk_usage(ARCHIVE).free
    log(f"content: {len(jobs)} files, {need / 2**30:.2f} GB in total (disk free {free / 2**30:.1f} GB)")
    stats, failed, done_bytes, t0 = {}, [], 0, time.time()
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(get_one, j, use_local): j for j in jobs}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            status, n = fut.result()
            kind = status.split(":")[0]
            stats[kind] = stats.get(kind, 0) + 1
            done_bytes += n
            if kind == "failed":
                failed.append({"file": futs[fut]["name"], "error": status})
            if i % 250 == 0 or i == len(jobs):
                log(f"  {i}/{len(jobs)} {stats}  ({done_bytes / 2**30:.2f} GB written, {time.time() - t0:.0f}s)")
    return stats, failed


def archive_images():
    out = ARCHIVE / "cdn" / "image"
    out.mkdir(parents=True, exist_ok=True)
    cfg = fetch(CDN + "image/ImageConfig.txt")
    (out / "ImageConfig.txt").write_bytes(cfg)
    got = []
    for line in cfg.decode("utf-8-sig", "replace").splitlines():
        parts = line.strip().split("|")
        if line.startswith("//") or len(parts) != 3 or not parts[2] or "." not in parts[2]:
            continue
        if not (out / parts[2]).exists():
            try:   # listed in image/ImageConfig.txt, served from cartoon/ (SunBornUrlManager.ImageUrl)
                (out / parts[2]).write_bytes(fetch(CDN + "cartoon/" + parts[2]))
            except (urllib.error.URLError, OSError) as e:
                log(f"image {parts[2]} not archived: {e}")
                continue
        got.append(parts[2])
    log(f"images: ImageConfig.txt + {len(got)} image(s)")
    return got


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-content", action="store_true", help="only versions, config, stc package, images")
    ap.add_argument("--config-only", action="store_true", help="only versions and config (first-time setup)")
    ap.add_argument("--no-local-copy", action="store_true", help="download bundles even if the game copy has them")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0, help="only the first N content files (testing)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    ARCHIVE.mkdir(parents=True, exist_ok=True)

    manifest = {"run": STAMP, "status": "incomplete"}
    try:
        ver = archive_versions()
    except (urllib.error.URLError, OSError, ValueError) as e:
        log(f"live service unreachable ({e}); existing archive left as it is")
        return 2
    manifest["versions"] = {k: ver[k] for k in ("client_version", "ab_version", "data_version")}
    cfg_path = archive_resconfig(ver)
    if args.config_only:
        return 0
    archive_stc(ver)
    manifest["images"] = archive_images()
    if not args.skip_content:
        cfg = read_resconfig(cfg_path)
        stats, failed = archive_content(cfg, not args.no_local_copy, args.workers, args.limit)
        manifest.update(content=stats, failed=failed)
    manifest["status"] = "ok" if not manifest.get("failed") else "partial"
    history = json.loads((ARCHIVE / "manifest.json").read_text("utf-8")).get("history", []) \
        if (ARCHIVE / "manifest.json").exists() else []
    manifest["history"] = history + [{k: manifest.get(k) for k in ("run", "status", "versions", "content")}]
    write_json(ARCHIVE / "manifest.json", manifest)
    log(f"done: {manifest['status']}" + (f", {len(manifest['failed'])} failed (see manifest.json)" if manifest.get("failed") else ""))
    return 0 if manifest["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
