from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TimedOut
from telegram.ext import ContextTypes

from config import OWNER_ID
from utils.database import col, get_player


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

async def _safe_edit(query, text, **kwargs):
    """Edit a message safely, falling back to reply on failure."""
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as exc:
        err = str(exc).lower()
        if "message is not modified" in err:
            return
        if any(token in err for token in ("can't be edited", "message to edit not found", "not found")):
            try:
                await query.message.reply_text(text, **kwargs)
            except Exception:
                pass
            return
        raise
    except TimedOut:
        pass


def is_owner(user_id):
    return user_id == OWNER_ID


def _fmt_ts(ts) -> str:
    """Format a datetime with milliseconds for bot-detection analysis."""
    if isinstance(ts, datetime):
        return ts.strftime("%m/%d %H:%M:%S.") + f"{ts.microsecond // 1000:03d}"
    return str(ts)[:23]


# ─────────────────────────────────────────────
#  Bot-Detection Analysis
# ─────────────────────────────────────────────

def _analyze_bot_signals(entries: list) -> dict:
    """
    Analyze a list of activity log entries for automation signals.

    Signals checked:
    - Action interval consistency  (bots repeat at near-identical intervals)
    - Burst speed                  (many actions in < 2 seconds)
    - Duplicate action repetition  (same button/command many times in a row)
    - Off-hours activity           (03:00–05:00 local — rare for humans)
    - Zero think-time clicks       (< 300 ms between consecutive actions)
    """
    if not entries:
        return {}

    timestamps = []
    for e in entries:
        ts = e.get("timestamp")
        if isinstance(ts, datetime):
            timestamps.append(ts)

    timestamps.sort()
    if len(timestamps) < 2:
        return {}

    intervals_ms = [
        (timestamps[i + 1] - timestamps[i]).total_seconds() * 1000
        for i in range(len(timestamps) - 1)
    ]

    # ── Burst: ≥3 actions within 2 seconds ──
    burst_count = sum(1 for ms in intervals_ms if ms < 2000)

    # ── Zero think-time: < 300 ms ──
    zero_think = sum(1 for ms in intervals_ms if ms < 300)

    # ── Interval consistency: low std-dev = robotic ──
    if len(intervals_ms) >= 3:
        avg = sum(intervals_ms) / len(intervals_ms)
        variance = sum((x - avg) ** 2 for x in intervals_ms) / len(intervals_ms)
        std_dev = variance ** 0.5
        consistency_ratio = (std_dev / avg * 100) if avg > 0 else 0
        # < 10% variation = highly consistent = bot-like
    else:
        avg = intervals_ms[0] if intervals_ms else 0
        std_dev = 0
        consistency_ratio = 0

    # ── Duplicate action streaks ──
    activities = [e.get("activity", "") for e in entries]
    max_streak = 1
    cur_streak = 1
    for i in range(1, len(activities)):
        if activities[i] == activities[i - 1]:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 1

    # ── Off-hours (03–05 UTC) ──
    off_hours = sum(1 for ts in timestamps if 3 <= ts.hour < 5)

    # ── Suspicion score (0–100) ──
    score = 0
    if burst_count >= 3:
        score += 30
    if zero_think >= 2:
        score += 25
    if consistency_ratio < 10 and len(intervals_ms) >= 5:
        score += 20
    if max_streak >= 4:
        score += 15
    if off_hours >= 3:
        score += 10

    score = min(score, 100)

    if score >= 70:
        verdict = "🔴 HIGH — Likely automated"
    elif score >= 40:
        verdict = "🟡 MEDIUM — Suspicious"
    elif score >= 15:
        verdict = "🟠 LOW — Slightly unusual"
    else:
        verdict = "🟢 CLEAN — Looks human"

    return {
        "score": score,
        "verdict": verdict,
        "total_actions": len(entries),
        "avg_interval_ms": round(avg, 1),
        "std_dev_ms": round(std_dev, 1),
        "consistency_ratio_pct": round(consistency_ratio, 1),
        "burst_count": burst_count,
        "zero_think_count": zero_think,
        "max_duplicate_streak": max_streak,
        "off_hours_actions": off_hours,
        "min_interval_ms": round(min(intervals_ms), 1) if intervals_ms else 0,
        "max_interval_ms": round(max(intervals_ms), 1) if intervals_ms else 0,
    }


