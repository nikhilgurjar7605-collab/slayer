import logging
from telegram.error import BadRequest, TimedOut
log = logging.getLogger(__name__)
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
            except Exception as e:
                log.error("[EXCEPTION] %s", e)
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
    except Exception as e:
        log.error("[EXCEPTION] %s", e)


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
    except Exception as e:
        log.error("[EXCEPTION] %s", e)


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
    except Exception as e:
        log.error("[EXCEPTION] %s", e)


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


# ══════════════════════════════════════════════════════════════════════════
# ADDITIONAL OWNER COMMANDS
# ══════════════════════════════════════════════════════════════════════════

async def ownersetyen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ownersetyen @user amount — Set a player's yen to exact value."""
    from utils.guards import dm_only
    if not is_owner(update.effective_user.id):
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: `/ownersetyen @username amount`", parse_mode="Markdown")
        return
    target = get_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return
    update_player(target["user_id"], yen=amount)
    await update.message.reply_text(
        f"✅ Set *{target['name']}*'s Yen to *{amount:,}¥*", parse_mode="Markdown"
    )


async def ownersetsp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ownersetsp @user amount — Set a player's skill points."""
    if not is_owner(update.effective_user.id):
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: `/ownersetsp @username amount`", parse_mode="Markdown")
        return
    target = get_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return
    update_player(target["user_id"], skill_points=amount)
    await update.message.reply_text(
        f"✅ Set *{target['name']}*'s SP to *{amount}*", parse_mode="Markdown"
    )


async def ownerclearinv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ownerclearinv @user — Clear all inventory for a player."""
    if not is_owner(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/ownerclearinv @username`", parse_mode="Markdown")
        return
    target = get_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    col("inventory").delete_many({"user_id": target["user_id"]})
    await update.message.reply_text(
        f"✅ Cleared *{target['name']}*'s inventory.", parse_mode="Markdown"
    )


async def ownersetfaction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ownersetfaction @user slayer|demon — Force-change player faction."""
    if not is_owner(update.effective_user.id):
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: `/ownersetfaction @username slayer|demon`", parse_mode="Markdown")
        return
    target = get_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    faction = context.args[1].lower()
    if faction not in ("slayer", "demon"):
        await update.message.reply_text("❌ Faction must be `slayer` or `demon`.", parse_mode="Markdown")
        return
    update_player(target["user_id"], faction=faction)
    await update.message.reply_text(
        f"✅ *{target['name']}* is now a *{faction.title()}*!", parse_mode="Markdown"
    )


