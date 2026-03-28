import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut
from utils.database import (get_player, update_player, col, get_inventory,
                             remove_item, apply_status_effect,
                             get_status_effects, tick_status_effects, clear_status_effects)
from utils.helpers import get_level, hp_bar
from utils.guards import group_only
from utils.pressure import calc_pressure, pressure_display
from config import TECHNIQUES, STATUS_EFFECTS_DATA, TECHNIQUE_STATUS_EFFECTS


# ── Safe edit ─────────────────────────────────────────────────────────────

async def _safe_edit(query, text, **kwargs):
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


# ── Helpers ───────────────────────────────────────────────────────────────

def duel_hp_bar(hp, max_hp):
    return hp_bar(hp, max_hp)


def build_duel_keyboard(user_id, challenger_id=None):
    """
    Build the duel action keyboard for the player whose turn it is.
    user_id = turn player (attack/technique use their id)
    challenger_id = who originally started the duel (settings use their id)
    Surrender uses 'duel_surrender_me' so any player can surrender at any time.
    """
    ch_id = challenger_id if challenger_id is not None else user_id
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚔️ Attack",        callback_data=f"duel_attack_{user_id}"),
            InlineKeyboardButton("💨 Technique",     callback_data=f"duel_technique_{user_id}"),
        ],
        [
            InlineKeyboardButton("🧪 Items",         callback_data=f"duel_items_{user_id}"),
            InlineKeyboardButton("🏳️ Surrender",     callback_data="duel_surrender_me"),
        ],
        [
            InlineKeyboardButton("🤝 Propose Draw",  callback_data=f"duel_draw_{user_id}"),
            InlineKeyboardButton("⚙️ Settings",      callback_data=f"duel_settings_{ch_id}"),
        ],
    ])


def waiting_keyboard(turn_name):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"⏳ Waiting for {turn_name}...", callback_data="duel_wait")
    ]])


def duel_status_text(p1, p1_hp, p1_max, p2, p2_hp, p2_max, turn_name, pressure=None, combo=0):
    bar1 = duel_hp_bar(p1_hp, p1_max)
    bar2 = duel_hp_bar(p2_hp, p2_max)
    fe1  = '🗡️' if p1['faction'] == 'slayer' else '👹'
    fe2  = '🗡️' if p2['faction'] == 'slayer' else '👹'
    combo_line    = f"\n🔥 *Combo ×{combo}!*" if combo >= 3 else ""
    pressure_line = f"\n{pressure_display(pressure)}" if pressure else ""
    return (
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ *PvP DUEL*{pressure_line}{combo_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{fe1} *{p1['name']}*\n"
        f"❤️ {p1_hp}/{p1_max} {bar1}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{fe2} *{p2['name']}*\n"
        f"❤️ {p2_hp}/{p2_max} {bar2}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *{turn_name}'s turn*"
    )


def get_active_duel(user_id):
    doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    if doc:
        doc.pop("_id", None)
    return doc


def get_opponent_id(duel, user_id):
    return duel['target_id'] if duel['challenger_id'] == user_id else duel['challenger_id']


def _duel_hp_key(duel, user_id):
    if duel['challenger_id'] == user_id:
        return 'challenger_hp', 'target_hp', 'challenger_max_hp', 'target_max_hp'
    return 'target_hp', 'challenger_hp', 'target_max_hp', 'challenger_max_hp'


def _challenge_keyboard(challenger_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Accept",   callback_data=f"duel_accept_{challenger_id}"),
            InlineKeyboardButton("❌ Decline",  callback_data=f"duel_decline_{challenger_id}"),
        ],
        [InlineKeyboardButton("⚙️ Settings", callback_data=f"duel_settings_{challenger_id}")]
    ])


def _challenge_text(player, settings=None):
    fe    = "🗡️" if player["faction"] == "slayer" else "👹"
    level = get_level(player["xp"])
    tags  = []
    if settings:
        if settings.get("no_items"):        tags.append("🚫 No Items")
        if settings.get("techniques_only"): tags.append("🌀 Techniques Only")
        hpm = settings.get("hp_multiplier", 1.0)
        if hpm != 1.0:                      tags.append(f"❤️ HP ×{hpm}")
    rules = f"\n⚙️ *Rules:* {' | '.join(tags)}" if tags else ""
    return (
        f"⚔️ *DUEL CHALLENGE!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{fe} *{player['name']}* (Lv.{level}) issued a challenge!\n"
        f"🏅 Rank: {player['rank']} {player['rank_kanji']}"
        f"{rules}\n\n"
        f"Do you accept?"
    )


