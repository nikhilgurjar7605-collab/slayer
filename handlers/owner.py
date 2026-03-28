from telegram.error import BadRequest, TimedOut
"""
/ownermode — Toggle owner god mode (bypasses all restrictions, cooldowns, costs)
/owneraccess — Full overview of owner powers
/bypass [command] — Owner executes any player action on anyone
/ownersetlevel @user [level] — Set exact level
/ownersetstyle @user [style] — Force any style including ultra legendary  
/ownergive @user [item/yen/xp] [amount] — Mass give with no limits
/ownerreset @user — Full reset
/ownerban @user / /ownerunban @user
/ownermsg @user [text] — Send anonymous bot message to any user
/ownerstats — Full bot statistics
"""
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, add_item, col, _player_defaults
from config import OWNER_ID, BREATHING_STYLES, DEMON_ARTS, TECHNIQUES
from utils.helpers import get_level, _xp_threshold, get_rank

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




def is_owner(uid):
    return uid == OWNER_ID


def _find_any_player(arg):
    """Find player by @username, user_id, or name."""
    arg = str(arg).strip()
    if arg.startswith('@'):
        p = col("players").find_one({"username": {"$regex": f"^{arg.lstrip('@')}$", "$options": "i"}})
    elif arg.isdigit():
        p = col("players").find_one({"user_id": int(arg)})
    else:
        p = col("players").find_one({"name": {"$regex": arg, "$options": "i"}})
    if p:
        p.pop("_id", None)
    return p


LEVEL_STAT_GROWTH = {
    "str_stat": 2,
    "spd": 1,
    "def_stat": 1,
    "max_hp": 15,
    "max_sta": 10,
}


def _scaled_stats_for_level(player: dict, target_level: int) -> dict:
    faction = player.get("faction", "slayer")
    defaults = _player_defaults(faction=faction)
    current_level = max(1, get_level(player.get("xp", 0)))
    current_steps = current_level - 1
    target_steps = max(0, target_level - 1)

    scaled = {}
    for stat, growth in LEVEL_STAT_GROWTH.items():
        base_value = int(defaults.get(stat, 0) or 0)
        current_value = int(player.get(stat, base_value) or base_value)
        non_level_bonus = current_value - (base_value + (growth * current_steps))
        scaled[stat] = base_value + max(0, non_level_bonus) + (growth * target_steps)

    scaled["hp"] = scaled["max_hp"]
    scaled["sta"] = scaled["max_sta"]
    return scaled


# ── /ownermode ────────────────────────────────────────────────────────────

async def ownermode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    current = col("settings").find_one({"key": "owner_godmode"})
    new_val  = not (current.get("value", False) if current else False)
    col("settings").update_one(
        {"key": "owner_godmode"},
        {"$set": {"key": "owner_godmode", "value": new_val}},
        upsert=True
    )
    status = "✅ *ENABLED*" if new_val else "🔒 *DISABLED*"
    await update.message.reply_text(
        f"👑 *OWNER GOD MODE: {status}*\n\n"
        f"{'✅ All cooldowns bypassed' if new_val else ''}\n"
        f"{'✅ All costs waived' if new_val else ''}\n"
        f"{'✅ No restrictions apply' if new_val else ''}",
        parse_mode='Markdown'
    )


def owner_godmode_active():
    doc = col("settings").find_one({"key": "owner_godmode"})
    return doc.get("value", False) if doc else False


# ── /owneraccess ──────────────────────────────────────────────────────────

