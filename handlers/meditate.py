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

COOLDOWN_SECONDS = 3600 # 1 hour

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
        6: "☄️ Tier VI (Astral)",
        7: "🌀 Tier VII (Ethereal)",
        8: "🔥 Tier VIII (Infernal)",
        9: "❄️ Tier IX (Glacial)",
        10: "⚡ Tier X (Tempest)",
        11: "🌑 Tier XI (Abyssal)",
        12: "☀️ Tier XII (Radiant)",
        13: "👁️ Tier XIII (Omniscient)",
        14: "🦾 Tier XIV (Unbreakable)",
        15: "⛩️ Tier XV (Sage)",
        16: "🐉 Tier XVI (Dragon Spirit)",
        17: "🌌 Tier XVII (Cosmic Entity)",
        18: "⏳ Tier XVIII (Timeless)",
        19: "🌠 Tier XIX (Nova)",
        20: "♾️ Tier XX (Absolute Zenith)",
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
            f"╭── 🧘 *TOTAL CONCENTRATION BREATHING* ──╮\n"
            f"│\n"
            f"│ 🔮 Your potential has reached its peak (*100%*)!{tier_label}\n"
            f"│\n"
            f"│ > _You stand at the edge of physical limitations._\n"
            f"│ > _Unleash your inner spirit and break your_\n"
            f"│ > _boundaries to ascend to the next tier!_\n"
            f"│\n"
            f"├─ ⚡ *Permanent rewards upon Ascension:* ─┤\n"
            f"│ • ❤️ Max HP:       *+15*\n"
            f"│ • 🌀 Max Stamina:  *+10*\n"
            f"│ • 💪 STR:          *+2*\n"
            f"│ • ⚡ SPD:          *+1*\n"
            f"│ • 🛡️ DEF:          *+1*\n"
            f"│ • ⚔️ Combat DMG:   *+5% per tier (stacked)*\n"
            f"│ • 🔰 DMG Reduce:   *+3% per tier (stacked)*\n"
            f"╰────────────────────────────────────────╯",
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
        f"╭── 🧘 *TOTAL CONCENTRATION MEDITATION* ──╮\n"
        f"│\n"
        f"│ > _Sit beneath a freezing waterfall, close your eyes,_\n"
        f"│ > _and focus your breathing. Expanding your potential_\n"
        f"│ > _unlocks permanent stat boosts!_\n"
        f"│\n"
        f"│ 🔋 Stamina: *{player['sta']}/{player['max_sta']}*\n"
        f"│ 🔮 Current Potential: *{potential}%* {tier_label}\n"
        f"│\n"
        f"╰─ 👉 *Choose your Focus Strategy:* ───────╯",
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

        current_tier = player.get("potential_tier", 0)
        if current_tier >= 20:
            await query.edit_message_text("❌ You have already reached the absolute zenith of your potential! (Max Tier 20)")
            return

        new_tier = current_tier + 1

        # ── Permanent stat boosts on every awakening ──────────────────────
        HP_BOOST  = 15
        STA_BOOST = 10
        STR_BOOST = 2
        SPD_BOOST = 1
        DEF_BOOST = 1

        new_max_hp  = player["max_hp"]  + HP_BOOST
        new_max_sta = player["max_sta"] + STA_BOOST
        new_str     = player.get("str_stat", 22) + STR_BOOST
        new_spd     = player.get("spd",      20) + SPD_BOOST
        new_def     = player.get("def_stat", 18) + DEF_BOOST

        update_player(
            user_id,
            potential=0,
            potential_tier=new_tier,
            max_hp=new_max_hp,
            max_sta=new_max_sta,
            hp=new_max_hp,
            sta=new_max_sta,
            str_stat=new_str,
            spd=new_spd,
            def_stat=new_def,
        )

        await query.edit_message_text(
            f"╭── 🎆 *LIMIT SHATTERED — AWAKENED!* 🎇 ──╮\n"
            f"│\n"
            f"│ > _Your spirit surges with raw, unbridled energy!_\n"
            f"│ > _The barriers holding your breathing and_\n"
            f"│ > _technique back have dissolved!_\n"
            f"│\n"
            f"│ 🔮 Meditation Rank:  *{_get_tier_title(new_tier)}*\n"
            f"│\n"
            f"├─ 📈 *PERMANENT STAT GAINS:* ─────────────┤\n"
            f"│ ❤️  Max HP:       *+{HP_BOOST}*  →  {new_max_hp}\n"
            f"│ 🌀  Max Stamina:  *+{STA_BOOST}*  →  {new_max_sta}\n"
            f"│ 💪  STR:          *+{STR_BOOST}*  →  {new_str}\n"
            f"│ ⚡  SPD:          *+{SPD_BOOST}*  →  {new_spd}\n"
            f"│ 🛡️  DEF:          *+{DEF_BOOST}*  →  {new_def}\n"
            f"│ ⚔️  DMG Bonus:    *+{new_tier * 5}%* (stacked)\n"
            f"│ 🔰  DMG Reduce:   *+{new_tier * 3}%* (stacked)\n"
            f"│\n"
            f"╰─ _Potential reset to 0%._ ───────────────╯",
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

    # Generate reaction timestamp and button
    import time
    react_time = time.time()

    # Store pending reaction data in database
    col("meditate_pending").update_one(
        {"user_id": user_id},
        {"$set": {
            "action": action,
            "fail_chance": fail_chance,
            "min_gain": min_gain,
            "max_gain": max_gain,
            "xp_gain": xp_gain,
            "sta_cost": sta_cost,
            "strategy_name": strategy_name,
            "created_at": react_time,
            "potential": potential,
        }},
        upsert=True
    )

    # Initial animation
    await query.edit_message_text(
        f"╭── 🧘 *{strategy_name.upper()}* ──╮\n"
        f"│\n"
        f"│ > _Gathering spiritual energy..._\n"
        f"│\n"
        f"│ ⏳ Get ready to react!\n"
        f"│\n"
        f"╰────────────────────────────╯",
        parse_mode="Markdown"
    )

    # Wait random delay before showing the react button
    delay = random.uniform(1.5, 3.5)
    await asyncio.sleep(delay)

    # Show react button
    react_time_now = time.time()
    col("meditate_pending").update_one(
        {"user_id": user_id},
        {"$set": {"react_start": react_time_now}}
    )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚡ REACT NOW!", callback_data="meditate_react")
    ]])

    try:
        await query.edit_message_text(
            f"╭── 🧘 *{strategy_name.upper()}* ──╮\n"
            f"│\n"
            f"│ > _The spiritual energy peaks!_\n"
            f"│\n"
            f"│ ⚡ *CLICK THE BUTTON QUICKLY!*\n"
            f"│\n"
            f"╰────────────────────────────╯",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    except:
        pass  # ignore if message is outdated or user clicked something else
    return

    tier_label = f"\n│ 🏆 Rank: *{_get_tier_title(tier)}*" if tier > 0 else ""

    status_msg = (f"│ ✨ *LIMIT BREAK READY!* Run /meditate again to Awaken!" if new_potential >= 100
                  else f"│ ⌚ _Your spiritual body is exhausted. Cooldown active for 1 hour._")

    await query.edit_message_text(
        f"╭── 🧘 *MEDITATION COMPLETE* 🌿 ──╮\n"
        f"│\n"
        f"│ > {outcome_text}\n"
        f"│\n"
        f"├─ 📈 *REWARDS:* ─────────────────┤\n"
        f"│ ⭐ XP: *+{xp_gain}*\n"
        f"│ 🔋 Stamina used: *-{sta_cost} STA*\n"
        f"│\n"
        f"├─ 🔮 *POTENTIAL:* ───────────────┤\n"
        f"│ {progress_bar} *{new_potential}%* / 100%{tier_label}\n"
        f"│\n"
        f"{status_msg}\n"
        f"╰─────────────────────────────────╯",
        parse_mode="Markdown"
    )

async def meditate_react_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes the reaction game result."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    player = get_player(user_id)
    if not player:
        return

    pending = col("meditate_pending").find_one({"user_id": user_id})
    if not pending or "react_start" not in pending:
        await query.edit_message_text("❌ Meditation session expired or invalid.")
        return

    import time
    react_time_now = time.time()
    react_start = pending["react_start"]
    reaction_duration = react_time_now - react_start

    # Remove pending session
    col("meditate_pending").delete_one({"user_id": user_id})

    fail_chance = pending["fail_chance"]
    min_gain = pending["min_gain"]
    max_gain = pending["max_gain"]
    xp_gain = pending["xp_gain"]
    sta_cost = pending["sta_cost"]
    strategy_name = pending["strategy_name"]
    potential = pending["potential"]

    # Base failure based on strategy risk
    success = random.random() >= fail_chance

    # Reaction time check (e.g. must react within 2.5 seconds)
    max_reaction_time = 2.5
    if reaction_duration > max_reaction_time:
        success = False
        outcome_text = f"❌ *Too Slow!* ({reaction_duration:.2f}s)\\nYour mind strayed to earthly thoughts. No potential was gained."
        gain = 0
    elif not success:
        outcome_text = f"❌ *Failed Focus* ({reaction_duration:.2f}s)\\nYou reacted in time, but your breathing was flawed. No potential was gained."
        gain = 0
    else:
        gain = random.randint(min_gain, max_gain)
        outcome_text = f"🔮 *Perfect Form!* ({reaction_duration:.2f}s)\\nYour breathing pattern aligns perfectly. You gained *+{gain}%* Potential!"

    new_potential = min(100, potential + gain)
    
    # Progress bar calculation
    filled_blocks = int(new_potential // 10)
    empty_blocks = 10 - filled_blocks
    progress_bar = ("🟩" * filled_blocks) + ("⬜" * empty_blocks)

    # Save player updates
    update_player(
        user_id,
        potential=new_potential,
        xp=player["xp"] + xp_gain
    )

    # Final response
    tier = player.get("potential_tier", 0)
    tier_label = f"\\n│ 🏆 Rank: *{_get_tier_title(tier)}*" if tier > 0 else ""

    status_msg = (f"│ ✨ *LIMIT BREAK READY!* Run /meditate again to Awaken!" if new_potential >= 100
                  else f"│ ⌚ _Your spiritual body is exhausted. Cooldown active for 1 hour._")

    await query.edit_message_text(
        f"╭── 🧘 *{strategy_name.upper()} COMPLETE* 🌿 ──╮\\n"
        f"│\\n"
        f"│ > {outcome_text}\\n"
        f"│\\n"
        f"├─ 📈 *REWARDS:* ─────────────────┤\\n"
        f"│ ⭐ XP: *+{xp_gain}*\\n"
        f"│ 🔋 Stamina used: *-{sta_cost} STA*\\n"
        f"│\\n"
        f"├─ 🔮 *POTENTIAL:* ───────────────┤\\n"
        f"│ {progress_bar} *{new_potential}%* / 100%{tier_label}\\n"
        f"│\\n"
        f"{status_msg}\\n"
        f"╰─────────────────────────────────╯",
        parse_mode="Markdown"
    )
