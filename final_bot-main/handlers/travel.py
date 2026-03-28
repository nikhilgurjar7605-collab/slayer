from telegram.error import BadRequest, TimedOut
from utils.guards import dm_only
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player
from utils.helpers import get_level
from config import TRAVEL_ZONES

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


@dm_only
async def travel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    level = get_level(player['xp'])
    current = player['location']

    buttons = []
    for zone in TRAVEL_ZONES:
        if level >= zone['level_req']:
            marker = " 📍" if zone['id'] == current else ""
            label = f"{zone['emoji']} {zone['name']}{marker}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"travel_to_{zone['id']}")])
        else:
            buttons.append([InlineKeyboardButton(
                f"🔒 {zone['name']}  (Lv.{zone['level_req']} required)",
                callback_data='travel_locked'
            )])

    current_zone = next((z for z in TRAVEL_ZONES if z['id'] == current), TRAVEL_ZONES[0])

    await update.message.reply_text(
        f"🗺️ *TRAVEL*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📍 *Current location:*  {current_zone['emoji']} {current_zone['name']}\n"
        f"⚔️  *Your level:*       Lv.{level}\n\n"
        f"🔓 *Accessible zones:*  {sum(1 for z in TRAVEL_ZONES if level >= z['level_req'])}/{len(TRAVEL_ZONES)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"_Tap a zone to travel there:_",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def travel_to(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == 'travel_locked':
        await query.answer("🔒 You haven't reached the required level!", show_alert=True)
        return

    zone_id = query.data[len('travel_to_'):]
    zone    = next((z for z in TRAVEL_ZONES if z['id'] == zone_id), None)
    if not zone:
        await query.answer("❌ Zone not found!", show_alert=True)
        return

    player = get_player(user_id)
    level  = get_level(player['xp'])
    if level < zone['level_req']:
        await query.answer(f"🔒 Requires Level {zone['level_req']}!", show_alert=True)
        return

    update_player(user_id, location=zone_id)

    # Butterfly Estate heals fully
    heal_note = ""
    if zone_id == 'butterfly':
        update_player(user_id, hp=player['max_hp'], sta=player['max_sta'])
        heal_note = "\n\n🌸 *The estate's warm atmosphere heals you fully!*\n❤️ HP + 🌀 STA fully restored!"

    await _safe_edit(query, 
        f"✈️ *TRAVELLED TO:*\n\n"
        f"{zone['emoji']} *{zone['name']}*\n\n"
        f"_{zone['desc']}_"
        f"{heal_note}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💡 Use /explore to fight enemies here!",
        parse_mode='Markdown'
    )
