import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import get_inventory, remove_item, update_player, get_player, col, add_item

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# FORGE RECIPES
# Each entry can produce:
#   - stat boosts:  str, spd, def, hp, max_sta
#   - equip items:  equip_sword / equip_armor  (sets the equipped slot)
#   - grant items:  grant_item / grant_item_type  (gives an item to inventory)
# ─────────────────────────────────────────────────────────────────────────────
FORGE_ITEMS = [

    # ── SWORDS (stat boost path) ──────────────────────────────────────────
    {
        "id":   "crimson_blade",
        "name": "Crimson Nichirin Blade",
        "category": "⚔️ Swords",
        "cost": 500,
        "str":  8,
        "requirements": {
            "Basic Nichirin Blade": 1,
            "Demon Blood":          3,
            "Wolf Fang":            2,
        },
    },
    {
        "id":   "jet_black_blade",
        "name": "Jet Black Nichirin Blade",
        "category": "⚔️ Swords",
        "cost": 2000,
        "str":  18,
        "requirements": {
            "Crimson Nichirin Blade": 1,
            "Blood Crystal":          2,
            "Boss Shard":             1,
            "Demon Blood":            5,
        },
    },
    {
        "id":   "scarlet_blade",
        "name": "Scarlet Crimson Blade",
        "category": "⚔️ Swords",
        "cost": 8000,
        "str":  30,
        "requirements": {
            "Jet Black Nichirin Blade": 1,
            "Blood Crystal":            4,
            "Boss Shard":               2,
            "Hashira Badge":            1,
            "Ancient Whetstone":        2,
        },
    },
    {
        "id":   "transparent_blade",
        "name": "Transparent Nichirin Blade",
        "category": "⚔️ Swords",
        "cost": 20000,
        "str":  50,
        "requirements": {
            "Scarlet Crimson Blade": 1,
            "Rare Ore Fragment":     3,
            "Boss Shard":            3,
            "Titan Core":            1,
            "Ancient Whetstone":     3,
        },
    },
    {
        "id":   "sun_blade",
        "name": "Sun Nichirin Blade",
        "category": "⚔️ Swords",
        "cost": 60000,
        "str":  80,
        "requirements": {
            "Transparent Nichirin Blade": 1,
            "Sun Breathing Tome":          1,
            "Boss Shard":                  5,
            "King Blade":                  1,
            "Rengoku Shard":               3,
        },
    },

    # ── ARMOR (stat boost path) ──────────────────────────────────────────
    {
        "id":   "reinforced_haori",
        "name": "Reinforced Haori",
        "category": "🛡️ Armor",
        "cost": 400,
        "def":  5,
        "hp":   20,
        "requirements": {
            "Corps Uniform": 1,
            "Spider Silk":   2,
            "Demon Blood":   3,
        },
    },
    {
        "id":   "hashira_haori",
        "name": "Hashira Haori",
        "category": "🛡️ Armor",
        "cost": 1500,
        "def":  12,
        "hp":   40,
        "requirements": {
            "Reinforced Haori": 1,
            "Boss Shard":       2,
            "Spider Silk":      4,
            "Blood Crystal":    2,
        },
    },

    # ── DEMON RELICS (new boss-drop crafts) ───────────────────────────────
    {
        "id":   "akaza_gauntlet",
        "name": "Akaza's Martial Gauntlet",
        "category": "👊 Demon Relics",
        "cost": 15000,
        "str":  22,
        "spd":  8,
        "lore": "Forged from Akaza's fallen fist — radiates overwhelming martial force.",
        "requirements": {
            "Akaza Fist":   3,
            "Boss Shard":   2,
            "Upper Moon Core": 1,
            "Blood Crystal":   2,
        },
    },
    {
        "id":   "ice_lotus_crown",
        "name": "Ice Lotus Haori",
        "category": "🛡️ Armor",
        "cost": 18000,
        "def":  25,
        "hp":   80,
        "spd":  5,
        "lore": "Woven from Doma's ice lotus — chillingly beautiful and lethal.",
        "requirements": {
            "Ice Lotus":    2,
            "Doma Shard":   1,
            "Spider Silk":  4,
            "Boss Shard":   2,
        },
    },
    {
        "id":   "muzan_blade",
        "name": "Muzan's Crimson Fang",
        "category": "⚔️ Swords",
        "cost": 120000,
        "str":  110,
        "spd":  12,
        "lore": "A blade reforged with Muzan's ancient blood. Only the strongest may wield it.",
        "requirements": {
            "Muzan Blood":       2,
            "Demon King Core":   1,
            "Sun Nichirin Blade": 1,
            "Boss Shard":         5,
        },
    },
    {
        "id":   "void_cloak",
        "name": "Void Tyrant's Cloak",
        "category": "🛡️ Armor",
        "cost": 45000,
        "def":  40,
        "hp":   120,
        "lore": "Shadowed armor torn from the Void Tyrant. Absorbs damage like a black hole.",
        "requirements": {
            "Void Core":   2,
            "Boss Shard":  3,
            "Upper Moon Core": 1,
            "Blood Crystal":   3,
        },
    },
    {
        "id":   "kokushibo_blade",
        "name": "Moon-Breathing Cursed Blade",
        "category": "⚔️ Swords",
        "cost": 200000,
        "str":  140,
        "spd":  18,
        "def":  10,
        "lore": "Kokushibo's demonic blade — imbued with Moon Breathing. The ultimate demon sword.",
        "requirements": {
            "Kokushibo Shard":     2,
            "Moon Blade Shard":    2,
            "Moon Breathing Scroll": 1,
            "Upper Moon Core":       2,
            "Boss Shard":            5,
        },
    },
    {
        "id":   "rui_silk_haori",
        "name": "Rui's Spider-Thread Haori",
        "category": "🛡️ Armor",
        "cost": 25000,
        "def":  30,
        "hp":   70,
        "spd":  6,
        "lore": "Woven from unbreakable spider threads by Rui himself — nearly impenetrable.",
        "requirements": {
            "Rui Thread":    3,
            "Spider Silk":   5,
            "Kizuki Blood":  2,
            "Boss Shard":    2,
        },
    },
    {
        "id":   "biwa_resonance_ring",
        "name": "Nakime's Resonance Talisman",
        "category": "🔮 Special",
        "cost": 22000,
        "spd":  15,
        "hp":   50,
        "max_sta": 30,
        "lore": "Nakime's biwa shard hums with dimensional power — sharpens instincts and stamina.",
        "requirements": {
            "Biwa Shard":  2,
            "Boss Shard":  2,
            "Phantom Core": 1,
            "Blood Crystal": 2,
        },
    },
    {
        "id":   "upper_moon_core_armor",
        "name": "Upper Moon Shell",
        "category": "🛡️ Armor",
        "cost": 35000,
        "def":  35,
        "hp":   100,
        "lore": "Crystallized armor shell made from Upper Moon remnants — near-indestructible.",
        "requirements": {
            "Upper Moon Core": 3,
            "Boss Shard":      3,
            "Blood Crystal":   3,
            "Titan Core":      1,
        },
    },
    {
        "id":   "demon_heart_blade",
        "name": "Demon Heart Blade",
        "category": "⚔️ Swords",
        "cost": 50000,
        "str":  65,
        "spd":  10,
        "lore": "A blade pulsing with a demon's stolen heart — drains the enemy's will to fight.",
        "requirements": {
            "Demon Heart":    2,
            "Boss Shard":     3,
            "Upper Moon Shard": 2,
            "Blood Crystal":    3,
        },
    },
    {
        "id":   "sun_blade_fragment_ultimate",
        "name": "Fragment of the First Breath",
        "category": "🌟 Legendary",
        "cost": 300000,
        "str":  180,
        "spd":  25,
        "def":  20,
        "hp":   200,
        "lore": "A relic forged from Yoriichi's blade fragment and the Breath of the Sun itself. The pinnacle of all craftsmanship.",
        "requirements": {
            "Sun Blade Fragment":       2,
            "Breath of the Sun Scroll": 1,
            "Muzan Blood":              1,
            "Kokushibo Shard":          1,
            "Boss Shard":               5,
        },
    },

    # ── ACCESSORY / SPECIAL CRAFTS ─────────────────────────────────────────
    {
        "id":   "moon3_shard_gauntlet",
        "name": "Upper Moon III Power Crest",
        "category": "🔮 Special",
        "cost": 30000,
        "str":  40,
        "def":  12,
        "max_sta": 40,
        "lore": "Infused with Upper Moon 3's raw power — permanently tempers the body.",
        "requirements": {
            "Moon 3 Shard":    2,
            "Boss Shard":      3,
            "Upper Moon Core": 1,
            "Blood Crystal":   2,
        },
    },
    {
        "id":   "doma_shard_fist",
        "name": "Doma's Soul Cracker",
        "category": "👊 Demon Relics",
        "cost": 40000,
        "str":  50,
        "spd":  12,
        "lore": "Fragments of Doma's crystallized aura — strikes that shatter the soul itself.",
        "requirements": {
            "Doma Shard":    2,
            "Ice Lotus":     1,
            "Boss Shard":    3,
            "Upper Moon Core": 1,
        },
    },
]

