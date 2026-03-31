"""
Skill Tree — 100 skills, paginated 10 per page, MongoDB skill_tree collection.
All bonuses are read by get_active_skill_bonuses() and applied in explore.py.
"""
from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, col, track_sp_spent
from utils.guards import dm_only
from config import SKILLS

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


def _bonus_label(k: str, v) -> str:
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
    }
    if isinstance(v, bool):
        return labels.get(k, k)
    return labels.get(k, f"{k}: +{v}")


def _build_page(owned: list, page: int, category_filter: str = "all") -> tuple:
    """
    Build the text and keyboard for a skill tree page.
    Returns (text, InlineKeyboardMarkup, total_pages)
    """
    flat = _all_skills_flat()

    # Filter by category
    if category_filter != "all":
        flat = [s for s in flat if s["category"] == category_filter]

    total_pages = max(1, (len(flat) + PAGE_SIZE - 1) // PAGE_SIZE)
    page        = max(0, min(page, total_pages - 1))
    page_skills = flat[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = [
        "╔══════════════════════╗",
        "      🌳 𝙎𝙆𝙄𝙇𝙇 𝙏𝙍𝙀𝙀",
        "╚══════════════════════╝\n",
        f"📄 Page *{page+1}/{total_pages}*  |  Skills: *{len(flat)}*  |  Category: *{category_filter.title()}*\n",
        "━━━━━━━━━━━━━━━━━━━━━\n",
    ]

    buy_buttons = []
    for skill in page_skills:
        icon     = _cat_icon(skill["category"])
        owned_   = skill["name"] in owned
        status   = "✅" if owned_ else f"💠 {skill['sp_cost']} SP"
        once_tag = "  🔔 _(once/battle)_" if skill.get("type") == "once_per_battle" else ""
        pos_bonus = {k:v for k,v in skill["bonus"].items() if not isinstance(v,(int,float)) or v >= 0}
        neg_bonus = {k:v for k,v in skill["bonus"].items() if isinstance(v,(int,float)) and v < 0}
        pos_str = " | ".join(_bonus_label(k,v) for k,v in pos_bonus.items())
        neg_str = ("  ⚠️ " + " | ".join(_bonus_label(k,v) for k,v in neg_bonus.items())) if neg_bonus else ""
        lines.append(
            f"{icon} *{skill['name']}*  [{status}]{once_tag}\n"
            f"   _{skill['description']}_\n"
            f"   `{pos_str}`{neg_str}"
        )
        if not owned_:
            buy_buttons.append([InlineKeyboardButton(
                f"💠 Buy — {skill['name']} ({skill['sp_cost']} SP)",
                callback_data=f"skillbuy_{skill['name'].replace(' ','_')}"
            )])

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━")

    # Navigation row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"skillpage_{page-1}_{category_filter}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"skillpage_{page+1}_{category_filter}"))

    # Category filter row
    cats = [
        ("All","all"), ("⚔️","Combat"), ("🌀","Technique"),
        ("🛡️","Survival"), ("💎","Elite"), ("👹","Demon Path"),
        ("🗡️","Slayer Path"), ("💰","Utility"), ("✨","Passive"),
        ("🌟","Legendary"), ("☠️","Forbidden")
    ]
    cat_row = [
        InlineKeyboardButton(f"{'✓' if (c=='all' and category_filter=='all') or category_filter==c else ''}{emoji}",
                             callback_data=f"skillpage_0_{c}")
        for emoji, c in cats
    ]

    buttons = buy_buttons.copy()
    if nav: buttons.append(nav)
    buttons.append(cat_row)
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
    bonuses = get_active_skill_bonuses(owned)

    text, kb, total_pages = _build_page(owned, 0)
    header = (
        f"💠 *Skill Points:* {sp} SP  |  ✅ *Owned:* {len(owned)}\n\n"
    )

    if update.callback_query:
        await _safe_edit(update.callback_query, header + text, parse_mode="Markdown", reply_markup=kb)
    else:
        await update.message.reply_text(header + text, parse_mode="Markdown", reply_markup=kb)


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
    text, kb, _ = _build_page(owned, page, category)
    header  = f"💠 *Skill Points:* {sp} SP  |  ✅ *Owned:* {len(owned)}\n\n"

    await _safe_edit(query, header + text, parse_mode="Markdown", reply_markup=kb)


async def _show_my_skills(query, user_id: int):
    """Show owned skills and active bonuses."""
    player  = get_player(user_id)
    owned   = get_player_skills(user_id)
    bonuses = get_active_skill_bonuses(owned)
    sp      = player.get("skill_points", 0) if player else 0

    if not owned:
        text = (
            "🌳 *YOUR SKILLS*\n\n"
            "_You haven't bought any skills yet!_\n\n"
            "💡 Use `/skilltree` to browse and buy skills.\n"
            f"💠 You have *{sp} SP* to spend."
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌳 Browse Skills", callback_data="skillpage_0_all")
        ]])
        await _safe_edit(query, text, parse_mode="Markdown", reply_markup=kb)
        return

    # Group owned skills by category
    flat = _all_skills_flat()
    by_cat = {}
    for s in flat:
        if s["name"] in owned:
            by_cat.setdefault(s["category"], []).append(s["name"])

    lines = [
        "╔══════════════════════╗",
        "   🌳 𝙈𝙔 𝙎𝙆𝙄𝙇𝙇𝙎",
        f"╚══════════════════════╝\n",
        f"✅ *Owned:* {len(owned)} skills  |  💠 *SP left:* {sp}\n",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]
    for cat, names in by_cat.items():
        lines.append(f"\n{_cat_icon(cat)} *{cat}*")
        for n in names:
            lines.append(f"  ✅ {n}")

    lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📊 *Active Bonuses:*")
    for k, v in bonuses.items():
        lines.append(f"  ╰➤ {_bonus_label(k, v)}")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ Back to Skill Tree", callback_data="skillpage_0_all")
    ]])
    await _safe_edit(query, "\n".join(lines), parse_mode="Markdown", reply_markup=kb)


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
            "Usage: `/skillbuy [skill name]`\n\nUse `/skilltree` to browse skills.",
            parse_mode="Markdown"
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
        txt = f"❌ Skill *{name}* not found.\nUse `/skilltree` to see all skills."
        if query:
            await query.answer(f"❌ Skill '{name}' not found!", show_alert=True)
        else:
            await msg.reply_text(txt, parse_mode="Markdown")
        return

    owned = get_player_skills(user_id)
    if skill["name"] in owned:
        if query:
            await query.answer(f"✅ Already own {skill['name']}!", show_alert=True)
        else:
            await msg.reply_text(f"✅ You already own *{skill['name']}*!", parse_mode="Markdown")
        return

    sp = player.get("skill_points", 0)
    if sp < skill["sp_cost"]:
        txt = (
            f"❌ *Not enough SP!*\n\n"
            f"Need: *{skill['sp_cost']} SP*\nYou have: *{sp} SP*\n\n"
            f"_Earn SP by leveling up or winning duels._"
        )
        if query:
            await query.answer(f"Need {skill['sp_cost']} SP, you have {sp}!", show_alert=True)
        else:
            await msg.reply_text(txt, parse_mode="Markdown")
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
        f"✅ *SKILL PURCHASED!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{_cat_icon(skill['category'])} *{skill['name']}*\n"
        f"_{skill['description']}_\n\n"
        f"📊 *Bonuses applied:*\n{bonus_lines}\n\n"
        f"💠 SP remaining: *{sp - skill['sp_cost']}*"
    )

    if query:
        # Refresh the skill tree page after purchase
        await query.answer(f"✅ {skill['name']} purchased!")
        await _safe_edit(query, result, parse_mode="Markdown",
                         reply_markup=InlineKeyboardMarkup([[
                             InlineKeyboardButton("◀️ Back to Skill Tree", callback_data="skillpage_0_all")
                         ]]))
    else:
        await msg.reply_text(result, parse_mode="Markdown")


