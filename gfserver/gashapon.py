"""The dorm Gashapon (furniture and costume lottery) and the black card exchange.

The pools and prizes are server data, from a recorded Dorm/gasha reply (data/gasha.json, shipped;
else data/responses/Dorm/gasha.json): activity_list (pools: price_1 / price_10 in tokens, item 41,
start_time / end_time; type 2 pools are limited and have exchange tickets) and reward_list
(prizes: item_type 1 furniture / 2 gift item, pool "<gasha ids>", exchange_cost tickets,
blackcard_exchange_cost black cards).
Reply formats (from the client's handlers):
  Dorm/gasha {} -> {"activity_list", "reward_list", "gasha_exchange_list": [{"gasha_id",
      "exchange_tickets"}]} (RequestGashaData)
  Dorm/gasha_draw {"gasha_id", "type", "draw_type": 1 | 10} -> {"furniture": [{"id": prize id,
      "dorm_with_user_id"}], "cosmetic": [gift ids], "decompose": [], "exchange_tickets"}
      (GashaponController$$RequestDrawRewardHandle: takes the tokens and adds the gifts itself)
  Dorm/gasha_exchange {"gasha_id", "type", "id": prize id} -> {"dorm_with_user_id",
      "exchange_tickets"} (RequestExchangeRewardHandle)
  Dorm/black_exchange_list {} -> {"list": prizes that can be bought with black cards}
  Dorm/black_exchange {"id"} -> {"dorm_with_user_id"} (RequestExchangeBlackCard: black cards,
      item 43, or BlackCardpiece_Num pieces, item 54, for each card short)
  Dorm/composeBlackCard {} -> {"compose_num"} (RequestComposeBlackCard: pieces into cards)
Recorded (2026-11-10, limited pool 85, seven 10-draws): a 10-draw gives 11 prizes and 11
exchange tickets; the prizes come back cheapest tier first, gift prizes (item_type 2) in the
"furniture" list without a dorm_with_user_id ("cosmetic" stayed empty). Each 10-draw also had one
"decompose" entry {"cosmetic_item", "decompose_list": [{"gift_id": 100001-100003, "num": "1"}]}
whose cosmetic_item isn't a prize, furniture or skin id: not reproduced (UNKNOWN).
APPROXIMATION: the draw rates are server-side. A prize's weight follows its tier, its exchange
cost (DRAW_WEIGHTS, fitted to the 77 recorded prizes: cost 0 ~56%, 20 ~30%, 50 ~9%, the 100+
outfits ~3%); a single draw gives one prize and one ticket.
"""
import json
import random
import time
from functools import lru_cache

from . import config, quests, squads

TOKEN, BLACK_CARD, BLACK_PIECE = "41", "43", "54"
FURNITURE, GIFT = "1", "2"
LIMITED = "2"
TEN_DRAW_PRIZES = 11       # recorded: 11 prizes and 11 tickets per 10-draw
# weight of one prize by its exchange_cost (tier): fitted to the recorded draws of pool 85
DRAW_WEIGHTS = ((0, 3.3), (20, 1.5), (50, 0.55), (100, 0.4))


def _weight(prize):
    cost, w = int(prize.get("exchange_cost") or 0), DRAW_WEIGHTS[0][1]
    for at, weight in DRAW_WEIGHTS:
        if cost >= at:
            w = weight
    return w


