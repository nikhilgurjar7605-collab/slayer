"""
🌙 NIGHT MARKET — /nightmarket

Player-driven marketplace + bounty board.  Completely separate from the
legacy /market (handlers/market.py) and the stock exchange
(handlers/stockmarket.py): different collections, different flows, zero
shared mutable state.  All economy logic lives in utils/nightmarket.py.

Callback namespace: nm_*  (never collides with market_/stock_/bm_ prefixes)
"""
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import ContextTypes

from utils.database import (get_player, get_available_inventory, nm_get_banner,
                            nm_set_config, nm_get_config)
from utils import nightmarket as NM

log = logging.getLogger(__name__)

SEP = "━━━━━━━━━━━━━━━━━━━━"


def _esc(s) -> str:
    return str(s).replace("_", "\\_").replace("*", "\\*").replace("`", "\\`").replace("[", "\\[")


async def _safe_edit(query, text, **kw):
    try:
        await query.edit_message_text(text, **kw)
    except BadRequest as e:
        err = str(e).lower()
        if "message is not modified" in err:
            return
        if any(x in err for x in ("can't be edited", "message to edit not found", "not found")):
            await query.message.reply_text(text, **kw)
        else:
            raise


async def _send_or_edit(update, context, text, kb=None):
    """Edit the callback message when possible, otherwise reply."""
    q = update.callback_query
    if q:
        await _safe_edit(q, text, parse_mode='Markdown', reply_markup=kb)
        await q.answer()
    else:
        msg = update.effective_message
        if msg:
            await msg.reply_text(text, parse_mode='Markdown', reply_markup=kb)


# ═══════════════════════ MAIN MENU ═══════════════════════

def _main_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 PLAYER MARKET", callback_data="nm:mkt:0"),
         InlineKeyboardButton("☠️ BOUNTY BOARD", callback_data="nm:bty:0")],
        [InlineKeyboardButton("📜 MY LISTINGS", callback_data="nm:mine:ACTIVE"),
         InlineKeyboardButton("🎯 MY BOUNTIES", callback_data="nm:myb:posted")],
        [InlineKeyboardButton("📖 LEDGER", callback_data="nm:ledger"),
         InlineKeyboardButton("◀ BACK", callback_data="nm:close")],
    ])


async def nightmarket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.effective_message.reply_text("❌ No character found. Use /start first.")
        return

    # housekeeping sweeps (idempotent, CAS-guarded inside)
    try:
        NM.expire_due_listings()
        NM.expire_due_bounties()
    except Exception as e:
        log.error("[NM] sweep failed: %s", e)

    locked = NM.locked_bounty_funds(user_id)
    text = (
        f"⚔️ *NIGHT MARKET*\n{SEP}\n\n"
        f"💰 *BALANCE*\n¥{(player.get('yen') or 0):,}\n"
        + (f"🔒 Locked in bounties: ¥{locked:,}\n" if locked else "")
        + f"\n{SEP}\n\n"
        f"🛒 *PLAYER MARKET* — trade w/ other slayers\n"
        f"☠️ *BOUNTY BOARD* — hunt players for yen\n"
        f"📜 *MY LISTINGS* • 🎯 *MY BOUNTIES* • 📖 *LEDGER*\n\n"
        f"{SEP}\n🌙 OPEN — Player\\-driven economy"
    )
    banner = nm_get_banner()
    if banner:
        try:
            await update.effective_message.reply_photo(banner, caption=text,
                                                       parse_mode='Markdown',
                                                       reply_markup=_main_kb())
            return
        except Exception as e:
            log.warning("[NM] banner send failed: %s", e)
    await update.effective_message.reply_text(text, parse_mode='Markdown',
                                              reply_markup=_main_kb())


# ═══════════════════════ PLAYER MARKET ═══════════════════════

SORTS = {"lowest": "💰 LOWEST", "highest": "💎 HIGHEST", "newest": "🕐 NEWEST", "oldest": "🕐 OLDEST"}


def _market_state(context):
    st = context.user_data.setdefault("nm_mkt", {})
    st.setdefault("page", 0)
    st.setdefault("sort", "newest")
    st.setdefault("search", None)
    return st


def _market_kb(st):
    rows = [[InlineKeyboardButton(f"[{SORTS[s]}]" if st["sort"] == s else SORTS[s],
                                  callback_data=f"nm:sort:{s}") for s in ("lowest", "highest")],
            [InlineKeyboardButton(f"[{SORTS[s]}]" if st["sort"] == s else SORTS[s],
                                  callback_data=f"nm:sort:{s}") for s in ("newest", "oldest")],
            [InlineKeyboardButton("🔎 SEARCH", callback_data="nm:search"),
             InlineKeyboardButton("➕ SELL", callback_data="nm:new:item")],
            [InlineKeyboardButton("◀ PREV", callback_data="nm:mkt:p:-1"),
             InlineKeyboardButton("NEXT ▶", callback_data="nm:mkt:p:1")],
            [InlineKeyboardButton("↩ MAIN", callback_data="nm:main")]]
    return InlineKeyboardMarkup(rows)


