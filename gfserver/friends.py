"""Friends (Friend/*), from the account file's friend_with_user_info.

The client ignores that block at login and shows only what Friend/list sends, so the rows are the list.
They hold a friend's card summary and nothing else: no dorm, echelons or medals, unless tools/live_archive.py saved that
friend's replies (archived.py), which are then served as they were. No one is really there, so praise and messages get no
answer. Reply formats (from the client's handlers):
  Friend/list {} -> {"list": [row]} (RequestFriendList, Friend$$.ctor; is_return_user is read unguarded and
      the recorded rows lack it); Friend/blackList and Friend/randomList the same
  Friend/usercard {"f_userid"} -> a card, every key guarded (UserCard$$.ctor)
  Friend/visit {"f_userid"} -> {"info": {...}, "notice", "dorm_type", "adjutant_list", "sangvis_with_user_list",
      "gun_with_user_list", "furniture_list", "commander_info"} (RequestVisitOtherDorm)
  Friend/praise {"f_userid"} -> {"today_praise_num"}, "package" optional (RequestNiceDorm)
  Friend/teamAndPraisePrize {} -> {"praise_num", "team_prize_num", "vehicle_maintain_num"}
  Friend/messageadd {"f_userid", "message"} -> {"message"}, "list" optional (RequestSendMessage): the client
      keeps conversations itself (FriendMessageUtility), so messagelist and messageget stay empty
  Friend/add {"f_userid", "type": FriendType} "1"; Friend/delete, Friend/apply {"f_userid"} "1"
  Vehicle/visit {"to_user_id"} -> a friend's garage (RequestVisitOtherVehicleRoom), archived replies only
  Friend/teamGuns {} -> {"borrow_team_today", "gun_with_friend": {"guns_with_friend_available": [gun row],
      "sangvis_with_friend_available": [...], "friend_team_effect_arr": {"<uid>": "..."}},
      "fairy_with_friend_info": {"<uid>": [fairy row]}} (RequestFriendTeams reads the first two unguarded):
      the archived reply, cut to the friends still on the list (support_teams)
An application is accepted at once. Removed friends are the random list, which is how to get one back.
APPROXIMATION: without an archived reply, a visit shows the player's own first room. Praise pays
nothing because the reward isn't in the client. Friend/usercard is also what the search box sends, but it
reads a list where the card is an object, so searching by id finds nobody.
"""
import random
import time
from functools import lru_cache

from . import account, archived, quests, stc

FRIENDS, BLOCKED, REMOVED = "friend_with_user_info", "_friend_black", "_friend_removed"
TYPE_BLOCKED = 2
DAY_OFFSET = 8 * 3600     # the server day turns over at 00:00 UTC-8 (handlers.SERVER_DAY_TZ)
INT_FIELDS = ("f_userid", "lv", "headpic_id", "frame_id", "homepage_time", "max_dorm", "dorm_id", "give_team_today", "end_time")


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _wire(row):
    return dict(row, **{k: _int(row.get(k)) for k in INT_FIELDS}, is_return_user=bool(_int(row.get("is_return_user"))),
                is_vehicle_visit=bool(_int(row.get("is_vehicle_visit"))))


def _me(state):
    return (state.get("user_info") or {}).get("user_id", "")


def _rows(state, key):
    return state.setdefault(key, [])


def _find(state, fid):
    for key in (FRIENDS, BLOCKED, REMOVED):
        for row in _rows(state, key):
            if str(row.get("f_userid")) == str(fid):
                return key, row
    return None, None


def _move(state, fid, dest):
    key, row = _find(state, fid)
    if row is None:
        return False
    if key != dest:
        _rows(state, key).remove(row)
        _rows(state, dest).append(row)
    return True


def _list(key):
    return lambda state, body: {"list": [_wire(r) for r in _rows(state, key)]}


friend_list, black_list, random_list = _list(FRIENDS), _list(BLOCKED), _list(REMOVED)


