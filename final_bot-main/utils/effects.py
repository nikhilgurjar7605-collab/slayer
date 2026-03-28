"""
Full status effects engine — called from explore.py and challenge.py
All effects processed here with correct logic and enemy-side application.
"""
import random
from utils.database import (get_player, update_player, col,
                             apply_status_effect, get_status_effects,
                             tick_status_effects, clear_status_effects)
from config import STATUS_EFFECTS_DATA


def apply_form_effect(user_id, player, form, art_name, log, context_data=None):
    """
    Apply the correct status effect when a technique form is used.
    Status effects here are applied TO THE ENEMY (stored in battle context).
    Returns (bonus_dmg, heal_amount, updated_context_data)
    """
    if context_data is None:
        context_data = {}

    effect = form.get('effect', '')
    bonus  = 0
    heal   = 0

    # ── WATER BREATHING ───────────────────────────────────────────────────
    if effect == 'flow_start':
        if not context_data.get('flow_used_this_battle'):
            context_data['flow_used_this_battle'] = True
            context_data['flow_active']           = True
            context_data['player_atk_bonus']      = context_data.get('player_atk_bonus', 0) + 0.10
            context_data['player_def_bonus']      = context_data.get('player_def_bonus', 0) + 0.10
            log.append("💧 *FLOW STATE!* ATK+DEF +10% for this battle")

    elif effect == 'flow_boost':
        if context_data.get('flow_active'):
            bonus = int(player['max_hp'] * 0.05)
            log.append(f"💧 Flow boost — +{bonus} bonus damage!")

    elif effect == 'flow_defense':
        context_data['water_shield'] = 2
        log.append("🛡️ *Water Shield!* Next 2 hits reduced by 30%")

    elif effect == 'flow_sustain':
        heal = int(player['max_hp'] * 0.08)
        new_sta = min(player['max_sta'], player['sta'] + 20)
        update_player(user_id, sta=new_sta)
        log.append(f"🍃 *Blessed Rain* — +{heal} HP, +20 STA")
        context_data['used_sustain'] = True

    elif effect == 'flow_control':
        context_data['enemy_staggered'] = True
        context_data['enemy_skip_turns'] = context_data.get('enemy_skip_turns', 0) + 1
        log.append("🌀 *Whirlpool!* Enemy STAGGERED — loses next action!")

    elif effect == 'flow_finisher':
        if context_data.get('used_sustain') and context_data.get('used_defensive'):
            bonus = 40
            log.append("💥 *CONSTANT FLUX — FULL POWER!* +40 bonus dmg!")
        else:
            bonus = int(40 * 0.60)
            log.append(f"💧 Constant Flux — partial power +{bonus} dmg (use Sustain+Defensive first)")

    # ── FLAME BREATHING ───────────────────────────────────────────────────
    elif effect == 'burn_apply':
        chance = form.get('burn_chance', 90) / 100
        if random.random() < chance:
            context_data['enemy_burn']       = True
            context_data['enemy_burn_turns'] = 5
            context_data['enemy_burn_pct']   = 0.05
            log.append("🔥 *BURN APPLIED!* 5% HP damage per turn for 5 turns")

    elif effect == 'burn_chase':
        if context_data.get('enemy_burn'):
            bonus = 20
            log.append("🔥 Chase! Burning target — +20 bonus damage!")

    elif effect == 'burn_burst':
        if context_data.get('last_art_used') == art_name:
            bonus = 12
            log.append("🔥 Flame combo! +12 damage for consecutive Flame form")

    elif effect == 'burn_punish':
        context_data['enemy_atk_reduce'] = 0.20
        log.append("🔥 *Blooming Undulation!* Enemy next ATK -20%")

    elif effect == 'burn_execute':
        enemy_hp    = context_data.get('enemy_hp', 999)
        enemy_maxhp = context_data.get('enemy_max_hp', 1000)
        if context_data.get('enemy_burn') and enemy_hp < enemy_maxhp * 0.50:
            bonus = 35
            log.append("🔥 *RENGOKU!* Burning target below 50% — EXECUTE +35!")

    # ── BLOOD WHIP / BLEED ────────────────────────────────────────────────
    elif effect == 'bleed_apply':
        stacks = context_data.get('bleed_stacks', 0) + 1
        context_data['bleed_stacks']       = stacks
        context_data['enemy_bleed']        = True
        context_data['enemy_bleed_turns']  = 3
        context_data['enemy_bleed_pct']    = 0.06
        log.append(f"🩸 *BLEED APPLIED!* Stack {stacks} — 6% HP/turn x3")
        if random.random() < form.get('vulnerable_chance', 0) / 100:
            context_data['enemy_vulnerable'] = True
            log.append("😰 *VULNERABLE!* Enemy takes +30% dmg next hit")

    elif effect == 'bleed_extend':
        stacks = context_data.get('bleed_stacks', 0) + 1
        context_data['bleed_stacks']      = stacks
        context_data['enemy_bleed']       = True
        context_data['enemy_bleed_turns'] = 3
        context_data['enemy_dodge_reduce']= 0.50
        log.append(f"🩸 *Crimson Cage!* Bleed stack {stacks}, dodge halved")

    elif effect == 'bleed_payoff':
        stacks = context_data.get('bleed_stacks', 0)
        if stacks > 0:
            bonus = stacks * 12
            heal  = stacks * 8
            new_sta = min(player['max_sta'], player['sta'] + stacks * 5)
            update_player(user_id, sta=new_sta)
            log.append(f"🩸 *Scarlet Torrent!* {stacks} stacks → +{bonus} dmg, +{heal} heal")

    # ── FREEZE / ICE ──────────────────────────────────────────────────────
    elif effect == 'freeze_apply':
        context_data['enemy_frozen']       = True
        context_data['enemy_frozen_turns'] = 2
        log.append("❄️ *FREEZE!* Enemy cannot attack for 2 turns")

    elif effect == 'ice_shatter':
        # Crystal Lotus Bloom — reduce enemy DEF
        context_data['enemy_def_reduce']       = context_data.get('enemy_def_reduce', 0) + 15
        context_data['enemy_def_reduce_turns'] = 3
        log.append("🧊 *SHATTERED!* Enemy DEF -15 for 3 turns")

    elif effect == 'ice_blind':
        # Blizzard Veil — 30% chance enemy misses next attack
        if random.random() < 0.30:
            context_data['enemy_blind']       = True
            context_data['enemy_blind_turns'] = 1
            log.append("🙈 *BLINDED!* Enemy has 30% chance to miss next attack")
        else:
            log.append("💨 Blizzard Veil — blind missed this time")

    elif effect == 'ice_bleed':
        # Frozen Spine — flat 12 dmg per turn for 2 turns
        context_data['enemy_ice_bleed']       = True
        context_data['enemy_ice_bleed_turns'] = 2
        context_data['enemy_ice_bleed_dmg']   = 12
        log.append("🩸 *ICE BLEED!* 12 damage per turn for 2 turns")

    elif effect == 'frostburn':
        # Arctic Soul Devourer — drain 10 STA per turn
        context_data['enemy_frostburn']       = True
        context_data['enemy_frostburn_turns'] = 3
        context_data['enemy_frostburn_drain'] = 10
        log.append("🌡️ *FROSTBURN!* Enemy loses 10 STA per turn for 3 turns")

    elif effect == 'ice_counter':
        # Mirror of the Ice Queen — reflect 20% damage for 1 turn
        context_data['player_reflect']       = 0.20
        context_data['player_reflect_turns'] = 1
        log.append("🪞 *ICE MIRROR!* Reflects 20% of incoming damage for 1 turn")

    elif effect == 'deep_freeze':
        # Permafrost Calamity — skip enemy's next 2 turns (100%)
        context_data['enemy_frozen']       = True
        context_data['enemy_frozen_turns'] = 2
        context_data['enemy_skip_turns']   = context_data.get('enemy_skip_turns', 0) + 2
        context_data['enemy_staggered']    = True
        log.append("❄️ *PERMAFROST!* Enemy is DEEP FROZEN — skips next 2 turns!")

    # ── POISON ────────────────────────────────────────────────────────────
    elif effect in ('poison_apply', 'poison_aoe'):
        turns = 5 if effect == 'poison_apply' else 4
        context_data['enemy_poison']       = True
        context_data['enemy_poison_turns'] = turns
        context_data['enemy_poison_pct']   = 0.03
        log.append(f"☠️ *POISON!* 3% HP/turn for {turns} turns")

    # ── REGEN (player-side) ───────────────────────────────────────────────
    elif effect == 'regen':
        heal = int(player['max_hp'] * 0.12)
        log.append(f"💚 *Regeneration* — +{heal} HP")

    elif effect == 'regen_apply':
        heal = int(player['max_hp'] * 0.10)
        log.append(f"💚 *Regen* — +{heal} HP")

    # Track combos
    form_type = form.get('type', '')
    context_data['last_form_type'] = form_type
    context_data['last_art_used']  = art_name
    if form_type == 'defensive':
        context_data['used_defensive'] = True

    return bonus, heal, context_data


