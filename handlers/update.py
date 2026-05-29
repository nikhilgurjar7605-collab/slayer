import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

log = logging.getLogger(__name__)

# Sample changelog data – can be extended later

# Short recent summary for quick /updates command
_RECENT_SUMMARY = [
    "✅ Added Forge UI with upgrade paths",
    "✅ Fixed import errors (broadcast, update, pettrade)",
    "✅ Added /update command with changelog & features UI",
    "✅ Integrated forge and update handlers into bot",
    "✅ Improved callback routing to stop further handling",
]

_CHANGELOG = [
    "🔧 Fixed pet trade import errors.",
    "⚔️ Added pet damage scaling in PvP duels.",
    "📢 New broadcast command for platform updates.",
    "🛠️ Refactored mission reset logic.",
]

_FEATURES = [
    "🧪 Pet Trading System",
    "🎯 Mission System Framework",
    "📣 Admin Broadcasts",
    "💎 Enhanced Skill Tree UI",
]

def _build_keyboard():
    buttons = [
        [InlineKeyboardButton("📜 Changelog", callback_data="update_changelog")],
        [InlineKeyboardButton("✨ Features", callback_data="update_features")],
        [InlineKeyboardButton("❌ Close", callback_data="update_close")],
    ]
    return InlineKeyboardMarkup(buttons)

async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/update – Show a premium UI with recent changes and buttons.
    The message is styled with Markdown and a concise button panel.
    """
    text = "*🆕 Bot Update Overview*\n\n" \
           "Press a button below to explore the latest changes or new features."
    try:
        await update.effective_message.reply_text(
            text,
            parse_mode="Markdown",
            reply_markup=_build_keyboard(),
        )
    except Exception as e:
        log.error("[EXCEPTION] %s", e)

# New short command to quickly show recent updates without UI
async def recent_updates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/updates – Send a concise list of recent changes made in the project."""
    try:
        msg = "*📢 Recent Updates*\n" + "\n".join(_RECENT_SUMMARY)
        await update.effective_message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        log.error("[EXCEPTION] %s", e)

# Callback handlers for the update UI
async def update_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data == "update_changelog":
        msg = "*📜 Changelog*\n" + "\n".join(_CHANGELOG)
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=_build_keyboard())
    elif data == "update_features":
        msg = "*✨ New Features*\n" + "\n".join(_FEATURES)
        await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=_build_keyboard())
    elif data == "update_close":
        await query.message.delete()
    else:
        # Unknown callback – ignore
        pass

# Register the callback handler – the bot registers this via bot.py

# Export symbols for import
__all__ = ["update_command", "update_callback", "recent_updates"]
