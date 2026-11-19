"""Daily, weekly and career quests, achievements, and the mail that carries their rewards.

Progress is counted server-side in the save's "_quest" (stripped from Index/index):
  counters  lifetime counts per event type (career quests, achievements)
  daily     {"day", "list", "refresh", "progress", "done"}   reset at local midnight
  weekly    {"week", "list", "refresh", "progress", "done", "accumulation", "paid"}  reset Mondays
  career_done / achievement_done  ids already rewarded
Events come from on_call (a hook after every saving handler, keyed by function name) and
from missions.py (battle wins, S ranks, bosses, captures, mission clears) through record().
Types the server cannot observe (exploration, coin missions, friends, dorm, ...) never progress,
so the daily list only offers quests it can track, one per daily group (stc daily.mission_type).
On first use, every career quest and achievement the save already meets is marked done without
mail, so an existing account is not flooded.
The live server's lifetime metrics are not in the player file. A saved Index/achievement reply in
player/achievements/<uid>.json (bare, or a packet log entry with "Response") is imported once into counters,
achievement_cond and achievement_done, again without mail. Metrics this server does not observe stay at the imported value.
An archived Index/Quest reply (archived.py) also fills career progress, once per save: career_base holds each lifetime figure
and what counters read when it was imported, career_cond the per-quest figures, and career and achievement figures stay apart
because the live server kept them apart (its career "upgrade" is not its achievement "upgrade").

Reply formats (from the client's handlers):
  Index/Quest   {"daily": {daily_quest_pool, refresh_count, daily_quest_list, accomplish_quest_list
                (comma strings), end_time, progress: {"<type>": n}}, "weekly": {weekly_quest_pool,
                refresh_count, weekly_quest_list, accomplish_quest_list, locked_quest_list, end_time,
                weekly_accumulation, progress}, "career": {"<type>": n | "<career_quest id>-n,..."} (read
                unguarded; rows with a condition are keyed by quest, as the live reply does),
                "career_quest_grade": [{"grade_id", "accomplish_quest_ids"}],
                "chess_game_counts": {"free", "match"}, "cheers_counts" (both guarded),
                "achievement": {"id", "user_id", "accomplish_achievement_ids", "<type>": n}}
                                                    RequestGetQuests, DailyQuestOverallInfo$$Update
  Index/accomplishDailyQuest {daily_quest_id} / accomplishWeeklyQuest {weekly_quest_id}
                -> {"weekly_accumulation", "mail_list": [mail]}   RequestCompleteDailyQuests
  Index/accomplishAllQuests -> {"daily": {"accomplish_quest_list": [ids]}, "weekly": {...},
                "weekly_accumulation", "mail_list"}
  Index/refreshDailyQuest {daily_quest_id} -> {"refresh_error", "refresh_count", "daily_quest_list"}
  Index/refreshWeeklyQuest {weekly_quest_id} -> {"refresh_error", "refresh_count",
                "weekly_quest_list", "locked_quest_list"}
  Index/achievement {uid} -> {"id", "user_id", "accomplish_achievement_ids", "<metric>": "n"} (RequestUpdateAchievement
                reads every other key as a metric); metrics of rows with a condition are "<achievement id>-n,..."
  Index/getMailList {start_id, ignore_time} -> [mail]   Index/ifNewMail -> {"kick", "if_new_mail"}
  Index/getResourceInMail {mail_with_user_id} -> {"mail": package}   Mail$$RequestMailResourceHandle
  Index/QuickGetQuestsResourceInMails {type, param} -> package + "career_mail_ids" (unguarded)
  mail: {"id", "sub_id", "title" (strings), "content", "type" (MailType: 2 achievement,
        7 daily, 8 weekly, 21 career), "start_time", "end_time", "if_read", "if_received"} plus
        the reward in prize-table form (user_exp, mp, ammo, mre, part, core, gem, item_ids
        "id-n,...", gun_id, equip_ids, fairy_ids, gift, ...)  (Mail$$.ctor reads it as a Package)
The daily chest and weekly point boxes (game_config daily_progress / weekly_progress "need:prize;...") go by mail
with sub_id = their need: the client finds a box's mail by type 7 / 8 and that sub_id (DWRewardItemCtrl
<CheckWeeklyRewardState>b__21_0, DailyWeekQuestCtrl <CheckDailyRewardState>b__111_0), and shows a reached box
with no such mail as already claimed.
The live account's day and week are taken from its archived Index/Quest while they last (_import_period): the
quest list, refreshes, progress, the quests claimed there, and the weekly points, whose boxes count as paid.
APPROXIMATION: the daily pick, the weekly-point values (WEEKLY_POINTS) and the reset times are
server rules not in the client. Rewarded dolls/equipment/fairies are added to the save; the
client may only show the equipment and fairies after a relogin.
"""
import datetime
import json
import random
import time
from functools import lru_cache

from . import archived, config, stc
from .factory import _add

MAIL_ACHIEVEMENT, MAIL_DAILY, MAIL_WEEKLY, MAIL_CAREER = 2, 7, 8, 21
QUEST_MAILS = (MAIL_ACHIEVEMENT, MAIL_DAILY, MAIL_WEEKLY, MAIL_CAREER)
WEEKLY_POINTS = {"daily": 10, "weekly": 40}
MAIL_DAYS = 30
RES = ("user_exp", "mp", "ammo", "mre", "part", "core", "gem")
WEAR = ("skin", "commander_uniform")     # doll skins and commander outfits: comma lists of ids
LISTS = ("item_ids", "equip_ids", "fairy_ids", "gift", "furniture", "coins", "vehicle_component", "sangvis", "chip")

# Event types this server records (on_call and missions.record calls).
TRACKED = {"win_normal", "s_win", "win_boss", "mission", "map_capture", "develop_gun", "develop_equip",
           "develop_all", "special_develop_gun", "special_develop_equip", "special_develop_fairy",
           "recycle", "retire_gun", "retire_equip", "upgrade_value", "eat_gun", "adjust_equip",
           "upgrade_equip", "operation", "auto_battle", "auto_mission", "combat_simulation", "gift",
           "like", "combine_gun", "eat_fairy", "adjust_fairy", "sangvis_resolution", "fix_gun", "upgrade",
           "mind_update", "enemy_die", "mission_win", "mission_lose", "team_die", "weekly_complete",
           "heart_collect", "explore", "consume_iop_contract", "develop_gun_rank4", "develop_gun_rank5",
           "open_gift", "get_build_coin", "upvote", "consume_furniture_coin"}


