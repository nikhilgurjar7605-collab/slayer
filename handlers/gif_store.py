"""
GIF Banner Store
─────────────────────────────────────────────────────────────
Owner commands:
  /addgifbanner <name> <stars_price> <file_id>
      Add a GIF to the store.
  /removegifbanner <gif_id>
      Remove a GIF from the store by its Mongo _id (shown in /listgifbanners).
  /listgifbanners
      List all GIFs currently in the store (owner/admin only).

Player commands:
  /gifstore
      Browse the GIF banner store. Each GIF is shown one at a time
      with Prev / Next / Buy buttons.

Purchase flow:
  1. Player taps Buy → bot sends a Telegram Stars invoice.
  2. Player pays → pre_checkout auto-approved.
  3. successful_payment fires → GIF applied to profile instantly,
     no admin approval required.
"""

import logging
from bson import ObjectId
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
)
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, col

log = logging.getLogger(__name__)

# MongoDB collection name
GIF_STORE_COL = "gif_banner_store"


# ── Tiny DB helpers ────────────────────────────────────────────────────────

def _all_gifs() -> list:
    return list(col(GIF_STORE_COL).find({}))


def _get_gif(gif_id: str) -> dict | None:
    try:
        return col(GIF_STORE_COL).find_one({"_id": ObjectId(gif_id)})
    except Exception:
        return None


def _add_gif(name: str, price: int, file_id: str) -> str:
    result = col(GIF_STORE_COL).insert_one({
        "name":    name,
        "price":   price,   # in Telegram Stars
        "file_id": file_id,
    })
    return str(result.inserted_id)


def _remove_gif(gif_id: str) -> bool:
    try:
        res = col(GIF_STORE_COL).delete_one({"_id": ObjectId(gif_id)})
        return res.deleted_count > 0
    except Exception:
        return False


# ── Owner guard ────────────────────────────────────────────────────────────

def _is_owner(user_id: int) -> bool:
    from config import OWNER_ID
    return user_id == OWNER_ID


def _is_owner_or_admin(user_id: int) -> bool:
    from utils.database import is_admin
    return _is_owner(user_id) or is_admin(user_id)


# ── /addgifbanner ──────────────────────────────────────────────────────────

async def addgifbanner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Owner only.
    Usage: /addgifbanner <name> <stars_price> <file_id>
    Example: /addgifbanner "Fire Hashira" 30 CgACAgIAA...
    """
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    # Need at least 3 args: name, price, file_id
    # Name can be multi-word if quoted; simplest: everything before last two tokens
    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "Usage: /addgifbanner <name> <stars_price> <file_id>\n\n"
            "Example:\n"
            "/addgifbanner Fire\\_Hashira 30 CgACAgIAAx...\n\n"
            "Use underscores for spaces in the name.\n"
            "Price is in Telegram Stars ⭐.",
            parse_mode="Markdown"
        )
        return

    file_id  = args[-1].strip()
    try:
        price = int(args[-2])
    except ValueError:
        await update.message.reply_text("Price must be a whole number (e.g. 30).")
        return
    if price < 1:
        await update.message.reply_text("Price must be at least 1 Star.")
        return

    name = " ".join(args[:-2]).replace("_", " ").strip()
    if not name:
        await update.message.reply_text("Please provide a name for the GIF banner.")
        return

    inserted_id = _add_gif(name, price, file_id)
    log.info("[GIF_STORE] Added gif '%s' price=%s id=%s by owner", name, price, inserted_id)

    try:
        await context.bot.send_animation(
            chat_id=user_id,
            animation=file_id,
            caption=(
                f"GIF Banner Added to Store\n\n"
                f"Name: {name}\n"
                f"Price: {price} ⭐ Stars\n"
                f"Store ID: {inserted_id}\n\n"
                f"Players can browse it with /gifstore."
            ),
            parse_mode=None,
        )
    except Exception as e:
        log.error("[GIF_STORE] Could not preview gif: %s", e)
        await update.message.reply_text(
            f"GIF added to store!\n\nName: {name}\nPrice: {price} ⭐\nID: {inserted_id}\n\n"
            "(Preview failed — check that file_id is correct.)"
        )


# ── /removegifbanner ───────────────────────────────────────────────────────

async def removegifbanner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner only. /removegifbanner <store_id>"""
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /removegifbanner <store_id>\n\n"
            "Use /listgifbanners to see the IDs.",
            parse_mode=None
        )
        return

    gif_id = context.args[0].strip()
    ok = _remove_gif(gif_id)
    if ok:
        await update.message.reply_text(f"GIF banner {gif_id} removed from the store.")
        log.info("[GIF_STORE] Removed gif id=%s by owner", gif_id)
    else:
        await update.message.reply_text(
            f"No GIF found with ID: {gif_id}\n\nUse /listgifbanners to see valid IDs."
        )


# ── /listgifbanners ────────────────────────────────────────────────────────

