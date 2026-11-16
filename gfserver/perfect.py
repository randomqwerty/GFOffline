"""The perfect account (launcher Account "Perfect account"): everything owned and opened, for reading the story.

Made once, from the sample account (data/player_template.json), when the account is first loaded. The sample's
progress stays (tutorial, unlocks, items, HOC, Armors, dorms); its dolls, equipment, fairies, Coalition units,
echelons, presets, logistics and adjutants are dropped (clear()), and then:
  dolls          every doll with an obtain source (gun.obtain_ids) or granted by a mod, at its Neural Upgrade version
                 (gun id + 20000) where there is one, level 120 and both skills 10; others level 100, skill 10; all 5
                 links, enhanced to the cap at their level (Gun/eatGunIndex); locked
  equipment      5 of each regular one and 1 of each exclusive one (fit_guns), full calibration, enhanced to max_level
                 (0: not enhanceable); locked
  fairies        each, mods' included, level 100, 5 stars, skill 10; locked
  Coalition      each, maxed (mods._max_sangvis)
                 1-2 star ones (rank 3 and 4: units start at rank - 2 stars) that are not Bosses (Ringleaders, type 1):
                 as many maxed copies as fit one echelon, 36 // ap_cost
  items          every item at its upper_limit, or 99999 where it has none
  gifts          every gift (gift_item) not hidden: 99999
  achievements   every one done, with its counter at the target (no mail)
  costumes       every skin not hidden
  maps           every mission opened and cleared (rank S, medals), with every unlock key (open_mission_keys)
  resources      300000 of each, 99999 gems; room for all of it
  echelon 1      only M4A1 as leader, since the game needs one doll there
  Armors         the sample's, with their crew moved to this account's copy of the same doll or Coalition unit
                 (crew points at unit record ids, which differ here: a crew member that isn't there hangs the fight)
"""
from . import factory, missions, mods, quests, stc, workshop

MOD_OFFSET = 20000
REGULAR_EQUIP, EXCLUSIVE_EQUIP = 5, 1
VERSION = 7       # saves made by an older fill() are made again (Store.load_player), except those in UPGRADES
UPGRADES = {6: "crew"}   # {old VERSION: what upgrade() still has to do}
LEADER = 55       # M4A1
DROPPED = {"gun_with_user_info": [], "equip_with_user_info": {}, "fairy_with_user_info": {}, "gun_preset_info": [],
           "sangvis_with_user_info": [], "sangvis_team_with_user_info": [], "sangvis_chip_with_user_info": [],
           "operation_act_info": [], "auto_mission_act_info": [], "team_in_coin_mission_info": {},
           "user_adjutant_multi": {"single": [], "combined": []}}
RESOURCES = {"mp": 300000, "ammo": 300000, "mre": 300000, "part": 300000, "core": 99999, "gem": 99999}
FULL_CALIBRATION = 10000
ITEM_NO_LIMIT = 99999
ECHELON_COST, BOSS_TYPE = 36, 1


def _granted(kind):
    return {int(e["id"] if isinstance(e, dict) else e) for e in ((mods.manifest() or {}).get("grant") or {}).get(kind, [])}


def _dolls():
    """{base id: id to own} for every collectable doll, and those the mods grant."""
    rows = factory.guns()
    out = {}
    granted = _granted("guns")
    for gid, g in rows.items():
        if gid not in granted and (gid >= MOD_OFFSET or str(g.get("obtain_ids") or "0") in ("", "0") or gid >= 9000):
            continue
        out[gid] = gid + MOD_OFFSET if gid + MOD_OFFSET in rows else gid
    return out


def _max_doll(rec, gun_id):
    modded = int(gun_id) >= MOD_OFFSET
    level = 120 if modded else 100
    rec.update({"gun_id": str(gun_id), "gun_level": str(level), "gun_exp": str(missions._level_exp()[level]), "number": "5",
                "if_modification": "3" if modded else "0", "life": str(factory.gun_life(int(gun_id), level, 5)),
                "skill1": "10", "skill2": "10" if modded or int(factory.guns()[int(gun_id)]["skill2"] or 0) else "0",
                "favor": max(str(rec.get("favor") or "0"), "1000000", key=int), "is_locked": "1"})
    for k, n in factory.gun_enhancement(int(gun_id), level).items():
        rec[k] = str(n)


