"""Save your own account's server-only data from the live game, so the offline server can use it after shutdown.

  python tools/live_archive.py --log <packet.log>      fetch everything, signing in with the session in a packet log
  python tools/live_archive.py --uid <your uid>        the same, asking for the session's sign (it is not echoed)
  python tools/live_archive.py --from-log <packet.log> no network at all: keep what a packet log already recorded
  python tools/live_archive.py --products              only the shop's paid goods (no login: the game asks without one)

Replies go to player/archive/<uid>/ (gfserver/archived.py reads them), and your account file (the "userinfo" reply,
Index/index) also goes to player/<uid>_user_info.json unless there is one. Safe to re-run: what is already saved is skipped
unless you pass --refresh, and a failed call is listed in the summary.

Every call needs a logged-in session: the game's server has no anonymous calls. Log in with the game, then run this; the
game can stay open, but logging in again ends the session in the log. The tool never asks for a password, and the session's sign is not written
to disk. It sends only the calls in OWN_CALLS and PLAYER_CALLS, which read and don't change anything except that a friend's
dorm shows you as a recent visitor, as visiting it in the game does, and the game's once-a-minute online heartbeat, as the game
sends while it runs. The server answers error:2 both to a call it won't serve (one player's vehicles, say), which is skipped,
and to an ended session, which stops the run.

Other players: your friends are fetched by default (--no-friends skips them). --players <file> adds players who agreed to it,
one uid per line, up to MAX_PLAYERS. There is deliberately no way to walk through every uid on the server: those people
haven't been asked.
The shop's paid goods (gem packs, cards, packages, battle pass) come from the paycenter's product list, asked with no
account at all; every run saves it to data/pay_products.json, as it is the same for everyone.
Friends' support echelons come with Friend/teamGuns, which takes no uid and lists only your own friends'. Their equipment's
stats come only when one is deployed in a mission, so --from-log also keeps each Mission/reinforceFriendTeam it finds.
"""
import argparse
import getpass
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
from gfserver import archived, config, crypto  # noqa: E402
from import_packet_log import read_log, recording_identity  # noqa: E402

GAME_HOST = "http://gf-game.sunborngame.com/index.php/1001/"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # direct, never via the game proxy
MAX_PLAYERS = 200
STOP_AFTER_ERRORS = 5
HEARTBEAT_URL = "http://gf-transit.sunborngame.com/index.php"     # ServerInfo.SendHeartBeatRequest, as a packet log records it
HEARTBEAT_EVERY = 60                                               # ServerInfo.HEART_BEAT_DELAY
PAY_URL = HEARTBEAT_URL            # ServerInfo.RequestProductList: AddrUtil R_PRODUCT_LIST is pay_transit_addr, this host
PAY_QUERY = {"c": "micasdk", "a": "getProducts", "channel_id": "en_mica", "device": "steam"}   # SunBornUrlManager.CHANNLE_ID
PRODUCTS_FILE = ROOT / "data" / "pay_products.json"
REFUSED = "error:2"                 # a refused call, or an ended session (the client logs in again: Request.CheckWWWError)
PROBE = "Friend/list"               # read-only, answered for every account


def own_calls(uid):
    """Calls about the account itself: function -> body, from each client request builder."""
    now = int(time.time())
    return {
        "Index/index": {"time": now, "furniture_data": False},
        "Index/Quest": {},
        "Index/achievement": {"uid": int(uid)},
        "Index/getMailList": {"start_id": 0, "ignore_time": 1},
        "Friend/dormInfo": {"furniture_data": True},
        "Friend/list": {},
        "Friend/blackList": {},
        "Friend/applylist": {},
        "Friend/messagelist": {},
        "Friend/teamGuns": {},
        "Friend/teamAndPraisePrize": {"user_id": int(uid)},
        "Fetter/index": {},
        "Fetter/orgInfo": {},
        "Mall/staticTables": {"is_special": 0},
        "Mission/combinationInfo": {},
        "Chess/index": {},
        "Battlepass/index": {},
        "Manual/ReadList": {"type": "all"},
        "Gun/likeList": {},
        "Dorm/Medal": {"uid": int(uid)},
        "Dorm/list": {},
        "Sangvis/duplicateIndex": {},
        "Event/letterIndex": {},
        "Explore/getMallList": {},
    }


def keyed_calls(uid):
    """Own calls asked more than once: function -> {key: body}. The cafe's comic stand (type 1) and projector
    (type 2) lists (DormMemoriesListController)."""
    return {
        "Dorm/coffeeshop_unlock_list": {str(t): {"user_id": str(uid), "id": 1, "type": t} for t in (1, 2)},
    }