def process_dot_effects(user_id, player, log):
    """
    Process all active DoT/status effects on the PLAYER each turn.
    Returns (total_hp_damage, skip_turn, no_technique, updated_player, heal_multiplier)
    """
    effs      = get_status_effects(user_id)
    total_dmg = 0
    skip_turn = False
    no_tech   = False
    sta_loss  = 0
    heal_mult = 1.0

    for eff in effs:
        edata = STATUS_EFFECTS_DATA.get(eff['effect'], {})
        name  = eff['effect']
        left  = eff.get('turns_left', 1)

        # DoT damage
        if 'dmg_pct' in edata:
            dot = max(1, int(player['max_hp'] * edata['dmg_pct']))
            total_dmg += dot
            log.append(f"{name} deals *{dot}* dmg! _{left}t left_")

        # Stun/skip
        if edata.get('skip_turn'):
            skip_turn = True
            log.append(f"🔒 *{name}* — STUNNED! Turn skipped")

        # Freeze — no techniques
        if edata.get('no_technique'):
            no_tech = True
            log.append(f"❄️ *{name}* — FROZEN! Cannot use techniques")

        # Exhaust — STA drain
        if edata.get('no_sta_regen') and 'sta_dmg_pct' in edata:
            sta_loss += max(1, int(player['max_sta'] * edata['sta_dmg_pct']))
            log.append(f"😵 *{name}* — STA drained!")

        # Curse — healing penalty
        if edata.get('heal_reduce'):
            heal_mult = 1.0 - edata['heal_reduce']

        # Burn — suppresses regen
        if edata.get('stop_regen'):
            log.append(f"🔥 Burn active — regeneration suppressed")

        # Confusion — chance to self-hit
        if edata.get('self_atk_chance') and random.random() < edata['self_atk_chance']:
            self_dmg = max(1, int(player['max_hp'] * 0.05))
            total_dmg += self_dmg
            log.append(f"🌀 *{name}* — Confused! Self-hit for *{self_dmg}*!")

    if total_dmg > 0:
        new_hp = max(1, player['hp'] - total_dmg)
        update_player(user_id, hp=new_hp)
        player = get_player(user_id)

    if sta_loss > 0:
        new_sta = max(0, player['sta'] - sta_loss)
        update_player(user_id, sta=new_sta)
        player = get_player(user_id)

    tick_status_effects(user_id)
    return total_dmg, skip_turn, no_tech, player, heal_mult


