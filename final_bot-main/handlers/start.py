from telegram.error import BadRequest, TimedOut
import random
import asyncio
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler
from telegram.constants import ChatType
from utils.database import get_player, create_player, update_player, add_item, col
from utils.helpers import get_rank
from config import BREATHING_STYLES, DEMON_ARTS, STORIES, SLAYER_RANKS, DEMON_RANKS
from handlers.logs import log_user_activity
import config

WAITING_NAME    = 1
WAITING_CAPTCHA = 4  # captcha state (inserted before name)
CHOOSING_FACTION = 2
CHOOSING_STORY = 3
CAPTCHA_LOCK_MINUTES = 30

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


def _get_captcha_lock(user_id: int) -> datetime | None:
    doc = col("captcha_guard").find_one({"user_id": user_id}) or {}
    lock_until = doc.get("lock_until")
    now = datetime.now()
    if isinstance(lock_until, datetime) and lock_until > now:
        return lock_until
    if lock_until:
        col("captcha_guard").update_one(
            {"user_id": user_id},
            {"$set": {"lock_until": None}},
            upsert=True,
        )
    return None


def _set_captcha_lock(user_id: int) -> datetime:
    lock_until = datetime.now() + timedelta(minutes=CAPTCHA_LOCK_MINUTES)
    col("captcha_guard").update_one(
        {"user_id": user_id},
        {"$set": {"lock_until": lock_until, "last_failed_at": datetime.now()}},
        upsert=True,
    )
    return lock_until


def _clear_captcha_lock(user_id: int) -> None:
    col("captcha_guard").update_one(
        {"user_id": user_id},
        {"$set": {
            "lock_until": None,
            "last_passed_at": datetime.now(),
            "challenge_required": False,
            "challenge_reason": None,
            "challenge_set_at": None,
        }},
        upsert=True,
    )


def _get_human_check_reason(user_id: int) -> str | None:
    doc = col("captcha_guard").find_one({"user_id": user_id}) or {}
    if not doc.get("challenge_required"):
        return None
    reason = str(doc.get("challenge_reason") or "").strip()
    return reason[:180] if reason else "Suspicious automated activity was detected."