async def ownergivepet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ownergivepet @user PetName — Give a pet directly to a player."""
    if not is_owner(update.effective_user.id):
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: `/ownergivepet @username Pet Name`", parse_mode="Markdown")
        return
    target = get_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    pet_name = " ".join(context.args[1:])
    from config import PETS, PET_EVOLUTIONS
    if pet_name not in PETS and pet_name not in PET_EVOLUTIONS:
        valid = ", ".join(list(PETS.keys())[:5]) + "..."
        await update.message.reply_text(
            f"❌ Unknown pet *{pet_name}*\nValid: {valid}", parse_mode="Markdown"
        )
        return
    from handlers.pets import add_pet
    is_new = add_pet(target["user_id"], pet_name)
    if is_new:
        await update.message.reply_text(
            f"✅ Gave *{pet_name}* to *{target['name']}*!", parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"ℹ️ *{target['name']}* already owns *{pet_name}*. Added +20 Bond XP.", parse_mode="Markdown"
        )


async def ownersetloc(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ownersetloc @user location — Teleport player to any region."""
    if not is_owner(update.effective_user.id):
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/ownersetloc @username location`\n"
            "Locations: asakusa, butterfly, mtsagiri, swordsmith, yoshiwara, natagumo, infinity, void",
            parse_mode="Markdown"
        )
        return
    target = get_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    location = context.args[1].lower()
    valid_locs = ["asakusa","butterfly","mtsagiri","swordsmith","yoshiwara","natagumo","infinity","void"]
    if location not in valid_locs:
        await update.message.reply_text(f"❌ Invalid location. Valid: {', '.join(valid_locs)}")
        return
    update_player(target["user_id"], location=location)
    await update.message.reply_text(
        f"✅ Moved *{target['name']}* to *{location.title()}*!", parse_mode="Markdown"
    )


async def ownersetstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ownersetstats @user stat value [stat value ...]
    Manually set or adjust any combat stat for a player.
    
    Supported stats: hp, max_hp, sta, max_sta, str, spd, def,
                     xp, yen, skill_points, potential, potential_tier
    
    Usage examples:
      /ownersetstats @user str 30 def 20
      /ownersetstats @user max_hp 300 max_sta 200 str 40 spd 25 def 22
      /ownersetstats @user potential_tier 2 potential 0
    """
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "📋 *OWNER SET STATS — Usage*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "`/ownersetstats @user <stat> <value> [<stat> <value> ...]`\n\n"
            "*Supported stats:*\n"
            "• `hp` / `max_hp`\n"
            "• `sta` / `max_sta`\n"
            "• `str` → str\\_stat\n"
            "• `spd`\n"
            "• `def` → def\\_stat\n"
            "• `xp`\n"
            "• `yen`\n"
            "• `skill_points` / `sp`\n"
            "• `potential`\n"
            "• `potential_tier`\n\n"
            "*Examples:*\n"
            "`/ownersetstats @user str 35 def 25 spd 22`\n"
            "`/ownersetstats @user max_hp 350 max_sta 220`\n"
            "`/ownersetstats @user potential_tier 3 potential 0`",
            parse_mode="Markdown"
        )
        return

    target = _find_any_player(args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    # Stat alias map: user-friendly name → DB field name
    STAT_ALIASES = {
        "hp":             "hp",
        "max_hp":         "max_hp",
        "sta":            "sta",
        "stamina":        "sta",
        "max_sta":        "max_sta",
        "max_stamina":    "max_sta",
        "str":            "str_stat",
        "str_stat":       "str_stat",
        "strength":       "str_stat",
        "spd":            "spd",
        "speed":          "spd",
        "def":            "def_stat",
        "def_stat":       "def_stat",
        "defense":        "def_stat",
        "xp":             "xp",
        "yen":            "yen",
        "sp":             "skill_points",
        "skill_points":   "skill_points",
        "potential":      "potential",
        "potential_tier": "potential_tier",
        "tier":           "potential_tier",
    }

    stat_pairs = args[1:]
    if len(stat_pairs) % 2 != 0:
        await update.message.reply_text(
            "❌ Stats must come in pairs: `stat value stat value ...`\n"
            "Example: `/ownersetstats @user str 30 def 20`",
            parse_mode="Markdown"
        )
        return

    updates = {}
    errors  = []
    changes = []  # human-readable list of what changed

    # Save old stats snapshot before applying changes
    OLD_STAT_SNAPSHOT = {
        "HP":             f"{target.get('hp', '?')}/{target.get('max_hp', '?')}",
        "STA":            f"{target.get('sta', '?')}/{target.get('max_sta', '?')}",
        "STR":            str(target.get('str_stat', '?')),
        "SPD":            str(target.get('spd', '?')),
        "DEF":            str(target.get('def_stat', '?')),
        "XP":             str(target.get('xp', '?')),
        "YEN":            f"{target.get('yen', 0):,}¥",
        "SP":             str(target.get('skill_points', '?')),
        "Potential":      f"{target.get('potential', 0)}%",
        "Potential Tier": str(target.get('potential_tier', 0)),
    }

    for i in range(0, len(stat_pairs), 2):
        raw_stat  = stat_pairs[i].lower()
        raw_value = stat_pairs[i + 1]

        db_field = STAT_ALIASES.get(raw_stat)
        if not db_field:
            errors.append(f"Unknown stat: `{raw_stat}`")
            continue

        try:
            value = int(raw_value)
        except ValueError:
            errors.append(f"Bad value for `{raw_stat}`: `{raw_value}` (must be integer)")
            continue

        # Clamp potential to 0–100
        if db_field == "potential":
            value = max(0, min(100, value))

        old_val = target.get(db_field, 0)
        updates[db_field] = value
        changes.append(f"  • `{db_field}`: *{old_val}* → *{value}*")

    if errors:
        await update.message.reply_text(
            "❌ *Errors found:*\n" + "\n".join(errors),
            parse_mode="Markdown"
        )
        return

    if not updates:
        await update.message.reply_text("❌ No valid stat changes provided.")
        return

    # Apply all updates atomically
    update_player(target["user_id"], **updates)

    # Log the action
    from handlers.logs import log_action
    log_action(uid, "ownersetstats", target["user_id"], target["name"],
               " | ".join(f"{k}={v}" for k, v in updates.items()))

    # Build old stats display
    old_stats_text = "\n".join(f"  {k}: {v}" for k, v in OLD_STAT_SNAPSHOT.items())

    result_msg = (
        f"✅ *STATS UPDATED — {target['name'].upper()}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Changes Applied:*\n"
        + "\n".join(changes) + "\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📋 *Old Stats (before change):*\n"
        f"{old_stats_text}"
    )

    await update.message.reply_text(result_msg, parse_mode="Markdown")

    # Optionally notify the player
    try:
        notif_lines = [f"  {c.strip().lstrip('• ')}" for c in changes]
        await context.bot.send_message(
            chat_id=target["user_id"],
            text=(
                f"⚙️ *Admin has adjusted your stats!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                + "\n".join(notif_lines) + "\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"_Use /profile to view your updated stats._"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        log.error("[ownersetstats notify] %s", e)


async def ownerviewstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ownerviewstats @user — View a player's full stats snapshot (owner only)."""
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/ownerviewstats @username`", parse_mode="Markdown"
        )
        return

    target = _find_any_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    tier = target.get("potential_tier", 0)
    tier_labels = {
        0: "None",
        1: "🌟 Tier I (Awakened)",
        2: "✨ Tier II (Ascended)",
        3: "💎 Tier III (Transcended)",
        4: "🌌 Tier IV (Demi-God)",
        5: "👑 Tier V (Supreme Sovereign)",
    }
    tier_label = tier_labels.get(tier, f"🔥 Tier {tier}")
    dmg_bonus  = tier * 5
    def_bonus  = tier * 3

    from utils.helpers import get_level
    level = get_level(target.get("xp", 0))

    await update.message.reply_text(
        f"🔍 *STATS SNAPSHOT — {target['name'].upper()}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 User ID:        `{target['user_id']}`\n"
        f"👤 Username:       @{target.get('username', 'N/A')}\n"
        f"⚔️  Faction:       {target.get('faction', '?').title()}\n"
        f"🌬️  Style:         {target.get('style', '?')}\n"
        f"📈 Level:          {level}\n"
        f"⭐ XP:             {target.get('xp', 0):,}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"❤️  HP:            {target.get('hp', '?')} / {target.get('max_hp', '?')}\n"
        f"🌀 STA:            {target.get('sta', '?')} / {target.get('max_sta', '?')}\n"
        f"💪 STR:            {target.get('str_stat', '?')}\n"
        f"⚡ SPD:            {target.get('spd', '?')}\n"
        f"🛡️  DEF:           {target.get('def_stat', '?')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔮 Potential:      {target.get('potential', 0)}%\n"
        f"🏆 Tier:           {tier_label}\n"
        f"⚔️  DMG Bonus:     +{dmg_bonus}% (from tier)\n"
        f"🔰 DMG Reduce:     +{def_bonus}% (from tier)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Yen:            {target.get('yen', 0):,}¥\n"
        f"💠 Skill Points:   {target.get('skill_points', 0)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗡️ Sword:          {target.get('equipped_sword', 'None')}\n"
        f"👘 Armor:          {target.get('equipped_armor', 'None')}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"_Use /ownersetstats @{target.get('username', target['name'])} to fix any value._",
        parse_mode="Markdown"
    )