RANK = "Index/rank"
RANK_PAGE = 20                      # the client's page length
# The standing boards by RankingListType and sub_type (1 kills, 2 data samples by difficulty, 3 exercises,
# 4 dolls collected, 5 furniture collected): rank table rows 1-7.
STANDING_BOARDS = ((1, "0"), (2, "1"), (2, "2"), (2, "3"), (3, "0"), (4, "0"), (5, "0"))
PERMANENT_TYPE = 10                 # the rank table's permanent boards (mission scores), asked by rank_id


def rank_boards():
    """{archive key: (first page's body, places shown)} for every leaderboard kept: the standing boards and the
    rank table's permanent ones (read from the game's tables when set up)."""
    boards = {}
    for kind, sub in STANDING_BOARDS:
        body = {"type": kind, "index": 0, "length": RANK_PAGE, "sub_type": sub, "condition": 0}
        boards[archived.board_key(body)] = (body, 100)
    try:
        from gfserver import stc
        rows = [r for r in stc.table("rank") if int(r["type"]) == PERMANENT_TYPE]
    except (OSError, ValueError, KeyError):
        rows = []
    for r in rows:
        body = {"type": PERMANENT_TYPE, "index": 0, "length": RANK_PAGE, "rank_id": int(r["id"]),
                "sub_type": str(r["sub_type"]), "condition": 0}
        boards[archived.board_key(body)] = (body, int(r.get("visable_count") or 100))
    return boards


def merge_page(kept, reply, index):
    """A board reply with this page (from offset index) placed into what was kept of the same board."""
    page = reply.get("rank_list") if isinstance(reply.get("rank_list"), list) else []
    if not index or not isinstance(kept, dict):
        return dict(reply, rank_list=list(page)) if not index else None
    rows = list(kept.get("rank_list") or [])
    if len(rows) < index:
        return None                     # a gap: the pages before it were never seen
    return dict(kept, rank_list=rows[:index] + list(page) + rows[index + len(page):])


OWN_CALLS = tuple(own_calls(1)) + tuple(keyed_calls(1)) + (RANK,)
PLAYER_CALLS = {"Friend/usercard": "f_userid", "Friend/visit": "f_userid", "Vehicle/visit": "to_user_id"}


class Session:
    def __init__(self, host, uid, sign, pause, heartbeat=None):
        """heartbeat: the address of the game's online ping, sent every minute as the game does while it runs."""
        self.host, self.uid, self.sign, self.pause = host.rstrip("/") + "/", str(uid), sign, pause
        self.count = 0
        self.heartbeat, self.last_beat = heartbeat, 0.0
        self.zone = next((p for p in reversed(urllib.parse.urlsplit(host).path.split("/")) if p.isdigit()), "")

    def beat(self):
        """The game's own heartbeat: no sign, just the zone, uid and time. A failure is ignored, as the game does."""
        if not self.heartbeat or time.time() - self.last_beat < HEARTBEAT_EVERY:
            return
        self.last_beat = time.time()
        query = urllib.parse.urlencode({"c": "user", "a": "heartBeatPacket", "zone_id": self.zone, "user_id": self.uid,
                                        "update_time": int(time.time())})
        try:
            with OPENER.open(f"{self.heartbeat}?{query}", timeout=30) as r:
                r.read()
        except (urllib.error.URLError, OSError):
            pass

    def call(self, function, body):
        """The reply as parsed JSON, or raises RuntimeError. Only the calls listed above may be sent."""
        if function not in OWN_CALLS and function not in PLAYER_CALLS:
            raise ValueError(f"{function} is not a read-only call on this tool's list")
        self.beat()
        self.count += 1
        form = urllib.parse.urlencode({"uid": self.uid, "outdatacode": crypto.encode(json.dumps(body), self.sign),
                                       "req_id": f"{int(time.time())}{self.count:05d}"}).encode()
        time.sleep(self.pause)
        with OPENER.open(urllib.request.Request(self.host + function, data=form), timeout=60) as r:
            text = r.read().decode("utf-8", "replace")
        return decode_reply(text, self.sign)


def decode_reply(text, sign):
    if text.startswith("error"):
        raise RuntimeError(text.strip()[:40])
    if text.startswith("#"):
        plain = crypto.decode_gzip(text, sign, check_expiry=False)
    else:
        plain = crypto.decode(text, sign, check_expiry=False)
        plain = text if plain is None else plain
    if plain is None:
        raise RuntimeError("could not decrypt the reply: the session has probably ended, so log in with the game again")
    try:
        return json.loads(plain)
    except ValueError:
        return plain


def without_sign(reply, sign):
    """Index/index holds the session's sign, which must not reach a file; the offline server fills in its own."""
    if isinstance(reply, dict):
        return {k: "" if v == sign else without_sign(v, sign) for k, v in reply.items()}
    if isinstance(reply, list):
        return [without_sign(x, sign) for x in reply]
    return reply


