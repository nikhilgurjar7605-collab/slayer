from telegram.error import BadRequest, TimedOut
import random
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ChatType
from utils.database import get_player, create_player, update_player, add_item, col
from utils.helpers import get_rank
from config import BREATHING_STYLES, DEMON_ARTS, STORIES, SLAYER_RANKS, DEMON_RANKS
from handlers.logs import log_user_activity
import config

WAITING_NAME     = 1
CHOOSING_FACTION = 2
CHOOSING_STORY   = 3


async def _safe_edit(query, text, **kwargs):
    """Edit a message safely, falling back to reply on failure."""
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        try:
            await query.message.reply_text(text, **kwargs)
        except Exception:
            pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat    = update.effective_chat
    user    = update.effective_user
    msg     = update.message or (update.callback_query.message if update.callback_query else None)

    if user and user.is_bot:
        if msg:
            await msg.reply_text("Bot accounts cannot create characters.")
        return ConversationHandler.END

    # Group chat — send DM button
    if chat and chat.type != ChatType.PRIVATE:
        bot_username = getattr(config, "BOT_USERNAME", "your_bot")
        bot_link = f"https://t.me/{bot_username}"
        if msg:
            await msg.reply_text(
                f"⚔️ *𝘿𝙀𝙈𝙊𝙉 𝙎𝙇𝘼𝙔𝙀𝙍 𝙍𝙋𝙂*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"╰➤ 𝙏𝙖𝙥 𝙗𝙚𝙡𝙤𝙬 𝙩𝙤 𝙨𝙩𝙖𝙧𝙩 𝙮𝙤𝙪𝙧 𝙟𝙤𝙪𝙧𝙣𝙚𝙮! 👇",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("⚔️ 𝙋𝙡𝙖𝙮 𝙉𝙤𝙬", url=bot_link)
                ]])
            )
        return ConversationHandler.END

    player = get_player(user_id)

    # ── Handle gifbuy_ deep-link — works for both new & existing players ──
    if context.args and context.args[0].startswith("gifbuy_"):
        from handlers.gif_store import gifstore_handle_deeplink
        if not player:
            # Not registered yet — tell them to create a character first
            if msg:
                await msg.reply_text(
                    "You need a character before buying a GIF banner!\n\n"
                    "📜 *What shall you be called in this world?*\n"
                    "_(Type your character name below)_",
                    parse_mode="Markdown"
                )
            # Keep the gifbuy arg in user_data so we can resume after registration
            context.user_data["pending_gifbuy"] = context.args[0]
            return WAITING_NAME
        # Already registered — send invoice directly
        await gifstore_handle_deeplink(update, context)
        return ConversationHandler.END

    if player:
        if msg:
            await msg.reply_text(
                f"⚔️ Welcome back, *{player['name']}*!\n\n"
                "Your journey continues...\n\n"
                "/menu - Return to main hub",
                parse_mode="Markdown"
            )
        return ConversationHandler.END

    # Handle referral code in /start ref_USERID
    if context.args:
        ref_arg = context.args[0]
        if ref_arg.startswith("ref_"):
            try:
                referrer_id = int(ref_arg[4:])
                if referrer_id != user_id and get_player(referrer_id):
                    context.user_data["referrer_id"] = referrer_id
            except (ValueError, TypeError):
                pass

    log_user_activity(
        user_id,
        "character_creation_started",
        details="New player started character creation",
        chat_id=chat.id if chat else None,
        chat_type=chat.type if chat else None,
        username=user.username if user else None,
        name=user.first_name if user else None,
    )

    if msg:
        await msg.reply_text(
            "🌸 *Welcome to Demon Slayer RPG* 🌸\n\n"
            "The year is Taisho Era Japan...\n"
            "Demons lurk in the shadows, feeding on the innocent.\n"
            "The Demon Slayer Corps stands as humanity's last hope.\n\n"
            "📜 *What shall you be called in this world?*\n"
            "_(Type your character name below)_",
            parse_mode="Markdown"
        )
    return WAITING_NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 20:
        await update.message.reply_text("⚠️ Name must be 2-20 characters. Try again:")
        return WAITING_NAME

    lowered = name.lower()
    if any(token in lowered for token in ("http", "www.", ".com", "t.me/", "@")):
        await update.message.reply_text("⚠️ Links and tags are not allowed in character names. Try again:")
        return WAITING_NAME
    if sum(ch.isalpha() for ch in name) < 2:
        await update.message.reply_text("⚠️ Name must contain at least 2 letters. Try again:")
        return WAITING_NAME
    if sum(ch.isdigit() for ch in name) > 4:
        await update.message.reply_text("⚠️ Name has too many numbers. Try again:")
        return WAITING_NAME

    context.user_data["char_name"] = name

    await update.message.reply_text(
        f"🌸 *Welcome, {name}!*\n\n"
        "The world of Taisho Era Japan awaits you.\n"
        "Demons lurk in the shadows...\n"
        "Your destiny is about to be revealed.\n\n"
        "⚔️ *Choose Your Path:*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🗡️ Demon Slayer", callback_data="faction_slayer"),
                InlineKeyboardButton("👹 Demon",        callback_data="faction_demon"),
            ]
        ])
    )
    return CHOOSING_FACTION


