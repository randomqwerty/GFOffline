"""Account-level calls: commander look, adjutant, settings, presets, resource regen, heartbeat.

Reply formats (from the client's handlers):
  Index/modName           "1"  {"new_name"}                         RequestChangeName
  Index/adjutant          "1"  {"adjutant_multi": {...} | json str}  RequestChangeAdjutant
                               (same shape as the save's user_adjutant_multi)
  Commander/changeGender  "1"  {"gender"}            Commander/changeDressed "1" {"dressed_info"}
  Commander/changeEmoji   "1"  {"emoji" | "commander_emoji"}
  Commander/savePreset    "1"  {"pos", "preset_info"}   Commander/usePreset "1" {"pos"}
  Index/gameSetting       "1"  {"settings": {...} | json str, "vibrate"}  ConfigData$$RequestSetGameSetting
  Mission/autoMissionPresets "1"  {"automission_presets": json str} or the preset object itself
                               (set_active, team, vehicle, squad)   RequsetAutoPlanTeamSet
  Index/recoverResource   {"recover_mp", "recover_ammo", "recover_mre", "recover_part"} (unguarded),
                          optional "gem"                      RequestRecoverResource
  Index/heartBeat         {} (every key guarded: time, max_time, status, play_start, play_end,
                          is_legal_holidays: play-time limits, unused offline)  RequestHeartPackage
  Index/setMailLock "1"   (mail itself: quests.py)
APPROXIMATION: the natural regen rate and cap are server-side; GF's commonly cited 3/3/3/1 every
3 minutes is used, stopping at a cap that grows with commander level (REGEN_CAP_*).
"""
import json
import logging
import random
import time
from functools import lru_cache

from . import archived

log = logging.getLogger(__name__)

REGEN_INTERVAL = 180
REGEN_AMOUNT = {"mp": 3, "ammo": 3, "mre": 3, "part": 1}
REGEN_CAP_BASE, REGEN_CAP_PER_LEVEL = 30000, 100


def _obj(value):
    """A body field the client may send as a JSON string or as an object."""
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _commander(state):
    return state.setdefault("commander_with_user_info", {})


def mod_name(state, body):
    name = str((body or {}).get("new_name") or "").strip()
    if not name:
        return None
    state["user_info"]["name"] = name
    return "1"


def adjutant(state, body):
    value = _obj((body or {}).get("adjutant_multi"))
    if not isinstance(value, dict):
        return None
    state["user_adjutant_multi"] = value
    return "1"


def change_gender(state, body):
    _commander(state)["gender"] = str((body or {}).get("gender") or 0)
    return "1"


def change_dressed(state, body):
    dressed = (body or {}).get("dressed_info")
    if dressed is None:
        return None
    _commander(state)["dressed"] = dressed if isinstance(dressed, str) else json.dumps(dressed)
    return "1"


def change_emoji(state, body):
    body = body or {}
    emoji = body.get("emoji", body.get("commander_emoji"))
    if emoji is None:
        return None
    _commander(state)["commander_emoji"] = str(emoji)
    return "1"


def save_preset(state, body):
    body = body or {}
    pos = int(body.get("pos") or 0)
    if not 1 <= pos <= 4:
        return None
    info = body.get("preset_info")
    _commander(state)[f"preset{pos}"] = info if isinstance(info, str) else json.dumps(info)
    return "1"


def use_preset(state, body):
    pos = int((body or {}).get("pos") or 0)
    preset = _commander(state).get(f"preset{pos}")
    if preset:
        _commander(state)["dressed"] = preset
    return "1"


def game_setting(state, body):
    body = body or {}
    row = state["user_game_setting"] = state.get("user_game_setting") or {}      # null in a new account
    settings = body.get("settings")
    if settings is None:
        return None
    row["settings"] = settings if isinstance(settings, str) else json.dumps(settings, separators=(",", ":"))
    if "vibrate" in body:
        row["vibrate"] = body["vibrate"]
    return "1"


def auto_mission_presets(state, body):
    body = body or {}
    presets = body.get("automission_presets", body)
    row = state["automission_presets_info"] = state.get("automission_presets_info") or {"user_id": str(state["user_info"].get("user_id", ""))}
    row["automission_presets"] = presets if isinstance(presets, str) else json.dumps(presets, separators=(",", ":"))
    return "1"


