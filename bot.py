import logging
import os
import asyncio
import urllib.request
import urllib.error
from collections import deque
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationHandlerStop,
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes
)
from config import BOT_TOKEN, OWNER_ID
from utils.database import init_db, get_player, col
from handlers.start import (start, get_name, choose_faction, choose_story, captcha_callback,
                            WAITING_NAME, WAITING_CAPTCHA, CHOOSING_FACTION, CHOOSING_STORY)
from handlers.menu import menu, close_menu
from handlers.profile import profile, profile_techniques, profile_more_info, setbanner, clearbanner
from handlers.explore import (explore, fight, attack, technique, choose_art, use_form,
                               items_menu, use_item, party_battle, flee, prize, form_info,
                               switch_ally, dismiss_ally_callback, ally_fainted_callback)
from handlers.shop import shop, buy, sell, equip, shop_page_callback
from handlers.inventory import inventory, inv_materials_callback, inv_back_callback
from handlers.use_item import use
from handlers.party import (party, alliance_invite, alliance_info, alliance_leave,
                             alliance_accept, alliance_decline, choose_ally,
                             party_invite_cmd)
from handlers.travel import travel, travel_to
from handlers.rankings import (rankings, rankings_slayers, rankings_demons,
                                rankings_richest, rankings_kills,
                                rankings_level, rankings_sp)
from handlers.help_cmd import help_command
from handlers.raid import joinraid, raidattack
from handlers.auction import auction, bid
from handlers.mission import mission, select_mission, confirm_mission, abandon_mission, mission_back
from handlers.daily import daily, streak
from handlers.gift import gift
from handlers.lottery import lottery, lottery_play
from handlers.slayermark import slayermark
from handlers.clan import (clan, createclan, joinclan, leaveclan, setclanlink, clandisband,
                            clanmembers, promotevice, demote, kick,
                            renameclan, clanannounce, clanleaderboard,
                            clanslogan, clanimage, clanreq,
                            clan_accept_callback, clan_reject_callback)
from handlers.clan_raid import (clanraid, clanrole,
    raid_attack_callback, raid_technique_callback, raid_use_form_callback,
    raid_items_callback, raid_use_item_callback,
    raid_retreat_callback, raid_back_callback)
from handlers.admin import (addsudo, removesudo, listadmins, announce, ban, unban, giveultimate,
                             resetplayer, givexp, giveyen, givesp, botstats,
                             startraid, stopraid, addauction,
                             openblackmarket, closeblackmarket, addblackmarket,
                             adminhelp, myid, admin_unstuck, activeusers, backup, restore,
                             giveslayermark, givedemonmark, master)
from handlers.admin_runtime import giveitem, addmission, removemission, listmissions
from handlers.challenge import (challenge, duel_accept_callback, duel_decline_callback,
    duel_settings_callback, duel_toggle_callback,
    duel_draw_callback, duel_details_callback,
    duel_settings_back_callback, duel_settings_done_callback,
                                  duel_attack, duel_technique_menu, duel_use_form,
                                  duel_art_callback, duel_view,
                                  duel_items_menu, duel_use_item, duel_surrender, duel_back)
from handlers.market import market, market_list, unlist, markethistory, market_buy
from handlers.bank import bank, deposit, withdraw, bankupgrade, banktax
from handlers.worldbank import (
    worldbank,
    worlddeposit,
    worldwithdraw,
    wbaddstock,
    wbsetprice,
    wbinfo,
    wbevent,
    wbblackmarket,
)
from handlers.bank_giveaway import (
    bankgiveaway,
    join_bank_giveaway,
    resume_bank_giveaways,
    schedule_daily_bank_tax,
)
from handlers.sp_bank import (
    resume_sp_features,
    spbank,
    spdeposit,
    spwithdraw,
    spgiveaway,
    spjoin,
)
from handlers.broadcast import bcast, handle_broadcast_callback
from handlers.admin_add import add
from handlers.blackmarket import blackmarket, bm_buy
from handlers.referral import referral
from handlers.style_art import breathing, art, givestyle, giveart
from handlers.guide import guide, guide_page_callback, guide_home_callback
from handlers.suggest import suggest, suggestions, suggestion_action_callback
from handlers.sqlview import sqlview
from handlers.info_cmd import info, infoall, view_suggestion
from handlers.know import know, know_callback
from handlers.give import give
from handlers.event import event_cmd, events, eventend, eventlist, event_callback
try:
    from handlers.event import eventresults, vote_cmd, vote_callback
except ImportError:
    async def eventresults(update, context): await eventend(update, context)
    async def vote_cmd(update, context): await event_cmd(update, context)
    async def vote_callback(update, context): await event_callback(update, context)
