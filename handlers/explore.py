import random
import json
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut
from utils.database import (get_player, get_battle_state, set_battle_state, clear_battle_state,
                             update_battle_enemy_hp, update_player, get_inventory, remove_item,
                             get_arts, get_party, set_active_ally, update_ally_hp, clear_ally,
                             col, append_battle_log, get_battle_log, clear_battle_log,
                             apply_status_effect, get_status_effects, tick_status_effects,
                             clear_status_effects)
from utils.helpers import get_unlocked_forms, get_level, hp_bar, get_rank
from utils.guards import dm_only, owner_only_button
from utils.pressure import calc_pressure, pressure_display, get_chaos_modifier
from config import TECHNIQUES, STATUS_EFFECTS_DATA, TECHNIQUE_STATUS_EFFECTS, SLAYER_ENEMIES, DEMON_ENEMIES, REGION_ENEMIES
from utils.effects import (apply_form_effect, process_dot_effects,
                            process_enemy_dots, is_enemy_frozen, is_enemy_staggered,
                            apply_enemy_context_effects)

import json as _json

# ── SKILL SAFE LOADER ─────────────────────────────────────────────────────
def _safe_get_skills(user_id):
    """Load player skills safely — returns empty list on any error."""
    try:
        from handlers.skilltree import get_player_skills as _gps_safe
        result = _gps_safe(user_id)
        return result if isinstance(result, list) else []
    except Exception:
        return []

def _safe_get_bonuses(user_id, context=None):
    """Load skill bonuses — respects deactivated and once_per_battle skills."""
    try:
        from handlers.skilltree import get_active_skill_bonuses as _gsb_safe
        skills = _safe_get_skills(user_id)
        used_once = []
        if context:
            ctx = context.user_data.get(f'battle_ctx_{user_id}', {})
            used_once = ctx.get('used_once_skills', [])
        return _gsb_safe(skills, user_id=user_id, used_once=used_once)
    except Exception:
        return {}

# ── DEVOUR SYSTEM ─────────────────────────────────────────────────────────
# Demon devours SLAYER/NEUTRAL enemies (absorbs human essence)
# Slayer absorbs DEMON essence from demon enemies
DEVOUR_TRIGGERS = {
    "demon":  ["slayer", "neutral"],   # demons devour humans/neutrals
    "slayer": ["demon"],               # slayers absorb demon essence
}
DEVOUR_STATS = {
    "slayer": [("str_stat", 1), ("def_stat", 1)],          # balanced
    "demon":  [("str_stat", 2), ("max_hp", 5), ("spd", 1)], # demons slightly stronger
}
MAX_DEVOUR_STACKS = 25


# ── SAFE EDIT HELPER ──────────────────────────────────────────────────────
async def safe_edit(query, text, **kwargs):
    """Edit a message, falling back to reply_text on failure."""
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        err = str(e)
        if "Message is not modified" in err:
            return  # Already showing this content — harmless
        elif "Message can't be edited" in err or "message to edit not found" in err.lower():
            await query.message.reply_text(text, **kwargs)
        else:
            raise
    except TimedOut:
        pass  # Transient network issue — safe to ignore




def get_enemies_for_region(player):
    """Get enemy for player's current region. Boss only spawns after 20 explores."""
    location = player.get('location', 'asakusa')
    region   = REGION_ENEMIES.get(location)
    faction  = player.get('faction', 'slayer')

    if not region:
        return random.choice(SLAYER_ENEMIES if faction == 'slayer' else DEMON_ENEMIES)

    all_enemies = region['enemies']
    if faction == 'slayer':
        pool = [e for e in all_enemies if e.get('faction_type') in ('demon', 'neutral')]
    else:
        pool = [e for e in all_enemies if e.get('faction_type') in ('slayer', 'neutral')]

    normal = [e for e in pool if not e.get('is_boss')]
    bosses = [e for e in pool if e.get('is_boss')]

    explores_since_boss = player.get('explores_since_boss', 20)
    boss_eligible = explores_since_boss >= 20

    if boss_eligible and bosses:
        chosen = random.choice(pool)
    else:
        chosen = random.choice(normal) if normal else random.choice(pool)

    return chosen


def get_enemies(faction):
    return SLAYER_ENEMIES if faction == 'slayer' else DEMON_ENEMIES


def build_combat_keyboard(has_ally=False):
    ally_label = "👥 Switch Ally" if has_ally else "👥 Call Ally"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚔️ Attack", callback_data='attack'),
            InlineKeyboardButton("💨 Technique", callback_data='technique'),
        ],
        [
            InlineKeyboardButton("🧪 Items", callback_data='items_menu'),
            InlineKeyboardButton(ally_label, callback_data='party_battle'),
        ],
        [InlineKeyboardButton("🏃 Flee", callback_data='flee')]
    ])


def build_encounter_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚔️ Fight!", callback_data='fight'),
            InlineKeyboardButton("🏆 Rewards", callback_data='prize'),
        ],
        [InlineKeyboardButton("🔍 Find Different Enemy", callback_data='goto_explore')]
    ])


