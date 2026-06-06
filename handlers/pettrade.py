"""
handlers/pettrade.py — Pet Trade System
========================================

Flow:
  1. Player A replies to Player B's message with /petoffer
     OR uses /petoffer @username
     → Bot sends a trade offer message to B with [✅ Accept] [❌ Decline]

  2. B clicks Accept
     → The SAME message becomes the shared trade screen.
     → Both A and B see their own pet-picker buttons on it.
     → A is notified with a "Pick your pet" button linking back to the screen.

  3. Each player picks their pet via the buttons on the shared screen.
     → As each picks, the screen updates in real time showing both choices.

  4. Once both have picked, [✅ Agree] buttons appear for each side.
     → As each agrees, the screen updates showing who agreed.

  5. When BOTH have agreed → pets are swapped, screen shows success.
     Either player can [❌ Cancel] at any point.

All state lives in MongoDB col("pet_trades") — survives restarts.
The shared trade screen is the offer message in B's DM.
"""

import logging
import math
from datetime import datetime
from bson import ObjectId

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut

from utils.database import col
from utils.guards import dm_only
from config import PETS, PET_RARITY_EMOJI, PET_IMAGES, PET_EVOLUTIONS

log = logging.getLogger(__name__)

TRADE_TIMEOUT_MIN = 15     # minutes before an offer auto-expires (informational)
PETS_PER_PAGE     = 6      # buttons shown per page in pet picker


# ══════════════════════════════════════════════════════════════════════════
# DB HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _create_trade(initiator_id: int, target_id: int,
                  group_chat_id: int | None = None,
                  group_msg_thread: int | None = None) -> str:
    result = col("pet_trades").insert_one({
        "initiator_id":     initiator_id,
        "target_id":        target_id,
        "status":           "pending",   # pending|selecting|done|cancelled|declined
        "initiator_pet":    None,
        "target_pet":       None,
        "initiator_agreed": False,
        "target_agreed":    False,
        "trade_msg_id":     None,        # message id of shared trade screen
        "trade_chat_id":    group_chat_id or target_id,  # where screen lives
        "notify_msg_id":    None,        # message id in initiator's DM
        "group_chat_id":    group_chat_id,   # None = DM flow, int = group flow
        "group_msg_thread": group_msg_thread,
        "i_page":           0,           # initiator pet-picker page
        "t_page":           0,           # target pet-picker page
        "created_at":       datetime.utcnow(),
    })
    return str(result.inserted_id)


def _get_trade(trade_id: str) -> dict | None:
    try:
        doc = col("pet_trades").find_one({"_id": ObjectId(trade_id)})
    except Exception:
        return None
    if not doc:
        return None
    doc["trade_id"] = str(doc.pop("_id"))
    return doc


def _set(trade_id: str, **kwargs):
    col("pet_trades").update_one({"_id": ObjectId(trade_id)}, {"$set": kwargs})


def _get_pets(user_id: int) -> list[dict]:
    """All pets for user, sorted legendary→common then name."""
    docs = list(col("pets").find({"user_id": user_id}, {"_id": 0}))
    order = ["legendary", "epic", "rare", "uncommon", "common"]
    def _key(p):
        name = p["name"]
        # Check evolved pets first, then base pets
        if name in PET_EVOLUTIONS:
            r = PETS.get(PET_EVOLUTIONS[name]["base"], {}).get("rarity", "common")
        elif name in PETS:
            r = PETS[name].get("rarity", "common")
        else:
            r = "common"
        return (order.index(r) if r in order else 99, name)
    return sorted(docs, key=_key)


def _pet_line(pet_name: str, bond_level: int = 0) -> str:
    cfg    = PETS.get(pet_name, {})
    emoji  = cfg.get("emoji", "🐾")
    rarity = cfg.get("rarity", "common")
    re     = PET_RARITY_EMOJI.get(rarity, "⚪")
    stars  = "★" * bond_level + "☆" * (4 - bond_level)
    return f"{emoji} *{pet_name}* {re} `[{stars}]`"


def _pet_card(pet_name: str, bond_level: int = 0, is_initiator: bool = True) -> str:
    """
    Returns a detailed pet stat card for the Visual Link Cable interface.
    Shows image URL, name, level/bond, and key stats.
    """
    cfg = PETS.get(pet_name, {})
    if not cfg:
        return "_Unknown Pet_"
    
    emoji   = cfg.get("emoji", "🐾")
    rarity  = cfg.get("rarity", "common")
    re      = PET_RARITY_EMOJI.get(rarity, "⚪")
    desc    = cfg.get("desc", "")
    passive = cfg.get("passive", {})
    skill   = cfg.get("skill", "None")
    img_url = PET_IMAGES.get(pet_name, "")
    
    # Build stat lines from passives
    stat_lines = []
    for k, v in passive.items():
        label = {
            "xp_pct": "⭐ XP", "yen_pct": "💰 Yen",
            "drop_pct": "🎁 Drop", "atk_pct": "💪 ATK",
            "def_pct": "🛡️ DEF", "hp_pct": "❤️ HP",
            "dodge_pct": "🎯 Dodge",
        }.get(k, k)
        stat_lines.append(f"  {label}: +{int(v*100)}%")
    
    # Bond level as "Level"
    level_display = f"Lv.{bond_level + 1}"
    
    card = [
        f"{'🔵' if is_initiator else '🔴'} *{pet_name}* {re} `{level_display}`",
        f"_{desc}_",
        f"Bond: {'★' * bond_level}{'☆' * (4 - bond_level)}",
    ]
    if stat_lines:
        card.append("*Stats:*")
        card.extend(stat_lines)
    if skill and skill != "None":
        card.append(f"⚔️ Skill: _{skill}_")
    
    return "\n".join(card), img_url


