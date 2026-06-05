"""
Shop — one dedicated page per category tab.
Tabs: ⚔️ Weapons | 🛡️ Armor | 🧪 Items | ⬆️ Upgrades
Each tab shows ALL items of that category (no cross-category pagination).
Prev/Next only appear when a single category has > PAGE_SIZE items.
"""
from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, add_item, get_inventory, col
from config import SHOP_ITEMS

PAGE_SIZE = 10

# ── Tab definitions ────────────────────────────────────────────────────────
# Each tab can cover one or more SHOP_ITEMS categories.
TABS = [
    {"id": "weapons",  "label": "⚔️ Weapons",  "cats": ["swords"],           "icon": "⚔️"},
    {"id": "armor",    "label": "🛡️ Armor",    "cats": ["armor"],            "icon": "🛡️"},
    {"id": "items",    "label": "🧪 Items",    "cats": ["items", "potions"], "icon": "🧪"},
    {"id": "upgrades", "label": "⬆️ Upgrades", "cats": ["upgrades"],         "icon": "⬆️"},
    {"id": "pets",     "label": "🐾 Pet Items","cats": ["pet_items"],        "icon": "🐾"},
]

CAT_FONTS = {
    "swords":   "⚔️ 𝙒𝙀𝘼𝙋𝙊𝙉  𝘼𝙍𝙈𝙊𝙍𝙔 ⚔️",
    "armor":    "🛡️ 𝘼𝙍𝙈𝙊𝙍  𝙎𝙏𝘼𝙉𝘿 🛡️",
    "items":    "🧪 𝙄𝙏𝙀𝙈𝙎  &amp;  𝙈𝘼𝙏𝙀𝙍𝙄𝘼𝙇𝙎 🧪",
    "potions":  "🔮 𝘼𝙇𝘾𝙃𝙀𝙈𝙔  𝙋𝙊𝙏𝙄𝙊𝙉𝙎 🔮",
    "upgrades": "⬆️ 𝙋𝙇𝘼𝙔𝙀𝙍  𝙐𝙋𝙂𝙍𝘼𝘿𝙀𝙎 ⬆️",
    "pet_items":"🐾 𝙋𝙀𝙏  𝙄𝙏𝙀𝙈𝙎  &amp;  𝙎𝙐𝙋𝙋𝙇𝙄𝙀𝙎 🐾",
}


# ── Helpers ────────────────────────────────────────────────────────────────

async def _safe_edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        elif any(x in err.lower() for x in ("can't be edited", "message to edit not found")):
            try:
                await query.message.reply_text(text, **kwargs)
            except Exception:
                pass
        else:
            raise
    except TimedOut:
        pass


def find_item(query_str):
    """Case-insensitive: exact code → exact name → partial name."""
    q = query_str.lower().strip()
    for category, items in SHOP_ITEMS.items():
        for item in items:
            if item.get('code', '').lower() == q:
                return item, category
    for category, items in SHOP_ITEMS.items():
        for item in items:
            if item['name'].lower() == q:
                return item, category
    for category, items in SHOP_ITEMS.items():
        for item in items:
            if q in item['name'].lower():
                return item, category
    return None, None


def _get_tab(tab_id):
    """Return the tab dict for a given tab_id (defaults to first tab)."""
    for t in TABS:
        if t["id"] == tab_id:
            return t
    return TABS[0]


def _tab_items(tab):
    """Flat list of (cat, item) for all categories in this tab."""
    flat = []
    for cat in tab["cats"]:
        for item in SHOP_ITEMS.get(cat, []):
            flat.append((cat, item))
    return flat


def _item_detail(cat, item, player):
    """Multi-line structured description for an item."""
    if cat == "swords":
        detail = f"+{item['atk_bonus']} ATK"
    elif cat == "armor":
        detail = f"+{item['def_bonus']} DEF"
    elif cat == "potions":
        detail = item.get('desc', '')[:40]
    elif cat == "upgrades":
        detail = item.get('desc', '')[:40]
    else:
        basic = {
            'wisteria': 'Cures status effects',
            'stamina':  '+50 STA',
            'gourd':    'Full HP restore',
        }
        detail = basic.get(item.get('code', ''), 'Special Item')

    eq_mark = ""
    if cat == "swords" and player and player.get('equipped_sword') == item['name']:
        eq_mark = " ✅"
    if cat == "armor" and player and player.get('equipped_armor') == item['name']:
        eq_mark = " ✅"

    return (
        f"❖ <b>{item['name']}</b>{eq_mark}\n"
        f"   ├─ 💰 Cost : ¥ <b>{item['price']:,}</b>\n"
        f"   ├─ 🏷️ Code : <code>{item.get('code', '—')}</code>\n"
        f"   └─ 📝 Info : <i>{detail}</i>"
    )