async def choose_faction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    faction = query.data.split("_")[1]
    context.user_data["faction"] = faction

    full_pool = BREATHING_STYLES if faction == "slayer" else DEMON_ARTS
    label     = "Breathing Style" if faction == "slayer" else "Blood Demon Art"

    # ── EXCLUSIVITY FILTER ───────────────────────────────────────────────
    from utils.database import col as _col
    pool    = []
    weights = []
    for s in full_pool:
        w = s.get("gacha_weight", 5)
        if w == 0:
            continue  # ULTRA LEGENDARY — never from gacha
        if s["name"] == "Stone Breathing":
            if _col("players").find_one({"style": "Stone Breathing"}):
                continue  # Already taken
        pool.append(s)
        weights.append(w)

    if not pool:
        pool    = full_pool[:5]
        weights = [10] * len(pool)

    # ── GACHA ANIMATION ──────────────────────────────────────────────────
    spin_emojis  = [s["emoji"] for s in pool]
    spin_display = " → ".join(random.choices(spin_emojis, k=6))

    await _safe_edit(
        query,
        f"🎰 *The fates are spinning...*\n\n"
        f"🎲 Rolling...\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{spin_display}...\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"✨ *Deciding your {label}...*",
        parse_mode="Markdown"
    )

    await asyncio.sleep(2)

    chosen = random.choices(pool, weights=weights, k=1)[0]
    context.user_data["style"]       = chosen["name"]
    context.user_data["style_emoji"] = chosen["emoji"]

    rarity = chosen["rarity"]
    if "ULTRA" in rarity:
        reveal = "🌑 ✨✨✨ 𝙐𝙇𝙏𝙍𝘼 𝙇𝙀𝙂𝙀𝙉𝘿𝘼𝙍𝙔 ✨✨✨"
    elif "LEGENDARY" in rarity:
        reveal = "🌟 ★★★★★ 𝙇𝙀𝙂𝙀𝙉𝘿𝘼𝙍𝙔 ★★★★★"
    elif "RARE" in rarity:
        reveal = "💎 ★★★ 𝙍𝘼𝙍𝙀"
    else:
        reveal = "✨ ★★ 𝘾𝙊𝙈𝙈𝙊𝙉"

    await _safe_edit(
        query,
        f"🎰 *THE FATES HAVE SPOKEN!*\n\n"
        f"{reveal}\n\n"
        f"{chosen['emoji']} *{chosen['name'].upper()}*\n"
        f"{rarity}\n\n"
        f"_\"{chosen['description']}\"_",
        parse_mode="Markdown"
    )

    await asyncio.sleep(2)

    keyboard = [
        [
            InlineKeyboardButton("😢 Lost Family",       callback_data="story_1"),
            InlineKeyboardButton("🏯 Noble Clan",        callback_data="story_2"),
        ],
        [
            InlineKeyboardButton("🌾 Village Protector", callback_data="story_3"),
            InlineKeyboardButton("🗡️ Wandering Warrior", callback_data="story_4"),
        ]
    ]

    await _safe_edit(
        query,
        f"📖 *What is your story?*\n\n"
        f"😢 *Lost Family to Demons*\n"
        f"   _Revenge burns hotter than any flame._\n"
        f"   Bonus: +10% damage vs enemies\n\n"
        f"🏯 *Noble Clan Duty*\n"
        f"   _Born and trained for this purpose._\n"
        f"   Bonus: +10% defense\n\n"
        f"🌾 *Village Protector*\n"
        f"   _You fight for the innocent._\n"
        f"   Bonus: +10% HP\n\n"
        f"🗡️ *Wandering Warrior*\n"
        f"   _No past. Only the blade._\n"
        f"   Bonus: +10% XP gain",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING_STORY


async def choose_story(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    story_id = int(query.data.split("_")[1])
    story    = STORIES[story_id - 1]
    context.user_data["story"]       = story["name"]
    context.user_data["story_bonus"] = story["bonus_type"]

    user_id     = query.from_user.id
    username    = query.from_user.username or query.from_user.first_name
    name        = context.user_data["char_name"]
    faction     = context.user_data["faction"]
    style       = context.user_data["style"]
    style_emoji = context.user_data["style_emoji"]
    story_name  = story["name"]
    story_bonus = story["bonus_type"]

    ranks         = SLAYER_RANKS if faction == "slayer" else DEMON_RANKS
    starting_rank = ranks[0]

    create_player(
        user_id, username, name, faction,
        style, style_emoji, story_name, story_bonus,
        starting_rank["name"], starting_rank["kanji"]
    )

    # ── NEW PLAYER WELCOME BONUS ──────────────────────────────────────────
    update_player(user_id, yen=1000 + 500, xp=200, skill_points=10)
    add_item(user_id, "Full Recovery Gourd", "item", 3)
    add_item(user_id, "Stamina Pill",        "item", 5)
    add_item(user_id, "Wisteria Antidote",   "item", 2)

    log_user_activity(
        user_id,
        "character_created",
        details=f"{faction} | {style} | {story_name}",
        chat_id=query.message.chat_id if query.message else None,
        chat_type=query.message.chat.type if query.message and query.message.chat else None,
        username=query.from_user.username,
        name=name,
    )

    # Process referral if any
    referrer_id = context.user_data.pop("referrer_id", None)
    if referrer_id:
        from utils.database import add_referral, was_referred
        if not was_referred(user_id):
            added = add_referral(referrer_id, user_id)
            if added:
                from handlers.referral import process_referral_reward
                asyncio.create_task(process_referral_reward(context, referrer_id, user_id))

    faction_label = "DEMON SLAYER" if faction == "slayer" else "DEMON"
    weapon_label  = "Basic Nichirin Blade" if faction == "slayer" else "Demon Claws"
    display_name  = name[:15]

    await _safe_edit(
        query,
        f"╔═══════════════════════╗\n"
        f"║  ⚔️  {display_name.upper():^15}  ⚔️  ║\n"
        f"╚═══════════════════════╝\n\n"
        f"🌅 _A new {faction_label} rises in Taisho Japan..._\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏅 Rank:    {starting_rank['name']} — {starting_rank['kanji']}\n"
        f"{style_emoji} Style:   {style}\n"
        f"{story['emoji']} Origin:  {story_name}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Starting Yen:  1,000¥\n"
        f"⚔️  Weapon:        {weapon_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔥 _\"Your blade is the only thing standing\n"
        f"between humanity and the darkness.\"\n\n"
        f"Your legend begins now, *{name}*...\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"/profile — View your stats\n"
        f"/party — Manage your alliance\n"
        f"/guide — Learn how to play\n"
        f"/help — View all commands\n\n"
        f"🎁 *WELCOME BONUS RECEIVED!*\n"
        f"💰 +500¥  |  ⭐ +200 XP  |  💠 +10 SP\n"
        f"🍶 ×3 Recovery Gourd  |  💊 ×5 Stamina Pill  |  🌿 ×2 Wisteria Antidote\n"
        f"\n💡 Use /skilltree to spend your 10 SP on skills!",
        parse_mode="Markdown"
    )

    # ── Resume pending GIF banner purchase if they came from a Buy deep-link ──
    pending_gifbuy = context.user_data.pop("pending_gifbuy", None)
    if pending_gifbuy:
        context.args = [pending_gifbuy]
        from handlers.gif_store import gifstore_handle_deeplink
        try:
            await gifstore_handle_deeplink(update, context)
        except Exception:
            pass  # don't let this crash the registration flow

    return ConversationHandler.END
