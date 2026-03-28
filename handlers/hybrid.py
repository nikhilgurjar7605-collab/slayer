"""
/hybrid — Unlock hybrid mode: use both breathing + demon art
Admin can enable/disable. Requires Slayer Mark + high rank.
"""
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, col
from utils.guards import dm_only
from config import BREATHING_STYLES, DEMON_ARTS, OWNER_ID


def is_hybrid_enabled():
    doc = col("settings").find_one({"key": "hybrid_enabled"})
    return doc.get("value", False) if doc else False


def has_demon_mark(player):
    return bool(player.get('demon_mark'))


@dm_only
async def hybrid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    if not is_hybrid_enabled():
        await update.message.reply_text(
            "🔒 *Hybrid mode is not yet available.*\n\n"
            "_This feature requires admin activation._",
            parse_mode='Markdown'
        )
        return

    # Check if already hybrid
    if player.get('hybrid_style'):
        hs      = player['hybrid_style']
        he      = player.get('hybrid_emoji', '⚡')
        s_mark  = "🔥 Active" if player.get('slayer_mark') else "🔒 Locked"
        d_mark  = "🔴 Active" if player.get('demon_mark')  else "🔒 Locked"
        fe      = '🗡️' if player['faction'] == 'slayer' else '👹'
        await update.message.reply_text(
            f"╔══════════════════════╗\n"
            f"      ⚡ 𝙃𝙔𝘽𝙍𝙄𝘿 𝙈𝙊𝘿𝙀\n"
            f"╚══════════════════════╝\n\n"
            f"✅ *Hybrid Activated!*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"{fe} Primary: *{player['style']}* {player.get('style_emoji','')}\n"
            f"⚡ Hybrid:  *{hs}* {he}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"🔥 Slayer Mark: {s_mark}\n"
            f"🔴 Demon Mark:  {d_mark}\n\n"
            f"_Both arts available in /explore techniques_\n"
            f"💡 `/info` to see your forms",
            parse_mode='Markdown'
        )
        return

    faction = player['faction']

    # Requirements check
    from utils.helpers import get_level
    level = get_level(player['xp'])

    requirements = []
    met = True

    if faction == 'slayer':
        # Slayer needs ONLY Slayer Mark
        if not player.get('slayer_mark'):
            requirements.append("❌ *Slayer Mark* required — use `/slayermark`")
            met = False
        else:
            requirements.append("✅ Slayer Mark active")
        if level < 30:
            requirements.append(f"❌ Level 30+ required _(you are Lv.{level})_")
            met = False
        else:
            requirements.append(f"✅ Level {level} ✓")
    else:
        # Demon needs ONLY Demon Mark
        if not has_demon_mark(player):
            requirements.append("❌ *Demon Mark* required — use `/demonmark`")
            met = False
        else:
            requirements.append("✅ Demon Mark active")
        if level < 30:
            requirements.append(f"❌ Level 30+ required _(you are Lv.{level})_")
            met = False
        else:
            requirements.append(f"✅ Level {level} ✓")

    if not met:
        req_text = '\n'.join(f"  {r}" for r in requirements)
        await update.message.reply_text(
            f"╔══════════════════════╗\n"
            f"      ⚡ 𝙃𝙔𝘽𝙍𝙄𝘿 𝙈𝙊𝘿𝙀\n"
            f"╚══════════════════════╝\n\n"
            f"🔓 *Requirements:*\n{req_text}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚡ *Hybrid Mode* = use BOTH Breathing + Demon Art in battle\n"
            f"_The rarest awakening — one soul, two powers._\n\n"
            f"🗡️ Slayers need: *Slayer Mark* (Lv.30+)\n"
            f"👹 Demons need:  *Demon Mark* (Lv.30+)",
            parse_mode='Markdown'
        )
        return

    # Choose hybrid style — opposite faction
    if not context.args:
        pool  = DEMON_ARTS if faction == 'slayer' else BREATHING_STYLES
        label = "Demon Art" if faction == 'slayer' else "Breathing Style"

        lines = [
            f"╔══════════════════════╗",
            f"      ⚡ 𝘾𝙃𝙊𝙊𝙎𝙀 𝙃𝙔𝘽𝙍𝙄𝘿",
            f"╚══════════════════════╝\n",
            f"✅ Requirements met! Choose your hybrid *{label}*:\n",
            f"━━━━━━━━━━━━━━━━━━━━━\n",
        ]
        # Show only common/rare (no legendary for hybrid)
        available = [s for s in pool if '⭐⭐' in s.get('rarity','') or '⭐⭐⭐ RARE' in s.get('rarity','')]
        for s in available:
            lines.append(f"╰➤ {s['emoji']} *{s['name']}*  {s['rarity']}")

        lines += [
            f"\n━━━━━━━━━━━━━━━━━━━━━",
            f"💡 `/hybrid [name]` to choose",
            f"_Example: `/hybrid Blood Whip`_",
            f"\n⚠️ _Legendary styles cannot be hybridized_",
        ]
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    style_name = ' '.join(context.args)
    pool       = DEMON_ARTS if faction == 'slayer' else BREATHING_STYLES
    available  = [s for s in pool if '⭐⭐' in s.get('rarity','') or '⭐⭐⭐ RARE' in s.get('rarity','')]
    chosen     = next((s for s in available if s['name'].lower() == style_name.lower()), None)

    if not chosen:
        await update.message.reply_text(
            f"❌ *{style_name}* not available for hybrid.\n"
            f"Use `/hybrid` to see options.",
            parse_mode='Markdown'
        )
        return

    update_player(user_id, hybrid_style=chosen['name'], hybrid_emoji=chosen['emoji'])

    s_mark = "🔥 Active" if player.get('slayer_mark') else "🔒 Locked"
    d_mark = "🔴 Active" if player.get('demon_mark')  else "🔒 Locked"
    fe     = '🗡️' if faction == 'slayer' else '👹'

    await update.message.reply_text(
        f"╔══════════════════════╗\n"
        f"      ⚡ 𝙃𝙔𝘽𝙍𝙄𝘿 𝙐𝙉𝙇𝙊𝘾𝙆𝙀𝘿!\n"
        f"╚══════════════════════╝\n\n"
        f"{fe} Primary: *{player['style']}* {player.get('style_emoji','')}\n"
        f"⚡ Hybrid:  *{chosen['name']}* {chosen['emoji']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 Slayer Mark: {s_mark}\n"
        f"🔴 Demon Mark:  {d_mark}\n\n"
        f"_Both arts are now available in /explore!_\n"
        f"_Tap Technique in battle → both styles appear._",
        parse_mode='Markdown'
    )


