from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from handlers.logs import log_action
from utils.database import col, get_player

MAX_GIVE_PER_DAY = 20

_give_locks: set = set()  # user_ids currently in a /give transaction


async def give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id in _give_locks:
        await update.message.reply_text("Please wait - your previous transfer is still processing.")
        return

    _give_locks.add(user_id)
    try:
        await _give_inner(update, context)
    finally:
        _give_locks.discard(user_id)


async def _give_inner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found. Use /start to create one.")
        return

    if not context.args:
        await update.message.reply_text(
            "*GIVE MENU*\n\n"
            "*Usage:*\n"
            "`/give @username [amount]`\n\n"
            "*Reply shortcut:*\n"
            "`/give [amount]`\n\n"
            "*Examples:*\n"
            "`/give @Tanjiro 500`\n"
            "`/give 250` (while replying)\n\n"
            "*Rules:*\n"
            f"- Max {MAX_GIVE_PER_DAY} Yen transfers per day\n"
            "- Minimum transfer: *10 Yen*\n"
            "- You cannot give more than you have\n\n"
            f"Your Yen: *{player.get('yen', 0):,}*\n\n"
            "*SP note:*\n"
            "Direct SP gifting is disabled.\n"
            "Use `/spbank`, `/spdeposit`, and `/spwithdraw` for the world SP bank.",
            parse_mode="Markdown",
        )
        return

    target = None
    amount_arg = None

    if update.message.reply_to_message:
        replied = update.message.reply_to_message.from_user
        if not replied.is_bot:
            target = col("players").find_one({"user_id": replied.id})
        if context.args:
            amount_arg = context.args[0]
    elif len(context.args) >= 2:
        if context.args[1].lower() == "sp":
            await update.message.reply_text(
                "Direct SP gifting is disabled.\nUse `/spbank`, `/spdeposit`, and `/spwithdraw` instead.",
                parse_mode="Markdown",
            )
            return
        uname = context.args[0].lstrip("@")
        target = col("players").find_one({"username": {"$regex": f"^{uname}$", "$options": "i"}})
        amount_arg = context.args[1]
    else:
        await update.message.reply_text(
            "Usage: `/give @username [amount]`\n"
            "Or reply with `/give [amount]`\n\n"
            "For SP, use `/spbank` instead.",
            parse_mode="Markdown",
        )
        return

    if amount_arg and amount_arg.lower() == "sp":
        await update.message.reply_text(
            "Direct SP gifting is disabled.\nUse `/spbank`, `/spdeposit`, and `/spwithdraw` instead.",
            parse_mode="Markdown",
        )
        return

    if not target:
        await update.message.reply_text("Player not found.")
        return

    target.pop("_id", None)

    if target["user_id"] == user_id:
        await update.message.reply_text("You can't give Yen to yourself.")
        return

    try:
        amount = int(amount_arg)
    except (TypeError, ValueError):
        await update.message.reply_text("Invalid amount. Use a number like `500`.", parse_mode="Markdown")
        return

    if amount < 10:
        await update.message.reply_text("Minimum transfer is *10 Yen*.", parse_mode="Markdown")
        return

    balance = int(player.get("yen", 0) or 0)
    if balance < amount:
        await update.message.reply_text(
            f"*Not enough Yen!*\n\n"
            f"- You want to give: *{amount:,} Yen*\n"
            f"- Your balance: *{balance:,} Yen*",
            parse_mode="Markdown",
        )
        return

    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    transfers_today = col("gift_log").count_documents(
        {
            "from_id": user_id,
            "item_name": "__yen_transfer__",
            "gifted_at": {"$gte": today},
        }
    )
    if transfers_today >= MAX_GIVE_PER_DAY:
        await update.message.reply_text(
            f"*Daily limit reached!*\n\n"
            f"- Max *{MAX_GIVE_PER_DAY}* Yen transfers per day.\n"
            "_Try again tomorrow!_",
            parse_mode="Markdown",
        )
        return

    debit_result = col("players").update_one(
        {"user_id": user_id, "yen": {"$gte": amount}},
        {"$inc": {"yen": -amount}},
    )
    if debit_result.modified_count != 1:
        await update.message.reply_text("Transfer failed. Your balance changed, so please try again.")
        return

    credit_result = col("players").update_one(
        {"user_id": target["user_id"]},
        {"$inc": {"yen": amount}},
    )
    if credit_result.modified_count != 1:
        col("players").update_one({"user_id": user_id}, {"$inc": {"yen": amount}})
        await update.message.reply_text("Transfer failed because the target player could not be updated.")
        return

    sender_after = balance - amount
    target_after = int(target.get("yen", 0) or 0) + amount

    col("gift_log").insert_one(
        {
            "from_id": user_id,
            "to_id": target["user_id"],
            "item_name": "__yen_transfer__",
            "amount": amount,
            "resource": "yen",
            "gifted_at": datetime.now(),
        }
    )

    log_action(
        user_id,
        "give_yen",
        target["user_id"],
        target["name"],
        f"{amount:,} Yen player transfer",
    )

    await update.message.reply_text(
        f"*Yen sent!*\n\n"
        f"Sent *{amount:,} Yen* to *{target['name']}*\n"
        f"Your balance: *{sender_after:,} Yen*\n"
        f"Transfers today: *{transfers_today + 1}/{MAX_GIVE_PER_DAY}*",
        parse_mode="Markdown",
    )

    try:
        await context.bot.send_message(
            chat_id=target["user_id"],
            text=(
                f"*Yen received!*\n\n"
                f"*{player['name']}* sent you *{amount:,} Yen*!\n"
                f"Your balance: *{target_after:,} Yen*"
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass
