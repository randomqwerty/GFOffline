"""Coalition recruitment ("capture"): box draws from the Sangvis gasha pools.

Each gasha (stc sangvis_gasha) has a pool, gasha_reward_ids "reward:count,..."; a draw takes
rewards out of the pool weighted by what is left, and every reward is a Coalition unit
(stc sangvis_gasha_reward.sangvis_id). The pools left are kept in the save's "_sangvis_gasha"
{gasha_id: row}, in the row format the client reads (SanvisCaptureGasha$$SetDynamicData):
  {"id", "user_id", "gasha_id", "draw_type_count", "gasha_content", "gasha_area", "gasha_reward",
   "can_reset", "last_refresh_time", "start_time", "end_time"}

Reply formats (from the client's handlers):
  Sangvis/gasha       {"event_info": [], "item_info": [{"item_id", "item_num", "last_recover_time"}],
                      "sangvis_gasha_list": [row]}   (was a canned recording)
  Sangvis/gashaDraw   {"gasha_id", "draw_type", "draw_param", "if_event"} -> every key guarded:
                      {"gasha_id", "sangvis_gasha_info": row, "sangvis_info": [new unit records],
                      "prize_info": [reward ids]}   RequestSangvisGashaDraw
  Sangvis/gashaRecover {"common_only"} -> {"item_info": [...], "event_info": [], "daily_free",
                      "author_free"}                RequestRecoverGasha
  Sangvis/gashaRefresh {"gasha_id", "refresh_type": 0} -> the row: new targets on show
  Sangvis/gashaReset {"gasha_id"} -> {"gasha_id"}: the pool refilled
gasha_area is the three targets on show, "reward,reward,reward" (repeats allowed), picked by what is left in the
pool. The player may pick them again (gashaRefresh, "Search Again") once refresh_rate seconds (72 hours) have passed
since last_refresh_time; SangvisCaptureController$$Count counts down from last_refresh_time + refresh_rate and
enables the button. A capture only replaces its slot and leaves the timer alone. gasha_reward is every target shown so far, "reward:sangvis_id".
The client parses each area entry as a number, so an empty area never finishes loading the capture screen.
A capture (recorded live): draw_type 1 spends an electronic impulse (daily_price, item 604) on the target in slot
draw_param (from 0); draw_type 2 spends an Aid Commission (author_price, item 605) per draw_param and always catches
a target on show at random. Either way the slot gets a new target. A catch takes the reward out of the pool and
gives the unit; the chance is by its stars (reward_type 5 1-star, 3 2-star, 1 and 2 3-star; type 2 picks the unit
from sangvis_id by single_num_weight): CATCH_CHANCE. 1- and 2-star units get a size (sangvis_shape_n 1-5, XS-XL)
by SIZE_WEIGHTS; 3-star ones have none (0). A miss leaves the pool and pays one of the Coalition material prizes in
prize_info (a recorded 2-star miss paid prize 4153, item 515 x100).
Impulses come back one per establish 901's parameter_1 seconds ("seconds:1"), up to its parameter_2.
APPROXIMATION: the chances, sizes and the miss prize's kind (FAIL_PRIZES, the amount by the target's stars) come
from player reports and one recorded miss.
"""
import datetime
import random
import time
from functools import lru_cache

from . import mods, quests, squads, stc
from .factory import _use_item


@lru_cache(maxsize=1)
def gashas():
    return {int(r["id"]): r for r in stc.table("sangvis_gasha")}


@lru_cache(maxsize=1)
def rewards():
    return {int(r["id"]): r for r in stc.table("sangvis_gasha_reward")}


CATCH_CHANCE = {1: 1.0, 2: 0.5, 3: 0.25}
STARS = {5: 1, 3: 2, 1: 3, 2: 3}                  # sangvis_gasha_reward.reward_type -> stars
SIZE_WEIGHTS = {1: 2, 2: 17, 3: 60, 4: 16, 5: 5}  # XS, S, M, L, XL
# a miss pays one kind (combat reports, 514, 516, 515), the amount by the target's stars (80 / 100 / 120)
FAIL_PRIZES = ((4143, 4144, 4145), (4146, 4147, 4148), (4149, 4150, 4151), (4152, 4153, 4154))
IMPULSE, AID = "604", "605"
IMPULSE_ROOM = "901"
LIVE_UNIT = {"sangvis_resolution": "0", "sangvis_resolution_level": "0", "skill1": "0", "skill2": "0",
             "skill_advance": "0", "favor": "500000", "max_favor": "500000"}


