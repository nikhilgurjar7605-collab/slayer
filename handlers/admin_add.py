from telegram import Update
from telegram.ext import ContextTypes

from handlers.admin import _find_player, has_admin_access
from handlers.logs import log_action
from utils.database import add_item, canonical_item_name, col, update_player


def _resolve_add_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.reply_to_message:
        return col("players").find_one({"user_id": update.message.reply_to_message.from_user.id}), list(context.args or [])
    if context.args:
        return _find_player(context.args[0]), list(context.args[1:])
    return None, []


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_admin_access(update.effective_user.id):
        return

    target, args = _resolve_add_target(update, context)
    if not target or len(args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "`/add @username yen 500`\n"
            "`/add @username exp 1000`\n"
            "`/add @username items Boss Shard 2`\n"
            "or reply to a user with:\n"
            "`/add yen 500`\n"
            "`/add exp 1000`\n"
            "`/add items Boss Shard 2`",
            parse_mode="Markdown",
        )
        return

    mode = args[0].lower()

    if mode == "yen":
        try:
            amount = int(args[1])
        except ValueError:
            await update.message.reply_text("Invalid Yen amount.")
            return
        update_player(target["user_id"], yen=target.get("yen", 0) + amount)
        log_action(update.effective_user.id, "giveyen", target["user_id"], target["name"], f"{amount:,} Yen")
        await update.message.reply_text(f"Added *{amount:,} Yen* to *{target['name']}*.", parse_mode="Markdown")
        return

    if mode == "exp":
        try:
            amount = int(args[1])
        except ValueError:
            await update.message.reply_text("Invalid EXP amount.")
            return
        update_player(target["user_id"], xp=target.get("xp", 0) + amount)
        log_action(update.effective_user.id, "givexp", target["user_id"], target["name"], f"+{amount:,} XP")
        await update.message.reply_text(f"Added *{amount:,} XP* to *{target['name']}*.", parse_mode="Markdown")
        return

    if mode in {"item", "items"}:
        if len(args) < 3:
            await update.message.reply_text("Usage: `/add @user items item_name amount`", parse_mode="Markdown")
            return
        try:
            amount = int(args[-1])
        except ValueError:
            await update.message.reply_text("Item amount must be a number.", parse_mode="Markdown")
            return
        item_name = canonical_item_name(" ".join(args[1:-1]).strip())
        if not item_name:
            await update.message.reply_text("Item name is required.", parse_mode="Markdown")
            return
        if item_name.lower() in {"skill points", "skill point", "skill pts", "skill pt"}:
            current_sp = int(target.get("skill_points", 0) or 0)
            update_player(target["user_id"], skill_points=current_sp + amount)
            log_action(update.effective_user.id, "givesp", target["user_id"], target["name"], f"{amount} SP")
            await update.message.reply_text(
                f"Added *{amount} SP* to *{target['name']}*.",
                parse_mode="Markdown",
            )
            return
        add_item(target["user_id"], item_name, "item", amount)
        log_action(update.effective_user.id, "giveitem", target["user_id"], target["name"], f"{item_name} x{amount}")
        await update.message.reply_text(f"Added *{item_name} x{amount}* to *{target['name']}*.", parse_mode="Markdown")
        return

    await update.message.reply_text("Type must be `yen`, `exp`, or `items`.", parse_mode="Markdown")
