"""
Faction-aware cultivation system.
Slayers train Total Concentration; demons cultivate Blood Power.
Sessions are three-stage choice adventures — no reaction timers or timing grades.
"""
import random
import logging
import time
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import col, get_player, update_player

log = logging.getLogger(__name__)
COOLDOWN_SECONDS = 3600
SESSION_TIMEOUT = 180

SLAYER_PATHS = {
    "water": {"name": "🌊 Waterfall Discipline", "cost": 20, "desc": "A steady path focused on control and endurance."},
    "thunder": {"name": "⚡ Thunder Focus", "cost": 20, "desc": "A demanding path that rewards bold decisions."},
    "flame": {"name": "🔥 Flame Resolve", "cost": 35, "desc": "An intense path with the highest potential gains."},
}
DEMON_PATHS = {
    "devour": {"name": "🩸 Blood Devour", "cost": 20, "desc": "Consume corrupted essence to strengthen your body."},
    "shadow": {"name": "🌑 Shadow Cultivation", "cost": 20, "desc": "Hone speed, concealment and predatory instinct."},
    "art": {"name": "🔴 Blood Art Evolution", "cost": 35, "desc": "Feed your Blood Demon Art and evolve its power."},
}

SLAYER_SCENES = [
    ("🌊 THE FALLING WATER", "A violent waterfall crashes around you. Your breathing begins to lose rhythm.",
     [("🧘 Stay calm", 3, 35), ("🌊 Follow the current", 5, 20), ("🔥 Push through the pressure", 7, 10)]),
    ("🌲 THE SILENT FOREST", "A demon's presence lurks between the trees. You must keep your senses sharp.",
     [("👂 Listen carefully", 5, 25), ("⚔️ Take a guarded stance", 4, 30), ("💨 Move without hesitation", 6, 15)]),
    ("⛰️ THE FINAL ASCENT", "Your legs tremble. One final climb stands between you and clarity.",
     [("🫁 Regulate your breathing", 4, 30), ("🪨 Advance steadily", 5, 25), ("☀️ Unleash everything", 7, 10)]),
]
DEMON_SCENES = [
    ("🩸 THE BLOOD ALTAR", "An ancient blood source pulses. Its power could strengthen you — or overwhelm you.",
     [("🩸 Absorb a measured amount", 5, 25), ("☠️ Consume the entire offering", 7, 10), ("👁️ Study its essence first", 4, 30)]),
    ("🌑 THE HUNTING SHADOW", "A powerful presence stalks your territory. Your instincts demand action.",
     [("🐺 Track it patiently", 5, 25), ("🌑 Disappear into the dark", 6, 20), ("💥 Challenge it directly", 7, 10)]),
    ("🔴 THE BLOOD ART TRIAL", "Your Blood Demon Art strains against its limits. You feel an evolution trying to emerge.",
     [("🧬 Refine its control", 5, 30), ("🩸 Feed it more blood", 7, 10), ("🔮 Explore a new mutation", 6, 20)]),
]

def _cooldown(user_id):
    doc = col("cooldowns").find_one({"user_id": user_id, "type": "meditate"})
    return doc.get("expire_at") if doc else None

def _set_cooldown(user_id):
    col("cooldowns").update_one(
        {"user_id": user_id, "type": "meditate"},
        {"$set": {"expire_at": datetime.utcnow() + timedelta(seconds=COOLDOWN_SECONDS)}},
        upsert=True,
    )

def _tier_title(tier):
    names = ["Unawakened", "Awakened", "Ascended", "Transcended", "Demi-God",
             "Supreme Sovereign", "Astral", "Ethereal", "Infernal", "Glacial",
             "Tempest", "Abyssal", "Radiant", "Omniscient", "Unbreakable",
             "Sage", "Dragon Spirit", "Cosmic Entity", "Timeless", "Nova", "Absolute Zenith"]
    return names[min(max(0, int(tier or 0)), 20)]