# Category display order
CATEGORY_ORDER = ["⚔️ Swords", "🛡️ Armor", "👊 Demon Relics", "🔮 Special", "🌟 Legendary"]


def _get_user_inventory_map(user_id: int) -> dict:
    """Return a dict of item_name.lower() -> quantity for the user."""
    try:
        inv = get_inventory(user_id)
        return {item["item_name"].lower(): item.get("quantity", 0) for item in inv}
    except Exception as e:
        log.error("[FORGE] Failed to get inventory: %s", e)
        return {}


def _build_forge_keyboard(category_filter: str = None):
    """Create keyboard grouped by category, with category tabs on top."""
    # Category filter buttons
    cat_buttons = []
    for cat in CATEGORY_ORDER:
        items_in_cat = [i for i in FORGE_ITEMS if i.get("category") == cat]
        if not items_in_cat:
            continue
        safe = cat.replace(" ", "_").replace("/", "_")
        label = cat if cat != category_filter else f"[{cat}]"
        cat_buttons.append(InlineKeyboardButton(label, callback_data=f"forge_cat_{safe}"))

    # Item buttons (filtered or all) - show ALL items clearly
    visible = FORGE_ITEMS
    if category_filter:
        visible = [i for i in FORGE_ITEMS if i.get("category") == category_filter]

    item_buttons = []
    for item in visible:
        try:
            idx = FORGE_ITEMS.index(item)
            # Show item name with stats preview
            stat_preview = ""
            if "str" in item:
                stat_preview = f" ⚔️+{item['str']}"
            elif "def" in item:
                stat_preview = f" 🛡️+{item['def']}"
            item_buttons.append([InlineKeyboardButton(
                f"{item['name']}{stat_preview}", callback_data=f"forge_{idx}"
            )])
        except ValueError:
            continue

    rows = []
    # Show category tabs in rows of 3
    for i in range(0, len(cat_buttons), 3):
        rows.append(cat_buttons[i:i+3])
    rows.extend(item_buttons)
    rows.append([InlineKeyboardButton("❌ Close", callback_data="forge_close")])
    return InlineKeyboardMarkup(rows)


