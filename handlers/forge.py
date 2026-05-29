import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import get_inventory, remove_item, update_player, get_player, col

log = logging.getLogger(__name__)

# Define forge items data
FORGE_ITEMS = [
    {
        "name": "Crimson Nichirin Blade",
        "cost": 500,
        "str": 8,
        "requirements": {
            "Basic Nichirin Blade": 1,
            "Demon Blood": 3,
            "Wolf Fang": 2,
        },
    },
    {
        "name": "Jet Black Nichirin Blade",
        "cost": 2000,
        "str": 18,
        "requirements": {
            "Crimson Nichirin Blade": 1,
            "Blood Crystal": 2,
            "Boss Shard": 1,
            "Demon Blood": 5,
        },
    },
    {
        "name": "Scarlet Crimson Blade",
        "cost": 8000,
        "str": 30,
        "requirements": {
            "Jet Black Nichirin Blade": 1,
            "Blood Crystal": 4,
            "Boss Shard": 2,
            "Hashira Badge": 1,
            "Ancient Whetstone": 2,
        },
    },
    {
        "name": "Transparent Nichirin Blade",
        "cost": 20000,
        "str": 50,
        "requirements": {
            "Scarlet Crimson Blade": 1,
            "Rare Ore Fragment": 3,
            "Boss Shard": 3,
            "Titan Core": 1,
            "Ancient Whetstone": 3,
        },
    },
    {
        "name": "Sun Nichirin Blade",
        "cost": 60000,
        "str": 80,
        "requirements": {
            "Transparent Nichirin Blade": 1,
            "Sun Breathing Tome": 1,
            "Boss Shard": 5,
            "King Blade": 1,
            "Rengoku Shard": 3,
        },
    },
    {
        "name": "Reinforced Haori",
        "cost": 400,
        "def": 5,
        "hp": 20,
        "requirements": {
            "Corps Uniform": 1,
            "Spider Silk": 2,
            "Demon Blood": 3,
        },
    },
    {
        "name": "Hashira Haori",
        "cost": 1500,
        "def": 12,
        "hp": 40,
        "requirements": {
            "Reinforced Haori": 1,
            "Boss Shard": 2,
            "Spider Silk": 4,
            "Blood Crystal": 2,
        },
    },
]


def _get_user_inventory_map(user_id: int) -> dict:
    """Return a dict of item_name.lower() -> quantity for the user."""
    try:
        inv = get_inventory(user_id)
        return {item["item_name"].lower(): item.get("quantity", 0) for item in inv}
    except Exception as e:
        log.error("[FORGE] Failed to get inventory: %s", e)
        return {}


def _build_forge_keyboard():
    """Create an inline keyboard with a button for each forge item."""
    buttons = []
    for idx, item in enumerate(FORGE_ITEMS):
        buttons.append([InlineKeyboardButton(item["name"], callback_data=f"forge_{idx}")])
    buttons.append([InlineKeyboardButton("❌ Close", callback_data="forge_close")])
    return InlineKeyboardMarkup(buttons)


def _can_afford(player: dict, cost: int) -> bool:
    return player.get("yen", 0) >= cost


def _check_requirements(inv_map: dict, requirements: dict) -> dict:
    """Return dict of req_name -> (have, need, met)."""
    result = {}
    for req, needed in requirements.items():
        have = inv_map.get(req.lower(), 0)
        result[req] = (have, needed, have >= needed)
    return result


