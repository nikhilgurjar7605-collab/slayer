from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import col, get_player
from utils.helpers import get_level

async def _safe_edit(query, text, **kwargs):
    """Edit a message safely, falling back to reply on failure."""
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        elif any(x in err.lower() for x in ("can't be edited", "message to edit not found", "not found")):
            try:
                await query.message.reply_text(text, **kwargs)
            except Exception:
                pass
        else:
            raise
    except TimedOut:
        pass




async def clan_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """List all clans — available to everyone."""
    page = 0
    if context.args:
        try:
            page = max(0, int(context.args[0]) - 1)
        except ValueError:
            pass

    PAGE_SIZE = 10
    total     = col("clans").count_documents({})
    clans     = list(col("clans").find().sort("xp", -1).skip(page * PAGE_SIZE).limit(PAGE_SIZE))

    if not clans:
        await (update.message or update.callback_query.message).reply_text(
            "🏯 No clans exist yet!\n\nUse `/clan createclan [name]` to found one.",
            parse_mode='Markdown'
        )
        return

    # Clan rank badges
    def rank_badge(xp):
        if xp >= 100000: return "💀"
        if xp >= 50000:  return "🔴"
        if xp >= 20000:  return "🟡"
        if xp >= 5000:   return "🟢"
        return "⚪"

    lines = [
        f"╔══════════════════════╗",
        f"      🏯 𝘾𝙇𝘼𝙉 𝙇𝙄𝙎𝙏",
        f"   Page {page+1} / {max(1,(total+PAGE_SIZE-1)//PAGE_SIZE)}",
        f"╚══════════════════════╝\n",
        f"📊 Total clans: *{total}*\n",
        f"━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    medals = ['🥇','🥈','🥉']
    for i, clan in enumerate(clans):
        rank_num = page * PAGE_SIZE + i + 1
        medal    = medals[rank_num-1] if rank_num <= 3 else f"`{rank_num}.`"
        members  = clan.get('members', [])
        if isinstance(members, str):
            import json
            try: members = json.loads(members)
            except: members = []
        badge    = rank_badge(clan.get('xp', 0))
        leader   = get_player(clan.get('leader_id'))
        lname    = leader['name'] if leader else "Unknown"

        lines.append(
            f"{medal} {badge} *{clan['name']}*\n"
            f"   👑 {lname}  |  👥 {len(members)}  |  ⭐ {clan.get('xp',0):,} XP"
        )

    lines.append(f"\n━━━━━━━━━━━━━━━━━━━━━")

    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"clanlist_page_{page-1}"))
    if (page+1)*PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"clanlist_page_{page+1}"))
    if nav:
        buttons.append(nav)

    msg = update.message if update.message else update.callback_query.message
    if update.callback_query:
        await update.callback_query.edit_message_text(
            '\n'.join(lines), parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
        )
    else:
        await msg.reply_text(
            '\n'.join(lines), parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
        )


async def clanlist_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page  = int(query.data.split('_')[-1])
    context.args = [str(page + 1)]
    await clan_list(update, context)