def add(state, body):
    body = body or {}
    dest = BLOCKED if _int(body.get("type")) == TYPE_BLOCKED else FRIENDS
    return "1" if _move(state, body.get("f_userid"), dest) else None


def apply(state, body):
    _move(state, (body or {}).get("f_userid"), FRIENDS)
    return "1"


def delete(state, body):
    _move(state, (body or {}).get("f_userid"), REMOVED)
    return "1"


def card(state, body):
    fid = (body or {}).get("f_userid")
    _, row = _find(state, fid)
    if row is None:
        return account.user_card(state, body)
    saved = archived.read(_me(state), "Friend/usercard", fid)
    if saved is not None:
        return saved
    return {**_wire(row), "card_id": 0, "homebg_id": 0, "intro": "", "medal": [], "medal_with_user": [],
            "medal_is_visible": 0, "team_info": [], "sangvis_info": [], "fairy_info": []}


def _today(state, key, now=None):
    """Friend ids done today under state[key] (praised, batteries taken)."""
    day = (int(now or time.time()) - DAY_OFFSET) // 86400
    record = state.setdefault(key, {"day": day, "ids": []})
    if record["day"] != day:
        record.update(day=day, ids=[])
    return record["ids"]


def _praised(state, now=None):
    return _today(state, "_friend_praise", now)


# Batteries from a friend's dorm: once a day per friend, one per dorm they have (friend row max_dorm), from
# at most game_config friends_coefficients' first number (10) of friends a day (Data$$GetDailyVegetealMaxCount).
# Friend/visit's build_coin_flag says how many are there (DormConfigData.buildCoinCanGet; the client
# only asks when it is above 0); Dorm/get_build_coin with their v_user_id takes them. Index/index's
# dorm_rest_friend_build_coin_count is what is left today (UserInfo.remainVegetealCount; the client counts it
# down itself and shows the limit text at 0).
def battery_limit():
    first = str(_config("friends_coefficients", "10")).split(",")[0].strip()
    return int(first) if first.isdigit() else 10


def batteries_left(state, now=None):
    return max(0, battery_limit() - len(_today(state, "_friend_battery", now)))


def battery_flag(state, fid, now=None):
    _, row = _find(state, fid)
    if row is None or str(fid) in _today(state, "_friend_battery", now) or not batteries_left(state, now):
        return 0
    return max(1, _int(row.get("max_dorm")))


def collect_battery(state, fid, now=None):
    amount = battery_flag(state, fid, now)
    if amount:
        _today(state, "_friend_battery", now).append(str(fid))
    return amount


def visit(state, body):
    fid = (body or {}).get("f_userid")
    _, row = _find(state, fid)
    if row is None:
        return None
    saved = archived.read(_me(state), "Friend/visit", fid)
    if saved is not None:
        return dict(saved, info=dict(saved.get("info") or {}, is_praise=str(fid) not in _praised(state)),
                    build_coin_flag=battery_flag(state, fid))
    # dorm 0 is the furniture in storage, and DormController$$LoadDorm(0) builds every row it is sent
    rooms = [r for r in account.furniture(state) if _int(r.get("dorm")) > 0]
    room = min((_int(r["dorm"]) for r in rooms), default=1)
    wired = _wire(row)
    info = {k: wired[k] for k in ("f_userid", "name", "lv", "headpic_id", "homepage_time", "is_vehicle_visit")}
    return {"info": {**info, "praise_num": 0, "is_praise": str(fid) not in _praised(state), "furniture_collect": 0, "gun_collect": 0},
            "notice": {"notice": "", "is_view_notice": False}, "dorm_type": room, "adjutant_list": [],
            "build_coin_flag": battery_flag(state, fid),
            "sangvis_with_user_list": [], "gun_with_user_list": [],
            "furniture_list": [r for r in rooms if _int(r.get("dorm")) == room]}


