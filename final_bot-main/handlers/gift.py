from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, get_inventory, remove_item, add_item, get_gift_count_today
from utils.database import col

MAX_GIFTS_PER_DAY = 10

async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    args = context.args

    # Method 1: Reply to a message
    target = None
    item_name = None

    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        if not replied_user.is_bot:
            doc = col("players").find_one({"user_id": replied_user.id})
            target = doc
            item_name = ' '.join(args) if args else None

    # Method 2: /gift @username item
    if not target and len(args) >= 2:
        target_username = args[0].lstrip('@')
        item_name = ' '.join(args[1:])
        target = col("players").find_one({"username": {"$regex": f"^{target_username}$", "$options": "i"}})

    if not item_name or not target:
        await update.message.reply_text(
            "🎁 *GIFT SYSTEM*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📖 *Method 1 — Reply:*\n"
            "Reply to someone's message → `/gift [item name]`\n\n"
            "📖 *Method 2 — Username:*\n"
            "`/gift @username [item name]`\n\n"
            "📋 *Rules:*\n"
            "  • Max 10 gifts per day\n"
            "  • Cannot gift equipped gear\n"
            "  • Both players are notified",
            parse_mode='Markdown'
        )
        return

    if not target:
        await update.message.reply_text(
            f"❌ *Player not found.*\n\n"
            f"_Make sure they have created a character with /start._",
            parse_mode='Markdown'
        )
        return

    if target['user_id'] == user_id:
        await update.message.reply_text("❌ You can't gift yourself!")
        return

    gift_count = get_gift_count_today(user_id)
    if gift_count >= MAX_GIFTS_PER_DAY:
        await update.message.reply_text(
            f"❌ *Daily gift limit reached!*\n\n"
            f"📦 Gifts sent today: *{gift_count}/{MAX_GIFTS_PER_DAY}*\n"
            f"⌚ _Come back tomorrow to send more gifts!_",
            parse_mode='Markdown'
        )
        return

    inventory = get_inventory(user_id)
    owned = next((i for i in inventory if i['item_name'].lower() == item_name.lower()), None)
    if not owned:
        await update.message.reply_text(
            f"❌ *Not in inventory:* `{item_name}`\n\n"
            f"Use /inventory to see your items.",
            parse_mode='Markdown'
        )
        return

    equipped = [player.get('equipped_sword', ''), player.get('equipped_armor', '')]
    if owned['item_name'] in equipped:
        await update.message.reply_text(
            f"❌ *Can't gift equipped items!*\n\n"
            f"Unequip *{owned['item_name']}* first.",
            parse_mode='Markdown'
        )
        return

    remove_item(user_id, owned['item_name'])
    add_item(target['user_id'], owned['item_name'], owned['item_type'])

    col("gift_log").insert_one({"from_id": user_id, "to_id": target["user_id"], "item_name": item_name})

    sender_name = f"@{player['username']}" if player.get('username') else player['name']

    await update.message.reply_text(
        f"🎁 *GIFT SENT!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Item:       *{owned['item_name']}*\n"
        f"👤 Sent to:    *@{target_username}*\n"
        f"📊 Gifts today: *{gift_count + 1}/{MAX_GIFTS_PER_DAY}*",
        parse_mode='Markdown'
    )

    try:
        await context.bot.send_message(
            chat_id=target['user_id'],
            text=(
                f"🎁 *GIFT RECEIVED!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 Item:     *{owned['item_name']}*\n"
                f"🤝 From:     *{sender_name}*\n\n"
                f"_Check /inventory to see it!_"
            ),
            parse_mode='Markdown'
        )
    except Exception:
        pass
