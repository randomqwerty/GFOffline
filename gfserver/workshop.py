"""Repair, equipment and fairy production, enhancement, retiring and gifts.

Reply formats (from the client's handlers):
  Gun/fixGuns          "1"   {"if_quick", "fix_guns": {"<fix_slot>": gun_with_user_id}}  RequestFixGun
  Gun/fixFinish        "1"   {"fix_slot"}                     RequestGunFixFinish
  Gun/quickFix         "1"   {"fix_slot"}                     RequestGunFixQuickFinish
  Sangvis/fix          "1"   {"fix_sangvis_list", "if_quick"} RequestSangvisFixStart
  Sangvis/fixFinish    "1"   {"fix_slot", "if_quick"}         RequestSangvisFixFinish
  Index/quickFix       "1"   {"gun_with_user_ids", "sangvis_with_user_ids", "squad_with_user_ids",
                             "vehicle_ids"}                   RequestQuickFixAll
  Index/fixUnbrokenTargets  {} (JSON, no keys read)  same body  RequestFixUnbrokenGuns
  Equip/develop        {"equip_id"}  {"mp","ammo","mre","part","build_slot","input_level"}
                                                    RequestStartEquipmentDevelop
  Equip/quickDevelop   "1"   {"build_slot"}           DevelopEquipmentController (CheckONE)
  Equip/finishDevelop  {"equip_with_user": {...}} (read unguarded), optional fairy_with_user
  Equip/finishAllDevelop {"equip_with_user_add_list": [{"build_slot", "equip_id",
                       "equip_with_user"}], "fairy_with_user_add_list": [{"build_slot", "fairy_id",
                       "fairy_with_user_id"}], "cost_item3_num"}  RequestGetAllDevelopEquipment
  Fairy/develop        {"equip_ids": [{"slot", "info": {"type": 1, "fairy_id", "passive_skill",
                       "quality_lv"}}]} (recorded live reply)  RequestStartFairyDevelop
  Fairy/finishDevelop  {"fairy_with_user": {...}}  {"build_slot", "if_quick"}
  Fairy/finishAllDevelop {"fairy_with_user_add_list": [...], "cost_item3_num"}  {"if_quick"}
  Equip/eatEquip       {"equip_add_exp", "cost_item50_num"}  {"equip_with_user_id", "food"}
  Fairy/eatFairy       {"add_fairy_exp"}  {"fairy_with_user_id", "food"}
  Equip/retire         "1"   {"equips": [...]}
  Sangvis/retireSangvis "1"  {"sangvises": [...]}
  Fairy/skillUpgrade   "1"   {"fairy_with_user_id", "upgrade_slot", "if_quick", "to_level"}
  Dorm/giftToGun       {"gun_with_user_id", "gun_exp", "skin_add_favor"}
                             {"item_id", "gun_with_user_id", "num", "new"}  RequestGiveGiftToGun
Battle damage is saved (missions.battle_finish), so repairs restore it. The highest life seen
for a unit is kept in the save's "_max_life" (stripped from Index/index): the gun formula
(factory.gun_life) covers dolls up to level 100, and Coalition units have no formula here.
APPROXIMATION: repair costs and the enhancement exp of fodder are not in the client data; the
client deducts its own repair cost, and fodder exp uses the tables below.
"""
import random
import time
from functools import lru_cache

from . import stc
from .factory import QUICK_CONTRACT_ITEM, _add, _use_item, gun_life, guns
from .inventory import _remove_keyed

EQUIP_OBTAIN = "3001"      # "Obtainable from Equipment Productions"
FAIRY_OBTAIN = "39"        # "Obtain from Fairy Production"
EQUIP_RARITY = {"standard": {2: 50, 3: 30, 4: 15, 5: 5}, "heavy": {3: 40, 4: 40, 5: 20}}
FOOD_EQUIP_EXP = {1: 5, 2: 10, 3: 30, 4: 100, 5: 300}     # APPROXIMATION
FOOD_FAIRY_EXP = 2000                                      # APPROXIMATION, per fairy
STAT_KEYS = ("pow", "hit", "dodge", "speed", "rate", "critical_harm_rate", "critical_percent",
             "armor_piercing", "armor", "shield", "damage_amplify", "damage_reduction",
             "night_view_percent", "bullet_number_up")


def _values(collection):
    return collection.values() if isinstance(collection, dict) else collection


def _find(collection, uid):
    if isinstance(collection, dict):
        # (vehicle_with_user_info is keyed by position, not id, in the recorded account)
        hit = collection.get(str(uid))
        if hit is not None and str(hit.get("id", uid)) == str(uid):
            return hit
        return next((x for x in collection.values() if isinstance(x, dict) and str(x.get("id")) == str(uid)), None)
    return next((x for x in collection or [] if str(x["id"]) == str(uid)), None)


def _new_id(collection):
    return str(max((int(x["id"]) for x in _values(collection or {})), default=0) + 1)


def _put(state, key, row):
    col = state.setdefault(key, {})
    if isinstance(col, dict):
        col[row["id"]] = row
    else:
        col.append(row)
    return row


# --- life and repair ---------------------------------------------------------------------

def max_life(state, kind, unit):
    """Full life of a doll ("gun") or Coalition unit ("sangvis")."""
    # never damaged (no record): the saved life is still full
    best = int(state.get("_max_life", {}).get(f"{kind}:{unit['id']}") or unit.get("life") or 0)
    if kind == "gun" and int(unit["gun_id"]) in guns():
        best = max(best, gun_life(int(unit["gun_id"]), min(100, int(unit.get("gun_level") or 1)),
                                  int(unit.get("number") or 1)))
    return best


def set_life(state, kind, unit, life):
    """A battle result: remember the full life first, then save the new one."""
    seen = state.setdefault("_max_life", {})
    key = f"{kind}:{unit['id']}"
    seen[key] = max(int(seen.get(key) or 0), int(unit.get("life") or 0))
    unit["life"] = str(max(0, min(int(life), max_life(state, kind, unit))))


def _heal(state, kind, uid):
    unit = _find(state.get(f"{kind}_with_user_info"), uid)
    if unit is not None:
        unit["life"] = str(max_life(state, kind, unit))
    return unit


def _fix_pairs(raw):
    """fix_guns / fix_sangvis_list as [(slot, unit id)] from {"slot": id} or [id, ...]."""
    if isinstance(raw, dict):
        return [(int(k), v) for k, v in raw.items() if str(k).isdigit()]
    return [(i, v) for i, v in enumerate(raw or [], 1)]


def _start_fix(state, kind, raw, quick):
    acts = state.setdefault("fix_act_info", [])
    busy = {int(a["fix_slot"]) for a in acts}
    for slot, uid in _fix_pairs(raw):
        if quick:
            _heal(state, kind, uid)
            continue
        while slot in busy:
            slot += 1
        busy.add(slot)
        acts.append({"fix_slot": slot, "gun_with_user_id": str(uid) if kind == "gun" else "0",
                     "sangvis_with_user_id": str(uid) if kind == "sangvis" else "0",
                     "start_time": int(time.time())})
    return "1"


def fix_guns(state, body):
    body = body or {}
    return _start_fix(state, "gun", body.get("fix_guns"), int(body.get("if_quick") or 0))


def fix_sangvis(state, body):
    body = body or {}
    return _start_fix(state, "sangvis", body.get("fix_sangvis_list"), int(body.get("if_quick") or 0))


def fix_finish(state, body):
    slot = int((body or {}).get("fix_slot") or 0)
    acts = state.get("fix_act_info") or []
    for a in [a for a in acts if int(a["fix_slot"]) == slot]:
        acts.remove(a)
        if str(a.get("gun_with_user_id") or "0") != "0":
            _heal(state, "gun", a["gun_with_user_id"])
        if str(a.get("sangvis_with_user_id") or "0") != "0":
            _heal(state, "sangvis", a["sangvis_with_user_id"])
    return "1"


def quick_fix_all(state, body):
    body = body or {}
    for gid in body.get("gun_with_user_ids") or []:
        _heal(state, "gun", gid)
    for sid in body.get("sangvis_with_user_ids") or []:
        _heal(state, "sangvis", sid)
    return "1"


def fix_unbroken(state, body):
    quick_fix_all(state, body)
    return {}


# --- equipment and fairy production ------------------------------------------------------

@lru_cache(maxsize=1)
def equips():
    return {int(e["id"]): e for e in stc.table("equip")}


@lru_cache(maxsize=1)
def fairies():
    return {int(f["id"]): f for f in stc.table("fairy")}


