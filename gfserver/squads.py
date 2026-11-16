"""HOC (squads) outside missions: training, promotion (stars), research (advanced level), unlocking.

Items: batteries 506 (UserInfo.buildCoin), HOC reports 46 (UserInfo.squadReport), advanced data
cells 15 (UserInfo.advancedDataCell); a squad's own pieces are stc squad.piece_item_id.
Reply formats (from the client's handlers):
  Squad/train {"squad_with_user_id", "num"} -> {"real_cost_power", "real_cost_item", "add_exp", "life"}
                                    (RequestSquadTraining: batteries, reports, exp gained)
  Squad/trainFinish {"train_slot", "if_quick"} -> {"life"}      Squad/trainGiveUp {"train_slot"} -> {}
  Squad/addUpStartProgress {"squad_with_user_id", "piece_num", "data_num"}
                                 -> {"current_rank_progress", "rank_end_time"} (both guarded)
  Squad/startUpStart {"squad_with_user_id"} -> {"rank_end_time"}  (wait: squad_rank.unlock_waiting_time)
  Squad/finishUpStart / speedUpStar / cancelUpStart {"squad_with_user_id"} -> {}
  Squad/upSquadStar {"squad_with_user_id"} -> [{"item_id", "cost"}]
  Squad/researchUp {"squad_with_user_id", "data_num", "piece_num"} -> {"current_adv_progress",
                                 "advanced_level"} (RequestSquadAddIteration)
  Squad/addSquadProgress {"squad_id", "piece_num", "data_num"} -> {"current_progress"}
  Squad/addSquad {"squad_id"} -> {"cost_item_info": [{"item_id", "cost"}], "squad_info": {...}}
APPROXIMATION: the exp per HOC report (EXP_PER_REPORT) is not in the client data; battery cost
per report is game_config squad_training_battery. Promotion progress counts pieces and data cells
one for one toward squad_rank.cost_data.
"""
import math
import time
from functools import lru_cache

from . import stc

BATTERY, REPORT, DATA_CELL = "506", "46", "15"
EXP_PER_REPORT = 3000
UNLOCK_PROGRESS = 500


@lru_cache(maxsize=1)
def _config():
    return {r["parameter_name"]: str(r["parameter_value"]) for r in stc.catch("game_config_info")}


@lru_cache(maxsize=1)
def squad_rows():
    return {int(r["id"]): r for r in stc.table("squad")}


@lru_cache(maxsize=1)
def _ranks():
    return {int(r["star_id"]): r for r in stc.table("squad_rank")}


@lru_cache(maxsize=1)
def _exp_table():
    return sorted((int(r["lv"]), int(r["exp"])) for r in stc.table("squad_exp"))


def _squad(state, sid):
    squads = state.get("squad_with_user_info") or {}
    if isinstance(squads, dict):
        return squads.get(str(sid))
    return next((q for q in squads if str(q["id"]) == str(sid)), None)


def _item(state, item_id):
    items = state.setdefault("item_with_user_info", [])
    row = next((i for i in items if str(i["item_id"]) == str(item_id)), None)
    if row is None:
        row = {"item_id": str(item_id), "number": "0", "last_recover_time": "0"}
        items.append(row)
    return row


def _spend(state, item_id, n):
    row = _item(state, item_id)
    used = min(int(row["number"]), max(0, int(n)))
    row["number"] = str(int(row["number"]) - used)
    return used


def _level(exp):
    return max([lv for lv, need in _exp_table() if exp >= need] or [1])


# --- training

def train(state, body):
    body = body or {}
    q = _squad(state, body.get("squad_with_user_id") or 0)
    num = max(0, int(body.get("num") or 0))
    if q is None or not num:
        return None
    per = int(_config().get("squad_training_battery") or 5)
    reports = min(num, int(_item(state, REPORT)["number"]))
    _spend(state, REPORT, reports)
    batteries = _spend(state, BATTERY, reports * per)
    gained = reports * EXP_PER_REPORT
    cap = max(e for _, e in _exp_table())
    q["squad_exp"] = str(min(cap, int(q.get("squad_exp") or 0) + gained))
    q["squad_level"] = str(_level(int(q["squad_exp"])))
    state.setdefault("_squad_training", []).append(str(q["id"]))
    return {"real_cost_power": batteries, "real_cost_item": reports, "add_exp": gained, "life": int(q.get("life") or 0)}


