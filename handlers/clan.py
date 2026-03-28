from telegram.error import BadRequest, TimedOut
import json
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, get_clan, get_clan_by_name, col
from datetime import datetime

CLAN_MAX_MEMBERS  = 20    # max players per clan
CLAN_CREATE_COST  = 50000 # yen to create a clan

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


def get_clan_members(clan_data):
    m = clan_data.get('members', [])
    if isinstance(m, str):
        try: return json.loads(m)
        except: return []
    return m if isinstance(m, list) else []


async def clan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    if not context.args:
        clan_data = get_clan(player.get('clan_id')) if player.get('clan_id') else None
        if clan_data:
            members = get_clan_members(clan_data)
            await update.message.reply_text(
                f"🏯 *{clan_data['name']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"👑 Your clan is active!\n"
                f"👥 Members: *{len(members)}*\n"
                f"⭐ XP: *{clan_data.get('xp',0):,}*\n\n"
                f"💡 `/claninfo` — Full clan details",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "🏯 *CLAN SYSTEM*\n"
                "━━━━━━━━━━━━━━━━━━━━━\n\n"
                "You are not in a clan.\n\n"
                "💡 `/clan createclan [name]` — Found a clan\n"
                "💡 `/clan joinclan [name]` — Join one\n"
                "💡 `/clanleaderboard` — Top clans",
                parse_mode='Markdown'
            )
        return

    sub = context.args[0].lower()

    if sub == 'createclan':
        if player.get('clan_id'):
            await update.message.reply_text("❌ You are already in a clan! Leave first.")
            return
        if len(context.args) < 2:
            await update.message.reply_text(
                f"⚔️ *CREATE A CLAN*\n\n"
                f"Usage: `/clan createclan [name]`\n\n"
                f"💸 Cost: *{CLAN_CREATE_COST:,}¥*\n"
                f"💰 Your balance: *{player['yen']:,}¥*",
                parse_mode='Markdown'
            )
            return
        clan_name = ' '.join(context.args[1:])
        if get_clan_by_name(clan_name):
            await update.message.reply_text(f"❌ Clan *{clan_name}* already exists!", parse_mode='Markdown')
            return
        if player['yen'] < CLAN_CREATE_COST:
            needed = 50000 - player['yen']
            await update.message.reply_text(
                f"❌ *Not enough Yen!*\n\n"
                f"╰➤ Cost:     *{CLAN_CREATE_COST:,}¥*\n"
                f"╰➤ You have: *{player['yen']:,}¥*\n"
                f"╰➤ Need:     *{needed:,}¥ more*",
                parse_mode='Markdown'
            )
            return
        clan_id = int(time.time() * 1000)
        col("clans").insert_one({
            "id": clan_id, "name": clan_name,
            "leader_id": user_id, "members": [user_id],
            "xp": 0, "group_link": None, "treasury": [],
            "created_at": datetime.now()
        })
        update_player(user_id, clan_id=clan_id, clan_role='leader', yen=player['yen'] - CLAN_CREATE_COST)
        await update.message.reply_text(
            f"✅ *𝘾𝙇𝘼𝙉 𝘾𝙍𝙀𝘼𝙏𝙀𝘿!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏯 *{clan_name}*\n\n"
            f"💸 Spent: *{CLAN_CREATE_COST:,}¥*\n"
            f"💰 Balance: *{player['yen'] - CLAN_CREATE_COST:,}¥*\n\n"
            f"💡 Invite members with `/clan invite @username`",
            parse_mode='Markdown'
        )

    elif sub == 'joinclan':
        if player.get('clan_id'):
            await update.message.reply_text("❌ Already in a clan! Use `/clan leave` first.")
            return
        if len(context.args) < 2:
            await update.message.reply_text(
                "📖 Usage:\n"
                "  `/clan joinclan [clan name]`\n"
                "  `/clan joinclan [leader telegram ID]`\n\n"
                "Example: `/clan joinclan Hashira Corps`\n"
                "Example: `/clan joinclan 123456789`",
                parse_mode='Markdown'
            )
            return

        arg = ' '.join(context.args[1:]).strip()

        # Try by telegram ID of the leader first
        clan_data = None
        if arg.isdigit():
            leader_id = int(arg)
            clan_data = col("clans").find_one({"leader_id": leader_id})
            if clan_data:
                clan_data.pop("_id", None)

        # Try by clan name
        if not clan_data:
            clan_data = get_clan_by_name(arg)

        if not clan_data:
            await update.message.reply_text(
                f"❌ Clan *{arg}* not found.\n\n"
                f"💡 Type `/joinclan` to see all available clans.",
                parse_mode='Markdown'
            )
            return

        members = get_clan_members(clan_data)
        if len(members) >= CLAN_MAX_MEMBERS:
            await update.message.reply_text(
                f"❌ *{clan_data['name']}* is full! ({len(members)}/{CLAN_MAX_MEMBERS} members)"
            )
            return

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Accept",  callback_data=f"clan_accept_{user_id}_{clan_data['id']}"),
            InlineKeyboardButton("❌ Reject",  callback_data=f"clan_reject_{user_id}_{clan_data['id']}"),
        ]])
        try:
            await context.bot.send_message(
                chat_id=clan_data['leader_id'],
                text=(
                    f"🏯 *JOIN REQUEST*\n"
                    f"━━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚔️ *{player['name']}* wants to join *{clan_data['name']}*!\n\n"
                    f"👥 Members: {len(members)}/{CLAN_MAX_MEMBERS}\n"
                    f"🆔 Their ID: `{user_id}`"
                ),
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            await update.message.reply_text(
                f"✅ *Join request sent to {clan_data['name']}!*\n"
                f"Wait for the leader to accept or reject.\n\n"
                f"👥 Members: {len(members)}/{CLAN_MAX_MEMBERS}",
                parse_mode='Markdown'
            )
        except Exception:
            # Leader blocked the bot or hasn't DM'd it — let them know
            await update.message.reply_text(
                f"❌ *Could not reach the clan leader!*\n\n"
                f"_The leader may have not started the bot in DM. Ask them to message the bot first._"
            , parse_mode='Markdown')

    elif sub == 'invite':
        clan_data = get_clan(player.get('clan_id')) if player.get('clan_id') else None
        if not clan_data or clan_data['leader_id'] != user_id:
            await update.message.reply_text("❌ Only clan leaders can invite members.")
            return
        if len(context.args) < 2:
            await update.message.reply_text("Usage: `/clan invite @username`", parse_mode='Markdown')
            return
        target_username = context.args[1].lstrip('@')
        target = col("players").find_one({"username": {"$regex": f"^{target_username}$", "$options": "i"}})
        if not target:
            await update.message.reply_text(f"❌ Player *@{target_username}* not found.", parse_mode='Markdown')
            return
        if target.get('clan_id'):
            await update.message.reply_text("❌ That player is already in a clan!")
            return
        col("clan_invites").insert_one({
            "clan_id": clan_data['id'], "user_id": target['user_id'],
            "status": "pending", "created_at": datetime.now()
        })
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Accept",  callback_data=f"clan_accept_{target['user_id']}_{clan_data['id']}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"clan_reject_{target['user_id']}_{clan_data['id']}"),
        ]])
        try:
            await context.bot.send_message(
                chat_id=target['user_id'],
                text=f"🏯 *{player['name']}* invites you to join *{clan_data['name']}*!",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            await update.message.reply_text(f"✅ Invite sent to *{target['name']}*!", parse_mode='Markdown')
        except Exception:
            await update.message.reply_text("❌ Could not reach that player.")

    elif sub == 'leave':
        if not player.get('clan_id'):
            await update.message.reply_text("❌ You are not in a clan.")
            return
        clan_data = get_clan(player['clan_id'])
        members   = get_clan_members(clan_data)
        members   = [m for m in members if m != user_id]
        if not members:
            col("clans").delete_one({"id": clan_data['id']})
        else:
            if clan_data['leader_id'] == user_id:
                new_leader = members[0]
                col("clans").update_one({"id": clan_data['id']}, {"$set": {"members": members, "leader_id": new_leader}})
                new_ldr = get_player(new_leader)
                if new_ldr:
                    update_player(new_leader, clan_role='leader')
            else:
                col("clans").update_one({"id": clan_data['id']}, {"$set": {"members": members}})
        update_player(user_id, clan_id=None, clan_role=None)
        await update.message.reply_text(f"🚪 You left *{clan_data['name']}*.", parse_mode='Markdown')

    else:
        await update.message.reply_text(
            "💡 *CLAN COMMANDS*\n\n"
            "`/clan createclan [name]`\n"
            "`/clan joinclan [name]`\n"
            "`/clan invite @username`\n"
            "`/clan leave`\n"
            "`/claninfo`",
            parse_mode='Markdown'
        )


async def clan_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        parts         = query.data.split('_')
        new_member_id = int(parts[2])
        clan_id       = int(parts[3])
    except (ValueError, IndexError):
        await query.answer("❌ Invalid request!", show_alert=True)
        return
    approver_id = query.from_user.id

    clan_data = get_clan(clan_id)
    if not clan_data:
        await query.answer("❌ Clan not found!", show_alert=True)
        return
    if approver_id != clan_data['leader_id']:
        await query.answer("❌ Only the clan leader can accept members!", show_alert=True)
        return

    new_member = get_player(new_member_id)
    if not new_member:
        await query.answer("Player not found!", show_alert=True)
        return

    members = get_clan_members(clan_data)
    if len(members) >= CLAN_MAX_MEMBERS:
        await _safe_edit(query, "❌ Clan is full!")
        return

    members.append(new_member_id)
    col("clans").update_one({"id": clan_id}, {"$set": {"members": members}})
    col("clan_invites").update_one({"clan_id": clan_id, "user_id": new_member_id}, {"$set": {"status": "accepted"}})
    update_player(new_member_id, clan_id=clan_id, clan_role='recruit')

    await _safe_edit(query, 
        f"✅ *{new_member['name']}* has been accepted into *{clan_data['name']}*!"
    )

    group_link = clan_data.get('group_link', '')
    link_line  = f"\n\n🔗 *Join our group:*\n{group_link}" if group_link else "\n\n💡 _Ask your clan leader for the group link._"

    try:
        await context.bot.send_message(
            chat_id=new_member_id,
            text=(
                f"🏯 *𝘾𝙇𝘼𝙉 𝙅𝙊𝙄𝙉𝙀𝘿!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ You have been accepted into\n"
                f"*{clan_data['name']}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏅 Role: *Recruit*\n"
                f"👥 Members: *{len(members)}*"
                f"{link_line}\n\n"
                f"Use /claninfo to see your clan!"
            ),
            parse_mode='Markdown'
        )
    except Exception:
        pass


async def clan_reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        parts         = query.data.split('_')
        new_member_id = int(parts[2])
        clan_id       = int(parts[3])
    except (ValueError, IndexError):
        await query.answer("❌ Invalid request!", show_alert=True)
        return
    col("clan_invites").update_one({"clan_id": clan_id, "user_id": new_member_id}, {"$set": {"status": "rejected"}})
    decliner = get_player(query.from_user.id)
    dname    = decliner['name'] if decliner else "Someone"
    await _safe_edit(query, f"❌ *{dname}* rejected the request.", parse_mode='Markdown')


async def clanleaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clans = list(col("clans").find().sort("xp", -1).limit(10))
    lines = ["🏯 *CLAN LEADERBOARD*\n━━━━━━━━━━━━━━━━━━━━━\n"]
    medals = ['🥇', '🥈', '🥉']
    for i, c in enumerate(clans):
        medal   = medals[i] if i < 3 else f"`{i+1}.`"
        members = get_clan_members(c)
        lines.append(f"{medal} *{c['name']}* — {c.get('xp',0):,} XP | {len(members)} members")
    if not clans:
        lines.append("_No clans yet!_")
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


async def setclanlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id   = update.effective_user.id
    player    = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ You are not in a clan.")
        return
    clan_data = get_clan(player['clan_id'])
    if not clan_data or clan_data['leader_id'] != user_id:
        await update.message.reply_text("❌ Only the clan leader can set the group link.")
        return
    if not context.args:
        current = clan_data.get('group_link', '')
        await update.message.reply_text(
            f"🔗 *SET CLAN GROUP LINK*\n\nCurrent: {current or '_Not set_'}\n\n"
            f"Usage: `/setclanlink https://t.me/+yourlink`",
            parse_mode='Markdown'
        )
        return
    link = context.args[0].strip()
    if not link.startswith('https://t.me/'):
        await update.message.reply_text("❌ Invalid link. Must start with `https://t.me/`", parse_mode='Markdown')
        return
    col("clans").update_one({"id": clan_data['id']}, {"$set": {"group_link": link}})
    await update.message.reply_text(f"✅ *Clan group link updated!*\n\n🔗 {link}", parse_mode='Markdown')


# ── Aliases / extra commands expected by bot.py ──────────────────────────

async def createclan(update, context):
    """Alias: /clan createclan"""
    context.args = ['createclan'] + (context.args or [])
    await clan(update, context)

async def joinclan(update, context):
    """
    /joinclan [clan name]  OR  /clan joinclan [clan name]
    Both work. If no name given, shows usage.
    """
    if not context.args:
        # Show list of clans to join
        clans = list(col("clans").find().sort("xp", -1).limit(10))
        if not clans:
            await update.message.reply_text(
                "🏯 *JOIN A CLAN*\n\n"
                "_No clans exist yet._\n\n"
                "💡 Create one with `/createclan [name]`",
                parse_mode='Markdown'
            )
            return
        lines = ["🏯 *CLANS YOU CAN JOIN*\n━━━━━━━━━━━━━━━━━━━━━\n"]
        for c in clans:
            members = get_clan_members(c)
            full = "🔴 FULL" if len(members) >= CLAN_MAX_MEMBERS else f"👥 {len(members)}/{CLAN_MAX_MEMBERS}"
            lines.append(f"  🏯 *{c['name']}*  —  {full}  ⭐ {c.get('xp',0):,} XP")
        lines.append(f"\n💡 `/joinclan [name]` to send a join request")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return
    context.args = ['joinclan'] + (context.args or [])
    await clan(update, context)

async def leaveclan(update, context):
    context.args = ['leave']
    await clan(update, context)

async def clandisband(update, context):
    from utils.database import get_player, update_player, col, get_clan
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ You are not in a clan.")
        return
    clan_data = get_clan(player['clan_id'])
    if clan_data['leader_id'] != user_id:
        await update.message.reply_text("❌ Only the leader can disband the clan.")
        return
    members = get_clan_members(clan_data)
    for mid in members:
        update_player(mid, clan_id=None, clan_role=None)
    col("clans").delete_one({"id": clan_data['id']})
    await update.message.reply_text(f"💔 *{clan_data['name']}* has been disbanded.", parse_mode='Markdown')

async def claninfo_cmd(update, context):
    """Redirect to claninfo handler"""
    from handlers.claninfo import claninfo as _ci
    await _ci(update, context)

async def clanmembers(update, context):
    from utils.database import get_player, get_clan, col
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ You are not in a clan.")
        return
    clan_data = get_clan(player['clan_id'])
    members   = get_clan_members(clan_data)
    lines = [f"👥 *{clan_data['name']} — Members*\n"]
    for mid in members:
        m = get_player(mid)
        if m:
            role = m.get('clan_role', 'recruit')
            icon = '👑' if mid == clan_data['leader_id'] else ('⚔️' if role == 'officer' else '🔰')
            lines.append(f"{icon} *{m['name']}*")
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')

async def promotevice(update, context):
    from utils.database import get_player, update_player, get_clan, col
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ You are not in a clan.")
        return
    clan_data = get_clan(player['clan_id'])
    if clan_data['leader_id'] != user_id:
        await update.message.reply_text("❌ Only the leader can promote members.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/promotevice @username`", parse_mode='Markdown')
        return
    target_username = context.args[0].lstrip('@')
    target = col("players").find_one({"username": {"$regex": f"^{target_username}$", "$options": "i"}})
    if not target or target.get('clan_id') != clan_data['id']:
        await update.message.reply_text("❌ Player not found in your clan.")
        return
    update_player(target['user_id'], clan_role='officer')
    await update.message.reply_text(f"✅ *{target['name']}* promoted to Officer!", parse_mode='Markdown')

async def demote(update, context):
    from utils.database import get_player, update_player, get_clan, col
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ You are not in a clan.")
        return
    clan_data = get_clan(player['clan_id'])
    if clan_data['leader_id'] != user_id:
        await update.message.reply_text("❌ Only the leader can demote.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/demote @username`", parse_mode='Markdown')
        return
    target_username = context.args[0].lstrip('@')
    target = col("players").find_one({"username": {"$regex": f"^{target_username}$", "$options": "i"}})
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    update_player(target['user_id'], clan_role='recruit')
    await update.message.reply_text(f"✅ *{target['name']}* demoted to Recruit.", parse_mode='Markdown')

async def kick(update, context):
    from utils.database import get_player, update_player, get_clan, col
    user_id   = update.effective_user.id
    player    = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ You are not in a clan.")
        return
    clan_data = get_clan(player['clan_id'])
    if clan_data['leader_id'] != user_id:
        await update.message.reply_text("❌ Only the leader can kick members.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/kick @username`", parse_mode='Markdown')
        return
    target_username = context.args[0].lstrip('@')
    target = col("players").find_one({"username": {"$regex": f"^{target_username}$", "$options": "i"}})
    if not target or target.get('clan_id') != clan_data['id']:
        await update.message.reply_text("❌ Player not found in your clan.")
        return
    members = get_clan_members(clan_data)
    members = [m for m in members if m != target['user_id']]
    col("clans").update_one({"id": clan_data['id']}, {"$set": {"members": members}})
    update_player(target['user_id'], clan_id=None, clan_role=None)
    await update.message.reply_text(f"✅ *{target['name']}* kicked from the clan.", parse_mode='Markdown')

async def renameclan(update, context):
    from utils.database import get_player, get_clan, col
    user_id   = update.effective_user.id
    player    = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ Not in a clan.")
        return
    clan_data = get_clan(player['clan_id'])
    if clan_data['leader_id'] != user_id:
        await update.message.reply_text("❌ Leader only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/renameclan [new name]`", parse_mode='Markdown')
        return
    new_name = ' '.join(context.args)
    col("clans").update_one({"id": clan_data['id']}, {"$set": {"name": new_name}})
    await update.message.reply_text(f"✅ Clan renamed to *{new_name}*!", parse_mode='Markdown')

async def clanannounce(update, context):
    from utils.database import get_player, get_clan
    user_id   = update.effective_user.id
    player    = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ Not in a clan.")
        return
    clan_data = get_clan(player['clan_id'])
    if clan_data['leader_id'] != user_id:
        await update.message.reply_text("❌ Leader only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/clanannounce [message]`", parse_mode='Markdown')
        return
    msg = ' '.join(context.args)
    members = get_clan_members(clan_data)
    sent = 0
    for mid in members:
        try:
            await context.bot.send_message(
                chat_id=mid,
                text=f"📢 *{clan_data['name']} ANNOUNCEMENT*\n\n{msg}",
                parse_mode='Markdown'
            )
            sent += 1
        except Exception:
            pass
    await update.message.reply_text(f"✅ Announced to *{sent}* members.", parse_mode='Markdown')


# ── /clanslogan ───────────────────────────────────────────────────────────
async def clanslogan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/clanslogan [text] — Set your clan's slogan."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ You must be in a clan.")
        return
    if player.get('clan_role') not in ('leader', 'chief'):
        await update.message.reply_text("❌ Only the Leader or Chief can set the slogan.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/clanslogan [your slogan text]`", parse_mode='Markdown')
        return
    slogan = ' '.join(context.args).strip()[:100]
    col("clans").update_one({"id": player['clan_id']}, {"$set": {"slogan": slogan}})
    await update.message.reply_text(
        f"✅ Clan slogan set:\n✨ _\"{slogan}\"_", parse_mode='Markdown'
    )


# ── /clanimage ────────────────────────────────────────────────────────────
async def clanimage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/clanimage [url] — Set clan image (shown in /claninfo)."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ You must be in a clan.")
        return
    if player.get('clan_role') not in ('leader', 'chief'):
        await update.message.reply_text("❌ Only Leader or Chief can set the clan image.")
        return
    if not context.args:
        await update.message.reply_text(
            "Usage: `/clanimage [image URL]`\n"
            "Example: `/clanimage https://i.imgur.com/example.jpg`",
            parse_mode='Markdown'
        )
        return
    url = context.args[0].strip()
    if not url.startswith('http'):
        await update.message.reply_text("❌ Invalid URL. Must start with http:// or https://")
        return
    col("clans").update_one({"id": player['clan_id']}, {"$set": {"image_url": url}})
    await update.message.reply_text("✅ Clan image updated! View with `/claninfo`", parse_mode='Markdown')


