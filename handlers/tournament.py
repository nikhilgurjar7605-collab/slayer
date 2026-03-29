"""
handlers/tournament.py — Full Tournament System for Demon Slayer RPG Bot

Flow:
  Admin: /createtour <name> <yen_fee> <sp_fee> <max_players> [tour_level]
         → Sends banner image, bot posts registration embed
  Players: tap [📝 Register] button
  Admin: /starttour <tour_id>  → locks registration, sets temp level, assigns random skills/arts/breathing
  Fights: same 1v1 duel engine (challenge.py) but inside tournament context
  End:   /endtour <tour_id>   → admin ends or auto-ends when only 1 left
         → prizes distributed: 60% / 25% / 15% to Top 3
"""

import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut

from utils.database import (
    get_player, update_player, col
)
from utils.helpers import get_level
from utils.guards import group_only
from config import OWNER_ID

# ── Constants ─────────────────────────────────────────────────────────────

PRIZE_SPLIT = {1: 0.60, 2: 0.25, 3: 0.15}   # Top 3 share of prize pool

# ── DB helpers ────────────────────────────────────────────────────────────

def _tours():
    return col("tournaments")

def _get_tour(tour_id: str):
    doc = _tours().find_one({"tour_id": tour_id})
    if doc:
        doc.pop("_id", None)
    return doc

def _update_tour(tour_id: str, **kwargs):
    _tours().update_one({"tour_id": tour_id}, {"$set": kwargs})

def _next_tour_id() -> str:
    count = _tours().count_documents({})
    return f"TOUR{count + 1:04d}"

# ── Auth helpers ──────────────────────────────────────────────────────────

def _is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    return col("admins").find_one({"user_id": user_id}) is not None

# ── Safe message edit ─────────────────────────────────────────────────────

async def _safe_edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        if any(x in err.lower() for x in ("can't be edited", "not found")):
            try:
                await query.message.reply_text(text, **kwargs)
            except Exception:
                pass
        else:
            raise
    except TimedOut:
        pass

# ── Registration embed builder ────────────────────────────────────────────

def _tour_embed(tour: dict, extra: str = "") -> str:
    regs     = tour.get("registrations", [])
    max_p    = tour.get("max_players", "∞")
    t_level  = tour.get("tour_level")
    status   = tour.get("status", "open")

    status_icon = {"open": "🟢 OPEN", "active": "⚔️ IN PROGRESS", "ended": "🏁 ENDED"}.get(status, status)
    level_line  = f"\n🎯 *Tournament Level:* {t_level}" if t_level else ""
    fee_yen     = tour.get("fee_yen", 0)
    fee_sp      = tour.get("fee_sp", 0)
    prize_pool  = tour.get("prize_pool_yen", 0)

    text = (
        f"🏆 *TOURNAMENT — {tour['name']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: `{tour['tour_id']}`\n"
        f"📊 Status: {status_icon}"
        f"{level_line}\n"
        f"💰 Entry Fee: {fee_yen:,} Yen + {fee_sp} SP\n"
        f"🎁 Prize Pool: {prize_pool:,} Yen\n"
        f"👥 Registered: {len(regs)}/{max_p}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *All your skills, arts & breathing available*\n"
        f"⚔️ *Fight opponents of same level only*\n"
        f"🏅 *Top 3 share the prize pool (60/25/15%)*\n"
    )
    if extra:
        text += f"\n{extra}"
    return text


def _tour_keyboard(tour_id: str, status: str) -> InlineKeyboardMarkup:
    if status == "open":
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("📝 Register", callback_data=f"tour_register_{tour_id}"),
            InlineKeyboardButton("📋 Info",     callback_data=f"tour_info_{tour_id}"),
        ]])
    if status == "active":
        return InlineKeyboardMarkup([[
            InlineKeyboardButton("⚔️ Fight",    callback_data=f"tour_fight_{tour_id}"),
            InlineKeyboardButton("📋 Bracket",  callback_data=f"tour_bracket_{tour_id}"),
        ]])
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🏁 Results", callback_data=f"tour_results_{tour_id}"),
    ]])

# ══════════════════════════════════════════════════════════════════════════
# ADMIN COMMANDS
# ══════════════════════════════════════════════════════════════════════════

