from telegram.error import BadRequest, TimedOut
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, col
from config import OWNER_ID, SUDO_ADMIN_IDS

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


async def suggest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)

    if not context.args:
        await update.message.reply_text(
            "╔══════════════════════╗\n"
            "      💡 𝙎𝙐𝙂𝙂𝙀𝙎𝙏𝙄𝙊𝙉𝙎\n"
            "╚══════════════════════╝\n\n"
            "╰➤ Share your ideas to improve the bot!\n\n"
            "📝 *Usage:*\n"
            "`/suggest [your idea here]`\n\n"
            "📌 *Example:*\n"
            "`/suggest Add a weekly tournament mode`\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "_All suggestions are reviewed by admins._",
            parse_mode='Markdown'
        )
        return

    text = ' '.join(context.args)

    if len(text) < 10:
        await update.message.reply_text(
            "❌ Suggestion too short!\n\n_Please write at least 10 characters._",
            parse_mode='Markdown'
        )
        return

    if len(text) > 500:
        await update.message.reply_text(
            "❌ Suggestion too long!\n\n_Max 500 characters. Please keep it concise._",
            parse_mode='Markdown'
        )
        return

    # Check rate limit — max 3 suggestions per day
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    count_today = col("suggestions").count_documents({
        "user_id": user_id,
        "created_at": {"$gte": today}
    })
    if count_today >= 3:
        await update.message.reply_text(
            "⏳ *Suggestion limit reached!*\n\n"
            "_You can send up to 3 suggestions per day._\n"
            "_Try again tomorrow!_",
            parse_mode='Markdown'
        )
        return

    name = player['name'] if player else update.effective_user.first_name
    username = update.effective_user.username or "no_username"

    # Save to MongoDB
    result = col("suggestions").insert_one({
        "user_id":    user_id,
        "name":       name,
        "username":   username,
        "text":       text,
        "status":     "pending",
        "created_at": datetime.now()
    })
    suggestion_id = str(result.inserted_id)[-6:].upper()  # short ID for display

    # Confirm to user
    await update.message.reply_text(
        f"╔══════════════════════╗\n"
        f"   ✅ 𝙎𝙐𝙂𝙂𝙀𝙎𝙏𝙄𝙊𝙉 𝙎𝙀𝙉𝙏!\n"
        f"╚══════════════════════╝\n\n"
        f"╰➤ ID: `#{suggestion_id}`\n"
        f"╰➤ Status: ⏳ *Pending review*\n\n"
        f"📝 *Your idea:*\n"
        f"_{text}_\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"_Thank you! Admins will review it soon._",
        parse_mode='Markdown'
    )

    # Forward to all admins
    admin_ids = list(SUDO_ADMIN_IDS or [])
    if OWNER_ID and OWNER_ID not in admin_ids:
        admin_ids.append(OWNER_ID)

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ 𝘼𝙥𝙥𝙧𝙤𝙫𝙚",  callback_data=f"sug_approve_{result.inserted_id}"),
            InlineKeyboardButton("❌ 𝘿𝙞𝙨𝙢𝙞𝙨𝙨", callback_data=f"sug_dismiss_{result.inserted_id}"),
        ],
        [
            InlineKeyboardButton("⭐ 𝙈𝙖𝙧𝙠 𝙋𝙡𝙖𝙣𝙣𝙚𝙙", callback_data=f"sug_planned_{result.inserted_id}"),
        ]
    ])

    admin_msg = (
        f"╔══════════════════════╗\n"
        f"      💡 𝙉𝙀𝙒 𝙎𝙐𝙂𝙂𝙀𝙎𝙏𝙄𝙊𝙉\n"
        f"╚══════════════════════╝\n\n"
        f"👤 *From:* {name} (@{username})\n"
        f"🆔 *User ID:* `{user_id}`\n"
        f"📋 *ID:* `#{suggestion_id}`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 *Suggestion:*\n"
        f"{text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    for admin_id in admin_ids:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_msg,
                parse_mode='Markdown',
                reply_markup=keyboard
            )
        except Exception:
            pass


# ── /suggestions — Admin view all ─────────────────────────────────────────

