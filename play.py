"""One-click offline play: starts the server, then the game with this server as its HTTP proxy.

  python play.py [path\to\GirlsFrontLine.exe]

The proxy is set only in the game process's environment (http_proxy / HTTP_PROXY / ...),
so no system setting or hosts file changes. The server stops when the game exits.
"""
import logging
import os
import subprocess
import sys
import threading
from pathlib import Path

from gfserver import app, config

DEFAULT_EXE = config.GAME_DIR / "GirlsFrontLine.exe"


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("play")
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_EXE
    if not exe.exists():
        sys.exit(f"Game not found: {exe}")

    sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
    import patch_gameassembly
    try:
        patch_gameassembly.apply(exe.parent / "GameAssembly.dll", say=lambda m: None)
    except (patch_gameassembly.PatchError, OSError) as e:
        log.warning("GameAssembly.dll not patched: %s", e)
    import setup_game
    try:
        shared = setup_game.unshare(exe.parent)
        if shared:
            log.info("%d game files no longer shared with the source install", shared)
    except OSError as e:
        log.warning("game files still shared with the source install: %s", e)
    import build_patch
    try:
        if build_patch.ensure():
            log.info("game patch rebuilt from client_patch/")
    except (SystemExit, subprocess.CalledProcessError, OSError) as e:
        log.warning("game patch not rebuilt: %s", e)

    app.startup_checks()
    httpd = app.ThreadingHTTPServer((config.BIND_HOST, config.BIND_PORT), app.GFHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    proxy = f"http://{config.BIND_HOST}:{config.BIND_PORT}"
    log.info("server/proxy on %s", proxy)

    env = dict(os.environ)
    for k in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
        env[k] = proxy
    for k in ("no_proxy", "NO_PROXY"):
        env.pop(k, None)

    log.info("launching %s", exe)
    game = subprocess.Popen([str(exe)], cwd=str(exe.parent), env=env)
    try:
        game.wait()
    except KeyboardInterrupt:
        log.info("stopping (game left running)")
    finally:
        httpd.shutdown()
        log.info("server stopped")


if __name__ == "__main__":
    main()
