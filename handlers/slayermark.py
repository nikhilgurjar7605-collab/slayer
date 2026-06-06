import random
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, update_player
from utils.helpers import get_level

SLAYER_MARK_COST      = 50000
SLAYER_MARK_MIN_LEVEL = 25
SLAYER_MARK_MIN_KILLS = 150
SLAYER_MARK_CHANCE    = 0.10

async def slayermark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    if player['faction'] != 'slayer':
        await update.message.reply_text(
            "❌ *SLAYER MARK*\n\n"
            "🗡️ Only Demon Slayers can awaken the Mark.\n"
            "👹 Demons have their own power — master your Blood Demon Art!",
            parse_mode='Markdown'
        )
        return

    if player.get('slayer_mark'):
        await update.message.reply_text(
            "🔥 *SLAYER MARK — AWAKENED*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Your mark is already blazing!\n\n"
            "✅ *Active Bonuses:*\n"
            "  💪 STR +20\n"
            "  ⚡ SPD +15\n"
            "  ❤️ Max HP +50\n"
            "  💨 Technique DMG +25%\n"
            "━━━━━━━━━━━━━━━━━━━━━",
            parse_mode='Markdown'
        )
        return

    level = get_level(player['xp'])
    issues = []
    if level < SLAYER_MARK_MIN_LEVEL:
        issues.append(f"  ❌ Level {SLAYER_MARK_MIN_LEVEL}+ required  _(you: Lv.{level})_")
    kills = player.get('demons_slain', 0)
    if kills < SLAYER_MARK_MIN_KILLS:
        issues.append(f"  ❌ {SLAYER_MARK_MIN_KILLS}+ enemies slain  _(you: {kills})_")
    if player['yen'] < SLAYER_MARK_COST:
        issues.append(f"  ❌ {SLAYER_MARK_COST:,}¥ fee  _(you: {player['yen']:,}¥)_")

    if issues:
        req_text = '\n'.join(issues)
        await update.message.reply_text(
            f"🔥 *SLAYER MARK AWAKENING*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"⚠️ *Requirements not met:*\n{req_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 *Requirements:*\n"
            f"  📈 Level {SLAYER_MARK_MIN_LEVEL}+\n"
            f"  💀 {SLAYER_MARK_MIN_KILLS}+ enemies slain\n"
            f"  💰 {SLAYER_MARK_COST:,}¥ fee\n"
            f"  🎲 {int(SLAYER_MARK_CHANCE*100)}% success chance",
            parse_mode='Markdown'
        )
        return

    # Attempt awakening
    update_player(user_id, yen=player['yen'] - SLAYER_MARK_COST)

    if random.random() < SLAYER_MARK_CHANCE:
        new_str    = player['str_stat'] + 22
        new_spd    = player['spd'] + 18
        new_max_hp = player['max_hp'] + 55
        update_player(user_id, slayer_mark=1, str_stat=new_str, spd=new_spd,
                       max_hp=new_max_hp, hp=new_max_hp)
        await update.message.reply_text(
            f"🔥 *SLAYER MARK AWAKENED!!!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"_The mark blazes on your skin!\n"
            f"A power beyond human limits..._\n\n"
            f"✅ *Bonuses Applied:*\n"
            f"  💪 STR:    +22\n"
            f"  ⚡ SPD:    +18\n"
            f"  ❤️ Max HP: +55\n"
            f"  💨 Combat DMG: +25%\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ _The mark may shorten your lifespan..._",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            f"💔 *AWAKENING FAILED...*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"_The mark did not awaken this time._\n"
            f"_Your will wasn't strong enough yet._\n\n"
            f"💸 Fee consumed: *{SLAYER_MARK_COST:,}¥*\n"
            f"💰 Remaining:    *{player['yen'] - SLAYER_MARK_COST:,}¥*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"💡 Keep training and try again!",
            parse_mode='Markdown'
        )
