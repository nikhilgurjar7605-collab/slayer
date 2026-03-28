CLAN_MAX_MEMBERS = 30
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import (get_player, get_clan, update_player, col,
                             get_clan_treasury, add_to_clan_treasury,
                             remove_from_clan_treasury, get_inventory, remove_item,
                             add_item)
from utils.helpers import get_level
from config import BREATHING_STYLES, DEMON_ARTS, OWNER_ID


def _get_member_list(clan):
    """Get member IDs handling both list and JSON string."""
    m = clan.get('members', [])
    if isinstance(m, str):
        try: return json.loads(m)
        except: return []
    return m if isinstance(m, list) else []


# ── /claninfo ─────────────────────────────────────────────────────────────

async def claninfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    # Allow viewing other clans: /claninfo [name]
    if context.args:
        clan_name = ' '.join(context.args)
        clan = col("clans").find_one({"name": {"$regex": f"^{clan_name}$", "$options": "i"}})
        if not clan:
            clan = col("clans").find_one({"name": {"$regex": clan_name, "$options": "i"}})
        # fix: use _get_member_list to handle JSON string members
        member_ids = _get_member_list(clan) if clan else []
        is_member  = clan and (user_id in member_ids)
    else:
        clan       = get_clan(player.get('clan_id')) if player.get('clan_id') else None
        member_ids = _get_member_list(clan) if clan else []
        is_member  = True

    if not clan:
        await update.message.reply_text(
            "╔══════════════════════╗\n"
            "      🏯 𝘾𝙇𝘼𝙉 𝙄𝙉𝙁𝙊\n"
            "╚══════════════════════╝\n\n"
            "╰➤ _You are not in a clan._\n\n"
            "╰➤ `/createclan [name]` — Found one\n"
            "╰➤ `/joinclan [name]` — Join one\n"
            "╰➤ `/clan_list` — Browse all clans",
            parse_mode='Markdown'
        )
        return

    clan.pop('_id', None)
    leader       = get_player(clan['leader_id'])
    leader_name  = leader['name'] if leader else "Unknown"
    is_leader    = user_id == clan['leader_id']
    my_role      = player.get('clan_role', 'recruit') if is_member else 'none'

    # Clan rank
    clan_xp = clan.get('xp', 0)
    if   clan_xp >= 100000: clan_rank, rank_bar = "💀 Shadow Clan",  "🔴🔴🔴🔴🔴"
    elif clan_xp >= 50000:  clan_rank, rank_bar = "🔴 Elite Clan",   "🟠🟠🟠🟠⬜"
    elif clan_xp >= 20000:  clan_rank, rank_bar = "🟡 Rising Clan",  "🟡🟡🟡⬜⬜"
    elif clan_xp >= 5000:   clan_rank, rank_bar = "🟢 Active Clan",  "🟢🟢⬜⬜⬜"
    else:                    clan_rank, rank_bar = "⚪ New Clan",     "⬜⬜⬜⬜⬜"

    # Slogan
    slogan      = clan.get('slogan', '')
    slogan_line = f"✨ _\"{slogan}\"_\n" if slogan else ""

    # Image
    image_url = clan.get('image_url', '')

    # Requirements
    req       = clan.get('requirements', {})
    req_lines = []
    if req.get('min_level'):
        player_lv = get_level(player['xp'])
        met = "✅" if player_lv >= req['min_level'] else "❌"
        req_lines.append(f"  {met} Min Level: *{req['min_level']}* (yours: {player_lv})")
    if req.get('min_xp'):
        met = "✅" if player['xp'] >= req['min_xp'] else "❌"
        req_lines.append(f"  {met} Min XP: *{req['min_xp']:,}*")
    if req.get('faction'):
        met = "✅" if player.get('faction') == req['faction'] else "❌"
        req_lines.append(f"  {met} Faction: *{req['faction'].title()}* only")

    # Treasury summary
    treasury  = get_clan_treasury(clan['id'])
    treas_yen = clan.get('treasury_yen', 0)
    treas_sum = f"💰 *{treas_yen:,}¥*" if treas_yen else ""
    if treasury:
        item_count = sum(t.get('quantity', 1) for t in treasury)
        treas_sum += f"  📦 *{item_count}* items" if treas_sum else f"📦 *{item_count}* items"
    if not treas_sum:
        treas_sum = "_Empty_"

    # Build main info text
    lines = [
        f"╔══════════════════════════╗",
        f"   🏯  {clan['name'].upper()}",
        f"╚══════════════════════════╝",
        slogan_line,
        f"👑 *Leader:*   {leader_name}",
        f"🏅 *Status:*   {clan_rank}  {rank_bar}",
        f"⭐ *Clan XP:*  {clan_xp:,}",
        f"👥 *Members:*  {len(member_ids)}/{CLAN_MAX_MEMBERS}",
    ]

    if req_lines and not is_member:
        lines += ["", "📋 *Join Requirements:*"] + req_lines

    lines += [
        "",
        f"🏦 *Treasury:*  {treas_sum}",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]

    # Buttons
    buttons = []
    if is_member:
        buttons.append([
            InlineKeyboardButton("👥 Members",  callback_data=f"claninfo_members_{clan['id']}"),
            InlineKeyboardButton("🏦 Treasury", callback_data=f"claninfo_treasury_{clan['id']}"),
        ])
        if is_leader or my_role in ('chief', 'deputy'):
            buttons.append([
                InlineKeyboardButton("⚙️ Manage",   callback_data=f"claninfo_manage_{clan['id']}"),
                InlineKeyboardButton("📢 Announce", callback_data=f"claninfo_announce_{clan['id']}"),
            ])
        buttons.append([
            InlineKeyboardButton("⚔️ Raid Status", callback_data=f"claninfo_raid_{clan['id']}"),
        ])
    else:
        # fix: only show join button if player has no clan
        if not player.get('clan_id'):
            buttons.append([
                InlineKeyboardButton("📨 Request to Join", callback_data=f"claninfo_reqjoin_{clan['id']}"),
            ])

    kb   = InlineKeyboardMarkup(buttons) if buttons else None
    text = '\n'.join(l for l in lines if l is not None)

    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return

    if image_url:
        try:
            await msg.reply_photo(
                photo=image_url, caption=text,
                parse_mode='Markdown', reply_markup=kb
            )
            return
        except Exception:
            pass  # fall through to text

    await msg.reply_text(text, parse_mode='Markdown', reply_markup=kb)


