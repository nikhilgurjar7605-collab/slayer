"""
Bank Interest System
════════════════════════════════════════════════════════════════════════════
Owner / Admin commands:
  /setinterest <rate>
      Set the daily interest rate as a percentage (e.g. 2 = 2% per day).
      Only owner or admin can use this.

  /interestinfo
      Show the current interest rate.

  /claiminterest
      Players claim their accrued interest from their bank balance.
      Interest is calculated from the last claim time.
      Cannot claim more than once every 24 hours.

How it works:
  - A single global interest rate (%) is stored in the DB.
  - When a player calls /claiminterest, we calculate:
        interest = balance × (rate / 100) × days_since_last_claim
    and add that to their bank balance.
  - Minimum 24h between claims.
  - Owner/admin set the rate with /setinterest.

DB collections:
  bank_settings  — single doc with {"key": "interest_rate", "value": float}
  bank_accounts  — existing, gains field "last_interest_claim" (ISO date str)
════════════════════════════════════════════════════════════════════════════
"""

import logging
from datetime import datetime, timezone, timedelta

from telegram import Update
from telegram.ext import ContextTypes

from handlers.admin import has_admin_access
from utils.database import col, get_bank, ensure_bank, get_player, update_player

log = logging.getLogger(__name__)

SETTINGS_COL = "bank_settings"
BANK_COL     = "bank_accounts"

DEFAULT_RATE = 1.0   # 1% per day default


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_interest_rate() -> float:
    """Return current daily interest rate (%)."""
    doc = col(SETTINGS_COL).find_one({"key": "interest_rate"})
    if doc and "value" in doc:
        try:
            return float(doc["value"])
        except (TypeError, ValueError):
            pass
    return DEFAULT_RATE


def _set_interest_rate(rate: float):
    col(SETTINGS_COL).update_one(
        {"key": "interest_rate"},
        {"$set": {"value": rate}},
        upsert=True
    )


def _now_utc() -> datetime:
    return datetime.now(tz=timezone.utc)


def _calculate_interest(balance: float, rate: float, days: float) -> float:
    """Simple interest: balance × rate% × days."""
    return balance * (rate / 100.0) * days


# ── /setinterest ───────────────────────────────────────────────────────────

async def setinterest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Owner/admin only.
    /setinterest <rate>
    Sets the daily interest rate as a percentage (e.g. 2 = 2% per day).
    """
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args:
        current = _get_interest_rate()
        await update.message.reply_text(
            f"💰 *Bank Interest Rate*\n\n"
            f"Current rate: *{current:.2f}% per day*\n\n"
            f"Usage: `/setinterest <rate>`\n"
            f"Example: `/setinterest 2` → 2% daily interest\n\n"
            f"Players claim interest with `/claiminterest`.",
            parse_mode="Markdown"
        )
        return

    try:
        rate = float(context.args[0])
        if rate < 0 or rate > 100:
            raise ValueError("Out of range")
    except ValueError:
        await update.message.reply_text(
            "❌ Rate must be a number between 0 and 100.\n"
            "Example: `/setinterest 1.5`",
            parse_mode="Markdown"
        )
        return

    _set_interest_rate(rate)
    log.info("[BANK] Interest rate set to %.2f%% by user %s", rate, user_id)

    await update.message.reply_text(
        f"✅ *Interest Rate Updated!*\n\n"
        f"💰 Daily Rate: *{rate:.2f}% per day*\n\n"
        f"Players will earn *{rate:.2f}%* of their bank balance per day.\n"
        f"They can claim with `/claiminterest`.",
        parse_mode="Markdown"
    )


# ── /interestinfo ──────────────────────────────────────────────────────────

async def interestinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Anyone can see the current interest rate."""
    rate = _get_interest_rate()
    user_id = update.effective_user.id

    # Show personal accrued interest if they have a bank account
    extra = ""
    ensure_bank(user_id)
    b = get_bank(user_id)
    if b:
        balance = float(b.get("balance", 0) or 0)
        last_claim_str = b.get("last_interest_claim")
        if last_claim_str and balance > 0:
            try:
                last_claim = datetime.fromisoformat(last_claim_str)
                if last_claim.tzinfo is None:
                    last_claim = last_claim.replace(tzinfo=timezone.utc)
                days = (_now_utc() - last_claim).total_seconds() / 86400
                days = max(0, days)
                accrued = _calculate_interest(balance, rate, days)
                extra = (
                    f"\n\n💼 *Your bank balance:* {balance:,.0f} ¥\n"
                    f"⏳ *Accrued interest:* ~{accrued:,.1f} ¥\n"
                    f"_(Claim with /claiminterest)_"
                )
            except Exception:
                pass

    await update.message.reply_text(
        f"🏦 *Bank Interest Info*\n\n"
        f"💰 Daily Interest Rate: *{rate:.2f}%*\n"
        f"Interest is paid on your bank balance.\n"
        f"Claim once per 24 hours with `/claiminterest`."
        f"{extra}",
        parse_mode="Markdown"
    )


