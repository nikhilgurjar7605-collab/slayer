"""
Skill Tree — 100 skills, paginated 10 per page, MongoDB skill_tree collection.
All bonuses are read by get_active_skill_bonuses() and applied in explore.py.
"""
from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, col, track_sp_spent
from utils.guards import dm_only
try:  # full skill data lives in config.SKILLS (falls back to the lightweight copy in utils.database)
    from config import SKILLS
except Exception:
    from utils.database import SKILLS

PAGE_SIZE = 10  # skills shown per page
VALID_SKILL_NAMES = {skill["name"] for skills in SKILLS.values() for skill in skills}
TOTAL_SKILL_COUNT = sum(len(skills) for skills in SKILLS.values())


def _normalize_skill_names(names: list) -> list:
    seen = set()
    clean = []
    for name in names or []:
        if name in VALID_SKILL_NAMES and name not in seen:
            seen.add(name)
            clean.append(name)
    return clean


# ── Safe edit ─────────────────────────────────────────────────────────────
async def _safe_edit(query, text, **kwargs):
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


# ── MongoDB helpers ───────────────────────────────────────────────────────
def get_player_skills(user_id: int) -> list:
    """Return list of skill names the player owns from MongoDB skill_tree."""
    doc = col("skill_tree").find_one({"user_id": user_id})
    if not doc:
        return []
    owned = doc.get("owned_skills", [])
    clean = _normalize_skill_names(owned if isinstance(owned, list) else [])
    if clean != owned:
        col("skill_tree").update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "owned_skills": clean}},
            upsert=True
        )
    return clean


def save_player_skills(user_id: int, owned: list):
    """Upsert the player's skill list into skill_tree collection."""
    clean = _normalize_skill_names(owned)
    col("skill_tree").update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "owned_skills": clean}},
        upsert=True
    )


def get_active_skill_bonuses(owned_skills: list, user_id: int = None,
                             used_once: list = None) -> dict:
    """
    Aggregate all bonuses from owned skills into one dict.
    - Respects deactivated skills (user_id provided)
    - Skips once_per_battle skills already used this battle (used_once list)
    - Numeric values stack; booleans are OR'd
    - Negative values (backlash) also applied
    """
    deactivated = _get_deactivated(user_id) if user_id else []
    used_once   = used_once or []
    active      = [s for s in owned_skills if s not in deactivated]

    bonuses = {}
    for category, skills in SKILLS.items():
        for skill in skills:
            if skill["name"] not in active:
                continue
            # Skip once_per_battle skills that have already fired
            if skill.get("type") == "once_per_battle" and skill["name"] in used_once:
                continue
            for k, v in skill["bonus"].items():
                if k in bonuses:
                    bonuses[k] = True if isinstance(v, bool) else bonuses[k] + v
                else:
                    bonuses[k] = v
    return bonuses


def get_once_skills(owned_skills: list, user_id: int = None) -> list:
    """Return list of once_per_battle skill names the player owns and are active."""
    deactivated = _get_deactivated(user_id) if user_id else []
    result = []
    for category, skills in SKILLS.items():
        for skill in skills:
            if (skill.get("type") == "once_per_battle"
                    and skill["name"] in owned_skills
                    and skill["name"] not in deactivated):
                result.append(skill["name"])
    return result


def _all_skills_flat() -> list:
    """Return all skills as a flat list with category attached."""
    flat = []
    for cat, skills in SKILLS.items():
        for s in skills:
            flat.append({**s, "category": cat})
    return flat


def _cat_icon(cat: str) -> str:
    return {
        "Combat":      "⚔️",
        "Technique":   "🌀",
        "Survival":    "🛡️",
        "Elite":       "💎",
        "Demon Path":  "👹",
        "Slayer Path": "🗡️",
        "Utility":     "💰",
        "Passive":     "✨",
        "Legendary":   "🌟",
        "Forbidden":   "☠️",
    }.get(cat, "⭐")


# Bonus keys that only apply under a condition — shown with a "<40%"-style tag
_CONDITIONAL_KEYS = {"low_hp_dmg": "<40%", "executioner": "<20%", "finish_pct": None}