async def _edit_msg(query, text, reply_markup=None):
    """
    Edit a message safely — works for both photo and text messages.
    When a clan has an image, the original message is a photo so
    edit_message_text fails silently. We detect this and use
    edit_message_caption instead.
    """
    is_photo = bool(query.message.photo)
    try:
        if is_photo:
            await query.edit_message_caption(
                caption=text, parse_mode='Markdown', reply_markup=reply_markup
            )
        else:
            await query.edit_message_text(
                text, parse_mode='Markdown', reply_markup=reply_markup
            )
    except Exception:
        try:
            await query.message.reply_text(text, parse_mode='Markdown', reply_markup=reply_markup)
        except Exception:
            pass


async def claninfo_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle claninfo inline buttons."""
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data    = query.data   # claninfo_ACTION_CLANID

    parts  = data.split('_')
    action = parts[1]
    # fix: clan_id parse was fragile — handle safely
    try:
        clan_id = int(parts[2]) if len(parts) > 2 else 0
    except (ValueError, IndexError):
        await query.answer("Invalid action.", show_alert=True)
        return

    clan = col("clans").find_one({"id": clan_id})
    if not clan:
        await query.answer("Clan not found!", show_alert=True)
        return
    clan.pop('_id', None)

    player = get_player(user_id)
    if not player:
        await query.answer("No character found.", show_alert=True)
        return

    # fix: use _get_member_list for consistent member check
    member_ids = _get_member_list(clan)
    is_member  = user_id in member_ids
    is_leader  = user_id == clan['leader_id']
    my_role    = player.get('clan_role', 'recruit') if player else 'none'
    role_icons = {"leader": "👑", "chief": "⭐", "deputy": "🔷",
                  "officer": "🔹", "recruit": "👤"}

    back_btn = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔙 Back", callback_data=f"claninfo_back_{clan_id}")
    ]])

    if action == "back":
        await _edit_msg(query, f"🏯 *{clan['name']}* — use /claninfo to refresh full view", back_btn)
        return

    if action == "members":
        member_ids_local = _get_member_list(clan)
        members_data = []
        for mid in member_ids_local:
            m = col("players").find_one({"user_id": mid})
            if m:
                m.pop("_id", None)
                members_data.append(m)

        lines = [f"👥 *{clan['name']} — MEMBERS* ({len(members_data)})", "━━━━━━━━━━━━━━━━━━━━━", ""]
        for m in sorted(members_data, key=lambda x: x.get('xp', 0), reverse=True):
            role = m.get('clan_role', 'recruit')
            icon = role_icons.get(role, '👤')
            lv   = get_level(m['xp'])
            fe   = '🗡️' if m['faction'] == 'slayer' else '👹'
            lines.append(f"  {icon} {fe} *{m['name']}* Lv.{lv}")

        await _edit_msg(query, '\n'.join(lines), back_btn)
        return

    if action == "treasury":
        if not is_member:
            await query.answer("❌ Members only.", show_alert=True)
            return
        treasury  = get_clan_treasury(clan['id'])
        treas_yen = clan.get('treasury_yen', 0)
        lines     = [f"🏦 *{clan['name']} — TREASURY*", "━━━━━━━━━━━━━━━━━━━━━", f"💰 Yen: *{treas_yen:,}¥*", ""]
        if treasury:
            for t in treasury:
                lines.append(f"  📦 {t['item_name']} × {t.get('quantity', 1)}")
        else:
            lines.append("  _No items in treasury_")
        lines += ["", "━━━━━━━━━━━━━━━━━━━━━",
                  "💡 `/clandeposit [item]` — Deposit item",
                  "💡 `/clandeposit [amount]` — Deposit Yen"]
        await _edit_msg(query, '\n'.join(lines), back_btn)
        return

    if action == "manage":
        if not (is_leader or my_role in ('chief', 'deputy')):
            await query.answer("❌ No permission.", show_alert=True)
            return
        slogan  = clan.get('slogan', '_Not set_')
        req     = clan.get('requirements', {})
        req_str = ', '.join(f"{k}={v}" for k, v in req.items()) if req else '_None_'
        lines = [
            f"⚙️ *{clan['name']} — MANAGE*",
            "━━━━━━━━━━━━━━━━━━━━━",
            f"✨ Slogan: {slogan}",
            f"📋 Requirements: {req_str}",
            f"🖼 Image: {'Set' if clan.get('image_url') else 'Not set'}",
            "",
            "━━━━━━━━━━━━━━━━━━━━━",
            "💡 `/clanslogan [text]` — Set slogan",
            "💡 `/clanreq level [n]` — Set min level",
            "💡 `/clanreq xp [n]` — Set min XP",
            "💡 `/clanreq faction [slayer|demon]` — Faction req",
            "💡 `/clanimage [url]` — Set clan image URL",
            "💡 `/setclanlink [url]` — Set group link",
        ]
        await _edit_msg(query, '\n'.join(lines), back_btn)
        return

    if action == "raid":
        raid = col("clan_raids").find_one({"clan_id": clan['id'], "status": "active"})
        if not raid:
            last = col("clan_raids").find_one({"clan_id": clan['id']}, sort=[("ended_at", -1)])
            text = (f"⚔️ *{clan['name']} — RAIDS*\n\n"
                    f"No active raid.\n\n"
                    f"{'Last raid: ' + str(last.get('boss_name', '?')) if last else 'No raids yet.'}\n\n"
                    f"💡 `/clanraid start [boss]` to begin!")
        else:
            hp_pct = raid['boss_hp'] / max(raid['boss_max_hp'], 1)
            hp_bar = "❤️" * int(hp_pct * 8) + "🖤" * (8 - int(hp_pct * 8))
            parts_data = raid.get('participants', {})
            top = sorted(parts_data.items(), key=lambda x: x[1].get('damage', 0), reverse=True)[:5]
            lines = [
                f"⚔️ *ACTIVE RAID — {raid['boss_name']}*",
                hp_bar,
                f"❤️ {raid['boss_hp']:,} / {raid['boss_max_hp']:,}",
                f"👥 {len(parts_data)} fighters",
                "",
                "🏆 *Top Damage:*",
            ]
            for i, (pid, pd) in enumerate(top, 1):
                lines.append(f"  {i}. {pd['name']} — {pd['damage']:,}")
            text = '\n'.join(lines)
        await _edit_msg(query, text, back_btn)
        return

    if action == "reqjoin":
        if is_member:
            await query.answer("You're already in this clan!", show_alert=True)
            return
        if player.get('clan_id'):
            await query.answer("Leave your current clan first!", show_alert=True)
            return
        # Check requirements
        req = clan.get('requirements', {})
        if req.get('min_level') and get_level(player['xp']) < req['min_level']:
            await query.answer(f"❌ Min level {req['min_level']} required.", show_alert=True)
            return
        if req.get('min_xp') and player['xp'] < req['min_xp']:
            await query.answer(f"❌ Min {req['min_xp']:,} XP required.", show_alert=True)
            return
        if req.get('faction') and player.get('faction') != req['faction']:
            await query.answer(f"❌ {req['faction'].title()} faction only.", show_alert=True)
            return
        try:
            await context.bot.send_message(
                chat_id=clan['leader_id'],
                text=(
                    f"📨 *JOIN REQUEST*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"*{player['name']}* wants to join *{clan['name']}*\n"
                    f"🏅 Rank: {player.get('rank', '?')}  |  Lv.{get_level(player['xp'])}\n\n"
                    f"Accept or decline?"
                ),
                parse_mode='Markdown',
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("✅ Accept", callback_data=f"clan_accept_{user_id}_{clan['id']}"),
                    InlineKeyboardButton("❌ Reject", callback_data=f"clan_reject_{user_id}_{clan['id']}"),
                ]])
            )
            await query.answer("✅ Join request sent to the clan leader!", show_alert=True)
        except Exception:
            await query.answer("❌ Could not reach clan leader.", show_alert=True)
        return

    # fix: unknown action fallback
    await query.answer("❓ Unknown action.", show_alert=True)


# ── /clandeposit ─────────────────────────────────────────────────────────

async def clandeposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /clandeposit [item name]  — deposit an item to treasury
    /clandeposit [amount]     — deposit Yen to clan treasury
    """
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ You must be in a clan to deposit.")
        return

    if not context.args:
        await update.message.reply_text(
            "📖 Usage:\n"
            "  `/clandeposit [item name]` — Deposit an item\n"
            "  `/clandeposit 5000` — Deposit 5,000¥ to clan treasury",
            parse_mode='Markdown'
        )
        return

    # Check if it's a Yen deposit
    arg = ' '.join(context.args).strip().lower().replace('¥', '').replace(',', '')
    try:
        amount = int(arg.replace('yen', '').strip())
        if amount < 100:
            await update.message.reply_text("❌ Minimum deposit is 100¥")
            return
        if player['yen'] < amount:
            await update.message.reply_text(f"❌ Not enough Yen! You have *{player['yen']:,}¥*", parse_mode='Markdown')
            return
        update_player(user_id, yen=player['yen'] - amount)
        col("clans").update_one({"id": player['clan_id']}, {"$inc": {"treasury_yen": amount}})
        await update.message.reply_text(
            f"✅ Deposited *{amount:,}¥* to clan treasury!", parse_mode='Markdown'
        )
        return
    except ValueError:
        pass  # not a number — treat as item deposit

    # Item deposit
    item_name = ' '.join(context.args).strip()
    inv   = get_inventory(user_id)
    found = next((i for i in inv if i['item_name'].lower() == item_name.lower()), None)
    if not found:
        found = next((i for i in inv if item_name.lower() in i['item_name'].lower()), None)
    if not found:
        await update.message.reply_text(f"❌ *{item_name}* not in your inventory.", parse_mode='Markdown')
        return

    remove_item(user_id, found['item_name'], 1)
    # fix: use add_to_clan_treasury (the proper DB helper) instead of raw collection write
    add_to_clan_treasury(player['clan_id'], found['item_name'], 1)
    await update.message.reply_text(
        f"✅ Deposited *{found['item_name']}* to the clan treasury!\n"
        f"Use `/claninfo` → 🏦 Treasury to view.",
        parse_mode='Markdown'
    )


