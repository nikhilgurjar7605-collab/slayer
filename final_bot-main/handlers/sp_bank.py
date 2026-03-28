import random
import re
from datetime import datetime

from telegram import Update
from telegram.ext import ContextTypes

from handlers.admin import has_admin_access, is_owner
from handlers.logs import log_action
from utils.database import col, get_player
from utils.helpers import get_level

SP_BANK_DOC_ID = "world_sp_bank"
SP_BANK_DEPOSIT_TAX_RATE = 0
SP_BANK_WITHDRAW_PRICE_PER_SP = 100000
SP_BANK_DAILY_WITHDRAW_LIMIT = 3
SP_BANK_MIN_LEVEL = 10
SP_BANK_MIN_ACCOUNT_AGE_DAYS = 7
_DURATION_RE = re.compile(r"^\s*(\d+)\s*(hr|h|m|s)\s*$", re.IGNORECASE)


def _now() -> datetime:
    return datetime.now()


def _today_key(now: datetime | None = None) -> str:
    return (now or _now()).strftime("%Y-%m-%d")


def _parse_duration(text: str) -> tuple[int | None, str | None]:
    match = _DURATION_RE.match(text or "")
    if not match:
        return None, None
    value = int(match.group(1))
    unit = match.group(2).lower()
    if value <= 0:
        return None, None
    if unit in {"hr", "h"}:
        return value * 3600, f"{value} hour(s)"
    if unit == "m":
        return value * 60, f"{value} minute(s)"
    return value, f"{value} second(s)"


