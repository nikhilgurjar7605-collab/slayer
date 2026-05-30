import logging
log = logging.getLogger(__name__)
"""
Clan Raid System — Full explore-style combat.
Each player gets a real battle screen (Attack/Technique/Items buttons)
when it is their turn. Damage reduces shared boss HP.

Flow:
  1. Leader: /clanraid start <boss>   — opens the raid
  2. Members: /clanraid join          — pay entry fee, enter roster
  3. Members: /clanraid attack        — get a personal DM battle screen
  4. Battle happens in DMs; collective boss HP tracked in DB
  5. When boss dies (or leader runs /clanraid end):
     • Rewards distributed to each player DM proportional to damage
     • Full MVP leaderboard posted to the clan group chat (group_chat_id)
"""
import random, json
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import (get_player, update_player, add_item, col,
                             get_battle_state, set_battle_state,
                             clear_battle_state, update_battle_enemy_hp,
                             get_inventory, remove_item)
from utils.guards import dm_only
from utils.helpers import hp_bar

RAID_COOLDOWN_DAYS = 7
RAID_JOIN_FEE      = 500
RAID_MAX_MEMBERS   = 15

# ── TIER DEFINITIONS ─────────────────────────────────────────────────────────
# Each boss has a "tier": "low", "medium", or "high"
# Tier controls base yen pool, item pool, and bonus multipliers.

TIER_CONFIG = {
    "low": {
        "label":        "🟢 Low Tier",
        "base_yen":     3_000,          # per-participant base before share calc
        "clan_xp":      500,            # XP added to clan after win
        "item_pool":    ["Boss Shard", "Whetstone", "Demon Bone", "Iron Fragment"],
        "item_chance":  0.50,           # chance each participant gets an item
        "mvp_bonus":    1_500,          # extra yen for #1 damage dealer
        "kill_bonus":   1.3,            # multiplier if boss is fully killed
    },
    "medium": {
        "label":        "🟡 Medium Tier",
        "base_yen":     7_000,
        "clan_xp":      1_500,
        "item_pool":    ["Demon Crystal", "Nichirin Fragment", "Moon Shard", "Spirit Core"],
        "item_chance":  0.70,
        "mvp_bonus":    4_000,
        "kill_bonus":   1.5,
    },
    "high": {
        "label":        "🔴 High Tier",
        "base_yen":     18_000,
        "clan_xp":      4_000,
        "item_pool":    ["Upper Moon Core", "Demon King Fragment", "Crimson Nichirin", "Yoriichi Scroll"],
        "item_chance":  1.00,           # everyone gets an item
        "mvp_bonus":    12_000,
        "kill_bonus":   2.0,
    },
}

RAID_BOSSES = {
    # ── LOW TIER ──────────────────────────────────────────────────────────────
    "Rui": {
        "hp": 35_000, "atk": 130, "emoji": "🕷️", "tier": "low",
        "enrage_pct": 0.50,
        "techniques": ["Steel Thread Slash", "Spider Web Cage", "Blood Thread Transformation"],
    },
    "Gyokko": {
        "hp": 40_000, "atk": 140, "emoji": "🐟", "tier": "low",
        "enrage_pct": 0.45,
        "techniques": ["10,000 Locust Fish", "Water Prison", "Killer Fish Scales"],
    },
    "Gyutaro": {
        "hp": 45_000, "atk": 155, "emoji": "☠️", "tier": "low",
        "enrage_pct": 0.45,
        "techniques": ["Flying Blood Sickles", "Rotating Circular Slashes", "Warding Scythe"],
    },
    # ── MEDIUM TIER ───────────────────────────────────────────────────────────
    "Akaza": {
        "hp": 50_000, "atk": 170, "emoji": "🥊", "tier": "medium",
        "enrage_pct": 0.40,
        "techniques": ["Destructive Death", "Annihilation Type", "Compass Needle"],
    },
    "Hantengu": {
        "hp": 55_000, "atk": 180, "emoji": "👻", "tier": "medium",
        "enrage_pct": 0.35,
        "techniques": ["Fear Manifestation", "Clone Split", "Thunder Shriek"],
    },
    "Doma": {
        "hp": 65_000, "atk": 200, "emoji": "🌸", "tier": "medium",
        "enrage_pct": 0.40,
        "techniques": ["Icy Breath", "Frozen Lotus", "Crystalline Shower"],
    },
    # ── HIGH TIER ─────────────────────────────────────────────────────────────
    "Kokushibo": {
        "hp": 80_000, "atk": 240, "emoji": "🌙", "tier": "high",
        "enrage_pct": 0.35,
        "techniques": ["Moon Breathing", "Crescent Moon Slashes", "Upper Moon Fury"],
    },
    "Muzan": {
        "hp": 100_000, "atk": 280, "emoji": "😈", "tier": "high",
        "enrage_pct": 0.30,
        "techniques": ["Blood Explosion", "Cellular Manipulation", "Infinite Blood"],
    },
}

# Group bosses by tier for the /clanraid bosses display
TIER_ORDER = ["low", "medium", "high"]


# ── HELPERS ───────────────────────────────────────────────────────────────────

def _get_active_raid(clan_id):
    return col("clan_raids").find_one({"clan_id": int(clan_id), "status": "active"})


def _raid_combat_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚔️ Attack",    callback_data="raid_attack"),
            InlineKeyboardButton("💨 Technique", callback_data="raid_technique"),
        ],
        [
            InlineKeyboardButton("🧪 Items",     callback_data="raid_items"),
            InlineKeyboardButton("🏃 Retreat",   callback_data="raid_retreat"),
        ],
    ])


def _tier_label(boss_name: str) -> str:
    tier = RAID_BOSSES.get(boss_name, {}).get("tier", "low")
    return TIER_CONFIG[tier]["label"]


