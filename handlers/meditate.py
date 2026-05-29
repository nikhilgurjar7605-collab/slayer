"""
🧘 Meditation System — Core Game Loop for training Potential
Allows players to gain Potential via 3 distinct focus strategies,
and ascend/awaken to next Potential Tiers for permanent max stats boosts.
"""
import random
import logging
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import col, get_player, update_player
from utils.helpers import get_level

log = logging.getLogger(__name__)

COOLDOWN_SECONDS = 3600  # 1 hour

def _get_meditate_cooldown(user_id: int) -> datetime | None:
    doc = col("cooldowns").find_one({"user_id": user_id, "type": "meditate"})
    if doc:
        return doc.get("expire_at")
    return None

def _set_meditate_cooldown(user_id: int):
    expire = datetime.utcnow() + timedelta(seconds=COOLDOWN_SECONDS)
    col("cooldowns").update_one(
        {"user_id": user_id, "type": "meditate"},
        {"$set": {"expire_at": expire}},
        upsert=True
    )

def _get_tier_title(tier: int) -> str:
    titles = {
        1: "🌟 Tier I (Awakened)",
        2: "✨ Tier II (Ascended)",
        3: "💎 Tier III (Transcended)",
        4: "🌌 Tier IV (Demi-God)",
        5: "👑 Tier V (Supreme Sovereign)",
    }
    return titles.get(tier, f"🔥 Tier {tier}")

