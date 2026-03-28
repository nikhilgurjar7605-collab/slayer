from telegram import Update
from telegram.ext import ContextTypes
from datetime import datetime
from utils.database import (
    get_player, get_inventory, remove_item, add_item, 
    get_gift_count_today, col, canonical_item_name
)

MAX_GIFTS_PER_DAY = 10


async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    args = context.args or []
    
    # No args and no reply = show help
    if not args and not update.message.reply_to_message:
        await _show_help(update)
        return

    target = None
    item_name_raw = None
    target_display = None

    # ── Method 1: Reply ──────────────────────────────────────────────
    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        
        if replied_user.is_bot:
            await update.message.reply_text("❌ Can't gift to bots!")
            return
        
        target = col("players").find_one({"user_id": replied_user.id})
        if not target:
            await update.message.reply_text(
                "❌ *Player not found.*\n"
                "_They need to create a character with /start first._",
                parse_mode='Markdown'
            )
            return
        
        # Get item name from remaining args
        item_name_raw = ' '.join(args).strip() if args else None
        target_display = f"@{replied_user.username}" if replied_user.username else replied_user.first_name

    # ── Method 2: /gift @username item_name ──────────────────────────
    elif len(args) >= 2:
        target_username = args[0].lstrip('@')
        item_name_raw = ' '.join(args[1:]).strip()
        target = col("players").find_one({
            "username": {"$regex": f"^{target_username}$", "$options": "i"}
        })
        target_display = f"@{target_username}"

    # ── Validation ───────────────────────────────────────────────────
    if not item_name_raw:
        await _show_help(update)
        return

    if not target:
        await update.message.reply_text(
            "❌ *Player not found.*\n"
            "_Make sure they have created a character with /start._",
            parse_mode='Markdown'
        )
        return

    if target['user_id'] == user_id:
        await update.message.reply_text("❌ You can't gift yourself!")
        return

    # Check daily limit
    gift_count = get_gift_count_today(user_id)
    if gift_count >= MAX_GIFTS_PER_DAY:
        await update.message.reply_text(
            f"❌ *Daily gift limit reached!*\n\n"
            f"📦 Gifts sent today: *{gift_count}/{MAX_GIFTS_PER_DAY}*\n"
            f"⌚ _Come back tomorrow!_",
            parse_mode='Markdown'
        )
        return

    # ── Find Item (using canonical name) ─────────────────────────────
    # This is the KEY fix - normalize the name same way DB does
    canonical_name = canonical_item_name(item_name_raw)
    
    if not canonical_name:
        await update.message.reply_text("❌ Invalid item name.")
        return

    inventory = get_inventory(user_id)
    owned = None
    for item in inventory:
        if item['item_name'].lower() == canonical_name.lower():
            owned = item
            break

    if not owned:
        # Show what they actually have for clarity
        available = [f"`{i['item_name']}`" for i in inventory[:5]]
        avail_str = ', '.join(available) + ('...' if len(inventory) > 5 else '')
        await update.message.reply_text(
            f"❌ *Item not found:* `{item_name_raw}`\n\n"
            f"📦 Your items: {avail_str}\n"
            f"_Use /inventory to see all items._",
            parse_mode='Markdown'
        )
        return

    # ── Check if equipped ────────────────────────────────────────────
    equipped_items = [
        player.get('equipped_sword'),
        player.get('equipped_armor')
    ]
    equipped_items = [e for e in equipped_items if e]  # Remove None values
    
    if owned['item_name'] in equipped_items:
        await update.message.reply_text(
            f"❌ *Can't gift equipped items!*\n\n"
            f"Unequip *{owned['item_name']}* first.",
            parse_mode='Markdown'
        )
        return

    # ── Perform the transfer ─────────────────────────────────────────
    actual_name = owned['item_name']
    actual_type = owned['item_type']
    qty = owned.get('quantity', 1)

    # Remove from sender
    remove_item(user_id, actual_name, qty)
    
    # Add to receiver (use canonical name)
    add_item(target['user_id'], actual_name, actual_type, qty)

    # Log the gift (include gifted_at for daily limit to work!)
    col("gift_log").insert_one({
        "from_id": user_id,
        "to_id": target["user_id"],
        "item_name": actual_name,
        "quantity": qty,
        "gifted_at": datetime.now()  # CRITICAL: without this, daily limit breaks
    })

    # ── Confirm to sender ────────────────────────────────────────────
    sender_name = f"@{player['username']}" if player.get('username') else player['name']
    qty_str = f" x{qty}" if qty > 1 else ""

    await update.message.reply_text(
        f"🎁 *GIFT SENT!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Item:        *{actual_name}{qty_str}*\n"
        f"👤 Sent to:     *{target_display}*\n"
        f"📊 Gifts today: *{gift_count + 1}/{MAX_GIFTS_PER_DAY}*",
        parse_mode='Markdown'
    )

    # ── Notify receiver ──────────────────────────────────────────────
    try:
        await context.bot.send_message(
            chat_id=target['user_id'],
            text=(
                f"🎁 *GIFT RECEIVED!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"📦 Item:     *{actual_name}{qty_str}*\n"
                f"🤝 From:     *{sender_name}*\n\n"
                f"_Check /inventory to see it!_"
            ),
            parse_mode='Markdown'
        )
    except Exception:
        pass  # User might have blocked the bot


async def _show_help(update: Update):
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
