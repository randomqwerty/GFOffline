"""HTTP front end.

  POST /index.php                      transit server list (gf-transit.sunborngame.com)
  POST /index.php/<world>/<Mod>/<act>  game API (ConnectionController / Request$$CreateRequest)

Game requests are x-www-form-urlencoded with: uid, outdatacode (AuthCode(body, sign)) or
signcode (AuthCode(sign, sign)), req_id, plus any per-request extra fields.
"""
import json
import logging
import select
import socket
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import battle_hold, client_settings, config, crypto, live_view, mods, passport, transit
from .handlers import HANDLERS, Request, Response, canned_response
from .store import Store

log = logging.getLogger("gfserver")


def _parse_body(blob, keys):
    """Try each candidate key; return (text, key) for the first that verifies."""
    for key in keys:
        if not key:
            continue
        text = crypto.decode(blob, key, check_expiry=False)
        if text is not None:
            return text, key
    return None, ""


def dispatch(function, form, alive=lambda: True):
    """alive(): False once the game has hung up (a battle result waiting for the launcher is then dropped)."""
    uid = form.get("uid", "")
    live_view.seen(uid)
    sign = Store.get().sign_for_uid(uid) if uid else ""
    body = None
    if "outdatacode" in form:
        text, _ = _parse_body(form["outdatacode"], [sign, config.PRELOGIN_KEY])
        if text is None:
            log.warning("%s: could not decrypt outdatacode for uid=%r", function, uid)
        else:
            try:
                body = json.loads(text)
            except ValueError:
                body = text
    req = Request(function=function, form=form, body=body, uid=uid, sign=sign)
    try:
        battle_hold.check(function, body, alive)   # raises battle_hold.Held: no answer at all
    except battle_hold.Rejected:
        return Response("error", battle_hold.REJECTED)
    fn = HANDLERS.get(function)
    if fn is not None:
        try:
            resp = fn(req)
            _map_log(req, resp)
            return resp
        except Exception:            # a failed call answers an error rather than dropping the connection
            log.exception("%s failed", function)
            config.LOG_DIR.mkdir(parents=True, exist_ok=True)
            with open(config.LOG_DIR / "server_errors.log", "a", encoding="utf-8") as f:
                f.write(f"===== {time.strftime('%Y-%m-%d %H:%M:%S')} {function}\n{traceback.format_exc()}\n")
            return Response("error", 1)
    canned = canned_response(req)
    if canned is not None:
        return canned
    # Most state-changing calls are answered with a bare "1" by the real server, so that is
    # the default; the call is still logged as a to-do.
    _record_unhandled(req)
    return Response("plain", "1")


MAP_LOGS_KEPT = 5


