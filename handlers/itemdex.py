"""
/itemdex — Item Encyclopedia (Dex)
Browse ALL items in the game: shop items, drop items, arts/styles, pets, black market.
Usage:
  /itemdex               — show category menu
  /itemdex swords        — show sword items
  /itemdex items         — show consumable items
  /itemdex armor         — show armor items
  /itemdex pet_items     — show pet-related shop items
  /itemdex drops         — show enemy drop items
  /itemdex breathing     — show all breathing styles
  /itemdex demon_arts    — show all demon arts
  /itemdex pets          — show all capturable pets
  /itemdex blackmarket   — show black market stock
  /itemdex <search>      — search by name across all categories
"""
import logging
log = logging.getLogger(__name__)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut

from config import SHOP_ITEMS, BREATHING_STYLES, DEMON_ARTS, PETS, SLAYER_ENEMIES, DEMON_ENEMIES, REGION_ENEMIES
from utils.database import col

# ── Rarity sort order ─────────────────────────────────────────────────────
RARITY_ORDER = {
    "COMMON": 1, "⭐⭐ COMMON": 1,
    "UNCOMMON": 2,
    "RARE": 3, "⭐⭐⭐ RARE": 3,
    "EPIC": 4, "⭐⭐⭐⭐ EPIC": 4,
    "LEGENDARY": 5, "⭐⭐⭐⭐⭐ LEGENDARY": 5,
    "ULTRA LEGENDARY": 6, "🌑 ULTRA LEGENDARY": 6,
}

def _rarity_sort(r):
    r_upper = str(r).upper()
    for key, val in RARITY_ORDER.items():
        if key in r_upper:
            return val
    return 0


def _format_passive(passive: dict) -> str:
    parts = []
    mapping = {
        "xp_pct":   lambda v: f"+{int(v*100)}% XP",
        "yen_pct":  lambda v: f"+{int(v*100)}% Yen",
        "atk_pct":  lambda v: f"+{int(v*100)}% ATK",
        "def_pct":  lambda v: f"+{int(v*100)}% DEF",
        "drop_pct": lambda v: f"+{int(v*100)}% Drops",
        "dodge_pct":lambda v: f"+{int(v*100)}% Dodge",
        "str_stat": lambda v: f"+{v} STR",
        "def_stat": lambda v: f"+{v} DEF",
        "spd":      lambda v: f"+{v} SPD",
        "max_hp":   lambda v: f"+{v} MaxHP",
        "max_sta":  lambda v: f"+{v} MaxSTA",
    }
    for k, v in (passive or {}).items():
        if k in mapping:
            parts.append(mapping[k](v))
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts) if parts else "—"


# ── Category builders ─────────────────────────────────────────────────────

def _build_shop_category(category: str) -> list[dict]:
    """Return formatted lines for a SHOP_ITEMS category."""
    items = SHOP_ITEMS.get(category, [])
    result = []
    for item in items:
        line = f"{item.get('emoji','📦')} *{item['name']}*\n"
        if "price" in item:
            line += f"  💰 Price: *{item['price']:,}¥*\n"
        if "atk_bonus" in item:
            line += f"  ⚔️ ATK Bonus: *+{item['atk_bonus']}*\n"
        if "def_bonus" in item:
            line += f"  🛡️ DEF Bonus: *+{item['def_bonus']}*\n"
        if "effect" in item:
            effect_map = {
                "cure_poison": "Cures poison status",
                "restore_sta_50": "Restores 50 STA",
                "restore_hp_full": "Fully restores HP",
            }
            line += f"  ✨ Effect: _{effect_map.get(item['effect'], item['effect'])}_\n"
        if "catch_bonus" in item:
            pct = int(item["catch_bonus"] * 100)
            line += f"  🎯 Catch Bonus: *+{pct}%*\n"
        if "desc" in item:
            line += f"  _{item['desc']}_\n"
        result.append(line.strip())
    return result


def _build_breathing_styles() -> list[str]:
    lines = []
    for s in sorted(BREATHING_STYLES, key=lambda x: _rarity_sort(x.get("rarity", ""))):
        stat_bonus = s.get("stat_bonus", {})
        bonus_str = ""
        if stat_bonus:
            parts = []
            for k, v in stat_bonus.items():
                lbl = {"str_stat": "STR", "spd": "SPD", "def_stat": "DEF",
                       "max_hp": "MaxHP", "max_sta": "MaxSTA"}.get(k, k)
                parts.append(f"+{v} {lbl}")
            bonus_str = f"\n  ⭐ Stat Bonus: *{', '.join(parts)}*"
        line = (
            f"{s.get('emoji','💧')} *{s['name']}*\n"
            f"  {s.get('rarity','')}{bonus_str}\n"
            f"  _{s.get('description','')}_"
        )
        lines.append(line)
    return lines