# ── /challenge ────────────────────────────────────────────────────────────

@group_only
async def challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    if get_active_duel(user_id):
        await update.message.reply_text(
            "⚔️ *You are already in a duel!*\n\nFinish it first or use /unstuck.",
            parse_mode='Markdown'
        )
        return

    target = None
    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        if replied_user.is_bot:
            await update.message.reply_text("❌ You can't challenge a bot!")
            return
        target = col("players").find_one({"user_id": replied_user.id})
        if not target:
            await update.message.reply_text(
                f"❌ *{replied_user.first_name}* hasn't created a character yet!",
                parse_mode='Markdown'
            )
            return
    elif context.args:
        username = context.args[0].lstrip('@')
        target   = col("players").find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
        if not target:
            await update.message.reply_text(f"❌ Player *@{username}* not found.", parse_mode='Markdown')
            return
    else:
        await update.message.reply_text(
            "⚔️ *HOW TO DUEL*\n\n"
            "📌 Reply to someone's message → `/challenge`\n"
            "📌 Or: `/challenge @username`\n\n"
            "_Duel plays out right here in the group!_",
            parse_mode='Markdown'
        )
        return

    if target['user_id'] == user_id:
        await update.message.reply_text("❌ You can't challenge yourself!")
        return
    if get_active_duel(target['user_id']):
        await update.message.reply_text(f"❌ *{target['name']}* is already in a duel!", parse_mode='Markdown')
        return

    # Expire old pending duels from this challenger
    col("duels").update_many(
        {"challenger_id": user_id, "status": "pending"},
        {"$set": {"status": "expired"}}
    )

    from datetime import datetime as _dt
    col("duels").insert_one({
        "challenger_id": user_id,
        "target_id":     target['user_id'],
        "status":        "pending",
        "created_at":    _dt.now()
    })

    fe  = '🗡️' if player['faction'] == 'slayer' else '👹'
    fe2 = '🗡️' if target['faction'] == 'slayer' else '👹'
    lv  = get_level(player['xp'])

    await update.message.reply_text(
        f"⚔️ *DUEL CHALLENGE!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{fe} *{player['name']}* (Lv.{lv}) challenges {fe2} *{target['name']}*!\n"
        f"🏅 Rank: {player['rank']} {player['rank_kanji']}\n\n"
        f"*{target['name']}*, do you accept?",
        parse_mode='Markdown',
        reply_markup=_challenge_keyboard(user_id)
    )


# ── Accept / Decline ──────────────────────────────────────────────────────

async def duel_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query         = update.callback_query
    await query.answer()
    user_id       = query.from_user.id
    challenger_id = int(query.data.split('_')[-1])

    if user_id == challenger_id:
        await query.answer("❌ You can't accept your own challenge!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "challenger_id": challenger_id,
        "target_id":     user_id,
        "status":        "pending"
    })
    if not duel_doc:
        await _safe_edit(query, "❌ This challenge has expired or was already handled.")
        return

    challenger = get_player(challenger_id)
    target     = get_player(user_id)
    if not challenger or not target:
        await _safe_edit(query, "❌ Player data not found.")
        return

    settings  = context.user_data.get(f"duel_settings_{challenger_id}", {})
    hp_mult   = settings.get("hp_multiplier", 1.0)
    ch_hp     = int(challenger['hp'] * hp_mult)
    ch_max_hp = int(challenger['max_hp'] * hp_mult)
    tg_hp     = int(target['hp'] * hp_mult)
    tg_max_hp = int(target['max_hp'] * hp_mult)

    first        = challenger_id if challenger['spd'] >= target['spd'] else user_id
    first_player = challenger if first == challenger_id else target

    col("duels").update_one({"_id": duel_doc["_id"]}, {"$set": {
        "status":          "active",
        "turn_user_id":    first,
        "challenger_hp":   ch_hp,   "challenger_max_hp": ch_max_hp,
        "target_hp":       tg_hp,   "target_max_hp":     tg_max_hp,
        "settings":        settings,
    }})

    duel_key = str(duel_doc["_id"])
    pressure = calc_pressure(challenger)
    context.bot_data[f"duel_pressure_{duel_key}"] = pressure
    context.bot_data[f"duel_combo_{duel_key}"]    = 0

    status = duel_status_text(
        challenger, ch_hp, ch_max_hp,
        target,     tg_hp, tg_max_hp,
        first_player['name'], pressure
    )

    tags = []
    if settings.get("no_items"):        tags.append("🚫 No Items")
    if settings.get("techniques_only"): tags.append("🌀 Techniques Only")
    if hp_mult != 1.0:                  tags.append(f"❤️ HP ×{hp_mult}")
    rules_line = f"\n⚙️ *Rules:* {' | '.join(tags)}" if tags else ""

    await _safe_edit(
        query,
        f"✅ *DUEL ACCEPTED!*{rules_line}\n\n"
        f"⚡ _{first_player['name']} moves first (higher SPD)_\n\n"
        f"{status}",
        parse_mode='Markdown',
        reply_markup=build_duel_keyboard(first, challenger_id=challenger_id)
    )