def _bot_signal_lines(signals: dict) -> list[str]:
    """Render bot-detection signals as Markdown lines."""
    if not signals:
        return ["_Not enough data for bot analysis._"]

    lines = [
        "🤖 *BOT DETECTION ANALYSIS*",
        "",
        f"Suspicion Score: *{signals['score']}/100*",
        f"Verdict: {signals['verdict']}",
        "",
        "*Signal Breakdown:*",
        f"  Total actions analysed: `{signals['total_actions']}`",
        f"  Avg interval: `{signals['avg_interval_ms']} ms`",
        f"  Std deviation: `{signals['std_dev_ms']} ms`",
        f"  Consistency ratio: `{signals['consistency_ratio_pct']}%` _(< 10% = robotic)_",
        f"  Burst clicks (< 2s): `{signals['burst_count']}`",
        f"  Zero think-time (< 300ms): `{signals['zero_think_count']}`",
        f"  Max duplicate streak: `{signals['max_duplicate_streak']}`",
        f"  Off-hours actions (03–05 UTC): `{signals['off_hours_actions']}`",
        f"  Fastest action: `{signals['min_interval_ms']} ms`",
        f"  Slowest action: `{signals['max_interval_ms']} ms`",
    ]
    return lines


# ─────────────────────────────────────────────
#  Logging helpers
# ─────────────────────────────────────────────

def log_action(admin_id, action, target_id=None, target_name=None, details=None):
    """Record owner/admin actions for audit."""
    col("admin_logs").insert_one({
        "admin_id": admin_id,
        "action": action,
        "target_id": target_id,
        "target_name": target_name,
        "details": details,
        "timestamp": datetime.now(),
    })


def log_user_activity(user_id, activity, details=None, chat_id=None, chat_type=None, username=None, name=None):
    """Record player activity such as commands, buttons, and verification events."""
    if not user_id or not activity:
        return

    details_text = str(details).strip() if details is not None else None
    if details_text:
        details_text = details_text[:300]

    col("user_activity_logs").insert_one({
        "user_id": user_id,
        "username": username,
        "name": name,
        "activity": str(activity)[:80],
        "details": details_text,
        "chat_id": chat_id,
        "chat_type": chat_type,
        "timestamp": datetime.now(),
    })


# ─────────────────────────────────────────────
#  Lookup / icon helpers
# ─────────────────────────────────────────────

def _find_player_for_logs(arg: str):
    arg = str(arg or "").strip()
    if not arg:
        return None
    if arg.startswith("@"):
        return col("players").find_one({
            "username": {"$regex": f"^{arg.lstrip('@')}$", "$options": "i"}
        })
    if arg.isdigit():
        return col("players").find_one({"user_id": int(arg)})
    return col("players").find_one({"name": {"$regex": f"^{arg}$", "$options": "i"}})


def _admin_action_icon(action: str) -> str:
    mapping = {
        "giveyen": "YEN",
        "givexp": "XP",
        "giveitem": "ITEM",
        "give": "GIVE",
        "ban": "BAN",
        "unban": "UNBAN",
        "resetplayer": "RESET",
        "giveultimate": "ULT",
        "givestyle": "STYLE",
        "giveart": "ART",
        "announce": "MSG",
        "startraid": "RAID",
        "addoffer": "OFFER",
        "addblackmarket": "BMARKET",
        "giveslayermark": "SMARK",
        "givedemonmark": "DMARK",
        "master": "MASTER",
    }
    return mapping.get(str(action or "").lower(), "ADMIN")


