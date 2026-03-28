import random
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import (get_player, update_player, add_item,
                             add_referral, get_referral_count,
                             get_referral_earnings, was_referred, col)
import config

REFERRER_XP   = 500
REFERRER_YEN  = 500
REFERRER_SP   = 3    # SP bonus for referring a new player
REFEREE_XP    = 300
REFEREE_YEN   = 300
REFEREE_ITEMS = [
    ("Full Recovery Gourd", "item",     2),
    ("Stamina Pill",        "item",     3),
    ("Wisteria Antidote",   "item",     1),
    ("Demon Blood",         "material", 2),
]

# Milestone rewards
REFERRAL_MILESTONES = {
    5:  {"yen": 2000,  "xp": 1000,  "item": ("Boss Shard", "material", 1),   "label": "5 referrals"},
    10: {"yen": 5000,  "xp": 2500,  "item": ("Kizuki Blood", "material", 1), "label": "10 referrals"},
    20: {"yen": 10000, "xp": 5000,  "style_reward": True,                    "label": "20 referrals 🎉"},
    50: {"yen": 25000, "xp": 15000, "style_reward": True,                    "label": "50 referrals 👑"},
}


def _get_random_style_reward(player):
    """Give a random rare/legendary breathing style or demon art."""
    faction = player.get('faction', 'slayer')
    if faction == 'slayer':
        pool = [s for s in config.BREATHING_STYLES
                if 'RARE' in s.get('rarity','') or 'LEGENDARY' in s.get('rarity','')]
        # Exclude ones they already own
        pool = [s for s in pool if s['name'] != player.get('style')]
        # Exclude Stone (unique) if already taken
        from utils.database import col as _col
        if _col('players').find_one({'style': 'Stone Breathing', 'user_id': {'$ne': player['user_id']}}):
            pool = [s for s in pool if s['name'] != 'Stone Breathing']
    else:
        pool = [s for s in config.DEMON_ARTS
                if ('RARE' in s.get('rarity','') or 'LEGENDARY' in s.get('rarity',''))
                and s.get('gacha_weight', 1) > 0]
        pool = [s for s in pool if s['name'] != player.get('style')]

    if not pool:
        return None
    return random.choice(pool)


async def referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    bot_username   = getattr(config, 'BOT_USERNAME', 'your_bot')
    ref_code       = f"ref_{user_id}"
    ref_link       = f"https://t.me/{bot_username}?start={ref_code}"
    total_referred = get_referral_count(user_id)
    total_xp, total_yen = get_referral_earnings(user_id)

    from utils.database import get_referrer
    referrer_id   = get_referrer(user_id)
    referred_line = ""
    if referrer_id:
        referrer = get_player(referrer_id)
        rname = referrer['name'] if referrer else f"#{referrer_id}"
        referred_line = f"\n🤝 _Referred by_ *{rname}*\n"

    # Next milestone
    next_milestone = ""
    claimed = player.get('referral_milestones_claimed', [])
    for req, reward in sorted(REFERRAL_MILESTONES.items()):
        if total_referred < req and req not in claimed:
            left = req - total_referred
            bonus = "🎲 *RANDOM STYLE/ART*" if reward.get('style_reward') else f"+{reward['yen']:,}¥"
            next_milestone = f"\n🎯 *Next milestone:* {req} referrals ({left} to go) → {bonus}"
            break

    # Build milestone progress display
    milestone_lines = []
    for req, reward in sorted(REFERRAL_MILESTONES.items()):
        done = req in claimed or total_referred >= req
        icon = "✅" if req in claimed else ("🔓" if total_referred >= req else "🔒")
        label = reward['label']
        if reward.get('scroll_reward'):
            bonus = "📜 Technique Scroll"
        elif reward.get('style_reward'):
            bonus = "🎲 Random Rare/Legendary Style"
        else:
            bonus = f"+{reward['yen']:,}¥ +{reward['xp']:,}XP"
        milestone_lines.append(f"  {icon} *{req} refs* — {bonus}")

    await update.message.reply_text(
        f"╔══════════════════════╗\n"
        f"      📨 𝙍𝙀𝙁𝙀𝙍𝙍𝘼𝙇\n"
        f"╚══════════════════════╝\n\n"
        f"🔗 *Your link:*\n"
        f"  `{ref_link}`\n"
        f"{referred_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Your Stats:*\n"
        f"  👥 Referred:  *{total_referred}*\n"
        f"  ⭐ XP earned: *{total_xp:,}*\n"
        f"  💰 Yen earned: *{total_yen:,}¥*\n"
        f"{next_milestone}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 *MILESTONES:*\n"
        + '\n'.join(milestone_lines) +
        f"\n\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎁 *Per referral:*\n"
        f"  You: *+{REFERRER_XP} XP  +{REFERRER_YEN}¥  +{REFERRER_SP} SP*\n"
        f"  Friend: *+{REFEREE_XP} XP  +{REFEREE_YEN}¥ + items*",
        parse_mode='Markdown'
    )