def _build_demon_arts() -> list[str]:
    lines = []
    for a in sorted(DEMON_ARTS, key=lambda x: _rarity_sort(x.get("rarity", ""))):
        stat_bonus = a.get("stat_bonus", {})
        bonus_str = ""
        if stat_bonus:
            parts = []
            for k, v in stat_bonus.items():
                lbl = {"str_stat": "STR", "spd": "SPD", "def_stat": "DEF",
                       "max_hp": "MaxHP", "max_sta": "MaxSTA"}.get(k, k)
                parts.append(f"+{v} {lbl}")
            bonus_str = f"\n  ⭐ Stat Bonus: *{', '.join(parts)}*"
        line = (
            f"{a.get('emoji','🩸')} *{a['name']}*\n"
            f"  {a.get('rarity','')}{bonus_str}\n"
            f"  _{a.get('description','')}_"
        )
        lines.append(line)
    return lines


def _build_pets() -> list[str]:
    lines = []
    rarity_order = ["common", "uncommon", "rare", "epic", "legendary"]
    for name, p in sorted(PETS.items(), key=lambda x: rarity_order.index(x[1].get("rarity","common")) if x[1].get("rarity","common") in rarity_order else 99):
        passive_str = _format_passive(p.get("passive"))
        skill_str = ""
        if p.get("skill"):
            skill_str = f"\n  💥 Skill: *{p['skill']}* — _{p.get('skill_desc','')}_"
        evo = p.get("evolution")
        evo_str = f"\n  🔄 Evolves into: *{evo}*" if evo else ""
        line = (
            f"{p.get('emoji','🐾')} *{name}*  _{p.get('rarity','').title()}_\n"
            f"  🏴 Faction: *{p.get('faction','neutral').title()}*\n"
            f"  🎯 Catch Rate: *{int(p.get('catch_rate',0)*100)}%*\n"
            f"  🌟 Passive: *{passive_str}*"
            f"{skill_str}{evo_str}\n"
            f"  _{p.get('desc','')}_"
        )
        lines.append(line)
    return lines


def _build_drops() -> list[str]:
    """Collect all enemy drops from all enemy lists."""
    seen = {}  # drop_name -> list of enemy names
    all_enemies = list(SLAYER_ENEMIES) + list(DEMON_ENEMIES)
    # Add region enemies
    for region_data in REGION_ENEMIES.values() if isinstance(REGION_ENEMIES, dict) else []:
        all_enemies.extend(region_data.get("enemies", []))

    for enemy in all_enemies:
        for drop in enemy.get("drops", []):
            if drop not in seen:
                seen[drop] = []
            seen[drop].append(enemy.get("name", "?"))

    lines = []
    for drop_name, enemy_names in sorted(seen.items()):
        unique_enemies = list(dict.fromkeys(enemy_names))[:3]
        src = ", ".join(unique_enemies)
        lines.append(
            f"💎 *{drop_name}*\n"
            f"  _Dropped by: {src}_"
        )
    return lines if lines else ["_No drop data found._"]


def _build_blackmarket() -> list[str]:
    """Pull current black market stock from DB."""
    try:
        items = list(col("black_market").find({
            "status": "active",
            "item_name": {"$ne": "__OPEN__"},
            "stock": {"$gt": 0}
        }))
        if not items:
            return ["_The Black Market has no stock right now._\n_(Market opens 10pm–6am UTC)_"]
        lines = []
        for i, item in enumerate(items, 1):
            line = (
                f"🌑 *{item.get('item_name','?')}*\n"
                f"  💰 Price: *{item.get('price', 0):,}¥*\n"
                f"  📦 Stock: *{item.get('stock','?')}*\n"
                f"  _{item.get('description', item.get('desc',''))}_"
            )
            lines.append(line.strip())
        return lines
    except Exception as e:
        log.error("[itemdex blackmarket] %s", e)
        return ["_Could not fetch Black Market data._"]


# ── Category registry ─────────────────────────────────────────────────────

CATEGORIES = {
    "swords":      ("⚔️ Swords",          lambda: _build_shop_category("swords")),
    "items":       ("🧪 Consumables",      lambda: _build_shop_category("items")),
    "armor":       ("🥋 Armor",            lambda: _build_shop_category("armor")),
    "pet_items":   ("🐾 Pet Items",        lambda: _build_shop_category("pet_items")),
    "breathing":   ("💧 Breathing Styles", _build_breathing_styles),
    "demon_arts":  ("🩸 Demon Arts",       _build_demon_arts),
    "pets":        ("🐾 Pets (Catchable)",  _build_pets),
    "drops":       ("⚔️ Enemy Drops",      _build_drops),
    "blackmarket": ("🌑 Black Market",     _build_blackmarket),
}