@lru_cache(maxsize=1)
def _recorded():
    for path in (config.ROOT / "data" / "gasha.json", config.RESPONSES_DIR / "Dorm" / "gasha.json"):
        try:
            return json.loads(path.read_text("utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def _pools(now):
    return {str(a["id"]): a for a in _recorded().get("activity_list") or []
            if int(a.get("start_time") or 0) <= now <= int(a.get("end_time") or 1 << 40)}


def _prizes():
    return {str(r["id"]): r for r in _recorded().get("reward_list") or []}


def _tickets(state):
    return state.setdefault("gasha_exchange_info", {})


def index(state, body, now=None):
    now = int(now or time.time())
    rec = _recorded()
    return {"activity_list": list(_pools(now).values()), "reward_list": rec.get("reward_list") or [],
            "gasha_exchange_list": [{"gasha_id": g, "exchange_tickets": str(n)} for g, n in sorted(_tickets(state).items())]}


def _give(state, prize):
    """Add one prize to the save; returns (furniture record id or 0, item id)."""
    from . import account
    if str(prize["item_type"]) == FURNITURE:
        pieces = account.furniture(state)
        rec = {"id": str(max((int(f["id"]) for f in pieces), default=0) + 1), "dorm": "0",
               "furniture_id": str(prize["item_id"]), "x": "0", "y": "0"}
        pieces.append(rec)
        return int(rec["id"]), int(prize["item_id"])
    quests.grant(state, {"gift": f"{prize['item_id']}-1"})
    return 0, int(prize["item_id"])


def draw(state, body, now=None, rng=random):
    body, now = body or {}, int(now or time.time())
    pool = _pools(now).get(str(body.get("gasha_id")))
    n = 10 if int(body.get("draw_type") or 1) == 10 else 1
    if pool is None:
        return None
    price = int(pool["price_10" if n == 10 else "price_1"])
    if int(squads._item(state, TOKEN)["number"]) < price:
        return None
    squads._spend(state, TOKEN, price)
    quests.record(state, "consume_furniture_coin", price)
    choices = [p for p in _prizes().values() if str(pool["id"]) in str(p["pool"]).split(",")]
    if not choices:
        return None
    count = TEN_DRAW_PRIZES if n == 10 else 1
    drawn = rng.choices(choices, weights=[_weight(p) for p in choices], k=count)
    drawn.sort(key=lambda p: (int(p.get("exchange_cost") or 0), int(p["id"])))
    reply = {"furniture": [], "cosmetic": [], "decompose": []}
    for prize in drawn:
        rec, _ = _give(state, prize)
        reply["furniture"].append({"id": int(prize["id"]), "dorm_with_user_id": rec} if rec else {"id": int(prize["id"])})
    tickets = _tickets(state)
    if str(pool.get("type")) == LIMITED:
        tickets[str(pool["id"])] = int(tickets.get(str(pool["id"])) or 0) + count
    reply["exchange_tickets"] = int(tickets.get(str(pool["id"])) or 0)
    return reply


def exchange(state, body):
    body = body or {}
    gid, prize = str(body.get("gasha_id")), _prizes().get(str(body.get("id")))
    tickets = _tickets(state)
    if prize is None or not int(prize.get("is_exchange") or 0) or gid not in str(prize["pool"]).split(","):
        return None
    cost = int(prize.get("exchange_cost") or 0)
    if int(tickets.get(gid) or 0) < cost:
        return None
    tickets[gid] = int(tickets.get(gid) or 0) - cost
    rec, _ = _give(state, prize)
    return {"dorm_with_user_id": rec, "exchange_tickets": tickets[gid]}


def _piece_rate():
    return int(quests._config().get("BlackCardpiece_Num") or 10)


def black_list(state, body):
    return {"list": [p for p in _prizes().values() if int(p.get("is_blackcard_exchange") or 0)]}


def black_exchange(state, body):
    prize = _prizes().get(str((body or {}).get("id")))
    if prize is None or not int(prize.get("is_blackcard_exchange") or 0):
        return None
    cost = int(prize.get("blackcard_exchange_cost") or 0)
    cards, pieces = int(squads._item(state, BLACK_CARD)["number"]), int(squads._item(state, BLACK_PIECE)["number"])
    short = max(0, cost - cards)
    if short * _piece_rate() > pieces:
        return None
    squads._spend(state, BLACK_CARD, cost - short)
    squads._spend(state, BLACK_PIECE, short * _piece_rate())
    rec, _ = _give(state, prize)
    return {"dorm_with_user_id": rec}


def compose_black_card(state, body):
    n = int(squads._item(state, BLACK_PIECE)["number"]) // _piece_rate()
    squads._spend(state, BLACK_PIECE, n * _piece_rate())
    row = squads._item(state, BLACK_CARD)
    row["number"] = str(int(row["number"]) + n)
    return {"compose_num": n}