def _activity_icon(activity: str) -> str:
    if activity.startswith("command:"):
        return "CMD"
    if activity.startswith("button:"):
        return "BTN"
    if activity == "captcha_sent":
        return "CAP"
    if activity == "captcha_passed":
        return "OK"
    if activity == "captcha_failed":
        return "WARN"
    if activity == "captcha_blocked":
        return "WAIT"
    if activity == "captcha_locked":
        return "LOCK"
    if activity == "human_check_required":
        return "CHK"
    if activity == "character_created":
        return "NEW"
    return "ACT"


def _activity_label(activity: str) -> str:
    if activity.startswith("command:"):
        return f"/{activity.split(':', 1)[1]}"
    if activity.startswith("button:"):
        return f"button:{activity.split(':', 1)[1]}"
    if activity == "human_check_required":
        return "HUMAN CHECK REQUIRED"
    return activity.replace("_", " ").upper()


# ─────────────────────────────────────────────
#  Admin logs pager
# ─────────────────────────────────────────────

def _parse_logs_filters(args):
    filter_admin = None
    filter_action = None
    page = 0

    for raw_arg in args or []:
        arg = str(raw_arg).strip()
        if not arg:
            continue
        if arg.startswith("@"):
            player = col("players").find_one({
                "username": {"$regex": f"^{arg.lstrip('@')}$", "$options": "i"}
            })
            if player:
                filter_admin = player["user_id"]
            continue
        if arg.isdigit() and len(arg) > 3:
            filter_admin = int(arg)
            continue
        if arg.isdigit():
            page = max(0, int(arg) - 1)
            continue
        filter_action = arg.lower()

    return filter_admin, filter_action, page


