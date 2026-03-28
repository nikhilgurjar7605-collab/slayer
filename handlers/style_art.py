import os
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, update_player
from utils.helpers import get_level, get_unlocked_forms
from utils.guards import dm_only
from config import BREATHING_STYLES, DEMON_ARTS, TECHNIQUES
from handlers.imgupload import get_style_image


def find_breathing(name):
    n = name.lower().strip()
    return next((s for s in BREATHING_STYLES if s['name'].lower() == n
                 or n in s['name'].lower()), None)


def find_demon_art(name):
    n = name.lower().strip()
    return next((a for a in DEMON_ARTS if a['name'].lower() == n
                 or n in a['name'].lower()), None)


def rarity_color(rarity):
    if 'LEGENDARY' in rarity:
        return '??'
    if 'RARE' in rarity:
        return '??'
    return '?'
def _resolve_style_media(style_name, style):
    media, media_type = get_style_image(style_name)
    if media:
        return media, media_type
    url = str((style or {}).get('image_url') or '').strip()
    if url.startswith('http'):
        return url, 'url'
    local = str((style or {}).get('image') or '').strip()
    if local:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_path = os.path.join(base_dir, local)
        if os.path.exists(full_path):
            return full_path, 'local'
    return None, None
async def _reply_style_card(message, style_name, style, text):
    media, media_type = _resolve_style_media(style_name, style)
    if media_type == 'file_id':
        await message.reply_photo(photo=media, caption=text, parse_mode='Markdown')
        return
    if media_type == 'url':
        await message.reply_photo(photo=media, caption=text, parse_mode='Markdown')
        return
    if media_type == 'local':
        with open(media, 'rb') as img:
            await message.reply_photo(photo=img, caption=text, parse_mode='Markdown')
        return
    await message.reply_text(text, parse_mode='Markdown')
# ── /breathing ────────────────────────────────────────────────────────────

async def breathing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    if player['faction'] != 'slayer':
        await update.message.reply_text(
            "❌ Only Demon Slayers have breathing styles!\n"
            "Use /art to view your demon art.",
            parse_mode='Markdown'
        )
        return

    style_name = player.get('style', '')
    style      = find_breathing(style_name)
    level      = get_level(player['xp'])
    forms      = TECHNIQUES.get(style_name, [])
    unlocked   = get_unlocked_forms(style_name, level)
    unlocked_nums = {f['form'] for f in unlocked}

    emoji    = style['emoji']    if style else '💨'
    rarity   = style['rarity']   if style else ''
    desc     = style['description'] if style else ''
    rc       = rarity_color(rarity)

    lines = [
        f"{emoji} *{style_name.upper()}*",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"{rc} {rarity}",
        f"_{desc}_",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"📜 *FORMS*",
        "",
    ]

    for f in forms:
        locked  = f['form'] not in unlocked_nums
        lock_icon = "🔒" if locked else "✅"
        req     = f.get('unlock_rank', '')
        req_str = f"  _(Req: {req})_" if locked and req else ""
        hits    = f"  `×{f['hits']} hits`" if f.get('hits', 1) > 1 else ""
        poison  = "  ☠️ _Poison_" if f.get('poison') else ""
        lines.append(
            f"{lock_icon} *Form {f['form']} — {f['name']}*{req_str}\n"
            f"   💥 {f['dmg_min']}–{f['dmg_max']} DMG  |  🌀 {f['sta_cost']} STA{hits}{poison}"
        )

    lines += [
        "",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"🔓 Unlocked: *{len(unlocked)}/{len(forms)}* forms  _(Lv.{level})_",
        f"💡 Use forms in battle via the *💨 Technique* button",
    ]

    msg = update.message
    await _reply_style_card(msg, style_name, style, '\n'.join(lines))


# ── /art ──────────────────────────────────────────────────────────────────