from handlers.logs import logs, logs_callback, logstats, logsearch, loguser, log_user_activity
from handlers.owner import (ownermode, owneraccess, ownersetlevel, ownersetstyle,
    ownergive, ownerreset, ownerban, ownerunban, ownermsg, ownerstats,
    ownerplayers, ownerplayers_callback, owner_godmode_active)
from handlers.upgrade import upgrade, upgradetoggle, upgrade_confirm_callback
from handlers.hybrid import hybrid, demonmark, hybridtoggle
from handlers.offer import offers, offer_buy_callback, addoffer
from handlers.tournament import (
    createtour, starttour, endtour, listtours, settourlevel,
    tournament, mytour, tour_fight, tournament_callback, rolltour, tourplayers, fixtour, tourreenter,
)
from handlers.imgupload import setimage, listimages
from handlers.clan_list import clan_list, clanlist_page_callback
from handlers.help_cmd import help_command, admin_help_list, help_callback, admin_help_callback

from handlers.skilltree import (skilltree, skilltree_owned, skillbuy, skilllist,
                                 skillinfo, skills, skilltree_buy_callback,
                                 skilltree_page_callback, myskills_callback,
                                 get_active_skill_bonuses, get_player_skills,
                                 deactivateskill, reactivateskill,
                                 deactivateall, reactivateall)
skill_detail = skillinfo
from handlers.claninfo import claninfo, clandeposit, clanwithdraw, changestyle, claninfo_callback
from handlers.unstuck import unstuck, forceunstuck
from handlers.coop import (
    joinbattle,
    coop_attack,
    coop_technique,
    coop_use_form,
    coop_join_callback,
    coop_leave,
    coop_back,
    coop_items,
    coop_use_item,
    coop_art_callback,
)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


async def _self_ping_loop(application):
    """Keep Render service alive by pinging itself every 14 minutes."""
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    if not RENDER_URL:
        logger.info("[PING] No RENDER_EXTERNAL_URL set, self-ping disabled")
        return
    ping_url = f"{RENDER_URL}/healthz"
    ping_interval = 14 * 60
    await asyncio.sleep(60)
    while True:
        try:
            req = urllib.request.Request(ping_url, method='GET')
            with urllib.request.urlopen(req, timeout=10) as response:
                logger.info(f"[PING] Self-ping OK: {response.status}")
        except Exception as e:
            logger.warning(f"[PING] Failed: {e}")
        await asyncio.sleep(ping_interval)


async def post_init(application):
    """Called after app starts — log webhook info."""
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
    BOT_TOKEN_ENV = os.environ.get("BOT_TOKEN", "")
    await resume_bank_giveaways(application)
    await resume_sp_features(application)
    schedule_daily_bank_tax(application)
    asyncio.create_task(_self_ping_loop(application))
    if WEBHOOK_URL and BOT_TOKEN_ENV:
        info = await application.bot.get_webhook_info()
        logger.info(f"Webhook active: {info.url}")
        logger.info(f"Pending updates: {info.pending_update_count}")
    else:
        logger.info("Running in polling mode")

PRIVATE = filters.ChatType.PRIVATE
ANY = filters.ALL
AUTO_GUARD_WINDOW_SECONDS = 12
AUTO_GUARD_MAX_ACTIONS = 14
AUTO_GUARD_REPEAT_LIMIT = 6