async def createtour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /createtour <name> <yen_fee> <sp_fee> <max_players> [tour_level]
    Admin sends a photo with caption = this command, OR sends command then bot asks for banner.
    """
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    args = context.args
    if not args or len(args) < 4:
        await update.message.reply_text(
            "❌ Usage: `/createtour <name> <yen_fee> <sp_fee> <max_players> [tour_level]`\n\n"
            "📌 Send this command as a *photo caption* to attach a banner image!\n\n"
            "Example: `/createtour Finals 5000 10 16 50`",
            parse_mode="Markdown"
        )
        return

    # Parse args — name can be multi-word if quoted, but here we do simple split
    # Format: name yen sp max [level]
    try:
        tour_name   = args[0].replace("_", " ")
        fee_yen     = int(args[1])
        fee_sp      = int(args[2])
        max_players = int(args[3])
        tour_level  = int(args[4]) if len(args) >= 5 else None
    except (ValueError, IndexError):
        await update.message.reply_text(
            "❌ Invalid args. Usage:\n`/createtour <name> <yen_fee> <sp_fee> <max_players> [tour_level]`",
            parse_mode="Markdown"
        )
        return

    tour_id = _next_tour_id()

    # Try to grab banner from photo caption
    banner_file_id = None
    if update.message.photo:
        banner_file_id = update.message.photo[-1].file_id

    doc = {
        "tour_id":       tour_id,
        "name":          tour_name,
        "fee_yen":       fee_yen,
        "fee_sp":        fee_sp,
        "max_players":   max_players,
        "tour_level":    tour_level,
        "prize_pool_yen":0,
        "prize_pool_sp": 0,
        "status":        "open",
        "registrations": [],       # list of {user_id, name, original_level, tour_level, ...}
        "bracket":       [],       # list of matches
        "results":       {},       # {place: user_id}
        "banner_file_id":banner_file_id,
        "created_by":    user_id,
        "created_at":    datetime.now(),
        "chat_id":       update.effective_chat.id,
        "message_id":    None,
    }
    _tours().insert_one(doc)

    text   = _tour_embed(doc, extra="✅ Tournament created! Players can now register.")
    kb     = _tour_keyboard(tour_id, "open")

    if banner_file_id:
        msg = await update.message.reply_photo(
            photo=banner_file_id,
            caption=text,
            parse_mode="Markdown",
            reply_markup=kb
        )
    else:
        msg = await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)

    _update_tour(tour_id, message_id=msg.message_id)
    await update.message.reply_text(
        f"✅ *Tournament `{tour_id}` created!*\n"
        f"📌 Use `/starttour {tour_id}` to begin when ready.\n"
        f"📸 Tip: Send this command as a photo caption to auto-attach a banner!",
        parse_mode="Markdown"
    )


async def starttour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/starttour <tour_id> — Lock registration, set tournament level, begin."""
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: `/starttour <tour_id>`", parse_mode="Markdown")
        return

    tour_id = context.args[0].upper()
    tour    = _get_tour(tour_id)
    if not tour:
        await update.message.reply_text(f"❌ Tournament `{tour_id}` not found.", parse_mode="Markdown")
        return
    if tour["status"] != "open":
        await update.message.reply_text("❌ Tournament is not in open state.")
        return

    regs = tour.get("registrations", [])
    if len(regs) < 2:
        await update.message.reply_text("❌ Need at least 2 registered players to start.")
        return

    tour_level = tour.get("tour_level")

    # Apply tournament level only — all skills, arts & breathing stay fully available
    import random as _random
    updated_regs = []
    for r in regs:
        uid    = r["user_id"]
        player = get_player(uid)
        if not player:
            continue

        original_level = get_level(player.get("xp", 0))

        r.update({
            "original_level": original_level,
            "tour_level":     tour_level or original_level,
            "hp":             player.get("max_hp", 240),
            "eliminated":     False,
            "wins":           0,
            "losses":         0,
        })
        updated_regs.append(r)

        # Store tour context on player doc
        update_player(uid,
            in_tournament       = tour_id,
            tour_level_override = tour_level or original_level,
        )

    # Shuffle and build first-round bracket
    _random.shuffle(updated_regs)
    bracket = _build_bracket(updated_regs)

    _update_tour(tour_id,
        status        = "active",
        registrations = updated_regs,
        bracket       = bracket,
        started_at    = datetime.now(),
    )

    # Announce
    participant_list = "\n".join(
        f"  {'🗡️' if get_player(r['user_id']) and get_player(r['user_id'])['faction']=='slayer' else '👹'} "
        f"*{r['name']}* (Lv.{r['tour_level']})"
        for r in updated_regs
    )
    text = (
        f"⚔️ *TOURNAMENT STARTED — {tour['name']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 ID: `{tour_id}`\n"
        f"👥 Fighters ({len(updated_regs)}):\n{participant_list}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ First round matches:\n"
    )
    for i, match in enumerate(bracket):
        if len(match) == 2:
            text += f"  Match {i+1}: *{match[0]['name']}* vs *{match[1]['name']}*\n"
        else:
            text += f"  Match {i+1}: *{match[0]['name']}* — BYE (auto-advance)\n"

    text += f"\nUse `/fight @opponent` to battle your match opponent!"

    kb = _tour_keyboard(tour_id, "active")
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def endtour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/endtour <tour_id> — Force-end the tournament and distribute prizes."""
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args:
        await update.message.reply_text("❌ Usage: `/endtour <tour_id>`", parse_mode="Markdown")
        return

    tour_id = context.args[0].upper()
    tour    = _get_tour(tour_id)
    if not tour:
        await update.message.reply_text(f"❌ Tournament `{tour_id}` not found.", parse_mode="Markdown")
        return
    if tour["status"] == "ended":
        await update.message.reply_text("❌ Tournament already ended.")
        return

    await _finalize_tournament(update, context, tour)


async def listtours(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/listtours — List all active/open tournaments."""
    tours = list(_tours().find({"status": {"$in": ["open", "active"]}}, {"_id": 0}))
    if not tours:
        await update.message.reply_text("📭 No active tournaments right now.")
        return

    text = "🏆 *Active Tournaments*\n━━━━━━━━━━━━━━━━━━━━━\n"
    for t in tours:
        regs   = len(t.get("registrations", []))
        status = "🟢 Open" if t["status"] == "open" else "⚔️ Active"
        text  += (
            f"{status} `{t['tour_id']}` — *{t['name']}*\n"
            f"  👥 {regs}/{t['max_players']} | 💰 {t['fee_yen']:,} Yen + {t['fee_sp']} SP\n"
        )
    await update.message.reply_text(text, parse_mode="Markdown")


