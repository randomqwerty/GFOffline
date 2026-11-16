"""Learn what maps spawn from packet logs of live runs, for missions.py to play back.

  python tools/import_spawns.py <packet.log> [<packet.log> ...] [--out <file>]

The live server chose spawns from columns the shipped tables don't have (the client's
SpotInfo.grow_enemy_team_pool and its turn and defeat columns), so the only record of them is what
it sent during play. For every run in a gf_alarm log this counts:
  grow    each grow_enemy in a Mission/startEnemyTurn reply: spot, turn, team
  start   each enemy in the Mission/startMission reply on a spot whose table entry has another team
  allies  each allied force in the Mission/startMission reply that neither the spot table nor the
          request (forces the player deployed) put there: spot, ally team
  turns   how many runs reached each turn
  enemy_turns  how many runs reached each enemy turn, which gives the chance of each spawn (a run
          abandoned before the enemy moved doesn't count against it)
  other   grow_enemy in any other reply (spawns on a kill, say): counted only, not played back

Only mission, spot and team numbers are written, nothing about the account. Results add up in
data/live_spawns.json, and a log already imported is skipped, so several sessions can be fed in over
time. More runs give truer chances. Restart the server to use them. A mod's own spawn rules for a map
win over these.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ["GF_NO_MODS"] = "1"
os.environ.setdefault("GF_SAVE_DIR", tempfile.mkdtemp())       # nothing here reads or writes saves
from import_packet_log import read_log  # noqa: E402
from gfserver import stc  # noqa: E402

OUT = ROOT / "data" / "live_spawns.json"


def _path(entry):
    return re.sub(r"^.*?(?=/[A-Z][A-Za-z]*/[A-Za-z]+$)", "", str(entry.get("URL") or "").split("?")[0])


def _mission_id(request):
    m = re.search(r'mission_id"?\s*[:=]\s*"?(\d+)', request if isinstance(request, str) else json.dumps(request or {}))
    return int(m.group(1)) if m else 0


def _rows(spots):
    return [s for s in (spots.values() if isinstance(spots, dict) else spots or []) if isinstance(s, dict)]


def collect(entries, table_teams, table_allies=None):
    """Counts per mission from one log: {mission: {"turns": {turn: runs}, "grow": {(spot, turn, team): n},
    "start": {(spot, team): n}, "other": n}}."""
    out, run, table_allies = {}, None, table_allies or {}
    for e in entries:
        path, reply = _path(e), e.get("Response")
        if not isinstance(reply, dict):
            continue
        if path == "/Mission/startMission":
            mid = _mission_id(e.get("Request"))
            if not mid:
                run = None
                continue
            run = {"mission": mid, "turn": 1}
            seen = out.setdefault(mid, {"turns": {}, "enemy_turns": {}, "grow": {}, "start": {}, "allies": {}, "other": 0})
            seen["turns"][1] = seen["turns"].get(1, 0) + 1
            for s in _rows(reply.get("spot_act_info")):
                spot, team = int(s.get("spot_id") or 0), int(s.get("enemy_team_id") or 0)
                if team and team != table_teams.get(spot, 0):
                    seen["start"][(spot, team)] = seen["start"].get((spot, team), 0) + 1
            req = e.get("Request") if isinstance(e.get("Request"), dict) else {}
            deployed = {(int(d.get("spot_id") or 0), int(d.get("ally_team_id") or 0))
                        for d in (req.get("mission_ally_spots") or []) + (req.get("ally_spots") or []) if isinstance(d, dict)}
            teams = {str(k): int(v.get("ally_team_id") or 0) for k, v in (reply.get("ally_instance_info") or {}).items()
                     if isinstance(v, dict)}
            for s in _rows(reply.get("spot_act_info")):
                for iid in s.get("ally_instance_ids") or []:
                    key = (int(s.get("spot_id") or 0), teams.get(str(iid), 0))
                    if key[1] and key[1] != table_allies.get(key[0], 0) and key not in deployed:
                        seen["allies"][key] = seen["allies"].get(key, 0) + 1
            continue
        if run is None:
            continue
        seen = out[run["mission"]]
        if path == "/Mission/startTurn":
            run["turn"] += 1
            seen["turns"][run["turn"]] = seen["turns"].get(run["turn"], 0) + 1
        if path == "/Mission/startEnemyTurn":
            seen["enemy_turns"][run["turn"]] = seen["enemy_turns"].get(run["turn"], 0) + 1
        for g in _rows(reply.get("grow_enemy")):
            if path == "/Mission/startEnemyTurn":
                key = (int(g.get("spot_id") or 0), run["turn"], int(g.get("enemy_team_id") or 0))
                seen["grow"][key] = seen["grow"].get(key, 0) + 1
            else:
                seen["other"] += 1
        # every live map reply carries both keys, empty until the map ends
        if path == "/Mission/abortMission" or reply.get("mission_win_result") or reply.get("mission_lose_result"):
            run = None
    return out


def merge(data, counts):
    missions = data.setdefault("missions", {})
    for mid, seen in counts.items():
        m = missions.setdefault(str(mid), {"turns": {}, "grow": [], "start": [], "other": 0})
        allies = {tuple(x[:2]): x[2] for x in m.get("allies", [])}
        for key, n in seen.get("allies", {}).items():
            allies[key] = allies.get(key, 0) + n
        if allies:
            m["allies"] = [[*k, n] for k, n in sorted(allies.items())]
        for turn, n in seen["turns"].items():
            m["turns"][str(turn)] = m["turns"].get(str(turn), 0) + n
        for turn, n in seen.get("enemy_turns", {}).items():
            et = m.setdefault("enemy_turns", {})
            et[str(turn)] = et.get(str(turn), 0) + n
        grow = {tuple(x[:3]): x[3] for x in m["grow"]}
        for key, n in seen["grow"].items():
            grow[key] = grow.get(key, 0) + n
        m["grow"] = [[*k, n] for k, n in sorted(grow.items())]
        start = {tuple(x[:2]): x[2] for x in m["start"]}
        for key, n in seen["start"].items():
            start[key] = start.get(key, 0) + n
        m["start"] = [[*k, n] for k, n in sorted(start.items())]
        m["other"] += seen["other"]
    return data


def main():
    args, out, logs = sys.argv[1:], OUT, []
    while args:
        a = args.pop(0)
        if a == "--out":
            out = Path(args.pop(0))
        else:
            logs.append(a)
    if not logs:
        raise SystemExit(__doc__)
    data = json.loads(out.read_text("utf-8")) if out.exists() else {"logs": [], "missions": {}}
    table_teams = {int(r["id"]): int(r["enemy_team_id"] or 0) for r in stc.table("spot")}
    table_allies = {int(r["id"]): int(r["ally_team_id"] or 0) for r in stc.table("spot")}
    for log in logs:
        digest = hashlib.sha256(Path(log).read_bytes()).hexdigest()
        if digest in data["logs"]:
            print(f"{log}: already imported")
            continue
        counts = collect(read_log(log), table_teams, table_allies)
        merge(data, counts)
        data["logs"].append(digest)
        print(f"{log}: {sum(s['turns'].get(1, 0) for s in counts.values())} runs on {len(counts)} maps")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1), "utf-8")
    for mid, m in sorted(data["missions"].items(), key=lambda kv: int(kv[0])):
        print(f"  map {mid}: {m['turns'].get('1', 0)} runs, {len(m['grow'])} turn spawns, "
              f"{len(m['start'])} start spawns, {len(m.get('allies', []))} starting allied forces, "
              f"{m['other']} spawns from other causes")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
