from telegram.error import BadRequest, TimedOut
"""
/offer — Admin creates time-limited shop offers
/offers — Players view active offers and buy
"""
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, add_item, col
from utils.guards import dm_only

async def _safe_edit(query, text, **kwargs):
    """Edit a message safely, falling back to reply on failure."""
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        try:
            await query.message.reply_text(text, **kwargs)
        except Exception:
            pass


def get_active_offers():
    now = datetime.now()
    offers = list(col("offers").find({
        "status": "active",
        "expires_at": {"$gt": now}
    }))
    for o in offers:
        o.pop("_id", None)
    return offers


@dm_only
async def offers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    active = get_active_offers()

    if not active:
        await update.message.reply_text(
            "╔══════════════════════╗\n"
            "      🎪 𝙇𝙄𝙈𝙄𝙏𝙀𝘿 𝙊𝙁𝙁𝙀𝙍𝙎\n"
            "╚══════════════════════╝\n\n"
            "🚫 *No active offers right now.*\n\n"
            "_Check back later — admins post special deals!_",
            parse_mode='Markdown'
        )
        return

    lines = [
        "╔══════════════════════╗",
        "      🎪 𝙇𝙄𝙈𝙄𝙏𝙀𝘿 𝙊𝙁𝙁𝙀𝙍𝙎",
        "╚══════════════════════╝\n",
        f"💰 Your balance: *{player['yen']:,}¥*\n",
        "━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    buttons = []
    now = datetime.now()
    for i, offer in enumerate(active, 1):
        remaining = offer['expires_at'] - now
        hrs  = int(remaining.total_seconds() // 3600)
        mins = int((remaining.total_seconds() % 3600) // 60)
        time_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"

        stock_txt = f"  📦 Stock: {offer['stock']}" if offer.get('stock') else ""
        lines.append(
            f"🎪 *[{i}]* {offer.get('emoji','🎁')} *{offer['item_name']}*\n"
            f"   💸 Price: *{offer['price']:,}¥*  _(was {offer.get('original_price', offer['price']):,}¥)_\n"
            f"   ⏳ Expires: *{time_str}*{stock_txt}"
        )
        lines.append("")
        buttons.append([InlineKeyboardButton(
            f"🛒 Buy [{i}] {offer['item_name']} — {offer['price']:,}¥",
            callback_data=f"offer_buy_{offer['id']}"
        )])

    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append("_Tap a button to buy ↓_")

    await update.message.reply_text(
        '\n'.join(lines),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def offer_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query    = update.callback_query
    await query.answer()
    user_id  = query.from_user.id
    offer_id = query.data.replace('offer_buy_', '')

    player = get_player(user_id)
    if not player:
        await query.answer("❌ No character.", show_alert=True)
        return

    offer = col("offers").find_one({"id": offer_id, "status": "active"})
    if not offer:
        await _safe_edit(query, "❌ This offer has expired or sold out.")
        return

    if datetime.now() > offer['expires_at']:
        col("offers").update_one({"id": offer_id}, {"$set": {"status": "expired"}})
        await _safe_edit(query, "❌ This offer has expired!")
        return

    if player['yen'] < offer['price']:
        await query.answer(
            f"❌ Need {offer['price']:,}¥ but you have {player['yen']:,}¥",
            show_alert=True
        )
        return

    # Check stock
    if offer.get('stock', 0) == 0 and 'stock' in offer:
        await query.answer("❌ Sold out!", show_alert=True)
        return

    # Purchase
    update_player(user_id, yen=player['yen'] - offer['price'])
    add_item(user_id, offer['item_name'], offer.get('item_type', 'item'))

    if 'stock' in offer and offer['stock'] > 0:
        new_stock = offer['stock'] - 1
        status = 'sold_out' if new_stock == 0 else 'active'
        col("offers").update_one({"id": offer_id}, {"$set": {"stock": new_stock, "status": status}})

    await _safe_edit(query, 
        f"✅ *PURCHASED!*\n\n"
        f"🎪 *{offer['item_name']}*\n"
        f"💸 Spent: *{offer['price']:,}¥*\n"
        f"💰 Balance: *{player['yen'] - offer['price']:,}¥*",
        parse_mode='Markdown'
    )


async def addoffer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: /addoffer [hours] [price] [original_price] [stock] [emoji] [item name]"""
    from handlers.admin import has_admin_access
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if len(context.args or []) < 5:
        await update.message.reply_text(
            "📖 Usage:\n"
            "`/addoffer [hours] [price] [orig_price] [stock] [emoji] [item name]`\n\n"
            "Example:\n"
            "`/addoffer 24 500 1200 10 🍶 Full Recovery Gourd`",
            parse_mode='Markdown'
        )
        return

    try:
        hours          = int(context.args[0])
        price          = int(context.args[1])
        original_price = int(context.args[2])
        stock          = int(context.args[3])
        emoji          = context.args[4]
        item_name      = ' '.join(context.args[5:])
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Invalid format. Check usage.")
        return

    import time
    offer_id = str(int(time.time()))
    expires  = datetime.now() + timedelta(hours=hours)

    col("offers").insert_one({
        "id":             offer_id,
        "item_name":      item_name,
        "item_type":      "item",
        "price":          price,
        "original_price": original_price,
        "stock":          stock,
        "emoji":          emoji,
        "expires_at":     expires,
        "status":         "active",
        "created_at":     datetime.now()
    })

    await update.message.reply_text(
        f"✅ *Offer created!*\n\n"
        f"{emoji} *{item_name}*\n"
        f"💸 Price: *{price:,}¥* _(was {original_price:,}¥)_\n"
        f"📦 Stock: *{stock}*\n"
        f"⏳ Expires in: *{hours}h*",
        parse_mode='Markdown'
    )
