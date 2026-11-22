"""New releases of GF Offline, from the GitHub releases of randomqwerty/GFOffline.

  check()             the latest release when it is newer than this one: {"version", "notes", "page", "url", "size"}, else None
  download(info)      fetch its zip into updates/ and unpack it; returns the unpacked GF-Offline folder
  install(new, pid)   write gf_offline_update.cmd in the temp folder and start it: it waits for process pid (the launcher) to end,
                      copies the new release over this folder and starts GF Offline.exe again

Only the release's own files are replaced. Program folders (_internal, gfserver, client_patch, tools) are mirrored, so
files a new release no longer has are removed (an old client_patch/*.lua would still be built into the game); data and
mods only get the release's files copied over them, so mods and imports stay. saves, player, logs, archive, build, game,
settings.json and install.json are never touched. The request carries no account or user data.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from . import config
from .version import VERSION

LATEST = "https://api.github.com/repos/randomqwerty/GFOffline/releases/latest"
AGENT = "GF-Offline-updater"
ASSET = re.compile(r"^GF-Offline-[\d.]+-win64\.zip$")
MIRRORED = ("_internal", "gfserver", "client_patch", "tools")
MERGED = ("data", "mods")
UPDATES = "updates"


class UpdateError(Exception):
    pass


def parse(version):
    """(1, 0, 3) from "v1.0.3"; () when it isn't a version."""
    m = re.match(r"^v?(\d+(?:\.\d+)*)$", str(version or "").strip())
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def newer(latest, current=VERSION):
    a, b = parse(latest), parse(current)
    n = max(len(a), len(b))
    return bool(a) and a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": AGENT, "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)


def check(timeout=15, current=VERSION):
    try:
        with _get(LATEST, timeout) as r:
            release = json.loads(r.read().decode("utf-8"))
    except (OSError, ValueError) as e:
        raise UpdateError(f"couldn't reach GitHub: {e}")
    version = str(release.get("tag_name") or "").lstrip("v")
    if not newer(version, current):
        return None
    asset = next((a for a in release.get("assets") or [] if ASSET.match(str(a.get("name") or ""))), None)
    return {"version": version, "notes": str(release.get("body") or "").strip(), "page": release.get("html_url") or "",
            "url": asset["browser_download_url"] if asset else "", "size": int(asset.get("size") or 0) if asset else 0}


def frozen():
    """True in the built release, the only layout install() can update."""
    return (config.ROOT / "GF Offline.exe").is_file() and (config.ROOT / "_internal").is_dir()


def download(info, root=None, progress=None, timeout=60):
    """progress(done_bytes, total_bytes) is called as it downloads."""
    if not info.get("url"):
        raise UpdateError("the release has no Windows zip")
    work = Path(root or config.ROOT) / UPDATES
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    zpath = work / f"GF-Offline-{info['version']}-win64.zip"
    part = zpath.with_name(zpath.name + ".part")
    try:
        with _get(info["url"], timeout) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or info.get("size") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except OSError as e:
        raise UpdateError(f"the download stopped: {e}")
    part.replace(zpath)
    out = work / "new"
    try:
        with zipfile.ZipFile(zpath) as z:
            for name in z.namelist():
                target = (out / name).resolve()
                if out.resolve() not in target.parents and target != out.resolve():
                    raise UpdateError(f"the zip has a file outside its folder: {name}")
            z.extractall(out)
    except zipfile.BadZipFile as e:
        raise UpdateError(f"the download isn't a good zip: {e}")
    new = out / "GF-Offline"
    if not (new / "GF Offline.exe").is_file() or not (new / "gfserver").is_dir():
        raise UpdateError("the zip isn't a GF Offline release")
    return new


def script(new, root, pid):
    """The batch file that puts the release in new over root once process pid has ended."""
    new, root = Path(new), Path(root)
    lines = ["@echo off", "chcp 65001 >nul", "title GF Offline update",
             "echo Waiting for GF Offline to close...",
             ":wait",
             f'tasklist /FI "PID eq {int(pid)}" 2>nul | find "{int(pid)}" >nul && (timeout /t 1 /nobreak >nul & goto wait)',
             "echo Copying the new version..."]
    for d in MIRRORED:
        lines.append(f'if exist "{new / d}" robocopy "{new / d}" "{root / d}" /MIR /R:3 /W:1 /NFL /NDL /NJH /NJS /NP >nul')
    for d in MERGED:
        lines.append(f'if exist "{new / d}" robocopy "{new / d}" "{root / d}" /E /R:3 /W:1 /NFL /NDL /NJH /NJS /NP >nul')
    for f in sorted(p.name for p in new.iterdir() if p.is_file()):
        lines.append(f'copy /Y "{new / f}" "{root / f}" >nul')
    lines += [f'start "" "{root / "GF Offline.exe"}"',
              f'cd /d "{root}"',
              f'rmdir /S /Q "{root / UPDATES}"',
              '(goto) 2>nul & del "%~f0"']
    return "\r\n".join(lines) + "\r\n"


def install(new, pid=None, root=None):
    """Start the copy; the caller closes itself right after."""
    root = Path(root or config.ROOT)
    if not frozen():
        raise UpdateError("only the built release can update itself; download the new one from GitHub")
    bat = Path(tempfile.gettempdir()) / "gf_offline_update.cmd"
    bat.write_text(script(new, root, pid or os.getpid()), "utf-8")
    subprocess.Popen(["cmd", "/c", str(bat)], cwd=tempfile.gettempdir(),
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    return bat
