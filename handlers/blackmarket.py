import re
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from utils.guards import dm_only, admin_only
from utils.database import get_player, update_player, col, add_item


def is_black_market_open():
    forced = col("black_market").find_one({"item_name": "__OPEN__", "status": "active"})
    if forced:
        return True
    hour = datetime.utcnow().hour
    return hour >= 22 or hour < 6


def get_bm_stock():
    items = list(col("black_market").find({
        "status": "active", "item_name": {"$ne": "__OPEN__"}, "stock": {"$gt": 0}
    }))
    return [{**{k: v for k, v in item.items() if k != "_id"}, "_id": item["_id"], "display_id": i+1}
            for i, item in enumerate(items)]


@dm_only
async def blackmarket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        return await update.message.reply_text("❌ No character found.")

    if not is_black_market_open():
        return await update.message.reply_text(
            "🌑 <b>BLACK MARKET CLOSED</b>\n\n"
            "Open 10pm–6am UTC or by admin.\n", parse_mode='HTML')

    stock = get_bm_stock()
    if not stock:
        return await update.message.reply_text("📦 No stock tonight.", parse_mode='HTML')

    lines = [
        "╔═════════════════╗",
        " 🌑 <b>BLACK MARKET</b>",
        "╚═════════════════╝\n",
        f"👛 Balance: ¥{player['yen']:,}\n",
        "🎭 TONIGHT'S STOCK",
        "━━━━━━━━━━━━━━━━━━━",
    ]

    for item in stock:
        warn = " ⚠️ Last one!" if item.get('stock') == 1 else ""
        lines.append(f"❖ <b>[{item['display_id']}] {item['item_name']}</b>\n"
                     f" ├ 💰 ¥{item['price']:,}\n"
                     f" └ 📦 {item.get('stock',1)}{warn}")

    lines += [
        "━━━━━━━━━━━━━━━━━━━",
        "🛒 <code>/bmbuy [id or name]</code>",
        "🗑️ <code>/bmremove [id or name]</code> (Admin)",
        "━━━━━━━━━━━━━━━━━━━",
    ]

    await update.message.reply_text('\n'.join(lines), parse_mode='HTML')


@dm_only
async def bm_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player or not is_black_market_open():
        return await update.message.reply_text("❌ Market closed or no player.")

    args = context.args or []
    if args and args[0].lower() == 'blackmarket':
        args = args[1:]
    if not args:
        return await update.message.reply_text("Usage: /bmbuy [id/name]")

    stock = get_bm_stock()
    query = ' '.join(args).strip().lower()

    item = next((i for i in stock if str(i['display_id']) == query), None) or \
           next((i for i in stock if i['item_name'].lower() == query), None) or \
           next((i for i in stock if query in i['item_name'].lower()), None)

    if not item or item.get('stock', 0) <= 0:
        return await update.message.reply_text("❌ Item not found or sold out.")

    if player['yen'] < item['price']:
        return await update.message.reply_text(f"❌ Need ¥{item['price']:,} (You have ¥{player['yen']:,})")

    # Atomic stock decrease
    if item['stock'] <= 1:
        col("black_market").update_one({"_id": item["_id"]}, {"$set": {"stock": 0, "status": "sold"}})
    else:
        col("black_market").update_one({"_id": item["_id"]}, {"$inc": {"stock": -1}})

    update_player(user_id, yen=player['yen'] - item['price'])

    if item.get('item_type') == 'sp':
        update_player(user_id, skill_points=player.get('skill_points', 0) + 1)
        return await update.message.reply_text("✅ +1 Skill Point purchased!")

    add_item(user_id, item['item_name'], item.get('item_type', 'material'))
    await update.message.reply_text(f"✅ Bought **{item['item_name']}** for ¥{item['price']:,}", parse_mode='HTML')


@dm_only
@admin_only
async def bm_remove(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        return await update.message.reply_text("Usage: /bmremove [id or name]")

    query = ' '.join(args).strip().lower()
    stock = get_bm_stock()

    item = next((i for i in stock if str(i['display_id']) == query), None) or \
           next((i for i in stock if i['item_name'].lower() == query), None) or \
           next((i for i in stock if query in i['item_name'].lower()), None)

    if not item:
        return await update.message.reply_text("❌ Item not found.")

    col("black_market").update_one({"_id": item["_id"]}, {"$set": {"status": "removed"}})

    await update.message.reply_text(f"🗑️ Removed **{item['item_name']}** from Black Market.", parse_mode='HTML')