async def owneraccess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    godmode = owner_godmode_active()
    total_players = col("players").count_documents({})
    total_clans   = col("clans").count_documents({})
    total_logs    = col("admin_logs").count_documents({})

    await update.message.reply_text(
        f"╔══════════════════════╗\n"
        f"   👑 𝙊𝙒𝙉𝙀𝙍 𝘼𝘾𝘾𝙀𝙎𝙎\n"
        f"╚══════════════════════╝\n\n"
        f"⚡ God Mode: {'✅ ON' if godmode else '🔒 OFF'} — `/ownermode`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *BOT STATS*\n"
        f"  👥 Players: *{total_players}*\n"
        f"  🏯 Clans:   *{total_clans}*\n"
        f"  📋 Logs:    *{total_logs}*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛠️ *OWNER COMMANDS*\n\n"
        f"  `/ownermode` — Toggle god mode\n"
        f"  `/ownersetlevel @user [lv]` — Set level\n"
        f"  `/ownersetstyle @user [style]` — Force any style\n"
        f"  `/ownergive @user yen [amount]`\n"
        f"  `/ownergive @user xp [amount]`\n"
        f"  `/ownergive @user item [name]`\n"
        f"  `/ownergive @user sp [amount]`\n"
        f"  `/ownerreset @user` — Wipe player\n"
        f"  `/ownerban @user` — Permanent ban\n"
        f"  `/ownerunban @user` — Unban\n"
        f"  `/ownermsg @user [text]` — DM any user\n"
        f"  `/ownerstats` — Full database stats\n"
        f"  `/ownerplayers` — List all players\n"
        f"  `/logs` `/logstats` `/logsearch` — Audit logs\n"
        f"  `/giveultimate @user` — Give Absolute Biokinesis\n"
        f"  `/addsudo` `/removesudo` `/listadmins`\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"_You have full unrestricted access to all bot systems._",
        parse_mode='Markdown'
    )


# ── /ownersetlevel ────────────────────────────────────────────────────────

async def ownersetlevel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    if len(context.args or []) < 2:
        await update.message.reply_text("Usage: `/ownersetlevel @user [level]`", parse_mode='Markdown')
        return

    target = _find_any_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    try:
        new_level = max(1, min(500, int(context.args[1])))
    except ValueError:
        await update.message.reply_text("❌ Invalid level number.")
        return

    new_xp = _xp_threshold(new_level)
    new_rank = get_rank(target.get('faction', 'slayer'), new_xp)
    scaled_stats = _scaled_stats_for_level(target, new_level)
    update_player(
        target['user_id'],
        xp=new_xp,
        level=new_level,
        rank=new_rank['name'],
        rank_kanji=new_rank['kanji'],
        **scaled_stats,
    )

    from handlers.logs import log_action
    log_action(uid, "ownersetlevel", target['user_id'], target['name'], f"→ Lv.{new_level}")

    await update.message.reply_text(
        f"✅ *{target['name']}* set to *Lv.{new_level}*\n"
        f"XP: *{new_xp:,}*\n"
        f"HP/STA reset to match the new level exactly.",
        parse_mode='Markdown'
    )
    try:
        await context.bot.send_message(
            chat_id=target['user_id'],
            text=f"⚡ *Admin set your level to Lv.{new_level}!*\n\nYour stats have been updated.",
            parse_mode='Markdown'
        )
    except Exception:
        pass


# ── /ownersetstyle ────────────────────────────────────────────────────────

async def ownersetstyle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    if len(context.args or []) < 2:
        await update.message.reply_text(
            "Usage: `/ownersetstyle @user [style name]`\n\n"
            "Can set ANY style including Ultra Legendary.",
            parse_mode='Markdown'
        )
        return

    target     = _find_any_player(context.args[0])
    style_name = ' '.join(context.args[1:])

    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    all_styles = BREATHING_STYLES + DEMON_ARTS
    style = next((s for s in all_styles if s['name'].lower() == style_name.lower()), None)
    if not style:
        style = next((s for s in all_styles if style_name.lower() in s['name'].lower()), None)
    if not style:
        await update.message.reply_text(
            f"❌ Style not found: *{style_name}*\n\nTry the exact name from `/infoall`",
            parse_mode='Markdown'
        )
        return

    update_player(target['user_id'], style=style['name'], style_emoji=style['emoji'])

    from utils.database import apply_style_stat_bonus
    apply_style_stat_bonus(target['user_id'], style['name'])

    from handlers.logs import log_action
    log_action(uid, "ownersetstyle", target['user_id'], target['name'], style['name'])

    await update.message.reply_text(
        f"✅ *{target['name']}* → *{style['emoji']} {style['name']}*\n{style['rarity']}",
        parse_mode='Markdown'
    )
    try:
        await context.bot.send_message(
            chat_id=target['user_id'],
            text=f"✨ *Your style has been changed!*\n\n{style['emoji']} *{style['name']}*\n{style['rarity']}",
            parse_mode='Markdown'
        )
    except Exception:
        pass


# ── /ownergive ────────────────────────────────────────────────────────────

