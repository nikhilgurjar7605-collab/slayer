import logging
from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
from telegram.ext import ContextTypes
from utils.database import get_player, get_arts, col, update_player, is_admin
from utils.helpers import get_unlocked_forms, get_level, hp_bar
from config import OWNER_ID, BANNER_APPROVAL_CHAT_ID, GIF_BANNER_STAR_COST
log = logging.getLogger(__name__)


SWORD_BONUSES = {
    "Basic Nichirin Blade": 8,
    "Crimson Nichirin Blade": 25,
    "Jet Black Nichirin Blade": 50,
    "Scarlet Crimson Blade": 80,
    "Transparent Nichirin Blade": 120,
    "Sun Nichirin Blade": 200,
}

ARMOR_BONUSES = {
    "Corps Uniform": 5,
    "Reinforced Haori": 15,
    "Hashira Haori": 30,
    "Demon Slayer Uniform EX": 55,
    "Flame Haori": 85,
    "Yoriichi Haori": 150,
}


def _sword_buff(name: str) -> str:
    bonus = SWORD_BONUSES.get(name, 0)
    return f" _(ATK +{bonus})_" if bonus > 0 else ""


def _armor_buff(name: str) -> str:
    bonus = ARMOR_BONUSES.get(name, 0)
    return f" _(DMG -{bonus})_" if bonus > 0 else ""


def _profile_banner_media(player: dict):
    """Return (media, is_gif) tuple for the player's banner, or (None, False)."""
    gif_id = str(player.get("profile_banner_gif_id") or "").strip()
    if gif_id:
        return gif_id, True
    file_id = str(player.get("profile_banner_file_id") or "").strip()
    if file_id:
        return file_id, False
    url = str(player.get("profile_banner_url") or "").strip()
    if url.startswith("http"):
        return url, False
    return None, False


def _is_owner_or_admin(user_id: int) -> bool:
    """Return True if user is owner or a registered admin."""
    if user_id == OWNER_ID:
        return True
    return is_admin(user_id)


# ── Banner request helpers ─────────────────────────────────────────────────

def _save_banner_request(user_id: int, file_id: str | None, url: str | None, gif_file_id: str | None = None):
    """Store a pending banner request in MongoDB."""
    banner_type = "gif" if gif_file_id else "image"
    col("banner_requests").update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "file_id": file_id,
            "url": url,
            "gif_file_id": gif_file_id,
            "banner_type": banner_type,
            "status": "pending",
        }},
        upsert=True,
    )


def _get_banner_request(user_id: int) -> dict | None:
    return col("banner_requests").find_one({"user_id": user_id})


def _delete_banner_request(user_id: int):
    col("banner_requests").delete_one({"user_id": user_id})


def _pending_requests() -> list:
    return list(col("banner_requests").find({"status": "pending"}))


# ── Shared helpers ─────────────────────────────────────────────────────────

async def _safe_edit(query, text, **kwargs):
    """Edit a message safely, falling back to reply on failure."""
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        try:
            await query.message.reply_text(text, **kwargs)
        except Exception as e:
            log.error("[EXCEPTION] %s", e)


