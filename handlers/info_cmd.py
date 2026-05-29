"""
/info [name]        — Details on any breathing style or demon art
/mytechnique        — Your own breathing style details (Slayers)
/myart              — Your own demon art details (Demons)
/setstyleimage      — Admin: set banner image/GIF for a style/art
/infoall            — Owner: full breakdown of ALL styles/arts
/is [id]            — View a specific suggestion in full detail
"""
import logging
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, col, is_admin
from config import BREATHING_STYLES, DEMON_ARTS, TECHNIQUES, OWNER_ID

log = logging.getLogger(__name__)

# ── Helpers ────────────────────────────────────────────────────────────────

def _get_level(xp: int) -> int:
    """Simple XP→Level formula (mirrors utils/helpers.py)."""
    level = 1
    xp_needed = 100
    while xp >= xp_needed:
        xp -= xp_needed
        level += 1
        xp_needed = int(xp_needed * 1.15)
    return level


def _get_unlocked_forms(style_name: str, level: int, player_rank: str = None) -> set:
    """Return set of form numbers the player has unlocked."""
    forms   = TECHNIQUES.get(style_name, [])
    rank_order = [
        "Mizunoto", "Mizunoe", "Kanoto", "Kanoe", "Tsuchinoto", "Tsuchinoe",
        "Hinoto", "Hinoe", "Kinoto", "Kinoe", "Hashira",
        "Lower Moon 6", "Lower Moon 5", "Lower Moon 4", "Lower Moon 3",
        "Lower Moon 2", "Lower Moon 1",
        "Upper Moon 6", "Upper Moon 5", "Upper Moon 4", "Upper Moon 3",
        "Upper Moon 2", "Upper Moon 1",
    ]
    rank_idx = rank_order.index(player_rank) if player_rank in rank_order else 0

    unlocked = set()
    for f in forms:
        req_rank = f.get("unlock_rank")
        req_lv   = 1 + (f["form"] - 1) * 3   # Form N unlocks at level 1+(N-1)*3
        if level >= req_lv:
            if req_rank:
                req_idx = rank_order.index(req_rank) if req_rank in rank_order else 999
                if rank_idx >= req_idx:
                    unlocked.add(f["form"])
            else:
                unlocked.add(f["form"])
    return unlocked


def _is_owner_or_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    return is_admin(user_id)


def get_style_image(style_name: str) -> str | None:
    """Look up a custom banner from MongoDB first, then fall back to config."""
    doc = col("style_images").find_one({"style_name": style_name})
    if doc:
        if doc.get("file_id"):
            return doc["file_id"]
        if doc.get("url"):
            return doc["url"]
        if doc.get("image"):
            return doc["image"]
    all_pool = BREATHING_STYLES + DEMON_ARTS
    meta = next((s for s in all_pool if s["name"] == style_name), {})
    return meta.get("image_url") or meta.get("image") or None


def _find_style(query: str):
    """Find a style/art by exact or partial name, case-insensitive."""
    all_pool = BREATHING_STYLES + DEMON_ARTS
    q = query.lower().strip()
    return (
        next((s for s in all_pool if s["name"].lower() == q), None)
        or next((s for s in all_pool if q in s["name"].lower()), None)
    )

# ── Format helper ──────────────────────────────────────────────────────────

