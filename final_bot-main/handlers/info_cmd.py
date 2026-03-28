"""
/info — View detailed info about your breathing style or demon art
/infoall — Owner-only: full breakdown of ALL styles/arts with damage, effects, forms
/is [id] — View a specific suggestion in full detail
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, col
from config import BREATHING_STYLES, DEMON_ARTS, TECHNIQUES, OWNER_ID


# ── /info [name] — View any breathing style or demon art ─────────────────

def _find_style(query: str):
    """Find a breathing style or demon art by name (exact or partial, case-insensitive)."""
    all_pool = BREATHING_STYLES + DEMON_ARTS
    q = query.lower().strip()
    # Exact match first
    match = next((s for s in all_pool if s['name'].lower() == q), None)
    if not match:
        # Partial match
        match = next((s for s in all_pool if q in s['name'].lower()), None)
    return match


def _format_style_info(style_meta: dict, player=None) -> str:
    """Build the full info text for a breathing style or demon art."""
    from utils.helpers import get_level, get_unlocked_forms

    name   = style_meta['name']
    emoji  = style_meta.get('emoji', '⚔️')
    rarity = style_meta.get('rarity', '⭐⭐ COMMON')
    desc   = style_meta.get('description', '')
    forms  = TECHNIQUES.get(name, [])

    is_breathing = style_meta in BREATHING_STYLES
    label = "BREATHING STYLE" if is_breathing else "DEMON ART"
    fe    = '🗡️' if is_breathing else '👹'

    # Stat bonus
    bonus_text = ""
    stat_bonus = style_meta.get('stat_bonus', {})
    if stat_bonus:
        parts = []
        for k, v in stat_bonus.items():
            label_map = {'str_stat': '💪 STR', 'spd': '⚡ SPD', 'def_stat': '🛡️ DEF',
                        'max_hp': '❤️ MaxHP', 'max_sta': '🌀 MaxSTA'}
            parts.append(f"{label_map.get(k, k)} +{v}")
        bonus_text = f"⭐ *Stat bonus:* {' | '.join(parts)}\n"

    # Gacha info
    weight = style_meta.get('gacha_weight', 0)
    pool   = BREATHING_STYLES if is_breathing else DEMON_ARTS
    total_w = sum(s.get('gacha_weight', 0) for s in pool)
    chance = f"{round(weight/total_w*100, 2)}%" if total_w > 0 and weight > 0 else "UNIQUE"
    gacha_line = f"🎲 *Gacha chance:* {chance}  (weight {weight})\n"

    # Player unlock info
    if player and player.get('style') == name:
        level    = get_level(player['xp'])
        unlocked = {f['form'] for f in get_unlocked_forms(name, level, player.get('rank') if player else None, player.get('faction') if player else None)}
        owned    = True
    elif player and player.get('hybrid_style') == name:
        level    = get_level(player['xp'])
        unlocked = {f['form'] for f in get_unlocked_forms(name, level, player.get('rank') if player else None, player.get('faction') if player else None)}
        owned    = True
    else:
        unlocked = set()
        owned    = False

    lines = [
        f"╔══════════════════════════╗",
        f"   {fe} {label}",
        f"╚══════════════════════════╝\n",
        f"{emoji} *{name}*",
        f"🏅 {rarity}",
        bonus_text.strip() if bonus_text else "",
        gacha_line.strip(),
        f"📖 _{desc}_\n",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"⚔️ *FORMS & TECHNIQUES* ({len(forms)} forms)\n",
    ]
    lines = [l for l in lines if l]  # remove empty

    if not forms:
        lines.append("_No technique forms defined for this style._")
    else:
        for f in forms:
            if owned and unlocked:
                locked  = f['form'] not in unlocked
                lock_ic = "🔒" if locked else "✅"
                req     = f"  _(Lv.{1+(f['form']-1)*3})_" if locked else ""
            else:
                lock_ic = "📋"
                req_lv  = 1 + (f['form'] - 1) * 3
                req     = f"  _(Unlocks Lv.{req_lv})_"

            lines.append(f"{lock_ic} *Form {f['form']} — {f['name']}*{req}")
            lines.append(f"   💥 DMG: *{f['dmg_min']}–{f['dmg_max']}*  |  🌀 STA: *{f['sta_cost']}*")

            extras = []
            if f.get('hits',1) > 1:     extras.append(f"🔁 ×{f['hits']} hits")
            if f.get('poison'):         extras.append("☠️ Poison")
            if f.get('effect'):
                eff_desc = {
                    'freeze_apply': '❄️ Freeze (2t)',
                    'burn_apply':   '🔥 Burn (5t)',
                    'bleed_apply':  '🩸 Bleed (3t)',
                    'poison_apply': '☠️ Poison (5t)',
                    'poison_aoe':   '☠️ Poison AOE (4t)',
                    'ice_shatter':  '🧊 Shatter: DEF-15 (3t)',
                    'ice_blind':    '🙈 Blind: 30% miss (1t)',
                    'ice_bleed':    '🩸 IceBleed: 12 DMG/t (2t)',
                    'frostburn':    '🌡️ Frostburn: -10 STA/t (3t)',
                    'ice_counter':  '🪞 Reflect 20% DMG (1t)',
                    'deep_freeze':  '❄️ Deep Freeze: skip 2 turns',
                    'flow_start':   '💧 Flow State',
                    'burn_execute': '🔥 Execute if burning <50%',
                    'bleed_payoff': '🩸 Payoff per bleed stack',
                }.get(f['effect'], f"✨ {f['effect'].replace('_',' ').title()}")
                extras.append(eff_desc)
            if f.get('unlock_rank'):    extras.append(f"🔐 Req: {f['unlock_rank']}")
            if f.get('desc'):           extras.append(f"📝 {f['desc']}")
            if extras:
                lines.append(f"   {chr(10) + '   '.join(extras) if len(extras) > 2 else ' | '.join(extras)}")
            lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    if owned:
        lines.append("✅ *You own this style!* Use in battle with 💨 Technique")
    else:
        lines.append("💡 Obtain via `/breathing` (slayer) or `/art` (demon) gacha")

    return '\n'.join(lines)


async def info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /info               — show YOUR current style details
    /info Water         — show Water Breathing details
    /info Ice           — show Ice Manipulation details
    /info Blood Whip    — show Blood Whip (demon art) details
    Works for ANY breathing style or demon art, regardless of faction.
    """
    user_id = update.effective_user.id
    player  = get_player(user_id)

    # If args given — look up that style (anyone can check any style)
    if context.args:
        query      = ' '.join(context.args).strip()
        style_meta = _find_style(query)
        if not style_meta:
            # Show all available names as hint
            all_names = [s['name'] for s in BREATHING_STYLES + DEMON_ARTS]
            await update.message.reply_text(
                f"❌ *Style not found:* `{query}`\n\n"
                f"💡 Try `/info Water` or `/info Blood Whip`\n\n"
                f"*All styles:*\n" +
                '\n'.join(f"  {'🗡️' if s in BREATHING_STYLES else '👹'} {s['name']}"
                           for s in BREATHING_STYLES + DEMON_ARTS),
                parse_mode='Markdown'
            )
            return
        text = _format_style_info(style_meta, player)
        await update.message.reply_text(text, parse_mode='Markdown')
        return

    # No args — show player's own style
    if not player:
        await update.message.reply_text(
            "❌ No character found.\n\n"
            "💡 `/info Water Breathing` — look up any style without an account",
            parse_mode='Markdown'
        )
        return

    style = player.get('style')
    if not style:
        await update.message.reply_text("❌ No style assigned. Use /breathing or /art.")
        return

    all_pool   = BREATHING_STYLES + DEMON_ARTS
    style_meta = next((s for s in all_pool if s['name'] == style), None)
    if not style_meta:
        await update.message.reply_text(f"❌ Style `{style}` not found in data.", parse_mode='Markdown')
        return

    text = _format_style_info(style_meta, player)
    await update.message.reply_text(text, parse_mode='Markdown')