def _bond(user_id: int, pet_name: str) -> int:
    doc = col("pets").find_one({"user_id": user_id, "name": pet_name}, {"bond_level": 1})
    return doc.get("bond_level", 0) if doc else 0


def _is_pet_locked(user_id: int, pet_name: str) -> tuple[bool, str]:
    """
    Check if a pet is locked and cannot be traded.
    Returns (is_locked, reason).
    """
    pet_doc = col("pets").find_one({"user_id": user_id, "name": pet_name})
    if not pet_doc:
        return True, "Pet not found"
    
    # Check if pet is active (being used)
    if pet_doc.get("active", False):
        return True, "Pet is currently active"
    
    # Check if user is in battle
    battle_state = col("battle_state").find_one({"user_id": user_id, "active": 1})
    if battle_state and battle_state.get("in_combat", False):
        return True, "User is in battle"
    
    # Check if pet is being used in a raid
    if battle_state and battle_state.get("raid_active", False):
        return True, "User is in a raid"
    
    return False, ""


# ══════════════════════════════════════════════════════════════════════════
# SCREEN BUILDER  — the single shared trade message
# ══════════════════════════════════════════════════════════════════════════

def _build_screen(trade: dict, i_name: str, t_name: str) -> tuple[str, InlineKeyboardMarkup]:
    """
    Returns (text, markup) for the shared trade screen.
    The message lives in the target's DM and is edited in-place as state changes.
    
    Features Visual Link Cable Interface with side-by-side pet display.
    """
    tid   = trade["trade_id"]
    i_pet = trade["initiator_pet"]
    t_pet = trade["target_pet"]
    i_agr = trade["initiator_agreed"]
    t_agr = trade["target_agreed"]
    i_pg  = trade.get("i_page", 0)
    t_pg  = trade.get("t_page", 0)

    # ── Text ────────────────────────────────────────────────────────────
    lines = [
        "🔗 *VISUAL LINK CABLE - PET TRADE*",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"👤 *{i_name}* offers:",
    ]

    if i_pet:
        bl = _bond(trade["initiator_id"], i_pet)
        card_text, _ = _pet_card(i_pet, bl, is_initiator=True)
        lines.append(card_text)
        lines.append("✅ _Agreed_" if i_agr else "⏳ _Waiting to confirm…_")
    else:
        lines.append("  _⌛ Selecting pet…_")

    lines += ["", "━━━━━━━━━━━━━━━━━━━━━", "", f"👤 *{t_name}* offers:"]

    if t_pet:
        bl = _bond(trade["target_id"], t_pet)
        card_text, _ = _pet_card(t_pet, bl, is_initiator=False)
        lines.append(card_text)
        lines.append("✅ _Agreed_" if t_agr else "⏳ _Waiting to confirm…_")
    else:
        lines.append("  _⌛ Selecting pet…_")

    lines += ["", "━━━━━━━━━━━━━━━━━━━━━"]
    if i_pet and t_pet:
        if i_agr and t_agr:
            lines.append("🎉 _Both agreed — completing trade!_")
        else:
            lines.append("_Both players must click ✅ Agree to confirm._")
    else:
        lines.append("_Both players must select a pet._")

    text = "\n".join(lines)

    # ── Keyboard ────────────────────────────────────────────────────────
    buttons: list[list] = []

    # ── Initiator pet picker (shown until they pick) ──────────────────
    if not i_pet:
        i_pets     = _get_pets(trade["initiator_id"])
        total_i    = len(i_pets)
        max_pg_i   = max(0, math.ceil(total_i / PETS_PER_PAGE) - 1)
        i_pg       = max(0, min(i_pg, max_pg_i))
        page_pets  = i_pets[i_pg * PETS_PER_PAGE : (i_pg + 1) * PETS_PER_PAGE]

        if total_i == 0:
            buttons.append([InlineKeyboardButton(f"❌ {i_name} has no pets", callback_data="noop")])
        else:
            buttons.append([InlineKeyboardButton(
                f"— {i_name}'s pets (pg {i_pg+1}/{max_pg_i+1}) —", callback_data="noop"
            )])
            row = []
            for p in page_pets:
                cfg = PETS.get(p["name"], {})
                em  = cfg.get("emoji", "🐾")
                row.append(InlineKeyboardButton(
                    f"{em} {p['name']}",
                    callback_data=f"pt_pick_{tid}_i_{p['name']}"
                ))
                if len(row) == 2:
                    buttons.append(row); row = []
            if row:
                buttons.append(row)
            # Pagination
            nav = []
            if i_pg > 0:
                nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"pt_ipage_{tid}_{i_pg-1}"))
            if i_pg < max_pg_i:
                nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"pt_ipage_{tid}_{i_pg+1}"))
            if nav:
                buttons.append(nav)

    # ── Target pet picker (shown until they pick) ─────────────────────
    if not t_pet:
        t_pets     = _get_pets(trade["target_id"])
        total_t    = len(t_pets)
        max_pg_t   = max(0, math.ceil(total_t / PETS_PER_PAGE) - 1)
        t_pg       = max(0, min(t_pg, max_pg_t))
        page_pets  = t_pets[t_pg * PETS_PER_PAGE : (t_pg + 1) * PETS_PER_PAGE]

        if total_t == 0:
            buttons.append([InlineKeyboardButton(f"❌ {t_name} has no pets", callback_data="noop")])
        else:
            buttons.append([InlineKeyboardButton(
                f"— {t_name}'s pets (pg {t_pg+1}/{max_pg_t+1}) —", callback_data="noop"
            )])
            row = []
            for p in page_pets:
                cfg = PETS.get(p["name"], {})
                em  = cfg.get("emoji", "🐾")
                row.append(InlineKeyboardButton(
                    f"{em} {p['name']}",
                    callback_data=f"pt_pick_{tid}_t_{p['name']}"
                ))
                if len(row) == 2:
                    buttons.append(row); row = []
            if row:
                buttons.append(row)
            nav = []
            if t_pg > 0:
                nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"pt_tpage_{tid}_{t_pg-1}"))
            if t_pg < max_pg_t:
                nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"pt_tpage_{tid}_{t_pg+1}"))
            if nav:
                buttons.append(nav)

    # ── Change selection buttons (after picking, before agree) ────────
    if i_pet and not i_agr:
        buttons.append([InlineKeyboardButton(
            f"🔁 {i_name}: Change pet", callback_data=f"pt_repick_{tid}_i"
        )])
    if t_pet and not t_agr:
        buttons.append([InlineKeyboardButton(
            f"🔁 {t_name}: Change pet", callback_data=f"pt_repick_{tid}_t"
        )])

    # ── Agree buttons (once both picked) ─────────────────────────────
    if i_pet and t_pet:
        agree_row = []
        if not i_agr:
            agree_row.append(InlineKeyboardButton(
                f"✅ {i_name}: Agree", callback_data=f"pt_agree_{tid}_i"
            ))
        if not t_agr:
            agree_row.append(InlineKeyboardButton(
                f"✅ {t_name}: Agree", callback_data=f"pt_agree_{tid}_t"
            ))
        if agree_row:
            buttons.append(agree_row)

    # ── Cancel always visible ─────────────────────────────────────────
    buttons.append([InlineKeyboardButton("❌ Cancel Trade", callback_data=f"pt_cancel_{tid}")])

    return text, InlineKeyboardMarkup(buttons)