async def buy_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route /buy to market, blackmarket, or shop — works everywhere."""
    args = context.args
    if args and args[0].lower() == 'market':
        await market_buy(update, context)
    elif args and args[0].lower() == 'blackmarket':
        await bm_buy(update, context)
    else:
        await buy(update, context)


def _is_privileged_user(user_id: int | None) -> bool:
    if not user_id:
        return False
    if user_id == OWNER_ID:
        return True
    return col("admins").find_one({"user_id": user_id}) is not None


def _get_human_check_doc(user_id: int) -> dict:
    return col("captcha_guard").find_one({"user_id": user_id}) or {}


def _set_human_check_required(user_id: int, reason: str) -> None:
    col("captcha_guard").update_one(
        {"user_id": user_id},
        {"$set": {
            "challenge_required": True,
            "challenge_reason": str(reason)[:180],
            "challenge_set_at": datetime.now(),
        }},
        upsert=True,
    )


def _activity_signature(update: Update) -> str | None:
    query = update.callback_query
    if query:
        data = (query.data or "").strip()
        if not data or data.startswith("captcha_") or data == "goto_start":
            return None
        return f"button:{data[:48]}"

    message = update.message
    if message and message.text and message.text.startswith("/"):
        command = message.text.split()[0][1:].split("@")[0].lower()
        if command == "start":
            return None
        return f"command:{command}"

    return None


def _note_recent_activity(context: ContextTypes.DEFAULT_TYPE, user_id: int, signature: str) -> tuple[int, int]:
    tracker = context.application.bot_data.setdefault("auto_guard_tracker", {})
    state = tracker.setdefault(user_id, {
        "events": deque(maxlen=50),
        "signatures": deque(maxlen=25),
    })

    now = datetime.now()
    events = state["events"]
    signatures = state["signatures"]

    while events and (now - events[0]).total_seconds() > AUTO_GUARD_WINDOW_SECONDS:
        events.popleft()
    while signatures and (now - signatures[0][0]).total_seconds() > AUTO_GUARD_WINDOW_SECONDS:
        signatures.popleft()

    events.append(now)
    signatures.append((now, signature))
    repeat_count = sum(1 for _, sig in signatures if sig == signature)
    return len(events), repeat_count


def _human_check_message(reason: str | None = None, remaining_minutes: int | None = None) -> str:
    if remaining_minutes:
        return (
            "Verification cooldown active.\n"
            f"Wait about {remaining_minutes} minute(s), then use /start in DM."
        )
    if reason:
        return (
            "Human verification required.\n"
            f"Trigger: {reason}\n\n"
            "Use /start in DM and solve the captcha to continue."
        )
    return "Human verification required. Use /start in DM and solve the captcha to continue."


async def _notify_human_check(update: Update, reason: str | None = None, remaining_minutes: int | None = None):
    text = _human_check_message(reason=reason, remaining_minutes=remaining_minutes)
    try:
        if update.callback_query:
            await update.callback_query.answer(text[:180], show_alert=True)
        elif update.message:
            await update.message.reply_text(text)
    except Exception:
        pass


async def _global_human_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or _is_privileged_user(user.id):
        return

    if update.callback_query and (update.callback_query.data or "").startswith("captcha_"):
        return
    if update.callback_query and (update.callback_query.data or "") == "goto_start":
        return
    if update.message and update.message.text and update.message.text.startswith("/start"):
        return

    guard_doc = _get_human_check_doc(user.id)
    now = datetime.now()
    lock_until = guard_doc.get("lock_until")
    if isinstance(lock_until, datetime) and lock_until <= now:
        col("captcha_guard").update_one(
            {"user_id": user.id},
            {"$set": {"lock_until": None}},
            upsert=True,
        )
        lock_until = None

    if isinstance(lock_until, datetime) and lock_until > now:
        remaining = max(1, int((lock_until - now).total_seconds() // 60))
        await _notify_human_check(update, remaining_minutes=remaining)
        raise ApplicationHandlerStop

    if guard_doc.get("challenge_required"):
        await _notify_human_check(update, reason=guard_doc.get("challenge_reason"))
        raise ApplicationHandlerStop

    signature = _activity_signature(update)
    if not signature:
        return

    player = get_player(user.id)
    if not player:
        return

    burst_count, repeat_count = _note_recent_activity(context, user.id, signature)
    if burst_count < AUTO_GUARD_MAX_ACTIONS and repeat_count < AUTO_GUARD_REPEAT_LIMIT:
        return

    reason = (
        f"{repeat_count} repeated {signature} actions in {AUTO_GUARD_WINDOW_SECONDS}s"
        if repeat_count >= AUTO_GUARD_REPEAT_LIMIT
        else f"{burst_count} rapid actions in {AUTO_GUARD_WINDOW_SECONDS}s"
    )
    _set_human_check_required(user.id, reason)
    log_user_activity(
        user.id,
        "human_check_required",
        details=reason,
        chat_id=update.effective_chat.id if update.effective_chat else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
        username=user.username,
        name=user.first_name,
    )
    await _notify_human_check(update, reason=reason)
    raise ApplicationHandlerStop



async def _global_ban_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        return

    if update.message and update.message.text:
        cmd = update.message.text.split()[0].lstrip('/').split('@')[0].lower()
        if cmd in ('unban', 'ban', 'start', 'adminhelp'):
            return

    from utils.database import get_player
    player = get_player(user_id)
    if not player or not player.get('banned'):
        return

    reason = player.get('ban_reason', 'No reason given')
    msg = (
        "🚫 *YOU ARE BANNED*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"❌ Reason: _{reason}_\n\n"
        "_Contact an admin if you believe this is a mistake._"
    )
    try:
        if update.callback_query:
            await update.callback_query.answer(
                "🚫 You are banned from this game.", show_alert=True
            )
        elif update.message:
            await update.message.reply_text(msg, parse_mode='Markdown')
    except Exception:
        pass

    raise ApplicationHandlerStop


async def _track_user_command_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    user = update.effective_user
    if not message or not user or not message.text or not message.text.startswith("/"):
        return

    command = message.text.split()[0][1:].split("@")[0].lower()
    args_text = " ".join(message.text.split()[1:]).strip()
    log_user_activity(
        user.id,
        f"command:{command}",
        details=args_text or None,
        chat_id=update.effective_chat.id if update.effective_chat else None,
        chat_type=update.effective_chat.type if update.effective_chat else None,
        username=user.username,
        name=user.first_name,
    )


async def _track_user_callback_activity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    if not query or not user:
        return

    data = (query.data or "").strip()
    if not data or data.startswith("captcha_"):
        return

    log_user_activity(
        user.id,
        f"button:{data[:80]}",
        details=None,
        chat_id=query.message.chat_id if query.message else None,
        chat_type=query.message.chat.type if query.message and query.message.chat else None,
        username=user.username,
        name=user.first_name,
    )


async def callback_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    conv_callbacks = ('faction_', 'story_')
    if any(data.startswith(p) for p in conv_callbacks):
        return

    battle_callbacks = (
        'fight', 'attack', 'technique', 'items_menu', 'flee', 'prize',
        'party_battle', 'form_', 'use_item_', 'art_', 'forminfo_',
        'dismiss_ally', 'ally_fainted', 'switch_ally_', 'choose_ally',
    )
    is_battle = any(data == b or data.startswith(b) for b in battle_callbacks)

    cross_user = (
        'duel_accept_', 'duel_decline_',
        'duel_attack_', 'duel_technique_', 'duel_art_', 'duel_view_', 'duel_surrender_', 'duel_surrender_me',
        'duel_items_', 'duel_form_', 'duel_useitem_', 'duel_wait',
        'clan_accept_', 'clan_reject_', 'claninfo_',
        'alliance_accept_', 'alliance_decline_',
        'coop_join_', 'coop_attack', 'coop_technique', 'coop_items',
        'coop_leave', 'coop_back',
        'coop_leave', 'coop_back', 'coop_art_', 'coop_form_',
        'rankings_',
        'guide_',
        'sug_',
        'offer_buy_',
        'clanlist_page_',
        'logs_',
        'vote_',
        'ownerplist_',
        'duel_settings_',
        'duel_settings_back_',
        'duel_settings_done_',
        'duel_toggle_',
        'duel_draw_',
        'duel_details_',
        'upgrade_confirm_',
        'travel_locked',
        'travel_to_',
        'goto_start',
        'tour_',
    )
    is_cross = any(data.startswith(p) or data == p for p in cross_user)

    from telegram.constants import ChatType
    in_private = query.message.chat.type == ChatType.PRIVATE
    if not is_battle and not is_cross and in_private and query.from_user.id != query.message.chat_id:
        await query.answer("❌ These buttons are not yours!", show_alert=True)
        return

    routes = {
        'fight': fight, 'prize': prize, 'attack': attack,
        'technique': technique, 'items_menu': items_menu,
        'party_battle': party_battle, 'flee': flee,
        'dismiss_ally': dismiss_ally_callback, 'ally_fainted': ally_fainted_callback,
        'profile_techniques': profile_techniques, 'profile_more_info': profile_more_info,
        'rankings_slayers': rankings_slayers, 'rankings_demons': rankings_demons,
        'rankings_richest': rankings_richest, 'rankings_kills': rankings_kills,
        'rankings_level': rankings_level, 'rankings_sp': rankings_sp,
        'alliance_invite': alliance_invite, 'alliance_info': alliance_info,
        'alliance_leave': alliance_leave,
        'goto_profile': profile, 'goto_party': party, 'goto_menu': menu,
        'goto_explore': explore, 'goto_close': close_menu,
        'goto_inventory': inventory, 'goto_shop': shop,
        'duel_back': duel_back,
        'duel_wait': duel_back,
        'coop_attack': coop_attack, 'coop_technique': coop_technique,
        'coop_items': coop_items, 'coop_leave': coop_leave, 'coop_back': coop_back,
        'skilltree_main':  skilltree,
        'skilltree_owned': skilltree_owned,
        'skilltree':       skilltree,
    }

    if data in routes:
        await routes[data](update, context)
    elif data.startswith('art_'):          await choose_art(update, context)
    elif data.startswith('form_'):         await use_form(update, context)
    elif data.startswith('forminfo_'):     await form_info(update, context)
    elif data.startswith('use_item_'):     await use_item(update, context)
    elif data.startswith('travel_to_'):    await travel_to(update, context)
    elif data.startswith('alliance_accept_'): await alliance_accept(update, context)
    elif data.startswith('alliance_decline_'): await alliance_decline(update, context)
    elif data.startswith('switch_ally_'):  await switch_ally(update, context)
    elif data.startswith('mission_select_'): await select_mission(update, context)
    elif data == 'mission_confirm':      await confirm_mission(update, context)
    elif data == 'mission_back':         await mission_back(update, context)
    elif data == 'mission_abandon':      await abandon_mission(update, context)
    elif data.startswith('guide_'):    await guide_page_callback(update, context)
    elif data.startswith('sug_'):      await suggestion_action_callback(update, context)
    elif data.startswith('upgrade_confirm_'): await upgrade_confirm_callback(update, context)
    elif data.startswith('offer_buy_'):  await offer_buy_callback(update, context)
    elif data.startswith('clanlist_page_'): await clanlist_page_callback(update, context)
    elif data.startswith('logs_'):          await logs_callback(update, context)
    elif data.startswith('vote_'):           await vote_callback(update, context)
    elif data.startswith('ownerplist_'):    await ownerplayers_callback(update, context)
    elif data.startswith('event_'):              await event_callback(update, context)
    elif data.startswith('abroad_'):             await handle_broadcast_callback(update, context)
    elif data.startswith('cancel_broadcast:'):   await handle_broadcast_callback(update, context)
    elif data.startswith('guide_'):        await guide_page_callback(update, context)
    elif data.startswith('sug_'):          await suggestion_action_callback(update, context)
    elif data.startswith('upgrade_confirm_'): await upgrade_confirm_callback(update, context)
    elif data.startswith('offer_buy_'):    await offer_buy_callback(update, context)
    elif data.startswith('clanlist_page_'): await clanlist_page_callback(update, context)
    elif data.startswith('logs_'):         await logs_callback(update, context)
    elif data.startswith('vote_'):         await vote_callback(update, context)
    elif data.startswith('ownerplist_'):   await ownerplayers_callback(update, context)
    elif data.startswith('event_'):              await event_callback(update, context)
    elif data.startswith('duel_settings_back_'): await duel_settings_back_callback(update, context)
    elif data.startswith('duel_settings_done_'): await duel_settings_done_callback(update, context)
    elif data.startswith('duel_settings_'): await duel_settings_callback(update, context)
    elif data.startswith('duel_toggle_'):   await duel_toggle_callback(update, context)
    elif data.startswith('duel_draw_'):     await duel_draw_callback(update, context)
    elif data.startswith('duel_details_'):  await duel_details_callback(update, context)
    elif data.startswith('skillbuy_'):      await skilltree_buy_callback(update, context)
    elif data == 'goto_upgrade':        await upgrade(update, context)
    elif data == 'goto_clan':           await clan(update, context)
    elif data == 'goto_skilltree':      await skilltree(update, context)
    elif data == 'goto_close':          await close_menu(update, context)

    elif data == 'inv_materials':    await inv_materials_callback(update, context)
    elif data == 'inv_back':         await inv_back_callback(update, context)
    elif data.startswith('duel_accept_'):  await duel_accept_callback(update, context)
    elif data.startswith('duel_decline_'): await duel_decline_callback(update, context)
    elif data.startswith('duel_attack_'):  await duel_attack(update, context)
    elif data.startswith('duel_technique_'): await duel_technique_menu(update, context)
    elif data.startswith('duel_art_'):        await duel_art_callback(update, context)
    elif data.startswith('duel_view_'):       await duel_view(update, context)
    elif data.startswith('duel_surrender_'): await duel_surrender(update, context)
    elif data.startswith('duel_items_'):   await duel_items_menu(update, context)
    elif data.startswith('duel_form_'):    await duel_use_form(update, context)
    elif data.startswith('duel_useitem_'): await duel_use_item(update, context)
    elif data.startswith('claninfo_'):     await claninfo_callback(update, context)
    elif data == 'raid_attack':             await raid_attack_callback(update, context)
    elif data == 'raid_technique':          await raid_technique_callback(update, context)
    elif data == 'raid_items':              await raid_items_callback(update, context)
    elif data == 'raid_back':               await raid_back_callback(update, context)
    elif data == 'raid_retreat':            await raid_retreat_callback(update, context)
    elif data.startswith('raid_form_'):     await raid_use_form_callback(update, context)
    elif data.startswith('raid_useitem_'):  await raid_use_item_callback(update, context)
    elif data.startswith('clan_accept_'):  await clan_accept_callback(update, context)
    elif data.startswith('clan_reject_'):  await clan_reject_callback(update, context)
    elif data.startswith('coop_join_'):    await coop_join_callback(update, context)
    elif data.startswith('coop_form_'):    await coop_use_form(update, context)
    elif data.startswith('coop_useitem_'): await coop_use_item(update, context)
    elif data.startswith('skillinfo_'):       await skill_detail(update, context)
    elif data.startswith('skillbuy_'):        await skilltree_buy_callback(update, context)
    elif data.startswith('skillpage_'):       await skilltree_page_callback(update, context)
    elif data.startswith('shop_'):             await shop_page_callback(update, context)
    elif data.startswith('myskills_'):          await myskills_callback(update, context)
    elif data == 'goto_start':                await start(update, context)
    elif data.startswith('know_'):               await know_callback(update, context)
    elif data.startswith('help_'):               await help_callback(update, context)
    elif data.startswith('ahelp_'):              await admin_help_callback(update, context)
    elif data.startswith('tour_'):               await tournament_callback(update, context)
    elif data == 'inv_materials':       await inv_materials_callback(update, context)
    elif data == 'inv_back':            await inv_back_callback(update, context)
    elif data.startswith('duel_accept_'):    await duel_accept_callback(update, context)
    elif data.startswith('duel_decline_'):   await duel_decline_callback(update, context)
    elif data.startswith('duel_attack_'):    await duel_attack(update, context)
    elif data.startswith('duel_technique_'): await duel_technique_menu(update, context)
    elif data.startswith('duel_art_'):       await duel_art_callback(update, context)
    elif data.startswith('duel_view_'):      await duel_view(update, context)
    elif data.startswith('duel_surrender_'): await duel_surrender(update, context)
    elif data.startswith('duel_items_'):     await duel_items_menu(update, context)
    elif data.startswith('duel_form_'):      await duel_use_form(update, context)
    elif data.startswith('duel_useitem_'):   await duel_use_item(update, context)
    elif data.startswith('claninfo_'):       await claninfo_callback(update, context)
    elif data == 'raid_attack':              await raid_attack_callback(update, context)
    elif data == 'raid_technique':           await raid_technique_callback(update, context)
    elif data == 'raid_items':               await raid_items_callback(update, context)
    elif data == 'raid_back':                await raid_back_callback(update, context)
    elif data == 'raid_retreat':             await raid_retreat_callback(update, context)
    elif data.startswith('raid_form_'):      await raid_use_form_callback(update, context)
    elif data.startswith('raid_useitem_'):   await raid_use_item(update, context)
    elif data.startswith('clan_accept_'):    await clan_accept_callback(update, context)
    elif data.startswith('clan_reject_'):    await clan_reject_callback(update, context)
    elif data.startswith('coop_join_'):      await coop_join_callback(update, context)
    elif data.startswith('coop_art_'):       await coop_art_callback(update, context)
    elif data.startswith('coop_form_'):      await coop_use_form(update, context)
    elif data.startswith('coop_useitem_'):   await coop_use_item(update, context)
    elif data.startswith('skillinfo_'):      await skill_detail(update, context)
    elif data.startswith('skillpage_'):      await skilltree_page_callback(update, context)
    elif data.startswith('shop_'):           await shop_page_callback(update, context)
    elif data.startswith('myskills_'):       await myskills_callback(update, context)
    elif data == 'goto_start':               await start(update, context)
    elif data.startswith('know_'):           await know_callback(update, context)
    elif data.startswith('help_'):           await help_callback(update, context)
    elif data.startswith('ahelp_'):          await admin_help_callback(update, context)
    else:
        await query.answer("❓ Unknown action!", show_alert=True)


async def _end_conv_passthrough(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return ConversationHandler.END


def main():
    import sys
    missing = []
    if not BOT_TOKEN or BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE' or ':' not in BOT_TOKEN:
        missing.append("BOT_TOKEN (set in Render Dashboard → Environment)")
    from config import MONGO_URL
    if not MONGO_URL:
        missing.append("MONGO_URL (MongoDB connection string)")
    if missing:
        logger.error("=" * 60)
        logger.error("MISSING REQUIRED ENVIRONMENT VARIABLES:")
        for m in missing:
            logger.error(f"  ❌ {m}")
        logger.error("=" * 60)
        logger.error("Set these in Render Dashboard → Your Service → Environment")
        sys.exit(1)

    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    conv = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(start, pattern='^goto_start$'),
        ],
        states={
            WAITING_CAPTCHA: [CallbackQueryHandler(captcha_callback, pattern='^captcha_')],
            WAITING_NAME:    [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            CHOOSING_FACTION:[CallbackQueryHandler(choose_faction, pattern='^faction_')],
            CHOOSING_STORY:  [CallbackQueryHandler(choose_story,   pattern='^story_')],
        },
        fallbacks=[
            CommandHandler('start', start),
            CallbackQueryHandler(_end_conv_passthrough),
        ],
        per_chat=True,
        per_user=True,
        allow_reentry=False,
        conversation_timeout=300,
    )
    app.add_handler(conv)

    app.add_handler(MessageHandler(filters.ALL, _global_ban_check), group=-1)
    app.add_handler(CallbackQueryHandler(_global_ban_check), group=-1)
    app.add_handler(MessageHandler(filters.ALL, _global_human_check), group=-1)
    app.add_handler(CallbackQueryHandler(_global_human_check), group=-1)

    everywhere = [
        ('profile',         profile),
        ('setbanner',       setbanner),
        ('clearbanner',     clearbanner),
        ('rankings',        rankings),
        ('help',            help_command),
        ('myid',            myid),
        ('daily',           daily),
        ('streak',          streak),
        ('mission',         mission),
        ('skilltree',       skilltree),
        ('skills',          skills),
        ('skillbuy',        skillbuy),
        ('skillinfo',       skillinfo),
        ('skilllist',       skilllist),
        ('deactivate',      deactivateskill),
        ('reactivate',      reactivateskill),
        ('deactivateall',   deactivateall),
        ('reactivateall',   reactivateall),
        ('shop',            shop),
        ('buy',             buy_router),
        ('sell',            sell),
        ('equip',           equip),
        ('use',             use),
        ('inventory',       inventory),
        ('market',          market),
        ('auction',         auction),
        ('gift',            gift),
        ('give',            give),
        ('blackmarket',      blackmarket),
        ('worldbank',       worldbank),
        ('worlddeposit',    worlddeposit),
        ('worldwithdraw',   worldwithdraw),
        ('wbaddstock',      wbaddstock),
        ('wbsetprice',      wbsetprice),
        ('wbinfo',          wbinfo),
        ('wbevent',         wbevent),
        ('wbblackmarket',   wbblackmarket),
        ('referral',        referral),
        ('slayermark',      slayermark),
        ('demonmark',       demonmark),
        ('breathing',       breathing),
        ('art',             art),
        ('givestyle',       givestyle),
        ('giveart',         giveart),
        ('challenge',       challenge),
        ('clan',            clan),
        ('setclanlink',     setclanlink),
        ('claninfo',        claninfo),
        ('clandeposit',     clandeposit),
        ('clanwithdraw',    clanwithdraw),
        ('changestyle',     changestyle),
        ('guide',           guide),
        ('suggest',         suggest),
        ('event',           event_cmd),
        ('events',          events),
        ('eventend',        eventend),
        ('eventresults',    eventresults),
        ('vote',            vote_cmd),
        ('eventlist',       eventlist),
        ('sqlview',         sqlview),
        ('giveultimate',    giveultimate),
        ('info',            info),
        ('know',            know),
        ('infoall',         infoall),
        ('is',              view_suggestion),
        ('upgrade',         upgrade),
        ('hybrid',          hybrid),
        ('offers',          offers),
        ('addoffer',        addoffer),
        # ── Tournament system ──────────────────────────────────────────────
        ('tournament',      tournament),
        ('mytour',          mytour),
        ('tourfight',       tour_fight),
        ('createtour',      createtour),
        ('starttour',       starttour),
        ('endtour',         endtour),
        ('listtours',       listtours),
        ('settourlevel',    settourlevel),
        ('roll',            rolltour),
        ('tourplayers',     tourplayers),
        ('fixtour',         fixtour),
        ('tourreenter',     tourreenter),
        ('setimage',        setimage),
        ('listimages',      listimages),
        ('upgradetoggle',   upgradetoggle),
        ('hybridtoggle',    hybridtoggle),
        ('clan_list',       clan_list),
        ('helpadmin',       admin_help_list),
        ('activeusers',     activeusers),
        ('ownermode',       ownermode),
        ('owneraccess',     owneraccess),
        ('ownersetlevel',   ownersetlevel),
        ('ownersetstyle',   ownersetstyle),
        ('ownergive',       ownergive),
        ('ownerreset',      ownerreset),
        ('ownerban',        ownerban),
        ('ownerunban',      ownerunban),
        ('ownermsg',        ownermsg),
        ('ownerstats',      ownerstats),
        ('ownerplayers',    ownerplayers),
        ('backup',          backup),
        ('giveslayermark',  giveslayermark),
        ('givedemonmark',   givedemonmark),
        ('master',          master),
        ('restore',         restore),
        ('logs',            logs),
        ('logstats',        logstats),
        ('logsearch',       logsearch),
        ('loguser',          loguser),
        ('suggestions',     suggestions),
        ('createclan',      createclan),
        ('joinclan',        joinclan),
        ('leaveclan',       leaveclan),
        ('clandisband',     clandisband),
        ('clanmembers',     clanmembers),
        ('clanannounce',    clanannounce),
        ('clanslogan',      clanslogan),
        ('clanimage',       clanimage),
        ('clanreq',         clanreq),
        ('clanleaderboard', clanleaderboard),
        ('promotevice',     promotevice),
        ('demote',          demote),
        ('kick',            kick),
        ('renameclan',      renameclan),
        ('addsudo',         addsudo),
        ('removesudo',      removesudo),
        ('listadmins',      listadmins),
        ('add',             add),
        ('announce',        bcast),
        ('bcast',           bcast),
        ('ban',             ban),
        ('unban',           unban),
        ('givexp',          givexp),
        ('giveyen',         giveyen),
        ('giveitem',        giveitem),
        ('resetplayer',     resetplayer),
        ('givesp',          givesp),
        ('botstats',        botstats),
        ('startraid',       startraid),
        ('stopraid',        stopraid),
        ('addauction',      addauction),
        ('addmission',      addmission),
        ('removemission',   removemission),
        ('listmissions',    listmissions),
        ('openblackmarket', openblackmarket),
        ('closeblackmarket',closeblackmarket),
        ('addblackmarket',  addblackmarket),
        ('adminhelp',       adminhelp),
        ('adminunstuck',    admin_unstuck),
        ('bankgiveaway',    bankgiveaway),
        ('spbank',          spbank),
        ('spdeposit',       spdeposit),
        ('spwithdraw',      spwithdraw),
        ('spgiveaway',      spgiveaway),
        ('spjoin',          spjoin),
        ('banktax',         banktax),
    ]
    for cmd, handler in everywhere:
        app.add_handler(CommandHandler(cmd, handler))

    guarded_cmds = [
        ('menu',         menu),
        ('open',         menu),
        ('close',        close_menu),
        ('explore',      explore),
        ('party',        party),
        ('invite',       party_invite_cmd),
        ('joinbattle',   joinbattle),
        ('bank',         bank),
        ('deposit',      deposit),
        ('withdraw',     withdraw),
        ('bankupgrade',  bankupgrade),
        ('join',         join_bank_giveaway),
        ('list',         market_list),
        ('unlist',       unlist),
        ('markethistory',markethistory),
        ('lottery',      lottery_play),
        ('joinraid',     joinraid),
        ('raidattack',   raidattack),
        ('travel',       travel),
        ('bid',          bid),
        ('unstuck',      unstuck),
        ('forceunstuck', forceunstuck),
        ('bmbuy',        bm_buy),
        ('clanraid',     clanraid),
        ('clanrole',     clanrole),
    ]
    for cmd, handler in guarded_cmds:
        app.add_handler(CommandHandler(cmd, handler))

    async def reply_kb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        text = update.message.text.strip() if update.message and update.message.text else ""
        routes = {
            "⚔️ Explore":    explore,
            "📜 Profile":    profile,
            "🎒 Inventory":  inventory,
            "🏪 Shop":       shop,
            "🌳 Skills":     skilltree,
            "❌ Close Menu": close_menu,
        }
        handler = routes.get(text)
        if handler:
            await handler(update, context)

    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        reply_kb_handler
    ), group=1)

    async def doc_restore_handler(update, context):
        if update.message and update.message.document:
            fname = update.message.document.file_name or ""
            if fname.endswith(".json"):
                await restore(update, context)

    app.add_handler(MessageHandler(
        filters.Document.MimeType('application/json') & filters.ChatType.PRIVATE,
        doc_restore_handler
    ))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.COMMAND, _track_user_command_activity), group=2)
    app.add_handler(CallbackQueryHandler(_track_user_callback_activity), group=2)

    logger.info("🗡️ Demon Slayer RPG Bot starting...")
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == '__main__':
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    HOST = os.environ.get("HOST", "0.0.0.0")
    try:
        PORT = int(str(os.environ.get("PORT", "10000")).strip())
    except (TypeError, ValueError):
        PORT = 10000
    RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
    _health_started = threading.Event()

    class _H(BaseHTTPRequestHandler):
        def _send_text(self, status_code: int, body: str):
            self.send_response(status_code)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode("utf-8"))

        def _send_json(self, status_code: int, payload: dict):
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode("utf-8"))

        def do_GET(self):
            env_ok = bool(os.environ.get("BOT_TOKEN")) and bool(os.environ.get("MONGO_URL"))
            status = "RUNNING" if env_ok else "MISSING ENV VARS"

            if self.path in ("/", "/health", "/healthz", "/ready"):
                if self.path == "/":
                    self._send_text(
                        200,
                        "\n".join([
                            "Demon Slayer RPG Bot",
                            f"Status: {status}",
                            f"Host: {HOST}",
                            f"Port: {PORT}",
                            f"Render URL: {RENDER_URL or 'not set'}",
                        ]),
                    )
                else:
                    self._send_json(
                        200,
                        {
                            "service": "demon-slayer-rpg-bot",
                            "status": status.lower().replace(" ", "_"),
                            "host": HOST,
                            "port": PORT,
                            "render_url": RENDER_URL or None,
                        },
                    )
                return

            self._send_text(404, "Not Found")

        def do_HEAD(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass

    def _run_health():
        try:
            srv = ThreadingHTTPServer((HOST, PORT), _H)
            _health_started.set()
            print(f"[HEALTH] Listening on {HOST}:{PORT}", flush=True)
            if RENDER_URL:
                print(f"[HEALTH] Render URL: {RENDER_URL}", flush=True)
                print(f"[HEALTH] Health check: {RENDER_URL}/healthz", flush=True)
            srv.serve_forever()
        except Exception as e:
            print(f"[HEALTH ERROR] {e}", flush=True)
            _health_started.set()

    t = threading.Thread(target=_run_health, daemon=True)
    t.start()
    _health_started.wait(timeout=3)
    print(f"[BOT] Render health server ready on {HOST}:{PORT}. Starting bot...", flush=True)

    main()