# ── /infoall — Owner full breakdown of EVERYTHING ─────────────────────────

async def infoall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ Owner only.")
        return

    args = context.args or []
    if args:
        # /infoall [style name] — detailed view of one
        target_name = ' '.join(args)
        forms = TECHNIQUES.get(target_name)
        if not forms:
            # Try partial match
            for key in TECHNIQUES:
                if target_name.lower() in key.lower():
                    target_name = key
                    forms = TECHNIQUES[key]
                    break
        if not forms:
            await update.message.reply_text(f"❌ Style/art not found: `{target_name}`\n\nUse `/infoall` to see all.", parse_mode='Markdown')
            return

        all_pool = BREATHING_STYLES + DEMON_ARTS
        meta     = next((s for s in all_pool if s['name'] == target_name), {})

        lines = [
            f"╔══════════════════════╗",
            f"   👑 𝙊𝙒𝙉𝙀𝙍 𝙄𝙉𝙁𝙊",
            f"╚══════════════════════╝\n",
            f"{meta.get('emoji','⚔️')} *{target_name}*",
            f"🏅 {meta.get('rarity','?')}",
            f"🎲 Gacha weight: *{meta.get('gacha_weight','?')}*",
            f"📖 _{meta.get('description','')}_\n",
            f"━━━━━━━━━━━━━━━━━━━━━",
        ]

        total_min = sum(f['dmg_min'] for f in forms)
        total_max = sum(f['dmg_max'] for f in forms)
        lines.append(f"📊 Total damage potential: *{total_min}–{total_max}*\n")

        for f in forms:
            lines.append(f"⚔️ *Form {f['form']}: {f['name']}*")
            lines.append(f"   💥 DMG: {f['dmg_min']}–{f['dmg_max']}")
            lines.append(f"   🌀 STA cost: {f['sta_cost']}")
            if f.get('hits',1) > 1:     lines.append(f"   🔁 Hits: ×{f['hits']} (total: {f['dmg_min']*f['hits']}–{f['dmg_max']*f['hits']})")
            if f.get('effect'):         lines.append(f"   ✨ Effect: {f['effect']}")
            if f.get('type'):           lines.append(f"   🎯 Type: {f['type']}")
            if f.get('poison'):         lines.append(f"   ☠️ Applies Poison")
            if f.get('burn_chance'):    lines.append(f"   🔥 Burn chance: {f['burn_chance']}%")
            if f.get('unlock_rank'):    lines.append(f"   🔐 Unlock: {f['unlock_rank']}")
            if f.get('max_uses'):       lines.append(f"   ⚠️ Max uses: {f['max_uses']} (cooldown: {f.get('cooldown','?')} turns)")
            lines.append("")

        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    # /infoall — overview of everything
    lines = [
        "╔══════════════════════╗",
        "   👑 𝘼𝙇𝙇 𝙎𝙏𝙔𝙇𝙀𝙎 & 𝘼𝙍𝙏𝙎",
        "╚══════════════════════╝\n",
        "🗡️ *BREATHING STYLES*\n",
    ]

    for s in BREATHING_STYLES:
        forms  = TECHNIQUES.get(s['name'], [])
        w      = s.get('gacha_weight', 0)
        chance = f"{round(w/sum(x.get('gacha_weight',1) for x in BREATHING_STYLES)*100,1)}%" if w > 0 else "UNIQUE"
        lines.append(f"{s['emoji']} *{s['name']}*  {s['rarity']}")
        lines.append(f"   🎲 Weight: {w} ({chance})  |  📋 {len(forms)} forms")
        if forms:
            max_dmg = max(f['dmg_max'] for f in forms)
            lines.append(f"   💥 Max single hit: {max_dmg}")
        lines.append("")

    lines += ["━━━━━━━━━━━━━━━━━━━━━", "👹 *DEMON ARTS*\n"]

    for a in DEMON_ARTS:
        forms  = TECHNIQUES.get(a['name'], [])
        w      = a.get('gacha_weight', 0)
        chance = f"{round(w/sum(x.get('gacha_weight',1) for x in DEMON_ARTS)*100,1)}%" if w > 0 else "UNGETTABLE"
        lines.append(f"{a['emoji']} *{a['name']}*  {a['rarity']}")
        lines.append(f"   🎲 Weight: {w} ({chance})  |  📋 {len(forms)} forms")
        if forms:
            max_dmg = max(f['dmg_max'] for f in forms)
            lines.append(f"   💥 Max single hit: {max_dmg}")
        lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append("💡 `/infoall [name]` — Full detail on one style")

    # Split if too long
    text = '\n'.join(lines)
    if len(text) > 4000:
        mid = len(lines) // 2
        await update.message.reply_text('\n'.join(lines[:mid]), parse_mode='Markdown')
        await update.message.reply_text('\n'.join(lines[mid:]), parse_mode='Markdown')
    else:
        await update.message.reply_text(text, parse_mode='Markdown')