CATEGORY_MENU = (
    "🗂 *ITEM DEX — All Game Items*\n"
    "━━━━━━━━━━━━━━━━━━━━━\n\n"
    "📦 *Shop Items:*\n"
    "  `/itemdex swords` — ⚔️ Swords / Nichirin Blades\n"
    "  `/itemdex items` — 🧪 Consumables (Potions, Pills)\n"
    "  `/itemdex armor` — 🥋 Armor / Haori\n"
    "  `/itemdex pet_items` — 🐾 Pet Traps, Eggs, Food\n\n"
    "🎴 *Combat Arts:*\n"
    "  `/itemdex breathing` — 💧 All Breathing Styles\n"
    "  `/itemdex demon_arts` — 🩸 All Demon Arts\n\n"
    "🐾 *Pets:*\n"
    "  `/itemdex pets` — All catchable pets & passives\n\n"
    "⚔️ *Drops & Market:*\n"
    "  `/itemdex drops` — Enemy drop items\n"
    "  `/itemdex blackmarket` — 🌑 Black Market stock\n\n"
    "🔍 *Search:*\n"
    "  `/itemdex <name>` — Search across all categories"
)


def _paginate(lines: list[str], page: int, per_page: int = 5) -> tuple[list[str], int, int]:
    """Return (page_lines, current_page, total_pages)."""
    total = max(1, (len(lines) + per_page - 1) // per_page)
    page  = max(1, min(page, total))
    start = (page - 1) * per_page
    return lines[start:start+per_page], page, total


def _search_all(query: str) -> list[str]:
    """Search all categories for items matching query."""
    q = query.lower()
    results = []
    for cat_key, (cat_label, builder) in CATEGORIES.items():
        try:
            lines = builder()
            for line in lines:
                if q in line.lower():
                    results.append(f"[{cat_label}]\n{line}")
        except Exception as e:
            log.error("[itemdex search %s] %s", cat_key, e)
    return results


# ── Command handler ───────────────────────────────────────────────────────

async def itemdex(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/itemdex [category|search]"""
    args = context.args or []

    # No args → show category menu
    if not args:
        await update.message.reply_text(CATEGORY_MENU, parse_mode="Markdown")
        return

    query = " ".join(args).lower().strip()

    # Check if it matches a known category key
    cat_key = query.replace(" ", "_")
    if cat_key in CATEGORIES:
        cat_label, builder = CATEGORIES[cat_key]
        lines = builder()
        if not lines:
            await update.message.reply_text(f"_{cat_label} has no items._", parse_mode="Markdown")
            return

        page_lines, page, total = _paginate(lines, 1)
        header = (
            f"📖 *{cat_label}*  (Page {page}/{total})\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        )
        body = "\n\n".join(page_lines)

        footer = ""
        if total > 1:
            footer = f"\n\n_Use `/itemdex {cat_key} 2` for next page_"

        text = header + body + footer

        # Telegram 4096 char limit guard
        if len(text) > 4000:
            text = text[:3990] + "\n…_(truncated — use page numbers)_"

        await update.message.reply_text(text, parse_mode="Markdown")
        return

    # Check category + page number: /itemdex swords 2
    parts = query.split()
    if len(parts) == 2 and parts[1].isdigit():
        cat_key2 = parts[0].replace(" ", "_")
        if cat_key2 in CATEGORIES:
            cat_label, builder = CATEGORIES[cat_key2]
            lines = builder()
            page_lines, page, total = _paginate(lines, int(parts[1]))
            header = (
                f"📖 *{cat_label}*  (Page {page}/{total})\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            )
            body = "\n\n".join(page_lines)
            footer = ""
            if page < total:
                footer = f"\n\n_`/itemdex {cat_key2} {page+1}` for next page_"
            text = header + body + footer
            if len(text) > 4000:
                text = text[:3990] + "\n…_(truncated)_"
            await update.message.reply_text(text, parse_mode="Markdown")
            return

    # Free-text search
    results = _search_all(query)
    if not results:
        await update.message.reply_text(
            f"🔍 No items found matching *{query}*.\n\n"
            f"Use `/itemdex` to see all categories.",
            parse_mode="Markdown"
        )
        return

    page_lines, page, total = _paginate(results, 1, per_page=4)
    header = (
        f"🔍 *Search: \"{query}\"*  ({len(results)} results, Page {page}/{total})\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
    )
    body = "\n\n".join(page_lines)
    text = header + body
    if len(text) > 4000:
        text = text[:3990] + "\n…_(truncated)_"
    await update.message.reply_text(text, parse_mode="Markdown")
