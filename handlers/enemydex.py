"""
/slayerdex & /demondex — Regional enemy encyclopedia
Shows which Slayers and Demons are found in each region/zone.
Usage:
  /slayerdex — Show all Slayer enemies by region
  /demondex  — Show all Demon enemies by region
  /slayerdex <region> — Show slayers in specific region
  /demondex <region>  — Show demons in specific region
"""
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import REGION_ENEMIES, TRAVEL_ZONES

log = logging.getLogger(__name__)


def _get_region_enemies_by_faction(faction_type: str):
    """Get enemies filtered by faction (slayer or demon) grouped by region."""
    result = {}
    
    for region_id, region_data in REGION_ENEMIES.items():
        enemies = region_data.get("enemies", [])
        faction_enemies = [e for e in enemies if e.get("faction_type") == faction_type]
        
        if faction_enemies:
            # Find region display name
            zone_info = next((z for z in TRAVEL_ZONES if z["id"] == region_id), None)
            region_name = zone_info["name"] if zone_info else region_id.title()
            region_emoji = zone_info["emoji"] if zone_info else "📍"
            
            result[region_id] = {
                "name": region_name,
                "emoji": region_emoji,
                "enemies": faction_enemies,
                "level_req": zone_info.get("level_req", 0) if zone_info else 0
            }
    
    return result


def _format_enemy(enemy: dict, show_drops: bool = False) -> str:
    """Format a single enemy entry."""
    emoji = enemy.get("emoji", "👤")
    name = enemy.get("name", "Unknown")
    threat = enemy.get("threat", "🟢 LOW")
    is_boss = enemy.get("is_boss", False)
    
    line = f"{emoji} **{name}** {threat}"
    if is_boss:
        line = f"💀 **{name}** (BOSS) {threat}"
    
    parts = []
    if "hp" in enemy:
        parts.append(f"HP:{enemy['hp']}")
    if "atk" in enemy:
        parts.append(f"ATK:{enemy['atk']}")
    if "xp" in enemy:
        parts.append(f"XP:{enemy['xp']}")
    
    if parts:
        line += f"\n  └ {', '.join(parts)}"
    
    if show_drops and enemy.get("drops"):
        drops = ", ".join(enemy["drops"][:3])
        if len(enemy["drops"]) > 3:
            drops += f" (+{len(enemy['drops'])-3} more)"
        line += f"\n  └ 🎁 Drops: {drops}"
    
    return line


