import logging
from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TimedOut
from telegram.ext import ContextTypes

from utils.database import get_player, get_inventory, col

log = logging.getLogger(__name__)

PAGE_SIZE = 10


def _safe(value):
    return escape(str(value if value not in (None, "") else "None"))


async def _safe_edit(query, text, **kwargs):
    """Edit the current inventory screen, falling back only when necessary."""
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
        log.warning("Timed out while updating inventory for user %s", query.from_user.id)


def _inventory_keyboard(material_count, material_total):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🎁 Materials · {material_count} types / {material_total} total",
            callback_data="inv_materials_0",
        )],
        [
            InlineKeyboardButton("🏯 Castle Gear", callback_data="castle:equipment"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="goto_menu"),
        ],
    ])


def _render_inventory(player, inventory, castle_gear):
    items = [item for item in inventory if item.get("item_type") == "item"]
    swords = [item for item in inventory if item.get("item_type") == "sword"]
    armours = [item for item in inventory if item.get("item_type") == "armor"]
    materials = [item for item in inventory if item.get("item_type") == "material"]

    lines = [
        "🎒 <b>INVENTORY</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"💴 Yen: <b>{int(player.get('yen', 0) or 0):,}</b>  •  💠 Skill Points: <b>{int(player.get('skill_points', 0) or 0)}</b>",
        "",
        "<b>⚔️ EQUIPPED GEAR</b>",
        f"🗡️ Sword: {_safe(player.get('equipped_sword'))}",
        f"🛡️ Armour: {_safe(player.get('equipped_armor'))}",
        "",
        f"<b>🧪 ITEMS</b> · {len(items)} types",
    ]

    if items:
        lines.extend(
            f"• {_safe(item.get('item_name'))} × <b>{int(item.get('quantity', 0) or 0)}</b>"
            for item in items
        )
    else:
        lines.append("<i>No usable items yet.</i>")

    lines.extend(["", f"<b>🗡️ WEAPONS</b> · {len(swords)} owned"])
    if swords:
        lines.extend(f"• {_safe(item.get('item_name'))}" for item in swords)
    else:
        lines.append("<i>No extra weapons.</i>")

    lines.extend(["", f"<b>🛡️ ARMOUR</b> · {len(armours)} owned"])
    if armours:
        lines.extend(f"• {_safe(item.get('item_name'))}" for item in armours)
    else:
        lines.append("<i>No extra armour.</i>")

    if castle_gear:
        lines.extend(["", "<b>🏯 CASTLE EQUIPMENT</b>"])
        for gear in castle_gear:
            equipped = " · <b>EQUIPPED</b>" if gear.get("equipped") else ""
            rarity = _safe(str(gear.get("rarity", "common")).title())
            lines.append(
                f"• {_safe(gear.get('name', 'Unknown gear'))} "
                f"<i>({rarity})</i>{equipped}"
            )

    return "\n".join(lines), materials


async def inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    msg = update.effective_message

    if not player:
        await msg.reply_text(
            "⚠️ No character found. Use /start to create your character."
        )
        return

    inv = get_inventory(user_id)
    castle_gear = list(
        col("castle_equipment")
        .find({"user_id": user_id})
        .sort("obtained_at", -1)
        .limit(10)
    )
    text, materials = _render_inventory(player, inv, castle_gear)
    material_total = sum(int(item.get("quantity", 0) or 0) for item in materials)
    keyboard = _inventory_keyboard(len(materials), material_total)

    if update.callback_query:
        await _safe_edit(
            update.callback_query, text, parse_mode="HTML", reply_markup=keyboard
        )
    else:
        await msg.reply_text(text, parse_mode="HTML", reply_markup=keyboard)


async def inv_materials_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Paginated material view; supports both legacy and page-specific callbacks."""
    query = update.callback_query
    await query.answer()
    materials = [
        item for item in get_inventory(query.from_user.id)
        if item.get("item_type") == "material"
    ]

    try:
        page = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        page = 0

    total_pages = max(1, (len(materials) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    page_items = materials[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = [
        "🎁 <b>MATERIALS</b>",
        "━━━━━━━━━━━━━━━━━━━━",
        f"Page <b>{page + 1}/{total_pages}</b>  •  {len(materials)} material types",
        "",
    ]
    if page_items:
        for item in page_items:
            lines.append(
                f"• {_safe(item.get('item_name'))} × <b>{int(item.get('quantity', 0) or 0)}</b>"
            )
    else:
        lines.extend(["<i>Your materials pouch is empty.</i>", "Defeat enemies to collect drops."])

    navigation = []
    if page > 0:
        navigation.append(InlineKeyboardButton("◀️ Previous", callback_data=f"inv_materials_{page - 1}"))
    navigation.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        navigation.append(InlineKeyboardButton("Next ▶️", callback_data=f"inv_materials_{page + 1}"))

    keyboard = InlineKeyboardMarkup([
        navigation,
        [
            InlineKeyboardButton("🎒 Inventory", callback_data="inv_back"),
            InlineKeyboardButton("🏠 Main Menu", callback_data="goto_menu"),
        ],
    ])
    await _safe_edit(query, "\n".join(lines), parse_mode="HTML", reply_markup=keyboard)


async def inv_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await inventory(update, context)
