"""
/know — Full game encyclopedia with category buttons.
Covers: styles, arts, skills, ranks, status effects, shop items,
        upgrades, clan raids, economy, and all commands.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player
from config import (BREATHING_STYLES, DEMON_ARTS, TECHNIQUES, SKILLS,
                    SHOP_ITEMS, SLAYER_RANKS, DEMON_RANKS, STATUS_EFFECTS_DATA)


def _know_pages():
    """Build all encyclopedia pages."""
    pages = {}
    total_skills = sum(len(skills) for skills in SKILLS.values())

    # ── OVERVIEW ──────────────────────────────────────────────────────────
    pages["overview"] = "\n".join([
        "╔══════════════════════════╗",
        "   📖 𝗚𝗔𝗠𝗘 𝗘𝗡𝗖𝗬𝗖𝗟𝗢𝗣𝗘𝗗𝗜𝗔",
        "╚══════════════════════════╝\n",
        "Choose a tab below for detailed info:\n",
        "🗡️ *Styles*   — All breathing styles & forms",
        "👹 *Arts*     — All demon arts & forms",
        f"🌳 *Skills*   — {total_skills} skills overview",
        "🏅 *Ranks*    — Slayer & Demon rank progression",
        "💊 *Status*   — All 24 status effects explained",
        "🏪 *Shop*     — All buyable items with prices & codes",
        "🔨 *Upgrade*  — Craft recipes & stat boosts",
        "⚔️ *Raids*    — Clan raid bosses & rewards",
        "💰 *Economy*  — Yen, SP, bank, market guide",
        "⚙️ *Commands* — Full command list by category",
    ])

    # ── BREATHING STYLES ──────────────────────────────────────────────────
    lines = [f"🗡️ *BREATHING STYLES* — {len(BREATHING_STYLES)} styles\n"]
    for s in BREATHING_STYLES:
        forms     = TECHNIQUES.get(s["name"], [])
        stat_b    = s.get("stat_bonus", {})
        stat_str  = "  ".join(f"+{v} {k.replace('_stat','').upper()}" for k,v in stat_b.items()) if stat_b else ""
        w         = s.get("gacha_weight", 0)
        total_w   = sum(x.get("gacha_weight",0) for x in BREATHING_STYLES)
        chance    = f"{round(w/total_w*100,1)}%" if total_w and w else "UNIQUE"
        lines += [
            f"{s['emoji']} *{s['name']}*  {s['rarity']}",
            f"   📋 {len(forms)} forms  |  🎲 {chance}  |  {stat_str}" if stat_str else f"   📋 {len(forms)} forms  |  🎲 {chance}",
            f"   _{s.get('description','')}_\n",
        ]
    lines.append("💡 `/info [name]` — Full form breakdown")
    pages["styles"] = "\n".join(lines)

    # ── DEMON ARTS ────────────────────────────────────────────────────────
    lines = [f"👹 *DEMON ARTS* — {len(DEMON_ARTS)} arts\n"]
    for a in DEMON_ARTS:
        forms    = TECHNIQUES.get(a["name"], [])
        stat_b   = a.get("stat_bonus", {})
        stat_str = "  ".join(f"+{v} {k.replace('_stat','').upper()}" for k,v in stat_b.items()) if stat_b else ""
        w        = a.get("gacha_weight", 0)
        total_w  = sum(x.get("gacha_weight",0) for x in DEMON_ARTS)
        chance   = f"{round(w/total_w*100,1)}%" if total_w and w else "UNGETTABLE"
        lines += [
            f"{a['emoji']} *{a['name']}*  {a['rarity']}",
            f"   📋 {len(forms)} forms  |  🎲 {chance}  |  {stat_str}" if stat_str else f"   📋 {len(forms)} forms  |  🎲 {chance}",
            f"   _{a.get('description','')}_\n",
        ]
    lines.append("💡 `/info [name]` — Full form breakdown")
    pages["arts"] = "\n".join(lines)

    # ── SKILLS ────────────────────────────────────────────────────────────
    cat_icons = {"Combat":"⚔️","Technique":"🌀","Survival":"🛡️","Elite":"💎",
                 "Demon Path":"👹","Slayer Path":"🗡️","Utility":"💰",
                 "Passive":"✨","Legendary":"🌟","Forbidden":"☠️"}
    lines = [f"🌳 *SKILLS* — {total_skills} total across {len(SKILLS)} categories\n"]
    for cat, skills in SKILLS.items():
        icon   = cat_icons.get(cat, "⭐")
        prices = [s["sp_cost"] for s in skills]
        once   = sum(1 for s in skills if s.get("type") == "once_per_battle")
        lines.append(f"{icon} *{cat}* — {len(skills)} skills  ({min(prices)}–{max(prices)} SP)" +
                     (f"  _[{once} one-time]_" if once else ""))
    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "💡 `/skilltree` — Browse & buy with buttons",
        "💡 `/skillinfo [name]` — Detailed skill info",
        "💡 `/skills` — Your owned skills",
        "💡 `/deactivate [name]` — Turn off a skill",
    ]
    pages["skills"] = "\n".join(lines)

    # ── RANKS ─────────────────────────────────────────────────────────────
    lines = ["🏅 *RANK SYSTEM*\n",
             "Ranks unlock higher technique forms in battle.\n",
             "🗡️ *Slayer Corps Ranks:*\n"]
    for r in SLAYER_RANKS:
        lines.append(f"  {r['kanji']}  {r['name']:22}  {r['xp_needed']:>10,} XP")
    lines += ["\n👹 *Demon Hierarchy:*\n"]
    for r in DEMON_RANKS:
        lines.append(f"  {r['kanji']}  {r['name']:22}  {r['xp_needed']:>10,} XP")
    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        "⚠️ *Higher rank = more forms unlocked in battle*",
        "💡 Earn XP by fighting in /explore",
    ]
    pages["ranks"] = "\n".join(lines)

    # ── STATUS EFFECTS ────────────────────────────────────────────────────
    lines = [f"💊 *STATUS EFFECTS* — {len(STATUS_EFFECTS_DATA)} effects\n",
             "━━━━━━━━━━━━━━━━━━━━━",
             "🔴 *Damage over Time (DoT):*\n"]
    dot_effs = ["🔥 Burn","🧪 Poison","🩸 Bleed","☠️ DeepPoison","🩸 IceBleed","🌡️ Frostburn"]
    for name in dot_effs:
        if name in STATUS_EFFECTS_DATA:
            lines.append(f"  {name}: _{STATUS_EFFECTS_DATA[name]['desc']}_")
    lines += ["", "⚡ *Control (CC):*\n"]
    cc_effs = ["⚡ Stun","❄️ Freeze","❄️ DeepFreeze","🌀 Confusion","🔒 Stagger","🙈 Blind"]
    for name in cc_effs:
        if name in STATUS_EFFECTS_DATA:
            lines.append(f"  {name}: _{STATUS_EFFECTS_DATA[name]['desc']}_")
    lines += ["", "📉 *Debuffs:*\n"]
    debuff_effs = ["💀 Curse","😰 Vulnerable","🧊 Shattered","🪞 IceCounter"]
    for name in debuff_effs:
        if name in STATUS_EFFECTS_DATA:
            lines.append(f"  {name}: _{STATUS_EFFECTS_DATA[name]['desc']}_")
    lines += ["", "📈 *Buffs (player-side):*\n"]
    buff_effs = ["💧 Flow","🛡️ WaterShield","🩹 Cleanse","⚡ Overcharge","🌀 Phantomstep",
                 "🧱 Fortress","☠️ Deathmark"]
    for name in buff_effs:
        if name in STATUS_EFFECTS_DATA:
            lines.append(f"  {name}: _{STATUS_EFFECTS_DATA[name]['desc']}_")
    pages["status"] = "\n".join(lines)

    # ── SHOP ITEMS ────────────────────────────────────────────────────────
    lines = ["🏪 *SHOP ITEMS*\n",
             "Buy with: `/buy [code]` or `/buy [name]`\n",
             "━━━━━━━━━━━━━━━━━━━━━"]
    cat_label = {"swords":"⚔️ Swords","armor":"🛡️ Armor","items":"🧪 Consumables",
                 "potions":"🔮 Potions","upgrades":"⬆️ Upgrades","scrolls":"📜 Scrolls",
                 "materials":"📦 Materials"}
    for cat, items in SHOP_ITEMS.items():
        if not items: continue
        label = cat_label.get(cat, f"📦 {cat.title()}")
        lines += ["", f"*{label}:*"]
        for item in items:
            code   = item.get("code", item["name"].lower().replace(" ",""))
            bonus  = ""
            if item.get("atk_bonus"): bonus = f" _(+{item['atk_bonus']} ATK)_"
            if item.get("def_bonus"): bonus = f" _(+{item['def_bonus']} DEF)_"
            if item.get("effect"):    bonus = f" _({item['effect'].replace('_',' ')})_"
            lines.append(f"  {item.get('emoji','📦')} *{item['name']}* `[{code}]` — *{item['price']:,}¥*{bonus}")
    pages["shop"] = "\n".join(lines)

    # ── UPGRADE ───────────────────────────────────────────────────────────
    try:
        from handlers.upgrade import UPGRADE_RECIPES, STAT_BOOSTS
        lines = ["🔨 *UPGRADE RECIPES*\n",
                 "Craft better gear: `/upgrade`\n",
                 "Each upgrade permanently boosts your stats.\n",
                 "━━━━━━━━━━━━━━━━━━━━━"]
        for name, recipe in UPGRADE_RECIPES.items():
            mats = ", ".join(f"{q}× {m}" for m,q in recipe["materials"].items())
            boost_map = STAT_BOOSTS.get(name, {})
            boost = ", ".join(
                f"+{value} {'STR' if stat == 'str_stat' else 'DEF' if stat == 'def_stat' else 'Max HP' if stat == 'max_hp' else stat}"
                for stat, value in boost_map.items()
            )
            lines += [
                f"",
                f"{recipe.get('emoji','🔨')} *{name}*",
                f"   💸 {recipe['cost_yen']:,}¥  |  Replaces: _{recipe.get('replaces','?')}_",
                f"   🔧 Materials: {mats}",
                f"   ⬆️ Stat boost: _{boost}_" if boost else "",
            ]
        lines = [l for l in lines if l is not None and l != ""]
    except Exception as e:
        lines = [f"🔨 *UPGRADES*\n\nUse `/upgrade` to see available recipes.\n(Data load error: {e})"]
    pages["upgrade"] = "\n".join(lines)

    # ── CLAN RAIDS ────────────────────────────────────────────────────────
    try:
        from handlers.clan_raid import RAID_BOSSES, RAID_JOIN_FEE, RAID_COOLDOWN_DAYS
        lines = ["⚔️ *CLAN RAID SYSTEM*\n",
                 f"💸 Join fee: *{RAID_JOIN_FEE:,}¥*",
                 f"⏳ Cooldown: *{RAID_COOLDOWN_DAYS} days* between raids",
                 "⚔️ *One player attacks at a time* (turn-based)\n",
                 "━━━━━━━━━━━━━━━━━━━━━",
                 "*Available Bosses:*\n"]
        for name, b in RAID_BOSSES.items():
            lines += [
                f"{b['emoji']} *{name}*",
                f"   ❤️ HP: {b['hp']:,}  |  ⚔️ ATK: ~{b['atk']}",
                f"   🎁 Reward mult: ×{b['reward_mult']}",
                "",
            ]
        lines += [
            "━━━━━━━━━━━━━━━━━━━━━",
            "*Raid Commands:*",
            "  `/clanraid bosses` — List all bosses",
            "  `/clanraid start [boss]` — Start raid (leader/chief)",
            "  `/clanraid join` — Join active raid",
            "  `/clanraid attack` — Attack boss (your turn)",
            "  `/clanraid status` — HP + damage board",
            "  `/clanraid end` — End & distribute rewards",
        ]
    except Exception as e:
        lines = [f"⚔️ *CLAN RAIDS*\n\nUse `/clanraid bosses` to see available bosses.\n(Error: {e})"]
    pages["raids"] = "\n".join(lines)

    # ── ECONOMY ───────────────────────────────────────────────────────────
    pages["economy"] = "\n".join([
        "💰 *ECONOMY GUIDE*\n",
        "━━━━━━━━━━━━━━━━━━━━━",
        "💴 *YEN* — Main currency\n",
        "  Sources: /explore battles, /daily, /market sales,",
        "  /give from other players, /clanraid rewards\n",
        "  Spend on: /shop, /upgrade, /auction, /lottery,",
        "  /clanraid join fee (500¥)\n",
        "━━━━━━━━━━━━━━━━━━━━━",
        "💠 *SKILL POINTS (SP)* — From PvP wins\n",
        "  Earn: Win /challenge duels (+1–5 SP per win)",
        "  Spend: /skillbuy to unlock skills from /skilltree",
        "  _New players start with 10 SP_\n",
        "━━━━━━━━━━━━━━━━━━━━━",
        "🏦 *BANK*\n",
        "  `/bank` — View balance & tier",
        "  `/deposit [amount]` — Store Yen safely",
        "  `/withdraw [amount]` — Take Yen out",
        "  `/bankupgrade` — Upgrade bank capacity\n",
        "━━━━━━━━━━━━━━━━━━━━━",
        "🏪 *PLAYER MARKET*\n",
        "  `/market` — Browse all listings",
        "  `/list [item] [price]` — Sell your item (5% fee)",
        "  `/buy market [item] [qty]` — Buy from market",
        "  `/unlist [item]` — Remove your listing\n",
        "━━━━━━━━━━━━━━━━━━━━━",
        "🌑 *BLACK MARKET* (10pm–6am UTC)\n",
        "  `/blackmarket` — Browse rare items",
        "  `/bmbuy [id or name]` — Buy",
        "  _Limited stock, auto-clears at dawn_\n",
        "━━━━━━━━━━━━━━━━━━━━━",
        "📦 *ITEMS FROM BATTLES*\n",
        "  Materials: Demon Blood, Spider Silk, Boss Shard...",
        "  Use in /upgrade recipes to craft better gear",
        "  Sell on /market or deposit in /clandeposit",
    ])

    # ── COMMANDS ──────────────────────────────────────────────────────────
    pages["commands"] = "\n".join([
        "⚙️ *ALL COMMANDS*\n",
        "🗡️ *Battle:*",
        "  /explore   /challenge   /party   /joinraid   /raidattack\n",
        "🧬 *Character:*",
        "  /profile   /breathing   /art   /info [name]",
        "  /skilltree   /skills   /skillbuy   /skillinfo\n",
        "🏯 *Clan:*",
        "  /clan   /claninfo   /clanraid   /clanrole",
        "  /clanslogan   /clanimage   /clanreq   /clandeposit\n",
        "🏪 *Economy:*",
        "  /shop   /buy   /sell   /inventory   /market",
        "  /give   /gift   /bank   /upgrade   /blackmarket\n",
        "📖 *Info:*",
        "  /help   /know   /guide   /info [style]   /skillinfo [name]\n",
        "⚙️ *Settings:*",
        "  /deactivate   /reactivate   /deactivateall   /reactivateall\n",
        "💡 Use /help with buttons for full detailed guide",
        "💡 Use /info [style name] for technique details",
    ])

    return pages


def _know_keyboard(current="overview"):
    cats = [
        ("📖 Overview", "overview"), ("🗡️ Styles",   "styles"),
        ("👹 Arts",     "arts"),     ("🌳 Skills",   "skills"),
        ("🏅 Ranks",    "ranks"),    ("💊 Status",   "status"),
        ("🏪 Shop",     "shop"),     ("🔨 Upgrade",  "upgrade"),
        ("⚔️ Raids",    "raids"),    ("💰 Economy",  "economy"),
        ("⚙️ Commands", "commands"),
    ]
    buttons = []
    row = []
    for label, key in cats:
        marker = "·" if key == current else ""
        row.append(InlineKeyboardButton(f"{marker}{label}", callback_data=f"know_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


async def know(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/know — Full game encyclopedia with category buttons."""
    try:
        pages  = _know_pages()
        text   = pages["overview"]
        msg    = update.message or (update.callback_query.message if update.callback_query else None)
        if not msg:
            return
        await msg.reply_text(text, parse_mode="Markdown", reply_markup=_know_keyboard("overview"))
    except Exception as e:
        msg = update.message or (update.callback_query.message if update.callback_query else None)
        if msg:
            await msg.reply_text(f"❌ Error loading encyclopedia: {e}")


async def know_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /know category button presses."""
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("know_"):
        return
    key   = query.data[len("know_"):]
    try:
        pages = _know_pages()
    except Exception as e:
        await query.answer(f"Error: {e}", show_alert=True)
        return
    if key not in pages:
        await query.answer("❓ Unknown section.", show_alert=True)
        return
    text = pages[key]
    if len(text) > 4000:
        text = text[:3900] + "\n\n_...use `/info [name]` for full details_"
    try:
        await query.edit_message_text(
            text, parse_mode="Markdown", reply_markup=_know_keyboard(key)
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            try:
                await query.message.reply_text(
                    text, parse_mode="Markdown", reply_markup=_know_keyboard(key)
                )
            except Exception:
                pass