def train_finish(state, body):
    queue = state.setdefault("_squad_training", [])
    q = _squad(state, queue.pop(0)) if queue else None
    return {"life": int((q or {}).get("life") or 0)}


def train_give_up(state, body):
    queue = state.setdefault("_squad_training", [])
    if queue:
        queue.pop(0)
    return {}


# --- promotion (stars)

def _next_rank(q):
    return _ranks().get(int(q.get("rank") or 1) + 1)


def add_rank_progress(state, body):
    body = body or {}
    q = _squad(state, body.get("squad_with_user_id") or 0)
    if q is None or _next_rank(q) is None:
        return None
    pieces = _spend(state, squad_rows().get(int(q["squad_id"]), {}).get("piece_item_id") or 0, int(body.get("piece_num") or 0))
    cells = _spend(state, DATA_CELL, int(body.get("data_num") or 0))
    q["current_rank_progress"] = str(int(q.get("current_rank_progress") or 0) + pieces + cells)
    return {"current_rank_progress": int(q["current_rank_progress"]), "rank_end_time": int(q.get("rank_end_time") or 0)}


def start_promotion(state, body):
    q = _squad(state, (body or {}).get("squad_with_user_id") or 0)
    nxt = _next_rank(q) if q is not None else None
    if nxt is None or int(q.get("current_rank_progress") or 0) < int(nxt["cost_data"]):
        return None
    q["rank_end_time"] = str(int(time.time()) + int(nxt["unlock_waiting_time"] or 0))
    return {"rank_end_time": int(q["rank_end_time"])}


def finish_promotion(state, body):
    q = _squad(state, (body or {}).get("squad_with_user_id") or 0)
    if q is None or _next_rank(q) is None:
        return None
    q["rank"] = str(int(q.get("rank") or 1) + 1)
    q["current_rank_progress"], q["rank_end_time"] = "0", "0"
    return {}


def cancel_promotion(state, body):
    q = _squad(state, (body or {}).get("squad_with_user_id") or 0)
    if q is None:
        return None
    q["rank_end_time"] = "0"
    return {}


def up_star(state, body):
    """Squad/upSquadStar: raise a star directly; reply the items spent (none tracked here)."""
    q = _squad(state, (body or {}).get("squad_with_user_id") or 0)
    if q is None or _next_rank(q) is None:
        return None
    q["rank"] = str(int(q.get("rank") or 1) + 1)
    return []


# --- research (advanced level)

def research(state, body):
    body = body or {}
    q = _squad(state, body.get("squad_with_user_id") or 0)
    if q is None:
        return None
    group = int(squad_rows().get(int(q["squad_id"]), {}).get("advanced_bonus") or 0)
    levels = sorted((int(r["lv"]), int(r["unlock_number"])) for r in stc.table("squad_advanced_bonus") if r["group_id"] == group)
    pieces = _spend(state, squad_rows().get(int(q["squad_id"]), {}).get("piece_item_id") or 0, int(body.get("piece_num") or 0))
    cells = _spend(state, DATA_CELL, int(body.get("data_num") or 0))
    progress, level = int(q.get("current_adv_progress") or 0) + pieces + cells, int(q.get("advanced_level") or 0)
    for lv, need in levels:
        if lv == level + 1 and progress >= need:
            progress -= need
            level = lv
    q["current_adv_progress"], q["advanced_level"] = str(progress), str(level)
    return {"current_adv_progress": progress, "advanced_level": level}


# --- unlocking a new HOC

def add_unlock_progress(state, body):
    body = body or {}
    sid = int(body.get("squad_id") or 0)
    row = squad_rows().get(sid)
    if row is None:
        return None
    rows = state.setdefault("squad_unlock_with_user_info", [])
    mine = next((r for r in rows if str(r["squad_id"]) == str(sid)), None)
    if mine is None:
        mine = {"user_id": str(state["user_info"].get("user_id", "")), "squad_id": str(sid), "current_progress": "0"}
        rows.append(mine)
    pieces = _spend(state, row.get("piece_item_id") or 0, int(body.get("piece_num") or 0))
    cells = _spend(state, DATA_CELL, int(body.get("data_num") or 0))
    mine["current_progress"] = str(min(UNLOCK_PROGRESS, int(mine["current_progress"]) + pieces + cells))
    return {"current_progress": int(mine["current_progress"])}