def recover_resource(state, body, now=None):
    """Natural regen since user_info.last_recover_time, for resources under the cap."""
    ui = state["user_info"]
    now = int(now or time.time())
    last = int(ui.get("last_recover_time") or now)
    ticks = max(0, (now - last) // REGEN_INTERVAL)
    cap = REGEN_CAP_BASE + REGEN_CAP_PER_LEVEL * int(ui.get("lv") or 1)
    reply = {}
    for res, per in REGEN_AMOUNT.items():
        have = int(ui.get(res) or 0)
        add = max(0, min(ticks * per, cap - have))
        ui[res] = str(have + add) if isinstance(ui.get(res), str) else have + add
        reply[f"recover_{res}"] = add
    ui["last_recover_time"] = str(last + ticks * REGEN_INTERVAL) if ticks else str(last)
    return reply


def heart_beat(state, body):
    return {}


# Fairy Command (item 509, Data.FairySupportCommand). The client takes a skill's cost off its own count
# (fairySkillPerform: mission_skill_config.consumption; a battle where the fairy's skill fired:
# battle_skill_config.consumption, which the battle report flags as use_fairy_skill) and adds what
# recoverSsoc / Index/home give back, so the save's count follows the same steps. The Fairy Room sets
# the numbers (Data$$GetFairySupportCommandRecoveryNumber / GetMaxFairySupportCommand): the railway
# model (establish 302) gives parameter_1 commands per period, up to the warehouse's (303) parameter_1.
# The period is ssoc_change_unit_time cut by fairy_command_recovery_time_reduce percent
# (Data$$RecoveryFairySupportCommandHour): what the organization departments have unlocked
# (GameData$$GetOrgMapUnlockSkillsList: every organization_level row up to a department's level adds
# its function skill's arguments) plus the commander's shown, active function skills (level x arguments;
# the fairy-command ones are all hidden, so none count).
SSOC_UNIT = 21600      # game_config ssoc_change_unit_time
SSOC_ITEM = 509
SSOC_REDUCE = "fairy_command_recovery_time_reduce"
RAILWAY_MODEL, WAREHOUSE_MODEL = "302", "303"


def _establish_number(state, kind):
    from . import squads
    try:
        return int(float(squads._establish(state, kind).get("parameter_1") or 0))
    except ValueError:
        return 0


def ssoc_cap(state):
    return _establish_number(state, WAREHOUSE_MODEL)


def ssoc_reduce(state):
    """fairy_command_recovery_time_reduce percent from the organization departments' levels."""
    from . import stc
    skills = {str(r["id"]): r for r in stc.table("function_skill_config")}
    levels = {str(d.get("department_id")): int(d.get("level") or 0) for d in state.get("org_department_info") or []}
    total = 0
    for row in stc.table("organization_level"):
        if int(row["level"]) > levels.get(str(row["organization_id"]), 0):
            continue
        for sid in str(row.get("function_skill_config_id") or "").split(","):
            skill = skills.get(sid.strip())
            if skill and skill["function_skill"] == SSOC_REDUCE:
                total += int(skill.get("arguments") or 0)
    return min(total, 99)


def ssoc_period(state):
    return max(1, SSOC_UNIT * (100 - ssoc_reduce(state)) // 100)


def spend_ssoc(state, n):
    from . import squads
    row = squads._item(state, SSOC_ITEM)
    have = int(row["number"] or 0)
    row["number"] = str(max(0, have - max(0, int(n or 0))))


def recover_ssoc(state, body, now=None):
    """Index/recoverSsoc -> {"recover_ssoc", "last_ssoc_change_time"} (RequestRecoverSupportCommand;
    Index/home carries the same two): the client adds recover_ssoc to its count. See the note above."""
    from . import squads
    ui = state["user_info"]
    now = int(now or time.time())
    period = ssoc_period(state)
    last = min(now, int(ui.get("last_ssoc_change_time") or now))
    ticks = max(0, (now - last) // period)
    row = squads._item(state, SSOC_ITEM)
    have, cap = int(row["number"] or 0), ssoc_cap(state)
    add = max(0, min(ticks * _establish_number(state, RAILWAY_MODEL), cap - have))
    row["number"] = str(have + add)
    # a full store doesn't bank time: the next command comes a full period after it drops below the cap
    last = now if have + add >= cap else last + ticks * period
    ui["last_ssoc_change_time"] = str(last)
    return {"recover_ssoc": add, "last_ssoc_change_time": last}


def home(state, body, now=None):
    """Index/home {data_version, ab_version, start_id, ignore_time} (RequestHomeData), sent on every
    visit to the main screen. The client adds the recover_* amounts and takes gem, daily, weekly and
    fetter_bounty_with_user as they are, so they come from the save (a recorded reply would put the
    gem count and quest panel back to the day it was recorded). Resources come back through
    Index/recoverResource, so recover_* is 0; career_quest_grade is guarded and left out."""
    from . import quests, sangvis_sim
    now = int(now or time.time())
    sangvis_sim.daily_energy(state, now)
    q = quests.quest_info(state, body)
    reply = {"kick": 0, "recover_mp": 0, "recover_ammo": 0, "recover_mre": 0, "recover_part": 0,
             "gem": int(state["user_info"].get("gem") or 0), **recover_ssoc(state, body, now),
             # armor energy: the hourly rate is a server rule not in the client data
             "recover_energy": 0, "last_energy_recover_time": now,
             "build_coin_flag": battery_flag(state, now), "friend_messagelist": [], "friend_applylist": [],
             "index_getmaillist": quests.mail_list(state, body), "push_message_list": [],
             "daily": q["daily"], "weekly": q["weekly"],
             "fetter_bounty_with_user": state.get("fetter_bounty_with_user") or [],
             "squad_data_daily": state.get("squad_data_daily") or []}
    return reply


def spare_names(state, body):
    """Dorm/spare_name_list -> [{"dorm_spare_id", "dorm_name"}] (RequestSpareRoomNameList)."""
    return [{"dorm_spare_id": int(k), "dorm_name": v} for k, v in sorted(state.get("_dorm_names", {}).items(), key=lambda kv: int(kv[0]))]


def spare_rename(state, body):
    """Dorm/spare_name_modify {"name", "dorm_id"} -> {"name"}."""
    body = body or {}
    name, dorm = str(body.get("name") or "").strip(), str(body.get("dorm_id") or "")
    if not name or not dorm:
        return None
    state.setdefault("_dorm_names", {})[dorm] = name
    return {"name": name}


def list_todo(state, body):
    """Index/listTodo: the home screen's to-do summary; every key is guarded
    (RequestGameTourGuidInfo), so only the career grades from Index/Quest are sent."""
    from . import quests
    return {"career_quest_grade": quests.quest_info(state, body)["career_quest_grade"]}


def mall_buy(state, body):
    """Mall/gemToResource, gemToItem, gemToGiftbag {"mall_id", "num", "is_special"}
    (MallGood$$RequestBuy) -> {"status": 1, "prize": [package per good]} (MallGood$$RequestBuyGoodHandle).
    The goods come from catchdata mall_info (resources, item_ids, gift, prize_id), or the shop list's own row for goods
    only it has (the 7-day packages: types 101, 201, 301, ids 101-107, 1001-1007, 3001-3007), and cost gemprice gems each. Limits are the shop reply's rest_num and daily_quota (mall_tables). APPROXIMATION: discounts are not applied."""
    from . import quests, stc
    body = body or {}
    row = next((r for r in stc.catch("mall_info") if str(r["id"]) == str(body.get("mall_id"))), None)
    if row is None:
        row = _shop(state["user_info"].get("user_id", ""))[1].get(str(body.get("mall_id")))
    num = max(1, int(body.get("num") or 1))
    if row is None:
        return None
    parts = [quests._reward(row)]
    if int(row.get("prize_id") or 0) in quests.prizes():
        parts.append(quests._reward(quests.prizes()[int(row["prize_id"])]))
    one = quests._merge(parts)
    cost = int(row.get("gemprice") or 0) * num
    ui = state["user_info"]
    if int(ui.get("gem") or 0) < cost or not _within_limits(state, str(row["id"]), num):
        return {"status": 0}
    ui["gem"] = str(int(ui.get("gem") or 0) - cost)
    _record_purchase(state, str(row["id"]), num)
    # "prize" is read as one package per good bought (MallGood.RequestBuyGoodHandle: prize[i], then its first
    # entry), so it is a list, and left out when a package would be empty
    prize = [quests.grant(state, one) for _ in range(num)]
    return {"status": 1, "prize": prize} if all(prize) else {"status": 1}


# Mall/staticTables {"is_special"} -> the shop (MallGoodResController$$RequestMallListHandler): an archived reply for this
# account, else the recording in data/responses, else the shipped new-account shop (data/shop.json). rest_num (absent, or -1, when unlimited) is what was left at recording time,
# so purchases since then come off it. A good with only a daily_quota is reported through pointmall_quota, whose rows are
# {"user_id", "product_id", "buy_count", "last_buy_time"}. A recording's own quota rows are someone else's and are dropped.
# APPROXIMATION: that pointmall_quota is what the client reads for daily_quota goods was inferred from the row's fields.
# without any of them, an empty shop
NO_SHOP = {"mall_list": {}, "increase_gem_order": [], "max_cost_list": [], "max_limit": {}, "pointmall_quota": {}, "pointmall_type23_quota": [], "battlepass_pt_item": {}, "mall_score": {}, "monthlycard1_end_time": "0", "monthlycard2_end_time": "0", "monthlycard3_end_time": "0", "gem_mall_ids": "0"}
SHOP_DAY_OFFSET = 8 * 3600     # the server day turns over at 00:00 UTC-8 (handlers.SERVER_DAY_TZ)


def _shop_day(now=None):
    return (int(now or time.time()) - SHOP_DAY_OFFSET) // 86400


@lru_cache(maxsize=2)
def _shop_file(path, mtime):
    tables = json.loads(path.read_text("utf-8"))
    return tables, {str(r["id"]): r for r in tables["mall_list"].values()}


def _shop(uid):
    """(tables, id -> row, is this account's own archive). Treat what comes back as read-only."""
    from . import archived, config
    own = archived.path(uid, "Mall/staticTables")
    path = own if own is not None and own.is_file() else config.RESPONSES_DIR / "Mall" / "staticTables.json"
    if not path.is_file():
        path = config.ROOT / "data" / "shop.json"
    if not path.is_file():
        return dict(NO_SHOP), {}, False
    tables, rows = _shop_file(path, path.stat().st_mtime_ns)
    return tables, rows, path == own


def _purchases(state):
    return state.setdefault("_mall_bought", {"total": {}, "day": _shop_day(), "today": {}})


def _bought_today(record):
    if record["day"] != _shop_day():
        record.update(day=_shop_day(), today={})
    return record["today"]


def _within_limits(state, mall_id, num):
    row = _shop(state["user_info"].get("user_id", ""))[1].get(mall_id)
    if row is None:
        return True
    record = _purchases(state)
    rest, daily = row.get("rest_num"), int(row.get("daily_quota") or 0)
    if rest is not None and int(rest) >= 0 and record["total"].get(mall_id, 0) + num > int(rest):
        return False
    return not daily or _bought_today(record).get(mall_id, 0) + num <= daily


def _record_purchase(state, mall_id, num):
    record = _purchases(state)
    today = _bought_today(record)
    record["total"][mall_id] = record["total"].get(mall_id, 0) + num
    today[mall_id] = today.get(mall_id, 0) + num
    record.setdefault("last", {})[mall_id] = int(time.time())


def mall_tables(state, body):
    uid = state["user_info"].get("user_id", "")
    tables, rows, own = _shop(uid)
    record = _purchases(state)
    today = _bought_today(record)
    reply = dict(tables, mall_list=dict(tables["mall_list"]))
    if not own:
        reply["pointmall_quota"] = {}
    quota = reply["pointmall_quota"] = dict(reply["pointmall_quota"] or {})
    index = {str(r["id"]): k for k, r in tables["mall_list"].items()}
    for mall_id, n in record["total"].items():
        row = rows.get(mall_id)
        if row is None:
            continue
        if row.get("rest_num") is not None and int(row["rest_num"]) >= 0:
            reply["mall_list"][index[mall_id]] = dict(row, rest_num=max(0, int(row["rest_num"]) - n))
        elif int(row.get("daily_quota") or 0) and mall_id in today:
            quota[mall_id] = {"user_id": str(uid), "product_id": mall_id, "buy_count": str(today[mall_id]),
                              "last_buy_time": str(record.get("last", {}).get(mall_id, 0))}
    from . import battlepass, paid_shop
    quota.update(paid_shop.quota_rows(state))
    # the handler sets these counts in the bag: a recording's are another season's or stale
    reply["battlepass_pt_item"] = battlepass.pt_items(state)
    for card in ("monthlycard1", "monthlycard2", "monthlycard3"):     # bought with gems (paid_shop)
        if int(state["user_info"].get(f"{card}_end_time") or 0) > int(reply.get(f"{card}_end_time") or 0):
            reply[f"{card}_end_time"] = str(state["user_info"][f"{card}_end_time"])
    return reply


# Fetter/orgInfo {} -> {"org_info_with_user": {"user_id", "max_gun", "max_fairy", "max_squad", "max_sangvis", "npc"},
# "org_department_info": [{"user_id", "department_id", "level", "exp", "function_skill_id"}]} (RequestFetterGetOrgInfo).
# The max_ fields are the ids met so far. Departments are the account file's, as Index/index sends them. What raised their
# experience was a server rule the client doesn't hold, so they stay as they were.
def fetter_org_info(state, body):
    from . import archived, stc
    uid = str(state["user_info"].get("user_id", ""))
    saved = (archived.read(uid, "Fetter/orgInfo") or {}).get("org_info_with_user") or {}

    def met(rows, field, key):
        ids = {str(r[field]) for r in (state.get(rows) or []) if field in r} | {str(x) for x in saved.get(key) or []}
        return sorted(ids, key=lambda x: int(x) if x.lstrip("-").isdigit() else 0)
    departments = state.get("org_department_info")
    if not departments:
        first = {r["organization_id"]: r for r in stc.table("organization_level") if int(r["level"]) == 1}
        departments = [{"user_id": uid, "department_id": str(o), "level": "1", "exp": "0", "function_skill_id": "0"} for o in sorted(first)]
    return {"org_info_with_user": {"user_id": uid, "max_gun": met("gun_with_user_info", "gun_id", "max_gun"),
                                   "max_fairy": met("fairy_with_user_info", "fairy_id", "max_fairy"),
                                   "max_squad": met("squad_with_user_info", "squad_id", "max_squad"),
                                   "max_sangvis": met("sangvis_with_user_info", "sangvis_id", "max_sangvis"),
                                   "npc": saved.get("npc") or []},
            "org_department_info": departments}


def gem_to_max(state, body):
    """Mall/gemToMax {"type": MallGood.ConstructionType, "num": purchases} "1" (MallGood$$RequestBuy for
    GoodType 11, RequestBuyConstructionHandle): the capacity shop, build slots (type 4) among them. The
    client takes the gems and raises the field itself. Prices are Mall/staticTables max_cost_list: a row
    applies at max_num, the field's current value, or at any value when max_num is 0. Goods with no row at
    the current value are at their limit. APPROXIMATION: any discount in GetBatchGemPrice is not applied."""
    body = body or {}
    tables = _shop(state["user_info"].get("user_id", ""))[0]
    rows = [r for r in tables["max_cost_list"] if str(r["max_type"]) == str(body.get("type"))]
    num = max(1, int(body.get("num") or 1))
    if not rows:
        return None
    field, step, ui = rows[0]["field"], int(rows[0]["step"]), state["user_info"]
    value, cost = int(ui.get(field) or 0), 0
    for _ in range(num):
        row = next((r for r in rows if int(r["max_num"]) in (value, 0)), None)
        if row is None:
            return None
        cost += int(row["cost"])
        value += step
    if int(ui.get("gem") or 0) < cost:
        return None
    ui["gem"] = str(int(ui.get("gem") or 0) - cost)
    ui[field] = str(value)
    return "1"


# --- dorm pet exploration
#
# Explore/setTeam {"guns", "pets", "time_type", "is_auto"} and Explore/setItem {"item_list"} choose the
# next run; Explore/start (no body) -> the run plus {"next_time"} starts it (RequestExploreStart reads the
# reply as an ExploreAction, start_time/end_time/cancel_time unguarded, then takes the time type's mp/ammo/
# mre/part and one of the chosen item itself; the save pays the same): a random area (stc explore_area) and destination, lasting explore_time_type.duration, with an affair
# (stc explore_affair_server) every AFFAIR_EVERY seconds. A run is kept in "_explore"["run"] in the
# ExploreAction format {"start_time", "end_time", "cancel_time", "affairs": [{"affair_id",
# "affair_time"}], "gun_ids", "pet_ids", "area_id", "target_id", "item_id", "draw_event_prize"}.
#   Explore/balance -> {"ex_prize": package, "list": [run], "is_auto", "explore_time_type", "pets",
#                      "items_taken", "next_explore_time", "next_time", "mp", "ammo", "mre", "part"}
#                      (ExploreData$$DecodeExploreBalance reads every key unguarded)
#   Explore/getEvent {"time"} -> {"event_list": [affair], "next_time", "is_prize"}
#   Index/getExploreMail -> {"get_list": [], "out": package} pays a finished run and clears it
#                      (RequestExploreGetReward)
#   Explore/cancel "1" ends the run without reward
# Explore/setItem's item_list is a queue: each run uses its first item and drops it (RequestExploreStart
# removes it and takes one from the bag itself). The item's stc explore_item row: explore_time_down scales the
# run's length, area_id_up "area:weight" weights the area picked (others weigh 1), reward1_up scales the
# run's reward and mid_reward_up the rewards found on the way.
# The run's dolls and pets go out as gun ids and pet furniture ids (ExploreAction arrGunInfoId / arrPetInfoId; recorded
# live: setTeam's instance ids came back as "332", "40402", ...). Each pet steers the area: its furniture's extra_spine
# explore_tag 1001 cat, 1002 dog, 1003 bird, 1004 other leads to area 1 City, 2 Snowfield, 3 Forest, 4 Wasteland.
# Each area weighs 10, plus 20 per pet leading there (player report: one dog 10/30/10/10, a dog and a cat 30/30/10/10).
# Each of the week's advantaged pets on the team (Explore/getAdaptiveTeam) gives a MYSTERY_CHANCE of a Mysterious
# Location, which pays a third more of the main reward.
# The time type's mp/ammo/mre/part are the run's cost; the reward is items (recorded: an 8-hour Forest run paid
# "4003-421,4004-39,4002-39,6003-1,45-20,9-1,44-10": 421 = 316 x 4/3 of the area's loot, the rest found on the way).
# Main reward: LOOT_PER_HOUR of the area's loot item (4001-4004, by area) per hour of the time type, times the
# item's reward1_up. On the way, each affair has MID_CHANCE of one find from MID_FINDS, times mid_reward_up.
# APPROXIMATION: MYSTERY_CHANCE (player estimate), MID_CHANCE and MID_FINDS (one recorded run and player reports;
# the live list is server-side), and the affair pacing.
AFFAIR_EVERY = 1800
AREA_BASE, PET_PULL = 10, 20
MYSTERY_CHANCE, MYSTERY_BONUS = 0.2, 4 / 3
LOOT_PER_HOUR = 316 / 8
MID_CHANCE = 0.35
# (weight, package); "loot" is an hour of another area's loot, "food" one of the expedition items 6001-6009,
# "equip" a random 5-star equipment from the basic production pool (the recommended recipes' list); 41 is tokens
MID_FINDS = ((30, "loot"), (12, "food"), (10, {"item_ids": "45-20"}), (8, {"item_ids": "44-10"}), (4, {"item_ids": "9-1"}),
             (8, {"core": 3}), (6, {"item_ids": "3-1"}), (6, {"item_ids": "4-1"}), (6, {"item_ids": "506-10"}),
             (6, {"item_ids": "41-3"}), (2, "equip"))
ADAPTIVE_PETS = 3


def _pet_tags():
    """pet furniture id -> its explore_tag (1001-1004)."""
    from . import stc
    spines = {int(r["id"]): str(r.get("explore_tag") or "") for r in stc.table("extra_spine")}
    return {int(r["id"]): int(spines[int(r["bonus_id"])]) for r in stc.table("furniture")
            if int(r.get("bonus_id") or 0) in spines and spines[int(r["bonus_id"])].isdigit()}


def _instances(rows, key, ids):
    by_id = {str(r.get("id")): str(r.get(key)) for r in rows if isinstance(r, dict)}
    return [by_id.get(str(i), str(i)) for i in ids]


def _explore_items():
    from . import stc
    return {int(r["id"]): r for r in stc.table("explore_item")}


def _explore(state):
    return state.setdefault("_explore", {"guns": [], "pets": [], "time_type": 1, "is_auto": 0, "items": []})


def _time_types():
    from . import stc
    return {int(r["id"]): r for r in stc.table("explore_time_type")}


def explore_start(state, body, now=None, rng=None):
    import random as _random
    from . import stc
    rng = rng or _random
    now = int(now or time.time())
    explore_settle(state, now)
    e = _explore(state)
    tt = _time_types().get(int(e.get("time_type") or 1)) or _time_types()[1]
    from . import squads
    queue = [int(i) for i in e["items"] or [] if str(i).strip().lstrip("-").isdigit()]
    item_id = queue.pop(0) if queue else 0
    e["items"] = queue
    effect = _explore_items().get(item_id, {}) if item_id and squads._spend(state, str(item_id), 1) else {}
    guns = _instances(state.get("gun_with_user_info") or [], "gun_id", e["guns"])
    pets = _instances(furniture(state), "furniture_id", e["pets"])
    tags = _pet_tags()
    areas = [r["id"] for r in stc.table("explore_area")]
    up_area, _, up_weight = str(effect.get("area_id_up") or "").partition(":")
    weights = [AREA_BASE + PET_PULL * sum(1 for p in pets if tags.get(int(p) if p.isdigit() else 0) == 1000 + int(a))
               + (AREA_BASE * (int(up_weight or 1) - 1) if str(a) == up_area.strip() else 0) for a in areas]
    area = rng.choices(areas, weights=weights)[0]
    advantaged = {str(p) for p in explore_adaptive_team(state, {}, now)["pets"]}
    mystery = rng.random() < MYSTERY_CHANCE * sum(1 for p in pets if p in advantaged)
    dests = [r["id"] for r in stc.table("explore_destination") if r["area_id"] == area] or [0]
    affairs = [r["id"] for r in stc.table("explore_affair_server")]
    end = now + int(int(tt["duration"]) * float(effect.get("explore_time_down") or 1))
    ui = state["user_info"]
    for res in ("mp", "ammo", "mre", "part"):
        ui[res] = str(max(0, int(ui.get(res) or 0) - int(tt.get(res) or 0)))
    e["run"] = {"start_time": now, "end_time": end, "cancel_time": 0,
                "affairs": [{"affair_id": rng.choice(affairs), "affair_time": t} for t in range(now + AFFAIR_EVERY, end, AFFAIR_EVERY)],
                "gun_ids": guns, "pet_ids": pets, "area_id": area, "mysterious": int(mystery),
                "target_id": rng.choice(dests), "item_id": item_id if effect else 0, "draw_event_prize": 0,
                "time_type": int(tt["id"]), "reward_up": float(effect.get("reward1_up") or 1),
                "mid_reward_up": float(effect.get("mid_reward_up") or 1)}
    return dict(e["run"], next_time=_next_affair(e["run"], now))


def _next_affair(run, now):
    return min([a["affair_time"] for a in run["affairs"] if a["affair_time"] > now] + [run["end_time"]])


def explore_balance(state, body):
    explore_settle(state)
    e = _explore(state)
    run, now = e.get("run"), int(time.time())
    return {"ex_prize": {}, "list": [run] if run else [], "is_auto": int(e["is_auto"] or 0),
            "explore_time_type": int(e["time_type"] or 0), "pets": [int(p) for p in e["pets"]],
            "items_taken": [int(i) for i in e["items"]], "next_explore_time": int(run["end_time"]) if run else 0,
            "next_time": _next_affair(run, now) if run else 0,
            # the client sets these as they are (ExploreData$$DecodeExploreBalance), so they are the
            # player's real resources: sending 0 wiped the display
            **{res: int(state["user_info"].get(res) or 0) for res in ("mp", "ammo", "mre", "part")}}


def explore_get_event(state, body):
    run, now = _explore(state).get("run"), int(time.time())
    if not run:
        return {"event_list": [], "next_time": 0, "is_prize": 0}
    return {"event_list": [a for a in run["affairs"] if a["affair_time"] <= now], "next_time": _next_affair(run, now),
            "is_prize": int(now >= run["end_time"])}


def _explore_rewards(run, rng=None):
    """The run's completion reward (the area's loot) and its finds on the way, each a package."""
    import random as _random
    rng = rng or _random.Random(int(run.get("start_time") or 0))
    tt = _time_types().get(int(run.get("time_type") or 1)) or _time_types()[1]
    area = int(run.get("area_id") or 1)
    hours = int(tt["duration"]) / 3600
    main = LOOT_PER_HOUR * hours * float(run.get("reward_up") or 1) * (MYSTERY_BONUS if run.get("mysterious") else 1)
    finds = []
    mid = float(run.get("mid_reward_up") or 1)
    for _ in run.get("affairs") or []:
        if rng.random() >= MID_CHANCE:
            continue
        find = rng.choices([f for _, f in MID_FINDS], weights=[w for w, _ in MID_FINDS])[0]
        if find == "loot":
            other = rng.choice([a for a in (1, 2, 3, 4) if a != area])
            finds.append({"item_ids": f"{4000 + other}-{round(LOOT_PER_HOUR * mid)}"})
            continue
        if find == "food":
            find = {"item_ids": f"{rng.randint(6001, 6009)}-1"}
        elif find == "equip":
            from . import workshop
            pick = rng.choice(sorted(workshop._equip_pool().get(5) or [0]))
            if pick:
                finds.append({"equip_ids": f"{pick}-1"})
            continue
        pkg = {}
        for key, value in find.items():
            if key == "item_ids":
                iid, _, n = value.partition("-")
                pkg[key] = f"{iid}-{max(1, round(int(n) * mid))}"
            else:
                pkg[key] = max(1, round(value * mid))
        finds.append(pkg)
    return {"item_ids": f"{4000 + area}-{round(main)}"}, finds


def _explore_finds(run, rng=None):
    """The run's whole reward as one package."""
    main, finds = _explore_rewards(run, rng)
    items, extra = {}, {}
    for pkg in [main] + finds:
        for key, value in pkg.items():
            if key == "item_ids":
                iid, _, n = value.partition("-")
                items[int(iid)] = items.get(int(iid), 0) + int(n)
            elif key == "equip_ids":
                extra.setdefault(key, []).append(value)
            else:
                extra[key] = extra.get(key, 0) + value
    if "equip_ids" in extra:
        extra["equip_ids"] = ",".join(extra["equip_ids"])
    return dict(extra, item_ids=",".join(f"{i}-{n}" for i, n in items.items()))


# A finished run's area loot becomes a Loot Rack completion mail (MailType 24 exploreReturn) and each find on the
# way a midway mail (25 exploreAffair), as live sends them: the rack shows the two kinds in separate rows
# (ExploreRewardStorage$$RefreshRewardMail counts them apart), and Index/getExploreMail claims them. Its
# get_list is the claimed mail ids; with none, the client shows "reached the max amount of rewards"
# (DormExploreRoomController$$OnRequestExploreGetReward: RequestExploreGetReward.mailCount 0).
EXPLORE_MAILS = (24, 25)
EXPLORE_MAIL_END = 2100000000     # the live mails' end_time


# Auto mode (setTeam is_auto) starts the next run when one ends, while the Loot Rack has room and the time type's
# resources are there (ExploreData$$GetNextAutoStartTime). The rack (establish 803) holds parameter_1 "<final>,<midway>"
# reward mails (ExploreData$$GetFinalRewardSlot / GetMidwayRewardSlot). Runs chain from each one's end time, so
# they go on while the player is away; full completion slots stop them until the mails are claimed
# (ExploreRewardStorage$$get_isFull), and finds beyond the midway slots are lost.
# APPROXIMATION: one midway mail per find, and dropping finds when the midway slots are full.
LOOT_RACK = "803"


def _rack_slots(state, kind=EXPLORE_MAILS[0]):
    """Completion (24) or midway (25) slots; the client's default is 1 of each (ExploreRewardStorage$$RefreshMaxNum)."""
    row = next((r for r in state.get("outhouse_establish_info") or [] if str(r.get("establish_type")) == LOOT_RACK), {})
    parts = str(row.get("parameter_1") or "").split(",")
    n = parts[EXPLORE_MAILS.index(kind)].strip() if len(parts) > 1 else ""
    return int(n) if n.isdigit() else 1


def _rack_held(state, kind=EXPLORE_MAILS[0]):
    from . import quests
    return sum(1 for m in quests._mails(state) if int(m["type"]) == kind and not m["if_received"])


def _can_auto(state, e):
    if not int(e.get("is_auto") or 0) or not [g for g in e.get("guns") or [] if str(g) not in ("", "0")]:
        return False
    tt = _time_types().get(int(e.get("time_type") or 1)) or _time_types()[1]
    ui = state["user_info"]
    return (_rack_held(state) < _rack_slots(state)
            and all(int(ui.get(res) or 0) >= int(tt.get(res) or 0) for res in ("mp", "ammo", "mre", "part")))


def explore_settle(state, now=None):
    """Turn finished runs into Loot Rack mails, starting the next ones in auto mode."""
    from . import quests
    now = int(now or time.time())
    e = _explore(state)
    while (run := e.get("run")) and now >= run["end_time"]:
        main, finds = _explore_rewards(run)
        room = _rack_slots(state, EXPLORE_MAILS[1]) - _rack_held(state, EXPLORE_MAILS[1])
        for kind, title, pkg in [(EXPLORE_MAILS[0], "探索结束奖励", main)] + [(EXPLORE_MAILS[1], "探索途中奖励", f)
                                                                       for f in finds[:max(0, room)]]:
            quests.send_mail(state, kind, 0, title, pkg, now=run["end_time"])["end_time"] = EXPLORE_MAIL_END
        e.pop("run", None)
        quests.record(state, "explore")
        if _can_auto(state, e):
            explore_start(state, {}, now=run["end_time"])
        else:
            e["waiting"] = int(e.get("is_auto") or 0)


def explore_reward(state, body, now=None):
    from . import quests
    explore_settle(state, now)
    picked = [m for m in quests._mails(state) if int(m["type"]) in EXPLORE_MAILS and not m["if_received"]]
    pkg = quests._merge(quests.grant(state, m) for m in picked)
    e = _explore(state)
    if e.pop("waiting", 0) and not e.get("run") and _can_auto(state, e):
        explore_start(state, {}, now=now)
    return {"get_list": [int(m["id"]) for m in picked], "out": pkg}


# Exploration shop (stc explore_mall: cost "<item>-<n>" choices split by "|", prize_id, quota per
# clear_cycle: 1 a day, 2 a week, 3 a month, 4 a limit that grows each month, otherwise for good).
#   Explore/getMallList {} -> [{"id", "start_time", "end_time", "n_time", "num"}] (RequestExploreMallList: num is
#       what was bought this cycle; n_time the next reset, as live: the client drops a cycled good whose n_time
#       has passed, so a list without it showed none of them)
#   Explore/buy {"mall_id", "cost", "num"} -> {"status": 1} (ExploreMall$$RequestExchangeHandle: the
#       client then gives the good's package num times and takes the cost itself). "cost" names the
#       currency item when there is a choice. Counts are kept in explore_mall_with_user_info.
# Resets follow the server day (00:00 UTC-8): the Items tab's monthly goods restock on the 1st. Clear cycle 4
# (Fire-Control Components, increase "2,2,2025-03-18 00:00:00"): num counts every purchase since that date and the
# limit is base + per x months since then (ExploreMall$$GetBuyCountMax), so what isn't bought carries over.
# The live account's counts come from its archived Explore/getMallList, once.
MALL_DAY_OFFSET = 8 * 3600


def _server_time(now):
    return time.gmtime(now - MALL_DAY_OFFSET)


def _period(cycle, now):
    t = _server_time(now)
    return {1: time.strftime("%Y%j", t), 2: time.strftime("%Y%W", t), 3: time.strftime("%Y%m", t)}.get(int(cycle or 0), "")


def _next_reset(cycle, now):
    """The start of the next day / week / month, server time."""
    import calendar
    t = _server_time(now)
    day = calendar.timegm((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0)) + MALL_DAY_OFFSET
    cycle = int(cycle or 0)
    if cycle == 1:
        return day + 86400
    if cycle == 2:
        return day + (7 - t.tm_wday) * 86400
    if cycle in (3, 4):
        year, month = (t.tm_year + 1, 1) if t.tm_mon == 12 else (t.tm_year, t.tm_mon + 1)
        return calendar.timegm((year, month, 1, 0, 0, 0)) + MALL_DAY_OFFSET
    return 0


def _growing_limit(row, now):
    """Clear cycle 4: base + per month since the start date."""
    parts = str(row.get("increase") or "").split(",")
    if len(parts) < 3:
        return int(row.get("quota") or 0)
    start = time.strptime(parts[2].strip()[:10], "%Y-%m-%d")
    t = _server_time(now)
    months = max(0, (t.tm_year - start.tm_year) * 12 + t.tm_mon - start.tm_mon)
    return int(parts[0] or 0) + int(parts[1] or 0) * months


def _mall_limit(row, now):
    return _growing_limit(row, now) if int(row.get("clear_cycle") or 0) == 4 else int(row.get("quota") or 0)


def _mall_import(state, counts, now):
    saved = archived.read(str(state["user_info"].get("user_id", "")), "Explore/getMallList")
    cycles = {str(x["id"]): x.get("clear_cycle") for x in _explore_mall()}
    for r in saved if isinstance(saved, list) else []:
        if not isinstance(r, dict) or not int(r.get("num") or 0) or str(r.get("id")) not in cycles:
            continue
        cycle = cycles[str(r["id"])]
        # the cycle the archived count belongs to: the one before its next reset
        when = int(r.get("n_time") or 0) - 1 if int(r.get("n_time") or 0) else now
        period = _period(cycle, when)
        num, have = int(r["num"]), counts.get(str(r["id"]))
        if have is None or have[1] != period:
            if have is None or period > have[1]:
                counts[str(r["id"])] = [num, period]
        else:
            have[0] = max(have[0], num)


def _mall_bought(state, row, now):
    counts = state.setdefault("explore_mall_with_user_info", {})
    if not state.get("_explore_mall_imported"):
        state["_explore_mall_imported"] = True
        _mall_import(state, counts, now)
    num, period = counts.get(str(row["id"]), [0, ""])
    return num if period == _period(row.get("clear_cycle"), now) else 0


def _explore_mall():
    from . import stc
    return stc.table("explore_mall")


def explore_mall_list(state, body, now=None):
    from . import stc
    now = int(now or time.time())
    return [{"id": int(r["id"]), "start_time": 0, "end_time": 0, "n_time": _next_reset(r.get("clear_cycle"), now),
             "num": _mall_bought(state, r, now)} for r in stc.table("explore_mall")]


def explore_buy(state, body, now=None):
    from . import squads, stc
    body, now = body or {}, int(now or time.time())
    row = next((r for r in stc.table("explore_mall") if str(r["id"]) == str(body.get("mall_id"))), None)
    num = max(1, int(body.get("num") or 1))
    if row is None:
        return None
    bought = _mall_bought(state, row, now)
    limit = _mall_limit(row, now)
    if (limit or int(row.get("clear_cycle") or 0) == 4) and bought + num > limit:
        return {"status": 0}
    options = [p.split("-") for p in str(row.get("cost") or "").split("|") if "-" in p]
    item, per = next((o for o in options if o[0] == str(body.get("cost"))), options[0] if options else ("0", "0"))
    if int(squads._item(state, item)["number"]) < int(per) * num:
        return {"status": 0}
    squads._spend(state, item, int(per) * num)
    for _ in range(num):
        _prize(state, row.get("prize_id"))
    state["explore_mall_with_user_info"][str(row["id"])] = [bought + num, _period(row.get("clear_cycle"), now)]
    return {"status": 1}


# Explore/getAdaptiveTeam {} -> {"guns": ["<gun id>"], "pets": ["<pet furniture id>"], "start_time", "end_time"}
# (ExplorationAdaptiveConfig: the week's advantaged dolls and pets; times as "Y-m-d H:M:S"). The week's picks
# (Monday to Sunday): ADAPTIVE_GUNS dolls of each rarity from the standard production pool (player report:
# 2/3/3/2 of 5/4/3/2 stars) and ADAPTIVE_PETS pets.
ADAPTIVE_GUNS = {5: 2, 4: 3, 3: 3, 2: 2}


def explore_adaptive_team(state, body, now=None):
    import random
    from . import factory
    now = int(now or time.time())
    t = time.localtime(now)
    start = int(time.mktime((t.tm_year, t.tm_mon, t.tm_mday - t.tm_wday, 0, 0, 0, 0, 0, -1)))
    end = start + 7 * 86400 - 1
    pool, rng = factory.pool("standard"), random.Random(start)
    picks = []
    for stars, n in ADAPTIVE_GUNS.items():
        dolls = sorted(set(pool.get(stars) or []))
        picks += rng.sample(dolls, min(n, len(dolls)))
    fmt = "%Y-%m-%d %H:%M:%S"
    pets = sorted(_pet_tags())
    pet_picks = random.Random(start + 1).sample(pets, min(ADAPTIVE_PETS, len(pets)))
    return {"guns": [str(g) for g in sorted(picks)], "pets": sorted(pet_picks),
            "start_time": time.strftime(fmt, time.localtime(start)), "end_time": time.strftime(fmt, time.localtime(end))}


# Coalition exchange shop (Protocol Assimilation; stc sangvis_exchange_mall: cost_item, cost_num, prize_id, quota
# per item over its start_time..end_time window).
#   Sangvis/getMallList {} -> [{"id", "num"}] (RequestExchangeMallList: num bought; the client hides
#       items outside their window)
#   Sangvis/exchangeMall {"mall_id", "num"} -> {"status": 1, "prize": [entry, ...]}
#       (RequestSangvisExchangeMall$$SuccessJsonHandleData). "prize" is a list: an entry holding "sangvis_info"
#       (one unit record) goes to GameData$$GetNewSangvis, any other entry is a Package. The client then takes
#       the cost and raises the good's bought count itself (SangvisExchangeShopItemController
#       $$RequestSangvisExchangeMall). A single package object made the loop throw after the purchase was
#       saved: no "sold out" until a relogin, and the next buy hit the "server busy" relogin box.
#       Counts are kept in sangvis_mall_with_user_info.

def sangvis_mall_list(state, body):
    from . import stc
    bought = state.get("sangvis_mall_with_user_info") or {}
    return [{"id": int(r["id"]), "num": int(bought.get(str(r["id"])) or 0)} for r in stc.table("sangvis_exchange_mall")]


def sangvis_mall_buy(state, body, now=None):
    from . import mods, quests, squads, stc
    body = body or {}
    row = next((r for r in stc.table("sangvis_exchange_mall") if str(r["id"]) == str(body.get("mall_id"))), None)
    num = max(1, int(body.get("num") or 1))
    stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(now or time.time())))
    if row is None or not (str(row["start_time"]) <= stamp <= str(row["end_time"] or "9999")):
        return None
    bought = state.setdefault("sangvis_mall_with_user_info", {})
    have = int(bought.get(str(row["id"])) or 0)
    cost = int(row["cost_num"]) * num
    if int(row.get("quota") or 0) and have + num > int(row["quota"]) or int(squads._item(state, row["cost_item"])["number"]) < cost:
        return {"status": 0}
    squads._spend(state, row["cost_item"], cost)
    bought[str(row["id"])] = have + num
    prize = quests.prizes().get(int(row["prize_id"]), {})
    entries = []
    for _ in range(num):
        package = {k: v for k, v in quests.grant(state, quests._reward(prize)).items() if k != "sangvis"}
        if package:
            entries.append(package)
        for part in str(prize.get("sangvis") or "").split(","):
            sid, _, n = part.partition("-")
            if sid.strip().isdigit() and int(sid) in mods._sangvis():
                entries += [{"sangvis_info": mods.new_sangvis_record(state, int(sid), state["user_info"].get("user_id", ""))}
                            for _ in range(int(n or 1))]
    return {"status": 1, "prize": entries}


def explore_cancel(state, body):
    _explore(state).pop("run", None)
    return "1"


def explore_set_team(state, body):
    body = body or {}
    e = _explore(state)
    e.update({"guns": list(body.get("guns") or []), "pets": list(body.get("pets") or []),
              "time_type": int(body.get("time_type") or 0), "is_auto": int(body.get("is_auto") or 0)})
    return "1"


def explore_set_item(state, body):
    _explore(state)["items"] = list((body or {}).get("item_list") or [])
    return "1"


# --- dorm batteries
#
# Dorm/get_build_coin {"v_user_id", "dorm_id"} -> {"build_coin", "build_coin_max", "remain_coin"}
# (RequestGetBuildCoin; batteries are item 506, UserInfo$$get_buildCoin). v_user_id is a friend's
# when visiting (friends.collect_battery), else the player's own condenser: it charges all the time and
# is emptied by a collection, which only works inside the hours of game_config
# dorm_build_coin_range_time ("10,11,12,13|18,...,24", server time UTC-8). Friend/dormInfo and
# Index/home show it as current_build_coin / build_coin_flag (live: both "800").
# APPROXIMATION: it charges each dorm's 10 + comfort/1000 every 12 hours and holds CONDENSER_PER_DORM
# per dorm (user_info maxdorm); the live rates are server-side.
BATTERY_ITEM = "506"
CONDENSER_PER_DORM = 80
SERVER_TZ = -8 * 3600


def _battery_window(now):
    from . import stc
    cfg = next((r["parameter_value"] for r in stc.catch("game_config_info")
                if r["parameter_name"] == "dorm_build_coin_range_time"), "10,11,12,13|18,19,20,21,22,23,24")
    t = time.gmtime(now + SERVER_TZ)
    for i, hours in enumerate(str(cfg).split("|")):
        if t.tm_hour in {int(h) % 24 for h in hours.split(",") if h.strip().isdigit()}:
            return f"{time.strftime('%Y-%m-%d', t)}#{i}"
    return None


def _dorms(state):
    return max(1, int((state.get("user_info") or {}).get("maxdorm") or 1))


def condenser(state, now=None):
    """Batteries waiting in the condenser, charged up to now."""
    now = int(now or time.time())
    c = state.get("_condenser")
    if c is None:
        saved = archived.read(state["user_info"].get("user_id", ""), "Friend/dormInfo") or {}
        c = state["_condenser"] = {"stored": float(saved.get("current_build_coin") or 0), "time": now}
    scores = state.get("dorm_score_info") or {}
    per_12h = sum(10 + int((scores.get(str(d)) or {}).get("score") or 0) // 1000 for d in range(1, _dorms(state) + 1))
    cap = CONDENSER_PER_DORM * _dorms(state)
    c["stored"] = min(cap, max(float(c["stored"]), float(c["stored"]) + per_12h * (now - int(c["time"])) / 43200))
    c["time"] = now
    return int(c["stored"])


def battery_flag(state, now=None):
    """build_coin_flag: what a collection would give now (0 outside the collection hours)."""
    now = int(now or time.time())
    stored = condenser(state, now)
    return stored if _battery_window(now) is not None else 0


def _add_batteries(state, amount):
    from . import squads
    row = squads._item(state, BATTERY_ITEM)
    row["number"] = str(int(row["number"]) + amount)


def get_build_coin(state, body, now=None):
    from . import friends
    now = int(now or time.time())
    body = body or {}
    me = str(state["user_info"].get("user_id", ""))
    visited = str(body.get("v_user_id") or "")
    if visited not in ("", "0", me):
        amount = friends.collect_battery(state, visited, now)
        _add_batteries(state, amount)
        return {"build_coin": amount, "build_coin_max": 0, "remain_coin": 0}
    amount = battery_flag(state, now)
    if amount:
        state["_condenser"]["stored"] = 0.0
        _add_batteries(state, amount)
    return {"build_coin": amount, "build_coin_max": 0, "remain_coin": 0}


# --- base facilities (Outhouse)
#
# outhouse_establish_info rows carry a facility's current level row of catchdata
# furniture_establish_info (establish_id, establish_type, establish_lv, furniture ids, upgrade_coin,
# upgrade_time, upgrade_condition, parameter_1..3). Outhouse/establish_upgrade {"establish_id"} ("1")
# starts the upgrade to the same type's next level, paying upgrade_coin batteries;
# Outhouse/establish_upgrade_finish {"establish_id", "is_quick"} -> {"cost_gem"} applies it.
LEVEL_FIELDS = ("establish_id", "establish_lv", "furniture_id", "update_furniture_id", "upgrade_coin", "upgrade_time",
                "upgrade_condition", "parameter_1", "parameter_2", "parameter_3")


def _facility(state, eid):
    return next((r for r in state.get("outhouse_establish_info") or []
                 if str(r["establish_id"]) == str(eid) or str(r.get("upgrade_establish_id")) == str(eid)), None)


def _next_level(row):
    from . import stc
    return next((r for r in stc.catch("furniture_establish_info") if r["establish_type"] == str(row["establish_type"])
                 and int(r["establish_lv"]) == int(row["establish_lv"]) + 1), None)


def establish_upgrade(state, body):
    row = _facility(state, (body or {}).get("establish_id"))
    nxt = _next_level(row) if row is not None else None
    if nxt is None:
        return None
    items = state.setdefault("item_with_user_info", [])
    bat = next((i for i in items if str(i["item_id"]) == BATTERY_ITEM), None)
    if bat is not None:
        bat["number"] = str(max(0, int(bat["number"]) - int(row.get("upgrade_coin") or 0)))
    row["upgrade_establish_id"], row["upgrade_starttime"] = nxt["establish_id"], str(int(time.time()))
    return "1"


def establish_upgrade_finish(state, body):
    row = _facility(state, (body or {}).get("establish_id"))
    if row is None or str(row.get("upgrade_establish_id") or "0") == "0":
        return None
    from . import stc
    nxt = next(r for r in stc.catch("furniture_establish_info") if r["establish_id"] == str(row["upgrade_establish_id"]))
    row.update({k: nxt[k] for k in LEVEL_FIELDS})
    row["upgrade_establish_id"], row["upgrade_starttime"] = "0", "0"
    return {"cost_gem": 0}


# Data Room combat reports (establish 201: parameter_1 "<gift item>:<batteries each>"; the batch
# time is establish 205 parameter_1 seconds, the most per batch establish 206 parameter_1):
#   Outhouse/establish_build {"establish_type": 201, "num", "payway", "special_report", "is_quick",
#       "cost_id"} -> {} (RequestEstablishBuildStart). Each report costs its batteries and its exp from
#       the free exp pool (item 507): the gift item's exp, or for a special (HOC) report, item 46,
#       game_config squad_spreport_battery / squad_spreport_exp.
#   Outhouse/establish_build_finish {"establish_type", "payway", "is_quick", "cost_id"} -> the package
#       ({"gift": "<item>-<n>"} or {"item_ids": "46-<n>"}, read by Package$$GetPackage).
# A quick start (is_quick) answers the package at once. SIMPLIFIED: the quick-finish cost (cost_id,
# counted by the client) is not taken.
REPORT_ROOM, REPORT_TIME, REPORT_MAX = "201", "205", "206"
FREE_EXP, SPECIAL_REPORT = "507", "46"


def _report_cost(state, special):
    from . import squads
    if special:
        cfg = squads._config()
        return SPECIAL_REPORT, int(cfg.get("squad_spreport_battery") or 0), int(cfg.get("squad_spreport_exp") or 0)
    from . import stc
    gift, _, bat = str(squads._establish(state, REPORT_ROOM).get("parameter_1") or "200001:3").partition(":")
    exp = next((int(r["exp"]) for r in stc.table("gift_item") if str(r["id"]) == gift), 0)
    return gift, int(bat or 0), exp


def _report_package(state, row):
    from . import quests
    n, special = int(row.get("build_num") or 0), row.get("build_tmp_data") == "special"
    item = _report_cost(state, special)[0]
    row.update(build_starttime="0", build_num="0", build_tmp_data="", build_get_time=str(int(time.time())))
    if n <= 0:
        return {}
    return quests.grant(state, {"item_ids" if special else "gift": f"{item}-{n}"})


def _report_pending(row):
    """A batch is waiting only if it hasn't been collected since it started: live leaves build_num
    set after collecting (imported saves: build_num 481 with build_get_time after build_starttime)."""
    return int(row.get("build_num") or 0) > 0 and int(row.get("build_get_time") or 0) < int(row.get("build_starttime") or 0)


def establish_build(state, body):
    from . import squads
    body = body or {}
    row = next((r for r in state.get("outhouse_establish_info") or [] if str(r["establish_type"]) == REPORT_ROOM), None)
    if row is None or _report_pending(row):
        return None
    special = bool(int(body.get("special_report") or 0))
    _, bat, exp = _report_cost(state, special)
    top = int(squads._establish(state, REPORT_MAX).get("parameter_1") or 0)
    have_bat, have_exp = int(squads._item(state, BATTERY_ITEM)["number"]), int(squads._item(state, FREE_EXP)["number"])
    n = min(int(body.get("num") or 0), top or 1 << 30,
            have_bat // bat if bat else 1 << 30, have_exp // exp if exp else 1 << 30)
    if n <= 0:
        return None
    squads._spend(state, BATTERY_ITEM, n * bat)
    squads._spend(state, FREE_EXP, n * exp)
    row.update(build_starttime=str(int(time.time())), build_num=str(n), build_tmp_data="special" if special else "")
    return _report_package(state, row) if body.get("is_quick") else {}


# Pet adoption (DormPetAdoptionController): each pet facility, establish types PET_TYPES, offers one pet. Its
# level's parameter_1 is "furniture,weight,batteries,gems|..." (furniture 0: nobody this time) and parameter_2
# the matching pet names. The offers go out as Friend/dormInfo establish_build_result
# [{"furniture_id", "build_coin", "gem", "establish_type", "pet_name", "build_tmp_data"}] (DormData$$ReadUserPet;
# live sent the same), picked again every PET_REFRESH, or PET_AFTER_ADOPT after one is adopted.
# Outhouse/establish_build_finish {"establish_type", "payway": "build_coin" | "gem"} adopts it and answers
# {"furniture": [{"dorm_with_user_id", "furniture_id"}]} (RequestEstablishBuildEnd, which takes the price itself).
PET_TYPES = ("102", "103", "104", "105")
PET_REFRESH, PET_AFTER_ADOPT = 3 * 86400, 86400


def _pet_roll(state, kind, rng):
    from . import squads
    row = squads._establish(state, kind)
    parts = [p.split(",") for p in str(row.get("parameter_1") or "").split("|") if p.count(",") >= 3]
    names = str(row.get("parameter_2") or "").split(",")
    if not parts:
        return None
    i = rng.choices(range(len(parts)), weights=[max(0, int(p[1] or 0)) for p in parts] if any(int(p[1] or 0) for p in parts) else None)[0]
    fid, _, coin, gem = parts[i][:4]
    if not fid.strip() or int(fid) == 0:
        return None
    name = names[i] if i < len(names) else "0"
    return {"furniture_id": fid, "build_coin": coin, "gem": gem, "establish_type": kind, "pet_name": name,
            "build_tmp_data": [fid, coin, gem, kind, name]}


def pet_offers(state, now=None, rng=random):
    now = int(now or time.time())
    pets = state.get("_pets")
    if pets is None:
        saved = archived.read(state["user_info"].get("user_id", ""), "Friend/dormInfo") or {}
        live = {str(o.get("establish_type")): o for o in saved.get("establish_build_result") or [] if isinstance(o, dict)}
        pets = state["_pets"] = {k: {"offer": live[k], "next": now + PET_REFRESH} for k in live}
    for kind in PET_TYPES:
        slot = pets.get(kind)
        if slot is None or now >= int(slot["next"]):
            pets[kind] = {"offer": _pet_roll(state, kind, rng), "next": now + PET_REFRESH}
    return [pets[k]["offer"] for k in PET_TYPES if pets[k]["offer"]]


def adopt_pet(state, body, now=None):
    from . import squads
    now = int(now or time.time())
    kind = str((body or {}).get("establish_type") or "")
    pet_offers(state, now)
    slot = state["_pets"].get(kind) or {}
    offer = slot.get("offer")
    if not offer:
        return None
    by_gem = str((body or {}).get("payway")) == "gem"
    price = int(offer["gem"] if by_gem else offer["build_coin"])
    if by_gem:
        if int(state["user_info"].get("gem") or 0) < price:
            return None
        state["user_info"]["gem"] = str(int(state["user_info"]["gem"]) - price)
    else:
        if int(squads._item(state, BATTERY_ITEM)["number"]) < price:
            return None
        squads._spend(state, BATTERY_ITEM, price)
    pieces = furniture(state)
    rec = {"id": str(max((int(f["id"]) for f in pieces), default=0) + 1), "dorm": "0",
           "furniture_id": str(offer["furniture_id"]), "x": "0", "y": "0"}
    pieces.append(rec)
    state["_pets"][kind] = {"offer": None, "next": now + PET_AFTER_ADOPT}
    return {"furniture": [{"dorm_with_user_id": int(rec["id"]), "furniture_id": int(rec["furniture_id"])}]}


def establish_build_finish(state, body, now=None):
    from . import squads
    if str((body or {}).get("establish_type") or "") in PET_TYPES:
        return adopt_pet(state, body, now)
    row = next((r for r in state.get("outhouse_establish_info") or [] if str(r["establish_type"]) == REPORT_ROOM), None)
    if row is None or not _report_pending(row):
        return None
    wait = int(squads._establish(state, REPORT_TIME).get("parameter_1") or 0)
    if not (body or {}).get("is_quick") and int(now or time.time()) < int(row["build_starttime"]) + wait:
        return None
    return _report_package(state, row)


# Dorm/kalinaFavorUpLevel {} -> {"level"} (RequestKalinaUpLevel sets Kalina's level from it): one
# level up once her favor reaches the next kalina_favor_info row's min_favor.

def kalina_level_up(state, body):
    from . import stc
    k = state.setdefault("kalina_with_user_info", {"level": "1", "favor": "0"})
    need = {int(r["level"]): int(r["min_favor"]) for r in stc.catch("kalina_favor_info")}
    level = int(k.get("level") or 1)
    if level + 1 in need and int(k.get("favor") or 0) >= need[level + 1]:
        level += 1
        k["level"], k["last_favor"] = str(level), str(k.get("favor") or 0)
    return {"level": level}


# Cafe collection (catchdata coffeeshop_comic / coffeeshop_pv: cost "<item>-<n>;...", prize_id).
#   Dorm/coffeeshop_unlock_list {} -> {"comic": [ids], "pv": [ids]} (RequestGetUnlockedComicPVList)
#   Dorm/coffeeshop_unlock {"id", "type"} -> {"prize": <package>} (RequestUnlockComicPV takes the cost
#       itself). Type 1 is a comic, otherwise a PV. Kept in coffeeshop_with_user_info.
CAFE_TABLES = {"comic": "coffeeshop_comic", "pv": "coffeeshop_pv"}


def _cafe(state):
    """Owned comics and PVs; the first time, what the live account had bought (its archived
    Dorm/coffeeshop_unlock_list replies, type 1 the comic stand and 2 the projector)."""
    if "coffeeshop_with_user_info" not in state:
        owned = {"comic": [], "pv": []}
        uid = str(state["user_info"].get("user_id", ""))
        for key in ("1", "2"):
            saved = archived.read(uid, "Dorm/coffeeshop_unlock_list", key) or {}
            for kind in CAFE_TABLES:
                owned[kind] += [int(i) for i in saved.get(kind) or [] if str(i).isdigit() and int(i) not in owned[kind]]
        state["coffeeshop_with_user_info"] = owned
    return state["coffeeshop_with_user_info"]


def cafe_list(state, body):
    owned = _cafe(state)
    return {k: [int(i) for i in owned.get(k) or []] for k in CAFE_TABLES}


def cafe_unlock(state, body):
    from . import squads, stc
    body = body or {}
    kind = "comic" if int(body.get("type") or 0) == 1 else "pv"
    row = next((r for r in stc.catch(CAFE_TABLES[kind]) if str(r["id"]) == str(body.get("id"))), None)
    owned = _cafe(state).setdefault(kind, [])
    if row is None or int(row["id"]) in owned:
        return None
    for part in str(row.get("cost") or "").split(";"):
        item, _, n = part.partition("-")
        if item.strip().isdigit() and n.strip().isdigit():
            squads._spend(state, item.strip(), int(n))
    owned.append(int(row["id"]))
    return {"prize": _prize(state, row.get("prize_id"))}


# Tutorial manuals and small dorm settings:
#   Manual/ReadList {} -> {"tutorial_guide_id": [...], "tutorial_manual_id": [...]}
#       (RequestUnionGetManualReadList); seeded from the recorded reply, then kept in manual_read_info
#   Manual/Read {"type": "guide" | "manual", "read_id"} -> {} (RequestUnionSetManualRead reads no keys)
#   Manual/like {"manual_id", "like"} "1"; Manual/counter {} -> {"manual_counter": [{"manual_id",
#       "like"}]} (RequestManualCounter): offline only the player's own likes count
#   Dorm/skinRead {"skin_group_id", "skin_id"} "1": the skin is no longer marked new
#   Dorm/set_notice {"is_view", "notice", "is_show_commander", "is_use_commander",
#       "is_sangvis_show_gun"} "1": kept in dorm_notice_info, sent back by Friend/dormInfo
#   Dorm/spare_exchange {"dorm_spare_id", "dorm_id"} "1": the two rooms swap furniture
#       (RequestSpareRoomSwap, DormData$$UpdateFurnitureDorm)
MANUAL_KEYS = {"guide": "tutorial_guide_id", "manual": "tutorial_manual_id"}


def _manual_read(state):
    if "manual_read_info" not in state:
        from . import config
        try:
            seed = json.loads((config.RESPONSES_DIR / "Manual" / "ReadList.json").read_text("utf-8"))
        except (OSError, ValueError):
            seed = {}
        state["manual_read_info"] = {k: [str(i) for i in seed.get(k) or []] for k in MANUAL_KEYS.values()}
    return state["manual_read_info"]


def manual_read_list(state, body):
    return {k: list(v) for k, v in _manual_read(state).items()}


def manual_read(state, body):
    body = body or {}
    key = MANUAL_KEYS.get(str(body.get("type") or ""))
    if key is None:
        return None
    ids = _manual_read(state).setdefault(key, [])
    if str(body.get("read_id")) not in ids:
        ids.append(str(body.get("read_id")))
    return {}


def manual_like(state, body):
    body = body or {}
    state.setdefault("manual_like_info", {})[str(body.get("manual_id") or 0)] = int(body.get("like") or 0)
    return "1"


def manual_counter(state, body):
    return {"manual_counter": [{"manual_id": int(k), "like": v} for k, v in sorted(
        (state.get("manual_like_info") or {}).items(), key=lambda kv: int(kv[0]))]}


# Daily explore routes (stc daily_map_route):
#   test/dailyMapRouteList {} -> {"map_route_list": {"<map_id>": {"map_id", "is_check", "route", "route2"}}}
#       (DailyExploreData$$RefreshMapRouteData reads every field unguarded)
#   test/mapRouteSetCheck {"map_id", "is_check"} -> {}
def daily_route_list(state, body):
    from . import stc
    checks = state.get("_map_route_check") or {}
    return {"map_route_list": {str(r["map_id"]): {"map_id": int(r["map_id"]), "is_check": int(checks.get(str(r["map_id"])) or 0),
                                                  "route": str(r["route"] or ""), "route2": ""}
                               for r in stc.table("daily_map_route")}}


def daily_route_check(state, body):
    body = body or {}
    state.setdefault("_map_route_check", {})[str(body.get("map_id") or 0)] = int(body.get("is_check") or 0)
    return {}


# Doll index likes:
#   Gun/like {"gun_id", "like" (bool)} "1" (RequestLikeGun)
#   Gun/likeList {} -> {"rank": [{"gun_id", "num"}], "user_like": [], "gun_like": [gun ids],
#       "gun_tag_like": [{"gun_id", "tag_ids"}]} (RequestGunLikeList): offline only the player's own likes count
#   Gun/tagLike {"gun_id", "tag_id", "like"} "1": no client code sends it, so this body is a guess
def _gun_likes(state):
    return state.setdefault("_gun_like", {"guns": [], "tags": {}})


def _toggle(ids, value, on):
    if on and value not in ids:
        ids.append(value)
    elif not on and value in ids:
        ids.remove(value)


def gun_like(state, body):
    body = body or {}
    gun_id = int(body.get("gun_id") or 0)
    if not gun_id:
        return None
    _toggle(_gun_likes(state)["guns"], gun_id, body.get("like") in (True, 1, "1", "true"))
    return "1"


def gun_tag_like(state, body):
    body = body or {}
    gun_id, tag_id = int(body.get("gun_id") or 0), int(body.get("tag_id") or 0)
    if not gun_id or not tag_id:
        return None
    _toggle(_gun_likes(state)["tags"].setdefault(str(gun_id), []), tag_id, body.get("like", True) in (True, 1, "1", "true"))
    return "1"


def gun_like_list(state, body):
    likes = _gun_likes(state)
    return {"rank": [{"gun_id": g, "num": 1} for g in likes["guns"]], "user_like": [], "gun_like": list(likes["guns"]),
            "gun_tag_like": [{"gun_id": int(g), "tag_ids": list(t)} for g, t in likes["tags"].items() if t]}


def gun_collect(state, body):
    """Index/getGunCollect, which no client code sends: the dolls marked by Gun/setCollect."""
    return [g["id"] for g in state.get("gun_with_user_info") or [] if str(g.get("is_collect")) == "1"]


def skin_read(state, body):
    skin = (state.get("skin_with_user_info") or {}).get(str((body or {}).get("skin_id") or ""))
    if skin is not None:
        skin["is_read"] = "1"
    return "1"


NOTICE_KEYS = ("is_view", "notice", "is_show_commander", "is_use_commander", "is_sangvis_show_gun")


def dorm_set_notice(state, body):
    body = body or {}
    state["dorm_notice_info"] = {k: str(body[k]) for k in NOTICE_KEYS if k in body}
    return "1"


def dorm_info(state, recorded=None, now=None):
    """Friend/dormInfo (DormConfigData$$DecodeFromJson): the dorm settings come from the account's archived live
    reply (main dorm info.dorm_id, notice, is_show_commander, is_use_commander) with later changes on top; the
    furniture is the account's own and the batteries its condenser. Offline there are no visitors."""
    uid = str(state["user_info"].get("user_id", ""))
    base = archived.read(uid, "Friend/dormInfo") or recorded or {
        "info": {"praise_num": 0, "visit_num": 0, "user_id": uid, "dorm_id": "1"},
        "establish_build_result": [], "reset_build_coin_data": [],
        "notice": {"is_view_notice": "1", "notice": ""},
        "is_show_commander": "1", "is_use_commander": "0", "is_sangvis_show_gun": "1"}
    reply = dict(base, info=dict(base.get("info") or {}), in_mydorm_list=[], my_visit_list=[])
    if state.get("_friend_dorm"):
        reply["info"]["dorm_id"] = str(state["_friend_dorm"])
    reply["establish_build_result"] = pet_offers(state, now)
    reply["build_coin_flag"] = battery_flag(state, now)
    reply["current_build_coin"] = str(condenser(state, now))
    reply["furniture_with_user_info"] = furniture(state)
    return dorm_notice(reply, state)


def dorm_notice(reply, state):
    """Overlay the saved dorm settings on a Friend/dormInfo reply."""
    saved = state.get("dorm_notice_info") or {}
    if "is_view" in saved or "notice" in saved:
        reply["notice"] = {"is_view_notice": saved.get("is_view", "1"), "notice": saved.get("notice", "")}
    for k in ("is_show_commander", "is_use_commander", "is_sangvis_show_gun"):
        if k in saved:
            reply[k] = saved[k]
    return reply


def spare_exchange(state, body):
    body = body or {}
    a, b = str(body.get("dorm_spare_id") or ""), str(body.get("dorm_id") or "")
    if not a or not b:
        return None
    for f in furniture(state):
        if f["dorm"] in (a, b):
            f["dorm"] = b if f["dorm"] == a else a
    return "1"


# Dorm/squadGuideFinish {"id"} "1" (RequestGuideFinishPrize shows game_config squad_new_guide
#   "<guide id>;<item>:<n>,..." as the reward): paid once, kept in squad_guide_finished.
# Dorm/Medal {"uid"} -> {"list": medal_with_user_info} (RequestUpdateMedal); nobody else offline.
# Index/setFunctionControl {} -> {"function_unlock": user_record.function_unlock}
#   (RequestMissionCountFunctionSwitch re-reads the switches).

def squad_guide_finish(state, body):
    from . import quests
    gid, _, reward = str(quests._config().get("squad_new_guide") or "").partition(";")
    done = state.setdefault("squad_guide_finished", [])
    if str((body or {}).get("id")) != gid or gid in done:
        return "1"
    done.append(gid)
    items = ",".join(p.replace(":", "-") for p in reward.split(",") if ":" in p)
    if items:
        quests.grant(state, {"item_ids": items})
    return "1"


def medal_list(state, body):
    mine = str((body or {}).get("uid") or state["user_info"].get("user_id")) == str(state["user_info"].get("user_id"))
    return {"list": list(state.get("medal_with_user_info") or []) if mine else []}


def function_control(state, body):
    return {"function_unlock": str(state.get("user_record", {}).get("function_unlock") or "")}


# Friends. Offline nobody else exists, so calls aimed at another player (visit, praise, messages,
# applications) find no one; the player's own card is the save's user_friend_info, which is the
# shape UserCard reads.
#   Friend/usercard {"f_userid"} -> user_friend_info for the player's own id, else an error
#   Friend/setCard {"headpic_id", "card_id", "homebg_id", "frame_id"} "1"; Friend/setIntro {"intro"} "1"
#   Friend/setMedal {"medal_ids_arr"} "1": the card shows those medals ({"id", "level", "num"}, level
#       and num from medal_with_user_info); Friend/setMedalIsVisible {"is_visible"} "1"
#   Friend/cosmeticBuy {"id", "type"} -> {} (RequestBuyFriendCosmetic: the client takes the price and
#       adds the cosmetic's item): type 1 pays stc friend_cosmetic item_ids (friend points, item 508),
#       otherwise gem and mp/ammo/mre/part.
# The friend point shops (Friend/mall, mallByType9) stay empty: their stock is server data.
CARD_FIELDS = ("headpic_id", "card_id", "homebg_id", "frame_id")


def _card(state):
    return state.setdefault("user_friend_info", {"f_userid": state["user_info"].get("user_id", ""),
                                                 "name": state["user_info"].get("name", ""), "intro": "",
                                                 "medal": [], "medal_is_visible": "1"})


def user_card(state, body):
    if str((body or {}).get("f_userid")) != str(state["user_info"].get("user_id")):
        return None
    card = dict(_card(state))
    card["name"], card["lv"] = state["user_info"].get("name", ""), str(state["user_info"].get("lv") or card.get("lv") or 1)
    card["medal_with_user"] = state.get("medal_with_user_info") or card.get("medal_with_user") or []
    return card


def set_card(state, body):
    body = body or {}
    _card(state).update({k: int(body[k]) for k in CARD_FIELDS if str(body.get(k, "")).lstrip("-").isdigit()})
    return "1"


def set_intro(state, body):
    _card(state)["intro"] = str((body or {}).get("intro") or "")
    return "1"


def set_medal(state, body):
    owned = {str(m["medal_id"]): m for m in state.get("medal_with_user_info") or []}
    ids = (body or {}).get("medal_ids_arr") or []
    if isinstance(ids, str):
        ids = [i for i in ids.split(",") if i.strip()]
    _card(state)["medal"] = [{"id": str(i), "level": str(owned[str(i)]["num"]), "num": str(owned[str(i)]["num"])}
                             for i in ids if str(i) in owned]
    return "1"


def set_medal_visible(state, body):
    _card(state)["medal_is_visible"] = str((body or {}).get("is_visible") or 0)
    return "1"


def buy_cosmetic(state, body):
    from . import squads, stc
    from .factory import _add
    body = body or {}
    row = next((r for r in stc.table("friend_cosmetic") if str(r["id"]) == str(body.get("id"))), None)
    if row is None or str(row["item_id"]) in {str(i["item_id"]) for i in state.get("item_with_user_info") or []
                                               if int(i["number"])}:
        return None
    ui = state["user_info"]
    if int(body.get("type") or 0) == 1:
        costs = [p.split("-") for p in str(row["item_ids"] or "").split(",") if "-" in p]
        if not costs or any(int(squads._item(state, i)["number"]) < int(n) for i, n in costs):
            return None
        for i, n in costs:
            squads._spend(state, i, int(n))
    else:
        if int(ui.get("gem") or 0) < int(row["gem"] or 0):
            return None
        for k in ("gem", "mp", "ammo", "mre", "part"):
            _add(ui, k, -min(int(ui.get(k) or 0), int(row[k] or 0)))
    item = squads._item(state, row["item_id"])
    item["number"] = str(int(item["number"]) + 1)
    return {}


# --- target training favourites (save: targettrain_collect_user_info [{"user_id", "order_id",
# "enemy_team_id", "fight_type", "fight_coef", "fight_environment_group", "is_lock"}])
# Targettrain/addCollect {"enemy_team_id", "fight_type", "fight_coef", "fight_environment_group",
# "order_id"}, delCollect / lockCollect {the same minus order_id}: each handler checks for "1".

def _target_key(row):
    return (str(row.get("enemy_team_id")), str(row.get("fight_type") or 0), str(row.get("fight_coef") or ""),
            str(row.get("fight_environment_group") or ""))


def target_practice_list(state, chosen):
    """The launcher's own list of enemy teams (settings "target_practice") as the saved list's rows; None when unset.
    A team with a stand-in enemy (no stats of its own, maxlife 0) is left out: the client's power figure for it
    overflows and the screen hangs (MissionSelectionDroneTrainSettingController.GetEnemyPower)."""
    from . import missions
    types = missions._enemy_types()

    def fightable(team):
        return all(int((types.get(t) or {}).get("maxlife") or 0) for t in missions._team_members().get(team, []))
    ids = [int(x) for x in str(chosen or "").split(",") if x.isdigit() and int(x) in missions._enemy_teams()]
    skipped = [t for t in ids if not fightable(t)]
    if skipped:
        log.warning("target practice: teams %s use an enemy with no stats and are left out", skipped)
    ids = [t for t in ids if t not in skipped]
    if not ids:
        return None
    uid = state["user_info"].get("user_id", "")
    return [{"user_id": uid, "order_id": n, "enemy_team_id": t, "fight_type": 0, "fight_coef": "", "fight_environment_group": "",
             "is_lock": 0} for n, t in enumerate(ids, 1)]


def target_add(state, body):
    body = body or {}
    rows = state.setdefault("targettrain_collect_user_info", [])
    if not body.get("enemy_team_id") or any(_target_key(r) == _target_key(body) for r in rows):
        return "1"
    rows.append({"user_id": state["user_info"].get("user_id", ""), "order_id": int(body.get("order_id") or len(rows) + 1),
                 "enemy_team_id": int(body["enemy_team_id"]), "fight_type": int(body.get("fight_type") or 0),
                 "fight_coef": str(body.get("fight_coef") or ""),
                 "fight_environment_group": str(body.get("fight_environment_group") or ""), "is_lock": 0})
    return "1"


def target_del(state, body):
    state["targettrain_collect_user_info"] = [r for r in state.get("targettrain_collect_user_info") or []
                                              if _target_key(r) != _target_key(body or {})]
    return "1"


def target_lock(state, body):
    for r in state.get("targettrain_collect_user_info") or []:
        if _target_key(r) == _target_key(body or {}):
            r["is_lock"] = 0 if r.get("is_lock") else 1
    return "1"


SHARE_PRIZE = 10000      # prize "Weekly First Share" (30 gems)


def dorm_share(state, body, now=None):
    """Dorm/share (no body) -> {"prize_id"} (RequestShareReward reads it unguarded and shows that
    prize). share_with_user_info.last_time is when the next reward can be had: the client asks only once
    the time is past it (Data$$CanGatSharePrize; live: 1794816000, a Monday 00:00 UTC-8). A reward moves it to
    the next Monday, server time. Asked again before then, the reply is an error: prize_id 0 would point
    the client at no prize."""
    from . import quests
    now = int(now or time.time())
    rec = state.setdefault("share_with_user_info", {})
    if now <= int(rec.get("last_time") or 0) or SHARE_PRIZE not in quests.prizes():
        return None
    rec["last_time"] = _next_reset(2, now)
    quests.grant(state, quests._reward(quests.prizes()[SHARE_PRIZE]))
    return {"prize_id": SHARE_PRIZE}


def target_end_battle(state, body):
    """Targettrain/endBattle {"mission_id", "score", "is_win", "battle_time", "log_data", ...} -> {}
    (BattleController$$RequestTargetTrainBattleFinishHandle). The client takes the stage's cost itself
    (stc mission_targettrain cost_type 2: mp/ammo/mre/part; 1: cost_item "id,num"), so the save does
    too. A {"package": {"id": prize}} would show a drop; no stage has is_reward set."""
    from . import stc
    from .factory import _add
    mid = int((body or {}).get("mission_id") or 0)
    row = next((r for r in stc.table("mission_targettrain") if r["id"] == mid), None)
    if row is None:
        return None
    ui = state["user_info"]
    if row["cost_type"] == 2:
        for k in ("mp", "ammo", "mre", "part"):
            _add(ui, k, -min(int(ui.get(k) or 0), int(row[k] or 0)))
    elif row["cost_type"] == 1 and "," in str(row["cost_item"]):
        iid, num = str(row["cost_item"]).split(",")[:2]
        item = next((r for r in state.get("item_with_user_info") or [] if str(r["item_id"]) == iid), None)
        if item is not None:
            item["number"] = str(max(0, int(item["number"]) - int(num)))
    best = state.setdefault("targettrain_best_score", {})
    best[str(mid)] = max(int(best.get(str(mid)) or 0), int((body or {}).get("score") or 0))
    return {}


def target_log(state, body):
    """Targettrain/log {"mission_id"} -> the best score as plain text
    (MissionSelectionDroneTrainSettingController$$RequestGetPersonalRecordHandler shows it)."""
    return str((state.get("targettrain_best_score") or {}).get(str((body or {}).get("mission_id")), 0))


def seven_attendance(state, body):
    """Index/sevenAttendance -> {"seven_attendant": "<day>,<day>,..."} (HomeController
    $$RequestSevenDaysAttendanceInfoHandle: the login days of the 7-day event, user_record
    seven_attendance_days)."""
    return {"seven_attendant": str(state.get("user_record", {}).get("seven_attendance_days") or "")}


def gem_info(state, body):
    """Index/japanGem -> {"gem", "gem_pay"} (RequestGemInfo)."""
    ui = state["user_info"]
    return {"gem": int(ui.get("gem") or 0), "gem_pay": int(ui.get("gem_pay") or 0)}


# --- organizations (Fetter)
#
# The save keeps fetter_with_user [{id, user_id, fetter_id, milestone (points), milestone_reward
# "0,1,..." per milestone}], fetter_story_with_user [{id, user_id, fetter_story_id}],
# fetter_bounty_with_user [{id, user_id, fetter_bounty_id, value, is_received}] and
# org_bounty_with_user [{id, user_id, org_bounty_id, get_time}].
#   Fetter/index -> those four lists (RequestFetterBaseInfo)
#   Fetter/readStory {"fetter_story_id"} / Fetter/milestone {"fetter_id", "milestone"} /
#   Fetter/receiveOrgBounty {"org_bounty_id"} -> {"status": 1, "prize": package}
#   Fetter/receiveBounty {"fetter_bounty_ids"} "1": marks them received and adds their points
#   Fetter/receiveAllOrgBounty {"department_id", "level"} -> {"status", "get_org_bounty_ids"}

def _fetter_rows(state, key):
    return state.setdefault(key, [])


def _next_row_id(rows):
    return str(max((int(r.get("id") or 0) for r in rows), default=0) + 1)


def _prize(state, prize_id):
    from . import quests
    return quests.grant(state, quests._reward(quests.prizes().get(int(prize_id or 0), {})))


def fetter_index(state, body):
    return {k: state.get(k) or [] for k in ("fetter_with_user", "fetter_story_with_user", "fetter_bounty_with_user",
                                             "org_bounty_with_user")}


def fetter_read_story(state, body):
    from . import stc
    sid = int((body or {}).get("fetter_story_id") or 0)
    row = next((r for r in stc.table("fetter_story") if r["id"] == sid), None)
    if row is None:
        return None
    rows = _fetter_rows(state, "fetter_story_with_user")
    if any(str(r["fetter_story_id"]) == str(sid) for r in rows):
        return {"status": 1, "prize": {}}
    rows.append({"id": _next_row_id(rows), "user_id": str(state["user_info"].get("user_id", "")), "fetter_story_id": str(sid)})
    return {"status": 1, "prize": _prize(state, row["reward"])}


def fetter_milestone(state, body):
    from . import stc
    body = body or {}
    fid, step = int(body.get("fetter_id") or 0), int(body.get("milestone") or 0)
    table = next((r for r in stc.table("fetter") if r["id"] == fid), None)
    if table is None or f"milestone{step}" not in table:
        return None
    rows = _fetter_rows(state, "fetter_with_user")
    row = next((r for r in rows if str(r["fetter_id"]) == str(fid)), None)
    if row is None or int(row.get("milestone") or 0) < int(table[f"milestone{step}"]):
        return {"status": 0}
    flags = (str(row.get("milestone_reward") or "").split(",") + ["0"] * 5)[:5]
    if flags[step - 1] == "1":
        return {"status": 0}
    flags[step - 1] = "1"
    row["milestone_reward"] = ",".join(flags)
    reward = str(table[f"milestone{step}_reward"])
    return {"status": 1, "prize": _prize(state, reward.split(":")[-1]) if reward.startswith("p:") else {}}


def fetter_receive_bounty(state, body):
    from . import stc
    ids = {str(i) for i in (body or {}).get("fetter_bounty_ids") or []}
    points = {r["id"]: (r["fetter_id"], int(r["point"] or 0)) for r in stc.table("fetter_bounty")}
    fetters = _fetter_rows(state, "fetter_with_user")
    for r in _fetter_rows(state, "fetter_bounty_with_user"):
        if str(r["fetter_bounty_id"]) in ids and r.get("is_received") != "1":
            r["is_received"] = "1"
            fid, pts = points.get(int(r["fetter_bounty_id"]), (0, 0))
            f = next((x for x in fetters if str(x["fetter_id"]) == str(fid)), None)
            if f is not None:
                f["milestone"] = str(int(f.get("milestone") or 0) + pts)
    return "1"


def _org_bounty(state, bid, now):
    from . import stc
    row = next((r for r in stc.table("organization_bounty") if r["id"] == int(bid)), None)
    rows = _fetter_rows(state, "org_bounty_with_user")
    mine = next((r for r in rows if str(r["org_bounty_id"]) == str(bid)), None)
    if row is None or (mine is not None and str(mine.get("get_time") or "0") != "0"):
        return None
    if mine is None:
        mine = {"id": _next_row_id(rows), "user_id": str(state["user_info"].get("user_id", "")), "org_bounty_id": str(bid)}
        rows.append(mine)
    mine["get_time"] = str(now)
    return _prize(state, row["reward"])


def fetter_receive_org_bounty(state, body):
    pkg = _org_bounty(state, (body or {}).get("org_bounty_id") or 0, int(time.time()))
    return {"status": 1, "prize": pkg} if pkg is not None else {"status": 0}


def fetter_receive_all_org_bounty(state, body):
    from . import stc
    body = body or {}
    org, level = int(body.get("department_id") or 0), int(body.get("level") or 0)
    got = []
    for r in stc.table("organization_bounty"):
        if r["org_id"] == org and int(r["organization_level"] or 0) <= level:
            if _org_bounty(state, r["id"], int(time.time())) is not None:
                got.append(r["id"])
    return {"status": 1, "get_org_bounty_ids": got}


# Mall/quickBuyResource {"resource": {mp, ammo, mre, part}} -> "1" (OneClickBuyPackage): the "buy the
# shortfall" button. The client prices it (OneClickBuyPackage..ctor, resource form): one gem per
# 8.33 manpower/ammo/rations or 2.77 parts, rounded up, and asks for floor(gems * rate) of each.
QUICK_BUY_RATE = {"mp": 8.33, "ammo": 8.33, "mre": 8.33, "part": 2.77}


def quick_buy_resource(state, body):
    import math
    import struct
    from .factory import _add
    res = (body or {}).get("resource") or body or {}
    ui = state["user_info"]
    gems, amounts = 0, {}
    for k, rate in QUICK_BUY_RATE.items():
        n = max(0, int(res.get(k) or 0))
        if n:
            rate = struct.unpack("<f", struct.pack("<f", rate))[0]     # the client's float32
            gems += math.ceil(n / rate)
            amounts[k] = n
    if not amounts:
        return None
    if int(ui.get("gem") or 0) < gems:
        return None
    _add(ui, "gem", -gems)
    for k, n in amounts.items():
        _add(ui, k, n)
    return "1"


def mall_buy_many(state, body):
    """Mall/buyUniform / Mall/buyVehicleSkin {"mall_ids": [...]} -> {"status", "prize": [package per good]}
    (RequestClothes reads prize[i] for the i-th good)."""
    pkgs = []
    for mid in (body or {}).get("mall_ids") or []:
        r = mall_buy(state, {"mall_id": mid, "num": 1})
        if not r or r.get("status") != 1:
            return {"status": 0}
        pkgs += r.get("prize") or [{}]
    return {"status": 1, "prize": pkgs} if all(pkgs) else {"status": 1}


def save_sangvis_preset(state, body):
    """Sangvis/preset {"preset_no", "team_set"|"sangvis": {...}}: kept in "_sangvis_presets" (the client
    reads its Coalition presets elsewhere; the reply has no keys)."""
    body = body or {}
    if not body.get("preset_no"):
        return None
    state.setdefault("_sangvis_presets", {})[str(body["preset_no"])] = body.get("team_set") or body.get("sangvis") or {}
    return {}


# --- dorm furniture
#
# Owned furniture [{"id", "dorm", "furniture_id", "x", "y"}] (dorm 0 = storage) is kept in the save's
# "_furniture"; an account that has none yet takes the list from its archived Friend/dormInfo or
# Dorm/list reply, else data/responses/Friend/dormInfo.json.
#   Dorm/list -> {"furniture_with_user_info": [...]}            DormController$$RequestDormListHandle
#   Dorm/change {"dorm_id", "furn_pos": [[furniture_with_user_id, x, y], ...]} "1": the dorm's layout;
#     pieces of that dorm not listed go back to storage            DormController$$RequestFurnitureChange
#   Dorm/decompose {"ids": [...]} -> {"gift_list": {}}: sold pieces are removed (RequestSellFurniture)

def furniture(state):
    if "_furniture" not in state:
        from . import archived, config
        uid = state.get("user_info", {}).get("user_id", "")
        found = None
        for function in ("Friend/dormInfo", "Dorm/list"):
            found = (archived.read(uid, function) or {}).get("furniture_with_user_info")
            if found:
                break
        if not found:
            try:
                path = config.RESPONSES_DIR / "Friend" / "dormInfo.json"
                found = json.loads(path.read_text("utf-8")).get("furniture_with_user_info")
            except (OSError, ValueError):
                pass
        state["_furniture"] = found or []
    return state["_furniture"]


def dorm_list(state, body):
    return {"furniture_with_user_info": furniture(state)}


def dorm_change(state, body):
    body = body or {}
    dorm = str(body.get("dorm_id") or "")
    layout = {}
    for entry in body.get("furn_pos") or []:
        if isinstance(entry, (list, tuple)) and len(entry) >= 3:
            layout[str(entry[0])] = (str(entry[1]), str(entry[2]))
        elif isinstance(entry, dict) and entry.get("id"):
            layout[str(entry["id"])] = (str(entry.get("x", 0)), str(entry.get("y", 0)))
    if not dorm:
        return None
    for f in furniture(state):
        if f["id"] in layout:
            f["dorm"], (f["x"], f["y"]) = dorm, layout[f["id"]]
        elif f["dorm"] == dorm:
            f["dorm"], f["x"], f["y"] = "0", "0", "0"
    return "1"


def dorm_decompose(state, body):
    ids = {str(i) for i in (body or {}).get("ids") or []}
    state["_furniture"] = [f for f in furniture(state) if f["id"] not in ids]
    return {"gift_list": {}}


# --- armour energy, commander dyes
#   Index/recoverEnergy {} -> {"recover_energy", "last_energy_recover_time"} (RequestRecoverVehicleEnergy:
#       adds recover_energy to item 57). The garage (establish 1002) gives parameter_2 energy every
#       ENERGY_INTERVAL seconds (Data$$NeedsRecoverVehicleEnergy's default) up to parameter_1.
#   Vehicle/exchangeEnergy {"add_num"} -> {} (RequestVehicleExchangeEnergy adds add_num to item 57);
#       each point costs game_config vehicle_energy_exchange "mp,ammo,mre,part".
#   Commander/getColor {"uniform_id", "type", "color"} -> {"color"} (RequestUseColorant: no "color"
#       key shows an error). Type 1 uses a chosen-colour dye (item 602) for "color"; otherwise a
#       random dye (item 601) gives one of the uniform's colours not yet owned (commander_uniform
#       color_0..4, empty = none). Kept in commander_uniform_info.color_get.
ENERGY_ITEM, ENERGY_INTERVAL, GARAGE = "57", 3600, "1002"
DYE_RANDOM, DYE_CHOSEN, DYE_COLORS = "601", "602", 5


def _garage(state):
    from . import squads
    row = squads._establish(state, GARAGE)
    return int(row.get("parameter_1") or 0), int(row.get("parameter_2") or 0)


def recover_energy(state, body, now=None):
    from . import squads
    now = int(now or time.time())
    record = state.setdefault("user_record", {})
    last = int(record.get("last_energy_recover_time") or now)
    top, step = _garage(state)
    ticks = max(0, (now - last) // ENERGY_INTERVAL)
    item = squads._item(state, ENERGY_ITEM)
    have = int(item["number"])
    add = max(0, min(ticks * step, top - have))
    item["number"] = str(have + add)
    last = now if have + add >= top else last + ticks * ENERGY_INTERVAL
    record["last_energy_recover_time"] = str(last)
    return {"recover_energy": add, "last_energy_recover_time": last}


def exchange_energy(state, body):
    from . import squads, stc
    n = max(0, int((body or {}).get("add_num") or 0))
    rate = next((r["parameter_value"] for r in stc.catch("game_config_info")
                 if r["parameter_name"] == "vehicle_energy_exchange"), "1,1,1,1")
    info = state["user_info"]
    for key, per in zip(("mp", "ammo", "mre", "part"), str(rate).split(",")):
        info[key] = str(max(0, int(info.get(key) or 0) - n * int(per)))
    item = squads._item(state, ENERGY_ITEM)
    item["number"] = str(int(item["number"]) + n)
    return {}


def use_dye(state, body, rng=None):
    import random
    from . import squads, stc
    body = body or {}
    uid = str(body.get("uniform_id") or "")
    row = next((r for r in stc.table("commander_uniform") if str(r["id"]) == uid), None)
    owned = next((u for u in state.get("commander_uniform_info") or [] if str(u["commander_uniform_id"]) == uid), None)
    if row is None or owned is None:
        return {}
    have = {int(c) for c in owned.get("color_get") or []}
    colors = [c for c in range(DYE_COLORS) if row.get(f"color_{c}") and c not in have]
    if int(body.get("type") or 0) == 1:
        dye, color = DYE_CHOSEN, int(body.get("color") or 0)
        if color not in colors:
            return {}
    else:
        if not colors:
            return {}
        dye, color = DYE_RANDOM, (rng or random).choice(colors)
    if not squads._spend(state, dye, 1):
        return {}
    owned["color_get"] = sorted(have | {color})
    owned["get_color_num"] = str(int(owned.get("get_color_num") or 0) + 1)
    return {"color": color}


# Leaderboards. Offline the only player is the commander, so every board lists just them:
#   Index/rank {"type", "index", "length", "rank_id", "sub_type", "condition"} -> {"rank_list": [entry],
#       "count", "refresh_time", "rank_count", "user_info": entry} (RankingListOPSController /
#       RankingListUIController$$AnalysisRankData). entry: {"rank", "id", "user_id", "user_name",
#       "user_level", "server_name", "server_id", "last_time", "headpic_id", "frame_id", and one of
#       "num", "duration", "trial", "score", the first present in that order, read as a string}.
#       Their optional "commander_info" is a string too (PlayerRankData$$AnalysisCloth); none is sent.
# A score-map activity's board (normal_activity.rank_id) scores the commander with the sum of their best
# type5_score on that activity's campaign; other boards score 0.
def _activity_score(state, rank_id):
    from . import missions, stc
    camps = {int(r["campaign_id"]) for r in stc.table("normal_activity") if str(r.get("rank_id")) == str(rank_id)}
    best = {str(r["mission_id"]): int(r.get("type5_score") or 0) for r in state.get("mission_with_user_info") or []}
    return sum(best.get(str(mid), 0) for mid, row in missions._missions().items()
               if int(row["campaign"]) in camps and missions.score_rule(mid) is not None)


# Leaderboards are the live ones the account archived (live_archive rank_boards: the standing boards by
# RankingListType 1 kills, 2 data samples, 3 exercises, 4 dolls collected, 5 furniture collected, and the rank
# table's own boards by rank_id), every visible place. The commander's entry is kept current: kills add the
# enemy_die counted since, the collections ("have/total") are counted from the save and a rank_id board's mission
# scores from the save's records, never below the live figure; when it changed the board is sorted again.
# index is an offset into the board (RankingListItem.Init asks from a rank rounded down to tens).
SCORE_KEYS = ("num", "duration", "trial", "score")


def _score(value):
    """A board figure: a number, or "have/total" for the collections. Returns (number, total or "")."""
    head, _, total = str(value or "0").partition("/")
    try:
        return float(head or 0), total
    except ValueError:
        return 0.0, total


def _board_score(state, body, live):
    from . import quests
    kind, rank_id = int(body.get("type") or 0), body.get("rank_id")
    if rank_id:
        return max(live, _activity_score(state, rank_id))
    counters = quests._state(state)["counters"]
    if kind == 1:
        base = state.setdefault("_rank_base", {}).setdefault("1", counters.get("enemy_die", 0))
        return live + counters.get("enemy_die", 0) - base
    if kind == 4:
        return max(live, len({str(g.get("gun_id")) for g in state.get("gun_with_user_info") or []}))
    if kind == 5:
        return max(live, len({str(f.get("furniture_id")) for f in furniture(state)}))
    return live


def _live_board(state, body, me, now):
    saved = archived.read(me["user_id"], "Index/rank", archived.board_key(body))
    if not isinstance(saved, dict) or not isinstance(saved.get("rank_list"), list):
        return None
    listed = [dict(r) for r in saved["rank_list"] if isinstance(r, dict)]
    rows = [r for r in listed if str(r.get("user_id")) != me["user_id"]]
    own = dict(saved.get("user_info") or {})
    key = next((k for k in SCORE_KEYS if k in own), None) or next((k for r in rows for k in SCORE_KEYS if k in r), "num")
    live, total = _score(own.get(key))
    ident = {k: me[k] for k in ("user_id", "user_name", "user_level", "headpic_id", "frame_id")}
    me = dict(own, **ident)
    score = _board_score(state, body, live)
    if total and total.isdigit():
        score = min(score, int(total))
    board = listed
    if score != live:
        me[key] = f"{int(score)}/{total}" if total else str(int(score))
        merged = sorted(rows + [me], key=lambda r: -_score(r.get(key))[0])     # stable: ties keep the live order
        pos = merged.index(me)
        shown = int(_score(saved.get("count"))[0]) or len(listed)
        if pos < len(rows) or len(rows) < len(listed) or len(rows) < shown:
            board = merged[:max(shown, 1)]
            for n, r in enumerate(board, 1):
                r["rank"] = str(n)
            me["rank"] = str(pos + 1)
        else:
            board = rows
    else:
        for r in board:
            if str(r.get("user_id")) == me["user_id"]:
                r.update(ident)
    index, length = max(0, int(body.get("index") or 0)), int(body.get("length") or 20)
    return dict(saved, rank_list=board[index:index + length], user_info=me, refresh_time=now + 7 * 86400)


def rank(state, body, now=None):
    body, now = body or {}, int(now or time.time())
    ui, card = state["user_info"], _card(state)
    entry = {"rank": 1, "id": 1, "user_id": str(ui.get("user_id", "")), "user_name": str(ui.get("name", "")),
             "user_level": int(ui.get("lv") or 1), "server_name": "", "server_id": 0, "last_time": now,
             "headpic_id": int(card.get("headpic_id") or 0), "frame_id": int(card.get("frame_id") or 0),
             "score": str(_activity_score(state, body.get("rank_id")))}
    board = _live_board(state, body, entry, now)
    if board is not None:
        return board
    return {"rank_list": [entry], "count": 1, "refresh_time": now + 7 * 86400, "rank_count": 1, "user_info": entry}
