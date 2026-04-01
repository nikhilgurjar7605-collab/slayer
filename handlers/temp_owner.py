"""
handlers/temp_owner.py
─────────────────────
Temp-Owner system for Demon Slayer RPG Bot.

A Temp Owner has FULL owner-level power over the bot for a limited
duration set by the real owner.  When the session expires (or is
revoked), they drop back to a normal player automatically.

Commands (owner only):
  /addtempowner @user [duration]  — grant temp-owner for e.g. "2h", "30m", "1d", "1month"
  /revoketo @user                 — revoke immediately
  /listtempowners                 — show all active sessions

Internal helpers:
  is_temp_owner(user_id)  → bool
  has_owner_level(user_id) → bool   (real owner OR active temp owner)
"""

from datetime import datetime, timedelta
import re
from typing import Dict, Optional

from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_ID
from utils.database import col, get_player
from handlers.logs import log_action


# ─────────────────────────────────────────────────────────────────
#  Internal helpers
# ─────────────────────────────────────────────────────────────────

def _get_temp_owner_doc(user_id: int) -> Optional[Dict]:
    """Retrieve temp owner document, deleting expired ones."""
    doc = col("temp_owners").find_one({"user_id": user_id})
    if not doc:
        return None
    expires = doc.get("expires_at")
    if isinstance(expires, datetime) and expires < datetime.now():
        col("temp_owners").delete_one({"user_id": user_id})
        return None
    return doc


def is_temp_owner(user_id: int) -> bool:
    """Return True if user currently has a valid (non-expired) temp-owner session."""
    return _get_temp_owner_doc(user_id) is not None


def has_owner_level(user_id: int) -> bool:
    """True for real owner OR an active temp owner."""
    if user_id == OWNER_ID:
        return True
    return is_temp_owner(user_id)


def _parse_duration(raw: str) -> Optional[timedelta]:
    """
    Parse a human-readable duration string into a timedelta.
    Accepted formats:
        30m  / 30min  / 30minutes
        2h   / 2hr    / 2hours
        1d   / 1day   / 1days
        1w   / 1week  / 1weeks
        1mo  / 1month / 1months
        e.g. "2h30m" or "1d12h" also supported
    Returns None if unparseable.
    """
    raw = raw.strip().lower()
    total = timedelta()
    pattern = re.findall(r'(\d+)\s*([mhdw]|mo)', raw)
    if not pattern:
        # Try bare number → minutes
        if raw.isdigit():
            return timedelta(minutes=int(raw))
        return None
    for amount, unit in pattern:
        if not unit:
            return None  # Invalid: number without unit (e.g., "2h30")
        amount = int(amount)
        if unit == 'm':
            total += timedelta(minutes=amount)
        elif unit == 'h':
            total += timedelta(hours=amount)
        elif unit == 'd':
            total += timedelta(days=amount)
        elif unit == 'w':
            total += timedelta(weeks=amount)
        elif unit == 'mo':
            # Approximate 1 month = 30 days for simplicity
            total += timedelta(days=amount * 30)
    return total if total.total_seconds() > 0 else None


def _fmt_duration(td: timedelta) -> str:
    """Format timedelta into human-readable string (e.g., "2h 30m")."""
    total_seconds = int(td.total_seconds())
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts = []
    if days >= 30:  # Show months if >= 30 days
        months = days // 30
        days = days % 30
        parts.append(f"{months}mo")
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    return " ".join(parts) or "< 1m"


def _find_player_by_arg(arg: str) -> Optional[Dict]:
    """Find player by username, user_id, or name."""
    arg = str(arg or "").strip()
    if not arg:
        return None
    if arg.startswith("@"):
        return col("players").find_one(
            {"username": {"$regex": f"^{arg.lstrip('@')}$", "$options": "i"}}
        )
    if arg.isdigit():
        return col("players").find_one({"user_id": int(arg)})
    return col("players").find_one({"name": {"$regex": f"^{arg}$", "$options": "i"}})


# ─────────────────────────────────────────────────────────────────
#  Commands
# ─────────────────────────────────────────────────────────────────

