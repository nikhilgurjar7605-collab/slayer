import re
from datetime import datetime
from telegram.error import BadRequest, TimedOut
from telegram import Update
from telegram.ext import ContextTypes
from utils.guards import dm_only
from utils.database import (get_player, update_player, col,
                             get_inventory, remove_item, add_item,
                             get_market_listings, get_listing_by_index)

LISTING_FEE_PCT = 0.05
TYPE_EMOJI = {
    'sword':    '⚔️',
    'armor':    '🛡️',
    'item':     '🧪',
    'material': '🎁',
    'scroll':   '📜',
    'misc':     '📦',
}


def _escape(text: str) -> str:
    """Escape special Markdown v1 characters in dynamic text."""
    # In Markdown v1, these break formatting: _ * ` [
    return str(text).replace('_', '\\_').replace('*', '\\*').replace('`', '\\`').replace('[', '\\[')


async def _safe_edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        elif any(x in err.lower() for x in ("can't be edited", "message to edit not found", "not found")):
            try:
                await query.message.reply_text(text, **kwargs)
            except Exception:
                pass
        else:
            raise
    except TimedOut:
        pass


# ── /market — browse listings ──────────────────────────────────────────────
def _seed_npc_market():
    """Seed default NPC listings if market is empty."""
    from utils.database import col as _col
    if _col("market_listings").count_documents({"status": "active"}) > 0:
        return
    seeds = [
        {"item_name": "Full Recovery Gourd",  "item_type": "item",     "price": 800,   "seller_id": 0, "quantity": 1, "status": "active"},
        {"item_name": "Stamina Pill",          "item_type": "item",     "price": 400,   "seller_id": 0, "quantity": 5, "status": "active"},
        {"item_name": "Wisteria Antidote",     "item_type": "item",     "price": 600,   "seller_id": 0, "quantity": 3, "status": "active"},
        {"item_name": "Demon Blood",           "item_type": "material", "price": 1200,  "seller_id": 0, "quantity": 2, "status": "active"},
        {"item_name": "Demon Crystal",         "item_type": "material", "price": 2500,  "seller_id": 0, "quantity": 1, "status": "active"},
        {"item_name": "Nichirin Fragment",     "item_type": "material", "price": 1800,  "seller_id": 0, "quantity": 2, "status": "active"},
        {"item_name": "Boss Shard",            "item_type": "material", "price": 5000,  "seller_id": 0, "quantity": 1, "status": "active"},
        {"item_name": "Basic Nichirin Blade",  "item_type": "sword",    "price": 3000,  "seller_id": 0, "quantity": 1, "status": "active"},
        {"item_name": "Corps Uniform",         "item_type": "armor",    "price": 2000,  "seller_id": 0, "quantity": 1, "status": "active"},
    ]
    _col("market_listings").insert_many(seeds)