async def duel_decline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query         = update.callback_query
    await query.answer()
    user_id       = query.from_user.id
    challenger_id = int(query.data.split('_')[-1])
    col("duels").update_one(
        {"challenger_id": challenger_id, "target_id": user_id, "status": "pending"},
        {"$set": {"status": "declined"}}
    )
    decliner = get_player(user_id)
    await _safe_edit(query, f"❌ *{decliner['name'] if decliner else 'Player'}* declined the duel.", parse_mode='Markdown')


async def duel_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("⏳ Wait for your turn!", show_alert=True)


async def duel_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current duel status WITHOUT consuming a turn — used by Back buttons."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    if not duel_doc:
        await _safe_edit(query, "⚔️ No active duel found.", parse_mode='Markdown')
        return

    duel    = dict(duel_doc); duel_oid = duel_doc["_id"]; duel.pop("_id", None)
    duel_key = str(duel_oid)
    opp_id  = get_opponent_id(duel, user_id)
    c_player = get_player(duel['challenger_id'])
    t_player = get_player(duel['target_id'])
    turn_player = get_player(duel['turn_user_id'])
    pressure = context.bot_data.get(f"duel_pressure_{duel_key}") or calc_pressure(c_player)
    combo    = context.bot_data.get(f"duel_combo_{duel_key}", 0)

    status = duel_status_text(
        c_player, duel['challenger_hp'], duel['challenger_max_hp'],
        t_player, duel['target_hp'],     duel['target_max_hp'],
        turn_player['name'] if turn_player else "?", pressure, combo
    )
    # Show correct keyboard for whose turn it is
    turn_id = duel['turn_user_id']
    await _safe_edit(query, status, parse_mode='Markdown',
                     reply_markup=build_duel_keyboard(turn_id))


# ── Finish duel ───────────────────────────────────────────────────────────

async def _finish_duel(query, duel_doc, winner_id, loser_id, context, reason="KO"):
    col("duels").update_one({"_id": duel_doc["_id"]}, {"$set": {"status": "finished"}})

    winner = get_player(winner_id)
    loser  = get_player(loser_id)
    if not winner or not loser:
        await _safe_edit(query, "⚔️ *Duel ended.*", parse_mode='Markdown')
        return

    xp_win = 300; yen_win = 150; xp_loss = 100

    # SP limit: max 5 SP per unique opponent per day
    from datetime import datetime, timedelta
    today_key = f"pvp_sp_{winner_id}_{loser_id}_{datetime.utcnow().strftime('%Y%m%d')}"
    sp_today  = context.bot_data.get(today_key, 0)
    SP_PER_PERSON_LIMIT = 7
    sp_win = 0
    if sp_today < SP_PER_PERSON_LIMIT:
        sp_win = min(1, SP_PER_PERSON_LIMIT - sp_today)
        context.bot_data[today_key] = sp_today + sp_win

    update_player(winner_id, xp=winner['xp'] + xp_win, yen=winner['yen'] + yen_win,
                  skill_points=winner.get('skill_points', 0) + sp_win)
    update_player(loser_id,  xp=max(0, loser['xp'] - xp_loss), deaths=loser['deaths'] + 1)

    wf = get_player(winner_id); lf = get_player(loser_id)
    update_player(winner_id, hp=wf['max_hp'], sta=wf['max_sta'])
    update_player(loser_id,  hp=int(lf['max_hp'] * 0.5), sta=lf['max_sta'])

    fe_w = '🗡️' if winner['faction'] == 'slayer' else '👹'
    await _safe_edit(
        query,
        f"🏆 *DUEL OVER!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{fe_w} *{winner['name']}* wins! _({reason})_\n\n"
        f"✅ *{winner['name']}:* +{xp_win} XP  +{yen_win}¥" + (f"  +{sp_win} SP" if sp_win else "  _(SP limit reached)_") + "\n"
        f"💔 *{loser['name']}:*  -{xp_loss} XP\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"_Rematch? Use /challenge to duel again!_",
        parse_mode='Markdown'
    )


# ── Attack ────────────────────────────────────────────────────────────────