async def ownergive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    if len(context.args or []) < 3:
        await update.message.reply_text(
            "Usage:\n"
            "`/ownergive @user yen [amount]`\n"
            "`/ownergive @user xp [amount]`\n"
            "`/ownergive @user sp [amount]`\n"
            "`/ownergive @user item [item name]`\n"
            "`/ownergive @user scroll [style name]`",
            parse_mode='Markdown'
        )
        return

    target  = _find_any_player(context.args[0])
    gtype   = context.args[1].lower()
    value   = ' '.join(context.args[2:])

    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    from handlers.logs import log_action
    msg = ""

    if gtype == 'yen':
        try:
            amount = int(value.replace(',', ''))
        except ValueError:
            await update.message.reply_text("❌ Invalid amount."); return
        update_player(target['user_id'], yen=target.get('yen', 0) + amount)
        msg = f"💰 *+{amount:,}¥* → *{target['name']}*"
        log_action(uid, "ownergive_yen", target['user_id'], target['name'], f"{amount:,}¥")

    elif gtype == 'xp':
        try:
            amount = int(value.replace(',', ''))
        except ValueError:
            await update.message.reply_text("❌ Invalid amount."); return
        update_player(target['user_id'], xp=target.get('xp', 0) + amount)
        new_lv = get_level(target.get('xp', 0) + amount)
        msg = f"⭐ *+{amount:,} XP* → *{target['name']}* (now Lv.{new_lv})"
        log_action(uid, "ownergive_xp", target['user_id'], target['name'], f"{amount:,} XP")

    elif gtype == 'sp':
        try:
            amount = int(value)
        except ValueError:
            await update.message.reply_text("❌ Invalid amount."); return
        update_player(target['user_id'], skill_points=target.get('skill_points', 0) + amount)
        msg = f"💠 *+{amount} SP* → *{target['name']}*"
        log_action(uid, "ownergive_sp", target['user_id'], target['name'], f"{amount} SP")

    elif gtype == 'item':
        add_item(target['user_id'], value, 'item')
        msg = f"🎁 *{value}* → *{target['name']}*"
        log_action(uid, "ownergive_item", target['user_id'], target['name'], value)

    elif gtype == 'scroll':
        scroll_name = f"Scroll: {value}"
        add_item(target['user_id'], scroll_name, 'scroll')
        msg = f"📜 *{scroll_name}* → *{target['name']}*"
        log_action(uid, "ownergive_scroll", target['user_id'], target['name'], scroll_name)

    else:
        await update.message.reply_text(f"❌ Unknown type: {gtype}")
        return

    await update.message.reply_text(f"✅ {msg}", parse_mode='Markdown')
    try:
        await context.bot.send_message(
            chat_id=target['user_id'],
            text=f"🎁 *You received a gift from the admin!*\n\n{msg}",
            parse_mode='Markdown'
        )
    except Exception:
        pass


# ── /ownerreset ───────────────────────────────────────────────────────────

async def ownerreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/ownerreset @user`", parse_mode='Markdown')
        return

    target = _find_any_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    tid = target['user_id']
    col("players").delete_one({"user_id": tid})
    for c in ["inventory", "battle_state", "skill_tree", "arts", "parties", "referrals"]:
        col(c).delete_many({"user_id": tid})

    from handlers.logs import log_action
    log_action(uid, "ownerreset", tid, target['name'])

    await update.message.reply_text(
        f"✅ *{target['name']}* (`{tid}`) has been fully reset.\n_They can /start to create a new character._",
        parse_mode='Markdown'
    )


# ── /ownerban / /ownerunban ───────────────────────────────────────────────

async def ownerban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/ownerban @user [reason]`", parse_mode='Markdown')
        return

    target = _find_any_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    reason = ' '.join(context.args[1:]) if len(context.args) > 1 else "Owner ban"
    col("players").update_one({"user_id": target['user_id']}, {"$set": {"banned": 1, "ban_reason": reason}})

    from handlers.logs import log_action
    log_action(uid, "ownerban", target['user_id'], target['name'], reason)

    await update.message.reply_text(
        f"🚫 *{target['name']}* banned.\nReason: _{reason}_",
        parse_mode='Markdown'
    )


