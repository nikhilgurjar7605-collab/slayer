"""Infinity Castle Telegram commands and persistent turn-based encounters."""
import random
import re
from datetime import datetime
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import get_player, update_player, col
from utils.helpers import get_level
from config import SHOP_ITEMS
from handlers.skilltree import get_player_skills, get_active_skill_bonuses
from utils.castle_database import (
    create_castle_run, get_active_castle_run, save_castle_run, apply_castle_enemy_damage,
    calculate_player_power, calculate_difficulty, create_castle_party,
    get_castle_party, add_castle_party_member, add_demon_xp,
    grant_castle_equipment, record_castle_clear, record_castle_progress,
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
    rank = "Upper Moon" if floor >= 70 else ("Lower Moon" if floor >= 30 else ("Elite" if floor >= 10 else "Demon"))
    rank_abilities = {
        "Demon": "Savage Claws",
        "Elite": "Blood Art Strike",
        "Lower Moon": "Crimson Blood Art",
        "Upper Moon": "Overwhelming Blood Technique",
    }
    return {
        "name": name, "level": level, "demon_level": level, "hp": hp, "max_hp": hp,
        "atk": atk, "boss": boss, "difficulty": difficulty["tier"],
        "rank": rank, "ability": "Muzan's Final Judgment" if floor == 100 else (rank_abilities.get(rank) if boss else rank_abilities.get(rank)),
    }


def _bar(value, maximum, width=12):
    maximum = max(1, int(maximum or 1))
    value = max(0, min(maximum, int(value or 0)))
    filled = int(round((value / maximum) * width))
    return "█" * filled + "░" * (width - filled)


def _keyboard(run, is_party_member=True):
    rows = []
    enemy = run.get("current_enemy") or {}
    if enemy and int(enemy.get("hp", 0)) > 0:
        rows.append([
            InlineKeyboardButton("⚔️ Attack", callback_data="castle:attack"),
            InlineKeyboardButton("⚡ Technique · 25 STA", callback_data="castle:technique"),
        ])
        rows.append([
            InlineKeyboardButton("🛡️ Guard", callback_data="castle:guard"),
            InlineKeyboardButton("🏃 Retreat", callback_data="castle:retreat"),
        ])
    else:
        rows.append([InlineKeyboardButton("➡️ Continue to Next Floor", callback_data="castle:next")])
    rows.append([InlineKeyboardButton("📊 Battle Status", callback_data="castle:status")])
    return InlineKeyboardMarkup(rows)


def _lobby_keyboard():
    """Main Castle hub: every major mode is reachable without memorising commands."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Enter Solo", callback_data="castle:solo"),
         InlineKeyboardButton("👥 Create Squad", callback_data="castle:squad")],
        [InlineKeyboardButton("🎒 Equipment", callback_data="castle:equipment"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="castle:leaderboard")],
    ])


def _render_run(run, player, party=None, notice=None):
    floor = int(run.get("floor", 1))
    enemy = run.get("current_enemy") or {}
    members = party.get("member_ids", []) if party else [run.get("user_id")]
    hp_map = run.get("player_hp_by_user", {})
    player_hp = int(hp_map.get(str(player.get("user_id")), player.get("hp", 1)))
    player_max_hp = int(player.get("max_hp", max(1, player_hp)))
    player_sta = int(player.get("sta", 0))
    player_max_sta = int(player.get("max_sta", max(1, player_sta)))
    lines = [
        "🏯 <b>INFINITY CASTLE</b>",
        f"Floor <b>{floor}/{MAX_FLOOR}</b>  <code>{_bar(floor, MAX_FLOOR, 16)}</code>",
        f"Mode: <b>{run.get('mode', 'solo').title()}</b>  •  Squad: <b>{len(members)}/4</b>",
        f"Level: <b>{_level(player)}</b>  •  Combat Power: <b>{calculate_player_power(player):,}</b>",
        "",
        f"❤️ You: <b>{max(0, player_hp):,}/{player_max_hp:,}</b>  <code>{_bar(player_hp, player_max_hp)}</code>",
        f"⚡ Stamina: <b>{player_sta:,}/{player_max_sta:,}</b>  <code>{_bar(player_sta, player_max_sta)}</code>",
    ]
    if notice:
        lines += ["", notice]
    if enemy and enemy.get("room_type"):
        lines += [
            "", "━━━━━━━━━━━━━━━━━━━━",
            f"🧭 <b>{escape(str(enemy.get('room_type')).title())} Chamber</b>",
            escape(str(run.get("room_notice", "The room is clear. Move to the next floor."))),
            "━━━━━━━━━━━━━━━━━━━━",
        ]
    elif enemy:
        enemy_hp = max(0, int(enemy.get("hp", 0)))
        enemy_max_hp = max(1, int(enemy.get("max_hp", 1)))
        lines += [
            "", "━━━━━━━━━━━━━━━━━━━━",
            f"{'☠️ FINAL BOSS' if floor == MAX_FLOOR else ('☠️ BOSS' if enemy.get('boss') else '👹 ENEMY')}",
            f"<b>{escape(str(enemy.get('name')))}</b>",
            f"Rank: <b>{escape(str(enemy.get('rank')))}</b>  •  Demon Level: <b>{enemy.get('demon_level', enemy.get('level'))}</b>",
            f"Difficulty: <b>{escape(str(enemy.get('difficulty')))}</b>",
            f"Blood Art: <b>{escape(str(enemy.get('ability', 'Basic Attack')))}</b>",
            f"Enemy HP: <b>{enemy_hp:,}/{enemy_max_hp:,}</b>",
            f"<code>{_bar(enemy_hp, enemy_max_hp, 16)}</code>",
            "━━━━━━━━━━━━━━━━━━━━",
            "<b>Squad Status</b>",
        ]
        for uid in members:
            member = get_player(int(uid))
            if member:
                hp = max(0, int(hp_map.get(str(uid), member.get("hp", 1))))
                maximum = max(1, int(member.get("max_hp", 1)))
                lines.append(
                    f"• {escape(str(member.get('name', 'Slayer')))}  "
                    f"{hp:,}/{maximum:,} HP  <code>{_bar(hp, maximum, 8)}</code>"
                )
    if floor == MAX_FLOOR and enemy.get("boss"):
        lines.append("\n⚠️ <b>FINAL BATTLE</b> — defeat Muzan to clear the Castle.")
    return "\n".join(lines)


async def castle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.effective_message.reply_text("Create your character first with /start.")
        return
    args = context.args or []
    action = args[0].lower() if args else "status"

    if action == "resume":
        previous = col("castle_runs").find_one(
            {"user_id": user_id, "status": "defeated"},
            sort=[("updated_at", -1)]
        )
        if not previous:
            await update.effective_message.reply_text("No defeated Castle run is available to resume.")
            return
        party = get_castle_party(previous.get("party_id")) if previous.get("party_id") else None
        if party and int(party.get("leader_id", 0)) != user_id:
            await update.effective_message.reply_text("Only the squad leader can resume this run.")
            return
        floor = max(1, int(previous.get("checkpoint_floor", 1)))
        members = _party_players(party) if party else [player]
        hp_map = {}
        for member in members:
            uid = int(member["user_id"])
            restored_hp = max(1, int(member.get("max_hp", 100) * 0.50))
            hp_map[str(uid)] = restored_hp
            update_player(uid, hp=restored_hp)
        col("castle_runs").update_one(
            {"run_id": previous["run_id"], "status": "defeated"},
            {"$set": {
                "status": "active", "floor": floor,
                "room_id": f"floor_{floor}", "player_hp_by_user": hp_map,
                "updated_at": datetime.utcnow(),
            }}
        )
        if party:
            col("castle_parties").update_one(
                {"party_id": party["party_id"]},
                {"$set": {"status": "running"}}
            )
        run = col("castle_runs").find_one({"run_id": previous["run_id"]})
        run.pop("_id", None)
        await _start_floor(run, player, party)
        run = _find_run(user_id)
        await update.effective_message.reply_text(
            _render_run(run, player, party, f"🔁 Resumed from checkpoint floor {floor}. Squad HP restored to 50%."),
            parse_mode="HTML", reply_markup=_keyboard(run)
        )
        return

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
        if _find_run(user_id):
            await update.effective_message.reply_text("Finish or retreat from your active Castle run before creating a squad.")
            return
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
        if _find_run(user_id):
            await update.effective_message.reply_text("You already have an active Castle run. Use /castle status.")
            return
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
            "user_id": user_id, "name": {"$regex": f"^{re.escape(item_name)}$", "$options": "i"}
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
            f"✅ Equipped <b>{escape(str(item['name']))}</b> in your {slot} slot.",
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
                f"• <b>{escape(str(item.get('name')))}</b> [{escape(str(item.get('rarity', 'Common').title()))}] "
                f"— {item.get('slot', item.get('item_type'))} — Floor {item.get('source_floor')}"
            )
        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    if action == "leaderboard":
        mode = "squad" if len(args) > 1 and args[1].lower() == "squad" else "solo"
        rows = list(col("castle_leaderboards").find({"mode": mode}).sort("highest_floor", -1).limit(10))
        lines = [f"🏆 <b>CASTLE {mode.upper()} LEADERBOARD</b>"]
        for i, row in enumerate(rows, 1):
            member = get_player(int(row["user_id"])) or {}
            lines.append(f"{i}. {escape(str(member.get('name', 'Unknown')))} — Floor {row.get('highest_floor', 0)}")
        if len(lines) == 1:
            lines.append("No clears recorded yet.")
        await update.effective_message.reply_text("\n".join(lines), parse_mode="HTML")
        return

    run = _find_run(user_id)
    if not run:
        await update.effective_message.reply_text(
            "🏯 <b>INFINITY CASTLE</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "100 floors. One climb. No second chances.\n\n"
            "Fight through shifting chambers, defeat the Twelve Kizuki, "
            "collect Castle equipment and reach Muzan on Floor 100.\n\n"
            "<b>Choose your path:</b>\n"
            "⚔️ Solo — fight alone\n"
            "👥 Squad — team up with up to 3 other slayers\n\n"
            "Use /castle resume to continue from your last checkpoint.",
            parse_mode="HTML", reply_markup=_lobby_keyboard(),
        )
        return
    party = get_castle_party(run.get("party_id")) if run.get("party_id") else None
    await update.effective_message.reply_text(
        _render_run(run, player, party), parse_mode="HTML", reply_markup=_keyboard(run)
    )


async def _start_floor(run, player, party):
    floor = int(run.get("floor", 1))
    members = _party_players(party) if party else [player]
    hp_map = run.get("player_hp_by_user") or {
        str(p["user_id"]): int(p.get("hp", p.get("max_hp", 100))) for p in members
    }
    room_type = "combat"
    room_notice = "An enemy blocks your path."
    if floor % 10 != 0 and floor % 10 == 5:
        room_type = "treasure"
        room_notice = "A hidden chamber contains Castle equipment."
        for member in members:
            item = _pick_equipment(int(member["user_id"]), floor, member, {"name": "Treasure Chamber"})
            if item:
                granted = grant_castle_equipment(
                    int(member["user_id"]), item["item_id"],
                    f"{run['run_id']}:{floor}:{member['user_id']}",
                    floor, "Treasure Chamber"
                )
                if granted:
                    room_notice += f"\n{member.get('name', 'Player')} found {granted['name']} ({granted['rarity']})."
    elif floor % 10 != 0 and floor % 10 == 7:
        room_type = "trap"
        room_notice = "The floor shifts and a hidden trap springs!"
        for member in members:
            uid = int(member["user_id"])
            trap_reduction = 0
            accessory = col("castle_equipment").find_one({
                "user_id": uid, "equipped": True,
                "passive.type": "trap_avoidance"
            })
            if accessory:
                trap_reduction = float(accessory.get("passive", {}).get("value", 0))
            damage = max(1, int(member.get("max_hp", 100) * 0.10 * (1 - trap_reduction)))
            hp_map[str(uid)] = max(1, int(hp_map.get(str(uid), member.get("hp", 1))) - damage)
            update_player(uid, hp=hp_map[str(uid)])
            room_notice += f"\n{member.get('name', 'Player')} lost {damage} HP."
    elif floor % 10 != 0 and floor % 10 == 9:
        room_type = "rest"
        room_notice = "A quiet chamber restores the squad before the next battle."
        for member in members:
            uid = int(member["user_id"])
            max_hp = int(member.get("max_hp", 100))
            restored = max(1, int(max_hp * 0.20))
            hp_map[str(uid)] = min(max_hp, int(hp_map.get(str(uid), member.get("hp", 1))) + restored)
            update_player(uid, hp=hp_map[str(uid)])
            room_notice += f"\n{member.get('name', 'Player')} recovered HP."
    if room_type == "combat":
        enemy = _enemy_for(player, floor, members)
    else:
        enemy = {
            "name": f"{room_type.title()} Chamber", "level": 0,
            "demon_level": 0, "hp": 0, "max_hp": 0, "atk": 0,
            "boss": False, "rank": "Room", "difficulty": "Event",
            "room_type": room_type,
        }
    save_castle_run(run["run_id"], {
        "current_enemy": enemy, "player_hp_by_user": hp_map,
        "room_id": f"floor_{floor}", "floor": floor,
        "room_type": room_type, "room_notice": room_notice,
        "checkpoint_floor": ((floor - 1) // 10) * 10 + 1,
    })
    for member in members:
        record_castle_progress(member["user_id"], floor, run.get("mode", "solo"))


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
                rewards.append(f"{escape(str(member.get('name', 'Player')))}: {escape(str(granted['name']))} ({escape(str(granted['rarity']))})")
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
    action = query.data.split(":", 1)[1]
    run = _find_run(user_id)

    # Lobby actions must work even when the player has no active run.
    if action == "menu":
        await query.edit_message_text(
            "🏯 <b>INFINITY CASTLE</b>\nChoose a mode to begin your climb.",
            parse_mode="HTML", reply_markup=_lobby_keyboard()
        )
        return
    if action == "solo":
        if run:
            await query.message.reply_text("You already have an active run. Use /castle status.")
            return
        run = create_castle_run(user_id, "solo")
        await _start_floor(run, player, None)
        run = _find_run(user_id)
        await query.edit_message_text(
            _render_run(run, player), parse_mode="HTML", reply_markup=_keyboard(run)
        )
        return
    if action == "squad":
        if run:
            await query.message.reply_text("Finish or retreat from your active run first.")
            return
        party = create_castle_party(user_id)
        await query.edit_message_text(
            "👥 <b>Squad created</b>\n"
            f"Party code: <code>{escape(str(party['party_id']))}</code>\n\n"
            "Share this code with up to 3 players:\n"
            f"<code>/castle join {escape(str(party['party_id']))}</code>\n\n"
            "When everyone has joined, start the run with /castle start.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↻ Castle Hub", callback_data="castle:menu")
            ]])
        )
        return
    if action == "equipment":
        owned = list(col("castle_equipment").find({"user_id": user_id}).sort("obtained_at", -1).limit(30))
        lines = ["🎒 <b>YOUR CASTLE ARMOURY</b>", "━━━━━━━━━━━━━━━━━━━━"]
        if not owned:
            lines.append("Your armoury is empty. Defeat enemies and bosses to earn gear.")
        else:
            for item in owned:
                slot = item.get("slot", item.get("item_type", "gear"))
                equipped = "  <b>✓ EQUIPPED</b>" if item.get("equipped") else ""
                lines.append(
                    f"• <b>{escape(str(item.get('name', 'Unknown gear')))}</b> "
                    f"[{escape(str(item.get('rarity', 'common')).title())}] — "
                    f"{escape(str(slot).title())}{equipped}"
                )
                stats = item.get("stats", {})
                bonuses = [f"+{int(v)} {k.replace('_bonus', '').upper()}" for k, v in stats.items() if v]
                if bonuses:
                    lines.append("  " + " · ".join(bonuses))
            lines.append("\nEquip an item with /castle equip ITEM NAME.")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↻ Castle Hub", callback_data="castle:menu")
            ]])
        )
        return
    if action == "leaderboard":
        rows = list(col("castle_leaderboards").find({"mode": "solo"}).sort("highest_floor", -1).limit(10))
        lines = ["🏆 <b>INFINITY CASTLE — SOLO RANKINGS</b>", "━━━━━━━━━━━━━━━━━━━━"]
        if not rows:
            lines.append("No explorers have made a recorded climb yet.")
        for i, row in enumerate(rows, 1):
            member = get_player(int(row["user_id"])) or {}
            lines.append(f"{i}. {escape(str(member.get('name', 'Unknown')))} — Floor {int(row.get('highest_floor', 0))}")
        await query.edit_message_text(
            "\n".join(lines), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↻ Castle Hub", callback_data="castle:menu")
            ]])
        )
        return
    if not run:
        await query.edit_message_text(
            "No active Castle run. Choose a mode to begin.",
            reply_markup=_lobby_keyboard()
        )
        return
    party = get_castle_party(run.get("party_id")) if run.get("party_id") else None
    members = party.get("member_ids", []) if party else [run["user_id"]]
    if user_id not in members:
        await query.edit_message_text("You are not a member of this Castle run.")
        return
    if action == "status":
        await query.edit_message_text(
            _render_run(run, player, party), parse_mode="HTML", reply_markup=_keyboard(run)
        )
        return
    if action == "retreat":
        if party and user_id != int(party.get("leader_id", 0)):
            await query.message.reply_text("Only the squad leader can retreat the whole squad.")
            return
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
            await query.message.reply_text("Defeat the current enemy first.")
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
    if action not in ("attack", "technique", "guard"):
        return

    enemy = run.get("current_enemy") or {}
    if int(enemy.get("hp", 0)) <= 0:
        await query.message.reply_text("This floor is already cleared. Move to the next floor.")
        return
    hp_map = run.get("player_hp_by_user") or {str(user_id): int(player.get("hp", 1))}
    current_hp = int(hp_map.get(str(user_id), player.get("hp", 1)))
    if current_hp <= 0:
        await query.message.reply_text("You are defeated. Another squad member must finish this enemy.")
        return

    is_technique = action == "technique"
    is_guard = action == "guard"
    current_sta = max(0, int(player.get("sta", 0) or 0))
    max_sta = max(0, int(player.get("max_sta", current_sta) or current_sta))
    technique_cost = 25
    if is_technique and current_sta < technique_cost:
        await query.message.reply_text(
            f"⚡ Not enough stamina. You need {technique_cost} STA; current stamina: {current_sta}."
        )
        return
    if is_technique:
        current_sta -= technique_cost
        player["sta"] = current_sta
        update_player(user_id, sta=current_sta)
    elif is_guard:
        current_sta = min(max_sta, current_sta + 12)
        player["sta"] = current_sta
        update_player(user_id, sta=current_sta)

    skill_bonuses = get_active_skill_bonuses(get_player_skills(user_id), user_id=user_id)
    player_atk = max(1, int(player.get("str_stat", player.get("atk", player.get("attack", 10))) or 10))
    player_atk = int(player_atk * (1 + float(skill_bonuses.get("atk_pct", 0) or 0)))
    for base_weapon in SHOP_ITEMS.get("swords", []):
        if base_weapon.get("name") == player.get("equipped_sword"):
            player_atk += int(base_weapon.get("atk_bonus", 0))
            break
    weapon_bonus = 0
    weapon_multiplier = 1.0
    weapon = None
    if player.get("castle_equipped_weapon"):
        weapon = col("castle_equipment").find_one({
            "user_id": user_id, "name": player["castle_equipped_weapon"], "equipped": True
        })
        if weapon:
            weapon_bonus = int(weapon.get("stats", {}).get("atk_bonus", 0))
            passive = weapon.get("passive", {})
            if passive.get("type") == "demon_damage":
                weapon_multiplier += float(passive.get("value", 0))
            elif passive.get("type") == "elite_damage" and enemy.get("rank") in ("Elite", "Lower Moon", "Upper Moon"):
                weapon_multiplier += float(passive.get("value", 0))
    accessory_bonus = 0
    accessory_multiplier = 1.0
    critical = random.random() < float(skill_bonuses.get("crit_bonus", 0) or 0)
    accessory = None
    if player.get("castle_equipped_accessory"):
        accessory = col("castle_equipment").find_one({
            "user_id": user_id, "name": player["castle_equipped_accessory"], "equipped": True
        })
        if accessory:
            accessory_bonus = int(accessory.get("stats", {}).get("atk_bonus", 0))
            passive = accessory.get("passive", {})
            if passive.get("type") == "combat_damage":
                accessory_multiplier += float(passive.get("value", 0))
            elif passive.get("type") == "demon_art_power" and str(player.get("faction", "")).lower() == "demon":
                accessory_multiplier += float(passive.get("value", 0))
            elif passive.get("type") == "critical_chance" and random.random() < float(passive.get("value", 0)):
                critical = True
    demon_bonus = 0
    if str(player.get("faction", "")).lower() == "demon":
        demon_bonus = int(player_atk * float(player.get("demon_art_bonus", 0) or 0))
    technique_multiplier = 1.85 if is_technique else 1.0
    damage = int((player_atk + weapon_bonus + accessory_bonus + demon_bonus + random.randint(0, max(2, player_atk // 3))) * weapon_multiplier * accessory_multiplier * technique_multiplier * (1.5 if critical else 1.0))
    damage = max(1, damage)
    expected_enemy_hp = int(enemy["hp"])
    if not apply_castle_enemy_damage(run["run_id"], expected_enemy_hp, damage):
        await query.message.reply_text("Another squad action updated this enemy first. Tap Status and try again.")
        return
    run = col("castle_runs").find_one({"run_id": run["run_id"]}) or run
    run.pop("_id", None)
    enemy = run.get("current_enemy") or {}
    if int(enemy.get("hp", 0)) <= 0:
        result = await _complete_enemy(run, player, party)
        run = col("castle_runs").find_one({"run_id": run["run_id"]}) or run
        run.pop("_id", None)
        if run.get("status") == "completed":
            await query.edit_message_text(
                result, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↻ Castle Hub", callback_data="castle:menu")
                ]])
            )
        else:
            await query.edit_message_text(
                _render_run(run, player, party, f"⚔️ You dealt {damage:,} damage.\n{result}"),
                parse_mode="HTML", reply_markup=_keyboard(run)
            )
        return

    armor_bonus = 0
    for base_armor in SHOP_ITEMS.get("armor", []):
        if base_armor.get("name") == player.get("equipped_armor"):
            armor_bonus += int(base_armor.get("def_bonus", 0))
            break
    armor = None
    if player.get("castle_equipped_armor"):
        armor = col("castle_equipment").find_one({
            "user_id": user_id, "name": player["castle_equipped_armor"], "equipped": True
        })
        if armor:
            armor_bonus += int(armor.get("stats", {}).get("def_bonus", 0))
    reduction = float(skill_bonuses.get("dmg_reduce", 0) or 0)
    if is_guard:
        reduction = max(reduction, 0.55)
    for gear in (armor, accessory):
        if gear:
            passive = gear.get("passive", {})
            if passive.get("type") == "damage_reduction":
                reduction += float(passive.get("value", 0))
    rank_multiplier = {"Elite": 1.05, "Lower Moon": 1.10, "Upper Moon": 1.20}.get(enemy.get("rank"), 1.0)
    if enemy.get("boss"):
        rank_multiplier += 0.10
    enemy_damage = max(1, int((int(enemy.get("atk", 5)) - (int(player.get("def_stat", player.get("defense", 0)) or 0) + armor_bonus) // 3) * rank_multiplier * max(0.25, 1 - max(0, min(0.60, reduction))))
    current_hp = max(0, current_hp - enemy_damage)
    regen = 0
    if str(player.get("faction", "")).lower() == "demon" and current_hp > 0:
        regen = min(
            max(0, int(player.get("max_hp", current_hp)) - current_hp),
            int(int(player.get("max_hp", current_hp)) * (
                float(player.get("demon_regen_bonus", 0) or 0) +
                float(skill_bonuses.get("regen_pct", 0) or 0)
            )) + int(skill_bonuses.get("regen_hp", 0) or 0)
        )
        current_hp += regen
    hp_map[str(user_id)] = current_hp
    save_castle_run(run["run_id"], {
        "current_enemy": enemy, "player_hp_by_user": hp_map,
    })
    update_player(user_id, hp=current_hp)
    run["current_enemy"] = enemy
    run["player_hp_by_user"] = hp_map
    action_label = (
        f"⚡ {escape(str(player.get('style') or 'Special Technique'))}"
        if is_technique else ("🛡️ Guard stance" if is_guard else "⚔️ Basic attack")
    )
    notice = f"{action_label}: {damage:,} damage. Enemy counterattacked for {enemy_damage:,}."
    if is_technique:
        notice += f" Spent {technique_cost} STA."
    if is_guard:
        notice += " Incoming damage reduced; recovered 12 STA."
    if regen:
        notice += f" Demon regeneration restored {regen:,} HP."
    if current_hp <= 0:
        notice += "\n💀 You were defeated. A squad member can continue the fight."
        if not party:
            save_castle_run(run["run_id"], {"status": "defeated"})
            notice += "\nYour solo run has ended. Use /castle resume to continue from your checkpoint."
        elif all(int(value) <= 0 for value in hp_map.values()):
            save_castle_run(run["run_id"], {"status": "defeated"})
            col("castle_parties").update_one(
                {"party_id": party["party_id"]}, {"$set": {"status": "defeated"}}
            )
            notice += "\nThe whole squad has fallen. The leader can use /castle resume."
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
        f"Unlocked abilities: <b>{escape(', '.join(player.get('demon_abilities', [])) or 'None yet')}</b>\n"
        f"Regeneration bonus: <b>{int(float(player.get('demon_regen_bonus', 0)) * 100)}%</b>\n"
        f"Demon Art bonus: <b>{int(float(player.get('demon_art_bonus', 0)) * 100)}%</b>\n"
        "Earn Demon XP by defeating Infinity Castle enemies and bosses. "
        "This progression is separate from your normal player level.",
        parse_mode="HTML",
    )
