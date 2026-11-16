"""Server settings. Override any value with an environment variable of the same name."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALL_FILE = Path(os.environ.get("GF_INSTALL_FILE", ROOT / "install.json"))      # the folders chosen (gfserver/install.py)


def install_settings():
    try:
        return json.loads(INSTALL_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _folder(env, key, default):
    """An environment variable, else install.json (relative to here), else the default."""
    value = os.environ.get(env) or install_settings().get(key)
    return (ROOT / value).resolve() if value else default


SAVE_DIR = Path(os.environ.get("GF_SAVE_DIR", ROOT / "saves"))
LOG_DIR = Path(os.environ.get("GF_LOG_DIR", ROOT / "logs"))
SETTINGS_FILE = Path(os.environ.get("GF_SETTINGS_FILE", ROOT / "settings.json"))     # the launcher's (gfserver/client_settings.py)
# per-map server settings the player edits (Mod Studio's Map spawns page): enemy spawn tables, random node odds
MAP_CONFIG = Path(os.environ.get("GF_MAP_CONFIG", ROOT / "map_config.json"))
MAP_RECORDINGS = Path(os.environ.get("GF_MAP_RECORDINGS", ROOT / "map_recordings.json"))     # tools/import_maps.py

# The server doubles as an HTTP proxy for the game process (see play.py): requests for the
# game's own hosts are answered here, anything else is refused, so no hosts-file edit is needed.
BIND_HOST = os.environ.get("GF_BIND_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("GF_BIND_PORT", "8080"))
# The chess minigame's socket server (gfserver/chess.py); the client is sent here by Index/guildGetGameSign.
CHESS_PORT = int(os.environ.get("GF_CHESS_PORT", str(BIND_PORT + 1)))

# Hosts answered by this server (transit + game API), and Sunborn CDN hosts (bundles/stc).
GAME_HOSTS = {"gf-transit.sunborngame.com", "gf-game.sunborngame.com", "127.0.0.1", "localhost", ""}
CDN_HOSTS = {"gfus-cdn.sunborngame.com", "s3.us-east-2.amazonaws.com"}
# Account SDK (MTSDKApi). Reachable over HTTP once tools/patch_sdk_urls.py has run on the copy.
PASSPORT_HOSTS = {"gf-passport.sunborngame.com", "gf-webpay-us-api.sunborngame.com"}


def classify_host(host):
    """'game', 'passport', 'cdn' (Sunborn CDNs), or 'other' (refused)."""
    if host in GAME_HOSTS:
        return "game"
    if host in PASSPORT_HOSTS:
        return "passport"
    if host in CDN_HOSTS:
        return "cdn"
    return "other"

# Address handed to the client in the server list. The client appends the function
# name directly (addr + "Index/index"), so it must end with "/".
PUBLIC_BASE = os.environ.get("GF_PUBLIC_BASE", f"http://127.0.0.1:{BIND_PORT}")
WORLD_ID = os.environ.get("GF_WORLD_ID", "1001")
GAME_ADDR = f"{PUBLIC_BASE}/index.php/{WORLD_ID}/"
SERVER_NAME = os.environ.get("GF_SERVER_NAME", "Offline")

# Pre-login key used by the client to decode the Index/getUid* response
# (SDKAdapter$$RequestGetUIDWithTokenHandle).
PRELOGIN_KEY = "yundoudou"

# Snapshots of the live service (tools fetched once; see archive/*.json).
ARCHIVE_DIR = _folder("GF_ARCHIVE_DIR", "archive", ROOT / "archive")


def _archived(name):
    p = ARCHIVE_DIR / name
    return json.loads(p.read_text("utf-8")) if p.exists() else None


LIVE_VERSION = (_archived("index_version.json") or {}).get("response", {})
RES_CONFIG = _archived("resconfig.json")   # {"file": "<encrypted name>.txt", ...}
MODDED_RES_CONFIG = ROOT / "build" / "resconfig.txt"

# Starting Index/index state for new accounts (a sample account, anonymized). Its identity
# fields hold these placeholders and are replaced per account when served.
PLAYER_TEMPLATE = Path(os.environ.get("GF_PLAYER_TEMPLATE", ROOT / "data" / "player_template.json"))
NEW_ACCOUNT_TEMPLATE = Path(os.environ.get("GF_NEW_ACCOUNT_TEMPLATE", ROOT / "data" / "new_account.json"))   # tools/make_new_account.py
TEMPLATE_UID = 100000

# A player's own saved account (gfserver/player.py); takes precedence over the template.
PLAYER_DIR = Path(os.environ.get("GF_PLAYER_DIR", ROOT / "player"))

# Static game data, read from the game's own .stc files (see gfserver/stc.py).
GAME_DIR = _folder("GF_GAME_DIR", "game", ROOT / "game")
SOURCE_DIR = _folder("GF_SOURCE_DIR", "source", None)        # the game as installed; only read
# Mod Studio's "take from the CN client": an optional folder of decoded CN tables
CN_DATA_DIR = _folder("GF_CN_DATA_DIR", "cn_data", ROOT / "cn-data")
# The original tables, extracted from the data package (stc.py does it on first use). Not the
# game copy's own stc folder: once the client has downloaded a modded package, that folder holds
# modded tables.
BASE_STC_DIR = ROOT / "build" / "base_stc"
BASE_PACKAGE = ROOT / "build" / "base_package.zip"           # the install's stc_data.dat (tools/setup_game.py)
PRISTINE_DIR = ROOT / "build" / "pristine"                   # original bundles kept by setup and mod builds
STC_DIR = Path(os.environ.get("GF_STC_DIR", BASE_STC_DIR))
STC_SCHEMA = Path(os.environ.get("GF_STC_SCHEMA", ROOT / "data" / "stc_schema.json"))

# Fixed replies for simple calls: data/responses/<Module>/<action>.json (KR tool convention).
RESPONSES_DIR = Path(os.environ.get("GF_RESPONSES_DIR", ROOT / "data" / "responses"))

# Version values reported by transit and Index/version. ab_version picks the resource
# config file name ("{X}_{ab}_PCResConfigData2018", DES-encrypted) the client downloads.
CLIENT_VERSION = os.environ.get("GF_CLIENT_VERSION", str(LIVE_VERSION.get("client_version", "0")))
AB_VERSION = os.environ.get("GF_AB_VERSION", str(LIVE_VERSION.get("ab_version", "")))
DATA_VERSION = os.environ.get("GF_DATA_VERSION", str(LIVE_VERSION.get("data_version", "")))

TIMEZONE = os.environ.get("GF_TIMEZONE", "PST8PDT")  # EN server; see GameData$$SetTimeZoneID

# Mods (gfserver/mods.py, built by tools/build_mods.py into build/mods/). When built, the
# merged tables replace the game's own, and the new data_version makes the client download the
# modded data package. GF_NO_MODS=1 ignores them (the client then re-downloads the original).
MODS_DISABLED = os.environ.get("GF_NO_MODS", "") not in ("", "0")
_MOD_MANIFEST = ROOT / "build" / "mods" / "manifest.json"
MOD_MANIFEST = (json.loads(_MOD_MANIFEST.read_text("utf-8"))
                if _MOD_MANIFEST.exists() and not MODS_DISABLED else None)
if MOD_MANIFEST and MOD_MANIFEST.get("mods"):
    if "GF_DATA_VERSION" not in os.environ:
        DATA_VERSION = MOD_MANIFEST["data_version"]
    if "GF_STC_DIR" not in os.environ:
        STC_DIR = ROOT / "build" / "mods" / "stc"


def reload_install():
    """After install.json changes, in this process (tools/setup_game.py)."""
    global GAME_DIR, SOURCE_DIR, ARCHIVE_DIR
    GAME_DIR = _folder("GF_GAME_DIR", "game", ROOT / "game")
    SOURCE_DIR = _folder("GF_SOURCE_DIR", "source", None)
    ARCHIVE_DIR = _folder("GF_ARCHIVE_DIR", "archive", ROOT / "archive")


def pc_dir(game):
    return Path(game) / "GirlsFrontLine_Data" / "StreamingAssets" / "Res" / "Pc"


def original_bundles(pattern):
    """An original bundle by name or *pattern: kept by setup, in an archive, or in the source folder."""
    folders = [PRISTINE_DIR, ARCHIVE_DIR / "cdn" / "pc"] + ([pc_dir(SOURCE_DIR)] if SOURCE_DIR else [])
    for folder in folders:
        hits = sorted(folder.glob(pattern)) if folder.is_dir() else []
        if hits:
            return hits
    return []


def base_package():
    """(path, data_version) of the original data package: an archive's, else the one setup kept from the install. None if neither."""
    meta = _archived("stc.json")
    if meta and (ARCHIVE_DIR / meta["file"]).is_file():
        return ARCHIVE_DIR / meta["file"], meta["data_version"]
    if BASE_PACKAGE.is_file():
        return BASE_PACKAGE, str(LIVE_VERSION.get("data_version", "")) or "offline"
    return None