async def _logs_send(query_or_msg, user_id, context):
    """Internal helper for /logs and the inline log pager."""
    filter_admin, filter_action, page = _parse_logs_filters(context.args or [])
    page_size = 10

    query_filter = {}
    if filter_admin:
        query_filter["admin_id"] = filter_admin
    if filter_action:
        query_filter["action"] = {"$regex": filter_action, "$options": "i"}

    total = col("admin_logs").count_documents(query_filter)
    entries = list(
        col("admin_logs").find(query_filter)
        .sort("timestamp", -1)
        .skip(page * page_size)
        .limit(page_size)
    )

    if not entries:
        text = (
            "*ADMIN LOGS*\n\n"
            "No log entries found.\n\n"
            "Usage:\n"
            "`/logs` - all recent admin actions\n"
            "`/logs @admin` - filter by admin\n"
            "`/logs giveyen` - filter by action\n"
            "`/logs 2` - page 2\n"
            "`/logs user @player` - player activity timeline"
        )
        if hasattr(query_or_msg, "message"):
            await _safe_edit(query_or_msg, text, parse_mode="Markdown")
        else:
            await query_or_msg.reply_text(text, parse_mode="Markdown")
        return

    total_pages = max(1, (total + page_size - 1) // page_size)
    lines = [
        "*ADMIN LOGS*",
        f"Page *{page + 1}/{total_pages}*",
        f"Entries: *{total}*",
        "",
    ]

    for entry in entries:
        admin = get_player(entry["admin_id"])
        aname = admin["name"] if admin else f"Admin {entry['admin_id']}"
        ts_str = _fmt_ts(entry.get("timestamp"))          # ← milliseconds
        target_str = ""
        if entry.get("target_name"):
            target_str = f" -> *{entry['target_name']}*"
        elif entry.get("target_id"):
            target_str = f" -> `{entry['target_id']}`"
        details_str = f"\n  note: _{entry['details']}_" if entry.get("details") else ""
        lines.append(
            f"[{_admin_action_icon(entry.get('action'))}] `{ts_str}` *{aname}*\n"
            f"  `{str(entry.get('action', '')).upper()}`{target_str}{details_str}"
        )
        lines.append("")

    nav = []
    if page > 0:
        nav.append(
            InlineKeyboardButton(
                "Prev",
                callback_data=f"logs_page_{page - 1}_{filter_admin or ''}_{filter_action or ''}",
            )
        )
    if (page + 1) * page_size < total:
        nav.append(
            InlineKeyboardButton(
                "Next",
                callback_data=f"logs_page_{page + 1}_{filter_admin or ''}_{filter_action or ''}",
            )
        )

    buttons = []
    if nav:
        buttons.append(nav)
    buttons.append([
        InlineKeyboardButton("Yen", callback_data="logs_filter_giveyen"),
        InlineKeyboardButton("Ban", callback_data="logs_filter_ban"),
    ])
    buttons.append([
        InlineKeyboardButton("Item", callback_data="logs_filter_giveitem"),
        InlineKeyboardButton("All", callback_data="logs_filter_all"),
    ])

    text = "\n".join(lines).strip()
    markup = InlineKeyboardMarkup(buttons)

    if hasattr(query_or_msg, "message"):
        await _safe_edit(query_or_msg, text, parse_mode="Markdown", reply_markup=markup)
    else:
        await query_or_msg.reply_text(text, parse_mode="Markdown", reply_markup=markup)


async def logs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    if context.args and str(context.args[0]).lower() == "user":
        context.args = list(context.args[1:])
        await loguser(update, context)
        return

    await _logs_send(update.message, user_id, context)


async def logs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if not is_owner(user_id):
        await query.answer("Owner only.", show_alert=True)
        return

    data = query.data or ""
    if data.startswith("logs_page_"):
        parts = data.split("_", 4)
        page = int(parts[2])
        filter_admin = parts[3] if len(parts) > 3 and parts[3] else None
        filter_action = parts[4] if len(parts) > 4 and parts[4] else None
        context.args = []
        if filter_admin:
            context.args.append(filter_admin)
        if filter_action:
            context.args.append(filter_action)
        context.args.append(str(page + 1))
        await _logs_send(query, user_id, context)
        return

    if data.startswith("logs_filter_"):
        action = data.replace("logs_filter_", "", 1)
        context.args = [] if action == "all" else [action]
        await _logs_send(query, user_id, context)


# ─────────────────────────────────────────────
#  Admin stats
# ─────────────────────────────────────────────

def _extract_yen_amount(details) -> int:
    if not details:
        return 0
    cleaned = (
        str(details)
        .replace("yen", "")
        .replace("YEN", "")
        .replace("¥", "")
        .replace(",", " ")
    )
    for token in cleaned.split():
        if token.isdigit():
            return int(token)
    return 0


async def logstats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    admins = list(col("admins").find())
    if not admins:
        await update.message.reply_text("No admins found.")
        return

    since = datetime.now() - timedelta(days=30)
    total_yen_given = 0
    total_xp_given = 0
    total_items_given = 0
    total_bans = 0

    lines = [
        "*ADMIN STATS*",
        "Window: last 30 days",
        "",
    ]

    for admin_doc in admins:
        aid = admin_doc["user_id"]
        admin_player = get_player(aid)
        aname = admin_player["name"] if admin_player else f"ID:{aid}"

        admin_entries = list(
            col("admin_logs").find({"admin_id": aid, "timestamp": {"$gte": since}})
        )
        if not admin_entries:
            continue

        yen_entries = [e for e in admin_entries if e.get("action") == "giveyen"]
        xp_entries = [e for e in admin_entries if e.get("action") == "givexp"]
        item_entries = [e for e in admin_entries if e.get("action") == "giveitem"]
        ban_entries = [e for e in admin_entries if e.get("action") == "ban"]
        yen_total = sum(_extract_yen_amount(e.get("details")) for e in yen_entries)

        total_yen_given += yen_total
        total_xp_given += len(xp_entries)
        total_items_given += len(item_entries)
        total_bans += len(ban_entries)

        lines.append(
            f"*{aname}* (`{aid}`)\n"
            f"  Yen given: *{yen_total:,}*\n"
            f"  XP grants: *{len(xp_entries)}*\n"
            f"  Item grants: *{len(item_entries)}*\n"
            f"  Bans: *{len(ban_entries)}*\n"
            f"  Total actions: *{len(admin_entries)}*"
        )
        lines.append("")

    lines.extend([
        "Totals:",
        f"Yen distributed: *{total_yen_given:,}*",
        f"XP grants: *{total_xp_given}*",
        f"Items given: *{total_items_given}*",
        f"Bans: *{total_bans}*",
        "",
        "`/logs @admin` for a detailed audit.",
    ])

    await update.message.reply_text("\n".join(lines).strip(), parse_mode="Markdown")


# ─────────────────────────────────────────────
#  User timeline (loguser)
# ─────────────────────────────────────────────

def _combined_user_log_lines(target: dict, include_bot_analysis: bool = True) -> list[str]:
    tid = target["user_id"]
    tname = target.get("name", str(tid))

    admin_entries = list(
        col("admin_logs").find({"target_id": tid}).sort("timestamp", -1).limit(25)
    )
    activity_entries = list(
        col("user_activity_logs").find({"user_id": tid}).sort("timestamp", -1).limit(40)
    )

    if not admin_entries and not activity_entries:
        return [f"*LOG USER - {tname}*\n\n_No recorded activity found for this player._"]

    combined = []

    for entry in admin_entries:
        admin = get_player(entry["admin_id"])
        aname = admin["name"] if admin else f"Admin {entry['admin_id']}"
        combined.append({
            "timestamp": entry.get("timestamp"),
            "icon": _admin_action_icon(entry.get("action")),
            "label": f"`{str(entry.get('action', '')).upper()}` by *{aname}*",
            "details": entry.get("details"),
        })

    for entry in activity_entries:
        activity = entry.get("activity", "activity")
        combined.append({
            "timestamp": entry.get("timestamp"),
            "icon": _activity_icon(activity),
            "label": f"*{_activity_label(activity)}*",
            "details": entry.get("details"),
        })

    combined.sort(key=lambda item: item.get("timestamp") or datetime.min, reverse=True)
    combined = combined[:30]

    lines = [
        f"*LOG USER - {tname[:20]}*",
        f"Telegram ID: `{tid}`",
        f"Admin actions: *{len(admin_entries)}*",
        f"User activities: *{len(activity_entries)}*",
        "",
    ]

    # ── Bot-detection block ──
    if include_bot_analysis:
        signals = _analyze_bot_signals(activity_entries)
        lines += _bot_signal_lines(signals)
        lines.append("")

    lines += [
        "Recent timeline:",
        "",
    ]

    for entry in combined:
        ts_str = _fmt_ts(entry.get("timestamp"))          # ← milliseconds
        details = f"\n  note: _{entry['details']}_" if entry.get("details") else ""
        lines.append(f"[{entry['icon']}] `{ts_str}` {entry['label']}{details}")
        lines.append("")

    return lines


async def loguser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "*LOG USER*\n\n"
            "Usage: `/loguser @username` or `/loguser [telegram_id]`\n"
            "Also works as `/logs user @username`.\n\n"
            "Shows admin actions + recorded player activity + 🤖 bot detection report.",
            parse_mode="Markdown",
        )
        return

    target = _find_player_for_logs(context.args[0])
    if not target:
        await update.message.reply_text(
            f"Player *{context.args[0]}* not found.",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        "\n".join(_combined_user_log_lines(target)),
        parse_mode="Markdown",
    )