def add_squad(state, body):
    sid = int((body or {}).get("squad_id") or 0)
    row = squad_rows().get(sid)
    squads = state.setdefault("squad_with_user_info", {})
    have = squads.values() if isinstance(squads, dict) else squads
    if row is None or any(str(q["squad_id"]) == str(sid) for q in have):
        return None
    new_id = str(max((int(q["id"]) for q in have), default=0) + 1)
    rec = {"id": new_id, "user_id": str(state["user_info"].get("user_id", "")), "squad_id": str(sid), "squad_exp": "0",
           "squad_level": "1", "rank": "1", "advanced_level": "0", "life": str(int(row.get("hp") or 0)), "cur_def": "0",
           "ammo": "0", "mre": "0", "assist_damage": "0", "assist_reload": "0", "assist_hit": "0", "assist_def_break": "0",
           "damage": "0", "atk_speed": "0", "hit": "0", "def": "0", "skill1": "1", "skill2": "1", "skill3": "1",
           "current_rank_progress": "0", "rank_end_time": "0", "current_adv_progress": "0"}
    if isinstance(squads, dict):
        squads[new_id] = rec
    else:
        squads.append(rec)
    return {"cost_item_info": [], "squad_info": rec}


# --- HOC chip library (chip_with_user_info {"<chip_id>": {"user_id", "chip_id", "chip_exp", "chip_level"}})
#   Chip/strengthen {"chip_id", "item_14_num", "item_15_num"} -> {"chip_exp", "chip_level"} (RequestPushUpgradeChip)
#   Chip/strengthenMax {"chip_ids", "item_14_num", "item_15_num"} -> [{"chip_id", "chip_exp", "chip_level"}]
# stc squad_chip_exp gives cumulative thresholds (every level-20 chip in a real save has at least
# 1175 exp). APPROXIMATION: items 14 and 15 give CHIP_ITEM_EXP exp each. Retiring or feeding
# individual chips (chip_with_user_id) is not handled: the save has no records for them.
CHIP_ITEM_EXP = {"14": 1, "15": 10}


@lru_cache(maxsize=1)
def _chip_levels():
    return sorted((int(r["lv"]), int(r["exp"])) for r in stc.table("squad_chip_exp"))


def _chip_level(exp):
    return max([lv for lv, need in _chip_levels() if exp >= need] or [0])


def _chip(state, cid):
    chips = state.setdefault("chip_with_user_info", {})
    row = chips.get(str(cid)) if isinstance(chips, dict) else None
    if row is None and isinstance(chips, dict):
        row = chips[str(cid)] = {"user_id": str(state["user_info"].get("user_id", "")), "chip_id": str(cid),
                                 "chip_exp": "0", "chip_level": "0"}
    return row


def _feed_chip(state, row, body):
    gained = sum(CHIP_ITEM_EXP[i] * _spend(state, i, int(body.get(f"item_{i}_num") or 0)) for i in CHIP_ITEM_EXP)
    row["chip_exp"] = str(int(row.get("chip_exp") or 0) + gained)
    row["chip_level"] = str(_chip_level(int(row["chip_exp"])))
    return row


def chip_strengthen(state, body):
    body = body or {}
    cid = int(body.get("chip_id") or 0)
    if cid not in {int(r["id"]) for r in stc.table("squad_chip")}:
        return None
    row = _feed_chip(state, _chip(state, cid), body)
    return {"chip_exp": int(row["chip_exp"]), "chip_level": int(row["chip_level"])}


def chip_strengthen_max(state, body):
    """Each listed chip is raised to the top level; the items sent pay for all of them."""
    body = body or {}
    top_lv, top_exp = _chip_levels()[-1]
    _feed_chip(state, {"chip_exp": "0"}, body)          # uses up the items sent
    out = []
    for cid in body.get("chip_ids") or []:
        row = _chip(state, cid)
        row["chip_exp"] = str(max(int(row.get("chip_exp") or 0), top_exp))
        row["chip_level"] = str(top_lv)
        out.append({"chip_id": int(cid), "chip_exp": int(row["chip_exp"]), "chip_level": top_lv})
    return out