def _bonus_label(k: str, v, compact: bool = False) -> str:
    """Human-readable bonus label. compact=True uses emoji prefixes (🛡 DMG −10%)."""
    pct = int(round(abs(v) * 100))
    sign = "+" if v >= 0 else "−"
    if compact:
        labels = {
            "atk_pct":        f"⚔ ATK {sign}{pct}%",
            "def_pct":        f"🛡 DEF {sign}{pct}%",
            "tech_pct":       f"🌀 TECH +{pct}%",
            "dmg_reduce":     f"🛡 DMG −{pct}%",
            "crit_bonus":     f"🎯 CRIT {sign}{pct}%",
            "dodge_bonus":    f"💨 DODGE {sign}{pct}%",
            "low_hp_dmg":     f"⚔ ATK +{pct}% <40%",
            "executioner":    f"💥 DMG +{pct}% <20%",
            "finish_pct":     f"💥 Kill Blow +{pct}%",
            "second_wind":    "❤️ Survive Fatal Hit",
            "last_stand":     "🔥 Last Stand",
            "null_status":    "🚫 Status Immune",
            "multi_art":      "🌀 Multi-Art Unlocked",
            "hp_on_kill":     f"❤️ +{pct}% HP on Kill",
            "regen_pct":      f"❤️ +{pct}% HP/turn",
            "regen_hp":       f"❤️ +{int(v)} HP/turn",
            "counter_chance": f"🗡 {pct}% Counter",
            "xp_pct":         f"⭐ XP +{pct}%",
            "yen_pct":        f"💰 Yen +{pct}%",
            "drop_pct":       f"🎁 Drops +{pct}%",
            "sta_reduce":     f"⚡ STA −{int(v)} cost",
            "combo_pct":      f"🔗 Combo +{pct}%",
            "first_strike":   f"💨 First Hit +{pct}%",
            "max_hp":         f"❤️ HP {sign}{int(v)}",
            "max_sta":        f"⚡ STA {sign}{int(v)}",
            "battle_hp_boost": f"❤️ +{int(v)} HP/battle",
        }
        if isinstance(v, bool):
            return labels.get(k, k)
        return labels.get(k, f"{k} {sign}{v}")
    labels = {
        "atk_pct":        f"+{int(v*100)}% ATK",
        "def_pct":        f"{'+' if v>=0 else ''}{int(v*100)}% DEF",
        "tech_pct":       f"+{int(v*100)}% TECH",
        "dmg_reduce":     f"-{int(v*100)}% DMG taken",
        "crit_bonus":     f"+{int(v*100)}% Crit",
        "dodge_bonus":    f"+{int(v*100)}% Dodge",
        "low_hp_dmg":     f"+{int(v*100)}% Bloodlust",
        "executioner":    f"+{int(v*100)}% Finisher",
        "finish_pct":     f"+{int(v*100)}% Kill Blow",
        "second_wind":    "Survive Fatal Hit",
        "last_stand":     "Last Stand",
        "null_status":    "Status Immune",
        "multi_art":      "Multi-Art Unlocked",
        "hp_on_kill":     f"+{int(v*100)}% HP on Kill",
        "regen_pct":      f"+{int(v*100)}% HP/turn",
        "regen_hp":       f"+{int(v)} HP/turn",
        "counter_chance": f"{int(v*100)}% Counter",
        "xp_pct":         f"+{int(v*100)}% XP",
        "yen_pct":        f"+{int(v*100)}% Yen",
        "drop_pct":       f"+{int(v*100)}% Drops",
        "sta_reduce":     f"-{int(v)} STA cost",
        "combo_pct":      f"+{int(v*100)}% Combo",
        "first_strike":   f"+{int(v*100)}% First Hit",
        "max_hp":         f"+{int(v)} Max HP",
        "max_sta":        f"+{int(v)} Max STA",
        "battle_hp_boost": f"+{int(v)} HP at battle start",
    }
    if isinstance(v, bool):
        return labels.get(k, k)
    return labels.get(k, f"{k}: +{v}")


