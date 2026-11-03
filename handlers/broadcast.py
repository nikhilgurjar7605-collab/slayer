import logging
import asyncio
import html
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from handlers.admin import has_admin_access
from utils.database import get_all_players, col
log = logging.getLogger(__name__)


broadcast_status = {}
broadcast_reply_cache = {}

def _known_group_ids():
    return [int(row["chat_id"]) for row in col("broadcast_groups").find({}, {"chat_id": 1}) if row.get("chat_id")]

async def track_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if not chat or chat.type not in ("group", "supergroup"):
        return
    try:
        col("broadcast_groups").update_one(
            {"chat_id": chat.id},
            {"$set": {"chat_id": chat.id, "title": chat.title or "", "active": True}},
            upsert=True,
        )
    except Exception:
        log.exception("Could not register broadcast group %s", chat.id)



def _message_link(from_chat_id: int, message_id: int) -> str | None:
    chat_str = str(from_chat_id)
    if chat_str.startswith("-100"):
        return f"https://t.me/c/{chat_str.replace('-100', '')}/{message_id}"
    return None


async def _send_payload(bot, user_id: int, mode: str, content: dict) -> None:
    if mode == "fwd":
        await bot.forward_message(chat_id=user_id, from_chat_id=content["from_chat_id"], message_id=content["message_id"])
        return
    if mode == "copy":
        await bot.copy_message(chat_id=user_id, from_chat_id=content["from_chat_id"], message_id=content["message_id"])
        return
    if mode == "link":
        link = _message_link(content["from_chat_id"], content["message_id"])
        if not link:
            raise ValueError("Message link works only for supergroups/channels.")
        await bot.send_message(chat_id=user_id, text=f"📢 An Important Announcement: {link}")
        return
    if mode == "direct_photo":
        caption = content.get("caption", "")
        try:
            await bot.send_photo(chat_id=user_id, photo=content["photo_id"], caption=caption, parse_mode="HTML")
        except Exception as e:
            await bot.send_photo(chat_id=user_id, photo=content["photo_id"], caption=caption)
        return
    if mode == "direct_text":
        try:
            await bot.send_message(chat_id=user_id, text=content["text"], parse_mode="HTML", disable_web_page_preview=True)
        except Exception as e:
            await bot.send_message(chat_id=user_id, text=content["text"], disable_web_page_preview=True)
        return
    raise ValueError("Unknown broadcast mode.")


async def _execute_broadcast(context: ContextTypes.DEFAULT_TYPE, notify_chat_id: int, mode: str, content: dict, broadcast_id: str, target: str = "all") -> None:
    start_time = time.time()
    players = get_all_players() if target in ("all", "users") else []
    groups = _known_group_ids() if target in ("all", "groups") else []
    destinations = [int(p["user_id"]) for p in players] + groups
    sent = 0
    failed = 0
    failures = {}

    for chat_id in destinations:
        state = broadcast_status.get(broadcast_id)
        if not state or state.get("cancelled"):
            break
        try:
            await _send_payload(context.bot, chat_id, mode, content)
            sent += 1
        except Exception as e:
            failed += 1
            reason = str(e)[:80] or "Unknown error"
            failures[reason] = failures.get(reason, 0) + 1
        if (sent + failed) % 25 == 0:
            await asyncio.sleep(1)

    cancelled = broadcast_status.get(broadcast_id, {}).get("cancelled", False)
    duration = time.time() - start_time
    summary = (
        f"📣 *Broadcast {'cancelled' if cancelled else 'complete'}*\n\n"
        f"👥 Users: *{len(players)}* | Groups: *{len(groups)}*\n"
        f"✅ Sent: *{sent}*\n"
        f"❌ Failed: *{failed}*\n"
        f"⏱️ Duration: *{duration:.2f}s*"
    )
    if failures:
        report = "\n".join(f"• `{html.escape(reason)}`: {count}" for reason, count in list(failures.items())[:5])
        summary += f"\n\n*Failure Report:*\n{report}"
    await context.bot.send_message(chat_id=notify_chat_id, text=summary, parse_mode="Markdown")
    broadcast_status.pop(broadcast_id, None)


def _start_broadcast(context: ContextTypes.DEFAULT_TYPE, notify_chat_id: int, mode: str, content: dict, target: str = "all") -> str:
    broadcast_id = f"{notify_chat_id}_{int(time.time())}"
    broadcast_status[broadcast_id] = {"cancelled": False}
    asyncio.create_task(_execute_broadcast(context, notify_chat_id, mode, content, broadcast_id, target))
    return broadcast_id