# --- stat boosts, piece conversion, chip unlocks, Data Room cells
#   Squad/strengthen {"squad_with_user_id", "strengthen_info": {"<SquadAttriType 1-8>": points}} -> {}
#       each point costs one capsule (item 9) and adds one to the stat (RequestSquadStrengthen)
#   Squad/dataChange {"squad_change_info": {"<squad id>": pieces}} -> "1"
#       pieces become Data Patches (item 17) one for one (RequestSquadTranscribe)
#   Chip/addChip {"chip_ids", "item_14_num", "item_15_num"} -> {} (RequestPushUnlockChips builds the
#       chips itself, at level 0)
#   Dorm/get_data_cell {} -> {"base_cell", "senior_cell", "surplus_datacell": {"base", "senior"}}
#       (RequestDormGetDataCell). The Data Room (establish 501: parameter_1 "primary,advanced" cells
#       per datacell_change_unit_time, parameter_2 the most it holds) fills surplus_datacell_info;
#       collecting moves what fits under the storage cap (establish 503 parameter_1) into items 14
#       and 15 and advances user_record.last_datacell_change_time by whole units.
# Data analysis (Dorm/data_analysis*) is not handled: establish 505 (analysis threads) has only a
# level 0 row with 0 threads, so the client never offers it.
CAPSULE, DATA_PATCH, PRIMARY_CELL, GENERAL_PIECE = "9", "17", "14", "519"
SQUAD_ATTRS = {1: "assist_damage", 2: "assist_def_break", 3: "assist_hit", 4: "assist_reload",
               5: "atk_speed", 6: "damage", 7: "def", 8: "hit"}
DATA_ROOM, DATA_STORAGE = "501", "503"


def strengthen(state, body):
    body = body or {}
    q = _squad(state, body.get("squad_with_user_id"))
    if q is None:
        return None
    for code, points in sorted((body.get("strengthen_info") or {}).items()):
        stat = SQUAD_ATTRS.get(int(code))
        if stat is None:
            continue
        paid = _spend(state, CAPSULE, int(points or 0))
        q[stat] = str(int(q.get(stat) or 0) + paid)
    return {}


def data_change(state, body):
    patches = 0
    for sid, n in ((body or {}).get("squad_change_info") or {}).items():
        piece = squad_rows().get(int(sid), {}).get("piece_item_id") or GENERAL_PIECE
        patches += _spend(state, piece, int(n or 0))
    row = _item(state, DATA_PATCH)
    row["number"] = str(int(row["number"]) + patches)
    return "1"


def add_chip(state, body):
    body = body or {}
    known = {int(r["id"]) for r in stc.table("squad_chip")}
    for i in ("14", "15"):
        _spend(state, i, int(body.get(f"item_{i}_num") or 0))
    for cid in body.get("chip_ids") or []:
        if int(cid) in known:
            _chip(state, cid)
    return {}


def _establish(state, kind):
    row = next((r for r in state.get("outhouse_establish_info") or [] if str(r["establish_type"]) == kind), None)
    if row is None:
        row = next((r for r in stc.catch("furniture_establish_info")
                    if r["establish_type"] == kind and int(r["establish_lv"]) == 0), {})
    return row


def _pair(text):
    a, _, b = str(text or "0,0").partition(",")
    return int(a or 0), int(b or 0)