async def _show_market(update, context, page=None):
    st = _market_state(context)
    if page is not None:
        st["page"] = max(0, st["page"] + page)
    docs, pno, pages, total = NM.browse_listings(page=st["page"], search=st["search"], sort=st["sort"])
    st["page"] = min(st["page"], pages - 1)
    lines = [f"🛒 *PLAYER MARKET*\n{SEP}"]
    if st["search"]:
        lines.append(f'🔎 "{_esc(st["search"])}"  ({total} found)\n')
    if not docs:
        lines.append("\n<i>The lanterns flicker over empty stalls.</i>\n<i>Be the first — tap ➕ SELL.</i>")
    for l in docs:
        lines.append(
            f"\n{_esc(l['item_name'])} ×{l['remaining_quantity']}\n"
            f"Seller: {_esc(NM.seller_handle(l['seller_id']))}   "
            f"¥{l['unit_price']:,} ea · ⏳{NM.fmt_time_left(l['expires_at'])}"
        )
    lines.append(f"\n{SEP}\nPage {pno + 1}/{pages}")
    kb = _market_kb(st)
    if docs:
        row1 = [InlineKeyboardButton(f"#{NM.mk_public_id(l['listing_id'])}", callback_data=f"nm:info:{l['listing_id']}")
                for l in docs[:2]]
        rows = [row1]
        if len(docs) > 2:
            rows.append([InlineKeyboardButton(f"#{NM.mk_public_id(l['listing_id'])}", callback_data=f"nm:info:{l['listing_id']}")
                         for l in docs[2:4]])
        rows += kb.inline_keyboard
        kb = InlineKeyboardMarkup(rows)
    await _send_or_edit(update, context, "\n".join(lines), kb)


