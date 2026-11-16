"""Echelons: dolls, equipment, fairies and Coalition units in teams, formation positions, locks.

Every reply here is the plain "1" (each client handler only checks for it); the client
applies the change on its side, and these functions keep the save in step so it survives a
relogin. Request bodies (from the client's request builders):
  Gun/teamGun        {"team_id", "team_set": {"<location 1-5>": gun_with_user_id | 0}}
                                                    FormationController$$RequestChangeTeam
  Gun/setPosition    {"<gun_with_user_id>": position}  FormationSettingController$$RequestGunSetPostion
  Gun/teamGuns       {"team_id", "guns": {"<gun_with_user_id>": location}}  RequestChangeGunLocation
  Gun/exchangeTeam   {"team_a", "team_b"}               RequestExchangeTeam
  Gun/quickTeam      {"team_id", "guns": [{"gun_with_user_id", "position"}, ...] (location =
                     order) or {"<location>": {...}}, "equips": [{"if_outfit", "gun_with_user_id",
                     "equip_with_user_id", "equip_slot"}]}  RequestApplyTeamWithEquipRecord
  Equip/gunEquip     {"if_outfit", "gun_with_user_id", "equip_with_user_id", "equip_slot"}
                                                    GF.Battle.Gun$$RequestChangeEquip
  Equip/unequip      {"equip_with_user_ids": [...]}    RequestEquipUnequip
  Fairy/teamFairy    {"team_id", "fairy_with_user_id"} RequestTeamFairy
  Sangvis/teamSangvis {"team_id", "team_set": {"<1-9>": {"sangvis_with_user_id", "position"}}}
                                                    SangvisFormaionController / RequestGunApplySangvisTeamRecord
  Sangvis/setPosition {"team_id", "positions": [position for slot 1..9]}
  Gun/Equip/Fairy/Sangvis changeLock  {"lock": [ids], "unlock": [ids]} (Fairy/Sangvis may wrap
                     it in "in_data")
Bodies whose shape was read from the request builders but not yet seen live are parsed
leniently (dict or list); see logs/new_endpoints.jsonl for what the client really sent.
"""
import json

# Formation grid cells (7-9, 12-14, 17-19); a doll new to a team takes the first free one.
GRID = (12, 7, 17, 13, 8, 18, 14, 9, 19)
SANGVIS_SLOTS = 9


def _guns(state):
    return state.get("gun_with_user_info", [])


def _gun(state, gid):
    gid = str(gid)
    return next((g for g in _guns(state) if str(g["id"]) == gid), None)


def _values(collection):
    return collection.values() if isinstance(collection, dict) else collection


def _equip(state, eid):
    eqs = state.get("equip_with_user_info") or {}
    if isinstance(eqs, dict):
        return eqs.get(str(eid))
    return next((e for e in eqs if str(e["id"]) == str(eid)), None)


def _fairy(state, fid):
    fs = state.get("fairy_with_user_info") or {}
    if isinstance(fs, dict):
        return fs.get(str(fid))
    return next((f for f in fs if str(f["id"]) == str(fid)), None)


def _leave_team(g):
    g["team_id"], g["location"], g["position"] = "0", "0", "0"


def _join(state, g, team, location, position=None):
    """Put a doll in a team slot, taking a free grid cell unless one is given."""
    if position is None:
        if str(g["team_id"]) == str(team) and int(g["position"] or 0):
            position = int(g["position"])
        else:
            used = {int(x["position"]) for x in _guns(state) if str(x["team_id"]) == str(team) and x is not g}
            position = next((p for p in GRID if p not in used), GRID[0])
    g["team_id"], g["location"], g["position"] = str(team), str(location), str(position)