# ── Page builder ───────────────────────────────────────────────────────────

def _build_shop_page(player, tab_id="weapons", page=0):
    """Build text + keyboard for one category tab page."""
    tab         = _get_tab(tab_id)
    flat        = _tab_items(tab)
    total_pages = max(1, (len(flat) + PAGE_SIZE - 1) // PAGE_SIZE)
    page        = max(0, min(page, total_pages - 1))
    page_items  = flat[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    bal  = f"¥ {player['yen']:,}" if player else "—"
    eq_s = player.get('equipped_sword', 'None') if player else 'None'
    eq_a = player.get('equipped_armor', 'None') if player else 'None'

    # ── Header ────────────────────────────────────────────────────────────
    lines = [
        "╔═════════════════╗",
        "     ⛩️ <b>𝘿𝙀𝙈𝙊𝙉 𝙎𝙇𝘼𝙔𝙀𝙍</b> ⛩️",
        "          <b>𝙈𝙀𝙍𝘾𝙃𝘼𝙉𝙏 𝙎𝙃𝙊𝙋</b>",
        "╚═════════════════╝\n",
        f"👛 <b>Balance:</b> {bal}",
        f"⚔️ <b>{eq_s}</b>  |  🛡️ <b>{eq_a}</b>",
    ]

    # Show page indicator only when there's more than one page
    if total_pages > 1:
        lines.append(f"📄 Page <b>{page + 1}/{total_pages}</b>")

    lines.append("")

    # ── Items ─────────────────────────────────────────────────────────────
    cur_cat = None
    for cat, item in page_items:
        if cat != cur_cat:
            cur_cat = cat
            lines.append(f"     {CAT_FONTS.get(cat, '📦 𝙎𝙃𝙊𝙋 𝙄𝙏𝙀𝙈𝙎 📦')}")
            lines.append("━━━━━━━━━━━━━━━━━━━")
        lines.append(_item_detail(cat, item, player) + "\n")

    if lines and lines[-1].endswith("\n"):
        lines[-1] = lines[-1].rstrip("\n")

    lines += [
        "━━━━━━━━━━━━━━━━━━━",
        "<blockquote>🛒 <b>Purchase Command</b>",
        "└ Use: <code>/buy [code]</code> or <code>/buy [name]</code></blockquote>",
        "━━━━━━━━━━━━━━━━━━━",
    ]

    # ── Keyboard ──────────────────────────────────────────────────────────
    buttons = []

    # Row 1 – tab buttons (one per category page)
    tab_row = []
    for t in TABS:
        active = "✦ " if t["id"] == tab_id else ""
        tab_row.append(
            InlineKeyboardButton(
                f"{active}{t['label']}",
                callback_data=f"shop_{t['id']}_0",
            )
        )
    # Split into two rows of 2 so they fit on mobile
    buttons.append(tab_row[:2])
    buttons.append(tab_row[2:])

    # Row 3 – Prev / page indicator / Next (only when needed)
    if total_pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"shop_{tab_id}_{page - 1}"))
        nav.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="shop_noop"))
        if page < total_pages - 1:
            nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"shop_{tab_id}_{page + 1}"))
        buttons.append(nav)

    kb = InlineKeyboardMarkup(buttons)
    return "\n".join(lines), kb


# ── /shop ──────────────────────────────────────────────────────────────────
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)

    text, kb = _build_shop_page(player, tab_id="weapons", page=0)

    if update.callback_query:
        await _safe_edit(update.callback_query, text, parse_mode='HTML', reply_markup=kb)
    else:
        msg = update.message
        await msg.reply_text(text, parse_mode='HTML', reply_markup=kb)