def keep_account_file(uid, reply):
    """The Index/index reply, where the offline server looks for an account file."""
    target = config.PLAYER_DIR / f"{uid}_user_info.json"
    if any(config.PLAYER_DIR.glob("*.json")):
        return None
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
    return target


def fetch_all(session, friends=True, players=(), refresh=False, log=print):
    """Returns (saved, skipped, failed)."""
    uid = session.uid
    saved, skipped, failed = 0, 0, []
    errors = 0
    started = time.time()

    def alive():
        """error:2 comes both for a call the server won't answer (a player's vehicles, say) and for an ended
        session: an own call that always works tells them apart."""
        try:
            session.call(PROBE, {})
        except RuntimeError as e:
            return str(e) != REFUSED
        except (urllib.error.URLError, OSError):
            return True                     # the network: the usual failure count handles it
        return True

    def one(function, body, key=None):
        nonlocal saved, skipped, errors
        if not refresh and archived.path(uid, function, key).exists():
            skipped += 1
            return archived.read(uid, function, key)
        try:
            reply = session.call(function, body)
        except (RuntimeError, urllib.error.URLError, OSError) as e:
            if str(e) == REFUSED:
                if not alive():
                    raise SystemExit(f"stopping: the live server ended the session after {saved} saved in "
                                     f"{(time.time() - started) / 60:.0f} minutes. Log in with the game, record a new packet "
                                     "log, and run this again with that log: what is already saved is skipped.")
                failed.append((function, key, "the live server refused this one (error:2)"))
                return None                 # one call refused, the session fine: not counted as a failure in a row
            failed.append((function, key, str(e)))
            errors += 1
            if errors >= STOP_AFTER_ERRORS:
                raise SystemExit(f"stopping: {errors} calls in a row failed, the last with {e}. What was saved is kept.")
            return None
        errors = 0
        reply = without_sign(reply, session.sign)
        archived.write(uid, function, reply, key)
        saved += 1
        log(f"  saved {function}" + (" (a player)" if key is not None else ""))
        return reply

    def board(body, key, shown):
        """A whole leaderboard, page by page, kept as one reply."""
        nonlocal saved, skipped
        if not refresh and archived.path(uid, RANK, key).exists():
            skipped += 1
            return
        kept = None
        for index in range(0, shown, RANK_PAGE):
            try:
                reply = session.call(RANK, dict(body, index=index))
            except (RuntimeError, urllib.error.URLError, OSError) as e:
                if str(e) == REFUSED and not alive():
                    raise SystemExit(f"stopping: the live server ended the session after {saved} saved.")
                failed.append((RANK, key, str(e)))
                break
            if not isinstance(reply, dict):
                break
            kept = merge_page(kept, without_sign(reply, session.sign), index)
            if len(reply.get("rank_list") or []) < RANK_PAGE:
                break
        if kept is not None:
            archived.write(uid, RANK, kept, key)
            saved += 1
            log(f"  saved {RANK} board {key}")

    replies = {function: one(function, body) for function, body in own_calls(uid).items()}
    for function, bodies in keyed_calls(uid).items():
        for key, body in bodies.items():
            one(function, body, key)
    for key, (body, shown) in rank_boards().items():
        board(body, key, shown)
    if isinstance(replies.get("Index/index"), dict):
        kept = keep_account_file(uid, replies["Index/index"])
        if kept:
            log(f"  account file: {kept.name}")
    others = [str(x) for x in players]
    if friends:
        rows = (replies.get("Friend/list") or {}).get("list") or []
        others = [str(r["f_userid"]) for r in rows if str(r.get("f_userid") or "").isdigit()] + others
    for n, other in enumerate(dict.fromkeys(others), 1):
        log(f"player {n} of {len(set(others))}")
        for function, field in PLAYER_CALLS.items():
            one(function, {field: int(other)}, other)
    return saved, skipped, failed


def fetch_products(url=PAY_URL, target=PRODUCTS_FILE, log=print):
    """The paycenter's product list as the game asks for it (GET, no uid or sign), saved as it came. Returns how many."""
    query = urllib.parse.urlencode(dict(PAY_QUERY, check_version=config.CLIENT_VERSION))
    with OPENER.open(f"{url}?{query}", timeout=60) as r:
        reply = json.loads(r.read().decode("utf-8", "replace"))
    if not isinstance(reply, dict) or str(reply.get("Err_No")) != "100":
        raise RuntimeError(f"the product list came back with {str(reply)[:80]}")
    n = sum(1 for k in reply if k.isdigit())
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(reply, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"  saved {n} paid goods to {target.name}")
    return n


FRIEND_DEPLOY = "Mission/reinforceFriendTeam"     # --from-log only: kept per friend, its "equips" merged


