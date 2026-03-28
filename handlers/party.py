from telegram.error import BadRequest, TimedOut
from utils.guards import dm_only
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import (get_player, get_party, update_player, col,
                             create_party, add_to_party, send_party_invite,
                             get_pending_invite, resolve_invite)
from utils.helpers import get_level

async def _safe_edit(query, text, **kwargs):
    """Edit a message safely, falling back to reply on failure."""
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        try:
            await query.message.reply_text(text, **kwargs)
        except Exception:
            pass


def get_party_member_ids(party):
    raw = party.get('members', [])
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        return []


@dm_only
async def party(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    current_party = get_party(user_id)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("👥 Info",    callback_data='alliance_info'),
            InlineKeyboardButton("📨 Invite",  callback_data='alliance_invite'),
        ],
        [InlineKeyboardButton("🚪 Leave",      callback_data='alliance_leave')]
    ])

    if not current_party:
        text = (
            "╔══════════════════════╗\n"
            "      👥 𝘼𝙇𝙇𝙄𝘼𝙉𝘾𝙀\n"
            "╚══════════════════════╝\n\n"
            "╰➤ You are not in a party.\n\n"
            "💡 `/invite @username` — Invite someone\n"
            "_Max 3 members per party_"
        )
    else:
        members     = get_party_member_ids(current_party)
        leader      = get_player(current_party['leader_id'])
        member_lines = []
        for mid in members:
            m = get_player(mid)
            if m:
                fe   = '🗡️' if m['faction'] == 'slayer' else '👹'
                lv   = get_level(m['xp'])
                role = '👑 Leader' if mid == current_party['leader_id'] else '🔰 Member'
                from utils.helpers import hp_bar
                bar  = hp_bar(m['hp'], m['max_hp'])
                member_lines.append(
                    f"  {fe} *{m['name']}* [{role}]\n"
                    f"     Lv.{lv} | ❤️ {m['hp']}/{m['max_hp']} {bar}"
                )
        text = (
            f"╔══════════════════════╗\n"
            f"      👥 𝘼𝙇𝙇𝙄𝘼𝙉𝘾𝙀\n"
            f"╚══════════════════════╝\n\n"
            f"👑 Leader: *{leader['name'] if leader else 'Unknown'}*\n"
            f"👥 Members: *{len(members)}/3*\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
        ) + '\n'.join(member_lines)

    msg = update.message if update.message else update.callback_query.message
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode='Markdown', reply_markup=keyboard)
    else:
        await msg.reply_text(text, parse_mode='Markdown', reply_markup=keyboard)


async def alliance_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _safe_edit(query, 
        "📨 *INVITE A PLAYER*\n\n"
        "Send: `/invite @username`\n\n"
        "_They will receive a request in their DM._",
        parse_mode='Markdown'
    )


async def alliance_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    current_party = get_party(user_id)

    if not current_party:
        await query.answer("You are not in a party!", show_alert=True)
        return

    members      = get_party_member_ids(current_party)
    member_lines = []
    for mid in members:
        m = get_player(mid)
        if m:
            fe   = '🗡️' if m['faction'] == 'slayer' else '👹'
            lv   = get_level(m['xp'])
            role = '👑' if mid == current_party['leader_id'] else '🔰'
            member_lines.append(f"  {role} {fe} *{m['name']}* Lv.{lv} | ❤️ {m['hp']}/{m['max_hp']}")

    leader = get_player(current_party['leader_id'])
    text = (
        f"👥 *ALLIANCE INFO*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👑 Leader: *{leader['name'] if leader else 'Unknown'}*\n"
        f"👥 Size: *{len(members)}/3*\n\n"
    )
    text += '\n' + '\n'.join(member_lines)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data='goto_party')]])
    await _safe_edit(query, text, parse_mode='Markdown', reply_markup=keyboard)


async def alliance_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    current_party = get_party(user_id)

    if not current_party:
        await query.answer("You are not in a party!", show_alert=True)
        return

    members = get_party_member_ids(current_party)
    members = [m for m in members if m != user_id]

    if not members:
        col("parties").delete_one({"id": current_party.get('id', current_party.get('leader_id'))})
    else:
        if current_party['leader_id'] == user_id:
            new_leader = members[0]
            col("parties").update_one(
                {"leader_id": current_party['leader_id']},
                {"$set": {"members": members, "leader_id": new_leader}}
            )
            update_player(new_leader, party_id=current_party.get('id'))
        else:
            col("parties").update_one(
                {"leader_id": current_party['leader_id']},
                {"$set": {"members": members}}
            )

    update_player(user_id, party_id=None)
    await _safe_edit(query, 
        "🚪 *You left the alliance.*\n\nUse /party to form a new one.",
        parse_mode='Markdown'
    )