async def meditate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main /meditate command entry point."""
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    potential = player.get("potential", 0)
    tier = player.get("potential_tier", 0)
    tier_label = f"\n🏆 Rank: *{_get_tier_title(tier)}*" if tier > 0 else ""

    # If potential is already 100%, offer limit break instantly
    if potential >= 100:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔮 SHATTER LIMITS / AWAKEN", callback_data="meditate_awaken")
        ]])
        await update.message.reply_text(
            f"🧘 *TOTAL CONCENTRATION BREATHING*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔮 Your potential has reached its peak (*100%*)!{tier_label}\n\n"
            f"You stand at the edge of physical limitations. Unleash your inner spirit and break your boundaries to ascend to the next tier!\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ Permanent rewards upon Ascension:\n"
            f"• ❤️ Max HP:  *+15 permanently*\n"
            f"• 🌀 Max Stamina: *+10 permanently*\n"
            f"• 💪 Passive combat bonus: *+5% DMG, +3% Def (stacked)*",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
        return

    # Check cooldown
    expire = _get_meditate_cooldown(user_id)
    if expire:
        diff = expire - datetime.utcnow()
        if diff.total_seconds() > 0:
            mins = int(diff.total_seconds() // 60)
            secs = int(diff.total_seconds() % 60)
            await update.message.reply_text(
                f"⏳ *MEDITATION RECOVERY*\n\n"
                f"Your spiritual energy is recovering from your last training session.\n\n"
                f"⌚ Next session available in:  *{mins}m {secs}s*",
                parse_mode="Markdown"
            )
            return

    # Build focus selection panel
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌬️ Focus Breath (20 STA)", callback_data="meditate_breath")],
        [InlineKeyboardButton("🌊 Clear Mind (20 STA)", callback_data="meditate_mind")],
        [InlineKeyboardButton("🔥 Ignite Spirit (40 STA)", callback_data="meditate_spirit")]
    ])

    await update.message.reply_text(
        f"🧘 *TOTAL CONCENTRATION MEDITATION*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Sit beneath a freezing waterfall, close your eyes, and focus your breathing. Expanding your potential unlocks permanent stat boosts!\n\n"
        f"🔋 Stamina: *{player['sta']}/{player['max_sta']}*\n"
        f"🔮 Current Potential: *{potential}%* {tier_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👉 *Choose your Focus Strategy:*",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def meditate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes focus strategy buttons."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)
    if not player:
        await query.edit_message_text("❌ No character found.")
        return

    action = query.data
    potential = player.get("potential", 0)

    # 1. Limit break Ascension action
    if action == "meditate_awaken":
        if potential < 100:
            await query.edit_message_text("❌ You haven't reached 100% potential yet!")
            return
        
        new_tier = player.get("potential_tier", 0) + 1
        new_max_hp = player["max_hp"] + 15
        new_max_sta = player["max_sta"] + 10
        update_player(
            user_id,
            potential=0,
            potential_tier=new_tier,
            max_hp=new_max_hp,
            max_sta=new_max_sta,
            hp=new_max_hp,
            sta=new_max_sta
        )
        
        await query.edit_message_text(
            f"🎆 *LIMIT SHATTERED — AWAKENED!* 🎇\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"Your spirit surges with raw, unbridled energy! The barriers holding your breathing and technique back have dissolved!\n\n"
            f"🔮 Meditation Rank:  *{_get_tier_title(new_tier)}*\n"
            f"❤️ Permanent Max HP:   *+{new_max_hp - player['max_hp']}* ({new_max_hp} total)\n"
            f"🌀 Permanent Max Stamina: *+{new_max_sta - player['max_sta']}* ({new_max_sta} total)\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"_Your potential has been reset to 0%. Continue meditating to ascend to the next Tier!_",
            parse_mode="Markdown"
        )
        return

    # Check cooldown again for safety
    expire = _get_meditate_cooldown(user_id)
    if expire and (expire - datetime.utcnow()).total_seconds() > 0:
        await query.edit_message_text("⏳ Meditation cooldown is active. Try again later.")
        return

    # Determine focus costs and rewards
    if action == "meditate_breath":
        sta_cost = 20
        min_gain, max_gain = 3, 6
        xp_gain = 50
        strategy_name = "🌬️ Focus Breath"
        fail_chance = 0.0
    elif action == "meditate_mind":
        sta_cost = 20
        min_gain, max_gain = 2, 11
        xp_gain = 40
        strategy_name = "🌊 Clear Mind"
        fail_chance = 0.15
    elif action == "meditate_spirit":
        sta_cost = 40
        min_gain, max_gain = 7, 14
        xp_gain = 100
        strategy_name = "🔥 Ignite Spirit"
        fail_chance = 0.0
    else:
        return

    if player["sta"] < sta_cost:
        await query.edit_message_text(f"❌ Not enough Stamina! Meditating requires *{sta_cost} STA*.", parse_mode="Markdown")
        return

    # Set cooldown and deduct stamina instantly to avoid spam
    _set_meditate_cooldown(user_id)
    update_player(user_id, sta=max(0, player["sta"] - sta_cost))

    # Breath phase 1 (Animation)
    await query.edit_message_text(
        f"🧘 *{strategy_name.upper()} IN PROGRESS...*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⏳ `[ ░░░░░░░░░░░░ ]` Sit straight... focus breath...",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1.2)

    # Breath phase 2 (Animation)
    await query.edit_message_text(
        f"🧘 *{strategy_name.upper()} IN PROGRESS...*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ `[ ██████░░░░░░ ]` Inhaling freezing waterfall mist...",
        parse_mode="Markdown"
    )
    await asyncio.sleep(1.2)

    # Resolve gains
    success = random.random() >= fail_chance
    if not success:
        gain = 0
        outcome_text = "❌ *Failed Focus*: Your mind strayed to earthly thoughts under the waterfall. No potential was gained, but you cleared your head."
    else:
        gain = random.randint(min_gain, max_gain)
        outcome_text = f"🔮 *Success!* Your breathing pattern aligns. You gained *+{gain}%* Potential!"

    new_potential = min(100, potential + gain)
    
    # Save player updates
    update_player(
        user_id,
        potential=new_potential,
        xp=player["xp"] + xp_gain
    )

    # Final response
    tier = player.get("potential_tier", 0)
    tier_label = f"\n🏆 Rank: *{_get_tier_title(tier)}*" if tier > 0 else ""

    await query.edit_message_text(
        f"🧘 *MEDITATION COMPLETE* 🌿\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{outcome_text}\n"
        f"⭐ XP: *+{xp_gain}*\n"
        f"🔋 Stamina used: *-{sta_cost} STA*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔮 New Potential: *{new_potential}%* / 100%{tier_label}\n"
        f"\n"
        + (f"✨ *LIMIT BREAK READY!* Run /meditate again to Awaken!" if new_potential >= 100 else f"⌚ _Your spiritual body is exhausted. Cooldown active for 1 hour._"),
        parse_mode="Markdown"
    )
