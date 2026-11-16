"""Arena Breakout minigame (campaign -73): Mission/*Breakout calls.

Missions 11832-11834 are played as phases (stc breakout_phase: mission, order). Battles run on the
client (GF.Tarkov); the server keeps the run, which the client also reads at login:
  breakout_phase_with_user_info {"user_id", "mission_id", "breakout_phase_order" (the phase id),
      "team": "<leader>-<lv>|<id>-<lv>,...", "breakout_item1_package" / "breakout_item3_package" /
      "tmp_package": comma lists of breakout_item ids, "shopping_breakout_item": "<item>:<stock>,...",
      "resource": "breakout_mre:<n>;breakout_part:<n>", "organize_package_order",
      "last_battleinfo" / "mission_battleinfo": "enemy_die:<n>;gun_die:<n>;duration:<s>"}
Reply formats (from the client's handlers):
  Mission/startBreakoutMission {"mission_id"} -> {"team", "resource", "shopping_breakout_item"}
  Mission/teamBreakout {"team"} -> {"resource"}
  Mission/shoppingBreakout {"breakout_item1_package", "breakout_item3_package"} -> {"resource",
      "shopping_breakout_item"}
  Mission/organizePackage {"organize_package_order", "breakout_item1_package"} -> {}
  Mission/breakoutBattleWin {"breakout_phase_order", "breakout_item1_package", "tmp_package", "team",
      "battle_info"} -> {"breakout_phase_with_user_info", "item2_drop": [{"item_id", "item_num"}],
      "reward_prize": [], "mission_keys": {"<key>": n}, "mission_drop": {}} (RequestBOBattleResult; the
      client adds item2_drop and mission_keys itself)
  Mission/abortBreakout {"mission_id"} -> {}
A run starts with game_config breakout_start_part parts and the phase's breakout_mre_reg rations; each
won phase adds the next phase's rations and shop stock (breakout_item_inshop). Items cost cost_part and
sell for sold_part (breakout_item); a gun level costs cost_upgrade[level - 2] parts (breakout_gun).
The phase's item_drop ("2-<item>:<n>") and drop_missionkey ("<key>:<n>") are paid on a win; winning a
mission's last phase clears the mission.
APPROXIMATION: the starting team (the first phase's shop guns at level 1, the last one leading), free
hiring of new guns, and carrying nothing over between missions are guesses.
"""
from collections import Counter
from functools import lru_cache

from . import quests, squads, stc

KEY = "breakout_phase_with_user_info"


@lru_cache(maxsize=1)
def _phases():
    return {int(r["id"]): r for r in stc.table("breakout_phase")}


@lru_cache(maxsize=1)
def _guns():
    return {int(r["id"]): r for r in stc.table("breakout_gun")}


@lru_cache(maxsize=1)
def _items():
    return {int(r["id"]): r for r in stc.table("breakout_item")}


def _list(text):
    return [int(x) for x in str(text or "").split(",") if x.strip().lstrip("-").isdigit()]


def _pairs(text, sep=","):
    out = {}
    for part in str(text or "").split(sep):
        k, _, v = part.partition(":")
        if k.strip() and v.strip().lstrip("-").isdigit():
            out[k.strip()] = int(v)
    return out


def _mission_phases(mid):
    return sorted((p for p in _phases().values() if int(p["mission"]) == int(mid)), key=lambda p: int(p["order"]))


def _run(state):
    if not state.get(KEY):          # null in a new account
        state[KEY] = {"user_id": str(state["user_info"].get("user_id", "")), "mission_id": "0", "breakout_phase_order": "0"}
    return state[KEY]


def _resource(run):
    r = _pairs(run.get("resource"), ";")
    return int(r.get("breakout_mre", 0)), int(r.get("breakout_part", 0))


def _set_resource(run, mre, part):
    run["resource"] = f"breakout_mre:{max(0, mre)};breakout_part:{max(0, part)}"


def _team(text):
    """"12-3|5-3,17-3" -> {gun: level} (leader first)."""
    out = {}
    for part in str(text or "").replace("|", ",").split(","):
        gid, _, lv = part.partition("-")
        if gid.strip().lstrip("-").isdigit():
            out[int(gid)] = int(lv) if lv.strip().isdigit() else 1
    return out


def _add_stock(run, phase):
    stock = Counter(_pairs(run.get("shopping_breakout_item")))
    stock.update(_pairs(phase.get("breakout_item_inshop")))
    run["shopping_breakout_item"] = ",".join(f"{k}:{v}" for k, v in sorted(stock.items(), key=lambda kv: int(kv[0])))


def start(state, body):
    mid = int((body or {}).get("mission_id") or 0)
    phases = _mission_phases(mid)
    if not phases:
        return None
    run = _run(state)
    if int(run.get("mission_id") or 0) != mid or int(run.get("breakout_phase_order") or 0) not in {int(p["id"]) for p in phases}:
        first = phases[0]
        guns = _list(first["breakout_gun_inshop"])
        run.update(mission_id=str(mid), breakout_phase_order=str(first["id"]),
                   team=(f"{guns[-1]}-1|" + ",".join(f"{g}-1" for g in guns[:-1])).rstrip("|") if guns else "",
                   breakout_item1_package="", breakout_item3_package="", tmp_package="", shopping_breakout_item="",
                   organize_package_order="0", last_battleinfo="", mission_battleinfo="enemy_die:0;gun_die:0;duration:0")
        _set_resource(run, int(first["breakout_mre_reg"] or 0), int(quests._config().get("breakout_start_part") or 220))
        _add_stock(run, first)
    return {"team": run["team"], "resource": run["resource"], "shopping_breakout_item": run["shopping_breakout_item"]}