async def settourlevel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/settourlevel <tour_id> <level> — Admin changes the tournament level mid-setup."""
    user_id = update.effective_user.id
    if not _is_admin(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text("❌ Usage: `/settourlevel <tour_id> <level>`", parse_mode="Markdown")
        return

    tour_id = context.args[0].upper()
    try:
        level = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Level must be a number.")
        return

    tour = _get_tour(tour_id)
    if not tour:
        await update.message.reply_text(f"❌ Tournament `{tour_id}` not found.", parse_mode="Markdown")
        return
    if tour["status"] != "open":
        await update.message.reply_text("❌ Can only change level before tournament starts.")
        return

    _update_tour(tour_id, tour_level=level)
    await update.message.reply_text(
        f"✅ Tournament `{tour_id}` level set to *{level}*.",
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════════════════════════════════════
# PLAYER COMMANDS
# ══════════════════════════════════════════════════════════════════════════

async def tournament(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/tournament — Show open tournaments or your current tournament status."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    # Check if already in a tournament
    in_tour = player.get("in_tournament")
    if in_tour:
        tour = _get_tour(in_tour)
        if tour and tour["status"] == "active":
            await _show_my_tournament(update, player, tour)
            return

    # Show open tournaments
    tours = list(_tours().find({"status": "open"}, {"_id": 0}))
    if not tours:
        await update.message.reply_text(
            "📭 *No open tournaments right now.*\n"
            "Check back later or ask an admin to create one!",
            parse_mode="Markdown"
        )
        return

    text = "🏆 *Open Tournaments*\n━━━━━━━━━━━━━━━━━━━━━\n"
    for t in tours:
        regs  = len(t.get("registrations", []))
        text += (
            f"🆔 `{t['tour_id']}` — *{t['name']}*\n"
            f"  💰 Fee: {t['fee_yen']:,} Yen + {t['fee_sp']} SP\n"
            f"  👥 {regs}/{t['max_players']} registered\n"
            f"  🎯 Level: {t.get('tour_level', 'Auto')}\n\n"
        )
    text += "Tap a tournament to register:"

    buttons = [
        [InlineKeyboardButton(f"📝 {t['name']} ({t['tour_id']})", callback_data=f"tour_register_{t['tour_id']}")]
        for t in tours
    ]
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=InlineKeyboardMarkup(buttons))


async def _show_my_tournament(update: Update, player: dict, tour: dict):
    """Show the player their tournament status."""
    user_id = player["user_id"]
    regs    = tour.get("registrations", [])
    me      = next((r for r in regs if r["user_id"] == user_id), None)

    if not me:
        await update.message.reply_text("❌ You're not registered in this tournament.")
        return

    alive = [r for r in regs if not r.get("eliminated")]
    elim  = me.get("eliminated", False)

    text = (
        f"⚔️ *YOUR TOURNAMENT STATUS*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 *{tour['name']}* (`{tour['tour_id']}`)\n"
        f"👤 Fighter: *{me['name']}*\n"
        f"🎯 Tour Level: {me.get('tour_level', '?')}\n"
        f"{'💀 ELIMINATED' if elim else '⚔️ STILL FIGHTING'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *All your skills, arts & breathing are available!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Players remaining: {len(alive)}/{len(regs)}\n"
        f"🎁 Prize pool: {tour.get('prize_pool_yen', 0):,} Yen\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown",
                                    reply_markup=_tour_keyboard(tour["tour_id"], "active"))


async def mytour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mytour — Show your current tournament status."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    in_tour = player.get("in_tournament")
    if not in_tour:
        await update.message.reply_text("📭 You're not in any tournament right now.")
        return

    tour = _get_tour(in_tour)
    if not tour:
        await update.message.reply_text("❌ Tournament not found.")
        return

    await _show_my_tournament(update, player, tour)


# ══════════════════════════════════════════════════════════════════════════
# BRACKET / MATCH HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _build_bracket(regs: list) -> list:
    """Pair players into matches. Odd player gets a BYE."""
    matches = []
    players = list(regs)
    while len(players) >= 2:
        p1 = players.pop(0)
        p2 = players.pop(0)
        matches.append([p1, p2])
    if players:  # BYE
        matches.append([players[0]])
    return matches


def _get_current_match(tour: dict, user_id: int):
    """Find the current bracket match for a user."""
    for match in tour.get("bracket", []):
        if len(match) == 2:
            ids = [m["user_id"] for m in match]
            if user_id in ids:
                return match
    return None


def _record_match_result(tour_id: str, winner_id: int, loser_id: int):
    """Record win/loss and eliminate the loser."""
    tour = _get_tour(tour_id)
    if not tour:
        return

    regs = tour.get("registrations", [])
    for r in regs:
        if r["user_id"] == winner_id:
            r["wins"] = r.get("wins", 0) + 1
        if r["user_id"] == loser_id:
            r["losses"]     = r.get("losses", 0) + 1
            r["eliminated"] = True

    # Remove completed match from bracket
    bracket = [
        m for m in tour.get("bracket", [])
        if not (len(m) == 2 and {m[0]["user_id"], m[1]["user_id"]} == {winner_id, loser_id})
    ]

    # Restore loser's level
    loser_player = get_player(loser_id)
    if loser_player:
        update_player(loser_id,
            in_tournament       = None,
            tour_level_override = None,
        )

    alive = [r for r in regs if not r.get("eliminated")]

    _update_tour(tour_id, registrations=regs, bracket=bracket)

    # If only 1 alive → auto-end
    if len(alive) <= 1:
        return "ended"

    # If bracket is empty, build next round
    if not bracket:
        new_bracket = _build_bracket(alive)
        _update_tour(tour_id, bracket=new_bracket)

    return "continue"


# ══════════════════════════════════════════════════════════════════════════
# TOURNAMENT FIGHT
# ══════════════════════════════════════════════════════════════════════════

@group_only
async def tour_fight(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /tourfight — Start your tournament match against your current bracket opponent.
    Reuses the same duel flow but tagged as a tournament fight.
    """
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    tour_id = player.get("in_tournament")
    if not tour_id:
        await update.message.reply_text("❌ You're not in any active tournament.")
        return

    tour = _get_tour(tour_id)
    if not tour or tour["status"] != "active":
        await update.message.reply_text("❌ Tournament is not active.")
        return

    match = _get_current_match(tour, user_id)
    if not match:
        await update.message.reply_text(
            "📭 No match scheduled for you right now.\n"
            "Wait for the current round to complete!"
        )
        return
    if len(match) == 1:
        await update.message.reply_text("🎉 You have a BYE this round — auto-advance!")
        return

    opponent = match[1] if match[0]["user_id"] == user_id else match[0]
    opp_player = get_player(opponent["user_id"])
    if not opp_player:
        await update.message.reply_text("❌ Opponent not found.")
        return

    # Check if a duel is already active
    existing = col("duels").find_one({
        "$or": [
            {"challenger_id": user_id, "target_id": opponent["user_id"]},
            {"challenger_id": opponent["user_id"], "target_id": user_id},
        ],
        "status": "active"
    })
    if existing:
        await update.message.reply_text(
            f"⚔️ Your tournament match against *{opponent['name']}* is already in progress!",
            parse_mode="Markdown"
        )
        return

    # Insert a tournament-tagged duel
    fe_me  = "🗡️" if player["faction"] == "slayer" else "👹"
    fe_opp = "🗡️" if opp_player["faction"] == "slayer" else "👹"
    level  = match[0]["tour_level"] if match[0]["user_id"] == user_id else match[1]["tour_level"]
    opp_lv = match[1]["tour_level"] if match[0]["user_id"] == user_id else match[0]["tour_level"]

    text = (
        f"🏆 *TOURNAMENT MATCH!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{fe_me} *{player['name']}* (Lv.{level})\n"
        f"        VS\n"
        f"{fe_opp} *{opp_player['name']}* (Lv.{opp_lv})\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎁 Prize pool: {tour.get('prize_pool_yen', 0):,} Yen\n\n"
        f"{fe_opp} *{opp_player['name']}*, do you accept the match?"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept",  callback_data=f"tour_match_accept_{tour_id}_{user_id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"tour_match_decline_{tour_id}_{user_id}"),
    ]])

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