async def forge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/forge – Show the upgrade UI with all items as buttons."""
    try:
        await update.effective_message.reply_text(
            "⚒️ *Upgrade Forge*\n\nSelect an item to view its upgrade cost and your current resources.",
            parse_mode="Markdown",
            reply_markup=_build_forge_keyboard(),
        )
    except Exception as e:
        log.error("[FORGE] Failed to send forge UI: %s", e)


async def forge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses from the forge UI."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "forge_close":
        try:
            await query.message.delete()
        except Exception:
            await query.edit_message_text("Forge closed.")
        return

    if data.startswith("forge_confirm_"):
        await _handle_forge_confirm(query)
        return

    if not data.startswith("forge_"):
        return

    idx_str = data.split("_")[1]
    if not idx_str.isdigit():
        return

    idx = int(idx_str)
    if idx < 0 or idx >= len(FORGE_ITEMS):
        await query.edit_message_text("Invalid selection.")
        return

    item = FORGE_ITEMS[idx]
    user_id = query.from_user.id
    player = get_player(user_id)
    inv_map = _get_user_inventory_map(user_id)

    req_check = _check_requirements(inv_map, item["requirements"])
    can_afford_yen = _can_afford(player, item["cost"])
    all_resources_met = all(met for _, _, met in req_check.values())
    can_forge = all_resources_met and can_afford_yen

    lines = [f"⚒️ *{item['name']}*\n"]

    # Stats gained
    stat_parts = []
    if "str" in item:
        stat_parts.append(f"⚔️ +{item['str']} STR")
    if "def" in item:
        stat_parts.append(f"🛡️ +{item['def']} DEF")
    if "hp" in item:
        stat_parts.append(f"❤️ +{item['hp']} Max HP")
    if stat_parts:
        lines.append("*Gain:* " + "  |  ".join(stat_parts))

    # Yen cost
    yen_icon = "✅" if can_afford_yen else "❌"
    lines.append(f"\n💰 *Cost:* {item['cost']:,}¥  {yen_icon} _(you have {player.get('yen', 0):,}¥)_")

    # Resource requirements — show current/needed
    lines.append("\n📦 *Resources Required:*")
    for req, (have, needed, met) in req_check.items():
        icon = "✅" if met else "❌"
        lines.append(f"{icon} {req}: `{have}/{needed}`")

    if can_forge:
        lines.append("\n✨ *You have everything to forge this!*")
        confirm_button = InlineKeyboardButton(
            f"⚒️ Forge {item['name']}!", callback_data=f"forge_confirm_{idx}"
        )
        keyboard = InlineKeyboardMarkup([[confirm_button], [InlineKeyboardButton("🔙 Back", callback_data="forge_back")]])
    else:
        missing = []
        for req, (have, needed, met) in req_check.items():
            if not met:
                missing.append(f"{req} ({needed - have} more needed)")
        if not can_afford_yen:
            missing.append(f"Yen ({item['cost'] - player.get('yen', 0):,}¥ more needed)")
        lines.append(f"\n⚠️ *Missing:* {', '.join(missing)}")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="forge_back")]])

    text = "\n".join(lines)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


async def _handle_forge_confirm(query):
    """Actually perform the forge when user confirms."""
    user_id = query.from_user.id
    idx = int(query.data.split("_")[2])

    if idx < 0 or idx >= len(FORGE_ITEMS):
        await query.edit_message_text("Invalid forge item.")
        return

    item = FORGE_ITEMS[idx]
    player = get_player(user_id)
    inv_map = _get_user_inventory_map(user_id)

    req_check = _check_requirements(inv_map, item["requirements"])
    can_afford_yen = _can_afford(player, item["cost"])
    all_resources_met = all(met for _, _, met in req_check.values())

    if not all_resources_met or not can_afford_yen:
        await query.answer("❌ You no longer meet the requirements!", show_alert=True)
        return

    # Deduct yen
    update_player(user_id, yen=player["yen"] - item["cost"])

    # Consume resources
    for req, (_, needed, _) in req_check.items():
        remove_item(user_id, req, needed)

    # Grant stats
    updates = {}
    if "str" in item:
        updates["strength"] = player.get("strength", 0) + item["str"]
    if "def" in item:
        updates["defense"] = player.get("defense", 0) + item["def"]
    if "hp" in item:
        new_max = player.get("max_hp", 100) + item["hp"]
        updates["max_hp"] = new_max
        updates["hp"] = min(player.get("hp", 100) + item["hp"], new_max)

    if updates:
        update_player(user_id, **updates)

    stat_lines = []
    if "str" in item:
        stat_lines.append(f"⚔️ +{item['str']} STR")
    if "def" in item:
        stat_lines.append(f"🛡️ +{item['def']} DEF")
    if "hp" in item:
        stat_lines.append(f"❤️ +{item['hp']} Max HP")

    text = (
        f"⚒️ *Forge Successful!*\n\n"
        f"✨ *{item['name']}* has been forged!\n\n"
        f"{'  |  '.join(stat_lines)}\n\n"
        f"💰 -{item['cost']:,}¥ spent"
    )
    await query.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup([[
                                       InlineKeyboardButton("⚒️ Forge More", callback_data="forge_back")
                                   ]]))

    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


# Handle "Back" button
async def forge_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚒️ *Upgrade Forge*\n\nSelect an item to view its upgrade cost and your current resources.",
        parse_mode="Markdown",
        reply_markup=_build_forge_keyboard(),
    )


__all__ = ["forge_command", "forge_callback", "forge_back_callback"]