# ─────────────────────────────────────────────
#  Bot check — standalone command
# ─────────────────────────────────────────────

async def logbotcheck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /logbotcheck @username  —  deep bot-detection report for one player.

    Analyses the last 100 activity log entries with millisecond precision
    and returns a full breakdown of all automation signals.
    """
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "*LOG BOT CHECK*\n\n"
            "Usage: `/logbotcheck @username` or `/logbotcheck [telegram_id]`\n\n"
            "Runs a deep automation analysis on the player's last 100 actions "
            "and returns a suspicion score with signal breakdown.",
            parse_mode="Markdown",
        )
        return

    target = _find_player_for_logs(context.args[0])
    if not target:
        await update.message.reply_text(
            f"Player *{context.args[0]}* not found.",
            parse_mode="Markdown",
        )
        return

    tid = target["user_id"]
    tname = target.get("name", str(tid))

    entries = list(
        col("user_activity_logs").find({"user_id": tid})
        .sort("timestamp", -1)
        .limit(100)
    )

    signals = _analyze_bot_signals(entries)

    lines = [
        f"*BOT CHECK — {tname[:20]}*",
        f"Telegram ID: `{tid}`",
        f"Entries analysed: *{len(entries)}*",
        "",
    ]
    lines += _bot_signal_lines(signals)

    # ── Recent action timeline with ms timestamps ──
    if entries:
        lines += [
            "",
            "*Last 15 actions (ms precision):*",
            "",
        ]
        for e in entries[:15]:
            ts_str = _fmt_ts(e.get("timestamp"))
            activity = e.get("activity", "activity")
            details = f" — _{e['details']}_" if e.get("details") else ""
            lines.append(f"`{ts_str}` [{_activity_icon(activity)}] *{_activity_label(activity)}*{details}")

    await update.message.reply_text("\n".join(lines).strip(), parse_mode="Markdown")


# ─────────────────────────────────────────────
#  Log search
# ─────────────────────────────────────────────

async def logsearch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "*LOG SEARCH*\n\n"
            "Usage: `/logsearch [keyword]`\n"
            "Searches both admin logs and player activity logs.",
            parse_mode="Markdown",
        )
        return

    keyword = " ".join(context.args).strip()

    admin_results = list(
        col("admin_logs").find({
            "$or": [
                {"target_name": {"$regex": keyword, "$options": "i"}},
                {"details": {"$regex": keyword, "$options": "i"}},
                {"action": {"$regex": keyword, "$options": "i"}},
            ]
        }).sort("timestamp", -1).limit(10)
    )
    activity_results = list(
        col("user_activity_logs").find({
            "$or": [
                {"activity": {"$regex": keyword, "$options": "i"}},
                {"details": {"$regex": keyword, "$options": "i"}},
                {"username": {"$regex": keyword, "$options": "i"}},
                {"name": {"$regex": keyword, "$options": "i"}},
            ]
        }).sort("timestamp", -1).limit(10)
    )

    if not admin_results and not activity_results:
        await update.message.reply_text(
            f"No logs found for: *{keyword}*",
            parse_mode="Markdown",
        )
        return

    merged = []
    for entry in admin_results:
        admin = get_player(entry["admin_id"])
        aname = admin["name"] if admin else f"ID:{entry['admin_id']}"
        target_name = entry.get("target_name") or entry.get("target_id") or "unknown"
        merged.append({
            "timestamp": entry.get("timestamp"),
            "text": (
                f"[ADMIN] *{aname}*\n"
                f"  `{str(entry.get('action', '')).upper()}` -> *{target_name}*"
                + (f"\n  note: _{entry['details']}_" if entry.get("details") else "")
            ),
        })

    for entry in activity_results:
        player_name = entry.get("name") or entry.get("username") or str(entry.get("user_id"))
        activity = entry.get("activity", "activity")
        merged.append({
            "timestamp": entry.get("timestamp"),
            "text": (
                f"[USER] *{player_name}*\n"
                f"  *{_activity_label(activity)}*"
                + (f"\n  note: _{entry['details']}_" if entry.get("details") else "")
            ),
        })

    merged.sort(key=lambda item: item.get("timestamp") or datetime.min, reverse=True)
    merged = merged[:20]

    lines = [
        "*LOG SEARCH*",
        f'Query: "{keyword}"',
        f"Results: *{len(merged)}*",
        "",
    ]

    for item in merged:
        ts_str = _fmt_ts(item.get("timestamp"))           # ← milliseconds
        lines.append(f"`{ts_str}` {item['text']}")
        lines.append("")

    await update.message.reply_text("\n".join(lines).strip(), parse_mode="Markdown")