# ── /profile ──────────────────────────────────────────────────────────────

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    log.info("[PROFILE] user_id=%s", user_id)
    player  = get_player(user_id)
    if not player:
        msg = update.message or update.callback_query.message
        await msg.reply_text("❌ No character found. Use /start to create one.")
        return

    level    = get_level(player['xp'])
    location = player.get('location', 'asakusa').title()
    game_name = player.get('name', '—')
    tg_username = player.get('username') or update.effective_user.username or ''
    uname_display = f"{game_name}" + (f" (@{tg_username})" if tg_username else "")

    p_bar    = hp_bar(player['hp'], player['max_hp'])
    s_bar    = hp_bar(player['sta'], player['max_sta'])

    if player.get('faction') == 'slayer':
        mark_label = "🔥 𝙎𝙡𝙖𝙮𝙚𝙧 𝙈𝙖𝙧𝙠"
        mark = "Active" if player.get('slayer_mark') else "Locked"
    else:
        mark_label = "🌑 𝘿𝙚𝙢𝙤𝙣 𝙈𝙖𝙧𝙠"
        mark = "Active" if player.get('demon_mark') else "Locked"

    clan_line = "╰➤🏯 𝘾𝙡𝙖𝙣 : None\n"
    if player.get('clan_id'):
        clan = col("clans").find_one({"id": player['clan_id']})
        if clan:
            role = player.get('clan_role', 'recruit').title()
            clan_line = f"╰➤🏯 𝘾𝙡𝙖𝙣 : {clan['name']} [{role}]\n"

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"{player['style_emoji']} Techniques", callback_data='profile_techniques'),
            InlineKeyboardButton("📊 Stats", callback_data='profile_more_info'),
        ]
    ])

    stars = player.get("stars", 0)
    stars_str = f"┣ ✮ 𝙎𝙩𝙖𝙧𝙨 : {stars} ⭐\n" if stars > 0 else ""

    text = (
        f"┏━━━━━━━━━━━━━━━━\n"
        f"┣ ✮ 𝙉𝙖𝙢𝙚 : {uname_display}\n"
        f"┣ ✮ 𝙄𝘿 : {user_id}\n"
        f"┣ ✮ 𝙇𝙚𝙫𝙚𝙡 : {level}\n"
        f"┣ ✮ 𝙀𝙭𝙥 : {player['xp']:,}\n"
        f"┣ ✮ 𝙍𝙖𝙣𝙠 : {player['rank']} {player['rank_kanji']}\n"
        f"┣ ✮ 𝙎𝙩𝙮𝙡𝙚 : {player['style_emoji']} {player['style']}\n"
        f"{stars_str}"
        #f"┣ ✮ 𝘽𝙖𝙡𝙖𝙣𝙘𝙚 : {player['yen']:,}¥\n"
        f"┗━━━━━━━━━━━━━━━━\n"
        f"╰➤🧭 𝘾𝙪𝙧𝙧𝙚𝙣𝙩 𝙇𝙤𝙘𝙖𝙩𝙞𝙤𝙣 : 「{location}」\n"
        f"╰➤📖 𝙊𝙧𝙞𝙜𝙞𝙣 : {player.get('story', '—')}\n"
        f"{clan_line}"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        #f"❤️ 𝗛𝗣 : {player['hp']}/{player['max_hp']}\n"
        #f"{p_bar}\n"
        #f"🌀 𝗦𝗧𝗔 : {player['sta']}/{player['max_sta']}\n"
       # f"{s_bar}\n"
       # f"▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁▁\n"
        f"╰➤☠️ 𝙎𝙡𝙖𝙞𝙣 : {player['demons_slain']}  |  💀 𝘿𝙚𝙖𝙩𝙝𝙨 : {player['deaths']}\n"
        f"╰➤📜 𝙈𝙞𝙨𝙨𝙞𝙤𝙣𝙨 : {player['missions_done']}\n"
        #f"╰➤💠 𝙎𝙠𝙞𝙡𝙡 𝙋𝙩𝙨 : {player.get('skill_points', 0)} SP\n"
        f"╰➤🍖 𝘿𝙚𝙫𝙤𝙪𝙧 : {player.get('devour_stacks', 0)}/20\n"
        f"╰➤{mark_label} : {mark}\n"
        f"▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔"
    )

    banner_media, banner_is_gif = _profile_banner_media(player)
    if banner_media:
        if update.callback_query:
            try:
                # Edit the existing message's caption instead of sending a new one
                await update.callback_query.edit_message_caption(caption=text[:1024], parse_mode='HTML', reply_markup=keyboard)
                return
            except Exception as e:
                log.error("[PROFILE] failed to edit caption: %s", e)
                # Fallback to sending a new message if editing fails

        target_msg = update.callback_query.message if update.callback_query else update.message
        try:
            if banner_is_gif:
                await target_msg.reply_animation(banner_media, caption=text[:1024], parse_mode='HTML', reply_markup=keyboard)
            else:
                await target_msg.reply_photo(banner_media, caption=text[:1024], parse_mode='HTML', reply_markup=keyboard)
            return
        except Exception as e:
            log.error("[PROFILE] Failed to send banner media: %s. Falling back to plain text.", e)
            col("players").update_one(
                {"user_id": user_id},
                {"$unset": {"profile_banner_url": "", "profile_banner_file_id": "", "profile_banner_gif_id": ""}}
            )
            text += "\n\n⚠️ <i>Your custom banner URL was invalid/unreachable and has been removed. Please set a valid direct image URL.</i>"

    # Plain text fallback
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode='HTML', reply_markup=keyboard)
    else:
        await update.message.reply_text(text, parse_mode='HTML', reply_markup=keyboard)


