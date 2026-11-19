"""T-Doll production (Gun/developGun, quickDevelop, finishDevelop, finishAllDevelop).

Reply formats (from the client's handlers):
  developGun        {"gun_id": N}                       RequestDevelopGun$$SuccessJsonHandleData
  quickDevelop      "1"                                 RequestQuickDevelopGun$$SuccessHandleData
  finishDevelop     {"gun_with_user_add": {"gun_with_user_id", "gun_id"}}
                                                        DevelopController$$RequestFinishDevelopGunHandle
  finishAllDevelop  {"gun_with_user_add_list": [{"build_slot","gun_with_user_id","gun_id"}],
                     "cost_item3_num": N}               (recorded live reply)
  developMultiGun   build_quick=1: [{"gun_with_user_add": {"gun_with_user_id", "gun_id"}}, ...]
                    build_quick=0: {"gun_ids": [{"id": gun_id, "slot": build_slot}, ...]}
                                                        RequestBatchDevelopGun$$SuccessJsonHandleData
  developCollectList {"log_list": [...]}               FactoryDevelopLogController$$RequestGunCollectionListHandle
In-progress builds live in the save's develop_act_info as {"build_slot","start_time","gun_id",
"wish_gun"} (GameData$$ReadUserInfo), so they survive a relogin.
"""
import math
from collections import defaultdict
import random
import time
from functools import lru_cache

from . import stc

QUICK_CONTRACT_ITEM = "3"   # finishAllDevelop reports its cost as "cost_item3_num"

# Production pools come from the gun table's obtain_ids (1 = standard production,
# 2 = heavy production; see gun_obtain + language "gun_obtain-1000000N").
# Builds use the official per-recipe rates (craft_rates); these weights are the fallback when that file is
# missing: a rarity is drawn from them, then a doll of that rarity evenly.
RARITY_WEIGHTS = {
    "standard": {2: 60, 3: 27, 4: 10, 5: 3},
    "heavy": {3: 45, 4: 37, 5: 18},
}

# HP per link = ceil((55 + (level - 1) * 0.555) * type multiplier * ratio_life / 100), times the
# dummy links. Matches every non-mod doll up to level 100 in a real save (696 of 696;
# HG..SG = types 1..6). Levels above 100 (Neural Upgrade) are not covered.
LIFE_TYPE_MULT = {1: 0.6, 2: 1.6, 3: 0.8, 4: 1.0, 5: 1.5, 6: 2.0}


def _type_info(gun_type):
    row = next(r for r in stc.catch("gun_type_info") if int(r["id"]) == int(gun_type))
    return {k: float(v) for k, v in row.items() if k.startswith("basic_attribute_")}


def gun_rec(gun_id, level=1, number=1):
    """Recovery, the HP a doll gets back at the start of each turn on a map that allows it:
    ceil((5 + (level - 1) x 0.05) x type basic_attribute_rec x ratio_rec / 100) a dummy link
    (doc/stc-guide/01), times the links (player report)."""
    g = guns()[gun_id]
    t = _type_info(g["type"])
    per = (5 + (min(100, level) - 1) * 0.05) * t["basic_attribute_rec"] * float(g["ratio_rec"] or 0) / 100
    return math.ceil(round(per, 6)) * number


def gun_enhancement(gun_id, level=100):
    """Max enhancement points (the save's pow/rate/hit/dodge) at a level (Neural Upgrades to 120):
    ceil((level - 1) x grow x type multiplier x ratio x eat_ratio / 10000) (doc/stc-guide/01)."""
    g = guns()[gun_id]
    t = _type_info(g["type"])
    e = float(g["eat_ratio"] or 0)
    calc = lambda grow, key, field: math.ceil(round((level - 1) * grow * t[key] * float(g[field] or 0) * e / 10000, 6))
    return {"pow": calc(0.242, "basic_attribute_pow", "ratio_pow"), "rate": calc(0.181, "basic_attribute_rate", "ratio_rate"),
            "hit": calc(0.303, "basic_attribute_hit", "ratio_hit"), "dodge": calc(0.303, "basic_attribute_dodge", "ratio_dodge")}