def combat_status(player, state, ally=None, log_lines=None):
    p_bar = hp_bar(player['hp'], player['max_hp'])
    e_bar = hp_bar(state['enemy_hp'], state['enemy_max_hp'])

    ally_line = ""
    if ally and state.get('active_ally_id') and state.get('ally_hp') is not None:
        a_bar = hp_bar(state.get('ally_hp', 0), state.get('ally_max_hp', 1) or 1)
        ally_line = (
            f"\n👥 *{ally['name']}* (Ally)\n"
            f"❤️ HP: {state.get('ally_hp',0)}/{state.get('ally_max_hp',0)} {a_bar}\n"
        )

    log_section = ""
    if log_lines:
        recent = log_lines[-3:] if len(log_lines) > 3 else log_lines
        log_section = '\n'.join(recent) + "\n\n"

    return (
        f"{log_section}"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{state['enemy_emoji']} *{state['enemy_name']}*\n"
        f"❤️ HP: {state['enemy_hp']}/{state['enemy_max_hp']} {e_bar}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗡️ *{player['name']}*\n"
        f"❤️ HP: {player['hp']}/{player['max_hp']} {p_bar}\n"
        f"🌀 STA: {player['sta']}/{player['max_sta']}"
        f"{ally_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )


def get_active_ally(state):
    """Return the ally player row if one is active in battle, else None."""
    if not state or not state.get('active_ally_id'):
        return None
    from utils.database import get_player
    return get_player(state.get('active_ally_id'))


def get_party_member_ids(party):
    import json
    raw = party.get('members', '[]')
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []


# ── Defined early so fight() can reference it ─────────────────────────────
def set_battle_state_in_combat(user_id):
    col("battle_state").update_one({"user_id": user_id}, {"$set": {"in_combat": 1}})


def calc_dmg(player, base_min=8, base_max=20, owned_skills=None, is_technique=False, user_id=None, context=None):
    from handlers.skilltree import get_active_skill_bonuses
    sword_bonus = {
        'Basic Nichirin Blade':         8,
        'Crimson Nichirin Blade':       25,
        'Jet Black Nichirin Blade':     50,
        'Scarlet Crimson Blade':        80,
        'Transparent Nichirin Blade':  120,
        'Sun Nichirin Blade':          200,
    }
    s_bonus = sword_bonus.get(player.get('equipped_sword', ''), 0)
    base    = player['str_stat'] * 2 + random.randint(base_min, base_max) + s_bonus
    dmg     = base

    # Story bonus (applied ONCE only)
    if player.get('story_bonus') == 'dmg_bonus':
        dmg = int(dmg * 1.10)

    # Mark bonuses
    if player.get('slayer_mark'):
        dmg = int(dmg * 1.25)
    if player.get('demon_mark'):
        dmg = int(dmg * 1.20)

    # Skill bonuses
    if owned_skills:
        used_once = []
        if context and user_id:
            used_once = context.user_data.get(f'battle_ctx_{user_id}', {}).get('used_once_skills', [])
        bonuses = get_active_skill_bonuses(owned_skills, user_id=user_id, used_once=used_once)
        if not is_technique and 'atk_pct' in bonuses:
            dmg = int(dmg * (1 + bonuses['atk_pct']))
        if is_technique and 'tech_pct' in bonuses:
            dmg = int(dmg * (1 + bonuses['tech_pct']))
        if 'low_hp_dmg' in bonuses and player['hp'] < player['max_hp'] * 0.30:
            dmg = int(dmg * (1 + bonuses['low_hp_dmg']))
        # NOTE: story_bonus NOT applied again here (was a double-apply bug)
    return dmg


def calc_enemy_dmg(player, state, owned_skills=None, user_id=None, context=None):
    from handlers.skilltree import get_active_skill_bonuses
    armor_bonus = {
        'Corps Uniform':           5,
        'Reinforced Haori':       15,
        'Hashira Haori':          30,
        'Demon Slayer Uniform EX': 55,
        'Flame Haori':            85,
        'Yoriichi Haori':        150,
    }
    a_bonus = armor_bonus.get(player.get('equipped_armor', ''), 0)
    dmg = max(1, random.randint(int(state['enemy_atk'] * 0.8), state['enemy_atk']) - a_bonus)
    if player.get('story_bonus') == 'def_bonus':
        dmg = int(dmg * 0.90)

    if owned_skills:
        used_once = []
        if context and user_id:
            used_once = context.user_data.get(f'battle_ctx_{user_id}', {}).get('used_once_skills', [])
        bonuses = get_active_skill_bonuses(owned_skills, user_id=user_id, used_once=used_once)
        if 'dmg_reduce' in bonuses:
            dmg = max(1, int(dmg * (1 - bonuses['dmg_reduce'])))

    return dmg


def _technique_level_scale(player):
    level = get_level(player['xp'])
    return 1 + min(0.75, max(0, level - 1) * 0.015)


def _apply_battle_start_skill_bonuses(user_id, player, bonuses, context, log_lines=None):
    battle_ctx = context.user_data.setdefault(f'battle_ctx_{user_id}', {})
    if battle_ctx.get('battle_start_applied'):
        return player

    boost_hp = int(bonuses.get('battle_hp_boost', 0) or 0)
    if boost_hp > 0:
        update_player(user_id, hp=player['hp'] + boost_hp)
        player = get_player(user_id)
        if log_lines is not None:
            log_lines.append(f"💠 Battle start bonus: +{boost_hp} HP")

    battle_ctx['battle_start_applied'] = True
    battle_ctx.setdefault('used_once_skills', [])
    context.user_data[f'battle_ctx_{user_id}'] = battle_ctx
    return player


def _calculate_form_hit_damage(player, form, state, owned_skills=None, user_id=None, context=None, bonuses=None, log=None):
    owned_skills = owned_skills or []
    bonuses = bonuses or {}
    log = log if log is not None else []

    dmg = calc_dmg(
        player,
        base_min=form['dmg_min'],
        base_max=form['dmg_max'],
        owned_skills=owned_skills,
        is_technique=True,
        user_id=user_id,
        context=context,
    )
    dmg = int(dmg * _technique_level_scale(player))

    combo = context.user_data.get('combo', 0) if context else 0
    if combo > 0 and bonuses.get('combo_pct'):
        dmg = int(dmg * (1 + bonuses['combo_pct']))
        log.append(f"🔥 Combo Master: +{int(bonuses['combo_pct'] * 100)}% technique damage")

    if bonuses.get('first_strike') and combo == 0:
        dmg = int(dmg * (1 + bonuses['first_strike']))
        log.append(f"⚡ First Strike: +{int(bonuses['first_strike'] * 100)}% technique damage")

    if bonuses.get('low_hp_dmg') and player['hp'] < player['max_hp'] * 0.30:
        dmg = int(dmg * (1 + bonuses['low_hp_dmg']))
        log.append(f"🩸 Low HP boost: +{int(bonuses['low_hp_dmg'] * 100)}% technique damage")

    if bonuses.get('executioner') and state['enemy_hp'] < state['enemy_max_hp'] * 0.20:
        dmg = int(dmg * (1 + bonuses['executioner']))
        log.append(f"☠️ Executioner: +{int(bonuses['executioner'] * 100)}% technique damage")

    if bonuses.get('finish_pct') and state['enemy_hp'] < state['enemy_max_hp'] * 0.20:
        dmg = int(dmg * (1 + bonuses['finish_pct']))
        log.append(f"💥 Finisher: +{int(bonuses['finish_pct'] * 100)}% technique damage")

    if context and user_id and 'Death Blow' in owned_skills:
        battle_ctx = context.user_data.setdefault(f'battle_ctx_{user_id}', {})
        used_once = battle_ctx.setdefault('used_once_skills', [])
        if 'Death Blow' not in used_once:
            dmg = int(dmg * 1.50)
            used_once.append('Death Blow')
            log.append("💀 Death Blow activated: +50% form damage")
            context.user_data[f'battle_ctx_{user_id}'] = battle_ctx

    return max(1, dmg)


def _try_counter_strike(user_id, player, owned_skills, bonuses, context, log):
    chance = bonuses.get('counter_chance', 0)
    if chance <= 0 or random.random() >= chance:
        return False

    state = get_battle_state(user_id)
    if not state or state.get('enemy_hp', 0) <= 0:
        return False

    counter_dmg = max(1, int(calc_dmg(
        player,
        base_min=4,
        base_max=10,
        owned_skills=owned_skills,
        user_id=user_id,
        context=context,
    ) * 0.35))
    new_enemy_hp = max(0, state['enemy_hp'] - counter_dmg)
    update_battle_enemy_hp(user_id, new_enemy_hp)
    log.append(f"🔁 Counter Strike! {counter_dmg} damage back to *{state['enemy_name']}*")
    return new_enemy_hp <= 0


# ── EXPLORE ───────────────────────────────────────────────────────────────
def _apply_turn_end_player_sustain(user_id, player, current_hp, bonuses, context, log):
    battle_ctx = context.user_data.setdefault(f'battle_ctx_{user_id}', {})
    used_once = battle_ctx.setdefault('used_once_skills', [])

    if current_hp <= 0 and bonuses.get('second_wind'):
        if 'Second Wind' not in used_once and random.random() < bonuses['second_wind']:
            current_hp = 1
            used_once.append('Second Wind')
            log.append(f"ðŸ’ª *Second Wind!* Survived with 1 HP! _(used for this battle)_")

    if current_hp <= 0 and bonuses.get('last_stand'):
        if 'Last Stand' not in used_once:
            current_hp = 1
            used_once.append('Last Stand')
            log.append("ðŸ’€ *LAST STAND!* Survived with 1 HP! _(used for this battle)_")

    if bonuses.get('regen_pct') and current_hp > 0:
        regen_pct_hp = int(player['max_hp'] * bonuses['regen_pct'])
        if regen_pct_hp > 0:
            current_hp = min(player['max_hp'], current_hp + regen_pct_hp)
            log.append(f"ðŸ’š *Regeneration* +{regen_pct_hp} HP")

    if 'regen_hp' in bonuses and current_hp > 0:
        regen = int(bonuses['regen_hp'])
        if regen > 0:
            current_hp = min(player['max_hp'], current_hp + regen)
            log.append(f"ðŸ§¬ *Demon Regen* â€” +{regen} HP")

    battle_ctx['used_once_skills'] = used_once
    context.user_data[f'battle_ctx_{user_id}'] = battle_ctx
    return max(0, current_hp)


@dm_only
async def explore(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        async def send(text, **kwargs):
            return await query.message.reply_text(text, **kwargs)
    else:
        user_id = update.effective_user.id
        async def send(text, **kwargs):
            return await update.message.reply_text(text, **kwargs)

    player = get_player(user_id)
    if not player:
        await send("❌ No character found. Use /start to create one.")
        return
    if player.get('banned'):
        await send("❌ You are banned from this game.")
        return

    existing = get_battle_state(user_id)
    if existing and existing.get('in_combat'):
        # Only auto-unstuck when user TYPES /explore as a command
        # Button presses (from menu) show the active battle warning
        if update.message and update.effective_chat and update.effective_chat.type == 'private':
            # Check if this was a direct command — unstuck and restart
            clear_battle_state(user_id)
            for key in list(context.user_data.keys()):
                if str(user_id) in str(key) or key.startswith('battle_') or key.startswith('last_stand'):
                    context.user_data.pop(key, None)
            existing = None
        else:
            # Button press during active battle — block and show current battle info
            enemy_name = existing.get('enemy_name', 'an enemy')
            enemy_hp   = existing.get('enemy_hp', '?')
            enemy_max  = existing.get('enemy_max_hp', '?')
            await send(
                f"⚔️ *BATTLE IN PROGRESS!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"You are currently fighting *{enemy_name}*\n"
                f"❤️ Enemy HP: *{enemy_hp}/{enemy_max}*\n\n"
                f"_Finish your current battle first!_\n"
                f"Type `/explore` to unstuck if needed.",
                parse_mode='Markdown'
            )
            return

    if existing and not existing.get('in_combat'):
        clear_battle_state(user_id)

    level = get_level(player['xp'])
    location = player.get('location', 'asakusa')

    update_player(user_id,
                  explore_count=player.get('explore_count', 0) + 1,
                  explores_since_boss=min(20, player.get('explores_since_boss', 20) + 1))
    player = get_player(user_id)

    enemy_template = get_enemies_for_region(player)
    enemy = dict(enemy_template)

    enemy['hp']  = int(enemy['hp']  * (1 + level * 0.05))
    enemy['atk'] = int(enemy['atk'] * (1 + level * 0.03))

    if enemy.get('is_boss'):
        enemy['hp']  = int(enemy['hp']  * 3)
        enemy['atk'] = int(enemy['atk'] * 1.5)
        enemy['xp']  = int(enemy['xp']  * 3)
        enemy['yen'] = int(enemy['yen'] * 3)
    else:
        enemy['xp']  = int(enemy['xp']  * 1.5)
        enemy['yen'] = int(enemy['yen'] * 1.5)

    set_battle_state(user_id, enemy, in_combat=False)

    from config import TRAVEL_ZONES
    zone = next((z for z in TRAVEL_ZONES if z['id'] == location), TRAVEL_ZONES[0])
    boss_warning = "\n🔴 *⚠️ BOSS ENCOUNTER!*" if enemy.get('is_boss') else ""

    encounter_text = (
        f"🌙 *{player['name']} ventures into {zone['emoji']} {zone['name']}...*\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{'💀' if enemy.get('is_boss') else '⚠️'} *{enemy['name'].upper()} APPEARS!*{boss_warning}\n\n"
        f"{enemy['emoji']} {enemy['name']}\n"
        f"❤️ HP: {enemy['hp']}\n"
        f"⚔️ ATK: {enemy['atk']}\n"
        f"⚠️ Threat: {enemy['threat']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗡️ *{player['name']}*\n"
        f"❤️ HP: {player['hp']}/{player['max_hp']}\n"
        f"🌀 STA: {player['sta']}/{player['max_sta']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⭐ *Reward:* {enemy['xp']} XP | 💰 {enemy['yen']}¥\n\n"
        f"Press *Fight* to engage or *Find Different Enemy* to search again!"
    )

    await send(encounter_text, parse_mode='Markdown', reply_markup=build_encounter_keyboard())


# ── PRIZE PREVIEW ─────────────────────────────────────────────────────────
@owner_only_button
async def prize(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = get_battle_state(user_id)
    if not state:
        await query.answer("No enemy encountered yet! Use /explore first.", show_alert=True)
        return

    drops = json.loads(state['prize_drops']) if state['prize_drops'] else []
    drops_text = ', '.join(drops) if drops else 'None'

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Fight!", callback_data='fight')],
        [InlineKeyboardButton("🔍 Find Different Enemy", callback_data='goto_explore')]
    ])
    await safe_edit(
        query,
        f"🏆 *REWARD PREVIEW*\n\n"
        f"{state['enemy_emoji']} *{state['enemy_name']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ XP:    +{state['prize_xp']}\n"
        f"💰 Yen:   +{state['prize_yen']}¥\n"
        f"🎁 Drops: {drops_text}\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


# ── FIGHT (start combat) ──────────────────────────────────────────────────
@owner_only_button
async def fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)
    state = get_battle_state(user_id)

    if not state:
        await safe_edit(query, "⚔️ No enemy found. Use /explore to search.")
        return

    set_battle_state_in_combat(user_id)
    ally = get_active_ally(state)
    log_lines = get_battle_log(user_id)

    location = player.get('location', 'asakusa')
    pressure = calc_pressure(player, location)
    context.user_data['pressure'] = pressure
    context.user_data['combo'] = 0
    context.user_data['boss_enraged'] = False
    context.user_data[f'battle_ctx_{user_id}'] = {}

    battle_skills  = _safe_get_skills(user_id)
    battle_bonuses = _safe_get_bonuses(user_id, context)
    player = _apply_battle_start_skill_bonuses(user_id, player, battle_bonuses, context, log_lines)
    skill_lines = []
    if battle_bonuses:
        bonus_map = {
            'atk_pct':     lambda v: f"+{int(v*100)}% ATK",
            'tech_pct':    lambda v: f"+{int(v*100)}% Tech",
            'crit_bonus':  lambda v: f"+{int(v*100)}% Crit",
            'dodge_bonus': lambda v: f"+{int(v*100)}% Dodge",
            'dmg_reduce':  lambda v: f"-{int(v*100)}% DMG",
            'regen_hp':    lambda v: f"+{int(v)} HP/turn",
            'first_strike':lambda v: "First Strike ⚡",
            'null_status': lambda v: "Status Immune 🛡️",
        }
        parts = [fmt(v) for k, v in battle_bonuses.items() if (fmt := bonus_map.get(k))]
        if parts:
            skill_lines = [f"💠 *Skills:* {' | '.join(parts[:4])}"]

    boss_line = f"\n☠️ *BOSS BATTLE!* HP x3 | ATK x1.5" if state.get('is_boss') else ""
    pdisp = pressure_display(pressure, location)

    intro = f"⚔️ *BATTLE BEGINS!*{boss_line}\n\n{pdisp}"
    if skill_lines:
        intro += "\n" + "\n".join(skill_lines)

    await safe_edit(
        query,
        f"{intro}\n\n{combat_status(player, state, ally, log_lines)}",
        parse_mode='Markdown',
        reply_markup=build_combat_keyboard(has_ally=bool(ally))
    )


# ── ATTACK ────────────────────────────────────────────────────────────────
@owner_only_button
async def attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)
    state = get_battle_state(user_id)
    if not state or not state.get('in_combat'):
        await safe_edit(query, "No active battle. Use /explore.")
        return
    ally = get_active_ally(state)
    log = []
    owned_skills = _safe_get_skills(user_id)
    bonuses = _safe_get_bonuses(user_id, context)
    pressure = context.user_data.get('pressure') or calc_pressure(player, player.get('location', 'asakusa'))
    combo = context.user_data.get('combo', 0)
    chaos_mod = get_chaos_modifier() if pressure.get('is_chaos') else 1.0
    attack_ctx = context.user_data.get(f'battle_ctx_{user_id}', {})
    base_dmg = calc_dmg(player, owned_skills=owned_skills, user_id=user_id, context=context)
    base_dmg = int(base_dmg * pressure['atk_mult'] * chaos_mod)
    def_reduce = attack_ctx.get('enemy_def_reduce', 0)
    if def_reduce > 0:
        base_dmg += def_reduce
        log.append(f"Shattered! +{def_reduce} bonus dmg (DEF reduced)")
    if combo >= 3:
        base_dmg = int(base_dmg * 1.25)
        log.append(f"COMBO x{combo}! +25% damage!")
    crit_chance = 0.15 + bonuses.get('crit_bonus', 0)
    crit = random.random() < crit_chance
    if crit:
        base_dmg = int(base_dmg * 1.5)
    ctx_v = context.user_data.get(f'battle_ctx_{user_id}', {})
    if ctx_v.get('enemy_vulnerable'):
        base_dmg = int(base_dmg * 1.30)
        ctx_v['enemy_vulnerable'] = False
        context.user_data[f'battle_ctx_{user_id}'] = ctx_v
        log.append("Vulnerable! +30% damage!")
    if 'executioner' in bonuses and state['enemy_hp'] < state['enemy_max_hp'] * 0.20:
        base_dmg = int(base_dmg * (1 + bonuses['executioner']))
        log.append("Executioner activated!")
    if 'finish_pct' in bonuses and state['enemy_hp'] < state['enemy_max_hp'] * 0.20:
        base_dmg = int(base_dmg * (1 + bonuses['finish_pct']))
    if 'first_strike' in bonuses and combo == 0:
        base_dmg = int(base_dmg * (1 + bonuses['first_strike']))
        log.append(f"First Strike! +{int(bonuses['first_strike'] * 100)}% dmg!")
    if state.get('is_boss') and state['enemy_hp'] <= state['enemy_max_hp'] * 0.50:
        if not context.user_data.get('boss_enraged'):
            context.user_data['boss_enraged'] = True
            log.append(f"{state['enemy_name']} enrages! ATK +30%!")
    new_enemy_hp = max(0, state['enemy_hp'] - base_dmg)
    update_battle_enemy_hp(user_id, new_enemy_hp)
    combo += 1
    context.user_data['combo'] = combo
    if not bonuses.get('null_status'):
        _dot_dmg, skip_turn, _no_t, player, _heal_m = process_dot_effects(user_id, player, log)
    else:
        skip_turn = False
        from utils.database import clear_status_effects as _cls
        _cls(user_id)
    if skip_turn:
        state_s = get_battle_state(user_id)
        ally_s = get_active_ally(state_s)
        full_log_s = get_battle_log(user_id)
        append_battle_log(user_id, log)
        await safe_edit(
            query,
            combat_status(player, state_s, ally_s, full_log_s),
            parse_mode='Markdown',
            reply_markup=build_combat_keyboard(has_ally=bool(ally_s))
        )
        return
    log.append(f"{player['name']} attacks!")
    log.append(f"CRITICAL HIT! {base_dmg} damage!" if crit else f"{base_dmg} damage!")
    if new_enemy_hp <= 0:
        await handle_victory(query, user_id, player, state, log, context)
        return
    current_enemy_hp = new_enemy_hp
    if ally and state.get('ally_hp', 0) > 0:
        ally_dmg = ally['str_stat'] + random.randint(5, 15)
        ally_crit = random.random() < 0.12
        if ally_crit:
            ally_dmg = int(ally_dmg * 1.5)
        current_enemy_hp = max(0, current_enemy_hp - ally_dmg)
        update_battle_enemy_hp(user_id, current_enemy_hp)
        log.append(f"{ally['name']} strikes - {ally_dmg} damage!" + (" Crit!" if ally_crit else ""))
        if current_enemy_hp <= 0:
            state_fresh = get_battle_state(user_id)
            await handle_victory(query, user_id, player, state_fresh, log, context)
            return
    context.user_data['_counter_ready'] = bonuses.get('counter_chance', 0)
    ctx = context.user_data.get(f'battle_ctx_{user_id}', {})
    ctx['enemy_hp'] = current_enemy_hp
    ctx['enemy_max_hp'] = state.get('enemy_max_hp', 1)
    enemy_dot, ctx = process_enemy_dots(ctx, state, log)
    if enemy_dot > 0:
        new_dot_hp = max(0, current_enemy_hp - enemy_dot)
        update_battle_enemy_hp(user_id, new_dot_hp)
        if new_dot_hp <= 0:
            state_dot = get_battle_state(user_id)
            context.user_data[f'battle_ctx_{user_id}'] = ctx
            await handle_victory(query, user_id, player, state_dot, log, context)
            return
    context.user_data[f'battle_ctx_{user_id}'] = ctx
    state_fresh = get_battle_state(user_id)
    if is_enemy_frozen(ctx) or is_enemy_staggered(ctx):
        log.append(f"{state_fresh['enemy_name']} is immobilized - skips turn!")
        end_turn_hp = _apply_turn_end_player_sustain(user_id, player, player['hp'], bonuses, context, log)
        if end_turn_hp != player['hp']:
            update_player(user_id, hp=end_turn_hp)
        append_battle_log(user_id, log)
        player = get_player(user_id)
        state_upd = get_battle_state(user_id)
        ally_upd = get_active_ally(state_upd)
        full_log = get_battle_log(user_id)
        await safe_edit(
            query,
            combat_status(player, state_upd, ally_upd, full_log),
            parse_mode='Markdown',
            reply_markup=build_combat_keyboard(has_ally=bool(ally_upd))
        )
        return
    enemy_dmg = calc_enemy_dmg(player, state_fresh, owned_skills=owned_skills, user_id=user_id, context=context)
    enemy_dmg = int(enemy_dmg / pressure['def_mult'])
    enemy_dmg, ctx = apply_enemy_context_effects(state_fresh, ctx, enemy_dmg, log)
    context.user_data[f'battle_ctx_{user_id}'] = ctx
    if bonuses.get('def_pct'):
        enemy_dmg = int(enemy_dmg * (1 - bonuses['def_pct']))
    mirror_ctx = context.user_data.get(f'battle_ctx_{user_id}', {})
    reflect_pct = mirror_ctx.get('player_reflect', 0)
    if reflect_pct > 0 and enemy_dmg > 0:
        reflect_dmg = int(enemy_dmg * reflect_pct)
        reflected_enemy_hp = max(0, state_fresh.get('enemy_hp', 0) - reflect_dmg)
        set_battle_state(user_id, enemy_hp=reflected_enemy_hp)
        log.append(f"Ice Mirror! Reflected {reflect_dmg} damage back!")
    if context.user_data.get('boss_enraged'):
        enemy_dmg = int(enemy_dmg * 1.30)
    if pressure.get('is_chaos'):
        enemy_dmg = int(enemy_dmg * get_chaos_modifier())
    blind_ctx = context.user_data.get(f'battle_ctx_{user_id}', {})
    if blind_ctx.get('enemy_blind') and random.random() < 0.30:
        log.append("Blizzard Veil! Enemy attack missed!")
        enemy_dmg = 0
    dodge_chance = 0.10 + bonuses.get('dodge_bonus', 0)
    dodge = random.random() < dodge_chance
    player_took_direct_hit = False
    if dodge:
        log.append(f"{player['name']} dodges the attack!")
        new_player_hp = player['hp']
    else:
        if ally and state_fresh.get('ally_hp', 0) > 0 and random.random() < 0.4:
            new_ally_hp = max(0, state_fresh['ally_hp'] - enemy_dmg)
            update_ally_hp(user_id, new_ally_hp)
            log.append(f"{state_fresh['enemy_name']} attacks {ally['name']} - {enemy_dmg} damage!")
            if new_ally_hp <= 0:
                log.append(f"{ally['name']} has fainted!")
                clear_ally(user_id)
                ally = None
            new_player_hp = player['hp']
        else:
            new_player_hp = max(0, player['hp'] - enemy_dmg)
            player_took_direct_hit = enemy_dmg > 0
            log.append(f"{state_fresh['enemy_name']} strikes {player['name']} - {enemy_dmg} damage!")
            context.user_data['combo'] = 0
    if player_took_direct_hit and new_player_hp > 0:
        if _try_counter_strike(user_id, player, owned_skills, bonuses, context, log):
            update_player(user_id, hp=max(0, new_player_hp))
            await handle_victory(query, user_id, get_player(user_id), get_battle_state(user_id), log, context)
            return
    new_player_hp = _apply_turn_end_player_sustain(user_id, player, new_player_hp, bonuses, context, log)
    update_player(user_id, hp=max(0, new_player_hp))
    append_battle_log(user_id, log)
    if new_player_hp <= 0:
        await handle_defeat(query, user_id, player, log, context)
        return
    player = get_player(user_id)
    state_updated = get_battle_state(user_id)
    ally_updated = get_active_ally(state_updated)
    full_log = get_battle_log(user_id)
    await safe_edit(
        query,
        combat_status(player, state_updated, ally_updated, full_log),
        parse_mode='Markdown',
        reply_markup=build_combat_keyboard(has_ally=bool(ally_updated))
    )
