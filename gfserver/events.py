"""Event draws (red packets and anniversary bundles) and doll letters.

Draw events (stc draw_event, type 1): an event item (item_id, e.g. 100001 Activity_RedPacket) is opened
for prizes. drop_ids "<draw count>:<prize>,..." gives each prize to the draws up to that count (event 1:
"149:672,150:2,299:672,300:3,..." gives prize 2 on the 150th draw, 3 on the 300th and 672 otherwise;
event 6087 "69:461,70:462,71:463" shrinks the pack after 69 and 70 draws); past the last count the
last prize repeats.
  Dorm/getDrawEvent {"id"} -> {"real_num": <draws so far>} (RequestDrawEventNum)
  Dorm/openRed {"id", "type": <draws>} -> {"list": [{"prize_id", <prize package>}, ...]} (RequestDraw;
      each entry is read with Package$$GetPackage; the client takes the items itself)
  Dorm/shareRed {"id"} "1" (ReqeustDrawSharePrize; the client adds the share prize itself)
Type 2 rows (drop "100:<gun or skin>") are exchanges, not draws, and are refused.
APPROXIMATION: the reading of drop_ids as draw counts is inferred from the tables; every draw event in
this client has ended, so this only opens items already held.

Letters (stc letter: a doll, Coalition unit or NPC to write to):
  Event/letterIndex {} -> {"letter_with_user_info": {"<letter_id>": {"letter_id", "is_sent" (bool),
      "content"}}} ([] when empty; RequsetGetAllLetterData)
  Event/saveLetter {"letter_id", "is_sent", "content"} -> {} (the client keeps its own copy)
  Event/revokeLetter {"letter_id"} -> {}
A letter is sent by saveLetter with is_sent true. The reply is the client's own story script: the notebook's
reply button plays AVGTxt/<code> (NotebookElement$$LookLetterReceive), so the server has nothing to send.
The live history is not in the account file; only Event/letterIndex ever carried it.
"""
import json
from functools import lru_cache

from . import config, quests, squads, stc

DRAW = 1


@lru_cache(maxsize=1)
def _draws():
    return {int(r["id"]): r for r in stc.table("draw_event")}


def _counts(state):
    return state.setdefault("_draw_event", {})


def _steps(row):
    out = []
    for part in str(row.get("drop_ids") or "").split(","):
        n, _, prize = part.partition(":")
        if n.strip().isdigit() and prize.strip().isdigit():
            out.append((int(n), int(prize)))
    return sorted(out)


def prize_for(row, n):
    """The prize of the n-th draw (1-based)."""
    steps = _steps(row)
    return next((p for upto, p in steps if n <= upto), steps[-1][1] if steps else 0)


def draw_num(state, body):
    return {"real_num": int(_counts(state).get(str((body or {}).get("id"))) or 0)}


def open_red(state, body):
    body = body or {}
    row = _draws().get(int(body.get("id") or 0))
    times = max(1, int(body.get("type") or 1))
    if row is None or int(row["type"]) != DRAW or not _steps(row):
        return None
    item = str(row["item_id"])
    if int(item) and int(squads._item(state, item)["number"]) < times:
        return None
    if int(item):
        squads._spend(state, item, times)
    counts, key = _counts(state), str(row["id"])
    out = []
    for _ in range(times):
        counts[key] = int(counts.get(key) or 0) + 1
        prize = prize_for(row, counts[key])
        package = quests.grant(state, quests._reward(quests.prizes().get(prize, {})))
        out.append(dict(package, prize_id=prize))
    return {"list": out}


def _letters(state):
    return state.setdefault("_letters", {})


def letter_index(state, body):
    return {"letter_with_user_info": dict(_letters(state)) or []}


def save_letter(state, body):
    body = body or {}
    lid = int(body.get("letter_id") or 0)
    if lid not in {int(r["id"]) for r in stc.table("letter")}:
        return None
    sent = body.get("is_sent")
    _letters(state)[str(lid)] = {"letter_id": lid, "is_sent": sent in (True, 1, "1", "true"),
                                 "content": str(body.get("content") or "")}
    return {}


def send_letter(state, body):
    """Event/sendLetter, which no client code sends: saveLetter with is_sent set."""
    return save_letter(state, dict(body or {}, is_sent=True))


def revoke_letter(state, body):
    _letters(state).pop(str((body or {}).get("letter_id")), None)
    return {}


# Mission/drawEvent {} -> [{"draw_event_id", "draw_num", "draw_endtime"}] (RequestNormalEventDraw): the recorded
#   list of events, with the draws made so far.
def draw_list(state, body):
    counts = _counts(state)
    try:
        rows = json.loads((config.RESPONSES_DIR / "Mission" / "drawEvent.json").read_text(encoding="utf-8"))
    except OSError:
        rows = []                  # nothing recorded
    return [dict(r, draw_num=int(counts.get(str(r["draw_event_id"])) or 0)) for r in rows]