async def addtempowner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /addtempowner @user [duration]
    Duration defaults to 1h if omitted.
    Examples:
      /addtempowner @alice 2h
      /addtempowner @bob 30m
      /addtempowner @charlie 1d
      /addtempowner @dave 1month
      /addtempowner @eve 2months
    """
    caller = update.effective_user.id
    if caller != OWNER_ID:
        await update.message.reply_text("❌ Owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "*ADD TEMP OWNER*\n\n"
            "Usage: `/addtempowner @user [duration]`\n\n"
            "Duration examples:\n"
            "  `30m` — 30 minutes\n"
            "  `2h` — 2 hours\n"
            "  `1d` — 1 day\n"
            "  `1w` — 1 week\n"
            "  `1mo` — 1 month (≈30 days)\n"
            "  `2months` — 2 months (≈60 days)\n"
            "  `2h30m` — 2 hours 30 minutes\n\n"
            "Default duration: `1h`",
            parse_mode="Markdown",
        )
        return

    target = _find_player_by_arg(context.args[0])
    if not target:
        await update.message.reply_text(f"❌ Player `{context.args[0]}` not found.", parse_mode="Markdown")
        return

    tid = target["user_id"]
    if tid == OWNER_ID:
        await update.message.reply_text("❌ That's already the owner.")
        return

    # Parse duration
    duration_str = context.args[1] if len(context.args) > 1 else "1h"
    duration = _parse_duration(duration_str)
    if not duration:
        await update.message.reply_text(
            f"❌ Could not parse duration `{duration_str}`.\n"
            "Use formats like `30m`, `2h`, `1d`, `1mo`.",
            parse_mode="Markdown",
        )
        return

    # Cap at 7 days for safety (or 1 month if specified)
    max_duration = timedelta(days=7)
    if duration.total_seconds() > max_duration.total_seconds():
        await update.message.reply_text("❌ Max temp-owner duration is 7 days (or 1 month).")
        return

    expires_at = datetime.now() + duration
    col("temp_owners").update_one(
        {"user_id": tid},
        {"$set": {
            "user_id": tid,
            "name": target.get("name", str(tid)),
            "username": target.get("username"),
            "granted_by": caller,
            "granted_at": datetime.now(),
            "expires_at": expires_at,
            "duration_str": _fmt_duration(duration),
        }},
        upsert=True,
    )

    log_action(
        caller, "addtempowner", tid, target.get("name"),
        f"Duration: {_fmt_duration(duration)} | Expires: {expires_at.strftime('%m/%d %H:%M')}"
    )

    await update.message.reply_text(
        f"✅ *{target['name']}* is now a *Temp Owner* for *{_fmt_duration(duration)}*.\n"
        f"Session expires: `{expires_at.strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
        "They have full owner-level control until then.\n"
        "Use `/revoketo @user` to revoke early.",
        parse_mode="Markdown",
    )

    # Notify target in DM
    try:
        await context.bot.send_message(
            tid,
            f"🔑 *You have been granted Temp Owner access*\n\n"
            f"Duration: *{_fmt_duration(duration)}*\n"
            f"Expires: `{expires_at.strftime('%Y-%m-%d %H:%M:%S')}`\n\n"
            "You have full bot management power while the session is active.\n"
            "_Use this responsibly._",
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def revoketo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /revoketo @user  — immediately revoke a temp-owner session.
    """
    caller = update.effective_user.id
    if caller != OWNER_ID:
        await update.message.reply_text("❌ Owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/revoketo @username`",
            parse_mode="Markdown",
        )
        return

    target = _find_player_by_arg(context.args[0])
    if not target:
        await update.message.reply_text(f"❌ Player `{context.args[0]}` not found.", parse_mode="Markdown")
        return

    tid = target["user_id"]
    result = col("temp_owners").delete_one({"user_id": tid})
    if result.deleted_count == 0:
        await update.message.reply_text(f"⚠️ *{target['name']}* has no active temp-owner session.", parse_mode="Markdown")
        return

    log_action(caller, "revoketo", tid, target.get("name"), "Session revoked by owner")

    await update.message.reply_text(
        f"✅ Temp-owner session for *{target['name']}* has been revoked.",
        parse_mode="Markdown",
    )

    try:
        await context.bot.send_message(
            tid,
            "🔒 *Your Temp Owner session has been revoked* by the owner.",
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def listtempowners(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /listtempowners — show all active temp-owner sessions.
    """
    caller = update.effective_user.id
    if caller != OWNER_ID:
        await update.message.reply_text("❌ Owner only.")
        return

    now = datetime.now()
    docs = list(col("temp_owners").find({"expires_at": {"$gt": now}}).sort("expires_at", 1))

    if not docs:
        await update.message.reply_text("*TEMP OWNERS*\n\nNo active temp-owner sessions.", parse_mode="Markdown")
        return

    lines = ["*ACTIVE TEMP OWNERS*", f"Count: *{len(docs)}*", ""]
    for doc in docs:
        expires = doc.get("expires_at")
        remaining = expires - now if isinstance(expires, datetime) else timedelta()
        granted_at = doc.get("granted_at")
        granted_str = granted_at.strftime("%m/%d %H:%M") if isinstance(granted_at, datetime) else "?"
        lines.append(
            f"👑 *{doc.get('name', '?')}* (`{doc['user_id']}`)\n"
            f"  Granted: `{granted_str}`\n"
            f"  Expires in: *{_fmt_duration(remaining)}*\n"
            f"  (`{expires.strftime('%Y-%m-%d %H:%M:%S') if isinstance(expires, datetime) else '?'}`)"
        )
        lines.append("")

    lines.append("Use `/revoketo @user` to revoke.")
    await update.message.reply_text("\n".join(lines).strip(), parse_mode="Markdown")


async def mytempowner(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /mytempowner — check your own temp-owner session status.
    """
    uid = update.effective_user.id
    doc = _get_temp_owner_doc(uid)
    if not doc:
        await update.message.reply_text("You don't have an active temp-owner session.")
        return

    expires = doc.get("expires_at")
    remaining = expires - datetime.now() if isinstance(expires, datetime) else timedelta()
    await update.message.reply_text(
        f"🔑 *Your Temp Owner Session*\n\n"
        f"Expires: `{expires.strftime('%Y-%m-%d %H:%M:%S') if isinstance(expires, datetime) else '?'}`\n"
        f"Remaining: *{_fmt_duration(remaining)}*",
        parse_mode="Markdown",
    )