def _upgrade_cost(gid, frm, to):
    costs = _list(_guns().get(gid, {}).get("cost_upgrade"))
    return sum(costs[lv - 2] for lv in range(max(2, frm + 1), to + 1) if 0 <= lv - 2 < len(costs))


def team(state, body):
    run = _run(state)
    new = _team((body or {}).get("team"))
    if not new or not int(run.get("mission_id") or 0) or any(g not in _guns() for g in new):
        return None
    old = _team(run.get("team"))
    cost = sum(_upgrade_cost(g, old.get(g, 1), lv) for g, lv in new.items())
    mre, part = _resource(run)
    if cost > part:
        return None
    _set_resource(run, mre, part - cost)
    run["team"] = str((body or {}).get("team"))
    return {"resource": run["resource"]}


def shopping(state, body):
    body, run = body or {}, _run(state)
    if not int(run.get("mission_id") or 0):
        return None
    before = Counter(_list(run.get("breakout_item1_package")) + _list(run.get("breakout_item3_package")))
    p1, p3 = str(body.get("breakout_item1_package") or "").strip(","), str(body.get("breakout_item3_package") or "").strip(",")
    after = Counter(_list(p1) + _list(p3))
    bought, sold = after - before, before - after
    stock = Counter(_pairs(run.get("shopping_breakout_item")))
    if any(n > stock.get(str(i), 0) for i, n in bought.items()) or any(i not in _items() for i in after):
        return None
    cost = sum(int(_items()[i]["cost_part"] or 0) * n for i, n in bought.items())
    refund = sum(int(_items().get(i, {}).get("sold_part") or 0) * n for i, n in sold.items())
    mre, part = _resource(run)
    if cost > part + refund:
        return None
    for i, n in bought.items():
        stock[str(i)] -= n
    run["shopping_breakout_item"] = ",".join(f"{k}:{v}" for k, v in sorted(stock.items(), key=lambda kv: int(kv[0])))
    run["breakout_item1_package"], run["breakout_item3_package"] = p1, p3
    _set_resource(run, mre, part - cost + refund)
    return {"resource": run["resource"], "shopping_breakout_item": run["shopping_breakout_item"]}


def organize(state, body):
    body, run = body or {}, _run(state)
    run["organize_package_order"] = str(body.get("organize_package_order") or "0")
    run["breakout_item1_package"] = str(body.get("breakout_item1_package") or "").strip(",")
    return {}


def _add_info(total, part):
    a, b = _pairs(total, ";"), _pairs(part, ";")
    keys = ("enemy_die", "gun_die", "duration")
    return ";".join(f"{k}:{a.get(k, 0) + b.get(k, 0)}" for k in keys)


def battle_win(state, body):
    body, run = body or {}, _run(state)
    pid = int(body.get("breakout_phase_order") or run.get("breakout_phase_order") or 0)
    phase = _phases().get(pid)
    if phase is None or int(phase["mission"]) != int(run.get("mission_id") or 0):
        return None
    for k in ("breakout_item1_package", "tmp_package", "team"):
        if k in body:
            run[k] = str(body[k] or "").strip(",")
    info = str(body.get("battle_info") or "")
    run["last_battleinfo"] = info
    run["mission_battleinfo"] = _add_info(run.get("mission_battleinfo"), info)
    drops = []
    for part in str(phase.get("item_drop") or "").split(","):
        kind, _, rest = part.partition("-")
        iid, _, n = rest.partition(":")
        if iid.strip().isdigit():
            row = squads._item(state, iid.strip())
            row["number"] = str(int(row["number"]) + int(n or 1))
            drops.append({"item_id": int(iid), "item_num": int(n or 1)})
    keys = {k: v for k, v in _pairs(phase.get("drop_missionkey")).items()}
    nxt = next((p for p in _mission_phases(phase["mission"]) if int(p["order"]) == int(phase["order"]) + 1), None)
    if nxt is not None:
        run["breakout_phase_order"] = str(nxt["id"])
        mre, part = _resource(run)
        _set_resource(run, mre + int(nxt["breakout_mre_reg"] or 0), part)
        _add_stock(run, nxt)
    else:
        from . import missions
        rec = missions._mission_record(state, int(phase["mission"]))
        rec["win_counter"] = str(int(rec["win_counter"]) + 1)
        rec["counter"] = str(max(int(rec["counter"]), int(rec["win_counter"])))
        rec["medal1"] = "1"
        missions._open_next(state, missions._missions().get(int(phase["mission"]), {}))
        quests.record(state, "mission_win")
        run["mission_id"] = "0"
    return {KEY: dict(run), "item2_drop": drops, "reward_prize": [], "mission_keys": keys, "mission_drop": {}}


def abort(state, body):
    run = _run(state)
    run["mission_id"] = "0"
    return {}
