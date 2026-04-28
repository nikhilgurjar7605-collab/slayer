from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut

from utils.database import get_player, get_inventory, remove_item, update_player
from utils.guards import dm_only


# ==================== UPGRADE RECIPES ====================
UPGRADE_RECIPES = {
    "Crimson Nichirin Blade": {
        "emoji": "⚔️",
        "replaces": "Basic Nichirin Blade",
        "desc": "Tempered with demon blood",
        "materials": {"Demon Blood": 5, "Wolf Fang": 3},
        "cost_yen": 500,
    },
    "Jet Black Nichirin Blade": {
        "emoji": "🗡️",
        "replaces": "Crimson Nichirin Blade",
        "desc": "Pinnacle of Nichirin blades",
        "materials": {"Blood Crystal": 3, "Boss Shard": 1, "Demon Blood": 10},
        "cost_yen": 2000,
    },
    "Reinforced Haori": {
        "emoji": "🛡️",
        "replaces": "Corps Uniform",
        "desc": "Reinforced demon silk armor",
        "materials": {"Spider Silk": 3, "Demon Blood": 5},
        "cost_yen": 400,
    },
    "Hashira Haori": {
        "emoji": "🥋",
        "replaces": "Reinforced Haori",
        "desc": "Elite Hashira protection",
        "materials": {"Boss Shard": 2, "Spider Silk": 5, "Blood Crystal": 2},
        "cost_yen": 1500,
    },
}

STAT_BOOSTS = {
    "Crimson Nichirin Blade": {"str_stat": 8},
    "Jet Black Nichirin Blade": {"str_stat": 18},
    "Reinforced Haori": {"def_stat": 5, "max_hp": 20},
    "Hashira Haori": {"def_stat": 12, "max_hp": 40},
}


def is_upgrade_enabled():
    from utils.database import col
    doc = col("settings").find_one({"key": "upgrade_enabled"})
    return doc.get("value", True) if doc else True


async def _safe_edit(query, text: str, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest:
        pass  # Ignore "message not modified" or similar errors


# ===================== MAIN UPGRADE HANDLER =====================
@dm_only
async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)

    if not player:
        await update.message.reply_text("❌ You don't have a character yet.\nUse /start to begin.")
        return

    if not is_upgrade_enabled():
        await update.message.reply_text("🔒 Upgrade system is currently disabled by admin.")
        return

    inv = get_inventory(user_id)
    inv_map = {item['item_name']: item['quantity'] for item in inv}

    # Show menu
    if not context.args:
        text = format_upgrade_menu(player, inv_map)
        buttons = create_upgrade_buttons(player, inv_map)

        await update.message.reply_text(
            text,
            parse_mode='HTML',
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
        )
        return

    # Direct upgrade using command: /upgrade Item Name
    item_name = ' '.join(context.args)
    recipe = UPGRADE_RECIPES.get(item_name)

    if not recipe:
        await update.message.reply_text(f"❌ No recipe found for <b>{item_name}</b>.", parse_mode='HTML')
        return

    await _do_upgrade(update.message, user_id, player, item_name, recipe, inv_map)


# ===================== CALLBACK HANDLER =====================
async def upgrade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    item_name = query.data.replace("upgrade_", "").replace("_", " ")
    player = get_player(query.from_user.id)

    if not player:
        await query.answer("❌ Player data not found.", show_alert=True)
        return

    recipe = UPGRADE_RECIPES.get(item_name)
    if not recipe:
        await query.answer("❌ Invalid upgrade.", show_alert=True)
        return

    inv = get_inventory(query.from_user.id)
    inv_map = {item['item_name']: item['quantity'] for item in inv}

    await _do_upgrade(query.message, query.from_user.id, player, item_name, recipe, inv_map, is_callback=True)