def _calc_tier_stats(faction: str, level: int, tier: int) -> dict:
    """Calculate the correct stats for a player based on faction, level, and tier."""
    if faction == "demon":
        BASE = {"max_hp": 280, "max_sta": 160, "str_stat": 26, "spd": 20, "def_stat": 14}
    else:  # slayer (default)
        BASE = {"max_hp": 240, "max_sta": 170, "str_stat": 22, "spd": 20, "def_stat": 18}

    LEVEL_GROWTH = {"max_hp": 15, "max_sta": 10, "str_stat": 2, "spd": 1, "def_stat": 1}
    TIER_BOOST   = {"max_hp": 15, "max_sta": 10, "str_stat": 2, "spd": 1, "def_stat": 1}

    level_steps = max(0, level - 1)
    result = {}
    for stat in BASE:
        result[stat] = (
            BASE[stat]
            + (level_steps * LEVEL_GROWTH[stat])
            + (tier * TIER_BOOST[stat])
        )
    return result


TIER_NAMES = {
    0: "None",
    1: "🌟 Tier I (Awakened)",
    2: "✨ Tier II (Ascended)",
    3: "💎 Tier III (Transcended)",
    4: "🌌 Tier IV (Demi-God)",
    5: "👑 Tier V (Supreme Sovereign)",
}

STAT_LABELS = {
    "max_hp":        "❤️  Max HP",
    "hp":            "❤️  HP",
    "max_sta":       "🌀 Max STA",
    "sta":           "🌀 STA",
    "str_stat":      "💪 STR",
    "spd":           "⚡ SPD",
    "def_stat":      "🛡️  DEF",
    "potential_tier":"🏆 Tier",
}


