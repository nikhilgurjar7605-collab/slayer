"""Infinity Castle Telegram commands and persistent turn-based encounters."""
import random
import re
from datetime import datetime
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
import logging
from functools import wraps

logger = logging.getLogger(__name__)

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


def _castle_guard(handler):
    """Log Castle failures and send a useful fallback instead of failing silently."""
    @wraps(handler)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await handler(update, context)
        except Exception:
            logger.exception("Infinity Castle handler failed: %s", handler.__name__)
            message = update.effective_message
            if message:
                try:
                    await message.reply_text(
                        "⚠️ Infinity Castle hit an internal error. The error has been logged; "
                        "please try again in a moment."
                    )
                except Exception:
                    logger.exception("Could not send Infinity Castle error notice")
            return None
    return wrapped


async def _safe_castle_edit(query, text, **kwargs):
    """Edit a Castle screen, falling back to a new message if Telegram lost the old one."""
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        reason = str(exc).lower()
        if "message is not modified" in reason:
            return
        if any(token in reason for token in (
            "message to edit not found", "message can't be edited",
            "message_id_invalid", "message to edit is not found",
        )):
            if query.message:
                await query.message.reply_text(text, **kwargs)
                return
        raise

RARITY_WEIGHT = {
    "common": 45, "uncommon": 30, "rare": 16,
    "epic": 7, "legendary": 1.7, "mythic": 0.3,
}


def _level(player):
    return max(1, int(get_level(int(player.get("xp", 0) or 0))))


def _party_players(party):
    if not party:
        return []
    # Always include the leader, including parties created by older bot versions
    # where leader_id was not copied into member_ids.
    member_ids = list(dict.fromkeys(
        [int(party.get("leader_id", 0))] +
        [int(uid) for uid in party.get("member_ids", [])]
    ))
    # Read the latest player documents directly so enemy scaling uses current
    # stats/equipment rather than a possibly stale in-memory player cache.
    players = []
    for uid in member_ids:
        if not uid:
            continue
        member = col("players").find_one({"user_id": uid})
        if member:
            member.pop("_id", None)
            players.append(member)
    return players


CASTLE_RECOVERY_ITEMS = {
    "bandage": {"name": "Field Bandage", "price": 120, "effect": "hp", "amount": 0.35},
    "medkit": {"name": "Wisteria Medkit", "price": 300, "effect": "hp", "amount": 0.80},
    "tonic": {"name": "Stamina Tonic", "price": 100, "effect": "sta", "amount": 0.60},
}


