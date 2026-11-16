"""Bingo (Bingo/*): a 6x6 card filled by drawing numbers with raffle tickets.

The event is catchdata bingo_info (grid_num 6: a 6x6 card, 14 lines = 6 rows, 6 columns, 2 diagonals;
line_prize_config one prize per line in that order; final_prize_config "<prize>_<lines>" paid when that
many lines are done; cost_raffle_ticket tickets a draw; a repeated number pays repeat_number_for_credit
credit; choosing a number costs choose_number_from_credit credit). The client reads the ticket as item 11
and the credit as item 12 (Bingo$$get_ticket / get_credit) and runs the event by its own dates
(Data$$GetCurrentBingo); the one in this client ran 2026-06-02..22, so it needs a mod to run again.
Tickets come from tasks (catchdata bingo_task_info), counted with the quest counters.
Reply formats (from the client's handlers):
  Bingo/user_bingo_info {} -> {"grid": ["<number>", ...36], "user_grid": [bool, ...36],
      "pay_task_refresh_count", "lines_index": [<line>, ...]} (Bingo$$.ctor)
  Bingo/tasklists {} -> [{"task_id", "type", "task_name", "size", "user_size", "ticket_num", "title",
      "content", "status", "function_control_id", "task_type_id", "goto_page_id"}] (BingoTask$$.ctor)
  Bingo/random_num {} -> {"new_number": "<n>", "lines_index": [...]} (RequestBingoRandom: the client takes
      the ticket and adds the credit for a repeat itself)
  Bingo/choose_num {"number"} -> {"new_number", "lines_index"} (RequestBingoSelectNum: the client takes
      the credit)
Line and final prizes are mailed (mail type MAIL_BINGO).
APPROXIMATION: the card is numbers 1-36 in a random order; the day's tasks are normal_task_num "general"
and pay_task_num "difficulty" tasks picked per day ("recharge" ones need purchases); a finished task pays
its tickets at once and counts from the day's first look at the list; task names map onto the server's counters (TASK_COUNTERS) and kinds it does not
count never progress; the mail type is a guess.
"""
import random
import time

from . import quests, squads, stc

TICKET, CREDIT = "11", "12"
MAIL_BINGO = 28
DAY_OFFSET = -8 * 3600
TASK_COUNTERS = {"mission_common_win": "mission_win", "mission_night_win": "mission_win",
                 "mission_emergent_win": "mission_win", "simulated_warfare": "combat_simulation",
                 "eat_equip": "upgrade_equip", "operation_iop_contract": "develop_gun",
                 "operation_equip_contract": "develop_equip", "consume_iop_contract": "consume_iop_contract",
                 "win_person": "enemy_die", "win_robot": "enemy_die", "win_armorrobot": "enemy_die",
                 "operation_duration": "operation", "consume_build_coin": "get_build_coin"}


def _ts(text):
    return int(time.mktime(time.strptime(str(text), "%Y-%m-%d %H:%M:%S")))


def event(now=None):
    """The running bingo_info row, else the latest one."""
    now = int(now or time.time())
    rows = list(stc.catch("bingo_info"))
    live = [r for r in rows if _ts(r["starttime"]) <= now <= _ts(r["endtime"])]
    return (live or sorted(rows, key=lambda r: r["starttime"]))[-1] if rows else None


def _size(ev):
    return int(ev.get("grid_num") or 6)


def _lines(n):
    rows = [[r * n + c for c in range(n)] for r in range(n)]
    cols = [[r * n + c for r in range(n)] for c in range(n)]
    return rows + cols + [[i * n + i for i in range(n)], [i * n + n - 1 - i for i in range(n)]]


def _card(state, now=None):
    ev = event(now)
    if ev is None:
        return None, None
    card = state.get("_bingo")
    if not card or card.get("event") != str(ev["id"]):
        n = _size(ev)
        nums = [str(i) for i in range(1, n * n + 1)]
        random.Random(f"{ev['id']}-{state['user_info'].get('user_id', '')}").shuffle(nums)
        card = state["_bingo"] = {"event": str(ev["id"]), "grid": nums, "checked": [False] * (n * n),
                                  "lines": [], "base": dict(quests._state(state)["counters"]), "tasks_done": [],
                                  "refresh": 0}
    return ev, card