async def _edit(query_or_msg, text: str, **kwargs):
    """Safe edit — ignores 'message not modified' errors."""
    try:
        fn = (query_or_msg.edit_message_text
              if hasattr(query_or_msg, "edit_message_text")
              else query_or_msg.edit_text)
        await fn(text, **kwargs)
    except (BadRequest, TimedOut) as e:
        if "not modified" not in str(e).lower():
            log.error("[pt_edit] %s", e)


async def _refresh(query, trade: dict, context):
    """Reload names and redraw the shared screen."""
    i_pl   = col("players").find_one({"user_id": trade["initiator_id"]}) or {}
    t_pl   = col("players").find_one({"user_id": trade["target_id"]})   or {}
    i_name = i_pl.get("name", "Trader 1")
    t_name = t_pl.get("name", "Trader 2")
    trade  = _get_trade(trade["trade_id"])   # always re-fetch latest
    text, markup = _build_screen(trade, i_name, t_name)

    # Resolve where the shared trade screen lives.
    # Fallback to target_id for old trades that predate the trade_chat_id field.
    trade_chat = trade.get("trade_chat_id") or trade["target_id"]
    trade_msg  = trade.get("trade_msg_id")

    # Are we already editing the trade screen message itself?
    in_trade_chat = (
        query.message is not None and
        query.message.chat_id == trade_chat and
        query.message.message_id == trade_msg
    )

    try:
        await query.answer()   # always ack the button press first
    except Exception:
        pass

    if in_trade_chat:
        # Button is on the trade screen — edit in place
        await _edit(query, text, parse_mode="Markdown", reply_markup=markup)
    else:
        # Button is on a notification message (e.g. initiator's "Pick my pet" DM)
        # Edit the real trade screen via bot API
        try:
            await context.bot.edit_message_text(
                chat_id=trade_chat,
                message_id=trade_msg,
                text=text,
                parse_mode="Markdown",
                reply_markup=markup,
            )
        except Exception as e:
            if "not modified" not in str(e).lower():
                log.error("[pt_refresh remote edit] %s", e)

    return trade, i_name, t_name


# ══════════════════════════════════════════════════════════════════════════
# COMMANDS
# ══════════════════════════════════════════════════════════════════════════

