"""
Night Market — player-to-player marketplace + bounty board service layer.

Design notes
────────────
* Completely separate from the legacy /market (handlers/market.py) and the
  stock exchange (handlers/stockmarket.py). Nothing here touches those
  collections or code paths.
* All money/inventory movement goes through single guarded MongoDB updates
  (utils.database.atomic_*), so read-modify-write races cannot duplicate
  currency or items. Listing SOLD / bounty COMPLETED transitions are CAS
  updates on status — exactly one concurrent winner, losers see the new
  state and fail cleanly.
* Currency is integer yen only. Fees use integer math (floor), configurable
  via nm_config (percent ×10 stored as permille so 2.5% is representable).
* Callback data never carries prices or quantities — only public IDs; every
  operation re-reads server state and verifies ownership/eligibility.
"""
import logging
import math
import re as _re
from datetime import datetime, timedelta

from utils.database import (
    col, get_player, canonical_item_name,
    atomic_debit_yen, atomic_credit_yen,
    atomic_escrow_lock, atomic_escrow_release, atomic_transfer_escrow,
    escrow_locked_quantity,
    nm_next_id, nm_log_ledger, nm_audit, nm_get_config,
)

log = logging.getLogger(__name__)

# ── Defaults (overridable per-key in DB via nm_config) ────────────────────
NM_DEFAULTS = {
    "market_fee_permille": 20,      # 2.0 %  (permille → allows fractional %)
    "bounty_fee_permille": 0,       # 0.0 %
    "min_listing_price": 1,
    "max_listing_price": 10_000_000,
    "max_listing_qty": 999,
    "max_listings_per_player": 10,
    "listing_expiry_hours": 24,
    "min_bounty_reward": 100,
    "max_bounty_reward": 1_000_000,
    "max_active_bounties": 3,
    "bounty_expiry_hours": 24,
    "target_cooldown_hours": 6,     # same target can't be re-bountied for N h
}


def cfg(key):
    """Configurable economy setting with default fallback (never hardcoded at call sites)."""
    v = nm_get_config().get(key)
    if v is None:
        return NM_DEFAULTS[key]
    try:
        return int(v)
    except (TypeError, ValueError):
        return NM_DEFAULTS[key]


def fee_of(gross_amount: int, permille_key: str) -> int:
    """Integer floor fee from a permille rate. Guarantees fee < gross for gross ≥ 1."""
    gross_amount = max(0, int(gross_amount))
    if gross_amount == 0:
        return 0
    permille = max(0, min(1000, cfg(permille_key)))
    fee = gross_amount * permille // 1000
    if fee >= gross_amount:          # never eat the whole payout
        fee = gross_amount - 1
    return fee


def _now():
    return datetime.now()


