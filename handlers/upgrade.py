from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from utils.database import get_player, get_inventory, remove_item, update_player
from utils.guards import dm_only

# ==================== UPGRADE RECIPES ====================
UPGRADE_RECIPES = {
    "Crimson Nichirin Blade": {
        "replaces": "Basic Nichirin Blade",
        "desc": "+18 STR",
        "materials": {"Demon Blood": 5, "Wolf Fang": 3},
        "cost_yen": 2000,
    },
    "Jet Black Nichirin Blade": {
        "replaces": "Crimson Nichirin Blade",
        "desc": "+35 STR",
        "materials": {"Blood Crystal": 3, "Boss Shard": 1, "Demon Blood": 10},
        "cost_yen": 8000,
    },
    "Reinforced Haori": {
        "replaces": "Corps Uniform",
        "desc": "+12 DEF, +40 HP",
        "materials": {"Spider Silk": 3, "Demon Blood": 5},
        "cost_yen": 1500,
    },
    "Hashira Haori": {
        "replaces": "Reinforced Haori",
        "desc": "+25 DEF, +80 HP",
        "materials": {"Boss Shard": 2, "Spider Silk": 5, "Blood Crystal": 2},
        "cost_yen": 12000,
    },
}

STAT_BOOSTS = {
    "Crimson Nichirin Blade": {"str_stat": 18},
    "Jet Black Nichirin Blade": {"str_stat": 35},
    "Reinforced Haori": {"def_stat": 12, "max_hp": 40},
    "Hashira Haori": {"def_stat": 25, "max_hp": 80},
}


def is_upgrade_enabled():
    from utils.database import col
    doc = col("settings").find_one({"key": "upgrade_enabled"})
    return doc.get("value", True) if doc else True


# ===================== MENU FORMATTER =====================
def format_upgrade_menu(player: dict, inv_map: dict) -> str:
    lines = [
        "╔════════════════════════════════╗",
        "     ⛩️ 𝘿𝙀𝙈𝙊𝙉 𝙎𝙇𝘼𝙔𝙀𝙍 ⛩️",
        "         𝙐𝙋𝙂𝙍𝘼𝘿𝙀 𝙒𝙊𝙍𝙆𝙎𝙃𝙊𝙋",
        "╚════════════════════════════════╝\n",
        f"👛 Balance: ¥ {player.get('yen', 0):,}\n",
        "⚔️ Basic Nichirin Blade     🛡️ Corps Uniform\n",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n",
        "     ⚒️ 𝘼𝙑𝘼𝙄𝙇𝘼𝘽𝙇𝙀 𝙐𝙋𝙂𝙍𝘼𝘿𝙀𝙎 ⚒️",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    ]

    for name, data in UPGRADE_RECIPES.items():
        is_equipped = data['replaces'] in (
            player.get('equipped_sword', ''), 
            player.get('equipped_armor', '')
        )
        equipped_tag = " ✅" if is_equipped else ""

        lines.append(f"❖ {name}{equipped_tag}")
        lines.append(f"   ├─ 💰 Cost     : ¥ {data['cost_yen']:,}")
        lines.append(f"   ├─ 🏷️ Code     : {name.lower().replace(' ', '')}")
        lines.append(f"   ├─ 📝 Info     : {data['desc']}")

        # Materials
        mat_lines = []
        for mat, qty in data['materials'].items():
            have = inv_map.get(mat, 0)
            status = "✅" if have >= qty else "❌"
            mat_lines.append(f"{mat} ({have}/{qty}) {status}")

        lines.append(f"   └─ Materials   : {', '.join(mat_lines)}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("🛒 Upgrade Command")
    lines.append("└ Use: /upgrade [code]  or  /upgrade [name]")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    return "\n".join(lines)


# ===================== MAIN UPGRADE COMMAND =====================
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

    # Show menu if no arguments
    if not context.args:
        text = format_upgrade_menu(player, inv_map)
        await update.message.reply_text(text, parse_mode='HTML')
        return

    # Direct upgrade using /upgrade [name or code]
    item_name = ' '.join(context.args).strip()
    # Try to match by name
    recipe = UPGRADE_RECIPES.get(item_name)
    
    # If not found, try fuzzy match by code
    if not recipe:
        for key in UPGRADE_RECIPES.keys():
            if item_name.lower() in key.lower() or item_name.lower() == key.lower().replace(" ", ""):
                recipe = UPGRADE_RECIPES[key]
                item_name = key
                break

    if not recipe:
        await update.message.reply_text(f"❌ No upgrade found for: <b>{item_name}</b>", parse_mode='HTML')
        return

    await _do_upgrade(update.message, user_id, player, item_name, recipe, inv_map)


# ===================== CORE UPGRADE LOGIC =====================
async def _do_upgrade(message, user_id: int, player: dict, item_name: str, recipe: dict, inv_map: dict):
    if not is_upgrade_enabled():
        await message.reply_text("🔒 Upgrade system is currently disabled.")
        return

    # Check materials
    missing = []
    for mat, qty in recipe['materials'].items():
        if inv_map.get(mat, 0) < qty:
            missing.append(f"• {mat} ({inv_map.get(mat, 0)}/{qty})")

    if missing:
        await message.reply_text(
            f"❌ <b>Not enough materials for {item_name}</b>\n\n" + "\n".join(missing),
            parse_mode='HTML'
        )
        return

    if player.get('yen', 0) < recipe['cost_yen']:
        await message.reply_text(
            f"❌ Not enough Yen!\nNeeded: ¥ <b>{recipe['cost_yen']:,}</b>\nYou have: ¥ <b>{player.get('yen', 0):,}</b>",
            parse_mode='HTML'
        )
        return

    # Execute Upgrade
    for mat, qty in recipe['materials'].items():
        remove_item(user_id, mat, qty)

    updates = {'yen': player.get('yen', 0) - recipe['cost_yen']}

    # Equip item
    if "Blade" in item_name or "Nichirin" in item_name:
        updates['equipped_sword'] = item_name
    else:
        updates['equipped_armor'] = item_name

    # Apply stat boosts
    for stat, value in STAT_BOOSTS.get(item_name, {}).items():
        updates[stat] = player.get(stat, 0) + value

    update_player(user_id, **updates)

    # Success Message
    success_msg = (
        f"🎉 <b>Upgrade Successful!</b>\n\n"
        f"❖ {item_name}\n"
        f"   {recipe['desc']}\n\n"
        f"💰 Cost: ¥ {recipe['cost_yen']:,}\n"
        f"✅ Item has been automatically equipped."
    )

    await message.reply_text(success_msg, parse_mode='HTML')


# ===================== ADMIN TOGGLE =====================
async def upgradetoggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.admin import has_admin_access
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Admin only command.")
        return

    from utils.database import col
    current = is_upgrade_enabled()
    new_val = not current

    col("settings").update_one(
        {"key": "upgrade_enabled"},
        {"$set": {"value": new_val}},
        upsert=True
    )

    status = "✅ ENABLED" if new_val else "🔒 DISABLED"
    await update.message.reply_text(f"🔨 Upgrade system: {status}")


# Optional: Callback support (if you want to use buttons later)
async def upgrade_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Upgrade feature using buttons coming soon!", show_alert=True)