def _esc(s: str) -> str:
    """Escape text for Telegram HTML parse mode."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _compact_effect_lines(skill: dict) -> list:
    """One short emoji line per effect, Telegram style: '⚔ ATK +20% <40%' / '⚠ DEF −5%'."""
    lines = []
    bonus = skill["bonus"]
    # Group regen_pct + battle_hp_boost into one combined line (e.g. Devour Soul)
    if "regen_pct" in bonus and "battle_hp_boost" in bonus:
        r, b = bonus["regen_pct"], bonus["battle_hp_boost"]
        lines.append(f"❤️ +{int(r*100)}% HP/turn · +{int(b)} HP")
        bonus = {k: v for k, v in bonus.items() if k not in ("regen_pct", "battle_hp_boost")}
    for k, v in bonus.items():
        label = _bonus_label(k, v, compact=True)
        if isinstance(v, (int, float)) and v < 0:
            # Avoid double minus: "⚠ ⚡ STA −5" not "⚠ ⚡ STA −-5"
            label = label.replace("−", "").lstrip()
            lines.append(f"⚠ {label}")
        else:
            lines.append(label)
    return lines


def _build_page(owned: list, page: int, category_filter: str = "all", sp: int = 0) -> tuple:
    """
    Build the text and keyboard for a skill tree page — compact Telegram-style UI:
        ⚔️ Iron Body          5 SP
           🛡 DMG −10%
    Locked skills (not enough SP) show 🔒 + how much more SP is needed.
    Returns (text, InlineKeyboardMarkup, total_pages)
    """
    flat = _all_skills_flat()

    # Filter by category
    if category_filter != "all":
        flat = [s for s in flat if s["category"] == category_filter]

    total_pages = max(1, (len(flat) + PAGE_SIZE - 1) // PAGE_SIZE)
    page        = max(0, min(page, total_pages - 1))
    page_skills = flat[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    cat_title = "Skill Tree" if category_filter == "all" else category_filter
    lines = [
        "⚔️ SKILL TREE",
        f"💠 {sp} SP  •  🧠 {len(owned)}/{TOTAL_SKILL_COUNT}",
        "─" * 20,
        "",
    ]

    buy_buttons = []
    for skill in page_skills:
        name     = skill["name"]
        cost     = skill["sp_cost"]
        owned_   = name in owned
        affordable = sp >= cost
        status   = "✅ OWNED" if owned_ else ("🟢" if affordable else "🔒")
        once_tag = "  🔔" if skill.get("type") == "once_per_battle" else ""

        # Header row: name padded left, cost on the right (Telegram-like alignment)
        left = f"{status} {name}"
        lines.append(f"<b>{_esc(left)}</b>{' ' * max(3, 20 - len(left))}<code>{cost} SP</code>{once_tag}")

        # Effect lines
        for eff in _compact_effect_lines(skill):
            lines.append(f"   {_esc(eff)}")

        # Locked → tell the player exactly what's missing
        if not owned_ and not affordable:
            lines.append(f"   🔸 +{cost - sp} SP required")
        lines.append("")

        if not owned_:
            buy_buttons.append([InlineKeyboardButton(
                f"💠 Buy {name} — {cost} SP" + ("" if affordable else " (🔒)"),
                callback_data=f"skillbuy_{name.replace(' ', '_')}"
            )])

    # Navigation footer + buttons
    lines.append("─" * 19)
    lines.append(f"{page + 1} / {total_pages}")

    nav = [InlineKeyboardButton("◀ PREV", callback_data=f"skillpage_{max(0, page-1)}_{category_filter}")]
    nav.append(InlineKeyboardButton("NEXT ▶", callback_data=f"skillpage_{min(total_pages-1, page+1)}_{category_filter}"))

    # Category filter rows (6 per row)
    cats = [
        ("All", "all"), ("⚔️ Combat", "Combat"), ("🌀 Tech", "Technique"),
        ("🛡️ Surv", "Survival"), ("💎 Elite", "Elite"), ("👹 Demon", "Demon Path"),
        ("🗡️ Slayer", "Slayer Path"), ("💰 Util", "Utility"), ("✨ Passive", "Passive"),
        ("🌟 Legend", "Legendary"), ("☠️ Forbid", "Forbidden"),
    ]
    cat_rows = []
    row = []
    for label, c in cats:
        prefix = "✓ " if ((c == "all" and category_filter == "all") or category_filter == c) else ""
        row.append(InlineKeyboardButton(f"{prefix}{label}", callback_data=f"skillpage_0_{c}"))
        if len(row) == 3:
            cat_rows.append(row); row = []
    if row:
        cat_rows.append(row)

    buttons = buy_buttons.copy()
    buttons.append(nav)
    buttons.extend(cat_rows)
    buttons.append([InlineKeyboardButton("📊 My Skills", callback_data="skillpage_mine")])

    return "\n".join(lines), InlineKeyboardMarkup(buttons), total_pages


# ── /skilltree ─────────────────────────────────────────────────────────────
@dm_only
async def skilltree(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        msg = update.message if update.message else update.callback_query.message
        await msg.reply_text("❌ No character found. Use /start to create one.")
        return

    owned   = get_player_skills(user_id)
    sp      = player.get("skill_points", 0)

    text, kb, total_pages = _build_page(owned, 0, sp=sp)

    if update.callback_query:
        await _safe_edit(update.callback_query, text, parse_mode="HTML", reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


# ── Skill page callback (pagination + category filter) ────────────────────
async def skilltree_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data    = query.data  # skillpage_N_category  or  skillpage_mine

    if data == "skillpage_mine":
        await _show_my_skills(query, user_id)
        return

    parts    = data.split("_", 2)
    page     = int(parts[1]) if len(parts) > 1 else 0
    category = parts[2] if len(parts) > 2 else "all"

    player = get_player(user_id)
    if not player:
        await query.answer("❌ No character found!", show_alert=True)
        return

    owned   = get_player_skills(user_id)
    sp      = player.get("skill_points", 0)
    text, kb, _ = _build_page(owned, page, category, sp=sp)

    await _safe_edit(query, text, parse_mode="HTML", reply_markup=kb)


async def _show_my_skills(query, user_id: int):
    """Show owned skills and active bonuses."""
    player  = get_player(user_id)
    owned   = get_player_skills(user_id)
    bonuses = get_active_skill_bonuses(owned)
    sp      = player.get("skill_points", 0) if player else 0

    if not owned:
        text = (
            "🌳 <b>YOUR SKILLS</b>\n\n"
            "<i>You haven't bought any skills yet!</i>\n\n"
            "💡 Use <code>/skilltree</code> to browse and buy skills.\n"
            f"💠 You have <b>{sp} SP</b> to spend."
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌳 Browse Skills", callback_data="skillpage_0_all")
        ]])
        await _safe_edit(query, text, parse_mode="HTML", reply_markup=kb)
        return

    # Group owned skills by category
    flat = _all_skills_flat()
    by_cat = {}
    for s in flat:
        if s["name"] in owned:
            by_cat.setdefault(s["category"], []).append(s["name"])

    lines = [
        "🌳 MY SKILLS",
        "─" * 20,
        f"✅ <b>Owned:</b> {len(owned)} skills  |  💠 <b>SP left:</b> {sp}\n",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]
    for cat, names in by_cat.items():
        lines.append(f"\n{_cat_icon(cat)} <b>{cat}</b>")
        for n in names:
            lines.append(f"  ✅ {n}")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
    lines.append("<b>📊 Active Bonuses:</b>")
    for k, v in bonuses.items():
        lines.append(f"  ╰➤ {_bonus_label(k, v)}")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Back to Skill Tree", callback_data="skillpage_0_all")
    ]])
    await _safe_edit(query, "\n".join(lines), parse_mode="HTML", reply_markup=kb)


# ── Buy skill (callback) ───────────────────────────────────────────────────
async def skilltree_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    name    = query.data.replace("skillbuy_", "").replace("_", " ")
    await _buy_skill(query.message, user_id, name, query=query)


# ── /skillbuy command ─────────────────────────────────────────────────────
@dm_only
async def skillbuy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(
            "Usage: <code>/skillbuy [skill name]</code>\n\nUse <code>/skilltree</code> to browse skills.",
            parse_mode="HTML"
        )
        return
    name = " ".join(context.args)
    await _buy_skill(update.message, user_id, name)


async def _buy_skill(msg, user_id: int, name: str, query=None):
    player = get_player(user_id)
    if not player:
        await msg.reply_text("❌ No character found.")
        return

    # Find skill (case-insensitive)
    flat   = _all_skills_flat()
    skill  = next((s for s in flat if s["name"].lower() == name.lower()), None)
    if not skill:
        # Partial match
        skill = next((s for s in flat if name.lower() in s["name"].lower()), None)
    if not skill:
        txt = f"❌ Skill <b>{_esc(name)}</b> not found.\nUse <code>/skilltree</code> to see all skills."
        if query:
            await query.answer(f"❌ Skill '{name}' not found!", show_alert=True)
        else:
            await msg.reply_text(txt, parse_mode="HTML")
        return

    owned = get_player_skills(user_id)
    if skill["name"] in owned:
        if query:
            await query.answer(f"✅ Already own {skill['name']}!", show_alert=True)
        else:
            await msg.reply_text(f"✅ You already own <b>{_esc(skill['name'])}</b>!", parse_mode="HTML")
        return

    sp = player.get("skill_points", 0)
    if sp < skill["sp_cost"]:
        txt = (
            f"❌ <b>Not enough SP!</b>\n\n"
            f"Need: <b>{skill['sp_cost']} SP</b>\nYou have: <b>{sp} SP</b>\n\n"
            f"<i>Earn SP by leveling up or winning duels.</i>"
        )
        if query:
            await query.answer(f"Need {skill['sp_cost']} SP, you have {sp}!", show_alert=True)
        else:
            await msg.reply_text(txt, parse_mode="HTML")
        return

    # Purchase — save to MongoDB skill_tree
    owned.append(skill["name"])
    save_player_skills(user_id, owned)
    update_player(user_id, skill_points=sp - skill["sp_cost"])
    track_sp_spent(skill["sp_cost"])

    # Apply permanent stat bonuses immediately to player doc
    perm = {"max_hp", "max_sta"}
    perm_updates = {}
    for k, v in skill["bonus"].items():
        if k in perm and not isinstance(v, bool):
            perm_updates[k] = player.get(k, 200 if k == "max_hp" else 150) + v
    if perm_updates:
        col("players").update_one({"user_id": user_id}, {"$set": perm_updates})

    bonus_lines = "\n".join(
        f"  ╰➤ {_bonus_label(k,v)}"
        for k, v in skill["bonus"].items()
    )
    result = (
        f"✅ <b>SKILL PURCHASED!</b>\n"
        f"{'─' * 20}\n"
        f"{_cat_icon(skill['category'])} <b>{_esc(skill['name'])}</b>  <code>{skill['sp_cost']} SP</code>\n"
        f"<i>{_esc(skill['description'])}</i>\n\n"
        f"<b>📊 Bonuses applied:</b>\n{bonus_lines}\n\n"
        f"💠 SP remaining: <b>{sp - skill['sp_cost']}</b>"
    )

    if query:
        # Refresh the skill tree page after purchase
        await query.answer(f"✅ {skill['name']} purchased!")
        await _safe_edit(query, result, parse_mode="HTML",
                         reply_markup=InlineKeyboardMarkup([[
                             InlineKeyboardButton("◀️ Back to Skill Tree", callback_data="skillpage_0_all")
                         ]]))
    else:
        await msg.reply_text(result, parse_mode="HTML")


# ── /skilllist ────────────────────────────────────────────────────────────
async def skilllist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick text list of all skills — use /skilltree for interactive browser."""
    lines = [f"🌳 <b>ALL {TOTAL_SKILL_COUNT} SKILLS</b>\n{'─' * 20}\n"]
    for cat, skills in SKILLS.items():
        icon = _cat_icon(cat)
        lines.append(f"{icon} <b>{cat.upper()}</b> ({len(skills)} skills)")
        for s in skills:
            lines.append(f"  ╰➤ <b>{_esc(s['name'])}</b> ({s['sp_cost']} SP) — <i>{_esc(s['description'])}</i>")
        lines.append("")
    lines.append("💡 <code>/skilltree</code> — Interactive browser with Buy buttons\n<code>/skillbuy [name]</code> — Buy directly")
    # Split into chunks to avoid 4096 char limit
    text = "\n".join(lines)
    chunks = [text[i:i+3800] for i in range(0, len(text), 3800)]
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode="HTML")