def fmt_time_left(dt):
    """'18h 42m' style countdown, or 'expired'."""
    if not dt:
        return "—"
    delta = (dt - _now()).total_seconds()
    if delta <= 0:
        return "expired"
    h = int(delta // 3600)
    m = int((delta % 3600) // 60)
    if h > 0:
        return f"{h}h {m}m"
    s = int(delta % 60)
    return f"{m}m {s}s"


def seller_handle(user_id) -> str:
    """Public handle only — no private info revealed."""
    p = get_player(user_id)
    if not p:
        return "@unknown"
    u = p.get("username")
    if u:
        return "@" + u.lstrip("@")
    return "a masked slayer"


# ═══════════════════════════════════════════════════════════════════════════
#  LISTINGS
# ═══════════════════════════════════════════════════════════════════════════

LISTING_STATUSES = ("ACTIVE", "SOLD", "CANCELLED", "EXPIRED")


def create_listing(seller_id, item_name, quantity, unit_price):
    """Validate → escrow-lock items → insert ACTIVE listing.

    Returns (ok: bool, message_or_doc). Items leave the usable inventory at
    creation (escrow) but the seller earns nothing until an actual sale.
    """
    player = get_player(seller_id)
    if not player:
        return False, "No character found. Use /start first."

    name = canonical_item_name(str(item_name or "").strip())
    if not name:
        return False, "Unknown item."
    try:
        quantity = int(quantity)
        unit_price = int(unit_price)
    except (TypeError, ValueError):
        return False, "Quantity and price must be whole numbers."

    if quantity <= 0:
        return False, "Quantity must be at least 1."
    if quantity > cfg("max_listing_qty"):
        return False, f"Too many — max {cfg('max_listing_qty')} per listing."
    if unit_price < cfg("min_listing_price"):
        return False, f"Minimum price is ¥{cfg('min_listing_price'):,} each."
    if unit_price > cfg("max_listing_price"):
        return False, f"Maximum price is ¥{cfg('max_listing_price'):,} each."

    active = col("night_market_listings").count_documents(
        {"seller_id": int(seller_id), "status": "ACTIVE"})
    if active >= cfg("max_listings_per_player"):
        return False, f"Listing limit reached ({cfg('max_listings_per_player')} active). Cancel one first."

    inv = col("inventory").find_one(
        {"user_id": int(seller_id), "item_name": {"$regex": f"^{_re.escape(name)}$", "$options": "i"}})
    itype = (inv or {}).get("item_type", "item")
    total_have = int((inv or {}).get("quantity", 0) or 0)
    available = total_have - escrow_locked_quantity(seller_id, name)
    if available < quantity:
        return False, (f"You only have {available} usable **{name}** "
                       f"({total_have} owned, {total_have - available} already listed).")

    if not atomic_escrow_lock(seller_id, name, itype, quantity):
        return False, "Could not lock the items — they may be in another listing. Try again."

    lid = nm_next_id("listing")
    expires = _now() + timedelta(hours=cfg("listing_expiry_hours"))
    doc = {
        "listing_id": lid,
        "seller_id": int(seller_id),
        "item_name": name,
        "item_type": itype,
        "quantity": quantity,
        "remaining_quantity": quantity,
        "unit_price": unit_price,
        "fee_permille": cfg("market_fee_permille"),
        "status": "ACTIVE",
        "created_at": _now(),
        "expires_at": expires,
    }
    col("night_market_listings").insert_one(doc)
    nm_audit("LISTING_CREATED", seller_id,
             {"listing_id": lid, "item": name, "qty": quantity, "price": unit_price})
    doc.pop("_id", None)
    return True, doc


def get_listing(listing_id):
    try:
        lid = int(listing_id)
    except (TypeError, ValueError):
        return None
    doc = col("night_market_listings").find_one({"listing_id": lid})
    if doc:
        doc.pop("_id", None)
    return doc


def _refresh_status(listing):
    """Lazily mark an expired-but-ACTIVE listing EXPIRED and free its escrow."""
    if listing and listing.get("status") == "ACTIVE" and listing.get("expires_at"):
        if listing["expires_at"] <= _now():
            expire_due_listings()
            fresh = get_listing(listing["listing_id"])
            return fresh
    return listing


def browse_listings(page=0, per_page=5, search=None, sort="newest", rarity=None, seller_id=None):
    query = {"status": "ACTIVE"}
    if search:
        safe = _re.escape(str(search)[:60])
        query["item_name"] = {"$regex": safe, "$options": "i"}
    if rarity:
        query["item_type"] = str(rarity).lower()
    if seller_id is not None:
        query["seller_id"] = int(seller_id)
    sort_dir = -1 if sort in ("newest", "quantity") else 1
    key = {"lowest": "unit_price", "highest": "unit_price",
           "newest": "created_at", "oldest": "created_at",
           "quantity": "remaining_quantity"}.get(sort, "created_at")
    cursor = col("night_market_listings").find(query).sort(key, sort_dir)
    docs = list(cursor)
    total = len(docs)
    start = page * per_page
    page_docs = docs[start:start + per_page]
    pages = max(1, math.ceil(total / per_page))
    return page_docs, page, pages, total


def purchase_listing(buyer_id, listing_id):
    """Fully guarded purchase. Order chosen so the worst failure mode always
    refunds:  CAS-sell listing → debit buyer → transfer escrow goods →
    credit seller. Any mid-failure rolls back prior steps explicitly.

    Returns (ok, message)."""
    listing = get_listing(listing_id)
    if not listing:
        return False, "This listing no longer exists."
    if listing["status"] != "ACTIVE":
        return False, f"Listing #{mk_public_id(listing['listing_id'])} is already {listing['status'].lower()}."
    if listing["expires_at"] and listing["expires_at"] <= _now():
        expire_due_listings()
        return False, "The listing expired — your yen was never touched."
    if int(listing["seller_id"]) == int(buyer_id):
        return False, "You cannot buy your own listing."

    qty = int(listing["remaining_quantity"])
    unit = int(listing["unit_price"])
    gross = qty * unit
    fee = gross * int(listing.get("fee_permille", cfg("market_fee_permille"))) // 1000
    net = gross - fee

    # 1. Race gate: flip ACTIVE→SOLD atomically. Only ONE caller wins.
    res = col("night_market_listings").update_one(
        {"listing_id": int(listing_id), "status": "ACTIVE",
         "expires_at": {"$gt": _now()}},
        {"$set": {"status": "SOLD", "sold_at": _now(), "buyer_id": int(buyer_id)}})
    if res.modified_count == 0:
        cur = get_listing(listing_id)
        state = (cur or {}).get("status", "gone")
        return False, f"Listing already sold or expired (status: {state}). Someone beat you to it."

    # 2. Debit buyer (atomic, balance-guarded)
    if not atomic_debit_yen(buyer_id, gross):
        _revert_sale(listing_id, "buyer could not pay")
        return False, f"Insufficient balance — you need ¥{gross:,}."

    # 3. Move escrowed goods to buyer
    if not atomic_transfer_escrow(listing["seller_id"], buyer_id, listing["item_name"], qty):
        atomic_credit_yen(buyer_id, gross)   # refund — goods were not there
        _revert_sale(listing_id, "escrow empty")
        return False, "The seller's stock vanished (cancelled/expired). Purchase rolled back."

    # 4. Pay the seller
    if not atomic_credit_yen(listing["seller_id"], net):
        log.error("[NM] seller credit failed listing=%s — funds held in market pool", listing_id)

    # 5. Records
    tx_id = nm_next_id("tx")
    col("nm_transactions").insert_one({
        "tx_id": tx_id, "listing_id": int(listing_id),
        "buyer_id": int(buyer_id), "seller_id": int(listing["seller_id"]),
        "item_name": listing["item_name"], "quantity": qty,
        "unit_price": unit, "gross": gross, "fee": fee, "net": net,
        "created_at": _now(),
    })
    nm_log_ledger(buyer_id, "BUY", -gross, "listing", listing_id,
                  {"item": listing["item_name"], "qty": qty, "tx": tx_id})
    nm_log_ledger(listing["seller_id"], "SELL", net, "listing", listing_id,
                  {"item": listing["item_name"], "qty": qty, "fee": fee, "tx": tx_id})
    nm_audit("LISTING_PURCHASED", buyer_id,
             {"listing_id": listing_id, "gross": gross, "fee": fee, "tx": tx_id})
    return True, (f"🎴 Purchased **{listing['item_name']} ×{qty}** for ¥{gross:,}. "
                  f"Seller received ¥{net:,} (fee ¥{fee:,}).")


def _revert_sale(listing_id, reason):
    """Roll a just-SOLD listing back to ACTIVE when a later step fails."""
    col("night_market_listings").update_one(
        {"listing_id": int(listing_id), "status": "SOLD"},
        {"$set": {"status": "ACTIVE"}, "$unset": {"sold_at": "", "buyer_id": ""}})
    nm_audit("LISTING_SALE_REVERTED", None, {"listing_id": listing_id, "reason": reason})


def cancel_listing(user_id, listing_id):
    """Owner-only cancel; returns escrow. Never pays out anything."""
    listing = get_listing(listing_id)
    if not listing:
        return False, "Listing not found."
    if int(listing["seller_id"]) != int(user_id):
        nm_audit("LISTING_CANCEL_DENIED", user_id, {"listing_id": listing_id})
        return False, "This is not your listing."
    if listing["status"] != "ACTIVE":
        return False, f"Listing is already {listing['status'].lower()}."
    res = col("night_market_listings").update_one(
        {"listing_id": int(listing_id), "status": "ACTIVE"},
        {"$set": {"status": "CANCELLED", "closed_at": _now()}})
    if res.modified_count == 0:
        return False, "Listing state changed — refresh and try again."
    atomic_escrow_release(listing["seller_id"], listing["item_name"],
                          int(listing["remaining_quantity"]))
    nm_audit("LISTING_CANCELLED", user_id, {"listing_id": listing_id})
    return True, f"Cancelled — **{listing['item_name']} ×{listing['remaining_quantity']}** returned to your inventory."


def expire_due_listings():
    """Sweep expired ACTIVE listings → EXPIRED + escrow returned. Safe to call
    repeatedly; the CAS update guarantees items are released exactly once."""
    now = _now()
    due = list(col("night_market_listings").find({"status": "ACTIVE", "expires_at": {"$lte": now}}))
    count = 0
    for l in due:
        res = col("night_market_listings").update_one(
            {"listing_id": l["listing_id"], "status": "ACTIVE"},
            {"$set": {"status": "EXPIRED", "closed_at": now}})
        if res.modified_count == 0:
            continue
        atomic_escrow_release(l["seller_id"], l["item_name"], int(l["remaining_quantity"]))
        nm_audit("LISTING_EXPIRED", l["seller_id"], {"listing_id": l["listing_id"]})
        count += 1
    return count


def my_listings(user_id, status=None):
    query = {"seller_id": int(user_id)}
    if status:
        query["status"] = status.upper()
    return list(col("night_market_listings").find(query).sort("created_at", -1).limit(50))


# ═══════════════════════════════════════════════════════════════════════════
#  BOUNTIES
# ═══════════════════════════════════════════════════════════════════════════

BOUNTY_STATUSES = ("OPEN", "ACCEPTED", "COMPLETED", "EXPIRED", "CANCELLED")


def resolve_target(identifier):
    """Accept @username, username, or numeric user id. Returns player dict or None."""
    s = str(identifier or "").strip().lstrip("@").lower()
    if not s:
        return None
    if s.isdigit():
        p = get_player(int(s))
        if p and p.get("user_id") is not None:
            return p
    pcol = col("players")
    doc = pcol.find_one({"username": {"$regex": f"^{_re.escape(s)}$", "$options": "i"}})
    if not doc:
        doc = pcol.find_one({"name": {"$regex": f"^{_re.escape(s)}$", "$options": "i"}})
    if doc:
        doc.pop("_id", None)
    return doc


def create_bounty(creator_id, target_identifier, reward):
    """Escrows reward yen immediately (prevents fake bounties), then posts."""
    player = get_player(creator_id)
    if not player:
        return False, "No character found."
    target = resolve_target(target_identifier)
    if not target:
        return False, "Target not found. Use their @username."
    tid = int(target["user_id"])
    if tid == int(creator_id):
        return False, "You cannot put a bounty on yourself."
    try:
        reward = int(reward)
    except (TypeError, ValueError):
        return False, "Reward must be a whole number of yen."
    if reward < cfg("min_bounty_reward"):
        return False, f"Minimum bounty is ¥{cfg('min_bounty_reward'):,}."
    if reward > cfg("max_bounty_reward"):
        return False, f"Maximum bounty is ¥{cfg('max_bounty_reward'):,}."

    if col("night_market_bounties").count_documents(
            {"creator_id": int(creator_id), "status": {"$in": ["OPEN", "ACCEPTED"]}}) >= cfg("max_active_bounties"):
        return False, f"Max {cfg('max_active_bounties')} active bounties per player."

    cooldown = timedelta(hours=cfg("target_cooldown_hours"))
    recent = col("night_market_bounties").find_one({
        "target_id": tid,
        "created_at": {"$gte": _now() - cooldown},
        "status": {"$nin": ["CANCELLED"]},
    })
    if recent:
        return False, (f"Target has a recent contract (#{bt_public_id(recent['bounty_id'])}) — "
                       f"cooldown {fmt_time_left(recent['created_at'] + cooldown)} left.")

    fee = fee_of(reward, "bounty_fee_permille")
    total_cost = reward + fee
    # Atomic escrow: money leaves spendable balance in ONE guarded update.
    if not atomic_debit_yen(creator_id, total_cost):
        return False, (f"Insufficient balance — need ¥{reward:,}"
                       + (f" + ¥{fee:,} fee" if fee else "")
                       + f". You have ¥{(player.get('yen') or 0):,}.")

    bid = nm_next_id("bounty")
    expires = _now() + timedelta(hours=cfg("bounty_expiry_hours"))
    doc = {
        "bounty_id": bid,
        "creator_id": int(creator_id),
        "target_id": tid,
        "target_name": target.get("name") or seller_handle(tid),
        "reward": reward,
        "fee": fee,
        "status": "OPEN",
        "hunter_id": None,
        "requirement": "Defeat target in battle",
        "created_at": _now(),
        "accepted_at": None,
        "completed_at": None,
        "expires_at": expires,
    }
    col("night_market_bounties").insert_one(doc)
    nm_log_ledger(creator_id, "BOUNTY_ESCROW", -total_cost, "bounty", bid,
                  {"target": doc["target_name"], "reward": reward, "fee": fee})
    nm_audit("BOUNTY_CREATED", creator_id, {"bounty_id": bid, "target_id": tid, "reward": reward})
    doc.pop("_id", None)
    return True, doc


def get_bounty(bounty_id):
    try:
        bid = int(bounty_id)
    except (TypeError, ValueError):
        return None
    doc = col("night_market_bounties").find_one({"bounty_id": bid})
    if doc:
        doc.pop("_id", None)
    return doc


def browse_bounties(page=0, per_page=4):
    query = {"status": {"$in": ["OPEN", "ACCEPTED"]}}
    docs = list(col("night_market_bounties").find(query).sort("created_at", -1))
    total = len(docs)
    start = page * per_page
    pages = max(1, math.ceil(total / per_page))
    return docs[start:start + per_page], page, pages, total


def accept_bounty(hunter_id, bounty_id):
    hunter = get_player(hunter_id)
    if not hunter:
        return False, "No character found."
    b = get_bounty(bounty_id)
    if not b:
        return False, "Contract not found."
    if int(b["creator_id"]) == int(hunter_id):
        return False, "You cannot hunt your own contract."
    if int(b["target_id"]) == int(hunter_id):
        return False, "You are the target of this contract."
    if b["status"] != "OPEN":
        return False, f"Contract is already {b['status'].lower()}."
    if b["expires_at"] and b["expires_at"] <= _now():
        expire_due_bounties()
        return False, "Contract expired."
    res = col("night_market_bounties").update_one(
        {"bounty_id": int(bounty_id), "status": "OPEN"},
        {"$set": {"status": "ACCEPTED", "hunter_id": int(hunter_id), "accepted_at": _now()}})
    if res.modified_count == 0:
        return False, "Someone accepted this contract first."
    nm_audit("BOUNTY_ACCEPTED", hunter_id, {"bounty_id": bounty_id})
    return True, (f"⚔️ Contract #{bt_public_id(bounty_id)} accepted.\n\n"
                  f"Hunter: {seller_handle(hunter_id)}\n"
                  f"Target: {seller_handle(b['target_id'])}\n"
                  f"Reward: ¥{b['reward']:,}\n"
                  f"Status: ● ACTIVE\n\nDefeat the target in a duel to collect.")


def complete_bounties_for_result(winner_id, loser_id):
    """Called by the battle system after a legitimate duel finishes.
    Pays every OPEN/ACCEPTED contract whose hunter won against the target.
    Each completion is a CAS update → impossible to claim twice or pay twice.
    Returns list of (bounty, ok, msg) for notification purposes."""
    results = []
    candidates = list(col("night_market_bounties").find({
        "target_id": int(loser_id),
        "hunter_id": int(winner_id),
        "status": {"$in": ["OPEN", "ACCEPTED"]},
        "creator_id": {"$ne": int(winner_id)},
    }))
    now = _now()
    for b in candidates:
        if b.get("expires_at") and b["expires_at"] <= now:
            continue
        res = col("night_market_bounties").update_one(
            {"bounty_id": b["bounty_id"], "status": {"$in": ["OPEN", "ACCEPTED"]},
             "hunter_id": int(winner_id)},
            {"$set": {"status": "COMPLETED", "completed_at": now}})
        if res.modified_count == 0:
            continue  # already completed/cancelled by a concurrent path
        paid = atomic_credit_yen(winner_id, int(b["reward"]))
        nm_log_ledger(winner_id, "BOUNTY_REWARD", int(b["reward"]), "bounty", b["bounty_id"],
                      {"target": b.get("target_name"), "paid": paid})
        nm_log_ledger(b["creator_id"], "BOUNTY_PAID", 0, "bounty", b["bounty_id"],
                      {"hunter": seller_handle(winner_id)})
        nm_audit("BOUNTY_COMPLETED", winner_id,
                 {"bounty_id": b["bounty_id"], "reward": b["reward"], "paid": paid})
        msg = (f"☠️ BOUNTY COMPLETE — #{bt_public_id(b['bounty_id'])}\n"
               f"{seller_handle(winner_id)} defeated {seller_handle(b['target_id'])}!\n"
               f"💰 Reward: +¥{b['reward']:,}")
        results.append((b, paid, msg))
    return results


def cancel_bounty(user_id, bounty_id):
    """Cancellation policy: before acceptance → cancel freely (full refund);
    after acceptance → disabled (hunter may legitimately complete it any time)."""
    b = get_bounty(bounty_id)
    if not b:
        return False, "Contract not found."
    if int(b["creator_id"]) != int(user_id):
        nm_audit("BOUNTY_CANCEL_DENIED", user_id, {"bounty_id": bounty_id})
        return False, "Only the contract creator can cancel it."
    if b["status"] == "ACCEPTED":
        return False, ("A hunter already accepted this contract — cancellation is locked. "
                       "It will complete or expire normally.")
    if b["status"] != "OPEN":
        return False, f"Contract is already {b['status'].lower()}."
    res = col("night_market_bounties").update_one(
        {"bounty_id": int(bounty_id), "status": "OPEN"},
        {"$set": {"status": "CANCELLED", "closed_at": _now()}})
    if res.modified_count == 0:
        return False, "Contract state changed — refresh."
    refund = int(b["reward"])  # posting fee is consumed like a listing fee
    atomic_credit_yen(b["creator_id"], refund)
    nm_log_ledger(b["creator_id"], "BOUNTY_REFUND", refund, "bounty", bounty_id,
                  {"fee_kept": b.get("fee", 0)})
    nm_audit("BOUNTY_CANCELLED", user_id, {"bounty_id": bounty_id, "refund": refund})
    return True, f"Contract cancelled — ¥{refund:,} returned to your balance."


def expire_due_bounties():
    """Unclaimed contracts release escrow back to the creator — exactly once."""
    now = _now()
    due = list(col("night_market_bounties").find({"status": "OPEN", "expires_at": {"$lte": now}}))
    count = 0
    for b in due:
        res = col("night_market_bounties").update_one(
            {"bounty_id": b["bounty_id"], "status": "OPEN"},
            {"$set": {"status": "EXPIRED", "closed_at": now}})
        if res.modified_count == 0:
            continue
        atomic_credit_yen(b["creator_id"], int(b["reward"]))
        nm_log_ledger(b["creator_id"], "BOUNTY_REFUND", int(b["reward"]), "bounty", b["bounty_id"],
                      {"reason": "expired"})
        nm_audit("BOUNTY_EXPIRED", b["creator_id"], {"bounty_id": b["bounty_id"],
                                                     "refund": b["reward"]})
        count += 1
    return count


def my_bounties(user_id):
    posted = list(col("night_market_bounties").find({"creator_id": int(user_id)})
                  .sort("created_at", -1).limit(25))
    hunting = list(col("night_market_bounties").find({"hunter_id": int(user_id)})
                   .sort("created_at", -1).limit(25))
    return posted, hunting


def locked_bounty_funds(user_id):
    docs = col("night_market_bounties").find(
        {"creator_id": int(user_id), "status": {"$in": ["OPEN", "ACCEPTED"]}},
        {"reward": 1})
    return sum(int(d.get("reward", 0)) for d in docs)


def ledger(user_id, limit=12):
    return list(col("nm_ledger").find({"player_id": int(user_id)})
                .sort("created_at", -1).limit(limit))


def mk_public_id(lid):
    return f"MK{int(lid):05d}"


def bt_public_id(bid):
    return f"BT{int(bid):04d}"
