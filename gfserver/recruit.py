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
  Sangvis/gashaRefresh {"gasha_id", "refresh_type"} / gashaReset {"gasha_id"} -> {"gasha_id"}: refill
APPROXIMATION: draw_type 1 pays the gasha's daily_price ticket and 2 its author_price; draw_param
is the number of draws (1-10). The live server's exact pricing rules are not in the client.
"""
import datetime
import random
import time
from functools import lru_cache

from . import mods, stc
from .factory import _use_item


@lru_cache(maxsize=1)
def gashas():
    return {int(r["id"]): r for r in stc.table("sangvis_gasha")}


@lru_cache(maxsize=1)
def rewards():
    return {int(r["id"]): r for r in stc.table("sangvis_gasha_reward")}


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


def _row(state, gid, now=None):
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
    return row


def _active(now):
    return [gid for gid, g in sorted(gashas().items()) if _ts(g["start_time"]) <= now <= _ts(g["end_time"])]


def _tickets(state):
    return [{"item_id": str(i["item_id"]), "item_num": int(i["number"]), "last_recover_time": str(i.get("last_recover_time") or 0)}
            for i in state.get("item_with_user_info", []) if str(i["item_id"]) in ("604", "605")]


def gasha_index(state, body):
    now = int(time.time())
    return {"event_info": [], "item_info": _tickets(state),
            "sangvis_gasha_list": [_row(state, gid, now) for gid in _active(now)]}


def draw(state, body, rng=random):
    body = body or {}
    gid = int(body.get("gasha_id") or 0)
    if gid not in gashas():
        return None
    row = _row(state, gid)
    pool = _pool(row["gasha_content"])
    count = max(1, min(10, int(body.get("draw_param") or 1)))
    g = gashas()[gid]
    price = g["author_price"] if int(body.get("draw_type") or 1) == 2 else g["daily_price"]
    item, _, per = str(price or "").partition(":")
    units, drawn = [], []
    for _ in range(count):
        left = {k: n for k, n in pool.items() if n > 0}
        if not left:
            break
        if item:
            _use_item(state, item, int(per or 1))
        rid = rng.choices(list(left), weights=list(left.values()))[0]
        pool[rid] -= 1
        drawn.append(rid)
        sid = int(rewards().get(rid, {}).get("sangvis_id") or 0)
        if sid in mods._sangvis():
            rec = mods.new_sangvis_record(state, sid, state["user_info"].get("user_id", ""))
            units.append(rec)
    row["gasha_content"] = _fmt(pool)
    counts = [int(x) for x in str(row["draw_type_count"] or "0,0").split(",")] + [0, 0]
    counts[1 if int(body.get("draw_type") or 1) == 2 else 0] += len(drawn)
    row["draw_type_count"] = f"{counts[0]},{counts[1]}"
    hist = [p for p in str(row["gasha_reward"] or "").split(",") if p]
    row["gasha_reward"] = ",".join(hist + [f"{r}:{rewards().get(r, {}).get('sangvis_id', 0)}" for r in drawn])
    row["gasha_area"] = ",".join(str(r) for r in drawn[-3:])
    return {"gasha_id": gid, "sangvis_gasha_info": row, "sangvis_info": units, "prize_info": drawn}


def recover(state, body):
    return {"event_info": [], "item_info": _tickets(state), "daily_free": 0, "author_free": 0}


def refill(state, body):
    gid = int((body or {}).get("gasha_id") or 0)
    if gid not in gashas():
        return None
    row = _row(state, gid)
    row.update({"gasha_content": gashas()[gid]["gasha_reward_ids"], "gasha_area": "", "gasha_reward": "",
                "draw_type_count": "0,0", "last_refresh_time": str(int(time.time()))})
    return {"gasha_id": gid}