async def bcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_admin_access(update.effective_user.id):
        return

    message = update.message
    args = list(context.args or [])
    target = "all"
    if args and args[0].lower() in ("group", "groups", "grouponly", "groupsonly"):
        target = "groups"
        args = args[1:]
    elif args and args[0].lower() in ("user", "users", "usersonly"):
        target = "users"
        args = args[1:]
    if message.reply_to_message:
        broadcast_reply_cache[update.effective_user.id] = {
            "from_chat_id": message.reply_to_message.chat.id,
            "message_id": message.reply_to_message.message_id,
            "target": target,
        }
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("➡️ Forward Message", callback_data="abroad_fwd")],
            [InlineKeyboardButton("©️ Send as Copy", callback_data="abroad_copy")],
            [InlineKeyboardButton("🔗 Send Message Link", callback_data="abroad_link")],
            [InlineKeyboardButton("❌ Cancel", callback_data="abroad_cancel")],
        ])
        await message.reply_text("❓ *Choose Broadcast Method:*", reply_markup=markup, parse_mode="Markdown")
        return

    if message.photo:
        caption = (message.caption or "").replace("/bcast", "", 1).replace("/announce", "", 1).strip()
        broadcast_id = _start_broadcast(
            context,
            message.chat.id,
            "direct_photo",
            {"photo_id": message.photo[-1].file_id, "caption": caption},
            target,
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Broadcast", callback_data=f"cancel_broadcast:{broadcast_id}")]])
        await message.reply_text("⏳ Photo broadcast initiated...", reply_markup=markup)
        return

    if args:
        text_to_send = " ".join(args)
        broadcast_id = _start_broadcast(
            context,
            message.chat.id,
            "direct_text",
            {"text": text_to_send},
            target,
        )
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Broadcast", callback_data=f"cancel_broadcast:{broadcast_id}")]])
        await message.reply_text("⏳ Text broadcast initiated...", reply_markup=markup)
        return

    await message.reply_text(
        "<b>Usage:</b>\n"
        "1. Reply to a message with <code>/bcast</code> or <code>/announce</code> for options.\n"
        "2. Send a photo with <code>/bcast your caption</code>.\n"
        "3. Type <code>/bcast your message</code> (users + groups).\n"
        "4. Use <code>/bcast groups your message</code> for groups only.\n"
        "5. Use <code>/bcast users your message</code> for users only.",
        parse_mode="HTML",
    )


async def handle_broadcast_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    admin_id = query.from_user.id
    if not has_admin_access(admin_id):
        await query.answer("Admins only.", show_alert=True)
        return

    if data == "abroad_cancel":
        broadcast_reply_cache.pop(admin_id, None)
        await query.edit_message_text("✅ Broadcast cancelled.")
        return

    if data.startswith("cancel_broadcast:"):
        broadcast_id = data.split(":", 1)[1]
        if broadcast_id in broadcast_status:
            broadcast_status[broadcast_id]["cancelled"] = True
        await query.answer("Broadcast cancellation requested.", show_alert=True)
        try:
            await query.edit_message_text("🛑 Broadcast cancellation requested.")
        except Exception as e:
            log.error("[EXCEPTION] %s", e)
        return

    cached = broadcast_reply_cache.get(admin_id)
    if not cached:
        await query.edit_message_text("⚠️ Broadcast session expired. Use the command again.")
        return

    mode = data.replace("abroad_", "")
    broadcast_id = _start_broadcast(
        context,
        query.message.chat.id,
        mode,
        {"from_chat_id": cached["from_chat_id"], "message_id": cached["message_id"]},
        cached.get("target", "all"),
    )
    broadcast_reply_cache.pop(admin_id, None)
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel Broadcast", callback_data=f"cancel_broadcast:{broadcast_id}")]])
    await query.edit_message_text("⏳ Broadcast initiated...", reply_markup=markup)
async def announce_changes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast a preset summary of recent platform changes.
    This command is admin‑only and uses the same broadcast infrastructure.
    """
    if not has_admin_access(update.effective_user.id):
        return
    # Summary of recent changes (keep concise for broadcast)
    summary = (
        "✨ *Slayer RPG – Recent Enhancements*\n"
        "\n"
        "• UI/UX overhaul – all techniques and styles now render as a single rich message.\n"
        "• Meditation system – gain *potential* and unlock Ascension tiers for permanent stat boosts.\n"
        "• Pet integration – active pets deal damage in combat, grant bonuses, and can be traded.\n"
        "• Reset command – fully clears pets, arts, missions, logs, cooldowns and clan membership.\n"
        "• New commands – /meditate, /pettrade, /petoffer, /petaccept and broadcast via /announce."
    )
    # Use direct_text mode to broadcast the summary to all users
    broadcast_id = _start_broadcast(
        context,
        update.effective_chat.id,
        "direct_text",
        {"text": summary},
    )
    # Provide a cancel button for the admin
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel Broadcast", callback_data=f"cancel_broadcast:{broadcast_id}")]
    ])
    await update.message.reply_text("⏳ Announcement broadcast initiated...", reply_markup=markup)

# End of file
