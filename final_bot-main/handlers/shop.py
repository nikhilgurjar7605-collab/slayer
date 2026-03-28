"""
Shop — paginated, 10 items per page, inline Prev/Next buttons.
Also supports category filter buttons.
"""
from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, add_item, get_inventory, col
from config import SHOP_ITEMS

PAGE_SIZE = 10

CAT_ICONS = {
    "swords":   "⚔️",
    "armor":    "🛡️",
    "items":    "🧪",
    "potions":  "🔮",
    "upgrades": "⬆️",
}


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


def _flat_items(cat_filter="all"):
    """All shop items as flat list, optionally filtered by category."""
    flat = []
    for cat, items in SHOP_ITEMS.items():
        if cat_filter == "all" or cat_filter == cat:
            for item in items:
                flat.append((cat, item))
    return flat


def _item_detail(cat, item, player):
    """One-line description for an item."""
    icon = CAT_ICONS.get(cat, "📦")
    price_str = f"{item['price']:,}¥"

    if cat == "swords":
        detail = f"+{item['atk_bonus']} ATK"
    elif cat == "armor":
        detail = f"+{item['def_bonus']} DEF"
    elif cat == "potions":
        detail = item.get('desc', '')[:40]
    elif cat == "upgrades":
        detail = item.get('desc', '')[:40]
    else:
        basic = {'wisteria': 'Cures status effects',
                 'stamina':  '+50 STA', 'gourd': 'Full HP restore'}
        detail = basic.get(item.get('code', ''), '')

    eq_mark = ""
    if cat == "swords" and player and player.get('equipped_sword') == item['name']:
        eq_mark = " ✅"
    if cat == "armor" and player and player.get('equipped_armor') == item['name']:
        eq_mark = " ✅"

    return f"{icon} *{item['name']}*{eq_mark}  `{item.get('code','—')}`  — *{price_str}*\n   _{detail}_"