# ══════════════════════════════════════════════════════════════════════════
# PRIZE DISTRIBUTION
# ══════════════════════════════════════════════════════════════════════════

async def _finalize_tournament(update_or_context, context_or_none, tour: dict):
    """Distribute prizes to top 3 and restore all players' levels."""
    tour_id  = tour["tour_id"]
    regs     = tour.get("registrations", [])
    prize    = tour.get("prize_pool_yen", 0)

    # Sort by wins desc, then by elimination order (not eliminated first)
    sorted_players = sorted(regs, key=lambda r: (not r.get("eliminated"), r.get("wins", 0)), reverse=True)
    top3 = sorted_players[:3]

    results_text = "🏆 *TOURNAMENT RESULTS*\n━━━━━━━━━━━━━━━━━━━━━\n"
    medals       = ["🥇", "🥈", "🥉"]
    stored_results = {}

    for i, r in enumerate(top3):
        uid   = r["user_id"]
        place = i + 1
        share = int(prize * PRIZE_SPLIT.get(place, 0))
        if share > 0:
            col("players").update_one({"user_id": uid}, {"$inc": {"yen": share}})
        stored_results[str(place)] = uid
        results_text += f"{medals[i]} *{r['name']}* — +{share:,} Yen\n"

    # Restore all players to their normal state
    for r in regs:
        uid = r["user_id"]
        update_player(uid,
            in_tournament       = None,
            tour_level_override = None,
        )

    _update_tour(tour_id,
        status     = "ended",
        results    = stored_results,
        ended_at   = datetime.now(),
    )

    results_text += (
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Total Prize Pool: {prize:,} Yen distributed!\n"
        f"🎉 Thanks for participating!"
    )

    msg = update_or_context
    if hasattr(msg, "message"):
        await msg.message.reply_text(results_text, parse_mode="Markdown")
    else:
        chat_id = tour.get("chat_id")
        if chat_id and context_or_none:
            await context_or_none.bot.send_message(chat_id, results_text, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════
# CALLBACK ROUTER
# ══════════════════════════════════════════════════════════════════════════

async def tournament_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all tour_* callbacks."""
    query   = update.callback_query
    data    = query.data
    user_id = query.from_user.id

    await query.answer()

    # ── Register ──────────────────────────────────────────────────────────
    if data.startswith("tour_register_"):
        tour_id = data.split("tour_register_")[1]
        await _cb_register(query, user_id, tour_id)

    # ── Info ──────────────────────────────────────────────────────────────
    elif data.startswith("tour_info_"):
        tour_id = data.split("tour_info_")[1]
        tour    = _get_tour(tour_id)
        if not tour:
            await query.answer("❌ Tournament not found.", show_alert=True)
            return
        await query.answer(_tour_embed(tour)[:200], show_alert=True)

    # ── Bracket ───────────────────────────────────────────────────────────
    elif data.startswith("tour_bracket_"):
        tour_id = data.split("tour_bracket_")[1]
        tour    = _get_tour(tour_id)
        if not tour:
            await query.answer("❌ Not found.", show_alert=True)
            return
        bracket = tour.get("bracket", [])
        text = "⚔️ *Current Bracket:*\n"
        for i, m in enumerate(bracket):
            if len(m) == 2:
                text += f"  Match {i+1}: *{m[0]['name']}* vs *{m[1]['name']}*\n"
            else:
                text += f"  Match {i+1}: *{m[0]['name']}* — BYE\n"
        await _safe_edit(query, text or "No matches yet.", parse_mode="Markdown")

    # ── Results ───────────────────────────────────────────────────────────
    elif data.startswith("tour_results_"):
        tour_id = data.split("tour_results_")[1]
        tour    = _get_tour(tour_id)
        if not tour:
            await query.answer("❌ Not found.", show_alert=True)
            return
        results  = tour.get("results", {})
        regs     = {r["user_id"]: r["name"] for r in tour.get("registrations", [])}
        medals   = {"1": "🥇", "2": "🥈", "3": "🥉"}
        text     = f"🏆 *{tour['name']} — Final Results*\n━━━━━━━━━━━━━━━━━━━━━\n"
        for place in ["1", "2", "3"]:
            uid  = results.get(place)
            name = regs.get(uid, "Unknown") if uid else "—"
            prize_share = int(tour.get("prize_pool_yen", 0) * PRIZE_SPLIT.get(int(place), 0))
            text += f"{medals[place]} *{name}* — {prize_share:,} Yen\n"
        await _safe_edit(query, text, parse_mode="Markdown")

    # ── Match accept ──────────────────────────────────────────────────────
    elif data.startswith("tour_match_accept_"):
        parts       = data.split("_")
        # format: tour_match_accept_{tour_id}_{challenger_id}
        tour_id     = parts[3]
        challenger_id = int(parts[4])
        if user_id == challenger_id:
            await query.answer("❌ You can't accept your own match request!", show_alert=True)
            return
        # Start the actual match (handled externally — inform players to use /challenge)
        await _safe_edit(query,
            f"✅ Match accepted! Both players: use `/challenge @opponent` to start the duel!\n"
            f"🏆 This is a *tournament match* — all your skills & arts are available!",
            parse_mode="Markdown"
        )

    # ── Match decline ─────────────────────────────────────────────────────
    elif data.startswith("tour_match_decline_"):
        parts         = data.split("_")
        tour_id       = parts[3]
        challenger_id = int(parts[4])
        if user_id == challenger_id:
            await query.answer("❌ You can't decline your own match!", show_alert=True)
            return
        await _safe_edit(query,
            "❌ Match declined. Admin will be notified.",
            parse_mode="Markdown"
        )

    # ── Fight shortcut ────────────────────────────────────────────────────
    elif data.startswith("tour_fight_"):
        await tour_fight(update, context)


async def _cb_register(query, user_id: int, tour_id: str):
    """Handle registration callback."""
    player = get_player(user_id)
    if not player:
        await query.answer("❌ No character found. Use /start first.", show_alert=True)
        return

    if player.get("banned"):
        await query.answer("❌ You are banned.", show_alert=True)
        return

    tour = _get_tour(tour_id)
    if not tour:
        await query.answer("❌ Tournament not found.", show_alert=True)
        return

    if tour["status"] != "open":
        await query.answer("❌ Registration is closed.", show_alert=True)
        return

    regs = tour.get("registrations", [])

    # Already registered?
    if any(r["user_id"] == user_id for r in regs):
        await query.answer("✅ You're already registered!", show_alert=True)
        return

    # Full?
    if len(regs) >= tour["max_players"]:
        await query.answer("❌ Tournament is full!", show_alert=True)
        return

    # Already in another tournament?
    if player.get("in_tournament"):
        await query.answer("❌ You're already in another tournament!", show_alert=True)
        return

    # Deduct fees
    fee_yen = tour.get("fee_yen", 0)
    fee_sp  = tour.get("fee_sp", 0)

    if player.get("yen", 0) < fee_yen:
        await query.answer(f"❌ Not enough Yen! Need {fee_yen:,} Yen.", show_alert=True)
        return
    if player.get("skill_points", 0) < fee_sp:
        await query.answer(f"❌ Not enough Skill Points! Need {fee_sp} SP.", show_alert=True)
        return

    col("players").update_one(
        {"user_id": user_id},
        {"$inc": {"yen": -fee_yen, "skill_points": -fee_sp}}
    )

    # Add to prize pool
    new_prize = tour.get("prize_pool_yen", 0) + fee_yen
    new_sp    = tour.get("prize_pool_sp",  0) + fee_sp

    regs.append({
        "user_id":   user_id,
        "name":      player.get("name", query.from_user.first_name),
        "faction":   player.get("faction", "slayer"),
        "joined_at": datetime.now().isoformat(),
    })

    _update_tour(tour_id,
        registrations  = regs,
        prize_pool_yen = new_prize,
        prize_pool_sp  = new_sp,
    )

    await query.answer(
        f"✅ Registered! -{fee_yen:,} Yen, -{fee_sp} SP\n"
        f"🎁 Prize pool: {new_prize:,} Yen",
        show_alert=True
    )

    # Update the registration message
    updated_tour = _get_tour(tour_id)
    new_text     = _tour_embed(updated_tour)
    try:
        if query.message.photo:
            await query.edit_message_caption(caption=new_text, parse_mode="Markdown",
                                              reply_markup=_tour_keyboard(tour_id, "open"))
        else:
            await query.edit_message_text(new_text, parse_mode="Markdown",
                                           reply_markup=_tour_keyboard(tour_id, "open"))
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════
# RECORD TOURNAMENT WIN  (call this from challenge.py when duel ends)
# ══════════════════════════════════════════════════════════════════════════

async def on_tournament_duel_end(context: ContextTypes.DEFAULT_TYPE,
                                  winner_id: int, loser_id: int, tour_id: str,
                                  chat_id: int):
    """
    Called by the duel system when a tournament duel ends.
    Records the result, checks for tournament completion.
    """
    result = _record_match_result(tour_id, winner_id, loser_id)

    tour      = _get_tour(tour_id)
    winner_p  = get_player(winner_id)
    loser_p   = get_player(loser_id)
    w_name    = winner_p["name"]  if winner_p else str(winner_id)
    l_name    = loser_p["name"]   if loser_p else str(loser_id)
    prize     = tour.get("prize_pool_yen", 0) if tour else 0

    text = (
        f"🏆 *Tournament Match Result*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ *{w_name}* advances!\n"
        f"💀 *{l_name}* is eliminated.\n"
        f"🎁 Prize pool: {prize:,} Yen\n"
    )

    if result == "ended":
        text += "\n🏁 *Tournament Over! Finalizing results...*"

    await context.bot.send_message(chat_id, text, parse_mode="Markdown")

    if result == "ended" and tour:
        # Build a fake update-like object to pass to _finalize_tournament
        class _FakeUpdate:
            message = None
        await _finalize_tournament(_FakeUpdate(), context, tour)