async def petoffer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/petoffer  — reply to someone's message  OR  /petoffer @username
    Works in both DMs and group chats.
    """
    user_id   = update.effective_user.id
    user_name = update.effective_user.full_name
    chat      = update.effective_chat
    is_group  = chat.type in ("group", "supergroup")

    # ── Resolve target: reply-based or @username arg ──────────────────
    target_player = None

    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        if replied_user:
            target_player = col("players").find_one({"user_id": replied_user.id})
            if not target_player:
                await update.message.reply_text(
                    "❌ That user hasn't started the bot yet (`/start`).",
                    parse_mode="Markdown"
                )
                return

    if not target_player:
        if not context.args:
            await update.message.reply_text(
                "❌ *Usage:*\n"
                "• Reply to a player's message with `/petoffer`\n"
                "• Or: `/petoffer @username`",
                parse_mode="Markdown"
            )
            return
        name = context.args[0].lstrip("@")
        target_player = col("players").find_one(
            {"username": {"$regex": f"^{name}$", "$options": "i"}}
        )
        if not target_player:
            await update.message.reply_text("❌ Player not found.")
            return

    target_id = target_player["user_id"]

    if target_id == user_id:
        await update.message.reply_text("⚠️ You can't trade with yourself.")
        return

    # ── Validate both sides have pets ─────────────────────────────────
    my_pets    = _get_pets(user_id)
    their_pets = _get_pets(target_id)

    if not my_pets:
        await update.message.reply_text("❌ You don't have any pets to trade.")
        return
    if not their_pets:
        tname = target_player.get("name", "that player")
        await update.message.reply_text(f"❌ {tname} doesn't have any pets.")
        return

    # ── Cancel stale pending offers from this user ────────────────────
    col("pet_trades").update_many(
        {"initiator_id": user_id, "status": "pending"},
        {"$set": {"status": "cancelled"}}
    )

    # In group: trade screen lives in the group. In DM: it lives in target's DM.
    group_chat_id   = chat.id if is_group else None
    group_msg_thread = update.message.message_thread_id if is_group else None

    trade_id = _create_trade(user_id, target_id, group_chat_id, group_msg_thread)

    markup = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept",  callback_data=f"pt_accept_{trade_id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"pt_decline_{trade_id}"),
    ]])

    tname = target_player.get("name", "them")

    if is_group:
        # Post the trade offer directly in the group so both players can see it
        try:
            sent = await context.bot.send_message(
                chat_id=chat.id,
                message_thread_id=group_msg_thread,
                text=(
                    f"🔄 *PET TRADE OFFER*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 *{user_name}* wants to trade pets with "
                    f"*{tname}*!\n\n"
                    f"Only *{tname}* can accept or decline.\n\n"
                    f"_Offer expires in {TRADE_TIMEOUT_MIN} minutes._"
                ),
                parse_mode="Markdown",
                reply_markup=markup,
            )
            _set(trade_id, trade_msg_id=sent.message_id,
                 trade_chat_id=chat.id)
        except Exception as e:
            log.error("[petoffer group send] %s", e)
            col("pet_trades").delete_one({"_id": ObjectId(trade_id)})
            await update.message.reply_text("❌ Couldn't post trade offer.")
    else:
        # DM flow — send to target's DM
        try:
            sent = await context.bot.send_message(
                chat_id=target_id,
                text=(
                    f"🔄 *PET TRADE OFFER*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 *{user_name}* wants to trade pets with you!\n\n"
                    f"If you accept, a shared trade screen will open — "
                    f"both of you choose which pet to offer, then both confirm.\n\n"
                    f"_Offer expires in {TRADE_TIMEOUT_MIN} minutes._"
                ),
                parse_mode="Markdown",
                reply_markup=markup,
            )
            _set(trade_id, trade_msg_id=sent.message_id,
                 trade_chat_id=target_id)

            await update.message.reply_text(
                f"📨 *Trade offer sent to {tname}!*\n_Waiting for them to accept…_",
                parse_mode="Markdown"
            )
        except Exception as e:
            log.error("[petoffer send] %s", e)
            col("pet_trades").delete_one({"_id": ObjectId(trade_id)})
            await update.message.reply_text(
                "❌ Couldn't DM that player. They may have blocked the bot.\n"
                "Try using `/petoffer` in a group where both of you are members."
            )


async def pettrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias for /petoffer."""
    await petoffer(update, context)


async def petaccept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Legacy stub — real accept is in pt_callback."""
    if update.callback_query:
        await update.callback_query.answer()


# ══════════════════════════════════════════════════════════════════════════
# CENTRAL CALLBACK ROUTER
# ══════════════════════════════════════════════════════════════════════════

async def pt_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Routes all  pt_*  callback data."""
    query   = update.callback_query
    data    = query.data
    user_id = query.from_user.id

    if data == "noop":
        try:
            await query.answer()
        except Exception:
            pass
        return
    elif data.startswith("pt_accept_"):   await _do_accept(query, user_id, data[10:], context)
    elif data.startswith("pt_decline_"):  await _do_decline(query, user_id, data[11:], context)
    elif data.startswith("pt_pick_"):     await _do_pick(query, user_id, data[8:], context)
    elif data.startswith("pt_repick_"):   await _do_repick(query, user_id, data[10:], context)
    elif data.startswith("pt_agree_"):    await _do_agree(query, user_id, data[9:], context)
    elif data.startswith("pt_cancel_"):   await _do_cancel(query, user_id, data[10:], context)
    elif data.startswith("pt_ipage_"):    await _do_page(query, user_id, data[9:], "i", context)
    elif data.startswith("pt_tpage_"):    await _do_page(query, user_id, data[9:], "t", context)
    elif data.startswith("pt_showpick_"): await _do_showpick(query, user_id, data[12:], context)