# --- static data ------------------------------------------------------------------------

@lru_cache(maxsize=1)
def daily_rows():
    return {int(r["identity"]): r for r in stc.table("daily")}


@lru_cache(maxsize=1)
def weekly_rows():
    return {int(r["identity"]): r for r in stc.table("weekly")}


@lru_cache(maxsize=1)
def career_rows():
    return {int(r["id"]): r for r in stc.table("career_quest")}


@lru_cache(maxsize=1)
def achievement_rows():
    return {int(r["identity"]): r for r in stc.table("achievement")}


@lru_cache(maxsize=1)
def prizes():
    return {int(r["id"]): r for r in stc.table("prize")}


@lru_cache(maxsize=1)
def _config():
    return {r["parameter_name"]: str(r["parameter_value"]) for r in stc.catch("game_config_info")}


def _pairs(text):
    return [tuple(int(x) for x in p.split(":")) for p in str(text or "").split(";") if ":" in p]


# --- periods ----------------------------------------------------------------------------

def _midnight(now):
    d = datetime.datetime.fromtimestamp(now).date()
    return d, int(time.mktime((d + datetime.timedelta(days=1)).timetuple()))


def _state(state, now=None):
    now = int(now or time.time())
    q = state.setdefault("_quest", {})
    q.setdefault("counters", {})
    day, day_end = _midnight(now)
    monday = day - datetime.timedelta(days=day.weekday())
    week_end = int(time.mktime((monday + datetime.timedelta(days=7)).timetuple()))
    d = q.get("daily") or {}
    if d.get("day") != day.isoformat():
        lst = _pick_daily(day)
        q["daily"] = {"day": day.isoformat(), "end": day_end, "list": lst, "refresh": [0] * len(lst),
                      "progress": {}, "done": [], "chest": False}
    w = q.get("weekly") or {}
    if w.get("week") != monday.isoformat():
        lst = [i for i, r in sorted(weekly_rows().items()) if r["type"] in TRACKED]
        q["weekly"] = {"week": monday.isoformat(), "end": week_end, "list": lst, "refresh": [0] * len(lst),
                       "progress": {}, "done": [], "accumulation": 0, "paid": []}
    for period in ("daily", "weekly"):
        if not q[period].get("live_checked"):
            q[period]["live_checked"] = True
            _import_period(state, q, period, now)
    _box_ids(state, q)
    _settle_old(state, MAIL_DAILY, int(time.mktime(day.timetuple())))
    _settle_old(state, MAIL_WEEKLY, int(time.mktime(monday.timetuple())))
    if "baseline" not in q:
        # an existing account: what it already meets is treated as rewarded long ago
        q["baseline"] = True
        ctx = _Ctx(state, q)
        q["career_done"] = [i for i, r in career_rows().items() if _met(ctx, r)]
        q["achievement_done"] = [i for i, r in achievement_rows().items() if _met(ctx, r)]
    if "metrics_imported" not in q:
        _import_metrics(state, q)
    if "career_imported" not in q:
        _import_career(state, q)
    return q


def _ids_in(text):
    return [int(x) for x in str(text or "").split(",") if x.strip().isdigit()]


def _import_period(state, q, period, now):
    """This day's / week's quests from the archived live Index/Quest, if it is still the period it was recorded in."""
    saved = archived.read(str((state.get("user_info") or {}).get("user_id", "")), "Index/Quest")
    block = saved.get(period) if isinstance(saved, dict) else None
    if not isinstance(block, dict) or not int(block.get("end_time") or 0) > now:
        return
    p = q[period]
    rows = daily_rows() if period == "daily" else weekly_rows()
    listed = [i for i in _ids_in(block.get(f"{period}_quest_list")) if i in rows]
    if listed:
        p["list"] = listed
        refresh = _ids_in(block.get("refresh_count"))
        p["refresh"] = (refresh + [0] * len(listed))[:len(listed)]
    live_done = [i for i in _ids_in(block.get("accomplish_quest_list")) if i in rows]
    both = len(set(live_done) & set(p["done"]))
    p["done"] = list(dict.fromkeys(p["done"] + live_done))
    for kind, n in (block.get("progress") or {}).items():
        if str(n).isdigit():
            p["progress"][kind] = max(p["progress"].get(kind, 0), int(n))
    if period == "weekly":
        p["locked"] = _ids_in(block.get("locked_quest_list"))
        live_points = int(block.get("weekly_accumulation") or 0)
        # points earned here this week add to live's, less any quest claimed in both places
        p["accumulation"] = live_points + max(0, p["accumulation"] - WEEKLY_POINTS["weekly"] * both)
        p["paid"] = sorted(set(p["paid"]) | {need for need, _ in _pairs(_config().get("weekly_progress")) if need <= live_points})
        _pay_boxes(state, q)
    else:
        p["chest"] = p.get("chest") or any(len(live_done) >= need for need, _ in _pairs(_config().get("daily_progress")))


def _box_ids(state, q):
    """Unclaimed box mails sent with sub_id 0, before boxes were matched by their need: each takes a need reached this
    period that has no mail yet, or is dropped when every one has (the live mailbox already holds that box)."""
    for kind, period, key in ((MAIL_DAILY, "daily", "daily_progress"), (MAIL_WEEKLY, "weekly", "weekly_progress")):
        stray = [m for m in _mails(state) if m["type"] == kind and str(m.get("sub_id")) == "0" and m["title"] == key
                 and not m["if_received"]]
        if not stray:
            continue
        p = q[period]
        reached = sorted(p["paid"]) if period == "weekly" else             [need for need, _ in _pairs(_config().get(key)) if p.get("chest")]
        start = int(p["end"]) - (7 if period == "weekly" else 1) * 86400
        taken = {str(m.get("sub_id")) for m in _mails(state) if m["type"] == kind and int(m["start_time"]) >= start - 86400}
        free = [n for n in reached if str(n) not in taken]
        for i, m in enumerate(sorted(stray, key=lambda m: int(m["id"]))):
            if i < len(free):
                m["sub_id"] = str(free[i])
            else:
                state["_mail"].remove(m)