# ===================== MENU FORMATTER =====================
def format_upgrade_menu(player: dict, inv_map: dict) -> str:
    lines = [
        "🔨 <b>Upgrade Workshop</b>\n",
        f"💰 Balance: <b>{player.get('yen', 0):,}</b> ¥\n",
        "────────────────────\n"
    ]

    for name, data in UPGRADE_RECIPES.items():
        is_equipped = data['replaces'] in (
            player.get('equipped_sword', ''),
            player.get('equipped_armor', '')
        )
        equipped_tag = "   ✅ <i>Equipped</i>" if is_equipped else ""

        lines.append(f"{data['emoji']} <b>{name}</b>{equipped_tag}")
        lines.append(f"   {data['desc']}")
        lines.append(f"   Cost: <b>{data['cost_yen']:,}</b> ¥\n")
        lines.append("   Materials:")

        for mat, qty in data['materials'].items():
            have = inv_map.get(mat, 0)
            status = "✅" if have >= qty else "❌"
            lines.append(f"   • {mat:<16} {have}/{qty} {status}")

        lines.append("────────────────────\n")

    lines.append("💡 <i>You must have the previous item equipped to upgrade.</i>")

    return "\n".join(lines)


# ===================== BUTTON CREATOR =====================
def create_upgrade_buttons(player: dict, inv_map: dict):
    buttons = []
    for name, data in UPGRADE_RECIPES.items():
        is_equipped = data['replaces'] in (player.get('equipped_sword', ''), player.get('equipped_armor', ''))
        can_afford = player.get('yen', 0) >= data['cost_yen']
        has_materials = all(inv_map.get(mat, 0) >= qty for mat, qty in data['materials'].items())

        if is_equipped and can_afford and has_materials:
            buttons.append([InlineKeyboardButton(
                f"🔨 Upgrade to {name}",
                callback_data=f"upgrade_{name.replace(' ', '_')}"
            )])
    return buttons


# ===================== CORE UPGRADE LOGIC =====================
async def _do_upgrade(message, user_id: int, player: dict, item_name: str, recipe: dict, inv_map: dict, is_callback: bool = False):
    if not is_upgrade_enabled():
        await message.reply_text("🔒 Upgrade system is currently disabled.")
        return

    # Check materials
    missing = []
    for mat, qty in recipe['materials'].items():
        if inv_map.get(mat, 0) < qty:
            missing.append(f"   • {mat} ({inv_map.get(mat, 0)}/{qty})")

    if missing:
        await message.reply_text(
            f"❌ <b>Not enough materials for {item_name}</b>\n\n" + "\n".join(missing),
            parse_mode='HTML'
        )
        return

    if player.get('yen', 0) < recipe['cost_yen']:
        await message.reply_text(
            f"❌ Not enough Yen!\nNeeded: <b>{recipe['cost_yen']:,}</b> ¥\nYou have: <b>{player.get('yen', 0):,}</b> ¥",
            parse_mode='HTML'
        )
        return

    # === Execute Upgrade ===
    for mat, qty in recipe['materials'].items():
        remove_item(user_id, mat, qty)

    new_yen = player.get('yen', 0) - recipe['cost_yen']
    updates = {'yen': new_yen}

    # Equip new item
    if any(word in item_name for word in ["Blade", "Sword", "Nichirin"]):
        updates['equipped_sword'] = item_name
    else:
        updates['equipped_armor'] = item_name

    # Apply stat boosts
    for stat, value in STAT_BOOSTS.get(item_name, {}).items():
        updates[stat] = player.get(stat, 0) + value

    update_player(user_id, **updates)

    # Success Message
    materials_used = ", ".join(f"{qty}× {mat}" for mat, qty in recipe['materials'].items())
    boost_text = " + ".join([f"+{v} {k.replace('_stat','').replace('max_hp','Max HP').upper()}" 
                             for k, v in STAT_BOOSTS.get(item_name, {}).items()])

    success_msg = (
        f"🎉 <b>Upgrade Successful!</b>\n\n"
        f"{recipe['emoji']} <b>{item_name}</b>\n"
        f"   {recipe['desc']}\n\n"
        f"🧪 Materials Used:\n   {materials_used}\n"
        f"💰 Cost: <b>{recipe['cost_yen']:,}</b> ¥\n"
        f"⬆️ Bonus: <b>{boost_text}</b>\n\n"
        f"✅ Item has been automatically equipped."
    )

    await message.reply_text(success_msg, parse_mode='HTML')
