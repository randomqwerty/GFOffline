"""Coalition simulation ("Sangvis duplicate"): three weekly challenges with a hired team.

Stages are server data; their shape is known from a recorded reply:
  {"id", "sangvis_hiringteam_id": "1002", "challenge_type": "1", "enemy_team_id": "940002",
   "gun_in_allys": "<hired team>,<extra allies>", "pass_time": "12", "award_item": "2:400001:10:10000",
   "item_cost": "603:3", "is_night": "0", "map_type": "4", "map_code": "forest",
   "default_team": "3006,3007,3008,3009,3010", "start_time", "end_time"} (a Monday-to-Sunday week).
Each challenge c (1-3) has 5 enemy teams (940001 + 5(c-1) .. +4) and 5 hired teams
(1001 + 5(c-1) .. +4; team t is gun_in_ally 3001 + 5(t-1001) .. +4); each week moves on to the next
pair, lined up so the recorded week gets the recorded team and enemy.
Reply formats (from the client's handlers):
  Sangvis/duplicateIndex {} -> {"sangvis_duplicate_with_user": {"<c>": {"win_counter"}},
      "sangvis_duplicate_info": {"<c>": stage}, "recover_bp_and_item603"} (RequestSangvisDuplicateHire)
  Sangvis/duplicateAward {"challenge_type", "award_item_key"} "1": which award_item entry (from 0) a
      run pays
  Sangvis/duplicateBattlefinish {"challenge_type", "sangvis_duplicate_info_id", "if_win", ...} ->
      {"get_reward_type", "get_reward_id", "get_reward_num", "recover_bp_and_item603"}
      (BattleController$$RequestSangvisSimBattleFinishHandle). recover_bp_and_item603 is a flag, not a
      count: non-zero refills the energy to the maximum and skips the client's own subtraction of the
      stage cost (GameData$$RecoverBPFromRequestJson), so it stays 0.
The reward the client shows is the amount sent here, and the settlement screen labels the bonus:
  defeat sangvis_hiringteam_battle_defeat_awardradio (-10%); finished under pass_time by up to 20% of it
  ..._lesstime_awardradio_1 (+10%), by more ..._lesstime_awardradio_2 (+20%); otherwise ..._moretime_awardradio (0);
  on the challenge's weekdays (sangvis_hiringteam_extra_time "<c>:<weekdays>|...", 0 Sunday, which the
  client counts for every challenge) sangvis_hiringteam_extra_ratio (300 = x3.0).
  Mission/simulation {"m_type": 1, "m_id": <challenge_type>, "count"} (a sweep: the mission detail
      sends the stage's challenge_type as m_id, MissionSelectionMissionDetailController$$StartRaid)
      -> {"item": {"<id>": n}} or {"gift_item": {"<id>": n}} (RequsetSimulationRaid)
Challenge c is mission 1600 + c (1601-1603, duplicate_type 7): the menu's mission detail and sweep
screens show it, and its costbp is the stage's item_cost. The battle itself does not go through the
mission: the box's Battle button clears the selected mission and loads the Battle scene, whose finish
goes to Sangvis/duplicateBattlefinish (BattleDynamicData$$GetEntranceType 4).
A battle costs the stage's item_cost: item 603 first, then the bought 10603 (UserInfo sangvisBpFree /
sangvisBpCharge); game_config item_recover_info_603 "603:6:2:1" gives one back every 2 hours up to 6.
A run pays the chosen award ("type:id:count:limit"; type 1 an item, 2 a gift item), won or lost. The client shows challenge 1 as UpgradeMat, 2 as UpQuality and 3 as a choice of two
SkillMat awards (MissionSelectionSangvisSimDungeonsController$$InitType3UI needs two entries).
APPROXIMATION: the extra allies (EXTRA_ALLIES of gun_in_ally 3501-3743, drawn per week), the map
(the recorded forest map for every stage) and the challenge 2/3 awards (items 514 sangvis_advance_item
and 515/516 sangvis_skill_coin1/2, counts guessed) are guesses; challenge 1's award is the recorded one.
"""
import random
import time
from functools import lru_cache

from . import quests, squads, stc

CHALLENGES = (1, 2, 3)
ENEMY_BASE, TEAM_BASE, ALLY_BASE, ROTATION = 940001, 1001, 3001, 5
EXTRA_ALLIES, EXTRA_RANGE = 15, (3501, 3743)
MISSION_BASE = 1600                       # challenge c is mission 1600 + c
COST_ITEM, COST = "603", 3                # COST when the mission row has no costbp
CHARGE_ITEM = "10603"                     # bought energy, spent after item 603
AWARDS = {1: "2:400001:10:10000",         # recorded: SangvisExp_RapidGrowthDisk x10
          2: "1:514:3:10000",
          3: "1:515:3:10000,1:516:3:10000"}
