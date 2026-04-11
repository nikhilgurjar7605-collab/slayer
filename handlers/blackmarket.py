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
        d["_id"]        = item["_id"]
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
            "╔═════════════════╗\n"
            "     🌑 <b>𝘿𝙀𝙈𝙊𝙉 𝙎𝙇𝘼𝙔𝙀𝙍</b> 🌑\n"
            "        <b>𝘽𝙇𝘼𝘾𝙆  𝙈𝘼𝙍𝙆𝙀𝙏</b>\n"
            "╚═════════════════╝\n\n"
            "🔒 <b>The market is CLOSED.</b>\n\n"
            "<i>The hooded figure is nowhere to be seen...</i>\n\n"
            "🕙 Open between <b>10pm — 6am UTC</b>\n"
            "🌕 Or when admin opens it manually",
            parse_mode='HTML'
        )
        return

    stock = get_bm_stock()
    if not stock:
        await update.message.reply_text(
            "╔═════════════════╗\n"
            "     🌑 <b>𝘿𝙀𝙈𝙊𝙉 𝙎𝙇𝘼𝙔𝙀𝙍</b> 🌑\n"
            "        <b>𝘽𝙇𝘼𝘾𝙆  𝙈𝘼𝙍𝙆𝙀𝙏</b>\n"
            "╚═════════════════╝\n\n"
            "<i>The hooded figure eyes you carefully...</i>\n\n"
            "📦 <b>No stock tonight.</b> Check back later.\n"
            "<i>Rare items appear randomly each night.</i>\n\n"
            "💡 Admin: <code>/addblackmarket [price] [stock] [item name]</code>",
            parse_mode='HTML'
        )
        return

    bal = f"¥ {player['yen']:,}"

    lines = [
        "╔═════════════════╗",
        "     🌑 <b>𝘿𝙀𝙈𝙊𝙉 𝙎𝙇𝘼𝙔𝙀𝙍</b> 🌑",
        "        <b>𝘽𝙇𝘼𝘾𝙆  𝙈𝘼𝙍𝙆𝙀𝙏</b>",
        "╚═════════════════╝\n",
        f"👛 <b>Balance:</b> {bal}\n",
        f"     🎭 𝙏𝙊𝙉𝙄𝙂𝙃𝙏'𝙎  𝙎𝙏𝙊𝘾𝙆 🎭",
        "━━━━━━━━━━━━━━━━━━━",
    ]

    for item in stock:
        stock_warn = "  ⚠️ <i>Last one!</i>" if item.get('stock') == 1 else ""
        lines.append(
            f"❖ <b>[{item['display_id']}] {item['item_name']}</b>\n"
            f"   ├─ 💰 Cost  : ¥ <b>{item['price']:,}</b>\n"
            f"   └─ 📦 Stock : {item.get('stock', 1)}{stock_warn}\n"
        )

    if lines[-1].endswith("\n"):
        lines[-1] = lines[-1].rstrip("\n")

    lines += [
        "━━━━━━━━━━━━━━━━━━━",
        "<blockquote>🛒 <b>Purchase Command</b>\n"
        "├ Use: <code>/bmbuy [id]</code> — Buy by number\n"
        "└ Use: <code>/bmbuy [item name]</code> — Buy by name</blockquote>",
        "━━━━━━━━━━━━━━━━━━━",
        "<i>Stock refreshes at dawn.</i>",
    ]

    await update.message.reply_text('\n'.join(lines), parse_mode='HTML')


@dm_only
async def bm_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    if not is_black_market_open():
        await update.message.reply_text(
            "🔒 <b>The Black Market is closed!</b>\n\n<i>Come back between 10pm — 6am UTC.</i>",
            parse_mode='HTML'
        )
        return

    # Strip 'blackmarket' prefix if called via /buy blackmarket [item]
    args = list(context.args or [])
    if args and args[0].lower() == 'blackmarket':
        args = args[1:]

    if not args:
        await update.message.reply_text(
            "💡 Usage:\n"
            "  <code>/bmbuy [id]</code> — Buy by number\n"
            "  <code>/bmbuy [item name]</code> — Buy by name\n\n"
            "Use /blackmarket to see available items.",
            parse_mode='HTML'
        )
        return

    stock = get_bm_stock()
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
            f"❌ <b>Item not found or sold out.</b>\n\n"
            f"Use /blackmarket to see current stock.\n"
            f"Buy by number: <code>/bmbuy 1</code> or by name: <code>/bmbuy Boss Shard</code>",
            parse_mode='HTML'
        )
        return

    if player['yen'] < item['price']:
        needed = item['price'] - player['yen']
        await update.message.reply_text(
            f"❌ <b>Not enough Yen!</b>\n\n"
            f"💰 Item price:  <b>{item['price']:,}¥</b>\n"
            f"👛 Your wallet: <b>{player['yen']:,}¥</b>\n"
            f"💸 Need:        <b>{needed:,}¥ more</b>",
            parse_mode='HTML'
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
            "╔═════════════════╗\n"
            "     🌑 <b>𝘿𝙀𝙈𝙊𝙉 𝙎𝙇𝘼𝙔𝙀𝙍</b> 🌑\n"
            "        <b>𝘽𝙇𝘼𝘾𝙆  𝙈𝘼𝙍𝙆𝙀𝙏</b>\n"
            "╚═════════════════╝\n\n"
            f"✅ <b>Purchase Successful!</b>\n\n"
            f"💠 <b>+1 Skill Point</b> added!\n"
            f"💸 Spent:   <b>{item['price']:,}¥</b>\n"
            f"💰 Balance: <b>{player['yen'] - item['price']:,}¥</b>\n"
            f"💠 Your SP: <b>{player.get('skill_points', 0) + 1}</b>\n\n"
            f"<i>Use /skilltree to spend your SP.</i>",
            parse_mode='HTML'
        )
        return

    add_item(user_id, item['item_name'], itype)

    await update.message.reply_text(
        "╔═════════════════╗\n"
        "     🌑 <b>𝘿𝙀𝙈𝙊𝙉 𝙎𝙇𝘼𝙔𝙀𝙍</b> 🌑\n"
        "        <b>𝘽𝙇𝘼𝘾𝙆  𝙈𝘼𝙍𝙆𝙀𝙏</b>\n"
        "╚═════════════════╝\n\n"
        f"✅ <b>Purchase Successful!</b>\n\n"
        f"🎭 <b>{item['item_name']}</b>\n"
        f"💸 Spent:   <b>{item['price']:,}¥</b>\n"
        f"💰 Balance: <b>{player['yen'] - item['price']:,}¥</b>\n\n"
        f"<i>Use /inventory to see your items.</i>",
        parse_mode='HTML'
    )
