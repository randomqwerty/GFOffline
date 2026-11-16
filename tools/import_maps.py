"""Keep what maps did on the live server from your own packet logs, for the offline server to play back.

  python tools/import_maps.py <packet.log> [<packet.log> ...] [--out <file>]

Record with a packet logging tool (GF Alarm) while you start maps. Each start counts as one run;
playing turns records what each turn brought too. From every run this keeps:
  spawns         enemies that appeared at the start and on each enemy turn, and starting allied
                 forces (as tools/import_spawns.py)
  hidden markers the special spots the live server laid itself at the start and at each turn change
                 (gfserver/recordings.py)
Only map, node, team and marker numbers are written, nothing about the account. Results add up in
map_recordings.json next to the server, and a log already imported is skipped. The server reads the
file again when it changes. A mod's own spawn rules for a map win over these.
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
os.environ.setdefault("GF_SAVE_DIR", tempfile.mkdtemp())       # nothing here reads or writes saves
import import_spawns  # noqa: E402
from import_packet_log import read_log  # noqa: E402
from gfserver import config, recordings, stc  # noqa: E402


def import_logs(logs, out=None, say=print):
    """Add the logs' runs to out (config.MAP_RECORDINGS); returns {mission: runs} for the new ones."""
    out = Path(out or config.MAP_RECORDINGS)
    data = json.loads(out.read_text("utf-8")) if out.exists() else {}
    data.setdefault("logs", [])
    data.setdefault("missions", {})
    table_teams = {int(r["id"]): int(r["enemy_team_id"] or 0) for r in stc.table("spot")}
    table_allies = {int(r["id"]): int(r["ally_team_id"] or 0) for r in stc.table("spot")}
    got = {}
    for log in logs:
        digest = hashlib.sha256(Path(log).read_bytes()).hexdigest()
        if digest in data["logs"]:
            say(f"{Path(log).name}: already imported")
            continue
        entries = read_log(log)
        spawns = import_spawns.collect(entries, table_teams, table_allies)
        fresh = {}
        import_spawns.merge({"missions": fresh}, spawns)
        for mid, runs in recordings.collect_markers(entries, import_spawns._mission_id).items():
            fresh.setdefault(str(mid), {"turns": {}, "grow": [], "start": [], "other": 0})["marker_runs"] = runs
        for mid, entry in fresh.items():
            recordings.add(data["missions"].setdefault(mid, {}), entry)
            got[int(mid)] = got.get(int(mid), 0) + int((entry.get("turns") or {}).get("1") or 0)
        data["logs"].append(digest)
        say(f"{Path(log).name}: {sum(int((e.get('turns') or {}).get('1') or 0) for e in fresh.values())} "
            f"map starts on {len(fresh)} maps")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1), "utf-8")
    for mid in sorted(got):
        m = data["missions"][str(mid)]
        markers = {(x[0], x[1]) for r in m.get("marker_runs", []) for x in r["markers"]}
        say(f"  map {mid}: {m['turns'].get('1', 0)} starts kept, {len(m.get('grow', []))} turn spawns, "
            f"{len(m.get('start', []))} start spawns, {len(markers)} hidden markers")
    return got


def main():
    args, out, logs = sys.argv[1:], None, []
    while args:
        a = args.pop(0)
        if a == "--out":
            out = args.pop(0)
        else:
            logs.append(a)
    if not logs:
        raise SystemExit(__doc__)
    import_logs(logs, out)
    print(f"wrote {out or config.MAP_RECORDINGS}")


if __name__ == "__main__":
    main()