def _raid_status_text(player, raid, battle_state, log_lines=None):
    """Build the personal DM battle status display."""
    boss_hp    = raid["boss_hp"]
    boss_max   = raid["boss_max_hp"]
    boss_name  = raid["boss_name"]
    boss_emoji = raid["boss_emoji"]
    boss_pct   = boss_hp / boss_max if boss_max else 0
    b_bar      = hp_bar(boss_hp, boss_max, 12)
    p_bar      = hp_bar(player["hp"], player["max_hp"])
    enrage_pct = RAID_BOSSES.get(boss_name, {}).get("enrage_pct", 0.4)
    enraged    = "\n😡 *ENRAGED!* ATK +40%!" if boss_pct <= enrage_pct else ""
    tier_label = _tier_label(boss_name)

    log_section = ""
    if log_lines:
        log_section = "\n".join(log_lines[-3:]) + "\n\n"

    parts_count = len(raid.get("participants", {}))
    dmg_done    = raid.get("participants", {}).get(str(player["user_id"]), {}).get("damage", 0)

    return (
        f"{log_section}"
        f"╔══════════════════════════╗\n"
        f"   ⚔️ CLAN RAID BATTLE\n"
        f"╚══════════════════════════╝\n\n"
        f"{tier_label}\n"
        f"{boss_emoji} *{boss_name}*{enraged}\n"
        f"❤️ {boss_hp:,} / {boss_max:,}\n"
        f"{b_bar}\n"
        f"👥 {parts_count} fighters | 💥 You dealt: {dmg_done:,}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🗡️ *{player['name']}*\n"
        f"❤️ {player['hp']}/{player['max_hp']} {p_bar}\n"
        f"🌀 {player['sta']}/{player['max_sta']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )


async def _post_raid_results_to_group(context, clan, raid, results: list, boss_dead: bool):
    """
    Post the full MVP leaderboard + reward summary to the clan group chat.
    `results` is a list of dicts: {name, damage, share, yen_reward, item_name}
    sorted highest damage first.
    """
    group_chat_id = clan.get("group_chat_id")
    if not group_chat_id:
        return  # No group configured — silent skip

    boss_name  = raid["boss_name"]
    boss_emoji = raid["boss_emoji"]
    tier_label = _tier_label(boss_name)
    total_dmg  = sum(r["damage"] for r in results)

    rank_icons = ["🥇", "🥈", "🥉"]
    lines = [
        f"⚔️ *CLAN RAID RESULTS*",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"{tier_label}",
        f"{boss_emoji} *{boss_name}* — {'☠️ DEFEATED!' if boss_dead else '🏃 Escaped'}",
        f"📊 Total damage dealt: *{total_dmg:,}*",
        f"",
        f"🏆 *MVP LEADERBOARD*",
        f"━━━━━━━━━━━━━━━━━━━━━",
    ]

    for i, r in enumerate(results):
        icon     = rank_icons[i] if i < 3 else f"`{i+1}.`"
        pct      = r["share"] * 100
        item_txt = f" + *{r['item_name']}*" if r.get("item_name") else ""
        lines.append(
            f"{icon} *{r['name']}*\n"
            f"   💥 {r['damage']:,} dmg ({pct:.1f}%) → 💰 +{r['yen_reward']:,}¥{item_txt}"
        )

    lines += [
        f"",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"🎉 GG to all raiders! Rewards sent to DMs.",
    ]

    try:
        await context.bot.send_message(
            chat_id=group_chat_id,
            text="\n".join(lines),
            parse_mode="Markdown"
        )
    except Exception as e:
        log.error("[RAID GROUP POST] %s", e)


# ── TURN ENGINE ───────────────────────────────────────────────────────────────

async def _start_raid_turn(context, user_id: int, raid: dict, intro_text: str = ""):
    """Give a player their personal DM battle screen for their raid turn."""
    player = get_player(user_id)
    if not player:
        return

    boss_name = raid["boss_name"]
    boss_data = RAID_BOSSES.get(boss_name, {})

    enemy = {
        "name":    boss_name,
        "emoji":   boss_data["emoji"],
        "hp":      raid["boss_hp"],
        "atk":     boss_data["atk"],
        "xp":      0,
        "yen":     0,
        "threat":  "🔴 EXTREME",
        "drops":   [],
        "is_boss": True,
        "is_raid": True,
        "clan_id": raid["clan_id"],
        "raid_id": str(raid["_id"]),
    }
    set_battle_state(user_id, enemy, in_combat=True)
    col("battle_state").update_one(
        {"user_id": user_id},
        {"$set": {"is_raid": True, "raid_clan_id": int(raid["clan_id"])}}
    )

    fresh = get_player(user_id)

    try:
        from handlers.explore import _safe_get_bonuses, _safe_get_skills, calc_pressure, pressure_display
        pressure = calc_pressure(fresh, fresh.get("location", "asakusa"))
        pdisp    = pressure_display(pressure, fresh.get("location", "asakusa"))
        context.user_data["pressure"] = pressure
        context.user_data["combo"]    = 0
    except Exception:
        pdisp = ""

    state = get_battle_state(user_id)
    text  = (
        f"⚔️ *IT'S YOUR TURN!*\n\n"
        f"{pdisp}\n\n"
        f"{_raid_status_text(fresh, raid, state)}"
    )
    if intro_text:
        text = intro_text + "\n\n" + text

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode="Markdown",
            reply_markup=_raid_combat_keyboard()
        )
    except Exception as e:
        # Can't reach user — release turn lock so others can proceed
        col("clan_raids").update_one(
            {"clan_id": int(raid["clan_id"]), "status": "active"},
            {"$unset": {"current_attacker": "", "attack_lock_at": ""}}
        )


