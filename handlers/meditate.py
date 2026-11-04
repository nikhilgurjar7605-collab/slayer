"""
🧘 Meditation System — Core Game Loop for training Potential
Allows players to gain Potential via 3 distinct focus strategies,
and ascend/awaken to next Potential Tiers for permanent max stats boosts.
"""
import random
import logging
import asyncio
import time
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

def _stamina_display(player: dict) -> str:
    """Compact stamina bar and automatic recovery countdown."""
    current = max(0, int(player.get("sta", 0) or 0))
    maximum = max(1, int(player.get("max_sta", current) or current))
    ratio = min(1.0, current / maximum)
    filled = min(10, int(ratio * 10))
    bar = "🟩" * filled + "⬜" * (10 - filled)
    lines = [f"🔋 *Stamina:* {current:,}/{maximum:,}", f"{bar}  *{int(ratio * 100)}%*"]
    recovery_at = player.get("sta_recovery_at")
    if current <= 0 and recovery_at:
        remaining = max(0, int((recovery_at - datetime.utcnow()).total_seconds()))
        hours, rem = divmod(remaining, 3600)
        minutes, seconds = divmod(rem, 60)
        lines.append(f"⏳ *Full recovery in:* {hours}h {minutes}m {seconds}s")
    elif current <= 0:
        lines.append("⏳ *Full recovery:* within 1 hour")
    else:
        lines.append("🌿 Stamina fully restores 1 hour after exhaustion.")
    return "\n".join(lines)


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

    potential = max(0, min(100, int(player.get("potential", 0) or 0)))
    tier = max(0, int(player.get("potential_tier", 0) or 0))
    tier_label = f"\n🏆 Rank: *{_get_tier_title(tier)}*" if tier > 0 else ""

    # Prevent a second command from overwriting an active reaction challenge.
    pending = col("meditate_pending").find_one({"user_id": user_id})
    if pending:
        age = time.time() - float(pending.get("created_at", 0) or 0)
        if age <= 90:
            note = ("Your reaction button is waiting. Tap it within 2.5 seconds." if "react_start" in pending else "Your breathing session is being prepared. Wait for the reaction button.")
            await update.message.reply_text("🧘 *Meditation already in progress*\n\n" + note, parse_mode="Markdown")
            return
        col("meditate_pending").delete_one({"user_id": user_id, "created_at": pending.get("created_at")})
        if "react_start" not in pending:
            refund = max(0, int(pending.get("sta_cost", 0) or 0))
            current_sta = int(player.get("sta", 0) or 0)
            max_sta = int(player.get("max_sta", current_sta) or current_sta)
            update_player(user_id, sta=min(max_sta, current_sta + refund))
            col("cooldowns").delete_one({"user_id": user_id, "type": "meditate"})

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

    # Three distinct training paths with different risk/reward profiles.
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🌊 WATERFALL · Steady control · 20 STA", callback_data="meditate_breath")],
        [InlineKeyboardButton("⚡ THUNDER · Reflex trial · 20 STA", callback_data="meditate_mind")],
        [InlineKeyboardButton("🔥 FLAME · High intensity · 40 STA", callback_data="meditate_spirit")]
    ])

    remaining = max(0, 100 - potential)
    filled = min(10, potential // 10)
    progress = "🟩" * filled + "⬜" * (10 - filled)
    combo = int(player.get("meditation_combo", 0) or 0)
    perfects = int(player.get("meditation_perfects", 0) or 0)
    await update.message.reply_text(
        f"╭── 🧘 *TOTAL CONCENTRATION TRIAL* ──╮\n"
        f"│\n"
        f"│ 🔮 *Potential:* {potential}% / 100%\n"
        f"│ {progress}\n"
        f"│ 🎯 *Awakening:* {remaining}% to go\n"
        f"│ 🏆 *Current tier:* {_get_tier_title(tier) if tier else 'Unawakened'}\n"
        f"│ ⚡ *Perfect-form combo:* {combo}  ·  🌟 *Perfect trials:* {perfects}\n"
        f"│\n"
        f"├─ 🔋 *BODY CONDITION* ──────────────┤\n"
        f"│ {_stamina_display(player).replace(chr(10), chr(10) + '│ ')}\n"
        f"│\n"
        f"├─ 🥋 *CHOOSE YOUR TRAINING PATH* ───┤\n"
        f"│ 🌊 Waterfall: reliable gains, balanced cost\n"
        f"│ ⚡ Thunder: risky focus test, bonus for speed\n"
        f"│ 🔥 Flame: biggest potential gains, heavy cost\n"
        f"│\n"
        f"│ Every trial can trigger a rare spiritual event.\n"
        f"╰────────────────────────────────────╯",
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

    # A random spiritual event changes the reward or difficulty of this trial.
    event = random.choices(
        [
            {"name": "🌟 SPIRIT SURGE", "description": "A wave of energy empowers your next form.", "kind": "potential", "bonus": 3, "window": 2.5},
            {"name": "🌿 CALMING CURRENT", "description": "A gentle current will restore 5 stamina after the trial.", "kind": "stamina", "bonus": 5, "window": 2.5},
            {"name": "📜 ANCIENT MEMORY", "description": "A forgotten master shares a fragment of wisdom.", "kind": "xp", "bonus": 75, "window": 2.5},
            {"name": "👁️ DEMON'S WHISPER", "description": "A hostile voice tests your reflexes; perfect timing grants extra potential.", "kind": "reflex", "bonus": 4, "window": 1.8},
        ],
        weights=[30, 30, 25, 15],
        k=1
    )[0]

    # Store pending reaction data in database.
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
            "event_name": event["name"],
            "event_description": event["description"],
            "event_kind": event["kind"],
            "event_bonus": event["bonus"],
            "reaction_window": event["window"],
        }},
        upsert=True
    )

    # Trial intro.
    await query.edit_message_text(
        f"╭── 🧘 *{strategy_name.upper()} TRIAL* ──╮\n"
        f"│\n"
        f"│ _{event['description']}_\n"
        f"│\n"
        f"│ 🎴 *Encounter:* {event['name']}\n"
        f"│\n"
        f"│ > _Slow your heartbeat. Feel the rhythm._\n"
        f"│ > _The signal can appear at any moment..._\n"
        f"│\n"
        f"╰────────────────────────────────╯",
        parse_mode="Markdown"
    )

    # Wait random delay before showing the react button
    delay = random.uniform(1.5, 3.5)
    await asyncio.sleep(delay)

    # Show react button
    react_time_now = time.time()
    armed = col("meditate_pending").update_one(
        {"user_id": user_id, "created_at": react_time},
        {"$set": {"react_start": react_time_now}}
    )
    if not armed.modified_count:
        return

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("⚡ RELEASE YOUR BREATH!", callback_data="meditate_react")
    ]])

    try:
        await query.edit_message_text(
            f"╭── ⚡ *SIGNAL DETECTED* ──╮\n"
            f"│\n"
            f"│ 🎴 *{event['name']}*\n"
            f"│ _{event['description']}_\n"
            f"│\n"
            f"│ 🫁 The moment is here. Release your breath!\n"
            f"│ ⚡ Tap fast for a *PERFECT FORM* bonus.\n"
            f"╰────────────────────────────╯",
            parse_mode="Markdown",
            reply_markup=keyboard
        )
    except:
        pass  # ignore if message is outdated or user clicked something else
    return