# ══════════════════════════════════════════════════════════════════════════
# STEP HANDLERS
# ══════════════════════════════════════════════════════════════════════════

async def _do_accept(query, user_id: int, trade_id: str, context):
    try:
        await query.answer()
    except Exception:
        pass
    trade = _get_trade(trade_id)
    if not trade:
        return await query.answer("❌ Trade not found.", show_alert=True)
    if trade["status"] != "pending":
        return await query.answer("⚠️ This offer is no longer active.", show_alert=True)
    if user_id != trade["target_id"]:
        return await query.answer("❌ This offer isn't for you.", show_alert=True)

    _set(trade_id, status="selecting")
    trade, i_name, t_name = await _refresh(query, trade, context)

    is_group = bool(trade.get("group_chat_id"))

    if is_group:
        # In group mode the trade screen is already visible to everyone;
        # just notify the initiator so they know to look at the group.
        try:
            await context.bot.send_message(
                chat_id=trade["initiator_id"],
                text=(
                    f"✅ *{t_name}* accepted your trade offer!\n\n"
                    f"Go to the group and pick your pet using the buttons on the trade screen."
                ),
                parse_mode="Markdown",
            )
        except Exception as e:
            log.error("[pt_accept group notify] %s", e)
    else:
        # ── DM flow: Notify initiator with a "pick my pet" shortcut ──────────
        try:
            sent = await context.bot.send_message(
                chat_id=trade["initiator_id"],
                text=(
                    f"✅ *{t_name}* accepted your trade offer!\n\n"
                    f"The shared trade screen is now open in their DMs.\n"
                    f"Tap below to choose which pet you want to offer."
                ),
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🐾 Pick my pet", callback_data=f"pt_showpick_{trade_id}")
                ]])
            )
            _set(trade_id, notify_msg_id=sent.message_id)
        except Exception as e:
            log.error("[pt_accept notify] %s", e)


async def _do_decline(query, user_id: int, trade_id: str, context):
    try:
        await query.answer()
    except Exception:
        pass
    trade = _get_trade(trade_id)
    if not trade:
        return await query.answer("❌ Trade not found.", show_alert=True)
    if user_id != trade["target_id"]:
        return await query.answer("❌ Not your offer.", show_alert=True)

    t_pl   = col("players").find_one({"user_id": user_id}) or {}
    t_name = t_pl.get("name", "The other player")

    _set(trade_id, status="declined")
    await _edit(query, "❌ *You declined the pet trade offer.*", parse_mode="Markdown")

    try:
        await context.bot.send_message(
            chat_id=trade["initiator_id"],
            text=f"❌ *{t_name}* declined your pet trade offer.",
            parse_mode="Markdown"
        )
    except Exception as e:
        log.error("[pt_decline notify] %s", e)


async def _do_pick(query, user_id: int, rest: str, context):
    """rest = '{trade_id}_{side}_{pet_name}'  — trade_id is 24 hex chars."""
    try:
        await query.answer()
    except Exception:
        pass
    trade_id = rest[:24]
    side     = rest[25]          # 'i' or 't'
    pet_name = rest[27:]         # everything after '{id}_{side}_'

    trade = _get_trade(trade_id)
    if not trade:
        return await query.answer("❌ Trade not found.", show_alert=True)
    if trade["status"] != "selecting":
        return await query.answer("⚠️ Trade is not active.", show_alert=True)

    expected_id = trade["initiator_id"] if side == "i" else trade["target_id"]
    if user_id != expected_id:
        return await query.answer("❌ Those aren't your pets to pick.", show_alert=True)

    # Can't re-pick after agreeing
    if side == "i" and trade["initiator_agreed"]:
        return await query.answer("⚠️ Already agreed — cancel to restart.", show_alert=True)
    if side == "t" and trade["target_agreed"]:
        return await query.answer("⚠️ Already agreed — cancel to restart.", show_alert=True)

    # Anti-scam: Check if pet is locked (in battle, active, etc.)
    is_locked, lock_reason = _is_pet_locked(user_id, pet_name)
    if is_locked:
        return await query.answer(f"❌ Cannot trade: {lock_reason}", show_alert=True)

    if not col("pets").find_one({"user_id": user_id, "name": pet_name}):
        return await query.answer(f"❌ You don't own {pet_name}.", show_alert=True)

    if side == "i":
        _set(trade_id, initiator_pet=pet_name, initiator_agreed=False)
    else:
        _set(trade_id, target_pet=pet_name, target_agreed=False)

    trade, i_name, t_name = await _refresh(query, _get_trade(trade_id), context)

    # Ping the other side if they still need to pick
    other_id    = trade["target_id"]   if side == "i" else trade["initiator_id"]
    other_pet   = trade["target_pet"]  if side == "i" else trade["initiator_pet"]
    picker_name = i_name               if side == "i" else t_name
    if not other_pet:
        try:
            await context.bot.send_message(
                chat_id=other_id,
                text=f"🔔 *{picker_name}* selected their pet! Choose yours on the trade screen.",
                parse_mode="Markdown"
            )
        except Exception:
            pass