# ── /clanwithdraw ─────────────────────────────────────────────────────────

async def clanwithdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ You are not in a clan.")
        return

    clan = get_clan(player['clan_id'])
    if not clan:
        await update.message.reply_text("❌ Clan not found.")
        return

    # fix: allow leader AND officers to withdraw (not just leader)
    my_role = player.get('clan_role', 'recruit')
    if clan['leader_id'] != user_id and my_role not in ('chief', 'deputy'):
        await update.message.reply_text("❌ Only the clan leader or officers can withdraw.")
        return

    if not context.args:
        treasury  = get_clan_treasury(player['clan_id'])
        treas_yen = clan.get('treasury_yen', 0)
        if not treasury and not treas_yen:
            await update.message.reply_text("🏦 Clan treasury is empty.")
            return
        lines = ["🏦 *CLAN TREASURY*\n"]
        if treas_yen:
            lines.append(f"╰➤ 💰 Yen: *{treas_yen:,}¥*")
        for item in treasury:
            lines.append(f"╰➤ {item['item_name']} × {item['quantity']}")
        lines.append("\n\nUsage: `/clanwithdraw [item name]` or `/clanwithdraw yen [amount]`")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    # fix: support yen withdrawal — /clanwithdraw yen 1000
    if context.args[0].lower() == 'yen':
        try:
            amount = int(context.args[1].replace(',', '').replace('¥', ''))
        except (IndexError, ValueError):
            await update.message.reply_text("Usage: `/clanwithdraw yen [amount]`", parse_mode='Markdown')
            return
        treas_yen = clan.get('treasury_yen', 0)
        if treas_yen < amount:
            await update.message.reply_text(f"❌ Only *{treas_yen:,}¥* in treasury!", parse_mode='Markdown')
            return
        if amount <= 0:
            await update.message.reply_text("❌ Amount must be positive.")
            return
        col("clans").update_one({"id": player['clan_id']}, {"$inc": {"treasury_yen": -amount}})
        update_player(user_id, yen=player['yen'] + amount)
        await update.message.reply_text(
            f"✅ Withdrew *{amount:,}¥* from treasury to your wallet!", parse_mode='Markdown'
        )
        return

    item_name = ' '.join(context.args)
    treasury  = get_clan_treasury(player['clan_id'])
    item      = next((i for i in treasury if i['item_name'].lower() == item_name.lower()), None)

    if not item:
        await update.message.reply_text(
            f"❌ *{item_name}* not found in treasury.\nUse `/clanwithdraw` to see what's available.",
            parse_mode='Markdown'
        )
        return

    success = remove_from_clan_treasury(player['clan_id'], item['item_name'], 1)
    if success:
        add_item(user_id, item['item_name'], 'material', 1)
        await update.message.reply_text(
            f"✅ *𝙒𝙄𝙏𝙃𝘿𝙍𝘼𝙒𝙉!*\n\n"
            f"╰➤ *{item['item_name']}* withdrawn to your inventory",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("❌ Withdrawal failed.")


# ── /changestyle ──────────────────────────────────────────────────────────

CHANGE_COST = 500_000

async def changestyle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    faction    = player['faction']
    style_list = BREATHING_STYLES if faction == 'slayer' else DEMON_ARTS
    label      = "Breathing Style" if faction == 'slayer' else "Demon Art"

    # Filter out ultra legendary and exclusive
    available = [s for s in style_list if s.get('gacha_weight', 1) > 0]
    # Stone uniqueness check
    for s in available[:]:
        if s['name'] == 'Stone Breathing':
            existing = col('players').find_one({'style': 'Stone Breathing', 'user_id': {'$ne': user_id}})
            if existing:
                available.remove(s)

    if not context.args:
        lines = [
            f"🔄 *𝘾𝙃𝘼𝙉𝙂𝙀 {label.upper()}*\n",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"💸 Cost: *{CHANGE_COST:,}¥*",
            f"💰 Your balance: *{player['yen']:,}¥*\n",
            f"━━━━━━━━━━━━━━━━━━━━━",
            f"📜 *Available {label}s:*\n",
        ]
        for s in available:
            cur = " ← *current*" if s['name'] == player['style'] else ""
            lines.append(f"╰➤ {s['emoji']} *{s['name']}*  {s['rarity']}{cur}")
        lines += [
            f"\n━━━━━━━━━━━━━━━━━━━━━",
            f"💡 `/changestyle [name]` to change",
        ]
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    new_name  = ' '.join(context.args)
    new_style = next((s for s in available if s['name'].lower() == new_name.lower()), None)

    if not new_style:
        await update.message.reply_text(f"❌ *{new_name}* not found.\nUse `/changestyle` to see options.", parse_mode='Markdown')
        return
    if new_style['name'] == player['style']:
        await update.message.reply_text(f"❌ You already use *{new_style['name']}*!", parse_mode='Markdown')
        return
    if player['yen'] < CHANGE_COST:
        needed = CHANGE_COST - player['yen']
        await update.message.reply_text(
            f"❌ *Not enough Yen!*\n\n"
            f"╰➤ Cost:     *{CHANGE_COST:,}¥*\n"
            f"╰➤ You have: *{player['yen']:,}¥*\n"
            f"╰➤ Need:     *{needed:,}¥ more*",
            parse_mode='Markdown'
        )
        return

    old_style = player['style']
    update_player(user_id, style=new_style['name'], style_emoji=new_style['emoji'],
                  yen=player['yen'] - CHANGE_COST)

    await update.message.reply_text(
        f"✅ *𝙎𝙏𝙔𝙇𝙀 𝘾𝙃𝘼𝙉𝙂𝙀𝘿!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"❌ Old: _{old_style}_\n"
        f"✅ New: *{new_style['emoji']} {new_style['name']}*\n"
        f"       {new_style['rarity']}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💸 Spent: *{CHANGE_COST:,}¥*\n"
        f"💰 Balance: *{player['yen'] - CHANGE_COST:,}¥*\n\n"
        f"_Use /info to see your new forms!_",
        parse_mode='Markdown'
    )