async def _end_raid_turn(context, user_id: int, raid_clan_id, dmg_dealt: int,
                          fled: bool = False, dead: bool = False):
    """Called when a player finishes their raid turn (combat, retreat, death)."""
    clan_id_int = int(raid_clan_id)
    raid = _get_active_raid(clan_id_int)
    if not raid:
        return

    uid_str = str(user_id)

    # Sync boss HP from personal battle state
    battle = get_battle_state(user_id)
    if battle and battle.get("is_raid"):
        real_boss_hp = battle["enemy_hp"]
        col("clan_raids").update_one(
            {"clan_id": clan_id_int, "status": "active", "boss_hp": {"$gt": real_boss_hp}},
            {"$set": {"boss_hp": real_boss_hp}}
        )

    clear_battle_state(user_id)

    col("clan_raids").update_one(
        {"clan_id": clan_id_int, "status": "active"},
        {
            "$inc": {f"participants.{uid_str}.damage": dmg_dealt},
            "$set": {f"participants.{uid_str}.last_turn": datetime.utcnow().isoformat()},
            "$unset": {"current_attacker": "", "attack_lock_at": ""}
        }
    )

    # Reload raid after updating damage
    raid = _get_active_raid(clan_id_int)
    if not raid:
        return

    # Auto-end if boss is dead
    if raid["boss_hp"] <= 0:
        clan = col("clans").find_one({"id": clan_id_int})
        await _finalize_raid(context, raid, clan, boss_dead=True)
        return

    # Otherwise notify all other participants that the turn is free
    player = get_player(user_id)
    name   = player["name"] if player else f"Player {user_id}"
    status = "💀 was defeated" if dead else ("🏃 retreated" if fled else f"dealt *{dmg_dealt:,}* damage")
    h_bar  = hp_bar(raid["boss_hp"], raid["boss_max_hp"], 10)

    notify = (
        f"⚔️ *{name}* {status}!\n"
        f"{raid['boss_emoji']} *{raid['boss_name']}*\n"
        f"{h_bar} {raid['boss_hp']:,} HP left\n\n"
        f"_Use /clanraid attack when you're ready!_"
    )
    for pid in raid.get("participants", {}):
        if int(pid) == user_id:
            continue
        try:
            await context.bot.send_message(chat_id=int(pid), text=notify, parse_mode="Markdown")
        except Exception as e:
            log.error("[EXCEPTION] %s", e)