GIFT = "2"
DAY_OFFSET = -8 * 3600                    # the live server's day runs 00:00 UTC-8 (handlers.SERVER_DAY_TZ)
ANCHOR_WEEK, ANCHOR_INDEX = 1641801600, 1  # the recorded week (2022-01-10) had team 1002 / enemy 940002


@lru_cache(maxsize=1)
def _recover_rule():
    item, top, hours, amount = (quests._config().get("item_recover_info_603") or "603:6:2:1").split(":")
    return item, int(top), int(hours) * 3600, int(amount)


def _week(now):
    """The Monday 00:00 - Sunday 23:59:59 week, in the live server's UTC-8 day."""
    day = (now + DAY_OFFSET) // 86400
    start = (day - (day + 3) % 7) * 86400 - DAY_OFFSET          # 1970-01-01 was a Thursday
    return start, start + 7 * 86400 - 1


@lru_cache(maxsize=1)
def _missions():
    return {int(r["id"]): r for r in stc.table("mission") if MISSION_BASE < int(r["id"]) <= MISSION_BASE + len(CHALLENGES)}


def mission_id(c):
    return MISSION_BASE + int(c)


def _cost(c):
    row = _missions().get(mission_id(c))
    return int(row["costbp"]) if row and int(row.get("costbp") or 0) else COST