@owner_only_button
async def technique(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    state   = get_battle_state(user_id)

    if not state or not state.get('in_combat'):
        await query.answer("No active battle!", show_alert=True)
        return

    arts = get_arts(user_id)
    from utils.database import get_inventory as _inv
    inv = _inv(user_id)
    scroll_arts = []
    for item in inv:
        name = item['item_name']
        if name.startswith('Scroll:'):
            art_name = name.replace('Scroll: ', '').strip()
            if art_name != player['style'] and art_name not in [a['art_name'] for a in arts]:
                scroll_arts.append(art_name)

    owned_skills = _safe_get_skills(user_id)
    bonuses      = _safe_get_bonuses(user_id, context)
    has_multi    = bonuses.get('multi_art', False)

    buttons = [[InlineKeyboardButton(
        f"{player['style_emoji']} {player['style']}",
        callback_data=f"art_{player['style']}"
    )]]
    for art in arts:
        buttons.append([InlineKeyboardButton(
            f"{art['art_emoji']} {art['art_name']} ✨",
            callback_data=f"art_{art['art_name']}"
        )])
    if player.get('hybrid_style'):
        hs = player['hybrid_style']
        he = player.get('hybrid_emoji', '⚡')
        buttons.append([InlineKeyboardButton(
            f"{he} {hs} ⚡Hybrid",
            callback_data=f"art_{hs}"
        )])
    if scroll_arts and (has_multi or not arts):
        for sart in scroll_arts[:2]:
            buttons.append([InlineKeyboardButton(
                f"📜 {sart} (Scroll)",
                callback_data=f"art_{sart}"
            )])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data='fight')])

    await safe_edit(
        query,
        "💨 *CHOOSE YOUR ART*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ── ART SELECTION ─────────────────────────────────────────────────────────
@owner_only_button
async def choose_art(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)

    art_name = query.data[4:]
    level = get_level(player['xp'])
    forms = get_unlocked_forms(art_name, level, player.get('rank'), player.get('faction'))

    if not forms:
        await query.answer("No forms unlocked for this art!", show_alert=True)
        return

    buttons = []
    for form in forms:
        buttons.append([InlineKeyboardButton(
            f"Form {form['form']} — {form['name']} | DMG:{form['dmg_min']}-{form['dmg_max']} STA:{form['sta_cost']}",
            callback_data=f"form_{art_name}_{form['form']}"
        )])
    buttons.append([InlineKeyboardButton("📖 Details", callback_data=f"forminfo_{art_name}")])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data='technique')])

    await safe_edit(
        query,
        f"💨 *{art_name.upper()}*\n\nChoose your form:",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ── FORM INFO ─────────────────────────────────────────────────────────────
async def form_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)

    art_name = query.data[9:]
    level = get_level(player['xp'])
    forms = get_unlocked_forms(art_name, level, player.get('rank'), player.get('faction'))

    lines = [f"📖 *{art_name.upper()} — ALL FORMS*\n"]
    for form in forms:
        lines.append(
            f"✨ *Form {form['form']} — {form['name']}*\n"
            f"   💥 DMG: {form['dmg_min']}-{form['dmg_max']} | 🌀 STA: {form['sta_cost']}\n"
        )

    buttons = [[InlineKeyboardButton("🔙 Back", callback_data=f"art_{art_name}")]]
    await safe_edit(
        query,
        '\n'.join(lines),
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ── USE FORM ──────────────────────────────────────────────────────────────
@owner_only_button
async def use_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)
    state = get_battle_state(user_id)
    if not state or not state.get('in_combat'):
        await safe_edit(query, "No active battle.")
        return
    parts = query.data.split('_', 2)
    art_name = parts[1]
    form_num = int(parts[2])
    all_forms = TECHNIQUES.get(art_name, [])
    form = next((f for f in all_forms if f['form'] == form_num), None)
    if not form:
        await query.answer("Form not found!", show_alert=True)
        return
    level = get_level(player['xp'])
    unlocked_forms = get_unlocked_forms(art_name, level, player.get('rank'), player.get('faction'))
    unlocked_nums = {f['form'] for f in unlocked_forms}
    if form_num not in unlocked_nums:
        req = form.get('unlock_rank', 'higher rank')
        await query.answer(f"Form {form_num} requires {req}!", show_alert=True)
        return
    owned_skills = _safe_get_skills(user_id)
    bonuses = _safe_get_bonuses(user_id, context)
    pressure = context.user_data.get('pressure') or calc_pressure(player, player.get('location', 'asakusa'))
    actual_sta_cost = max(0, form['sta_cost'] - bonuses.get('sta_reduce', 0))
    if player['sta'] < actual_sta_cost:
        await query.answer(f"Not enough STA! Need {actual_sta_cost}.", show_alert=True)
        return
    ally = get_active_ally(state)
    log = []
    log.append(f"{player['name']} uses {art_name} - Form {form['form']}!")
    log.append(f"{form['name']}")
    hits = form.get('hits', 1)
    total_dmg = 0
    for i in range(hits):
        hit_dmg = _calculate_form_hit_damage(
            player,
            form,
            state,
            owned_skills=owned_skills,
            user_id=user_id,
            context=context,
            bonuses=bonuses,
            log=log if i == 0 else None,
        )
        hit_dmg = int(hit_dmg * pressure['tech_mult'])
        if hits > 1:
            log.append(f"Hit {i + 1} -> {hit_dmg} damage!")
        total_dmg += hit_dmg
    log.append(f"{total_dmg} damage!" if hits == 1 else f"Total: {total_dmg} damage!")
    ctx = context.user_data.setdefault(f'battle_ctx_{user_id}', {})
    ctx['enemy_hp'] = state.get('enemy_hp', 0)
    ctx['enemy_max_hp'] = state.get('enemy_max_hp', state.get('enemy_hp', 1000))
    eff_bonus, eff_heal, ctx = apply_form_effect(user_id, player, form, art_name, log, ctx)
    context.user_data[f'battle_ctx_{user_id}'] = ctx
    total_dmg += eff_bonus
    if eff_heal > 0:
        new_hp = min(player['max_hp'], player['hp'] + eff_heal)
        update_player(user_id, hp=new_hp)
        player = get_player(user_id)
        log.append(f"+{eff_heal} HP healed")
    if not bonuses.get('null_status'):
        dot_dmg, skip_turn, no_tech, player, heal_mult = process_dot_effects(user_id, player, log)
    else:
        skip_turn, no_tech = False, False
    if no_tech:
        append_battle_log(user_id, log)
        state_fr = get_battle_state(user_id)
        ally_fr = get_active_ally(state_fr)
        full_fr = get_battle_log(user_id)
        await safe_edit(
            query,
            "Frozen! Cannot use techniques this turn!\n\n" + combat_status(player, state_fr, ally_fr, full_fr),
            parse_mode='Markdown',
            reply_markup=build_combat_keyboard(has_ally=bool(ally_fr))
        )
        return
    if skip_turn:
        append_battle_log(user_id, log)
        state_sk = get_battle_state(user_id)
        ally_sk = get_active_ally(state_sk)
        full_sk = get_battle_log(user_id)
        await safe_edit(
            query,
            combat_status(player, state_sk, ally_sk, full_sk),
            parse_mode='Markdown',
            reply_markup=build_combat_keyboard(has_ally=bool(ally_sk))
        )
        return
    new_sta = max(0, player['sta'] - actual_sta_cost)
    new_enemy_hp = max(0, state['enemy_hp'] - total_dmg)
    update_player(user_id, sta=new_sta)
    update_battle_enemy_hp(user_id, new_enemy_hp)
    if new_enemy_hp <= 0:
        await handle_victory(query, user_id, player, state, log, context)
        return
    current_hp = new_enemy_hp
    if ally and state.get('ally_hp', 0) > 0:
        ally_dmg = ally['str_stat'] + random.randint(5, 12)
        current_hp = max(0, current_hp - ally_dmg)
        update_battle_enemy_hp(user_id, current_hp)
        log.append(f"{ally['name']} follows up - {ally_dmg} damage!")
        if current_hp <= 0:
            await handle_victory(query, user_id, player, get_battle_state(user_id), log, context)
            return
    ctx = context.user_data.get(f'battle_ctx_{user_id}', {})
    ctx['enemy_hp'] = current_hp
    ctx['enemy_max_hp'] = state.get('enemy_max_hp', state.get('enemy_hp', 1000))
    enemy_dot, ctx = process_enemy_dots(ctx, get_battle_state(user_id), log)
    if enemy_dot > 0:
        current_hp = max(0, current_hp - enemy_dot)
        update_battle_enemy_hp(user_id, current_hp)
        if current_hp <= 0:
            context.user_data[f'battle_ctx_{user_id}'] = ctx
            await handle_victory(query, user_id, player, get_battle_state(user_id), log, context)
            return
    context.user_data[f'battle_ctx_{user_id}'] = ctx
    state_fresh = get_battle_state(user_id)
    if is_enemy_frozen(ctx) or is_enemy_staggered(ctx):
        log.append(f"{state_fresh['enemy_name']} is immobilized - skips turn!")
        end_turn_hp = _apply_turn_end_player_sustain(user_id, player, player['hp'], bonuses, context, log)
        if end_turn_hp != player['hp']:
            update_player(user_id, hp=end_turn_hp)
        append_battle_log(user_id, log)
        player = get_player(user_id)
        state_updated = get_battle_state(user_id)
        ally_updated = get_active_ally(state_updated)
        full_log = get_battle_log(user_id)
        await safe_edit(
            query,
            combat_status(player, state_updated, ally_updated, full_log),
            parse_mode='Markdown',
            reply_markup=build_combat_keyboard(has_ally=bool(ally_updated))
        )
        return
    enemy_dmg = calc_enemy_dmg(player, state_fresh, owned_skills=owned_skills, user_id=user_id, context=context)
    enemy_dmg = int(enemy_dmg / pressure['def_mult'])
    enemy_dmg, ctx = apply_enemy_context_effects(state_fresh, ctx, enemy_dmg, log)
    context.user_data[f'battle_ctx_{user_id}'] = ctx
    if bonuses.get('def_pct'):
        enemy_dmg = int(enemy_dmg * (1 - bonuses['def_pct']))
    mirror_ctx = context.user_data.get(f'battle_ctx_{user_id}', {})
    reflect_pct = mirror_ctx.get('player_reflect', 0)
    if reflect_pct > 0 and enemy_dmg > 0:
        reflect_dmg = int(enemy_dmg * reflect_pct)
        reflected_enemy_hp = max(0, state_fresh.get('enemy_hp', 0) - reflect_dmg)
        set_battle_state(user_id, enemy_hp=reflected_enemy_hp)
        log.append(f"Ice Mirror! Reflected {reflect_dmg} damage back!")
    if context.user_data.get('boss_enraged'):
        enemy_dmg = int(enemy_dmg * 1.30)
    if pressure.get('is_chaos'):
        enemy_dmg = int(enemy_dmg * get_chaos_modifier())
    blind_ctx = context.user_data.get(f'battle_ctx_{user_id}', {})
    if blind_ctx.get('enemy_blind') and random.random() < 0.30:
        log.append("Blizzard Veil! Enemy attack missed!")
        enemy_dmg = 0
    dodge_chance = 0.10 + bonuses.get('dodge_bonus', 0)
    dodge = random.random() < dodge_chance
    player_took_direct_hit = False
    if dodge:
        log.append(f"{player['name']} dodges!")
        new_player_hp = player['hp']
    else:
        if ally and state_fresh.get('ally_hp', 0) > 0 and random.random() < 0.35:
            new_ally_hp = max(0, state_fresh['ally_hp'] - enemy_dmg)
            update_ally_hp(user_id, new_ally_hp)
            log.append(f"{state_fresh['enemy_name']} targets {ally['name']} - {enemy_dmg} damage!")
            if new_ally_hp <= 0:
                log.append(f"{ally['name']} has fainted!")
                clear_ally(user_id)
                ally = None
            new_player_hp = player['hp']
        else:
            new_player_hp = max(0, player['hp'] - enemy_dmg)
            player_took_direct_hit = enemy_dmg > 0
            log.append(f"{state_fresh['enemy_name']} strikes back - {enemy_dmg} damage!")
            context.user_data['combo'] = 0
    if player_took_direct_hit and new_player_hp > 0:
        if _try_counter_strike(user_id, player, owned_skills, bonuses, context, log):
            update_player(user_id, hp=max(0, new_player_hp))
            await handle_victory(query, user_id, get_player(user_id), get_battle_state(user_id), log, context)
            return
    new_player_hp = _apply_turn_end_player_sustain(user_id, player, new_player_hp, bonuses, context, log)
    update_player(user_id, hp=max(0, new_player_hp))
    append_battle_log(user_id, log)
    if new_player_hp <= 0:
        await handle_defeat(query, user_id, player, log, context)
        return
    player = get_player(user_id)
    state_updated = get_battle_state(user_id)
    ally_updated = get_active_ally(state_updated)
    full_log = get_battle_log(user_id)
    await safe_edit(
        query,
        combat_status(player, state_updated, ally_updated, full_log),
        parse_mode='Markdown',
        reply_markup=build_combat_keyboard(has_ally=bool(ally_updated))
    )