# ── /skillinfo ────────────────────────────────────────────────────────────
async def skillinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: <code>/skillinfo [skill name]</code>", parse_mode="HTML")
        return
    name  = " ".join(context.args)
    flat  = _all_skills_flat()
    skill = next((s for s in flat if s["name"].lower() == name.lower()), None)
    if not skill:
        skill = next((s for s in flat if name.lower() in s["name"].lower()), None)
    if not skill:
        await update.message.reply_text(f"❌ Skill <b>{_esc(name)}</b> not found.", parse_mode="HTML")
        return

    user_id = update.effective_user.id
    owned   = get_player_skills(user_id)
    status  = "✅ OWNED" if skill["name"] in owned else f"💠 {skill['sp_cost']} SP"

    lines = [
        "⚔️ SKILL TREE",
        f"{_cat_icon(skill['category'])} <b>{_esc(skill['name'])}</b>" + " " * max(3, 20 - len(skill['name'])) + f"<code>{skill['sp_cost']} SP</code>",
        f"   🏷 {_esc(skill['category'])}  •  {status}",
    ]
    if skill.get("type") == "once_per_battle":
        lines.append("   🔔 Once per battle")
    lines.append("─" * 20)
    for eff in _compact_effect_lines(skill):
        lines.append(f"   {_esc(eff)}")
    lines.append("")
    lines.append(f"<i>{_esc(skill['description'])}</i>")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