# ── Shop callback (tab switch + pagination) ────────────────────────────────
async def shop_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Callback data format:
        shop_noop               – page indicator button, do nothing
        shop_<tab_id>_<page>   – switch tab and/or page
    """
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "shop_noop":
        return

    # shop_<tab_id>_<page>
    parts  = data.split("_", 2)          # ["shop", tab_id, page]
    tab_id = parts[1] if len(parts) > 1 else "weapons"
    page   = int(parts[2]) if len(parts) > 2 else 0

    user_id = query.from_user.id
    player  = get_player(user_id)
    text, kb = _build_shop_page(player, tab_id=tab_id, page=page)
    await _safe_edit(query, text, parse_mode='HTML', reply_markup=kb)


# ── /buy ───────────────────────────────────────────────────────────────────
async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    if not context.args:
        await update.message.reply_text(
            "🏪 *SHOP — BUY*\n\n"
            "Usage: `/buy [code]` or `/buy [code] [amount]`\n\n"
            "📌 *Examples:*\n"
            "  `/buy gourd` — Recovery Gourd\n"
            "  `/buy stamina 5` — 5 Stamina Pills\n"
            "  `/buy elixir` — Demon Blood Elixir\n"
            "  `/buy vitcore` — Vitality Core (+50 HP)\n"
            "  `/buy spscroll` — +3 Skill Points\n"
            "  `/buy scarlet` — Scarlet Crimson Blade\n\n"
            "Use /shop to browse all items.",
            parse_mode='Markdown',
        )
        return

    args   = context.args
    amount = 1
    if len(args) >= 2:
        try:
            amount    = int(args[-1])
            query_str = ' '.join(args[:-1])
        except ValueError:
            query_str = ' '.join(args)
    else:
        query_str = args[0]

    amount = max(1, min(amount, 99))

    item, category = find_item(query_str)
    if not item:
        await update.message.reply_text(
            f"❌ *Item not found:* `{query_str}`\n\nUse /shop to browse items and codes.",
            parse_mode='Markdown',
        )
        return

    # Gear and upgrades — 1 at a time
    if category in ('swords', 'armor', 'upgrades') and amount > 1:
        amount = 1

    total_cost = item['price'] * amount
    if player['yen'] < total_cost:
        needed = total_cost - player['yen']
        await update.message.reply_text(
            f"❌ *Not enough Yen!*\n\n"
            f"{item['emoji']} *{item['name']}* × {amount}\n"
            f"💰 Total:   *{total_cost:,}¥*\n"
            f"👛 Balance: *{player['yen']:,}¥*\n"
            f"💸 Need:    *{needed:,}¥ more*",
            parse_mode='Markdown',
        )
        return

    new_yen    = player['yen'] - total_cost
    equip_note = ""
    extra_note = ""
    update_player(user_id, yen=new_yen)

    # ── Swords ────────────────────────────────────────────────────────────
    if category == 'swords':
        add_item(user_id, item['name'], 'sword')
        current = player.get('equipped_sword', 'None')
        tier    = {
            'Basic Nichirin Blade':       1,
            'Crimson Nichirin Blade':     2,
            'Jet Black Nichirin Blade':   3,
            'Scarlet Crimson Blade':      4,
            'Transparent Nichirin Blade': 5,
            'Sun Nichirin Blade':         6,
        }
        if tier.get(item['name'], 0) > tier.get(current, 0) or current == 'None':
            update_player(user_id, equipped_sword=item['name'])
            equip_note = f"\n⚔️ *Auto-equipped!*"
        else:
            equip_note = f"\n📦 *In inventory.* `/equip {item['name']}` to switch."

    # ── Armor ─────────────────────────────────────────────────────────────
    elif category == 'armor':
        add_item(user_id, item['name'], 'armor')
        current = player.get('equipped_armor', 'None')
        tier    = {
            'Corps Uniform':          1,
            'Reinforced Haori':       2,
            'Hashira Haori':          3,
            'Demon Slayer Uniform EX':4,
            'Flame Haori':            5,
            'Yoriichi Haori':         6,
        }
        if tier.get(item['name'], 0) > tier.get(current, 0) or current == 'None':
            update_player(user_id, equipped_armor=item['name'])
            equip_note = f"\n🛡️ *Auto-equipped!*"
        else:
            equip_note = f"\n📦 *In inventory.* `/equip {item['name']}` to switch."

    # ── Upgrades — apply immediately ──────────────────────────────────────
    elif category == 'upgrades':
        effect  = item.get('effect', '')
        pf      = get_player(user_id)
        applied = []

        mapping = {
            'str_stat+5':     [('str_stat', 5)],
            'spd+5':          [('spd', 5)],
            'def_stat+5':     [('def_stat', 5)],
            'max_hp+50':      [('max_hp', 50), ('hp', 50)],
            'max_sta+50':     [('max_sta', 50), ('sta', 50)],
            'str_stat+15':    [('str_stat', 15)],
            'all_stats+10':   [('str_stat', 10), ('spd', 10), ('def_stat', 10)],
            'all_stats+25':   [('str_stat', 25), ('spd', 25), ('def_stat', 25),
                               ('max_hp', 100), ('hp', 100)],
            'all_stats+50':   [('str_stat', 50), ('spd', 50), ('def_stat', 50),
                               ('max_hp', 200), ('hp', 200)],
            'all_stats+100':  [('str_stat', 100), ('spd', 100), ('def_stat', 100),
                               ('max_hp', 500), ('hp', 500)],
            'skill_points+3': [('skill_points', 3)],
            'skill_points+10':[('skill_points', 10)],
        }
        stat_labels = {
            'str_stat':    '💪 STR',
            'spd':         '⚡ SPD',
            'def_stat':    '🛡️ DEF',
            'max_hp':      '❤️ MaxHP',
            'hp':          '❤️ HP',
            'max_sta':     '🌀 MaxSTA',
            'sta':         '🌀 STA',
            'skill_points':'💠 SP',
        }
        ups = {}
        for stat, val in mapping.get(effect, []):
            ups[stat] = pf.get(stat, 0) + val
            applied.append(f"{stat_labels.get(stat, stat)} +{val}")
        if ups:
            update_player(user_id, **ups)
        extra_note = "\n\n⬆️ *Applied permanently:*\n" + "\n".join(f"  ╰➤ {a}" for a in applied)

    # ── Potions + basic items — add to inventory ───────────────────────────
    else:
        add_item(user_id, item['name'], 'item', amount)
        equip_note = (
            f"\n📦 Added to inventory × {amount}" if amount > 1
            else "\n📦 Added to inventory"
        )

    qty_str = f" × {amount}" if amount > 1 else ""
    await update.message.reply_text(
        f"✅ *Purchase Successful!*\n\n"
        f"{item['emoji']} *{item['name']}*{qty_str}\n"
        f"💸 Spent:   *{total_cost:,}¥*\n"
        f"💰 Balance: *{new_yen:,}¥*"
        f"{equip_note}{extra_note}",
        parse_mode='Markdown',
    )


# ── /sell ──────────────────────────────────────────────────────────────────
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 To sell items use the player market:\n\n"
        "`/list [item name] [price]`\n\n"
        "Example: `/list Demon Blood 500`\n\n"
        "Use /market to browse listings.",
        parse_mode='Markdown',
    )


# ── /equip ─────────────────────────────────────────────────────────────────
async def equip(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    if not context.args:
        inv    = get_inventory(user_id)
        swords = [i for i in inv if i['item_type'] == 'sword']
        armors = [i for i in inv if i['item_type'] == 'armor']
        eq_s   = player.get('equipped_sword', 'None')
        eq_a   = player.get('equipped_armor', 'None')
        lines  = [
            "🔧 *EQUIP*\n━━━━━━━━━━━━━━━━━━━━━\n",
            f"⚔️ Equipped: *{eq_s}*",
            f"🛡️ Equipped: *{eq_a}*\n",
            "📦 *In Inventory:*",
        ]
        for s in swords:
            lines.append(f"  ⚔️ {s['item_name']}" + (" ✅" if s['item_name'] == eq_s else ""))
        for a in armors:
            lines.append(f"  🛡️ {a['item_name']}" + (" ✅" if a['item_name'] == eq_a else ""))
        lines.append("\nUsage: `/equip [item name]`")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    item_name = ' '.join(context.args)
    inv       = get_inventory(user_id)
    sword = next(
        (i for i in inv if i['item_name'].lower() == item_name.lower()
         and i['item_type'] == 'sword'), None
    )
    armor = next(
        (i for i in inv if i['item_name'].lower() == item_name.lower()
         and i['item_type'] == 'armor'), None
    )

    if sword:
        update_player(user_id, equipped_sword=sword['item_name'])
        await update.message.reply_text(f"⚔️ *Equipped:* *{sword['item_name']}*", parse_mode='Markdown')
    elif armor:
        update_player(user_id, equipped_armor=armor['item_name'])
        await update.message.reply_text(f"🛡️ *Equipped:* *{armor['item_name']}*", parse_mode='Markdown')
    else:
        await update.message.reply_text(
            f"❌ *{item_name}* not found in inventory.\nUse /inventory to see your items.",
            parse_mode='Markdown',
        )


def get_inventory(user_id):
    from utils.database import get_inventory as _gi
    return _gi(user_id)
