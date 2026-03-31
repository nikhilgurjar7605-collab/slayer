"""
Guards: private-chat redirects and button ownership checks.
"""
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType
from telegram.ext import ContextTypes

import config


STRICT_DM_HANDLERS = {"menu", "close_menu", "explore"}


def get_bot_link():
    """Return the direct bot link using BOT_USERNAME when configured."""
    username = getattr(config, "BOT_USERNAME", "your_bot")
    return f"https://t.me/{username}"


def _current_command_name(update: Update, func) -> str:
    """Best-effort command name for redirects; falls back to handler name."""
    text = update.message.text.strip() if update.message and update.message.text else ""
    if text.startswith("/"):
        first = text.split()[0]
        return first[1:].split("@")[0]
    return func.__name__


async def send_dm_redirect(update: Update, command: str):
    """Send a redirect message when a strict DM-only command is used in groups."""
    bot_link = get_bot_link()
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("Open Bot - Play in DM", url=bot_link)]]
    )
    await update.message.reply_text(
        f"*This command only works in private chat!*\n\n"
        f"`/{command}` is a DM-only gameplay command.\n"
        f"Use it directly in the bot to play.\n\n"
        f"*Tap below to open the bot:*",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


def dm_only(func):
    """Keep only a small set of legacy commands private-only."""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat = update.effective_chat
        uid = update.effective_user.id if update.effective_user else None

        if uid and uid == getattr(config, "OWNER_ID", None):
            return await func(update, context, *args, **kwargs)

        if chat and chat.type != ChatType.PRIVATE and func.__name__ in STRICT_DM_HANDLERS:
            cmd = _current_command_name(update, func)
            bot_link = get_bot_link()
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Use in Bot DM", url=bot_link)]]
            )
            dm_msg = (
                "*PRIVATE ONLY*\n\n"
                f"`/{cmd}` only works in the bot DM.\n\n"
                "*Tap below to use it:*"
            )
            if update.callback_query:
                await update.callback_query.answer(
                    f"/{cmd} only works in bot DM!",
                    show_alert=True,
                )
                try:
                    await update.callback_query.message.reply_text(
                        dm_msg,
                        parse_mode="Markdown",
                        reply_markup=keyboard,
                    )
                except Exception:
                    pass
            elif update.message:
                await update.message.reply_text(
                    dm_msg,
                    parse_mode="Markdown",
                    reply_markup=keyboard,
                )
            return

        return await func(update, context, *args, **kwargs)

    return wrapper


def owner_only_button(func):
    """Only the DM owner can click their own private battle buttons."""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        query = update.callback_query
        if query and query.from_user.id != query.message.chat_id:
            await query.answer("These buttons are not yours!", show_alert=True)
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


async def send_group_redirect(update: Update):
    """Tell the user the command only works in groups."""
    await update.message.reply_text(
        "*This command only works in a group!*\n\n"
        "`/challenge` is designed for group chat.\n"
        "Reply to someone's message in a group and type `/challenge`.\n\n"
        "*Add the bot to a group to use this feature!*",
        parse_mode="Markdown",
    )


def group_only(func):
    """Command only works in groups. Redirect DM users."""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        chat = update.effective_chat
        if chat and chat.type == ChatType.PRIVATE:
            await send_group_redirect(update)
            return
        return await func(update, context, *args, **kwargs)

    return wrapper


# ── Button spam guard ─────────────────────────────────────────────────────
import asyncio

def _get_user_lock(context, user_id: int) -> asyncio.Lock:
    """Return (creating if needed) a per-user asyncio.Lock stored in bot_data."""
    locks = context.bot_data.setdefault('_user_locks', {})
    if user_id not in locks:
        locks[user_id] = asyncio.Lock()
    return locks[user_id]


def no_button_spam(func):
    """
    Decorator that drops duplicate callback presses while a handler is still
    running for the same user.  The second press gets a silent query.answer()
    so Telegram stops showing the loading spinner — no error shown to the user.
    """
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        query = update.callback_query
        user_id = update.effective_user.id if update.effective_user else None
        if user_id is None:
            return await func(update, context, *args, **kwargs)

        lock = _get_user_lock(context, user_id)
        if lock.locked():
            # Already processing — silently dismiss the duplicate tap
            try:
                await query.answer()
            except Exception:
                pass
            return

        async with lock:
            return await func(update, context, *args, **kwargs)

    return wrapper
