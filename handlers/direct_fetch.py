"""
/sword & /armour — Direct fetch commands for forged items
Usage:
  /sword <item_name> — Fetch any sword directly to inventory (if you have materials)
  /armour <item_name> — Fetch any armor directly to inventory (if you have materials)
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes

from handlers.forge import FORGE_ITEMS
from utils.database import get_player, get_inventory, update_player, add_item, remove_item

log = logging.getLogger(__name__)


def _find_forge_item(item_name: str, category_filter: str = None):
    """Find a forge item by name (partial match)."""
    target = item_name.lower().strip()
    candidates = FORGE_ITEMS
    
    if category_filter:
        candidates = [i for i in FORGE_ITEMS if category_filter.lower() in i.get("category", "").lower()]
    
    # Exact match first
    for item in candidates:
        if item["name"].lower() == target or item["id"].lower() == target:
            return item
    
    # Partial match
    for item in candidates:
        if target in item["name"].lower() or target in item["id"].lower():
            return item
    
    return None


def _get_user_inventory_map(user_id: int) -> dict:
    """Return a dict of item_name.lower() -> quantity for the user."""
    try:
        inv = get_inventory(user_id)
        return {item["item_name"].lower(): item.get("quantity", 0) for item in inv}
    except Exception as e:
        log.error("[DIRECT_FETCH] Failed to get inventory: %s", e)
        return {}


async def sword_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/sword <item_name> — Directly fetch a sword to inventory."""
    user_id = update.effective_user.id
    player = get_player(user_id)
    
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "🗡️ *SWORD FETCH*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Usage: `/sword <name>`\n\n"
            "Examples:\n"
            "  `/sword Crimson Nichirin Blade`\n"
            "  `/sword Jet Black`\n"
            "  `/sword Sun Blade`\n\n"
            "⚠️ You must have the required materials in inventory!",
            parse_mode="Markdown"
        )
        return
    
    item_name = " ".join(context.args)
    item = _find_forge_item(item_name, category_filter="Swords")
    
    if not item:
        await update.message.reply_text(
            f"❌ Sword *{item_name}* not found in forge recipes.\n\n"
            f"Use `/forge` to see all available swords.",
            parse_mode="Markdown"
        )
        return
    
    # Check if it's actually a sword
    cat = item.get("category", "")
    if "Swords" not in cat and "blade" not in item.get("id", "").lower() and "fang" not in item.get("name", "").lower():
        await update.message.reply_text(
            f"❌ *{item['name']}* is not a sword!\n"
            f"Category: {cat}\n\n"
            f"Use `/armour` for armor items.",
            parse_mode="Markdown"
        )
        return
    
    inv_map = _get_user_inventory_map(user_id)
    
    # Check requirements
    missing = []
    for req, needed in item["requirements"].items():
        have = inv_map.get(req.lower(), 0)
        if have < needed:
            missing.append(f"{req} ({have}/{needed})")
    
    if missing:
        await update.message.reply_text(
            f"❌ Cannot fetch *{item['name']}* — missing materials:\n\n" +
            "\n".join([f"  • {m}" for m in missing]) +
            f"\n\n💰 Cost: {item['cost']:,}¥ (you have {player.get('yen', 0):,}¥)",
            parse_mode="Markdown"
        )
        return
    
    # Check yen
    if player.get("yen", 0) < item["cost"]:
        await update.message.reply_text(
            f"❌ Not enough yen!\n\n"
            f"Required: {item['cost']:,}¥\n"
            f"You have: {player.get('yen', 0):,}¥",
            parse_mode="Markdown"
        )
        return
    
    # Deduct yen and consume materials
    update_player(user_id, yen=player["yen"] - item["cost"])
    for req, needed in item["requirements"].items():
        remove_item(user_id, req, needed)
    
    # Add sword to inventory
    add_item(user_id, item["name"], "sword")
    
    # Apply stat boosts
    updates = {}
    if "str" in item:
        updates["str_stat"] = player.get("str_stat", 22) + item["str"]
    if "spd" in item:
        updates["spd"] = player.get("spd", 20) + item["spd"]
    if "def" in item:
        updates["def_stat"] = player.get("def_stat", 18) + item["def"]
    if "hp" in item:
        new_max_hp = player.get("max_hp", 240) + item["hp"]
        updates["max_hp"] = new_max_hp
        updates["hp"] = min(player.get("hp", 240) + item["hp"], new_max_hp)
    if "max_sta" in item:
        new_max_sta = player.get("max_sta", 170) + item["max_sta"]
        updates["max_sta"] = new_max_sta
        updates["sta"] = min(player.get("sta", 170) + item["max_sta"], new_max_sta)
    
    if updates:
        update_player(user_id, **updates)
    
    stat_lines = []
    if "str" in item: stat_lines.append(f"⚔️ +{item['str']} STR")
    if "spd" in item: stat_lines.append(f"⚡ +{item['spd']} SPD")
    if "def" in item: stat_lines.append(f"🛡️ +{item['def']} DEF")
    if "hp" in item: stat_lines.append(f"❤️ +{item['hp']} Max HP")
    if "max_sta" in item: stat_lines.append(f"🌀 +{item['max_sta']} Max STA")
    
    stats_text = "  |  ".join(stat_lines) if stat_lines else "No stat boosts"
    
    await update.message.reply_text(
        f"🗡️ *SWORD ACQUIRED!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✨ *{item['name']}* added to inventory!\n\n"
        f"{stats_text}\n\n"
        f"💰 -{item['cost']:,}¥ spent\n\n"
        f"Use `/equip` to wield your new blade!",
        parse_mode="Markdown"
    )


