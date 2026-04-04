"""
World Bank - Global SP economy system.

Commands (players):
  /worldbank          - show bank status + your limits
  /worlddeposit sp X  - deposit X SP into bank stock
  /worldwithdraw sp X - withdraw X SP (costs Yen)

Commands (owner/admin):
  /wbaddstock X       - add X SP directly to bank stock
  /wbsetprice X       - set Yen cost per 1 SP withdrawal
  /wbinfo             - full bank stats + transaction log
  /wbevent X @user    - give X SP from tax_pool as event reward
  /wbblackmarket X    - put X SP into blackmarket daily stock at current price

Rules:
  - Minimum level 15 to interact
  - Deposit: max 10 SP/day per player, 100% goes to stock
  - Depositors are rewarded with Yen
  - Withdraw: max 3 SP/day, max 1 SP per transaction, 6h cooldown
"""

from datetime import datetime, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from utils.database import col, get_player, update_player
from utils.helpers import get_level
from utils.guards import dm_only

DEFAULT_SP_PRICE = 25_000
DEPOSIT_YEN_RATE = 1.00
DEPOSIT_DAILY_CAP = 10
WITHDRAW_DAILY_CAP = 100
WITHDRAW_MAX_PER_TXN = 100
WITHDRAW_COOLDOWN_H = 6
MIN_LEVEL = 15


def _get_bank() -> dict:
    doc = col("world_bank").find_one({"_id": "global"})
    if not doc:
        doc = {
            "_id": "global",
            "sp_stock": 0,
            "tax_pool": 0,
            "sp_price": DEFAULT_SP_PRICE,
            "total_deposited": 0,
            "total_withdrawn": 0,
        }
        col("world_bank").insert_one(doc)
    return doc


def _get_wb_player(user_id: int) -> dict:
    doc = col("world_bank_players").find_one({"user_id": user_id})
    if not doc:
        doc = {
            "user_id": user_id,
            "deposited_today": 0,
            "withdrawn_today": 0,
            "last_deposit_day": None,
            "last_withdraw_day": None,
            "last_withdraw_at": None,
            "total_deposited": 0,
            "total_withdrawn": 0,
        }
        col("world_bank_players").insert_one(doc)
    return doc


def _reset_daily(wbp: dict) -> dict:
    today = datetime.utcnow().date().isoformat()
    changed = False

    if wbp.get("last_deposit_day") != today:
        wbp["deposited_today"] = 0
        wbp["last_deposit_day"] = today
        changed = True

    if wbp.get("last_withdraw_day") != today:
        wbp["withdrawn_today"] = 0
        wbp["last_withdraw_day"] = today
        changed = True

    if changed:
        col("world_bank_players").update_one(
            {"user_id": wbp["user_id"]},
            {
                "$set": {
                    "deposited_today": wbp["deposited_today"],
                    "last_deposit_day": wbp["last_deposit_day"],
                    "withdrawn_today": wbp["withdrawn_today"],
                    "last_withdraw_day": wbp["last_withdraw_day"],
                }
            },
            upsert=True,
        )
    return wbp


def _wb_log(user_id: int, action: str, amount: int, details: str = "") -> None:
    col("world_bank_logs").insert_one(
        {
            "user_id": user_id,
            "action": action,
            "amount": amount,
            "details": details,
            "timestamp": datetime.utcnow(),
        }
    )


def _check_eligibility(player: dict, user_id: int) -> str | None:
    level = get_level(player.get("xp", 0))
    if level < MIN_LEVEL:
        return f"Minimum level *{MIN_LEVEL}* required. You are Lv.*{level}*."
    return None


def _is_owner_or_sudo(user_id: int) -> bool:
    from handlers.admin import has_admin_access

    return has_admin_access(user_id)