async def slayerdex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/slayerdex — Show all Slayer enemies by region."""
    args = context.args or []
    
    slayer_regions = _get_region_enemies_by_faction("slayer")
    
    if not slayer_regions:
        await update.message.reply_text("❌ No Slayer enemies found in any region.")
        return
    
    # If region specified
    if args:
        region_query = args[0].lower()
        matched_region = None
        
        for rid, rdata in slayer_regions.items():
            if rid.lower() == region_query or rdata["name"].lower() == region_query.lower():
                matched_region = (rid, rdata)
                break
        
        if not matched_region:
            await update.message.reply_text(
                f"❌ Region *{args[0]}* not found.\n\n"
                f"Available regions:\n" +
                "\n".join([f"• {r['emoji']} {r['name']}" for r in slayer_regions.values()]),
                parse_mode="Markdown"
            )
            return
        
        rid, rdata = matched_region
        enemies = rdata["enemies"]
        
        text = (
            f"{rdata['emoji']} *{rdata['name']} — SLAYER ENEMIES*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Level Required: {rdata['level_req']}+\n\n"
        )
        
        bosses = [e for e in enemies if e.get("is_boss")]
        regular = [e for e in enemies if not e.get("is_boss")]
        
        if bosses:
            text += "*💀 BOSS ENEMIES:*\n"
            for boss in bosses:
                text += _format_enemy(boss, show_drops=True) + "\n\n"
        
        if regular:
            text += "*⚔️ REGULAR ENEMIES:*\n"
            for enemy in regular[:10]:  # Limit to 10
                text += _format_enemy(enemy) + "\n\n"
        
        if len(regular) > 10:
            text += f"_(+{len(regular)-10} more enemies)_\n"
        
        await update.message.reply_text(text, parse_mode="Markdown")
        return
    
    # Show all regions overview
    text = "🗡️ *SLAYER DEX — Enemy Locations*\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "_Slayer Corps members stationed across regions:_\n\n"
    
    for rid, rdata in slayer_regions.items():
        enemy_count = len(rdata["enemies"])
        boss_count = sum(1 for e in rdata["enemies"] if e.get("is_boss"))
        text += f"{rdata['emoji']} *{rdata['name']}* (Lv.{rdata['level_req']}+)\n"
        text += f"  └ {enemy_count} enemies ({boss_count} bosses)\n\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += "_Use `/slayerdex <region>` to see detailed enemy list_\n\n"
    text += "*Examples:*\n"
    text += "  `/slayerdex asakusa`\n"
    text += "  `/slayerdex butterfly`\n"
    text += "  `/slayerdex infinity`"
    
    await update.message.reply_text(text, parse_mode="Markdown")


async def demondex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/demondex — Show all Demon enemies by region."""
    args = context.args or []
    
    demon_regions = _get_region_enemies_by_faction("demon")
    
    if not demon_regions:
        await update.message.reply_text("❌ No Demon enemies found in any region.")
        return
    
    # If region specified
    if args:
        region_query = args[0].lower()
        matched_region = None
        
        for rid, rdata in demon_regions.items():
            if rid.lower() == region_query or rdata["name"].lower() == region_query.lower():
                matched_region = (rid, rdata)
                break
        
        if not matched_region:
            await update.message.reply_text(
                f"❌ Region *{args[0]}* not found.\n\n"
                f"Available regions:\n" +
                "\n".join([f"• {r['emoji']} {r['name']}" for r in demon_regions.values()]),
                parse_mode="Markdown"
            )
            return
        
        rid, rdata = matched_region
        enemies = rdata["enemies"]
        
        text = (
            f"{rdata['emoji']} *{rdata['name']} — DEMON ENEMIES*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Level Required: {rdata['level_req']}+\n\n"
        )
        
        bosses = [e for e in enemies if e.get("is_boss")]
        regular = [e for e in enemies if not e.get("is_boss")]
        
        if bosses:
            text += "*💀 BOSS DEMONS:*\n"
            for boss in bosses:
                text += _format_enemy(boss, show_drops=True) + "\n\n"
        
        if regular:
            text += "*👹 REGULAR DEMONS:*\n"
            for enemy in regular[:10]:  # Limit to 10
                text += _format_enemy(enemy) + "\n\n"
        
        if len(regular) > 10:
            text += f"_(+{len(regular)-10} more demons)_\n"
        
        await update.message.reply_text(text, parse_mode="Markdown")
        return
    
    # Show all regions overview
    text = "👹 *DEMON DEX — Enemy Locations*\n"
    text += "━━━━━━━━━━━━━━━━━━━━━\n\n"
    text += "_Demons lurking across the lands:_\n\n"
    
    for rid, rdata in demon_regions.items():
        enemy_count = len(rdata["enemies"])
        boss_count = sum(1 for e in rdata["enemies"] if e.get("is_boss"))
        text += f"{rdata['emoji']} *{rdata['name']}* (Lv.{rdata['level_req']}+)\n"
        text += f"  └ {enemy_count} demons ({boss_count} bosses)\n\n"
    
    text += "━━━━━━━━━━━━━━━━━━━━━\n"
    text += "_Use `/demondex <region>` to see detailed demon list_\n\n"
    text += "*Examples:*\n"
    text += "  `/demondex asakusa`\n"
    text += "  `/demondex yoshiwara`\n"
    text += "  `/demondex infinity`"
    
    await update.message.reply_text(text, parse_mode="Markdown")