async def duel_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query       = update.callback_query
    await query.answer()
    user_id     = query.from_user.id
    attacker_id = int(query.data.split('_')[-1])

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    if not duel_doc or duel_doc['turn_user_id'] != user_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel     = dict(duel_doc); duel_oid = duel_doc["_id"]; duel.pop("_id", None)
    attacker = get_player(user_id)
    opp_id   = get_opponent_id(duel, user_id)
    defender = get_player(opp_id)

    my_hp_key, opp_hp_key, my_max_key, opp_max_key = _duel_hp_key(duel, user_id)
    my_hp  = duel[my_hp_key]
    opp_hp = duel[opp_hp_key]

    duel_key = str(duel_oid)
    pressure = context.bot_data.get(f"duel_pressure_{duel_key}") or calc_pressure(attacker)
    combo    = context.bot_data.get(f"duel_combo_{duel_key}", 0)

    # Techniques only mode check
    if duel.get("settings", {}).get("techniques_only"):
        await query.answer("🌀 Techniques Only mode! Use 💨 Technique.", show_alert=True)
        return

    # PvP damage is intentionally lower than explore (no skill bonuses, lower multiplier)
    dmg = int(attacker['str_stat'] * 0.45) + random.randint(2, 6)
    dmg = int(dmg * pressure['atk_mult'])
    if combo >= 3: dmg = int(dmg * 1.15)

    # Base crit/dodge only — no skill bonuses in PvP
    crit  = random.random() < 0.12
    dodge = random.random() < 0.08
    if crit: dmg = int(dmg * 1.4)

    log_lines = []
    if dodge:
        log_lines.append(f"💨 *{defender['name']}* dodges!")
        combo = 0
        new_opp_hp = opp_hp
    else:
        new_opp_hp = max(0, opp_hp - dmg)
        log_lines.append(f"⚔️ *{attacker['name']}* attacks!")
        log_lines.append(f"💥 *CRITICAL!* {dmg} damage!" if crit else f"💥 {dmg} damage!")
        combo += 1
        if new_opp_hp <= 0:
            context.bot_data[f"duel_combo_{duel_key}"] = 0
            col("duels").update_one({"_id": duel_oid}, {"$set": {opp_hp_key: 0}})
            await _finish_duel(query, duel_doc, user_id, opp_id, context, "KO")
            return

    context.bot_data[f"duel_combo_{duel_key}"] = combo
    col("duels").update_one({"_id": duel_oid}, {"$set": {opp_hp_key: new_opp_hp, "turn_user_id": opp_id}})

    c_hp = my_hp      if duel['challenger_id'] == user_id else new_opp_hp
    t_hp = new_opp_hp if duel['challenger_id'] == user_id else my_hp

    status = duel_status_text(
        get_player(duel['challenger_id']), c_hp, duel['challenger_max_hp'],
        get_player(duel['target_id']),     t_hp, duel['target_max_hp'],
        defender['name'], pressure, combo
    )
    await _safe_edit(
        query,
        f"📜 *LOG*\n" + '\n'.join(log_lines) + f"\n\n{status}",
        parse_mode='Markdown',
        reply_markup=build_duel_keyboard(opp_id)
    )


# ── Technique ─────────────────────────────────────────────────────────────