async def profile_techniques(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    if not player:
        await query.answer("No character found!", show_alert=True)
        return
    level   = get_level(player['xp'])

    from config import TECHNIQUES
    all_forms     = TECHNIQUES.get(player['style'], [])
    unlocked_nums = {f['form'] for f in get_unlocked_forms(player['style'], level)}

    lines = [f"{player['style_emoji']} *{player['style'].upper()}*\n"]
    for form in all_forms:
        if form['form'] in unlocked_nums:
            lines.append(f"✅ *Form {form['form']}* — {form['name']}")
            lines.append(f"   💥 DMG: {form['dmg_min']}-{form['dmg_max']}  |  🌀 STA: {form['sta_cost']}")
        else:
            req = f"Lv.{1 + (form['form']-1)*3}"
            lines.append(f"🔒 *Form {form['form']}* — {form['name']}  _({req} required)_")

    arts = get_arts(user_id)
    if arts:
        lines.append("\n━━ 🎴 EXTRA ARTS ━━━━━━━")
        for art in arts:
            lines.append(f"  {art['art_emoji']} *{art['art_name']}*  _({art['source']})_")

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='goto_profile')]])
    try:
        await query.edit_message_caption(caption='\n'.join(lines), parse_mode='Markdown', reply_markup=keyboard)
    except Exception:
        await _safe_edit(query, '\n'.join(lines), parse_mode='Markdown', reply_markup=keyboard)


async def profile_more_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)
    if not player:
        await query.answer("No character found!", show_alert=True)
        return

    p_bar = hp_bar(player['hp'],  player['max_hp'])
    s_bar = hp_bar(player['sta'], player['max_sta'])

    tier = player.get('potential_tier', 0)
    tier_label = ""
    if tier > 0:
        titles = {
            1: "🌟 Tier I",
            2: "✨ Tier II",
            3: "💎 Tier III",
            4: "🌌 Tier IV",
            5: "👑 Tier V",
        }
        tier_label = f"  ({titles.get(tier, f'🔥 Tier {tier}')})"

    text = (
        f"📊 *DETAILED STATS — {player['name'].upper()}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"❤️  HP:        *{player['hp']}/{player['max_hp']}*  {p_bar}\n"
        f"🌀  STA:       *{player['sta']}/{player['max_sta']}*  {s_bar}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💪  STR:       *{player['str_stat']}*\n"
        f"⚡  SPD:       *{player['spd']}*\n"
        f"🛡️  DEF:       *{player['def_stat']}*\n"
        f"🔮  Potential: *{player.get('potential', 0)}%*{tier_label}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️  Sword:     _{player.get('equipped_sword','None')}_"
        + (_sword_buff(player.get('equipped_sword',''))) + "\n"
        + f"👘  Armor:     _{player.get('equipped_armor','None')}_"
        + (_armor_buff(player.get('equipped_armor',''))) + "\n"
        f"💠  Skill Pts: *{player.get('skill_points', 0)} SP*\n"
        f"🍖  Devour:    *{player.get('devour_stacks', 0)}/20*\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )

    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='goto_profile')]])
    try:
        await query.edit_message_caption(caption=text, parse_mode='Markdown', reply_markup=keyboard)
    except Exception:
        await _safe_edit(query, text, parse_mode='Markdown', reply_markup=keyboard)


# ── /setbanner — requires admin/owner approval ────────────────────────────