@dm_only
async def party_invite_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/invite @username`", parse_mode='Markdown')
        return

    target_username = context.args[0].lstrip('@')
    target = col("players").find_one({"username": {"$regex": f"^{target_username}$", "$options": "i"}})

    if not target:
        await update.message.reply_text(f"❌ Player *@{target_username}* not found.", parse_mode='Markdown')
        return
    if target['user_id'] == user_id:
        await update.message.reply_text("❌ You can't invite yourself!")
        return
    if target.get('party_id'):
        await update.message.reply_text(f"❌ *{target['name']}* is already in a party.", parse_mode='Markdown')
        return

    current_party = get_party(user_id)
    if current_party:
        members = get_party_member_ids(current_party)
        if len(members) >= 3:
            await update.message.reply_text("❌ Your party is already full (3/3)!")
            return

    send_party_invite(user_id, target['user_id'])

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept",  callback_data=f"alliance_accept_{user_id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"alliance_decline_{user_id}"),
    ]])

    fe  = '🗡️' if player['faction'] == 'slayer' else '👹'
    lv  = get_level(player['xp'])
    try:
        await context.bot.send_message(
            chat_id=target['user_id'],
            text=(
                f"╔══════════════════════╗\n"
                f"      👥 𝙋𝘼𝙍𝙏𝙔 𝙄𝙉𝙑𝙄𝙏𝙀\n"
                f"╚══════════════════════╝\n\n"
                f"{fe} *{player['name']}* invites you to their party!\n"
                f"🏅 Rank: {player['rank']}  |  ⚔️ Lv.{lv}\n\n"
                f"Do you accept?"
            ),
            parse_mode='Markdown',
            reply_markup=keyboard
        )
        await update.message.reply_text(f"✅ Invite sent to *{target['name']}*!", parse_mode='Markdown')
    except Exception:
        await update.message.reply_text("❌ Could not reach that player. They may have blocked the bot.")


async def alliance_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    from_id = int(query.data.split('_')[-1])

    player      = get_player(user_id)
    from_player = get_player(from_id)

    if not player or not from_player:
        await query.answer("Player not found!", show_alert=True)
        return
    if player.get('party_id'):
        await query.answer("You are already in a party!", show_alert=True)
        return

    resolve_invite(from_id, user_id, 'accepted')

    current_party = get_party(from_id)
    if current_party:
        members = get_party_member_ids(current_party)
        if len(members) >= 3:
            await _safe_edit(query, "❌ Party is full!")
            return
        add_to_party(current_party['id'], user_id)
    else:
        party_id = create_party(from_id)
        add_to_party(party_id, user_id)

    fe1 = '🗡️' if from_player['faction'] == 'slayer' else '👹'
    fe2 = '🗡️' if player['faction'] == 'slayer' else '👹'

    await _safe_edit(query, 
        f"✅ *𝘼𝙇𝙇𝙄𝘼𝙉𝘾𝙀 𝙁𝙊𝙍𝙈𝙀𝘿!*\n\n"
        f"{fe1} *{from_player['name']}* + {fe2} *{player['name']}*\n\n"
        f"_Use /party to manage your alliance!_",
        parse_mode='Markdown'
    )
    try:
        await context.bot.send_message(
            chat_id=from_id,
            text=f"✅ *{player['name']}* accepted your party invite!\nUse /party to see your alliance.",
            parse_mode='Markdown'
        )
    except Exception:
        pass


async def alliance_decline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    from_id = int(query.data.split('_')[-1])

    resolve_invite(from_id, user_id, 'declined')
    decliner = get_player(user_id)
    await _safe_edit(query, "❌ Alliance invite declined.")
    try:
        await context.bot.send_message(
            chat_id=from_id,
            text=f"❌ *{decliner['name'] if decliner else 'The player'}* declined your party invite.",
            parse_mode='Markdown'
        )
    except Exception:
        pass


async def choose_ally(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    current_party = get_party(user_id)

    if not current_party:
        await query.answer("You have no allies!", show_alert=True)
        return

    members   = get_party_member_ids(current_party)
    ally_list = []
    for mid in members:
        if mid != user_id:
            m = get_player(mid)
            if m:
                lv = get_level(m['xp'])
                fe = '🗡️' if m['faction'] == 'slayer' else '👹'
                ally_list.append((mid, f"{fe} {m['name']} Lv.{lv} ❤️{m['hp']}"))

    if not ally_list:
        await query.answer("No allies available!", show_alert=True)
        return

    buttons = [[InlineKeyboardButton(label, callback_data=f"switch_ally_{mid}")] for mid, label in ally_list]
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data='fight')])

    await _safe_edit(query, 
        "👥 *CHOOSE YOUR ALLY*\n\nWho will fight alongside you?",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def switch_ally(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    ally_id = int(query.data.split('_')[-1])
    ally    = get_player(ally_id)

    if not ally:
        await query.answer("Ally not found!", show_alert=True)
        return

    fe = '🗡️' if ally['faction'] == 'slayer' else '👹'
    await _safe_edit(query, 
        f"✅ *{fe} {ally['name']}* joins the battle!\n\n"
        f"❤️ {ally['hp']}/{ally['max_hp']}  |  ⚔️ STR: {ally['str_stat']}",
        parse_mode='Markdown'
    )