async def armour_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/armour <item_name> — Directly fetch armor to inventory."""
    user_id = update.effective_user.id
    player = get_player(user_id)
    
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return
    
    if not context.args:
        await update.message.reply_text(
            "🛡️ *ARMOUR FETCH*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Usage: `/armour <name>`\n\n"
            "Examples:\n"
            "  `/armour Reinforced Haori`\n"
            "  `/armour Hashira Haori`\n"
            "  `/armour Void Cloak`\n\n"
            "⚠️ You must have the required materials in inventory!",
            parse_mode="Markdown"
        )
        return
    
    item_name = " ".join(context.args)
    item = _find_forge_item(item_name, category_filter="Armor")
    
    if not item:
        # Try broader search
        item = _find_forge_item(item_name)
        if item:
            cat = item.get("category", "")
            if "Armor" not in cat and "Haori" not in item.get("name", "") and "Cloak" not in item.get("name", ""):
                await update.message.reply_text(
                    f"❌ *{item['name']}* is not armor!\n"
                    f"Category: {cat}\n\n"
                    f"Use `/sword` for weapons.",
                    parse_mode="Markdown"
                )
                return
    
    if not item:
        await update.message.reply_text(
            f"❌ Armor *{item_name}* not found in forge recipes.\n\n"
            f"Use `/forge` to see all available armor.",
            parse_mode="Markdown"
        )
        return
    
    inv_map = _get_user_inventory_map(user_id)
    
    # Check requirements
    missing = []
    for req, needed in item["requirements"].items():
        have = inv_map.get(req.lower(), 0)
        if have < needed:
            missing.append(f"{req} ({have}/{needed})")
    
    if missing:
        await update.message.reply_text(
            f"❌ Cannot fetch *{item['name']}* — missing materials:\n\n" +
            "\n".join([f"• {m}" for m in missing]) +
            f"\n\n💰 Cost: {item['cost']:,}¥ (you have {player.get('yen', 0):,}¥)",
            parse_mode="Markdown"
        )
        return
    
    # Check yen
    if player.get("yen", 0) < item["cost"]:
        await update.message.reply_text(
            f"❌ Not enough yen!\n\n"
            f"Required: {item['cost']:,}¥\n"
            f"You have: {player.get('yen', 0):,}¥",
            parse_mode="Markdown"
        )
        return
    
    # Deduct yen and consume materials
    update_player(user_id, yen=player["yen"] - item["cost"])
    for req, needed in item["requirements"].items():
        remove_item(user_id, req, needed)
    
    # Add armor to inventory
    add_item(user_id, item["name"], "armor")
    
    # Apply stat boosts
    updates = {}
    if "str" in item:
        updates["str_stat"] = player.get("str_stat", 22) + item["str"]
    if "spd" in item:
        updates["spd"] = player.get("spd", 20) + item["spd"]
    if "def" in item:
        updates["def_stat"] = player.get("def_stat", 18) + item["def"]
    if "hp" in item:
        new_max_hp = player.get("max_hp", 240) + item["hp"]
        updates["max_hp"] = new_max_hp
        updates["hp"] = min(player.get("hp", 240) + item["hp"], new_max_hp)
    if "max_sta" in item:
        new_max_sta = player.get("max_sta", 170) + item["max_sta"]
        updates["max_sta"] = new_max_sta
        updates["sta"] = min(player.get("sta", 170) + item["max_sta"], new_max_sta)
    
    if updates:
        update_player(user_id, **updates)
    
    stat_lines = []
    if "str" in item: stat_lines.append(f"⚔️ +{item['str']} STR")
    if "spd" in item: stat_lines.append(f"⚡ +{item['spd']} SPD")
    if "def" in item: stat_lines.append(f"🛡️ +{item['def']} DEF")
    if "hp" in item: stat_lines.append(f"❤️ +{item['hp']} Max HP")
    if "max_sta" in item: stat_lines.append(f"🌀 +{item['max_sta']} Max STA")
    
    stats_text = "  |  ".join(stat_lines) if stat_lines else "No stat boosts"
    
    await update.message.reply_text(
        f"🛡️ *ARMOUR ACQUIRED!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"✨ *{item['name']}* added to inventory!\n\n"
        f"{stats_text}\n\n"
        f"💰 -{item['cost']:,}¥ spent\n\n"
        f"Use `/equip` to wear your new armor!",
        parse_mode="Markdown"
    )