@owner_only_button
async def items_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = get_battle_state(user_id)

    if not state or not state.get('in_combat'):
        await query.answer("No active battle!", show_alert=True)
        return

    items = get_inventory(user_id)
    usable = [i for i in items if i['item_type'] == 'item']

    if not usable:
        await query.answer("No usable items in inventory!", show_alert=True)
        return

    buttons = [[InlineKeyboardButton(
        f"{i['item_name']} x{i['quantity']}",
        callback_data=f"use_item_{i['item_name']}"
    )] for i in usable]
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data='fight')])

    await safe_edit(
        query,
        "🧪 *ITEMS — Choose to use:*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ── USE ITEM ──────────────────────────────────────────────────────────────
@owner_only_button
async def use_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)
    item_name = query.data[9:]
    state = get_battle_state(user_id)
    ally = get_active_ally(state) if state else None
    log = []

    if 'Recovery Gourd' in item_name:
        update_player(user_id, hp=player['max_hp'])
        log.append(f"🍶 *{item_name}* used! ❤️ HP fully restored to {player['max_hp']}!")
    elif 'Stamina Pill' in item_name:
        new_sta = min(player['max_sta'], player['sta'] + 50)
        update_player(user_id, sta=new_sta)
        log.append(f"💊 *{item_name}* used! 🌀 STA +50 → {new_sta}/{player['max_sta']}")
    elif 'Wisteria' in item_name:
        log.append(f"🌿 *{item_name}* used! ☘️ All status effects cleared!")
    else:
        log.append(f"Used {item_name}.")

    remove_item(user_id, item_name)
    player = get_player(user_id)
    state = get_battle_state(user_id)
    log_text = '\n'.join(log)
    await safe_edit(
        query,
        f"📜 *COMBAT LOG*\n\n{log_text}\n\n{combat_status(player, state, ally)}",
        parse_mode='Markdown',
        reply_markup=build_combat_keyboard(has_ally=bool(ally))
    )