def _build_shop_page(player, page, cat_filter="all"):
    """Build text + keyboard for one shop page."""
    flat        = _flat_items(cat_filter)
    total_pages = max(1, (len(flat) + PAGE_SIZE - 1) // PAGE_SIZE)
    page        = max(0, min(page, total_pages - 1))
    page_items  = flat[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    bal  = f"{player['yen']:,}¥" if player else "—"
    eq_s = player.get('equipped_sword', 'None') if player else 'None'
    eq_a = player.get('equipped_armor', 'None') if player else 'None'

    lines = [
        "╔══════════════════════╗",
        "      🏪 𝙎𝙃𝙊𝙋",
        "╚══════════════════════╝\n",
        f"💰 *Balance:* {bal}  |  📄 Page *{page+1}/{total_pages}*",
        f"⚔️ *{eq_s}*  🛡️ *{eq_a}*\n",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]

    # Group items by category for headers
    cur_cat = None
    for cat, item in page_items:
        if cat != cur_cat:
            cur_cat = cat
            lines.append(f"\n{CAT_ICONS.get(cat,'📦')} *{cat.upper()}*")
        lines.append(_item_detail(cat, item, player))

    lines += [
        "\n━━━━━━━━━━━━━━━━━━━━━",
        "💡 `/buy [code]` or `/buy [name]`",
    ]

    # ── Navigation buttons ─────────────────────────────────────────────
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Prev", callback_data=f"shop_{page-1}_{cat_filter}"))
    nav.append(InlineKeyboardButton(f"📄 {page+1}/{total_pages}", callback_data="shop_noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("Next ▶️", callback_data=f"shop_{page+1}_{cat_filter}"))

    # ── Category filter buttons ────────────────────────────────────────
    cats = [("All","all"),("⚔️","swords"),("🛡️","armor"),
            ("🧪","items"),("🔮","potions"),("⬆️","upgrades")]
    cat_row = [
        InlineKeyboardButton(
            f"{'✓' if (cf=='all' and cat_filter=='all') or cat_filter==cf else ''}{emoji}",
            callback_data=f"shop_0_{cf}"
        )
        for emoji, cf in cats
    ]

    buttons = [nav, cat_row]
    kb = InlineKeyboardMarkup(buttons)
    return "\n".join(lines), kb


# ── /shop ──────────────────────────────────────────────────────────────────
async def shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)

    text, kb = _build_shop_page(player, 0, "all")

    msg = update.message if update.message else update.callback_query.message
    if update.callback_query:
        await _safe_edit(update.callback_query, text, parse_mode='Markdown', reply_markup=kb)
    else:
        await msg.reply_text(text, parse_mode='Markdown', reply_markup=kb)


# ── Shop page callback ─────────────────────────────────────────────────────
async def shop_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    data    = query.data   # shop_N_catfilter  or  shop_noop

    if data == "shop_noop":
        return

    parts      = data.split("_", 2)
    page       = int(parts[1]) if len(parts) > 1 else 0
    cat_filter = parts[2] if len(parts) > 2 else "all"

    user_id = query.from_user.id
    player  = get_player(user_id)
    text, kb = _build_shop_page(player, page, cat_filter)
    await _safe_edit(query, text, parse_mode='Markdown', reply_markup=kb)


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
            parse_mode='Markdown'
        )
        return

    args = context.args
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
            parse_mode='Markdown'
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
            parse_mode='Markdown'
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
        tier    = {'Basic Nichirin Blade':1,'Crimson Nichirin Blade':2,
                   'Jet Black Nichirin Blade':3,'Scarlet Crimson Blade':4,
                   'Transparent Nichirin Blade':5,'Sun Nichirin Blade':6}
        if tier.get(item['name'], 0) > tier.get(current, 0) or current == 'None':
            update_player(user_id, equipped_sword=item['name'])
            equip_note = f"\n⚔️ *Auto-equipped!*"
        else:
            equip_note = f"\n📦 *In inventory.* `/equip {item['name']}` to switch."

    # ── Armor ─────────────────────────────────────────────────────────────
    elif category == 'armor':
        add_item(user_id, item['name'], 'armor')
        current = player.get('equipped_armor', 'None')
        tier    = {'Corps Uniform':1,'Reinforced Haori':2,'Hashira Haori':3,
                   'Demon Slayer Uniform EX':4,'Flame Haori':5,'Yoriichi Haori':6}
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
            'str_stat':'💪 STR','spd':'⚡ SPD','def_stat':'🛡️ DEF',
            'max_hp':'❤️ MaxHP','hp':'❤️ HP','max_sta':'🌀 MaxSTA',
            'sta':'🌀 STA','skill_points':'💠 SP',
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
        equip_note = f"\n📦 Added to inventory × {amount}" if amount > 1 else "\n📦 Added to inventory"

    qty_str = f" × {amount}" if amount > 1 else ""
    await update.message.reply_text(
        f"✅ *Purchase Successful!*\n\n"
        f"{item['emoji']} *{item['name']}*{qty_str}\n"
        f"💸 Spent:   *{total_cost:,}¥*\n"
        f"💰 Balance: *{new_yen:,}¥*"
        f"{equip_note}{extra_note}",
        parse_mode='Markdown'
    )


# ── /sell ──────────────────────────────────────────────────────────────────
async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💡 To sell items use the player market:\n\n"
        "`/list [item name] [price]`\n\n"
        "Example: `/list Demon Blood 500`\n\n"
        "Use /market to browse listings.",
        parse_mode='Markdown'
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
    sword = next((i for i in inv if i['item_name'].lower() == item_name.lower()
                  and i['item_type'] == 'sword'), None)
    armor = next((i for i in inv if i['item_name'].lower() == item_name.lower()
                  and i['item_type'] == 'armor'), None)

    if sword:
        update_player(user_id, equipped_sword=sword['item_name'])
        await update.message.reply_text(f"⚔️ *Equipped:* *{sword['item_name']}*", parse_mode='Markdown')
    elif armor:
        update_player(user_id, equipped_armor=armor['item_name'])
        await update.message.reply_text(f"🛡️ *Equipped:* *{armor['item_name']}*", parse_mode='Markdown')
    else:
        await update.message.reply_text(
            f"❌ *{item_name}* not found in inventory.\nUse /inventory to see your items.",
            parse_mode='Markdown'
        )


def get_inventory(user_id):
    from utils.database import get_inventory as _gi
    return _gi(user_id)