# ── /skills — show player's owned skills + active bonuses ─────────────────
def _build_my_skills_page(user_id: int, cat_filter: str = "all") -> tuple:
    """Build paginated My Skills view — shows 12 skills per page per category."""
    from utils.database import get_player
    player  = get_player(user_id)
    owned   = get_player_skills(user_id)
    deacted = _get_deactivated(user_id)
    sp      = player.get("skill_points", 0) if player else 0

    # Build by-category map of owned skills
    flat   = _all_skills_flat()
    by_cat = {}
    for s in flat:
        if s["name"] in owned:
            by_cat.setdefault(s["category"], []).append(s)

    # Filter by category
    if cat_filter == "all":
        show_cats = list(by_cat.items())
    else:
        show_cats = [(cat, skills) for cat, skills in by_cat.items() if cat == cat_filter]

    # Build text
    lines = [f"🌳 <b>MY SKILLS</b> ({len(owned)} owned)  💠 <b>{sp} SP</b>",
             "─" * 20]

    for cat, cat_skills in show_cats:
        lines.append(f"\n{_cat_icon(cat)} <b>{cat}</b>")
        for s in cat_skills:
            status = "🔴" if s["name"] in deacted else "✅"
            once   = " _(once/battle)_" if s.get("type") == "once_per_battle" else ""
            lines.append(f"  {status} {s['name']}{once}")

    if not show_cats:
        lines.append("\n<i>No skills in this category.</i>")

    # Bonuses summary - show more buffs with "More" button if needed
    active_names = [s for s in owned if s not in deacted]
    bonuses = get_active_skill_bonuses(active_names)
    if bonuses:
        lines.append("\n" + "─" * 20)
        lines.append("<b>📊 Active Bonuses:</b>")
        bonus_limit = 15  # show up to 15 bonuses
        bonus_items = list(bonuses.items())
        for k, v in bonus_items[:bonus_limit]:
            lines.append(f"  ╰➤ {_bonus_label(k, v)}")
        if len(bonuses) > bonus_limit:
            lines.append(f"  ╰➤ <i>...+{len(bonuses)-bonus_limit} more</i>")
            # Add a button to view all bonuses

    # Build keyboard — category tabs
    all_cats = list(by_cat.keys())
    cat_buttons = []
    row = []
    for cat in ["all"] + all_cats:
        icon = "🌳" if cat == "all" else _cat_icon(cat)
        active_marker = "·" if cat == cat_filter else ""
        row.append(InlineKeyboardButton(
            f"{active_marker}{icon}",
            callback_data=f"myskills_{cat}"
        ))
        if len(row) == 4:
            cat_buttons.append(row); row = []
    if row:
        cat_buttons.append(row)

    cat_buttons.append([
        InlineKeyboardButton("⚙️ Manage", callback_data="myskills_manage"),
        InlineKeyboardButton("🌳 Browse Tree", callback_data="skillpage_0_all"),
    ])
    
    # Add "View All Bonuses" button if there are many bonuses
    if bonuses and len(bonuses) > bonus_limit:
        cat_buttons.append([
            InlineKeyboardButton("📜 View All Buffs", callback_data="myskills_allbonuses")
        ])

    kb = InlineKeyboardMarkup(cat_buttons)
    return "\n".join(lines), kb


