"""
Black Market — open 10pm-6am UTC, admin can force open/close.
Buy with: /blackmarket to browse, /bmbuy [id or name] to buy
Or: /buy blackmarket [id or name]
"""
import re
from utils.guards import dm_only
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, add_item, col
from telegram.error import BadRequest, TimedOut


def is_black_market_open():
    forced = col("black_market").find_one({"item_name": "__OPEN__", "status": "active"})
    if forced:
        return True
    hour = datetime.utcnow().hour
    return hour >= 22 or hour < 6


def get_bm_stock():
    items = list(col("black_market").find({
        "status": "active",
        "item_name": {"$ne": "__OPEN__"},
        "stock": {"$gt": 0}
    }))
    result = []
    for i, item in enumerate(items, 1):
        d = {k: v for k, v in item.items() if k != "_id"}
        d["_id"]        = item["_id"]   # keep real _id for atomic updates
        d["display_id"] = i
        result.append(d)
    return result


@dm_only
async def blackmarket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    if not is_black_market_open():
        await update.message.reply_text(
            "🌑 *BLACK MARKET*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔒 *The market is CLOSED.*\n\n"
            "_The hooded figure is nowhere to be seen..._\n\n"
            "🕙 Open between *10pm — 6am UTC*\n"
            "🌕 Or when admin opens it manually",
            parse_mode='Markdown'
        )
        return

    stock = get_bm_stock()
    if not stock:
        await update.message.reply_text(
            "🌑 *BLACK MARKET*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "_The hooded figure eyes you carefully..._\n\n"
            "📦 *No stock tonight.* Check back later.\n"
            "_Rare items appear randomly each night._\n\n"
            "💡 Admin: `/addblackmarket [price] [stock] [item name]`",
            parse_mode='Markdown'
        )
        return

    lines = [
        "🌑 *BLACK MARKET*",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
        "_The hooded figure eyes you carefully..._",
        "",
        "🎭 *Tonight's Stock:*",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]
    for item in stock:
        stock_warn = " ⚠️ _Last one!_" if item.get('stock') == 1 else ""
        lines.append(
            f"🔹 *[{item['display_id']}]* {item['item_name']}\n"
            f"      💰 *{item['price']:,}¥*  •  📦 Stock: {item.get('stock', 1)}{stock_warn}"
        )

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━",
        f"💰 *Your wallet:* {player['yen']:,}¥",
        "",
        "💡 `/bmbuy [id]` — Buy by number",
        "💡 `/bmbuy [item name]` — Buy by name",
        "_Stock refreshes at dawn._",
    ]
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


@dm_only
async def bm_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    if not is_black_market_open():
        await update.message.reply_text(
            "🔒 *The Black Market is closed!*\n\n_Come back between 10pm — 6am UTC._",
            parse_mode='Markdown'
        )
        return

    # Strip 'blackmarket' prefix if called via /buy blackmarket [item]
    args = list(context.args or [])
    if args and args[0].lower() == 'blackmarket':
        args = args[1:]

    if not args:
        await update.message.reply_text(
            "💡 Usage:\n"
            "  `/bmbuy [id]` — Buy by number\n"
            "  `/bmbuy [item name]` — Buy by name\n\n"
            "Use /blackmarket to see available items.",
            parse_mode='Markdown'
        )
        return

    stock     = get_bm_stock()
    if not stock:
        await update.message.reply_text("❌ No stock available right now. Use /blackmarket to check.")
        return

    query_str = ' '.join(args).strip()

    # Find by display_id OR name (exact then partial)
    item = None
    if query_str.isdigit():
        item = next((i for i in stock if i['display_id'] == int(query_str)), None)
    if not item:
        item = next((i for i in stock if i['item_name'].lower() == query_str.lower()), None)
    if not item:
        item = next((i for i in stock if query_str.lower() in i['item_name'].lower()), None)

    if not item or item.get('stock', 0) <= 0:
        await update.message.reply_text(
            f"❌ *Item not found or sold out.*\n\n"
            f"Use /blackmarket to see current stock.\n"
            f"Buy by number: `/bmbuy 1` or by name: `/bmbuy Boss Shard`",
            parse_mode='Markdown'
        )
        return

    if player['yen'] < item['price']:
        needed = item['price'] - player['yen']
        await update.message.reply_text(
            f"❌ *Not enough Yen!*\n\n"
            f"💰 Item price:  *{item['price']:,}¥*\n"
            f"👛 Your wallet: *{player['yen']:,}¥*\n"
            f"💸 Need:        *{needed:,}¥ more*",
            parse_mode='Markdown'
        )
        return

    # Atomically decrement stock — prevent race conditions
    new_stock = item['stock'] - 1
    if new_stock <= 0:
        result = col("black_market").update_one(
            {"_id": item["_id"], "stock": {"$gt": 0}},
            {"$set": {"stock": 0, "status": "sold"}}
        )
    else:
        result = col("black_market").update_one(
            {"_id": item["_id"], "stock": {"$gt": 0}},
            {"$inc": {"stock": -1}}
        )

    if result.modified_count == 0:
        await update.message.reply_text("❌ That item was just sold out! Use /blackmarket to check stock.")
        return

    update_player(user_id, yen=player['yen'] - item['price'])
    itype = item.get('item_type', 'material')

    # Special handling for SP items from World Bank
    if itype == 'sp':
        update_player(user_id, skill_points=player.get('skill_points', 0) + 1)
        from handlers.worldbank import _wb_log
        _wb_log(user_id, "bm_purchase", 1,
                f"bought 1 SP from blackmarket for {item['price']:,}¥")
        await update.message.reply_text(
            f"✅ *PURCHASED!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💠 *+1 Skill Point* added!\n"
            f"💸 Spent:    *{item['price']:,}¥*\n"
            f"💰 Balance:  *{player['yen'] - item['price']:,}¥*\n"
            f"💠 Your SP:  *{player.get('skill_points', 0) + 1}*\n\n"
            f"_Use /skilltree to spend your SP._",
            parse_mode='Markdown'
        )
        return

    add_item(user_id, item['item_name'], itype)

    await update.message.reply_text(
        f"✅ *PURCHASED!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎭 *{item['item_name']}*\n"
        f"💸 Spent:    *{item['price']:,}¥*\n"
        f"💰 Balance:  *{player['yen'] - item['price']:,}¥*\n\n"
        f"_Use /inventory to see your items._",
        parse_mode='Markdown'
    )