async def ownerfixtierstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ownerfixtierstats @user [tier]

    Usage:
      /ownerfixtierstats @user        — VIEW current stats (no changes applied)
      /ownerfixtierstats @user 2      — APPLY tier 2 stats (never nerfs; only raises stats)
      /ownerfixtierstats @user 0      — APPLY base stats for tier 0
      /ownerfixtierstats @user 2 fix  — APPLY and correct old nerfed stats upward

    Stats are NEVER reduced — the command always takes the higher value.
    """
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "📋 *OWNER FIX TIER STATS — Usage*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "`/ownerfixtierstats @user` — 👁 VIEW current stats (no changes)\n"
            "`/ownerfixtierstats @user 2` — ✅ Apply tier 2 stats (never nerfs)\n"
            "`/ownerfixtierstats @user 0` — 🔄 Apply base stats (tier 0)\n\n"
            "_Stats are NEVER reduced — always takes the higher value._\n"
            "_Use `/ownersetstats` to manually set exact values._",
            parse_mode="Markdown"
        )
        return

    target = _find_any_player(args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    faction = target.get("faction", "slayer")
    level   = max(1, get_level(target.get("xp", 0)))
    cur_tier = target.get("potential_tier", 0)
    faction_emoji = "👹" if faction == "demon" else "🗡️"

    # ── VIEW MODE: no tier argument → just show stats, apply nothing ─────
    if len(args) < 2:
        calc = _calc_tier_stats(faction, level, cur_tier)
        tier_name = TIER_NAMES.get(cur_tier, "?")

        lines = [
            f"👁 *STATS SNAPSHOT — {target['name'].upper()}*",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"{faction_emoji} Faction: *{faction.title()}*  |  📈 Level: *{level}*  |  🏆 *{tier_name}*",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"*Current (live) stats:*",
            f"  ❤️  Max HP : *{target.get('max_hp', 0):,}*  |  HP: *{target.get('hp', 0):,}*",
            f"  🌀 Max STA: *{target.get('max_sta', 0):,}*  |  STA: *{target.get('sta', 0):,}*",
            f"  💪 STR    : *{target.get('str_stat', 0):,}*",
            f"  ⚡ SPD    : *{target.get('spd', 0):,}*",
            f"  🛡️  DEF    : *{target.get('def_stat', 0):,}*",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"*Formula-correct values for Lv{level} T{cur_tier}:*",
            f"  ❤️  Max HP : *{calc['max_hp']:,}*",
            f"  🌀 Max STA: *{calc['max_sta']:,}*",
            f"  💪 STR    : *{calc['str_stat']:,}*",
            f"  ⚡ SPD    : *{calc['spd']:,}*",
            f"  🛡️  DEF    : *{calc['def_stat']:,}*",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"_To apply corrections: `/ownerfixtierstats @{target.get('username','user')} {cur_tier}`_",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # ── APPLY MODE: tier argument given ──────────────────────────────────
    try:
        new_tier = int(args[1])
        if not (0 <= new_tier <= 5):
            await update.message.reply_text("❌ Tier must be 0–5.")
            return
    except ValueError:
        await update.message.reply_text("❌ Tier must be a number (0–5).")
        return

    calc = _calc_tier_stats(faction, level, new_tier)

    # NEVER NERF: take the maximum of formula value and current value
    to_apply = {}
    for stat, formula_val in calc.items():
        current_val = int(target.get(stat, 0) or 0)
        to_apply[stat] = max(formula_val, current_val)

    # Set hp/sta to their (possibly raised) max
    to_apply["hp"]  = to_apply["max_hp"]
    to_apply["sta"] = to_apply["max_sta"]
    to_apply["potential_tier"] = new_tier

    old_tier_name = TIER_NAMES.get(cur_tier, "?")
    new_tier_name = TIER_NAMES.get(new_tier, "?")

    changes = []
    for field, new_val in to_apply.items():
        old_val = target.get(field, 0)
        label   = STAT_LABELS.get(field, field)
        if field == "potential_tier":
            changes.append(f"  {label}: *{old_tier_name}* → *{new_tier_name}*")
        else:
            diff = new_val - old_val
            sign = "+" if diff >= 0 else ""
            flag = " _(no change)_" if diff == 0 else ""
            changes.append(f"  {label}: *{old_val:,}* → *{new_val:,}* ({sign}{diff:,}){flag}")

    # Apply changes
    update_player(target["user_id"], **to_apply)

    from handlers.logs import log_action
    log_action(uid, "ownerfixtierstats", target["user_id"], target["name"],
               f"lv={level} faction={faction} tier={new_tier}")

    result = (
        f"✅ *TIER STATS APPLIED — {target['name'].upper()}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{faction_emoji} Faction: *{faction.title()}*\n"
        f"📈 Level: *{level}*\n"
        f"🏆 Tier: *{new_tier_name}*\n"
        f"⚔️ DMG Bonus: *+{new_tier * 5}%*\n"
        f"🔰 DMG Reduce: *+{new_tier * 3}%*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Changes (stats NEVER reduced):*\n"
        + "\n".join(changes)
    )

    await update.message.reply_text(result, parse_mode="Markdown")

    try:
        await context.bot.send_message(
            chat_id=target["user_id"],
            text=(
                f"⚙️ *Your stats have been corrected by the admin!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏆 Tier: *{new_tier_name}*\n"
                f"❤️ HP fully restored to *{to_apply['max_hp']:,}*\n"
                f"🌀 STA fully restored to *{to_apply['max_sta']:,}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"_Use /profile to view your updated stats._"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        log.error("[ownerfixtierstats notify] %s", e)


async def ownerrestorestats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ownerrestorestats @user stat:value [stat:value ...]
    OR /ownerrestorestats @user stat value [stat value ...]

    Restore a player's stats to specific old values — never reduces below current.
    Use this when a previous command accidentally nerfed someone's stats.

    Supported stats:
      max_hp  hp  max_sta  sta  str_stat  spd  def_stat  potential_tier

    Example:
      /ownerrestorestats @darkslayer max_hp:4500 str_stat:320 spd:180
      /ownerrestorestats 5033184932 max_hp:6673 str_stat:440 spd 378 max_sta 3625 def_stat 459

    The command ONLY raises stats — it will never reduce a stat that is already higher.
    To force-set exact values regardless, use /ownersetstats instead.
    """
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ Owner only.")
        return

    args = context.args or []

    if len(args) < 2:
        await update.message.reply_text(
            "📋 *RESTORE STATS — Usage*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "`/ownerrestorestats @user stat:value [stat:value ...]`\n"
            "`/ownerrestorestats @user stat value [stat value ...]`\n\n"
            "*Valid stats:*\n"
            "`max_hp` `hp` `max_sta` `sta`\n"
            "`str_stat` `spd` `def_stat` `potential_tier`\n\n"
            "*Example:*\n"
            "`/ownerrestorestats @darkslayer max_hp:4500 str_stat:320 spd:180`\n\n"
            "_Stats are NEVER reduced — only raised to the provided value._\n"
            "_To force-set exact values, use /ownersetstats._",
            parse_mode="Markdown"
        )
        return

    target = _find_any_player(args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    VALID_STATS = {
        "max_hp", "hp", "max_sta", "sta",
        "str_stat", "spd", "def_stat", "potential_tier"
    }

    # Aliases so typos like spd_stat, speed, defense etc. still work
    STAT_ALIASES = {
        "spd_stat":       "spd",
        "speed":          "spd",
        "str":            "str_stat",
        "strength":       "str_stat",
        "def":            "def_stat",
        "defense":        "def_stat",
        "defence":        "def_stat",
        "stamina":        "sta",
        "max_stamina":    "max_sta",
        "max_hp":         "max_hp",
        "hp":             "hp",
        "sta":            "sta",
        "max_sta":        "max_sta",
        "str_stat":       "str_stat",
        "spd":            "spd",
        "def_stat":       "def_stat",
        "potential_tier": "potential_tier",
    }

    # ── Flexible token parser: handles both "stat:value" and "stat value" ──
    # First expand all "stat:value" tokens into ["stat", "value"]
    expanded = []
    for token in args[1:]:
        if ":" in token:
            stat_part, _, val_part = token.partition(":")
            expanded.append(stat_part.strip())
            if val_part.strip():
                expanded.append(val_part.strip())
        else:
            expanded.append(token)

    parsed   = {}
    bad_args = []
    i = 0
    while i < len(expanded):
        token = expanded[i]
        # Is this token a stat name?
        stat_key = token.lower()
        resolved = STAT_ALIASES.get(stat_key) or (stat_key if stat_key in VALID_STATS else None)
        if resolved:
            # Expect the next token to be the value
            if i + 1 >= len(expanded):
                bad_args.append(f"`{token}` (no value provided after stat name)")
                i += 1
                continue
            raw_val = expanded[i + 1]
            try:
                val = int(raw_val.strip().replace(",", ""))
                if val < 0:
                    bad_args.append(f"`{token}:{raw_val}` (value must be ≥ 0)")
                else:
                    parsed[resolved] = val
            except ValueError:
                bad_args.append(f"`{token} {raw_val}` ('{raw_val}' is not a number)")
            i += 2
        else:
            # Not a stat name — could be a stray value or typo
            bad_args.append(f"`{token}` (unknown stat name)")
            i += 1

    if bad_args:
        await update.message.reply_text(
            "⚠️ *Some arguments were invalid:*\n" + "\n".join(bad_args) +
            "\n\nFix them and try again.",
            parse_mode="Markdown"
        )
        return

    if not parsed:
        await update.message.reply_text("❌ No valid stat:value pairs provided.")
        return

    # ── Apply: NEVER reduce — take max(old, new) ──────────────────────
    to_apply = {}
    changes  = []

    for stat, restore_val in parsed.items():
        old_val = int(target.get(stat, 0) or 0)
        new_val = max(old_val, restore_val)
        to_apply[stat] = new_val

        label = STAT_LABELS.get(stat, stat)
        diff  = new_val - old_val
        if diff == 0:
            changes.append(f"  {label}: *{old_val:,}* _(no change — already higher)_")
        else:
            changes.append(f"  {label}: *{old_val:,}* → *{new_val:,}* _(+{diff:,} restored)_")

    # If max_hp/max_sta was raised, also bring hp/sta up proportionally
    if "max_hp" in to_apply and "hp" not in to_apply:
        old_hp  = int(target.get("hp", 0) or 0)
        new_hp  = max(old_hp, to_apply["max_hp"])
        to_apply["hp"] = new_hp
        if new_hp != old_hp:
            changes.append(f"  ❤️  HP: *{old_hp:,}* → *{new_hp:,}* _(auto-raised to match MaxHP)_")

    if "max_sta" in to_apply and "sta" not in to_apply:
        old_sta = int(target.get("sta", 0) or 0)
        new_sta = max(old_sta, to_apply["max_sta"])
        to_apply["sta"] = new_sta
        if new_sta != old_sta:
            changes.append(f"  🌀 STA: *{old_sta:,}* → *{new_sta:,}* _(auto-raised to match MaxSTA)_")

    update_player(target["user_id"], **to_apply)

    from handlers.logs import log_action
    summary = " ".join(f"{k}={v}" for k, v in parsed.items())
    log_action(uid, "ownerrestorestats", target["user_id"], target["name"], summary)

    faction_e = "👹" if target.get("faction") == "demon" else "🗡️"

    await update.message.reply_text(
        f"✅ *STATS RESTORED — {target['name'].upper()}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{faction_e} {target.get('faction','slayer').title()}\n\n"
        f"📊 *Result (stats never reduced):*\n"
        + "\n".join(changes) +
        f"\n\n_Use /ownerviewstats @{target.get('username', target['name'])} to verify._",
        parse_mode="Markdown"
    )

    try:
        await context.bot.send_message(
            chat_id=target["user_id"],
            text=(
                f"⚙️ *Your stats have been restored by an admin.*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"_Use /profile to see your updated stats._"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        log.error("[ownerrestorestats notify] %s", e)


# ── Owner Help Pages ──────────────────────────────────────────────────────
# Each page is (button_label, page_key, text_content)
_OWNER_HELP_PAGES = {

    "menu": None,   # special — the main category picker

    "player": (
        "👤 Player Management",
        "👤 *PLAYER MANAGEMENT*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔍 *View & Info:*\n"
        "`/owneraccess @u` — full player data dump\n"
        "`/ownerviewstats @u` — detailed stats snapshot\n"
        "`/check @u` / `/inspect @u` — quick player view\n"
        "`/ownerplayers` — browse all players with pagination\n"
        "`/activeusers` — recently active players\n"
        "`/botstats` — total players, economy, usage stats\n\n"
        "✏️ *Edit Player:*\n"
        "`/ownersetlevel @u <lvl>` — set exact level (1–100)\n"
        "`/ownersetstyle @u <style>` — force any breathing style\n"
        "`/ownersetfaction @u slayer|demon` — change faction\n"
        "`/ownersetloc @u <location>` — teleport to any region\n"
        "`/ownersetyen @u <amount>` — set yen balance\n"
        "`/ownersetsp @u <amount>` — set skill points\n"
        "`/ownerclearinv @u` — wipe entire inventory\n"
        "`/ownerreset @u` — full reset (keeps user ID)\n"
        "`/resetplayer @u` — alias for full reset\n"
        "`/adminunstuck @u` — unstuck stuck battle state\n"
        "`/unstuck` / `/forceunstuck` — player self-unstuck\n\n"
        "🔒 *Bans:*\n"
        "`/ownerban @u` — owner-level ban\n"
        "`/ownerunban @u` — owner-level unban\n"
        "`/ban @u [reason]` — admin ban\n"
        "`/unban @u` — admin unban\n"
    ),

    "stats": (
        "📊 Stats & Anti-Nerf",
        "📊 *STATS & ANTI-NERF COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ _All commands below NEVER reduce stats — only raise them._\n\n"
        "👁 *View:*\n"
        "`/ownerviewstats @u` — full live stats snapshot\n"
        "`/ownerfixtierstats @u` — VIEW stats vs formula (no changes)\n\n"
        "🔧 *Fix / Restore:*\n"
        "`/ownersetstats @u stat val [stat val ...]`\n"
        "  → Force-set exact values (can reduce — use carefully)\n"
        "  → Stats: `max_hp hp max_sta sta str_stat spd def_stat`\n\n"
        "`/ownerfixtierstats @u <tier>`\n"
        "  → Apply formula-correct stats for level+faction+tier\n"
        "  → Never reduces — takes max(formula, current)\n"
        "  → Tiers: 0=None 1=Awakened 2=Ascended 3=Transcended\n"
        "           4=Demi-God 5=Supreme Sovereign\n\n"
        "`/ownerrestorestats @u stat:value [stat:value ...]`\n"
        "  → Restore specific old values — never nerfs\n"
        "  → Example: `/ownerrestorestats @u max_hp:4500 str_stat:320`\n"
        "  → Stats: `max_hp hp max_sta sta str_stat spd def_stat potential_tier`\n\n"
        "💡 *Workflow for nerfed player:*\n"
        "  1. `/ownerviewstats @u` — see current vs correct\n"
        "  2. `/ownerrestorestats @u max_hp:X str_stat:Y` — restore\n"
        "  3. `/ownerviewstats @u` — verify\n"
    ),

    "giving": (
        "🎁 Giving Commands",
        "🎁 *GIVING COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "💰 *Resources:*\n"
        "`/ownergive @u xp|yen|sp|items <amount>` — bulk give anything\n"
        "`/add @u yen|exp|sp|items <amount>` — admin give\n"
        "`/givexp @u <amount>` — give XP directly\n"
        "`/giveyen @u <amount>` — give Yen directly\n"
        "`/givesp @u <amount>` — give Skill Points\n"
        "`/giveitem @u <item name>` — give specific item\n"
        "`/adminsp @u <amount>` — admin grant SP freely\n\n"
        "🎴 *Styles & Arts:*\n"
        "`/givestyle @u <style name>` — give any breathing style\n"
        "`/giveart @u <art name>` — give any demon art\n"
        "`/giveultimate @u` — give Absolute Biokinesis (legendary)\n\n"
        "🏆 *Marks & Special:*\n"
        "`/giveslayermark @u` — give Slayer Mark\n"
        "`/givedemonmark @u` — give Demon Mark\n"
        "`/ownergivepet @u <PetName>` — give pet directly\n\n"
        "🖼 *Banners & Cosmetics:*\n"
        "`/givegifbanner @u <store_id>` — give GIF banner (by store ID)\n"
        "`/givegifbanner @u file <file_id>` — give custom GIF banner\n"
        "`/giveskin @u <skin name>` — give skin\n"
        "`/giveaccessory @u <name>` — give accessory\n\n"
        "🌟 *Master Give:*\n"
        "`/master @u` — give EVERYTHING to a player at once\n"
    ),

    "moderation": (
        "🛡️ Moderation",
        "🛡️ *MODERATION COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "👑 *Owner — Admin Control:*\n"
        "`/addsudo @u` — promote user to admin\n"
        "`/removesudo @u` — remove admin rights\n"
        "`/listadmins` — list all current admins\n\n"
        "🔨 *Bans:*\n"
        "`/ownerban @u` — owner-level ban (strongest)\n"
        "`/ownerunban @u` — owner-level unban\n"
        "`/ban @u [reason]` — standard admin ban\n"
        "`/unban @u` — standard admin unban\n\n"
        "🔇 *Maintenance:*\n"
        "`/ownermode on|off` — toggle maintenance mode\n"
        "`/maintenance` — check maintenance status\n"
        "`/approveuser @u` — whitelist user during maintenance\n"
        "`/unapproveuser @u` — remove whitelist\n"
        "`/approvedlist` — see all whitelisted users\n\n"
        "📢 *Broadcasts:*\n"
        "`/announce <text>` — broadcast to all players\n"
        "`/bcast <text>` — alias for announce\n"
        "`/ownermsg @u <text>` — DM any specific player\n"
        "`/clanannounce <text>` — announce inside a clan\n\n"
        "📋 *Logs:*\n"
        "`/logs` — recent admin action log\n"
        "`/logstats` — log usage statistics\n"
        "`/logsearch <term>` — search log entries\n"
        "`/loguser @u` — all actions on a player\n"
        "`/suggestions` — view player suggestions\n"
    ),

    "economy": (
        "💰 Economy & Market",
        "💰 *ECONOMY & MARKET COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🏦 *World Bank:*\n"
        "`/worldbank` — view world bank\n"
        "`/worlddeposit <amount>` — deposit into world bank\n"
        "`/worldwithdraw <amount>` — withdraw\n"
        "`/wbaddstock <item> <qty>` — add stock\n"
        "`/wbsetprice <item> <price>` — set price\n"
        "`/wbinfo` — bank info\n"
        "`/wbevent` — trigger bank event\n"
        "`/wbblackmarket` — world bank black market\n"
        "`/bankgiveaway 24hr|15m|25s` — start bank giveaway\n"
        "`/banktax 0.1%` _(reply to user)_ — charge tax\n"
        "`/setinterest <rate>` — set interest rate\n"
        "`/interestinfo` — view current rate\n\n"
        "🌑 *Black Market:*\n"
        "`/openblackmarket` — open the black market\n"
        "`/closeblackmarket` — close it\n"
        "`/addblackmarket <item> <price> <stock>` — add item\n"
        "`/blackmarket` — player-facing BM view\n\n"
        "🏪 *Auction:*\n"
        "`/addauction` — add new auction item\n"
        "`/auction` — view active auctions\n"
        "`/bid <amount>` — bid on an item\n\n"
        "🏦 *SP Bank:*\n"
        "`/spbank` — SP bank overview\n"
        "`/spdeposit <amount>` — deposit SP\n"
        "`/spwithdraw <amount>` — withdraw SP\n"
        "`/spgiveaway` — start SP giveaway\n"
        "`/spjoin` — join SP giveaway\n\n"
        "🎰 *Lottery:*\n"
        "`/lottery` — play the lottery\n"
    ),

    "events_raids": (
        "⚔️ Events & Raids",
        "⚔️ *EVENTS & RAIDS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎉 *Events:*\n"
        "`/event` — view current event\n"
        "`/events` — list all events\n"
        "`/eventlist` — event list (admin)\n"
        "`/eventend` — end active event\n"
        "`/eventresults` — view event results\n"
        "`/vote` — vote in event\n\n"
        "⚔️ *Global Raids:*\n"
        "`/startraid <BossName>` — launch a global raid\n"
        "`/stopraid` — cancel active raid\n"
        "`/joinraid` — join active raid\n"
        "`/raidattack` — attack in raid\n\n"
        "🏰 *Clan Raids:*\n"
        "`/clanraid` — start a clan raid\n\n"
        "📋 *Missions:*\n"
        "`/addmission` — add new mission\n"
        "`/removemission <id>` — remove mission\n"
        "`/listmissions` — list all missions\n"
        "`/mission` — player mission view\n\n"
        "🤝 *Co-op:*\n"
        "`/joinbattle` — join party leader's battle\n"
        "`/party` — view/manage party\n"
        "`/invite @u` — invite to party\n"
    ),

    "cosmetics": (
        "🎨 Cosmetics & Skins",
        "🎨 *COSMETICS & SKINS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🖼 *GIF Banners:*\n"
        "`/gifstore` — view GIF banner store\n"
        "`/addgifbanner` — add banner to store\n"
        "`/removegifbanner <id>` — remove banner\n"
        "`/listgifbanners` — list all banners\n"
        "`/setmygifbanner <id>` — equip a banner\n"
        "`/givegifbanner @u <id>` — give banner to player\n"
        "`/setbanner` — set profile banner (image)\n"
        "`/clearbanner` — remove profile banner\n"
        "`/bannershow` — show banner preview\n"
        "`/bannerpending` — banners pending approval\n"
        "`/approvebanner` — approve a banner\n\n"
        "👘 *Skins:*\n"
        "`/skins` — view your skins\n"
        "`/addskin` — add skin to pool\n"
        "`/removeskin <name>` — remove skin\n"
        "`/listskins` — list all skins\n"
        "`/giveskin @u <name>` — give skin to player\n\n"
        "💎 *Accessories:*\n"
        "`/customise` — open customisation menu\n"
        "`/mycharacter` — view character appearance\n"
        "`/addaccessory` — add accessory to pool\n"
        "`/removeaccessory <name>` — remove accessory\n"
        "`/listaccessories` — list all accessories\n"
        "`/giveaccessory @u <name>` — give accessory\n\n"
        "🖼 *Style Images:*\n"
        "`/setstyleimage <style>` — set image for a style\n"
        "`/setimage` — set a general image\n"
        "`/listimages` — list stored images\n"
    ),

    "clans": (
        "🏯 Clans",
        "🏯 *CLAN COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🏗 *Clan Admin:*\n"
        "`/createclan <name>` — create a new clan\n"
        "`/clandisband` — disband your clan\n"
        "`/renameclan <new name>` — rename clan\n"
        "`/clanimage` — set clan image\n"
        "`/clanslogan <text>` — set clan slogan\n"
        "`/clanreq <level>` — set join requirement\n"
        "`/setclanlink` — set clan invite link\n\n"
        "👥 *Clan Members:*\n"
        "`/clan` — your clan overview\n"
        "`/claninfo <name>` — view any clan's info\n"
        "`/clanmembers` — list all members\n"
        "`/clan_list` — browse all clans\n"
        "`/clanleaderboard` — clan rankings\n"
        "`/joinclan <name>` — join a clan\n"
        "`/leaveclan` — leave clan\n"
        "`/kick @u` — kick member\n"
        "`/promotevice @u` — promote to vice-leader\n"
        "`/demote @u` — demote vice-leader\n"
        "`/clanrole @u <role>` — set member role\n\n"
        "💰 *Clan Economy:*\n"
        "`/clandeposit <amount>` — deposit to clan bank\n"
        "`/clanwithdraw <amount>` — withdraw from clan bank\n"
        "`/clanannounce <text>` — announce to clan members\n"
        "`/clanraid` — start a clan raid\n"
    ),

    "bot_control": (
        "🤖 Bot Control",
        "🤖 *BOT CONTROL*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "⚙️ *Owner Controls:*\n"
        "`/ownermode on|off` — toggle maintenance / lockdown\n"
        "`/ownermode` — view current mode\n"
        "`/ownerstats` — full bot analytics & counts\n"
        "`/ownerplayers` — paginated player browser\n"
        "`/master` — emergency owner super-panel\n\n"
        "💾 *Backup & Restore:*\n"
        "`/backup` — export full database as JSON file\n"
        "`/restore` — import database from JSON file\n\n"
        "🗄 *Database:*\n"
        "`/sqlview` — run raw DB query (read-only)\n\n"
        "🔧 *Maintenance:*\n"
        "`/maintenance` — check maintenance status\n"
        "`/approveuser @u` — whitelist during maintenance\n"
        "`/unapproveuser @u` — remove whitelist\n"
        "`/approvedlist` — list whitelisted users\n\n"
        "🔑 *Admin Rights:*\n"
        "`/addsudo @u` — promote to admin\n"
        "`/removesudo @u` — revoke admin\n"
        "`/listadmins` — all current admins\n\n"
        "📊 *Logs & Monitoring:*\n"
        "`/logs` — recent action log\n"
        "`/logstats` — log statistics\n"
        "`/logsearch <term>` — search logs\n"
        "`/loguser @u` — all actions on a user\n"
        "`/botstats` — player counts + economy overview\n"
        "`/activeusers` — recently active players\n\n"
        "💬 *Messaging:*\n"
        "`/ownermsg @u <text>` — DM any player\n"
        "`/announce <text>` — broadcast to all\n"
        "`/bcast <text>` — broadcast alias\n"
    ),

    "info_dex": (
        "📖 Info & Item Dex",
        "📖 *INFO & ITEM DEX*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🗂 *Item Dex — Browse all game items:*\n"
        "`/itemdex` — category menu\n"
        "`/itemdex swords` — ⚔️ Nichirin blades + prices\n"
        "`/itemdex items` — 🧪 Consumables (potions, pills)\n"
        "`/itemdex armor` — 🥋 Armor & haori\n"
        "`/itemdex pet_items` — 🐾 Pet traps, eggs, food\n"
        "`/itemdex breathing` — 💧 All breathing styles\n"
        "`/itemdex demon_arts` — 🩸 All demon arts\n"
        "`/itemdex pets` — All catchable pets & passives\n"
        "`/itemdex drops` — Enemy drop items\n"
        "`/itemdex blackmarket` — 🌑 Live black market stock\n"
        "`/itemdex <search>` — Search across all categories\n"
        "`/itemdex swords 2` — Page 2 of swords\n\n"
        "🔍 *Style & Skill Lookup:*\n"
        "`/info <style name>` — Full style info + forms\n"
        "`/infoall` — All styles overview\n"
        "`/skillinfo <name>` — Skill details & bonuses\n"
        "`/skilllist` — List all available skills\n"
        "`/know` — Game encyclopedia (tabbed UI)\n"
        "`/guide` — Full gameplay guide\n\n"
        "🖼 *Image Management:*\n"
        "`/listimages` — All stored style images\n"
        "`/setstyleimage <style>` — Set image for a style\n"
        "`/setimage` — Set general game image\n"
        "`/listgifbanners` — All GIF banners\n"
        "`/bannerpending` — Banners awaiting approval\n"
        "`/approvebanner` — Approve a banner\n\n"
        "📋 *Suggestions:*\n"
        "`/suggest <text>` — Submit suggestion (player)\n"
        "`/suggestions` — View all suggestions (admin)\n"
        "`/is <id>` — View specific suggestion\n"
        "`/myid` — Your Telegram user ID\n"
    ),

    "combat_pets": (
        "⚔️ Combat & Pets",
        "⚔️ *COMBAT & PETS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🐾 *Pet Admin:*\n"
        "`/ownergivepet @u <PetName>` — give pet directly\n"
        "`/pets` — view your pet stable\n"
        "`/pet <name>` — activate a pet\n"
        "`/releasepet <name>` — release a pet\n"
        "`/feedpet` — feed active pet\n"
        "`/petskill` — use pet's battle skill\n"
        "`/petbattle @u` — challenge someone's pet\n"
        "`/hatchegg` — hatch a pet egg\n"
        "`/catch` — attempt to catch a wild pet\n\n"
        "🤝 *Pet Trades:*\n"
        "`/petoffer @u` — send a pet trade offer\n"
        "`/petoffer` _(reply to message)_ — offer to replier\n"
        "`/pettrade @u` — alias for petoffer\n\n"
        "⚔️ *Combat:*\n"
        "`/explore` — explore and find enemies\n"
        "`/meditate` — meditate to awaken tier\n"
        "`/challenge @u` — duel another player\n"
        "`/joinbattle` — join party leader's coop battle\n"
        "`/joinraid` — join active global raid\n"
        "`/raidattack` — attack in raid\n"
        "`/clanraid` — start clan raid\n\n"
        "🗡 *Styles & Arts:*\n"
        "`/breathing` — your breathing styles\n"
        "`/art` — your demon arts\n"
        "`/mytechnique` — your unlocked techniques\n"
        "`/myart` — your active demon arts\n"
        "`/changestyle` — switch active style\n"
        "`/slayermark` — activate Slayer Mark\n"
        "`/demonmark` — activate Demon Mark\n"
        "`/hybrid` — enter hybrid mode\n"
        "`/re_hybrid` — reset hybrid\n"
        "`/upgrade` — upgrade your style\n"
        "`/upgradetoggle` / `/hybridtoggle` — toggle auto\n"
    ),
}


def _ownerhelp_menu_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👤 Player Mgmt",   callback_data="ownerhelp_player"),
            InlineKeyboardButton("📊 Stats",          callback_data="ownerhelp_stats"),
        ],
        [
            InlineKeyboardButton("🎁 Giving",         callback_data="ownerhelp_giving"),
            InlineKeyboardButton("🛡️ Moderation",     callback_data="ownerhelp_moderation"),
        ],
        [
            InlineKeyboardButton("💰 Economy",        callback_data="ownerhelp_economy"),
            InlineKeyboardButton("⚔️ Events & Raids", callback_data="ownerhelp_events_raids"),
        ],
        [
            InlineKeyboardButton("🎨 Cosmetics",      callback_data="ownerhelp_cosmetics"),
            InlineKeyboardButton("🏯 Clans",          callback_data="ownerhelp_clans"),
        ],
        [
            InlineKeyboardButton("🤖 Bot Control",    callback_data="ownerhelp_bot_control"),
            InlineKeyboardButton("📖 Info & Dex",     callback_data="ownerhelp_info_dex"),
        ],
        [
            InlineKeyboardButton("⚔️ Combat & Pets",  callback_data="ownerhelp_combat_pets"),
        ],
    ])


