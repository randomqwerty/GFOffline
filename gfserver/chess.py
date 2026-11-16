"""The chess minigame's socket server ("Flight Chess": lobby and games are not HTTP).

Connection (SocketManagerController / SocketHelper):
  1. HTTP Index/guildGetGameSign {} -> {"gateway_url": "<ip>:<port>", "sessionKey", "guid"}
     (RequestSocketGetSessionKey); the client opens a TCP socket there.
  2. Every frame is <int32 length, little-endian><payload>; the payload is <int16 command id,
     little-endian><protobuf message> (SocketHelper$$Send, DataStream little-endian). Command ids are the
     C_CMD / S_CMD enums of the client's embedded game.proto (data/chess_proto.json); the message of an id
     is the one whose name matches it without underscores (C_CHESSLOBBY_STARTTUTORIAL ->
     C_ChessLobbyStartTutorial), or none (an empty body).
  3. C_VerifySession {uid, sessionkey} -> S_VerifySession {result}: any reply counts as verified
     (SocketManagerController$$OnResponseVerifySession). C_HEARTBEST -> S_HEARTBEST.
Lobby (FlightChessSystemNetworkController / FlightChessLobbyNetworkController):
  C_CHESSLOBBY_CONNECT -> S_ChessLobbyConnect {}. A private room (CreateRoom -> S_ChessLobbyCreateRoom
  {roomId}) holds only the commander, whose Start button works with any number of players
  (FlightChessLobbyRoomController$$RefreshGameButtons); StartGame fills the room's empty seats with bots
  (JoinRoomOther + PrepareOther), then S_ChessLobbyStartGame {missionId}, after which the client asks
  Chess/getUserInfo for the players and loads the game. Matching finds three bots (Match -> MatchFinish {users}).
  Quick join finds no rooms.
  The single-player game is the tutorial room:
  C_ChessLobbyStartTutorial {missionId} -> S_ChessLobbyStartTutorial {} and the client loads the
  FlightChessGame scene (RequestStartSingleGame).
Game (FlightChessGameNetworkController): C_CHESS_ROOM_IS_READY (7230) -> S_CHESS_ROOM_READY (17224);
  C_ChessInit (7213) starts the game: S_ChessInitInfo, then S_GameStage events (GameStageEventType:
  1 GameStartInit, 2 SelectCamp, 3 SelectTeam, 4 RoundStartingCardSel, 5 TurnStartPhase,
  6 PreBattleMainPhase, 7 TurnStartGoFlight, 8 MovePhase, 9 BattleSelectPhase, 10 BattlePhase,
  11 PostBattleMainPhase, 12 EndPhase, 14 MonsterMove, 15 RoundStart, 16 MonsterBattle,
  17 MonsterBattleRoll, 18 InitalGoFlight, 21 RandomAirDrop).
Reconnecting: a game outlives its socket for GAME_KEEP seconds (_games), its timeouts playing on. The next lobby connect gets
  S_ChessLobbyReconnectGame instead of S_ChessLobbyConnect, and C_ChessReconnect -> S_ChessReconnect (Game.snapshot). Which of the
  snapshot's fields the client needs was read from the message, not tried against a real dropped socket.
Commands the protocol has no reply for, or nothing offline can do (NO_REPLY), are ignored without a log entry.
Every message the server does not answer yet is logged to logs/chess_unhandled.jsonl with its decoded
body, and every frame to logs/chess_traffic.jsonl when GF_CHESS_TRACE is set.
The game itself is chess_game.py (simplified rules, built-in bots). When it ends, settle() below adds the
rewards to the save and S_ChessLobbyEndGame unlocks the reward screen's Back button.
"""
import json
import logging
import os
import random
import secrets
import socketserver
import struct
import threading
import time
from functools import lru_cache

from . import chess_game, config, protowire, quests, squads, stc
from .store import Store

log = logging.getLogger("gfserver.chess")

# server -> client ids whose message name does not follow the enum name
S_MESSAGE = {"S_CHESSUSECHIPRESULT": "S_ChessUseChip", "S_GAME_STAGE_END": "S_GameStageEnd"}
C_MESSAGE = {"C_CHESS_SET_SHOP_END": "C_ChessShopEnd"}
ERROR_ROOM_NOT_FOUND = 202          # ErrorMsg.ChessLobbyRoomNotFound
GAME_KEEP = 2 * 3600
# previews for other players, client notices with no reply in the protocol, and commands with no sender in the client
NO_REPLY = {"C_CHESS_PREPARE_SET_CAMP", "C_CHESS_PREPARE_SET_TEAM", "C_CHESS_PREPARE_SET_GUN", "C_CHESS_PREPARE_SET_DIRECTION",
            "C_CHESS_PREPARE_MOVE_GUN", "C_CHESS_PREPARE_ATTACK_GUN", "C_CHESS_ANIME_COMP", "C_CHESS_WAKEUP_SUB_STAGE",
            "C_CHESSSKILLEND", "C_CHESSEXITGUN"}

_sessions = {}            # sessionKey -> uid
_lock = threading.Lock()
_games = {}               # uid -> the running game and its lobby state, so a new socket can take it over


def new_session(uid):
    key = secrets.token_hex(16)
    with _lock:
        _sessions[key] = str(uid)
    return key


def gateway_host():
    return "127.0.0.1" if config.BIND_HOST in ("0.0.0.0", "", "::") else config.BIND_HOST


def game_sign(state, body):
    """Index/guildGetGameSign: where the socket server is, and a session key for it. The client asks when
    chess opens, so the socket server starts here and not with the game."""
    ensure_running()
    uid = str(state["user_info"].get("user_id", ""))
    return {"gateway_url": f"{gateway_host()}:{config.CHESS_PORT}", "sessionKey": new_session(uid),
            "guid": int(uid) if uid.isdigit() else 0}


# --- HTTP side (Chess/*): the lobby's own data
#   Chess/index {} -> {"chess_info": {"chess_score", "max_chess_score", "tutorial", "ticket_daily_num",
#       "ticket_daily_refresh_time", "ticket_cost", "acquired_bonus", "team_list": [member]}}
#       (ChessUserInfo$$DecodeUserData; team_list is read from chess_info)
#   Chess/getTeamList {"user_id"} -> {"team_list": [member]}
#   Chess/setTeam {"team_id", "guns": [{"member_id", "gun_id", "skin", "chess_chip_id", "chess_gun_type"}]} "1"
#   member: {"user_id", "team_id", "member_id", "gun_id", "skin", "chess_chip_id", "chess_gun_type"}
#   (PlayerChessData$$.ctor). tutorial 1 = done, so the lobby does not force the tutorial.
def _record(state):
    return state.setdefault("_chess", {"score": 0, "max_score": 0, "tutorial": 1, "teams": {}})


def _team_list(state):
    """The saved teams. The deployment screen only lists a team with all chess_member_num members
    (FlightChessSelectTeamController$$InitUI, ids from 1) and the client has no default of its own,
    so team 1 is the default team until one is saved."""
    uid = int(state["user_info"].get("user_id") or 0)
    teams = {int(tid): members for tid, members in _record(state)["teams"].items()}
    if len(teams.get(1) or []) < chess_game.member_count():
        teams[1] = chess_game.default_members()
    return [dict(m, user_id=uid, team_id=tid) for tid, members in sorted(teams.items()) for m in members]


def index(state, body, now=None):
    rec = _record(state)
    now = int(now or time.time())
    tomorrow = (now - 8 * 3600) // 86400 * 86400 + 86400 + 8 * 3600
    return {"chess_info": {"chess_score": int(rec["score"]), "max_chess_score": int(rec["max_score"]),
                           "tutorial": int(rec["tutorial"]), "ticket_daily_num": _ticket_allowance(rec, now),
                           "ticket_daily_refresh_time": tomorrow, "ticket_cost": int(rec.get("ticket_cost") or 0),
                           "acquired_bonus": ",".join(str(i) for i in rec.get("acquired") or []),
                           "team_list": _team_list(state)}}


BOT_BASE = 9000001                 # bot players' user ids (BOT_BASE .. BOT_BASE + 2)
BOT_NAMES = ("M4A1", "AR-15", "SOP II")


def is_bot(uid):
    return BOT_BASE <= int(uid or 0) < BOT_BASE + len(BOT_NAMES)