async def process_referral_reward(context, referrer_id, new_user_id):
    """Called after new player finishes character creation."""
    referrer   = get_player(referrer_id)
    new_player = get_player(new_user_id)
    if not referrer or not new_player:
        return

    # Base rewards
    update_player(referrer_id,
                  xp=referrer['xp'] + REFERRER_XP,
                  yen=referrer['yen'] + REFERRER_YEN,
                  skill_points=referrer.get('skill_points', 0) + REFERRER_SP)
    update_player(new_user_id,
                  xp=new_player['xp'] + REFEREE_XP,
                  yen=new_player['yen'] + REFEREE_YEN)
    for item_name, item_type, qty in REFEREE_ITEMS:
        add_item(new_user_id, item_name, item_type, qty)

    # Check milestone rewards for referrer
    new_count = get_referral_count(referrer_id)
    claimed   = referrer.get('referral_milestones_claimed', [])
    milestone_msg = ""

    for req, reward in sorted(REFERRAL_MILESTONES.items()):
        if new_count >= req and req not in claimed:
            # Claim this milestone
            claimed.append(req)
            update_player(referrer_id,
                          yen=referrer['yen'] + REFERRER_YEN + reward.get('yen', 0),
                          xp=referrer['xp'] + REFERRER_XP + reward.get('xp', 0),
                          referral_milestones_claimed=claimed)

            if reward.get('item'):
                iname, itype, iqty = reward['item']
                add_item(referrer_id, iname, itype, iqty)

            if reward.get('style_reward'):
                chosen = _get_random_style_reward(referrer)
                if chosen:
                    update_player(referrer_id,
                                  style=chosen['name'],
                                  style_emoji=chosen['emoji'])
                    milestone_msg += (
                        f"\n\n🎲 *MILESTONE {req} REFERRALS!*\n"
                        f"━━━━━━━━━━━━━━━━━━━━━\n"
                        f"🎉 You unlocked a random style!\n\n"
                        f"{chosen['emoji']} *{chosen['name']}*\n"
                        f"{chosen['rarity']}\n\n"
                        f"_{chosen['description']}_\n\n"
                        f"_Your style has been changed!_"
                    )
            else:
                milestone_msg += (
                    f"\n\n🏆 *MILESTONE {req} REFERRALS!*\n"
                    f"+{reward.get('yen',0):,}¥  +{reward.get('xp',0):,}XP"
                )

    # Notify referrer
    try:
        await context.bot.send_message(
            chat_id=referrer_id,
            text=(
                f"🎉 *REFERRAL REWARD!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"👥 *{new_player['name']}* joined!\n\n"
                f"⭐ *+{REFERRER_XP} XP*\n"
                f"💰 *+{REFERRER_YEN}¥*\n"
                f"👥 Total referred: *{new_count}*"
                f"{milestone_msg}"
            ),
            parse_mode='Markdown'
        )
    except Exception:
        pass

    # Notify new player
    try:
        await context.bot.send_message(
            chat_id=new_user_id,
            text=(
                f"🎁 *REFERRAL BONUS!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"Joined via *{referrer['name']}'s* link!\n\n"
                f"⭐ *+{REFEREE_XP} XP*\n"
                f"💰 *+{REFEREE_YEN}¥*\n"
                f"🍶 ×2 Full Recovery Gourd\n"
                f"💊 ×3 Stamina Pill\n"
                f"🌿 ×1 Wisteria Antidote\n"
                f"🩸 ×2 Demon Blood\n\n"
                f"_Good luck on your journey!_"
            ),
            parse_mode='Markdown'
        )
    except Exception:
        pass