@lru_cache(maxsize=1)
def _equip_pool():
    out = {}
    for e in equips().values():
        if EQUIP_OBTAIN in str(e["obtain_ids"]).split(",") and int(e["develop_duration"] or 0):
            out.setdefault(int(e["rank"]), []).append(int(e["id"]))
    return out


@lru_cache(maxsize=1)
def _fairy_pool():
    return [f["id"] for f in fairies().values() if FAIRY_OBTAIN in str(f["obtain_ids"]).split(",")]


@lru_cache(maxsize=1)
def _talents():
    return [int(t["id"]) for t in stc.table("fairy_talent") if int(t["rank"] or 0) in (1, 2)]


def roll_equip(kind, rng=random):
    pool = _equip_pool()
    weights = {r: w for r, w in EQUIP_RARITY[kind].items() if pool.get(r)}
    return rng.choice(pool[rng.choices(list(weights), weights=list(weights.values()))[0]])


def new_equip(state, equip_id, rng=random):
    eqs = state.setdefault("equip_with_user_info", {})
    row = {"id": _new_id(eqs), "user_id": str(state["user_info"].get("user_id", "")), "gun_with_user_id": "0",
           "equip_id": str(equip_id), "equip_exp": "0", "equip_level": "0"}
    row.update({k: str(rng.randint(0, 10000)) for k in STAT_KEYS})     # calibration, per 10000
    row.update({"adjust_count": "0", "is_locked": "0", "last_adjust": "0"})
    return _put(state, "equip_with_user_info", row)


def new_fairy(state, fairy_id, talent):
    fs = state.setdefault("fairy_with_user_info", {})
    row = {"id": _new_id(fs), "user_id": str(state["user_info"].get("user_id", "")), "fairy_id": str(fairy_id),
           "team_id": "0", "fairy_lv": "1", "fairy_exp": "0", "quality_lv": "1", "quality_exp": "0",
           "skill_lv": "1", "passive_skill": str(talent), "is_locked": "0", "equip_id": "0",
           "adjust_count": "0", "last_adjust": "0", "passive_skill_collect": str(talent), "skin": "0",
           "mod": "0", "mod_exp": "0", "is_collect": "0"}
    return _put(state, "fairy_with_user_info", row)


def _pay(state, body, times=1):
    for res in ("mp", "ammo", "mre", "part"):
        _add(state["user_info"], res, -int(body.get(res) or 0) * times)


def _equip_slots(state):
    """Equipment and fairy builds share the even build slots."""
    busy = {int(a["build_slot"]) for k in ("develop_equip_act_info", "develop_fairy_act_info")
            for a in state.get(k) or []}
    top = int(state["user_info"].get("max_equip_build_slot") or state["user_info"].get("max_build_slot") or 16)
    return [s for s in range(2, top + 1, 2) if s not in busy]


def _set_act(state, key, act):
    acts = [a for a in state.get(key) or [] if int(a["build_slot"]) != int(act["build_slot"])]
    acts.append(act)
    state[key] = acts


def equip_develop(state, body, rng=random):
    body = body or {}
    kind = "heavy" if int(body.get("input_level") or 0) > 0 else "standard"
    equip_id = roll_equip(kind, rng)
    _pay(state, body)
    _set_act(state, "develop_equip_act_info", {"build_slot": int(body.get("build_slot") or 0),
                                               "start_time": int(time.time()), "equip_id": equip_id,
                                               "passive_skill": 0, "quality_lv": 0, "is_produce": 0})
    return {"equip_id": str(equip_id)}


def _quick_slot(state, key, body):
    slot = int((body or {}).get("build_slot") or 0)
    for a in state.get(key) or []:
        if int(a["build_slot"]) == slot and int(a["start_time"]):
            a["start_time"] = 0
            _use_item(state, QUICK_CONTRACT_ITEM)
    return "1"


def equip_quick_develop(state, body):
    return _quick_slot(state, "develop_equip_act_info", body)


def _take_act(state, key, slot):
    acts = state.get(key) or []
    act = next((a for a in acts if int(a["build_slot"]) == int(slot)), None)
    if act is not None:
        state[key] = [a for a in acts if a is not act]
    return act


def _collect_fairy(state, act):
    return new_fairy(state, int(act["fairy_id"]), int(act.get("passive_skill") or 0) or _talents()[0])