# ── PARTY / ALLY SELECTION ────────────────────────────────────────────────
@owner_only_button
async def party_battle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    state = get_battle_state(user_id)
    if not state or not state.get('in_combat'):
        await query.answer("No active battle!", show_alert=True)
        return

    current_party = get_party(user_id)
    if not current_party:
        await query.answer("You have no party! Use /invite @username to form one.", show_alert=True)
        return

    from handlers.party import get_party_member_ids
    members = get_party_member_ids(current_party)
    ally_list = []
    for mid in members:
        if mid == user_id:
            continue
        m = get_player(mid)
        if m:
            lv = get_level(m['xp'])
            fe = '🗡️' if m['faction'] == 'slayer' else '👹'
            is_active = state.get('active_ally_id') == mid
            status = "✅ ACTIVE" if is_active else ("💀 FAINTED" if m['hp'] <= 0 else "")
            label = f"{fe} {m['name']} Lv.{lv} ❤️{m['hp']}/{m['max_hp']} {status}"
            ally_list.append((mid, label, m['hp']))

    if not ally_list:
        await query.answer("No party members available!", show_alert=True)
        return

    buttons = []
    for mid, label, hp in ally_list:
        if hp <= 0:
            buttons.append([InlineKeyboardButton(f"💀 {label}", callback_data='ally_fainted')])
        else:
            buttons.append([InlineKeyboardButton(label, callback_data=f"switch_ally_{mid}")])

    if state.get('active_ally_id'):
        buttons.append([InlineKeyboardButton("❌ Dismiss Ally", callback_data='dismiss_ally')])

    buttons.append([InlineKeyboardButton("🔙 Back to Battle", callback_data='fight')])

    current_ally = get_active_ally(state)
    header = (
        f"👥 *PARTY — ALLY SELECTION*\n\n"
        f"Active ally: *{current_ally['name']}* ❤️{state.get('ally_hp',0)}/{state.get('ally_max_hp',0)}\n\n"
        if current_ally and state.get('ally_hp') else
        "👥 *PARTY — ALLY SELECTION*\n\nNo active ally. Choose one to fight with you!\n\n"
    )
    header += "Choose an ally to switch in:"

    await safe_edit(
        query,
        header,
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ── SWITCH ALLY ───────────────────────────────────────────────────────────
@owner_only_button
async def switch_ally(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    ally_id = int(query.data.split('_')[-1])
    ally = get_player(ally_id)
    state = get_battle_state(user_id)
    player = get_player(user_id)

    if not ally:
        await query.answer("Ally not found!", show_alert=True)
        return
    if not state or not state.get('in_combat'):
        await query.answer("No active battle!", show_alert=True)
        return
    if ally['hp'] <= 0:
        await query.answer(f"{ally['name']} has fainted and can't battle!", show_alert=True)
        return

    set_active_ally(user_id, ally_id, ally['hp'], ally['max_hp'])
    state = get_battle_state(user_id)

    fe = '🗡️' if ally['faction'] == 'slayer' else '👹'
    log_text = (
        f"👥 *{ally['name']} enters the battle!*\n\n"
        f"{fe} {ally['name']} | Lv.{get_level(ally['xp'])}\n"
        f"❤️ HP: {ally['hp']}/{ally['max_hp']}\n"
        f"💨 Style: {ally['style_emoji']} {ally['style']}\n\n"
        f"_Your ally fights alongside you!_"
    )

    await safe_edit(
        query,
        f"📜 *ALLY SWITCHED!*\n\n{log_text}\n\n{combat_status(player, state, ally)}",
        parse_mode='Markdown',
        reply_markup=build_combat_keyboard(has_ally=True)
    )


# ── DISMISS ALLY ──────────────────────────────────────────────────────────
@owner_only_button
async def dismiss_ally_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    state = get_battle_state(user_id)
    if not state:
        await query.answer("No active battle!", show_alert=True)
        return

    clear_ally(user_id)
    player = get_player(user_id)
    state = get_battle_state(user_id)

    await safe_edit(
        query,
        f"👥 Ally dismissed.\n\n{combat_status(player, state, None)}",
        parse_mode='Markdown',
        reply_markup=build_combat_keyboard(has_ally=False)
    )


async def ally_fainted_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer("This ally has fainted and cannot battle!", show_alert=True)


# ── FLEE ──────────────────────────────────────────────────────────────────
@owner_only_button
async def flee(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)
    state = get_battle_state(user_id)

    if not state or not state.get('in_combat'):
        await safe_edit(query, "⚔️ You're not in battle.")
        return

    success = random.random() < 0.6
    if success:
        new_hp  = min(player['max_hp'],  player['hp']  + int(player['max_hp']  * 0.10))
        new_sta = min(player['max_sta'], player['sta'] + 20)
        update_player(user_id, hp=new_hp, sta=new_sta)
        clear_battle_state(user_id)
        await safe_edit(
            query,
            f"🏃 *{player['name']} flees!*\n\n✅ *Escaped successfully!*\n\n"
            f"❤️ HP: {new_hp}/{player['max_hp']}\n\nUse /explore to find a new enemy.",
            parse_mode='Markdown'
        )
    else:
        enemy_dmg = calc_enemy_dmg(player, state)
        new_hp = max(0, player['hp'] - enemy_dmg)
        update_player(user_id, hp=new_hp)
        if new_hp <= 0:
            await handle_defeat(query, user_id, player, [
                "🏃 Failed to flee!",
                f"👹 *{state['enemy_name']}* strikes — {enemy_dmg} damage!"
            ], context)
            return
        player = get_player(user_id)
        state  = get_battle_state(user_id)
        ally   = get_active_ally(state)
        await safe_edit(
            query,
            f"🏃 *Failed to flee!*\n👹 {state['enemy_name']} strikes — {enemy_dmg} damage!\n\n"
            f"{combat_status(player, state, ally)}",
            parse_mode='Markdown',
            reply_markup=build_combat_keyboard(has_ally=bool(ally))
        )


# ── VICTORY ───────────────────────────────────────────────────────────────
async def handle_victory(query, user_id, player, state, log, context=None):
    log.append(f"💀 *{state['enemy_name']}* — DEFEATED!")

    xp_gain  = state['prize_xp']
    yen_gain = state['prize_yen']
    drops    = json.loads(state['prize_drops']) if state['prize_drops'] else []

    if player.get('story_bonus') == 'xp_bonus':
        xp_gain = int(xp_gain * 1.1)

    # Apply skill bonuses for XP and Yen (safe loader — never crashes)
    _victory_bonuses = _safe_get_bonuses(user_id, context)
    if _victory_bonuses.get('xp_pct'):
        xp_gain = int(xp_gain * (1 + _victory_bonuses['xp_pct']))
    if _victory_bonuses.get('yen_pct'):
        yen_gain = int(yen_gain * (1 + _victory_bonuses['yen_pct']))

    kill_bonuses = _victory_bonuses
    if 'hp_on_kill' in kill_bonuses:
        heal_amt = int(player['max_hp'] * kill_bonuses['hp_on_kill'])
        player = dict(player)
        player['hp'] = min(player['max_hp'], player['hp'] + heal_amt)
        log.append(f"❤️ *Devour/Regen* — +{heal_amt} HP on kill!")

    from utils.helpers import get_level
    old_level    = get_level(player['xp'])
    new_xp       = player['xp'] + xp_gain
    new_level    = get_level(new_xp)
    levels_gained = new_level - old_level

    sp_gained = levels_gained
    if state.get('is_boss'):
        sp_gained += 1

    new_yen   = player['yen'] + yen_gain
    new_kills = player['demons_slain'] + 1
    old_rank  = player['rank']
    new_rank_data = get_rank(player['faction'], new_xp)
    ranked_up = new_rank_data['name'] != old_rank

    bonus_str    = player['str_stat'] + (levels_gained * 2)
    bonus_spd    = player['spd']      + (levels_gained * 1)
    bonus_def    = player['def_stat'] + (levels_gained * 1)
    bonus_maxhp  = player['max_hp']   + (levels_gained * 15)
    bonus_maxsta = player['max_sta']  + (levels_gained * 10)

    update_player(
        user_id,
        xp=new_xp, yen=new_yen, demons_slain=new_kills,
        rank=new_rank_data['name'], rank_kanji=new_rank_data['kanji'],
        str_stat=bonus_str, spd=bonus_spd, def_stat=bonus_def,
        max_hp=bonus_maxhp, max_sta=bonus_maxsta,
        hp=bonus_maxhp,
        sta=bonus_maxsta,
        skill_points=player.get('skill_points', 0) + sp_gained
    )

    from utils.database import add_item
    drop_lines = []
    drop_chance = 0.65 + _victory_bonuses.get('drop_pct', 0)
    for drop in drops:
        if random.random() < drop_chance:
            add_item(user_id, drop, 'material')
            drop_lines.append(f"🎁 {drop}")

    enemy_faction = state.get('faction_type', '')
    player_faction = player.get('faction', 'slayer')

    # Slayers fighting demons → Demon Blood drop
    if player_faction == 'slayer' and enemy_faction == 'demon' and random.random() < 0.80:
        add_item(user_id, 'Demon Blood', 'material')
        if 'Demon Blood' not in ' '.join(drop_lines):
            drop_lines.append("🩸 Demon Blood")

    # Demons fighting slayers → Slayer Badge drop  
    if player_faction == 'demon' and enemy_faction == 'slayer' and random.random() < 0.75:
        add_item(user_id, 'Slayer Badge', 'material')
        drop_lines.append("🏅 Slayer Badge")

    # Demons fighting neutral → Wolf Fang / misc drops
    if player_faction == 'demon' and enemy_faction == 'neutral' and random.random() < 0.65:
        add_item(user_id, 'Wolf Fang', 'material')
        drop_lines.append("🐺 Wolf Fang")

    # Slayers fighting slayer/neutral → Wolf Fang
    if player_faction == 'slayer' and enemy_faction in ('slayer', 'neutral') and random.random() < 0.60:
        add_item(user_id, 'Wolf Fang', 'material')
        drop_lines.append("🐺 Wolf Fang")

    if state.get('is_boss'):
        add_item(user_id, 'Boss Shard', 'material')
        drop_lines.append("🔸 Boss Shard")

    # ── DEVOUR SYSTEM ─────────────────────────────────────────────────────
    faction           = player.get('faction', 'slayer')
    enemy_faction_type = state.get('faction_type', '')
    devour_msg = ""
    if enemy_faction_type in DEVOUR_TRIGGERS.get(faction, []):
        devour_stacks = player.get('devour_stacks', 0)
        if devour_stacks < MAX_DEVOUR_STACKS:
            stat_boosts  = DEVOUR_STATS.get(faction, [])
            boost_parts  = []
            player_fresh = get_player(user_id)
            for stat, val in stat_boosts:
                cur = player_fresh.get(stat, 0)
                update_player(user_id, **{stat: cur + val})
                # If we boosted max_hp, also top up current HP
                if stat == 'max_hp':
                    update_player(user_id, hp=min(player_fresh.get('hp', cur) + val, cur + val))
                boost_parts.append(f"+{val} {stat.replace('_stat','').replace('_',' ').upper()}")
            update_player(user_id, devour_stacks=devour_stacks + 1)
            remaining  = MAX_DEVOUR_STACKS - devour_stacks - 1
            devour_emoji = "🍖" if faction == "demon" else "✨"
            devour_msg = f"\n{devour_emoji} *{'DEVOURED' if faction=='demon' else 'ABSORBED'}!* {' | '.join(boost_parts)}  _({remaining} left)_"
            log.append(f"{devour_emoji} {'Devoured' if faction=='demon' else 'Absorbed'} {state['enemy_name']}!")

    if hasattr(context, 'user_data'):
        context.user_data['boss_enraged'] = False
        context.user_data['combo'] = 0
        context.user_data.pop(f'battle_ctx_{user_id}', None)
        context.user_data.pop('_counter_ready', None)

    if state.get('is_boss'):
        update_player(user_id, explores_since_boss=0)

    # ── BUILD RESULT STRING (must come before mission block) ──────────────
    result = (
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"☀️ *VICTORY!*\n"
        f"⭐ +{xp_gain:,} XP\n"
        f"💰 +{yen_gain:,}¥\n"
        f"❤️ HP fully restored!\n"
        f"🌀 STA fully restored!\n"
    )
    if sp_gained:
        result += f"💠 +{sp_gained} Skill Point(s)!\n"
    if devour_msg:
        result += devour_msg + "\n"
    if drop_lines:
        result += '\n'.join(drop_lines) + '\n'
    if ranked_up:
        result += f"\n🎊 *RANK UP!* _{old_rank}_ → *{new_rank_data['name']}* {new_rank_data['kanji']}\n"
    if levels_gained > 0:
        result += (
            f"📈 *LEVEL UP!* Lv.{old_level} → *Lv.{new_level}*\n"
            f"   💪 STR +{levels_gained*2} | ⚡ SPD +{levels_gained} | 🛡️ DEF +{levels_gained}\n"
            f"   ❤️ Max HP +{levels_gained*15} | 🌀 Max STA +{levels_gained*10}\n"
        )
        if new_level % 10 == 0:
            add_item(user_id, "Full Recovery Gourd", "item")
            result += f"   🎁 *Milestone bonus:* Full Recovery Gourd!\n"
        elif new_level % 5 == 0:
            add_item(user_id, "Stamina Pill", "item")
            result += f"   💊 *Level bonus:* Stamina Pill!\n"
        elif new_level % 3 == 0:
            add_item(user_id, "Wisteria Antidote", "item")
            result += f"   🌿 *Level bonus:* Wisteria Antidote!\n"

    # ── MISSION PROGRESS TRACKING ─────────────────────────────────────────
    player_now = get_player(user_id)  # fresh copy after all updates
    if player_now.get('active_mission'):
        try:
            import json as _mj
            am = _mj.loads(player_now['active_mission']) if isinstance(player_now['active_mission'], str) else player_now['active_mission']
            if am and isinstance(am, dict):
                am['progress'] = am.get('progress', 0) + 1
                if am['progress'] >= am.get('required', 5):
                    m_xp  = am.get('xp', 0)
                    m_yen = am.get('yen', 0)
                    update_player(user_id,
                                  active_mission=None,
                                  xp=player_now['xp'] + m_xp,
                                  yen=player_now['yen'] + m_yen,
                                  missions_done=player_now.get('missions_done', 0) + 1)
                    result += (
                        f"\n\n🎉 *MISSION COMPLETE!*\n"
                        f"   {am.get('emoji','📜')} *{am.get('name','')}*\n"
                        f"   ⭐ +{m_xp:,} XP  💰 +{m_yen:,}¥"
                    )
                else:
                    update_player(user_id, active_mission=_mj.dumps(am))
                    remaining = am['required'] - am['progress']
                    result += f"\n\n📜 Mission: *{am['progress']}/{am['required']}* kills _(need {remaining} more)_"
        except Exception:
            pass

    # ── CLAN CONTRIBUTION ─────────────────────────────────────────────────
    if player_now.get('clan_id'):
        from utils.database import add_clan_xp, add_to_clan_treasury
        clan_xp_gain = max(10, xp_gain // 10)
        add_clan_xp(player_now['clan_id'], clan_xp_gain)
        drops_list = state.get('drops', [])
        if isinstance(drops_list, str):
            import json as _j
            try: drops_list = _j.loads(drops_list)
            except: drops_list = []
        if drops_list and random.random() < 0.30:
            add_to_clan_treasury(player_now['clan_id'], drops_list[0], 1)

    append_battle_log(user_id, log)
    clear_battle_state(user_id)
    clear_status_effects(user_id)

    result += f"\n━━━━━━━━━━━━━━━━━━━━━\n\n💡 Use /explore to fight again!"

    await safe_edit(query, result, parse_mode='Markdown')


# ── DEFEAT ────────────────────────────────────────────────────────────────
async def handle_defeat(query, user_id, player, log, context=None):
    log.append(f"💀 *{player['name']}* has fallen...")
    xp_loss    = max(0, player['xp'] - 200)
    new_deaths = player['deaths'] + 1
    new_hp     = int(player['max_hp'] * 0.5)
    update_player(user_id, hp=new_hp, sta=player['max_sta'], xp=xp_loss, deaths=new_deaths)
    append_battle_log(user_id, log)
    clear_battle_state(user_id)
    clear_status_effects(user_id)
    if hasattr(context, 'user_data'):
        context.user_data.pop(f'battle_ctx_{user_id}', None)
        context.user_data.pop('_counter_ready', None)
        context.user_data['combo'] = 0
        context.user_data['boss_enraged'] = False

    await safe_edit(
        query,
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💔 *DEFEATED*\n"
        f"⭐ XP Lost: -200\n"
        f"💀 Deaths: {new_deaths}\n"
        f"❤️ HP restored to 50%\n"
        f"🌀 STA fully restored\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"_You wake up at the safe house..._\n"
        f"💡 Use /explore to try again!",
        parse_mode='Markdown'
    )