def stages(now):
    start, end = _week(now)
    k = ((start - ANCHOR_WEEK) // (7 * 86400) + ANCHOR_INDEX) % ROTATION
    rng = random.Random(start)
    extra_pool = [int(r["id"]) for r in stc.table("gun_in_ally") if EXTRA_RANGE[0] <= int(r["id"]) <= EXTRA_RANGE[1]]
    out = {}
    for c in CHALLENGES:
        team = TEAM_BASE + ROTATION * (c - 1) + k
        members = [ALLY_BASE + ROTATION * (team - TEAM_BASE) + i for i in range(ROTATION)]
        extras = sorted(rng.sample(extra_pool, min(EXTRA_ALLIES, len(extra_pool))))
        out[str(c)] = {
            "id": str(start // 86400 * 10 + c), "sangvis_hiringteam_id": str(team), "challenge_type": str(c),
            "enemy_team_id": str(ENEMY_BASE + ROTATION * (c - 1) + k),
            "gun_in_allys": ",".join(str(i) for i in members + extras), "pass_time": "12",
            "award_item": AWARDS[c], "item_cost": f"{COST_ITEM}:{_cost(c)}", "is_night": "0", "map_type": "4",
            "map_code": "forest", "default_team": ",".join(str(i) for i in members),
            "start_time": start, "end_time": end}
    return out


def _energy(state, now):
    """Item 603 after its recovery; returns the count."""
    item, top, every, amount = _recover_rule()
    row = squads._item(state, item)
    last = int(row.get("last_recover_time") or 0) or now
    have = int(row["number"])
    if have >= top:
        row["last_recover_time"] = str(now)
        return have
    ticks = max(0, (now - last) // every)
    have = min(top, have + ticks * amount)
    row["number"] = str(have)
    row["last_recover_time"] = str(now if have >= top else last + ticks * every)
    return have


def daily_energy(state, now=None):
    """Each new server day tops the free energy of combat simulations (user_info bp) and Coalition simulations (item 603) up to
    sim_energy_recover_max. Energy above that is left alone. A client already running hears of it through _flag."""
    now = int(now or time.time())
    day = (now + DAY_OFFSET) // 86400
    if state.get("_energy_day") == day:
        return
    state["_energy_day"] = day
    top = _config_int("sim_energy_recover_max")
    ui = state["user_info"]
    ui["bp"] = str(max(int(ui.get("bp") or 0), top))
    row = squads._item(state, COST_ITEM)
    row["number"] = str(max(int(row["number"]), top))
    state["_energy_unsent"] = True


def _flag(state, now):
    """recover_bp_and_item603 stays 0 except for a day's refill the client hasn't heard of (see above); the save's energy is brought up to date."""
    _energy(state, now)
    return 1 if state.pop("_energy_unsent", False) else 0


def _charge(state, item, n):
    """Spend the stage cost: item 603, then the bought energy."""
    paid = squads._spend(state, item, n)
    squads._spend(state, CHARGE_ITEM, n - paid)


def _config_int(name):
    return int(quests._config().get(name) or 0)


def _weekday(now):
    """0 Sunday .. 6 Saturday, in the live server's day (GameData$$get_serverWeekday)."""
    return (time.gmtime(now + DAY_OFFSET).tm_wday + 1) % 7


def _day_bonus(c, now):
    day = _weekday(now)
    if day == 0:
        return True
    for part in str(quests._config().get("sangvis_hiringteam_extra_time") or "").split("|"):
        key, _, days = part.partition(":")
        if key == str(c):
            return str(day) in days.split(",")
    return False


def reward_amount(stage, num, won, duration, now):
    """The award after the settlement's time bonus and the weekday bonus."""
    base = int(stage["pass_time"])
    if not won:
        ratio = _config_int("sangvis_hiringteam_battle_defeat_awardradio")
    elif duration is None or duration >= base:
        ratio = _config_int("sangvis_hiringteam_battle_moretime_awardradio")
    elif base - duration <= base * 0.2:
        ratio = _config_int("sangvis_hiringteam_battle_lesstime_awardradio_1")
    else:
        ratio = _config_int("sangvis_hiringteam_battle_lesstime_awardradio_2")
    amount = num * (100 + ratio) / 100
    if _day_bonus(stage["challenge_type"], now):
        amount = amount * _config_int("sangvis_hiringteam_extra_ratio") / 100
    return max(1, int(amount))


def _record(state, now):
    start, _ = _week(now)
    rec = state.get("_sangvis_duplicate")
    if not rec or rec.get("week") != start:
        rec = state["_sangvis_duplicate"] = {"week": start, "wins": {}, "award": {}}
    return rec


def index(state, body, now=None):
    now = int(now or time.time())
    rec = _record(state, now)
    return {"sangvis_duplicate_with_user": {str(c): {"win_counter": int(rec["wins"].get(str(c)) or 0)} for c in CHALLENGES},
            "sangvis_duplicate_info": stages(now), "recover_bp_and_item603": _flag(state, now)}


def choose_award(state, body, now=None):
    """award_item_key counts from 0 (SkillMat Holder1/Holder2); the client reads the choice back from
    user_record.sangvis_duplicate_award_k "<challenge_type>,<key>" (UserRecord.sangvisDuplicateAwardIndex)."""
    body = body or {}
    c, key = str(body.get("challenge_type")), int(body.get("award_item_key") or 0)
    _record(state, int(now or time.time()))["award"][c] = key
    state.setdefault("user_record", {})["sangvis_duplicate_award_k"] = f"{c},{key}"
    return "1"


def _award(state, stage, rec):
    c = stage["challenge_type"]
    saved = str((state.get("user_record") or {}).get("sangvis_duplicate_award_k") or "").split(",")
    key = rec["award"].get(c)
    if key is None:
        key = int(saved[1]) if len(saved) == 2 and saved[0] == c and saved[1].isdigit() else 0
    awards = [a.split(":") for a in stage["award_item"].split(",") if a.count(":") >= 2]
    kind, rid, num = awards[max(0, min(int(key), len(awards) - 1))][:3]
    return kind, rid, int(num)


def battle_finish(state, body, now=None):
    now, body = int(now or time.time()), body or {}
    c = str(body.get("challenge_type") or "")
    stage = stages(now).get(c)
    if stage is None:
        return None
    rec = _record(state, now)
    _energy(state, now)
    item, n = stage["item_cost"].split(":")
    _charge(state, item, int(n))
    won = bool(int(body.get("if_win") or 0))
    if won:
        rec["wins"][c] = int(rec["wins"].get(c) or 0) + 1
    kind, rid, num = _award(state, stage, rec)
    duration = float(body["duration"]) if body.get("duration") else None
    amount = reward_amount(stage, num, won, duration, now)
    quests.grant(state, {"gift" if kind == GIFT else "item_ids": f"{rid}-{amount}"})
    return {"get_reward_type": int(kind), "get_reward_id": int(rid), "get_reward_num": amount, "recover_bp_and_item603": 0}


def sweep(state, body, now=None):
    """Mission/simulation for a challenge (m_id 1-3): count wins at once for count times the cost."""
    now, body = int(now or time.time()), body or {}
    stage = stages(now).get(str(body.get("m_id")))
    count = max(1, int(body.get("count") or 1))
    if stage is None:
        return None
    item, n = stage["item_cost"].split(":")
    if _energy(state, now) + int(squads._item(state, CHARGE_ITEM)["number"]) < int(n) * count:
        return None
    _charge(state, item, int(n) * count)
    rec = _record(state, now)
    rec["wins"][stage["challenge_type"]] = int(rec["wins"].get(stage["challenge_type"]) or 0) + count
    kind, rid, num = _award(state, stage, rec)
    amount = reward_amount(stage, num, True, None, now) * count
    quests.grant(state, {"gift" if kind == GIFT else "item_ids": f"{rid}-{amount}"})
    return {"gift_item" if kind == GIFT else "item": {rid: amount}}
