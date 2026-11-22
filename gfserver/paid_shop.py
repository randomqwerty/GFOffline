"""The shop's paid ($) goods, bought with gems: offline there is no payment.

The list is the live paycenter's (ServerInfo.RequestProductList, c=micasdk&a=getProducts), saved by
tools/live_archive.py --products to data/pay_products.json. Every product is a point_mall row: its prize_id holds what
it gives, its type what it is (4 gem pack, 5 monthly card, 6 battle pass, 21/22/24/25 packages; 22 is daily), and
quota_num how often it can be bought (0: no limit).

Buying (client_patch/paid_shop.lua): the shop's buy button asks to confirm the gem price, then sends the client's own
Mall/ifAble {"product_id"}. That takes the gems and mails the goods (MailType 26, payPackage, as live sends them after a
payment), and the patch then runs MallGoodController.OnPayFinished, which fetches the mail list. Monthly cards set the
user_info end time; the Monthly Gems Card mails its daily gems on the first mail list of each day.

Price: the product's gem value, or what its goods hold in gems if more (the Daily Special Supply and the Monthly Gems
Card give more gems than their value). Gem packs cost basic resources instead and pay their point_mall gem at once:
a quarter of the gems' worth in each of manpower, ammo, rations and parts, at the Supply shop's rate (mall 2/4/6/8:
4500 manpower, ammo or rations, or 1500 parts, for 480 gems). client_patch/paid_shop.lua shows the same price.
Battle pass products are given at once too, not mailed: the pass screen unlocks from the client's own bag
(PassOrderUserData$$UnlockLevel: GameData.GetItem of either unlock_itemid item), so the reply's "items" {id: count}
are set there by the patch.
"""
import copy
import json
import time
from functools import lru_cache

from . import config, quests, stc

PRODUCTS_FILE = config.ROOT / "data" / "pay_products.json"
GEM_PACK, MONTHLY_CARD, BATTLE_PASS, DAILY = 4, 5, 6, 22
RESOURCES = ("mp", "ammo", "mre", "part")
GEM_PACK_MARK = "offline_gem_pack_"
RES_PER_480_GEMS = {"mp": 4500, "ammo": 4500, "mre": 4500, "part": 1500}
RES_NAMES = {"mp": "manpower", "ammo": "ammo", "mre": "rations", "part": "parts"}
MAIL_PAY_PACKAGE = 26
CARD_DAYS = 30
DAY_OFFSET = 8 * 3600       # the server day turns over at 00:00 UTC-8 (account.SHOP_DAY_OFFSET)


@lru_cache(maxsize=2)
def _load(path, mtime):
    return json.loads(path.read_text("utf-8"))


def _reply():
    if not PRODUCTS_FILE.is_file():
        return {"Err_No": 100, "Err_Msg": ""}
    return _load(PRODUCTS_FILE, PRODUCTS_FILE.stat().st_mtime_ns)


def products():
    """{product id: product} from the saved list."""
    return {str(p["id"]): p for k, p in _reply().items() if k.isdigit() and isinstance(p, dict)}


@lru_cache(maxsize=1)
def _point_mall():
    return {int(r["id"]): r for r in stc.table("point_mall")}


def product_list():
    """The getProducts reply: the saved list with each "gem" (PayProduct.gemValue, which the patch shows as the
    price) the gem price. Gem packs keep theirs, the gems they give, which the patch prices in resources; their
    third_product_id (MallGood.thirdProductId, a store id unused offline: Mall/ifAble sends the product id) is
    GEM_PACK_MARK + id, so the patch can tell them apart without the product type."""
    out = copy.deepcopy(_reply())
    for k, p in out.items():
        if not k.isdigit() or not isinstance(p, dict):
            continue
        if int(p.get("product_type") or 0) == GEM_PACK:
            p["third_product_id"] = GEM_PACK_MARK + str(p["id"])
        else:
            p["gem"] = str(price(p))
    return out


def _find(pid):
    pid = str(pid or "")
    found = products().get(pid)
    return found or next((p for p in products().values() if p.get("third_product_id") == pid), None)


def price(product):
    if int(product.get("product_type") or 0) == GEM_PACK:
        return 0
    row = _point_mall().get(int(product["id"]), {})
    prize = quests.prizes().get(int(row.get("prize_id") or 0), {})
    holds = int(prize.get("gem") or 0) + int(prize.get("gem_pay") or 0)
    if row.get("month_card_type") == "monthlycard1":
        holds += int(row.get("gem") or 0) * CARD_DAYS
    return max(int(product.get("gem") or 0), holds)


