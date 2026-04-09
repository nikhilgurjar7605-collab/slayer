import logging
from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, get_inventory
log = logging.getLogger(__name__)

PAGE_SIZE = 10   # materials shown per page


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
        except Exception as e:
            log.error("[EXCEPTION] %s", e)


async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    inv = get_inventory(user_id)

    items     = [i for i in inv if i["item_type"] == "item"]
    swords    = [i for i in inv if i["item_type"] == "sword"]
    armor_inv = [i for i in inv if i["item_type"] == "armor"]
    materials = [i for i in inv if i["item_type"] == "material"]

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

    lines.append("")
    lines.append("━━━━━━━━ 🧪 ━━━━━━━")
    lines.append("𝙄𝙏𝙀𝙈𝙎   ( /use )")
    if items:
        for i in items:
            lines.append(f"╰➤ {i['item_name']}   × {i['quantity']}")
    else:
        lines.append("╰➤ _No items_")

    lines.append("")
    lines.append("━━━━━━━━ ⚔️ ━━━━━━━")
    lines.append("𝙎𝙒𝙊𝙍𝘿𝙎   ( /equip )")
    if swords:
        for i in swords:
            lines.append(f"╰➤ {i['item_name']}")
    else:
        lines.append("╰➤ _No swords_")

    if armor_inv:
        lines.append("")
        lines.append("━━━━━━━━ 🛡️ ━━━━━━━")
        lines.append("𝘼𝙍𝙈𝙊𝙍")
        for i in armor_inv:
            lines.append(f"╰➤ {i['item_name']}")

    mat_count = sum(i["quantity"] for i in materials)
    mat_types = len(materials)
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"🎁 Materials ({mat_types} types  ×{mat_count} total)",
            callback_data="inv_materials_0"
        )
    ]])

    msg = update.message if update.message else update.callback_query.message
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "\n".join(lines), parse_mode="Markdown", reply_markup=keyboard
        )
    else:
        await msg.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


async def inv_materials_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle both inv_materials (legacy) and inv_materials_<page> callbacks."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    inv     = get_inventory(user_id)
    materials = [i for i in inv if i["item_type"] == "material"]

    # Parse page number from callback_data
    data = query.data  # e.g. "inv_materials_0" or legacy "inv_materials"
    try:
        page = int(data.split("_")[-1])
    except (ValueError, IndexError):
        page = 0

    total = len(materials)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))   # clamp
    start = page * PAGE_SIZE
    page_items = materials[start:start + PAGE_SIZE]

    lines = [
        f"╔══════════════════════╗",
        f"      🎁 𝙈𝘼𝙏𝙀𝙍𝙄𝘼𝙇𝙎",
        f"        「 {player['name'].upper()} 」",
        f"╚══════════════════════╝",
        f"",
        f"━━━━━━━ 🎁 ━━━━━━━━",
        f"𝙈𝘼𝙏𝙀𝙍𝙄𝘼𝙇𝙎   ( /sell )  • Page {page+1}/{total_pages}",
    ]

    if page_items:
        for i in page_items:
            lines.append(f"╰➤ {i['item_name']}   × {i['quantity']}")
    else:
        lines.append("╰➤ _No materials yet_")
        lines.append("_Defeat enemies to collect drops!_")

    # Build navigation row
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"inv_materials_{page-1}"))
    nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"inv_materials_{page+1}"))

    keyboard = InlineKeyboardMarkup([
        nav_buttons,
        [InlineKeyboardButton("🔙 Back to Inventory", callback_data="inv_back")]
    ])

    await _safe_edit(query, "\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


async def inv_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await inventory(update, context)
