import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.error import BadRequest, TimedOut
from telegram.ext import ContextTypes

from utils.database import get_player
from utils.guards import dm_only

log = logging.getLogger(__name__)


async def _safe_edit(query, text, **kwargs):
    """Edit a menu screen without creating duplicate messages."""
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        message = str(exc).lower()
        if "message is not modified" in message:
            return
        if "can't be edited" in message or "message to edit not found" in message:
            await query.message.reply_text(text, **kwargs)
            return
        raise
    except TimedOut:
        log.warning("Timed out while updating the menu screen.")


def _main_menu_keyboard():
    """Compact two-column navigation for Telegram mobile."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚔️ Explore", callback_data="goto_explore"),
            InlineKeyboardButton("👤 Profile", callback_data="goto_profile"),
        ],
        [
            InlineKeyboardButton("🎒 Inventory", callback_data="goto_inventory"),
            InlineKeyboardButton("🏪 Shop", callback_data="goto_shop"),
        ],
        [
            InlineKeyboardButton("🌳 Skill Tree", callback_data="goto_skilltree"),
            InlineKeyboardButton("👥 Party", callback_data="goto_party"),
        ],
        [
            InlineKeyboardButton("🏯 Infinity Castle", callback_data="castle:menu"),
            InlineKeyboardButton("🏯 Clan", callback_data="goto_clan"),
        ],
        [InlineKeyboardButton("✖️ Close Menu", callback_data="goto_close")],
    ])


@dm_only
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player = get_player(update.effective_user.id)
    msg = update.effective_message

    if not player:
        await msg.reply_text(
            "⚔️ <b>DEMON SLAYER</b>\n\n"
            "Your journey has not begun yet. Create your character to enter the world.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("🗡️ Create Character", callback_data="goto_start")
            ]]),
        )
        return

    name = escape(str(player.get("name") or update.effective_user.first_name or "Slayer"))
    rank = escape(str(player.get("rank", "Unranked")))
    level = max(1, int(player.get("level", 1) or 1))
    text = (
        "⛩️ <b>DEMON SLAYER CORPS</b>\n"
        "<i>Your journey continues.</i>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"Welcome back, <b>{name}</b>\n"
        f"🎖️ Rank: <b>{rank}</b>  •  Level: <b>{level}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "<b>Choose your destination</b>"
    )
    keyboard = _main_menu_keyboard()

    if update.callback_query:
        await _safe_edit(update.callback_query, text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await msg.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


@dm_only
async def close_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.edit_message_reply_markup(reply_markup=None)
        except BadRequest:
            pass
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Menu closed.",
            reply_markup=ReplyKeyboardRemove(),
        )
    elif update.message:
        await update.message.reply_text("Menu closed.", reply_markup=ReplyKeyboardRemove())