def equip_finish_develop(state, body, rng=random):
    slot = int((body or {}).get("build_slot") or 0)
    act = _take_act(state, "develop_equip_act_info", slot)
    if act is not None:
        return {"equip_with_user": new_equip(state, int(act["equip_id"]), rng)}
    act = _take_act(state, "develop_fairy_act_info", slot)
    if act is None:
        return None
    return {"equip_with_user": {}, "fairy_with_user": _collect_fairy(state, act)}


def _finished(state, act, duration, quick):
    late = int(act["start_time"]) + int(duration) > time.time()
    if late and not quick:
        return None
    return _use_item(state, QUICK_CONTRACT_ITEM) if late else 0


def _finish_all_fairies(state, quick):
    out, keep, cost = [], [], 0
    for a in state.get("develop_fairy_act_info") or []:
        paid = _finished(state, a, fairies().get(int(a["fairy_id"]), {}).get("develop_duration") or 0, quick)
        if paid is None:
            keep.append(a)
            continue
        cost += paid
        f = _collect_fairy(state, a)
        out.append({"build_slot": int(a["build_slot"]), "fairy_id": f["fairy_id"], "fairy_with_user_id": f["id"]})
    state["develop_fairy_act_info"] = keep
    return out, cost


def equip_finish_all(state, body, rng=random):
    quick = bool(int((body or {}).get("is_cost_item3") or 0))
    out, keep, cost = [], [], 0
    for a in state.get("develop_equip_act_info") or []:
        paid = _finished(state, a, equips().get(int(a["equip_id"]), {}).get("develop_duration") or 0, quick)
        if paid is None:
            keep.append(a)
            continue
        cost += paid
        e = new_equip(state, int(a["equip_id"]), rng)
        out.append({"build_slot": int(a["build_slot"]), "equip_id": e["equip_id"], "equip_with_user": e})
    state["develop_equip_act_info"] = keep
    fairy_out, fairy_cost = _finish_all_fairies(state, quick)
    return {"equip_with_user_add_list": out, "fairy_with_user_add_list": fairy_out,
            "cost_item3_num": cost + fairy_cost}


def fairy_develop(state, body, rng=random):
    """One fairy per slot: the given build_slot, or build_multi free slots."""
    body = body or {}
    count = max(1, int(body.get("build_multi") or 1))
    slots = [int(body["build_slot"])] if count == 1 and body.get("build_slot") else _equip_slots(state)[:count]
    quick = bool(int(body.get("build_quick") or 0))
    _pay(state, body, len(slots))
    out = []
    for slot in slots:
        fairy_id, talent = rng.choice(_fairy_pool()), rng.choice(_talents())
        if quick:
            _use_item(state, QUICK_CONTRACT_ITEM)
        _set_act(state, "develop_fairy_act_info", {"build_slot": slot, "start_time": 0 if quick else int(time.time()),
                                                   "fairy_id": fairy_id, "passive_skill": talent,
                                                   "quality_lv": 1, "is_produce": 0})
        out.append({"slot": slot, "info": {"type": 1, "fairy_id": fairy_id, "passive_skill": talent, "quality_lv": 1}})
    return {"equip_ids": out}


def fairy_finish_develop(state, body):
    act = _take_act(state, "develop_fairy_act_info", int((body or {}).get("build_slot") or 0))
    if act is None:
        return None
    return {"fairy_with_user": _collect_fairy(state, act)}


def fairy_finish_all(state, body):
    out, cost = _finish_all_fairies(state, bool(int((body or {}).get("if_quick") or 0)))
    return {"fairy_with_user_add_list": out, "cost_item3_num": cost}


# --- enhancement, retiring, skills, gifts ----------------------------------------------------

def _level_for(exp, table, level_key, cap):
    """Highest level whose cumulative exp requirement is met."""
    need = sorted((int(r[level_key]), int(r["exp"])) for r in table)
    return min(cap, sum(1 for _, e in need if exp >= e))


def eat_equip(state, body):
    body = body or {}
    eqs = state.get("equip_with_user_info") or {}
    target = _find(eqs, body.get("equip_with_user_id") or 0)
    if target is None:
        return None
    food = [str(i) for i in body.get("food") or [] if str(i) != str(target["id"])]
    gained = sum(FOOD_EQUIP_EXP.get(int(equips().get(int(_find(eqs, f)["equip_id"]), {}).get("rank") or 2), 10)
                 for f in food if _find(eqs, f) is not None)
    state["equip_with_user_info"] = _remove_keyed(eqs, food)
    target["equip_exp"] = str(int(target.get("equip_exp") or 0) + gained)
    cap = int(equips().get(int(target["equip_id"]), {}).get("max_level") or 0) or 10
    target["equip_level"] = str(_level_for(int(target["equip_exp"]), stc.catch("equip_exp_info"), "level", cap))
    return {"equip_add_exp": gained, "cost_item50_num": 0}