async def meditate_react_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes the reaction game result."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    player = get_player(user_id)
    if not player:
        return

    # Atomically claim the session so rapid/double taps cannot grant rewards twice.
    pending = col("meditate_pending").find_one_and_delete({
        "user_id": user_id,
        "react_start": {"$exists": True},
    })
    if not pending:
        await query.edit_message_text("❌ This meditation session has expired or was already claimed. Use /meditate to try again.")
        return

    react_time_now = time.time()
    react_start = float(pending["react_start"])
    reaction_duration = max(0.0, react_time_now - react_start)

    fail_chance = float(pending.get("fail_chance", 0) or 0)
    min_gain = int(pending.get("min_gain", 0) or 0)
    max_gain = int(pending.get("max_gain", 0) or 0)
    xp_gain = int(pending.get("xp_gain", 0) or 0)
    sta_cost = int(pending.get("sta_cost", 0) or 0)
    strategy_name = pending.get("strategy_name", "Concentration")
    potential = int(pending.get("potential", 0) or 0)
    event_name = pending.get("event_name", "🌿 QUIET MIND")
    event_kind = pending.get("event_kind", "none")
    event_bonus = int(pending.get("event_bonus", 0) or 0)
    reaction_window = float(pending.get("reaction_window", 2.5) or 2.5)

    # Grade the player's timing instead of treating every successful tap equally.
    success = random.random() >= fail_chance
    grade = "MISS"
    bonus_gain = 0
    stamina_refund = 0
    bonus_xp = 0

    if reaction_duration > reaction_window:
        success = False
        outcome_text = f"❌ *MISSED THE MOMENT* ({reaction_duration:.2f}s)\n│ > Your breathing rhythm broke before the signal."
        gain = 0
    elif not success:
        outcome_text = f"🫥 *FOCUS BROKEN* ({reaction_duration:.2f}s)\n│ > You reacted, but your concentration slipped."
        gain = 0
    else:
        if reaction_duration <= 0.70:
            grade = "PERFECT"
            gain = random.randint(min_gain, max_gain)
            bonus_gain = 2
            outcome_text = f"🌟 *PERFECT FORM!* ({reaction_duration:.2f}s)\n│ > Your body moved as one. Bonus potential unlocked!"
        elif reaction_duration <= 1.45:
            grade = "GOOD"
            gain = random.randint(min_gain, max_gain)
            outcome_text = f"✨ *GOOD FORM!* ({reaction_duration:.2f}s)\n│ > A clean, controlled breath. Your training paid off."
        else:
            grade = "LATE"
            gain = max(1, random.randint(min_gain, max_gain) // 2)
            outcome_text = f"🌫️ *LATE FORM* ({reaction_duration:.2f}s)\n│ > You caught the rhythm late, but salvaged part of the training."

    if success and event_kind == "potential":
        bonus_gain += event_bonus
    elif success and event_kind == "reflex" and grade == "PERFECT":
        bonus_gain += event_bonus
    elif success and event_kind == "stamina":
        stamina_refund = event_bonus
    elif success and event_kind == "xp":
        bonus_xp = event_bonus

    # Consecutive perfect forms build a small capped combo bonus.
    old_combo = int(player.get("meditation_combo", 0) or 0)
    combo = min(5, old_combo + 1) if grade == "PERFECT" else 0
    combo_bonus = min(3, max(0, combo - 1))
    if grade == "PERFECT":
        bonus_gain += combo_bonus
    perfects = int(player.get("meditation_perfects", 0) or 0) + (1 if grade == "PERFECT" else 0)

    gain += bonus_gain
    xp_total = xp_gain + bonus_xp
    new_potential = min(100, potential + gain)
    new_sta = min(int(player.get("max_sta", 0) or 0), int(player.get("sta", 0) or 0) + stamina_refund)
    
    # Progress bar calculation
    filled_blocks = int(new_potential // 10)
    empty_blocks = 10 - filled_blocks
    progress_bar = ("🟩" * filled_blocks) + ("⬜" * empty_blocks)

    # Save player updates
    update_player(
        user_id,
        potential=new_potential,
        xp=int(player.get("xp", 0) or 0) + xp_total,
        meditation_combo=combo,
        meditation_perfects=perfects,
        **({"sta": new_sta} if stamina_refund else {})
    )

    # Final response
    tier = player.get("potential_tier", 0)
    tier_label = f"\n│ 🏆 Rank: *{_get_tier_title(tier)}*" if tier > 0 else ""

    status_msg = (f"│ ✨ *AWAKENING READY!* Use /meditate to ascend." if new_potential >= 100
                  else f"│ ⏳ Next trial unlocks in 1 hour.")

    grade_emoji = {"PERFECT": "🌟", "GOOD": "✨", "LATE": "🌫️", "MISS": "❌"}.get(grade, "❔")
    event_result = f"🎴 *Event:* {event_name}\n"
    reward_lines = [
        f"│ ⭐ XP: *+{xp_total}*",
        f"│ 🔋 Stamina used: *-{sta_cost} STA*" + (f"  ·  Refunded: *+{stamina_refund}*" if stamina_refund else ""),
        f"│ 🔮 Potential: *+{gain}%*" + (f"  (includes +{bonus_gain}% bonus)" if bonus_gain else ""),
        f"│ 🏅 Form grade: {grade_emoji} *{grade}*",
        f"│ 🔥 Perfect combo: *{combo}*",
    ]

    await query.edit_message_text(
        f"╭── 🧘 *TRIAL COMPLETE* ──╮\n"
        f"│\n"
        f"│ {event_result}"
        f"│ > {outcome_text}\n"
        f"│\n"
        f"├─ 🎁 *TRIAL REWARDS* ──────────────┤\n"
        + "\n".join(reward_lines) + "\n"
        f"│\n"
        f"├─ 🔮 *AWAKENING PROGRESS* ─────────┤\n"
        f"│ {progress_bar} *{new_potential}%* / 100%{tier_label}\n"
        f"│\n"
        f"{status_msg}\n"
        f"╰──────────────────────────────────╯",
        parse_mode="Markdown"
    )