def _max_equip(rec, row):
    rec["equip_level"] = str(int(row.get("max_level") or 0))
    rec["is_locked"] = "1"
    for k in workshop.STAT_KEYS:
        rec[k] = str(FULL_CALIBRATION if str(row.get(k) or "0").strip("0,.-") else 0)


def _items(state):
    have = {str(i["item_id"]): i for i in state.get("item_with_user_info") or []}
    for row in stc.table("item"):
        rec = have.setdefault(str(row["id"]), {"item_id": str(row["id"]), "number": "0", "last_recover_time": "0"})
        rec["number"] = str(int(row.get("upper_limit") or 0) or ITEM_NO_LIMIT)
    state["item_with_user_info"] = list(have.values())


def _gifts(state):
    have = {str(g["item_id"]): g for g in state.get("gift_with_user_info") or []}
    for row in stc.table("gift_item"):
        if not int(row.get("is_hidden") or 0):
            have.setdefault(str(row["id"]), {"item_id": str(row["id"])})["number"] = str(ITEM_NO_LIMIT)
    state["gift_with_user_info"] = list(have.values())


def _achievements(state):
    q = quests._state(state)
    rows = quests.achievement_rows()
    q["achievement_done"] = sorted(rows)
    conds = q.setdefault("achievement_cond", {})
    for aid, row in rows.items():
        target = int(row.get("count") or 0)
        if row.get("condition"):
            conds[str(aid)] = max(conds.get(str(aid), 0), target)
        elif row.get("type"):
            q["counters"][row["type"]] = max(q["counters"].get(row["type"], 0), target)


def clear(state):
    """Drop the sample's own units and everything placed with them."""
    for k, empty in DROPPED.items():
        state[k] = type(empty)(empty)
    state.pop("_quest", None)
    state["automission_presets_info"] = None     # the key must stay: GameData.ReadUserInfo makes the auto-plan settings from it
    return state


def _units(state):
    """{("1", gun record id): gun_id, ("2", sangvis record id): sangvis_id}: what a crew entry's type and id point at."""
    out = {("1", str(g["id"])): str(g["gun_id"]) for g in state.get("gun_with_user_info") or []}
    out.update({("2", str(r["id"])): str(r["sangvis_id"]) for r in state.get("sangvis_with_user_info") or []})
    return out


def crew(state, sample_units):
    """Point every Armor's and Armor preset's crew (slot:type-id, type 1 doll, 2 Coalition unit, 3 HOC) at this
    account's unit of the same kind: a doll by its base id (the Neural Upgrade copy here stands in for the plain one).
    A member already pointing at one of this account's units stays; one with no match is left out of the crew."""
    own = _units(state)
    by_kind = {}
    for (t, rid), unit in reversed(list(own.items())):
        by_kind[(t, str(int(unit) % MOD_OFFSET) if t == "1" else unit)] = rid
    squads = state.get("squad_with_user_info") or {}
    squads = {str(r["id"]) for r in (squads.values() if isinstance(squads, dict) else squads)}
    for table in ("vehicle_with_user_info", "vehicle_preset_info"):
        rows = state.get(table) or []
        for v in rows.values() if isinstance(rows, dict) else rows:
            kept = []
            for entry in str(v.get("crew") or "").split(","):
                slot, _, member = entry.partition(":")
                t, _, rid = member.partition("-")
                if t == "3":
                    new = rid if rid in squads else None
                elif (t, rid) in own:
                    new = rid
                else:
                    unit = sample_units.get((t, rid))
                    new = by_kind.get((t, str(int(unit) % MOD_OFFSET) if t == "1" else unit)) if unit else None
                if new:
                    kept.append(f"{slot}:{t}-{new}")
            v["crew"] = ",".join(kept)
    return state


def upgrade(state, sample):
    """Bring a save made by an older fill() up to VERSION without making it again, where UPGRADES says how."""
    if UPGRADES.get(state.get("_perfect")) == "crew":
        crew(state, _units(sample))
    state["_perfect"] = VERSION
    return state