async def nm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router for every nm:* callback. Ownership/state verified server-side."""
    q = update.callback_query
    data = q.data or ""
    if not data.startswith("nm:"):
        return False
    parts = data.split(":")
    act = parts[1]
    arg = parts[2] if len(parts) > 2 else ""
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await q.answer("Create a character with /start first.", show_alert=True)
        return True

    # ── navigation ──
    if act == "main":
        await q.answer()
        await _show_market_back_to_main(update, context)
    elif act == "close":
        await q.answer()
        await _safe_edit(q, "🌙 The night market gates close behind you.", parse_mode='Markdown')
    elif act == "mkt":
        await _show_market(update, context, page=int(arg) if arg in ("-1", "1") else None)
    elif act == "sort":
        st = _market_state(context); st["sort"] = arg; st["page"] = 0
        await _show_market(update, context)
    elif act == "search":
        context.user_data["nm_flow"] = "search"
        await _safe_edit(q, "🔎 MARKET SEARCH\n━━━━━━━━━━━━━━━━━━\n\nSend item name to search.\n"
                            "Send `0` to clear the filter.", parse_mode='Markdown')
    elif act == "info":
        await _show_listing_info(update, context, int(arg))
    elif act == "buyask":
        await _show_buy_confirm(update, context, int(arg))
    elif act == "buygo":
        ok, msg = NM.purchase_listing(user_id, int(arg))
        context.user_data.pop("nm_flow", None)
        if ok:
            await q.answer("Purchased!", show_alert=True)
        await _send_or_edit(update, context, ("✅ " if ok else "❌ ") + msg,
                            InlineKeyboardMarkup([[InlineKeyboardButton("🛒 MARKET", callback_data="nm:mkt:0")],
                                                  [InlineKeyboardButton("↩ MAIN", callback_data="nm:main")]]))
    # ── create listing flow ──
    elif act == "new":
        await _new_listing_start(update, context)
    elif act == "selitem":
        idx = int(arg)
        avail = get_available_inventory(user_id)
        if not (0 <= idx < len(avail)):
            await q.answer("That item is no longer available.", show_alert=True)
            return True
        it = avail[idx]
        context.user_data["nm_listing"] = {"item": it["item_name"], "type": it.get("item_type", "item"),
                                          "have": it["quantity"]}
        context.user_data["nm_flow"] = "nm_qty"
        await _safe_edit(
            q,
            f"🛒 CREATE LISTING\n{SEP}\n\n{_esc(it['item_name'])}\n\nAvailable: {it['quantity']}\n\n"
            f"Enter quantity to sell:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ BACK", callback_data="nm:new:item")]]))
    elif act == "price":
        st = context.user_data.get("nm_listing")
        if not st:
            await q.answer("Session expired — start again.", show_alert=True)
            return True
        context.user_data["nm_flow"] = "nm_price"
        fee_rate = NM.cfg("market_fee_permille")
        await _safe_edit(
            q,
            f"🛒 CONFIRM LISTING\n{SEP}\n\nItem: {_esc(st['item'])}\nQuantity: {st['qty']}\n\n"
            f"Enter price per unit:\n_(fee {fee_rate/10:g}% applied on sale)_",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ BACK", callback_data="nm:new:item")]]))
    elif act == "listgo":
        st = context.user_data.get("nm_listing")
        if not st:
            await q.answer("Session expired.", show_alert=True)
            return True
        ok, res = NM.create_listing(user_id, st["item"], st["qty"], st["price"])
        context.user_data.pop("nm_listing", None)
        context.user_data.pop("nm_flow", None)
        if not ok:
            await _send_or_edit(update, context, f"❌ {res}",
                                InlineKeyboardMarkup([[InlineKeyboardButton("🛒 MARKET", callback_data="nm:mkt:0")]]))
        else:
            gross = st["qty"] * st["price"]
            fee = gross * st.get("fee_permille", NM.cfg("market_fee_permille")) // 1000
            await _send_or_edit(
                update, context,
                f"✅ LISTED #{NM.mk_public_id(res['listing_id'])}\n{SEP}\n\n"
                f"{_esc(st['item'])} ×{st['qty']}\n¥{st['price']:,} each · Total ¥{gross:,}\n"
                f"Fee on sale: ¥{fee:,} → you receive ¥{gross - fee:,}\n"
                f"Expires: {NM.fmt_time_left(res['expires_at'])}\n\n"
                f"_Items are locked in escrow until sold, cancelled, or expired._",
                InlineKeyboardMarkup([[InlineKeyboardButton("📜 MY LISTINGS", callback_data="nm:mine:ACTIVE")],
                                      [InlineKeyboardButton("🛒 MARKET", callback_data="nm:mkt:0")]]))
    elif act == "cancelask":
        l = NM.get_listing(int(arg))
        if not l or int(l["seller_id"]) != int(user_id):
            await q.answer("Not your listing.", show_alert=True)
            return True
        await _safe_edit(
            q,
            f"❌ CANCEL LISTING?\n{SEP}\n\n{_esc(l['item_name'])} ×{l['remaining_quantity']}\n\n"
            f"The items will be returned to your inventory.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("YES, CANCEL", callback_data=f"nm:cancelgo:{arg}"),
                 InlineKeyboardButton("NO", callback_data="nm:mine:ACTIVE")]]))
    elif act == "cancelgo":
        ok, msg = NM.cancel_listing(user_id, int(arg))
        await _send_or_edit(update, context, ("✅ " if ok else "❌ ") + msg,
                            InlineKeyboardMarkup([[InlineKeyboardButton("📜 MY LISTINGS", callback_data="nm:mine:ACTIVE")],
                                                  [InlineKeyboardButton("↩ MAIN", callback_data="nm:main")]]))
    # ── my listings ──
    elif act == "mine":
        await _show_my_listings(update, context, arg or "ACTIVE")
    # ── bounty board ──
    elif act == "bty":
        await _show_bounty_board(update, context, page=int(arg) if arg.isdigit() else 0)
    elif act == "btyinfo":
        await _show_bounty_detail(update, context, int(arg))
    elif act == "btyaccept":
        ok, msg = NM.accept_bounty(user_id, int(arg))
        await q.answer("Accepted!" if ok else "Failed", show_alert=not ok)
        await _send_or_edit(update, context, msg,
                            InlineKeyboardMarkup([[InlineKeyboardButton("☠️ BOARD", callback_data="nm:bty:0")],
                                                  [InlineKeyboardButton("↩ MAIN", callback_data="nm:main")]]))
    elif act == "newbty":
        context.user_data["nm_flow"] = "nm_bty_target"
        await _safe_edit(
            q,
            f"☠️ CREATE BOUNTY\n{SEP}\n\nEnter target @username:",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ BACK", callback_data="nm:main")]]))
    elif act == "btyreward":
        st = context.user_data.get("nm_bounty")
        if not st:
            await q.answer("Session expired.", show_alert=True)
            return True
        context.user_data["nm_flow"] = "nm_bty_reward"
        await _safe_edit(
            q,
            f"☠️ TARGET: {_esc(st['handle'])}\n\nEnter reward amount \\(¥):\n"
            f"Min ¥{NM.cfg('min_bounty_reward'):,} · Max ¥{NM.cfg('max_bounty_reward'):,}\n"
            f"Money is escrowed immediately.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀ BACK", callback_data="nm:main")]]))
    elif act == "btyconfirm":
        st = context.user_data.get("nm_bounty")
        if not st:
            await q.answer("Session expired.", show_alert=True)
            return True
        await _safe_edit(
            q,
            f"☠️ CONFIRM BOUNTY\n{SEP}\n\nTarget: {_esc(st['handle'])}\nReward: ¥{st['reward']:,}\n\n"
            f"Requirement: ⚔️ Defeat target in battle\n"
            f"Duration: {NM.cfg('bounty_expiry_hours')}h\n"
            f"Your balance after: ¥{max(0, (player.get('yen') or 0) - st['reward']):,}\n{SEP}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ POST BOUNTY", callback_data="nm:btygo")],
                [InlineKeyboardButton("❌ CANCEL", callback_data="nm:main")]]))
    elif act == "btygo":
        # target/reward are read from server-side session state only —
        # never from the (unsigned, user-editable) callback payload.
        st = context.user_data.get("nm_bounty")
        if not st or "reward" not in st:
            await q.answer("Session expired — start the bounty again.", show_alert=True)
            return True
        ok, res = NM.create_bounty(user_id, st["target"], st["reward"])
        context.user_data.pop("nm_bounty", None)
        context.user_data.pop("nm_flow", None)
        if ok:
            await _send_or_edit(
                update, context,
                f"☠️ CONTRACT #{NM.bt_public_id(res['bounty_id'])} POSTED\n{SEP}\n\n"
                f"Target: {_esc(res['target_name'])}\nReward: ¥{res['reward']:,}\n"
                f"Escrowed from your balance ✅\nExpires: {NM.fmt_time_left(res['expires_at'])}",
                InlineKeyboardMarkup([[InlineKeyboardButton("☠️ BOARD", callback_data="nm:bty:0")],
                                      [InlineKeyboardButton("🎯 MY BOUNTIES", callback_data="nm:myb:posted")]]))
        else:
            await _send_or_edit(update, context, f"❌ {res}",
                                InlineKeyboardMarkup([[InlineKeyboardButton("☠️ BOARD", callback_data="nm:bty:0")]]))
    elif act == "myb":
        await _show_my_bounties(update, context, arg or "posted")
    elif act == "btycancelask":
        b = NM.get_bounty(int(arg))
        if not b or int(b["creator_id"]) != int(user_id):
            await q.answer("Not your contract.", show_alert=True)
            return True
        await _safe_edit(
            q,
            f"❌ CANCEL CONTRACT #{NM.bt_public_id(b['bounty_id'])}?\n{SEP}\n\n"
            f"Target: {_esc(NM.seller_handle(b['target_id']))}\nReward: ¥{b['reward']:,}\n\n"
            f"Full reward refund only while unaccepted.",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("YES, CANCEL", callback_data=f"nm:btycancel:{arg}"),
                 InlineKeyboardButton("NO", callback_data="nm:myb:posted")]]))
    elif act == "btycancel":
        ok, msg = NM.cancel_bounty(user_id, int(arg))
        await _send_or_edit(update, context, ("✅ " if ok else "❌ ") + msg,
                            InlineKeyboardMarkup([[InlineKeyboardButton("🎯 MY BOUNTIES", callback_data="nm:myb:posted")]]))
    elif act == "ledger":
        await _show_ledger(update, context)
    else:
        await q.answer()
    return True


async def _show_market_back_to_main(update, context):
    q = update.callback_query
    await _safe_edit(q,
                     f"🌙 *NIGHT MARKET*\n{SEP}\nChoose your path…",
                     parse_mode='Markdown', reply_markup=_main_kb())


# ═══════════════════════ LISTING PAGES ═══════════════════════

async def _show_listing_info(update, context, lid):
    q = update.callback_query
    l = NM.get_listing(lid)
    if not l:
        await _safe_edit(q, "❌ Listing no longer exists.")
        return
    status = l["status"]
    expired = bool(l.get("expires_at") and l["expires_at"] <= datetime.now())
    gross = l["remaining_quantity"] * l["unit_price"]
    kb_rows = []
    if status == "ACTIVE" and not expired and int(l["seller_id"]) != int(update.effective_user.id):
        kb_rows.append([InlineKeyboardButton("💰 BUY", callback_data=f"nm:buyask:{lid}")])
    if int(l["seller_id"]) == int(update.effective_user.id) and status == "ACTIVE":
        kb_rows.append([InlineKeyboardButton("❌ CANCEL LISTING", callback_data=f"nm:cancelask:{lid}")])
    kb_rows.append([InlineKeyboardButton("◀ BACK", callback_data="nm:mkt:0")])
    badge = {"ACTIVE": "● ACTIVE", "SOLD": "✓ SOLD", "EXPIRED": "⏱ EXPIRED", "CANCELLED": "✖ CANCELLED"}.get(status, status)
    await _safe_edit(
        q,
        f"🛒 MARKET LISTING\n{SEP}\n\n"
        f"{_esc(l['item_name']).upper()}\n\n"
        f"Quantity:\n{l['remaining_quantity']}\n\n"
        f"Price:\n¥{l['unit_price']:,} each\n\n"
        f"Total:\n¥{gross:,}\n\n"
        f"Seller:\n{_esc(NM.seller_handle(l['seller_id']))}\n\n"
        f"Listing ID:\n#{NM.mk_public_id(lid)}\n\n"
        f"Expires:\n{NM.fmt_time_left(l['expires_at']) if status == 'ACTIVE' else '—'}\n"
        f"Status: {badge}\n{SEP}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(kb_rows))


async def _show_buy_confirm(update, context, lid):
    q = update.callback_query
    user_id = update.effective_user.id
    l = NM.get_listing(lid)
    if not l or l["status"] != "ACTIVE":
        await _safe_edit(q, "❌ That listing is gone.")
        return
    if int(l["seller_id"]) == int(user_id):
        await _safe_edit(q, "You cannot buy your own listing.")
        return
    gross = l["remaining_quantity"] * l["unit_price"]
    player = get_player(user_id)
    bal = player.get("yen") or 0
    after = bal - gross
    note = "" if after >= 0 else "\n\n⚠️ Insufficient balance."
    await _safe_edit(
        q,
        f"💰 PURCHASE CONFIRMATION\n{SEP}\n\n"
        f"{_esc(l['item_name'])} ×{l['remaining_quantity']}\n\n"
        f"Price:\n¥{gross:,}\n\n"
        f"Your balance:\n¥{bal:,}\n\n"
        f"Balance after:\n¥{max(0, after):,}{note}\n{SEP}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ CONFIRM PURCHASE", callback_data=f"nm:buygo:{lid}")],
            [InlineKeyboardButton("❌ CANCEL", callback_data=f"nm:info:{lid}")]]))


# ═══════════════════════ CREATE LISTING ═══════════════════════

async def _new_listing_start(update, context):
    q = update.callback_query
    user_id = update.effective_user.id
    avail = get_available_inventory(user_id)
    lines = [f"🛒 CREATE LISTING\n{SEP}\n\nSelect an item:"]
    rows = []
    shown = avail[:8]
    for i, it in enumerate(shown):
        rows.append([InlineKeyboardButton(f"{it['item_name']} ×{it['quantity']}",
                                          callback_data=f"nm:selitem:{i}")])
    if not shown:
        lines.append("\n<i>No tradable items in your pack.</i>")
    rows.append([InlineKeyboardButton("◀ BACK", callback_data="nm:main")])
    await _safe_edit(q, "\n".join(lines), parse_mode='Markdown',
                     reply_markup=InlineKeyboardMarkup(rows))


# ═══════════════════════ MY LISTINGS ═══════════════════════

STATUS_BADGE = {"ACTIVE": "● ACTIVE", "SOLD": "✓ SOLD", "EXPIRED": "⏱ EXPIRED", "CANCELLED": "✖ CANCELLED"}


async def _show_my_listings(update, context, status):
    q = update.callback_query
    user_id = update.effective_user.id
    docs = NM.my_listings(user_id, status)
    lines = [f"📜 MY LISTINGS\n{SEP}\n\n_{status}_\n"]
    rows = [[InlineKeyboardButton(t, callback_data=f"nm:mine:{t}")
             for t in ("ACTIVE", "SOLD", "EXPIRED")]]
    for l in docs[:6]:
        extra = (f" · ⏳{NM.fmt_time_left(l['expires_at'])}" if status == "ACTIVE" else "")
        lines.append(f"{_esc(l['item_name'])} ×{l['remaining_quantity']}\n"
                     f"¥{l['unit_price']:,} each{extra}  [{STATUS_BADGE.get(l['status'], l['status'])}]  `#{NM.mk_public_id(l['listing_id'])}`")
        if status == "ACTIVE":
            rows.insert(-1, [InlineKeyboardButton(f"Cancel #{NM.mk_public_id(l['listing_id'])}",
                                                  callback_data=f"nm:cancelask:{l['listing_id']}")])
    if not docs:
        lines.append("<i>Nothing here yet.</i>")
    lines.append(f"\n{SEP}")
    rows.append([InlineKeyboardButton("➕ NEW LISTING", callback_data="nm:new:item"),
                 InlineKeyboardButton("↩ MAIN", callback_data="nm:main")])
    await _safe_edit(q, "\n".join(lines), parse_mode='Markdown',
                     reply_markup=InlineKeyboardMarkup(rows))


# ═══════════════════════ BOUNTY BOARD ═══════════════════════

async def _show_bounty_board(update, context, page=0):
    q = update.callback_query
    user_id = update.effective_user.id
    NM.expire_due_bounties()
    docs, pno, pages, total = NM.browse_bounties(page=page)
    lines = [f"☠️ BOUNTY BOARD\n{SEP}\n\n_ACTIVE CONTRACTS_"]
    rows = []
    for b in docs[:4]:
        state = "● OPEN" if b["status"] == "OPEN" else f"🤝 {b['hunter_id'] and 'TAKEN'}"
        lines.append(
            f"\n☠️ #{NM.bt_public_id(b['bounty_id'])}\n"
            f"TARGET: {_esc(NM.seller_handle(b['target_id']))}\n"
            f"💰 ¥{b['reward']:,}  ·  Posted by {_esc(NM.seller_handle(b['creator_id']))}\n"
            f"⚔️ Defeat target in battle  ·  ⏳{NM.fmt_time_left(b['expires_at'])}  [{state}]"
        )
        if b["status"] == "OPEN" and int(b["creator_id"]) != int(user_id) and int(b["target_id"]) != int(user_id):
            rows.append([InlineKeyboardButton(f"⚔️ ACCEPT #{NM.bt_public_id(b['bounty_id'])}",
                                              callback_data=f"nm:btyinfo:{b['bounty_id']}")])
    if not docs:
        lines.append("\n<i>No blood contracts written tonight.</i>")
    lines.append(f"\n{SEP}\nPage {pno + 1}/{pages}")
    rows.append([InlineKeyboardButton("◀ PREV", callback_data=f"nm:bty:{max(0, page - 1)}"),
                 InlineKeyboardButton("NEXT ▶", callback_data=f"nm:bty:{page + 1}")])
    rows.append([InlineKeyboardButton("➕ POST BOUNTY", callback_data="nm:newbty"),
                 InlineKeyboardButton("🎯 MY BOUNTIES", callback_data="nm:myb:posted")])
    rows.append([InlineKeyboardButton("↩ MAIN", callback_data="nm:main")])
    await _safe_edit(q, "\n".join(lines), parse_mode='Markdown',
                     reply_markup=InlineKeyboardMarkup(rows))


async def _show_bounty_detail(update, context, bid):
    q = update.callback_query
    user_id = update.effective_user.id
    b = NM.get_bounty(bid)
    if not b:
        await _safe_edit(q, "❌ Contract not found.")
        return
    can_accept = (b["status"] == "OPEN" and int(b["creator_id"]) != int(user_id)
                  and int(b["target_id"]) != int(user_id))
    rows = []
    if can_accept:
        rows.append([InlineKeyboardButton("⚔️ ACCEPT", callback_data=f"nm:btyaccept:{bid}")])
    if int(b["creator_id"]) == int(user_id) and b["status"] == "OPEN":
        rows.append([InlineKeyboardButton("❌ CANCEL CONTRACT", callback_data=f"nm:btycancelask:{bid}")])
    rows.append([InlineKeyboardButton("◀ BACK", callback_data="nm:bty:0")])
    hunter = NM.seller_handle(b["hunter_id"]) if b.get("hunter_id") else "—"
    await _safe_edit(
        q,
        f"☠️ CONTRACT #{NM.bt_public_id(bid)}\n{SEP}\n\n"
        f"Target:\n{_esc(NM.seller_handle(b['target_id']))}\n\n"
        f"Reward:\n¥{b['reward']:,}  _(escrowed)_\n\n"
        f"Requirement:\n⚔️ Defeat target in one eligible duel\n\n"
        f"Hunter: {_esc(hunter)}\n"
        f"Posted by: {_esc(NM.seller_handle(b['creator_id']))}\n"
        f"Expires: {NM.fmt_time_left(b['expires_at'])}\n"
        f"Status: {b['status']}\n{SEP}",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(rows))


async def _show_my_bounties(update, context, tab):
    q = update.callback_query
    user_id = update.effective_user.id
    posted, hunting = NM.my_bounties(user_id)
    docs = posted if tab == "posted" else hunting
    lines = [f"🎯 MY BOUNTIES\n{SEP}\n\n_{tab.upper()}_\n"]
    for b in docs[:6]:
        who = NM.seller_handle(b["target_id"]) if tab == "posted" else NM.seller_handle(b["creator_id"])
        mark = {"OPEN": "● OPEN", "ACCEPTED": "● ACTIVE", "COMPLETED": "✓ COMPLETED",
                "EXPIRED": "⏱ EXPIRED", "CANCELLED": "✖ CANCELLED"}.get(b["status"], b["status"])
        lines.append(f"☠️ #{NM.bt_public_id(b['bounty_id'])}  {_esc(who)}\n¥{b['reward']:,}  [{mark}]")
    if not docs:
        lines.append("<i>No contracts signed.</i>")
    lines.append(f"\n{SEP}")
    await _safe_edit(
        q, "\n".join(lines), parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📤 POSTED", callback_data="nm:myb:posted"),
             InlineKeyboardButton("⚔️ HUNTING", callback_data="nm:myb:hunting")],
            [InlineKeyboardButton("➕ POST BOUNTY", callback_data="nm:newbty")],
            [InlineKeyboardButton("↩ MAIN", callback_data="nm:main")]]))


# ═══════════════════════ LEDGER ═══════════════════════

TYPE_ICON = {"BUY": "🛒 BUY", "SELL": "💰 SELL", "BOUNTY_ESCROW": "☠️ ESCROW",
             "BOUNTY_REWARD": "☠️ REWARD", "BOUNTY_REFUND": "↩ REFUND",
             "BOUNTY_PAID": "☠️ PAID OUT"}


async def _show_ledger(update, context):
    q = update.callback_query
    user_id = update.effective_user.id
    entries = NM.ledger(user_id, limit=10)
    lines = [f"📖 MARKET LEDGER\n{SEP}"]
    net = 0
    for e in entries:
        amt = int(e.get("amount", 0))
        net += amt
        meta = e.get("metadata", {})
        detail = meta.get("item") or ("@" + str(meta.get("target", "")).lstrip("@")) or e.get("reference_type", "")
        sign = "+" if amt > 0 else ""
        icon = TYPE_ICON.get(e.get("type"), e.get("type", "?"))
        lines.append(f"\n{icon}\n{_esc(detail)}\n{sign}¥{abs(amt):,}" if amt else
                     f"\n{icon}\n{_esc(detail)}\n—")
    if not entries:
        lines.append("\n<i>Your ledger page is blank.</i>")
    lines.append(f"\n{SEP}\nNET: {'+' if net > 0 else ''}¥{net:,}")
    await _safe_edit(q, "\n".join(lines), parse_mode='Markdown',
                     reply_markup=InlineKeyboardMarkup([
                         [InlineKeyboardButton("🛒 MARKET", callback_data="nm:mkt:0"),
                          InlineKeyboardButton("☠️ BOUNTIES", callback_data="nm:bty:0")],
                         [InlineKeyboardButton("↩ MAIN", callback_data="nm:main")]]))


# ═══════════════════════ TEXT INPUT STEPS ═══════════════════════

async def handle_nightmarket_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Conversational steps (search / qty / price / target / reward).
    Returns True if this update was consumed."""
    flow = context.user_data.get("nm_flow")
    if not flow or not update.message:
        return False
    raw = (update.message.text or "").strip()
    user_id = update.effective_user.id

    if flow == "search":
        st = _market_state(context)
        st["search"] = None if raw in ("0", "-", "clear") else raw[:60]
        st["page"] = 0
        context.user_data.pop("nm_flow", None)
        await _show_market(update, context)
        return True

    if flow == "nm_qty":
        st = context.user_data.get("nm_listing") or {}
        if not raw.isdigit() or int(raw) <= 0:
            await update.message.reply_text("Enter a whole number greater than 0.")
            return True
        qty = min(int(raw), NM.cfg("max_listing_qty"))
        if qty > st.get("have", 0):
            await update.message.reply_text(f"You only have {st.get('have', 0)} usable of that item.")
            return True
        st["qty"] = qty
        context.user_data["nm_flow"] = "nm_price"
        await update.message.reply_text(
            f"🛒 {st['item']} ×{qty}\n\nNow enter price per unit \\(¥):", parse_mode='Markdown')
        return True

    if flow == "nm_price":
        st = context.user_data.get("nm_listing") or {}
        if not raw.isdigit() or int(raw) <= 0:
            await update.message.reply_text("Enter a whole-number price in yen.")
            return True
        price = int(raw)
        if price < NM.cfg("min_listing_price") or price > NM.cfg("max_listing_price"):
            await update.message.reply_text(
                f"Price must be ¥{NM.cfg('min_listing_price'):,} – ¥{NM.cfg('max_listing_price'):,}.")
            return True
        st["price"] = price
        context.user_data.pop("nm_flow", None)
        gross = st["qty"] * price
        fee = NM.fee_of(gross, "market_fee_permille")
        hours = NM.cfg("listing_expiry_hours")
        # NOTE: callback carries only a token — qty/price stay server-side in
        # user_data (unsigned callback data must never carry financials).
        await update.message.reply_text(
            f"🛒 CONFIRM LISTING\n{SEP}\n\n"
            f"Item:\n{_esc(st['item'])}\n\nQuantity:\n{st['qty']}\n\n"
            f"Price:\n¥{price:,} each\n\nTotal:\n¥{gross:,}\n\n"
            f"Market fee:\n¥{fee:,}\n\nYou receive:\n¥{gross - fee:,}\n\n"
            f"Expires:\n{hours} hours\n{SEP}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ LIST", callback_data="nm:listgo"),
                 InlineKeyboardButton("❌ CANCEL", callback_data="nm:main")]]))
        return True

    if flow == "nm_bty_target":
        target = NM.resolve_target(raw)
        if not target:
            await update.message.reply_text("No such player. Send their exact @username.")
            return True
        if int(target["user_id"]) == int(user_id):
            await update.message.reply_text("You cannot put a bounty on yourself.")
            return True
        context.user_data["nm_bounty"] = {"target": int(target["user_id"]),
                                          "handle": NM.seller_handle(target["user_id"])}
        context.user_data["nm_flow"] = "nm_bty_reward"
        await update.message.reply_text(
            f"☠️ TARGET: {_esc(context.user_data['nm_bounty']['handle'])}\n\n"
            f"Enter reward \\(¥): Min ¥{NM.cfg('min_bounty_reward'):,} · Max ¥{NM.cfg('max_bounty_reward'):,}",
            parse_mode='Markdown')
        return True

    if flow == "nm_bty_reward":
        st = context.user_data.get("nm_bounty") or {}
        if not raw.isdigit() or int(raw) <= 0:
            await update.message.reply_text("Enter the reward in whole yen.")
            return True
        reward = int(raw)
        if reward < NM.cfg("min_bounty_reward") or reward > NM.cfg("max_bounty_reward"):
            await update.message.reply_text(
                f"Reward must be ¥{NM.cfg('min_bounty_reward'):,} – ¥{NM.cfg('max_bounty_reward'):,}.")
            return True
        player = get_player(user_id)
        fee = NM.fee_of(reward, "bounty_fee_permille")
        if (player.get("yen") or 0) < reward + fee:
            await update.message.reply_text(
                f"Insufficient balance — need ¥{reward + fee:,} escrow. You have ¥{(player.get('yen') or 0):,}.")
            return True
        context.user_data.pop("nm_flow", None)
        st["reward"] = reward
        await update.message.reply_text(
            f"☠️ CONFIRM BOUNTY\n{SEP}\n\nTarget:\n{st['handle']}\n\nReward:\n¥{reward:,}\n\n"
            + (f"Fee:\n¥{fee:,}\n\n" if fee else "")
            + f"Requirement:\n⚔️ Defeat target in battle\n\n"
            f"💰 Money leaves your balance the moment you post.\n{SEP}",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ POST", callback_data=f"nm:btygo:{st['target']}:{reward}"),
                 InlineKeyboardButton("❌ CANCEL", callback_data="nm:main")]]))
        return True

    return False