def _apply_timed_recovery(user_id, player):
    """Restore 10% HP and stamina for every completed 30-minute rest interval."""
    now = datetime.utcnow()
    last = player.get("castle_last_recovery_at")
    if not isinstance(last, datetime):
        update_player(user_id, castle_last_recovery_at=now)
        player["castle_last_recovery_at"] = now
        return False
    intervals = int(max(0, (now - last).total_seconds()) // 1800)
    if intervals <= 0:
        return False
    max_hp = max(1, int(player.get("max_hp", player.get("hp", 1)) or 1))
    max_sta = max(1, int(player.get("max_sta", player.get("sta", 1)) or 1))
    hp_gain = min(max_hp - int(player.get("hp", 0) or 0), max(1, int(max_hp * 0.10)) * intervals)
    sta_gain = min(max_sta - int(player.get("sta", 0) or 0), max(1, int(max_sta * 0.10)) * intervals)
    update_player(
        user_id,
        hp=min(max_hp, int(player.get("hp", 0) or 0) + max(0, hp_gain)),
        sta=min(max_sta, int(player.get("sta", 0) or 0) + max(0, sta_gain)),
        castle_last_recovery_at=last.replace() if intervals == 0 else last + __import__("datetime").timedelta(seconds=1800 * intervals),
    )
    player["hp"] = min(max_hp, int(player.get("hp", 0) or 0) + max(0, hp_gain))
    player["sta"] = min(max_sta, int(player.get("sta", 0) or 0) + max(0, sta_gain))
    if hp_gain > 0:
        active_run = _find_run(user_id)
        if active_run:
            hp_map = active_run.get("player_hp_by_user", {})
            hp_map[str(user_id)] = player["hp"]
            save_castle_run(active_run["run_id"], {"player_hp_by_user": hp_map})
    return bool(hp_gain or sta_gain)


def _castle_shop_text(user_id):
    player = get_player(user_id) or {}
    supplies = {
        row.get("item_id"): int(row.get("quantity", 0))
        for row in col("castle_supplies").find({"user_id": int(user_id)})
    }
    lines = [
        "🏪 <b>INFINITY CASTLE — RECOVERY SHOP</b>",
        f"🪙 Castle Coins: <b>{int(player.get('castle_coins', 0) or 0):,}</b>",
        "",
    ]
    for key, item in CASTLE_RECOVERY_ITEMS.items():
        lines.append(
            f"• <b>{item['name']}</b> — {item['price']} coins"
            f"\n  Owned: <b>{supplies.get(key, 0)}</b>"
        )
    lines.append("\nBuy supplies, then use them when your team needs recovery.")
    return "\n".join(lines), supplies


def _castle_shop_keyboard(supplies):
    rows = [
        [InlineKeyboardButton("🩹 Buy Bandage · 120", callback_data="castle:buy_bandage"),
         InlineKeyboardButton("🧪 Buy Medkit · 300", callback_data="castle:buy_medkit")],
        [InlineKeyboardButton("⚡ Buy Tonic · 100", callback_data="castle:buy_tonic")],
    ]
    use = []
    for key, label in (("bandage", "Use Bandage"), ("medkit", "Use Medkit"), ("tonic", "Use Tonic")):
        if supplies.get(key, 0) > 0:
            use.append(InlineKeyboardButton(f"➕ {label}", callback_data=f"castle:use_{key}"))
    if use:
        rows.append(use)
    rows.append([InlineKeyboardButton("↻ Refresh Shop", callback_data="castle:shop"),
                 InlineKeyboardButton("🏯 Castle Hub", callback_data="castle:menu")])
    return InlineKeyboardMarkup(rows)


def _find_user_party(user_id):
    """Return the one open/running squad this player belongs to, if any."""
    user_id = int(user_id)
    party = col("castle_parties").find_one(
        {"$or": [{"member_ids": user_id}, {"leader_id": user_id}],
         "status": {"$in": ["open", "running"]}},
        sort=[("updated_at", -1)]
    )
    if party:
        party.pop("_id", None)
    return party


def _find_run(user_id):
    user_id = int(user_id)
    run = get_active_castle_run(user_id)
    if run:
        return run
    party = _find_user_party(user_id)
    if party and party.get("status") == "running":
        run = col("castle_runs").find_one(
            {"party_id": party["party_id"], "status": "active"}
        )
        if run:
            run.pop("_id", None)
    return run


def _enemy_for(player, floor, party_players):
    difficulty = calculate_difficulty(player, floor, party_players)
    level = difficulty["enemy_level"]
    floor = max(1, min(MAX_FLOOR, int(floor)))
    boss = floor in BOSS_FLOORS
    name = BOSS_NAMES.get(floor) if boss else random.choice(ENEMY_NAMES)

    # Exact floor progression requested: floor 5 = 1,000 HP, +500 per
    # floor thereafter. The hard 10,000 HP cap is reached at floor 23.
    floor_hp = floor * 200 if floor < 5 else 1000 + (floor - 5) * 500
    hp = min(10_000, floor_hp)
    if boss:
        hp = min(10_000, int(hp * 1.15))

    # Make demons a little more threatening, without returning to the old
    # excessive attack scaling. Squad size and player level still matter.
    size = max(1, len(party_players))
    base_atk = 12 + level * 1.8 + floor * 0.22
    atk = max(6, int(base_atk * (1 + 0.12 * (size - 1)) * 1.10))
    if boss:
        atk = int(atk * 1.30)

    rank = "Upper Moon" if floor >= 30 else ("Lower Moon" if floor >= 10 else ("Elite" if floor >= 5 else "Demon"))
    rank_abilities = {
        "Demon": "Savage Claws",
        "Elite": "Blood Art Strike",
        "Lower Moon": "Crimson Blood Art",
        "Upper Moon": "Overwhelming Blood Technique",
    }
    return {
        "name": name, "level": level, "demon_level": level, "hp": hp, "max_hp": hp,
        "atk": atk, "boss": boss, "difficulty": difficulty["tier"],
        "rank": rank, "ability": "Muzan's Final Judgment" if floor == 100 else rank_abilities.get(rank),
    }


def _bar(value, maximum, width=12):
    maximum = max(1, int(maximum or 1))
    value = max(0, min(maximum, int(value or 0)))
    filled = int(round((value / maximum) * width))
    return "█" * filled + "░" * (width - filled)


def _keyboard(run, is_party_member=True, user_id=None):
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
        if user_id is not None:
            supplies = {
                row.get("item_id"): int(row.get("quantity", 0))
                for row in col("castle_supplies").find({"user_id": int(user_id)})
            }
            item_buttons = []
            for key, label in (("bandage", "🩹"), ("medkit", "🧪"), ("tonic", "⚡")):
                if supplies.get(key, 0) > 0:
                    item_buttons.append(InlineKeyboardButton(
                        f"{label} {CASTLE_RECOVERY_ITEMS[key]['name']} ×{supplies[key]}",
                        callback_data=f"castle:use_{key}",
                    ))
            if item_buttons:
                rows.append(item_buttons[:2])
                if len(item_buttons) > 2:
                    rows.append(item_buttons[2:])
    else:
        rows.append([InlineKeyboardButton("➡️ Continue to Next Floor", callback_data="castle:next")])
    rows.append([
        InlineKeyboardButton("📊 Battle Status", callback_data="castle:status"),
        InlineKeyboardButton("🏪 Recovery Shop", callback_data="castle:shop"),
    ])
    return InlineKeyboardMarkup(rows)


def _lobby_keyboard():
    """Main Castle hub with direct access to squad management and recovery."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Enter Solo", callback_data="castle:solo"),
         InlineKeyboardButton("👥 Create Squad", callback_data="castle:squad")],
        [InlineKeyboardButton("👥 My Squad", callback_data="castle:my_squad"),
         InlineKeyboardButton("🏪 Recovery Shop", callback_data="castle:shop")],
        [InlineKeyboardButton("🎒 Equipment", callback_data="castle:equipment"),
         InlineKeyboardButton("🏆 Leaderboard", callback_data="castle:leaderboard")],
        [InlineKeyboardButton("🏠 Main Menu", callback_data="goto_menu")],
    ])


def _render_run(run, player, party=None, notice=None):
    """Compact Telegram battle panel with clear hierarchy and less visual noise."""
    floor = int(run.get("floor", 1))
    enemy = run.get("current_enemy") or {}
    members = party.get("member_ids", []) if party else [run.get("user_id")]
    hp_map = run.get("player_hp_by_user", {})
    player_hp = int(hp_map.get(str(player.get("user_id")), player.get("hp", 1)))
    player_max_hp = max(1, int(player.get("max_hp", max(1, player_hp))))
    player_sta = int(player.get("sta", 0))
    player_max_sta = max(1, int(player.get("max_sta", max(1, player_sta))))

    lines = [
        "🏯 <b>INFINITY CASTLE</b>  <code>EXPEDITION</code>",
        f"Floor <b>{floor}/{MAX_FLOOR}</b>  <code>{_bar(floor, MAX_FLOOR, 10)}</code>",
        f"⚔️ {run.get('mode', 'solo').title()}  ·  👥 {len(members)}/4  ·  ⭐ Lv.{_level(player)}",
        f"Power <b>{calculate_player_power(player):,}</b>",
        "",
        f"❤️ <b>{max(0, player_hp):,}/{player_max_hp:,}</b>  <code>{_bar(player_hp, player_max_hp, 10)}</code>",
        f"⚡ <b>{player_sta:,}/{player_max_sta:,}</b>  <code>{_bar(player_sta, player_max_sta, 10)}</code>",
    ]
    if notice:
        lines.extend(["", f"💬 {escape(str(notice))}"])

    if enemy and enemy.get("room_type"):
        lines.extend([
            "", "━━━━━━━━━━━━━━━━",
            f"🧭 <b>{escape(str(enemy.get('room_type')).title())} Chamber</b>",
            escape(str(run.get("room_notice", "The room is clear. Move to the next floor."))),
            "━━━━━━━━━━━━━━━━",
        ])
    elif enemy:
        enemy_hp = max(0, int(enemy.get("hp", 0)))
        enemy_max_hp = max(1, int(enemy.get("max_hp", 1)))
        enemy_label = "FINAL BOSS" if floor == MAX_FLOOR else ("BOSS" if enemy.get("boss") else "ENEMY")
        lines.extend([
            "", "⚔️ <b>OPPONENT</b>",
            f"{'☠️' if enemy.get('boss') else '👹'} <b>{escape(str(enemy.get('name', 'Unknown Demon')))}</b>  ·  {escape(str(enemy.get('rank', 'Unknown')))}",
            f"Demon Lv. <b>{enemy.get('demon_level', enemy.get('level', 1))}</b>  ·  {escape(str(enemy.get('ability', 'Basic Attack')))}",
            f"🩸 <b>{enemy_hp:,}/{enemy_max_hp:,}</b>  <code>{_bar(enemy_hp, enemy_max_hp, 10)}</code>",
            "",
            f"📖 <b>Chapter {int(enemy.get('chapter', (floor - 1) // 10 + 1))}</b> — {escape(str(enemy.get('story', 'The demon blocks your path.')))}",
            "",
            "<b>YOUR SQUAD</b>",
        ])
        for uid in members:
            member = get_player(int(uid))
            if member:
                hp = max(0, int(hp_map.get(str(uid), member.get("hp", 1))))
                maximum = max(1, int(member.get("max_hp", 1)))
                lines.append(
                    f"• {escape(str(member.get('name', 'Slayer')))}  "
                    f"<b>{hp:,}/{maximum:,}</b> HP"
                )
                lines.append(f"  <code>{_bar(hp, maximum, 10)}</code>")

    if floor == MAX_FLOOR and enemy.get("boss"):
        lines.append("\n⚠️ <b>FINAL BATTLE</b> — defeat Muzan to clear the Castle.")
    return "\n".join(lines)

@_castle_guard
async def castle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    logger.info("Castle command received: user_id=%s args=%s", user_id, context.args or [])
    player = get_player(user_id)
    if not player:
        await update.effective_message.reply_text("Create your character first with /start.")
        return
    _apply_timed_recovery(user_id, player)
    args = context.args or []
    action = args[0].lower() if args else "status"

    if action in ("menu", "hub", "help"):
        await update.effective_message.reply_text(
            "🏯 <b>INFINITY CASTLE</b>\n"
            "Climb 100 floors, defeat ranked demons, collect Castle gear, "
            "and face Muzan at the summit.\n\nChoose your expedition:",
            parse_mode="HTML", reply_markup=_lobby_keyboard()
        )
        return

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
            parse_mode="HTML", reply_markup=_keyboard(run, user_id=user_id)
        )
        return

    if action in ("solo", "enter"):
        if _find_user_party(user_id):
            await update.effective_message.reply_text("You are already in a Castle squad. Use /castle my_squad or open the Castle Hub and tap My Squad.")
            return
        if _find_run(user_id):
            await update.effective_message.reply_text("You already have an active Castle run. Use /castle status.")
            return
        run = create_castle_run(user_id, "solo")
        await _start_floor(run, player, None)
        run = _find_run(user_id)
        await update.effective_message.reply_text(
            _render_run(run, player), parse_mode="HTML", reply_markup=_keyboard(run, user_id=user_id)
        )
        return

    if action in ("squad", "party"):
        existing_party = _find_user_party(user_id)
        if existing_party:
            await update.effective_message.reply_text(
                f"You are already in a squad ({'leader' if int(existing_party.get('leader_id', 0)) == user_id else 'member'}). "
                "Open /castle and tap My Squad."
            )
            return
        if _find_run(user_id):
            await update.effective_message.reply_text("Finish or retreat from your active Castle run before creating a squad.")
            return
        party = create_castle_party(user_id)
        await update.effective_message.reply_text(
            "👥 <b>Castle squad created!</b>\n"
            f"Party code: <code>{party['party_id']}</code>\n"
            "Share this code. Up to 4 players can join with:\n"
            f"<code>/castle join {party['party_id']}</code>\n"
            "The leader can start the co-op battle using the button below.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⚔️ Start Squad Battle", callback_data="castle:start_squad")
            ]]),
        )
        return

    if action == "leave":
        party = _find_user_party(user_id)
        if not party or party.get("status") != "open":
            await update.effective_message.reply_text("You are not in an open Castle squad.")
            return
        leader_id = int(party.get("leader_id", 0))
        members = list(dict.fromkeys([leader_id] + [int(uid) for uid in party.get("member_ids", [])]))
        if leader_id != user_id or len(members) > 1:
            await update.effective_message.reply_text(
                "Only the owner/leader of an empty squad can disband it. "
                "A squad with members must transfer leadership first."
            )
            return
        col("castle_parties").update_one(
            {"party_id": party["party_id"], "status": "open", "leader_id": user_id},
            {"$set": {"status": "disbanded", "member_ids": [],
                      "disbanded_at": datetime.utcnow(), "updated_at": datetime.utcnow()}}
        )
        await update.effective_message.reply_text(
            "🚪 Your empty squad has been disbanded. You can create or join another squad."
        )
        return

    if action == "gift":
        if len(args) < 3:
            await update.effective_message.reply_text(
                "🎁 Usage: /castle gift USER_ID bandage|medkit|tonic [quantity]"
            )
            return
        try:
            recipient_id = int(args[1])
            quantity = max(1, min(10, int(args[3]) if len(args) > 3 else 1))
        except (TypeError, ValueError):
            await update.effective_message.reply_text("❌ Enter a valid numeric USER_ID and quantity.")
            return
        item_key = args[2].lower()
        item = CASTLE_RECOVERY_ITEMS.get(item_key)
        party = _find_user_party(user_id)
        if not item or not party or recipient_id == user_id:
            await update.effective_message.reply_text("❌ You and the recipient must be different members of the same Castle squad. Valid gifts: bandage, medkit, tonic.")
            return
        party_members = set([int(party.get("leader_id", 0))] + [int(uid) for uid in party.get("member_ids", [])])
        if recipient_id not in party_members or not get_player(recipient_id):
            await update.effective_message.reply_text("❌ That player is not a member of your squad.")
            return
        consumed = col("castle_supplies").update_one(
            {"user_id": user_id, "item_id": item_key, "quantity": {"$gte": quantity}},
            {"$inc": {"quantity": -quantity}, "$set": {"updated_at": datetime.utcnow()}}
        )
        if consumed.modified_count != 1:
            await update.effective_message.reply_text(f"❌ You don't have {quantity} {item['name']}(s).")
            return
        col("castle_supplies").update_one(
            {"user_id": recipient_id, "item_id": item_key},
            {"$inc": {"quantity": quantity}, "$set": {"updated_at": datetime.utcnow()}},
            upsert=True
        )
        await update.effective_message.reply_text(
            f"🎁 Gift sent! You gave {quantity} × {item['name']} to your squad member."
        )
        try:
            await context.bot.send_message(
                chat_id=recipient_id,
                text=f"🎁 You received {quantity} × {item['name']} from your Castle squad member!"
            )
        except Exception:
            logger.info("Could not DM Castle gift recipient %s", recipient_id)
        return

    if action == "join":
        if len(args) < 2:
            await update.effective_message.reply_text("Usage: /castle join PARTY_CODE")
            return
        target_party = get_castle_party(args[1])
        if not target_party or target_party.get("status") != "open":
            await update.effective_message.reply_text("❌ Squad not found or it has already started.")
            return
        existing_party = _find_user_party(user_id)
        if existing_party:
            if existing_party.get("party_id") == args[1]:
                await update.effective_message.reply_text("✅ You are already in this squad. Open /castle and tap My Squad.")
                return
            if existing_party.get("status") != "open":
                await update.effective_message.reply_text("⚠️ You cannot switch squads while your current squad is running.")
                return
            if int(existing_party.get("leader_id", 0)) == user_id and not [
                int(uid) for uid in existing_party.get("member_ids", []) if int(uid) != user_id
            ]:
                await update.effective_message.reply_text("⚠️ Add at least one squad member first so leadership can be transferred before you join another squad.")
                return
            await update.effective_message.reply_text(
                "👥 <b>Switch Castle Squad?</b>\n\n"
                "You are already in another open squad. If you continue, you will leave your current squad and join the new one.\n"
                f"New squad: <code>{escape(str(args[1]))}</code>\n"
                "Do you want to switch?",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Confirm & Join", callback_data=f"castle:transfer_confirm:{args[1]}"),
                    InlineKeyboardButton("❌ Cancel", callback_data="castle:transfer_cancel"),
                ]]),
            )
            return
        if _find_run(user_id):
            await update.effective_message.reply_text("Finish or retreat from your active Castle run first.")
            return
        ok = add_castle_party_member(args[1], user_id)
        if ok:
            party_after = get_castle_party(args[1])
            if party_after and int(party_after.get("leader_id", 0)) != user_id:
                joined_player = player.get("name", f"Player {user_id}")
                try:
                    await context.bot.send_message(
                        chat_id=int(party_after["leader_id"]),
                        text=(
                            "👥 <b>New Castle squad member!</b>\n"
                            f"<b>{escape(str(joined_player))}</b> joined your squad.\n"
                            f"Squad size: <b>{len(party_after.get('member_ids', []))}/4</b>"
                        ),
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.exception("Could not notify Castle squad leader about join")
            await update.effective_message.reply_text(
                "✅ You joined the squad! The leader has been notified."
            )
        else:
            await update.effective_message.reply_text(
                "❌ Party not found, already full (4 players), or already started."
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
        # Repair older squad records and guarantee the owner is a member.
        col("castle_parties").update_one(
            {"party_id": party["party_id"], "status": "open"},
            {"$addToSet": {"member_ids": user_id},
             "$set": {"updated_at": datetime.utcnow()}}
        )
        party = get_castle_party(party["party_id"])
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
            parse_mode="HTML", reply_markup=_keyboard(run, user_id=user_id)
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
        _render_run(run, player, party), parse_mode="HTML", reply_markup=_keyboard(run, user_id=user_id)
    )


async def _start_floor(run, player, party):
    floor = int(run.get("floor", 1))
    # Always use fresh DB data when generating an enemy, including solo runs.
    if party:
        members = _party_players(party)
    else:
        fresh_player = col("players").find_one({"user_id": int(player["user_id"])})
        if fresh_player:
            fresh_player.pop("_id", None)
            player = fresh_player
        members = [player]
    hp_map = run.get("player_hp_by_user") or {
        str(p["user_id"]): int(p.get("hp", p.get("max_hp", 100))) for p in members
    }
    room_type = "combat"
    room_notice = (
        f"Chapter {(floor - 1) // 10 + 1}: The Infinity Castle twists around you. "
        "A demon's presence emerges from the darkness."
    )
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
    # Recovery caches can appear unexpectedly while exploring. A found cache
    # is shared fairly: every active expedition member receives the same drop.
    if floor not in BOSS_FLOORS and random.random() < 0.18:
        item_key = random.choices(
            ["bandage", "medkit", "tonic"], weights=[50, 15, 35], k=1
        )[0]
        item = CASTLE_RECOVERY_ITEMS[item_key]
        quantity = random.choices([1, 2], weights=[85, 15], k=1)[0]
        room_notice += (
            f"\n\n🎁 HIDDEN SUPPLY CACHE! "
            f"The squad discovered {quantity} × {item['name']}!"
        )
        for member in members:
            uid = int(member["user_id"])
            col("castle_supplies").update_one(
                {"user_id": uid, "item_id": item_key},
                {"$inc": {"quantity": quantity},
                 "$set": {"updated_at": datetime.utcnow()}},
                upsert=True,
            )

    if room_type == "combat":
        enemy = _enemy_for(player, floor, members)
        chapter = (floor - 1) // 10 + 1
        story_beats = [
            "The wooden corridors groan as the castle rearranges itself. A cold presence is watching your every move.",
            "A distant biwa note echoes. The walls fold inward, sealing the path behind your squad.",
            "Wisteria petals drift through the air, but the scent is quickly swallowed by demonic blood.",
            "A wounded Kakushi's warning reaches you: the next chamber is guarded by a demon that hunts in silence.",
            "The castle lights fade. Your footsteps awaken something that has waited here for centuries.",
            "A blood-red moon appears beyond the impossible windows. The enemy knows your names.",
            "The floor trembles as the castle shifts. Every step forward feels like walking into a trap.",
            "A broken Nichirin blade lies at the doorway. Its owner never made it to the next room.",
            "The air grows heavy with Muzan's presence. Even the demons ahead seem afraid.",
            "A final biwa note rings out. The path to the next Kizuki is open—but survival is not promised.",
        ]
        enemy["story"] = story_beats[(floor - 1) % len(story_beats)]
        enemy["chapter"] = chapter
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
        castle_coins = 20 + floor * 5 + (100 if enemy.get("boss") else 0)
        col("players").update_one({"user_id": uid}, {"$inc": {"castle_coins": castle_coins}})
        fresh_wallet = col("players").find_one({"user_id": uid}, {"castle_coins": 1}) or {}
        update_player(uid, castle_coins=int(fresh_wallet.get("castle_coins", 0)))
        rewards.append(f"🪙 {escape(str(member.get('name', 'Player')))}: +{castle_coins} Castle Coins")
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


@_castle_guard
async def castle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info("Castle callback received: user_id=%s data=%s", query.from_user.id, query.data)
    await query.answer()
    user_id = query.from_user.id
    player = get_player(user_id)
    if not player:
        await _safe_castle_edit(query, "Create your character first with /start.")
        return
    _apply_timed_recovery(user_id, player)
    player = get_player(user_id) or player
    action = query.data.split(":", 1)[1] if ":" in (query.data or "") else (query.data or "")
    run = _find_run(user_id)

    # Lobby actions must work even when the player has no active run.
    if action == "menu":
        await _safe_castle_edit(query, 
            "🏯 <b>INFINITY CASTLE</b>\nChoose a mode to begin your climb.",
            parse_mode="HTML", reply_markup=_lobby_keyboard()
        )
        return
    if action == "solo":
        if _find_user_party(user_id):
            await _safe_castle_edit(query, "You are already in a Castle squad. Open My Squad to view it.", parse_mode="HTML", reply_markup=_lobby_keyboard())
            return
        if run:
            await query.message.reply_text("You already have an active run. Use /castle status.")
            return
        run = create_castle_run(user_id, "solo")
        await _start_floor(run, player, None)
        run = _find_run(user_id)
        await _safe_castle_edit(query, 
            _render_run(run, player), parse_mode="HTML", reply_markup=_keyboard(run, user_id=user_id)
        )
        return
    if action == "squad":
        existing_party = _find_user_party(user_id)
        if existing_party:
            await _safe_castle_edit(query, "You are already in a squad. Open My Squad to view its members and status.", parse_mode="HTML", reply_markup=_lobby_keyboard())
            return
        if run:
            await query.message.reply_text("Finish or retreat from your active run first.")
            return
        # Reuse the leader's existing open squad instead of generating a
        # different invite code whenever Create Squad is tapped again.
        party = col("castle_parties").find_one(
            {"$or": [{"owner_id": user_id}, {"original_owner_id": user_id}, {"leader_id": user_id}]},
            sort=[("created_at", 1)]
        )
        if party:
            party.pop("_id", None)
            if party.get("status") not in ("open", "running"):
                col("castle_parties").update_one(
                    {"party_id": party["party_id"]},
                    {"$set": {
                        "leader_id": user_id, "member_ids": [user_id],
                        "status": "open", "updated_at": datetime.utcnow()
                    }}
                )
                party = get_castle_party(party["party_id"])
        else:
            party = create_castle_party(user_id)
            col("castle_parties").update_one(
                {"party_id": party["party_id"]},
                {"$set": {"owner_id": user_id, "original_owner_id": user_id}}
            )
            party["owner_id"] = user_id
            party["original_owner_id"] = user_id
        await _safe_castle_edit(query,
            "👥 <b>Your Castle Squad</b>\n"
            f"Party code: <code>{escape(str(party['party_id']))}</code>\n\n"
            "This invite code stays the same while this squad is open. "
            "Share it with up to 3 players:\n"
            f"<code>/castle join {escape(str(party['party_id']))}</code>\n\n"
            "When everyone has joined, the leader can start the co-op battle below.",
            parse_mode="HTML", reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 My Squad", callback_data="castle:my_squad")],
                [InlineKeyboardButton("⚔️ Start Squad Battle", callback_data="castle:start_squad")],
                [InlineKeyboardButton("↻ Castle Hub", callback_data="castle:menu")]
            ])
        )
        return
    if action.startswith("transfer_confirm:"):
        target_id = action.split(":", 1)[1]
        old_party = _find_user_party(user_id)
        target_party = get_castle_party(target_id)
        if not target_party or target_party.get("status") != "open":
            await _safe_castle_edit(query, "❌ That squad is no longer available. Your current squad has not been changed.", parse_mode="HTML", reply_markup=_lobby_keyboard())
            return
        if old_party and old_party.get("party_id") == target_id:
            await _safe_castle_edit(query, "✅ You are already in that squad.", parse_mode="HTML", reply_markup=_lobby_keyboard())
            return
        # If this is the squad's original owner returning, restore the
        # owner/leader title and keep the acting leader as a normal member.
        reclaiming_own_squad = int(target_party.get("owner_id", target_party.get("original_owner_id", 0)) or 0) == user_id
        if reclaiming_own_squad:
            if old_party and old_party.get("status") != "open":
                await _safe_castle_edit(query, "⚠️ Finish the current squad battle before switching squads.", parse_mode="HTML", reply_markup=_lobby_keyboard())
                return
            if old_party:
                col("castle_parties").update_one(
                    {"party_id": old_party["party_id"], "status": "open"},
                    {"$pull": {"member_ids": user_id}, "$set": {"updated_at": datetime.utcnow()}}
                )
            acting_leader = int(target_party.get("leader_id", 0))
            col("castle_parties").update_one(
                {"party_id": target_id, "status": "open", "owner_id": user_id},
                {"$set": {"leader_id": user_id, "updated_at": datetime.utcnow()},
                 "$addToSet": {"member_ids": acting_leader}}
            )
            joined = True
        else:
            if old_party:
                if old_party.get("status") != "open":
                    await _safe_castle_edit(query, "⚠️ You cannot switch while your current squad is running. Your membership is unchanged.", parse_mode="HTML", reply_markup=_lobby_keyboard())
                    return
                if int(old_party.get("leader_id", 0)) == user_id:
                    eligible = [int(uid) for uid in old_party.get("member_ids", []) if int(uid) != user_id]
                    if not eligible:
                        await _safe_castle_edit(query, "⚠️ Add at least one member before transferring squad leadership.", parse_mode="HTML", reply_markup=_lobby_keyboard())
                        return
                    new_leader = eligible[0]
                    col("castle_parties").update_one(
                        {"party_id": old_party["party_id"], "status": "open", "leader_id": user_id},
                        {"$set": {"leader_id": new_leader, "owner_id": user_id,
                                  "original_owner_id": user_id, "updated_at": datetime.utcnow()},
                         "$pull": {"member_ids": user_id}}
                    )
                else:
                    col("castle_parties").update_one(
                        {"party_id": old_party["party_id"], "status": "open"},
                        {"$pull": {"member_ids": user_id}, "$set": {"updated_at": datetime.utcnow()}}
                    )
            joined = add_castle_party_member(target_id, user_id)
        if not joined:
            # Best-effort rollback so a full/closed target does not strand the player.
            if old_party:
                if int(old_party.get("leader_id", 0)) != user_id and int(old_party.get("owner_id", 0) or 0) == user_id:
                    col("castle_parties").update_one(
                        {"party_id": old_party["party_id"], "status": "open"},
                        {"$set": {"leader_id": user_id, "updated_at": datetime.utcnow()},
                         "$addToSet": {"member_ids": user_id}}
                    )
                else:
                    col("castle_parties").update_one(
                        {"party_id": old_party["party_id"], "status": "open"},
                        {"$addToSet": {"member_ids": user_id}, "$set": {"updated_at": datetime.utcnow()}}
                    )
            await _safe_castle_edit(query, "❌ That squad became full or started. Your previous squad membership was restored.", parse_mode="HTML", reply_markup=_lobby_keyboard())
            return
        new_party = get_castle_party(target_id) or target_party
        try:
            await context.bot.send_message(
                chat_id=int(new_party["leader_id"]),
                text=f"👥 <b>Squad member joined!</b>\n{escape(str(player.get('name', f'Player {user_id}')))} joined your squad.\nSquad size: <b>{len(new_party.get('member_ids', []))}/4</b>",
                parse_mode="HTML",
            )
        except Exception:
            logger.exception("Could not notify new Castle squad leader about transferred member")
        await _safe_castle_edit(query, "✅ You left your previous squad and joined the new squad. The new leader has been notified.", parse_mode="HTML", reply_markup=_lobby_keyboard())
        return
    if action == "transfer_cancel":
        await _safe_castle_edit(query, "↩️ Squad switch cancelled. You are still in your previous squad.", parse_mode="HTML", reply_markup=_lobby_keyboard())
        return
    if action == "my_squad":
        party = _find_user_party(user_id)
        # Fallback for older leader-created records whose member_ids field
        # may be missing or malformed: always show the leader's saved open squad.
        if not party:
            party = col("castle_parties").find_one(
                {"leader_id": user_id, "status": {"$in": ["open", "running"]}},
                sort=[("updated_at", -1)]
            )
            if party:
                party.pop("_id", None)
        if not party:
            await _safe_castle_edit(
                query, "👥 You are not in a squad yet. Create one or join using /castle join PARTY_CODE.",
                parse_mode="HTML", reply_markup=_lobby_keyboard()
            )
            return
        leader_id = int(party.get("leader_id", 0))
        member_ids = list(dict.fromkeys([leader_id] + [int(uid) for uid in party.get("member_ids", [])]))
        lines = [
            "👥 <b>MY INFINITY CASTLE SQUAD</b>",
            f"Party code: <code>{escape(str(party.get('party_id', '')))}</code>",
            f"Status: <b>{escape(str(party.get('status', 'unknown')).title())}</b>",
            f"Members: <b>{len(member_ids)}/4</b>",
            "",
        ]
        for uid in member_ids:
            member = get_player(uid) or {}
            owner_id = int(party.get("owner_id", party.get("original_owner_id", leader_id)) or leader_id)
            role = "Owner" if uid == owner_id else ("Acting Leader" if uid == leader_id else "Member")
            lines.append(f"• {escape(str(member.get('name', f'Player {uid}')))} — {role}")
        lines.extend([
            "",
            "🎁 <b>Squad gifting</b>",
            "Share recovery supplies with a teammate:",
            "<code>/castle gift USER_ID bandage 1</code>",
            "Items: bandage, medkit, tonic (up to 10 at once).",
        ])
        buttons = []
        if party.get("status") == "open" and leader_id == user_id:
            buttons.append([InlineKeyboardButton("⚔️ Start Squad Battle", callback_data="castle:start_squad")])
            if len(member_ids) == 1:
                buttons.append([InlineKeyboardButton("🚪 Disband Empty Squad", callback_data="castle:leave_squad")])
        if party.get("status") == "open" and leader_id != user_id:
            buttons.append([InlineKeyboardButton("🚪 Leave Squad", callback_data="castle:leave_squad")])
        buttons.append([InlineKeyboardButton("🏪 Recovery Shop", callback_data="castle:shop"),
                        InlineKeyboardButton("🏯 Castle Hub", callback_data="castle:menu")])
        await _safe_castle_edit(query, "\n".join(lines), parse_mode="HTML",
                                reply_markup=InlineKeyboardMarkup(buttons))
        return
    if action == "leave_squad":
        party = _find_user_party(user_id)
        if party and int(party.get("leader_id", 0)) == user_id and party.get("status") == "open":
            members = list(dict.fromkeys(
                [int(party.get("leader_id", 0))] +
                [int(uid) for uid in party.get("member_ids", [])]
            ))
            if len(members) != 1:
                await query.answer("Your squad has members. Transfer leadership before leaving.", show_alert=True)
                return
            col("castle_parties").update_one(
                {"party_id": party["party_id"], "status": "open", "leader_id": user_id},
                {"$set": {"status": "disbanded", "member_ids": [],
                          "disbanded_at": datetime.utcnow(), "updated_at": datetime.utcnow()}}
            )
            await _safe_castle_edit(
                query, "🚪 Your empty squad has been disbanded. You can now create or join another squad.",
                parse_mode="HTML", reply_markup=_lobby_keyboard()
            )
            return
        if not party or int(party.get("leader_id", 0)) == user_id or party.get("status") != "open":
            await query.answer("Only squad members can leave an open squad.", show_alert=True)
            return
        col("castle_parties").update_one(
            {"party_id": party["party_id"], "status": "open"},
            {"$pull": {"member_ids": user_id}, "$set": {"updated_at": datetime.utcnow()}}
        )
        await _safe_castle_edit(query, "🚪 You left the squad. You can now join or create another one.",
                                parse_mode="HTML", reply_markup=_lobby_keyboard())
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
        await _safe_castle_edit(query, 
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
        await _safe_castle_edit(query, 
            "\n".join(lines), parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("↻ Castle Hub", callback_data="castle:menu")
            ]])
        )
        return
    if action == "start_squad":
        if run:
            await _safe_castle_edit(query, "You already have an active Castle run. Use /castle status.")
            return
        party = col("castle_parties").find_one({"leader_id": user_id, "status": "open"})
        if not party:
            await _safe_castle_edit(query, "You don't have an open squad to start. Create one from the Castle Hub.")
            return
        col("castle_parties").update_one(
            {"party_id": party["party_id"], "status": "open"},
            {"$addToSet": {"member_ids": user_id},
             "$set": {"updated_at": datetime.utcnow()}}
        )
        party = get_castle_party(party["party_id"])
        members = _party_players(party)
        if not members:
            await _safe_castle_edit(query, "No valid squad members found. Ask everyone to join again.")
            return
        run = create_castle_run(user_id, "squad", party["party_id"])
        hp_map = {
            str(member["user_id"]): int(member.get("hp", member.get("max_hp", 100)))
            for member in members
        }
        save_castle_run(run["run_id"], {"player_hp_by_user": hp_map})
        col("castle_parties").update_one(
            {"party_id": party["party_id"], "status": "open"},
            {"$set": {"status": "running", "updated_at": datetime.utcnow()}}
        )
        await _start_floor(run, player, party)
        run = _find_run(user_id)
        # Give every squad member a personal battle message with working
        # Attack/Technique/Guard buttons. The leader already has the edited panel.
        await _safe_castle_edit(
            query,
            _render_run(run, player, party, "🤝 Co-op battle started! Every squad member can take a turn."),
            parse_mode="HTML", reply_markup=_keyboard(run, user_id=user_id)
        )
        notified_ids = []
        dm_failed_ids = []
        group_chat_id = query.message.chat_id if query.message else None
        for member in members:
            member_id = int(member["user_id"])
            if member_id == user_id:
                continue
            member_player = get_player(member_id) or member
            battle_text = (
                "⚔️ <b>YOUR SQUAD BATTLE HAS STARTED!</b>\n"
                "Your squad leader has entered the Infinity Castle. "
                "You can now take your own turns using the battle buttons below.\n\n"
                + _render_run(run, member_player, party)
            )
            try:
                await context.bot.send_message(
                    chat_id=member_id,
                    text=battle_text,
                    parse_mode="HTML",
                    reply_markup=_keyboard(run, user_id=member_id),
                )
                notified_ids.append(member_id)
            except Exception as exc:
                # Telegram blocks unsolicited private messages until that user
                # opens the bot. If the squad was started in a shared group,
                # post a group notice so the member still sees the battle start.
                logger.warning(
                    "Castle DM failed for member %s: %s", member_id, exc
                )
                dm_failed_ids.append(member_id)
                if group_chat_id and group_chat_id < 0:
                    try:
                        await context.bot.send_message(
                            chat_id=group_chat_id,
                            text=(
                                f"⚔️ <b>{escape(str(member_player.get('name', 'Squad member')))}</b>, "
                                "your squad battle has started! Open the bot and send /castle "
                                "to get your personal battle controls."
                            ),
                            parse_mode="HTML",
                        )
                    except Exception:
                        logger.exception(
                            "Could not post Castle group fallback for member %s",
                            member_id,
                        )
        if dm_failed_ids:
            await query.message.reply_text(
                "⚠️ I couldn't DM every squad member. Those members must open this bot "
                "and send /start once; Telegram does not allow bots to start private chats. "
                + (f"Members needing /start: {', '.join(str(uid) for uid in dm_failed_ids)}")
            )
        return
    if action == "shop":
        shop_text, supplies = _castle_shop_text(user_id)
        await _safe_castle_edit(
            query, shop_text, parse_mode="HTML",
            reply_markup=_castle_shop_keyboard(supplies)
        )
        return
    if action.startswith("buy_"):
        item_key = action[4:]
        item = CASTLE_RECOVERY_ITEMS.get(item_key)
        if not item:
            await query.answer("Unknown supply.", show_alert=True)
            return
        balance = int(player.get("castle_coins", 0) or 0)
        if balance < item["price"]:
            await query.answer(f"Need {item['price']} Castle Coins.", show_alert=True)
            return
        result = col("players").update_one(
            {"user_id": user_id, "castle_coins": {"$gte": item["price"]}},
            {"$inc": {"castle_coins": -item["price"]}}
        )
        if result.modified_count != 1:
            await query.answer("Not enough Castle Coins.", show_alert=True)
            return
        fresh_wallet = col("players").find_one({"user_id": user_id}, {"castle_coins": 1}) or {}
        update_player(user_id, castle_coins=int(fresh_wallet.get("castle_coins", 0)))
        col("castle_supplies").update_one(
            {"user_id": user_id, "item_id": item_key},
            {"$inc": {"quantity": 1}, "$set": {"updated_at": datetime.utcnow()}},
            upsert=True
        )
        player = get_player(user_id) or player
        shop_text, supplies = _castle_shop_text(user_id)
        await _safe_castle_edit(
            query, shop_text + f"\n\n✅ Purchased <b>{item['name']}</b>.",
            parse_mode="HTML", reply_markup=_castle_shop_keyboard(supplies)
        )
        return
    if action.startswith("use_"):
        item_key = action[4:]
        item = CASTLE_RECOVERY_ITEMS.get(item_key)
        if not item:
            await query.answer("Unknown supply.", show_alert=True)
            return
        # In a live run, only a living member may use supplies and the battle
        # panel is refreshed immediately after the recovery.
        battle_party = get_castle_party(run.get("party_id")) if run and run.get("party_id") else None
        if run and run.get("status") == "active":
            battle_members = (
                list(dict.fromkeys([int(battle_party.get("leader_id", 0))] +
                                   [int(uid) for uid in battle_party.get("member_ids", [])]))
                if battle_party else [int(run.get("user_id", user_id))]
            )
            if user_id not in battle_members:
                await query.answer("You are not in this battle.", show_alert=True)
                return
            if int((run.get("current_enemy") or {}).get("hp", 0)) <= 0:
                await query.answer("The battle is over. Continue to the next floor.", show_alert=True)
                return

        consumed = col("castle_supplies").update_one(
            {"user_id": user_id, "item_id": item_key, "quantity": {"$gt": 0}},
            {"$inc": {"quantity": -1}, "$set": {"updated_at": datetime.utcnow()}}
        )
        if consumed.modified_count != 1:
            await query.answer("You don't own this recovery item.", show_alert=True)
            return
        field = item["effect"]
        maximum = max(1, int(player.get("max_hp" if field == "hp" else "max_sta",
                                      player.get(field, 1)) or 1))
        if field == "hp" and run and run.get("status") == "active":
            hp_map = run.get("player_hp_by_user", {})
            current = max(0, int(hp_map.get(str(user_id), player.get("hp", 0)) or 0))
        else:
            current = max(0, int(player.get(field, 0) or 0))
        restored = min(maximum - current, max(1, int(maximum * item["amount"])))
        if restored <= 0:
            col("castle_supplies").update_one(
                {"user_id": user_id, "item_id": item_key}, {"$inc": {"quantity": 1}}
            )
            await query.answer(f"Your {field.upper()} is already full.", show_alert=True)
            return
        new_value = current + restored
        update_player(user_id, **{field: new_value})
        if field == "hp" and run and run.get("status") == "active":
            hp_map = run.get("player_hp_by_user", {})
            hp_map[str(user_id)] = new_value
            save_castle_run(run["run_id"], {"player_hp_by_user": hp_map})
            run["player_hp_by_user"] = hp_map
        player = get_player(user_id) or player
        if run and run.get("status") == "active":
            await query.answer(f"+{restored} {field.upper()} restored.")
            await _safe_castle_edit(
                query,
                _render_run(run, player, battle_party,
                            f"✅ Used {item['name']}: +{restored} {field.upper()}."),
                parse_mode="HTML",
                reply_markup=_keyboard(run, user_id=user_id),
            )
        else:
            shop_text, supplies = _castle_shop_text(user_id)
            await _safe_castle_edit(
                query, shop_text + f"\n\n✅ Used <b>{item['name']}</b>: +{restored} {field.upper()}.",
                parse_mode="HTML", reply_markup=_castle_shop_keyboard(supplies)
            )
        return
    if not run:
        await _safe_castle_edit(query, 
            "No active Castle run. Choose a mode to begin.",
            reply_markup=_lobby_keyboard()
        )
        return
    party = get_castle_party(run.get("party_id")) if run.get("party_id") else None
    members = (
        list(dict.fromkeys(
            [int(party.get("leader_id", 0))] +
            [int(uid) for uid in party.get("member_ids", [])]
        ))
        if party else [int(run["user_id"])]
    )
    if user_id not in members:
        await _safe_castle_edit(query, "You are not a member of this Castle run.")
        return
    if action == "status":
        await _safe_castle_edit(query, 
            _render_run(run, player, party), parse_mode="HTML", reply_markup=_keyboard(run, user_id=user_id)
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
        await _safe_castle_edit(query, "🏃 You retreated. Your Castle run has ended. Use /castle to begin again.")
        return
    if action == "next":
        # Re-read the persistent run before advancing; callbacks may arrive late
        # or from an old Telegram message after another squad member has advanced.
        fresh_run = col("castle_runs").find_one(
            {"run_id": run["run_id"], "status": "active"}
        )
        if not fresh_run:
            await _safe_castle_edit(query, "This Castle run is no longer active. Open /castle to continue.")
            return
        fresh_run.pop("_id", None)
        enemy = fresh_run.get("current_enemy") or {}
        if int(enemy.get("hp", 1)) > 0:
            await query.answer("Defeat the current enemy first.", show_alert=True)
            return
        current_floor = int(fresh_run.get("floor", 1))
        if current_floor >= MAX_FLOOR:
            await _safe_castle_edit(query, "🏆 The Castle is complete. Return to the Castle Hub.")
            return
        floor = current_floor + 1
        # Use the latest party roster so newly joined squad members are included.
        party = get_castle_party(fresh_run.get("party_id")) if fresh_run.get("party_id") else None
        if party:
            party = col("castle_parties").find_one({"party_id": party["party_id"]}) or party
            party.pop("_id", None)
        save_castle_run(fresh_run["run_id"], {"floor": floor})
        fresh_run["floor"] = floor
        await _start_floor(fresh_run, player, party)
        run = col("castle_runs").find_one({"run_id": fresh_run["run_id"]}) or fresh_run
        run.pop("_id", None)
        await _safe_castle_edit(
            query,
            _render_run(run, player, party, f"⚔️ Floor {floor}: the next chamber opens!"),
            parse_mode="HTML", reply_markup=_keyboard(run, user_id=user_id)
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
    enemy_hp_before = expected_enemy_hp
    if not apply_castle_enemy_damage(run["run_id"], expected_enemy_hp, damage):
        await query.message.reply_text("Another squad action updated this enemy first. Tap Status and try again.")
        return
    run = col("castle_runs").find_one({"run_id": run["run_id"]}) or run
    run.pop("_id", None)
    enemy = run.get("current_enemy") or {}
    enemy_hp_after = max(0, int(enemy.get("hp", 0)))
    enemy_damage_dealt = min(enemy_hp_before, damage)
    if int(enemy.get("hp", 0)) <= 0:
        result = await _complete_enemy(run, player, party)
        run = col("castle_runs").find_one({"run_id": run["run_id"]}) or run
        run.pop("_id", None)
        if run.get("status") == "completed":
            await _safe_castle_edit(query, 
                result, parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("↻ Castle Hub", callback_data="castle:menu")
                ]])
            )
        else:
            await _safe_castle_edit(query, 
                _render_run(run, player, party, f"⚔️ You dealt {damage:,} damage.\n{result}"),
                parse_mode="HTML", reply_markup=_keyboard(run, user_id=user_id)
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
    base_damage = int(enemy.get("atk", 5)) - (
        int(player.get("def_stat", player.get("defense", 0)) or 0) + armor_bonus
    ) // 3
    damage_multiplier = rank_multiplier * max(
        0.25, 1 - max(0, min(0.60, reduction))
    )
    enemy_damage = max(1, int(base_damage * damage_multiplier))
    player_hp_before = current_hp
    current_hp = max(0, current_hp - enemy_damage)
    player_hp_after_hit = current_hp
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
    notice = (
        f"{action_label}\\n"
        f"🗡️ Damage dealt: <b>{enemy_damage_dealt:,}</b> | Demon HP: "
        f"<b>{enemy_hp_before:,} → {enemy_hp_after:,}</b>\\n"
        f"💥 Damage received: <b>{enemy_damage:,}</b> | Your HP: "
        f"<b>{player_hp_before:,} → {player_hp_after_hit:,}</b>"
    )
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
    await _safe_castle_edit(query, 
        _render_run(run, player, party, notice),
        parse_mode="HTML", reply_markup=_keyboard(run, user_id=user_id)
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
