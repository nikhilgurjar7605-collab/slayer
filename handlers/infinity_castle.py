"""Infinity Castle Telegram commands and persistent turn-based encounters."""
import random
from datetime import datetime
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import get_player, update_player, col
from utils.helpers import get_level
from utils.castle_database import (
    create_castle_run, get_active_castle_run, save_castle_run,
    calculate_player_power, calculate_difficulty, create_castle_party,
    get_castle_party, add_castle_party_member, add_demon_xp,
    grant_castle_equipment, record_castle_clear,
)

MAX_FLOOR = 100
BOSS_FLOORS = {10, 20, 30, 40, 50, 60, 70, 80, 90, 100}
ENEMY_NAMES = [
    "Castle Wraith", "Infinity Guardian", "Upper Moon Shade",
    "Void Stalker", "Demon General",
]
BOSS_NAMES = {
    10: "Lower Moon Executioner", 20: "Blood Art Commander",
    30: "Upper Moon Sentinel", 40: "Crimson Kizuki",
    50: "Ancient Upper Moon", 60: "Infinity Castle General",
    70: "Upper Moon Champion", 80: "Moon Breathing Phantom",
    90: "Kokushibo's Shadow", 100: "Muzan Kibutsuji",
}
RARITY_WEIGHT = {
    "common": 45, "uncommon": 30, "rare": 16,
    "epic": 7, "legendary": 1.7, "mythic": 0.3,
}


def _level(player):
    return max(1, int(get_level(int(player.get("xp", 0) or 0))))


def _party_players(party):
    if not party:
        return []
    return [p for uid in party.get("member_ids", [])
            if (p := get_player(int(uid))) is not None]


def _find_run(user_id):
    run = get_active_castle_run(user_id)
    if run:
        return run
    party = col("castle_parties").find_one(
        {"member_ids": int(user_id), "status": "running"}
    )
    if party:
        run = col("castle_runs").find_one(
            {"party_id": party["party_id"], "status": "active"}
        )
        if run:
            run.pop("_id", None)
    return run


def _enemy_for(player, floor, party_players):
    difficulty = calculate_difficulty(player, floor, party_players)
    level = difficulty["enemy_level"]
    boss = floor in BOSS_FLOORS
    name = BOSS_NAMES.get(floor) if boss else random.choice(ENEMY_NAMES)
    base_hp = 65 + level * 17 + floor * 9
    base_atk = 8 + level * 2 + floor // 3
    size = max(1, len(party_players))
    # Team scaling increases enemy durability and attack gently, not 4x.
    hp = int(base_hp * (1 + 0.48 * (size - 1)))
    atk = int(base_atk * (1 + 0.12 * (size - 1)))
    if boss:
        hp = int(hp * 2.2)
        atk = int(atk * 1.35)
    return {
        "name": name, "level": level, "demon_level": level, "hp": hp, "max_hp": hp,
        "atk": atk, "boss": boss, "difficulty": difficulty["tier"],
        "rank": "Upper Moon" if floor >= 70 else ("Lower Moon" if floor >= 30 else ("Elite" if floor >= 10 else "Demon")),
    }


def _keyboard(run, is_party_member=True):
    rows = []
    enemy = run.get("current_enemy") or {}
    if enemy and int(enemy.get("hp", 0)) > 0:
        rows.append([
            InlineKeyboardButton("⚔️ Attack", callback_data="castle:attack"),
            InlineKeyboardButton("🏃 Retreat", callback_data="castle:retreat"),
        ])
    else:
        rows.append([InlineKeyboardButton("➡️ Next Floor", callback_data="castle:next")])
    rows.append([InlineKeyboardButton("📊 Status", callback_data="castle:status")])
    return InlineKeyboardMarkup(rows)