async def listgifbanners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner/admin only. List all GIFs in the store."""
    user_id = update.effective_user.id
    if not _is_owner_or_admin(user_id):
        await update.message.reply_text("Admin only.")
        return

    gifs = _all_gifs()
    if not gifs:
        await update.message.reply_text("No GIF banners in the store yet.\n\nAdd with /addgifbanner.")
        return

    lines = [f"GIF Banner Store ({len(gifs)} items)\n"]
    for g in gifs:
        gid  = str(g["_id"])
        name = g.get("name", "?")
        price = g.get("price", "?")
        lines.append(f"• {name} — {price} ⭐\n  ID: `{gid}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /setmygifbanner – owner free self-apply ───────────────────────────────

async def setmygifbanner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Owner only. Apply any GIF banner to own profile without paying Stars.
    Usage: /setmygifbanner <file_id>
    """
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /setmygifbanner <file_id>\n\n"
            "Send a GIF to @raw_data_bot to get its file_id."
        )
        return

    file_id = context.args[0].strip()

    update_player(
        user_id,
        profile_banner_gif_id=file_id,
        profile_banner_file_id=None,
        profile_banner_url=None,
    )
    log.info("[GIF_STORE] Owner %s set own GIF banner file_id=%s", user_id, file_id)

    try:
        await context.bot.send_animation(
            chat_id=user_id,
            animation=file_id,
            caption="✅ Your GIF banner has been set (free, no Stars deducted).\nUse /profile to see it.",
        )
    except Exception as e:
        log.warning("[GIF_STORE] Could not preview gif: %s", e)
        await update.message.reply_text(
            "✅ GIF banner applied to your profile.\n"
            "(Preview failed — check the file_id is correct.)"
        )


# ── /gifstore — player browsing UI ────────────────────────────────────────

def _store_keyboard(index: int, total: int, gif_id: str, price: int, bot_username: str) -> InlineKeyboardMarkup:
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"gifstore_page_{index - 1}"))
    if index < total - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"gifstore_page_{index + 1}"))
    # Deep-link: opens bot DM and auto-triggers the invoice
    buy_url = f"https://t.me/{bot_username}?start=gifbuy_{gif_id}"
    buy_row = [InlineKeyboardButton(f"🛒 Buy {price} ⭐", url=buy_url)]
    rows = []
    if nav:
        rows.append(nav)
    rows.append(buy_row)
    return InlineKeyboardMarkup(rows)


async def gifstore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the GIF banner store, starting at page 0."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found. Use /start first.")
        return

    gifs = _all_gifs()
    if not gifs:
        await update.message.reply_text(
            "The GIF Banner Store is empty right now.\nCheck back later!"
        )
        return

    await _show_gif_page(update, context, gifs, index=0, edit=False)


async def _show_gif_page(update, context, gifs: list, index: int, edit: bool):
    g      = gifs[index]
    gif_id = str(g["_id"])
    name   = g.get("name", "GIF Banner")
    price  = g.get("price", 0)
    total  = len(gifs)

    from config import BOT_USERNAME
    keyboard = _store_keyboard(index, total, gif_id, price, BOT_USERNAME)

    caption = (
        f"🎨 GIF Banner Store\n\n"
        f"Name: {name}\n"
        f"Price: {price} ⭐ Stars\n"
        f"({index + 1} / {total})\n\n"
        f"Tap 🛒 Buy to open the bot DM and purchase instantly!"
    )

    try:
        if edit and update.callback_query:
            await update.callback_query.message.delete()
            await update.callback_query.message.chat.send_animation(
                animation=g["file_id"],
                caption=caption,
                parse_mode=None,
                reply_markup=keyboard,
            )
        else:
            msg = update.message or (update.callback_query.message if update.callback_query else None)
            await msg.reply_animation(
                animation=g["file_id"],
                caption=caption,
                parse_mode=None,
                reply_markup=keyboard,
            )
    except Exception as e:
        log.error("[GIF_STORE] Could not send GIF page: %s", e)
        err_msg = "Failed to load this GIF. It may have been removed."
        if update.callback_query:
            await update.callback_query.answer(err_msg, show_alert=True)
        else:
            await update.message.reply_text(err_msg)


