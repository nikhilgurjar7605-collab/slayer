"""
social.py — Player query and SP-gifting commands.

/check [@username | reply]     — View another player's public profile
/givesp @username amount       — Gift SP to another player (costs your own SP)
"""
from telegram import Update
from telegram.ext import ContextTypes

from utils.database import get_player, update_player, col
from utils.helpers import get_level


# ── Helpers ───────────────────────────────────────────────────────────────

def _find_target(update: Update, context):
    """Return target player doc or None. Checks reply > @mention > arg."""
    msg = update.effective_message

    # 1. Reply-to
    if msg.reply_to_message:
        uid = msg.reply_to_message.from_user.id
        return col("players").find_one({"user_id": uid})

    args = context.args or []
    if not args:
        return None

    raw = args[0].lstrip("@")

    # 2. Try numeric user_id
    if raw.isdigit():
        return col("players").find_one({"user_id": int(raw)})

    # 3. Try username (case-insensitive)
    return col("players").find_one({"name": {"$regex": f"^{raw}$", "$options": "i"}})


def _rank_bar(hp, max_hp, length=10):
    filled = int((hp / max(max_hp, 1)) * length)
    return "█" * filled + "░" * (length - filled)


# ── /check ────────────────────────────────────────────────────────────────

async def check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /check [@username | reply]
    Shows a public snapshot of another player — level, faction, rank, stats.
    """
    target = _find_target(update, context)
    if not target:
        await update.message.reply_text(
            "❌ Player not found.\n"
            "Usage: `/check @username` or reply to their message with `/check`",
            parse_mode="Markdown"
        )
        return

    level  = get_level(target.get("xp", 0))
    hp     = target.get("hp", 0)
    max_hp = target.get("max_hp", 1)
    bar    = _rank_bar(hp, max_hp)
    faction_emoji = "🗡️" if target.get("faction") == "slayer" else "👹"
    mark = ""
    if target.get("slayer_mark"):
        mark = " ✨ *Slayer Mark*"
    elif target.get("demon_mark"):
        mark = " 🔴 *Demon Mark*"

    await update.message.reply_text(
        f"👤 *{target['name']}*{mark}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{faction_emoji} Faction: *{target.get('faction', '?').title()}*\n"
        f"📊 Level: *{level}*\n"
        f"🏅 Rank: *{target.get('rank', '?')}* {target.get('rank_kanji', '')}\n"
        f"⭐ XP: *{target.get('xp', 0):,}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"❤️ HP: *{hp:,}/{max_hp:,}*\n"
        f"  `{bar}`\n"
        f"💪 STR: *{target.get('str_stat', 0)}*  "
        f"⚡ SPD: *{target.get('spd', 0)}*  "
        f"🛡️ DEF: *{target.get('def_stat', 0)}*\n"
        f"💠 Skill Points: *{target.get('skill_points', 0)}*\n"
        f"💰 Yen: *{target.get('yen', 0):,}¥*\n"
        f"☠️ Demons Slain: *{target.get('demons_slain', 0):,}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ Style: *{target.get('style', 'None')}*\n"
        f"🗡️ Sword: *{target.get('equipped_sword', 'None')}*",
        parse_mode="Markdown"
    )


# ── /givesp ───────────────────────────────────────────────────────────────

async def givesp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /givesp @username amount
    Gift SP from your pool to another player. Both must have characters.
    Cooldown: once per day per sender (stored as last_givesp_date).
    """
    from datetime import date

    sender_id = update.effective_user.id
    sender    = get_player(sender_id)
    if not sender:
        await update.message.reply_text("❌ You don't have a character yet. Use /start.")
        return

    # Parse args
    args = context.args or []
    # Support: /givesp @name 10  OR reply + /givesp 10
    msg = update.effective_message
    if msg.reply_to_message and len(args) >= 1:
        target = col("players").find_one({"user_id": msg.reply_to_message.from_user.id})
        amount_raw = args[0]
    elif len(args) >= 2:
        target = _find_target(update, context)
        amount_raw = args[-1]
    else:
        await update.message.reply_text(
            "Usage:\n"
            "`/givesp @username amount`\n"
            "or reply to a player's message:\n"
            "`/givesp amount`",
            parse_mode="Markdown"
        )
        return

    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    if target["user_id"] == sender_id:
        await update.message.reply_text("❌ You can't give SP to yourself.")
        return

    try:
        amount = int(amount_raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Amount must be a positive number.")
        return

    # Daily cooldown — one gift per day
    today = str(date.today())
    if sender.get("last_givesp_date") == today:
        await update.message.reply_text(
            "⏳ You've already gifted SP today. Come back tomorrow!",
            parse_mode="Markdown"
        )
        return

    # Cap gift at 10 SP per day
    MAX_GIFT = 10
    if amount > MAX_GIFT:
        await update.message.reply_text(
            f"❌ You can gift at most *{MAX_GIFT} SP* per day.",
            parse_mode="Markdown"
        )
        return

    sender_sp = sender.get("skill_points", 0)
    if sender_sp < amount:
        await update.message.reply_text(
            f"❌ You only have *{sender_sp} SP*. Not enough to gift *{amount} SP*.",
            parse_mode="Markdown"
        )
        return

    # Transfer
    update_player(sender_id, skill_points=sender_sp - amount, last_givesp_date=today)
    update_player(target["user_id"], skill_points=target.get("skill_points", 0) + amount)

    await update.message.reply_text(
        f"✅ Gifted *{amount} SP* to *{target['name']}*!\n"
        f"💠 Your SP remaining: *{sender_sp - amount}*",
        parse_mode="Markdown"
    )
