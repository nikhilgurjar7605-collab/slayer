"""
Co-op Battle System — MongoDB version
"""
import random
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut
from utils.database import (get_player, get_battle_state, update_battle_enemy_hp,
                             update_player, get_party, col, add_item, get_arts)
from utils.helpers import hp_bar, get_level, get_unlocked_forms
from utils.guards import dm_only
from config import TECHNIQUES
from datetime import datetime


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


def get_party_member_ids(party):
    raw = party.get('members', [])
    if isinstance(raw, str):
        try: return json.loads(raw)
        except: return []
    return raw if isinstance(raw, list) else []


def build_coop_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚔️ Attack",       callback_data='coop_attack'),
            InlineKeyboardButton("💨 Technique",    callback_data='coop_technique'),
        ],
        [
            InlineKeyboardButton("🧪 Items",        callback_data='coop_items'),
            InlineKeyboardButton("🏃 Leave Battle", callback_data='coop_leave'),
        ]
    ])


def get_coop_battle(user_id):
    """Find coop battle where user is either host or guest."""
    doc = col("coop_battles").find_one({
        "$or": [{"guest_id": user_id}, {"host_id": user_id}],
        "status": "active"
    })
    if doc:
        doc.pop("_id", None)
        return doc
    return None


def get_coop_guests(host_id):
    docs = list(col("coop_battles").find({"host_id": host_id, "status": "active"}))
    for d in docs: d.pop("_id", None)
    return docs


def end_coop_battle(host_id):
    col("coop_battles").update_many(
        {"host_id": host_id, "status": "active"},
        {"$set": {"status": "finished"}}
    )


@dm_only
async def joinbattle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    party = get_party(user_id)
    if not party:
        await update.message.reply_text(
            "👥 *No party found!*\nJoin a party first with `/party`.",
            parse_mode='Markdown'
        )
        return

    leader_id = party['leader_id']
    members   = get_party_member_ids(party)

    # ── LEADER: show battle status ────────────────────────────────────────
    if leader_id == user_id:
        my_state = get_battle_state(user_id)
        if not my_state or not my_state.get('in_combat'):
            await update.message.reply_text(
                "⚔️ *You need to be in combat first!*\n\n"
                "Use /explore to find an enemy, press *Fight*, then your party members can `/joinbattle`!",
                parse_mode='Markdown'
            )
            return

        guests  = get_coop_guests(user_id)
        g_names = []
        for g in guests:
            gp = get_player(g['guest_id'])
            if gp: g_names.append(f"👤 {gp['name']}")

        bar = hp_bar(my_state['enemy_hp'], my_state['enemy_max_hp'])
        await update.message.reply_text(
            f"⚔️ *YOUR BATTLE IS OPEN!*\n\n"
            f"{my_state['enemy_emoji']} *{my_state['enemy_name']}*\n"
            f"❤️ {my_state['enemy_hp']}/{my_state['enemy_max_hp']} {bar}\n\n"
            f"👥 *Allies joined:* {len(guests)}\n"
            + ('\n'.join(g_names) if g_names else '_No allies yet_') +
            "\n\n_Tell your party to use `/joinbattle` to assist you!_",
            parse_mode='Markdown'
        )
        return

    # ── MEMBER: join the leader's active battle ───────────────────────────
    if get_battle_state(user_id):
        await update.message.reply_text(
            "⚔️ *You're already in your own battle!*\nFinish it first before joining another.",
            parse_mode='Markdown'
        )
        return

    leader_state = get_battle_state(leader_id)
    if not leader_state or not leader_state.get('in_combat'):
        await update.message.reply_text(
            "❌ *Your party leader is not in combat.*\nWait for them to start a fight!",
            parse_mode='Markdown'
        )
        return

    existing = col("coop_battles").find_one({"guest_id": user_id, "host_id": leader_id, "status": "active"})
    if existing:
        await update.message.reply_text("⚔️ You're already in this co-op battle!")
        return

    col("coop_battles").insert_one({
        "host_id":   leader_id,
        "guest_id":  user_id,
        "status":    "active",
        "joined_at": datetime.now()
    })

    leader = get_player(leader_id)
    state  = leader_state
    bar    = hp_bar(state['enemy_hp'], state['enemy_max_hp'])

    await update.message.reply_text(
        f"✅ *JOINED CO-OP BATTLE!*\n\n"
        f"Helping *{leader['name']}* fight:\n"
        f"{state['enemy_emoji']} *{state['enemy_name']}*\n"
        f"❤️ {state['enemy_hp']}/{state['enemy_max_hp']} {bar}\n\n"
        f"Use the buttons below to attack!",
        parse_mode='Markdown',
        reply_markup=build_coop_keyboard()
    )

    try:
        await context.bot.send_message(
            chat_id=leader_id,
            text=f"👥 *{player['name']}* joined your battle as an ally!",
            parse_mode='Markdown'
        )
    except Exception:
        pass


# ── ATTACK ────────────────────────────────────────────────────────────────