async def demonmark(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Demon equivalent of slayer mark."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return
    if player.get('faction') != 'demon':
        await update.message.reply_text("❌ Only demons can activate the Demon Mark.")
        return

    from utils.helpers import get_level
    level = get_level(player['xp'])

    if player.get('demon_mark'):
        await update.message.reply_text(
            "🔴 *DEMON MARK — ACTIVE*\n\n"
            "Your mark is already awakened.\n"
            "_You fight at peak demon power._",
            parse_mode='Markdown'
        )
        return

    if level < 25:
        await update.message.reply_text(
            f"🔒 *Demon Mark requires Lv.25+*\n\nYou are Lv.{level}.",
            parse_mode='Markdown'
        )
        return

    if player['yen'] < 5000:
        await update.message.reply_text(
            f"❌ Need *5,000¥* to awaken your mark.\nYou have *{player['yen']:,}¥*.",
            parse_mode='Markdown'
        )
        return

    new_str    = player['str_stat'] + 25
    new_spd    = player['spd'] + 18
    new_max_hp = player['max_hp'] + 60
    update_player(user_id,
                  demon_mark=1,
                  yen=player['yen'] - 5000,
                  str_stat=new_str,
                  spd=new_spd,
                  max_hp=new_max_hp,
                  hp=new_max_hp)

    await update.message.reply_text(
        "🔴 *𝘿𝙀𝙈𝙊𝙉 𝙈𝘼𝙍𝙆 𝘼𝙒𝘼𝙆𝙀𝙉𝙀𝘿!*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "_The mark of the Demon King burns on your flesh!_\n"
        "_Your power transcends human limits..._\n\n"
        "✅ *Bonuses Applied:*\n"
        "  💪 STR:      +25\n"
        "  ⚡ SPD:      +18\n"
        "  ❤️ Max HP:   +60\n"
        "  🔴 Combat:   +20% all damage\n\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "_Required for `/hybrid` mode_",
        parse_mode='Markdown'
    )


async def hybridtoggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.admin import has_admin_access
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return
    current = is_hybrid_enabled()
    new_val = not current
    col("settings").update_one(
        {"key": "hybrid_enabled"},
        {"$set": {"key": "hybrid_enabled", "value": new_val}},
        upsert=True
    )
    status = "✅ ENABLED" if new_val else "🔒 DISABLED"
    await update.message.reply_text(f"⚡ Hybrid system: *{status}*", parse_mode='Markdown')