def eat_fairy(state, body):
    body = body or {}
    fs = state.get("fairy_with_user_info") or {}
    target = _find(fs, body.get("fairy_with_user_id") or 0)
    if target is None:
        return None
    food = [str(i) for i in body.get("food") or [] if str(i) != str(target["id"]) and _find(fs, i) is not None]
    gained = FOOD_FAIRY_EXP * len(food)
    state["fairy_with_user_info"] = _remove_keyed(fs, food)
    target["fairy_exp"] = str(int(target.get("fairy_exp") or 0) + gained)
    target["fairy_lv"] = str(max(1, _level_for(int(target["fairy_exp"]), stc.catch("fairy_exp_info"), "id", 100)))
    return {"add_fairy_exp": gained}


def retire_equip(state, body):
    ids = {str(i) for i in (body or {}).get("equips") or []}
    eqs = state.get("equip_with_user_info") or {}
    for e in [_find(eqs, i) for i in ids]:
        row = equips().get(int(e["equip_id"]), {}) if e else {}
        for res in ("mp", "ammo", "mre", "part"):
            _add(state["user_info"], res, int(row.get("retire_" + res) or 0))
    state["equip_with_user_info"] = _remove_keyed(eqs, ids)
    return "1"


def retire_sangvis(state, body):
    # the Coalition cores refunded (SangvisGun basic type data) are added client-side only
    state["sangvis_with_user_info"] = _remove_keyed(state.get("sangvis_with_user_info") or [],
                                                    (body or {}).get("sangvises") or [])
    return "1"


def fairy_skill_upgrade(state, body):
    """Like Gun/skillUpgrade; a timed one is finished by Gun/finishUpgrade (upgrade_act_info)."""
    from .inventory import TRAINING_SECONDS_PER_LEVEL
    body = body or {}
    f = _find(state.get("fairy_with_user_info"), body.get("fairy_with_user_id") or 0)
    if f is None:
        return None
    to_level = int(body.get("to_level") or int(f.get("skill_lv") or 1) + 1)
    if int(body.get("if_quick") or 0):
        f["skill_lv"] = str(to_level)
        return "1"
    slot = int(body.get("upgrade_slot") or 1)
    acts = [a for a in state.get("upgrade_act_info") or [] if int(a["upgrade_slot"]) != slot]
    acts.append({"upgrade_slot": slot, "gun_with_user_id": 0, "sangvis_with_user_id": 0,
                 "fairy_with_user_id": str(f["id"]), "skill": 1, "to_level": to_level,
                 "end_time": int(time.time()) + TRAINING_SECONDS_PER_LEVEL})
    state["upgrade_act_info"] = acts
    return "1"


@lru_cache(maxsize=1)
def _gifts():
    return {int(g["id"]): g for g in stc.table("gift_item")}


def gift_to_gun(state, body):
    body = body or {}
    g = _find(state.get("gun_with_user_info"), body.get("gun_with_user_id") or 0)
    gift = _gifts().get(int(body.get("item_id") or 0))
    if g is None or gift is None:
        return None
    num = max(1, int(body.get("num") or 1))
    for it in state.get("gift_with_user_info") or []:
        if str(it["item_id"]) == str(gift["id"]):
            it["number"] = str(max(0, int(it["number"]) - num))
    cap = int(g.get("max_favor") or 1000000)
    g["favor"] = str(max(int(g.get("favor") or 0), min(cap, int(g.get("favor") or 0) + int(gift["favor"] or 0) * num)))
    if int(gift.get("exp") or 0):
        from .missions import add_gun_exp
        add_gun_exp(g, int(gift["exp"]) * num)
    return {"gun_with_user_id": str(g["id"]), "gun_exp": str(g.get("gun_exp") or 0), "skin_add_favor": 0}


BLACK_CARD_EXCHANGE = "43"