def _settle_old(state, kind, period_start):
    """Pay out daily / weekly reward mails from before this period that are still waiting: an unclaimed one
    keeps the quest screen's (!) lit (the game's questscontroller patch checks for any such mail) and can show
    the new period's quest of the same id as already claimed."""
    for m in _mails(state):
        if m["type"] == kind and not m["if_received"] and int(m["start_time"]) < period_start:
            grant(state, m)


def _saved_achievements(uid):
    """The newest way of having them first: an archived reply, the block inside an archived Index/Quest, a dropped-in file."""
    saved = archived.read(uid, "Index/achievement") or (archived.read(uid, "Index/Quest") or {}).get("achievement")
    if saved:
        return saved
    try:
        saved = json.loads((config.PLAYER_DIR / "achievements" / f"{uid}.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return saved.get("Response", saved)


def _import_metrics(state, q):
    saved = _saved_achievements(state.get("user_info", {}).get("user_id", ""))
    if not saved:
        return
    q["metrics_imported"] = True
    conds = q.setdefault("achievement_cond", {})
    for key, value in saved.items():
        text = str(value)
        if key == "accomplish_achievement_ids":
            done = [int(x) for x in text.split(",") if x.isdigit()]
            q["achievement_done"] = list(dict.fromkeys(done + q.get("achievement_done", [])))
        elif key.startswith("c_"):
            for part in filter(None, text.split(",")):
                aid, _, n = part.partition("-")
                conds[aid] = int(n)
        elif key not in ("id", "user_id") and text.isdigit():
            q["counters"][key] = q["counters"].get(key, 0) + int(text)
    # what the imported numbers now meet was rewarded long ago
    ctx = _Ctx(state, q)
    q["career_done"] = list(dict.fromkeys(q.get("career_done", []) + [i for i, r in career_rows().items() if _met(ctx, r)]))
    q["achievement_done"] = list(dict.fromkeys(q["achievement_done"] + [i for i, r in achievement_rows().items() if _met(ctx, r)]))


def _import_career(state, q):
    saved = archived.read(state.get("user_info", {}).get("user_id", ""), "Index/Quest")
    if not saved or not isinstance(saved.get("career"), dict):
        return
    q["career_imported"] = True
    base, conds = q.setdefault("career_base", {}), q.setdefault("career_cond", {})
    for key, value in saved["career"].items():
        text = str(value)
        if key in ("id", "user_id"):
            continue
        if "-" in text:
            for part in text.split(","):
                qid, _, n = part.partition("-")
                if qid.isdigit() and n.isdigit():
                    conds[qid] = int(n)
        elif text.isdigit():
            base[key] = {"value": int(text), "at": q["counters"].get(key, 0)}
    done = [int(x) for g in saved.get("career_quest_grade") or [] for x in str(g.get("accomplish_quest_ids") or "").split(",") if x.isdigit()]
    ctx = _Ctx(state, q)
    met = [i for i, r in career_rows().items() if _career_met(ctx, r)]
    q["career_done"] = list(dict.fromkeys([i for i in done if i in career_rows()] + q.get("career_done", []) + met))
    counts = saved.get("chess_game_counts") or {}
    q["chess_counts"] = {k: int(counts.get(k) or 0) for k in ("free", "match")}
    q["cheers"] = int(saved.get("cheers_counts") or 0)


def _pick_daily(day):
    """One trackable quest per daily group, the same all day."""
    rng = random.Random(day.toordinal())
    groups = {}
    for i, r in sorted(daily_rows().items()):
        if r["type"] in TRACKED:
            groups.setdefault(int(r["mission_type"]), []).append(i)
    return [rng.choice(ids) for _, ids in sorted(groups.items())]


# --- recording --------------------------------------------------------------------------

def record(state, kind, n=1):
    """Count an event for today's and this week's quests and for the lifetime counters."""
    if n <= 0:
        return
    q = _state(state)
    q["counters"][kind] = q["counters"].get(kind, 0) + n
    for period in ("daily", "weekly"):
        prog = q[period]["progress"]
        prog[kind] = prog.get(kind, 0) + n


def _n(body, key, default=1):
    try:
        return int((body or {}).get(key) or default)
    except (TypeError, ValueError, AttributeError):
        return default


def on_call(state, function, body, reply):
    """Events implied by a handled call that succeeded."""
    if reply is None:
        return
    b = body if isinstance(body, dict) else {}
    heavy = _n(b, "input_level", 0) > 0 or _n(b, "build_heavy", 0) > 0
    if function in ("Gun/developGun", "Gun/developMultiGun", "Gun/wishGunDevelop"):
        n = {"Gun/developMultiGun": _n(b, "build_multi"), "Gun/wishGunDevelop": len(b.get("build_slots") or [])}.get(function, 1)
        heavy = heavy or function == "Gun/wishGunDevelop"
        record(state, "develop_gun", n)
        record(state, "develop_all", n)
        record(state, "consume_iop_contract", n)        # APPROXIMATION: one contract a build
        if heavy:
            record(state, "special_develop_gun", n)
        for gid in _developed(reply):
            rank = int(factory_guns().get(gid, {}).get("rank") or 0)
            if rank in (4, 5):
                record(state, f"develop_gun_rank{rank}")
    elif function in ("Equip/produceDevelop", "Equip/spProduceDevelop"):
        record(state, "develop_equip", len(b.get("build_slots") or []))
        record(state, "develop_all", len(b.get("build_slots") or []))
    elif function == "Equip/developMulti":
        record(state, "develop_equip", _n(b, "build_multi"))
        record(state, "develop_all", _n(b, "build_multi"))
        if heavy:
            record(state, "special_develop_equip", _n(b, "build_multi"))
    elif function == "Equip/develop":
        record(state, "develop_equip")
        record(state, "develop_all")
        if heavy:
            record(state, "special_develop_equip")
    elif function == "Fairy/develop":
        record(state, "develop_all", _n(b, "build_multi"))
        if heavy:
            record(state, "special_develop_fairy", _n(b, "build_multi"))
    elif function == "Gun/retireGun":
        n = len(body) if isinstance(body, list) else 0
        record(state, "recycle", n)
        record(state, "retire_gun", n)
    elif function == "Equip/retire":
        record(state, "recycle", len(b.get("equips") or []))
        record(state, "retire_equip", len(b.get("equips") or []))
    elif function == "Gun/eatGun":
        record(state, "upgrade_value")
        record(state, "eat_gun")
    elif function == "Gun/fixGuns":
        fix = b.get("fix_guns")
        record(state, "fix_gun", len(fix) if isinstance(fix, (list, dict)) else 1)
    elif function == "Dorm/giftToGun":
        record(state, "gift", _n(b, "num"))
        record(state, "open_gift", _n(b, "num"))
    elif function == "Mission/simulation":
        # a sweep of n runs counts as n simulations
        record(state, "combat_simulation", max(1, _n(b, "count")))
    elif function == "Dorm/get_build_coin" and isinstance(reply, dict):
        record(state, "get_build_coin", int(reply.get("build_coin") or 0))
    else:
        for kind in _SIMPLE.get(function, ()):
            record(state, kind)


def factory_guns():
    from . import factory
    return factory.guns()


def _developed(reply):
    """Doll ids a production reply hands out (developGun, developMultiGun, wishGunDevelop)."""
    ids = []
    if isinstance(reply, dict):
        if "gun_id" in reply:
            ids.append(reply["gun_id"])
        ids += [g.get("id") for g in reply.get("gun_ids") or []]
        ids += [g.get("gun_id") for g in reply.get("develop_result") or []]
    elif isinstance(reply, list):
        ids += [(g.get("gun_with_user_add") or {}).get("gun_id") for g in reply if isinstance(g, dict)]
    return [int(i) for i in ids if str(i or "").isdigit()]


_SIMPLE = {
    "Equip/eatEquip": ("upgrade_equip",), "Equip/adjust": ("adjust_equip",), "Fairy/adjust": ("adjust_fairy",),
    "Fairy/eatFairy": ("eat_fairy",), "Gun/combineGun": ("combine_gun",), "Operation/finishOperation": ("operation",),
    "Automission/finishAutomission": ("auto_battle", "auto_mission"),
    "Gun/skillUpgrade": ("upgrade",), "Gun/mindupdate": ("mind_update",),
    "Sangvis/resolution": ("sangvis_resolution",), "Gun/like": ("like", "upvote"),
    "Dorm/receive_favor": ("heart_collect",), "Dorm/receiveSangvisFavor": ("heart_collect",),
}


# --- state-based progress (career quests, achievements) -----------------------------------

def _rows(state, key):
    v = state.get(key) or []
    return list(v.values()) if isinstance(v, dict) else v


def _cleared(state):
    return {int(r["mission_id"]) for r in state.get("mission_with_user_info") or [] if int(r.get("win_counter") or 0) > 0}


def _mission_type(kind):
    """mission_<0|emergency>_<campaign>_<sub>_<x> -> (emergency, campaign, sub)."""
    parts = kind.split("_")
    try:
        if parts[1] == "emergency":
            return 1, int(parts[2]), int(parts[3])
        return 0, int(parts[1]), int(parts[2])
    except (IndexError, ValueError):
        return None


class _Ctx:
    """The save summarised once per call (each quest row would otherwise rescan it)."""

    def __init__(self, state, q):
        from .missions import _missions
        self.state, self.q, self.memo = state, q, {}
        self.missions = _missions()
        self.guns, self.fairies = _rows(state, "gun_with_user_info"), _rows(state, "fairy_with_user_info")
        self.sangvis, self.equips = _rows(state, "sangvis_with_user_info"), _rows(state, "equip_with_user_info")
        self.records = state.get("mission_with_user_info") or []
        self.cleared = _cleared(state)
        m = self.missions
        self.cleared_keys = {(int(m[i]["if_emergency"]), int(m[i]["campaign"]), int(m[i]["sub"]))
                             for i in self.cleared if i in m}
        self.by_cond = {
            "c_gun_level": [int(g.get("gun_level") or 0) for g in self.guns],
            "c_gun_skill_level": [int(g.get("skill1") or 0) for g in self.guns],
            "c_gun_skill2_level": [int(g.get("skill2") or 0) for g in self.guns],
            "c_sangvis_level": [int(x.get("sangvis_level") or 0) for x in self.sangvis],
            "c_sangvis_advance": [int(x.get("sangvis_advance") or 0) for x in self.sangvis],
            "c_fairy_level": [int(f.get("fairy_lv") or 0) for f in self.fairies],
            "c_fairy_rank": [int(f.get("quality_lv") or 0) for f in self.fairies],
            "c_fairy_skill_level": [int(f.get("skill_lv") or 0) for f in self.fairies],
            "c_equip_enhancement": [int(e.get("equip_level") or 0) for e in self.equips],
        }

    def simple(self, kind):
        m, cleared = self.missions, self.cleared
        table = {
            "up_mod1": lambda: sum(1 for g in self.guns if int(g.get("if_modification") or 0) >= 1),
            "up_mod2": lambda: sum(1 for g in self.guns if int(g.get("if_modification") or 0) >= 2),
            "different_gun": lambda: len({g["gun_id"] for g in self.guns}),
            "different_fairy": lambda: len({f["fairy_id"] for f in self.fairies}),
            "different_equip": lambda: len({e["equip_id"] for e in self.equips}),
            "complete_normal_mission": lambda: sum(1 for i in cleared if i in m and int(m[i]["if_emergency"]) == 0),
            "complete_emergency_mission": lambda: sum(1 for i in cleared if i in m and int(m[i]["if_emergency"]) == 1),
            "complete_night_mission": lambda: sum(1 for i in cleared if i in m and int(m[i].get("special_type") or 0) == 1),
            "mission_medal1": lambda: sum(1 for r in self.records if r.get("medal1") == "1"),
            "mission_medal4": lambda: sum(1 for r in self.records if r.get("medal4") == "1"),
            "mission_bestrank5": lambda: sum(1 for r in self.records if r.get("bestrank") == "5"),
        }
        return table[kind]() if kind in table else None


def _value(ctx, kind, cond=None):
    """Progress for one quest/achievement type (and condition), or None when not tracked."""
    key = (kind, cond)
    if key not in ctx.memo:
        ctx.memo[key] = _compute(ctx, kind, cond)
    return ctx.memo[key]


def _compute(ctx, kind, cond):
    if kind in TRACKED:
        return ctx.q["counters"].get(kind, 0)
    derived = _derive(ctx, kind, cond)
    counted = ctx.q["counters"].get(kind)
    # an imported figure is a floor: what the save can show may have passed it
    return derived if counted is None else max(counted, derived or 0)


def _derive(ctx, kind, cond):
    first = str(cond or "").split(",")[0]
    if kind in ctx.by_cond:
        return sum(1 for v in ctx.by_cond[kind] if v >= int(first)) if first.isdigit() else None
    if kind in ("c_tutorial_mission", "c_mission"):
        # condition: one mission id or several ("a,b"); progress = how many are cleared
        ids = [int(x) for x in str(cond or "").replace(";", ",").split(",") if x.strip().isdigit()]
        return sum(1 for i in ids if i in ctx.cleared) if ids else None
    if kind == "c_establish_up":
        # condition: facility type; progress: its level
        rows = [r for r in ctx.state.get("outhouse_establish_info") or [] if str(r.get("establish_type")) == first]
        return max((int(r.get("establish_lv") or 0) for r in rows), default=0) if first else None
    if kind.startswith("mission_") and _mission_type(kind):
        return int(_mission_type(kind) in ctx.cleared_keys)
    return ctx.simple(kind)


def _met(ctx, row):
    v = _value(ctx, row["type"], row.get("condition") or None)
    return v is not None and v >= int(row["count"] or 0)


def _career_value(ctx, row):
    """Career progress: what the save shows, or the imported figure plus what has been counted since."""
    kind, cond = row["type"], row.get("condition") or None
    q = ctx.q
    if cond:
        saved = q.get("career_cond", {}).get(str(row["id"]))
        v = _value(ctx, kind, cond)
        return v if saved is None else max(saved, v or 0)
    base = q.get("career_base", {}).get(kind)
    if base is None:
        return _value(ctx, kind)
    return max(base["value"] + max(0, q["counters"].get(kind, 0) - base["at"]), _derive(ctx, kind, None) or 0)


def _career_met(ctx, row):
    v = _career_value(ctx, row)
    return v is not None and v >= int(row["count"] or 0)


def _career_progress(ctx):
    out, conds = {}, {}
    for r in career_rows().values():
        v = _career_value(ctx, r) or 0
        if r.get("condition"):
            conds.setdefault(r["type"], []).append(f"{r['id']}-{v}")
        else:
            out[r["type"]] = v
    out.update({kind: ",".join(parts) for kind, parts in conds.items()})
    return out


# --- mail -------------------------------------------------------------------------------

def _mails(state):
    if not state.get("_mail_imported"):
        _import_mails(state)
    if not state.get("_mail_flags_synced"):
        _sync_mail_flags(state)
    for m in state["_mail"]:
        m.setdefault("if_locked", False)
    return state["_mail"]


def _flag(value):
    return str(value).strip().lower() in ("1", "true")


def _import_mails(state):
    """Once: the account's live mailbox from its archived Index/getMailList, received and locked state kept.
    The server's own mails are numbered after the live ones, as Index/getMailList's start_id is the client's
    newest id."""
    from . import archived
    mails = state.setdefault("_mail", [])
    state["_mail_imported"] = state["_mail_flags_synced"] = True
    live = archived.read(str((state.get("user_info") or {}).get("user_id", "")), "Index/getMailList")
    have = {m["id"] for m in mails}
    for m in live if isinstance(live, list) else []:
        if not isinstance(m, dict) or not str(m.get("id") or "").isdigit() or str(m["id"]) in have:
            continue
        mail = {"id": str(m["id"]), "sub_id": str(m.get("sub_id") or 0), "title": m.get("title") or "",
                "content": m.get("content") or "", "type": int(m.get("type") or 1),
                "start_time": int(m.get("start_time") or 0), "end_time": int(m.get("end_time") or 0),
                "if_read": _flag(m.get("if_read")), "if_received": _flag(m.get("if_received")),
                "if_locked": _flag(m.get("if_locked"))}
        if m.get("code"):
            mail["code"] = str(m["code"])
        mail.update(_reward(m))
        mails.append(mail)
    top = max((int(m["id"]) for m in mails), default=0)
    state["_mail_next"] = max(int(state.get("_mail_next") or 1), top + 1)


def _sync_mail_flags(state):
    """Once: locked and received from the archived live mailbox, for live mails imported before they were kept.
    Either one set here stays set."""
    from . import archived
    state["_mail_flags_synced"] = True
    live = archived.read(str((state.get("user_info") or {}).get("user_id", "")), "Index/getMailList")
    by_id = {str(m.get("id")): m for m in live if isinstance(m, dict)} if isinstance(live, list) else {}
    for mail in state.get("_mail") or []:
        m = by_id.get(mail["id"])
        if m is None:
            continue
        for key in ("if_locked", "if_received", "if_read"):
            mail[key] = bool(mail.get(key)) or _flag(m.get(key))


def set_mail_lock(state, body):
    """Index/setMailLock {"mail_id", "if_locked"} (RequestLockMails)."""
    body = body or {}
    mail = next((m for m in _mails(state) if m["id"] == str(body.get("mail_id"))), None)
    if mail is not None:
        mail["if_locked"] = _flag(body.get("if_locked"))
    return "1"


def _unit_count(rest):
    """The count after "id-" in a prize's gun_id / equip_ids entry. "id-n" is n of them; longer entries are one
    unit with its details (dolls "id-50-3-1-1", the level first), not a count. fairy_ids has no count."""
    rest = str(rest or "").strip()
    return int(rest) if rest.isdigit() else 1


def _reward(row):
    """The reward fields of a prize/achievement row, in prize-table (Package) form."""
    out = {k: int(row.get(k) or 0) for k in RES if int(row.get(k) or 0)}
    for k in LISTS:
        if str(row.get(k) or "").strip() not in ("", "0"):
            out[k] = str(row[k])
    if str(row.get("gun_id") or "").strip() not in ("", "0"):
        out["gun_id"] = str(row["gun_id"])
    for k in WEAR:
        if str(row.get(k) or "").strip() not in ("", "0"):
            out[k] = str(row[k])
    return out


def send_mail(state, kind, sub_id, title, reward, now=None):
    now = int(now or time.time())
    mid = int(state.get("_mail_next") or 1)
    state["_mail_next"] = mid + 1
    mail = {"id": str(mid), "sub_id": str(sub_id), "title": title, "content": "", "type": kind,
            "start_time": now, "end_time": now + MAIL_DAYS * 86400, "if_read": False, "if_received": False,
            # Mail$$.ctor starts every mail locked and unlocks it only by this key; a locked mail is kept after its
            # claim (RequestMailResourceHandle), so a quest box could be claimed again and an achievement mail
            # showed again on each return to the screen
            "if_locked": False}
    mail.update(reward)
    _mails(state).append(mail)
    return mail


def _prize_mail(state, kind, sub_id, title, prize_id):
    return send_mail(state, kind, sub_id, title, _reward(prizes().get(int(prize_id or 0), {})))


def grant(state, mail):
    """Add a mail's reward to the save; returns the package for the client."""
    from . import factory, workshop
    ui = state["user_info"]
    pkg = {k: mail[k] for k in RES + LISTS + WEAR + ("gun_id",) if k in mail}
    for k in RES:
        if k == "user_exp":
            _add(ui, "experience", int(mail.get(k) or 0))
        elif k in mail:
            _add(ui, k, int(mail[k]))
    for key, coll in (("item_ids", "item_with_user_info"), ("gift", "gift_with_user_info")):
        for part in str(mail.get(key) or "").split(","):
            if "-" not in part:
                continue
            iid, num = (int(x) for x in part.split("-")[:2])
            rows = state.setdefault(coll, [])
            row = next((r for r in rows if str(r["item_id"]) == str(iid)), None)
            if row is None:
                row = {"item_id": str(iid), "number": "0"}
                if coll == "item_with_user_info":
                    row["last_recover_time"] = "0"
                rows.append(row)
            row["number"] = str(int(row["number"]) + num)
    guns = []
    for part in str(mail.get("gun_id") or "").split(","):
        gid, _, num = part.partition("-")
        if gid.strip().isdigit() and int(gid) in factory.guns():
            for _ in range(_unit_count(num)):
                rec = factory.new_gun_record(state, int(gid), ui.get("user_id", ""))
                guns.append({"gun_with_user_id": rec["id"], "gun_id": rec["gun_id"]})
    if guns:
        pkg["guns"] = guns
    # the new records go in the package too: the client adds equipment and fairies from its "equips" / "fairys"
    # lists (Package$$GetPackage reads them from the package's own JSON), and only ids would show after a relogin
    equips, fairys = [], []
    for part in str(mail.get("equip_ids") or "").split(","):
        eid, _, num = part.partition("-")
        if eid.strip().isdigit() and int(eid) in workshop.equips():
            for _ in range(_unit_count(num)):
                equips.append(dict(workshop.new_equip(state, int(eid))))
    for part in str(mail.get("fairy_ids") or "").split(","):
        # one fairy per entry: "fairy_id-talent" (0: none given, "18-910118"), longer ones "26-0-100-5";
        # the number after the id is never a count (read as one, "15-910101" made 910101 fairies)
        fid, _, rest = part.partition("-")
        if fid.strip().isdigit() and int(fid) in workshop.fairies():
            talent = rest.split("-")[0].strip()
            known = {int(t["id"]) for t in stc.table("fairy_talent")}
            talent = int(talent) if talent.isdigit() and int(talent) in known else workshop._talents()[0]
            rec = workshop.new_fairy(state, int(fid), talent)
            fairys.append({"fairy_with_user_id": rec["id"], "fairy_id": rec["fairy_id"], "passive_skill": rec["passive_skill"],
                           "fairy_exp": rec["fairy_exp"], "quality_exp": rec["quality_exp"]})
    if equips:
        pkg["equips"] = equips
    if fairys:
        pkg["fairys"] = fairys
    uid = str(ui.get("user_id", ""))
    skins = state.setdefault("skin_with_user_info", {})
    for sid in _ids(mail.get("skin")):
        rec = {"skin_id": sid, "user_id": uid, "is_read": "0"}
        if isinstance(skins, dict):
            skins.setdefault(sid, rec)
        elif not any(str(s.get("skin_id")) == sid for s in skins):
            skins.append(rec)
    outfits = state.setdefault("commander_uniform_info", [])
    for cid in _ids(mail.get("commander_uniform")):
        if not any(str(u.get("commander_uniform_id")) == cid for u in outfits):
            outfits.append({"user_id": uid, "commander_uniform_id": cid, "color_get": [], "get_color_num": "0",
                            "create_time": str(int(time.time()))})
    mail["if_received"] = mail["if_read"] = True
    return pkg


def quiet_records(state, pkg):
    """Replies the client unpacks with forceShowPerformance (Giftbox/open, the Collect All replies) carry no
    "equips" / "fairys" records: each would queue the factory's get-new animation (GetEquipItem /
    CommonGetNewFariyController), which can't play elsewhere, and the reward popup queued after it never showed.
    The popup lists them from equip_ids / fairy_ids; they are in the save and show from the next login."""
    pkg.pop("equips", None)
    pkg.pop("fairys", None)
    return pkg


def _ids(value):
    return [x.split("-")[0].strip() for x in str(value or "").split(",") if x.split("-")[0].strip() not in ("", "0")]


def _merge(packages):
    out = {}
    for p in packages:
        for k, v in p.items():
            if k in RES:
                out[k] = out.get(k, 0) + int(v)
            elif k in ("guns", "equips", "fairys"):
                out.setdefault(k, []).extend(v)
            else:
                out[k] = f"{out[k]},{v}" if k in out else v
    return out


# --- endpoints --------------------------------------------------------------------------

def _period_block(q, period):
    p = q[period]
    rows = daily_rows() if period == "daily" else weekly_rows()
    block = {f"{period}_quest_pool": ",".join(str(i) for i in sorted(rows)),
             "refresh_count": ",".join(str(x) for x in p["refresh"]),
             f"{period}_quest_list": ",".join(str(i) for i in p["list"]),
             "accomplish_quest_list": ",".join(str(i) for i in p["done"]),
             "end_time": p["end"],
             # every quest type in the pool, 0 when nothing counted yet: the client looks each listed
             # quest's type up in this dictionary (WeekQuestInfo$$get_IsAccomplished)
             "progress": dict({str(r["type"]): 0 for r in rows.values() if r.get("type")}, **p["progress"])}
    if period == "weekly":
        block["locked_quest_list"] = ",".join(str(i) for i in p.get("locked") or [])
        block["weekly_accumulation"] = p["accumulation"]
    return block


def _check_long_term(state, q, ctx):
    """Reward newly met career quests and achievements by mail."""
    done_c, done_a = set(q["career_done"]), set(q["achievement_done"])
    for cid, row in sorted(career_rows().items()):
        if cid not in done_c and _career_met(ctx, row):
            q["career_done"].append(cid)
            _prize_mail(state, MAIL_CAREER, cid, row["title"], row["prize_id"])
    for aid, row in sorted(achievement_rows().items()):
        if aid not in done_a and _met(ctx, row):
            q["achievement_done"].append(aid)
            reward = _reward(prizes()[int(row["prize_id"])]) if int(row.get("prize_id") or 0) in prizes() else _reward(row)
            send_mail(state, MAIL_ACHIEVEMENT, aid, row["title"], reward)


def _achievement_block(state, q, ctx):
    block = {k: str(v) for k, v in q["counters"].items()}
    block.update({"id": "1", "user_id": str(state["user_info"].get("user_id", "")),
                  "accomplish_achievement_ids": ",".join(str(i) for i in q["achievement_done"])})
    conds, imported = {}, q.get("achievement_cond", {})
    for aid, row in sorted(achievement_rows().items()):
        v = _value(ctx, row["type"], row.get("condition") or None)
        if row.get("condition"):
            n = max(imported.get(str(aid), 0), v or 0)
            parts = conds.setdefault(row["type"], [])
            if n:
                parts.append(f"{aid}-{n}")
        elif v is not None:
            block[row["type"]] = str(v)
    block.update({kind: ",".join(parts) for kind, parts in conds.items()})
    return block


def quest_info(state, body):
    q = _state(state)
    ctx = _Ctx(state, q)
    _check_long_term(state, q, ctx)
    grades = {}
    for cid in q["career_done"]:
        grades.setdefault(int(career_rows()[cid]["grade_id"]), []).append(cid)
    return {"daily": _period_block(q, "daily"), "weekly": _period_block(q, "weekly"),
            "career": _career_progress(ctx),
            "career_quest_grade": [{"grade_id": g, "accomplish_quest_ids": ",".join(str(i) for i in ids)}
                                   for g, ids in sorted(grades.items())],
            "chess_game_counts": q.get("chess_counts") or {"free": 0, "match": 0}, "cheers_counts": int(q.get("cheers") or 0),
            "achievement": _achievement_block(state, q, ctx)}


def _accomplish(state, q, period, qid):
    """Reward one finished quest; returns the mails sent (empty if not finishable)."""
    p = q[period]
    rows = daily_rows() if period == "daily" else weekly_rows()
    row = rows.get(int(qid or 0))
    if row is None or row["identity"] in p["done"] or row["identity"] not in p["list"] \
            or p["progress"].get(row["type"], 0) < int(row["count"]):
        return []
    p["done"].append(row["identity"])
    mails = [send_mail(state, MAIL_DAILY if period == "daily" else MAIL_WEEKLY, row["identity"],
                       row["title"], _quest_prize(state, row))]
    w = q["weekly"]
    w["accumulation"] += WEEKLY_POINTS[period]
    if period == "weekly":
        w["progress"]["weekly_complete"] = w["progress"].get("weekly_complete", 0) + 1
    if period == "daily" and not p.get("chest"):
        for need, prize in _pairs(_config().get("daily_progress")):
            if len(p["done"]) >= need:
                p["chest"] = True
                mails.append(_prize_mail(state, MAIL_DAILY, need, "daily_progress", prize))
    return mails + _pay_boxes(state, q)


def _pay_boxes(state, q):
    """Mail each weekly point box reached and not yet paid."""
    w, mails = q["weekly"], []
    for need, prize in _pairs(_config().get("weekly_progress")):
        if w["accumulation"] >= need and need not in w["paid"]:
            w["paid"].append(need)
            mails.append(_prize_mail(state, MAIL_WEEKLY, need, "weekly_progress", prize))
    return mails


def _quest_prize(state, row):
    """A daily / weekly quest's reward. While a battle pass season runs, the prize's pass points
    (the season's pt_item_id) are paid at once and the rest goes by mail (the claim replies carry
    battlepass_pt_item: RequestCompleteDailyQuests / Weekly / All read it into GameData items);
    with no season, exchange_prize_id, the same prize without them."""
    from . import battlepass, squads
    season, _ = battlepass.current()
    pid = row["prize_id"] if season or not int(row.get("exchange_prize_id") or 0) else row["exchange_prize_id"]
    reward = _reward(prizes().get(int(pid or 0), {}))
    if season is None:
        return reward
    pt, keep, gained = str(season["pt_item_id"]), [], 0
    for part in str(reward.get("item_ids") or "").split(","):
        iid, _, num = part.partition("-")
        if iid.strip() == pt and num.strip().isdigit():
            gained += int(num)
        elif part.strip():
            keep.append(part)
    if gained:
        battlepass._record(state, season, int(time.time()))     # a new season's record zeroes the points first
        item = squads._item(state, pt)
        item["number"] = str(int(item["number"]) + gained)
        reward["item_ids"] = ",".join(keep)
        if not keep:
            reward.pop("item_ids")
    return reward


def _pass_points(state):
    from . import battlepass, squads
    season, _ = battlepass.current()
    return {} if season is None else {str(season["pt_item_id"]): int(squads._item(state, str(season["pt_item_id"]))["number"])}


def _claimed(state, q, mails):
    # a quest already claimed (or not finished) still gets a reply: none drops the connection
    return {"weekly_accumulation": q["weekly"]["accumulation"], "mail_list": mails,
            "battlepass_pt_item": _pass_points(state)}


def accomplish_daily(state, body):
    q = _state(state)
    return _claimed(state, q, _accomplish(state, q, "daily", (body or {}).get("daily_quest_id")))


def accomplish_weekly(state, body):
    q = _state(state)
    return _claimed(state, q, _accomplish(state, q, "weekly", (body or {}).get("weekly_quest_id")))


def accomplish_all(state, body):
    q = _state(state)
    mails = []
    for period in ("daily", "weekly"):
        for qid in list(q[period]["list"]):
            mails += _accomplish(state, q, period, qid)
    # arrays here: DailyQuestOverallInfo / WeeklyQuestOverallInfo$$UpdateAcomplishList read each entry
    # with get_Int (a comma string threw, and the client kept the quests claimable)
    return dict(_claimed(state, q, mails),
                daily={"accomplish_quest_list": [int(i) for i in q["daily"]["done"]]},
                weekly={"accomplish_quest_list": [int(i) for i in q["weekly"]["done"]]})


def _refresh(state, period, qid):
    q = _state(state)
    p = q[period]
    rows = daily_rows() if period == "daily" else weekly_rows()
    qid = int(qid or 0)
    limit = int(_config().get("task_refresh") or 1)
    if qid not in p["list"] or qid in p["done"] or p["refresh"][p["list"].index(qid)] >= limit:
        return q, p, 1
    i = p["list"].index(qid)
    same = [k for k, r in sorted(rows.items()) if r["type"] in TRACKED and k not in p["list"]
            and (period == "weekly" or r["mission_type"] == rows[qid]["mission_type"])]
    if not same:
        return q, p, 1
    p["list"][i] = random.choice(same)
    p["refresh"][i] += 1
    return q, p, 0


def refresh_daily(state, body):
    q, p, err = _refresh(state, "daily", (body or {}).get("daily_quest_id"))
    return {"refresh_error": err, "refresh_count": ",".join(str(x) for x in p["refresh"]),
            "daily_quest_list": ",".join(str(i) for i in p["list"])}


def refresh_weekly(state, body):
    q, p, err = _refresh(state, "weekly", (body or {}).get("weekly_quest_id"))
    return {"refresh_error": err, "refresh_count": ",".join(str(x) for x in p["refresh"]),
            "weekly_quest_list": ",".join(str(i) for i in p["list"]), "locked_quest_list": ""}


def achievement(state, body):
    q = _state(state)
    ctx = _Ctx(state, q)
    _check_long_term(state, q, ctx)
    return _achievement_block(state, q, ctx)


# Point event (carnival) mail types, which its Collect All may name. A claimed one must leave the list: the
# client shows any type 16/17 mail it holds as claimable and never reads if_received
# (CarnivalController <CreateTasks>b__1, <CreateRewards>b__0, Data <ExistsNewCarnivalTaskRewards>b__86_0).
KEPT_MAILS = (16, 17)


# Mailbox mails (MailType 1, 3, 6) stay listed once received, as live lists them (its Index/getMailList had 197
# received type 1 mails); the client drops an unlocked one itself when it is claimed (Mail$$IsMailNeedDelete).
MAILBOX_TYPES = (1, 3, 6)


def mail_list(state, body):
    """A locked mail stays listed after its end time, as live lists it (locking keeps it)."""
    start = _n(body, "start_id", 0)
    now = time.time()
    return [m for m in _mails(state) if (not m["if_received"] or int(m["type"]) in MAILBOX_TYPES)
            and int(m["id"]) > start and (m["end_time"] > now or m.get("if_locked"))]


def one_mail(state, body):
    """Index/getOneMail, which no client code sends: one row of Index/getMailList."""
    mid = str((body or {}).get("mail_with_user_id") or "")
    return next((m for m in _mails(state) if m["id"] == mid), None)


def if_new_mail(state, body):
    return {"kick": 0, "if_new_mail": int(any(not m["if_received"] for m in _mails(state)))}


def get_mail_resource(state, body):
    mid = str((body or {}).get("mail_with_user_id") or "")
    mail = next((m for m in _mails(state) if m["id"] == mid and not m["if_received"]), None)
    # the client can ask twice, and Mail$$RequestMailResourceHandle reads "mail" with no check for an error
    return {"mail": grant(state, mail) if mail else {}}


def quick_get_quest_mails(state, body):
    """Claim every unclaimed quest reward mail (of the MailType in "type" when it is one)."""
    kind = (body or {}).get("type")
    # Only the type asked for, as the client drops only those after the reply (RequestQuickGetResourceInQuests
    # b__5_0): the quest screen's Collect All sends 7 (daily and weekly, the point boxes too) or 21 (career), the
    # point event's 16 (param -1), and the daily exploration map 27 on its own when it opens
    # (DailyMapCreater$$CheckHavePtPrize), which here claimed every quest mail, the weekly boxes with them.
    if str(kind or "").isdigit():
        kinds = {MAIL_DAILY, MAIL_WEEKLY} if int(kind) == MAIL_DAILY else {int(kind)}
    else:
        kinds = set(QUEST_MAILS)
    picked = [m for m in _mails(state) if not m["if_received"] and m["type"] in kinds]
    pkg = quiet_records(state, _merge(grant(state, m) for m in picked))
    pkg["career_mail_ids"] = [int(m["id"]) for m in picked if m["type"] == MAIL_CAREER]
    return pkg


def delete_mails(state, body):
    ids = {str(i) for i in (body or {}).get("mail_ids") or []}
    state["_mail"] = [m for m in _mails(state) if m["id"] not in ids]
    return {}


def quick_get_all_mails(state, body):
    """Index/quickGetResourceInMails: claim every unclaimed mail; the reply is one package
    (RequestQuickGetResourceInMails reads it with Package$$GetPackage)."""
    picked = [m for m in _mails(state) if not m["if_received"] and m["end_time"] > time.time()]
    return quiet_records(state, _merge(grant(state, m) for m in picked))
