import random
import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import ContextTypes

from handlers.admin import has_admin_access
from handlers.logs import log_action
from utils.database import col, get_player, update_player

BANK_TAX_RATE = 0.0
TAX_POOL_DOC_ID = "bank_tax_pool"
BANK_TAX_TIMEZONE = ZoneInfo("Asia/Kolkata")
_DURATION_RE = re.compile(r"^\s*(\d+)\s*(hr|h|m|s)\s*$", re.IGNORECASE)


def _now_local() -> datetime:
    return datetime.now(BANK_TAX_TIMEZONE)


def _today_key(now: datetime | None = None) -> str:
    base = now or _now_local()
    return base.strftime("%Y-%m-%d")


def calculate_pending_tax(amount: int) -> int:
    return 0


def parse_tax_percent(text: str) -> float | None:
    raw = (text or "").strip().replace("%", "")
    try:
        value = float(raw)
    except ValueError:
        return None
    if value < 0:
        return None
    return value


def apply_manual_bank_tax(user_id: int, percent: float) -> tuple[int, int, int]:
    account = col("bank_accounts").find_one({"user_id": user_id}) or {}
    deposit_total = int(account.get("daily_deposit_total", 0) or 0)
    return deposit_total, 0, 0


def get_tax_pool_state() -> dict:
    doc = col("bank_meta").find_one({"_id": TAX_POOL_DOC_ID}) or {}
    return {
        "_id": TAX_POOL_DOC_ID,
        "available_tax": int(doc.get("available_tax", 0) or 0),
        "reserved_tax": int(doc.get("reserved_tax", 0) or 0),
        "total_tax_collected": int(doc.get("total_tax_collected", 0) or 0),
        "total_tax_awarded": int(doc.get("total_tax_awarded", 0) or 0),
    }


def add_tax_to_pool(amount: int) -> None:
    if amount <= 0:
        return
    col("bank_meta").update_one(
        {"_id": TAX_POOL_DOC_ID},
        {"$inc": {"available_tax": amount, "total_tax_collected": amount}},
        upsert=True,
    )


def process_due_bank_taxes() -> int:
    return 0


async def _run_daily_bank_tax(context: ContextTypes.DEFAULT_TYPE) -> None:
    return


def schedule_daily_bank_tax(application) -> None:
    return


def _reserve_tax(amount: int) -> None:
    col("bank_meta").update_one(
        {"_id": TAX_POOL_DOC_ID},
        {"$inc": {"available_tax": -amount, "reserved_tax": amount}},
        upsert=True,
    )


def _release_reserved_tax(amount: int) -> None:
    col("bank_meta").update_one(
        {"_id": TAX_POOL_DOC_ID},
        {"$inc": {"available_tax": amount, "reserved_tax": -amount}},
        upsert=True,
    )


def _consume_reserved_tax(amount: int) -> None:
    col("bank_meta").update_one(
        {"_id": TAX_POOL_DOC_ID},
        {"$inc": {"reserved_tax": -amount, "total_tax_awarded": amount}},
        upsert=True,
    )


def _parse_duration(text: str) -> tuple[int, str] | tuple[None, None]:
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


def _get_active_giveaway() -> dict | None:
    doc = col("bank_giveaways").find_one({"status": "active"}, sort=[("created_at", -1)])
    if doc:
        doc.pop("_id", None)
        return doc
    return None


async def _announce_result(application, giveaway: dict, text: str) -> None:
    chat_id = giveaway.get("chat_id")
    if chat_id:
        try:
            await application.bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
        except Exception:
            pass


async def finalize_bank_giveaway(application, giveaway_id: int) -> None:
    doc = col("bank_giveaways").find_one({"id": giveaway_id})
    if not doc or doc.get("status") != "active":
        return

    prize_amount = int(doc.get("prize_amount", 0) or 0)
    participant_ids = list(dict.fromkeys(doc.get("participants", []) or []))
    valid_participants = [uid for uid in participant_ids if get_player(uid)]

    if not valid_participants:
        col("bank_giveaways").update_one(
            {"id": giveaway_id, "status": "active"},
            {"$set": {"status": "ended_no_entries", "ended_at": datetime.now()}},
        )
        _release_reserved_tax(prize_amount)
        await _announce_result(
            application,
            doc,
            f"🎁 *BANK GIVEAWAY ENDED*\n\nNo one joined.\n*{prize_amount:,}¥* was returned to the tax pool.",
        )
        return

    winner_id = random.choice(valid_participants)
    winner = get_player(winner_id)
    if not winner:
        col("bank_giveaways").update_one(
            {"id": giveaway_id, "status": "active"},
            {"$set": {"status": "ended_no_entries", "ended_at": datetime.now()}},
        )
        _release_reserved_tax(prize_amount)
        return

    update_player(winner_id, yen=winner.get("yen", 0) + prize_amount)
    _consume_reserved_tax(prize_amount)
    col("bank_giveaways").update_one(
        {"id": giveaway_id, "status": "active"},
        {
            "$set": {
                "status": "completed",
                "winner_id": winner_id,
                "winner_name": winner.get("name", f"User {winner_id}"),
                "ended_at": datetime.now(),
            }
        },
    )
    await _announce_result(
        application,
        doc,
        f"🎉 *BANK GIVEAWAY ENDED*\n\n"
        f"🏆 Winner: *{winner.get('name', f'User {winner_id}') }*\n"
        f"💰 Reward transferred: *{prize_amount:,}¥*",
    )
    try:
        await application.bot.send_message(
            chat_id=winner_id,
            text=(
                f"🎉 *YOU WON THE BANK GIVEAWAY!*\n\n"
                f"💰 *{prize_amount:,}¥* has been transferred to your wallet."
            ),
            parse_mode="Markdown",
        )
    except Exception:
        pass