def _render_run(run, player, party=None, notice=None):
    floor = int(run.get("floor", 1))
    enemy = run.get("current_enemy") or {}
    members = party.get("member_ids", []) if party else [run.get("user_id")]
    hp_map = run.get("player_hp_by_user", {})
    lines = [
        "🏯 <b>INFINITY CASTLE</b>",
        f"Floor <b>{floor}/{MAX_FLOOR}</b>  •  Checkpoint: {run.get('checkpoint_floor', 1)}",
        f"Mode: <b>{run.get('mode', 'solo').title()}</b>  •  Squad: {len(members)}/4",
        f"Your level: <b>{_level(player)}</b>  •  Combat power: <b>{calculate_player_power(player):,}</b>",
    ]
    if notice:
        lines += ["", notice]
    if enemy:
        lines += [
            "", "━━━━━━━━━━━━━━━━━━━━",
            f"{'☠️ BOSS' if enemy.get('boss') else '👹 ENEMY'}: <b>{enemy.get('name')}</b>",
            f"Enemy Demon Level: <b>{enemy.get('level')}</b>  •  Rank: {enemy.get('rank')}",
            f"Difficulty: <b>{enemy.get('difficulty')}</b>",
            f"Enemy HP: <b>{max(0, int(enemy.get('hp', 0))):,}/{int(enemy.get('max_hp', 1)):,}</b>",
            "━━━━━━━━━━━━━━━━━━━━",
            "<b>Squad HP</b>",
        ]
        for uid in members:
            member = get_player(int(uid))
            if member:
                hp = hp_map.get(str(uid), member.get("hp", 1))
                lines.append(f"• {member.get('name', 'Slayer')}: {max(0, int(hp)):,} HP")
    if floor == MAX_FLOOR and enemy.get("boss"):
        lines.append("
⚠️ Final battle. Defeat Muzan to clear the Castle.")
    return "
".join(lines)


async def castle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.effective_message.reply_text("Create your character first with /start.")
        return
    args = context.args or []
    action = args[0].lower() if args else "status"

    if action in ("solo", "enter"):
        if _find_run(user_id):
            await update.effective_message.reply_text("You already have an active Castle run. Use /castle status.")
            return
        run = create_castle_run(user_id, "solo")
        await _start_floor(run, player, None)
        run = _find_run(user_id)
        await update.effective_message.reply_text(
            _render_run(run, player), parse_mode="HTML", reply_markup=_keyboard(run)
        )
        return

    if action in ("squad", "party"):
        party = create_castle_party(user_id)
        await update.effective_message.reply_text(
            "👥 <b>Castle squad created!</b>\n"
            f"Party code: <code>{party['party_id']}</code>\n"
            "Share this code. Up to 4 players can join with:\n"
            f"<code>/castle join {party['party_id']}</code>\n"
            "Leader starts the run using <code>/castle start</code>.",
            parse_mode="HTML",
        )
        return

    if action == "join":
        if len(args) < 2:
            await update.effective_message.reply_text("Usage: /castle join PARTY_CODE")
            return
        if _find_run(user_id):
            await update.effective_message.reply_text("Finish or retreat from your active Castle run first.")
            return
        ok = add_castle_party_member(args[1], user_id)
        await update.effective_message.reply_text(
            "✅ Joined the squad. The leader can start with /castle start."
            if ok else "❌ Party not found, already full (4 players), or already started."
        )
        return

    if action == "start":
        party = col("castle_parties").find_one(
            {"leader_id": user_id, "status": "open"}
        )
        if not party:
            await update.effective_message.reply_text("You don't have an open squad to start.")
            return
        members = _party_players(party)
        if not members:
            await update.effective_message.reply_text("No valid squad members found.")
            return
        run = create_castle_run(user_id, "squad", party["party_id"])
        hp_map = {str(p["user_id"]): int(p.get("hp", p.get("max_hp", 100)))
                  for p in members}
        save_castle_run(run["run_id"], {"player_hp_by_user": hp_map})
        col("castle_parties").update_one(
            {"party_id": party["party_id"], "status": "open"},
            {"$set": {"status": "running", "updated_at": datetime.utcnow()}}
        )
        await _start_floor(run, player, party)
        run = _find_run(user_id)
        await update.effective_message.reply_text(
            _render_run(run, player, party, "The squad run has begun! Any squad member can take a turn."),
            parse_mode="HTML", reply_markup=_keyboard(run)
        )
        return

    if action == "leave":
        party = col("castle_parties").find_one(
            {"member_ids": user_id, "status": {"$in": ["open", "running"]}}
        )
        if party and party.get("status") == "open":
            col("castle_parties").update_one(
                {"party_id": party["party_id"]},
                {"$pull": {"member_ids": user_id}}
            )
            await update.effective_message.reply_text("You left the open squad.")
        else:
            await update.effective_message.reply_text("You can leave a running squad by retreating from its Castle run.")
        return

    if action == "equip":
        if len(args) < 2:
            await update.effective_message.reply_text("Usage: /castle equip ITEM NAME")
            return
        item_name = " ".join(args[1:]).strip()
        item = col("castle_equipment").find_one({
            "user_id": user_id, "name": {"$regex": f"^{item_name}$", "$options": "i"}
        })
        if not item:
            await update.effective_message.reply_text("You don't own that Castle equipment.")
            return
        slot = item.get("slot", item.get("item_type"))
        field = {"weapon": "castle_equipped_weapon", "sword": "castle_equipped_weapon",
                 "armor": "castle_equipped_armor", "accessory": "castle_equipped_accessory"}.get(slot)
        if not field:
            await update.effective_message.reply_text("This equipment slot is not supported.")
            return
        col("castle_equipment").update_many(
            {"user_id": user_id, "item_type": slot}, {"$set": {"equipped": False}}
        )
        col("castle_equipment").update_one(
            {"instance_id": item["instance_id"], "user_id": user_id},
            {"$set": {"equipped": True}}
        )
        update_player(user_id, **{field: item["name"]})
        await update.effective_message.reply_text(
            f"✅ Equipped <b>{item['name']}</b> in your {slot} slot.",
            parse_mode="HTML"
        )
        return

    if action in ("equipment", "items"):
        owned = list(col("castle_equipment").find({"user_id": user_id}).sort("obtained_at", -1).limit(30))
        if not owned:
            await update.effective_message.reply_text("No Castle equipment yet. Defeat enemies and bosses to earn equipment.")
            return
        lines = ["🎁 <b>CASTLE EQUIPMENT</b>"]
        for item in owned:
            lines.append(
                f"• <b>{item.get('name')}</b> [{item.get('rarity', 'Common').title()}] "
                f"— {item.get('slot')} — Floor {item.get('source_floor')}"
            )
        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    if action == "leaderboard":
        rows = list(col("castle_leaderboards").find({"mode": "solo"}).sort("highest_floor", -1).limit(10))
        lines = ["🏆 <b>CASTLE SOLO LEADERBOARD</b>"]
        for i, row in enumerate(rows, 1):
            member = get_player(int(row["user_id"])) or {}
            lines.append(f"{i}. {member.get('name', 'Unknown')} — Floor {row.get('highest_floor', 0)}")
        if len(lines) == 1:
            lines.append("No clears recorded yet.")
        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    run = _find_run(user_id)
    if not run:
        await update.effective_message.reply_text(
            "🏯 <b>INFINITY CASTLE</b>\n"
            "100 floors • Adaptive difficulty • Solo or squads of 4\n\n"
            "/castle solo — Start alone\n"
            "/castle squad — Create a squad\n"
            "/castle join CODE — Join a squad\n"
            "/castle start — Leader starts squad run\n"
            "/castle status — Current run\n"
            "/castle equipment — Your Castle gear\n"
            "/castle leaderboard — Top solo clears",
            parse_mode="HTML",
        )
        return
    party = get_castle_party(run.get("party_id")) if run.get("party_id") else None
    await update.effective_message.reply_text(
        _render_run(run, player, party), parse_mode="HTML", reply_markup=_keyboard(run)
    )


async def _start_floor(run, player, party):
    floor = int(run.get("floor", 1))
    members = _party_players(party) if party else [player]
    enemy = _enemy_for(player, floor, members)
    hp_map = run.get("player_hp_by_user") or {
        str(p["user_id"]): int(p.get("hp", p.get("max_hp", 100))) for p in members
    }
    save_castle_run(run["run_id"], {
        "current_enemy": enemy, "player_hp_by_user": hp_map,
        "room_id": f"floor_{floor}", "floor": floor,
        "checkpoint_floor": ((floor - 1) // 10) * 10 + 1,
    })


def _pick_equipment(user_id, floor, player, enemy):
    catalog = list(col("castle_item_catalog").find({
        "min_floor": {"$lte": int(floor)},
        "min_level": {"$lte": _level(player)},
        "faction": {"$in": ["any", str(player.get("faction", "")).lower()]},
    }))
    if not catalog:
        return None
    # Reward quality is gated by floor milestones and weighted rarity.
    bands = [
        (1, 10, {"common", "uncommon"}), (11, 20, {"uncommon", "rare"}),
        (21, 30, {"rare"}), (31, 40, {"rare", "epic"}),
        (41, 50, {"epic"}), (51, 60, {"epic", "legendary"}),
        (61, 80, {"legendary"}), (81, 99, {"legendary", "mythic"}),
        (100, 100, {"mythic"}),
    ]
    allowed = next((rarities for low, high, rarities in bands if low <= floor <= high), {"common"})
    candidates = [i for i in catalog if i.get("rarity") in allowed]
    if not candidates:
        return None
    weights = [RARITY_WEIGHT.get(i.get("rarity"), 1) for i in candidates]
    return random.choices(candidates, weights=weights, k=1)[0]


async def _complete_enemy(run, player, party):
    floor = int(run.get("floor", 1))
    enemy = run.get("current_enemy") or {}
    members = _party_players(party) if party else [player]
    recipients = members if party else [player]
    rewards = []
    for member in recipients:
        uid = int(member["user_id"])
        # Demon progression is faction-only; ordinary XP and Yen are untouched.
        if str(member.get("faction", "")).lower() == "demon":
            add_demon_xp(uid, 20 + floor * 2 + (50 if enemy.get("boss") else 0))
        item = _pick_equipment(uid, floor, member, enemy)
        # Equipment is rare on ordinary floors; every tenth-floor boss has a drop.
        chance = 1.0 if enemy.get("boss") else 0.08
        if item and random.random() < chance:
            granted = grant_castle_equipment(
                uid, item["item_id"], f"{run['run_id']}:{floor}:{uid}",
                floor, enemy.get("name")
            )
            if granted:
                rewards.append(f"{member.get('name', 'Player')}: {granted['name']} ({granted['rarity']})")
    if floor == MAX_FLOOR:
        for member in recipients:
            record_castle_clear(member["user_id"], floor, run.get("mode", "solo"))
        save_castle_run(run["run_id"], {"status": "completed", "current_enemy": enemy})
        if party:
            col("castle_parties").update_one(
                {"party_id": party["party_id"]}, {"$set": {"status": "completed"}}
            )
        return "🏆 <b>INFINITY CASTLE CLEARED!</b> Muzan has fallen.\n" + ("\n".join(rewards) if rewards else "No equipment drop this time.")
    save_castle_run(run["run_id"], {"current_enemy": dict(enemy, hp=0), "room_id": "cleared"})
    message = f"✅ Floor {floor} cleared!"
    if floor in BOSS_FLOORS:
        message += f" Checkpoint reached.\n"
    if rewards:
        message += "\n🎁 Equipment earned:\n" + "\n".join(rewards)
    return message + "\nContinue to the next floor when ready."


async def castle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)
    if not player:
        await query.edit_message_text("Create your character first with /start.")
        return
    run = _find_run(user_id)
    if not run:
        await query.edit_message_text("No active Castle run. Use /castle solo or /castle squad.")
        return
    party = get_castle_party(run.get("party_id")) if run.get("party_id") else None
    members = party.get("member_ids", []) if party else [run["user_id"]]
    if user_id not in members:
        await query.edit_message_text("You are not a member of this Castle run.")
        return
    action = query.data.split(":", 1)[1]
    if action == "status":
        await query.edit_message_text(
            _render_run(run, player, party), parse_mode="HTML", reply_markup=_keyboard(run)
        )
        return
    if action == "retreat":
        save_castle_run(run["run_id"], {"status": "retreated"})
        if party:
            col("castle_parties").update_one(
                {"party_id": party["party_id"]}, {"$set": {"status": "open"}}
            )
        await query.edit_message_text("🏃 You retreated. Your Castle run has ended. Use /castle to begin again.")
        return
    if action == "next":
        enemy = run.get("current_enemy") or {}
        if int(enemy.get("hp", 1)) > 0:
            await query.answer("Defeat the current enemy first.", show_alert=True)
            return
        floor = int(run.get("floor", 1)) + 1
        save_castle_run(run["run_id"], {"floor": floor})
        await _start_floor(run, player, party)
        run = _find_run(user_id)
        await query.edit_message_text(
            _render_run(run, player, party, f"⚔️ Floor {floor}: a new enemy appears!"),
            parse_mode="HTML", reply_markup=_keyboard(run)
        )
        return
    if action != "attack":
        return

    enemy = run.get("current_enemy") or {}
    if int(enemy.get("hp", 0)) <= 0:
        await query.answer("This floor is already cleared.", show_alert=True)
        return
    hp_map = run.get("player_hp_by_user") or {str(user_id): int(player.get("hp", 1))}
    current_hp = int(hp_map.get(str(user_id), player.get("hp", 1)))
    if current_hp <= 0:
        await query.answer("You are defeated. Another squad member must finish this enemy.", show_alert=True)
        return
    player_atk = max(1, int(player.get("atk", player.get("attack", 10)) or 10))
    weapon_bonus = 0
    if player.get("castle_equipped_weapon"):
        weapon = col("castle_equipment").find_one({
            "user_id": user_id, "name": player["castle_equipped_weapon"], "equipped": True
        })
        if weapon:
            weapon_bonus = int(weapon.get("stats", {}).get("atk_bonus", 0))
    damage = max(1, player_atk + weapon_bonus + random.randint(0, max(2, player_atk // 3)))
    enemy["hp"] = max(0, int(enemy["hp"]) - damage)
    if enemy["hp"] <= 0:
        save_castle_run(run["run_id"], {"current_enemy": enemy})
        result = await _complete_enemy(run, player, party)
        run = col("castle_runs").find_one({"run_id": run["run_id"]}) or run
        run.pop("_id", None)
        if run.get("status") == "completed":
            await query.edit_message_text(result, parse_mode="HTML")
        else:
            run["current_enemy"] = dict(enemy, hp=0)
            await query.edit_message_text(
                _render_run(run, player, party, f"⚔️ You dealt {damage:,} damage.\n{result}"),
                parse_mode="HTML", reply_markup=_keyboard(run)
            )
        return

    armor_bonus = 0
    if player.get("castle_equipped_armor"):
        armor = col("castle_equipment").find_one({
            "user_id": user_id, "name": player["castle_equipped_armor"], "equipped": True
        })
        if armor:
            armor_bonus = int(armor.get("stats", {}).get("def_bonus", 0))
    enemy_damage = max(1, int(enemy.get("atk", 5)) - (int(player.get("def_stat", player.get("defense", 0)) or 0) + armor_bonus) // 3)
    current_hp = max(0, current_hp - enemy_damage)
    hp_map[str(user_id)] = current_hp
    save_castle_run(run["run_id"], {
        "current_enemy": enemy, "player_hp_by_user": hp_map,
    })
    update_player(user_id, hp=current_hp)
    run["current_enemy"] = enemy
    run["player_hp_by_user"] = hp_map
    notice = f"⚔️ You dealt {damage:,} damage. Enemy counterattacked for {enemy_damage:,}."
    if current_hp <= 0:
        notice += "\n💀 You were defeated. A squad member can continue the fight."
        if not party:
            save_castle_run(run["run_id"], {"status": "defeated"})
            notice += "\nYour solo run has ended."
    await query.edit_message_text(
        _render_run(run, player, party, notice),
        parse_mode="HTML", reply_markup=_keyboard(run)
    )


async def demonlevel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player = get_player(update.effective_user.id)
    if not player:
        await update.effective_message.reply_text("Create your character first with /start.")
        return
    if str(player.get("faction", "")).lower() != "demon":
        await update.effective_message.reply_text("Demon Level is available only to Demon-faction players.")
        return
    await update.effective_message.reply_text(
        "🩸 <b>DEMON PROGRESSION</b>\n"
        f"Demon Level: <b>{int(player.get('demon_level', 1))}</b>\n"
        f"Demon XP: <b>{int(player.get('demon_xp', 0)):,}</b>\n"
        "Earn Demon XP by defeating Infinity Castle enemies and bosses. "
        "This progression is separate from your normal player level.",
        parse_mode="HTML",
    )