def skin_to_gun(state, body):
    """Dorm/skinToGun {"item_id", "gun_with_user_id", "num"} -> {"skin_add_favor", "dorm_with_user_id",
    "furniture_id"} (RequestSendGift). A costume gift (gift_item with a skin) unlocks the skin (a skin
    already owned adds one item 43 instead, as the client does), adds the gift's affection and
    gives its poster furniture (gift_item.poster) as a new piece in storage. The client adds the
    skin and the affection itself and needs a real furniture id. gun_with_user_id 0 (the costume's
    doll is not owned) unlocks the skin and gives the poster with no affection."""
    body = body or {}
    g = _find(state.get("gun_with_user_info"), body.get("gun_with_user_id") or 0) or {}
    gift = _gifts().get(int(body.get("item_id") or 0))
    if gift is None or not int(gift.get("skin") or 0):
        return {"skin_add_favor": 0, "dorm_with_user_id": 0, "furniture_id": 0}
    from . import account, squads
    for it in state.get("gift_with_user_info") or []:
        if str(it["item_id"]) == str(gift["id"]):
            it["number"] = str(max(0, int(it["number"]) - 1))
    skins = state.setdefault("skin_with_user_info", {})
    sid = str(gift["skin"])
    if sid in skins:
        squads._item(state, BLACK_CARD_EXCHANGE)["number"] = str(int(squads._item(state, BLACK_CARD_EXCHANGE)["number"]) + 1)
    else:
        skins[sid] = {"user_id": str(state["user_info"].get("user_id", "")), "skin_id": sid, "is_read": "0"}
    before = int(g.get("favor") or 0)
    if g:
        g["favor"] = str(max(before, min(int(g.get("max_favor") or 1000000), before + int(gift["favor"] or 0))))
    pieces = account.furniture(state)
    piece = {"id": str(max((int(f["id"]) for f in pieces), default=0) + 1), "dorm": "0",
             "furniture_id": str(int(gift.get("poster") or 0)), "x": "0", "y": "0"}
    if int(piece["furniture_id"]):
        pieces.append(piece)
    return {"skin_add_favor": int(g.get("favor") or 0) - before, "dorm_with_user_id": int(piece["id"]),
            "furniture_id": int(piece["furniture_id"])}


def skin_to_npc(state, body):
    """Dorm/skinToNpc {"item_id"} -> {"adjutant_skin_item": [], "item_info": {...}} (RequestSendGiftToNpc).
    An NPC costume gift (gift_item whose skin fits an NPC: fit_gun -1 Kalina, -5 Persica) unlocks the
    skin; the client adds the skin itself. A skin already owned pays game_config npc_skin_repeat
    ("4001-1000;4002-1000;..."), which the client shows from item_info {"<item>": n} (sent only then).
    APPROXIMATION: every npc_skin_repeat entry is paid; no adjutant skin items are given."""
    from . import quests, squads
    gift = _gifts().get(int((body or {}).get("item_id") or 0))
    skin = int((gift or {}).get("skin") or 0)
    if not skin or int(_skins().get(skin, {}).get("fit_gun") or 0) >= 0:
        return None
    for it in state.get("gift_with_user_info") or []:
        if str(it["item_id"]) == str(gift["id"]):
            it["number"] = str(max(0, int(it["number"]) - 1))
    skins = state.setdefault("skin_with_user_info", {})
    info = {}
    if str(skin) in skins:
        for part in str(quests._config().get("npc_skin_repeat") or "").split(";"):
            iid, _, n = part.partition("-")
            if iid.strip().isdigit() and n.strip().isdigit():
                row = squads._item(state, iid.strip())
                row["number"] = str(int(row["number"]) + int(n))
                info[iid.strip()] = int(n)
    else:
        skins[str(skin)] = {"user_id": str(state["user_info"].get("user_id", "")), "skin_id": str(skin), "is_read": "0"}
    reply = {"adjutant_skin_item": []}
    if info:
        reply["item_info"] = info       # its presence makes the client show the repeat reward box
    return reply


@lru_cache(maxsize=1)
def _skins():
    return {int(r["id"]): r for r in stc.table("skin")}