_EFFECT_LABELS = {
    "freeze_apply":   "❄️ Freeze (2t)",
    "burn_apply":     "🔥 Burn (5t)",
    "bleed_apply":    "🩸 Bleed (3t)",
    "poison_apply":   "☠️ Poison (5t)",
    "deep_poison":    "☠️ Deep Poison",
    "confuse_apply":  "😵 Confusion (2t)",
    "exhaust_apply":  "😮‍💨 Exhaust",
    "stagger_apply":  "🥴 Stagger",
    "stun_apply":     "⚡ Stun",
    "regen_apply":    "💚 Regen",
    "atk_buff":       "⬆️ ATK+",
    "def_buff":       "🛡️ DEF+",
    "burn_execute":   "🔥 Execute if burning",
    "bleed_payoff":   "🩸 Bleed payoff",
    "bleed_sustain":  "🩸 Blood Shield",
    "bleed_extend":   "🩸 Extend Bleed",
    "flow_start":     "💧 Flow State",
    "flow_finisher":  "💧 Flow Finisher",
    "ice_shatter":    "🧊 Shatter: DEF-15",
    "stagger_chance": "🥴 Stagger Chance",
    "freeze_chance":  "❄️ Freeze Chance",
    "exhaust_chance": "😮‍💨 Exhaust Chance",
    "confuse_chance": "😵 Confuse Chance",
    "stun_chance":    "⚡ Stun Chance",
    "curse_apply":    "💀 Curse",
}


def _format_forms(style_meta: dict, player: dict = None) -> str:
    name   = style_meta["name"]
    forms  = TECHNIQUES.get(name, [])

    is_breathing = any(s["name"] == name for s in BREATHING_STYLES)

    # Unlock status for this player
    if player:
        owns = player.get("style") == name or player.get("hybrid_style") == name
        if owns:
            level    = _get_level(player.get("xp", 0))
            unlocked = _get_unlocked_forms(name, level, player.get("rank"))
        else:
            owns     = False
            unlocked = set()
    else:
        owns     = False
        unlocked = set()

    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"⚔️ *FORMS & TECHNIQUES* ({len(forms)} forms)",
        f"",
    ]

    if not forms:
        lines.append("_No technique forms defined yet._")
    else:
        for f in forms:
            form_num = f["form"]
            if owns:
                locked  = form_num not in unlocked
                icon    = "🔒" if locked else "✅"
                req_txt = f"  _(Lv.{1+(form_num-1)*3})_" if locked else ""
            else:
                icon    = "📋"
                req_txt = f"  _(Unlocks Lv.{1+(form_num-1)*3})_"

            lines.append(f"{icon} Form {form_num} — *{f['name']}*{req_txt}")
            lines.append(f"   💥 DMG: *{f['dmg_min']}–{f['dmg_max']}*  |  🌀 STA: *{f['sta_cost']}*")

            extras = []
            if f.get("hits", 1) > 1:
                extras.append(f"🔁 ×{f['hits']} hits")
            if f.get("effect"):
                extras.append(_EFFECT_LABELS.get(f["effect"], f"✨ {f['effect'].replace('_',' ').title()}"))
            if f.get("poison"):
                extras.append("☠️ Poison")
            if f.get("unlock_rank"):
                extras.append(f"🔐 Req: {f['unlock_rank']}")
            if f.get("desc"):
                extras.append(f"📝 {f['desc']}")

            if extras:
                lines.append("   " + " | ".join(extras[:3]))
                if len(extras) > 3:
                    lines.append("   " + " | ".join(extras[3:]))
            lines.append("")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━",
        "✅ *You own this style!* Use it in battle." if owns else
        f"💡 Obtain via {'`/breathing`' if is_breathing else '`/art`'} gacha",
    ]
    return "\n".join(lines)


def _format_style_info(style_meta: dict, player: dict = None) -> str:
    caption = _format_caption(style_meta)
    forms_txt = _format_forms(style_meta, player)
    return caption + "\n\n" + forms_txt



# ── /info ──────────────────────────────────────────────────────────────────