def visit_random(state, body):
    """Friend/visitRandom, which no client code sends: Friend/visit of the first friend."""
    rows = _rows(state, FRIENDS)
    return visit(state, {"f_userid": rows[0]["f_userid"]}) if rows else None


# The archived reply carries the day it was recorded; the interaction count and whether this friend can still
# be interacted with today are the save's.
def vehicle_visit(state, body):
    fid = str((body or {}).get("to_user_id") or "")
    saved = archived.read(_me(state), "Vehicle/visit", fid)
    if not isinstance(saved, dict):
        return saved
    limit = int(str(_config("vehicle_maintainance", "10:508-10")).partition(":")[0] or 10)
    done = _today(state, "_vehicle_maintain")
    day = (int(time.time()) - DAY_OFFSET) // 86400
    return dict(saved, vehicle_maintain_num=len(done), can_maintain=fid not in done and len(done) < limit,
                vehicle_maintain_refresh_time=(day + 1) * 86400 + DAY_OFFSET)


# A praise (like) pays game_config dorm_visit_prize (prize 71: 10 friendship points) for the first
# dorm_visit_prize_limit of the day; RequestNiceDorm finds the prize by package.id and adds it itself.
def _config(name, default):
    return next((r["parameter_value"] for r in stc.catch("game_config_info") if r["parameter_name"] == name), default)


def praise(state, body):
    fid = str((body or {}).get("f_userid"))
    if _find(state, fid)[1] is None:
        return None
    ids = _praised(state)
    if fid in ids:
        return {"today_praise_num": len(ids)}
    ids.append(fid)
    reply = {"today_praise_num": len(ids)}
    if len(ids) <= int(_config("dorm_visit_prize_limit", 10)):
        prize = int(_config("dorm_visit_prize", 71))
        quests.grant(state, quests._reward(quests.prizes().get(prize, {})))
        reply["package"] = {"id": prize}
    return reply


def progress(state, body):
    return {"praise_num": len(_praised(state)), "team_prize_num": 0, "vehicle_maintain_num": len(_today(state, "_vehicle_maintain"))}


# Interact in a friend's armor room: Vehicle/maintain {"to_user_id"} -> {"visit_message": a line id of
# game_config vehicle_visitmessage}. RequestVehicleMaintain adds game_config vehicle_maintainance's item
# ("10:508-10": 10 friendship points, the first 10 a day) itself; the save gets it too, once per friend a day.
def vehicle_maintain(state, body, rng=random):
    fid = str((body or {}).get("to_user_id") or "")
    if _find(state, fid)[1] is None:
        return None
    limit, _, item = str(_config("vehicle_maintainance", "10:508-10")).partition(":")
    done = _today(state, "_vehicle_maintain")
    if fid not in done and len(done) < int(limit or 10):
        done.append(fid)
        quests.grant(state, {"item_ids": item})
    lines = [p.partition(":")[0] for p in str(_config("vehicle_visitmessage", "19:0")).split(";") if p.strip()]
    return {"visit_message": int(rng.choice(lines))}


def message_add(state, body):
    body = body or {}
    if _find(state, body.get("f_userid"))[1] is None:
        return None
    return {"message": str(body.get("message") or "")}