async def _do_repick(query, user_id: int, rest: str, context):
    """Reset a player's pet selection so they can pick again."""
    try:
        await query.answer()
    except Exception:
        pass
    trade_id = rest[:24]
    side     = rest[25]

    trade = _get_trade(trade_id)
    if not trade:
        return await query.answer("❌ Trade not found.", show_alert=True)
    if trade["status"] != "selecting":
        return await query.answer("⚠️ Trade not active.", show_alert=True)

    expected_id = trade["initiator_id"] if side == "i" else trade["target_id"]
    if user_id != expected_id:
        return await query.answer("❌ Not your side.", show_alert=True)

    if side == "i":
        _set(trade_id, initiator_pet=None, initiator_agreed=False)
    else:
        _set(trade_id, target_pet=None, target_agreed=False)

    await _refresh(query, _get_trade(trade_id), context)


async def _do_page(query, user_id: int, rest: str, side: str, context):
    """Handle pet-picker pagination.  rest = '{trade_id}_{page_num}'"""
    try:
        await query.answer()
    except Exception:
        pass
    trade_id = rest[:24]
    page     = int(rest[25:])

    trade = _get_trade(trade_id)
    if not trade:
        return await query.answer("❌ Trade not found.", show_alert=True)
    if trade["status"] != "selecting":
        return await query.answer("⚠️ Trade not active.", show_alert=True)

    # Only the correct player can page their own picker
    expected_id = trade["initiator_id"] if side == "i" else trade["target_id"]
    if user_id != expected_id:
        return await query.answer("❌ Not your picker.", show_alert=True)

    if side == "i":
        _set(trade_id, i_page=page)
    else:
        _set(trade_id, t_page=page)

    await _refresh(query, _get_trade(trade_id), context)


async def _do_agree(query, user_id: int, rest: str, context):
    """rest = '{trade_id}_{side}'"""
    trade_id = rest[:24]
    side     = rest[25:]

    try:
        await query.answer()
    except Exception:
        pass

    trade = _get_trade(trade_id)
    if not trade:
        return await query.answer("❌ Trade not found.", show_alert=True)
    if trade["status"] not in ("selecting",):
        return await query.answer("⚠️ Trade not active.", show_alert=True)

    expected_id = trade["initiator_id"] if side == "i" else trade["target_id"]
    if user_id != expected_id:
        return await query.answer("❌ Not your side.", show_alert=True)

    if not trade["initiator_pet"] or not trade["target_pet"]:
        return await query.answer("⚠️ Both players must pick a pet first.", show_alert=True)

    # Anti-scam: Re-verify pets are still tradable before agreeing
    i_pet = trade["initiator_pet"]
    t_pet = trade["target_pet"]

    if side == "i":
        is_locked, lock_reason = _is_pet_locked(user_id, i_pet)
        if is_locked:
            _set(trade_id, initiator_pet=None, initiator_agreed=False)
            return await query.answer(f"❌ Pet locked: {lock_reason}", show_alert=True)
    else:
        is_locked, lock_reason = _is_pet_locked(user_id, t_pet)
        if is_locked:
            _set(trade_id, target_pet=None, target_agreed=False)
            return await query.answer(f"❌ Pet locked: {lock_reason}", show_alert=True)

    # Atomically set agreed=True only if trade is still "selecting"
    # This prevents a stale agree from firing after a cancel
    if side == "i":
        result = col("pet_trades").update_one(
            {"_id": ObjectId(trade_id), "status": "selecting", "initiator_agreed": False},
            {"$set": {"initiator_agreed": True}}
        )
    else:
        result = col("pet_trades").update_one(
            {"_id": ObjectId(trade_id), "status": "selecting", "target_agreed": False},
            {"$set": {"target_agreed": True}}
        )

    if result.modified_count == 0:
        # Already agreed or trade state changed — just refresh the screen silently
        trade = _get_trade(trade_id)
        if not trade or trade["status"] not in ("selecting", "executing", "done"):
            return
        if trade["status"] in ("executing", "done"):
            return  # _execute already running or done, screen will update
    
    trade = _get_trade(trade_id)

    if trade["initiator_agreed"] and trade["target_agreed"]:
        # Atomically claim the trade for execution — prevents double-execution race condition
        # Only ONE of the two concurrent agree clicks will succeed this update.
        claimed = col("pet_trades").find_one_and_update(
            {"_id": ObjectId(trade_id), "status": "selecting",
             "initiator_agreed": True, "target_agreed": True},
            {"$set": {"status": "executing"}},
        )
        if not claimed:
            # Another agree click already claimed it — do nothing, screen will update shortly
            return
        trade = _get_trade(trade_id)
        await _execute(trade, context)
        # Edit the trade screen to show success
        trade_chat = trade.get("trade_chat_id") or trade["target_id"]
        trade_msg  = trade.get("trade_msg_id")
        i_pl   = col("players").find_one({"user_id": trade["initiator_id"]}) or {}
        t_pl   = col("players").find_one({"user_id": trade["target_id"]})   or {}
        i_name = i_pl.get("name", "Trader 1")
        t_name = t_pl.get("name", "Trader 2")
        i_cfg  = PETS.get(trade["initiator_pet"], {})
        t_cfg  = PETS.get(trade["target_pet"], {})
        success = (
            f"🎉 *PET TRADE COMPLETE!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 *{i_name}* gave: {i_cfg.get('emoji','🐾')} *{trade['initiator_pet']}*\n"
            f"👤 *{t_name}* gave: {t_cfg.get('emoji','🐾')} *{trade['target_pet']}*\n\n"
            f"✅ _Pets swapped successfully! Use /pets to see your stable._"
        )
        try:
            await context.bot.edit_message_text(
                chat_id=trade_chat,
                message_id=trade_msg,
                text=success,
                parse_mode="Markdown",
            )
        except Exception as e:
            if "not modified" not in str(e).lower():
                log.error("[pt_agree execute edit] %s", e)
    else:
        # Redraw the trade screen via bot API directly — don't rely on query.message location
        i_pl   = col("players").find_one({"user_id": trade["initiator_id"]}) or {}
        t_pl   = col("players").find_one({"user_id": trade["target_id"]})   or {}
        i_name = i_pl.get("name", "Trader 1")
        t_name = t_pl.get("name", "Trader 2")
        text, markup = _build_screen(trade, i_name, t_name)
        trade_chat = trade.get("trade_chat_id") or trade["target_id"]
        trade_msg  = trade.get("trade_msg_id")
        try:
            await context.bot.edit_message_text(
                chat_id=trade_chat,
                message_id=trade_msg,
                text=text,
                parse_mode="Markdown",
                reply_markup=markup,
            )
        except Exception as e:
            if "not modified" not in str(e).lower():
                log.error("[pt_agree refresh] %s", e)

        agreer_name = i_name if side == "i" else t_name
        other_id    = trade["target_id"] if side == "i" else trade["initiator_id"]
        try:
            await context.bot.send_message(
                chat_id=other_id,
                text=f"🔔 *{agreer_name}* agreed to the trade!\nClick ✅ Agree on the screen to complete it.",
                parse_mode="Markdown"
            )
        except Exception:
            pass