async def duel_technique_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show art selection — supports hybrid (switch between primary + hybrid art)."""
    query       = update.callback_query
    await query.answer()
    user_id     = query.from_user.id
    attacker_id = int(query.data.split('_')[-1])

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    if not duel_doc or duel_doc['turn_user_id'] != user_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await query.answer("❌ No character found!", show_alert=True)
        return

    # Build art selection buttons
    buttons = []

    # Primary art
    buttons.append([InlineKeyboardButton(
        f"{player.get('style_emoji','💨')} {player['style']} (Primary)",
        callback_data=f"duel_art_{user_id}_{player['style'].replace(' ','_')}"
    )])

    # Hybrid art (if unlocked)
    if player.get('hybrid_style'):
        hs = player['hybrid_style']
        he = player.get('hybrid_emoji', '⚡')
        buttons.append([InlineKeyboardButton(
            f"{he} {hs} ⚡ (Hybrid)",
            callback_data=f"duel_art_{user_id}_{hs.replace(' ','_')}"
        )])

    buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"duel_view_{user_id}")])

    # If only one art available — skip art selection, go straight to forms
    if not player.get('hybrid_style'):
        await _show_duel_forms(query, user_id, player, player['style'])
        return

    await _safe_edit(
        query,
        f"💨 *CHOOSE ART*\n\nYou have Hybrid Mode active!\nWhich art will you use?",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def _show_duel_forms(query, user_id, player, art_name):
    """Show form selection for a given art in a duel."""
    level = get_level(player['xp'])
    from utils.helpers import get_unlocked_forms
    forms = get_unlocked_forms(art_name, level)

    if not forms:
        await query.answer(f"No forms unlocked for {art_name}!", show_alert=True)
        return

    buttons = []
    for f in forms[:9]:
        buttons.append([InlineKeyboardButton(
            f"Form {f['form']} — {f['name']} | {f['dmg_min']}-{f['dmg_max']} DMG",
            callback_data=f"duel_form_{user_id}_{f['form']}_{art_name.replace(' ','_')}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"duel_technique_{user_id}")])

    await _safe_edit(
        query,
        f"💨 *{art_name.upper()}*\n\nChoose your form:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def duel_art_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle art selection in duel — shows forms for the selected art."""
    query       = update.callback_query
    await query.answer()
    user_id     = query.from_user.id
    parts       = query.data.split('_', 3)  # duel_art_USERID_ArtName
    attacker_id = int(parts[2])
    art_name    = parts[3].replace('_', ' ')

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await query.answer("❌ No character found!", show_alert=True)
        return

    # Validate: art must be player's primary or hybrid style
    valid_arts = [player.get('style', '')]
    if player.get('hybrid_style'):
        valid_arts.append(player['hybrid_style'])

    if art_name not in valid_arts:
        await query.answer(f"❌ You don't have access to {art_name}!", show_alert=True)
        return

    await _show_duel_forms(query, user_id, player, art_name)


async def duel_use_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query       = update.callback_query
    await query.answer()
    user_id     = query.from_user.id
    # Supports both old format: duel_form_{uid}_{form}
    # and new format: duel_form_{uid}_{form}_{art_name}
    parts       = query.data.split('_')
    attacker_id = int(parts[2])
    form_num    = int(parts[3])
    # Art name: parts[4:] joined, or fall back to player's primary style
    art_name_raw = '_'.join(parts[4:]) if len(parts) > 4 else None

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    if not duel_doc or duel_doc['turn_user_id'] != user_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel     = dict(duel_doc); duel_oid = duel_doc["_id"]; duel.pop("_id", None)
    attacker = get_player(user_id)
    opp_id   = get_opponent_id(duel, user_id)
    level    = get_level(attacker['xp'])

    # Determine which art to use
    if art_name_raw:
        art_name = art_name_raw.replace('_', ' ')
    else:
        art_name = attacker['style']

    from utils.helpers import get_unlocked_forms
    forms = get_unlocked_forms(art_name, level)
    form  = next((f for f in forms if f['form'] == form_num), None)
    if not form:
        await query.answer("Form not available!", show_alert=True)
        return

    duel_key = str(duel_oid)
    pressure = context.bot_data.get(f"duel_pressure_{duel_key}") or calc_pressure(attacker)

    _, opp_hp_key, _, _ = _duel_hp_key(duel, user_id)
    opp_hp  = duel[opp_hp_key]
    enemy_state = {
        "enemy_hp": opp_hp,
        "enemy_max_hp": duel['challenger_max_hp'] if opp_hp_key == 'challenger_hp' else duel['target_max_hp'],
    }
    try:
        from handlers.explore import _safe_get_skills, _safe_get_bonuses, _calculate_form_hit_damage
        owned_skills = _safe_get_skills(user_id)
        bonuses = _safe_get_bonuses(user_id, None)
        dmg = _calculate_form_hit_damage(
            attacker,
            form,
            enemy_state,
            owned_skills=owned_skills,
            user_id=user_id,
            context=None,
            bonuses=bonuses,
            log=None,
        )
    except Exception:
        dmg = random.randint(form['dmg_min'], form['dmg_max'])
    dmg = int(dmg * 0.70)
    dmg = int(dmg * pressure['tech_mult'])
    new_opp = max(0, opp_hp - dmg)

    # Show technique image if available
    try:
        from handlers.explore import _send_art_image
        context.bot_data[f"art_reply_to_message_id_{query.message.chat_id}"] = query.message.message_id
        await _send_art_image(context, query.message.chat_id, art_name,
                              caption=f"⚔️ *{art_name}* — Form {form_num}: *{form['name']}*",
                              form_num=form_num)
    except Exception:
        pass

    log_lines = [
        f"💨 *{attacker['name']}* uses *{art_name} Form {form_num}!*",
        f"✨ *{form['name']}*",
        f"💥 {dmg} damage!",
    ]

    if new_opp <= 0:
        col("duels").update_one({"_id": duel_oid}, {"$set": {opp_hp_key: 0}})
        await _finish_duel(query, duel_doc, user_id, opp_id, context, "Technique KO")
        return

    col("duels").update_one({"_id": duel_oid}, {"$set": {opp_hp_key: new_opp, "turn_user_id": opp_id}})

    c_hp = duel['challenger_hp'] if duel['challenger_id'] == user_id else new_opp
    t_hp = new_opp if duel['challenger_id'] == user_id else duel['target_hp']

    combo = context.bot_data.get(f"duel_combo_{duel_key}", 0) + 1
    context.bot_data[f"duel_combo_{duel_key}"] = combo

    opp_player = get_player(opp_id)
    status = duel_status_text(
        get_player(duel['challenger_id']), c_hp, duel['challenger_max_hp'],
        get_player(duel['target_id']),     t_hp, duel['target_max_hp'],
        opp_player['name'] if opp_player else "Opponent", pressure, combo
    )
    await _safe_edit(
        query,
        f"📜 *LOG*\n" + '\n'.join(log_lines) + f"\n\n{status}",
        parse_mode='Markdown',
        reply_markup=build_duel_keyboard(opp_id)
    )


