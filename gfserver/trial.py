"""Defense Drill (Mission/startTrial, startTrialExercise, endTrialExercise, abortTrial).

The save keeps the run in trial_exercise_info (trial_id = current wave, 0 when no run is open;
start_trial_id, team_ids "1,4,6", battle_team, guns_info / guns_dps as JSON strings keyed team ->
gun -> {life} / {dps}) and the record in trial_with_user_info (max_trial, max_time, counter).
Waves are catchdata trial_info rows; a row with a prize_id is a checkpoint, where the client
restores the echelons to full life (DefenseTrialInfo.isCheckPoint).

Replies (RequestDefenseTrialBattleFinish / RequestDefenseTrialAbort):
  - startTrial, startTrialExercise: "1" (the client takes trial_stamina_cost from bp itself)
  - endTrialExercise, run goes on: [] (an array means "next wave")
  - run over (lost, last wave won, or abortTrial):
    {reward_voucher: <item 44 count>, prize: [{id: <prize id>}], guns_real_life, guns_dps}
A run pays the reward_voucher of the highest wave it cleared (the column is a running total) and
the prize of every checkpoint it cleared. The next run starts after the last checkpoint of the best
wave ever cleared (cleared 141-149: next start 141); Index/index sends it as start_trial_id.
"""
import json
import time
from functools import lru_cache

from . import stc
from .factory import _add
from .quests import _reward, grant, prizes

VOUCHER = 44


@lru_cache(maxsize=1)
def waves():
    return {int(r["id"]): r for r in stc.catch("trial_info")}


def _stamina_cost():
    row = next((r for r in stc.catch("game_config_info") if r["parameter_name"] == "trial_stamina_cost"), None)
    return int(row["parameter_value"]) if row else 0


def _run(state):
    if not state.get("trial_exercise_info"):        # null in a new account
        state["trial_exercise_info"] = {"trial_id": "0", "team_ids": "", "battle_team": "0", "start_trial_id": "0",
                                        "guns_info": "{}", "guns_dps": "{}", "cheat": "0"}
    return state["trial_exercise_info"]


def _record(state):
    if not state.get("trial_with_user_info"):
        state["trial_with_user_info"] = {"max_trial": "0", "max_time": "0", "counter": "0"}
    return state["trial_with_user_info"]


def _loads(text):
    try:
        out = json.loads(text or "{}")
    except ValueError:
        return {}
    return out if isinstance(out, dict) else {}


def start(state, body):
    body = body or {}
    first = int(body.get("start_trial_id") or 1)
    if first not in waves():
        return None
    run = _run(state)
    run.update({"trial_id": str(first), "start_trial_id": str(first),
                "team_ids": str(body.get("team_ids") or ""), "battle_team": str(body.get("battle_team") or 0),
                "guns_info": "{}", "guns_dps": "{}"})
    ui = state["user_info"]
    _add(ui, "bp", -min(int(ui.get("bp") or 0), _stamina_cost()))
    return "1"


def start_battle(state, body):
    _run(state)["battle_team"] = str((body or {}).get("team_id") or 0)
    return "1"


def _report(run, battle_guns):
    """Save one battle's lives and DPS under the battle echelon."""
    team = str(run.get("battle_team") or 0)
    lives, dps = _loads(run.get("guns_info")), _loads(run.get("guns_dps"))
    for gid, g in (battle_guns or {}).items():
        if isinstance(g, dict):
            lives.setdefault(team, {})[str(gid)] = {"life": int(g.get("life") or 0)}
            old = dps.setdefault(team, {}).get(str(gid), {}).get("dps", 0)
            dps[team][str(gid)] = {"dps": old + int(g.get("dps") or 0)}
    run["guns_info"], run["guns_dps"] = json.dumps(lives), json.dumps(dps)


def _finish(state, last_cleared, now):
    """Close the run and pay for the waves cleared since start_trial_id."""
    run = _run(state)
    first = int(run.get("start_trial_id") or 0)
    cleared = [w for w in range(first, last_cleared + 1) if w in waves()]
    reply = {"guns_real_life": _loads(run.get("guns_info")), "guns_dps": _loads(run.get("guns_dps"))}
    vouchers = int(waves()[cleared[-1]]["reward_voucher"]) if cleared else 0
    reply["reward_voucher"] = vouchers
    if vouchers:
        grant(state, {"item_ids": f"{VOUCHER}-{vouchers}"})
    reply["prize"] = []
    for w in cleared:
        pid = int(waves()[w]["prize_id"] or 0)
        if pid in prizes():
            grant(state, _reward(prizes()[pid]))
            reply["prize"].append({"id": pid})
    run["trial_id"] = "0"
    run["start_trial_id"] = str(restart_wave(int(_record(state).get("max_trial") or 0)))
    run["last_battle_finish_time"] = str(now)
    return reply


def restart_wave(best):
    """The wave after the last checkpoint at or below the best wave cleared (1 before the first)."""
    checkpoints = [w for w, r in waves().items() if int(r["prize_id"] or 0) and w <= best]
    return max(checkpoints, default=0) + 1


def end_battle(state, body, now=None):
    body, now = body or {}, int(now or time.time())
    run = _run(state)
    wave = int(run.get("trial_id") or 0)
    if wave not in waves():
        return None
    _report(run, body.get("battle_guns"))
    if not body.get("if_win"):
        return _finish(state, wave - 1, now)
    rec = _record(state)
    _add(rec, "counter", 1)
    if wave > int(rec.get("max_trial") or 0):
        rec["max_trial"], rec["max_time"] = str(wave), str(now)
    if wave + 1 not in waves():
        return _finish(state, wave, now)
    run["trial_id"] = str(wave + 1)
    if int(waves()[wave]["prize_id"] or 0):
        run["guns_info"] = "{}"           # checkpoint: back to full life, as the client does
    return []


def abort(state, body, now=None):
    run = _run(state)
    wave = int(run.get("trial_id") or 0)
    if wave not in waves():
        return {"reward_voucher": 0, "prize": []}
    return _finish(state, wave - 1, int(now or time.time()))