async def _do_cancel(query, user_id: int, trade_id: str, context):
    try:
        await query.answer()
    except Exception:
        pass
    trade = _get_trade(trade_id)
    if not trade:
        return await query.answer("❌ Trade not found.", show_alert=True)
    if trade["status"] not in ("pending", "selecting"):
        return await query.answer("⚠️ Trade already finished.", show_alert=True)
    if user_id not in (trade["initiator_id"], trade["target_id"]):
        return await query.answer("❌ You're not part of this trade.", show_alert=True)

    pl     = col("players").find_one({"user_id": user_id}) or {}
    c_name = pl.get("name", "Someone")

    _set(trade_id, status="cancelled")
    await _edit(query, f"❌ *Trade cancelled by {c_name}.*", parse_mode="Markdown")

    other_id = trade["target_id"] if user_id == trade["initiator_id"] else trade["initiator_id"]
    try:
        await context.bot.send_message(
            chat_id=other_id,
            text=f"❌ *{c_name}* cancelled the pet trade.",
            parse_mode="Markdown"
        )
    except Exception:
        pass


async def _do_showpick(query, user_id: int, trade_id: str, context):
    """
    Initiator tapped 'Pick my pet' from their notification.
    Edit their notification message into a personal pet picker.
    """
    try:
        await query.answer()
    except Exception:
        pass
    trade = _get_trade(trade_id)
    if not trade or trade["status"] != "selecting":
        return await query.answer("⚠️ Trade no longer active.", show_alert=True)
    if user_id != trade["initiator_id"]:
        return await query.answer("❌ Not your trade.", show_alert=True)
    if trade["initiator_pet"]:
        return await query.answer("✅ You already picked a pet!", show_alert=True)

    pets   = _get_pets(user_id)
    pg     = trade.get("i_page", 0)
    max_pg = max(0, math.ceil(len(pets) / PETS_PER_PAGE) - 1)
    pg     = max(0, min(pg, max_pg))
    page_pets = pets[pg * PETS_PER_PAGE : (pg + 1) * PETS_PER_PAGE]

    buttons = []
    row = []
    for p in page_pets:
        cfg = PETS.get(p["name"], {})
        em  = cfg.get("emoji", "🐾")
        row.append(InlineKeyboardButton(
            f"{em} {p['name']}", callback_data=f"pt_pick_{trade_id}_i_{p['name']}"
        ))
        if len(row) == 2:
            buttons.append(row); row = []
    if row:
        buttons.append(row)

    nav = []
    if pg > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"pt_ipage_{trade_id}_{pg-1}"))
    if pg < max_pg:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"pt_ipage_{trade_id}_{pg+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("❌ Cancel Trade", callback_data=f"pt_cancel_{trade_id}")])

    await _edit(
        query,
        f"🐾 *Pick the pet you want to offer:*\n"
        f"_(Page {pg+1}/{max_pg+1} — {len(pets)} pets total)_\n\n"
        f"_Your pick will appear on the shared trade screen._",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )


