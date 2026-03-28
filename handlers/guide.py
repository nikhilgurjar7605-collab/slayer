from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player

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


async def guide(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    faction = player['faction'] if player else 'slayer'
    fe = '🗡️' if faction == 'slayer' else '👹'

    pages = {
        'start':    _page_start(),
        'battle':   _page_battle(),
        'skills':   _page_skills(),
        'economy':  _page_economy(),
        'social':   _page_social(),
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚔️ 𝘽𝙖𝙩𝙩𝙡𝙚", callback_data='guide_battle'),
            InlineKeyboardButton("🌳 𝙎𝙠𝙞𝙡𝙡𝙨", callback_data='guide_skills'),
        ],
        [
            InlineKeyboardButton("💰 𝙀𝙘𝙤𝙣𝙤𝙢𝙮", callback_data='guide_economy'),
            InlineKeyboardButton("👥 𝙎𝙤𝙘𝙞𝙖𝙡", callback_data='guide_social'),
        ],
    ])

    msg = update.message if update.message else update.callback_query.message
    if update.callback_query:
        await update.callback_query.edit_message_text(
            pages['start'], parse_mode='Markdown', reply_markup=keyboard
        )
    else:
        await msg.reply_text(pages['start'], parse_mode='Markdown', reply_markup=keyboard)


def _page_start():
    return (
        "╔══════════════════════╗\n"
        "      📖 𝙂𝙐𝙄𝘿𝙀\n"
        "    「 𝙃𝙊𝙒 𝙏𝙊 𝙋𝙇𝘼𝙔 」\n"
        "╚══════════════════════╝\n\n"
        "🌸 *𝙒𝙀𝙇𝘾𝙊𝙈𝙀 𝙏𝙊 𝘿𝙀𝙈𝙊𝙉 𝙎𝙇𝘼𝙔𝙀𝙍 𝙍𝙋𝙂*\n\n"
        "╰➤ Use /start to create your character\n"
        "╰➤ Choose *Slayer* 🗡️ or *Demon* 👹\n"
        "╰➤ Pick your *breathing style* or *demon art*\n"
        "╰➤ Choose your *origin story* for a bonus\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "🎁 *𝙉𝙀𝙒 𝙋𝙇𝘼𝙔𝙀𝙍 𝘽𝙊𝙉𝙐𝙎*\n\n"
        "╰➤ 💰 +500¥ starting bonus\n"
        "╰➤ ⭐ +200 XP head start\n"
        "╰➤ 🍶 ×3 Full Recovery Gourd\n"
        "╰➤ 💊 ×5 Stamina Pill\n"
        "╰➤ 🌿 ×2 Wisteria Antidote\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "_Select a topic below to learn more_ 👇"
    )


def _page_battle():
    return (
        "╔══════════════════════╗\n"
        "      ⚔️ 𝘽𝘼𝙏𝙏𝙇𝙀 𝙂𝙐𝙄𝘿𝙀\n"
        "╚══════════════════════╝\n\n"
        "*𝙃𝙊𝙒 𝙏𝙊 𝙁𝙄𝙂𝙃𝙏*\n\n"
        "╰➤ `/explore` — Find enemies in your region\n"
        "╰➤ Press *⚔️ Fight* to start the battle\n"
        "╰➤ Press *⚔️ Attack* for basic attack\n"
        "╰➤ Press *💨 Technique* for special moves\n"
        "╰➤ Press *🧪 Items* to use potions\n"
        "╰➤ Press *🏃 Flee* to escape\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝙎𝙋𝙄𝙍𝙄𝙏𝙐𝘼𝙇 𝙋𝙍𝙀𝙎𝙎𝙐𝙍𝙀*\n\n"
        "╰➤ Every battle has a pressure roll\n"
        "╰➤ 🔥 Overwhelming → +25% ATK\n"
        "╰➤ 💪 Dominant → +15% ATK\n"
        "╰➤ 😨 Overwhelmed → -15% ATK\n"
        "╰➤ 💀 Crushed → -25% ATK\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝘽𝙊𝙎𝙎 𝙀𝙉𝘾𝙊𝙐𝙉𝙏𝙀𝙍𝙎*\n\n"
        "╰➤ 1 boss per region — appears randomly\n"
        "╰➤ Boss cooldown: *20 explores* after kill\n"
        "╰➤ Boss enrages at *50% HP* (+30% ATK)\n"
        "╰➤ 3× rewards on boss kill\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝘾𝙊𝙈𝘽𝙊 𝙎𝙔𝙎𝙏𝙀𝙈*\n\n"
        "╰➤ 3 hits in a row → 🔥 *COMBO ×3* +25% DMG\n"
        "╰➤ Taking damage resets your combo\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝘿𝙀𝙑𝙊𝙐𝙍 𝙎𝙔𝙎𝙏𝙀𝙈* 🍖\n\n"
        "╰➤ Slayer kills Slayer-type enemy → +1 STR +1 DEF\n"
        "╰➤ Demon kills Demon-type enemy → +1 STR +1 SPD\n"
        "╰➤ Max 20 devour stacks"
    )


