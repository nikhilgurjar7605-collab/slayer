from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, get_leaderboard
from utils.helpers import get_level

MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}

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


def rankings_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗡️ Top Slayers",  callback_data='rankings_slayers'),
            InlineKeyboardButton("👹 Top Demons",   callback_data='rankings_demons'),
        ],
        [
            InlineKeyboardButton("💰 Richest",      callback_data='rankings_richest'),
            InlineKeyboardButton("💀 Most Kills",   callback_data='rankings_kills'),
        ],
        [
            InlineKeyboardButton("⭐ Top Level",    callback_data='rankings_level'),
            InlineKeyboardButton("💠 Most SP",      callback_data='rankings_sp'),
        ],
        [
            InlineKeyboardButton("🎯 Highest Bounties", callback_data='rankings_bounty'),
        ]
    ])

async def rankings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message if update.message else update.callback_query.message
    await msg.reply_text(
        "🏆 *GLOBAL RANKINGS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Choose a category to view:",
        parse_mode='Markdown',
        reply_markup=rankings_keyboard()
    )

async def rankings_slayers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    rows = get_leaderboard('slayers')
    lines = ["🏆 *TOP SLAYERS*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, p in enumerate(rows, 1):
        medal = MEDALS.get(i, f"`{i}.`")
        you   = " 👈 *(You)*" if p['user_id'] == user_id else ""
        lv    = get_level(p['xp'])
        lines.append(f"{medal} *{p['name']}*{you}\n     🏅 {p['rank']}  |  ⚔️ Lv.{lv}  |  💀 {p['demons_slain']} kills")
    if not rows:
        lines.append("_No slayers yet — be the first!_")
    await _safe_edit(query, '\n'.join(lines), parse_mode='Markdown', reply_markup=rankings_keyboard())

async def rankings_demons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    rows = get_leaderboard('demons')
    lines = ["🏆 *TOP DEMONS*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, p in enumerate(rows, 1):
        medal = MEDALS.get(i, f"`{i}.`")
        you   = " 👈 *(You)*" if p['user_id'] == user_id else ""
        lv    = get_level(p['xp'])
        lines.append(f"{medal} *{p['name']}*{you}\n     🏅 {p['rank']}  |  👹 Lv.{lv}  |  💀 {p['demons_slain']} kills")
    if not rows:
        lines.append("_No demons yet — be the first!_")
    await _safe_edit(query, '\n'.join(lines), parse_mode='Markdown', reply_markup=rankings_keyboard())

async def rankings_richest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    rows = get_leaderboard('richest')
    lines = ["💰 *RICHEST PLAYERS*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, p in enumerate(rows, 1):
        medal = MEDALS.get(i, f"`{i}.`")
        you   = " 👈 *(You)*" if p['user_id'] == user_id else ""
        fe    = '🗡️' if p['faction'] == 'slayer' else '👹'
        lines.append(f"{medal} {fe} *{p['name']}*{you}\n     💰 {p['yen']:,}¥")
    if not rows:
        lines.append("_No data yet._")
    await _safe_edit(query, '\n'.join(lines), parse_mode='Markdown', reply_markup=rankings_keyboard())

async def rankings_kills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    rows = get_leaderboard('kills')
    lines = ["💀 *MOST KILLS — ALL FACTIONS*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, p in enumerate(rows, 1):
        medal = MEDALS.get(i, f"`{i}.`")
        you   = " 👈 *(You)*" if p['user_id'] == user_id else ""
        fe    = '🗡️' if p['faction'] == 'slayer' else '👹'
        lv    = get_level(p['xp'])
        lines.append(f"{medal} {fe} *{p['name']}*{you}\n     💀 {p['demons_slain']} kills  |  Lv.{lv}")
    if not rows:
        lines.append("_No kills recorded yet._")
    await _safe_edit(query, '\n'.join(lines), parse_mode='Markdown', reply_markup=rankings_keyboard())


async def rankings_level(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    from utils.database import get_leaderboard
    from utils.helpers import get_level
    rows = get_leaderboard('level')
    lines = ["⭐ *TOP LEVELS*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, p in enumerate(rows, 1):
        medal = MEDALS.get(i, f"`{i}.`")
        you   = " 👈 *(You)*" if p['user_id'] == user_id else ""
        fe    = '🗡️' if p['faction'] == 'slayer' else '👹'
        lv    = get_level(p['xp'])
        lines.append(f"{medal} {fe} *{p['name']}*{you}\n     ⭐ Lv.{lv}  |  ✨ {p['xp']:,} XP")
    if not rows:
        lines.append("_No data yet._")
    await _safe_edit(query, '\n'.join(lines), parse_mode='Markdown', reply_markup=rankings_keyboard())


async def rankings_sp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    from utils.database import get_leaderboard
    rows = get_leaderboard('sp')
    lines = ["💠 *MOST SKILL POINTS SPENT*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    for i, p in enumerate(rows, 1):
        medal = MEDALS.get(i, f"`{i}.`")
        you   = " 👈 *(You)*" if p['user_id'] == user_id else ""
        fe    = '🗡️' if p['faction'] == 'slayer' else '👹'
        lines.append(f"{medal} {fe} *{p['name']}*{you}\n     💠 {p.get('skill_points',0)} SP remaining")
    if not rows:
        lines.append("_No data yet._")
    await _safe_edit(query, '\n'.join(lines), parse_mode='Markdown', reply_markup=rankings_keyboard())

async def rankings_bounty(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    top_bounty = get_leaderboard('bounty', limit=10)

    text = "🎯 *MOST WANTED (Highest Bounties)*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    if not top_bounty:
        text += "No active bounties yet.\n"
    else:
        for i, p in enumerate(top_bounty):
            bounty_amt = p.get('bounty', 5000)
            faction_emoji = "🗡️" if p.get('faction') == 'slayer' else "👹"
            text += f"`{i+1}.` {faction_emoji} *{p.get('name', 'Unknown')}* — 💰 {bounty_amt:,}\n"

    await _safe_edit(
        query,
        text,
        reply_markup=rankings_keyboard(),
        parse_mode='Markdown'
    )