def team_gun(state, body):
    body = body or {}
    team = str(body.get("team_id") or 0)
    slots = {int(k): int(v or 0) for k, v in (body.get("team_set") or {}).items()}
    if team == "0" or not slots:
        return None
    wanted = {str(v) for v in slots.values() if v}
    for g in _guns(state):
        if str(g["team_id"]) == team and str(g["id"]) not in wanted:
            _leave_team(g)
    for loc, gid in sorted(slots.items()):
        g = _gun(state, gid) if gid else None
        if g is not None:
            _join(state, g, team, loc)
    return "1"


def set_position(state, body):
    for gid, pos in (body or {}).items():
        g = _gun(state, gid) if str(gid).isdigit() else None
        if g is not None:
            g["position"] = str(int(pos or 0))
    return "1"


def team_guns(state, body):
    body = body or {}
    team = str(body.get("team_id") or 0)
    for gid, loc in (body.get("guns") or {}).items():
        g = _gun(state, gid)
        if g is not None and str(g["team_id"]) == team:
            g["location"] = str(int(loc or 0))
    return "1"


def exchange_team(state, body):
    body = body or {}
    a, b = str(body.get("team_a") or 0), str(body.get("team_b") or 0)
    swap = {a: b, b: a}
    for g in _guns(state):
        if str(g["team_id"]) in swap:
            g["team_id"] = swap[str(g["team_id"])]
    for f in _values(state.get("fairy_with_user_info") or {}):
        if str(f.get("team_id")) in swap:
            f["team_id"] = swap[str(f["team_id"])]
    return "1"


def quick_team(state, body):
    body = body or {}
    team = str(body.get("team_id") or 0)
    guns = body.get("guns") or []
    entries = (sorted(((int(k), v) for k, v in guns.items()), key=lambda kv: kv[0]) if isinstance(guns, dict)
               else list(enumerate(guns, 1)))
    wanted = {str((e or {}).get("gun_with_user_id") or 0) for _, e in entries}
    for g in _guns(state):
        if str(g["team_id"]) == team and str(g["id"]) not in wanted:
            _leave_team(g)
    for loc, e in entries:
        g = _gun(state, (e or {}).get("gun_with_user_id") or 0)
        if g is not None:
            _join(state, g, team, loc, int(e.get("position") or 0) or None)
    for eq in body.get("equips") or []:
        gun_equip(state, eq)
    return "1"


def _take_off(state, e):
    owner = _gun(state, e.get("gun_with_user_id") or 0)
    if owner is not None:
        for k in ("equip1", "equip2", "equip3", "equip4"):
            if str(owner.get(k)) == str(e["id"]):
                owner[k] = "0"
    e["gun_with_user_id"] = "0"


def gun_equip(state, body):
    body = body or {}
    g = _gun(state, body.get("gun_with_user_id") or 0)
    slot = f"equip{int(body.get('equip_slot') or 0)}"
    if g is None or slot not in g:
        return None
    old = _equip(state, g[slot]) if str(g[slot]) != "0" else None
    if old is not None:
        _take_off(state, old)
    g[slot] = "0"
    if int(body.get("if_outfit") or 0):
        e = _equip(state, body.get("equip_with_user_id") or 0)
        if e is None:
            return None
        _take_off(state, e)
        e["gun_with_user_id"], g[slot] = str(g["id"]), str(e["id"])
    return "1"


def unequip(state, body):
    for eid in (body or {}).get("equip_with_user_ids") or []:
        e = _equip(state, eid)
        if e is not None:
            _take_off(state, e)
    return "1"


def team_fairy(state, body):
    body = body or {}
    team, fid = str(body.get("team_id") or 0), str(body.get("fairy_with_user_id") or 0)
    if team == "0":
        return None
    for f in _values(state.get("fairy_with_user_info") or {}):
        if str(f.get("team_id")) == team:
            f["team_id"] = "0"
    f = _fairy(state, fid) if fid != "0" else None
    if f is not None:
        f["team_id"] = team
    return "1"


# --- Coalition echelons (save: sangvis_team_with_user_info [{id, user_id, team_id, ammo, mre,
# info: {"1".."9": {"sangvis_with_user_id", "position"}}}])