def gift_to_sangvis(state, body):
    """Dorm/giftToSangvis {"item_id", "sangvis_with_user_id", "num"} -> {"add_favor", "sangvis_exp"}
    (RequestSangvisGiveGift)."""
    body = body or {}
    s = _find(state.get("sangvis_with_user_info"), body.get("sangvis_with_user_id") or 0)
    gift = _gifts().get(int(body.get("item_id") or 0))
    if s is None or gift is None:
        return None
    num = max(1, int(body.get("num") or 1))
    for it in state.get("gift_with_user_info") or []:
        if str(it["item_id"]) == str(gift["id"]):
            it["number"] = str(max(0, int(it["number"]) - num))
    before = int(s.get("favor") or 0)
    cap = int(s.get("max_favor") or 1000000)
    s["favor"] = str(max(before, min(cap, before + int(gift["favor"] or 0) * num)))
    s["sangvis_exp"] = str(int(s.get("sangvis_exp") or 0) + int(gift.get("exp") or 0) * num)
    return {"add_favor": int(s["favor"]) - before, "sangvis_exp": int(s["sangvis_exp"])}


FAVOR_CLICK = 1000      # APPROXIMATION: 0.1 affection per dorm heart (the live value is server-side)


def dorm_favor(kind):
    """Dorm/receive_favor {"dorm_id", "gun_with_user_id"} / Dorm/receiveSangvisFavor
    {"dorm_id", "sangvis_with_user_id"} -> {"favor_click"} (RequestGunDormPet / RequestSangvisDormPet):
    collecting a unit's heart in the dorm."""
    def collect(state, body):
        unit = _find(state.get(f"{kind}_with_user_info"), (body or {}).get(f"{kind}_with_user_id") or 0)
        if unit is None:
            return None
        before = int(unit.get("favor") or 0)
        unit["favor"] = str(max(before, min(int(unit.get("max_favor") or 1000000), before + FAVOR_CLICK)))
        return {"favor_click": int(unit["favor"]) - before}
    return collect


def equip_develop_multi(state, body, rng=random):
    """Equip/developMulti {"mp", "ammo", "mre", "part", "input_level", "build_quick", "build_multi",
    "build_heavy"} (RequestBatchDevelopEquipment). Like Gun/developMultiGun: build_quick=1 ->
    [{"equip_with_user": {...}}, ...] added at once; otherwise {"equip_ids": [{"slot", "info":
    {"equip_id", "fairy_id": 0, "type": 0, "passive_skill": 0, "quality_lv": 0}}]} with one timed
    build per free even slot (info.equip_id and info.fairy_id are both read unguarded)."""
    body = body or {}
    kind = "heavy" if int(body.get("input_level") or 0) > 0 or int(body.get("build_heavy") or 0) else "standard"
    count = max(1, int(body.get("build_multi") or 1))
    quick = bool(int(body.get("build_quick") or 0))
    slots = list(range(count)) if quick else _equip_slots(state)[:count]
    _pay(state, body, len(slots))
    if quick:
        out = []
        for _ in slots:
            _use_item(state, QUICK_CONTRACT_ITEM)
            out.append({"equip_with_user": new_equip(state, roll_equip(kind, rng), rng)})
        return out
    out = []
    for slot in slots:
        eid = roll_equip(kind, rng)
        _set_act(state, "develop_equip_act_info", {"build_slot": slot, "start_time": int(time.time()), "equip_id": eid,
                                                   "passive_skill": 0, "quality_lv": 0, "is_produce": 0})
        out.append({"slot": slot, "info": {"equip_id": eid, "fairy_id": 0, "type": 0, "passive_skill": 0, "quality_lv": 0}})
    return {"equip_ids": out}


def core_recover_gun(state, body):
    """Gun/coreRecoverGun {"gun_id"} -> {"gun_with_user_id"} (RequestRecoverGun): get back a doll from
    the index for cores (game_config gun_recover_core, by rank)."""
    from . import factory
    from .inventory import _link_core_cost
    gid = int((body or {}).get("gun_id") or 0)
    if gid not in guns():
        return None
    _add(state["user_info"], "core", -_link_core_cost().get(int(guns()[gid].get("rank") or 5), 15))
    rec = factory.new_gun_record(state, gid, state["user_info"].get("user_id", ""))
    return {"gun_with_user_id": rec["id"]}


def core_recover_equip(state, body, rng=random):
    """Equip/coreRecoverEquip {"equip_id"} -> {"id"} (RequestRecoverEquip): the client pays the cost
    (game_config equip_recover_supplies) itself."""
    eid = int((body or {}).get("equip_id") or 0)
    if eid not in equips():
        return None
    return {"id": new_equip(state, eid, rng)["id"]}