def _can_afford(player: dict, cost: int) -> bool:
    return player.get("yen", 0) >= cost


def _check_requirements(inv_map: dict, requirements: dict) -> dict:
    """Return dict of req_name -> (have, need, met)."""
    result = {}
    for req, needed in requirements.items():
        have = inv_map.get(req.lower(), 0)
        result[req] = (have, needed, have >= needed)
    return result


async def forge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/forge – Show the upgrade UI with all items as buttons."""
    try:
        await update.effective_message.reply_text(
            "⚒️ *UPGRADE FORGE*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "Craft powerful gear from rare battle drops!\n"
            "Select a *category* then choose what to forge.",
            parse_mode="Markdown",
            reply_markup=_build_forge_keyboard(),
        )
    except Exception as e:
        log.error("[FORGE] Failed to send forge UI: %s", e)


async def forge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses from the forge UI."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "forge_close":
        try:
            await query.message.delete()
        except Exception:
            await query.edit_message_text("Forge closed.")
        return

    if data.startswith("forge_cat_"):
        cat_safe = data[len("forge_cat_"):]
        # Reverse map safe name to display name
        cat_display = next(
            (c for c in CATEGORY_ORDER if c.replace(" ", "_").replace("/", "_") == cat_safe),
            None
        )
        await query.edit_message_text(
            "⚒️ *UPGRADE FORGE*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"Browsing: *{cat_display}*\n"
            "Select an item to see requirements.",
            parse_mode="Markdown",
            reply_markup=_build_forge_keyboard(category_filter=cat_display),
        )
        return

    if data.startswith("forge_confirm_"):
        await _handle_forge_confirm(query)
        return

    if data == "forge_back":
        await query.edit_message_text(
            "⚒️ *UPGRADE FORGE*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "Craft powerful gear from rare battle drops!\n"
            "Select a *category* then choose what to forge.",
            parse_mode="Markdown",
            reply_markup=_build_forge_keyboard(),
        )
        return

    if not data.startswith("forge_"):
        return

    idx_str = data.split("_")[1]
    if not idx_str.isdigit():
        return

    idx = int(idx_str)
    if idx < 0 or idx >= len(FORGE_ITEMS):
        await query.edit_message_text("Invalid selection.")
        return

    item = FORGE_ITEMS[idx]
    user_id = query.from_user.id
    player = get_player(user_id)
    inv_map = _get_user_inventory_map(user_id)

    req_check = _check_requirements(inv_map, item["requirements"])
    can_afford_yen = _can_afford(player, item["cost"])
    all_resources_met = all(met for _, _, met in req_check.values())
    can_forge = all_resources_met and can_afford_yen

    lines = [f"⚒️ *{item['name']}*\n"]
    if item.get("lore"):
        lines.append(f"_\"{item['lore']}\"_\n")

    # Stats gained
    stat_parts = []
    if "str"     in item: stat_parts.append(f"⚔️ +{item['str']} STR")
    if "spd"     in item: stat_parts.append(f"⚡ +{item['spd']} SPD")
    if "def"     in item: stat_parts.append(f"🛡️ +{item['def']} DEF")
    if "hp"      in item: stat_parts.append(f"❤️ +{item['hp']} Max HP")
    if "max_sta" in item: stat_parts.append(f"🌀 +{item['max_sta']} Max STA")
    if stat_parts:
        lines.append("*Gain:* " + "  |  ".join(stat_parts))

    # Yen cost
    yen_icon = "✅" if can_afford_yen else "❌"
    lines.append(f"\n💰 *Cost:* {item['cost']:,}¥  {yen_icon} _(you have {player.get('yen', 0):,}¥)_")

    # Resource requirements
    lines.append("\n📦 *Resources Required:*")
    for req, (have, needed, met) in req_check.items():
        icon = "✅" if met else "❌"
        lines.append(f"{icon} {req}: `{have}/{needed}`")

    if can_forge:
        lines.append("\n✨ *You have everything to forge this!*")
        confirm_button = InlineKeyboardButton(
            f"⚒️ Forge {item['name']}!", callback_data=f"forge_confirm_{idx}"
        )
        keyboard = InlineKeyboardMarkup([[confirm_button], [InlineKeyboardButton("🔙 Back", callback_data="forge_back")]])
    else:
        missing = []
        for req, (have, needed, met) in req_check.items():
            if not met:
                missing.append(f"{req} ({needed - have} more needed)")
        if not can_afford_yen:
            missing.append(f"Yen ({item['cost'] - player.get('yen', 0):,}¥ more needed)")
        lines.append(f"\n⚠️ *Missing:* {chr(10).join(missing)}")
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="forge_back")]])

    text = "\n".join(lines)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)

    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


async def _handle_forge_confirm(query):
    """Actually perform the forge when user confirms."""
    user_id = query.from_user.id
    idx = int(query.data.split("_")[2])

    if idx < 0 or idx >= len(FORGE_ITEMS):
        await query.edit_message_text("Invalid forge item.")
        return

    item   = FORGE_ITEMS[idx]
    player = get_player(user_id)
    inv_map = _get_user_inventory_map(user_id)

    req_check      = _check_requirements(inv_map, item["requirements"])
    can_afford_yen = _can_afford(player, item["cost"])
    all_resources_met = all(met for _, _, met in req_check.values())

    if not all_resources_met or not can_afford_yen:
        await query.answer("❌ You no longer meet the requirements!", show_alert=True)
        return

    # Deduct yen
    update_player(user_id, yen=player["yen"] - item["cost"])

    # Consume resources
    for req, (_, needed, _) in req_check.items():
        remove_item(user_id, req, needed)

    # ── Determine item category ────────────────────────────────────────
    cat = item.get("category", "")
    is_sword = "Swords" in cat or "sword" in item.get("id", "").lower() or "blade" in item.get("name", "").lower() or "fang" in item.get("name", "").lower()
    is_armor = "Armor" in cat or "Haori" in item.get("name", "") or "Cloak" in item.get("name", "") or "Shell" in item.get("name", "")

    # ── Add to inventory as equippable item ───────────────────────────
    if is_sword:
        add_item(user_id, item["name"], "sword")
    elif is_armor:
        add_item(user_id, item["name"], "armor")
    else:
        # Demon Relics / accessories — add as material so they show in inventory
        add_item(user_id, item["name"], "material")

    # ── Also apply stat boosts directly (permanent passive buff) ──────
    updates = {}
    if "str"     in item:
        updates["str_stat"] = player.get("str_stat", 22) + item["str"]
    if "spd"     in item:
        updates["spd"]      = player.get("spd", 20)      + item["spd"]
    if "def"     in item:
        updates["def_stat"] = player.get("def_stat", 18) + item["def"]
    if "hp"      in item:
        new_max_hp = player.get("max_hp", 240) + item["hp"]
        updates["max_hp"] = new_max_hp
        updates["hp"]     = min(player.get("hp", 240) + item["hp"], new_max_hp)
    if "max_sta" in item:
        new_max_sta = player.get("max_sta", 170) + item["max_sta"]
        updates["max_sta"] = new_max_sta
        updates["sta"]     = min(player.get("sta", 170) + item["max_sta"], new_max_sta)

    if updates:
        update_player(user_id, **updates)

    stat_lines = []
    if "str"     in item: stat_lines.append(f"⚔️ +{item['str']} STR")
    if "spd"     in item: stat_lines.append(f"⚡ +{item['spd']} SPD")
    if "def"     in item: stat_lines.append(f"🛡️ +{item['def']} DEF")
    if "hp"      in item: stat_lines.append(f"❤️ +{item['hp']} Max HP")
    if "max_sta" in item: stat_lines.append(f"🌀 +{item['max_sta']} Max STA")

    equip_hint = ""
    if is_sword:
        equip_hint = "\n\n🗡️ *Added to inventory!* Use `/equip` to wield it."
    elif is_armor:
        equip_hint = "\n\n🛡️ *Added to inventory!* Use `/equip` to wear it."
    else:
        equip_hint = "\n\n🎒 *Added to inventory!* Use `/inventory` to see it."

    stats_text = "  |  ".join(stat_lines) if stat_lines else "No stat boosts"

    text = (
        f"⚒️ *Forge Successful!*\n\n"
        f"✨ *{item['name']}* has been forged!\n\n"
        f"{stats_text}\n\n"
        f"💰 -{item['cost']:,}¥ spent"
        f"{equip_hint}"
    )
    await query.edit_message_text(text, parse_mode="Markdown",
                                   reply_markup=InlineKeyboardMarkup([[
                                       InlineKeyboardButton("⚒️ Forge More", callback_data="forge_back")
                                   ]]))

    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop


async def forge_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "⚒️ *UPGRADE FORGE*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "Craft powerful gear from rare battle drops!\n"
        "Select a *category* then choose what to forge.",
        parse_mode="Markdown",
        reply_markup=_build_forge_keyboard(),
    )


__all__ = ["forge_command", "forge_callback", "forge_back_callback", "_handle_forge_confirm"]
