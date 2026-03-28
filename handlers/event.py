"""
/event - Admin creates customisable events (voting, polls, giveaways, etc.)
/events - Players view active events
/vote [option] - Players vote in active voting events
/eventend [id] - Admin ends event and announces winner
"""

import re
import secrets
from datetime import datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, TimedOut
from telegram.ext import ContextTypes

from utils.database import add_item, col, get_player, update_player


async def _safe_edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        if any(x in err.lower() for x in ("can't be edited", "message to edit not found", "not found")):
            try:
                await query.message.reply_text(text, **kwargs)
            except Exception:
                pass
            return
        raise
    except TimedOut:
        pass


def _event_short_id(event_doc) -> str:
    return str(event_doc.get("_id", ""))[-6:].upper()


def _reward_item_type(item_name: str) -> str:
    listing = col("market_listings").find_one({"item_name": item_name})
    if listing and listing.get("item_type"):
        return listing["item_type"]
    black_market = col("black_market").find_one({"item_name": item_name})
    if black_market and black_market.get("item_type"):
        return black_market["item_type"]
    lowered = item_name.lower()
    if "blade" in lowered or "sword" in lowered:
        return "sword"
    if "armor" in lowered or "uniform" in lowered or "haori" in lowered:
        return "armor"
    return "material"


def _apply_event_reward(user_id: int, reward_text: str) -> str:
    player = get_player(user_id)
    if not player or not reward_text:
        return reward_text or "No reward"

    reward = reward_text.strip()
    yen_match = re.fullmatch(r"(?i)\s*([\d,]+)\s*(yen|¥)\s*", reward)
    if yen_match:
        amount = int(yen_match.group(1).replace(",", ""))
        update_player(user_id, yen=player.get("yen", 0) + amount)
        return f"{amount:,} Yen"

    item_match = re.fullmatch(r"\s*(.+?)\s*x\s*(\d+)\s*", reward, re.IGNORECASE)
    if item_match:
        item_name = item_match.group(1).strip()
        quantity = int(item_match.group(2))
        add_item(user_id, item_name, _reward_item_type(item_name), quantity)
        return f"{item_name} x{quantity}"

    add_item(user_id, reward, _reward_item_type(reward), 1)
    return reward