async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    msg     = update.message or (update.callback_query.message if update.callback_query else None)
    if not player:
        if msg:
            await msg.reply_text("❌ No character found. Use /start to create one.")
        return

    try:
        _seed_npc_market()
    except Exception:
        pass

    search = ' '.join(context.args) if context.args else None
    try:
        listings = get_market_listings(search)
    except Exception:
        await msg.reply_text("❌ Market temporarily unavailable. Try again.")
        return

    if not listings:
        note = f"for *{_escape(search)}*" if search else ""
        await msg.reply_text(
            f"🏪 *PLAYER MARKET*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"_No listings found {note}._\n\n"
            f"💡 `/list [item] [price]` — Sell your items\n"
            f"🔍 `/market [search]` — Search listings",
            parse_mode='Markdown'
        )
        return

    lines = [
        "🏪 *PLAYER MARKET*",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"📊 *{len(listings)} listings*  •  💰 Balance: *{player['yen']:,}¥*",
        "",
    ]
    for i, item in enumerate(listings[:20], 1):
        emoji = TYPE_EMOJI.get(item.get('item_type', 'misc'), '📦')
        if item.get('seller_id', 0) == 0:
            sname = "🏪 Shop"
        else:
            seller = get_player(item['seller_id'])
            # ✅ fix: escape username — underscores break Markdown
            raw_name = f"@{seller['username']}" if seller and seller.get('username') else "Player"
            sname = _escape(raw_name)
        qty     = item.get('quantity', 1)
        qty_txt = f" ×{qty}" if qty > 1 else ""
        # ✅ fix: escape item name — special chars break Markdown
        safe_name = _escape(item['item_name'])
        lines.append(
            f"  `[{i}]` {emoji} *{safe_name}*{qty_txt}"
            f" — *{item['price']:,}¥*  _{sname}_"
        )

    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "💡 `/buy market [item name] [amount]` — Buy items",
        "📦 `/list [item] [price]` — List your item",
    ]
    # ✅ fix: wrap send in try/except with fallback to plain text
    try:
        await msg.reply_text('\n'.join(lines), parse_mode='Markdown')
    except BadRequest:
        # Strip markdown and retry as plain text
        plain = '\n'.join(lines).replace('*', '').replace('_', '').replace('`', '')
        await msg.reply_text(plain)