def _ts(text):
    try:
        return int(time.mktime(datetime.datetime.strptime(str(text), "%Y-%m-%d %H:%M:%S").timetuple()))
    except ValueError:
        return 0


def _pool(text):
    out = {}
    for part in str(text or "").split(","):
        if ":" in part:
            k, n = part.split(":")[:2]
            out[int(k)] = int(n)
    return out


def _fmt(pool):
    return ",".join(f"{k}:{n}" for k, n in pool.items())


def _row(state, gid, now=None, rng=random):
    now = int(now or time.time())
    rows = state.setdefault("_sangvis_gasha", {})
    g = gashas()[gid]
    row = rows.get(str(gid))
    if row is None:
        row = rows[str(gid)] = {
            "id": str(gid + 1), "user_id": str(state["user_info"].get("user_id", "")), "gasha_id": str(gid),
            "draw_type_count": "0,0", "gasha_content": g["gasha_reward_ids"], "gasha_area": "", "gasha_reward": "",
            "can_reset": "0", "last_refresh_time": str(now), "start_time": _ts(g["start_time"]),
            "end_time": _ts(g["end_time"])}
    if not _area(row):
        _show(row, rng)
    return row


def _area(row):
    return [int(a) for a in str(row.get("gasha_area") or "").split(",") if a.strip().lstrip("-").isdigit()]


def _show(row, rng=random):
    """Pick the three targets on show from what is left in the pool, and add them to the ones seen."""
    left = {k: n for k, n in _pool(row["gasha_content"]).items() if n > 0}
    if not left:
        left = _pool(gashas()[int(row["gasha_id"])]["gasha_reward_ids"])
    area = rng.choices(list(left), weights=list(left.values()), k=3)
    row["gasha_area"] = ",".join(str(a) for a in area)
    _seen(row, area)


def _seen(row, ids):
    seen = {}
    for part in str(row.get("gasha_reward") or "").split(","):
        k, _, v = part.partition(":")
        if k.strip().isdigit():
            seen[int(k)] = v
    for r in ids:
        seen.setdefault(int(r), str(rewards().get(int(r), {}).get("sangvis_id", 0)))
    row["gasha_reward"] = ",".join(f"{k}:{v}" for k, v in seen.items())


def _impulse_rule(state):
    """(seconds per impulse, most held) from the impulse facility's level."""
    row = squads._establish(state, IMPULSE_ROOM)
    every = str(row.get("parameter_1") or "60480:1").partition(":")[0]
    return max(1, int(every or 60480)), int(row.get("parameter_2") or 9)


def recover_impulses(state, now=None):
    now = int(now or time.time())
    every, cap = _impulse_rule(state)
    item = squads._item(state, IMPULSE)
    have, last = int(item["number"]), int(item.get("last_recover_time") or 0)
    if have >= cap or not last:
        item["last_recover_time"] = str(now)
        return
    n = (now - last) // every
    if n > 0:
        add = min(n, cap - have)
        item["number"] = str(have + add)
        item["last_recover_time"] = str(now if have + add >= cap else last + n * every)


def _spend(state, item_id, n, now):
    """Spend a ticket; an impulse spent from full starts its recovery clock now."""
    item = squads._item(state, item_id)
    if int(item["number"]) < n:
        return False
    if item_id == IMPULSE and int(item["number"]) >= _impulse_rule(state)[1]:
        item["last_recover_time"] = str(now)
    _use_item(state, item_id, n)
    return True


def _unit_id(reward, rng):
    """The unit a reward gives: its sangvis_id, or one of them by single_num_weight."""
    ids = [int(x) for x in str(reward.get("sangvis_id") or "").split(",") if x.strip().isdigit()]
    weights = {}
    for part in str(reward.get("single_num_weight") or "").split(","):
        k, _, v = part.partition(":")
        if k.strip().isdigit() and v.strip().isdigit():
            weights[int(k)] = int(v)
    if len(ids) > 1:
        return rng.choices(ids, weights=[weights.get(i, 1) for i in ids])[0]
    return ids[0] if ids else 0