def _page_skills():
    from config import TECHNIQUES
    skill_preview = ""
    try:
        styles = list(TECHNIQUES.keys())[:4]
        skill_preview = f"\n📋 *{len(TECHNIQUES)} styles/arts* with forms\n"
        for style in styles:
            forms = TECHNIQUES[style]
            skill_preview += f"\n  ⚔️ *{style}* — {len(forms)} forms"
        skill_preview += "\n  _...and more_"
    except Exception:
        skill_preview = ""

    return (
        "╔══════════════════════╗\n"
        "      💠 𝙎𝙆𝙄𝙇𝙇 𝙂𝙐𝙄𝘿𝙀\n"
        "╚══════════════════════╝\n\n"
        "*𝙃𝙊𝙒 𝙏𝙊 𝙀𝘼𝙍𝙉 𝙎𝙆𝙄𝙇𝙇 𝙋𝙊𝙄𝙉𝙏𝙎 (𝙎𝙋)*\n\n"
        "╰➤ 💠 50% chance per level gained in battle\n"
        "╰➤ 💠 *Always* 1 SP for killing a boss\n"
        "╰➤ 💠 PvP win → +1 SP guaranteed\n"
        "╰➤ ❌ *SP never earned from other sources*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝙎𝙆𝙄𝙇𝙇 𝙏𝙍𝙀𝙀 𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎*\n\n"
        "╰➤ `/skilltree` — Browse all skill trees\n"
        "╰➤ `/skilllist` — All skills listed\n"
        "╰➤ `/skillbuy [name]` — Purchase a skill\n"
        "╰➤ `/skillinfo [name]` — Full skill details\n"
        "╰➤ `/skills` — Your owned skills + bonuses\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝙎𝙆𝙄𝙇𝙇 𝙏𝙍𝙀𝙀 𝙋𝙍𝙀𝙑𝙄𝙀𝙒*\n"
        f"{skill_preview}\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝙎𝙏𝙔𝙇𝙀 / 𝘼𝙍𝙏 𝘾𝙊𝙈𝙈𝘼𝙉𝘿𝙎*\n\n"
        "╰➤ `/breathing` — View your breathing + forms\n"
        "╰➤ `/art` — View your demon art + forms\n"
        "╰➤ `/info` — Detailed stat view of your style\n"
        "╰➤ `/changestyle` — Change style *(500,000¥)*\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝙏𝙍𝘼𝙑𝙀𝙇*\n\n"
        "╰➤ `/travel` — Move between regions\n"
        "╰➤ Higher regions = stronger enemies + better loot"
    )