# ══════════════════════════════════════════════════════════════════════════
# TRADE EXECUTION
# ══════════════════════════════════════════════════════════════════════════

async def _execute(trade: dict, context):
    """Swap pets between both players. Screen update is handled by caller."""
    i_id     = trade["initiator_id"]
    t_id     = trade["target_id"]
    i_pet    = trade["initiator_pet"]
    t_pet    = trade["target_pet"]
    trade_id = trade["trade_id"]

    # Fetch full docs (no projection) so _id is available for stable atomic updates
    i_doc = col("pets").find_one({"user_id": i_id, "name": i_pet}, {"_id": 1, "user_id": 1, "name": 1, "active": 1})
    t_doc = col("pets").find_one({"user_id": t_id, "name": t_pet}, {"_id": 1, "user_id": 1, "name": 1, "active": 1})

    trade_chat = trade.get("trade_chat_id") or t_id
    trade_msg  = trade.get("trade_msg_id")

    async def _fail(msg: str):
        _set(trade_id, status="cancelled")
        try:
            await context.bot.edit_message_text(
                chat_id=trade_chat, message_id=trade_msg,
                text=msg, parse_mode="Markdown",
            )
        except Exception:
            pass

    if not i_doc or not t_doc:
        await _fail(
            "❌ *Trade failed* — one or both pets could not be found.\n"
            "_They may have been released or traded elsewhere._"
        )
        return False

    # Duplicate-name clash guard — check BEFORE touching anything
    # Exclude the pets being traded themselves from the clash check
    if col("pets").find_one({"user_id": i_id, "name": t_pet, "_id": {"$ne": t_doc["_id"]}}):
        await _fail(f"❌ Trade failed — you already own a *{t_pet}*!")
        return False
    if col("pets").find_one({"user_id": t_id, "name": i_pet, "_id": {"$ne": i_doc["_id"]}}):
        await _fail(f"❌ Trade failed — the other player already owns a *{i_pet}*!")
        return False

    was_i_active = i_doc.get("active", False)
    was_t_active = t_doc.get("active", False)

    # ── Atomic swap using _id — never use (user_id + name) after ownership changes ──
    # Initiator's pet → target player (always set active=False; target manages their own active)
    col("pets").update_one(
        {"_id": i_doc["_id"]},
        {"$set": {"user_id": t_id, "active": False}}
    )
    # Target's pet → initiator player (preserve initiator's active status if they traded active pet)
    col("pets").update_one(
        {"_id": t_doc["_id"]},
        {"$set": {"user_id": i_id, "active": was_i_active}}
    )

    # ── After swap, fix active pet state for both players ──
    # At this point:
    #   i_doc["_id"] = initiator's old pet, now owned by target (active=False)
    #   t_doc["_id"] = target's old pet, now owned by initiator (active=was_i_active)

    # Fix initiator: if they traded away their active pet, activate the received one
    if was_i_active and not was_t_active:
        col("pets").update_one({"_id": t_doc["_id"]}, {"$set": {"active": True}})

    # Fix target: if they traded away their active pet, find another pet to activate
    if was_t_active:
        # Look for any of target's remaining pets (excluding the one just received)
        nxt = col("pets").find_one({
            "user_id": t_id,
            "active": False,
            "_id": {"$ne": i_doc["_id"]}   # exclude the pet we just gave them
        })
        if nxt:
            col("pets").update_one({"_id": nxt["_id"]}, {"$set": {"active": True}})
        else:
            # The only pet target now has is the received one — activate it
            col("pets").update_one({"_id": i_doc["_id"]}, {"$set": {"active": True}})

    _set(trade_id, status="done")

    i_pl   = col("players").find_one({"user_id": i_id}) or {}
    t_pl   = col("players").find_one({"user_id": t_id}) or {}
    i_cfg  = PETS.get(i_pet, {})
    t_cfg  = PETS.get(t_pet, {})

    # Notify initiator via DM
    try:
        await context.bot.send_message(
            chat_id=i_id,
            text=(
                f"🎉 *Pet trade complete!*\n\n"
                f"You gave: {i_cfg.get('emoji','🐾')} *{i_pet}*\n"
                f"You received: {t_cfg.get('emoji','🐾')} *{t_pet}*\n\n"
                f"Use /pets to view your stable!"
            ),
            parse_mode="Markdown"
        )
    except Exception as e:
        log.error("[pt_execute notify i] %s", e)

    # Notify target via DM (only if trade screen is NOT in their DM, i.e. group trade)
    if trade.get("group_chat_id"):
        try:
            await context.bot.send_message(
                chat_id=t_id,
                text=(
                    f"🎉 *Pet trade complete!*\n\n"
                    f"You gave: {t_cfg.get('emoji','🐾')} *{t_pet}*\n"
                    f"You received: {i_cfg.get('emoji','🐾')} *{i_pet}*\n\n"
                    f"Use /pets to view your stable!"
                ),
                parse_mode="Markdown"
            )
        except Exception as e:
            log.error("[pt_execute notify t] %s", e)

    return True


# ── alias kept for backward compat ──────────────────────────────────────
async def pt_showpick_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await pt_callback(update, context)
