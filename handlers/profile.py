from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, get_arts, col, update_player
from utils.helpers import get_unlocked_forms, get_level, hp_bar


SWORD_BONUSES = {
    "Basic Nichirin Blade": 8,
    "Crimson Nichirin Blade": 25,
    "Jet Black Nichirin Blade": 50,
    "Scarlet Crimson Blade": 80,
    "Transparent Nichirin Blade": 120,
    "Sun Nichirin Blade": 200,
}

ARMOR_BONUSES = {
    "Corps Uniform": 5,
    "Reinforced Haori": 15,
    "Hashira Haori": 30,
    "Demon Slayer Uniform EX": 55,
    "Flame Haori": 85,
    "Yoriichi Haori": 150,
}


def _sword_buff(name: str) -> str:
    bonus = SWORD_BONUSES.get(name, 0)
    return f" _(ATK +{bonus})_" if bonus > 0 else ""


def _armor_buff(name: str) -> str:
    bonus = ARMOR_BONUSES.get(name, 0)
    return f" _(DMG -{bonus})_" if bonus > 0 else ""


def _profile_banner_media(player: dict):
    file_id = str(player.get("profile_banner_file_id") or "").strip()
    if file_id:
        return file_id
    url = str(player.get("profile_banner_url") or "").strip()
    if url.startswith("http"):
        return url
    return None


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


async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        msg = update.message or update.callback_query.message
        await msg.reply_text("❌ No character found. Use /start to create one.")
        return

    level    = get_level(player['xp'])
    fe       = '🗡️' if player['faction'] == 'slayer' else '👹'
    faction  = 'DEMON SLAYER' if player['faction'] == 'slayer' else 'DEMON'
    # Show faction-appropriate mark
    if player.get('faction') == 'slayer':
        mark_label = "🔥 𝙎𝙡𝙖𝙮𝙚𝙧 𝙈𝙖𝙧𝙠"
        mark = "🔥 Active" if player.get('slayer_mark') else "🔒 Locked"
    else:
        mark_label = "🌑 𝘿𝙚𝙢𝙤𝙣 𝙈𝙖𝙧𝙠"
        mark = "🌑 Active" if player.get('demon_mark') else "🔒 Locked"
    location = player.get('location', 'asakusa').title()
    game_name = player.get('name', '—')
    tg_username = player.get('username') or update.effective_user.username or ''
    uname_display = f"{game_name}" + (f" (@{tg_username})" if tg_username else "")

    lvl_str  = f"〔{'0' + str(level) if level < 10 else str(level)}〕"
    p_bar    = hp_bar(player['hp'], player['max_hp'])
    s_bar    = hp_bar(player['sta'], player['max_sta'])

    # Clan info
    clan_line = ""
    if player.get('clan_id'):
        clan = col("clans").find_one({"id": player['clan_id']})
        if clan:
            role = player.get('clan_role', 'recruit').title()
            clan_line = f"🏯 𝘾𝙡𝙖𝙣      : {clan['name']} [{role}]\n"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{player['style_emoji']} Techniques", callback_data='profile_techniques'),
            InlineKeyboardButton("📊 Stats",                             callback_data='profile_more_info'),
        ]
    ])

    text = (
        f"╔═════════════════════╗\n"
        f"      {fe} 𝙋𝙍𝙊𝙁𝙄𝙇𝙀\n"
        f"   「 {player['name'].upper()} 」\n"
        f"╚═════════════════════╝\n"
        f"👤 𝙉𝙖𝙢𝙚      : {uname_display}\n"
        f"🏅 𝙍𝙖𝙣𝙠      : {player['rank']} {player['rank_kanji']}\n"
        f"{player['style_emoji']} 𝙎𝙩𝙮𝙡𝙚     : {player['style']}\n"
        f"📖 𝙊𝙧𝙞𝙜𝙞𝙣    : {player.get('story', '—')}\n"
        f"📍 𝙇𝙤𝙘𝙖𝙩𝙞𝙤𝙣  : {location}\n"
        f"⚔️ 𝙇𝙚𝙫𝙚𝙡     : {lvl_str}\n"
        f"{clan_line}"
        f"━━━━━━━━━━━ 📊 ━━━━━━━\n"
        f"❤️  HP  : {player['hp']}/{player['max_hp']}  {p_bar}\n"
        f"🌀  STA : {player['sta']}/{player['max_sta']}  {s_bar}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ 𝙓𝙋        : {player['xp']:,}\n"
        f"👹 𝙎𝙡𝙖𝙞𝙣     : {player['demons_slain']}\n"
        f"📜 𝙈𝙞𝙨𝙨𝙞𝙤𝙣𝙨  : {player['missions_done']}\n"
        f"💀 𝘿𝙚𝙖𝙩𝙝𝙨    : {player['deaths']}\n"
        f"{mark_label} : {mark}\n"
        f"🍖 𝘿𝙚𝙫𝙤𝙪𝙧      : {player.get('devour_stacks', 0)}/20\n"
        f"💠 𝙎𝙠𝙞𝙡𝙡 𝙋𝙩𝙨    : {player.get('skill_points', 0)} SP\n"
        f"💰 𝘽𝙖𝙡𝙖𝙣𝙘𝙚     : {player['yen']:,}¥\n"
        f"━━━━━━━━━━━━━━━━━━━━━━"
    )

    banner_media = _profile_banner_media(player)
    if banner_media:
        target_msg = update.callback_query.message if update.callback_query else update.message
        await target_msg.reply_photo(banner_media, caption=text[:1024], parse_mode=None, reply_markup=keyboard)
    elif update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=None, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode=None, reply_markup=keyboard)