@lru_cache(maxsize=1)
def _presents():
    return {int(r["item_id"]): r for r in stc.table("present")}


def open_gift_box(state, body):
    """Giftbox/open {"gift_box_id", "open_num", "select_list", plus the chosen prize fields of a
    selectable box (gun_id, equip_ids, item_ids, ...)} -> {"presentBox": package} (RequestOpenPresentBox).
    A fixed box pays its prize_id (stc present) per box opened."""
    from . import quests
    body = body or {}
    box = _presents().get(int(body.get("gift_box_id") or 0))
    num = max(1, int(body.get("open_num") or 1))
    if box is None:
        return None
    have = next((i for i in state.get("item_with_user_info", []) if str(i["item_id"]) == str(box["item_id"])), None)
    if have is None or int(have["number"]) < num:
        return None
    have["number"] = str(int(have["number"]) - num)
    chosen = {k: str(body[k]) for k in quests.LISTS + ("gun_id",) if body.get(k)}
    one = quests._reward(quests.prizes().get(int(box["prize_id"] or 0), {}))
    # a pick-one box lists bare ids ("16,20,32"); the client sends the choice in the same field
    if any("," in str(v) and "-" not in str(v) for k, v in one.items() if k in quests.LISTS + ("gun_id",)):
        if not chosen:
            have["number"] = str(int(have["number"]) + num)
            return None
        one = chosen
    return {"presentBox": quests.grant(state, quests._merge([one] * num))}


# --- equipment "produce" builds (targeted, from a recommended formula)
#   Equip/produceDevelop / spProduceDevelop {"build_slots": [..], "recommended_formula_id", "if_quick"}
#     -> [{"slot", "equip_id"}] (timed, into develop_equip_act_info with is_produce 1) or
#        [{"equip_with_user": {...}}] (quick)                    RequestEquipProduceDevelop
#     The equipment is drawn from the formula's produce_preview "equip_id:weight,..." (stc
#     recommended_formula), falling back to the ids in its preview. The client pays the cost.
#   Equip/produceRecover / spProduceRecover -> {"equip_type_(sp)produce_num",
#     "equip_type_(sp)produce_recover_time"}: the daily produce count, reported full
#     (game_config equip_type_produce_limit / equip_type_spproduce_limit).
# APPROXIMATION: the daily limits are not enforced.

@lru_cache(maxsize=1)
def _formulas():
    return {int(r["id"]): r for r in stc.table("recommended_formula")}


def _produce_pool(formula):
    pool = {}
    for part in str(formula.get("produce_preview") or "").split(","):
        if ":" in part:
            k, w = part.split(":")[:2]
            pool[int(k)] = int(w or 1)
    if not pool:
        for group in str(formula.get("preview") or "").split("|"):
            for x in group.split(":")[-1].split(","):
                if x.split("-")[0].strip().isdigit():
                    pool[int(x.split("-")[0])] = 1
    return {k: w for k, w in pool.items() if k in equips()}


def produce_develop(state, body, rng=random):
    body = body or {}
    formula = _formulas().get(int(body.get("recommended_formula_id") or 0))
    pool = _produce_pool(formula) if formula else {}
    if not pool:
        return None
    quick = bool(int(body.get("if_quick") or 0))
    out = []
    for slot in [int(x) for x in body.get("build_slots") or []]:
        eid = rng.choices(list(pool), weights=list(pool.values()))[0]
        if quick:
            _use_item(state, QUICK_CONTRACT_ITEM)
            out.append({"equip_with_user": new_equip(state, eid, rng)})
        else:
            _set_act(state, "develop_equip_act_info", {"build_slot": slot, "start_time": int(time.time()), "equip_id": eid,
                                                       "passive_skill": 0, "quality_lv": 0, "is_produce": 1})
            out.append({"slot": slot, "equip_id": eid})
    return out


def _config_value(name, default):
    row = next((r for r in stc.catch("game_config_info") if r["parameter_name"] == name), None)
    return int(row["parameter_value"]) if row else default


def produce_recover(state, body):
    return {"equip_type_produce_num": _config_value("equip_type_produce_limit", 20),
            "equip_type_produce_recover_time": int(time.time())}


def sp_produce_recover(state, body):
    return {"equip_type_spproduce_num": _config_value("equip_type_spproduce_limit", 10),
            "equip_type_spproduce_recover_time": int(time.time())}
