"""
Maintenance Mode System
========================
/maintenance on|off      — Owner only: toggle maintenance mode
/approveuser @user|id    — Owner only: approve a user to use bot during maintenance
/unapproveuser @user|id  — Owner only: remove a user's maintenance approval
/approvedlist            — Owner only: list all approved users

When maintenance is ON:
- Only the OWNER can use the bot
- Approved users can also use the bot
- Everyone else sees a maintenance message
"""

from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import col
from config import OWNER_ID


# ── Helpers ───────────────────────────────────────────────────────────────

def is_owner(uid: int) -> bool:
    return uid == OWNER_ID


def is_maintenance_on() -> bool:
    doc = col("settings").find_one({"key": "maintenance_mode"})
    return bool(doc and doc.get("value", False))


def is_approved_user(uid: int) -> bool:
    """Check if a user is approved to use the bot during maintenance."""
    return col("maintenance_approved").find_one({"user_id": uid}) is not None


def _find_user_by_arg(arg: str):
    """Find a player by @username or user_id."""
    arg = arg.strip()
    if arg.startswith("@"):
        return col("players").find_one({"username": {"$regex": f"^{arg.lstrip('@')}$", "$options": "i"}})
    elif arg.isdigit():
        return col("players").find_one({"user_id": int(arg)})
    return None


# ── /maintenance ──────────────────────────────────────────────────────────

async def maintenance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ This command is owner only.")
        return

    args = context.args
    if not args or args[0].lower() not in ("on", "off"):
        current = "🔴 ON" if is_maintenance_on() else "🟢 OFF"
        await update.message.reply_text(
            f"⚙️ *Maintenance Mode*\n\n"
            f"Current status: *{current}*\n\n"
            f"Usage:\n"
            f"`/maintenance on` — Enable maintenance mode\n"
            f"`/maintenance off` — Disable maintenance mode\n\n"
            f"Only you and users approved with `/approveuser` can use the bot while maintenance is ON.",
            parse_mode="Markdown"
        )
        return

    new_val = args[0].lower() == "on"
    col("settings").update_one(
        {"key": "maintenance_mode"},
        {"$set": {"key": "maintenance_mode", "value": new_val, "set_at": datetime.now(), "set_by": uid}},
        upsert=True
    )

    if new_val:
        await update.message.reply_text(
            "🔴 *Maintenance Mode ENABLED*\n\n"
            "The bot is now in maintenance mode.\n"
            "Only you and approved users can interact with the bot.\n"
            "Everyone else will see a maintenance message.\n\n"
            "Use `/approveuser @username` to grant access.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "🟢 *Maintenance Mode DISABLED*\n\n"
            "The bot is now back online for all users! ✅",
            parse_mode="Markdown"
        )


# ── /approveuser ──────────────────────────────────────────────────────────

async def approveuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ This command is owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/approveuser @username` or `/approveuser user_id`",
            parse_mode="Markdown"
        )
        return

    player = _find_user_by_arg(context.args[0])
    if not player:
        await update.message.reply_text(
            f"❌ User `{context.args[0]}` not found.\n"
            "Make sure they have started the bot first.",
            parse_mode="Markdown"
        )
        return

    target_id = player["user_id"]
    target_name = player.get("name", "Unknown")

    if target_id == OWNER_ID:
        await update.message.reply_text("⚠️ You're already the owner — no need to approve yourself!")
        return

    col("maintenance_approved").update_one(
        {"user_id": target_id},
        {"$set": {
            "user_id": target_id,
            "name": target_name,
            "username": player.get("username", ""),
            "approved_at": datetime.now(),
            "approved_by": uid
        }},
        upsert=True
    )

    await update.message.reply_text(
        f"✅ *{target_name}* has been approved!\n\n"
        f"They can now use the bot even during maintenance mode.",
        parse_mode="Markdown"
    )


# ── /unapproveuser ────────────────────────────────────────────────────────

async def unapproveuser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ This command is owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/unapproveuser @username` or `/unapproveuser user_id`",
            parse_mode="Markdown"
        )
        return

    player = _find_user_by_arg(context.args[0])
    if not player:
        await update.message.reply_text(
            f"❌ User `{context.args[0]}` not found.",
            parse_mode="Markdown"
        )
        return

    target_id = player["user_id"]
    target_name = player.get("name", "Unknown")

    result = col("maintenance_approved").delete_one({"user_id": target_id})
    if result.deleted_count:
        await update.message.reply_text(
            f"🗑️ *{target_name}*'s maintenance access has been removed.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            f"⚠️ *{target_name}* was not in the approved list.",
            parse_mode="Markdown"
        )


# ── /approvedlist ─────────────────────────────────────────────────────────

async def approvedlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_owner(uid):
        await update.message.reply_text("❌ This command is owner only.")
        return

    approved = list(col("maintenance_approved").find({}))
    status = "🔴 ON" if is_maintenance_on() else "🟢 OFF"

    if not approved:
        await update.message.reply_text(
            f"⚙️ *Maintenance Mode:* {status}\n\n"
            "📋 *Approved Users List*\n\n"
            "No users approved yet.\n"
            "Use `/approveuser @username` to add users.",
            parse_mode="Markdown"
        )
        return

    lines = []
    for i, user in enumerate(approved, 1):
        name = user.get("name", "Unknown")
        uname = f"@{user['username']}" if user.get("username") else f"ID: {user['user_id']}"
        lines.append(f"{i}. *{name}* ({uname})")

    text = (
        f"⚙️ *Maintenance Mode:* {status}\n\n"
        f"📋 *Approved Users* ({len(approved)} total)\n\n"
        + "\n".join(lines)
    )
    await update.message.reply_text(text, parse_mode="Markdown")