# ── /claiminterest ─────────────────────────────────────────────────────────

async def claiminterest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Available to all players.
    Calculates and credits accrued interest on bank balance.
    Cooldown: 24 hours.
    """
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    ensure_bank(user_id)
    b = get_bank(user_id)
    if not b:
        await update.message.reply_text("❌ Could not access your bank account.")
        return

    balance = float(b.get("balance", 0) or 0)
    if balance <= 0:
        await update.message.reply_text(
            "🏦 Your bank balance is empty.\n"
            "Deposit some Yen first with `/deposit <amount>`.",
            parse_mode="Markdown"
        )
        return

    rate = _get_interest_rate()
    if rate <= 0:
        await update.message.reply_text(
            "🏦 Interest is currently set to *0%*.\n"
            "No interest to claim right now.",
            parse_mode="Markdown"
        )
        return

    now = _now_utc()

    # Check last claim time
    last_claim_str = b.get("last_interest_claim")
    if last_claim_str:
        try:
            last_claim = datetime.fromisoformat(last_claim_str)
            if last_claim.tzinfo is None:
                last_claim = last_claim.replace(tzinfo=timezone.utc)
            elapsed = (now - last_claim).total_seconds()
            cooldown = 86400  # 24 hours
            if elapsed < cooldown:
                remaining = cooldown - elapsed
                hrs  = int(remaining // 3600)
                mins = int((remaining % 3600) // 60)
                await update.message.reply_text(
                    f"⏳ You already claimed your interest today!\n\n"
                    f"Next claim available in: *{hrs}h {mins}m*",
                    parse_mode="Markdown"
                )
                return
            # Use actual days elapsed (capped at 7 days max to prevent abuse on old accounts)
            days = min(elapsed / 86400, 7.0)
        except Exception:
            days = 1.0
    else:
        # First claim — treat as 1 day
        days = 1.0

    interest = _calculate_interest(balance, rate, days)
    interest_int = max(1, int(interest))  # at least 1 yen if rate > 0

    # Credit interest to bank balance
    col(BANK_COL).update_one(
        {"user_id": user_id},
        {
            "$inc": {"balance": interest_int},
            "$set": {"last_interest_claim": now.isoformat()}
        }
    )

    new_balance = balance + interest_int
    log.info(
        "[BANK] User %s claimed interest: +%d ¥ (%.2f%% × %.2f days × %d balance)",
        user_id, interest_int, rate, days, balance
    )

    await update.message.reply_text(
        f"✅ *Interest Claimed!*\n\n"
        f"💰 Rate: *{rate:.2f}% / day*\n"
        f"📅 Period: *{days:.1f} day(s)*\n"
        f"💵 Interest earned: *+{interest_int:,} ¥*\n\n"
        f"🏦 New Balance: *{new_balance:,.0f} ¥*\n\n"
        f"_Come back in 24 hours to claim again!_",
        parse_mode="Markdown"
    )