async def _finish_bank_giveaway_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    giveaway_id = context.job.data["giveaway_id"]
    await finalize_bank_giveaway(context.application, giveaway_id)


def _schedule_giveaway(context: ContextTypes.DEFAULT_TYPE, giveaway_id: int, delay_seconds: int) -> None:
    if not context.job_queue:
        return
    context.job_queue.run_once(
        _finish_bank_giveaway_job,
        when=max(1, delay_seconds),
        data={"giveaway_id": giveaway_id},
        name=f"bank_giveaway_{giveaway_id}",
    )


async def resume_bank_giveaways(application) -> None:
    active = list(col("bank_giveaways").find({"status": "active"}))
    if not active or not application.job_queue:
        return
    now = datetime.now()
    for raw in active:
        giveaway_id = raw.get("id")
        ends_at = raw.get("ends_at")
        if not giveaway_id or not ends_at:
            continue
        remaining = int((ends_at - now).total_seconds())
        if remaining <= 0:
            await finalize_bank_giveaway(application, giveaway_id)
            continue
        application.job_queue.run_once(
            _finish_bank_giveaway_job,
            when=remaining,
            data={"giveaway_id": giveaway_id},
            name=f"bank_giveaway_{giveaway_id}",
        )


async def bankgiveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/bankgiveaway 24hr` or `/bankgiveaway 15m` or `/bankgiveaway 25s`",
            parse_mode="Markdown",
        )
        return

    active = _get_active_giveaway()
    if active:
        await update.message.reply_text("❌ A bank giveaway is already active.")
        return

    delay_seconds, display = _parse_duration(context.args[0])
    if delay_seconds is None:
        await update.message.reply_text(
            "❌ Invalid time. Use formats like `24hr`, `15m`, or `25s`.",
            parse_mode="Markdown",
        )
        return

    pool = get_tax_pool_state()
    prize_amount = pool.get("available_tax", 0)
    if prize_amount <= 0:
        await update.message.reply_text("❌ No tax is available in the bank pool right now.")
        return

    _reserve_tax(prize_amount)
    now = datetime.now()
    ends_at = now + timedelta(seconds=delay_seconds)
    last_doc = col("bank_giveaways").find_one(sort=[("id", -1)])
    giveaway_id = int(last_doc.get("id", 0)) + 1 if last_doc else 1
    col("bank_giveaways").insert_one(
        {
            "id": giveaway_id,
            "status": "active",
            "prize_amount": prize_amount,
            "participants": [],
            "started_by": user_id,
            "chat_id": update.effective_chat.id,
            "created_at": now,
            "ends_at": ends_at,
        }
    )
    _schedule_giveaway(context, giveaway_id, delay_seconds)
    log_action(user_id, "bankgiveaway", details=f"Prize {prize_amount:,}¥ | Duration {display}")
    await update.message.reply_text(
        f"🎁 *BANK GIVEAWAY STARTED*\n\n"
        f"💰 Prize snapshot: *{prize_amount:,}¥*\n"
        f"⏳ Duration: *{display}*\n"
        f"🕒 Ends at: *{ends_at.strftime('%Y-%m-%d %H:%M:%S')}*\n\n"
        f"Players can now use `/join` to enter.\n"
        f"_New tax collected after this point is excluded from this giveaway._",
        parse_mode="Markdown",
    )


async def join_bank_giveaway(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player = get_player(update.effective_user.id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    active = _get_active_giveaway()
    if not active:
        await update.message.reply_text("❌ No active bank giveaway right now.")
        return

    ends_at = active.get("ends_at")
    if ends_at and ends_at <= datetime.now():
        await finalize_bank_giveaway(context.application, active["id"])
        await update.message.reply_text("⏳ That giveaway just ended. Use `/join` on the next one.")
        return

    if update.effective_user.id in (active.get("participants") or []):
        await update.message.reply_text("✅ You already joined this bank giveaway.")
        return

    col("bank_giveaways").update_one(
        {"id": active["id"], "status": "active"},
        {"$addToSet": {"participants": update.effective_user.id}},
    )
    participant_count = col("bank_giveaways").find_one({"id": active["id"]}).get("participants", [])
    await update.message.reply_text(
        f"✅ *You joined the bank giveaway!*\n\n"
        f"💰 Prize: *{active.get('prize_amount', 0):,}¥*\n"
        f"👥 Entries: *{len(participant_count)}*\n"
        f"⏳ Ends at: *{ends_at.strftime('%Y-%m-%d %H:%M:%S')}*",
        parse_mode="Markdown",
    )