def _format_time_left(ends_at: datetime | None) -> str:
    if not ends_at:
        return "Unknown"
    remaining = int((ends_at - _now()).total_seconds())
    if remaining <= 0:
        return "Ending now"
    hours, rem = divmod(remaining, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _get_bank_state() -> dict:
    doc = col("bank_meta").find_one({"_id": SP_BANK_DOC_ID}) or {}
    legacy_taxed_sp = int(doc.get("taxed_sp", 0) or 0)
    if legacy_taxed_sp > 0:
        col("bank_meta").update_one(
            {"_id": SP_BANK_DOC_ID},
            {"$inc": {"available_sp": legacy_taxed_sp, "taxed_sp": -legacy_taxed_sp}},
            upsert=True,
        )
        doc["available_sp"] = int(doc.get("available_sp", 0) or 0) + legacy_taxed_sp
        doc["taxed_sp"] = 0
    return {
        "available_sp": int(doc.get("available_sp", 0) or 0),
        "taxed_sp": int(doc.get("taxed_sp", 0) or 0),
        "reserved_sp": int(doc.get("reserved_sp", 0) or 0),
        "total_deposited": int(doc.get("total_deposited", 0) or 0),
        "total_taxed": int(doc.get("total_taxed", 0) or 0),
        "total_withdrawn": int(doc.get("total_withdrawn", 0) or 0),
        "total_sp_awarded": int(doc.get("total_sp_awarded", 0) or 0),
        "total_yen_burned": int(doc.get("total_yen_burned", 0) or 0),
    }


def _get_user_state(user_id: int) -> dict:
    doc = col("sp_bank_users").find_one({"user_id": user_id}) or {"user_id": user_id}
    today = _today_key()
    if doc.get("withdraw_date") != today:
        doc["daily_withdrawn"] = 0
    doc.setdefault("lifetime_deposit", 0)
    doc.setdefault("lifetime_withdraw", 0)
    doc.setdefault("lifetime_tax_paid", 0)
    doc.setdefault("lifetime_yen_spent", 0)
    return doc


def _is_eligible_for_sp_bank(player: dict) -> tuple[bool, str | None]:
    created_at = player.get("created_at")
    level = get_level(player.get("xp", 0))
    if level < SP_BANK_MIN_LEVEL:
        return False, f"You need to be at least level {SP_BANK_MIN_LEVEL}."
    if not isinstance(created_at, datetime):
        return False, "Your account age could not be verified yet."
    age_days = (_now() - created_at).days
    if age_days < SP_BANK_MIN_ACCOUNT_AGE_DAYS:
        return False, f"Your account must be at least {SP_BANK_MIN_ACCOUNT_AGE_DAYS} days old."
    return True, None


def _reserve_bank_sp(amount: int) -> bool:
    result = col("bank_meta").update_one(
        {"_id": SP_BANK_DOC_ID, "available_sp": {"$gte": amount}},
        {"$inc": {"available_sp": -amount, "reserved_sp": amount}},
        upsert=False,
    )
    return result.modified_count == 1


def _release_reserved_sp(amount: int) -> None:
    if amount <= 0:
        return
    col("bank_meta").update_one(
        {"_id": SP_BANK_DOC_ID},
        {"$inc": {"available_sp": amount, "reserved_sp": -amount}},
        upsert=True,
    )


def _consume_reserved_sp(amount: int) -> None:
    if amount <= 0:
        return
    col("bank_meta").update_one(
        {"_id": SP_BANK_DOC_ID},
        {"$inc": {"reserved_sp": -amount, "total_sp_awarded": amount}},
        upsert=True,
    )


def _get_active_sp_giveaway() -> dict | None:
    doc = col("sp_giveaways").find_one({"status": "active"}, sort=[("created_at", -1)])
    if not doc:
        return None
    doc.pop("_id", None)
    return doc


def _get_active_tournament() -> dict | None:
    doc = col("sp_tournaments").find_one({"status": "active"}, sort=[("created_at", -1)])
    if not doc:
        return None
    doc.pop("_id", None)
    return doc


async def _announce(chat_id: int | None, application, text: str) -> None:
    if not chat_id:
        return
    try:
        await application.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
    except Exception:
        pass


async def finalize_sp_giveaway(application, giveaway_id: int) -> None:
    doc = col("sp_giveaways").find_one({"id": giveaway_id})
    if not doc or doc.get("status") != "active":
        return

    prize_sp = int(doc.get("prize_sp", 0) or 0)
    participant_ids = list(dict.fromkeys(doc.get("participants", []) or []))
    valid_players = [get_player(uid) for uid in participant_ids]
    valid_players = [p for p in valid_players if p]

    if not valid_players:
        col("sp_giveaways").update_one(
            {"id": giveaway_id, "status": "active"},
            {"$set": {"status": "ended_no_entries", "ended_at": _now()}},
        )
        _release_reserved_sp(prize_sp)
        await _announce(
            doc.get("chat_id"),
            application,
            f"*SP GIVEAWAY ENDED*\n\nNo one joined. *{prize_sp} SP* was returned to the bank stock.",
        )
        return

    winner = random.choice(valid_players)
    winner_name = winner.get("name", f"User {winner['user_id']}")
    col("players").update_one({"user_id": winner["user_id"]}, {"$inc": {"skill_points": prize_sp}})
    _consume_reserved_sp(prize_sp)
    col("sp_giveaways").update_one(
        {"id": giveaway_id, "status": "active"},
        {
            "$set": {
                "status": "completed",
                "winner_id": winner["user_id"],
                "winner_name": winner_name,
                "ended_at": _now(),
            }
        },
    )
    await _announce(
        doc.get("chat_id"),
        application,
        f"*SP GIVEAWAY ENDED*\n\nWinner: *{winner_name}*\nPrize: *{prize_sp} SP*",
    )
    try:
        await application.bot.send_message(
            chat_id=winner["user_id"],
            text=f"*YOU WON THE SP GIVEAWAY!*\n\nPrize credited: *{prize_sp} SP*",
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def finalize_tournament(application, tournament_id: int) -> None:
    doc = col("sp_tournaments").find_one({"id": tournament_id})
    if not doc or doc.get("status") != "active":
        return

    prize_sp = int(doc.get("prize_sp", 0) or 0)
    participant_ids = list(dict.fromkeys(doc.get("participants", []) or []))
    valid_players = [get_player(uid) for uid in participant_ids]
    valid_players = [p for p in valid_players if p]

    if not valid_players:
        col("sp_tournaments").update_one(
            {"id": tournament_id, "status": "active"},
            {"$set": {"status": "ended_no_entries", "ended_at": _now()}},
        )
        _release_reserved_sp(prize_sp)
        await _announce(
            doc.get("chat_id"),
            application,
            f"*TOURNAMENT ENDED*\n\nNo players joined. *{prize_sp} SP* was returned to the bank stock.",
        )
        return

    highest_level = max(get_level(p.get("xp", 0)) for p in valid_players)
    top_players = [p for p in valid_players if get_level(p.get("xp", 0)) == highest_level]
    winner = random.choice(top_players)
    winner_name = winner.get("name", f"User {winner['user_id']}")
    col("players").update_one({"user_id": winner["user_id"]}, {"$inc": {"skill_points": prize_sp}})
    _consume_reserved_sp(prize_sp)
    col("sp_tournaments").update_one(
        {"id": tournament_id, "status": "active"},
        {
            "$set": {
                "status": "completed",
                "winner_id": winner["user_id"],
                "winner_name": winner_name,
                "winner_level": highest_level,
                "ended_at": _now(),
            }
        },
    )
    await _announce(
        doc.get("chat_id"),
        application,
        f"*TOURNAMENT ENDED*\n\nChampion: *{winner_name}*\nWinning level: *{highest_level}*\nPrize: *{prize_sp} SP*",
    )
    try:
        await application.bot.send_message(
            chat_id=winner["user_id"],
            text=f"*YOU WON THE TOURNAMENT!*\n\nReward credited: *{prize_sp} SP*",
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def _finish_sp_giveaway_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await finalize_sp_giveaway(context.application, context.job.data["giveaway_id"])


async def _finish_tournament_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await finalize_tournament(context.application, context.job.data["tournament_id"])


def _schedule_sp_giveaway(context: ContextTypes.DEFAULT_TYPE, giveaway_id: int, delay_seconds: int) -> None:
    if not context.job_queue:
        return
    context.job_queue.run_once(
        _finish_sp_giveaway_job,
        when=max(1, delay_seconds),
        data={"giveaway_id": giveaway_id},
        name=f"sp_giveaway_{giveaway_id}",
    )


def _schedule_tournament(context: ContextTypes.DEFAULT_TYPE, tournament_id: int, delay_seconds: int) -> None:
    if not context.job_queue:
        return
    context.job_queue.run_once(
        _finish_tournament_job,
        when=max(1, delay_seconds),
        data={"tournament_id": tournament_id},
        name=f"sp_tournament_{tournament_id}",
    )


async def resume_sp_features(application) -> None:
    if not application.job_queue:
        return
    now = _now()
    for doc in list(col("sp_giveaways").find({"status": "active"})):
        giveaway_id = doc.get("id")
        ends_at = doc.get("ends_at")
        if not giveaway_id or not ends_at:
            continue
        remaining = int((ends_at - now).total_seconds())
        if remaining <= 0:
            await finalize_sp_giveaway(application, giveaway_id)
            continue
        application.job_queue.run_once(
            _finish_sp_giveaway_job,
            when=remaining,
            data={"giveaway_id": giveaway_id},
            name=f"sp_giveaway_{giveaway_id}",
        )

    for doc in list(col("sp_tournaments").find({"status": "active"})):
        tournament_id = doc.get("id")
        ends_at = doc.get("ends_at")
        if not tournament_id or not ends_at:
            continue
        remaining = int((ends_at - now).total_seconds())
        if remaining <= 0:
            await finalize_tournament(application, tournament_id)
            continue
        application.job_queue.run_once(
            _finish_tournament_job,
            when=remaining,
            data={"tournament_id": tournament_id},
            name=f"sp_tournament_{tournament_id}",
        )


async def spbank(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player = get_player(update.effective_user.id)
    if not player:
        await update.message.reply_text("No character found.")
        return

    bank = _get_bank_state()
    user_state = _get_user_state(update.effective_user.id)
    active_giveaway = _get_active_sp_giveaway()
    remaining_withdraw = max(0, SP_BANK_DAILY_WITHDRAW_LIMIT - int(user_state.get("daily_withdrawn", 0) or 0))

    lines = [
        "*WORLD SP BANK*",
        "",
        f"Available SP for withdrawal: *{bank['available_sp']:,} SP*",
        f"Reserved for giveaways: *{bank['reserved_sp']:,} SP*",
        f"Total deposited: *{bank['total_deposited']:,} SP*",
        f"Total withdrawn: *{bank['total_withdrawn']:,} SP*",
        f"Total giveaway rewards: *{bank['total_sp_awarded']:,} SP*",
        f"Total Yen burned: *{bank['total_yen_burned']:,} Yen*",
        "",
        f"Your SP: *{player.get('skill_points', 0):,}*",
        f"Your Yen: *{player.get('yen', 0):,}*",
        f"Your daily withdrawal left: *{remaining_withdraw}/{SP_BANK_DAILY_WITHDRAW_LIMIT} SP*",
        "",
        "Deposits now go fully into the bank stock.",
        f"Withdrawal price: *{SP_BANK_WITHDRAW_PRICE_PER_SP:,} Yen* per SP.",
        f"Eligibility: *Level {SP_BANK_MIN_LEVEL}+* and account age *{SP_BANK_MIN_ACCOUNT_AGE_DAYS}+ days*.",
        "",
        "Commands:",
        "`/spdeposit [amount]`",
        "`/spwithdraw [amount]`",
        "`/spjoin` - join active SP giveaway",
    ]

    if active_giveaway:
        lines.extend(
            [
                "",
                f"Active SP giveaway: *{active_giveaway.get('prize_sp', 0):,} SP*",
                f"Entries: *{len(active_giveaway.get('participants', []))}* | Ends in *{_format_time_left(active_giveaway.get('ends_at'))}*",
            ]
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def spdeposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/spdeposit [amount]`", parse_mode="Markdown")
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return

    if int(player.get("skill_points", 0) or 0) < amount:
        await update.message.reply_text(
            f"Not enough SP. You only have *{player.get('skill_points', 0):,} SP*.",
            parse_mode="Markdown",
        )
        return

    result = col("players").update_one(
        {"user_id": user_id, "skill_points": {"$gte": amount}},
        {"$inc": {"skill_points": -amount}},
    )
    if result.modified_count != 1:
        await update.message.reply_text("Deposit failed because your SP changed. Please try again.")
        return

    col("bank_meta").update_one(
        {"_id": SP_BANK_DOC_ID},
        {
            "$inc": {
                "available_sp": amount,
                "total_deposited": amount,
            }
        },
        upsert=True,
    )
    col("sp_bank_users").update_one(
        {"user_id": user_id},
        {"$inc": {"lifetime_deposit": amount}},
        upsert=True,
    )

    log_action(user_id, "spbank_deposit", details=f"Deposit {amount} SP | Bank +{amount} SP")
    await update.message.reply_text(
        f"*SP deposited successfully*\n\n"
        f"Deposited: *{amount:,} SP*\n"
        f"Added to community bank: *{amount:,} SP*\n"
        f"Your SP now: *{player.get('skill_points', 0) - amount:,}*",
        parse_mode="Markdown",
    )


async def spwithdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/spwithdraw [amount]`", parse_mode="Markdown")
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid amount.")
        return

    if amount <= 0:
        await update.message.reply_text("Amount must be positive.")
        return

    eligible, reason = _is_eligible_for_sp_bank(player)
    if not eligible:
        await update.message.reply_text(reason)
        return

    user_state = _get_user_state(user_id)
    current_withdraw_date = user_state.get("withdraw_date")
    already_taken = int(user_state.get("daily_withdrawn", 0) or 0)
    if already_taken + amount > SP_BANK_DAILY_WITHDRAW_LIMIT:
        remaining = max(0, SP_BANK_DAILY_WITHDRAW_LIMIT - already_taken)
        await update.message.reply_text(
            f"Daily SP withdrawal limit reached. You can still withdraw *{remaining} SP* today.",
            parse_mode="Markdown",
        )
        return

    bank = _get_bank_state()
    if bank["available_sp"] < amount:
        await update.message.reply_text(
            f"The world bank only has *{bank['available_sp']:,} SP* available right now.",
            parse_mode="Markdown",
        )
        return

    yen_cost = amount * SP_BANK_WITHDRAW_PRICE_PER_SP
    result = col("players").update_one(
        {"user_id": user_id, "yen": {"$gte": yen_cost}},
        {"$inc": {"yen": -yen_cost, "skill_points": amount}},
    )
    if result.modified_count != 1:
        await update.message.reply_text(
            f"You need *{yen_cost:,} Yen* to withdraw *{amount} SP*.",
            parse_mode="Markdown",
        )
        return

    bank_result = col("bank_meta").update_one(
        {"_id": SP_BANK_DOC_ID, "available_sp": {"$gte": amount}},
        {"$inc": {"available_sp": -amount, "total_withdrawn": amount, "total_yen_burned": yen_cost}},
        upsert=False,
    )
    if bank_result.modified_count != 1:
        col("players").update_one({"user_id": user_id}, {"$inc": {"yen": yen_cost, "skill_points": -amount}})
        await update.message.reply_text("Withdrawal failed because the bank SP changed. Please try again.")
        return

    today = _today_key()
    if current_withdraw_date == today:
        col("sp_bank_users").update_one(
            {"user_id": user_id},
            {
                "$inc": {
                    "daily_withdrawn": amount,
                    "lifetime_withdraw": amount,
                    "lifetime_yen_spent": yen_cost,
                },
                "$set": {"withdraw_date": today},
            },
            upsert=True,
        )
    else:
        col("sp_bank_users").update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "daily_withdrawn": amount,
                    "withdraw_date": today,
                },
                "$inc": {
                    "lifetime_withdraw": amount,
                    "lifetime_yen_spent": yen_cost,
                },
            },
            upsert=True,
        )

    remaining = max(0, SP_BANK_DAILY_WITHDRAW_LIMIT - already_taken - amount)
    log_action(user_id, "spbank_withdraw", details=f"Withdraw {amount} SP | Cost {yen_cost} Yen")
    await update.message.reply_text(
        f"*SP withdrawn successfully*\n\n"
        f"Received: *{amount:,} SP*\n"
        f"Cost paid: *{yen_cost:,} Yen*\n"
        f"Daily withdrawal left: *{remaining}/{SP_BANK_DAILY_WITHDRAW_LIMIT} SP*",
        parse_mode="Markdown",
    )


async def spgiveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: `/spgiveaway [amount] [duration]`", parse_mode="Markdown")
        return

    try:
        amount = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid SP amount.")
        return

    duration_seconds, duration_display = _parse_duration(context.args[1])
    if duration_seconds is None:
        await update.message.reply_text("Invalid duration. Use `24h`, `30m`, or `45s`.", parse_mode="Markdown")
        return

    if amount <= 0:
        await update.message.reply_text("Prize must be positive.")
        return

    if _get_active_sp_giveaway():
        await update.message.reply_text("An SP giveaway is already active.")
        return

    if not _reserve_bank_sp(amount):
        bank = _get_bank_state()
        await update.message.reply_text(
            f"Not enough SP in the bank stock. Available: *{bank['available_sp']:,} SP*.",
            parse_mode="Markdown",
        )
        return

    now = _now()
    ends_at = now.timestamp() + duration_seconds
    last_doc = col("sp_giveaways").find_one(sort=[("id", -1)])
    giveaway_id = int(last_doc.get("id", 0)) + 1 if last_doc else 1
    col("sp_giveaways").insert_one(
        {
            "id": giveaway_id,
            "status": "active",
            "prize_sp": amount,
            "participants": [],
            "started_by": user_id,
            "chat_id": update.effective_chat.id,
            "created_at": now,
            "ends_at": datetime.fromtimestamp(ends_at),
        }
    )
    _schedule_sp_giveaway(context, giveaway_id, duration_seconds)
    log_action(user_id, "spgiveaway_start", details=f"Prize {amount} SP | Duration {duration_display}")
    await update.message.reply_text(
        f"*SP GIVEAWAY STARTED*\n\n"
        f"Prize: *{amount:,} SP*\n"
        f"Duration: *{duration_display}*\n"
        f"Players can now use `/spjoin` to enter.",
        parse_mode="Markdown",
    )


async def spjoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player = get_player(update.effective_user.id)
    if not player:
        await update.message.reply_text("No character found.")
        return

    eligible, reason = _is_eligible_for_sp_bank(player)
    if not eligible:
        await update.message.reply_text(reason)
        return

    active = _get_active_sp_giveaway()
    if not active:
        await update.message.reply_text("No active SP giveaway right now.")
        return

    ends_at = active.get("ends_at")
    if ends_at and ends_at <= _now():
        await finalize_sp_giveaway(context.application, active["id"])
        await update.message.reply_text("That SP giveaway just ended.")
        return

    result = col("sp_giveaways").update_one(
        {"id": active["id"], "status": "active", "participants": {"$ne": update.effective_user.id}},
        {"$addToSet": {"participants": update.effective_user.id}},
    )
    if result.modified_count == 0:
        await update.message.reply_text("You already joined this SP giveaway.")
        return

    updated = col("sp_giveaways").find_one({"id": active["id"]}) or active
    await update.message.reply_text(
        f"*You joined the SP giveaway*\n\n"
        f"Prize: *{updated.get('prize_sp', 0):,} SP*\n"
        f"Entries: *{len(updated.get('participants', []))}*\n"
        f"Ends in: *{_format_time_left(updated.get('ends_at'))}*",
        parse_mode="Markdown",
    )


async def tour(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player = get_player(update.effective_user.id)
    if not player:
        await update.message.reply_text("No character found.")
        return

    active = _get_active_tournament()
    if not active:
        await update.message.reply_text(
            "No active tournament right now. The owner can start one with `/tourstart`.",
            parse_mode="Markdown",
        )
        return

    ends_at = active.get("ends_at")
    if ends_at and ends_at <= _now():
        await finalize_tournament(context.application, active["id"])
        await update.message.reply_text("That tournament just ended.")
        return

    if context.args and context.args[0].lower() == "join":
        eligible, reason = _is_eligible_for_sp_bank(player)
        if not eligible:
            await update.message.reply_text(reason)
            return

        result = col("sp_tournaments").update_one(
            {"id": active["id"], "status": "active", "participants": {"$ne": update.effective_user.id}},
            {"$addToSet": {"participants": update.effective_user.id}},
        )
        if result.modified_count == 0:
            await update.message.reply_text("You are already in the tournament.")
            return

        updated = col("sp_tournaments").find_one({"id": active["id"]}) or active
        await update.message.reply_text(
            f"*Tournament entry confirmed*\n\n"
            f"Tournament: *{updated.get('title', 'World Tournament')}*\n"
            f"Prize: *{updated.get('prize_sp', 0):,} SP*\n"
            f"Entries: *{len(updated.get('participants', []))}*",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        f"*ACTIVE TOURNAMENT*\n\n"
        f"Title: *{active.get('title', 'World Tournament')}*\n"
        f"Description: {active.get('description', 'No description set.')}\n"
        f"Prize: *{active.get('prize_sp', 0):,} SP*\n"
        f"Entries: *{len(active.get('participants', []))}*\n"
        f"Ends in: *{_format_time_left(active.get('ends_at'))}*\n"
        f"Rule: highest level entrant wins, ties are broken randomly.\n\n"
        "Use `/tour join` to participate.",
        parse_mode="Markdown",
    )


async def tourstart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return
    if len(context.args) < 3:
        await update.message.reply_text(
            "Usage: `/tourstart [prize_sp] [duration] [title] | [description]`",
            parse_mode="Markdown",
        )
        return

    try:
        prize_sp = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid SP amount.")
        return

    duration_seconds, duration_display = _parse_duration(context.args[1])
    if duration_seconds is None:
        await update.message.reply_text("Invalid duration. Use `24h`, `30m`, or `45s`.", parse_mode="Markdown")
        return

    title_desc = " ".join(context.args[2:])
    if "|" in title_desc:
        title, description = [part.strip() for part in title_desc.split("|", 1)]
    else:
        title, description = title_desc.strip(), "Join with `/tour join`."

    if prize_sp <= 0:
        await update.message.reply_text("Prize must be positive.")
        return

    if _get_active_tournament():
        await update.message.reply_text("A tournament is already active.")
        return

    if not _reserve_bank_sp(prize_sp):
        bank = _get_bank_state()
        await update.message.reply_text(
            f"Not enough SP in the bank stock. Available: *{bank['available_sp']:,} SP*.",
            parse_mode="Markdown",
        )
        return

    now = _now()
    last_doc = col("sp_tournaments").find_one(sort=[("id", -1)])
    tournament_id = int(last_doc.get("id", 0)) + 1 if last_doc else 1
    col("sp_tournaments").insert_one(
        {
            "id": tournament_id,
            "status": "active",
            "title": title or "World Tournament",
            "description": description,
            "prize_sp": prize_sp,
            "participants": [],
            "started_by": user_id,
            "chat_id": update.effective_chat.id,
            "created_at": now,
            "ends_at": datetime.fromtimestamp(now.timestamp() + duration_seconds),
        }
    )
    _schedule_tournament(context, tournament_id, duration_seconds)
    log_action(user_id, "tourstart", details=f"Prize {prize_sp} SP | Duration {duration_display} | Title {title}")
    await update.message.reply_text(
        f"*TOURNAMENT STARTED*\n\n"
        f"Title: *{title or 'World Tournament'}*\n"
        f"Prize: *{prize_sp:,} SP*\n"
        f"Duration: *{duration_display}*\n"
        f"Players can join with `/tour join`.\n"
        f"Winner rule: highest level entrant wins, ties are random.",
        parse_mode="Markdown",
    )


async def tourend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("Admin only.")
        return

    active = _get_active_tournament()
    if not active:
        await update.message.reply_text("No active tournament right now.")
        return

    await finalize_tournament(context.application, active["id"])
    await update.message.reply_text("Tournament ended and rewards were processed.")
