from telegram.error import BadRequest, TimedOut
from datetime import datetime, date, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, add_item

async def _safe_edit(query, text, **kwargs):
    """Edit a message safely, falling back to reply on failure."""
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        elif any(x in err.lower() for x in ("can't be edited", "message to edit not found", "not found")):
            try:
                await query.message.reply_text(text, **kwargs)
            except Exception:
                pass
        else:
            raise
    except TimedOut:
        pass



DAILY_REWARDS = {
    (1,5):   {"xp":200,  "yen":100,  "item":"Stamina Pill",        "item_emoji":"💊"},
    (6,10):  {"xp":400,  "yen":250,  "item":"Full Recovery Gourd", "item_emoji":"🍶"},
    (11,20): {"xp":700,  "yen":500,  "item":"Full Recovery Gourd", "item_emoji":"🍶"},
    (21,30): {"xp":1000, "yen":1000, "item":"Full Recovery Gourd", "item_emoji":"🍶"},
}

STREAK_BONUSES = {
    3:   {"xp_mult":1.5,  "bonus_item":None,                      "bonus_emoji":""},
    7:   {"xp_mult":2.0,  "bonus_item":"Wisteria Antidote",       "bonus_emoji":"🌿"},
    14:  {"xp_mult":3.0,  "bonus_item":"Full Recovery Gourd",     "bonus_emoji":"🍶"},
    30:  {"xp_mult":6.0,  "bonus_item":"Full Recovery Gourd",     "bonus_emoji":"🍶"},
    100: {"xp_mult":10.0, "bonus_item":"Jet Black Nichirin Blade","bonus_emoji":"⬛"},
}

def get_daily_reward(level):
    for (lo, hi), reward in DAILY_REWARDS.items():
        if lo <= level <= hi:
            return dict(reward)
    return {"xp":200,"yen":100,"item":"Stamina Pill","item_emoji":"💊"}

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        msg = update.message or update.callback_query.message
        await msg.reply_text("❌ No character found. Use /start to create one.")
        return

    from utils.helpers import get_level
    now     = datetime.utcnow()
    today   = date.today().isoformat()
    level   = get_level(player['xp'])
    reward  = get_daily_reward(level)

    last_daily = player['last_daily']
    if last_daily:
        try:
            # Handle both datetime objects (MongoDB) and ISO strings (SQLite legacy)
            if isinstance(last_daily, str):
                last_dt = datetime.fromisoformat(last_daily)
            else:
                last_dt = last_daily.replace(tzinfo=None) if hasattr(last_daily, 'tzinfo') else last_daily
            diff    = now - last_dt
            if diff.total_seconds() < 86400:
                remaining = timedelta(seconds=86400) - diff
                hrs  = int(remaining.total_seconds() // 3600)
                mins = int((remaining.total_seconds() % 3600) // 60)
                msg = update.message or update.callback_query.message
                await msg.reply_text(
                    f"⏳ *DAILY REWARD*\n\n"
                    f"✅ Already claimed today!\n\n"
                    f"⌚ Next reward in:  *{hrs}h {mins}m*\n"
                    f"🔥 Current streak:  *{player['daily_streak']} days*",
                    parse_mode='Markdown'
                )
                return
        except Exception:
            pass

    yesterday = (date.today() - timedelta(days=1)).isoformat()
    last_streak_day = player.get('last_streak_day','')
    new_streak = player['daily_streak'] + 1 if last_streak_day == yesterday else 1

    # Find applicable streak bonus
    streak_bonus = None
    for day_req in sorted(STREAK_BONUSES.keys(), reverse=True):
        if new_streak >= day_req:
            streak_bonus = STREAK_BONUSES[day_req]
            break

    xp_gain  = reward['xp']
    yen_gain = reward['yen']
    bonus_lines = []

    if streak_bonus:
        xp_gain = int(xp_gain * streak_bonus['xp_mult'])
        pct = int((streak_bonus['xp_mult'] - 1)*100)
        bonus_lines.append(f"🔥 Streak bonus:  *+{pct}% XP!*")
        if streak_bonus['bonus_item']:
            add_item(user_id, streak_bonus['bonus_item'], 'item')
            bonus_lines.append(f"{streak_bonus['bonus_emoji']} Bonus item:  *{streak_bonus['bonus_item']}*")

    add_item(user_id, reward['item'], 'item')
    update_player(
        user_id,
        xp=player['xp'] + xp_gain,
        yen=player['yen'] + yen_gain,
        last_daily=now.isoformat(),
        daily_streak=new_streak,
        last_streak_day=today
    )

    next_milestone = ""
    for day_req in sorted(STREAK_BONUSES.keys()):
        if new_streak < day_req:
            next_milestone = f"\n⏭️ _Next milestone: Day {day_req} ({day_req - new_streak} days away)_"
            break

    bonus_text = '\n'.join(bonus_lines)
    msg = update.message or update.callback_query.message
    await msg.reply_text(
        f"☀️ *DAILY REWARD CLAIMED!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ XP:    *+{xp_gain:,}*\n"
        f"💰 Yen:   *+{yen_gain:,}¥*\n"
        f"{reward['item_emoji']} Item:   *{reward['item']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 Streak:  *{new_streak} days*{next_milestone}\n"
        + (f"\n{bonus_text}\n" if bonus_text else "") +
        f"\n⌚ _Come back in 24h for tomorrow's reward!_",
        parse_mode='Markdown'
    )

async def streak(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        msg = update.message or update.callback_query.message
        await msg.reply_text("❌ No character found.")
        return

    s = player['daily_streak']
    lines = [
        f"🔥 *DAILY STREAK*",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"🗓️ Current Streak:  *{s} days*",
        f"",
        f"🏆 *MILESTONES*",
        f"  Day 3    →  +50% XP",
        f"  Day 7    →  +100% XP  🌿 Wisteria Antidote",
        f"  Day 14   →  +200% XP  🍶 Recovery Gourd",
        f"  Day 30   →  +500% XP  🍶 Recovery Gourd",
        f"  Day 100  →  +900% XP  ⬛ Jet Black Nichirin Blade  🎊",
        f"",
        f"⚠️ _Miss a day → streak resets to 0_",
        f"━━━━━━━━━━━━━━━━━━━━━",
    ]
    for day_req in sorted(STREAK_BONUSES.keys()):
        if s < day_req:
            lines.append(f"⏭️ _Next milestone: Day {day_req}  ({day_req - s} days away)_")
            break
    else:
        lines.append("🏆 *ALL MILESTONES REACHED — MAX STREAK!* 🎊")

    msg = update.message or update.callback_query.message
    await msg.reply_text('\n'.join(lines), parse_mode='Markdown')