def _sangvis_teams(state):
    return state.setdefault("sangvis_team_with_user_info", [])


def _sangvis_team(state, team):
    teams = _sangvis_teams(state)
    row = next((t for t in teams if str(t["team_id"]) == str(team)), None)
    if row is None:
        row = {"id": str(max((int(t.get("id") or 0) for t in teams), default=0) + 1),
               "user_id": str(state["user_info"].get("user_id", "")), "team_id": str(team), "ammo": 0, "mre": 0,
               "info": {str(i): {"sangvis_with_user_id": "0", "position": "0"} for i in range(1, SANGVIS_SLOTS + 1)}}
        teams.append(row)
    return row


def team_sangvis(state, body):
    body = body or {}
    team = str(body.get("team_id") or 0)
    slots = body.get("team_set") or {}
    if team == "0" or not slots:
        return None
    info = {str(i): {"sangvis_with_user_id": "0", "position": "0"} for i in range(1, SANGVIS_SLOTS + 1)}
    for k, v in slots.items():
        if str(k) in info and isinstance(v, dict):
            info[str(k)] = {"sangvis_with_user_id": str(v.get("sangvis_with_user_id") or 0),
                            "position": str(v.get("position") or 0)}
    members = {v["sangvis_with_user_id"] for v in info.values()} - {"0"}
    for other in _sangvis_teams(state):
        if str(other["team_id"]) != team:
            for v in (other.get("info") or {}).values():
                if str(v.get("sangvis_with_user_id")) in members:
                    v["sangvis_with_user_id"], v["position"] = "0", "0"
    _sangvis_team(state, team)["info"] = info
    return "1"


def sangvis_set_position(state, body):
    body = body or {}
    row = _sangvis_team(state, body.get("team_id") or 0)
    for i, pos in enumerate(body.get("positions") or [], 1):
        if str(i) in row["info"]:
            row["info"][str(i)]["position"] = str(int(pos or 0))
    return "1"


# --- locks

def _lock_body(body):
    body = body or {}
    if "in_data" in body:
        inner = body["in_data"]
        body = json.loads(inner) if isinstance(inner, str) else inner
    return {str(i) for i in body.get("lock") or []}, {str(i) for i in body.get("unlock") or []}


def _set_locks(collection, body):
    lock, unlock = _lock_body(body)
    for row in _values(collection or {}):
        if str(row["id"]) in lock:
            row["is_locked"] = "1"
        elif str(row["id"]) in unlock:
            row["is_locked"] = "0"
    return "1"


def gun_lock(state, body):
    return _set_locks(state.get("gun_with_user_info"), body)


def equip_lock(state, body):
    return _set_locks(state.get("equip_with_user_info"), body)


def fairy_lock(state, body):
    return _set_locks(state.get("fairy_with_user_info"), body)


def sangvis_lock(state, body):
    return _set_locks(state.get("sangvis_with_user_info"), body)


# --- presets
#
# Gun/preset {"preset_no", "gun"|"guns": {"<location>": "gun_with_user_id-gun_id-0-location-position-
# number-level"}} (CommonCharacterRecord$$RequestSaveGunRecord; the save's gun_preset_info keeps the
# same "gun" map). Gun/presetToTeam {"team_id", "preset_no", "guns": [{"gun_with_user_id",
# "position"}]} applies one like quickTeam. Equip/preset {"gun_with_user_id", "preset_no",
# "equips": {"equip1", "equip2", "equip3"}}; Equip/presetList {"gun_with_user_id"} -> [{"gun_with_user_id",
# "preset_no", "equip"}] (RequestGunEquipPresetInfo). Sangvis/presetToTeam has teamSangvis's body.