def _make_captcha():
    """
    Generate an anti-bot captcha with multiple question types.
    Types: emoji count, symbol math, word association, pattern.
    Bots cannot reliably solve these without understanding context.
    """
    captcha_type = random.choice(['emoji_count', 'symbol_math', 'emoji_pick', 'sequence'])

    if captcha_type == 'emoji_count':
        # "Count the 🗡️ in: 🗡️💧🗡️🔥🗡️" -> answer is 3
        emojis = ['🗡️','💧','🔥','🌸','⚡','🌀','🛡️','👹']
        target = random.choice(emojis[:4])
        filler = [e for e in emojis if e != target]
        count  = random.randint(2, 5)
        extras = random.randint(1, 3)
        seq    = [target]*count + random.sample(filler, min(extras, len(filler)))
        random.shuffle(seq)
        q   = f"How many *{target}* are in this sequence?\n\n`{'  '.join(seq)}`"
        ans = count

    elif captcha_type == 'symbol_math':
        # Replace digits with symbols to confuse pattern matchers
        num_map = {'1':'①','2':'②','3':'③','4':'④','5':'⑤','6':'⑥','7':'⑦','8':'⑧','9':'⑨'}
        a = random.randint(2, 9)
        b = random.randint(2, 9)
        op = random.choice(['+', '−'])
        if op == '+':
            ans = a + b
            sa  = num_map.get(str(a), str(a))
            sb  = num_map.get(str(b), str(b))
            q   = f"Solve: *{sa} ＋ {sb} = ?*"
        else:
            if b > a: a, b = b, a
            ans = a - b
            sa  = num_map.get(str(a), str(a))
            sb  = num_map.get(str(b), str(b))
            q   = f"Solve: *{sa} － {sb} = ?*"

    elif captcha_type == 'emoji_pick':
        # "Which of these is a WEAPON?" -> tap the sword
        categories = [
            ('WEAPON',  ['🗡️','⚔️','🏹','🔪'], ['💧','🌸','🍎','🎵','🌙','🏠']),
            ('ANIMAL',  ['🐺','🦅','🐍','🦋'], ['🌊','🔥','⛰️','🎭','💎','🌑']),
            ('WEATHER', ['⛈️','🌊','🌀','❄️'], ['🗡️','👹','🏯','🌸','🔮','⚔️']),
            ('NATURE',  ['🌸','🌿','🍃','🌊'], ['🗡️','⚡','🔥','💀','🏯','👹']),
        ]
        cat, correct_pool, wrong_pool = random.choice(categories)
        correct = random.choice(correct_pool)
        wrongs  = random.sample(wrong_pool, 3)
        choices_list = wrongs + [correct]
        random.shuffle(choices_list)
        q   = f"👆 Tap the *{cat}*:\n\n{'   '.join(choices_list)}"
        # ans = index of correct in shuffled list (store emoji as ans)
        # Special: store emoji string instead of int
        return q, correct, choices_list  # string answers

    else:  # sequence
        # "What comes next? 🔴 🔴 🔵 🔴 🔴 ?"
        patterns = [
            (['🔴','🔴','🔵'], '🔴','🔵','🟡'),
            (['⬆️','⬇️','⬆️'], '⬇️','➡️','↗️'),
            (['🌕','🌖','🌗'], '🌘','🌑','🌕'),
            (['1️⃣','2️⃣','3️⃣'], '4️⃣','5️⃣','0️⃣'),
        ]
        pat, correct, w1, w2 = random.choice(patterns)
        seq  = ' '.join(pat) + ' ❓'
        q    = f"What comes next?\n\n*{seq}*"
        ans  = correct
        choices_list = [correct, w1, w2, random.choice([w1,w2])]
        random.shuffle(choices_list)
        return q, correct, choices_list  # string answers

    # Numeric answer path
    wrong = set()
    while len(wrong) < 3:
        w = ans + random.choice([-3,-2,-1,1,2,3,4,5])
        if w != ans and w > 0 and w < 30:
            wrong.add(w)
    choices = list(wrong) + [ans]
    random.shuffle(choices)
    return q, ans, choices