async def setbanner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    log.info("[SETBANNER] user_id=%s", user_id)
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found. Use /start first.")
        return

    msg = update.message
    has_photo     = bool(msg.photo)
    has_animation = bool(msg.animation)  # GIF / animated sticker sent as file
    has_url_arg   = bool(context.args and context.args[-1].strip().startswith("http"))

    # ── Admins & owner: apply instantly without approval ─────────────────
    if _is_owner_or_admin(user_id):
        if not has_photo and not has_animation and not has_url_arg:
            await msg.reply_text(
                "SET PROFILE BANNER (Admin/Owner - instant)\n\n"
                "Send a photo/GIF with /setbanner\n"
                "or /setbanner https://example.com/image.jpg",
                parse_mode=None
            )
            return

        update_fields = {"profile_banner_file_id": None,
                         "profile_banner_url": None,
                         "profile_banner_gif_id": None}
        if has_animation:
            update_fields["profile_banner_gif_id"] = msg.animation.file_id
        elif has_photo:
            update_fields["profile_banner_file_id"] = msg.photo[-1].file_id
        elif has_url_arg:
            update_fields["profile_banner_url"] = context.args[-1].strip()
        else:
            await msg.reply_text("Send a photo, GIF, or a direct http image URL.")
            return

        update_player(user_id, **update_fields)
        log.info("[SETBANNER] Admin/owner banner set instantly: user_id=%s", user_id)
        await msg.reply_text(
            "Banner set instantly (admin privilege).\nUse /profile to preview.",
            parse_mode=None
        )
        return

    # ── GIF path: send Telegram Stars invoice ────────────────────────────
    if has_animation:
        existing = _get_banner_request(user_id)
        if existing and existing.get("status") == "pending":
            await msg.reply_text(
                "You already have a pending banner request.\n"
                "Wait for it to be reviewed before submitting another.",
                parse_mode=None
            )
            return
        # Store gif file_id temporarily so we can retrieve it after payment
        context.user_data["pending_gif_file_id"] = msg.animation.file_id
        try:
            await context.bot.send_invoice(
                chat_id=user_id,
                title="Animated GIF Profile Banner",
                description=(
                    f"Set an animated GIF as your profile banner.\n"
                    f"Cost: {GIF_BANNER_STAR_COST} ⭐ Stars\n\n"
                    "After payment your GIF will be sent for admin approval."
                ),
                payload=f"gif_banner_{user_id}_{msg.animation.file_id}",
                provider_token="",  # Empty string required for Telegram Stars (XTR)
                currency="XTR",
                prices=[LabeledPrice("Animated Banner", GIF_BANNER_STAR_COST)],
            )
        except Exception as e:
            log.error("[SETBANNER] Failed to send Stars invoice: %s", e)
            await msg.reply_text("Failed to start payment. Please try again.")
        return

    # ── Regular image/URL path: submit for approval ───────────────────────
    if not has_photo and not has_url_arg:
        existing = _get_banner_request(user_id)
        if existing and existing.get("status") == "pending":
            await msg.reply_text(
                "Your banner request is already pending approval.\n\n"
                "An admin will review it soon. Please wait.",
                parse_mode=None
            )
            return

        await msg.reply_text(
            "SET PROFILE BANNER\n\n"
            "• Send a photo with /setbanner\n"
            "• /setbanner https://example.com/image.jpg\n"
            f"• Send a GIF with /setbanner (costs {GIF_BANNER_STAR_COST} ⭐ Stars)\n\n"
            "Photos require admin approval before appearing on your profile.",
            parse_mode=None
        )
        return

    url = context.args[-1].strip() if has_url_arg else None
    file_id = msg.photo[-1].file_id if has_photo else None

    if not file_id and not url:
        await msg.reply_text("Send a photo or a direct http image URL.")
        return

    _save_banner_request(user_id, file_id=file_id, url=url)
    log.info("[SETBANNER] Banner request submitted for approval: user_id=%s", user_id)

    await _notify_approval_chat(context, user_id, player, file_id=file_id, url=url, gif_file_id=None)

    await msg.reply_text(
        "Banner request submitted.\n\n"
        "An admin will review your banner shortly.\n"
        "You will be notified when it is approved or denied.",
        parse_mode=None
    )


# ── Stars payment handlers for GIF banners ────────────────────────────────