def save_gun_preset(state, body):
    body = body or {}
    slots = body.get("gun") or body.get("guns") or {}
    if isinstance(slots, dict) and isinstance(slots.get("gun"), dict):
        slots = slots["gun"]
    if not isinstance(slots, dict) or not body.get("preset_no"):
        return None
    no = str(body["preset_no"])
    presets = [p for p in state.setdefault("gun_preset_info", []) if str(p.get("preset_no")) != no]
    presets.append({"user_id": str(state["user_info"].get("user_id", "")), "preset_no": no,
                    "gun": {str(k): str(v) for k, v in slots.items()}})
    state["gun_preset_info"] = sorted(presets, key=lambda p: int(p["preset_no"]))
    return "1"


def gun_preset_to_team(state, body):
    body = dict(body or {})
    body.setdefault("equips", [])
    return quick_team(state, body)


def save_equip_preset(state, body):
    body = body or {}
    gid, no = str(body.get("gun_with_user_id") or 0), str(body.get("preset_no") or 0)
    equips = body.get("equips") or {}
    if gid == "0" or no == "0" or not isinstance(equips, dict):
        return None
    presets = state.setdefault("_equip_presets", {}).setdefault(gid, {})
    presets[no] = {k: str(equips.get(k) or 0) for k in ("equip1", "equip2", "equip3")}
    return "1"


def equip_preset_list(state, body):
    gid = str((body or {}).get("gun_with_user_id") or 0)
    presets = state.get("_equip_presets", {}).get(gid, {})
    return [{"gun_with_user_id": gid, "preset_no": int(no), "equip": eq} for no, eq in sorted(presets.items())]


def save_vehicle_preset(state, body):
    """Vehicle/preset (VehicleData$$WriteFormationObject) {vehicle_id, preset_no, component_list
    {slot: id}, common_component_list {slot: id}, crew_list {crew: [kind, unit id]}, vehicle_skin,
    component_skin_list {component: skin}} -> {} (RequestSaveVehiclePreset reads no keys).
    Kept in vehicle_preset_info in Index/index's form: "slot:id,..." strings, crew "crew:kind-unit"."""
    body = body or {}
    vid, no = str(body.get("vehicle_id") or 0), str(body.get("preset_no") or 0)
    if vid == "0" or no == "0":
        return None
    presets = state.setdefault("vehicle_preset_info", [])
    old = next((p for p in presets if str(p.get("vehicle_id")) == vid and str(p.get("preset_no")) == no), None)
    rec = old if old is not None else {"id": str(1 + max([int(p.get("id") or 0) for p in presets] or [0])),
                                       "user_id": str(state["user_info"].get("user_id", "")),
                                       "vehicle_id": vid, "preset_no": no}
    rec.update(_vehicle_fields(body), vehicle_skin=str(body.get("vehicle_skin") or 0))
    if old is None:
        presets.append(rec)
    return {}


def _vehicle_fields(body):
    def pairs(d):
        return ",".join(f"{k}:{v}" for k, v in sorted((d or {}).items(), key=lambda kv: int(kv[0])))

    crew = {k: "-".join(str(x) for x in (v if isinstance(v, list) else [v])) for k, v in (body.get("crew_list") or {}).items()}
    return {"component": pairs(body.get("component_list")), "common_component": pairs(body.get("common_component_list")),
            "crew": pairs(crew), "component_skin": pairs(body.get("component_skin_list"))}


def vehicle_team_up(state, body):
    """Vehicle/teamUp: the same body as Vehicle/preset, for the vehicle's current formation -> {}
    (RequestSaveVehicleFormation reads no keys; a plain "1" is not JSON and fails there)."""
    body = body or {}
    vehicles = state.get("vehicle_with_user_info") or {}
    have = vehicles.values() if isinstance(vehicles, dict) else vehicles
    rec = next((v for v in have if str(v["vehicle_id"]) == str(body.get("vehicle_id"))), None)
    if rec is None:
        return None
    rec.update(_vehicle_fields(body), skin=str(body.get("vehicle_skin") or 0))
    return {}
