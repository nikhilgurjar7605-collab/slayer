import json
import asyncio
import html
import time
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from datetime import datetime, timedelta
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, get_all_players, get_inventory, add_item, col, get_bot_counters, get_total_yen_circulated
from handlers.logs import log_action
from config import OWNER_ID, SUDO_ADMIN_IDS

broadcast_status = {}
broadcast_reply_cache = {}


def is_owner(user_id):
    """True for real owner OR an active temp owner."""
    if user_id == OWNER_ID:
        return True
    # Lazy import to avoid circular imports at module load time
    try:
        from handlers.temp_owner import is_temp_owner
        return is_temp_owner(user_id)
    except Exception:
        return False


def has_admin_access(user_id):
    """True for real owner, active temp owner, or any sudo admin."""
    if is_owner(user_id):
        return True
    doc = col("admins").find_one({"user_id": user_id})
    return doc is not None


def _find_player(arg):
    """Find player by user_id or username."""
    try:
        uid = int(arg)
        return col("players").find_one({"user_id": uid})
    except ValueError:
        uname = arg.lstrip('@')
        return col("players").find_one({"username": {"$regex": f"^{uname}$", "$options": "i"}})


def _resolve_add_target(update: Update, context):
    if update.message and update.message.reply_to_message:
        target = col("players").find_one({"user_id": update.message.reply_to_message.from_user.id})
        return target, list(context.args or [])
    if context.args:
        target = _find_player(context.args[0])
        return target, list(context.args[1:])
    return None, []


def _resolve_item_name_and_type(item_name: str):
    """Best-effort item lookup so admin grants keep the correct item type."""
    from config import SHOP_ITEMS, REGION_ENEMIES, SLAYER_ENEMIES, DEMON_ENEMIES

    raw_name = str(item_name or "").strip()
    query = raw_name.lower()
    if not query:
        return raw_name, "item"

    catalog = {}

    for cat, items in SHOP_ITEMS.items():
        item_type = "sword" if cat == "swords" else ("armor" if cat == "armor" else "item")
        for item in items:
            catalog[item["name"].lower()] = (item["name"], item_type)

    for region in REGION_ENEMIES.values():
        for enemy in region.get("enemies", []):
            for drop in enemy.get("drops", []):
                catalog.setdefault(drop.lower(), (drop, "material"))

    for enemy in SLAYER_ENEMIES + DEMON_ENEMIES:
        for drop in enemy.get("drops", []):
            catalog.setdefault(drop.lower(), (drop, "material"))

    if query in catalog:
        return catalog[query]

    if query.startswith("scroll:"):
        return raw_name, "scroll"

    for key, value in catalog.items():
        if query in key:
            return value

    return raw_name, "item"

async def myid(update: Update, context):
    uid = update.effective_user.id
    await update.message.reply_text(f"🆔 Your Telegram ID: `{uid}`", parse_mode='Markdown')