async def skills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /skills or /myskills — show your owned skills with category filter buttons.
    Replaces the giant wall-of-text with a compact paginated view.
    """
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    owned = get_player_skills(user_id)
    sp    = player.get("skill_points", 0)

    if not owned:
        await update.message.reply_text(
            "🌳 <b>Your Skills</b>\n\n<i>No skills owned yet.</i>\n\n"
            f"💠 You have <b>{sp} SP</b> available.\n"
            "Use <code>/skilltree</code> to browse and buy skills.",
            parse_mode="HTML"
        )
        return

    text, kb = _build_my_skills_page(user_id, "all")
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=kb)


async def myskills_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category tab buttons in My Skills view."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data    = query.data  # myskills_{cat} or myskills_manage or myskills_allbonuses

    if data == "myskills_manage":
        # Redirect to deactivate command view
        owned   = get_player_skills(user_id)
        deacted = _get_deactivated(user_id)
        active  = [s for s in owned if s not in deacted]
        inactive = [s for s in owned if s in deacted]
        lines = [
            "⚙️ <b>SKILL MANAGER</b>",
            "─" * 20,
            f"✅ Active: <b>{len(active)}</b>  🔴 Deactivated: <b>{len(inactive)}</b>\n",
        ]
        if inactive:
            lines.append("<b>Deactivated:</b>")
            for s in inactive:
                lines.append(f"  🔴 {s}")
        lines += [
            "",
            "─" * 20,
            "💡 <code>/deactivate [name]</code> or <code>/deactivateall</code>",
            "💡 <code>/reactivate [name]</code> or <code>/reactivateall</code>",
        ]
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Back", callback_data="myskills_all")
        ]])
        try:
            await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass
        return
    
    if data == "myskills_allbonuses":
        # Show all active bonuses in a detailed view
        owned   = get_player_skills(user_id)
        deacted = _get_deactivated(user_id)
        active_names = [s for s in owned if s not in deacted]
        bonuses = get_active_skill_bonuses(active_names)
        
        lines = [
            "📊 <b>ALL ACTIVE BONUSES</b>",
            "─" * 20,
            f"<i>Total: {len(bonuses)} active buffs</i>\n",
        ]
        
        if bonuses:
            for k, v in sorted(bonuses.items()):
                lines.append(f"  ╰➤ {_bonus_label(k, v)}")
        else:
            lines.append("<i>No active bonuses.</i>")
        
        lines.append("\n" + "─" * 20)
        lines.append("<i>From your equipped items and learned skills</i>")
        
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Back to Skills", callback_data="myskills_all")
        ]])
        try:
            await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass
        return

    cat_filter = data[len("myskills_"):] if data.startswith("myskills_") else "all"
    text, kb   = _build_my_skills_page(user_id, cat_filter)
    try:
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=kb)
    except Exception:
        pass


# ── Legacy aliases ────────────────────────────────────────────────────────
async def skilltree_owned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await skills(update, context)



# ── /deactivate — toggle a skill off without losing it ─────────────────────
async def deactivateskill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /deactivate [skill name]    — deactivate a skill (stops its bonuses)
    /deactivate                 — show your active + deactivated skills
    /reactivate [skill name]    — re-enable a deactivated skill
    
    Skills stay owned — you don't lose SP. Just their bonuses stop applying.
    Useful for fine-tuning your build.
    """
    from telegram import Update as _U
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    owned    = get_player_skills(user_id)
    deactive = _get_deactivated(user_id)

    if not context.args:
        # Show active vs deactivated skills
        active_list   = [s for s in owned if s not in deactive]
        inactive_list = [s for s in owned if s in deactive]

        lines = [
            "⚙️ <b>SKILL MANAGER</b>",
            "─" * 20,
            f"✅ <b>Active:</b> {len(active_list)} skills",
            f"🔴 <b>Deactivated:</b> {len(inactive_list)} skills",
            "",
        ]
        if active_list:
            lines.append("<b>Active skills:</b>")
            for s in active_list[:15]:
                lines.append(f"  ✅ {s}")
        if inactive_list:
            lines.append("\n<b>Deactivated skills:</b>")
            for s in inactive_list:
                lines.append(f"  🔴 {s}")

        lines += [
            "",
            "─" * 20,
            "💡 <code>/deactivate [skill name]</code> — deactivate",
            "💡 <code>/reactivate [skill name]</code> — re-enable",
        ]
        await update.message.reply_text('\n'.join(lines), parse_mode='HTML')
        return

    skill_name = ' '.join(context.args).strip()

    # Fuzzy match
    match = next((s for s in owned if s.lower() == skill_name.lower()), None)
    if not match:
        match = next((s for s in owned if skill_name.lower() in s.lower()), None)
    if not match:
        await update.message.reply_text(
            f"❌ <b>{_esc(skill_name)}</b> not found in your skills.\n\n"
            f"Use <code>/deactivate</code> to see your full skill list.",
            parse_mode='HTML'
        )
        return

    if match in deactive:
        await update.message.reply_text(
            f"❌ <b>{_esc(match)}</b> is already deactivated.\n"
            f"Use <code>/reactivate {match}</code> to re-enable it.",
            parse_mode='HTML'
        )
        return

    deactive.append(match)
    _save_deactivated(user_id, deactive)
    await update.message.reply_text(
        f"🔴 <b>{_esc(match)}</b> deactivated.\n\n"
        f"<i>Its bonuses will no longer apply in battle.</i>\n"
        f"Use <code>/reactivate {match}</code> to turn it back on.",
        parse_mode='HTML'
    )