# ── /clanreq ─────────────────────────────────────────────────────────────
async def clanreq(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /clanreq                       — view current requirements
    /clanreq level [n]             — set minimum level
    /clanreq xp [n]                — set minimum XP
    /clanreq faction [slayer|demon]— faction restriction
    /clanreq clear                 — remove all requirements
    """
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player or not player.get('clan_id'):
        await update.message.reply_text("❌ You must be in a clan.")
        return
    if player.get('clan_role') not in ('leader', 'chief'):
        await update.message.reply_text("❌ Only Leader or Chief can set requirements.")
        return

    clan = col("clans").find_one({"id": player['clan_id']})
    req  = clan.get('requirements', {}) if clan else {}

    if not context.args:
        lines = ["📋 *CLAN REQUIREMENTS*", "━━━━━━━━━━━━━━━━━━━━━"]
        if req:
            for k, v in req.items():
                lines.append(f"  ╰➤ {k}: *{v}*")
        else:
            lines.append("  ╰➤ _No requirements set_")
        lines += [
            "", "━━━━━━━━━━━━━━━━━━━━━",
            "💡 `/clanreq level [n]` — Min level",
            "💡 `/clanreq xp [n]` — Min XP",
            "💡 `/clanreq faction [slayer|demon]`",
            "💡 `/clanreq clear` — Remove all",
        ]
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    sub = context.args[0].lower()

    if sub == 'clear':
        col("clans").update_one({"id": player['clan_id']}, {"$set": {"requirements": {}}})
        await update.message.reply_text("✅ All clan requirements cleared.")
        return

    if sub == 'level' and len(context.args) > 1:
        try:
            n = int(context.args[1])
            req['min_level'] = n
            col("clans").update_one({"id": player['clan_id']}, {"$set": {"requirements": req}})
            await update.message.reply_text(f"✅ Min level set to *{n}*", parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("❌ Invalid number.")
        return

    if sub == 'xp' and len(context.args) > 1:
        try:
            n = int(context.args[1])
            req['min_xp'] = n
            col("clans").update_one({"id": player['clan_id']}, {"$set": {"requirements": req}})
            await update.message.reply_text(f"✅ Min XP set to *{n:,}*", parse_mode='Markdown')
        except ValueError:
            await update.message.reply_text("❌ Invalid number.")
        return

    if sub == 'faction' and len(context.args) > 1:
        fac = context.args[1].lower()
        if fac not in ('slayer', 'demon'):
            await update.message.reply_text("❌ Faction must be `slayer` or `demon`", parse_mode='Markdown')
            return
        req['faction'] = fac
        col("clans").update_one({"id": player['clan_id']}, {"$set": {"requirements": req}})
        await update.message.reply_text(f"✅ Faction requirement: *{fac}* only", parse_mode='Markdown')
        return

    await update.message.reply_text("❓ Unknown option. Use `/clanreq` to see options.", parse_mode='Markdown')
