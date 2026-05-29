import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import get_player, col, update_player
from utils.guards import dm_only
from handlers.admin import has_admin_access

log = logging.getLogger(__name__)

# In‑memory pending trade storage {initiator_id: {'target_id': int, 'pet_id': str}}
_pending_trades = {}

def _get_active_pet(user_id: int):
    """Return the active pet document for a user, or None if none exists."""
    return col("pets").find_one({"user_id": user_id, "active": True})

@dm_only
async def petoffer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate a pet trade offer.
    Usage: ``/petoffer @target`` – offers your active pet to the target player.
    """
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ Usage: `/petoffer @username`", parse_mode='Markdown')
        return
    # Resolve target player
    target_name = context.args[0].lstrip('@')
    target_player = col("players").find_one({"username": {"$regex": f"^{target_name}$", "$options": "i"}})
    if not target_player:
        await update.message.reply_text("❌ Target player not found.")
        return
    target_id = target_player["user_id"]
    if target_id == user_id:
        await update.message.reply_text("⚠️ You cannot trade with yourself.")
        return
    # Check initiator has an active pet
    my_pet = _get_active_pet(user_id)
    if not my_pet:
        await update.message.reply_text("❌ You don't have an active pet to trade.")
        return
    # Record pending trade
    _pending_trades[user_id] = {"target_id": target_id, "pet_id": my_pet["_id"]}
    # Notify target with accept button
    markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Accept Pet Trade", callback_data=f"petaccept:{user_id}")]
    ])
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"👤 *{update.effective_user.full_name}* offers you their pet *{my_pet.get('name','Unnamed')}*.\n"
                "Use the button below to accept the trade."
            ),
            parse_mode='Markdown',
            reply_markup=markup,
        )
        await update.message.reply_text("📨 Trade offer sent to the target player.")
    except Exception as e:
        log.error("[EXCEPTION] %s", e)
        await update.message.reply_text("❌ Failed to send trade offer.")

async def _handle_trade_accept(initiator_id: int, accepter_id: int, query):
    """Finalize the trade: transfer pet ownership and clear pending state."""
    trade = _pending_trades.get(initiator_id)
    if not trade or trade["target_id"] != accepter_id:
        await query.answer("⚠️ No pending trade found.", show_alert=True)
        return
    pet_doc = col("pets").find_one({"_id": trade["pet_id"]})
    if not pet_doc:
        await query.answer("❌ Pet not found.", show_alert=True)
        _pending_trades.pop(initiator_id, None)
        return
    # Transfer ownership
    col("pets").update_one({"_id": pet_doc["_id"]}, {"$set": {"user_id": accepter_id}})
    # Optionally reset bond level or keep it – we keep it.
    _pending_trades.pop(initiator_id, None)
    await query.answer("✅ Trade accepted! Pet transferred.", show_alert=True)
    # Notify both parties
    await query.edit_message_text("✅ You accepted the pet trade. The pet is now yours.")
    try:
        await query.bot.send_message(
            chat_id=initiator_id,
            text=f"🎉 *{query.from_user.full_name}* accepted your pet trade. Your pet has been transferred.",
            parse_mode='Markdown',
        )
    except Exception as e:
        log.error("[EXCEPTION] %s", e)

async def petaccept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Callback handler for accepting a pet trade offer.
    The callback data is of the form ``petaccept:<initiator_id>``.
    """
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("petaccept:"):
        return
    initiator_id = int(data.split(":", 1)[1])
    accepter_id = query.from_user.id
    await _handle_trade_accept(initiator_id, accepter_id, query)

# Register a dummy command for direct trade without callback (optional)
@dm_only
async def pettrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for /petoffer – kept for backward compatibility."""
    await petoffer(update, context)