async def banner_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Auto-approve the pre-checkout for GIF banner invoices."""
    query = update.pre_checkout_query
    if query.invoice_payload.startswith("gif_banner_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Unknown payment.")


async def banner_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """After Stars payment succeeds, save the GIF request and notify admins."""
    payment = update.message.successful_payment
    payload = payment.invoice_payload  # "gif_banner_<uid>_<file_id>"
    if not payload.startswith("gif_banner_"):
        return

    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found. Use /start first.")
        return

    # Extract gif file_id from payload (format: gif_banner_<uid>_<file_id>)
    parts    = payload.split("_", 3)  # ["gif", "banner", uid, file_id]
    gif_file_id = parts[3] if len(parts) == 4 else context.user_data.get("pending_gif_file_id")

    if not gif_file_id:
        await update.message.reply_text("Payment received but GIF file lost. Contact an admin.")
        log.error("[SETBANNER] Payment ok but gif_file_id missing for user %s", user_id)
        return

    _save_banner_request(user_id, file_id=None, url=None, gif_file_id=gif_file_id)
    context.user_data.pop("pending_gif_file_id", None)
    log.info("[SETBANNER] GIF banner payment ok, request saved: user_id=%s", user_id)

    # Credit Stars to the Owner's account in database
    col("players").update_one(
        {"user_id": OWNER_ID},
        {"$inc": {"stars": GIF_BANNER_STAR_COST}}
    )
    log.info("[SETBANNER] Credited %s stars to owner %s", GIF_BANNER_STAR_COST, OWNER_ID)

    await _notify_approval_chat(context, user_id, player, file_id=None, url=None, gif_file_id=gif_file_id)

    await update.message.reply_text(
        f"Payment received ({GIF_BANNER_STAR_COST} ⭐ Stars).\n\n"
        "Your animated GIF banner has been submitted for admin approval.\n"
        "You will be notified once it is reviewed.",
        parse_mode=None
    )


# ── Shared helper: send approval message to admin chat ────────────────────

async def _notify_approval_chat(
    context, user_id: int, player: dict,
    file_id: str | None, url: str | None, gif_file_id: str | None
):
    approval_chat_id = BANNER_APPROVAL_CHAT_ID or OWNER_ID
    player_name = player.get("name", str(user_id))
    tg_username = player.get("username") or ""
    user_display = player_name + (f" (@{tg_username})" if tg_username else f" [ID: {user_id}]")
    banner_type_label = "Animated GIF" if gif_file_id else "Photo/Image"

    approve_btn = InlineKeyboardButton("✅ Approve", callback_data=f"banner_approve_{user_id}")
    deny_btn    = InlineKeyboardButton("❌ Deny",    callback_data=f"banner_deny_{user_id}")
    keyboard    = InlineKeyboardMarkup([[approve_btn, deny_btn]])

    caption = (
        f"Banner Approval Request\n\n"
        f"Player: {user_display}\n"
        f"ID: {user_id}\n"
        f"Type: {banner_type_label}\n\n"
        f"Approve or deny using the buttons below.\n"
        f"Or use: /approvebanner {user_id}"
    )

    try:
        if gif_file_id:
            await context.bot.send_animation(
                chat_id=approval_chat_id,
                animation=gif_file_id,
                caption=caption,
                parse_mode=None,
                reply_markup=keyboard,
            )
        elif file_id:
            await context.bot.send_photo(
                chat_id=approval_chat_id,
                photo=file_id,
                caption=caption,
                parse_mode=None,
                reply_markup=keyboard,
            )
        elif url:
            await context.bot.send_photo(
                chat_id=approval_chat_id,
                photo=url,
                caption=caption,
                parse_mode=None,
                reply_markup=keyboard,
            )
    except Exception as e:
        log.error("[SETBANNER] Failed to notify approval chat: %s", e)


# ── /approvebanner <user_id> — approve via command ────────────────────────

async def approvebanner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin/owner command: /approvebanner <user_id> — approve a pending banner."""
    admin_id = update.effective_user.id
    if not _is_owner_or_admin(admin_id):
        await update.message.reply_text("Admin only.")
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text(
            "Usage: /approvebanner <user_id>\n\n"
            "Use /bannerpending to see pending requests.",
            parse_mode=None
        )
        return

    target_uid = int(context.args[0])
    request    = _get_banner_request(target_uid)

    if not request or request.get("status") != "pending":
        await update.message.reply_text(f"No pending banner request found for ID: {target_uid}.")
        return

    player = get_player(target_uid)
    player_name = player.get("name", str(target_uid)) if player else str(target_uid)

    update_fields = {"profile_banner_file_id": None,
                     "profile_banner_url": None,
                     "profile_banner_gif_id": None}
    if request.get("gif_file_id"):
        update_fields["profile_banner_gif_id"] = request["gif_file_id"]
    elif request.get("file_id"):
        update_fields["profile_banner_file_id"] = request["file_id"]
    elif request.get("url"):
        update_fields["profile_banner_url"] = request["url"]
    else:
        await update.message.reply_text("Request has no banner data. Deleting it.")
        _delete_banner_request(target_uid)
        return

    update_player(target_uid, **update_fields)
    _delete_banner_request(target_uid)
    log.info("[SETBANNER] Approved via command by admin=%s for user=%s", admin_id, target_uid)

    await update.message.reply_text(
        f"Banner approved for {player_name} (ID: {target_uid}).",
        parse_mode=None
    )

    # Notify the player
    try:
        await context.bot.send_message(
            chat_id=target_uid,
            text=(
                "Your profile banner has been approved.\n\n"
                "Use /profile to see it live."
            ),
            parse_mode=None,
        )
    except Exception as e:
        log.error("[SETBANNER] Could not notify player %s of approval: %s", target_uid, e)