def _bar(value):
    filled = min(10, max(0, int(value) // 10))
    return "🟩" * filled + "⬜" * (10 - filled)

def _stamina_text(player):
    sta = max(0, int(player.get("sta", 0) or 0))
    maximum = max(1, int(player.get("max_sta", sta) or sta))
    lines = [f"🔋 Stamina: *{sta:,}/{maximum:,}*", f"{_bar(int(sta / maximum * 100))}"]
    recovery = player.get("sta_recovery_at")
    if sta <= 0 and recovery:
        if recovery.tzinfo is not None:
            recovery = recovery.replace(tzinfo=None)
        left = max(0, int((recovery - datetime.utcnow()).total_seconds()))
        lines.append(f"⏳ Recovery: *{left // 60}m {left % 60}s*")
    elif sta <= 0:
        lines.append("⏳ Stamina recovers automatically after exhaustion.")
    return "\n".join(lines)

def _path_keyboard(faction):
    paths = DEMON_PATHS if faction == "demon" else SLAYER_PATHS
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{p['name']} · {p['cost']} STA", callback_data=f"meditate_path_{key}")]
        for key, p in paths.items()
    ])

def _scene_for(faction):
    return random.choice(DEMON_SCENES if faction == "demon" else SLAYER_SCENES)

async def meditate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start first.")
        return

    faction = str(player.get("faction", "slayer")).lower()
    is_demon = faction == "demon"
    potential = max(0, min(100, int(player.get("potential", 0) or 0)))
    tier = int(player.get("potential_tier", 0) or 0)

    pending = col("meditate_pending").find_one({"user_id": user_id})
    if pending:
        age = time.time() - float(pending.get("created_at", 0) or 0)
        if age < SESSION_TIMEOUT:
            await update.message.reply_text("⏳ Your cultivation journey is already in progress. Finish the choices in the active session.")
            return
        col("meditate_pending").delete_one({"user_id": user_id})
        refund = int(pending.get("sta_cost", 0) or 0)
        if refund:
            update_player(user_id, sta=min(int(player.get("max_sta", 0) or 0), int(player.get("sta", 0) or 0) + refund))
        col("cooldowns").delete_one({"user_id": user_id, "type": "meditate"})

    if potential >= 100:
        title = "☠️ DEMON EVOLUTION" if is_demon else "☀️ TOTAL CONCENTRATION AWAKENING"
        button = "🩸 EVOLVE DEMON FORM" if is_demon else "🔮 AWAKEN NEXT TIER"
        await update.message.reply_text(
            f"*{title}*\n\nYour cultivation has reached *100%*.\n"
            f"Current tier: *{_tier_title(tier)}*\n\n"
            "Break through your current limits and claim permanent growth.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(button, callback_data="meditate_awaken")]]),
        )
        return

    expire = _cooldown(user_id)
    if expire:
        if expire.tzinfo is not None:
            expire = expire.replace(tzinfo=None)
        seconds = int((expire - datetime.utcnow()).total_seconds())
        if seconds > 0:
            await update.message.reply_text(
                f"⏳ Your energy is recovering. Next cultivation in *{seconds // 60}m {seconds % 60}s*.",
                parse_mode="Markdown",
            )
            return

    if is_demon:
        heading = "☠️ BLOOD CULTIVATION"
        intro = "Strengthen your demonic body, sharpen your instincts and evolve your Blood Demon Art."
        progress_name = "Blood Potential"
        stats = f"🩸 Demon level: *{player.get('demon_level', 1)}*"
    else:
        heading = "🧘 TOTAL CONCENTRATION"
        intro = "Train your breathing, discipline your body and push beyond your human limits."
        progress_name = "Breathing Potential"
        stats = f"🥋 Breathing style: *{player.get('style') or 'Unassigned'}*"

    await update.message.reply_text(
        f"*{heading}*\n\n{intro}\n\n"
        f"🔮 *{progress_name}:* {potential}% / 100%\n{_bar(potential)}\n"
        f"🏆 *Cultivation tier:* {_tier_title(tier)}\n{stats}\n\n"
        f"{_stamina_text(player)}\n\n"
        "Choose your cultivation path. Each session contains three story choices.",
        parse_mode="Markdown",
        reply_markup=_path_keyboard(faction),
    )