async def events(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active = list(col("events").find({"status": "active"}).sort("created_at", -1))
    msg = update.message if update.message else update.callback_query.message

    if not active:
        await msg.reply_text(
            "🎪 *No active events right now.*\n\n_Check back later - admins post events regularly!_",
            parse_mode="Markdown",
        )
        return

    for ev in active:
        await _send_event_card(msg, ev, context)


async def _send_event_card(msg, ev, context):
    etype = ev.get("type", "announcement")
    eid = _event_short_id(ev)
    title = ev.get("title", "Event")
    desc = ev.get("description", "")
    ends = ev.get("ends_at")
    reward = ev.get("reward", "")

    time_left = ""
    if ends:
        remaining = ends - datetime.now()
        if remaining.total_seconds() > 0:
            hrs = int(remaining.total_seconds() // 3600)
            mins = int((remaining.total_seconds() % 3600) // 60)
            time_left = f"\n⏳ Ends in: *{hrs}h {mins}m*"

    lines = [
        f"🎪 *{title}*",
        f"📋 *ID:* `#{eid}`",
        f"🎭 *Type:* {etype.title()}",
        time_left,
        f"\n{desc}\n",
    ]

    if reward:
        lines.append(f"🎁 *Reward:* {reward}")

    buttons = []
    if etype == "vote":
        options = ev.get("options", [])
        votes = ev.get("votes", {})
        total_votes = sum(votes.values()) if votes else 0
        lines.append("\n📊 *Vote Options:*")
        for i, opt in enumerate(options):
            count = votes.get(opt, 0)
            pct = int(count / total_votes * 100) if total_votes > 0 else 0
            bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
            lines.append(f"  *{i+1}.* {opt}\n     `[{bar}]` {count} votes ({pct}%)")
            buttons.append([InlineKeyboardButton(f"Vote: {opt}", callback_data=f"event_vote_{eid}_{i}")])
        lines.append(f"\n👥 Total votes: *{total_votes}*")
    elif etype == "poll":
        for i, opt in enumerate(ev.get("options", [])):
            buttons.append([InlineKeyboardButton(opt, callback_data=f"event_poll_{eid}_{i}")])
    elif etype == "giveaway":
        entries = ev.get("entries", [])
        lines.append(f"\n🎟️ *Entries:* {len(entries)}")
        buttons.append([InlineKeyboardButton("🎟️ Enter Giveaway", callback_data=f"event_enter_{eid}")])

    kb = InlineKeyboardMarkup(buttons) if buttons else None
    await msg.reply_text("\n".join(l for l in lines if l is not None), parse_mode="Markdown", reply_markup=kb)


async def event_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.admin import has_admin_access

    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await events(update, context)
        return

    if not context.args:
        await update.message.reply_text(
            "📖 *Usage:*\n\n"
            "`/event vote [hours] [title] | [desc] | opt1, opt2, opt3 | [reward]`\n"
            "`/event giveaway [hours] [title] | [desc] | [reward]`\n"
            "`/event announce [title] | [message]`\n\n"
            "`/eventend [id]` - End event + announce winner\n"
            "`/eventlist` - List all events",
            parse_mode="Markdown",
        )
        return

    etype = context.args[0].lower()
    rest = " ".join(context.args[1:])

    if etype == "vote":
        try:
            parts = rest.split("|")
            hours = int(parts[0].strip().split()[0])
            title = " ".join(parts[0].strip().split()[1:])
            desc = parts[1].strip()
            opts = [o.strip() for o in parts[2].split(",")]
            reward = parts[3].strip() if len(parts) > 3 else ""
        except Exception:
            await update.message.reply_text(
                "❌ Format: `/event vote [hours] [title] | [desc] | opt1, opt2 | [reward]`",
                parse_mode="Markdown",
            )
            return

        if len(opts) < 2:
            await update.message.reply_text("❌ Need at least 2 voting options.")
            return

        result = col("events").insert_one(
            {
                "type": "vote",
                "title": title,
                "description": desc,
                "options": opts,
                "votes": {opt: 0 for opt in opts},
                "voted_users": [],
                "reward": reward,
                "ends_at": datetime.now() + timedelta(hours=hours),
                "status": "active",
                "created_by": user_id,
                "created_at": datetime.now(),
            }
        )
        await update.message.reply_text(
            f"✅ *Vote event created!*\n\n📋 ID: `#{str(result.inserted_id)[-6:].upper()}`",
            parse_mode="Markdown",
        )
        return

    if etype == "giveaway":
        try:
            parts = rest.split("|")
            hours = int(parts[0].strip().split()[0])
            title = " ".join(parts[0].strip().split()[1:])
            desc = parts[1].strip()
            reward = parts[2].strip() if len(parts) > 2 else "Surprise!"
        except Exception:
            await update.message.reply_text(
                "❌ Format: `/event giveaway [hours] [title] | [desc] | [reward]`",
                parse_mode="Markdown",
            )
            return

        result = col("events").insert_one(
            {
                "type": "giveaway",
                "title": title,
                "description": desc,
                "reward": reward,
                "entries": [],
                "ends_at": datetime.now() + timedelta(hours=hours),
                "status": "active",
                "created_by": user_id,
                "created_at": datetime.now(),
            }
        )
        await update.message.reply_text(
            f"✅ *Giveaway created!*\n\n📋 ID: `#{str(result.inserted_id)[-6:].upper()}`\n🎁 Reward: {reward}",
            parse_mode="Markdown",
        )
        return

    if etype == "announce":
        try:
            parts = rest.split("|", 1)
            title = parts[0].strip()
            desc = parts[1].strip() if len(parts) > 1 else ""
        except Exception:
            await update.message.reply_text(
                "❌ Format: `/event announce [title] | [message]`",
                parse_mode="Markdown",
            )
            return

        result = col("events").insert_one(
            {
                "type": "announcement",
                "title": title,
                "description": desc,
                "status": "active",
                "created_by": user_id,
                "created_at": datetime.now(),
                "ends_at": datetime.now() + timedelta(days=7),
            }
        )
        await update.message.reply_text(
            f"✅ *Announcement posted!*\n\nID: `#{str(result.inserted_id)[-6:].upper()}`",
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text("❌ Unknown type. Use: `vote`, `giveaway`, `announce`", parse_mode="Markdown")


async def event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split("_")
    action = parts[1]
    eid_short = parts[2]

    ev = next(
        (e for e in col("events").find({"status": "active"}) if _event_short_id(e) == eid_short.upper()),
        None,
    )
    if not ev:
        await query.answer("❌ Event not found or ended.", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await query.answer("❌ Create a character first with /start", show_alert=True)
        return

    if action == "vote":
        opt_idx = int(parts[3])
        options = ev.get("options", [])
        if opt_idx >= len(options):
            await query.answer("❌ Invalid option.", show_alert=True)
            return
        if user_id in ev.get("voted_users", []):
            await query.answer("✅ You already voted!", show_alert=True)
            return

        chosen = options[opt_idx]
        col("events").update_one(
            {"_id": ev["_id"]},
            {"$inc": {f"votes.{chosen}": 1}, "$push": {"voted_users": user_id}},
        )
        await query.answer(f"✅ Voted for: {chosen}!", show_alert=True)
        ev_updated = col("events").find_one({"_id": ev["_id"]})
        if ev_updated:
            try:
                await _send_event_card(query.message, ev_updated, context)
            except Exception:
                pass
        return

    if action == "enter":
        result = col("events").update_one(
            {"_id": ev["_id"], "entries": {"$ne": user_id}},
            {"$addToSet": {"entries": user_id}},
        )
        if result.modified_count == 0:
            await query.answer("You already joined!", show_alert=True)
            return
        updated = col("events").find_one({"_id": ev["_id"]}) or ev
        await query.answer(f"Entered! ({len(updated.get('entries', []))} entries total)", show_alert=True)


async def eventend(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.admin import has_admin_access

    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/eventend [id]`", parse_mode="Markdown")
        return

    eid_short = context.args[0].lstrip("#").upper()
    ev = next((e for e in col("events").find() if _event_short_id(e) == eid_short), None)
    if not ev:
        await update.message.reply_text(f"❌ Event `#{eid_short}` not found.", parse_mode="Markdown")
        return

    col("events").update_one({"_id": ev["_id"]}, {"$set": {"status": "ended"}})

    etype = ev.get("type", "announcement")
    result_msg = f"🎪 *EVENT ENDED: {ev['title']}*\n━━━━━━━━━━━━━━━━━━━━━\n\n"

    if etype == "vote":
        votes = ev.get("votes", {})
        total = sum(votes.values())
        winner = max(votes, key=votes.get) if votes else "No votes"
        result_msg += f"🏆 *Winner:* {winner}\n\n📊 *Final Results:*\n"
        for opt, count in sorted(votes.items(), key=lambda x: x[1], reverse=True):
            pct = int(count / total * 100) if total > 0 else 0
            result_msg += f"  {'🥇' if opt == winner else '  '} *{opt}*: {count} votes ({pct}%)\n"
        result_msg += f"\n👥 Total voters: *{len(ev.get('voted_users', []))}*"

    elif etype == "giveaway":
        entries = list(dict.fromkeys(ev.get("entries", [])))
        if entries:
            winner_id = secrets.choice(entries)
            winner_p = get_player(winner_id)
            winner_name = winner_p["name"] if winner_p else f"ID:{winner_id}"
            delivered_reward = _apply_event_reward(winner_id, ev.get("reward", "?"))
            result_msg += (
                f"🏆 *Winner:* {winner_name}\n"
                f"🎁 *Prize:* {delivered_reward}\n"
                f"👥 Total entries: {len(entries)}\n"
                f"✅ *Reward transferred automatically*"
            )
            try:
                await context.bot.send_message(
                    chat_id=winner_id,
                    text=(
                        f"🎊 *YOU WON THE GIVEAWAY!*\n\n"
                        f"🎁 Prize: *{delivered_reward}*\n\n"
                        f"✅ The reward has been added to your account automatically."
                    ),
                    parse_mode="Markdown",
                )
            except Exception:
                pass
        else:
            result_msg += "😔 No entries - no winner."

    await update.message.reply_text(result_msg, parse_mode="Markdown")


async def eventlist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.admin import has_admin_access

    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return

    evs = list(col("events").find().sort("created_at", -1).limit(10))
    if not evs:
        await update.message.reply_text("No events found.")
        return

    lines = ["🎪 *ALL EVENTS*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    status_icon = {"active": "🟢", "ended": "🔴", "cancelled": "⚫"}
    for ev in evs:
        lines.append(f"{status_icon.get(ev.get('status', ''), '⚪')} `#{_event_short_id(ev)}` *{ev['title']}* _{ev['type']}_")
    lines.append("\n`/eventend [id]` to end an event")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def eventresults(update, context):
    await eventend(update, context)


async def vote_cmd(update, context):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return
    if not context.args:
        await update.message.reply_text(
            "🗳️ *VOTE*\n\nUsage: `/vote [option number]`\n\nSee /events for active votes.",
            parse_mode="Markdown",
        )
        return

    ev = col("events").find_one({"type": "vote", "status": "active"})
    if not ev:
        await update.message.reply_text("❌ No active voting event right now. Check /events.")
        return

    opts = list(ev.get("votes", {}).keys())
    try:
        idx = int(context.args[0]) - 1
        if idx < 0 or idx >= len(opts):
            raise ValueError
    except (ValueError, IndexError):
        opts_display = "\n".join(f"{i+1}. {o}" for i, o in enumerate(opts))
        await update.message.reply_text(
            f"🗳️ *{ev['title']}*\n\nOptions:\n{opts_display}\n\nUse `/vote [number]`",
            parse_mode="Markdown",
        )
        return

    if user_id in ev.get("voted_users", []):
        await update.message.reply_text("✅ You have already voted in this event!")
        return

    chosen = opts[idx]
    col("events").update_one(
        {"_id": ev["_id"]},
        {"$inc": {f"votes.{chosen}": 1}, "$push": {"voted_users": user_id}},
    )
    await update.message.reply_text(
        f"✅ *Vote cast!*\n\n🗳️ You voted for: *{chosen}*\n\nSee results in /events.",
        parse_mode="Markdown",
    )


async def vote_callback(update, context):
    await event_callback(update, context)
