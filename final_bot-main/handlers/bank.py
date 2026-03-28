from telegram import Update
from telegram.ext import ContextTypes

from config import BANK_LEVELS
from handlers.admin import has_admin_access
from utils.database import col, ensure_bank, get_bank, get_player, update_player
from utils.guards import dm_only


def _get_display_bank_doc(user_id: int) -> dict:
    ensure_bank(user_id)
    return get_bank(user_id) or {}


@dm_only
async def bank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found.")
        return

    b = _get_display_bank_doc(user_id)
    lvl = b.get("bank_level", 1)
    bal = int(b.get("balance", 0) or 0)
    limit = 999999999

    await update.message.reply_text(
        f"*DEMON SLAYER BANK*\n"
        f"---------------------\n"
        f"Level: *{lvl}*\n"
        f"Balance: *{bal:,} Yen*\n"
        f"Limit: *{limit:,} Yen*\n"
        f"Wallet: *{player['yen']:,} Yen*\n"
        f"---------------------\n"
        f"`/deposit [amount]` - Deposit Yen\n"
        f"`/withdraw [amount]` - Withdraw\n"
        f"`/bankupgrade` - Upgrade bank level",
        parse_mode="Markdown",
    )


@dm_only
async def deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/deposit [amount]`", parse_mode="Markdown")
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return
    if player["yen"] < amount:
        await update.message.reply_text(
            f"Not enough Yen. You have *{player['yen']:,} Yen*",
            parse_mode="Markdown",
        )
        return

    ensure_bank(user_id)
    b = get_bank(user_id) or {}
    limit = 999999999

    if int(b.get("balance", 0) or 0) + amount > limit:
        await update.message.reply_text(f"Bank limit is *{limit:,} Yen*.", parse_mode="Markdown")
        return

    update_player(user_id, yen=player["yen"] - amount)
    col("bank_accounts").update_one(
        {"user_id": user_id},
        {"$inc": {"balance": amount}},
    )

    new_balance = int(b.get("balance", 0) or 0) + amount
    new_wallet = player["yen"] - amount
    await update.message.reply_text(
        f"*Deposit successful*\n\n"
        f"Deposited: *{amount:,} Yen*\n"
        f"Balance: *{new_balance:,} Yen*\n"
        f"Wallet: *{new_wallet:,} Yen*",
        parse_mode="Markdown",
    )


@dm_only
async def withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/withdraw [amount]`", parse_mode="Markdown")
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return

    b = _get_display_bank_doc(user_id)
    balance = int(b.get("balance", 0) or 0)
    if balance < amount:
        await update.message.reply_text(
            f"Only *{balance:,} Yen* is in the bank.",
            parse_mode="Markdown",
        )
        return

    update_player(user_id, yen=player["yen"] + amount)
    col("bank_accounts").update_one({"user_id": user_id}, {"$inc": {"balance": -amount}})
    await update.message.reply_text(
        f"*Withdrew {amount:,} Yen*\n\n"
        f"Balance: *{balance - amount:,} Yen*\n"
        f"Wallet: *{player['yen'] + amount:,} Yen*",
        parse_mode="Markdown",
    )


@dm_only
async def bankupgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found.")
        return

    b = _get_display_bank_doc(user_id)
    lvl = b.get("bank_level", 1)
    if lvl >= len(BANK_LEVELS):
        await update.message.reply_text("*Bank is already at max level.*", parse_mode="Markdown")
        return

    cost = BANK_LEVELS[lvl].get("upgrade_cost", 10000)
    if player["yen"] < cost:
        await update.message.reply_text(
            f"Need *{cost:,} Yen* to upgrade. You have *{player['yen']:,} Yen*",
            parse_mode="Markdown",
        )
        return

    update_player(user_id, yen=player["yen"] - cost)
    col("bank_accounts").update_one({"user_id": user_id}, {"$inc": {"bank_level": 1}})
    await update.message.reply_text(
        f"*BANK UPGRADED!*\n\n"
        f"Level: *{lvl}* -> *{lvl + 1}*\n"
        f"Cost: *{cost:,} Yen*",
        parse_mode="Markdown",
    )


async def banktax(update: Update, context: ContextTypes.DEFAULT_TYPE):
    admin_id = update.effective_user.id
    if not has_admin_access(admin_id):
        return

    await update.message.reply_text(
        "Bank tax is disabled now.\nOnly the World Bank uses tax.",
        parse_mode="Markdown",
    )