def user_info(state, body):
    """Chess/getUserInfo {"user_ids": [...]} -> [{"user_id", "username", "chess_score", "user_lv",
    "headpic_id", "frame_id", "commander_info"}] (FlightChessPlayerUser$$DecodeDetailInfo;
    commander_info is the comma list of worn uniform pieces, CommanderInfo$$AnalysisSelfCloth).
    Offline the room holds the commander and bots, who wear the commander's look."""
    ui, rec = state["user_info"], _record(state)
    me = int(ui.get("user_id") or 0)
    card = state.get("user_friend_info") or {}
    look = str((state.get("commander_with_user_info") or {}).get("dressed") or "")
    out = []
    for uid in (body or {}).get("user_ids") or []:
        uid = int(uid)
        if uid != me and not is_bot(uid):
            continue
        out.append({"user_id": uid, "username": str(ui.get("name", "")) if uid == me else BOT_NAMES[uid - BOT_BASE],
                    "chess_score": int(rec["score"]) if uid == me else 0, "user_lv": int(ui.get("lv") or 1),
                    "headpic_id": int(card.get("headpic_id") or 0), "frame_id": int(card.get("frame_id") or 0),
                    "commander_info": look})
    return out


def team_list(state, body):
    return {"team_list": _team_list(state)}


def set_team(state, body):
    body = body or {}
    keys = ("member_id", "gun_id", "skin", "chess_chip_id", "chess_gun_type")
    guns = [{k: int(g.get(k) or 0) for k in keys} for g in body.get("guns") or [] if isinstance(g, dict)]
    _record(state)["teams"][str(int(body.get("team_id") or 0))] = guns
    return "1"


@lru_cache(maxsize=1)
def _names():
    """(client id -> message name or None, server enum name -> (id, message name or None))."""
    msgs = {m.replace("_", "").lower(): m for m in protowire.schema()["messages"] if "." not in m}
    c = {v: C_MESSAGE.get(k) or msgs.get(k.replace("_", "").lower()) for k, v in protowire.enum("C_CMD").items()}
    s = {k: (v, S_MESSAGE.get(k) or msgs.get(k.replace("_", "").lower())) for k, v in protowire.enum("S_CMD").items()}
    return c, s


def frame(cmd, body=None):
    """A server frame for S_CMD name cmd."""
    sid, msg = _names()[1][cmd]
    payload = struct.pack("<H", sid) + (protowire.encode(msg, body or {}) if msg else b"")
    return struct.pack("<i", len(payload)) + payload