async def suggestions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    # Check admin
    from handlers.admin import has_admin_access
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    # Parse filter
    status_filter = context.args[0].lower() if context.args else "pending"
    valid = ["pending", "approved", "planned", "dismissed", "all"]
    if status_filter not in valid:
        status_filter = "pending"

    query_filter = {} if status_filter == "all" else {"status": status_filter}
    items = list(col("suggestions").find(query_filter).sort("created_at", -1).limit(10))

    if not items:
        await update.message.reply_text(
            f"📭 No *{status_filter}* suggestions found.\n\n"
            f"Usage: `/suggestions [pending|approved|planned|dismissed|all]`",
            parse_mode='Markdown'
        )
        return

    status_icons = {
        "pending":   "⏳",
        "approved":  "✅",
        "planned":   "⭐",
        "dismissed": "❌",
    }

    lines = [
        f"╔══════════════════════╗",
        f"      💡 𝙎𝙐𝙂𝙂𝙀𝙎𝙏𝙄𝙊𝙉𝙎 [{status_filter.upper()}]",
        f"╚══════════════════════╝\n",
    ]

    for item in items:
        sid   = str(item['_id'])[-6:].upper()
        icon  = status_icons.get(item['status'], '⏳')
        lines.append(
            f"{icon} `#{sid}` — *{item['name']}*\n"
            f"   _{item['text'][:80]}{'...' if len(item['text']) > 80 else ''}_\n"
        )

    total = col("suggestions").count_documents({})
    pending = col("suggestions").count_documents({"status": "pending"})
    lines += [
        "━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Total: *{total}*  |  ⏳ Pending: *{pending}*",
        "",
        "💡 `/suggestions [pending|approved|planned|dismissed|all]`"
    ]

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


# ── Callback: approve / dismiss / planned ─────────────────────────────────

async def suggestion_action_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    from handlers.admin import has_admin_access
    if not has_admin_access(user_id):
        await query.answer("❌ Admins only!", show_alert=True)
        return

    parts  = query.data.split('_')
    action = parts[1]          # approve / dismiss / planned
    oid    = parts[2]          # MongoDB ObjectId string

    from bson import ObjectId
    try:
        obj_id = ObjectId(oid)
    except Exception:
        await query.answer("❌ Invalid suggestion ID.", show_alert=True)
        return

    status_map = {
        "approve": "approved",
        "dismiss": "dismissed",
        "planned": "planned",
    }
    new_status = status_map.get(action)
    if not new_status:
        return

    sug = col("suggestions").find_one({"_id": obj_id})
    if not sug:
        await query.answer("❌ Suggestion not found.", show_alert=True)
        return

    col("suggestions").update_one({"_id": obj_id}, {"$set": {
        "status":      new_status,
        "reviewed_by": user_id,
        "reviewed_at": datetime.now()
    }})

    icons = {"approved": "✅", "dismissed": "❌", "planned": "⭐"}
    icon  = icons[new_status]
    sid   = oid[-6:].upper()

    # Update the admin message
    await _safe_edit(query, 
        f"╔══════════════════════╗\n"
        f"      💡 𝙎𝙐𝙂𝙂𝙀𝙎𝙏𝙄𝙊𝙉 {icon}\n"
        f"╚══════════════════════╝\n\n"
        f"👤 *From:* {sug['name']} (@{sug.get('username','?')})\n"
        f"📋 *ID:* `#{sid}`\n"
        f"📊 *Status:* {icon} *{new_status.upper()}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 *Suggestion:*\n"
        f"{sug['text']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        parse_mode='Markdown'
    )

    # Notify the user
    label_map = {
        "approved":  "✅ Your suggestion was *approved!* It may be added to the bot.",
        "dismissed": "❌ Your suggestion was reviewed and dismissed.\n_Keep suggesting — great ideas are always welcome!_",
        "planned":   "⭐ Your suggestion has been *marked as planned!* It's coming to the bot soon.",
    }
    try:
        await context.bot.send_message(
            chat_id=sug['user_id'],
            text=(
                f"╔══════════════════════╗\n"
                f"   📬 𝙎𝙐𝙂𝙂𝙀𝙎𝙏𝙄𝙊𝙉 𝙐𝙋𝘿𝘼𝙏𝙀\n"
                f"╚══════════════════════╝\n\n"
                f"📋 *ID:* `#{sid}`\n"
                f"💬 *Your idea:* _{sug['text'][:100]}_\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{label_map[new_status]}"
            ),
            parse_mode='Markdown'
        )
    except Exception:
        pass