async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/info [name] — View details of any breathing style or demon art."""
    user_id = update.effective_user.id
    player  = get_player(user_id)

    if not context.args:
        faction  = player.get("faction") if player else None
        own_hint = (
            "• `/mytechnique` — Your Breathing Style (Slayers)\n"
            if faction == "slayer" else
            "• `/myart` — Your Demon Art (Demons)\n"
            if faction == "demon" else
            "• `/mytechnique` — Breathing Style\n• `/myart` — Demon Art\n"
        )
        await update.message.reply_text(
            "🏮 *Style & Art Info*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"{own_hint}\n"
            "🔍 *Search any style:*\n"
            "• `/info Water Breathing`\n"
            "• `/info Ice Manipulation`\n"
            "• `/info Blood Whip`",
            parse_mode="Markdown",
        )
        return

    query      = " ".join(context.args).strip()
    style_meta = _find_style(query)
    if not style_meta:
        names = "\n".join(
            f"  {'🗡️' if s in BREATHING_STYLES else '👹'} {s['name']}"
            for s in BREATHING_STYLES + DEMON_ARTS
        )
        await update.message.reply_text(
            f"❌ *Not found:* `{query}`\n\n*Available styles:*\n{names}",
            parse_mode="Markdown",
        )
        return

    await _send_style(update, style_meta, player)


def _format_caption(style_meta: dict) -> str:
    """Short caption for the image — name, rarity, gacha, description only."""
    name   = style_meta["name"]
    emoji  = style_meta.get("emoji", "⚔️")
    rarity = style_meta.get("rarity", "⭐⭐ COMMON")
    desc   = style_meta.get("description", "")
    is_breathing = any(s["name"] == name for s in BREATHING_STYLES)
    pool   = BREATHING_STYLES if is_breathing else DEMON_ARTS
    weight = style_meta.get("gacha_weight", 0)
    total  = sum(s.get("gacha_weight", 0) for s in pool)
    chance = f"{round(weight/total*100, 2)}%" if total and weight else "UNIQUE"
    fe     = "🗡️" if is_breathing else "👹"
    label  = "BREATHING STYLE" if is_breathing else "DEMON ART"
    return (
        f"┌─── {fe} {label} ───┐\n"
        f"{emoji} *{name}*\n"
        f"🏅 {rarity}\n"
        f"🎲 Gacha: {chance}  (weight {weight})\n"
        f"📖 _{desc}_"
    )


def _format_forms_compact(style_meta: dict, player: dict = None) -> str:
    name   = style_meta["name"]
    forms  = TECHNIQUES.get(name, [])

    if player:
        owns = player.get("style") == name or player.get("hybrid_style") == name
        if owns:
            level    = _get_level(player.get("xp", 0))
            unlocked = _get_unlocked_forms(name, level, player.get("rank"))
        else:
            owns     = False
            unlocked = set()
    else:
        owns     = False
        unlocked = set()

    lines = [
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"⚔️ *FORMS & TECHNIQUES* ({len(forms)} forms)",
    ]
    for f in forms:
        form_num = f["form"]
        if owns:
            locked  = form_num not in unlocked
            icon    = "🔒" if locked else "✅"
            req_txt = f" _(Lv.{1+(form_num-1)*3})_" if locked else ""
        else:
            icon    = "📋"
            req_txt = f" _(Lv.{1+(form_num-1)*3})_"

        effect = ""
        if f.get("effect"):
            lbl = _EFFECT_LABELS.get(f["effect"], "").strip()
            # simplify icons
            lbl = lbl.replace(" Chance", "").replace(" Shatter", "")
            if lbl:
                effect = f" | {lbl}"

        lines.append(f"{icon} F{form_num}: *{f['name']}*{req_txt} • 💥{f['dmg_min']}–{f['dmg_max']} | 🌀{f['sta_cost']}{effect}")
    return "\n".join(lines)


async def _send_style(update, style_meta: dict, player: dict = None):
    caption   = _format_caption(style_meta)
    forms_txt = _format_forms(style_meta, player)
    image     = get_style_image(style_meta["name"])

    if image:
        # 1. Try fully detailed single message
        full_detailed = caption + "\n" + forms_txt
        if len(full_detailed) <= 1024:
            try:
                await update.message.reply_photo(image, caption=full_detailed, parse_mode="Markdown")
                return
            except Exception:
                pass

        # 2. Try compact single message (guaranteed to fit 99% of the time)
        forms_compact = _format_forms_compact(style_meta, player)
        full_compact = caption + "\n" + forms_compact
        if len(full_compact) <= 1024:
            try:
                await update.message.reply_photo(image, caption=full_compact, parse_mode="Markdown")
                return
            except Exception:
                pass

        # 3. Fallback: split message if they both exceed 1024 characters
        try:
            await update.message.reply_photo(image, caption=caption, parse_mode="Markdown")
            if forms_txt:
                await update.message.reply_text(forms_txt, parse_mode="Markdown")
            return
        except Exception as e:
            log.warning("[INFO] Banner fallback failed: %s", e)

    # No image — send everything as one text block
    full = caption + "\n\n" + forms_txt
    await update.message.reply_text(full, parse_mode="Markdown")


# ── /mytechnique ───────────────────────────────────────────────────────────

async def mytechnique(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mytechnique — Slayers: see your breathing style forms."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return
    if player.get("faction") != "slayer":
        await update.message.reply_text("💡 You're a Demon — use `/myart` instead.", parse_mode="Markdown")
        return
    style = player.get("style")
    if not style:
        await update.message.reply_text("❌ No Breathing Style assigned yet. Use /breathing to roll one.")
        return
    style_meta = next((s for s in BREATHING_STYLES if s["name"] == style), None)
    if not style_meta:
        await update.message.reply_text(f"❌ Style `{style}` not found in config.")
        return
    await _send_style(update, style_meta, player)


# ── /myart ─────────────────────────────────────────────────────────────────

async def myart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/myart — Demons: see your demon art forms."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return
    if player.get("faction") != "demon":
        await update.message.reply_text("💡 You're a Slayer — use `/mytechnique` instead.", parse_mode="Markdown")
        return
    style = player.get("style")
    if not style:
        await update.message.reply_text("❌ No Blood Demon Art assigned. Use /art to roll one.")
        return
    style_meta = next((s for s in DEMON_ARTS if s["name"] == style), None)
    if not style_meta:
        await update.message.reply_text(f"❌ Art `{style}` not found in config.")
        return
    await _send_style(update, style_meta, player)


# ── /setstyleimage ─────────────────────────────────────────────────────────

async def setstyleimage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/setstyleimage [style name] [file_id/url]  OR  reply to a photo with /setstyleimage [name]"""
    user_id = update.effective_user.id
    if not _is_owner_or_admin(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    args  = context.args or []
    image = None

    # Check if replying to a photo / animation / document image
    reply = update.message.reply_to_message
    if reply:
        if reply.photo:
            image = reply.photo[-1].file_id
        elif reply.animation:
            image = reply.animation.file_id
        elif reply.document and (reply.document.mime_type or "").startswith("image/"):
            image = reply.document.file_id

    if not args:
        await update.message.reply_text(
            "📖 *Usage:*\n"
            "• `/setstyleimage Water Breathing <file_id>`\n"
            "• Reply to a photo with `/setstyleimage Water Breathing`",
            parse_mode="Markdown",
        )
        return

    if image:
        style_name_query = " ".join(args).strip()
    else:
        if len(args) < 2:
            await update.message.reply_text("❌ Provide a style name AND a file_id / URL.")
            return
        image            = args[-1].strip()
        style_name_query = " ".join(args[:-1]).strip()

    style_meta = _find_style(style_name_query)
    if not style_meta:
        await update.message.reply_text(f"❌ Style *'{style_name_query}'* not found.", parse_mode="Markdown")
        return

    col("style_images").update_one(
        {"style_name": style_meta["name"]},
        {"$set": {"style_name": style_meta["name"], "image": image, "set_by": user_id}},
        upsert=True,
    )
    await update.message.reply_text(
        f"✅ Banner updated for *{style_meta['name']}*!\n🖼️ `{image[:40]}...`",
        parse_mode="Markdown",
    )


# ── /infoall ───────────────────────────────────────────────────────────────

async def infoall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/infoall — Owner: full overview or deep-dive into one style."""
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Owner only.")
        return

    args = context.args or []
    if args:
        target = " ".join(args)
        style_meta = _find_style(target)
        if not style_meta:
            await update.message.reply_text(f"❌ `{target}` not found.", parse_mode="Markdown")
            return
        text = _format_style_info(style_meta)
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    # Full overview
    def _section(pool, label, icon):
        lines = [f"\n{icon} *{label}*\n"]
        for s in pool:
            forms   = TECHNIQUES.get(s["name"], [])
            w       = s.get("gacha_weight", 0)
            total_w = sum(x.get("gacha_weight", 0) for x in pool)
            chance  = f"{round(w/total_w*100,1)}%" if total_w and w else "UNIQUE"
            max_dmg = max((f["dmg_max"] for f in forms), default=0)
            lines.append(f"{s['emoji']} *{s['name']}*  {s['rarity']}")
            lines.append(f"   🎲 {chance}  |  📋 {len(forms)} forms  |  💥 max {max_dmg}")
        return "\n".join(lines)

    text = (
        "╔══════════════════════╗\n"
        "   👑 ALL STYLES & ARTS\n"
        "╚══════════════════════╝"
        + _section(BREATHING_STYLES, "BREATHING STYLES", "🗡️")
        + "\n━━━━━━━━━━━━━━━━━━━━━"
        + _section(DEMON_ARTS, "DEMON ARTS", "👹")
        + "\n\n💡 `/infoall [name]` — deep dive one style"
    )
    if len(text) > 4000:
        mid = len(text) // 2
        split = text.rfind("\n", 0, mid)
        await update.message.reply_text(text[:split], parse_mode="Markdown")
        await update.message.reply_text(text[split:], parse_mode="Markdown")
    else:
        await update.message.reply_text(text, parse_mode="Markdown")


# ── /is [id] ───────────────────────────────────────────────────────────────

async def view_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/is [id] — View a specific player suggestion in full."""
    user_id = update.effective_user.id
    player  = get_player(user_id)

    if not context.args:
        recent = list(col("suggestions").find({"status": "pending"}).sort("created_at", -1).limit(5))
        if not recent:
            await update.message.reply_text("📭 No pending suggestions.")
            return
        lines = ["💡 *RECENT SUGGESTIONS*\n━━━━━━━━━━━━━━━━━━━━━\n"]
        for s in recent:
            sid = str(s["_id"])[-6:].upper()
            lines.append(f"📋 `#{sid}` — _{s.get('text','')[:60]}..._")
        lines.append("\n💡 `/is [id]` — View full suggestion")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    sid      = context.args[0].lstrip("#").upper()
    all_sug  = list(col("suggestions").find().sort("created_at", -1))
    match    = next((s for s in all_sug if str(s["_id"])[-6:].upper() == sid), None)

    if not match:
        await update.message.reply_text(f"❌ Suggestion `#{sid}` not found.", parse_mode="Markdown")
        return

    icons = {"pending": "⏳", "approved": "✅", "planned": "⭐", "dismissed": "❌"}
    icon  = icons.get(match.get("status", "pending"), "⏳")

    lines = [
        "╔══════════════════════╗",
        f"      💡 SUGGESTION #{sid}",
        "╚══════════════════════╝\n",
        f"👤 *From:*   {match.get('name','?')} (@{match.get('username','?')})",
        f"📊 *Status:* {icon} {match.get('status','pending').upper()}",
        f"⏳ *Sent:*   {str(match.get('created_at','?'))[:16]}\n",
        "━━━━━━━━━━━━━━━━━━━━━",
        "💬 *Full Suggestion:*\n",
        match.get("text", ""),
        "━━━━━━━━━━━━━━━━━━━━━",
    ]
    if match.get("reviewed_by"):
        reviewer = get_player(match["reviewed_by"])
        r_name   = reviewer["name"] if reviewer else f"Admin {match['reviewed_by']}"
        lines.append(f"👑 *Reviewed by:* {r_name}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