def log_uid(entries):
    """Whose log this is: its login, or a reply naming the account when it holds no login (one saved reply, say)."""
    for e in entries:
        reply = e.get("Response")
        if isinstance(reply, dict):
            if "uid" in reply and "sign" in reply:
                return str(reply["uid"])
            for block in ("user_info", "achievement", "weekly"):
                if str((reply.get(block) or {}).get("user_id") or "").isdigit():
                    return str(reply[block]["user_id"])
    raise SystemExit("nothing in the log says whose account it is")


def import_log(path, log=print):
    """Keep the replies in a packet log, newest last, without any network. Returns how many were written."""
    entries = read_log(path)
    uid = log_uid(entries)
    written = 0
    for e in entries:
        function, reply, body = str(e.get("URL", "")).strip("/"), e.get("Response"), e.get("Request")
        if not isinstance(reply, (dict, list)):
            continue
        if function == RANK and isinstance(reply, dict) and isinstance(body, dict):
            key = archived.board_key(body)
            kept = merge_page(archived.read(uid, RANK, key), reply, int(body.get("index") or 0))
            if kept is not None:
                archived.write(uid, RANK, kept, key)
                written += 1
        elif function in keyed_calls(uid):
            kind = str((body if isinstance(body, dict) else {}).get("type") or "")
            if kind in keyed_calls(uid)[function]:
                archived.write(uid, function, reply, kind)
                written += 1
        elif function in OWN_CALLS:
            archived.write(uid, function, reply)
            written += 1
        elif function in PLAYER_CALLS:
            other = (body if isinstance(body, dict) else {}).get(PLAYER_CALLS[function])
            if str(other or "").isdigit():
                archived.write(uid, function, reply, other)
                written += 1
        elif function == FRIEND_DEPLOY and isinstance(reply, dict) and isinstance(body, dict):
            # a friend's support echelon deployed in a mission: the only reply with its equipment's stats
            friend = str(body.get("friend_team_id") or "").lstrip("-")
            if friend.isdigit() and isinstance(reply.get("equips"), dict):
                kept = archived.read(uid, function, friend) or {}
                archived.write(uid, function, {"equips": {**(kept.get("equips") or {}), **reply["equips"]}}, friend)
                written += 1
    index = archived.read(uid, "Index/index")
    if isinstance(index, dict):
        kept = keep_account_file(uid, index)
        if kept:
            log(f"account file: {kept.name}")
    return written


def read_players(path):
    ids = [line.strip() for line in Path(path).read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    bad = [x for x in ids if not x.isdigit()]
    if bad:
        raise SystemExit(f"{len(bad)} line(s) in {path} are not uids")
    if len(ids) > MAX_PLAYERS:
        raise SystemExit(f"{path} lists {len(ids)} players; the limit is {MAX_PLAYERS}")
    return ids


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", help="packet log holding a login from this session")
    ap.add_argument("--uid", help="your uid, to type the session's sign instead")
    ap.add_argument("--from-log", help="keep what this packet log recorded, with no network")
    ap.add_argument("--host", default=GAME_HOST, help="your server's game address (default: the EN server)")
    ap.add_argument("--no-friends", action="store_true")
    ap.add_argument("--players", help="file of uids of players who agreed, one per line")
    ap.add_argument("--refresh", action="store_true", help="fetch again what is already saved")
    ap.add_argument("--products", action="store_true", help="only the shop's paid goods, with no login")
    ap.add_argument("--pause", type=float, default=2.0, help="seconds between calls (at least 1)")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.from_log:
        print(f"{import_log(args.from_log)} replies kept in {config.PLAYER_DIR / 'archive'}")
        return 0
    if args.products or args.log or args.uid:
        try:
            fetch_products()
        except (RuntimeError, ValueError, urllib.error.URLError, OSError) as e:
            print(f"  failed: the paid goods list: {e}")
            if args.products:
                return 1
    if args.products:
        return 0
    if args.log:
        ident = recording_identity(read_log(args.log))
        uid, sign = ident["uid"], ident["sign"]
        age = (time.time() - Path(args.log).stat().st_mtime) / 60
        print(f"The packet log was last written {age:.0f} minutes ago. The session in it ends when the game logs in again.",
              flush=True)
    elif args.uid:
        uid, sign = args.uid, getpass.getpass("Session sign (hidden): ").strip()
    else:
        ap.error("give --log, --uid or --from-log")
    players = read_players(args.players) if args.players else []
    session = Session(args.host, uid, sign, max(1.0, args.pause), heartbeat=HEARTBEAT_URL)
    saved, skipped, failed = fetch_all(session, friends=not args.no_friends, players=players, refresh=args.refresh)
    print(f"{saved} saved, {skipped} already there, {len(failed)} failed, in {config.PLAYER_DIR / 'archive'}")
    for function, key, why in failed:
        print(f"  failed: {function}{' (a player)' if key else ''}: {why}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