# --- friends' support echelons -----------------------------------------------------------
#
# The echelons come from the archived Friend/teamGuns (tools/live_archive.py). That reply has the dolls and
# fairies but only the instance ids of their equipment: the live server sent the equipment's stats only
# when the echelon was deployed (Mission/reinforceFriendTeam "equips": {"<id>": {id, user_id, group_id,
# gun_with_friend_id, equip_id, equip_exp, equip_level, <stat calibrations per 10000>, equip_with_user_id}}).
# Those replies, when a packet log recorded one, are archived per friend (Mission/reinforceFriendTeam/<uid>,
# live_archive.py --from-log) and used as they are.
# APPROXIMATION: equipment that was never recorded is the best-rarity equip of the first type each slot
# takes (gun.type_equipN "slot;type,..."), at its max level and full calibration.
# Coalition support echelons: the deploy reply's parts are as the client reads them
# (DeploymentTeamInfoController$$RequestReinforceHandle), never recorded: "sangvisteam" {"sangvis":
# {"<n>": {sangvis_with_user_id, position}}}, "sangvis_chips" [{chip_id, sangvis_with_friend_id,
# chip_slot}] and "sangvises" {"<id>": the archived unit row}.
# Using a friend's echelon puts it on cooldown for use_friend_team_cd seconds (7200; the friend row's
# end_time, and the reply's friend_team_end_time as recorded) and counts towards support_daily_limit (20).

BORROW = "_friend_borrow"


def _borrowed_today(state, now=None):
    day = (int(now or time.time()) - DAY_OFFSET) // 86400
    record = state.setdefault(BORROW, {"day": day, "count": 0})
    if record["day"] != day:
        record.update(day=day, count=0)
    return record


def _team_archive(state):
    saved = archived.read(_me(state), "Friend/teamGuns")
    return saved if isinstance(saved, dict) else None


def support_teams(state, body=None, now=None):
    """Friend/teamGuns: the archived echelons of friends still on the list and off cooldown."""
    saved = _team_archive(state)
    count = _borrowed_today(state, now)["count"]
    if saved is None:
        return {"borrow_team_today": count, "gun_with_friend": [], "guns_with_friend_available": [],
                "sangvis_with_friend_available": [], "fairy_with_friend_info": []}
    now = int(now or time.time())
    ready = {str(r.get("f_userid")) for r in _rows(state, FRIENDS) if _int(r.get("end_time")) <= now}
    team = saved.get("gun_with_friend") or {}
    guns = [g for g in team.get("guns_with_friend_available") or [] if str(g.get("user_id")) in ready]
    units = [u for u in team.get("sangvis_with_friend_available") or [] if str(u.get("user_id")) in ready]
    effect = {k: v for k, v in (team.get("friend_team_effect_arr") or {}).items() if k in ready}
    fairies = {k: v for k, v in (saved.get("fairy_with_friend_info") or {}).items() if k in ready}
    return {"borrow_team_today": count,
            "gun_with_friend": {"guns_with_friend_available": guns, "sangvis_with_friend_available": units,
                                "friend_team_effect_arr": effect},
            "fairy_with_friend_info": fairies}


@lru_cache(maxsize=1)
def _equip_rows():
    return {int(r["id"]): r for r in stc.table("equip")}


@lru_cache(maxsize=1)
def _gun_rows():
    return {int(r["id"]): r for r in stc.table("gun")}


@lru_cache(maxsize=None)
def _best_equip(equip_type):
    """The rarest shown equip of a type that isn't one doll's own, lowest id first."""
    fits = [r for r in _equip_rows().values() if _int(r.get("type")) == equip_type and _int(r.get("is_show"))
            and not str(r.get("fit_guns") or "").strip()]
    return min(fits, key=lambda r: (-_int(r.get("rank")), _int(r["id"])), default=None)


def _slot_types(gun_id, slot):
    row = _gun_rows().get(_int(gun_id)) or _gun_rows().get(_int(gun_id) % 20000) or {}
    _, _, types = str(row.get(f"type_equip{slot}") or "").partition(";")
    return [_int(t) for t in types.split(",") if t.strip()]


def _made_equip(gun, slot, uid):
    for kind in _slot_types(gun["gun_id"], slot):
        row = _best_equip(kind)
        if row is not None:
            stats = {k: ("10000" if str(row.get(k) or "").strip() else "0") for k in STAT_KEYS}
            return {"id": str(gun[f"equip{slot}"]), "user_id": str(uid), "group_id": str(gun.get("group_id") or ""),
                    "gun_with_friend_id": str(gun["id"]), "equip_id": str(row["id"]), "equip_exp": "0",
                    "equip_level": str(_int(row.get("max_level"))), **stats, "equip_with_user_id": str(gun[f"equip{slot}"])}
    return None