async def _finalize_raid(context, raid: dict, clan: dict, boss_dead: bool):
    """
    Distribute rewards, DM every participant their personal result,
    and post the full MVP board to the clan group.
    Called automatically when boss dies, or manually via /clanraid end.
    Idempotent — marks raid finished first to prevent double-run.
    """
    # Mark finished immediately so concurrent calls don't double-reward
    result = col("clan_raids").update_one(
        {"_id": raid["_id"], "status": "active"},
        {"$set": {"status": "finished", "ended_at": datetime.utcnow()}}
    )
    if result.modified_count == 0:
        return  # Another call already finalized this raid

    boss_name  = raid["boss_name"]
    boss_data  = RAID_BOSSES.get(boss_name, {})
    tier       = boss_data.get("tier", "low")
    tcfg       = TIER_CONFIG[tier]

    parts       = raid.get("participants", {})
    total_dmg   = sum(p.get("damage", 0) for p in parts.values())
    sorted_parts = sorted(parts.items(), key=lambda x: x[1].get("damage", 0), reverse=True)
    n_players   = max(len(parts), 1)

    results = []
    for rank, (pid, pdata) in enumerate(sorted_parts):
        share      = pdata["damage"] / total_dmg if total_dmg else 0
        yen_reward = int(tcfg["base_yen"] * share * n_players)
        if boss_dead:
            yen_reward = int(yen_reward * tcfg["kill_bonus"])
        # MVP bonus for #1 damage dealer (only if boss killed)
        if rank == 0 and boss_dead:
            yen_reward += tcfg["mvp_bonus"]

        # Item drop based on tier chance; everyone gets one on high tier
        give_item = boss_dead and (random.random() < tcfg["item_chance"])
        item_name = random.choice(tcfg["item_pool"]) if give_item else None

        try:
            tgt = get_player(int(pid))
            if tgt:
                if yen_reward > 0:
                    update_player(int(pid), yen=tgt["yen"] + yen_reward)
                if item_name:
                    add_item(int(pid), item_name, "material")

            rank_txt = {0: "🥇 *MVP!*", 1: "🥈 2nd", 2: "🥉 3rd"}.get(rank, f"`#{rank+1}`")
            item_txt = f"\n🎁 *{item_name}*" if item_name else ""
            pct      = share * 100

            await context.bot.send_message(
                chat_id=int(pid),
                text=(
                    f"🏆 *RAID OVER — {raid['boss_emoji']} {boss_name}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{_tier_label(boss_name)}\n"
                    f"{'☠️ *BOSS DEFEATED!*' if boss_dead else '🏃 Boss escaped.'}\n\n"
                    f"📊 Your damage: *{pdata['damage']:,}* ({pct:.1f}%)\n"
                    f"🏅 Rank: {rank_txt}\n"
                    f"💰 Reward: *+{yen_reward:,}¥*{item_txt}"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            log.error("[EXCEPTION] %s", e)

        results.append({
            "name":       pdata["name"],
            "damage":     pdata["damage"],
            "share":      share,
            "yen_reward": yen_reward,
            "item_name":  item_name,
        })

    # Award clan XP if boss was killed
    if boss_dead and clan:
        col("clans").update_one(
            {"id": raid["clan_id"]},
            {"$inc": {"xp": tcfg["clan_xp"]}}
        )

    # Post MVP leaderboard to clan group
    if clan:
        await _post_raid_results_to_group(context, clan, raid, results, boss_dead)


# ── MAIN /clanraid COMMAND ────────────────────────────────────────────────────

@dm_only
async def clanraid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start.")
        return

    clan_id = player.get("clan_id")
    if not clan_id:
        await update.message.reply_text("❌ You must be in a clan. Use `/clan` to join one.", parse_mode="Markdown")
        return

    clan = col("clans").find_one({"id": clan_id})
    if not clan:
        await update.message.reply_text("❌ Clan not found.")
        return

    sub = context.args[0].lower() if context.args else "status"

    # ── START ─────────────────────────────────────────────────────────────────
    if sub == "start":
        role = player.get("clan_role", "recruit")
        if role not in ("leader", "chief", "deputy"):
            await update.message.reply_text("❌ Only Leader/Chief/Deputy can start a raid.")
            return

        last = col("clan_raids").find_one(
            {"clan_id": clan_id, "status": "finished"},
            sort=[("ended_at", -1)]
        )
        if last and last.get("ended_at"):
            diff = datetime.utcnow() - last["ended_at"]
            if diff < timedelta(days=RAID_COOLDOWN_DAYS):
                rem  = timedelta(days=RAID_COOLDOWN_DAYS) - diff
                days = rem.days
                hrs  = int(rem.seconds // 3600)
                await update.message.reply_text(
                    f"⏳ *Raid Cooldown:* {days}d {hrs}h remaining.\n_Raids have a 1-week cooldown._",
                    parse_mode="Markdown"
                )
                return

        if _get_active_raid(clan_id):
            await update.message.reply_text("❌ A raid is already active! Use `/clanraid status`.")
            return

        boss_name = " ".join(context.args[1:]).strip().title() if len(context.args) > 1 else "Muzan"
        boss      = RAID_BOSSES.get(boss_name)
        if not boss:
            # Build boss list grouped by tier for the error message
            tier_lines = []
            for t in TIER_ORDER:
                tcfg  = TIER_CONFIG[t]
                names = [n for n, b in RAID_BOSSES.items() if b["tier"] == t]
                tier_lines.append(f"{tcfg['label']}: {', '.join(names)}")
            await update.message.reply_text(
                f"❌ Unknown boss: *{boss_name}*\n\n"
                f"📋 *Available bosses:*\n" + "\n".join(tier_lines) + "\n\n"
                f"Usage: `/clanraid start Muzan`",
                parse_mode="Markdown"
            )
            return

        tier  = boss["tier"]
        tcfg  = TIER_CONFIG[tier]

        col("clan_raids").insert_one({
            "clan_id":     clan_id,
            "clan_name":   clan.get("name", "?"),
            "boss_name":   boss_name,
            "boss_emoji":  boss["emoji"],
            "boss_hp":     boss["hp"],
            "boss_max_hp": boss["hp"],
            "boss_atk":    boss["atk"],
            "tier":        tier,
            "status":      "active",
            "started_by":  user_id,
            "started_at":  datetime.utcnow(),
            "ended_at":    None,
            "participants": {},
        })

        await update.message.reply_text(
            f"⚔️ *CLAN RAID STARTED!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{tcfg['label']}\n"
            f"{boss['emoji']} *Boss: {boss_name}*\n"
            f"❤️ HP: *{boss['hp']:,}*\n"
            f"⚔️ ATK: *{boss['atk']}*\n\n"
            f"🎁 *Rewards (on kill):*\n"
            f"  💰 Base pool: *{tcfg['base_yen']:,}¥* per fighter\n"
            f"  🏅 MVP bonus: *+{tcfg['mvp_bonus']:,}¥*\n"
            f"  🎁 Item chance: *{int(tcfg['item_chance']*100)}%*\n"
            f"  ⭐ Clan XP: *+{tcfg['clan_xp']:,}*\n\n"
            f"📢 Members: `/clanraid join` (fee: {RAID_JOIN_FEE:,}¥)\n"
            f"⚔️ Then: `/clanraid attack` to fight!",
            parse_mode="Markdown"
        )
        return

    # ── JOIN ──────────────────────────────────────────────────────────────────
    if sub == "join":
        raid    = _get_active_raid(clan_id)
        if not raid:
            await update.message.reply_text("❌ No active raid. Ask your leader to start one.")
            return
        uid_str = str(user_id)
        if uid_str in (raid.get("participants") or {}):
            await update.message.reply_text("✅ You already joined! Use `/clanraid attack` to fight.", parse_mode="Markdown")
            return
        if len(raid.get("participants", {})) >= RAID_MAX_MEMBERS:
            await update.message.reply_text(f"❌ Raid full ({RAID_MAX_MEMBERS} max).")
            return
        if player["yen"] < RAID_JOIN_FEE:
            await update.message.reply_text(f"❌ Need {RAID_JOIN_FEE:,}¥ to join. You have {player['yen']:,}¥.")
            return

        update_player(user_id, yen=player["yen"] - RAID_JOIN_FEE)
        col("clan_raids").update_one(
            {"_id": raid["_id"]},
            {"$set": {f"participants.{uid_str}": {
                "name":      player["name"],
                "damage":    0,
                "attacks":   0,
                "joined_at": datetime.utcnow().isoformat(),
            }}}
        )
        tier_label = _tier_label(raid["boss_name"])
        await update.message.reply_text(
            f"✅ *Joined the raid!*\n\n"
            f"{tier_label}\n"
            f"{raid['boss_emoji']} Fighting *{raid['boss_name']}*\n"
            f"❤️ Boss HP: *{raid['boss_hp']:,}*\n"
            f"💸 Fee paid: *{RAID_JOIN_FEE:,}¥*\n\n"
            f"⚔️ Use `/clanraid attack` to take your turn!",
            parse_mode="Markdown"
        )
        return

    # ── ATTACK ────────────────────────────────────────────────────────────────
    if sub == "attack":
        raid    = _get_active_raid(clan_id)
        if not raid:
            await update.message.reply_text("❌ No active raid.")
            return
        uid_str = str(user_id)
        if uid_str not in (raid.get("participants") or {}):
            await update.message.reply_text("❌ Join the raid first with `/clanraid join`.", parse_mode="Markdown")
            return
        if raid["boss_hp"] <= 0:
            await update.message.reply_text("✅ Boss already defeated! Leader use `/clanraid end`.")
            return

        existing = get_battle_state(user_id)
        if existing and existing.get("in_combat") and existing.get("is_raid"):
            await update.message.reply_text(
                "⚔️ You're already in the raid battle!\n_Use the buttons in your battle message._",
                parse_mode="Markdown"
            )
            return

        now_ts           = datetime.utcnow()
        current_attacker = raid.get("current_attacker")

        # Auto-expire stale lock after 3 minutes
        if current_attacker and current_attacker != user_id:
            lock_time = raid.get("attack_lock_at")
            if lock_time:
                lock_dt = datetime.fromisoformat(lock_time) if isinstance(lock_time, str) else lock_time
                if (now_ts - lock_dt).total_seconds() > 180:
                    col("clan_raids").update_one(
                        {"_id": raid["_id"]},
                        {"$unset": {"current_attacker": "", "attack_lock_at": ""}}
                    )
                    current_attacker = None

        if current_attacker and current_attacker != user_id:
            atk_name  = raid.get("participants", {}).get(str(current_attacker), {}).get("name", "Someone")
            lock_time = raid.get("attack_lock_at")
            if lock_time:
                lock_dt = datetime.fromisoformat(lock_time) if isinstance(lock_time, str) else lock_time
                wait    = max(1, 180 - int((now_ts - lock_dt).total_seconds()))
            else:
                wait = 180
            await update.message.reply_text(
                f"⚔️ *{atk_name}* is currently fighting!\n"
                f"_Their turn ends in ~{wait}s_\n\n"
                f"Only one warrior faces the boss at a time.",
                parse_mode="Markdown"
            )
            return

        result = col("clan_raids").update_one(
            {"_id": raid["_id"], "current_attacker": {"$exists": False}},
            {"$set": {"current_attacker": user_id, "attack_lock_at": now_ts.isoformat()}}
        )
        if result.modified_count == 0:
            await update.message.reply_text("⏳ Someone just grabbed the turn. Try again in a moment.")
            return

        await _start_raid_turn(context, user_id, raid)
        return

    # ── STATUS ────────────────────────────────────────────────────────────────
    if sub in ("status", ""):
        raid = _get_active_raid(clan_id)
        if not raid:
            last = col("clan_raids").find_one(
                {"clan_id": clan_id, "status": "finished"},
                sort=[("ended_at", -1)]
            )
            if last:
                await update.message.reply_text(
                    f"📋 *Last Raid:* {last['boss_emoji']} {last['boss_name']}\n"
                    f"No active raid.\n\n"
                    f"💡 `/clanraid bosses` — see all bosses by tier\n"
                    f"💡 `/clanraid start [boss]` to begin!",
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text(
                    f"📋 No raids yet.\n\n"
                    f"💡 `/clanraid bosses` — see available bosses\n"
                    f"💡 `/clanraid start [boss]` — start one!",
                    parse_mode="Markdown"
                )
            return

        parts        = raid.get("participants", {})
        h_bar        = hp_bar(raid["boss_hp"], raid["boss_max_hp"], 12)
        uid_str      = str(user_id)
        sorted_parts = sorted(parts.items(), key=lambda x: x[1].get("damage", 0), reverse=True)
        current      = raid.get("current_attacker")
        cur_name     = parts.get(str(current), {}).get("name", "?") if current else "No one"
        tier_label   = _tier_label(raid["boss_name"])

        lines = [
            f"⚔️ *ACTIVE RAID*",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"{tier_label}",
            f"{raid['boss_emoji']} *{raid['boss_name']}*",
            f"❤️ {raid['boss_hp']:,} / {raid['boss_max_hp']:,}",
            f"{h_bar}",
            f"",
            f"⚔️ *Currently fighting:* {cur_name}",
            f"👥 *Damage Board:*",
        ]
        rank_icons = ["🥇", "🥈", "🥉"]
        for i, (pid, pd) in enumerate(sorted_parts, 0):
            icon = rank_icons[i] if i < 3 else f"  {i+1}."
            you  = " ← you" if pid == uid_str else ""
            lines.append(f"{icon} {pd['name']} — *{pd['damage']:,}*{you}")

        joined = uid_str in parts
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"{'⚔️ `/clanraid attack` — Fight!' if joined else f'💡 `/clanraid join` (fee: {RAID_JOIN_FEE:,}¥)'}",
        ]
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # ── BOSSES ────────────────────────────────────────────────────────────────
    if sub == "bosses":
        lines = ["👹 *RAID BOSSES*\n━━━━━━━━━━━━━━━━━━━━━\n"]
        for tier in TIER_ORDER:
            tcfg  = TIER_CONFIG[tier]
            names = [(n, b) for n, b in RAID_BOSSES.items() if b["tier"] == tier]
            lines.append(f"{tcfg['label']}")
            lines.append(f"  💰 Base reward: *{tcfg['base_yen']:,}¥*  |  🏅 MVP bonus: *+{tcfg['mvp_bonus']:,}¥*")
            lines.append(f"  🎁 Item chance: *{int(tcfg['item_chance']*100)}%*  |  ⭐ Clan XP: *+{tcfg['clan_xp']:,}*\n")
            for name, b in names:
                techs = ", ".join(b.get("techniques", []))
                lines += [
                    f"  {b['emoji']} *{name}*",
                    f"     ❤️ {b['hp']:,} HP  |  ⚔️ ATK {b['atk']}",
                    f"     💫 _{techs}_\n",
                ]
        lines.append("Usage: `/clanraid start [boss name]`")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    # ── END ───────────────────────────────────────────────────────────────────
    if sub == "end":
        role = player.get("clan_role", "recruit")
        if role not in ("leader", "chief", "deputy"):
            await update.message.reply_text("❌ Only Leader/Chief/Deputy can end a raid.")
            return
        raid = _get_active_raid(clan_id)
        if not raid:
            await update.message.reply_text("❌ No active raid.")
            return

        boss_dead = raid["boss_hp"] <= 0
        await _finalize_raid(context, raid, clan, boss_dead=boss_dead)

        # Confirm in the leader's DM
        await update.message.reply_text(
            f"✅ *Raid finalized!*\n"
            f"{raid['boss_emoji']} *{raid['boss_name']}* — "
            f"{'☠️ Defeated' if boss_dead else '🏃 Escaped'}\n\n"
            f"Rewards sent to all participants.\n"
            f"{'Results posted to clan group!' if clan.get('group_chat_id') else '⚠️ No clan group set — use `/setclangroupid` to enable group posts.'}",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "❓ *Raid subcommands:*\n"
        "  `/clanraid start [boss]` — start a raid\n"
        "  `/clanraid join` — join active raid\n"
        "  `/clanraid attack` — take your turn\n"
        "  `/clanraid status` — live damage board\n"
        "  `/clanraid bosses` — all bosses by tier\n"
        "  `/clanraid end` — end and distribute rewards",
        parse_mode="Markdown"
    )


# ── RAID BATTLE CALLBACKS ─────────────────────────────────────────────────────

async def raid_attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Player presses ⚔️ Attack during raid battle."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    state   = get_battle_state(user_id)

    if not state or not state.get("in_combat") or not state.get("is_raid"):
        await query.edit_message_text("⚔️ No active raid battle. Use `/clanraid attack`.", parse_mode="Markdown")
        return

    clan_id = state.get("raid_clan_id")
    raid    = _get_active_raid(clan_id) if clan_id else None
    if not raid or raid["boss_hp"] <= 0:
        clear_battle_state(user_id)
        await query.edit_message_text("✅ Boss already defeated! Leader use `/clanraid end`.", parse_mode="Markdown")
        return

    battle_log = []
    try:
        from handlers.explore import (calc_dmg, _safe_get_skills, _safe_get_bonuses, calc_pressure)
        owned    = _safe_get_skills(user_id)
        bonuses  = _safe_get_bonuses(user_id, context)
        pressure = context.user_data.get("pressure") or calc_pressure(player, player.get("location", "asakusa"))
        combo    = context.user_data.get("combo", 0)

        base_dmg = calc_dmg(player, owned_skills=owned, user_id=user_id, context=context)
        base_dmg = int(base_dmg * pressure.get("atk_mult", 1.0))
        if combo >= 3:
            base_dmg = int(base_dmg * 1.25)
            battle_log.append(f"🔥 *COMBO x{combo}!* +25% dmg!")
        crit = random.random() < (0.15 + bonuses.get("crit_bonus", 0))
        if crit:
            base_dmg = int(base_dmg * 1.5)
            battle_log.append("💥 *CRITICAL HIT!*")
    except Exception:
        base_dmg = player["str_stat"] * 3 + random.randint(15, 40)

    boss_data   = RAID_BOSSES.get(raid["boss_name"], {})
    boss_pct    = state["enemy_hp"] / raid["boss_max_hp"]
    enrage_mult = 1.4 if boss_pct <= boss_data.get("enrage_pct", 0.4) else 1.0
    if enrage_mult > 1.0 and not context.user_data.get("raid_enraged"):
        context.user_data["raid_enraged"] = True
        battle_log.append(f"😡 *{raid['boss_name']} ENRAGES!* ATK x1.4!")

    boss_atk = int(raid["boss_atk"] * enrage_mult)
    if raid["boss_name"] == "Muzan":
        boss_raw = random.randint(int(boss_atk * 1.3), int(boss_atk * 1.6))
    elif raid["boss_name"] in ("Kokushibo", "Doma"):
        boss_raw = random.randint(int(boss_atk * 1.0), int(boss_atk * 1.4))
    else:
        boss_raw = random.randint(int(boss_atk * 0.7), int(boss_atk * 1.1))

    armor_map = {
        "Corps Uniform": 5, "Reinforced Haori": 15, "Hashira Haori": 30,
        "Demon Slayer Uniform EX": 55, "Flame Haori": 85, "Yoriichi Haori": 150,
    }
    boss_dmg = max(1, boss_raw - armor_map.get(player.get("equipped_armor", ""), 0))

    techs = boss_data.get("techniques", [])
    if techs and random.random() < 0.35:
        tech     = random.choice(techs)
        boss_dmg = int(boss_dmg * 1.3)
        battle_log.append(f"💫 *{raid['boss_name']}* uses *{tech}!* (+30% dmg)")

    new_boss_hp   = max(0, state["enemy_hp"] - base_dmg)
    new_player_hp = max(0, player["hp"] - boss_dmg)
    update_battle_enemy_hp(user_id, new_boss_hp)
    update_player(user_id, hp=new_player_hp)

    col("clan_raids").update_one(
        {"clan_id": clan_id, "status": "active", "boss_hp": {"$gt": new_boss_hp}},
        {"$set": {"boss_hp": new_boss_hp}}
    )

    try:
        context.user_data["combo"] = context.user_data.get("combo", 0) + 1
    except Exception:
        pass

    battle_log.insert(0, f"⚔️ You hit for *{base_dmg:,}*! Boss counters: *{boss_dmg}* back.")
    player_after = get_player(user_id)

    if new_boss_hp <= 0:
        await query.edit_message_text(
            f"💀 *{raid['boss_emoji']} {raid['boss_name']} DEFEATED!*\n\n"
            f"Your final hit: *{base_dmg:,}*\n\n"
            f"🎉 Raid complete! Rewards being distributed...",
            parse_mode="Markdown"
        )
        await _end_raid_turn(context, user_id, clan_id, base_dmg)
        return

    if new_player_hp <= 0:
        await query.edit_message_text(
            f"💀 *You were defeated by {raid['boss_name']}!*\n\n"
            f"You dealt *{base_dmg:,}* before falling.\n"
            f"_Your turn is over — other fighters notified._",
            parse_mode="Markdown"
        )
        await _end_raid_turn(context, user_id, clan_id, base_dmg, dead=True)
        update_player(user_id, hp=player["max_hp"] // 2)
        return

    state_fresh = get_battle_state(user_id)
    raid_fresh  = _get_active_raid(clan_id) or raid

    await query.edit_message_text(
        _raid_status_text(player_after, raid_fresh, state_fresh, battle_log),
        parse_mode="Markdown",
        reply_markup=_raid_combat_keyboard()
    )


async def raid_technique_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Player presses 💨 Technique — show form list."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    state   = get_battle_state(user_id)

    if not state or not state.get("is_raid"):
        await query.answer("No active raid battle!", show_alert=True)
        return

    try:
        from handlers.explore import get_level
        from utils.helpers import get_unlocked_forms
        style = player.get("style") or player.get("art")
        level = get_level(player["xp"])
        if not style:
            await query.answer("No style/art equipped!", show_alert=True)
            return
        forms = get_unlocked_forms(style, level, player.get("rank"), player.get("faction"))
        if not forms:
            await query.answer("No forms unlocked yet!", show_alert=True)
            return

        buttons = []
        for f in forms:
            buttons.append([InlineKeyboardButton(
                f"✨ Form {f['form']} — {f['name']} ({f['sta_cost']} STA)",
                callback_data=f"raid_form_{f['form']}"
            )])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data="raid_back")])
        await query.edit_message_text(
            f"💨 *{style.upper()} — CHOOSE FORM*\n\n🌀 STA: {player['sta']}/{player['max_sta']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        await query.answer(f"Error: {e}", show_alert=True)


async def raid_use_form_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Player selects a technique form during raid."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    state   = get_battle_state(user_id)

    if not state or not state.get("is_raid"):
        await query.answer("No active raid battle!", show_alert=True)
        return

    clan_id = state.get("raid_clan_id")
    raid    = _get_active_raid(clan_id) if clan_id else None
    if not raid:
        await query.answer("Raid ended!", show_alert=True)
        return

    try:
        form_num = int(query.data.split("_")[2])
    except Exception:
        await query.answer("Invalid form!", show_alert=True)
        return

    try:
        from utils.helpers import get_unlocked_forms
        from handlers.explore import get_level, calc_pressure, _safe_get_bonuses
        style  = player.get("style") or player.get("art")
        level  = get_level(player["xp"])
        forms  = get_unlocked_forms(style, level, player.get("rank"), player.get("faction"))
        form   = next((f for f in forms if f["form"] == form_num), None)
        if not form:
            await query.answer("Form not unlocked!", show_alert=True)
            return

        bonuses  = _safe_get_bonuses(user_id, context)
        sta_cost = max(0, form["sta_cost"] - bonuses.get("sta_reduce", 0))
        if player["sta"] < sta_cost:
            await query.answer(f"Not enough STA! Need {sta_cost}.", show_alert=True)
            return

        pressure = context.user_data.get("pressure") or calc_pressure(player, player.get("location", "asakusa"))
        base_dmg = random.randint(form["dmg_min"], form["dmg_max"])
        base_dmg = int(base_dmg * pressure.get("tech_mult", 1.0))
        if bonuses.get("tech_pct"):
            base_dmg = int(base_dmg * (1 + bonuses["tech_pct"]))
        crit = random.random() < 0.20
        if crit:
            base_dmg = int(base_dmg * 1.5)

        boss_data = RAID_BOSSES.get(raid["boss_name"], {})
        boss_pct  = state["enemy_hp"] / raid["boss_max_hp"]
        enrage_m  = 1.4 if boss_pct <= boss_data.get("enrage_pct", 0.4) else 1.0
        boss_raw  = random.randint(int(raid["boss_atk"] * enrage_m * 0.6), int(raid["boss_atk"] * enrage_m * 1.1))
        boss_dmg  = max(1, boss_raw)

        new_boss_hp   = max(0, state["enemy_hp"] - base_dmg)
        new_player_hp = max(0, player["hp"] - boss_dmg)
        update_battle_enemy_hp(user_id, new_boss_hp)
        update_player(user_id, hp=new_player_hp, sta=max(0, player["sta"] - sta_cost))

        col("clan_raids").update_one(
            {"clan_id": clan_id, "status": "active", "boss_hp": {"$gt": new_boss_hp}},
            {"$set": {"boss_hp": new_boss_hp}}
        )

        battle_log = [
            f"💨 *{style} — Form {form_num}!* _{form['name']}_",
            f"✨ Dealt *{base_dmg:,}*" + (" 💥 *CRIT!*" if crit else "") + f"  |  Boss hits *{boss_dmg}*",
        ]

        if new_boss_hp <= 0:
            await query.edit_message_text(
                f"💀 *BOSS DEFEATED BY TECHNIQUE!*\n\n"
                f"{style} Form {form_num} — {form['name']}\n"
                f"Dealt *{base_dmg:,}*!\n\n"
                f"🎉 Rewards being distributed...",
                parse_mode="Markdown"
            )
            await _end_raid_turn(context, user_id, clan_id, base_dmg)
            return

        if new_player_hp <= 0:
            await query.edit_message_text(
                f"💀 *You fell using {form['name']}!*\n"
                f"Dealt *{base_dmg:,}* before going down.\n_Next fighter notified._",
                parse_mode="Markdown"
            )
            await _end_raid_turn(context, user_id, clan_id, base_dmg, dead=True)
            update_player(user_id, hp=player["max_hp"] // 2)
            return

        raid_fresh   = _get_active_raid(clan_id) or raid
        state_fresh  = get_battle_state(user_id)
        player_after = get_player(user_id)

        await query.edit_message_text(
            _raid_status_text(player_after, raid_fresh, state_fresh, battle_log),
            parse_mode="Markdown",
            reply_markup=_raid_combat_keyboard()
        )

    except Exception as e:
        await query.edit_message_text(f"❌ Form error: {e}", parse_mode="Markdown",
                                       reply_markup=_raid_combat_keyboard())


async def raid_items_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show usable items during raid battle."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state   = get_battle_state(user_id)

    if not state or not state.get("is_raid"):
        await query.answer("No active raid battle!", show_alert=True)
        return

    inv    = get_inventory(user_id)
    usable = [i for i in inv if i.get("item_type") in ("item", "potion") or
              any(k in i["item_name"].lower() for k in ("gourd", "pill", "antidote", "elixir", "core"))]
    if not usable:
        await query.answer("No usable items!", show_alert=True)
        return

    buttons = []
    for item in usable[:8]:
        buttons.append([InlineKeyboardButton(
            f"🧪 {item['item_name']} ×{item.get('quantity', 1)}",
            callback_data=f"raid_useitem_{item['item_name'][:20]}"
        )])
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="raid_back")])
    await query.edit_message_text(
        "🧪 *USE ITEM*\nChoose an item to use:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def raid_use_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use an item during raid battle."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    state   = get_battle_state(user_id)

    if not state or not state.get("is_raid"):
        await query.answer("No active raid battle!", show_alert=True)
        return

    item_name = query.data[len("raid_useitem_"):]
    clan_id   = state.get("raid_clan_id")
    raid      = _get_active_raid(clan_id) if clan_id else None
    if not raid:
        return

    inv  = get_inventory(user_id)
    item = next((i for i in inv if i["item_name"].startswith(item_name)), None)
    if not item:
        await query.answer("Item not found!", show_alert=True)
        return

    battle_log = []
    nm = item["item_name"].lower()
    if "recovery gourd" in nm or "full recovery" in nm:
        update_player(user_id, hp=player["max_hp"])
        battle_log.append("🍶 *Full Recovery Gourd!* HP fully restored!")
    elif "stamina pill" in nm or "stamina" in nm:
        update_player(user_id, sta=min(player["max_sta"], player["sta"] + 50))
        battle_log.append("💊 *Stamina Pill!* +50 STA!")
    elif "wisteria" in nm:
        battle_log.append("🌿 *Wisteria Antidote!* Status effects cleared!")
    elif "elixir" in nm or "blood" in nm:
        heal = int(player["max_hp"] * 0.5)
        update_player(user_id, hp=min(player["max_hp"], player["hp"] + heal))
        battle_log.append(f"🔮 *Demon Blood Elixir!* +{heal} HP!")
    else:
        heal = int(player["max_hp"] * 0.30)
        update_player(user_id, hp=min(player["max_hp"], player["hp"] + heal))
        battle_log.append(f"🧪 *{item['item_name']}!* +{heal} HP!")

    remove_item(user_id, item["item_name"], 1)

    player_after = get_player(user_id)
    raid_fresh   = _get_active_raid(clan_id) or raid
    state_fresh  = get_battle_state(user_id)

    await query.edit_message_text(
        _raid_status_text(player_after, raid_fresh, state_fresh, battle_log),
        parse_mode="Markdown",
        reply_markup=_raid_combat_keyboard()
    )


async def raid_retreat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Player retreats from raid — releases turn lock."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state   = get_battle_state(user_id)

    if not state or not state.get("is_raid"):
        await query.answer("No active raid battle!", show_alert=True)
        return

    clan_id = state.get("raid_clan_id")

    await query.edit_message_text(
        "🏃 *You retreated from the raid!*\n\n"
        "_Your turn is over — other fighters notified._",
        parse_mode="Markdown"
    )
    await _end_raid_turn(context, user_id, clan_id or "", 0, fled=True)


async def raid_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Return to main raid combat screen."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    state   = get_battle_state(user_id)

    if not state or not state.get("is_raid"):
        await query.answer("No active raid battle!", show_alert=True)
        return

    clan_id = state.get("raid_clan_id")
    raid    = _get_active_raid(clan_id) if clan_id else None
    if not raid:
        await query.edit_message_text("❌ Raid not found.", parse_mode="Markdown")
        return

    await query.edit_message_text(
        _raid_status_text(player, raid, state),
        parse_mode="Markdown",
        reply_markup=_raid_combat_keyboard()
    )


# ── /clanrole command ──────────────────────────────────────────────────────────

@dm_only
async def clanrole(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player or not player.get("clan_id"):
        await update.message.reply_text("❌ You are not in a clan.")
        return
    my_role = player.get("clan_role", "recruit")
    if my_role not in ("leader", "chief"):
        await update.message.reply_text("❌ Only Leader or Chief can assign roles.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "📋 *CLAN ROLES*\n👑 Leader  ⭐ Chief  🔷 Deputy  🔹 Officer  👤 Member\n\n"
            "Usage: `/clanrole @username [chief|deputy|officer|member]`",
            parse_mode="Markdown"
        )
        return

    uname    = context.args[0].lstrip("@")
    new_role = context.args[1].lower()
    if new_role == "member":
        new_role = "recruit"
    if new_role not in ("chief", "deputy", "officer", "recruit"):
        await update.message.reply_text("❌ Valid roles: chief, deputy, officer, member")
        return
    if new_role == "chief" and my_role != "leader":
        await update.message.reply_text("❌ Only the Leader can assign Chief.")
        return

    target = col("players").find_one({"username": {"$regex": f"^{uname}$", "$options": "i"}})
    if not target or target.get("clan_id") != player["clan_id"]:
        await update.message.reply_text(f"❌ @{uname} not found in your clan.")
        return
    if target.get("clan_role") == "leader":
        await update.message.reply_text("❌ Cannot change the leader's role.")
        return

    icons = {"chief": "⭐", "deputy": "🔷", "officer": "🔹", "recruit": "👤"}
    update_player(target["user_id"], clan_role=new_role)
    await update.message.reply_text(
        f"✅ *{target['name']}* is now {icons[new_role]} *{new_role.title()}*",
        parse_mode="Markdown"
    )
    try:
        await context.bot.send_message(
            chat_id=target["user_id"],
            text=f"📢 Your clan role has been updated to {icons[new_role]} *{new_role.title()}* by {player['name']}.",
            parse_mode="Markdown"
        )
    except Exception as e:
        log.error("[EXCEPTION] %s", e)


# ── /setclangroupid — let leader link the clan group chat ─────────────────────

async def setclangroupid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Run this command INSIDE the clan group chat.
    The bot must be an admin there to be able to post results later.
    Usage: /setclangroupid  (just run it in the group, no args needed)
    """
    chat = update.effective_chat
    user_id = update.effective_user.id

    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text(
            "❌ Run this command *inside your clan group chat*, not in DM.",
            parse_mode="Markdown"
        )
        return

    player = get_player(user_id)
    if not player or not player.get("clan_id"):
        await update.message.reply_text("❌ You are not in a clan.")
        return

    clan_data = col("clans").find_one({"id": player["clan_id"]})
    if not clan_data or clan_data["leader_id"] != user_id:
        await update.message.reply_text("❌ Only the clan leader can link the group.")
        return

    col("clans").update_one(
        {"id": player["clan_id"]},
        {"$set": {"group_chat_id": chat.id}}
    )
    await update.message.reply_text(
        f"✅ *Clan group linked!*\n\n"
        f"Raid results and MVP boards will now be posted here after every raid.\n"
        f"Make sure the bot is an admin so it can send messages.",
        parse_mode="Markdown"
    )