def _page_economy():
    return (
        "╔══════════════════════╗\n"
        "      💰 𝙀𝘾𝙊𝙉𝙊𝙈𝙔\n"
        "╚══════════════════════╝\n\n"
        "*𝙀𝘼𝙍𝙉𝙄𝙉𝙂 𝙔𝙀𝙉*\n\n"
        "╰➤ Win battles → Yen + XP rewards\n"
        "╰➤ Complete `/mission` — Bonus Yen\n"
        "╰➤ `/daily` — Daily reward + streak bonus\n"
        "╰➤ Sell items on `/market`\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝙎𝙃𝙊𝙋𝙋𝙄𝙉𝙂*\n\n"
        "╰➤ `/shop` — Buy swords, armor, potions\n"
        "╰➤ `/buy [code] [amount]` — Quick buy\n"
        "╰➤ `/market` — Player listings\n"
        "╰➤ `/blackmarket` — Rare items (night only)\n"
        "╰➤ `/auction` — Bid on rare items\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝘽𝘼𝙉𝙆*\n\n"
        "╰➤ `/bank` — Deposit Yen for interest\n"
        "╰➤ Upgrade bank for higher interest rates\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝙍𝙀𝙁𝙀𝙍𝙍𝘼𝙇 𝙍𝙀𝙒𝘼𝙍𝘿𝙎*\n\n"
        "╰➤ `/referral` — Get your invite link\n"
        "╰➤ Friend joins → You get +500¥ +500 XP\n"
        "╰➤ Friend gets → +300¥ +300 XP + items"
    )


def _page_social():
    return (
        "╔══════════════════════╗\n"
        "      👥 𝙎𝙊𝘾𝙄𝘼𝙇 𝙂𝙐𝙄𝘿𝙀\n"
        "╚══════════════════════╝\n\n"
        "*𝘾𝙇𝘼𝙉𝙎*\n\n"
        "╰➤ `/clan createclan [name]` — Found a clan\n"
        "╰➤ `/clan invite @user` — Invite members\n"
        "╰➤ `/claninfo` — View clan stats + treasury\n"
        "╰➤ `/clandeposit [item]` — Add to treasury\n"
        "╰➤ `/setclanlink [url]` — Set group link\n"
        "╰➤ Killing monsters adds XP to your clan!\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝙋𝙑𝙋 𝘿𝙐𝙀𝙇𝙎*\n\n"
        "╰➤ In a group: reply to someone → `/challenge`\n"
        "╰➤ Or: `/challenge @username`\n"
        "╰➤ Battle plays out in the group chat\n"
        "╰➤ Winner gets +300 XP +150¥ +1 SP\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝙋𝘼𝙍𝙏𝙔*\n\n"
        "╰➤ `/party` — Create/manage your party\n"
        "╰➤ Allies fight alongside you in battle\n"
        "╰➤ `/joinbattle` — Join a co-op fight\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "*𝙂𝙄𝙁𝙏𝙄𝙉𝙂*\n\n"
        "╰➤ Reply to a message → `/gift [item]`\n"
        "╰➤ Or: `/gift @username [item]`"
    )


async def guide_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page  = query.data.split('_')[1]

    pages = {
        'battle':  _page_battle(),
        'skills':  _page_skills(),
        'economy': _page_economy(),
        'social':  _page_social(),
    }

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚔️ 𝘽𝙖𝙩𝙩𝙡𝙚", callback_data='guide_battle'),
            InlineKeyboardButton("🌳 𝙎𝙠𝙞𝙡𝙡𝙨", callback_data='guide_skills'),
        ],
        [
            InlineKeyboardButton("💰 𝙀𝙘𝙤𝙣𝙤𝙢𝙮", callback_data='guide_economy'),
            InlineKeyboardButton("👥 𝙎𝙤𝙘𝙞𝙖𝙡", callback_data='guide_social'),
        ],
        [
            InlineKeyboardButton("🏠 𝙃𝙤𝙢𝙚", callback_data='guide_home'),
        ],
    ])

    text = pages.get(page, _page_start())
    await _safe_edit(query, text, parse_mode='Markdown', reply_markup=keyboard)


async def guide_home_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await guide(update, context)
