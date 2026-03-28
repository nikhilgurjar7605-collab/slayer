from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, get_inventory

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


async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    inv = get_inventory(user_id)

    # Categorize
    items     = [i for i in inv if i['item_type'] == 'item']
    swords    = [i for i in inv if i['item_type'] == 'sword']
    armor_inv = [i for i in inv if i['item_type'] == 'armor']
    materials = [i for i in inv if i['item_type'] == 'material']

    location_name = player.get('location', 'asakusa').replace('_', ' ').title()

    lines = [
        f"╔══════════════════════╗",
        f"      🎒 𝙄𝙉𝙑𝙀𝙉𝙏𝙊𝙍𝙔",
        f"        「 {player['name'].upper()} 」",
        f"╚══════════════════════╝",
        f"",
        f"💠 𝙎𝙠𝙞𝙡𝙡 𝙋𝙩𝙨    : {player.get('skill_points', 0)} SP",
        f"💰 𝘽𝙖𝙡𝙖𝙣𝙘𝙚     : {player.get('yen', 0):,}¥",
        f"",
        f"🗡️ 𝙀𝙌𝙐𝙄𝙋𝙋𝙀𝘿",
        f"╰➤ ⚔️ 𝙎𝙬𝙤𝙧𝙙   : {player.get('equipped_sword', 'None')}",
        f"╰➤ 🛡️ 𝘼𝙧𝙢𝙤𝙧   : {player.get('equipped_armor', 'None')}",
    ]

    # Items
    lines.append(f"")
    lines.append(f"━━━━━━━━ 🧪 ━━━━━━━")
    lines.append(f"𝙄𝙏𝙀𝙈𝙎   ( /use )")
    if items:
        for i in items:
            lines.append(f"╰➤ {i['item_name']}   × {i['quantity']}")
    else:
        lines.append(f"╰➤ _No items_")

    # Swords
    lines.append(f"")
    lines.append(f"━━━━━━━━ ⚔️ ━━━━━━━")
    lines.append(f"𝙎𝙒𝙊𝙍𝘿𝙎   ( /equip )")
    if swords:
        for i in swords:
            lines.append(f"╰➤ {i['item_name']}")
    else:
        lines.append(f"╰➤ _No swords_")

    # Armor
    if armor_inv:
        lines.append(f"")
        lines.append(f"━━━━━━━━ 🛡️ ━━━━━━━")
        lines.append(f"𝘼𝙍𝙈𝙊𝙍")
        for i in armor_inv:
            lines.append(f"╰➤ {i['item_name']}")

    # Materials button at bottom
    mat_count = sum(i['quantity'] for i in materials)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"🎁 Materials ({len(materials)} types  ×{mat_count} total)",
            callback_data='inv_materials'
        )
    ]])

    msg = update.message if update.message else update.callback_query.message
    if update.callback_query:
        await update.callback_query.edit_message_text(
            '\n'.join(lines), parse_mode='Markdown', reply_markup=keyboard
        )
    else:
        await msg.reply_text('\n'.join(lines), parse_mode='Markdown', reply_markup=keyboard)


async def inv_materials_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    inv     = get_inventory(user_id)
    materials = [i for i in inv if i['item_type'] == 'material']

    lines = [
        f"╔══════════════════════╗",
        f"      🎁 𝙈𝘼𝙏𝙀𝙍𝙄𝘼𝙇𝙎",
        f"        「 {player['name'].upper()} 」",
        f"╚══════════════════════╝",
        f"",
        f"━━━━━━━ 🎁 ━━━━━━━━",
        f"𝙈𝘼𝙏𝙀𝙍𝙄𝘼𝙇𝙎   ( /sell )",
    ]

    if materials:
        for i in materials:
            lines.append(f"╰➤ {i['item_name']}   × {i['quantity']}")
    else:
        lines.append("╰➤ _No materials yet_")
        lines.append("_Defeat enemies to collect drops!_")

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back to Inventory", callback_data='inv_back')
    ]])

    await _safe_edit(query, '\n'.join(lines), parse_mode='Markdown', reply_markup=keyboard)


async def inv_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await inventory(update, context)