def _new_target(row, slot, rng):
    left = {k: n for k, n in _pool(row["gasha_content"]).items() if n > 0} or _pool(gashas()[int(row["gasha_id"])]["gasha_reward_ids"])
    area = (_area(row) + [0, 0, 0])[:3]
    area[slot] = rng.choices(list(left), weights=list(left.values()))[0]
    row["gasha_area"] = ",".join(str(a) for a in area)
    _seen(row, [area[slot]])


def _stars(reward):
    return STARS.get(int(reward.get("reward_type") or 5), 1)


def _unit(state, reward, rng):
    sid = _unit_id(reward, rng)
    if sid not in mods._sangvis():
        return None
    stars = _stars(reward)
    rec = mods.new_sangvis_record(state, sid, state["user_info"].get("user_id", ""))
    size = rng.choices(list(SIZE_WEIGHTS), weights=list(SIZE_WEIGHTS.values()))[0] if stars < 3 else 0
    rec.update(LIVE_UNIT, sangvis_advance=str(stars), sangvis_shape_n=str(size),
               skill3="1" if int(mods._sangvis()[sid].get("skill3") or 0) else "0")
    return rec


def _active(now):
    return [gid for gid, g in sorted(gashas().items()) if _ts(g["start_time"]) <= now <= _ts(g["end_time"])]


def _tickets(state):
    return [{"item_id": str(i["item_id"]), "item_num": int(i["number"]), "last_recover_time": str(i.get("last_recover_time") or 0)}
            for i in state.get("item_with_user_info", []) if str(i["item_id"]) in ("604", "605")]


def gasha_index(state, body):
    now = int(time.time())
    recover_impulses(state, now)
    return {"event_info": [], "item_info": _tickets(state),
            "sangvis_gasha_list": [_row(state, gid, now) for gid in _active(now)]}


def draw(state, body, rng=random, now=None):
    body, now = body or {}, int(now or time.time())
    gid = int(body.get("gasha_id") or 0)
    if gid not in gashas():
        return None
    recover_impulses(state, now)
    row = _row(state, gid, now, rng=rng)
    aid = int(body.get("draw_type") or 1) == 2
    param = int(body.get("draw_param") or 0)
    tries = [None] * max(1, min(10, param)) if aid else [max(0, min(2, param))]
    pool = _pool(row["gasha_content"])
    units, prizes = [], []
    for slot in tries:
        area = _area(row)
        if len(area) < 3 or not _spend(state, AID if aid else IMPULSE, 1, now):
            break
        if slot is None:
            slot = rng.randrange(3)
        reward = rewards().get(area[slot], {})
        if not aid and rng.random() >= CATCH_CHANCE[_stars(reward)]:
            prize = rng.choice(FAIL_PRIZES)[_stars(reward) - 1]
            quests.grant(state, quests._reward(quests.prizes().get(prize, {})))
            prizes.append(prize)
        else:
            pool[area[slot]] = max(0, pool.get(area[slot], 0) - 1)
            rec = _unit(state, reward, rng)
            if rec is not None:
                units.append(rec)
        row["gasha_content"] = _fmt(pool)
        _new_target(row, slot, rng)
    counts = [int(x) for x in str(row["draw_type_count"] or "0,0").split(",")] + [0, 0]
    counts[1 if aid else 0] += len(tries)
    row["draw_type_count"] = f"{counts[0]},{counts[1]}"
    return {"gasha_id": gid, "sangvis_gasha_info": row, "sangvis_info": units, "prize_info": prizes}


def recover(state, body):
    recover_impulses(state)
    return {"event_info": [], "item_info": _tickets(state), "daily_free": 0, "author_free": 0}


def refresh(state, body, rng=random, now=None):
    """New targets on show, once refresh_rate has passed since the last time; the pool stays."""
    now = int(now or time.time())
    gid = int((body or {}).get("gasha_id") or 0)
    if gid not in gashas():
        return None
    row = _row(state, gid, now, rng=rng)
    if now - int(row.get("last_refresh_time") or 0) >= int(gashas()[gid].get("refresh_rate") or 0):
        _show(row, rng)
        row["last_refresh_time"] = str(now)
    return row


def refill(state, body):
    gid = int((body or {}).get("gasha_id") or 0)
    if gid not in gashas():
        return None
    row = _row(state, gid)
    row.update({"gasha_content": gashas()[gid]["gasha_reward_ids"], "gasha_reward": "",
                "draw_type_count": "0,0", "last_refresh_time": str(int(time.time()))})
    _show(row)
    return {"gasha_id": gid}