async def profile_techniques(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    if not player:
        await query.answer("No character found!", show_alert=True)
        return
    level   = get_level(player['xp'])

    from config import TECHNIQUES
    all_forms     = TECHNIQUES.get(player['style'], [])
    unlocked_nums = {f['form'] for f in get_unlocked_forms(player['style'], level)}

    lines = [f"{player['style_emoji']} *{player['style'].upper()}*\n"]
    for form in all_forms:
        if form['form'] in unlocked_nums:
            lines.append(f"✅ *Form {form['form']}* — {form['name']}")
            lines.append(f"   💥 DMG: {form['dmg_min']}-{form['dmg_max']}  |  🌀 STA: {form['sta_cost']}")
        else:
            req = f"Lv.{1 + (form['form']-1)*3}"
            lines.append(f"🔒 *Form {form['form']}* — {form['name']}  _({req} required)_")

    arts = get_arts(user_id)
    if arts:
        lines.append("\n━━ 🎴 EXTRA ARTS ━━━━━━━")
        for art in arts:
            lines.append(f"  {art['art_emoji']} *{art['art_name']}*  _({art['source']})_")

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='goto_profile')]])
    await _safe_edit(query, '\n'.join(lines), parse_mode='Markdown', reply_markup=keyboard)


async def profile_more_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    if not player:
        await query.answer("No character found!", show_alert=True)
        return

    p_bar = hp_bar(player['hp'],  player['max_hp'])
    s_bar = hp_bar(player['sta'], player['max_sta'])

    text = (
        f"📊 *DETAILED STATS — {player['name'].upper()}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"❤️  HP:        *{player['hp']}/{player['max_hp']}*  {p_bar}\n"
        f"🌀  STA:       *{player['sta']}/{player['max_sta']}*  {s_bar}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💪  STR:       *{player['str_stat']}*\n"
        f"⚡  SPD:       *{player['spd']}*\n"
        f"🛡️  DEF:       *{player['def_stat']}*\n"
        f"🔮  Potential: *{player.get('potential', 0)}%*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️  Sword:     _{player.get('equipped_sword','None')}_"
        + (_sword_buff(player.get('equipped_sword','')) ) + "\n"
        + f"👘  Armor:     _{player.get('equipped_armor','None')}_"
        + (_armor_buff(player.get('equipped_armor','')) ) + "\n"
        f"💠  Skill Pts: *{player.get('skill_points', 0)} SP*\n"
        f"🍖  Devour:    *{player.get('devour_stacks', 0)}/20*\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='goto_profile')]])
    await _safe_edit(query, text, parse_mode='Markdown', reply_markup=keyboard)


async def setbanner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found. Use /start first.")
        return

    if not update.message.photo and not context.args:
        await update.message.reply_text(
            "*SET PROFILE BANNER*\n\n"
            "Send a photo with `/setbanner`\n"
            "or send `/setbanner https://example.com/banner.jpg`\n\n"
            "Your banner will appear on `/profile`.",
            parse_mode='Markdown'
        )
        return

    url = None
    if context.args:
        maybe_url = context.args[-1].strip()
        if maybe_url.startswith("http"):
            url = maybe_url

    update_fields = {}
    if update.message.photo:
        update_fields["profile_banner_file_id"] = update.message.photo[-1].file_id
        update_fields["profile_banner_url"] = None
    elif url:
        update_fields["profile_banner_url"] = url
        update_fields["profile_banner_file_id"] = None
    else:
        await update.message.reply_text("Send a photo or a direct http image URL.")
        return

    update_player(user_id, **update_fields)
    await update.message.reply_text(
        "Profile banner updated.\nUse `/profile` to see it.",
        parse_mode='Markdown'
    )


async def clearbanner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found. Use /start first.")
        return

    update_player(user_id, profile_banner_file_id=None, profile_banner_url=None)
    await update.message.reply_text("Profile banner cleared.")