async def meditate_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)
    if not player:
        await query.edit_message_text("❌ No character found.")
        return

    faction = str(player.get("faction", "slayer")).lower()
    is_demon = faction == "demon"
    action = query.data
    potential = max(0, min(100, int(player.get("potential", 0) or 0)))

    if action == "meditate_awaken":
        if potential < 100:
            await query.edit_message_text("❌ You need 100% potential before ascending.")
            return
        tier = int(player.get("potential_tier", 0) or 0)
        if tier >= 20:
            await query.edit_message_text("♾️ You have reached the maximum cultivation tier.")
            return
        new_tier = tier + 1
        hp_boost, sta_boost, str_boost, spd_boost, def_boost = 15, 10, 2, 1, 1
        new_max_hp = int(player.get("max_hp", 240) or 240) + hp_boost
        new_max_sta = int(player.get("max_sta", 170) or 170) + sta_boost
        new_str = int(player.get("str_stat", 22) or 22) + str_boost
        new_spd = int(player.get("spd", 20) or 20) + spd_boost
        new_def = int(player.get("def_stat", 18) or 18) + def_boost
        updates = {
            "potential": 0, "potential_tier": new_tier,
            "max_hp": new_max_hp, "max_sta": new_max_sta,
            "hp": new_max_hp, "sta": new_max_sta,
            "str_stat": new_str, "spd": new_spd, "def_stat": new_def,
        }
        if is_demon:
            updates["demon_evolution_tier"] = int(player.get("demon_evolution_tier", 0) or 0) + 1
        update_player(user_id, **updates)
        label = "☠️ DEMON FORM EVOLVED" if is_demon else "☀️ BREATHING AWAKENED"
        path_label = "Blood Cultivation" if is_demon else "Total Concentration"
        await query.edit_message_text(
            f"*{label}*\n\n"
            f"Your {path_label} has broken through to *Tier {new_tier}: {_tier_title(new_tier)}*.\n\n"
            f"❤️ Max HP: +{hp_boost} → {new_max_hp}\n"
            f"🔋 Max Stamina: +{sta_boost} → {new_max_sta}\n"
            f"💪 STR: +{str_boost} · ⚡ SPD: +{spd_boost} · 🛡️ DEF: +{def_boost}\n\n"
            "Your potential has reset to 0%.",
            parse_mode="Markdown",
        )
        return

    if action.startswith("meditate_path_"):
        expire = _cooldown(user_id)
        if expire:
            if expire.tzinfo is not None:
                expire = expire.replace(tzinfo=None)
            if (expire - datetime.utcnow()).total_seconds() > 0:
                await query.edit_message_text("⏳ Cultivation cooldown is active.")
                return

        path_key = action.removeprefix("meditate_path_")
        paths = DEMON_PATHS if is_demon else SLAYER_PATHS
        path = paths.get(path_key)
        if not path:
            await query.edit_message_text("❌ That path does not belong to your faction.")
            return
        if int(player.get("sta", 0) or 0) < path["cost"]:
            await query.edit_message_text(f"❌ You need {path['cost']} stamina for this path.")
            return
        scene = _scene_for(faction)
        created = time.time()
        update_player(user_id, sta=max(0, int(player.get("sta", 0) or 0) - path["cost"]))
        _set_cooldown(user_id)
        col("meditate_pending").update_one(
            {"user_id": user_id},
            {"$set": {
                "faction": faction, "path": path_key, "path_name": path["name"],
                "sta_cost": path["cost"], "created_at": created,
                "scene_index": 0, "score": 0, "xp_bonus": 0,
                "scene_title": scene[0], "scene_text": scene[1], "scene_options": scene[2],
            }},
            upsert=True,
        )
        options = scene[2]
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(label, callback_data=f"meditate_choice_0_{i}")]
            for i, (label, _, _) in enumerate(options)
        ])
        await query.edit_message_text(
            f"*{path['name']}*\n_{path['desc']}_\n\n"
            f"*{scene[0]}*\n{scene[1]}\n\n"
            "*Stage 1 of 3 — Choose your approach:*",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
        return

    if action.startswith("meditate_choice_"):
        pending = col("meditate_pending").find_one({"user_id": user_id})
        if not pending:
            await query.edit_message_text("⌛ This cultivation session has expired. Use /meditate to begin again.")
            return
        if pending.get("faction") != faction:
            col("meditate_pending").delete_one({"user_id": user_id})
            await query.edit_message_text("❌ Your faction changed. Start a new cultivation session.")
            return
        if time.time() - float(pending.get("created_at", 0) or 0) > SESSION_TIMEOUT:
            col("meditate_pending").delete_one({"user_id": user_id})
            refund = int(pending.get("sta_cost", 0) or 0)
            update_player(user_id, sta=min(int(player.get("max_sta", 0) or 0), int(player.get("sta", 0) or 0) + refund))
            col("cooldowns").delete_one({"user_id": user_id, "type": "meditate"})
            await query.edit_message_text("⌛ The trial faded before completion. Your stamina was refunded; use /meditate to retry.")
            return

        try:
            _, _, expected_stage, choice_index = action.split("_", 3)
            expected_stage = int(expected_stage)
            choice_index = int(choice_index)
            if int(pending.get("scene_index", 0) or 0) != expected_stage:
                return
            options = pending.get("scene_options", [])
            label, points, xp_bonus = options[choice_index]
        except (ValueError, IndexError, TypeError):
            await query.edit_message_text("❌ Invalid choice. Please start /meditate again.")
            return

        score = int(pending.get("score", 0) or 0) + int(points)
        total_xp_bonus = int(pending.get("xp_bonus", 0) or 0) + int(xp_bonus)
        stage = int(pending.get("scene_index", 0) or 0) + 1

        if stage < 3:
            scene = _scene_for(faction)
            col("meditate_pending").update_one(
                {"user_id": user_id},
                {"$set": {
                    "scene_index": stage, "score": score, "xp_bonus": total_xp_bonus,
                    "scene_title": scene[0], "scene_text": scene[1], "scene_options": scene[2],
                }},
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(opt[0], callback_data=f"meditate_choice_{stage}_{i}")]
                for i, opt in enumerate(scene[2])
            ])
            faction_word = "blood trial" if is_demon else "breathing trial"
            await query.edit_message_text(
                f"✅ *Choice recorded:* {label}\n\n"
                f"*{scene[0]}*\n{scene[1]}\n\n"
                f"*Stage {stage + 1} of 3 — Continue your {faction_word}:*",
                parse_mode="Markdown",
                reply_markup=keyboard,
            )
            return

        # Complete the journey and award faction-specific mastery.
        base_gain = {"water": 5, "thunder": 5, "flame": 7, "devour": 5, "shadow": 5, "art": 7}.get(pending.get("path"), 5)
        gain = max(3, min(16, base_gain + score // 5))
        xp_gain = (55 if is_demon else 50) + total_xp_bonus + score * 2
        new_potential = min(100, potential + gain)
        update_player(user_id, potential=new_potential, xp=int(player.get("xp", 0) or 0) + xp_gain)
        col("meditate_pending").delete_one({"user_id": user_id})
        progress_name = "Blood Potential" if is_demon else "Breathing Potential"
        event_reward = "🩸 Blood Art mastery strengthened." if is_demon else "🌬️ Breathing control improved."
        next_step = "☠️ Use /meditate to evolve your demon form at 100%." if is_demon else "☀️ Use /meditate to awaken your next tier at 100%."
        await query.edit_message_text(
            f"*{'☠️ BLOOD CULTIVATION COMPLETE' if is_demon else '🧘 MEDITATION COMPLETE'}*\n\n"
            f"🛤️ Path: *{pending.get('path_name', 'Cultivation')}*\n"
            f"📖 Final choice: _{label}_\n"
            f"🏅 Journey score: *{score}*\n\n"
            f"*Rewards*\n"
            f"🔮 {progress_name}: *+{gain}%*\n"
            f"⭐ XP: *+{xp_gain}*\n"
            f"{event_reward}\n\n"
            f"*Progress:* {new_potential}% / 100%\n{_bar(new_potential)}\n\n"
            f"{'✨ ' + next_step if new_potential >= 100 else '⏳ Next session in 1 hour.'}",
            parse_mode="Markdown",
        )
        return