# ── Items ─────────────────────────────────────────────────────────────────

async def duel_items_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query       = update.callback_query
    await query.answer()
    user_id     = query.from_user.id
    attacker_id = int(query.data.split('_')[-1])

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    if duel_doc and duel_doc.get("settings", {}).get("no_items"):
        await query.answer("🚫 No Items mode is active!", show_alert=True)
        return

    inv     = get_inventory(user_id)
    usables = [i for i in inv if i['item_type'] == 'item']
    if not usables:
        await query.answer("No usable items!", show_alert=True)
        return

    buttons = []
    for item in usables[:5]:
        buttons.append([InlineKeyboardButton(
            f"🧪 {item['item_name']} ×{item['quantity']}",
            callback_data=f"duel_useitem_{user_id}_{item['item_name'].replace(' ','_')}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"duel_view_{user_id}")])

    await _safe_edit(
        query, "🧪 *USE ITEM*\n\nChoose an item:",
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons)
    )


async def duel_use_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query       = update.callback_query
    await query.answer()
    user_id     = query.from_user.id
    parts       = query.data.split('_')
    attacker_id = int(parts[2])
    item_name   = ' '.join(parts[3:]).replace('_', ' ')

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    if not duel_doc:
        await query.answer("No active duel found!", show_alert=True)
        return

    duel = dict(duel_doc); duel_oid = duel_doc["_id"]; duel.pop("_id", None)
    inv  = get_inventory(user_id)
    owned = next((i for i in inv if i['item_name'].lower() == item_name.lower()), None)
    if not owned:
        await query.answer("Item not found!", show_alert=True)
        return

    player = get_player(user_id)
    opp_id = get_opponent_id(duel, user_id)
    my_hp_k, opp_hp_k, my_max_k, _ = _duel_hp_key(duel, user_id)
    my_max = duel[my_max_k]

    result = ""
    if 'Gourd' in owned['item_name']:
        col("duels").update_one({"_id": duel_oid}, {"$set": {my_hp_k: my_max}})
        result = "❤️ HP fully restored!"
    elif 'Stamina' in owned['item_name']:
        result = "🌀 +50 STA!"

    remove_item(user_id, owned['item_name'])
    col("duels").update_one({"_id": duel_oid}, {"$set": {"turn_user_id": opp_id}})

    fresh    = col("duels").find_one({"_id": duel_oid})
    c_hp     = fresh['challenger_hp'] if fresh else 0
    t_hp     = fresh['target_hp']     if fresh else 0
    opp      = get_player(opp_id)
    duel_key = str(duel_oid)
    pressure = context.bot_data.get(f"duel_pressure_{duel_key}")

    status = duel_status_text(
        get_player(duel['challenger_id']), c_hp, duel['challenger_max_hp'],
        get_player(duel['target_id']),     t_hp, duel['target_max_hp'],
        opp['name'] if opp else "Opponent", pressure
    )
    await _safe_edit(
        query,
        f"📜 *LOG*\n🧪 *{player['name']}* used *{owned['item_name']}*!\n{result}\n\n{status}",
        parse_mode='Markdown',
        reply_markup=build_duel_keyboard(opp_id)
    )


# ── Surrender ─────────────────────────────────────────────────────────────

async def duel_surrender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    # Any participant can surrender at any time — no turn check
    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    if not duel_doc:
        await query.answer("No active duel found!", show_alert=True)
        return
    opp_id = get_opponent_id(dict(duel_doc), user_id)
    await _finish_duel(query, duel_doc, opp_id, user_id, context, "Surrender")


# ── Settings ──────────────────────────────────────────────────────────────

async def duel_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query         = update.callback_query
    await query.answer()
    user_id       = query.from_user.id
    try:
        challenger_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.answer("Invalid.", show_alert=True)
        return

    if user_id != challenger_id:
        await query.answer("Only the challenger can change settings!", show_alert=True)
        return

    settings = context.user_data.get(f"duel_settings_{challenger_id}", {
        "no_items": False, "techniques_only": False, "hp_multiplier": 1.0,
    })
    ni  = settings.get("no_items", False)
    to  = settings.get("techniques_only", False)
    hpm = settings.get("hp_multiplier", 1.0)

    buttons = [
        [InlineKeyboardButton(("✅ " if ni else "⬜ ") + "No Items Mode",
            callback_data=f"duel_toggle_noitems_{challenger_id}")],
        [InlineKeyboardButton(("✅ " if to else "⬜ ") + "Techniques Only",
            callback_data=f"duel_toggle_techonly_{challenger_id}")],
        [InlineKeyboardButton(f"❤️ HP Multiplier: {hpm}x  (tap to cycle)",
            callback_data=f"duel_toggle_hp_{challenger_id}")],
        [
            InlineKeyboardButton("🔙 Cancel", callback_data=f"duel_settings_back_{challenger_id}"),
            InlineKeyboardButton("✅ Save",   callback_data=f"duel_settings_done_{challenger_id}"),
        ],
    ]
    await _safe_edit(
        query,
        "⚙️ *DUEL SETTINGS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🚫 No Items:        {'*ON*' if ni else 'OFF'}\n"
        f"🌀 Techniques Only: {'*ON*' if to else 'OFF'}\n"
        f"❤️ HP Multiplier:   *{hpm}x*\n\n"
        "_Tap to toggle. Cancel = discard, Save = apply._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def duel_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts   = query.data.split('_')
    ch_id   = int(parts[-1])
    toggle  = parts[2]

    if user_id != ch_id:
        await query.answer("❌ Only the challenger!", show_alert=True)
        return

    settings = context.user_data.get(f'duel_settings_{ch_id}', {
        'no_items': False, 'techniques_only': False, 'hp_multiplier': 1.0,
    })
    if toggle == 'noitems':
        settings['no_items'] = not settings.get('no_items', False)
    elif toggle == 'techonly':
        settings['techniques_only'] = not settings.get('techniques_only', False)
    elif toggle == 'hp':
        cycle = [0.5, 1.0, 1.5, 2.0]
        cur   = settings.get('hp_multiplier', 1.0)
        try: idx = cycle.index(cur)
        except ValueError: idx = 1
        settings['hp_multiplier'] = cycle[(idx + 1) % len(cycle)]

    context.user_data[f'duel_settings_{ch_id}'] = settings
    await duel_settings_callback(update, context)


async def duel_settings_back_callback(update, context):
    """Cancel — discard changes, go back to challenge screen."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    ch_id   = int(query.data.split('_')[-1])

    if user_id != ch_id:
        await query.answer("Only the challenger!", show_alert=True)
        return

    context.user_data.pop(f"duel_settings_{ch_id}", None)  # discard changes

    player = get_player(user_id)
    if not player:
        await _safe_edit(query, "No character found.")
        return

    await _safe_edit(
        query,
        _challenge_text(player),
        parse_mode="Markdown",
        reply_markup=_challenge_keyboard(ch_id)
    )


async def duel_settings_done_callback(update, context):
    """Save — keep settings and return to challenge screen."""
    query   = update.callback_query
    await query.answer("✅ Settings saved!")
    user_id = query.from_user.id
    ch_id   = int(query.data.split('_')[-1])

    if user_id != ch_id:
        await query.answer("Only the challenger can save settings!", show_alert=True)
        return

    settings = context.user_data.get(f"duel_settings_{ch_id}", {
        "no_items": False, "techniques_only": False, "hp_multiplier": 1.0,
    })
    player = get_player(user_id)
    if not player:
        await _safe_edit(query, "No character found.")
        return

    await _safe_edit(
        query,
        _challenge_text(player, settings),
        parse_mode="Markdown",
        reply_markup=_challenge_keyboard(ch_id)
    )


# ── Draw ──────────────────────────────────────────────────────────────────

async def duel_draw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    if not duel_doc:
        await query.answer("❌ No active duel found.", show_alert=True)
        return

    opponent_id      = get_opponent_id(dict(duel_doc), user_id)
    draw_proposed_by = duel_doc.get('draw_proposed_by')

    if draw_proposed_by == opponent_id:
        # Accept the draw
        col("duels").update_one({"_id": duel_doc["_id"]}, {"$set": {"status": "finished", "result": "draw"}})
        player   = get_player(user_id)
        opponent = get_player(opponent_id)
        xp_draw  = 150
        update_player(user_id,     xp=player['xp'] + xp_draw)
        update_player(opponent_id, xp=opponent['xp'] + xp_draw)

        fe_p = '🗡️' if player['faction'] == 'slayer' else '👹'
        fe_o = '🗡️' if opponent['faction'] == 'slayer' else '👹'
        await _safe_edit(
            query,
            f"🤝 *DRAW AGREED!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{fe_p} *{player['name']}* and\n"
            f"{fe_o} *{opponent['name']}*\n\n"
            f"_Both warriors acknowledged each other's strength._\n\n"
            f"✅ Both receive: *+{xp_draw} XP*\n"
            f"_No HP or Yen penalty_",
            parse_mode='Markdown'
        )
        return

    # Propose draw
    col("duels").update_one({"_id": duel_doc["_id"]}, {"$set": {"draw_proposed_by": user_id}})
    player   = get_player(user_id)
    opponent = get_player(opponent_id)

    accept_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("🤝 Accept Draw",   callback_data=f"duel_draw_{opponent_id}"),
        InlineKeyboardButton("⚔️ Keep Fighting", callback_data=f"duel_attack_{opponent_id}"),
    ]])
    await _safe_edit(
        query,
        f"🤝 *{player['name']}* proposes a *DRAW*!\n\n"
        f"_{opponent['name'] if opponent else 'Opponent'}, do you accept?_\n\n"
        f"_Accept = both get +150 XP, no penalty_\n"
        f"_Refuse = battle continues_",
        parse_mode='Markdown',
        reply_markup=accept_kb
    )


# ── Technique Details Panel ───────────────────────────────────────────────

async def duel_details_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    req_id  = int(query.data.split('_')[-1])

    if user_id != req_id:
        await query.answer("❌ These are not your techniques!", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await query.answer("❌ No character found.", show_alert=True)
        return

    from utils.helpers import get_level, get_unlocked_forms
    level     = get_level(player['xp'])
    style     = player['style']
    forms     = get_unlocked_forms(style, level, player.get('rank'), player.get('faction'))
    all_forms = TECHNIQUES.get(style, [])

    lines = [
        "╔══════════════════════╗",
        "      📋 𝙈𝙔 𝙏𝙀𝘾𝙃𝙉𝙄𝙌𝙐𝙀𝙎",
        f"╚══════════════════════╝\n",
        f"{player['style_emoji']} *{style}* — Lv.{level}\n",
        "━━━━━━━━━━━━━━━━━━━━━\n",
    ]
    unlocked_nums = {f['form'] for f in forms}
    for f in all_forms:
        if f['form'] in unlocked_nums:
            extras = []
            if f.get('hits', 1) > 1: extras.append(f"×{f['hits']} hits")
            if f.get('poison'):      extras.append("☠️ Poison")
            if f.get('effect'):      extras.append(f"✨ {f['effect'].replace('_',' ').title()}")
            extra_str = f"  _{'  |  '.join(extras)}_" if extras else ""
            lines.append(
                f"✅ *Form {f['form']}* — {f['name']}\n"
                f"   💥 {f['dmg_min']}–{f['dmg_max']} DMG  🌀 {f['sta_cost']} STA{extra_str}"
            )
        else:
            lines.append(f"🔒 *Form {f['form']}* — {f['name']}  _(locked)_")

    if player.get('hybrid_style'):
        hs = player['hybrid_style']; he = player.get('hybrid_emoji', '⚡')
        hforms = get_unlocked_forms(hs, level)
        lines.append(f"\n⚡ *HYBRID: {hs}* {he}\n")
        for f in hforms[:3]:
            lines.append(f"  ⚡ *Form {f['form']}* — {f['name']}\n"
                         f"     💥 {f['dmg_min']}–{f['dmg_max']}  🌀 {f['sta_cost']} STA")

    lines += [f"\n━━━━━━━━━━━━━━━━━━━━━", f"🌀 *STA:* {player['sta']}/{player['max_sta']}"]
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Battle", callback_data=f"duel_view_{user_id}")]])

    try:
        await _safe_edit(query, '\n'.join(lines), parse_mode='Markdown', reply_markup=kb)
    except Exception:
        await query.answer('\n'.join(lines[:5]), show_alert=True)