async def banner_decision_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles Approve / Deny button presses from admin/owner."""
    query   = update.callback_query
    reviewer_id = query.from_user.id

    if not _is_owner_or_admin(reviewer_id):
        await query.answer("You are not authorized to approve banners.", show_alert=True)
        return

    await query.answer()
    data = query.data  # "banner_approve_<uid>" or "banner_deny_<uid>"
    parts = data.split("_")
    action  = parts[1]          # "approve" or "deny"
    user_id = int(parts[2])

    request = _get_banner_request(user_id)
    if not request or request.get("status") != "pending":
        await query.edit_message_caption(
            caption="This request has already been handled or expired.",
            reply_markup=None,
        )
        return

    player = get_player(user_id)
    player_name = player.get("name", str(user_id)) if player else str(user_id)
    player_username = player.get("username") or "" if player else ""
    player_display = f"{player_name}" + (f" (@{player_username})" if player_username else f" [ID: {user_id}]")

    if action == "approve":
        # Apply the banner — check gif first
        update_fields = {"profile_banner_file_id": None,
                         "profile_banner_url": None,
                         "profile_banner_gif_id": None}
        if request.get("gif_file_id"):
            update_fields["profile_banner_gif_id"] = request["gif_file_id"]
        elif request.get("file_id"):
            update_fields["profile_banner_file_id"] = request["file_id"]
        elif request.get("url"):
            update_fields["profile_banner_url"] = request["url"]

        update_player(user_id, **update_fields)
        _delete_banner_request(user_id)
        log.info("[SETBANNER] Approved by reviewer=%s for user=%s", reviewer_id, user_id)

        # Update reviewer's message
        await query.edit_message_caption(
            caption=f"Banner approved for {player_name} (ID: {user_id})\nReviewed by: {reviewer_id}",
            parse_mode=None,
            reply_markup=None,
        )

        # Log approval to owner DM (include reviewer + requester)
        try:
            reviewer_name = query.from_user.full_name
            reviewer_username = query.from_user.username or ""
            reviewer_display = f"{reviewer_name}" + (f" (@{reviewer_username})" if reviewer_username else f" [ID: {reviewer_id}]")
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    "Banner Approved\n\n"
                    f"Reviewer: {reviewer_display} (ID: {reviewer_id})\n"
                    f"Requester: {player_display} (ID: {user_id})"
                ),
                parse_mode=None
            )
        except Exception as e:
            log.error("[SETBANNER] Failed to log approval to owner: %s", e)

        # Notify the player
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "Your profile banner has been approved.\n\n"
                    "Use /profile to see it live."
                ),
                parse_mode=None,
            )
        except Exception as e:
            log.error("[SETBANNER] Could not notify player %s of approval: %s", user_id, e)

    else:  # deny
        _delete_banner_request(user_id)
        log.info("[SETBANNER] Denied by reviewer=%s for user=%s", reviewer_id, user_id)

        await query.edit_message_caption(
            caption=f"Banner denied for {player_name} (ID: {user_id})\nReviewed by: {reviewer_id}",
            parse_mode=None,
            reply_markup=None,
        )

        # Log denial to owner DM (include reviewer + requester)
        try:
            reviewer_name = query.from_user.full_name
            reviewer_username = query.from_user.username or ""
            reviewer_display = f"{reviewer_name}" + (f" (@{reviewer_username})" if reviewer_username else f" [ID: {reviewer_id}]")
            await context.bot.send_message(
                chat_id=OWNER_ID,
                text=(
                    "Banner Denied\n\n"
                    f"Reviewer: {reviewer_display} (ID: {reviewer_id})\n"
                    f"Requester: {player_display} (ID: {user_id})"
                ),
                parse_mode=None
            )
        except Exception as e:
            log.error("[SETBANNER] Failed to log denial to owner: %s", e)

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "Your profile banner request was denied.\n\n"
                    "Please submit a different image that follows the community guidelines."
                ),
                parse_mode=None,
            )
        except Exception as e:
            log.error("[SETBANNER] Could not notify player %s of denial: %s", user_id, e)


# ── /bannerpending — list all pending requests (admin/owner only) ──────────

async def bannerpending(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner_or_admin(user_id):
        await update.message.reply_text("Admin only.")
        return

    requests = _pending_requests()
    if not requests:
        await update.message.reply_text("No pending banner requests.")
        return

    lines = [f"Pending Banner Requests ({len(requests)})\n"]
    for r in requests:
        uid = r["user_id"]
        p   = get_player(uid)
        name = p.get("name", "?") if p else "?"
        if r.get("file_id"):
            src = "Photo"
        else:
            url = r.get("url", "")
            src = f"[Open]({url})" if url else "URL"
        lines.append(f"- {name} (ID: `{uid}`) - {src}")

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
    return

    user_id = update.effective_user.id
    if not _is_owner_or_admin(user_id):
        await update.message.reply_text("Admin only.")
        return

    requests = _pending_requests()
    if not requests:
        await update.message.reply_text("No pending banner requests.")
        return

    lines = [f"Pending Banner Requests ({len(requests)})\n"]
    for r in requests:
        uid = r["user_id"]
        p   = get_player(uid)
        name = p.get("name", "?") if p else "?"
        src  = "Photo" if r.get("file_id") else "URL"
        lines.append(f"- {name} (ID: `{uid}`) - {src}")

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


# ── /clearbanner ───────────────────────────────────────────────────────────

async def bannershow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only: show a user's current profile banner by reply or ID."""
    user_id = update.effective_user.id
    if not _is_owner_or_admin(user_id):
        await update.message.reply_text("Admin only.")
        return

    target_id = None
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    elif context.args and context.args[0].isdigit():
        target_id = int(context.args[0])

    if not target_id:
        await update.message.reply_text("Usage: /bannershow <id> or reply to a user.")
        return

    player = get_player(target_id)
    if not player:
        await update.message.reply_text("No character found for that ID.")
        return

    banner_media, banner_is_gif = _profile_banner_media(player)
    if not banner_media:
        await update.message.reply_text("That user has no banner set.")
        return

    name = player.get("name", str(target_id))
    try:
        if banner_is_gif:
            await update.message.reply_animation(
                banner_media,
                caption=f"Banner for {name} (ID: {target_id})",
                parse_mode=None
            )
        else:
            await update.message.reply_photo(
                banner_media,
                caption=f"Banner for {name} (ID: {target_id})",
                parse_mode=None
            )
    except Exception:
        await update.message.reply_text("Failed to display banner media.")


async def clearbanner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    target_id = None
    if update.message.reply_to_message:
        target_id = update.message.reply_to_message.from_user.id
    elif context.args and context.args[0].isdigit():
        target_id = int(context.args[0])

    if target_id and not _is_owner_or_admin(user_id):
        await update.message.reply_text("Admin only.")
        return

    if target_id is None:
        target_id = user_id

    player = get_player(target_id)
    if not player:
        await update.message.reply_text("No character found. Use /start first.")
        return

    update_player(target_id, profile_banner_file_id=None, profile_banner_url=None, profile_banner_gif_id=None)
    _delete_banner_request(target_id)

    if target_id == user_id:
        await update.message.reply_text("Profile banner cleared.")
    else:
        await update.message.reply_text(f"Profile banner cleared for ID: {target_id}.")