@dm_only
async def worldbank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found.")
        return

    bank = _get_bank()
    wbp = _reset_daily(_get_wb_player(user_id))
    price = bank.get("sp_price", DEFAULT_SP_PRICE)

    cooldown_str = ""
    last_wd = wbp.get("last_withdraw_at")
    if isinstance(last_wd, str):
        try:
            last_wd = datetime.fromisoformat(last_wd)
        except Exception:
            last_wd = None
    if last_wd:
        next_wd = last_wd + timedelta(hours=WITHDRAW_COOLDOWN_H)
        remaining = next_wd - datetime.utcnow()
        if remaining.total_seconds() > 0:
            h = int(remaining.total_seconds() // 3600)
            m = int((remaining.total_seconds() % 3600) // 60)
            cooldown_str = f"\nNext withdrawal in: *{h}h {m}m*"

    err = _check_eligibility(player, user_id)
    warning = f"\n\nWarning: {err}" if err else ""

    await update.message.reply_text(
        f"*WORLD BANK*\n"
        f"---------------------\n"
        f"SP in stock: *{bank.get('sp_stock', 0):,}*\n"
        f"Price per SP: *{price:,} Yen*\n"
        f"Tax pool: *{bank.get('tax_pool', 0):,} SP*\n"
        f"---------------------\n"
        f"Your deposit today: *{wbp['deposited_today']}/{DEPOSIT_DAILY_CAP} SP*\n"
        f"Your withdraw today: *{wbp['withdrawn_today']}/{WITHDRAW_DAILY_CAP} SP*\n"
        f"Your Yen: *{player.get('yen', 0):,} Yen*\n"
        f"Your SP: *{player.get('skill_points', 0)}*"
        f"{cooldown_str}"
        f"{warning}\n"
        f"---------------------\n"
        f"`/worlddeposit sp [amount]` - Deposit SP\n"
        f"`/worldwithdraw sp [amount]` - Withdraw SP\n\n"
        f"_Deposits go fully to stock | Deposit reward: 1 SP = current SP price in Yen | Min level: {MIN_LEVEL}_",
        parse_mode="Markdown",
    )


@dm_only
async def worlddeposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found.")
        return

    err = _check_eligibility(player, user_id)
    if err:
        await update.message.reply_text(err, parse_mode="Markdown")
        return

    args = context.args
    if not args or len(args) < 2 or args[0].lower() != "sp":
        await update.message.reply_text(
            "Usage: `/worlddeposit sp [amount]`\nExample: `/worlddeposit sp 5`",
            parse_mode="Markdown",
        )
        return

    try:
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return

    current_sp = int(player.get("skill_points", 0) or 0)
    if current_sp < amount:
        await update.message.reply_text(
            f"Not enough SP. You have *{current_sp} SP*.",
            parse_mode="Markdown",
        )
        return

    wbp = _reset_daily(_get_wb_player(user_id))
    dep_remaining = DEPOSIT_DAILY_CAP - int(wbp.get("deposited_today", 0) or 0)
    if amount > dep_remaining:
        await update.message.reply_text(
            f"Daily deposit limit reached.\nYou can deposit *{dep_remaining} more SP* today.",
            parse_mode="Markdown",
        )
        return

    bank = _get_bank()
    price = int(bank.get("sp_price", DEFAULT_SP_PRICE) or DEFAULT_SP_PRICE)
    reward_yen = max(0, int(amount * price * DEPOSIT_YEN_RATE))
    new_yen = int(player.get("yen", 0) or 0) + reward_yen
    new_sp = current_sp - amount

    update_player(user_id, skill_points=new_sp, yen=new_yen)
    col("world_bank").update_one(
        {"_id": "global"},
        {"$inc": {"sp_stock": amount, "total_deposited": amount}},
        upsert=True,
    )
    col("world_bank_players").update_one(
        {"user_id": user_id},
        {"$inc": {"deposited_today": amount, "total_deposited": amount}},
        upsert=True,
    )

    _wb_log(
        user_id,
        "deposit",
        amount,
        f"added {amount} to stock, rewarded {reward_yen} Yen",
    )

    await update.message.reply_text(
        f"*SP DEPOSITED!*\n"
        f"You deposited: *{amount} SP*\n"
        f"Added to bank: *{amount} SP*\n"
        f"Yen reward: *{reward_yen:,} Yen*\n"
        f"Your SP left: *{new_sp}*\n"
        f"Your Yen now: *{new_yen:,} Yen*\n"
        f"Daily remaining: *{dep_remaining - amount}/{DEPOSIT_DAILY_CAP} SP*",
        parse_mode="Markdown",
    )


@dm_only
async def worldwithdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found.")
        return

    err = _check_eligibility(player, user_id)
    if err:
        await update.message.reply_text(err, parse_mode="Markdown")
        return

    args = context.args
    if not args or len(args) < 2 or args[0].lower() != "sp":
        await update.message.reply_text(
            f"Usage: `/worldwithdraw sp [amount]`\nExample: `/worldwithdraw sp 1`\n\n_Max {WITHDRAW_MAX_PER_TXN} SP per transaction_",
            parse_mode="Markdown",
        )
        return

    try:
        amount = int(args[1])
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return

    if amount > WITHDRAW_MAX_PER_TXN:
        await update.message.reply_text(
            f"Max *{WITHDRAW_MAX_PER_TXN} SP* per transaction.",
            parse_mode="Markdown",
        )
        return

    wbp = _reset_daily(_get_wb_player(user_id))
    wdw_remaining = WITHDRAW_DAILY_CAP - int(wbp.get("withdrawn_today", 0) or 0)
    if amount > wdw_remaining:
        await update.message.reply_text(
            f"Daily withdrawal limit reached.\nYou can withdraw *{wdw_remaining} more SP* today.",
            parse_mode="Markdown",
        )
        return

    last_wd = wbp.get("last_withdraw_at")
    if isinstance(last_wd, str):
        try:
            last_wd = datetime.fromisoformat(last_wd)
        except Exception:
            last_wd = None
    if last_wd:
        next_wd = last_wd + timedelta(hours=WITHDRAW_COOLDOWN_H)
        remaining = next_wd - datetime.utcnow()
        if remaining.total_seconds() > 0:
            h = int(remaining.total_seconds() // 3600)
            m = int((remaining.total_seconds() % 3600) // 60)
            await update.message.reply_text(
                f"Withdrawal cooldown.\nNext withdrawal in: *{h}h {m}m*",
                parse_mode="Markdown",
            )
            return

    bank = _get_bank()
    stock = int(bank.get("sp_stock", 0) or 0)
    if stock < amount:
        await update.message.reply_text(
            f"Not enough SP in the World Bank.\nCurrent stock: *{stock} SP*",
            parse_mode="Markdown",
        )
        return

    price = int(bank.get("sp_price", DEFAULT_SP_PRICE) or DEFAULT_SP_PRICE)
    total_cost = price * amount
    current_yen = int(player.get("yen", 0) or 0)
    current_sp = int(player.get("skill_points", 0) or 0)
    if current_yen < total_cost:
        await update.message.reply_text(
            f"Not enough Yen.\n\n"
            f"*{amount} SP* costs *{total_cost:,} Yen*\n"
            f"You have: *{current_yen:,} Yen*\n"
            f"Need: *{total_cost - current_yen:,} Yen* more",
            parse_mode="Markdown",
        )
        return

    new_yen = current_yen - total_cost
    new_sp = current_sp + amount
    update_player(user_id, yen=new_yen, skill_points=new_sp)
    col("world_bank").update_one(
        {"_id": "global"},
        {"$inc": {"sp_stock": -amount, "total_withdrawn": amount}},
        upsert=True,
    )

    now = datetime.utcnow()
    col("world_bank_players").update_one(
        {"user_id": user_id},
        {
            "$inc": {"withdrawn_today": amount, "total_withdrawn": amount},
            "$set": {
                "last_withdraw_at": now.isoformat(),
                "last_withdraw_day": now.date().isoformat(),
            },
        },
        upsert=True,
    )

    _wb_log(user_id, "withdraw", amount, f"paid {total_cost:,} Yen at {price:,} Yen/SP")

    await update.message.reply_text(
        f"*SP WITHDRAWN!*\n"
        f"Withdrawn: *+{amount} SP*\n"
        f"Paid: *{total_cost:,} Yen*\n"
        f"Your SP now: *{new_sp}*\n"
        f"Your Yen left: *{new_yen:,} Yen*\n"
        f"Daily remaining: *{wdw_remaining - amount}/{WITHDRAW_DAILY_CAP} SP*\n"
        f"Next withdrawal: *{WITHDRAW_COOLDOWN_H}h*",
        parse_mode="Markdown",
    )


async def wbaddstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner_or_sudo(user_id):
        await update.message.reply_text("Owner/admin only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/wbaddstock [amount]`", parse_mode="Markdown")
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return

    col("world_bank").update_one({"_id": "global"}, {"$inc": {"sp_stock": amount}}, upsert=True)
    _wb_log(user_id, "admin_addstock", amount, f"added {amount} SP to stock")

    bank = _get_bank()
    await update.message.reply_text(
        f"Added *{amount} SP* to World Bank stock.\n"
        f"Total stock now: *{bank.get('sp_stock', 0)} SP*",
        parse_mode="Markdown",
    )


async def wbsetprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner_or_sudo(user_id):
        await update.message.reply_text("Owner/admin only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/wbsetprice [yen_amount]`", parse_mode="Markdown")
        return

    try:
        price = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid price.")
        return

    if price < 1000:
        await update.message.reply_text("Minimum price is 1,000 Yen.")
        return

    col("world_bank").update_one({"_id": "global"}, {"$set": {"sp_price": price}}, upsert=True)
    _wb_log(user_id, "admin_setprice", price, f"price set to {price:,} Yen/SP")
    await update.message.reply_text(
        f"SP price set to *{price:,} Yen* per SP.",
        parse_mode="Markdown",
    )


async def wbinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner_or_sudo(user_id):
        await update.message.reply_text("Owner/admin only.")
        return

    bank = _get_bank()
    logs = list(col("world_bank_logs").find().sort("timestamp", -1).limit(10))
    log_lines = []
    for lg in logs:
        ts = lg["timestamp"].strftime("%m/%d %H:%M") if hasattr(lg.get("timestamp"), "strftime") else str(lg.get("timestamp", ""))[:16]
        log_lines.append(f"`{ts}` {lg.get('action', '?')} {lg.get('amount', 0)} SP - uid:{lg.get('user_id', '?')}")

    await update.message.reply_text(
        f"*WORLD BANK - ADMIN VIEW*\n"
        f"---------------------\n"
        f"Stock: *{bank.get('sp_stock', 0):,} SP*\n"
        f"Tax pool: *{bank.get('tax_pool', 0):,} SP*\n"
        f"Price/SP: *{bank.get('sp_price', DEFAULT_SP_PRICE):,} Yen*\n"
        f"Total deposited: *{bank.get('total_deposited', 0):,} SP*\n"
        f"Total withdrawn: *{bank.get('total_withdrawn', 0):,} SP*\n"
        f"---------------------\n"
        f"*Recent transactions:*\n"
        + ("\n".join(log_lines) if log_lines else "_None yet_")
        + "\n---------------------\n"
        + "`/wbaddstock [n]` - Add SP to stock\n"
        + "`/wbsetprice [n]` - Set Yen/SP price\n"
        + "`/wbevent [n] @user` - Give tax pool SP as reward\n"
        + "`/wbblackmarket [n]` - Put SP in blackmarket",
        parse_mode="Markdown",
    )


async def wbevent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner_or_sudo(user_id):
        await update.message.reply_text("Owner/admin only.")
        return

    if len(context.args or []) < 2:
        await update.message.reply_text(
            "Usage: `/wbevent [amount] @username`\nGives SP from the tax pool as an event reward.",
            parse_mode="Markdown",
        )
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return

    username = context.args[1].lstrip("@")
    target = col("players").find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
    if not target:
        await update.message.reply_text(f"Player @{username} not found.")
        return

    bank = _get_bank()
    tax_pool = int(bank.get("tax_pool", 0) or 0)
    if tax_pool < amount:
        await update.message.reply_text(
            f"Tax pool only has *{tax_pool} SP*.",
            parse_mode="Markdown",
        )
        return

    col("world_bank").update_one({"_id": "global"}, {"$inc": {"tax_pool": -amount}}, upsert=True)
    col("players").update_one({"user_id": target["user_id"]}, {"$inc": {"skill_points": amount}})
    _wb_log(user_id, "admin_event_reward", amount, f"gave {amount} SP from tax_pool to {target.get('name', target['user_id'])}")

    try:
        await context.bot.send_message(
            chat_id=target["user_id"],
            text=(
                f"*EVENT REWARD!*\n\n"
                f"*+{amount} SP* from the World Bank tax pool.\n"
                f"Rewarded by the game owner."
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass

    await update.message.reply_text(
        f"Gave *{amount} SP* from tax pool to *{target.get('name', username)}*.\n"
        f"Tax pool remaining: *{tax_pool - amount} SP*",
        parse_mode="Markdown",
    )


async def wbblackmarket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner_or_sudo(user_id):
        await update.message.reply_text("Owner/admin only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/wbblackmarket [amount]`", parse_mode="Markdown")
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    if amount <= 0 or amount > 50:
        await update.message.reply_text("Amount must be between 1 and 50.")
        return

    bank = _get_bank()
    tax_pool = int(bank.get("tax_pool", 0) or 0)
    if tax_pool < amount:
        await update.message.reply_text(
            f"Tax pool only has *{tax_pool} SP*.\nUse `/wbaddstock` if needed.",
            parse_mode="Markdown",
        )
        return

    price = int(bank.get("sp_price", DEFAULT_SP_PRICE) or DEFAULT_SP_PRICE)

    col("black_market").delete_many({"item_name": "Skill Point (WB)", "status": "active"})
    col("black_market").insert_one(
        {
            "item_name": "Skill Point (WB)",
            "item_type": "sp",
            "price": price,
            "stock": amount,
            "status": "active",
            "added_by": user_id,
            "added_at": datetime.utcnow(),
            "description": "World Bank SP - use /skilltree to spend",
        }
    )
    col("world_bank").update_one({"_id": "global"}, {"$inc": {"tax_pool": -amount}}, upsert=True)
    _wb_log(user_id, "admin_bm_stock", amount, f"put {amount} SP into blackmarket at {price:,} Yen each")

    await update.message.reply_text(
        f"*{amount} SP* added to Black Market stock.\n"
        f"Price: *{price:,} Yen* each\n"
        f"Available via `/blackmarket`\n"
        f"Tax pool remaining: *{tax_pool - amount} SP*",
        parse_mode="Markdown",
    )