def gun_life(gun_id, level=1, number=1):
    g = guns()[gun_id]
    per_link = math.ceil((55 + (level - 1) * 0.555) * LIFE_TYPE_MULT[int(g["type"])] * int(g["ratio_life"]) / 100)
    return per_link * number


@lru_cache(maxsize=1)
def guns():
    return {int(g["id"]): g for g in stc.table("gun")}


@lru_cache(maxsize=2)
def pool(kind):
    obtain = "1" if kind == "standard" else "2"
    by_rank = {}
    for g in guns().values():
        if obtain in str(g.get("obtain_ids", "")).split(","):
            by_rank.setdefault(int(g["rank"]), []).append(int(g["id"]))
    return by_rank


# A handgun is built only below this many resources in all (the community-documented cutoff; the KR rates list
# handguns only in the 130/130/130/30 recipe).
HANDGUN_CEILING = 920


@lru_cache(maxsize=1)
def craft_rates():
    """The official rates per recipe and each doll's resource needs (data/craft_rates.json, from
    tools/build_craft_rates.py), {} when missing."""
    from . import config
    import json
    try:
        doc = json.loads((config.ROOT / "data" / "craft_rates.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    out = {kind: [dict(r, rates={int(g): p for g, p in r["rates"].items() if int(g) in guns()}) for r in doc.get(kind) or []]
           for kind in ("standard", "heavy")}
    out["needs"] = {int(g): v for g, v in (doc.get("needs") or {}).items() if int(g) in guns()}
    return out


def _distance(res, other):
    """How far apart two recipes are, by the ratio of each resource; parts count a tenth (no doll needs them)."""
    return sum(w * math.log(max(1, a) / max(1, b)) ** 2 for w, a, b in zip((1, 1, 1, 0.1), res, other))


def _eligible(kind, gun_id, res):
    """Whether a doll can come out of these resources: at least the mp, ammo and mre of a recipe it is known to come
    from (parts are not a limit: dolls are seen built with 30)."""
    needs = craft_rates().get("needs", {}).get(gun_id)
    if kind == "heavy" or needs is None:
        return True
    return any(all(x >= n for x, n in zip(res, low)) for low in needs)


def recipe_rates(kind, body):
    """{gun_id: chance} for the resources put in. A listed recipe gives its official rates. Any other is an
    estimate from the nearest listed one (nearest in resources; for heavy, of the same input level): its dolls,
    less handguns at HANDGUN_CEILING or more, plus the dolls of other listed recipes these resources can build
    (_eligible) at their rate there; each rarity keeps the nearest recipe's share."""
    recipes = craft_rates().get(kind) or []
    if not recipes:
        return {}
    body = body or {}
    res = [int(body.get(k) or 0) for k in ("mp", "ammo", "mre", "part")]
    if not any(res):
        return dict(recipes[0]["rates"])
    level = int(body.get("input_level") or 0)
    order = sorted(recipes, key=lambda r: (r["level"] != level if kind == "heavy" else 0, _distance(res, r["res"])))
    if order[0]["res"] == res and (kind != "heavy" or order[0]["level"] == level):
        return dict(order[0]["rates"])
    handguns_out = kind == "standard" and sum(res) >= HANDGUN_CEILING
    keep = lambda gid: not (handguns_out and int(guns()[gid]["type"]) == 1)
    rank = lambda gid: int(guns()[gid]["rank"])
    rates = {g: p for g, p in order[0]["rates"].items() if keep(g)}
    share = defaultdict(float)
    for g, p in rates.items():
        share[rank(g)] += p
    for r in order[1:]:
        for gid, p in r["rates"].items():
            if gid not in rates and keep(gid) and _eligible(kind, gid, res):
                rates[gid] = p
    in_rank = defaultdict(float)
    for g, p in rates.items():
        in_rank[rank(g)] += p
    rates = {g: p * share[rank(g)] / in_rank[rank(g)] for g, p in rates.items() if share[rank(g)]}
    total = sum(rates.values())
    return {g: p / total for g, p in rates.items()}


def roll_gun(kind, rng=random, body=None):
    """A doll by recipe_rates; without the rates file, a rarity from RARITY_WEIGHTS and then an even pick."""
    rates = recipe_rates(kind, body)
    if rates:
        return rng.choices(list(rates), weights=list(rates.values()))[0]
    by_rank = pool(kind)
    weights = {r: w for r, w in RARITY_WEIGHTS[kind].items() if by_rank.get(r)}
    rank = rng.choices(list(weights), weights=list(weights.values()))[0]
    return rng.choice(by_rank[rank])


def new_gun_record(state, gun_id, uid):
    """A level-1 doll in the save's gun_with_user_info format."""
    ids = [int(r["id"]) for r in state.get("gun_with_user_info", [])]
    rec = {
        "id": str(max(ids, default=0) + 1), "user_id": str(uid), "gun_id": str(gun_id),
        "gun_exp": "0", "gun_level": "1", "team_id": "0", "if_modification": "0",
        "location": "0", "position": "0",
        "life": str(gun_life(gun_id)),
        "ammo": "0", "mre": "0", "pow": "0", "hit": "0", "dodge": "0", "rate": "0",
        "skill1": "1", "skill2": "1" if int(guns()[gun_id]["skill2"] or 0) else "0", "fix_end_time": "0", "is_locked": "0", "number": "1",
        "equip1": "0", "equip2": "0", "equip3": "0", "equip4": "0",
        "favor": "0", "max_favor": "1000000", "favor_toplimit": "1000000", "soul_bond": "0",
        "skin": "0", "can_click": "0", "soul_bond_time": "0", "special_effect": "0", "is_collect": "0",
    }
    state.setdefault("gun_with_user_info", []).append(rec)
    return rec


def _add(user_info, key, delta):
    """Add to a numeric user_info field, keeping its stored type (the save mixes str/int)."""
    cur = user_info.get(key, 0)
    val = int(cur) + delta
    user_info[key] = str(val) if isinstance(cur, str) else val


def _use_item(state, item_id, count=1):
    for it in state.get("item_with_user_info", []):
        if str(it["item_id"]) == item_id:
            have = int(it["number"])
            it["number"] = str(max(0, have - count)) if isinstance(it["number"], str) else max(0, have - count)
            return min(have, count)
    return 0


def develop(state, uid, body, rng=random):
    kind = "heavy" if int(body.get("input_level") or 0) > 0 else "standard"
    gun_id = roll_gun(kind, rng, body)
    ui = state["user_info"]
    for res in ("mp", "ammo", "mre", "part"):
        _add(ui, res, -int(body.get(res) or 0))
    slot = int(body["build_slot"])
    acts = [a for a in state.get("develop_act_info") or [] if int(a["build_slot"]) != slot]
    acts.append({"build_slot": slot, "start_time": int(time.time()), "gun_id": gun_id, "wish_gun": 0})
    state["develop_act_info"] = acts
    return {"gun_id": str(gun_id)}


def quick_develop(state, body):
    slot = int(body["build_slot"])
    for a in state.get("develop_act_info") or []:
        if int(a["build_slot"]) == slot:
            a["start_time"] = 0          # long finished
            _use_item(state, QUICK_CONTRACT_ITEM)
    return "1"


def _collect(state, uid, act):
    rec = new_gun_record(state, int(act["gun_id"]), uid)
    return {"build_slot": int(act["build_slot"]), "gun_with_user_id": rec["id"], "gun_id": rec["gun_id"]}


def finish_develop(state, uid, body):
    slot = int(body["build_slot"])
    acts = state.get("develop_act_info") or []
    act = next((a for a in acts if int(a["build_slot"]) == slot), None)
    if act is None:
        return None
    state["develop_act_info"] = [a for a in acts if a is not act]
    got = _collect(state, uid, act)
    return {"gun_with_user_add": {"gun_with_user_id": got["gun_with_user_id"], "gun_id": got["gun_id"]}}


def retire(state, gun_with_user_ids):
    """Gun/retireGun (body: list of gun_with_user_id). Removes the dolls and refunds each
    doll's retire* resources from the gun table, times its link count. Reply: "1"."""
    ids = {str(i) for i in gun_with_user_ids or []}
    keep, refund = [], {"mp": 0, "ammo": 0, "mre": 0, "part": 0}
    for g in state.get("gun_with_user_info", []):
        if str(g["id"]) in ids:
            row = guns().get(int(g["gun_id"]), {})
            for res in refund:
                refund[res] += int(row.get("retire" + res) or 0) * int(g.get("number") or 1)
        else:
            keep.append(g)
    state["gun_with_user_info"] = keep
    for res, n in refund.items():
        _add(state["user_info"], res, n)
    return "1"


# T-Doll build slots are the odd numbers up to user_info.max_build_slot (equipment uses the
# even ones), so a 16-slot account has 8 doll slots: 1, 3, ..., 15.
def free_gun_slots(state):
    busy = {int(a["build_slot"]) for a in state.get("develop_act_info") or []}
    top = int(state["user_info"].get("max_build_slot") or 16)
    return [s for s in range(1, top + 1, 2) if s not in busy]


def batch_develop(state, uid, body, rng=random):
    """Gun/developMultiGun: build_multi dolls with one recipe, each in a free slot.
    Resources/contracts are deducted by the client too; the save mirrors that."""
    kind = "heavy" if int(body.get("input_level") or 0) > 0 or int(body.get("build_heavy") or 0) else "standard"
    count = int(body.get("build_multi") or 1)
    quick = bool(int(body.get("build_quick") or 0))
    slots = free_gun_slots(state)[:count] if not quick else list(range(count))
    ui = state["user_info"]
    for res in ("mp", "ammo", "mre", "part"):
        _add(ui, res, -int(body.get(res) or 0) * len(slots))
    if quick:
        out = []
        for _ in slots:
            _use_item(state, QUICK_CONTRACT_ITEM)
            rec = new_gun_record(state, roll_gun(kind, rng, body), uid)
            out.append({"gun_with_user_add": {"gun_with_user_id": rec["id"], "gun_id": rec["gun_id"]}})
        return out
    now, ids = int(time.time()), []
    acts = state.setdefault("develop_act_info", [])
    for slot in slots:
        gun_id = roll_gun(kind, rng, body)
        acts.append({"build_slot": slot, "start_time": now, "gun_id": gun_id, "wish_gun": 0})
        ids.append({"id": gun_id, "slot": slot})
    return {"gun_ids": ids}


def finish_all_develop(state, uid, body):
    """Collect every finished build; with is_cost_item3, also those still running (1 contract each)."""
    now, quick = int(time.time()), bool(int(body.get("is_cost_item3") or 0))
    done, keep, cost = [], [], 0
    for a in state.get("develop_act_info") or []:
        dur = int(guns()[int(a["gun_id"])]["develop_duration"])
        if int(a["start_time"]) + dur <= now or quick:
            if int(a["start_time"]) + dur > now:
                cost += _use_item(state, QUICK_CONTRACT_ITEM)
            done.append(_collect(state, uid, a))
        else:
            keep.append(a)
    state["develop_act_info"] = keep
    return {"gun_with_user_add_list": done, "cost_item3_num": cost}


# --- anchored construction (wish builds, event): the save's wish_gun_with_user_info [{"id", "user_id", "event_id",
# "wish_gun", "wish_gun_probability", "wish_gun_probability_add", "wish_gun_count", "wish_gun_num", ...}]
#   Gun/setWishGun {"event_id", "gun_id"} -> {"wish_gun_probability", "wish_gun_probability_add"}
#   Gun/wishGunDevelop {"event_id", "build_slots": [..], "if_quick"} -> {"develop_result": [...],
#     "wish_gun_with_user": row, "special_develop_quickInput": 0}; a result is {"gun_id", "slot",
#     "wish_gun"} (timed, into develop_act_info) or {"gun_with_user_id", "gun_id", "wish_gun"} (quick)
#     (RequestWishGunDevel). wish_gun is the anchored doll's id (0 with none): the client plays the anchored
#     get animation when the doll built is that one (DevelopAction.wishGunId).
# The event's condition (event_info, read by FactoryWishGunData$$CreateEventInfo) gives the pool (develop_type 1
# standard, 2 heavy), each doll's guaranteed build (wish_griffin_num: 50 standard 5-star, 25 heavy 5-star, ...)
# and how many anchored dolls end the event (wish_gun_num). Rates are in 1/10000 (shown as rate / 100 %).
# Counters are per doll (wish_gun_count "gun:builds"), so a doll newly picked starts at 0.
# APPROXIMATION: the live rate curve is server-side. A build starts at the doll's base rate (its best recipe's
# official rate, as the live server's wish_gun_probability matches; without the rates, its rarity's share of
# RARITY_WEIGHTS split evenly among that rarity's dolls), each miss adds the doll's
# rank_weight_add_num / 100 (1200 for a standard 5-star: +0.12%), and the guaranteed build always hits.
DEFAULT_GUARANTEE = {"standard": 50, "heavy": 25}


@lru_cache(maxsize=1)
def _template_events():
    from . import config
    import json
    try:
        return json.loads(config.PLAYER_TEMPLATE.read_text("utf-8-sig")).get("event_info") or {}
    except (OSError, ValueError):
        return {}


def wish_event(state, event_id):
    """{"kind", "guarantee": {gun_id: builds}, "add": {gun_id: rate per miss}, "limit"} from the event's condition."""
    row = (state.get("event_info") or {}).get(str(event_id)) or _template_events().get(str(event_id)) or {}
    cond = dict(p.split(":", 1) for p in str(row.get("condition") or "").split(";") if ":" in p)
    ids = [int(x) for x in cond.get("gun_pool", "").split(",") if x.strip()]
    counts = [int(x) for x in cond.get("wish_griffin_num", "").split(",") if x.strip()]
    adds = [int(x) // 100 for x in cond.get("rank_weight_add_num", "").split(",") if x.strip()]
    return {"kind": "heavy" if cond.get("develop_type") == "2" else "standard",
            "guarantee": dict(zip(ids, counts)), "add": dict(zip(ids, adds)), "limit": int(cond.get("wish_gun_num") or 1)}


def _per_miss(event, gun_id):
    return event["add"].get(gun_id) or base_rate(event["kind"], gun_id)


def base_rate(kind, gun_id):
    """A doll's chance in one build of that kind, in 1/10000: its best recipe's official rate."""
    listed = [r["rates"][gun_id] for r in craft_rates().get(kind) or [] if gun_id in r["rates"]]
    if listed:
        return max(1, round(10000 * max(listed)))
    by_rank = pool(kind)
    weights = {r: w for r, w in RARITY_WEIGHTS[kind].items() if by_rank.get(r)}
    rank = int(guns()[gun_id]["rank"])
    if rank not in weights:
        return 1
    return max(1, round(10000 * weights[rank] / sum(weights.values()) / len(by_rank[rank])))


def _wish_row(state, event_id):
    rows = state.setdefault("wish_gun_with_user_info", [])
    row = next((r for r in rows if str(r["event_id"]) == str(event_id)), None)
    if row is None:
        row = {"id": str(max((int(r["id"]) for r in rows), default=0) + 1), "user_id": str(state["user_info"].get("user_id", "")),
               "event_id": str(event_id), "wish_gun": "0", "wish_gun_probability": "0", "wish_gun_probability_add": "0",
               "wish_gun_count": "", "wish_gun_num": "", "end_time": "0", "start_time": "0"}
        rows.append(row)
    return row


def _counts(text):
    return {int(k): int(v) for k, v in (p.split(":") for p in str(text or "").split(",") if ":" in p)}


def _bump(counts, gid, reset=False):
    """"gun:n,..." with gid's n raised by one (or set to 0). The save's rows read as builds since the last hit
    (wish_gun_count, 0 after one) and dolls got (wish_gun_num)."""
    pairs = dict(p.split(":") for p in str(counts or "").split(",") if ":" in p)
    pairs[str(gid)] = "0" if reset else str(int(pairs.get(str(gid), 0)) + 1)
    return ",".join(f"{k}:{v}" for k, v in pairs.items())


def _wish_ended(row, event):
    return sum(_counts(row["wish_gun_num"]).values()) >= event["limit"]


def _set_rates(row, event):
    """The picked doll's base rate and what its misses so far have added."""
    wish = int(row["wish_gun"] or 0)
    if wish not in guns():
        return
    base = base_rate(event["kind"], wish)
    row["wish_gun_probability"] = str(base)
    row["wish_gun_probability_add"] = str(_per_miss(event, wish) * _counts(row["wish_gun_count"]).get(wish, 0))


def set_wish_gun(state, body):
    body = body or {}
    gid = int(body.get("gun_id") or 0)
    if gid not in guns():
        return None
    event = wish_event(state, body.get("event_id") or 0)
    row = _wish_row(state, body.get("event_id") or 0)
    if _wish_ended(row, event):
        return None
    row["wish_gun"] = str(gid)
    _set_rates(row, event)
    return {"wish_gun_probability": int(row["wish_gun_probability"]), "wish_gun_probability_add": int(row["wish_gun_probability_add"])}


def wish_develop(state, uid, body, rng=random):
    body = body or {}
    event = wish_event(state, body.get("event_id") or 0)
    row = _wish_row(state, body.get("event_id") or 0)
    wish = int(row["wish_gun"] or 0)
    quick = bool(int(body.get("if_quick") or 0))
    out, now = [], int(time.time())
    for slot in [int(x) for x in body.get("build_slots") or []]:
        anchored = wish in guns() and not _wish_ended(row, event)
        hit = False
        if anchored:
            built = _counts(row["wish_gun_count"]).get(wish, 0) + 1          # this build's number for the doll
            guarantee = event["guarantee"].get(wish) or DEFAULT_GUARANTEE[event["kind"]]
            rate = base_rate(event["kind"], wish) + _per_miss(event, wish) * (built - 1)
            hit = built >= guarantee or rng.random() < rate / 10000
        gid = wish if hit else roll_gun(event["kind"], rng)
        if hit:
            row["wish_gun_num"] = _bump(row["wish_gun_num"], wish)
            row["wish_gun_count"] = _bump(row["wish_gun_count"], wish, reset=True)
        elif anchored:
            row["wish_gun_count"] = _bump(row["wish_gun_count"], wish)
        _set_rates(row, event)
        target = wish if anchored else 0
        if quick:
            _use_item(state, QUICK_CONTRACT_ITEM)
            rec = new_gun_record(state, gid, uid)
            # RequestWishGunDevel reads these two as strings, wish_gun as a number
            out.append({"gun_with_user_id": str(rec["id"]), "gun_id": str(rec["gun_id"]), "wish_gun": target})
        else:
            acts = [a for a in state.get("develop_act_info") or [] if int(a["build_slot"]) != slot]
            acts.append({"build_slot": slot, "start_time": now, "gun_id": gid, "wish_gun": target})
            state["develop_act_info"] = acts
            out.append({"gun_id": gid, "slot": slot, "wish_gun": target})
    # the client finds the event to update by this row's event_id (a number); without it the reply throws
    wish_row = {k: int(row[k] or 0) for k in ("event_id", "wish_gun", "wish_gun_probability", "wish_gun_probability_add")}
    wish_row.update({k: str(row[k] or "") for k in ("wish_gun_count", "wish_gun_num")})
    return {"develop_result": out, "wish_gun_with_user": wish_row, "special_develop_quickInput": 0}