# ── /skilllist ────────────────────────────────────────────────────────────
async def skilllist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick text list of all skills — use /skilltree for interactive browser."""
    lines = [f"🌳 *ALL {TOTAL_SKILL_COUNT} SKILLS*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    for cat, skills in SKILLS.items():
        icon = _cat_icon(cat)
        lines.append(f"{icon} *{cat.upper()}* ({len(skills)} skills)")
        for s in skills:
            lines.append(f"  ╰➤ *{s['name']}* ({s['sp_cost']} SP) — _{s['description']}_")
        lines.append("")
    lines.append("💡 `/skilltree` — Interactive browser with Buy buttons\n`/skillbuy [name]` — Buy directly")
    # Split into chunks to avoid 4096 char limit
    text = "\n".join(lines)
    chunks = [text[i:i+3800] for i in range(0, len(text), 3800)]
    for chunk in chunks:
        await update.message.reply_text(chunk, parse_mode="Markdown")


# ── /skillinfo ────────────────────────────────────────────────────────────
async def skillinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/skillinfo [skill name]`", parse_mode="Markdown")
        return
    name  = " ".join(context.args)
    flat  = _all_skills_flat()
    skill = next((s for s in flat if s["name"].lower() == name.lower()), None)
    if not skill:
        skill = next((s for s in flat if name.lower() in s["name"].lower()), None)
    if not skill:
        await update.message.reply_text(f"❌ Skill *{name}* not found.", parse_mode="Markdown")
        return

    bonus_lines = "\n".join(f"  ╰➤ {_bonus_label(k,v)}" for k, v in skill["bonus"].items())
    user_id = update.effective_user.id
    owned   = get_player_skills(user_id)
    status  = "✅ *OWNED*" if skill["name"] in owned else f"💠 *{skill['sp_cost']} SP*"

    once_line = "\n🔔 *Once per battle* — fires once then locks until next fight" if skill.get("type") == "once_per_battle" else ""
    backlash = {k: v for k, v in skill["bonus"].items() if isinstance(v, (int,float)) and v < 0}
    backlash_line = ""
    if backlash:
        bl_parts = " | ".join(_bonus_label(k, v) for k, v in backlash.items())
        backlash_line = f"\n⚠️ *Backlash:* {bl_parts}"

    await update.message.reply_text(
        f"{_cat_icon(skill['category'])} *{skill['name']}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ Category: *{skill['category']}*\n"
        f"💠 Cost: *{skill['sp_cost']} SP*  |  {status}"
        f"{once_line}\n\n"
        f"📖 _{skill['description']}_\n\n"
        f"📊 *Bonuses:*\n{bonus_lines}"
        f"{backlash_line}",
        parse_mode="Markdown"
    )


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
    lines = [f"🌳 *MY SKILLS* ({len(owned)} owned)  💠 *{sp} SP*",
             "━━━━━━━━━━━━━━━━━━━━━"]

    for cat, cat_skills in show_cats:
        lines.append(f"\n{_cat_icon(cat)} *{cat}*")
        for s in cat_skills:
            status = "🔴" if s["name"] in deacted else "✅"
            once   = " _(once/battle)_" if s.get("type") == "once_per_battle" else ""
            lines.append(f"  {status} {s['name']}{once}")

    if not show_cats:
        lines.append("\n_No skills in this category._")

    # Bonuses summary (only if showing all or specific category)
    active_names = [s for s in owned if s not in deacted]
    bonuses = get_active_skill_bonuses(active_names)
    if bonuses and cat_filter == "all":
        lines.append("\n━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📊 *Active Bonuses:*")
        for k, v in list(bonuses.items())[:12]:  # show max 12 to avoid overflow
            lines.append(f"  ╰➤ {_bonus_label(k, v)}")
        if len(bonuses) > 12:
            lines.append(f"  ╰➤ _...+{len(bonuses)-12} more_")

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
            "🌳 *Your Skills*\n\n_No skills owned yet._\n\n"
            f"💠 You have *{sp} SP* available.\n"
            "Use `/skilltree` to browse and buy skills.",
            parse_mode="Markdown"
        )
        return

    text, kb = _build_my_skills_page(user_id, "all")
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


async def myskills_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle category tab buttons in My Skills view."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data    = query.data  # myskills_{cat} or myskills_manage

    if data == "myskills_manage":
        # Redirect to deactivate command view
        owned   = get_player_skills(user_id)
        deacted = _get_deactivated(user_id)
        active  = [s for s in owned if s not in deacted]
        inactive = [s for s in owned if s in deacted]
        lines = [
            "⚙️ *SKILL MANAGER*",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"✅ Active: *{len(active)}*  🔴 Deactivated: *{len(inactive)}*\n",
        ]
        if inactive:
            lines.append("*Deactivated:*")
            for s in inactive:
                lines.append(f"  🔴 {s}")
        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "💡 `/deactivate [name]` or `/deactivateall`",
            "💡 `/reactivate [name]` or `/reactivateall`",
        ]
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Back", callback_data="myskills_all")
        ]])
        try:
            await query.edit_message_text("\n".join(lines), parse_mode="Markdown", reply_markup=kb)
        except Exception:
            pass
        return

    cat_filter = data[len("myskills_"):] if data.startswith("myskills_") else "all"
    text, kb   = _build_my_skills_page(user_id, cat_filter)
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass


# ── Legacy aliases ────────────────────────────────────────────────────────
async def skilltree_owned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await skills(update, context)



async def skillinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /skillinfo [name]  — detailed view of any skill
    Shows: SP cost, type, bonuses, backlash, description, category
    """
    user_id = update.effective_user.id

    if not context.args:
        await update.message.reply_text(
            "🔍 *SKILL INFO*\n\n"
            "Usage: `/skillinfo [skill name]`\n\n"
            "Examples:\n"
            "  `/skillinfo iron body`\n"
            "  `/skillinfo berserker`\n"
            "  `/skillinfo crimson reaper`\n\n"
            f"Use `/skilltree` to browse all {TOTAL_SKILL_COUNT} skills.",
            parse_mode='Markdown'
        )
        return

    query_str = ' '.join(context.args).strip().lower()
    flat      = _all_skills_flat()

    # Exact match first, then partial
    match = next((s for s in flat if s['name'].lower() == query_str), None)
    if not match:
        match = next((s for s in flat if query_str in s['name'].lower()), None)
    if not match:
        # Suggest closest
        suggestions = [s['name'] for s in flat if any(w in s['name'].lower() for w in query_str.split())]
        sugg_text = '\n'.join(f"  • {n}" for n in suggestions[:5]) if suggestions else "_No similar skills found._"
        await update.message.reply_text(
            f"❌ Skill *{query_str}* not found.\n\n"
            f"Did you mean:\n{sugg_text}\n\n"
            f"Use `/skilltree` to browse all skills.",
            parse_mode='Markdown'
        )
        return

    skill    = match
    cat_icon = _cat_icon(skill['category'])
    sp       = skill['sp_cost']
    stype    = skill.get('type', 'passive')
    desc     = skill.get('description', '')
    bonus    = skill.get('bonus', {})

    # Separate positive vs negative (backlash) bonuses
    pos_bonuses = {k: v for k, v in bonus.items() if not (isinstance(v, (int,float)) and v < 0)}
    neg_bonuses = {k: v for k, v in bonus.items() if isinstance(v, (int,float)) and v < 0}

    type_label = "⚡ *One-time use per battle*" if stype == 'once_per_battle' else "♾️ *Passive — always active*"

    # Check if player owns it
    owned_skills = get_player_skills(user_id)
    deactivated  = _get_deactivated(user_id)
    owned  = skill['name'] in owned_skills
    active = owned and skill['name'] not in deactivated
    status_line = ""
    if owned:
        status_line = "\n✅ *You own this skill*" + (" _(active)_" if active else " _(deactivated)_")

    lines = [
        f"╔══════════════════════════╗",
        f"   🔍 𝙎𝙆𝙄𝙇𝙇 𝙄𝙉𝙁𝙊",
        f"╚══════════════════════════╝\n",
        f"{cat_icon} *{skill['name']}*",
        f"📂 Category: *{skill['category']}*",
        f"💠 SP Cost: *{sp} SP*",
        f"🔧 Type: {type_label}{status_line}\n",
        f"📖 _{desc}_\n",
        f"━━━━━━━━━━━━━━━━━━━━━",
    ]

    if pos_bonuses:
        lines.append("✅ *Bonuses:*")
        for k, v in pos_bonuses.items():
            lines.append(f"   ╰➤ {_bonus_label(k, v)}")

    if neg_bonuses:
        lines.append("⚠️ *Backlash:*")
        for k, v in neg_bonuses.items():
            lines.append(f"   ╰➤ {_bonus_label(k, v)}")

    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    if not owned:
        lines.append(f"💡 Use `/skillbuy {skill['name']}` to purchase")
    elif not active:
        lines.append(f"💡 Use `/reactivate {skill['name']}` to enable")

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

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
            "⚙️ *SKILL MANAGER*",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"✅ *Active:* {len(active_list)} skills",
            f"🔴 *Deactivated:* {len(inactive_list)} skills",
            "",
        ]
        if active_list:
            lines.append("*Active skills:*")
            for s in active_list[:15]:
                lines.append(f"  ✅ {s}")
        if inactive_list:
            lines.append("\n*Deactivated skills:*")
            for s in inactive_list:
                lines.append(f"  🔴 {s}")

        lines += [
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "💡 `/deactivate [skill name]` — deactivate",
            "💡 `/reactivate [skill name]` — re-enable",
        ]
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    skill_name = ' '.join(context.args).strip()

    # Fuzzy match
    match = next((s for s in owned if s.lower() == skill_name.lower()), None)
    if not match:
        match = next((s for s in owned if skill_name.lower() in s.lower()), None)
    if not match:
        await update.message.reply_text(
            f"❌ *{skill_name}* not found in your skills.\n\n"
            f"Use `/deactivate` to see your full skill list.",
            parse_mode='Markdown'
        )
        return

    if match in deactive:
        await update.message.reply_text(
            f"❌ *{match}* is already deactivated.\n"
            f"Use `/reactivate {match}` to re-enable it.",
            parse_mode='Markdown'
        )
        return

    deactive.append(match)
    _save_deactivated(user_id, deactive)
    await update.message.reply_text(
        f"🔴 *{match}* deactivated.\n\n"
        f"_Its bonuses will no longer apply in battle._\n"
        f"Use `/reactivate {match}` to turn it back on.",
        parse_mode='Markdown'
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
            "💡 Usage: `/reactivate [skill name]`\n\n"
            "Use `/deactivate` to see your deactivated skills.\n"
            "Or: `/reactivateall` to enable everything at once.",
            parse_mode='Markdown'
        )
        return

    skill_name = ' '.join(context.args).strip()
    deactive   = _get_deactivated(user_id)

    match = next((s for s in deactive if s.lower() == skill_name.lower()), None)
    if not match:
        match = next((s for s in deactive if skill_name.lower() in s.lower()), None)
    if not match:
        await update.message.reply_text(
            f"❌ *{skill_name}* is not deactivated.\n\n"
            f"Use `/deactivate` to see your deactivated skills.",
            parse_mode='Markdown'
        )
        return

    deactive.remove(match)
    _save_deactivated(user_id, deactive)
    await update.message.reply_text(
        f"✅ *{match}* reactivated!\n\n"
        f"_Its bonuses will apply in battle again._",
        parse_mode='Markdown'
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
        f"🔴 *All {len(owned)} skills deactivated.*\n\n"
        f"_No skill bonuses will apply in battle._\n"
        f"Use `/reactivateall` to re-enable everything.",
        parse_mode='Markdown'
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
        f"✅ *{count} skill(s) reactivated!*\n\n"
        f"_All your skill bonuses are now active in battle._",
        parse_mode='Markdown'
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