async def send_captcha(update, context):
    """Send captcha — called from start() before name entry."""
    q, ans, choices = _make_captcha()
    context.user_data['captcha_ans'] = str(ans)
    context.user_data['captcha_tries'] = 0

    # Build buttons — each choice is a separate row to prevent pattern scanning
    buttons = []
    row = []
    for i, c in enumerate(choices):
        row.append(InlineKeyboardButton(str(c), callback_data=f"captcha_{c}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if msg:
        await msg.reply_text(
            "🔐 *HUMAN VERIFICATION*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "_Before entering the world, prove you are human:_\n\n"
            f"{q}\n\n"
            "👇 _Tap the correct answer:_",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    return WAITING_CAPTCHA


async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle captcha answer button press."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id if query.message else None
    chat_type = query.message.chat.type if query.message and query.message.chat else None

    # Ignore stale callbacks — if captcha_ans not in user_data the state is gone
    if not context.user_data.get('captcha_ans'):
        await query.answer("⏰ This captcha has expired. Use /start again.", show_alert=True)
        try:
            await query.edit_message_text(
                "⏰ *Captcha expired.* Use /start to begin again.",
                parse_mode='Markdown'
            )
        except Exception:
            pass
        return ConversationHandler.END

    await query.answer()

    # Answer can be int or emoji string
    raw     = query.data[len('captcha_'):]   # strip prefix
    chosen  = raw
    correct = str(context.user_data.get('captcha_ans', ''))
    tries   = context.user_data.get('captcha_tries', 0) + 1
    context.user_data['captcha_tries'] = tries

    if chosen == correct or (chosen.isdigit() and correct.isdigit() and int(chosen)==int(correct)):
        # Passed — proceed to name entry
        _clear_captcha_lock(user_id)
        log_user_activity(
            user_id,
            "captcha_passed",
            details=f"Passed after {tries} attempt(s)",
            chat_id=chat_id,
            chat_type=chat_type,
            username=query.from_user.username,
            name=query.from_user.first_name,
        )
        await query.edit_message_text(
            "✅ *Verification passed!*\n\n"
            "🌸 *Welcome to Demon Slayer RPG* 🌸\n\n"
            "The year is Taisho Era Japan...\n"
            "Demons lurk in the shadows, feeding on the innocent.\n"
            "The Demon Slayer Corps stands as humanity's last hope.\n\n"
            "📜 *What shall you be called in this world?*\n"
            "_(Type your character name below)_",
            parse_mode='Markdown'
        )
        return WAITING_NAME
    else:
        if tries >= 3:
            lock_until = _set_captcha_lock(user_id)
            remaining = max(1, int((lock_until - datetime.now()).total_seconds() // 60))
            log_user_activity(
                user_id,
                "captcha_locked",
                details=f"Locked for {remaining} minute(s) after repeated failures",
                chat_id=chat_id,
                chat_type=chat_type,
                username=query.from_user.username,
                name=query.from_user.first_name,
            )
            await query.edit_message_text(
                "❌ *Too many wrong answers.*\n\n"
                "_Automated bots are not allowed.\n"
                f"Try again in about *{remaining} minute(s)* with /start._",
                parse_mode='Markdown'
            )
            return ConversationHandler.END
        # Wrong — regenerate captcha
        log_user_activity(
            user_id,
            "captcha_failed",
            details=f"Wrong answer on attempt {tries}/3",
            chat_id=chat_id,
            chat_type=chat_type,
            username=query.from_user.username,
            name=query.from_user.first_name,
        )
        q2, ans2, choices2 = _make_captcha()
        context.user_data['captcha_ans'] = str(ans2)
        buttons = [[InlineKeyboardButton(str(c), callback_data=f"captcha_{c}") for c in choices2]]
        await query.edit_message_text(
            f"❌ *Wrong answer!* _(Attempt {tries}/3)_\n\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"❓ *{q2} = ?*\n\n"
            "_Try again:_",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        return WAITING_CAPTCHA


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat    = update.effective_chat

    if update.effective_user and update.effective_user.is_bot:
        await update.message.reply_text("âŒ Bot accounts cannot create characters.")
        return ConversationHandler.END

    # If used in a group — send DM button instead of starting character creation
    if chat and chat.type != ChatType.PRIVATE:
        bot_username = getattr(config, 'BOT_USERNAME', 'your_bot')
        bot_link = f"https://t.me/{bot_username}"
        await update.message.reply_text(
            f"⚔️ *𝘿𝙀𝙈𝙊𝙉 𝙎𝙇𝘼𝙔𝙀𝙍 𝙍𝙋𝙂*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"╰➤ 𝙏𝙖𝙥 𝙗𝙚𝙡𝙤𝙬 𝙩𝙤 𝙨𝙩𝙖𝙧𝙩 𝙮𝙤𝙪𝙧 𝙟𝙤𝙪𝙧𝙣𝙚𝙮! 👇",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚔️ 𝙋𝙡𝙖𝙮 𝙉𝙤𝙬", url=bot_link)
            ]])
        )
        return ConversationHandler.END

    player = get_player(user_id)
    if player:
        await update.message.reply_text(
            f"⚔️ Welcome back, *{player['name']}*!\n\n"
            "Your journey continues...\n\n"
            "/menu — Return to main hub",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    lock_until = _get_captcha_lock(user_id)
    if lock_until:
        remaining = max(1, int((lock_until - datetime.now()).total_seconds() // 60))
        log_user_activity(
            user_id,
            "captcha_blocked",
            details=f"Blocked by active captcha lock ({remaining} minute(s) left)",
            chat_id=chat.id if chat else None,
            chat_type=chat.type if chat else None,
            username=update.effective_user.username if update.effective_user else None,
            name=update.effective_user.first_name if update.effective_user else None,
        )
        await update.message.reply_text(
            f"ðŸš« *Verification cooldown active*\n\n"
            f"Too many failed human checks were detected.\n"
            f"Please wait about *{remaining} minute(s)* and use /start again.",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    # Check for referral code in /start ref_USERID
    if context.args:
        ref_arg = context.args[0]
        if ref_arg.startswith('ref_'):
            try:
                referrer_id = int(ref_arg[4:])
                if referrer_id != user_id and get_player(referrer_id):
                    context.user_data['referrer_id'] = referrer_id
            except (ValueError, TypeError):
                pass

    # Skip captcha — go straight to name entry
    log_user_activity(
        user_id,
        "captcha_sent",
        details="New player verification started",
        chat_id=chat.id if chat else None,
        chat_type=chat.type if chat else None,
        username=update.effective_user.username if update.effective_user else None,
        name=update.effective_user.first_name if update.effective_user else None,
    )
    return await send_captcha(update, context)
    await update.message.reply_text(
        "🌸 *Welcome to Demon Slayer RPG* 🌸\n\n"
        "The year is Taisho Era Japan...\n"
        "Demons lurk in the shadows, feeding on the innocent.\n"
        "The Demon Slayer Corps stands as humanity\'s last hope.\n\n"
        "📜 *What shall you be called in this world?*\n"
        "_(Type your character name below)_",
        parse_mode='Markdown'
    )
    return WAITING_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2 or len(name) > 20:
        await update.message.reply_text("⚠️ Name must be 2-20 characters. Try again:")
        return WAITING_NAME

    lowered = name.lower()
    if any(token in lowered for token in ("http", "www.", ".com", "t.me/", "@")):
        await update.message.reply_text("âš ï¸ Links and tags are not allowed in character names. Try again:")
        return WAITING_NAME
    if sum(ch.isalpha() for ch in name) < 2:
        await update.message.reply_text("âš ï¸ Name must contain at least 2 letters. Try again:")
        return WAITING_NAME
    if sum(ch.isdigit() for ch in name) > 4:
        await update.message.reply_text("âš ï¸ Name has too many numbers. Try again:")
        return WAITING_NAME

    context.user_data['char_name'] = name

    await update.message.reply_text(
        f"🌸 *Welcome, {name}!*\n\n"
        "The world of Taisho Era Japan awaits you.\n"
        "Demons lurk in the shadows...\n"
        "Your destiny is about to be revealed.\n\n"
        "⚔️ *Choose Your Path:*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🗡️ Demon Slayer", callback_data='faction_slayer'),
                InlineKeyboardButton("👹 Demon", callback_data='faction_demon')
            ]
        ])
    )
    return CHOOSING_FACTION

async def choose_faction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    faction = query.data.split('_')[1]
    context.user_data['faction'] = faction

    full_pool = BREATHING_STYLES if faction == 'slayer' else DEMON_ARTS
    label     = "Breathing Style" if faction == 'slayer' else "Blood Demon Art"

    # ── EXCLUSIVITY FILTER ───────────────────────────────────────────────
    from utils.database import col as _col
    pool    = []
    weights = []
    for s in full_pool:
        w = s.get('gacha_weight', 5)
        if w == 0:
            continue  # ULTRA LEGENDARY — never rolls from gacha
        # Stone Breathing: only ONE player in the entire game can own it
        if s['name'] == 'Stone Breathing':
            if _col('players').find_one({'style': 'Stone Breathing'}):
                continue  # Already taken
        pool.append(s)
        weights.append(w)

    if not pool:
        pool    = full_pool[:5]
        weights = [10] * len(pool)

    # ── GACHA ANIMATION ──────────────────────────────────────────────────
    spin_emojis  = [s['emoji'] for s in pool]
    spin_display = ' → '.join(random.choices(spin_emojis, k=6))

    await _safe_edit(query, 
        f"🎰 *The fates are spinning...*\n\n"
        f"🎲 Rolling...\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{spin_display}...\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"✨ *Deciding your {label}...*",
        parse_mode='Markdown'
    )

    await asyncio.sleep(2)

    chosen = random.choices(pool, weights=weights, k=1)[0]
    context.user_data['style']       = chosen['name']
    context.user_data['style_emoji'] = chosen['emoji']

    # Rarity reveal effect
    rarity = chosen['rarity']
    if 'ULTRA' in rarity:
        reveal = "🌑 ✨✨✨ 𝙐𝙇𝙏𝙍𝘼 𝙇𝙀𝙂𝙀𝙉𝘿𝘼𝙍𝙔 ✨✨✨"
    elif 'LEGENDARY' in rarity:
        reveal = "🌟 ★★★★★ 𝙇𝙀𝙂𝙀𝙉𝘿𝘼𝙍𝙔 ★★★★★"
    elif 'RARE' in rarity:
        reveal = "💎 ★★★ 𝙍𝘼𝙍𝙀"
    else:
        reveal = "✨ ★★ 𝘾𝙊𝙈𝙈𝙊𝙉"

    await _safe_edit(query, 
        f"🎰 *THE FATES HAVE SPOKEN!*\n\n"
        f"{reveal}\n\n"
        f"{chosen['emoji']} *{chosen['name'].upper()}*\n"
        f"{rarity}\n\n"
        f"_\"{chosen['description']}\"_",
        parse_mode='Markdown'
    )

    await asyncio.sleep(2)

    # Story selection
    keyboard = [
        [
            InlineKeyboardButton("😢 Lost Family", callback_data='story_1'),
            InlineKeyboardButton("🏯 Noble Clan", callback_data='story_2'),
        ],
        [
            InlineKeyboardButton("🌾 Village Protector", callback_data='story_3'),
            InlineKeyboardButton("🗡️ Wandering Warrior", callback_data='story_4'),
        ]
    ]

    await _safe_edit(query, 
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
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return CHOOSING_STORY

async def choose_story(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    story_id = int(query.data.split('_')[1])
    story = STORIES[story_id - 1]
    context.user_data['story'] = story['name']
    context.user_data['story_bonus'] = story['bonus_type']

    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name
    name = context.user_data['char_name']
    faction = context.user_data['faction']
    style = context.user_data['style']
    style_emoji = context.user_data['style_emoji']
    story_name = story['name']
    story_bonus = story['bonus_type']

    ranks = SLAYER_RANKS if faction == 'slayer' else DEMON_RANKS
    starting_rank = ranks[0]

    create_player(
        user_id, username, name, faction,
        style, style_emoji, story_name, story_bonus,
        starting_rank['name'], starting_rank['kanji']
    )

    # ── NEW PLAYER WELCOME BONUS ──────────────────────────────────────────
    update_player(user_id, yen=1000 + 500, xp=200, skill_points=10)  # extra 500¥ + 200 XP + 10 SP
    add_item(user_id, "Full Recovery Gourd",  "item", 3)
    add_item(user_id, "Stamina Pill",         "item", 5)
    add_item(user_id, "Wisteria Antidote",    "item", 2)
    update_player(user_id, human_verified_at=datetime.now())
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
    referrer_id = context.user_data.pop('referrer_id', None)
    if referrer_id:
        from utils.database import add_referral, was_referred
        if not was_referred(user_id):
            added = add_referral(referrer_id, user_id)
            if added:
                from handlers.referral import process_referral_reward
                import asyncio
                asyncio.create_task(process_referral_reward(context, referrer_id, user_id))

    faction_label = "DEMON SLAYER" if faction == 'slayer' else "DEMON"
    weapon_label = "Basic Nichirin Blade" if faction == 'slayer' else "Demon Claws"

    # Center the name in the card header (max 15 chars)
    display_name = name[:15]

    await _safe_edit(query, 
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
        f"🔥 _\"Your blade is the only thing standing_\n"
        f"_between humanity and the darkness.\"_\n\n"
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
        parse_mode='Markdown'
    )
    return ConversationHandler.END


def _build_captcha_markup(choices):
    buttons = []
    row = []
    for choice in choices:
        row.append(InlineKeyboardButton(str(choice), callback_data=f"captcha_{choice}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


async def send_captcha(update, context):
    """Send captcha for either onboarding or a security re-check."""
    q, ans, choices = _make_captcha()
    context.user_data["captcha_ans"] = str(ans)
    context.user_data["captcha_tries"] = 0

    mode = context.user_data.get("captcha_mode", "new_player")
    reason = str(context.user_data.get("captcha_reason") or "").strip()
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return WAITING_CAPTCHA

    if mode == "security_check":
        text = (
            "*SECURITY CHECK*\n\n"
            "Suspicious automated activity was detected on this account.\n"
            "Pass this human check to unlock your commands again."
        )
        if reason:
            text += f"\n\nLast trigger: `{reason[:120]}`"
    else:
        text = (
            "*HUMAN VERIFICATION*\n\n"
            "Before entering the world, prove you are human."
        )

    text += f"\n\n{q}\n\n_Select the correct answer._"

    await msg.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=_build_captcha_markup(choices),
    )
    return WAITING_CAPTCHA


async def captcha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle captcha answer button press."""
    query = update.callback_query
    user_id = query.from_user.id
    chat_id = query.message.chat_id if query.message else None
    chat_type = query.message.chat.type if query.message and query.message.chat else None
    mode = context.user_data.get("captcha_mode", "new_player")

    if not context.user_data.get("captcha_ans"):
        await query.answer("This captcha has expired. Use /start again.", show_alert=True)
        try:
            await query.edit_message_text(
                "*Captcha expired.* Use /start to begin again.",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        return ConversationHandler.END

    await query.answer()

    chosen = str((query.data or "")[len("captcha_"):])
    correct = str(context.user_data.get("captcha_ans", ""))
    tries = context.user_data.get("captcha_tries", 0) + 1
    context.user_data["captcha_tries"] = tries

    if chosen == correct or (chosen.isdigit() and correct.isdigit() and int(chosen) == int(correct)):
        _clear_captcha_lock(user_id)
        if get_player(user_id):
            update_player(user_id, human_verified_at=datetime.now())

        pass_details = (
            f"Security check passed after {tries} attempt(s)"
            if mode == "security_check"
            else f"Passed after {tries} attempt(s)"
        )
        log_user_activity(
            user_id,
            "captcha_passed",
            details=pass_details,
            chat_id=chat_id,
            chat_type=chat_type,
            username=query.from_user.username,
            name=query.from_user.first_name,
        )
        context.user_data.pop("captcha_ans", None)
        context.user_data.pop("captcha_tries", None)
        context.user_data.pop("captcha_reason", None)
        context.user_data.pop("captcha_mode", None)

        if mode == "security_check":
            await query.edit_message_text(
                "*Verification passed.*\n\nYour account is unlocked again.\nUse /menu to continue.",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        await query.edit_message_text(
            "✅ *Verification passed!*\n\n"
            "🌸 *Welcome to Demon Slayer RPG* 🌸\n\n"
            "The year is Taisho Era Japan...\n"
            "Demons lurk in the shadows, feeding on the innocent.\n"
            "The Demon Slayer Corps stands as humanity's last hope.\n\n"
            "📜 *What shall you be called in this world?*\n"
            "_(Type your character name below)_",
            parse_mode="Markdown"
        )
        return WAITING_NAME

    if tries >= 3:
        lock_until = _set_captcha_lock(user_id)
        remaining = max(1, int((lock_until - datetime.now()).total_seconds() // 60))
        lock_details = (
            f"Security check locked for {remaining} minute(s)"
            if mode == "security_check"
            else f"Locked for {remaining} minute(s) after repeated failures"
        )
        log_user_activity(
            user_id,
            "captcha_locked",
            details=lock_details,
            chat_id=chat_id,
            chat_type=chat_type,
            username=query.from_user.username,
            name=query.from_user.first_name,
        )
        await query.edit_message_text(
            "❌ *Too many wrong answers.*\n\n"
            "Automated bots are not allowed.\n"
            f"Try again in about *{remaining} minute(s)* with /start.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    log_user_activity(
        user_id,
        "captcha_failed",
        details=f"Wrong answer on attempt {tries}/3",
        chat_id=chat_id,
        chat_type=chat_type,
        username=query.from_user.username,
        name=query.from_user.first_name,
    )
    q2, ans2, choices2 = _make_captcha()
    context.user_data["captcha_ans"] = str(ans2)
    await query.edit_message_text(
        f"❌ *Wrong answer.* Attempt {tries}/3.\n\n{q2}\n\n_Select the correct answer._",
        parse_mode="Markdown",
        reply_markup=_build_captcha_markup(choices2),
    )
    return WAITING_CAPTCHA


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    chat = update.effective_chat
    user = update.effective_user
    msg = update.message or (update.callback_query.message if update.callback_query else None)

    if user and user.is_bot:
        if msg:
            await msg.reply_text("Bot accounts cannot create characters.")
        return ConversationHandler.END

    if chat and chat.type != ChatType.PRIVATE:
        bot_username = getattr(config, "BOT_USERNAME", "your_bot")
        bot_link = f"https://t.me/{bot_username}"
        if msg:
            await msg.reply_text(
                "Character creation is DM only.\nTap below to open the bot privately.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("Open Bot", url=bot_link)
                ]])
            )
        return ConversationHandler.END

    context.user_data.pop("captcha_ans", None)
    context.user_data.pop("captcha_tries", None)

    lock_until = _get_captcha_lock(user_id)
    if lock_until:
        remaining = max(1, int((lock_until - datetime.now()).total_seconds() // 60))
        log_user_activity(
            user_id,
            "captcha_blocked",
            details=f"Blocked by active captcha lock ({remaining} minute(s) left)",
            chat_id=chat.id if chat else None,
            chat_type=chat.type if chat else None,
            username=user.username if user else None,
            name=user.first_name if user else None,
        )
        if msg:
            await msg.reply_text(
                "🚫 *Verification cooldown active*\n\n"
                f"Please wait about *{remaining} minute(s)* and use /start again.",
                parse_mode="Markdown",
            )
        return ConversationHandler.END

    player = get_player(user_id)
    challenge_reason = _get_human_check_reason(user_id)
    if player and challenge_reason:
        context.user_data["captcha_mode"] = "security_check"
        context.user_data["captcha_reason"] = challenge_reason
        log_user_activity(
            user_id,
            "captcha_sent",
            details=f"Security check started: {challenge_reason}",
            chat_id=chat.id if chat else None,
            chat_type=chat.type if chat else None,
            username=user.username if user else None,
            name=user.first_name if user else None,
        )
        return await send_captcha(update, context)

    if player:
        if msg:
            await msg.reply_text(
                f"⚔️ Welcome back, *{player['name']}*!\n\n"
                "Your journey continues...\n\n"
                "/menu - Return to main hub",
                parse_mode="Markdown"
            )
        return ConversationHandler.END

    if context.args:
        ref_arg = context.args[0]
        if ref_arg.startswith("ref_"):
            try:
                referrer_id = int(ref_arg[4:])
                if referrer_id != user_id and get_player(referrer_id):
                    context.user_data["referrer_id"] = referrer_id
            except (ValueError, TypeError):
                pass

    context.user_data["captcha_mode"] = "new_player"
    context.user_data.pop("captcha_reason", None)
    log_user_activity(
        user_id,
        "captcha_sent",
        details="New player verification started",
        chat_id=chat.id if chat else None,
        chat_type=chat.type if chat else None,
        username=user.username if user else None,
        name=user.first_name if user else None,
    )
    return await send_captcha(update, context)