async def gifstore_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Prev/Next navigation in the store."""
    query = update.callback_query
    await query.answer()

    index = int(query.data.split("_")[-1])
    gifs  = _all_gifs()

    if not gifs:
        await query.answer("Store is empty.", show_alert=True)
        return

    index = max(0, min(index, len(gifs) - 1))
    await _show_gif_page(update, context, gifs, index=index, edit=True)


# ── Buy via deep-link: /start gifbuy_<gif_id> ─────────────────────────────

async def gifstore_handle_deeplink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Called from start.py when user arrives via deep-link:
      /start gifbuy_<gif_id>
    Sends the Stars invoice directly in DM.
    """
    user_id = update.effective_user.id
    msg     = update.message

    if not context.args:
        return

    arg = context.args[0]
    if not arg.startswith("gifbuy_"):
        return

    gif_id = arg[len("gifbuy_"):]
    gif    = _get_gif(gif_id)

    if not gif:
        await msg.reply_text(
            "Sorry, that GIF banner is no longer available.\n"
            "Use /gifstore to browse current items."
        )
        return

    player = get_player(user_id)
    if not player:
        await msg.reply_text("No character found. Use /start to create one first.")
        return

    name  = gif.get("name", "GIF Banner")
    price = gif.get("price", 1)

    # Show a preview of the GIF before the invoice
    try:
        await context.bot.send_animation(
            chat_id=user_id,
            animation=gif["file_id"],
            caption=(
                f"🎨 *{name}*\n\n"
                f"Price: {price} ⭐ Stars\n\n"
                f"Applied to your profile instantly after purchase!\n"
                f"No admin approval needed."
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass  # preview failing shouldn't block the invoice

    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title=f"{name} — GIF Banner",
            description=(
                f"Buy the '{name}' animated GIF banner.\n"
                f"Applied to your profile instantly. No approval needed!"
            ),
            payload=f"gifstore_{gif_id}",
            provider_token="",  # Empty string required for Telegram Stars (XTR)
            currency="XTR",
            prices=[LabeledPrice(name, price)],
        )
        log.info("[GIF_STORE] Invoice sent via deeplink to user=%s gif=%s", user_id, gif_id)
    except Exception as e:
        log.error("[GIF_STORE] Deeplink invoice failed: %s", e)
        await msg.reply_text(
            "Failed to create the payment invoice. Please try again or contact an admin."
        )


# ── Buy flow: invoice → pre-checkout → successful payment ─────────────────

async def gifstore_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send Stars invoice when player taps Buy."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    gif_id = query.data.split("gifstore_buy_")[-1]
    gif    = _get_gif(gif_id)
    if not gif:
        await query.answer("This GIF is no longer available.", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await query.answer("No character found. Use /start first.", show_alert=True)
        return

    name  = gif.get("name", "GIF Banner")
    price = gif.get("price", 1)

    try:
        await context.bot.send_invoice(
            chat_id=user_id,
            title=f"{name} — GIF Banner",
            description=(
                f"Buy the '{name}' animated GIF banner.\n"
                f"It will be applied to your profile instantly upon purchase.\n"
                f"No approval needed!"
            ),
            payload=f"gifstore_{gif_id}",
            provider_token="",  # Empty string required for Telegram Stars (XTR)
            currency="XTR",
            prices=[LabeledPrice(name, price)],
        )
        # Tell user in-chat that invoice was sent to DM
        chat_id = update.callback_query.message.chat_id if update.callback_query.message else None
        if chat_id and chat_id != user_id:
            await query.answer("Invoice sent to your DM! Check your messages.", show_alert=True)
        else:
            await query.answer("Invoice sent! Check below to pay.", show_alert=False)
    except Exception as e:
        log.error("[GIF_STORE] Invoice send failed: %s", e)
        await query.answer(f"Failed to start payment: {e}", show_alert=True)


async def gifstore_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-approve pre-checkout for GIF store purchases."""
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("gifstore_"):
        await query.answer(ok=True)
    else:
        # Not our payload — pass (other handlers may take it)
        await query.answer(ok=False, error_message="Unknown payment.")


async def gifstore_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Apply the purchased GIF banner to the player's profile instantly."""
    payment = update.message.successful_payment
    payload = payment.invoice_payload  # "gifstore_<gif_id>"

    if not payload.startswith("gifstore_"):
        return  # not our payment

    user_id = update.effective_user.id
    gif_id  = payload.split("gifstore_")[-1]
    gif     = _get_gif(gif_id)

    player = get_player(user_id)
    if not player:
        await update.message.reply_text("Payment received but no character found. Contact an admin.")
        return

    if not gif:
        # GIF was removed after purchase — refund note + manual resolution
        await update.message.reply_text(
            "Payment received but the GIF is no longer available.\n"
            "Please contact an admin for a refund."
        )
        log.error("[GIF_STORE] Payment ok but gif %s not found for user %s", gif_id, user_id)
        return

    # Apply instantly — no approval needed
    update_player(
        user_id,
        profile_banner_gif_id=gif["file_id"],
        profile_banner_file_id=None,
        profile_banner_url=None,
    )
    log.info("[GIF_STORE] Purchased & applied gif='%s' to user=%s", gif.get("name"), user_id)

    name  = gif.get("name", "GIF Banner")
    price = payment.total_amount  # in Stars

    await update.message.reply_text(
        f"Purchase Successful!\n\n"
        f"'{name}' has been set as your profile banner.\n"
        f"Use /profile to see it.\n\n"
        f"Paid: {price} ⭐ Stars",
        parse_mode=None,
    )