def _ownerhelp_back_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back to Menu", callback_data="ownerhelp_menu")
    ]])


async def ownerhelp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/ownerhelp — Interactive paginated owner command list."""
    if not is_owner(update.effective_user.id):
        return

    menu_text = (
        "👑 *OWNER COMMAND CENTRE*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Select a category to view all commands:\n\n"
        "👤 Player Mgmt — view/edit/reset players\n"
        "📊 Stats — fix/restore/view stats\n"
        "🎁 Giving — give yen, XP, items, arts, pets\n"
        "🛡️ Moderation — bans, admins, logs, broadcasts\n"
        "💰 Economy — bank, market, auction, black market\n"
        "⚔️ Events & Raids — events, raids, missions, coop\n"
        "🎨 Cosmetics — skins, banners, accessories\n"
        "🏯 Clans — clan creation, members, bank\n"
        "🤖 Bot Control — maintenance, backup, DB\n"
        "📖 Info & Dex — itemdex, guide, styles, images\n"
        "⚔️ Combat & Pets — pets, trade, combat, styles"
    )

    await update.message.reply_text(
        menu_text,
        parse_mode="Markdown",
        reply_markup=_ownerhelp_menu_markup()
    )


async def ownerhelp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all ownerhelp_ button presses."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not is_owner(user_id):
        await query.answer("❌ Owner only.", show_alert=True)
        return

    data = query.data  # e.g. "ownerhelp_player" or "ownerhelp_menu"
    page_key = data[len("ownerhelp_"):]   # strip prefix

    if page_key == "menu":
        menu_text = (
            "👑 *OWNER COMMAND CENTRE*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "Select a category to view all commands:\n\n"
            "👤 Player Mgmt — view/edit/reset players\n"
            "📊 Stats — fix/restore/view stats\n"
            "🎁 Giving — give yen, XP, items, arts, pets\n"
            "🛡️ Moderation — bans, admins, logs, broadcasts\n"
            "💰 Economy — bank, market, auction, black market\n"
            "⚔️ Events & Raids — events, raids, missions, coop\n"
            "🎨 Cosmetics — skins, banners, accessories\n"
            "🏯 Clans — clan creation, members, bank\n"
            "🤖 Bot Control — maintenance, backup, DB\n"
            "📖 Info & Dex — itemdex, guide, styles, images\n"
            "⚔️ Combat & Pets — pets, trade, combat, styles"
        )
        try:
            await query.edit_message_text(
                menu_text,
                parse_mode="Markdown",
                reply_markup=_ownerhelp_menu_markup()
            )
        except Exception:
            pass
        return

    page = _OWNER_HELP_PAGES.get(page_key)
    if not page:
        await query.answer("Unknown page.", show_alert=True)
        return

    _label, content = page
    try:
        await query.edit_message_text(
            content,
            parse_mode="Markdown",
            reply_markup=_ownerhelp_back_markup()
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            log.error("[ownerhelp_callback] %s", e)