async def art(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    if player['faction'] != 'demon':
        await update.message.reply_text(
            "❌ Only Demons have demon arts!\n"
            "Use /breathing to view your breathing style.",
            parse_mode='Markdown'
        )
        return

    art_name  = player.get('style', '')
    demon_art = find_demon_art(art_name)
    level     = get_level(player['xp'])
    forms     = TECHNIQUES.get(art_name, [])
    unlocked  = get_unlocked_forms(art_name, level)
    unlocked_nums = {f['form'] for f in unlocked}

    emoji = demon_art['emoji']       if demon_art else '👹'
    rarity= demon_art['rarity']      if demon_art else ''
    desc  = demon_art['description'] if demon_art else ''
    rc    = rarity_color(rarity)

    lines = [
        f"{emoji} *{art_name.upper()}*",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"{rc} {rarity}",
        f"_{desc}_",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"🎭 *ARTS*",
        "",
    ]

    for f in forms:
        locked   = f['form'] not in unlocked_nums
        lock_icon= "🔒" if locked else "✅"
        req      = f.get('unlock_rank', '')
        req_str  = f"  _(Req: {req})_" if locked and req else ""
        hits     = f"  `×{f['hits']} hits`" if f.get('hits', 1) > 1 else ""
        lines.append(
            f"{lock_icon} *Art {f['form']} — {f['name']}*{req_str}\n"
            f"   💥 {f['dmg_min']}–{f['dmg_max']} DMG  |  🌀 {f['sta_cost']} STA{hits}"
        )

    lines += [
        "",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"🔓 Unlocked: *{len(unlocked)}/{len(forms)}* arts  _(Lv.{level})_",
        f"💡 Use arts in battle via the *💨 Technique* button",
    ]

    msg = update.message
    await _reply_style_card(msg, art_name, demon_art, '\n'.join(lines))


# ── ADMIN: /givestyle @user [style name] ──────────────────────────────────

async def givestyle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.admin import has_admin_access, is_owner
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return
    if not is_owner(user_id):
        await update.message.reply_text(
            "🔒 *Owner Only*\n\n_Sudo admins cannot assign breathing styles._",
            parse_mode='Markdown'
        )
        return

    # Args: @username StyleName... or user_id StyleName...
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⚙️ *GIVE BREATHING STYLE*\n\n"
            "Usage: `/givestyle @username Water Breathing`\n"
            "Or:    `/givestyle 123456789 Sun Breathing`\n\n"
            "Available styles:\n" +
            '\n'.join(f"  {s['emoji']} {s['name']}" for s in BREATHING_STYLES),
            parse_mode='Markdown'
        )
        return

    target_arg = context.args[0].lstrip('@')
    style_name = ' '.join(context.args[1:])

    # Find style
    style = find_breathing(style_name)
    if not style:
        await update.message.reply_text(
            f"❌ Style *{style_name}* not found.\n\nAvailable:\n" +
            '\n'.join(f"  {s['emoji']} {s['name']}" for s in BREATHING_STYLES),
            parse_mode='Markdown'
        )
        return

    # Find target player
    from utils.database import col as _col
    try:
        tid = int(target_arg)
        target = _col("players").find_one({"user_id": tid})
    except ValueError:
        target = _col("players").find_one({"username": {"$regex": f"^{target_arg}$", "$options": "i"}})

    if not target:
        await update.message.reply_text(f"❌ Player *{target_arg}* not found.", parse_mode='Markdown')
        return

    if target['faction'] != 'slayer':
        await update.message.reply_text(
            f"❌ *{target['name']}* is a Demon — use `/giveart` instead.",
            parse_mode='Markdown'
        )
        return

    update_player(target['user_id'], style=style['name'], style_emoji=style['emoji'])

    await update.message.reply_text(
        f"✅ *Style Given!*\n\n"
        f"{style['emoji']} *{style['name']}* → *{target['name']}*\n"
        f"{style['rarity']}",
        parse_mode='Markdown'
    )

    # Notify the player
    try:
        await context.bot.send_message(
            chat_id=target['user_id'],
            text=(
                f"🎁 *YOU RECEIVED A NEW BREATHING STYLE!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{style['emoji']} *{style['name']}*\n"
                f"{style['rarity']}\n"
                f"_{style['description']}_\n\n"
                f"Use /breathing to view your forms!"
            ),
            parse_mode='Markdown'
        )
    except Exception:
        pass


# ── ADMIN: /giveart @user [art name] ─────────────────────────────────────

async def giveart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.admin import has_admin_access, is_owner
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return
    if not is_owner(user_id):
        await update.message.reply_text(
            "🔒 *Owner Only*\n\n_Sudo admins cannot assign demon arts._",
            parse_mode='Markdown'
        )
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "⚙️ *GIVE DEMON ART*\n\n"
            "Usage: `/giveart @username Blood Whip`\n"
            "Or:    `/giveart 123456789 Biokinesis`\n\n"
            "Available arts:\n" +
            '\n'.join(f"  {a['emoji']} {a['name']}" for a in DEMON_ARTS),
            parse_mode='Markdown'
        )
        return

    target_arg = context.args[0].lstrip('@')
    art_name   = ' '.join(context.args[1:])

    demon_art = find_demon_art(art_name)
    if not demon_art:
        await update.message.reply_text(
            f"❌ Art *{art_name}* not found.\n\nAvailable:\n" +
            '\n'.join(f"  {a['emoji']} {a['name']}" for a in DEMON_ARTS),
            parse_mode='Markdown'
        )
        return

    from utils.database import col as _col
    try:
        tid = int(target_arg)
        target = _col("players").find_one({"user_id": tid})
    except ValueError:
        target = _col("players").find_one({"username": {"$regex": f"^{target_arg}$", "$options": "i"}})

    if not target:
        await update.message.reply_text(f"❌ Player *{target_arg}* not found.", parse_mode='Markdown')
        return

    if target['faction'] != 'demon':
        await update.message.reply_text(
            f"❌ *{target['name']}* is a Slayer — use `/givestyle` instead.",
            parse_mode='Markdown'
        )
        return

    update_player(target['user_id'], style=demon_art['name'], style_emoji=demon_art['emoji'])

    await update.message.reply_text(
        f"✅ *Demon Art Given!*\n\n"
        f"{demon_art['emoji']} *{demon_art['name']}* → *{target['name']}*\n"
        f"{demon_art['rarity']}",
        parse_mode='Markdown'
    )

    try:
        await context.bot.send_message(
            chat_id=target['user_id'],
            text=(
                f"🎁 *YOU RECEIVED A NEW DEMON ART!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{demon_art['emoji']} *{demon_art['name']}*\n"
                f"{demon_art['rarity']}\n"
                f"_{demon_art['description']}_\n\n"
                f"Use /art to view your arts!"
            ),
            parse_mode='Markdown'
        )
    except Exception:
        pass