async def reactivateskill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-enable a deactivated skill."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    if not context.args:
        await update.message.reply_text(
            "💡 Usage: <code>/reactivate [skill name]</code>\n\n"
            "Use <code>/deactivate</code> to see your deactivated skills.\n"
            "Or: <code>/reactivateall</code> to enable everything at once.",
            parse_mode='HTML'
        )
        return

    skill_name = ' '.join(context.args).strip()
    deactive   = _get_deactivated(user_id)

    match = next((s for s in deactive if s.lower() == skill_name.lower()), None)
    if not match:
        match = next((s for s in deactive if skill_name.lower() in s.lower()), None)
    if not match:
        await update.message.reply_text(
            f"❌ <b>{_esc(skill_name)}</b> is not deactivated.\n\n"
            f"Use <code>/deactivate</code> to see your deactivated skills.",
            parse_mode='HTML'
        )
        return

    deactive.remove(match)
    _save_deactivated(user_id, deactive)
    await update.message.reply_text(
        f"✅ <b>{_esc(match)}</b> reactivated!\n\n"
        f"<i>Its bonuses will apply in battle again.</i>",
        parse_mode='HTML'
    )


async def deactivateall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/deactivateall — deactivate every skill at once."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    owned = get_player_skills(user_id)
    if not owned:
        await update.message.reply_text("❌ You have no skills to deactivate.")
        return

    _save_deactivated(user_id, list(owned))
    await update.message.reply_text(
        f"🔴 <b>All {len(owned)} skills deactivated.</b>\n\n"
        f"<i>No skill bonuses will apply in battle.</i>\n"
        f"Use <code>/reactivateall</code> to re-enable everything.",
        parse_mode='HTML'
    )


async def reactivateall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/reactivateall — re-enable every skill at once."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    deactive = _get_deactivated(user_id)
    if not deactive:
        await update.message.reply_text("✅ All your skills are already active!")
        return

    count = len(deactive)
    _save_deactivated(user_id, [])
    await update.message.reply_text(
        f"✅ <b>{count} skill(s) reactivated!</b>\n\n"
        f"<i>All your skill bonuses are now active in battle.</i>",
        parse_mode='HTML'
    )


def _get_deactivated(user_id: int) -> list:
    """Get list of deactivated skill names for a player."""
    doc = col("skill_tree").find_one({"user_id": user_id})
    if not doc:
        return []
    deactivated = doc.get("deactivated_skills", [])
    clean = _normalize_skill_names(deactivated if isinstance(deactivated, list) else [])
    if clean != deactivated:
        col("skill_tree").update_one(
            {"user_id": user_id},
            {"$set": {"deactivated_skills": clean}},
            upsert=True
        )
    return clean


def _save_deactivated(user_id: int, deactivated: list):
    """Save deactivated skill list."""
    clean = _normalize_skill_names(deactivated)
    col("skill_tree").update_one(
        {"user_id": user_id},
        {"$set": {"deactivated_skills": clean}},
        upsert=True
    )