def resource_price(product):
    """A gem pack's price in basic resources, {resource: amount}; {} for other goods."""
    if int(product.get("product_type") or 0) != GEM_PACK:
        return {}
    gems = int(_point_mall().get(int(product["id"]), {}).get("gem") or product.get("gem") or 0)
    return {res: -(-gems * n // (4 * 480)) for res, n in RES_PER_480_GEMS.items()}


def _day(now):
    return (int(now) - DAY_OFFSET) // 86400


def _bought(state):
    return state.setdefault("_paid_bought", {})


def _count(state, product, now):
    rec = _bought(state).get(str(product["id"]))
    if not rec:
        return 0
    if int(product.get("product_type") or 0) == DAILY and rec["day"] != _day(now):
        return 0
    return rec["n"]


def buy(state, body, now=None):
    """Mall/ifAble {"product_id"}: buy it with gems. Plain JSON for the patch: {"gem_buy": 1, "gem", "cost"}, or
    {"gem_buy": 0, "reason"}; "items" {item id: count now} for goods given at once."""
    now = int(now or time.time())
    product = _find((body or {}).get("product_id"))
    if product is None:
        return json.dumps({"gem_buy": 0, "reason": "This item isn't on sale offline."})
    kind = int(product.get("product_type") or 0)
    row = _point_mall().get(int(product["id"]), {})
    quota = int(row.get("quota_num") or 0)
    if quota and _count(state, product, now) >= quota:
        return json.dumps({"gem_buy": 0, "reason": "Already bought" + (" today." if kind == DAILY else ".")})
    if not (int(product.get("sale_starttime") or 0) <= now < int(product.get("sale_endtime") or 2**31)):
        return json.dumps({"gem_buy": 0, "reason": "This item isn't on sale now."})
    ui = state["user_info"]
    cost = price(product)
    if int(ui.get("gem") or 0) < cost:
        return json.dumps({"gem_buy": 0, "reason": f"Not enough gems: this costs {cost}."})
    res_cost = resource_price(product)
    short = [RES_NAMES[r] for r, n in res_cost.items() if int(ui.get(r) or 0) < n]
    if short:
        need = ", ".join(f"{n} {RES_NAMES[r]}" for r, n in res_cost.items())
        return json.dumps({"gem_buy": 0, "reason": f"Not enough {' and '.join(short)}: this costs {need}."})
    for r, n in res_cost.items():
        ui[r] = str(int(ui.get(r) or 0) - n)
    ui["gem"] = str(int(ui.get("gem") or 0) - cost + (int(row.get("gem") or 0) if kind == GEM_PACK else 0))
    rec = _bought(state).get(str(product["id"]))
    if rec is None or (kind == DAILY and rec["day"] != _day(now)):
        rec = {"n": 0, "day": _day(now)}
    rec.update(n=rec["n"] + 1, day=_day(now), last=now)
    _bought(state)[str(product["id"])] = rec
    if kind == MONTHLY_CARD and row.get("month_card_type"):
        card = row["month_card_type"]
        end = max(int(ui.get(f"{card}_end_time") or 0), now)
        ui[f"{card}_end_time"] = str(end + CARD_DAYS * 86400)
        card_mails(state, now)
    elif kind == BATTLE_PASS and int(row.get("prize_id") or 0):
        from . import squads
        prize = quests.prizes().get(int(row["prize_id"]), {})
        quests.grant(state, quests._reward(prize))
        ids = [x.partition("-")[0] for x in str(prize.get("item_ids") or "").split(",") if x.strip()]
        items = {i: int(squads._item(state, i)["number"]) for i in ids}
        return json.dumps({"gem_buy": 1, "gem": int(ui["gem"]), "cost": cost, "items": items})
    elif int(row.get("prize_id") or 0):
        quests._prize_mail(state, MAIL_PAY_PACKAGE, product["id"], product.get("title") or "", row["prize_id"])
        return json.dumps({"gem_buy": 1, "gem": int(ui["gem"]), "cost": cost, "mailed": 1})
    if res_cost:
        return json.dumps({"gem_buy": 1, "gem": int(ui["gem"]), "cost": cost,
                           "resources": {r: int(ui[r]) for r in RESOURCES}})
    return json.dumps({"gem_buy": 1, "gem": int(ui["gem"]), "cost": cost})


def card_mails(state, now=None):
    """The Monthly Gems Card's gems for today, once a day while it lasts (last_monthlycard1_recover_time)."""
    now = int(now or time.time())
    ui = state["user_info"]
    for card, row in _cards().items():
        if int(ui.get(f"{card}_end_time") or 0) <= now or not int(row.get("gem") or 0):
            continue
        if _day(int(ui.get(f"last_{card}_recover_time") or 0)) == _day(now):
            continue
        ui[f"last_{card}_recover_time"] = str(now)
        quests.send_mail(state, MAIL_PAY_PACKAGE, row["id"], "Monthly Gems Card", {"gem": int(row["gem"])}, now)


def _cards():
    """{card type: the point_mall row of a card on sale} for cards that give gems daily."""
    out = {}
    for p in products().values():
        row = _point_mall().get(int(p["id"]), {})
        if int(row.get("type") or 0) == MONTHLY_CARD and row.get("month_card_type"):
            out.setdefault(row["month_card_type"], row)
    return out


def quota_rows(state, now=None):
    """Paid goods bought, as Mall/staticTables pointmall_quota rows ({user_id, product_id, buy_count, last_buy_time})."""
    now = int(now or time.time())
    uid = str(state["user_info"].get("user_id", ""))
    out = {}
    for pid, rec in _bought(state).items():
        product = products().get(pid)
        n = _count(state, product, now) if product else 0
        if n:
            out[pid] = {"user_id": uid, "product_id": pid, "buy_count": str(n), "last_buy_time": str(rec.get("last", 0))}
    return out