# ── /list — list an item for sale ─────────────────────────────────────────
@dm_only
async def market_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /list                           — show listable inventory
    /list [item name] [price]       — list 1 item
    /list [item name] [qty] [price] — list multiple
    """
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    inv      = get_inventory(user_id)
    equipped = [player.get('equipped_sword'), player.get('equipped_armor')]
    listable = [i for i in inv
                if i.get('quantity', 1) > 0
                and i['item_name'] not in equipped
                and i.get('item_type') not in ('sword', 'armor')]

    if not context.args:
        if not listable:
            await update.message.reply_text(
                "📦 *YOUR LISTABLE ITEMS*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                "_You have no items to list._\n\n"
                "Go explore to find materials!",
                parse_mode='Markdown'
            )
            return
        lines = [
            "📦 *YOUR LISTABLE ITEMS*",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"💰 Balance: *{player['yen']:,}¥*",
            f"💸 Listing fee: *{int(LISTING_FEE_PCT*100)}%* of sale price\n",
        ]
        TYPE_ICONS = {'material': '🎁', 'item': '🧪', 'potion': '🔮', 'scroll': '📜'}
        for item in listable[:20]:
            icon = TYPE_ICONS.get(item.get('item_type', 'material'), '📦')
            qty  = item.get('quantity', 1)
            # ✅ fix: escape item name
            lines.append(f"  {icon} *{_escape(item['item_name'])}* × {qty}")
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "📖 Usage: `/list [item name] [price]`",
            "📖 Multi:  `/list [item name] [qty] [price]`",
            "🔤 Example: `/list Demon Blood 500`",
            "🔤 Example: `/list Boss Shard 2 15000`",
        ]
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    args = context.args
    try:
        price = int(args[-1])
    except ValueError:
        await update.message.reply_text(
            "❌ Last argument must be the price.\n"
            "Example: `/list Demon Blood 500`",
            parse_mode='Markdown'
        )
        return

    qty_to_list = 1
    if len(args) >= 3:
        try:
            qty_to_list = int(args[-2])
            item_name   = ' '.join(args[:-2]).strip()
        except ValueError:
            item_name = ' '.join(args[:-1]).strip()
    else:
        item_name = ' '.join(args[:-1]).strip()

    if not item_name:
        await update.message.reply_text(
            "❌ Missing item name.\nExample: `/list Demon Blood 500`",
            parse_mode='Markdown'
        )
        return

    if price < 10:
        await update.message.reply_text("❌ Minimum price is *10¥*.", parse_mode='Markdown')
        return

    qty_to_list = max(1, min(qty_to_list, 99))

    owned = next((i for i in inv if i['item_name'].lower() == item_name.lower()), None)
    if not owned:
        owned = next((i for i in inv if item_name.lower() in i['item_name'].lower()), None)
    if not owned:
        await update.message.reply_text(
            f"❌ *Not in inventory:* `{_escape(item_name)}`\n\n"
            f"Type `/list` to see your listable items.",
            parse_mode='Markdown'
        )
        return

    if owned['item_name'] in equipped:
        await update.message.reply_text(
            f"❌ *Can't list equipped items!*\nUnequip *{_escape(owned['item_name'])}* first.",
            parse_mode='Markdown'
        )
        return

    available = owned.get('quantity', 1)
    if qty_to_list > available:
        await update.message.reply_text(
            f"❌ You only have *{available}× {_escape(owned['item_name'])}*.",
            parse_mode='Markdown'
        )
        return

    fee = max(1, int(price * LISTING_FEE_PCT * qty_to_list))
    if player['yen'] < fee:
        await update.message.reply_text(
            f"❌ *Not enough Yen for listing fee!*\n\n"
            f"💸 Fee: *{fee:,}¥*  |  💰 You have: *{player['yen']:,}¥*",
            parse_mode='Markdown'
        )
        return

    remove_item(user_id, owned['item_name'], qty_to_list)
    update_player(user_id, yen=player['yen'] - fee)

    from datetime import datetime as _dt
    for _ in range(qty_to_list):
        col("market_listings").insert_one({
            "seller_id": user_id,
            "item_name": owned['item_name'],
            "item_type": owned.get('item_type', 'material'),
            "price":     price,
            "status":    "active",
            "listed_at": _dt.now(),
            "quantity":  1,
        })

    qty_str = f" × {qty_to_list}" if qty_to_list > 1 else ""
    await update.message.reply_text(
        f"✅ *ITEM LISTED!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Item:    *{_escape(owned['item_name'])}*{qty_str}\n"
        f"💰 Price:   *{price:,}¥* each\n"
        f"💸 Fee:     *-{fee:,}¥*\n"
        f"💰 Balance: *{player['yen'] - fee:,}¥*\n\n"
        f"💡 Use `/unlist [number]` to remove.\n"
        f"💡 Use `/markethistory` to see your listings.",
        parse_mode='Markdown'
    )


# ── /unlist — remove your listing ─────────────────────────────────────────
@dm_only
async def unlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "📖 Usage: `/unlist [number]`\n\nUse /markethistory to see your listings.",
            parse_mode='Markdown'
        )
        return
    try:
        listing_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid ID. Use a number.")
        return

    listing = get_listing_by_index(listing_id)
    if not listing:
        await update.message.reply_text("❌ Listing not found.")
        return
    if listing['seller_id'] != user_id:
        await update.message.reply_text("❌ That's not your listing!")
        return
    if listing['status'] != 'active':
        await update.message.reply_text("❌ This listing is no longer active.")
        return

    col("market_listings").update_one(
        {"_id": listing["_id"]},
        {"$set": {"status": "cancelled"}}
    )
    add_item(user_id, listing['item_name'], listing.get('item_type', 'item'))
    await update.message.reply_text(
        f"✅ *Listing Removed*\n\n"
        f"📦 *{_escape(listing['item_name'])}* returned to inventory.",
        parse_mode='Markdown'
    )


# ── /markethistory ─────────────────────────────────────────────────────────
@dm_only
async def markethistory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    history = list(
        col("market_listings").find({"seller_id": user_id})
        .sort("listed_at", -1).limit(10)
    )
    if not history:
        await update.message.reply_text(
            "📊 *MARKET HISTORY*\n\n"
            "_You haven't listed any items yet._\n\n"
            "Use `/list [item] [price]` to start selling!",
            parse_mode='Markdown'
        )
        return

    lines  = ["📊 *YOUR MARKET HISTORY*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    icons  = {"active": "🟢", "sold": "✅", "cancelled": "❌"}
    for h in history:
        icon = icons.get(h.get('status', ''), "❓")
        lines.append(
            f"{icon} *{_escape(h['item_name'])}*  —  {h['price']:,}¥"
            f"  _({h.get('status','?')})_"
        )
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


# ── /buy market [item name] [amount] ──────────────────────────────────────
async def market_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    args = context.args or []
    if args and args[0].lower() == 'market':
        args = args[1:]

    if not args:
        await update.message.reply_text(
            "🏪 *BUY FROM MARKET*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📖 Usage: `/buy market [item name] [amount]`\n\n"
            "📌 Examples:\n"
            "  `/buy market Demon Blood 3`\n"
            "  `/buy market Wolf Fang 1`\n"
            "  `/buy market Boss Shard 5`\n\n"
            "🔍 Use /market to browse all listings.",
            parse_mode='Markdown'
        )
        return

    try:
        amount    = int(args[-1])
        item_name = ' '.join(args[:-1]).strip()
    except ValueError:
        amount    = 1
        item_name = ' '.join(args).strip()

    if not item_name:
        await update.message.reply_text(
            "❌ Specify an item name.\nExample: `/buy market Demon Blood 2`",
            parse_mode='Markdown'
        )
        return

    amount = max(1, min(amount, 999))

    def _find_listings(pattern, exact=True):
        regex = f"^{re.escape(pattern)}$" if exact else re.escape(pattern)
        return list(
            col("market_listings").find({
                "status":    "active",
                "item_name": {"$regex": regex, "$options": "i"}
            }).sort("price", 1)
        )

    listings = _find_listings(item_name, exact=True)
    if not listings:
        listings = _find_listings(item_name, exact=False)

    if not listings:
        await update.message.reply_text(
            f"❌ *No listings found for:* `{_escape(item_name)}`\n\n"
            f"Use /market to browse all listings.",
            parse_mode='Markdown'
        )
        return

    bought      = 0
    total_spent = 0
    current_yen = player['yen']
    bought_name = listings[0]['item_name']

    for listing in listings:
        if bought >= amount:
            break
        if listing.get('seller_id') == user_id:
            continue
        if current_yen < listing['price']:
            break

        result = col("market_listings").update_one(
            {"_id": listing["_id"], "status": "active"},
            {"$set": {"status": "sold"}}
        )
        if result.modified_count == 0:
            continue

        current_yen -= listing['price']
        total_spent += listing['price']
        bought      += 1
        bought_name  = listing['item_name']

        if listing.get('seller_id', 0) != 0:
            seller = get_player(listing['seller_id'])
            if seller:
                update_player(listing['seller_id'], yen=seller['yen'] + listing['price'])
                try:
                    await context.bot.send_message(
                        chat_id=listing['seller_id'],
                        text=(
                            f"💰 *ITEM SOLD!*\n"
                            f"━━━━━━━━━━━━━━━━━━━━━\n"
                            f"📦 *{_escape(listing['item_name'])}* → *+{listing['price']:,}¥*"
                        ),
                        parse_mode='Markdown'
                    )
                except Exception:
                    pass

        add_item(user_id, listing['item_name'], listing.get('item_type', 'material'))

    if bought == 0:
        cheapest = listings[0]['price']
        if current_yen < cheapest:
            await update.message.reply_text(
                f"❌ *Not enough Yen!*\n\n"
                f"💰 Cheapest *{_escape(bought_name)}*: *{cheapest:,}¥*\n"
                f"👛 Your balance: *{current_yen:,}¥*",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"❌ All listings for *{_escape(item_name)}* are your own or sold out.",
                parse_mode='Markdown'
            )
        return

    update_player(user_id, yen=current_yen)

    await update.message.reply_text(
        f"✅ *PURCHASED!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 *{_escape(bought_name)}* × {bought}\n"
        f"💸 Spent:   *{total_spent:,}¥*\n"
        f"💰 Balance: *{current_yen:,}¥*\n\n"
        f"_Use /inventory to see your items._",
        parse_mode='Markdown'
    )