def fill(state):
    sample_units = _units(state)
    clear(state)
    uid = str(state["user_info"].get("user_id", ""))
    guns = state["gun_with_user_info"]
    dolls = _dolls()
    for gid in dolls.values():
        _max_doll(factory.new_gun_record(state, gid, uid), gid)
    leader = next((g for g in guns if g["gun_id"] == str(dolls.get(LEADER))), guns[0] if guns else None)
    if leader:
        leader.update(team_id="1", location="1", position="7")
        state["team_in_coin_mission_info"] = {"1": {"user_id": uid, "location": "1",
                                                    "gun_with_user_id": leader["id"], "position": "7"}}
    state["user_info"]["gun_collect"] = ",".join(sorted({g["gun_id"] for g in guns} | {str(b) for b in dolls}, key=int))

    for eid, row in workshop.equips().items():
        if not int(row.get("is_show") or 0):
            continue
        want = EXCLUSIVE_EQUIP if str(row.get("fit_guns") or "").strip("0,") else REGULAR_EQUIP
        for _ in range(want):
            workshop.new_equip(state, eid)
    for rec in (state.get("equip_with_user_info") or {}).values():
        row = workshop.equips().get(int(rec["equip_id"]))
        if row is not None:
            _max_equip(rec, row)

    granted = _granted("fairies")
    for fid, row in workshop.fairies().items():
        if fid in granted or str(row.get("obtain_ids", "1") or "0") not in ("", "0"):
            workshop.new_fairy(state, fid, workshop._talents()[0])
    for f in (state.get("fairy_with_user_info") or {}).values():
        mods._max_fairy(f)
        f["is_locked"] = "1"

    for sid, row in mods._sangvis().items():
        spare = int(row.get("rank") or 5) <= 4 and int(row.get("type") or 0) != BOSS_TYPE and int(row.get("ap_cost") or 0) > 0
        for _ in range(ECHELON_COST // int(row["ap_cost"]) if spare else 1):
            mods.new_sangvis_record(state, sid, uid)
    for r in state.get("sangvis_with_user_info") or []:
        if int(r["sangvis_id"]) in mods._sangvis():
            mods._max_sangvis(r, int(r["sangvis_id"]))

    skins = state.setdefault("skin_with_user_info", {})
    for s in stc.table("skin"):
        if not int(s.get("is_hidden") or 0) and str(s["id"]) not in skins:
            skins[str(s["id"])] = {"skin_id": str(s["id"]), "user_id": uid, "is_read": "1"}

    keys = state.setdefault("mission_key_with_user_info", {})
    for mid, row in missions._missions().items():
        rec = missions._mission_record(state, mid)
        rec.update(is_open="1", is_close="0", bestrank="5", medal1="1", medal4="1",
                   counter=str(max(1, int(rec.get("counter") or 0))), win_counter=str(max(1, int(rec.get("win_counter") or 0))))
        for part in str(row.get("open_mission_keys") or "").replace("|", ";").split(";"):
            key, _, n = part.partition(":")
            if key.strip().isdigit():
                keys[key.strip()] = str(max(int(keys.get(key.strip()) or 0), int(n or 1)))

    crew(state, sample_units)
    _items(state)
    _gifts(state)

    grants = (mods.manifest() or {}).get("grant") or {}       # already given here: mods.apply_grants adds no copies
    done = state["_mod_grants"] = {k: sorted(_granted(k)) for k in grants}
    done["_options"] = {f"{k}:{e['id']}": {o: v for o, v in e.items() if o != "id"}
                        for k, entries in grants.items() for e in entries if isinstance(e, dict)}
    state["_perfect"] = VERSION
    ui = state["user_info"]
    for k, v in RESOURCES.items():
        ui[k] = str(max(int(ui.get(k) or 0), v))
    ui["maxgun"] = str(max(int(ui.get("maxgun") or 0), len(guns) + 50))
    ui["maxequip"] = str(max(int(ui.get("maxequip") or 0), len(state.get("equip_with_user_info") or {}) + 100))
    ui["max_fairy"] = str(max(int(ui.get("max_fairy") or 0), len(state.get("fairy_with_user_info") or {}) + 20))
    ui["max_sangvis"] = str(max(int(ui.get("max_sangvis") or 0), len(state.get("sangvis_with_user_info") or []) + 20))
    _achievements(state)          # last: the quest baseline reads the finished save
    return state
