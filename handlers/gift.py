from telegram import Update
from telegram.ext import ContextTypes
from datetime import datetime
from utils.database import (
    get_player, get_inventory, remove_item, add_item, 
    get_gift_count_today, col, canonical_item_name
)

MAX_GIFTS_PER_DAY = 10


async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        player = get_player(user_id)
        
        if not player:
            await update.message.reply_text("❌ No character found. Use /start to create one.")
            return

        args = context.args or []
        raw_text = update.message.text
        
        # Debug log
        print(f"[GIFT] Raw command: {raw_text}")
        print(f"[GIFT] Args: {args}")
        print(f"[GIFT] Has reply: {update.message.reply_to_message is not None}")

        if not args and not update.message.reply_to_message:
            await _show_help(update)
            return

        target = None
        item_name_raw = None
        target_display = None

        # Method 1: Reply
        if update.message.reply_to_message:
            replied_user = update.message.reply_to_message.from_user
            print(f"[GIFT] Replied to user: {replied_user.id} (@{replied_user.username})")
            
            if replied_user.is_bot:
                await update.message.reply_text("❌ Can't gift to bots!")
                return
            
            target = col("players").find_one({"user_id": replied_user.id})
            print(f"[GIFT] Target found in DB: {target is not None}")
            
            if not target:
                await update.message.reply_text(
                    "❌ *Player not found.*\n_They need /start first._",
                    parse_mode='Markdown'
                )
                return
            
            item_name_raw = ' '.join(args).strip() if args else None
            target_display = f"@{replied_user.username}" if replied_user.username else replied_user.first_name

        # Method 2: @username
        elif len(args) >= 2:
            target_username = args[0].lstrip('@')
            item_name_raw = ' '.join(args[1:]).strip()
            print(f"[GIFT] Looking for username: {target_username}")
            print(f"[GIFT] Item name raw: {item_name_raw}")
            
            target = col("players").find_one({
                "username": {"$regex": f"^{target_username}$", "$options": "i"}
            })
            print(f"[GIFT] Target found: {target is not None}")
            target_display = f"@{target_username}"

        # Validation
        if not item_name_raw:
            await _show_help(update)
            return

        if not target:
            await update.message.reply_text("❌ *Player not found.*", parse_mode='Markdown')
            return

        if target['user_id'] == user_id:
            await update.message.reply_text("❌ You can't gift yourself!")
            return

        # Gift limit
        gift_count = get_gift_count_today(user_id)
        print(f"[GIFT] Gift count today: {gift_count}")
        
        if gift_count >= MAX_GIFTS_PER_DAY:
            await update.message.reply_text(
                f"❌ *Daily limit reached!* ({gift_count}/{MAX_GIFTS_PER_DAY})",
                parse_mode='Markdown'
            )
            return

        # === CRITICAL PART: Item matching ===
        canonical_name = canonical_item_name(item_name_raw)
        print(f"[GIFT] Raw input: '{item_name_raw}'")
        print(f"[GIFT] Canonical name: '{canonical_name}'")

        inventory = get_inventory(user_id)
        print(f"[GIFT] Inventory count: {len(inventory)}")
        print(f"[GIFT] Inventory items: {[i['item_name'] for i in inventory]}")

        owned = None
        for item in inventory:
            print(f"[GIFT] Comparing: '{item['item_name'].lower()}' == '{canonical_name.lower()}' -> {item['item_name'].lower() == canonical_name.lower()}")
            if item['item_name'].lower() == canonical_name.lower():
                owned = item
                break

        if not owned:
            available = [f"`{i['item_name']}`" for i in inventory[:5]]
            avail_str = ', '.join(available) + ('...' if len(inventory) > 5 else '')
            await update.message.reply_text(
                f"❌ *Item not found:* `{item_name_raw}`\n"
                f"(looked for: `{canonical_name}`)\n\n"
                f"📦 Your items: {avail_str if avail_str else '*none*'}",
                parse_mode='Markdown'
            )
            return

        # Equipped check
        equipped = [player.get('equipped_sword'), player.get('equipped_armor')]
        equipped = [e for e in equipped if e]
        print(f"[GIFT] Equipped items: {equipped}")
        
        if owned['item_name'] in equipped:
            await update.message.reply_text(
                f"❌ *Can't gift equipped items!*\nUnequip *{owned['item_name']}* first.",
                parse_mode='Markdown'
            )
            return

        # Transfer
        actual_name = owned['item_name']
        actual_type = owned['item_type']
        qty = owned.get('quantity', 1)

        print(f"[GIFT] Transferring: {actual_name} x{qty}")

        remove_item(user_id, actual_name, qty)
        add_item(target['user_id'], actual_name, actual_type, qty)

        col("gift_log").insert_one({
            "from_id": user_id,
            "to_id": target["user_id"],
            "item_name": actual_name,
            "quantity": qty,
            "gifted_at": datetime.now()
        })

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
        except Exception as e:
            print(f"[GIFT] Could not notify receiver: {e}")

    except Exception as e:
        import traceback
        print(f"[GIFT ERROR] {traceback.format_exc()}")
        await update.message.reply_text(f"❌ Error: `{str(e)}`", parse_mode='Markdown')


async def _show_help(update: Update):
    await update.message.reply_text(
        "🎁 *GIFT SYSTEM*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📖 *Method 1 — Reply:*\n"
        "Reply to someone → `/gift [item name]`\n\n"
        "📖 *Method 2 — Username:*\n"
        "`/gift @username [item name]`\n\n"
        "📋 *Rules:*\n"
        "  • Max 10 gifts per day\n"
        "  • Cannot gift equipped gear",
        parse_mode='Markdown'
    )