# ── /is [id] — View full suggestion ───────────────────────────────────────

async def view_suggestion(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)

    if not context.args:
        # List recent suggestions
        recent = list(col("suggestions").find({"status": "pending"}).sort("created_at", -1).limit(5))
        if not recent:
            await update.message.reply_text("📭 No pending suggestions right now.")
            return
        lines = ["💡 *RECENT SUGGESTIONS*\n━━━━━━━━━━━━━━━━━━━━━\n"]
        for s in recent:
            sid   = str(s['_id'])[-6:].upper()
            lines.append(f"📋 `#{sid}` — _{s['text'][:60]}..._")
        lines.append("\n💡 `/is [id]` — View full suggestion")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    sid = context.args[0].lstrip('#').upper()

    # Find by short ID (last 6 chars of ObjectId)
    all_sug = list(col("suggestions").find().sort("created_at", -1))
    match   = next((s for s in all_sug if str(s['_id'])[-6:].upper() == sid), None)

    if not match:
        await update.message.reply_text(f"❌ Suggestion `#{sid}` not found.", parse_mode='Markdown')
        return

    status_icons = {"pending": "⏳", "approved": "✅", "planned": "⭐", "dismissed": "❌"}
    icon  = status_icons.get(match['status'], '⏳')

    lines = [
        f"╔══════════════════════╗",
        f"      💡 𝙎𝙐𝙂𝙂𝙀𝙎𝙏𝙄𝙊𝙉 #{sid}",
        f"╚══════════════════════╝\n",
        f"👤 *From:*   {match['name']} (@{match.get('username','?')})",
        f"📊 *Status:* {icon} {match['status'].upper()}",
        f"🕐 *Sent:*   {str(match.get('created_at','?'))[:16]}\n",
        f"━━━━━━━━━━━━━━━━━━━━━",
        f"💬 *Full Suggestion:*\n",
        f"{match['text']}",
        f"━━━━━━━━━━━━━━━━━━━━━",
    ]

    if match.get('reviewed_by'):
        reviewer = get_player(match['reviewed_by'])
        r_name   = reviewer['name'] if reviewer else f"Admin {match['reviewed_by']}"
        lines.append(f"👑 *Reviewed by:* {r_name}")

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
