from utils.guards import dm_only
import random
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, add_item
from config import LOTTERY_TIERS

@dm_only
async def lottery_play(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    args = context.args
    if len(args) < 2:
        tier_list = '\n'.join([
            f"  {t['emoji']} `{t['name'].lower():8}` — {t['cost']:,}¥ ticket  →  Win *{t['prize']:,}¥*"
            for t in LOTTERY_TIERS
        ])
        await update.message.reply_text(
            f"🎰 *DEMON SLAYER LOTTERY*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 Pick a number *1–100*\n"
            f"  ✨ Exact match  →  *JACKPOT!*\n"
            f"  🎊 Within ±5    →  *Consolation (2× ticket)*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🏷️ *TIERS*\n{tier_list}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Your Balance:  *{player['yen']:,}¥*\n\n"
            f"📖 Usage:  `/lottery [tier] [number]`\n"
            f"🔤 Example: `/lottery gold 42`\n"
            f"_Tiers: basic · silver · gold · diamond_",
            parse_mode='Markdown'
        )
        return

    tier_name = args[0].lower()
    tier = next((t for t in LOTTERY_TIERS if t['name'].lower() == tier_name), None)
    if not tier:
        await update.message.reply_text(
            "❌ *Invalid tier!*\n\nChoose: `basic` `silver` `gold` `diamond`",
            parse_mode='Markdown'
        )
        return

    try:
        guess = int(args[1])
    except ValueError:
        await update.message.reply_text("❌ Please enter a number between *1* and *100*.", parse_mode='Markdown')
        return

    if not 1 <= guess <= 100:
        await update.message.reply_text("❌ Number must be between *1* and *100*.", parse_mode='Markdown')
        return

    if player['yen'] < tier['cost']:
        await update.message.reply_text(
            f"❌ *Not enough Yen!*\n\n"
            f"Ticket cost:  *{tier['cost']:,}¥*\n"
            f"Your balance: *{player['yen']:,}¥*",
            parse_mode='Markdown'
        )
        return

    winning = random.randint(1, 100)
    new_yen = player['yen'] - tier['cost']

    if guess == winning:
        prize = tier['prize']
        new_yen += prize
        update_player(user_id, yen=new_yen)
        result = (
            f"🎉 *JACKPOT!!!*\n\n"
            f"🎰 Winning number:  *{winning}*\n"
            f"🎯 Your guess:      *{guess}*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Prize:    *+{prize:,}¥*\n"
            f"💰 Balance:  *{new_yen:,}¥*\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
        if tier['name'] == 'Diamond':
            add_item(user_id, 'Full Recovery Gourd', 'item')
            result += "\n🍶 *Bonus: Full Recovery Gourd!*"
    elif abs(guess - winning) <= 5:
        consolation = tier['cost'] * 2
        new_yen += consolation
        update_player(user_id, yen=new_yen)
        result = (
            f"🎊 *SO CLOSE!*\n\n"
            f"🎰 Winning number:  *{winning}*\n"
            f"🎯 Your guess:      *{guess}*  _(within 5!)_\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💰 Consolation:  *+{consolation:,}¥*\n"
            f"💰 Balance:      *{new_yen:,}¥*\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )
    else:
        update_player(user_id, yen=new_yen)
        result = (
            f"😔 *BETTER LUCK NEXT TIME*\n\n"
            f"🎰 Winning number:  *{winning}*\n"
            f"🎯 Your guess:      *{guess}*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💸 Lost:     *-{tier['cost']:,}¥*\n"
            f"💰 Balance:  *{new_yen:,}¥*\n"
            f"━━━━━━━━━━━━━━━━━━━━━"
        )

    await update.message.reply_text(result, parse_mode='Markdown')


# alias
async def lottery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await lottery_play(update, context)