async def coop_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    coop = get_coop_battle(user_id)
    if not coop:
        await _safe_edit(query, "❌ You are not in a co-op battle. Use /joinbattle.")
        return

    host_id = coop['host_id']
    if user_id == host_id:
        await query.answer("⚔️ Fight using your main battle buttons!", show_alert=True)
        return

    state = get_battle_state(host_id)
    if not state or not state.get('in_combat'):
        col("coop_battles").update_one(
            {"guest_id": user_id, "status": "active"},
            {"$set": {"status": "ended"}}
        )
        await _safe_edit(query, "⚔️ The battle has ended!\nUse /joinbattle to join another fight.")
        return

    player = get_player(user_id)
    if not player:
        await _safe_edit(query, "❌ No character found.")
        return

    dmg    = player['str_stat'] * 2 + random.randint(5, 15)
    new_hp = max(0, state['enemy_hp'] - dmg)
    update_battle_enemy_hp(host_id, new_hp)

    bar = hp_bar(new_hp, state['enemy_max_hp'])

    if new_hp <= 0:
        col("coop_battles").update_one({"guest_id": user_id, "status": "active"}, {"$set": {"status": "finished"}})
        xp_share  = state['prize_xp'] // 3
        yen_share = state['prize_yen'] // 3
        update_player(user_id, xp=player['xp'] + xp_share, yen=player['yen'] + yen_share)
        await _safe_edit(
            query,
            f"☀️ *VICTORY! (Co-op assist)*\n\n"
            f"⭐ +{xp_share:,} XP\n"
            f"💰 +{yen_share:,}¥\n\n"
            f"_Great teamwork!_",
            parse_mode='Markdown'
        )
        return

    await _safe_edit(
        query,
        f"⚔️ *{player['name']}* attacks for *{dmg}* damage!\n\n"
        f"{state['enemy_emoji']} *{state['enemy_name']}*\n"
        f"❤️ {new_hp}/{state['enemy_max_hp']} {bar}",
        parse_mode='Markdown',
        reply_markup=build_coop_keyboard()
    )


# ── TECHNIQUE — Step 1: choose art ────────────────────────────────────────