async def addsudo(update: Update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/addsudo @username`", parse_mode='Markdown')
        return
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    col("admins").update_one({"user_id": target["user_id"]},
                              {"$setOnInsert": {"user_id": target["user_id"]}}, upsert=True)
    await update.message.reply_text(f"✅ *{target['name']}* added as admin.", parse_mode='Markdown')


async def removesudo(update: Update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/removesudo @username`", parse_mode='Markdown')
        return
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    col("admins").delete_one({"user_id": target["user_id"]})
    await update.message.reply_text(f"✅ *{target['name']}* removed from admins.", parse_mode='Markdown')


async def listadmins(update: Update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Owner only.")
        return
    admins = list(col("admins").find())
    lines = ["👑 *ADMIN LIST*\n━━━━━━━━━━━━━━━━━━━━━"]
    for a in admins:
        p = get_player(a["user_id"])
        name = p['name'] if p else f"ID:{a['user_id']}"
        lines.append(f"• *{name}* (`{a['user_id']}`)")
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


async def ban(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/ban @username [reason]`", parse_mode='Markdown')
        return
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    reason = ' '.join(context.args[1:]) or "No reason"
    col("players").update_one({"user_id": target["user_id"]}, {"$set": {"banned": 1, "ban_reason": reason}})
    log_action(update.effective_user.id, "ban", target["user_id"], target["name"], f"Reason: {reason}")
    await update.message.reply_text(f"✅ *{target['name']}* banned.\nReason: _{reason}_", parse_mode='Markdown')


async def unban(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/unban @username`", parse_mode='Markdown')
        return
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    col("players").update_one({"user_id": target["user_id"]}, {"$set": {"banned": 0, "ban_reason": None}})
    log_action(update.effective_user.id, "unban", target["user_id"], target["name"])
    await update.message.reply_text(f"✅ *{target['name']}* unbanned.", parse_mode='Markdown')


async def givexp(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if len(context.args or []) < 2:
        await update.message.reply_text("Usage: `/givexp @user [amount]`", parse_mode='Markdown')
        return
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return
    update_player(target["user_id"], xp=target.get("xp", 0) + amount)
    log_action(update.effective_user.id, "givexp", target["user_id"], target["name"], f"+{amount:,} XP")
    await update.message.reply_text(f"✅ Gave *{amount:,} XP* to *{target['name']}*.", parse_mode='Markdown')


async def giveyen(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if len(context.args or []) < 2:
        await update.message.reply_text("Usage: `/giveyen @user [amount]`", parse_mode='Markdown')
        return
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return
    update_player(target["user_id"], yen=target.get("yen", 0) + amount)
    log_action(update.effective_user.id, "giveyen", target["user_id"], target["name"], f"{amount:,}¥")
    await update.message.reply_text(f"✅ Gave *{amount:,}¥* to *{target['name']}*.", parse_mode='Markdown')


async def giveitem(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if len(context.args or []) < 2:
        await update.message.reply_text("Usage: `/giveitem @user [item name]`", parse_mode='Markdown')
        return
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    item_name = ' '.join(context.args[1:])
    add_item(target["user_id"], item_name, 'item')
    log_action(update.effective_user.id, "giveitem", target["user_id"], target["name"], item_name)
    await update.message.reply_text(f"✅ Gave *{item_name}* to *{target['name']}*.", parse_mode='Markdown')


async def giveitem(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if len(context.args or []) < 2:
        await update.message.reply_text(
            "Usage: `/giveitem @user [item name]`\n"
            "Or: `/giveitem @user [item name] [qty]`",
            parse_mode='Markdown'
        )
        return

    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("âŒ Player not found.")
        return

    item_args = list(context.args[1:])
    quantity = 1
    if len(item_args) >= 2:
        try:
            quantity = int(item_args[-1])
            item_args = item_args[:-1]
        except ValueError:
            quantity = 1

    item_name = ' '.join(item_args).strip()
    if not item_name:
        await update.message.reply_text("âŒ Item name is required.", parse_mode='Markdown')
        return

    quantity = max(1, min(quantity, 9999))
    real_name, item_type = _resolve_item_name_and_type(item_name)
    add_item(target["user_id"], real_name, item_type, quantity)

    detail = f"{real_name} x{quantity}" if quantity > 1 else real_name
    log_action(update.effective_user.id, "giveitem", target["user_id"], target["name"], detail)

    qty_text = f" Ã— {quantity}" if quantity > 1 else ""
    await update.message.reply_text(
        f"âœ… Gave *{real_name}*{qty_text} to *{target['name']}*.\n"
        f"Type: `{item_type}`",
        parse_mode='Markdown'
    )


async def resetplayer(update: Update, context):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("❌ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/resetplayer @username`", parse_mode='Markdown')
        return
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    uid = target["user_id"]
    col("players").delete_one({"user_id": uid})
    col("inventory").delete_many({"user_id": uid})
    col("battle_state").delete_many({"user_id": uid})
    col("skill_tree").delete_many({"user_id": uid})
    log_action(update.effective_user.id, "resetplayer", uid, target["name"])
    await update.message.reply_text(f"✅ *{target['name']}* has been reset.", parse_mode='Markdown')


async def announce(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/announce [message]`", parse_mode='Markdown')
        return
    msg = ' '.join(context.args)
    players = get_all_players()
    # Filter banned players
    active_players = [p for p in players if not p.get('banned')]
    sent = 0
    failed = 0
    import asyncio
    status_msg = await update.message.reply_text(
        f"📢 Sending to *{len(active_players)}* players...", parse_mode='Markdown')
    for p in active_players:
        try:
            # Send as plain text so admin's message is never mangled by Markdown parser
            # Admin can use their own formatting freely
            await context.bot.send_message(
                chat_id=p['user_id'],
                text=(
                    "📢 SERVER ANNOUNCEMENT\n"
                    "━━━━━━━━━━━━━━━━━━━━━\n\n"
                    + msg +
                    "\n\n━━━━━━━━━━━━━━━━━━━━━\n"
                    "Demon Slayer RPG"
                ),
            )
            sent += 1
        except Exception:
            failed += 1
        # Rate limit: 30 msgs/sec max, stay safe at 25
        if sent % 25 == 0:
            await asyncio.sleep(1)
    try:
        await status_msg.edit_text(
            f"✅ *Announced!*\n\n📊 Sent: *{sent}*\n❌ Failed: *{failed}*\n🚫 Skipped (banned): *{len(players)-len(active_players)}*",
            parse_mode='Markdown'
        )
    except Exception:
        await update.message.reply_text(f"✅ Announced to *{sent}/{len(active_players)}* players.", parse_mode='Markdown')


async def botstats(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    total     = col("players").count_documents({})
    slayers   = col("players").count_documents({"faction": "slayer"})
    demons    = col("players").count_documents({"faction": "demon"})
    banned    = col("players").count_documents({"banned": 1})
    total_yen = get_total_yen_circulated()
    counters  = get_bot_counters()
    sp_spent  = counters.get("sp_spent", 0)
    await update.message.reply_text(
        f"📊 *BOT STATS*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total players: *{total}*\n"
        f"🗡️ Slayers: *{slayers}*\n"
        f"👹 Demons:  *{demons}*\n"
        f"🚫 Banned:  *{banned}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Yen in circulation: *{total_yen:,}¥*\n"
        f"💠 Total SP spent: *{sp_spent:,} SP*",
        parse_mode='Markdown'
    )


async def startraid(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return

    boss_name = ' '.join(context.args) if context.args else "Muzan Kibutsuji"
    col("raids").update_many({"status": {"$in": ["waiting", "active"]}}, {"$set": {"status": "closed"}})

    import time as _t
    rid = int(_t.time())
    col("raids").insert_one({
        "id": rid, "boss_name": boss_name,
        "boss_hp": 500000, "boss_max_hp": 500000,
        "boss_atk": 80, "min_players": 20, "status": "waiting"
    })

    await update.message.reply_text(
        f"✅ Raid started: *{boss_name}*\nBroadcasting to all players...",
        parse_mode='Markdown'
    )

    # ── Broadcast to ALL players in DM ───────────────────────────────────
    raid_msg = (
        f"🔴 *RAID ALERT!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"☠️ *{boss_name.upper()}* has appeared!\n\n"
        f"❤️ HP: *500,000*\n"
        f"👥 Needs *20 warriors* to activate\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ Use `/joinraid` to join the battle!\n"
        f"_All participants earn XP, Yen & Boss Shards!_"
    )

    players = list(col("players").find({}, {"user_id": 1}))
    sent = 0
    failed = 0
    for p in players:
        try:
            await context.bot.send_message(
                chat_id=p["user_id"],
                text=raid_msg,
                parse_mode='Markdown'
            )
            sent += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"📢 *Raid broadcast complete!*\n"
        f"✅ Sent: *{sent}* players\n"
        f"❌ Failed: *{failed}* (blocked/inactive)",
        parse_mode='Markdown'
    )


async def stopraid(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    col("raids").update_many({"status": {"$in": ["waiting", "active"]}}, {"$set": {"status": "cancelled"}})
    await update.message.reply_text("✅ All active raids cancelled.", parse_mode='Markdown')


async def addauction(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if len(context.args or []) < 2:
        await update.message.reply_text("Usage: `/addauction [hours] [item name]`", parse_mode='Markdown')
        return
    try:
        hours = int(context.args[0])
        item_name = ' '.join(context.args[1:])
    except ValueError:
        await update.message.reply_text("❌ Invalid format.")
        return
    ends_at = datetime.utcnow() + timedelta(hours=hours)
    col("auctions").insert_one({
        "item_name": item_name, "item_emoji": "🎴",
        "current_bid": 0, "highest_bidder": None,
        "ends_at": ends_at, "status": "active"
    })
    await update.message.reply_text(f"✅ Auction added: *{item_name}* ends in {hours}h", parse_mode='Markdown')


async def addmission(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if len(context.args or []) < 4:
        await update.message.reply_text("Usage: `/addmission [difficulty] [xp] [yen] [name]`", parse_mode='Markdown')
        return
    try:
        difficulty = context.args[0]
        xp  = int(context.args[1])
        yen = int(context.args[2])
        name = ' '.join(context.args[3:])
    except ValueError:
        await update.message.reply_text("❌ Invalid format.")
        return
    col("custom_missions").insert_one({
        "difficulty": difficulty, "name": name,
        "xp": xp, "yen": yen, "description": name,
        "added_by": update.effective_user.id, "active": 1
    })
    await update.message.reply_text(f"✅ Mission added: *{name}*", parse_mode='Markdown')


async def removemission(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/removemission [mission name]`", parse_mode='Markdown')
        return
    name = ' '.join(context.args)
    col("custom_missions").update_one({"name": {"$regex": name, "$options": "i"}}, {"$set": {"active": 0}})
    await update.message.reply_text(f"✅ Mission *{name}* deactivated.", parse_mode='Markdown')


async def listmissions(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    missions = list(col("custom_missions").find({"active": 1}))
    if not missions:
        await update.message.reply_text("No active custom missions.")
        return
    lines = ["📋 *CUSTOM MISSIONS*\n"]
    for m in missions:
        lines.append(f"• *{m['name']}* — {m['xp']} XP / {m['yen']}¥ [{m['difficulty']}]")
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


async def openblackmarket(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    col("black_market").update_one(
        {"item_name": "__OPEN__"},
        {"$set": {"item_name": "__OPEN__", "price": 0, "stock": 1, "status": "active"}},
        upsert=True
    )
    await update.message.reply_text("✅ Black Market force-opened!", parse_mode='Markdown')


async def closeblackmarket(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    col("black_market").delete_many({"item_name": "__OPEN__"})
    await update.message.reply_text("✅ Black Market forced closed.", parse_mode='Markdown')


async def addblackmarket(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if len(context.args or []) < 3:
        await update.message.reply_text(
            "📖 *ADD BLACK MARKET ITEM*\n\n"
            "Usage: `/addblackmarket [price] [stock] [item name]`\n\n"
            "Examples:\n"
            "  `/addblackmarket 50000 3 Boss Shard`\n"
            "  `/addblackmarket 150000 1 Muzan Blood`\n\n"
            "💡 Use `/openblackmarket` to force-open\n"
            "💡 Use `/closeblackmarket` to force-close",
            parse_mode='Markdown')
        return
    try:
        price     = int(context.args[0])
        stock     = int(context.args[1])
        item_name = ' '.join(context.args[2:])
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Usage: `/addblackmarket [price] [stock] [name]`", parse_mode='Markdown')
        return
    if price <= 0 or stock <= 0:
        await update.message.reply_text("❌ Price and stock must be greater than 0.")
        return
    # Determine item_type from known items
    from config import SHOP_ITEMS
    item_type = 'material'  # default
    for cat, items in SHOP_ITEMS.items():
        for i in items:
            if i['name'].lower() == item_name.lower():
                item_type = 'sword' if cat == 'swords' else ('armor' if cat == 'armor' else 'item')
                break
    expires_at = datetime.utcnow() + timedelta(days=1)
    col("black_market").insert_one({
        "item_name": item_name, "item_type": item_type,
        "price": price, "stock": stock,
        "expires_at": expires_at, "status": "active"
    })
    await update.message.reply_text(
        f"✅ *Added to Black Market!*\n\n"
        f"📦 *{item_name}* × {stock}\n"
        f"💰 Price: *{price:,}¥*\n"
        f"🏷️ Type: `{item_type}`\n\n"
        f"💡 Use `/blackmarket` to see the listing.",
        parse_mode='Markdown')



async def admin_unstuck(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    if not context.args:
        await update.message.reply_text("Usage: `/adminunstuck @username`", parse_mode='Markdown')
        return
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    from utils.database import clear_battle_state
    clear_battle_state(target["user_id"])
    col("duels").update_many(
        {"$or": [{"challenger_id": target["user_id"]}, {"target_id": target["user_id"]}], "status": "active"},
        {"$set": {"status": "abandoned"}}
    )
    await update.message.reply_text(f"✅ *{target['name']}* unstuck.", parse_mode='Markdown')


async def adminhelp(update: Update, context):
    if not has_admin_access(update.effective_user.id):
        return
    await update.message.reply_text(
        "⚙️ *ADMIN COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "*Owner only:*\n"
        "`/addsudo` ` /removesudo` ` /listadmins`\n"
        "`/ban` ` /unban` ` /resetplayer`\n\n"
        "*Admin + Owner:*\n"
        "`/add` ` /givexp` ` /giveyen` ` /giveitem`\n"
        "`/announce` ` /bcast` ` /botstats`\n"
        "`/startraid` ` /stopraid`\n"
        "`/addauction` ` /addmission` ` /removemission` ` /listmissions`\n"
        "`/openblackmarket` ` /closeblackmarket` ` /addblackmarket`\n"
        "`/adminunstuck`\n"
        "`/bankgiveaway 24hr|15m|25s`\n"
        "`/banktax 0.1%` _(reply to user)_",
        parse_mode='Markdown'
    )


async def giveultimate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Give Absolute Biokinesis to a demon player — OWNER ONLY. Only 1 can exist."""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner only. This is the ULTRA LEGENDARY ability.")
        return

    if not context.args:
        # Check who currently owns it
        current = col("players").find_one({"style": "Absolute Biokinesis"})
        if current:
            await update.message.reply_text(
                f"👁️ *ABSOLUTE BIOKINESIS STATUS*\n\n"
                f"Current owner: *{current['name']}* (`{current['user_id']}`)\n\n"
                f"Only ONE player in the game can hold this.\n"
                f"Usage: `/giveultimate @username` to transfer it.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                f"👁️ *ABSOLUTE BIOKINESIS*\n\n"
                f"Currently: *No owner*\n\n"
                f"Usage: `/giveultimate @username`",
                parse_mode='Markdown'
            )
        return

    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    if target.get('faction') != 'demon':
        await update.message.reply_text("❌ Only demons can receive Absolute Biokinesis.")
        return

    # Remove from any current owner
    col("players").update_many(
        {"style": "Absolute Biokinesis"},
        {"$set": {"style": "Blood Whip", "style_emoji": "🩸"}}
    )

    # Give to new owner
    col("players").update_one(
        {"user_id": target['user_id']},
        {"$set": {"style": "Absolute Biokinesis", "style_emoji": "👁️"}}
    )
    log_action(update.effective_user.id, "giveultimate", target["user_id"], target["name"], "Absolute Biokinesis")

    await update.message.reply_text(
        f"👁️ *ABSOLUTE BIOKINESIS GRANTED*\n\n"
        f"*{target['name']}* is now the Demon King.\n\n"
        f"_All others who held it have been reverted to Blood Whip._",
        parse_mode='Markdown'
    )

    try:
        await context.bot.send_message(
            chat_id=target['user_id'],
            text=(
                f"👁️ *𝘼𝘽𝙎𝙊𝙇𝙐𝙏𝙀 𝘽𝙄𝙊𝙆𝙄𝙉𝙀𝙎𝙄𝙎*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"🌑 *ULTRA LEGENDARY*\n\n"
                f"You have been chosen as the *Demon King*.\n"
                f"Muzan's true power now flows through you.\n\n"
                f"_Only one being in the world can wield this._\n"
                f"━━━━━━━━━━━━━━━━━━━━━"
            ),
            parse_mode='Markdown'
        )
    except Exception:
        pass


async def admin_give(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick /give @user [amount] command - admin shortcut for giveyen."""
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if len(context.args or []) < 2:
        await update.message.reply_text(
            "💰 *GIVE YEN*\n\n"
            "Usage: `/give @username [amount]`\n"
            "Example: `/give @Tanjiro 5000`",
            parse_mode='Markdown'
        )
        return

    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    try:
        amount = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid amount.")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Amount must be positive.")
        return

    update_player(target["user_id"], yen=target.get("yen", 0) + amount)

    await update.message.reply_text(
        f"✅ *Given {amount:,}¥ to {target['name']}*\n\n"
        f"💰 Their new balance: *{target.get('yen',0) + amount:,}¥*",
        parse_mode='Markdown'
    )

    try:
        await context.bot.send_message(
            chat_id=target['user_id'],
            text=(
                f"🎁 *𝙔𝙀𝙉 𝙍𝙀𝘾𝙀𝙄𝙑𝙀𝘿!*\n\n"
                f"╰➤ *+{amount:,}¥* from Admin\n"
                f"💰 Balance: *{target.get('yen',0) + amount:,}¥*"
            ),
            parse_mode='Markdown'
        )
    except Exception:
        pass



async def activeusers(update, context):
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("admin only")
        return
    from datetime import datetime, timedelta
    now = datetime.now()
    total   = col("players").count_documents({})
    banned  = col("players").count_documents({"banned": 1})
    slayers = col("players").count_documents({"faction": "slayer"})
    demons  = col("players").count_documents({"faction": "demon"})
    in_bat  = col("battle_state").count_documents({"in_combat": 1})
    d1  = (now - timedelta(days=1)).isoformat()
    d7  = (now - timedelta(days=7)).isoformat()
    d30 = (now - timedelta(days=30)).isoformat()
    a24 = col("players").count_documents({"last_daily": {"$gte": d1}})
    a7  = col("players").count_documents({"last_daily": {"$gte": d7}})
    a30 = col("players").count_documents({"last_daily": {"$gte": d30}})
    top = list(col("players").aggregate([
        {"$group": {"_id": "$style", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 3}
    ]))
    slines = ""
    for s in top:
        slines += "  ╰➤ " + str(s["_id"]) + ": " + str(s["count"]) + " players\n"

    await update.message.reply_text(
        "╔══════════════════════╗\n"
        "      📊 𝘼𝘾𝙏𝙄𝙑𝙀 𝙐𝙎𝙀𝙍𝙎\n"
        "╚══════════════════════╝\n\n"
        "👥 Total: *" + str(total) + "*  🚫 Banned: *" + str(banned) + "*\n"
        "🗡️ Slayers: *" + str(slayers) + "*  👹 Demons: *" + str(demons) + "*\n\n"
        "📅 *Activity (by daily claim):*\n"
        "  24h: *" + str(a24) + "*  |  7d: *" + str(a7) + "*  |  30d: *" + str(a30) + "*\n\n"
        "⚔️ In battle right now: *" + str(in_bat) + "*\n\n"
        "🌀 *Top Styles:*\n"
        + slines,
        parse_mode="Markdown"
    )


async def givesp(update, context):
    """Give SP to a specific user or all users. Admin only."""
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args:
        await update.message.reply_text(
            "💠 *GIVE SKILL POINTS*\n\n"
            "Usage:\n"
            "`/givesp @user [amount]` — give SP to one player\n"
            "`/givesp all [amount]` — give SP to ALL players\n\n"
            "Examples:\n"
            "`/givesp @Tanjiro 5`\n"
            "`/givesp all 3`",
            parse_mode='Markdown'
        )
        return

    target_arg = context.args[0].lower()
    try:
        amount = int(context.args[1]) if len(context.args) > 1 else 1
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Invalid amount.")
        return

    if amount < 1:
        await update.message.reply_text("❌ Amount must be at least 1.")
        return

    # ── Give to ALL players ──────────────────────────────────────────────
    if target_arg == "all":
        result = col("players").update_many(
            {},
            {"$inc": {"skill_points": amount}}
        )
        count = result.modified_count

        log_action(update.effective_user.id, "givesp_all", None, "ALL", f"+{amount} SP to {count} players")

        await update.message.reply_text(
            f"✅ *SP GIVEN TO ALL PLAYERS!*\n\n"
            f"💠 *+{amount} SP* → *{count} players*\n\n"
            f"_All players received {amount} Skill Point(s)._",
            parse_mode='Markdown'
        )

        # Announce to all players
        try:
            players = list(col("players").find({}, {"user_id": 1, "name": 1}))
            sent = 0
            for p in players:
                try:
                    await context.bot.send_message(
                        chat_id=p["user_id"],
                        text=(
                            f"🎁 *SP REWARD!*\n\n"
                            f"💠 *+{amount} Skill Point(s)* added to your account!\n\n"
                            f"Use /skilltree to spend your SP."
                        ),
                        parse_mode='Markdown'
                    )
                    sent += 1
                except Exception:
                    pass
            await update.message.reply_text(f"📨 Notified *{sent}/{count}* players.", parse_mode='Markdown')
        except Exception as e:
            await update.message.reply_text(f"⚠️ Could not notify players: {e}")
        return

    # ── Give to ONE player ───────────────────────────────────────────────
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    col("players").update_one(
        {"user_id": target["user_id"]},
        {"$inc": {"skill_points": amount}}
    )

    new_sp = target.get("skill_points", 0) + amount
    log_action(update.effective_user.id, "givesp", target["user_id"], target["name"], f"+{amount} SP")

    await update.message.reply_text(
        f"✅ *SP GIVEN!*\n\n"
        f"💠 *+{amount} SP* → *{target['name']}*\n"
        f"📊 Their SP: *{new_sp}*",
        parse_mode='Markdown'
    )

    try:
        await context.bot.send_message(
            chat_id=target["user_id"],
            text=(
                f"🎁 *SP RECEIVED!*\n\n"
                f"💠 *+{amount} Skill Point(s)* from admin!\n"
                f"📊 Your SP: *{new_sp}*\n\n"
                f"Use /skilltree to spend them."
            ),
            parse_mode='Markdown'
        )
    except Exception:
        pass


# ── BACKUP / RESTORE ──────────────────────────────────────────────────────
async def giveslayermark(update, context):
    """Admin: /giveslayermark [user_id|@username] — grant Slayer Mark instantly."""
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/giveslayermark [user_id or @username]`", parse_mode='Markdown')
        return
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    if target.get('faction') != 'slayer':
        await update.message.reply_text("❌ This player is a Demon — use `/givedemonmark` instead.", parse_mode='Markdown')
        return
    if target.get('slayer_mark'):
        await update.message.reply_text(f"⚠️ *{target['name']}* already has Slayer Mark.", parse_mode='Markdown')
        return
    tid = target['user_id']
    new_str    = target['str_stat'] + 20
    new_spd    = target['spd'] + 15
    new_max_hp = target['max_hp'] + 50
    update_player(tid, slayer_mark=1, str_stat=new_str, spd=new_spd,
                  max_hp=new_max_hp, hp=new_max_hp)
    try:
        await context.bot.send_message(tid,
            "🔥 *SLAYER MARK GRANTED BY ADMIN!*\n\n"
            "The mark blazes on your skin!\n\n"
            "✅ STR +20 | SPD +15 | Max HP +50\n"
            "💨 Technique DMG +25%",
            parse_mode='Markdown')
    except Exception: pass
    await update.message.reply_text(
        f"✅ Slayer Mark granted to *{target['name']}*.",
        parse_mode='Markdown')


async def givedemonmark(update, context):
    """Admin: /givedemonmark [user_id|@username] — grant Demon Mark instantly."""
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/givedemonmark [user_id or @username]`", parse_mode='Markdown')
        return
    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    if target.get('faction') != 'demon':
        await update.message.reply_text("❌ This player is a Slayer — use `/giveslayermark` instead.", parse_mode='Markdown')
        return
    if target.get('demon_mark'):
        await update.message.reply_text(f"⚠️ *{target['name']}* already has Demon Mark.", parse_mode='Markdown')
        return
    tid = target['user_id']
    new_str    = target['str_stat'] + 25
    new_spd    = target['spd'] + 18
    new_max_hp = target['max_hp'] + 60
    update_player(tid, demon_mark=1, str_stat=new_str, spd=new_spd,
                  max_hp=new_max_hp, hp=new_max_hp)
    try:
        await context.bot.send_message(tid,
            "🔴 *DEMON MARK GRANTED BY ADMIN!*\n\n"
            "The mark of the Demon King is yours!\n\n"
            "✅ STR +25 | SPD +18 | Max HP +60\n"
            "🔴 Combat DMG +20%",
            parse_mode='Markdown')
    except Exception: pass
    await update.message.reply_text(
        f"✅ Demon Mark granted to *{target['name']}*.",
        parse_mode='Markdown')


async def master(update, context):
    """
    Owner only:
      /master @username              — give EVERYTHING (max stats, all skills, marks)
      /master @username item amount  — give a specific item in specific amount
    Examples:
      /master @tanjiro
      /master @tanjiro "Boss Shard" 50
      /master @tanjiro "Full Recovery Gourd" 100
    """
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner only.")
        return

    args = context.args
    if not args:
        # Build item list for help
        from config import SHOP_ITEMS, REGION_ENEMIES, SLAYER_ENEMIES, DEMON_ENEMIES
        shop_names = [i['name'] for cat in SHOP_ITEMS.values() for i in cat]
        await update.message.reply_text(
            "👑 *MASTER COMMAND — OWNER ONLY*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "*Usage 1 — Give everything:*\n"
            "  `/master @username`\n\n"
            "*Usage 2 — Give specific item:*\n"
            "  `/master @username Item Name amount`\n\n"
            "*Examples:*\n"
            "  `/master @tanjiro`\n"
            "  `/master @tanjiro Boss Shard 50`\n"
            "  `/master @tanjiro Full Recovery Gourd 99`\n"
            "  `/master @tanjiro Jet Black Nichirin Blade 1`\n\n"
            f"*Shop items:* {', '.join(shop_names)}\n"
            "_Also accepts any drop item name from the game._",
            parse_mode='Markdown')
        return

    # Parse: first arg is @username or user_id
    target = _find_player(args[0])
    if not target:
        await update.message.reply_text(f"❌ Player *{args[0]}* not found.", parse_mode='Markdown')
        return

    tid     = target['user_id']
    faction = target.get('faction', 'slayer')

    # ── MODE 2: /master @user Item Name amount ──────────────────────────
    if len(args) >= 3:
        # Last arg = amount if numeric, otherwise default 1
        try:
            amount = int(args[-1])
            item_name_parts = args[1:-1]
        except ValueError:
            amount = 1
            item_name_parts = args[1:]

        item_name = ' '.join(item_name_parts).strip()
        amount    = max(1, min(amount, 9999))   # cap at 9999

        # Determine item type from known lists
        from config import SHOP_ITEMS, REGION_ENEMIES, SLAYER_ENEMIES, DEMON_ENEMIES
        from utils.database import add_item as _add

        item_catalog = {}
        for cat, lst in SHOP_ITEMS.items():
            itype = 'sword' if cat == 'swords' else ('armor' if cat == 'armor' else 'item')
            for i in lst:
                item_catalog[i['name'].lower()] = (i['name'], itype)
        for region, data in REGION_ENEMIES.items():
            for e in data['enemies']:
                for d in e.get('drops', []):
                    item_catalog[d.lower()] = (d, 'material')
        for e in SLAYER_ENEMIES + DEMON_ENEMIES:
            for d in e.get('drops', []):
                item_catalog[d.lower()] = (d, 'material')

        # Fuzzy match
        key   = item_name.lower()
        match = item_catalog.get(key)
        if not match:
            # Partial match
            matches = [(k, v) for k, v in item_catalog.items() if key in k]
            if matches:
                match = matches[0][1]
                item_name = matches[0][1][0]
            else:
                # Unknown item — give as material anyway
                match = (item_name, 'material')

        real_name, itype = match
        for _ in range(amount):
            _add(tid, real_name, itype)

        try:
            await context.bot.send_message(tid,
                f"🎁 *ITEM GRANTED BY ADMIN!*\n\n"
                f"📦 *{real_name}* × {amount}\n"
                f"_Check your /inventory_",
                parse_mode='Markdown')
        except Exception: pass

        await update.message.reply_text(
            f"✅ Gave *{real_name}* × *{amount}* to *{target['name']}*\n"
            f"Type: `{itype}`",
            parse_mode='Markdown')
        return

    # ── MODE 1: /master @user — give EVERYTHING ──────────────────────────
    updates = {
        'yen':          999999,
        'xp':           999999,
        'str_stat':     999,
        'spd':          999,
        'def_stat':     999,
        'max_hp':       9999,
        'hp':           9999,
        'max_sta':      999,
        'sta':          999,
        'skill_points': 500,
        'devour_stacks': 25,
    }
    if faction == 'slayer':
        updates['slayer_mark']    = 1
        updates['equipped_sword'] = 'Jet Black Nichirin Blade'
        updates['equipped_armor'] = 'Hashira Haori'
    else:
        updates['demon_mark'] = 1

    update_player(tid, **updates)

    from handlers.skilltree import save_player_skills
    from config import SKILLS
    all_skill_names = [s['name'] for cat in SKILLS.values() for s in cat]
    save_player_skills(tid, all_skill_names)

    from utils.database import add_item
    for item, itype, qty in [
        ('Full Recovery Gourd', 'item',     50),
        ('Stamina Pill',        'item',     50),
        ('Wisteria Antidote',   'item',     20),
        ('Boss Shard',          'material', 20),
        ('Kizuki Blood',        'material', 10),
        ('Upper Moon Shard',    'material', 10),
        ('Demon Blood',         'material', 30),
        ('Wolf Fang',           'material', 30),
        ('Muzan Blood',         'material',  5),
        ('Demon King Core',     'material',  5),
    ]:
        for _ in range(qty):
            add_item(tid, item, itype)

    mark_line = "🔥 Slayer Mark" if faction == 'slayer' else "🔴 Demon Mark"
    try:
        await context.bot.send_message(tid,
            f"👑 *MASTER POWER GRANTED!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💪 STR/SPD/DEF: *999* each\n"
            f"❤️ HP: *9999* | 🌀 STA: *999*\n"
            f"💰 *999,999¥* | 💠 *500 SP*\n"
            f"{mark_line}: *ACTIVE*\n"
            f"✅ All *{len(all_skill_names)}* skills unlocked\n"
            f"🎒 Full item kit granted",
            parse_mode='Markdown')
    except Exception: pass

    await update.message.reply_text(
        f"👑 *MASTER granted to {target['name']}* ({faction})\n"
        f"All stats maxed + all {len(all_skill_names)} skills + marks + items.",
        parse_mode='Markdown')


async def backup(update, context):
    """Export all player data as a JSON file — owner only."""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner only.")
        return

    import json as _j
    from datetime import datetime

    await update.message.reply_text("⏳ Generating backup, please wait...")

    collections_to_backup = [
        "players", "inventory", "battle_state", "skill_tree",
        "admins", "clans", "auctions", "custom_missions",
        "black_market", "raids", "events", "gift_log",
        "market_listings", "bank_accounts", "arts", "party",
        "battle_log", "status_effects", "referrals", "coop_battles",
        "duels", "raid_participants", "suggestions", "admin_logs",
    ]

    backup_data = {"timestamp": datetime.utcnow().isoformat(), "collections": {}}
    total_docs = 0
    for cname in collections_to_backup:
        try:
            docs = list(col(cname).find({}, {"_id": 0}))
            backup_data["collections"][cname] = docs
            total_docs += len(docs)
        except Exception:
            backup_data["collections"][cname] = []

    import io
    json_bytes = _j.dumps(backup_data, indent=2, default=str).encode("utf-8")
    buf = io.BytesIO(json_bytes)
    buf.name = f"backup_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"

    await update.message.reply_document(
        document=buf,
        filename=buf.name,
        caption=(
            f"✅ *Backup complete!*\n"
            f"📦 {total_docs} documents across {len(collections_to_backup)} collections\n"
            f"🕐 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC"
        ),
        parse_mode="Markdown"
    )


async def restore(update, context):
    """Restore player data from a JSON backup file — owner only."""
    user_id = update.effective_user.id
    if not is_owner(user_id):
        await update.message.reply_text("❌ Owner only.")
        return

    # If called as a command (no document) — show instructions
    has_doc = update.message and update.message.document
    if not has_doc:
        await update.message.reply_text(
            "📂 *RESTORE DATABASE*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "To restore from backup:\n"
            "1️⃣ Use `/backup` to generate a backup file\n"
            "2️⃣ Send the `.json` file as a **document** (not photo)\n"
            "   to this chat with the caption `/restore`\n\n"
            "⚠️ *Warning:* Restore will OVERWRITE existing data!\n"
            "Players and inventory are upserted (safe).\n"
            "Other collections are dropped and re-inserted.\n\n"
            "💡 Or forward the backup file from your saved messages.",
            parse_mode="Markdown"
        )
        return

    doc = update.message.document
    if not doc.file_name.endswith(".json"):
        await update.message.reply_text(
            "❌ *Wrong file type!*\n\n"
            "Please send a `.json` backup file.\n"
            "Use `/backup` first to generate one.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text("⏳ Restoring from backup, please wait...")

    import json as _j
    import io

    try:
        file = await context.bot.get_file(doc.file_id)
        buf = io.BytesIO()
        await file.download_to_memory(buf)
        buf.seek(0)
        backup_data = _j.loads(buf.read().decode("utf-8"))
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to read file: {e}")
        return

    collections = backup_data.get("collections", {})
    restored = 0
    skipped = 0
    for cname, docs in collections.items():
        if not docs:
            continue
        try:
            # Upsert players by user_id, others by natural key
            if cname == "players":
                for d in docs:
                    col(cname).update_one(
                        {"user_id": d["user_id"]}, {"$set": d}, upsert=True
                    )
            elif cname == "inventory":
                for d in docs:
                    col(cname).update_one(
                        {"user_id": d["user_id"], "item_name": d["item_name"]},
                        {"$set": d}, upsert=True
                    )
            else:
                # Drop and re-insert for other collections
                col(cname).drop()
                if docs:
                    col(cname).insert_many(docs)
            restored += len(docs)
        except Exception:
            skipped += 1

    await update.message.reply_text(
        f"✅ *RESTORE COMPLETE!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Restored: *{restored:,}* documents\n"
        f"📁 Collections: *{len([c for c in collections if collections[c]])}* processed\n"
        f"⚠️ Errors: *{skipped}*\n\n"
        f"_All player data, inventory, and game state restored._\n"
        f"_Use /botstats to verify._",
        parse_mode="Markdown"
    )