async def ownerunban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/ownerunban @user`", parse_mode='Markdown')
        return

    target = _find_any_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    col("players").update_one({"user_id": target['user_id']}, {"$set": {"banned": 0, "ban_reason": None}})

    from handlers.logs import log_action
    log_action(uid, "ownerunban", target['user_id'], target['name'])

    await update.message.reply_text(f"✅ *{target['name']}* unbanned.", parse_mode='Markdown')


# ── /ownermsg ─────────────────────────────────────────────────────────────

async def ownermsg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    if len(context.args or []) < 2:
        await update.message.reply_text("Usage: `/ownermsg @user [message]`", parse_mode='Markdown')
        return

    target = _find_any_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    text = ' '.join(context.args[1:])
    try:
        await context.bot.send_message(
            chat_id=target['user_id'],
            text=f"📨 *Message from Bot Admin:*\n\n{text}",
            parse_mode='Markdown'
        )
        await update.message.reply_text(f"✅ Message sent to *{target['name']}*.", parse_mode='Markdown')
    except Exception as e:
        await update.message.reply_text(f"❌ Failed: {e}")


# ── /ownerstats ───────────────────────────────────────────────────────────

async def ownerstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    p_total    = col("players").count_documents({})
    p_slayer   = col("players").count_documents({"faction": "slayer"})
    p_demon    = col("players").count_documents({"faction": "demon"})
    p_banned   = col("players").count_documents({"banned": 1})
    p_hybrid   = col("players").count_documents({"hybrid_style": {"$ne": None}})
    p_hashira  = col("players").count_documents({"rank": "Hashira"})
    clans      = col("clans").count_documents({})
    items_col  = col("inventory").count_documents({})
    logs_col   = col("admin_logs").count_documents({})
    offers     = col("offers").count_documents({"status": "active"})
    suggestions= col("suggestions").count_documents({"status": "pending"})
    duels      = col("duels").count_documents({})

    # Top 3 players by XP
    top = list(col("players").find().sort("xp", -1).limit(3))

    lines = [
        f"╔══════════════════════╗",
        f"      👑 𝙊𝙒𝙉𝙀𝙍 𝙎𝙏𝘼𝙏𝙎",
        f"╚══════════════════════╝\n",
        f"👥 *Players:* {p_total}",
        f"   🗡️ Slayers: {p_slayer}  |  👹 Demons: {p_demon}",
        f"   ⚡ Hybrid: {p_hybrid}  |  🚫 Banned: {p_banned}",
        f"   🏅 Hashira: {p_hashira}",
        f"",
        f"🏯 *Clans:* {clans}",
        f"🎒 *Inventory entries:* {items_col}",
        f"📋 *Admin logs:* {logs_col}",
        f"🎪 *Active offers:* {offers}",
        f"💡 *Pending suggestions:* {suggestions}",
        f"⚔️ *Total duels:* {duels}",
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"🏆 *TOP 3 PLAYERS:*",
    ]
    medals = ['🥇', '🥈', '🥉']
    for i, p in enumerate(top):
        lv = get_level(p.get('xp', 0))
        lines.append(f"  {medals[i]} *{p['name']}* — Lv.{lv} | {p.get('xp',0):,} XP")

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


# ── /ownerplayers ─────────────────────────────────────────────────────────

async def ownerplayers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    page = 0
    if context.args:
        try: page = max(0, int(context.args[0]) - 1)
        except ValueError: pass

    PAGE = 15
    total   = col("players").count_documents({})
    players = list(col("players").find().sort("xp", -1).skip(page * PAGE).limit(PAGE))

    lines = [
        f"👥 *ALL PLAYERS* (Page {page+1}/{max(1,(total+PAGE-1)//PAGE)})\n"
        f"Total: *{total}*\n━━━━━━━━━━━━━━━━━━━━━\n"
    ]
    for i, p in enumerate(players):
        rank_num = page * PAGE + i + 1
        lv   = get_level(p.get('xp', 0))
        fe   = '🗡️' if p.get('faction') == 'slayer' else '👹'
        ban  = " 🚫" if p.get('banned') else ""
        lines.append(
            f"`{rank_num}.` {fe} *{p['name']}*{ban}\n"
            f"     Lv.{lv} | ID:`{p['user_id']}` | @{p.get('username','?')}"
        )

    buttons = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=f"ownerplist_{page-1}"))
    if (page+1)*PAGE < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=f"ownerplist_{page+1}"))
    if nav:
        buttons.append(nav)

    await update.message.reply_text(
        '\n'.join(lines), parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons) if buttons else None
    )


async def ownerplayers_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != OWNER_ID:
        await query.answer("❌ Owner only!", show_alert=True)
        return
    page = int(query.data.split('_')[-1])
    context.args = [str(page + 1)]
    await ownerplayers(update, context)