def _map_log(req, resp):
    """Every map call and its reply, one file per map run in logs/maps/ (the last MAP_LOGS_KEPT
    runs): what the client asked and what it was told, for when a map misbehaves."""
    if not req.function.startswith("Mission/"):
        return
    try:
        folder = config.LOG_DIR / "maps"
        folder.mkdir(parents=True, exist_ok=True)
        if req.function == "Mission/startMission" or not any(folder.glob("*.jsonl")):
            mid = (req.body or {}).get("mission_id", "map") if isinstance(req.body, dict) else "map"
            (folder / f"{time.strftime('%Y%m%d-%H%M%S')}-{mid}.jsonl").touch()
            for old in sorted(folder.glob("*.jsonl"))[:-MAP_LOGS_KEPT]:
                old.unlink()
        current = sorted(folder.glob("*.jsonl"))[-1]
        entry = {"time": time.strftime("%H:%M:%S"), "function": req.function, "request": req.body,
                 "reply": resp.payload if resp.kind in ("json", "plain") else f"error:{resp.payload}"}
        with open(current, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        log.exception("map log")


def _record_unhandled(req):
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"t": int(time.time()), "function": req.function, "uid": req.uid,
             "form": {k: v for k, v in req.form.items() if k not in ("outdatacode", "signcode")},
             "body": req.body}
    with open(config.LOG_DIR / "unhandled.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    log.warning("UNHANDLED %s body=%s", req.function, json.dumps(req.body, ensure_ascii=False)[:300])


class GFHandler(BaseHTTPRequestHandler):
    server_version = "gfserver"

    def _form(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8", "replace") if n else ""
        query = urllib.parse.urlsplit(self.path).query
        merged = urllib.parse.parse_qs(query, keep_blank_values=True)
        merged.update(urllib.parse.parse_qs(raw, keep_blank_values=True))
        return {k: v[-1] for k, v in merged.items()}

    def _serve_cdn(self):
        # The resource config is requested as <cdn root>/<encrypted name>.txt?r=<ts> (the copy's
        # GetConfigResUrl is patched from HTTPS S3 to this HTTP CDN base). The name only encodes
        # the version, so any root-level .txt is answered with the archived config.
        path = urllib.parse.urlsplit(self.path).path
        segs = [p for p in path.split("/") if p]
        if len(segs) == 1 and segs[0].endswith(".txt") and config.RES_CONFIG:
            # build/resconfig.txt (tools/build_resconfig.py) declares modded bundles with their
            # new sizes; without it the client re-downloads them from the real CDN.
            f = config.MODDED_RES_CONFIG if config.MODDED_RES_CONFIG.exists() else config.ARCHIVE_DIR / config.RES_CONFIG["file"]
            log.info("resource config (requested %s) -> %s (%d bytes)", segs[0], f.name, f.stat().st_size)
            return self._send(f.read_bytes(), "application/octet-stream")
        f = self._archived_cdn_file(segs)
        if f is not None:
            log.info("cdn %s -> %s (%d bytes)", "/".join(segs), f.relative_to(f.parents[2]) if len(f.parents) > 2 else f.name,
                     f.stat().st_size)
            return self._send(f.read_bytes(), "application/octet-stream")
        log.warning("CDN file not archived: %s %s", self.command, self.path)
        return self._send("", status=404)

    @staticmethod
    def _archived_cdn_file(segs):
        """Map a CDN path to the archive (tools/archive_live.py), else the game copy."""
        arch = config.ARCHIVE_DIR
        if len(segs) == 2 and segs[0] == "image":
            cands = [arch / "cdn" / "image" / segs[1]]
        elif len(segs) == 2 and segs[0] == "cartoon":
            cands = [arch / "cdn" / "image" / segs[1]]
        elif len(segs) == 2 and segs[0] == "data" and segs[1].startswith("stc_"):
            # stc_<data_version><md5>.zip: the modded package when its data_version is asked for
            base = config.base_package()
            cands = [p for p in [mods.package_file(segs[1])] if p] + [arch / "stc" / segs[1]] + ([base[0]] if base else [])
        elif len(segs) == 2 and segs[0] == "pc":
            cands = [arch / "cdn" / "pc" / segs[1], config.GAME_DIR / "GirlsFrontLine_Data" / "StreamingAssets" / "Res" / "Pc" / segs[1]]
        else:
            return None
        if ".." in segs[1] or "/" in segs[1] or "\\" in segs[1]:
            return None
        return next((c for c in cands if c.is_file()), None)

    def _send(self, text, ctype="text/html; charset=utf-8", status=200):
        data = text if isinstance(text, bytes) else text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (ConnectionAbortedError, ConnectionResetError, BrokenPipeError):
            log.debug("client closed the connection before the reply was sent")

    def _target_host(self):
        """Host the client meant to reach: from an absolute (proxy-form) URL, else the Host header."""
        url = urllib.parse.urlsplit(self.path)
        host = url.hostname if url.scheme else (self.headers.get("Host") or "").split(":")[0]
        return (host or "").lower()

    def _client_waiting(self):
        """False once the caller has closed its end (a closed socket reads as ready with no data)."""
        try:
            ready, _, _ = select.select([self.connection], [], [], 0)
            return not ready or bool(self.connection.recv(1, socket.MSG_PEEK))
        except OSError:
            return False

    def _launcher_call(self):
        """/gfoffline/...: the launcher's map and battle prompt (gfserver/live_view.py), for local callers only."""
        if self.client_address[0] not in ("127.0.0.1", "::1"):
            return self._send("", status=403)
        url = urllib.parse.urlsplit(self.path)
        what, query = url.path.strip("/").split("/")[-1], urllib.parse.parse_qs(url.query)
        try:
            if what == "map":
                out = live_view.map_view()
            elif what == "team":
                out = live_view.team_view((query.get("id") or ["0"])[0])
            elif what == "chibi":
                out = live_view.chibi_view((query.get("code") or [""])[0], (query.get("skin") or ["0"])[0],
                                           (query.get("kind") or ["gun"])[0])
            elif what == "battle" and self.command == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                out = {"ok": battle_hold.decide(body.get("id"), body.get("send"))}
            elif what == "battle":
                out = battle_hold.waiting()
            else:
                return self._send("", status=404)
        except Exception:
            log.exception("launcher call %s", self.path)
            return self._send(json.dumps({"error": "failed"}), "application/json", status=500)
        return self._send(json.dumps(out, ensure_ascii=False), "application/json; charset=utf-8")

    def _route(self):
        if urllib.parse.urlsplit(self.path).path.startswith("/gfoffline/"):
            return self._launcher_call()
        host = self._target_host()
        kind = config.classify_host(host)
        # Downloads redirected to this server (resUrl in the served config, and the data
        # package URL via client_patch/offline_downloads.lua) arrive directly, not via proxy.
        first = urllib.parse.urlsplit(self.path).path.strip("/").split("/")[0]
        if kind == "game" and (first in ("pc", "data", "image", "cartoon")
                               or (first.endswith(".txt") and "/" not in urllib.parse.urlsplit(self.path).path.strip("/"))):
            kind = "cdn"
        if kind == "cdn":
            return self._serve_cdn()
        if kind == "other":
            log.warning("blocked (offline): %s %s", self.command, self.path)
            return self._send("offline", status=502)
        # After the server list the SDK's passport base becomes our passport_addr (the local
        # server), so passport calls also arrive directly on the game address.
        if kind == "game" and urllib.parse.urlsplit(self.path).path.startswith("/passport/"):
            kind = "passport"
        if kind == "passport":
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n).decode("utf-8", "replace") if n else ""
            result = passport.handle(urllib.parse.urlsplit(self.path).path, raw)
            return self._send(json.dumps(result, ensure_ascii=False), "application/json; charset=utf-8")
        path = urllib.parse.urlsplit(self.path).path
        form = self._form()
        parts = [p for p in path.split("/") if p]
        if not parts and form.get("a") == "heartBeatPacket":
            # ServerInfo.SendHeartBeatRequest, every ~60 s; without an answer the client
            # eventually drops back to the title screen. Recorded live reply:
            return self._send(json.dumps({"1": None, "Err_Msg": "", "Err_No": 100}),
                              "application/json; charset=utf-8")
        if not parts and form.get("a") == "bannerAndSpot":
            # ServerInfo.RequestBannerAndAnnounce: GET <R_BANNER addr>?c=game&a=bannerAndSpot,
            # plain JSON read by Request.RequestResult (Err_No 100 = OK) + banner/spot lists.
            banner = mods.banners()
            log.info("bannerAndSpot -> %d banner(s)", len(banner))
            return self._send(json.dumps({"Err_No": 100, "Err_Msg": "", "banner": banner, "spot": []}),
                              "application/json; charset=utf-8")
        if parts[:1] == ["index.php"] and len(parts) == 1:
            log.info("transit %s", {k: form[k] for k in ("c", "a", "channel", "platformChannelId") if k in form})
            return self._send(transit.server_list_xml(), "text/xml; charset=utf-8")
        if parts[:1] == ["index.php"] and len(parts) >= 4:
            function = "/".join(parts[2:])
            try:
                resp = dispatch(function, form, self._client_waiting)
            except battle_hold.Held:
                self.close_connection = True
                return None
            log.info("%s uid=%s -> %s", function, form.get("uid", ""), resp.kind)
            return self._send(resp.encode())
        log.info("404 %s %s", self.command, self.path)
        self._send("", status=404)

    do_GET = _route
    do_POST = _route

    def do_CONNECT(self):
        # HTTPS through the proxy is an opaque tunnel; nothing here can answer it, so refuse
        # and record the host so it shows up as remaining work.
        log.warning("blocked HTTPS (offline): CONNECT %s", self.path)
        self.send_response(502)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, fmt, *args):
        log.debug("%s - " + fmt, self.address_string(), *args)


def startup_checks():
    m = config.MOD_MANIFEST
    if m and m.get("mods"):
        log.info("mods: %s (data_version %s)", ", ".join(x["name"] for x in m["mods"]), m["data_version"])
        for p in m.get("problems", []):
            log.warning("mod data: %s", p)
    if not config.MODS_DISABLED and mods.stale():
        log.warning("mods/ changed since the last build; run tools/build_mods.py")
    try:
        if client_settings.sync():
            log.info("battle tools and keys updated in the game copy")
    except (client_settings.SettingsError, OSError) as e:
        log.warning("battle tools and keys: %s", e)
    live_view.text("")      # starts reading the game text for the launcher's Map tab


def serve():
    startup_checks()
    httpd = ThreadingHTTPServer((config.BIND_HOST, config.BIND_PORT), GFHandler)
    log.info("listening on %s:%d, game addr %s", config.BIND_HOST, config.BIND_PORT, config.GAME_ADDR)
    httpd.serve_forever()