def apply_enemy_context_effects(state, context_data, enemy_dmg, log):
    """
    Apply context_data enemy debuffs to the enemy attack.
    Call this before enemy attacks player.
    Returns modified enemy_dmg and updated context_data.
    """
    # ATK reduce (from burn_punish etc)
    if context_data.get('enemy_atk_reduce'):
        reduction = context_data.pop('enemy_atk_reduce')
        enemy_dmg = int(enemy_dmg * (1 - reduction))
        log.append(f"🔥 Enemy ATK reduced by {int(reduction*100)}%!")

    # Vulnerable on player — incoming dmg increase
    # (vulnerable is enemy-side, but tracked in context; already handled in damage calc)

    return enemy_dmg, context_data


def process_enemy_dots(context_data, state, log):
    """
    Process DoT effects on the ENEMY from context_data each turn.
    Returns (enemy_hp_damage, updated_context_data, updated_state_enemy_hp).
    """
    total = 0
    enemy_hp = state.get('enemy_hp', 0)
    enemy_max = state.get('enemy_max_hp', 1)

    # Burn
    if context_data.get('enemy_burn') and context_data.get('enemy_burn_turns', 0) > 0:
        dot = max(1, int(enemy_max * context_data.get('enemy_burn_pct', 0.05)))
        total += dot
        context_data['enemy_burn_turns'] -= 1
        log.append(f"🔥 *Enemy BURNS!* -{dot} HP ({context_data['enemy_burn_turns']}t left)")
        if context_data['enemy_burn_turns'] <= 0:
            context_data['enemy_burn'] = False

    # Bleed
    if context_data.get('enemy_bleed') and context_data.get('enemy_bleed_turns', 0) > 0:
        stacks = context_data.get('bleed_stacks', 1)
        dot = max(1, int(enemy_max * context_data.get('enemy_bleed_pct', 0.06)) * stacks)
        total += dot
        context_data['enemy_bleed_turns'] -= 1
        log.append(f"🩸 *Enemy BLEEDS!* -{dot} HP ({context_data['enemy_bleed_turns']}t left)")
        if context_data['enemy_bleed_turns'] <= 0:
            context_data['enemy_bleed'] = False

    # Poison
    if context_data.get('enemy_poison') and context_data.get('enemy_poison_turns', 0) > 0:
        dot = max(1, int(enemy_max * context_data.get('enemy_poison_pct', 0.03)))
        total += dot
        context_data['enemy_poison_turns'] -= 1
        log.append(f"☠️ *Enemy POISONED!* -{dot} HP ({context_data['enemy_poison_turns']}t left)")
        if context_data['enemy_poison_turns'] <= 0:
            context_data['enemy_poison'] = False

    # Ice Bleed — flat damage per turn
    if context_data.get('enemy_ice_bleed') and context_data.get('enemy_ice_bleed_turns', 0) > 0:
        dot = context_data.get('enemy_ice_bleed_dmg', 12)
        total += dot
        context_data['enemy_ice_bleed_turns'] -= 1
        log.append(f"🩸 *Ice Bleed!* -{dot} HP ({context_data['enemy_ice_bleed_turns']}t left)")
        if context_data['enemy_ice_bleed_turns'] <= 0:
            context_data['enemy_ice_bleed'] = False

    # Frostburn — STA drain (tracked in context, applied to enemy side)
    if context_data.get('enemy_frostburn') and context_data.get('enemy_frostburn_turns', 0) > 0:
        context_data['enemy_frostburn_turns'] -= 1
        drain = context_data.get('enemy_frostburn_drain', 10)
        context_data['enemy_sta_drained'] = context_data.get('enemy_sta_drained', 0) + drain
        log.append(f"🌡️ *Frostburn!* Enemy STA -{drain} ({context_data['enemy_frostburn_turns']}t left)")
        if context_data['enemy_frostburn_turns'] <= 0:
            context_data['enemy_frostburn'] = False

    # Blind — handled in explore attack logic; just tick down here
    if context_data.get('enemy_blind') and context_data.get('enemy_blind_turns', 0) > 0:
        context_data['enemy_blind_turns'] -= 1
        if context_data['enemy_blind_turns'] <= 0:
            context_data['enemy_blind'] = False

    # DEF reduce — tick down
    if context_data.get('enemy_def_reduce_turns', 0) > 0:
        context_data['enemy_def_reduce_turns'] -= 1
        if context_data['enemy_def_reduce_turns'] <= 0:
            context_data.pop('enemy_def_reduce', None)

    # Reflect — tick down
    if context_data.get('player_reflect_turns', 0) > 0:
        context_data['player_reflect_turns'] -= 1
        if context_data['player_reflect_turns'] <= 0:
            context_data.pop('player_reflect', None)

    return total, context_data


def is_enemy_frozen(context_data):
    """Returns True if enemy is frozen (cannot attack this turn)."""
    if context_data.get('enemy_frozen') and context_data.get('enemy_frozen_turns', 0) > 0:
        context_data['enemy_frozen_turns'] -= 1
        if context_data['enemy_frozen_turns'] <= 0:
            context_data['enemy_frozen'] = False
        return True
    return False


def is_enemy_staggered(context_data):
    """Returns True if enemy loses their turn this round."""
    if context_data.get('enemy_skip_turns', 0) > 0:
        context_data['enemy_skip_turns'] -= 1
        return True
    if context_data.get('enemy_staggered'):
        context_data['enemy_staggered'] = False
        return True
    return False