def get_data_cell(state, body, now=None):
    now = int(now or time.time())
    room = _establish(state, DATA_ROOM)
    speed, cap = _pair(room.get("parameter_1")), _pair(room.get("parameter_2"))
    storage = _pair(_establish(state, DATA_STORAGE).get("parameter_1"))
    record = state.setdefault("user_record", {})
    unit = int(_config().get("datacell_change_unit_time") or 28800)
    last = int(record.get("last_datacell_change_time") or now)
    units = max(0, (now - last) // unit)
    record["last_datacell_change_time"] = str(last + units * unit)
    surplus = state.setdefault("surplus_datacell_info", {})
    got = []
    for key, item, i in (("base", PRIMARY_CELL, 0), ("senior", DATA_CELL, 1)):
        have = min(cap[i], int(surplus.get(key) or 0) + units * speed[i])
        row = _item(state, item)
        take = max(0, min(have, storage[i] - int(row["number"])))
        row["number"] = str(int(row["number"]) + take)
        surplus[key] = have - take
        got.append(take)
    return {"base_cell": got[0], "senior_cell": got[1],
            "surplus_datacell": {"base": surplus["base"], "senior": surplus["senior"]}}


# --- calls this client has no way to make: chips are unlocked by type now and the analysis facility
# (establish 505) has 0 threads. Replies have the shape their handlers read; nothing is refunded or produced,
# because the rules for that aren't in the client.
#   Chip/retire {"user_id", "chips"} -> {"mp", "ammo", "mre", "part"} (RequestSquadChipRetire)
#   Chip/change {"user_id", "squad_with_user_id", "change_info"} -> {"voucher"} (RequestSquadCPUChange)
#   Dorm/data_analysis {"build_slot", "input_level", "number", "quick"} -> {"data": {"<slot>": {"id", "build_slot",
#       "end_time"}}, "squad_advanced_data_cell", "squad_primary_data_cell"} (RequestSquadDataAnalysisBegin)
#   Dorm/data_analysis_complete {"is_cost_item16"} -> {"cost_item16_num"}; Dorm/data_analysis_finish {"build_slot",
#       "quick"} -> {}; Dorm/data_analysis_finish_all {} "1"
def chip_retire(state, body):
    return {"mp": 0, "ammo": 0, "mre": 0, "part": 0}


def chip_change(state, body):
    return {"voucher": 0}


def analysis_begin(state, body):
    body = body or {}
    slot = int(body.get("build_slot") or 0)
    actions = state.setdefault("_data_analysis", {})
    action = {"id": slot, "build_slot": slot, "end_time": int(time.time())}
    actions[str(slot)] = action
    return {"data": {str(slot): action}, "squad_advanced_data_cell": 0, "squad_primary_data_cell": 0}


def analysis_complete(state, body):
    return {"cost_item16_num": 0}


def analysis_finish(state, body):
    state.setdefault("_data_analysis", {}).pop(str((body or {}).get("build_slot")), None)
    return {}


def analysis_finish_all(state, body):
    state["_data_analysis"] = {}
    return "1"


# --- a HOC's pierce (assist_def_break as the client shows it; Squad$$UpdateData)
#   base   ceil(squad.assist_def_break * standard_attribute * squad_type.assist_def_break
#               * (level + squad_basic_lv - 1) * standard basic_rate * squad.basic_rate / 1e8)
#          (squad_standard_attribution row 2; squad_basic_lv in game_config)
#   + squad_advanced_bonus.assist_def_break for the squad's advanced level
#   + every chip of the squad in the chip library: round(chip.assist_def_break *
#          squad_chip_exp.strength_coef / 100 at the chip's level) (SquadChip$$UpdateData)
# Checked against the live server: a level-100 PP-93 HOC with advanced level 10 and its three
# pierce chips at level 20 has 67 + 24 + 123 = 214, the damage it did to a building.
def _round_half_even(x):
    return int(round(x))


@lru_cache(maxsize=None)
def _standard(attr):
    return next((r for r in stc.table("squad_standard_attribution") if r["attribute_type"] == attr), {})


@lru_cache(maxsize=None)
def _game_config_int(name, default):
    return int(next((r["parameter_value"] for r in stc.catch("game_config_info") if r["parameter_name"] == name), default))


def _chip_coef(level):
    rows = {int(r["lv"]): int(r["strength_coef"]) for r in stc.table("squad_chip_exp")}
    if not rows:
        return 1.0
    return rows.get(int(level), rows[min(rows)]) / 100


def panel_attribute(state, q, attr="assist_def_break"):
    """A HOC's attribute as the client's panel shows it (q: its squad_with_user_info record)."""
    row = squad_rows().get(int(q.get("squad_id") or 0), {})
    if not row:
        return 0
    typ = next((t for t in stc.table("squad_type") if int(t["type_id"]) == int(row.get("type") or 0)), {})
    std = _standard(attr)
    level = int(q.get("squad_level") or 1)
    base = (float(row.get(attr) or 0) * float(std.get("standard_attribute") or 0) * float(typ.get(attr) or 0)
            * (level + _game_config_int("squad_basic_lv", 50) - 1) * float(std.get("basic_rate") or 0)
            * float(row.get("basic_rate") or 0) / 1e8)
    total = math.ceil(round(base, 4))
    group = int(row.get("advanced_bonus") or 0)
    adv = int(q.get("advanced_level") or 0)
    total += next((int(r[attr] or 0) for r in stc.table("squad_advanced_bonus")
                   if int(r["group_id"]) == group and int(r["lv"]) == adv), 0)
    lib = state.get("chip_with_user_info") or {}
    lib = lib if isinstance(lib, dict) else {str(r.get("chip_id")): r for r in lib}
    for chip in stc.table("squad_chip"):
        owned = lib.get(str(chip["id"]))
        if int(chip["squad_id"]) == int(row["id"]) and owned is not None and int(chip.get(attr) or 0):
            total += _round_half_even(int(chip[attr]) * _chip_coef(owned.get("chip_level") or 0))
    return total