def info(state, body, now=None):
    ev, card = _card(state, now)
    if ev is None:
        return None
    return {"grid": card["grid"], "user_grid": card["checked"], "pay_task_refresh_count": int(card["refresh"]),
            "lines_index": card["lines"]}


def _mark(state, ev, card, number):
    """Mark a number; mail the prizes of lines it finishes. Returns False for a repeat."""
    if number not in card["grid"]:
        return None
    i = card["grid"].index(number)
    if card["checked"][i]:
        return False
    card["checked"][i] = True
    prizes = [int(p) for p in str(ev.get("line_prize_config") or "").split(",") if p.strip().isdigit()]
    finals = [tuple(int(x) for x in p.split("_")) for p in str(ev.get("final_prize_config") or "").split(",") if "_" in p]
    for li, cells in enumerate(_lines(_size(ev))):
        if li not in card["lines"] and all(card["checked"][c] for c in cells):
            card["lines"].append(li)
            if li < len(prizes):
                quests._prize_mail(state, MAIL_BINGO, prizes[li], "bingo_line", prizes[li])
            for prize, need in finals:
                if len(card["lines"]) == need:
                    quests._prize_mail(state, MAIL_BINGO, prize, "bingo_final", prize)
    return True


def random_num(state, body, now=None, rng=random):
    ev, card = _card(state, now)
    if ev is None:
        return None
    cost = int(ev.get("cost_raffle_ticket") or 1)
    if int(squads._item(state, TICKET)["number"]) < cost:
        return None
    squads._spend(state, TICKET, cost)
    number = rng.choice(card["grid"])
    if not _mark(state, ev, card, number):
        row = squads._item(state, CREDIT)
        row["number"] = str(int(row["number"]) + int(ev.get("repeat_number_for_credit") or 0))
    return {"new_number": number, "lines_index": card["lines"]}


def choose_num(state, body, now=None):
    ev, card = _card(state, now)
    number = str((body or {}).get("number") or "")
    cost = int((ev or {}).get("choose_number_from_credit") or 0)
    if ev is None or number not in card["grid"] or card["checked"][card["grid"].index(number)]:
        return None
    if int(squads._item(state, CREDIT)["number"]) < cost:
        return None
    squads._spend(state, CREDIT, cost)
    _mark(state, ev, card, number)
    return {"new_number": number, "lines_index": card["lines"]}


def _day_tasks(ev, now):
    rows = list(stc.catch("bingo_task_info"))
    day = (int(now) + DAY_OFFSET) // 86400
    rng = random.Random(f"{ev['id']}-{day}")
    picks = []
    for kind, n in (("general", int(ev.get("normal_task_num") or 3)), ("difficulty", int(ev.get("pay_task_num") or 3))):
        pool = [r for r in rows if r["type"] == kind]
        picks += rng.sample(pool, min(n, len(pool)))
    return picks


def tasks(state, body, now=None):
    now = int(now or time.time())
    ev, card = _card(state, now)
    if ev is None:
        return None
    counters = quests._state(state)["counters"]
    day = str((now + DAY_OFFSET) // 86400)
    if card.get("day") != day:          # the day's tasks count from the day's first look
        card.update(day=day, base=dict(counters), tasks_done=[])
    out = []
    for t in _day_tasks(ev, now):
        kind = TASK_COUNTERS.get(t["task_name"], t["task_name"])
        have = max(0, int(counters.get(kind, 0)) - int(card["base"].get(kind, 0)))
        size, tid = int(t["size"]), str(t["task_id"])
        done = tid in card["tasks_done"]
        if not done and have >= size:
            card["tasks_done"].append(tid)
            row = squads._item(state, TICKET)
            row["number"] = str(int(row["number"]) + int(t["ticket_num"] or 0))
            done = True
        out.append({"task_id": int(t["task_id"]), "type": t["type"], "task_name": t["task_name"], "size": size,
                    "user_size": min(have, size), "ticket_num": int(t["ticket_num"] or 0), "title": t["title"],
                    "content": t["content"], "status": 1 if done else 0,
                    "function_control_id": int(t.get("function_control_id") or 0),
                    "task_type_id": int(t.get("task_type_id") or 0), "goto_page_id": int(t.get("goto_page_id") or 0)})
    return out