def _log(name, entry):
    try:
        config.LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(config.LOG_DIR / name, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except OSError:
        pass


def _running(uid):
    with _lock:
        entry = _games.get(str(uid))
        if entry and (entry["play"].over or time.time() - entry["play"].started > GAME_KEEP):
            del _games[str(uid)]
            entry = None
    return entry


class Connection:
    """One client socket: its session and what it is doing."""

    def __init__(self, send):
        self.send = send
        self.uid = None
        self.room = None
        self.game = None
        self.play = None           # the running chess_game.Game

    def reply(self, cmd, body=None):
        if os.environ.get("GF_CHESS_TRACE"):
            _log("chess_traffic.jsonl", {"t": time.time(), "dir": "out", "cmd": cmd, "body": body})
        self.send(frame(cmd, body))

    def game_reply(self, cmd, body=None):
        """A game's timers keep running after the socket has gone."""
        try:
            self.reply(cmd, body)
        except OSError:
            pass

    def _adopt(self, entry):
        self.play, self.game, self.room = entry["play"], entry["game"], entry["room"]
        self.play.reply, self.play.on_finish = self.game_reply, self.game_finished

    # --- session
    def on_C_VERIFYSESSION(self, body):
        with _lock:
            uid = _sessions.get(body.get("sessionkey"))
        self.uid = uid or str(body.get("uid"))
        self.reply("S_VERIFYSESSION", {"result": 0})

    def on_C_HEARTBEST(self, body):
        self.reply("S_HEARTBEST")

    def on_C_GETSERVERTIME(self, body):
        self.reply("S_GETSERVERTIME", {"serverTime": int(time.time())})

    # --- lobby
    def on_C_CHESSLOBBY_CONNECT(self, body):
        entry = _running(self.uid)
        if entry is None:
            return self.reply("S_CHESSLOBBY_CONNECT")
        self._adopt(entry)
        info = self.game or {}
        users = [p["uid"] for p in self.play.players]
        self.reply("S_CHESSLOBBY_RECONNECT_GAME", {
            "roomId": int(info.get("room") or 0) % 1000000, "crewMode": int(info.get("crew") or 1), "userNum": len(users), "joinLimit": 0,
            "ownerId": self.play.me, "users": users, "preparedUsers": users, "isMatch": int(bool(info.get("match"))),
            "missionId": self.play.mission, "mapId": 0, "isRandomMission": False})

    def on_C_CHESSLOBBY_STARTTUTORIAL(self, body):
        self.game = {"mission": int(body.get("missionId") or 0)}
        self.reply("S_CHESSLOBBY_STARTTUTORIAL")

    def on_C_CHESSLOBBY_ENDTUTORIAL(self, body):
        self.game = None
        self.reply("S_CHESSLOBBY_ENDTUTORIAL")

    # --- rooms: offline the commander waits alone, and bots take the empty seats when the game starts.
    def _later(self, fn, delay=0.8):
        t = threading.Timer(delay, fn)
        t.daemon = True
        t.start()

    def _fill_with_bots(self):
        users = self.room["users"]
        seats = min(int(self.room.get("userNum") or len(users)), len(BOT_NAMES) + 1)
        for bot in [BOT_BASE + i for i in range(seats - len(users))]:
            users.append(bot)
            self.reply("S_CHESSLOBBY_JOINROOM_OTHER", {"userId": bot})
            self.reply("S_CHESSLOBBY_PREPARE_OTHER", {"userId": bot, "prepare": 1})

    def on_C_CHESSLOBBY_CREATEROOM(self, body):
        self.room = dict(body, roomId=100000 + int(time.time()) % 900000, users=[int(self.uid or 0)])
        self.reply("S_CHESSLOBBY_CREATEROOM", {"roomId": self.room["roomId"]})

    def on_C_CHESSLOBBY_MODROOM(self, body):
        if self.room:
            self.room.update(body)
        self.reply("S_CHESSLOBBY_MODROOM")

    def on_C_CHESSLOBBY_LEAVEROOM(self, body):
        self.room = None
        self.reply("S_CHESSLOBBY_LEAVEROOM")

    def on_C_CHESSLOBBY_PREPARE(self, body):
        self.reply("S_CHESSLOBBY_PREPARE")

    def on_C_CHESSLOBBY_STARTGAME(self, body):
        room = self.room or {}
        if room.get("started"):         # all seats ready also starts a countdown on the room screen
            return
        if room:
            room["started"] = True
            self._fill_with_bots()
        mission = int(room.get("missionId") or 1)
        self.game = {"mission": mission, "users": list(room.get("users") or [int(self.uid or 0)]), "match": bool(room.get("isMatch")),
                     "crew": int(room.get("crewMode") or 1), "room": str(room.get("roomId") or int(time.time()))}
        self.reply("S_CHESSLOBBY_STARTGAME", {"missionId": mission})

    def on_C_CHESSLOBBY_CHAT(self, body):
        self.reply("S_CHESSLOBBY_CHAT", {"uid": int(self.uid or 0), "chatType": int(body.get("chatType") or 0),
                                         "chatContent": str(body.get("chatContent") or "")})

    def on_C_CHESSLOBBY_JOINROOM(self, body):
        self.reply("S_ERROR", {"errorNum": ERROR_ROOM_NOT_FOUND})      # nobody else's rooms offline

    def on_C_CHESSLOBBY_KICKUSER(self, body):
        kicked = int(body.get("kickedUserId") or 0)
        if self.room and kicked in self.room.get("users", []):
            self.room["users"].remove(kicked)
        self.reply("S_CHESSLOBBY_KICKUSER")
        self.reply("S_CHESSLOBBY_KICKUSER_OTHER", {"userId": kicked})

    def on_C_CHESSLOBBY_BLACKLIST(self, body):
        self.reply("S_CHESSLOBBY_BLACKLIST", {"status": 0, "num": 0})

    def on_C_CHESSLOBBY_QUICKJOIN(self, body):
        self.reply("S_CHESSLOBBY_QUICKJOIN_FAILED")      # nobody else's rooms offline

    def on_C_CHESSLOBBY_SEARCHROOM(self, body):
        self.reply("S_CHESSLOBBY_SEARCHROOM", {"status": 0})

    def on_C_CHESSLOBBY_MATCH(self, body):
        """Matching finds three bots."""
        self.room = {"missionId": 1, "users": [int(self.uid or 0)] + [BOT_BASE + i for i in range(3)], "isMatch": True,
                     "crewMode": int(body.get("crewMode") or 1)}
        self.reply("S_CHESSLOBBY_MATCH", {"userNum": 1})
        self._later(lambda: self.reply("S_CHESSLOBBY_MATCH_FINISH", {"users": self.room["users"]} if self.room else {}), 1.5)

    def on_C_CHESSLOBBY_CANCELMATCH(self, body):
        self.room = None
        self.reply("S_CHESSLOBBY_CANCELMATCH")

    def on_C_CHESSLOBBY_MATCHPREPARE(self, body):
        self.reply("S_CHESSLOBBY_MATCHPREPARE")
        for b in (self.room or {}).get("users", [])[1:]:
            self.reply("S_CHESSLOBBY_MATCHPREPARE_OTHER", {"userId": b})
        self.on_C_CHESSLOBBY_STARTGAME({})

    # --- game
    def on_C_CHESS_ROOM_IS_READY(self, body):
        self.reply("S_CHESS_ROOM_READY")

    def on_C_CHESSINIT(self, body):
        """Seats left empty (the single game, a two-seat room) stay empty; the single game gets three bots."""
        me = int(self.uid or 0)
        info = self.game or {}
        users = list(info.get("users") or [me] + [BOT_BASE + i for i in range(len(BOT_NAMES))])
        try:
            own = str(Store.get().load_player(str(me), config.PLAYER_TEMPLATE)["user_info"].get("name", ""))
        except (OSError, ValueError, KeyError):
            own = ""
        names = {me: own, **{BOT_BASE + i: n for i, n in enumerate(BOT_NAMES)}}
        self.play = chess_game.Game(self.game_reply, me, users, names, info.get("mission") or 1, on_finish=self.game_finished,
                                    single=not info.get("users"))
        with _lock:
            _games[str(me)] = {"play": self.play, "game": self.game, "room": self.room}
        self.play.start()

    def on_C_CHESSRECONNECT(self, body):
        entry = _running(self.uid)
        if entry is None:
            return self.reply("S_CHESSLOBBY_ENDGAME")
        self._adopt(entry)
        with self.play.lock:
            self.reply("S_CHESSRECONNECT", self.play.snapshot())

    def on_C_CHESS_ROOM_IS_ALIVE(self, body):
        self.reply("S_CHESS_ROOM_IS_ALIVE", {"isAlive": _running(self.uid) is not None})

    def on_C_CHESS_CHANCE_CHOOSE_INFO(self, body):
        open_now = bool(self.play) and self.play.stage_id == chess_game.AIR_DROP
        self.reply("S_CHESS_CHANCE_CHOOSE_INFO", {"isChoose": not open_now, "chanceList": [chess_game.AIR_DROP_CARD, chess_game.AIR_DROP_COINS] if open_now else []})

    def game_finished(self, play):
        """Save the result, then tell the client: the reward screen only unlocks Back on S_ChessLobbyEndGame
        and only hears it once it has opened (after the rank animation, of unknown length), so it is sent a few
        times. Nothing else depends on it, and a repeat after the screen has closed is only logged by the client."""
        if self.room:
            self.room.pop("started", None)
        with _lock:
            _games.pop(str(play.me), None)
        try:
            store = Store.get()
            state = store.load_player(str(play.me), config.PLAYER_TEMPLATE)
            settle(state, play, self.game or {})
            store.save_player(str(play.me), state)
        except (OSError, ValueError, KeyError, IndexError):
            log.exception("chess: could not save the result")

        def tell():
            try:
                self.reply("S_CHESSLOBBY_ENDGAME")
            except OSError:
                pass                     # the client has gone
        for delay in END_NOTICES:
            self._later(tell, delay)

    def on_C_CHESSLOBBY_ENDGAME(self, body):
        self.play, self.game, self.room = None, None, None
        self.reply("S_CHESSLOBBY_ENDGAME")

    def on_C_CHESSLOBBY_GIVEUP(self, body):
        self.play, self.game, self.room = None, None, None
        self.reply("S_CHESSLOBBY_GIVEUP")

    def handle(self, cid, data):
        cnames = _names()[0]
        msg = cnames.get(cid)
        body = protowire.decode(msg, data) if msg else {}
        name = next((k for k, v in protowire.enum("C_CMD").items() if v == cid), str(cid))
        if os.environ.get("GF_CHESS_TRACE"):
            _log("chess_traffic.jsonl", {"t": time.time(), "dir": "in", "cmd": name, "body": body})
        fn = getattr(self, "on_" + name, None)
        if fn is None and self.play is not None:
            game_fn = getattr(self.play, "on_" + name, None)
            if game_fn is not None:
                log.info("chess %s %s", name, body)
                with self.play.lock:
                    game_fn(body)
                return
        if fn is None and name in NO_REPLY:
            return
        if fn is None:
            log.info("chess %s (not handled yet) %s", name, body)
            _log("chess_unhandled.jsonl", {"t": int(time.time()), "uid": self.uid, "cmd": name, "id": cid, "body": body})
            return
        log.info("chess %s", name)
        fn(body)


class _Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sock = self.request
        out = threading.Lock()

        def send(data):
            with out:
                sock.sendall(data)

        conn = Connection(send)
        log.info("chess client connected from %s:%d", *self.client_address[:2])
        buf = b""
        try:
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    return
                buf += chunk
                while len(buf) >= 4:
                    (n,) = struct.unpack("<i", buf[:4])
                    if len(buf) < 4 + n:
                        break
                    payload, buf = buf[4:4 + n], buf[4 + n:]
                    (cid,) = struct.unpack("<H", payload[:2])
                    try:
                        conn.handle(cid, payload[2:])
                    except Exception:                       # one bad message must not drop the socket
                        log.exception("chess command %s", cid)
        except OSError:
            return


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def serve_in_background():
    """Start the socket server on config.CHESS_PORT in a daemon thread; returns the server."""
    srv = _Server((config.BIND_HOST, config.CHESS_PORT), _Handler)
    threading.Thread(target=srv.serve_forever, name="chess", daemon=True).start()
    log.info("chess socket server on %s:%d", config.BIND_HOST, config.CHESS_PORT)
    return srv


_server = None


def ensure_running():
    """The socket server, started once; None when its port is taken (the rest of the game runs without it)."""
    global _server
    with _lock:
        if _server is None:
            try:
                _server = serve_in_background()
            except OSError as e:
                log.warning("chess socket server not started (port %d): %s", config.CHESS_PORT, e)
        return _server


# --- the end of a game. The client works out the rewards by itself and adds them to its own copy
#   (FlightChessRewardController$$UpdateUserInfo, $$ShowTicket), so this does the same to the save:
#   score: only a matched game, chess_scorelevel.score_get "<crew mode>:<by rank>;..." of the player's level
#   prize: chess_model[crew mode].prize by rank; not the single game (it has no crew mode)
#   tickets (FlightChessGasha$$SetTicketCount), not the single game: time_ticket_limit "1:5,100,100" is 5 per
#     minute, at most 100 a game, and at most the allowance left; rank_ticket_get "7,5,4,2" by rank in a
#     matched game; item 53 stops at ticket_get_limit. The allowance (chess_info.ticket_daily_num) grows by
#     100 a day up to ticket_dailyget_max.
#   APPROXIMATION: chess_scorelevel.prize is not paid (no client call claims it; presumably a season-end mail).
# Chess/log {"chess_log_id"} -> {"chess_log_with_user": [row]}, the commander's games, newest first, older than
#   chess_log_id when it is set. Chess/getLogInfo {"chess_log_id"} -> {"chess_log_info": [row of each seat]}.
#   row: GF.FlightChess.ChessRecordInfo$$.ctor.
END_NOTICES = (2, 6, 12, 20)
LOG_LIMIT = 30


def _chess_config(name):
    return next(str(r["parameter_value"]) for r in stc.table("chess_game_config") if r["parameter_name"] == name)


def _ticket_allowance(rec, now):
    """Tickets the time reward can still pay; a day's allowance arrives with each new server day."""
    day = (int(now) - 8 * 3600) // 86400
    per_day = int(_chess_config("time_ticket_limit").split(",")[-1])
    rec["ticket_allowance"] = min(int(_chess_config("ticket_dailyget_max")),
                                  int(rec.get("ticket_allowance", 0)) + (day - int(rec.get("ticket_day", day - 1))) * per_day)
    rec["ticket_day"] = day
    return rec["ticket_allowance"]


def _score_gain(score, crew, rank):
    level = next((r for r in stc.table("chess_scorelevel")
                  if int(r["score_floor"]) <= score and (int(r["score_ceilling"]) < 0 or score <= int(r["score_ceilling"]))), None)
    for part in str((level or {}).get("score_get") or "").split(";"):
        mode, _, values = part.partition(":")
        values = values.split(",")
        if mode == str(crew) and rank <= len(values):
            return int(values[rank - 1])
    return 0


def _rank_prize(crew, rank):
    row = next((r for r in stc.table("chess_model") if int(r["id"]) == crew), None)
    ids = str((row or {}).get("prize") or "").split(",")
    return int(ids[rank - 1]) if rank <= len(ids) and ids[rank - 1].isdigit() else 0


def _time_tickets(rec, seconds, now):
    every, rest = _chess_config("time_ticket_limit").split(":")
    per, game_limit = rest.split(",")[:2]
    allowance = _ticket_allowance(rec, now)
    return min(seconds // 60 // int(every) * int(per), int(game_limit), allowance)


def settle(state, play, info, now=None):
    """Add the commander's rewards to the save and record the game. Returns what they got."""
    now = int(now or time.time())
    rec, me = _record(state), play.player()
    single, match, crew = play.single, bool(info.get("match")), int(info.get("crew") or 1)
    counts = quests._state(state, now).setdefault("chess_counts", {"free": 0, "match": 0})
    counts["match" if match else "free"] += 1
    gain = {"score": 0, "prize": 0, "tickets": 0}
    if match:
        gain["score"] = _score_gain(int(rec["score"]), crew, me["rank"])
        rec["score"] = int(rec["score"]) + gain["score"]
        rec["max_score"] = max(int(rec["max_score"]), rec["score"])
    if not single:
        gain["prize"] = _rank_prize(crew, me["rank"])
        if gain["prize"] in quests.prizes():
            quests.grant(state, quests._reward(quests.prizes()[gain["prize"]]))
        by_time = _time_tickets(rec, int(play.game_time), now)
        rec["ticket_allowance"] -= by_time
        by_rank = 0
        if match:
            ranks = _chess_config("rank_ticket_get").split(",")
            by_rank = int(ranks[me["rank"] - 1]) if me["rank"] <= len(ranks) else 0
        row = squads._item(state, TICKET_ITEM)
        total = min(int(_chess_config("ticket_get_limit")), int(row["number"]) + by_time + by_rank)
        gain["tickets"] = max(0, total - int(row["number"]))
        row["number"] = str(max(int(row["number"]), total))
    logs = rec.setdefault("logs", [])
    next_id = 1 + max((int(x["id"]) for game in logs for x in game), default=0)
    users = ",".join(str(p["uid"]) for p in play.players)
    level = int(state["user_info"].get("lv") or 1)
    rows = []
    for i, p in enumerate(play.players):
        own = p["uid"] == play.me
        rows.append({"id": next_id + i, "user_id": p["uid"], "user_name": p["name"], "rank": p["rank"],
                     "score": gain["score"] if own else 0, "point": p["points"], "kill_num": p["kills"],
                     "achieve_num": p["achieves"], "room_mode": crew, "is_match": int(match), "camp": p["camp"] or 1,
                     "total_score": int(rec["score"]) if own else 0, "is_robot": bool(p["bot"]), "user_level": level,
                     "room_id": str(info.get("room") or next_id), "room_users": users, "user_status": 0,
                     "start_time": int(play.started), "end_time": now})
    logs.append(rows)
    del logs[:-LOG_LIMIT]
    return gain


def log_list(state, body):
    me, before = int(state["user_info"].get("user_id") or 0), int((body or {}).get("chess_log_id") or 0)
    rows = [x for game in _record(state).get("logs") or [] for x in game if x["user_id"] == me]
    return {"chess_log_with_user": [x for x in reversed(rows) if not before or x["id"] < before]}


def log_detail(state, body):
    wanted = int((body or {}).get("chess_log_id") or 0)
    game = next((g for g in _record(state).get("logs") or [] if any(x["id"] == wanted for x in g)), [])
    return {"chess_log_info": game}


# --- the lobby's prize machine and its exchange (stc chess_gasha_reward)
#   Chess/gashaDraw {"draw_param": 1 | 10} -> {"ticket_cost": tickets spent towards the guarantee,
#       "result": [reward id], "reward_index_<i>": package of a prize_id reward}
#       (FlightChessLobbyGashaController$$RequestDrawRewardHandle)
#   Chess/exchangeReward {"reward_id"} -> {"prize": package} (FlightChessLobbyGashaExchangeItem$$RequestDrawRewardHandle:
#       no "prize" key is its failure path, and it adds item and gift rewards itself from the table)
#   The tickets are item 53 (FlightChessGasha$$get_ticketCount), and the client takes them off itself.
#   chess_game_config gasha_cost_ensure "20,4500": a draw costs 20, and each 4500 spent pays the guarantee.
#   Reward type: 0 common, 3 rare, 2 guarantee, 1 exchange.
#   APPROXIMATION: the table has no weights, so a draw is RARE_CHANCE rare and otherwise common, each
#   reward of a type equally likely.
TICKET_ITEM, RARE_CHANCE = "53", 0.1


def _gasha_rules():
    row = next(r for r in stc.table("chess_game_config") if r["parameter_name"] == "gasha_cost_ensure")
    cost, floor = row["parameter_value"].split(",")
    return int(cost), int(floor)


def _gasha_pay(state, row):
    """Add the reward to the save; returns its package for a prize_id reward."""
    if int(row.get("prize_id") or 0):
        return quests.grant(state, quests._reward(quests.prizes().get(int(row["prize_id"]), {})))
    quests.grant(state, {k: row[k] for k in ("item_ids", "gift") if row.get(k)})
    return None


def gasha_draw(state, body, rng=random):
    times = int((body or {}).get("draw_param") or 0)
    if times not in (1, 10):
        return None
    cost, floor = _gasha_rules()
    if int(squads._item(state, TICKET_ITEM)["number"]) < cost * times:
        return None
    squads._spend(state, TICKET_ITEM, cost * times)
    rec, rows = _record(state), stc.table("chess_gasha_reward")
    kinds = {k: [r for r in rows if int(r["type"]) == k] for k in (0, 2, 3)}
    reply = {"result": []}
    for i in range(times):
        spent = int(rec.get("ticket_cost") or 0) + cost
        kind = 2 if spent >= floor else 3 if rng.random() < RARE_CHANCE else 0
        rec["ticket_cost"] = spent - floor if kind == 2 else spent
        row = rng.choice(kinds[kind])
        pkg = _gasha_pay(state, row)
        reply["result"].append(int(row["id"]))
        if pkg is not None:
            reply[f"reward_index_{i}"] = pkg
    reply["ticket_cost"] = int(rec["ticket_cost"])
    return reply


def gasha_exchange(state, body):
    rid = int((body or {}).get("reward_id") or 0)
    row = next((r for r in stc.table("chess_gasha_reward") if int(r["id"]) == rid and int(r["type"]) == 1), None)
    rec = _record(state)
    if row is None or rid in rec.setdefault("acquired", []):
        return None
    need = int(row.get("tickets_num") or 0)
    if int(squads._item(state, TICKET_ITEM)["number"]) < need:
        return None
    squads._spend(state, TICKET_ITEM, need)
    rec["acquired"].append(rid)
    return {"prize": _gasha_pay(state, row) or {}}