# ═══════════════════════ OWNER BANNER ═══════════════════════

async def setmarketbanner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: /setmarketbanner — attach or reply to a photo to set the
    Night Market banner image. `/setmarketbanner clear` removes it."""
    from config import OWNER_ID
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.effective_message.reply_text("🔒 Owner only.")
        return
    args = " ".join(context.args or []).strip().lower()
    if args == "clear":
        nm_set_config(banner_file_id="")
        await update.effective_message.reply_text("🧹 Banner removed.")
        return
    msg = update.message.reply_to_message or update.message
    file_id = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.document and (msg.document.mime_type or "").startswith("image/"):
        file_id = msg.document.file_id
    if not file_id:
        await update.effective_message.reply_text(
            "🖼 Send or reply to a photo/GIF document with /setmarketbanner\n"
            "Use `/setmarketbanner clear` to remove.")
        return
    nm_set_config(banner_file_id=file_id)
    await update.effective_message.reply_text("✅ Night Market banner saved. It now shows on /nightmarket.")


async def marketsettings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only: view/tune Night Market economy knobs.
    /marketsettings key=value ..."""
    from config import OWNER_ID
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.effective_message.reply_text("🔒 Owner only.")
        return
    args = context.args or []
    changed = {}
    for a in args:
        if "=" in a:
            k, _, v = a.partition("=")
            k = k.strip()
            if k in NM.NM_DEFAULTS:
                try:
                    nm_set_config(**{k: int(v)})
                    changed[k] = int(v)
                except ValueError:
                    pass
    if changed:
        nm_get_config.cache_clear() if hasattr(nm_get_config, "cache_clear") else None
        await update.effective_message.reply_text(f"✅ Updated: {changed}")
        return
    lines = [f"⚙️ NIGHT MARKET SETTINGS\n{SEP}"]
    for k, default in NM.NM_DEFAULTS.items():
        cur = NM.cfg(k)
        pretty = f"{cur / 10:g}%" if k.endswith("_permille") else f"{cur:,}"
        lines.append(f"{k}: {pretty}" + (" (default)" if cur == default else ""))
    lines.append(f"\nUsage: /marketsettings market_fee_permille=30")
    await update.effective_message.reply_text("\n".join(lines))