STAT_KEYS = ("pow", "hit", "dodge", "speed", "rate", "critical_harm_rate", "critical_percent", "armor_piercing",
             "armor", "shield", "damage_amplify", "damage_reduction", "night_view_percent", "bullet_number_up")


def _chips(row):
    """A Coalition unit's chips as the deploy reply lists them (SangvisChipData$$.ctor: chip_id,
    sangvis_with_friend_id, chip_slot); the archived row has {chip_slot, chip_id} each."""
    # recorded (2026-11-07, No More Omens): each with the friend's user_id and group_id too
    return [{"user_id": str(row.get("user_id") or ""), "chip_id": str(c.get("chip_id")), "group_id": str(row.get("group_id") or ""),
             "sangvis_with_friend_id": str(row["id"]), "chip_slot": str(c.get("chip_slot"))}
            for c in row.get("sangvis_chips") or [] if isinstance(c, dict) and _int(c.get("chip_id"))]


def borrow(state, uid, group, gun_ids, sangvis_ids=None, now=None):
    """A friend's echelon for Mission/reinforceFriendTeam, or None if it isn't archived, the friend is
    gone or on cooldown, or today's limit is used up. Dolls: {"guns", "equips", "fairy"}; Coalition:
    {"sangvises", "chips", "team"}; both with "end_time"."""
    now = int(now or time.time())
    key, row = _find(state, uid)
    saved = _team_archive(state)
    record = _borrowed_today(state, now)
    limit = _int(quests._config().get("support_daily_limit") or 20)
    if row is None or key != FRIENDS or saved is None or _int(row.get("end_time")) > now or record["count"] >= limit:
        return None
    team = saved.get("gun_with_friend") or {}

    def pick(pool, ids):
        wanted = {str(i) for i in ids or []}
        rows = [r for r in pool or [] if str(r.get("user_id")) == str(uid) and str(r.get("id")) in wanted
                and (group is None or str(r.get("group_id")) == str(group))]
        return rows if rows and len(rows) == len(wanted) else None
    cd = _int(quests._config().get("use_friend_team_cd") or 7200)
    if sangvis_ids:
        units = pick(team.get("sangvis_with_friend_available"), sangvis_ids)
        if units is None:
            return None
        out = {"sangvises": {str(u["id"]): u for u in units}, "chips": [c for u in units for c in _chips(u)],
               # recorded: {"user_id", "group_id", "sangvis": {"<n>": {sangvis_with_user_id, position}}}, numbers
               "team": {"user_id": str(uid), "group_id": str(group if group is not None else units[0].get("group_id") or ""),
                        "sangvis": {str(n): {"sangvis_with_user_id": _int(u["id"]), "position": _int(u.get("position"))}
                                    for n, u in enumerate(units, 1)}}}
    else:
        guns = pick(team.get("guns_with_friend_available"), gun_ids)
        if guns is None:
            return None
        recorded = (archived.read(_me(state), "Mission/reinforceFriendTeam", uid) or {}).get("equips") or {}
        equips = {}
        for g in guns:
            for slot in (1, 2, 3):
                eid = str(g.get(f"equip{slot}") or "0")
                if eid == "0":
                    continue
                e = recorded.get(eid) or _made_equip(g, slot, uid)
                if e is not None:
                    equips[eid] = e
        fairy = next((f for f in (saved.get("fairy_with_friend_info") or {}).get(str(uid)) or []
                      if str(f.get("group_id")) == str(group)), None)
        out = {"guns": {str(g["id"]): g for g in guns}, "equips": equips, "fairy": fairy}
    row["end_time"] = now + cd
    record["count"] += 1
    return dict(out, end_time=now + cd)