async def coop_technique(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    coop = get_coop_battle(user_id)
    if not coop:
        await _safe_edit(query, "❌ You are not in a co-op battle. Use /joinbattle.")
        return

    host_id = coop['host_id']
    if user_id == host_id:
        await query.answer("⚔️ Use your main battle screen for techniques!", show_alert=True)
        return

    state = get_battle_state(host_id)
    if not state or not state.get('in_combat'):
        col("coop_battles").update_one({"guest_id": user_id, "status": "active"}, {"$set": {"status": "ended"}})
        await _safe_edit(query, "⚔️ The battle has ended!\nUse /joinbattle to join another fight.")
        return

    player = get_player(user_id)
    if not player:
        await _safe_edit(query, "❌ No character found.")
        return

    # Build art selection buttons — main style + unlocked arts
    arts    = get_arts(user_id)
    buttons = [[InlineKeyboardButton(
        f"{player['style_emoji']} {player['style']}",
        callback_data=f"coop_art_{player['style']}"
    )]]
    for art in arts:
        buttons.append([InlineKeyboardButton(
            f"{art['art_emoji']} {art['art_name']} ✨",
            callback_data=f"coop_art_{art['art_name']}"
        )])
    if player.get('hybrid_style'):
        hs = player['hybrid_style']
        he = player.get('hybrid_emoji', '⚡')
        buttons.append([InlineKeyboardButton(
            f"{he} {hs} ⚡Hybrid",
            callback_data=f"coop_art_{hs}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data='coop_back')])

    await _safe_edit(
        query,
        "💨 *CHOOSE YOUR ART*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ── TECHNIQUE — Step 2: choose form (called from callback_router) ─────────

async def coop_art_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles coop_art_ARTNAME callbacks — shows form list."""
    query   = update.callback_query
    await query.answer()
    user_id  = query.from_user.id
    art_name = query.data[len("coop_art_"):]

    coop = get_coop_battle(user_id)
    if not coop:
        await _safe_edit(query, "❌ Not in a co-op battle.")
        return

    player = get_player(user_id)
    level  = get_level(player['xp'])
    forms  = get_unlocked_forms(art_name, level, player.get('rank'), player.get('faction'))

    if not forms:
        await query.answer("No forms unlocked for this art!", show_alert=True)
        return

    buttons = []
    for form in forms:
        buttons.append([InlineKeyboardButton(
            f"Form {form['form']} — {form['name']} | DMG:{form['dmg_min']}-{form['dmg_max']} STA:{form['sta_cost']}",
            callback_data=f"coop_form_{art_name}_{form['form']}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data='coop_technique')])

    await _safe_edit(
        query,
        f"💨 *{art_name.upper()}*\n\nChoose your form:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ── TECHNIQUE — Step 3: use form ─────────────────────────────────────────

async def coop_use_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles coop_form_ARTNAME_FORMNUM callbacks — applies technique damage."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    coop = get_coop_battle(user_id)
    if not coop:
        await _safe_edit(query, "❌ Not in a co-op battle.")
        return

    host_id = coop['host_id']
    state   = get_battle_state(host_id)
    if not state or not state.get('in_combat'):
        col("coop_battles").update_one({"guest_id": user_id, "status": "active"}, {"$set": {"status": "ended"}})
        await _safe_edit(query, "⚔️ The battle has ended!")
        return

    # Parse: coop_form_ARTNAME_FORMNUM
    parts    = query.data.split('_', 3)   # ['coop', 'form', 'ArtName', '2']
    art_name = parts[2]
    try:
        form_num = int(parts[3])
    except (IndexError, ValueError):
        await query.answer("Invalid form.", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await _safe_edit(query, "❌ No character found.")
        return

    # Validate form is unlocked
    level  = get_level(player['xp'])
    forms  = get_unlocked_forms(art_name, level, player.get('rank'), player.get('faction'))
    form   = next((f for f in forms if f['form'] == form_num), None)
    if not form:
        await query.answer(f"🔒 Form {form_num} is locked!", show_alert=True)
        return

    # Check stamina
    sta_cost = form['sta_cost']
    if player['sta'] < sta_cost:
        await query.answer(f"❌ Not enough STA! Need {sta_cost}, have {player['sta']}.", show_alert=True)
        return

    # Calculate damage
    hits      = form.get('hits', 1)
    total_dmg = 0
    hit_lines = []
    for i in range(hits):
        hit_dmg = random.randint(form['dmg_min'], form['dmg_max'])
        total_dmg += hit_dmg
        if hits > 1:
            hit_lines.append(f"  🔥 Hit {i+1} → {hit_dmg}")

    # Apply stamina cost
    update_player(user_id, sta=max(0, player['sta'] - sta_cost))

    # Apply damage to host's enemy
    new_hp = max(0, state['enemy_hp'] - total_dmg)
    update_battle_enemy_hp(host_id, new_hp)
    bar = hp_bar(new_hp, state['enemy_max_hp'])

    log = [
        f"💨 *{player['name']}* uses *{art_name} — Form {form_num}!*",
        f"✨ {form['name']}",
    ]
    log.extend(hit_lines)
    if hits == 1:
        log.append(f"🔥 {total_dmg} damage!")
    else:
        log.append(f"💥 Total: {total_dmg} damage!")

    # Victory check
    if new_hp <= 0:
        col("coop_battles").update_one({"guest_id": user_id, "status": "active"}, {"$set": {"status": "finished"}})
        xp_share  = state['prize_xp'] // 3
        yen_share = state['prize_yen'] // 3
        update_player(user_id, xp=player['xp'] + xp_share, yen=player['yen'] + yen_share)
        await _safe_edit(
            query,
            f"☀️ *VICTORY! (Co-op assist)*\n\n"
            f"{'chr(10)'.join(log)}\n\n"
            f"⭐ +{xp_share:,} XP\n"
            f"💰 +{yen_share:,}¥\n\n"
            f"_Great teamwork!_",
            parse_mode='Markdown'
        )
        return

    log += [
        "",
        f"{state['enemy_emoji']} *{state['enemy_name']}*",
        f"❤️ {new_hp}/{state['enemy_max_hp']} {bar}",
    ]

    await _safe_edit(
        query,
        '\n'.join(log),
        parse_mode='Markdown',
        reply_markup=build_coop_keyboard()
    )


# ── ITEMS ─────────────────────────────────────────────────────────────────

async def coop_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Use /use [item] from DM to use items!", show_alert=True)


# ── LEAVE ─────────────────────────────────────────────────────────────────

async def coop_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    col("coop_battles").update_many(
        {"guest_id": user_id, "status": "active"},
        {"$set": {"status": "left"}}
    )
    await _safe_edit(
        query,
        "🏃 *You left the co-op battle.*\nUse /explore to start your own fight.",
        parse_mode='Markdown'
    )


# ── BACK ──────────────────────────────────────────────────────────────────

async def coop_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    coop = get_coop_battle(user_id)
    if not coop:
        await _safe_edit(query, "Use /joinbattle to rejoin a co-op battle.")
        return

    host_id = coop['host_id']
    state   = get_battle_state(host_id)
    if not state or not state.get('in_combat'):
        await _safe_edit(query, "⚔️ The battle has ended!\nUse /joinbattle to join another fight.")
        return

    bar = hp_bar(state['enemy_hp'], state['enemy_max_hp'])
    await _safe_edit(
        query,
        f"{state['enemy_emoji']} *{state['enemy_name']}*\n"
        f"❤️ {state['enemy_hp']}/{state['enemy_max_hp']} {bar}\n\n"
        f"Choose your action:",
        parse_mode='Markdown',
        reply_markup=build_coop_keyboard()
    )


# ── JOIN CALLBACK ─────────────────────────────────────────────────────────

async def coop_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await joinbattle(update, context)


# ── USE ITEM (stub — handled via /use command) ────────────────────────────

async def coop_use_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("Use /use [item] in DM!", show_alert=True)
