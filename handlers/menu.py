from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.error import BadRequest, TimedOut
from telegram.ext import ContextTypes

from utils.database import get_player
from utils.guards import dm_only


async def _safe_edit(query, text, **kwargs):
    """Edit a message safely, falling back to reply on failure."""
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        if any(x in err.lower() for x in ("can't be edited", "message to edit not found", "not found")):
            try:
                await query.message.reply_text(text, **kwargs)
            except Exception:
                pass
            return
        raise
    except TimedOut:
        pass


@dm_only
async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)

    if not player:
        msg = update.message if update.message else update.callback_query.message
        await msg.reply_text(
            "No character found. Use /start to create one.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Create Character", callback_data="goto_start")]]
            ),
        )
        return

    text = (
        "*Main Menu*\n\n"
        "Choose an action below."
    )

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("  E X P L O R E  ", callback_data="goto_explore")]]
    )

    reply_kb = ReplyKeyboardMarkup(
        [
            [KeyboardButton("⚔️ Explore"), KeyboardButton("📜 Profile")],
            [KeyboardButton("❌ Close Menu")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
        input_field_placeholder="Use buttons or type a command...",
    )

    msg = update.message if update.message else update.callback_query.message
    if update.callback_query:
        await _safe_edit(update.callback_query, text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=reply_kb)


@dm_only
async def close_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        try:
            await query.delete_message()
        except Exception:
            pass
        try:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text="Menu closed.",
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception:
            pass
    elif update.message:
        await update.message.reply_text(
            "Menu closed.",
            reply_markup=ReplyKeyboardRemove(),
        )
