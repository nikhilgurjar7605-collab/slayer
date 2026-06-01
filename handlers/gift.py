import logging
from telegram import Update
from telegram.ext import ContextTypes
from datetime import datetime
from utils.database import (
    get_player, get_inventory, remove_item, add_item, 
    get_gift_count_today, col, canonical_item_name
)

log = logging.getLogger(__name__)
MAX_GIFTS_PER_DAY = 10


async def gift(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = update.effective_user.id
        player = get_player(user_id)
        
        if not player:
            await update.message.reply_text("❌ No character found. Use /start to create one.")
            return

        args = context.args or []
        
        log.info(f"[GIFT-CMD] User {user_id} ran: {update.message.text}")

        if not args and not update.message.reply_to_message:
            await _show_help(update)
            return

        target = None
        item_name_raw = None
        qty_requested = None
        target_display = None

        # ── Method 1: Reply to a message ─────────────────────────────────
        if update.message.reply_to_message:
            replied_user = update.message.reply_to_message.from_user
            
            if replied_user.is_bot:
                await update.message.reply_text("❌ Can't gift to bots!")
                return
            
            target = col("players").find_one({"user_id": replied_user.id})
            if not target:
                await update.message.reply_text("❌ Player not found. They need /start first.")
                return
            
            target_display = f"@{replied_user.username}" if replied_user.username else replied_user.first_name

            # Args after reply: /gift itemname  OR  /gift itemname qty
            if args:
                # Check if last arg is a number → quantity
                if args[-1].isdigit():
                    qty_requested = int(args[-1])
                    item_name_raw = ' '.join(args[:-1]).strip()
                else:
                    item_name_raw = ' '.join(args).strip()

        # ── Method 2: @username [item] [qty] ─────────────────────────────
        elif args and args[0].startswith('@'):
            target_username = args[0].lstrip('@')
            target = col("players").find_one({"username": {"$regex": f"^{target_username}$", "$options": "i"}})
            target_display = f"@{target_username}"

            rest = args[1:]
            if rest:
                if rest[-1].isdigit():
                    qty_requested = int(rest[-1])
                    item_name_raw = ' '.join(rest[:-1]).strip()
                else:
                    item_name_raw = ' '.join(rest).strip()

        # ── Method 3: /gift itemname [qty]  (no @ and no reply — legacy) ─
        elif args:
            if args[-1].isdigit() and len(args) >= 2:
                qty_requested = int(args[-1])
                item_name_raw = ' '.join(args[:-1]).strip()
            else:
                item_name_raw = ' '.join(args).strip()

        if not item_name_raw:
            await _show_help(update)
            return

        if not target:
            await update.message.reply_text("❌ Player not found.")
            return

        if target['user_id'] == user_id:
            await update.message.reply_text("❌ You can't gift yourself!")
            return

        # ── Daily limit ───────────────────────────────────────────────────
        gift_count = get_gift_count_today(user_id)
        if gift_count >= MAX_GIFTS_PER_DAY:
            await update.message.reply_text(f"❌ Daily limit reached! ({gift_count}/{MAX_GIFTS_PER_DAY})")
            return

        # ── Find item in inventory ────────────────────────────────────────
        canonical_name = canonical_item_name(item_name_raw)
        log.info(f"[GIFT-CMD] Looking for: '{canonical_name}'")

        inventory = get_inventory(user_id)
        log.info(f"[GIFT-CMD] User inventory: {[i['item_name'] for i in inventory]}")

        owned = None
        for item in inventory:
            if item['item_name'].lower() == canonical_name.lower():
                owned = item
                break

        if not owned:
            available = [f"`{i['item_name']}`" for i in inventory[:5]]
            avail_str = ', '.join(available) + ('...' if len(inventory) > 5 else '')
            await update.message.reply_text(
                f"❌ *Item not found:* `{item_name_raw}`\n"
                f"(Looked for: `{canonical_name}`)\n\n"
                f"📦 Your items: {avail_str if avail_str else '*none*'}",
                parse_mode='Markdown'
            )
            return

        # ── Equipped check ────────────────────────────────────────────────
        equipped = [player.get('equipped_sword'), player.get('equipped_armor')]
        equipped = [e for e in equipped if e]
        
        if owned['item_name'] in equipped:
            await update.message.reply_text(
                f"❌ Can't gift equipped items! Unequip *{owned['item_name']}* first.",
                parse_mode='Markdown'
            )
            return

        # ── Quantity resolution ───────────────────────────────────────────
        actual_name = owned['item_name']
        actual_type = owned['item_type']
        stack_qty   = owned.get('quantity', 1)

        if qty_requested is None:
            qty_requested = stack_qty           # default: send all
        elif qty_requested < 1:
            await update.message.reply_text("❌ Quantity must be at least 1.")
            return
        elif qty_requested > stack_qty:
            await update.message.reply_text(
                f"❌ You only have *{stack_qty}x {actual_name}* — can't send {qty_requested}.",
                parse_mode='Markdown'
            )
            return

        # ── Transfer ──────────────────────────────────────────────────────
        remove_item(user_id, actual_name, qty_requested)
        add_item(target['user_id'], actual_name, actual_type, qty_requested)

        col("gift_log").insert_one({
            "from_id": user_id,
            "to_id": target["user_id"],
            "item_name": actual_name,
            "quantity": qty_requested,
            "gifted_at": datetime.now()
        })

        sender_name = f"@{player['username']}" if player.get('username') else player['name']
        qty_str = f" x{qty_requested}" if qty_requested > 1 else ""

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
        except Exception:
            pass

    except Exception as e:
        log.error(f"[GIFT-ERROR] {e}", exc_info=True)
        try:
            await update.message.reply_text(f"❌ Error: `{str(e)}`", parse_mode='Markdown')
        except Exception:
            pass


async def _show_help(update: Update):
    await update.message.reply_text(
        "🎁 *GIFT SYSTEM*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📖 *Method 1 — Reply:*\n"
        "Reply to someone → `/gift [item name]`\n"
        "Reply to someone → `/gift [item name] [qty]`\n\n"
        "📖 *Method 2 — Username:*\n"
        "`/gift @username [item name]`\n"
        "`/gift @username [item name] [qty]`\n\n"
        "📋 *Examples:*\n"
        "  `/gift Health Potion 5` — send 5 potions (reply)\n"
        "  `/gift @john Elixir 3` — send 3 elixirs to John\n\n"
        "📋 *Rules:*\n"
        "  • Max 10 gifts per day\n"
        "  • Cannot gift equipped gear\n"
        "  • Omit quantity to send full stack",
        parse_mode='Markdown'
    )
