"""
handlers/start.py — Character creation flow (captcha removed)

Flow:
    /start → check if existing player → ask for name → choose faction → choose story → done
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from utils.database import get_player, col
from config import (
    STARTING_YEN, STARTING_HP, STARTING_STA,
    STARTING_STR, STARTING_SPD, STARTING_DEF,
    BREATHING_STYLES, DEMON_ARTS, STORIES,
)

logger = logging.getLogger(__name__)

# ── Conversation states ───────────────────────────────────────────────────
WAITING_NAME     = 0
CHOOSING_FACTION = 1
CHOOSING_STORY   = 2

# (WAITING_CAPTCHA removed — captcha is disabled)


# ── /start entry point ────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point for /start. Skips captcha and jumps straight to name entry."""
    user = update.effective_user
    if not user:
        return ConversationHandler.END

    # Existing player — show welcome back message
    player = get_player(user.id)
    if player:
        name = player.get("name", user.first_name)
        faction = player.get("faction", "slayer").capitalize()
        rank = player.get("rank", "Mizunoto")
        level = player.get("level", 1)

        text = (
            f"⚔️ Welcome back, *{name}*!\n\n"
            f"Faction: *{faction}*\n"
            f"Rank: *{rank}* | Level: *{level}*\n\n"
            "Use /menu to open your player menu."
        )
        keyboard = [[InlineKeyboardButton("📋 Open Menu", callback_data="goto_menu")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        msg = update.message or (update.callback_query and update.callback_query.message)
        if update.callback_query:
            try:
                await update.callback_query.answer()
            except Exception:
                pass
            try:
                await update.callback_query.edit_message_text(
                    text, parse_mode="Markdown", reply_markup=reply_markup
                )
            except Exception:
                if update.callback_query.message:
                    await update.callback_query.message.reply_text(
                        text, parse_mode="Markdown", reply_markup=reply_markup
                    )
        elif update.message:
            await update.message.reply_text(
                text, parse_mode="Markdown", reply_markup=reply_markup
            )
        return ConversationHandler.END

    # New player — ask for their name directly (no captcha)
    text = (
        "⚔️ *Welcome to the Demon Slayer RPG!*\n\n"
        "Your journey begins now.\n\n"
        "Please send your *character name* to get started:"
    )
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
        try:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown")
        except Exception:
            if update.callback_query.message:
                await update.callback_query.message.reply_text(text, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(text, parse_mode="Markdown")

    return WAITING_NAME


# ── Name input ────────────────────────────────────────────────────────────
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive the player's chosen name and ask for faction."""
    name = update.message.text.strip() if update.message and update.message.text else ""

    if not name or len(name) < 2:
        await update.message.reply_text(
            "❌ Name must be at least 2 characters. Please try again:"
        )
        return WAITING_NAME

    if len(name) > 32:
        await update.message.reply_text(
            "❌ Name is too long (max 32 characters). Please try again:"
        )
        return WAITING_NAME

    # Store name in context for use in later steps
    context.user_data["new_name"] = name

    keyboard = [
        [InlineKeyboardButton("🗡️ Demon Slayer", callback_data="faction_slayer")],
        [InlineKeyboardButton("😈 Demon",         callback_data="faction_demon")],
    ]
    await update.message.reply_text(
        f"✅ Great name, *{name}*!\n\n"
        "Now choose your faction:\n\n"
        "🗡️ *Demon Slayer* — Protect humanity, master breathing styles\n"
        "😈 *Demon* — Embrace darkness, wield Blood Demon Arts",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSING_FACTION


# ── Faction choice ────────────────────────────────────────────────────────
async def choose_faction(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle faction selection and show origin story choices."""
    query = update.callback_query
    await query.answer()

    faction = query.data.replace("faction_", "")  # "slayer" or "demon"
    context.user_data["new_faction"] = faction

    keyboard = [
        [InlineKeyboardButton(f"{s['emoji']} {s['name']}", callback_data=f"story_{s['id']}")]
        for s in STORIES
    ]
    faction_label = "Demon Slayer" if faction == "slayer" else "Demon"
    await query.edit_message_text(
        f"⚔️ Faction: *{faction_label}*\n\n"
        "Choose your *origin story*:\n"
        + "\n".join(
            f"{s['emoji']} *{s['name']}* — {s['description']}\n_{s['bonus_text']}_"
            for s in STORIES
        ),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return CHOOSING_STORY


# ── Story / origin choice — creates player ────────────────────────────────
async def choose_story(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle origin story selection and create the player document."""
    query = update.callback_query
    await query.answer()

    story_id = int(query.data.replace("story_", ""))
    story = next((s for s in STORIES if s["id"] == story_id), STORIES[0])

    user        = update.effective_user
    name        = context.user_data.get("new_name", user.first_name)
    faction     = context.user_data.get("new_faction", "slayer")

    # Pick a random starting art / style appropriate to the faction
    import random
    if faction == "slayer":
        style_pool = BREATHING_STYLES
    else:
        style_pool = DEMON_ARTS

    # Filter to common-only for starters
    common_styles = [s for s in style_pool if "COMMON" in s.get("rarity", "")]
    starting_style = random.choice(common_styles) if common_styles else style_pool[0]

    # Build stat bonuses from the chosen story
    bonus_type  = story.get("bonus_type", "")
    bonus_value = story.get("bonus_value", 0)

    base_hp  = STARTING_HP
    base_sta = STARTING_STA
    base_str = STARTING_STR
    base_spd = STARTING_SPD
    base_def = STARTING_DEF

    if bonus_type == "hp_bonus":
        base_hp = int(base_hp * (1 + bonus_value))
    elif bonus_type == "def_bonus":
        base_def = int(base_def * (1 + bonus_value))

    player_doc = {
        "user_id":        user.id,
        "username":       user.username,
        "name":           name,
        "faction":        faction,
        "story_id":       story_id,
        "story_name":     story["name"],
        "story_bonus":    {bonus_type: bonus_value} if bonus_type else {},
        "level":          1,
        "xp":             0,
        "yen":            STARTING_YEN,
        "max_hp":         base_hp,
        "hp":             base_hp,
        "max_sta":        base_sta,
        "sta":            base_sta,
        "str_stat":       base_str,
        "spd":            base_spd,
        "def_stat":       base_def,
        "style":          starting_style["name"],
        "sp":             0,
        "rank":           "Mizunoto" if faction == "slayer" else "Stray Demon",
        "banned":         False,
        "location":       "asakusa",
        "inventory":      [],
        "equipped_sword": None,
        "equipped_armor": None,
        "pets":           [],
        "active_pet":     None,
        "skills":         [],
        "bank":           {"balance": 0, "level": 1},
        "sp_bank":        {"balance": 0},
        "daily_streak":   0,
        "last_daily":     None,
        "mission":        None,
        "referral_used":  False,
    }

    col("players").insert_one(player_doc)
    logger.info(f"New player created: {user.id} ({name}) faction={faction}")

    faction_label = "Demon Slayer" if faction == "slayer" else "Demon"
    style_label   = starting_style["name"]

    await query.edit_message_text(
        f"✅ *{name}* has entered the world!\n\n"
        f"Faction: *{faction_label}*\n"
        f"Origin: *{story['name']}*\n"
        f"Starting Style: *{style_label}* {starting_style.get('emoji','')}\n\n"
        f"HP: {base_hp} | STA: {base_sta} | STR: {base_str} | SPD: {base_spd} | DEF: {base_def}\n\n"
        "Use /menu to begin your journey. ⚔️",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


# ── Stub: captcha_callback (no longer used, kept for safety) ─────────────
async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Captcha has been disabled. This handler is a no-op stub."""
    if update.callback_query:
        await update.callback_query.answer()
    return ConversationHandler.END
