import logging

# ── Configure logging FIRST — before any handler/util imports ──────────────
# basicConfig must run before any module-level getLogger() calls, otherwise
# those loggers receive a NullHandler and produce zero output.

_fmt_default = logging.Formatter('%(asctime)s [%(name)s] [%(levelname)s] "%(message)s"')
_fmt_explore = logging.Formatter('%(asctime)s [EXPLORE] [%(levelname)s] "%(message)s"')

# Root handler — catches everything at INFO+
_root_handler = logging.StreamHandler()
_root_handler.setFormatter(_fmt_default)
_root_handler.setLevel(logging.INFO)

logging.root.setLevel(logging.INFO)
logging.root.addHandler(_root_handler)

# Silence noisy telegram/httpx libraries — keep only WARNING+
for _noisy in ("httpx", "telegram", "apscheduler"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ── Explore-specific handler: prints with ⚔️ prefix so it stands out ────────
class _ExploreFilter(logging.Filter):
    def filter(self, record):
        return record.name == "handlers.explore"

_explore_handler = logging.StreamHandler()
_explore_handler.setFormatter(_fmt_explore)
_explore_handler.setLevel(logging.DEBUG)
_explore_handler.addFilter(_ExploreFilter())
logging.root.addHandler(_explore_handler)

from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationHandlerStop,
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ConversationHandler, filters, ContextTypes, PreCheckoutQueryHandler
)
from config import BOT_TOKEN, OWNER_ID
from utils.guards import dm_only, owner_only, owner_only_button
from apscheduler.schedulers.background import BackgroundScheduler
from handlers.missions import register_missions, refresh_missions_job
from utils.database import get_player, col, init_db
from handlers.start import (start, get_name, choose_faction, choose_story,
                            WAITING_NAME, CHOOSING_FACTION, CHOOSING_STORY)
from handlers.menu import menu, close_menu
from handlers.profile import profile, profile_techniques, profile_more_info, setbanner, clearbanner, bannershow, banner_decision_callback, bannerpending, approvebanner, banner_successful_payment
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
from handlers.social import check, givesp as user_givesp
from handlers.pets import (
    pets, pet, hatchegg, feedpet, petskill,
    petbattle, releasepet, catch,
    pet_catch_callback, pet_flee_callback, pet_hatch_callback,
)
from handlers.lottery import lottery, lottery_play
from handlers.slayermark import slayermark
from handlers.gif_store import (
    addgifbanner, removegifbanner, listgifbanners, setmygifbanner,
    gifstore, gifstore_page_callback,
    gifstore_successful_payment,
)
from handlers.hybrid import hybrid, rehybrid, demonmark, hybridtoggle
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
from handlers.info_cmd import info, infoall, view_suggestion, mytechnique, myart, setstyleimage
from handlers.know import know, know_callback
from handlers.give import give
from handlers.event import event_cmd, events, eventend, eventlist, event_callback
try:
    from handlers.event import eventresults, vote_cmd, vote_callback
except ImportError:
    # Fallback stubs if event.py hasn't been updated yet
    async def eventresults(update, context): await eventend(update, context)
    async def vote_cmd(update, context): await event_cmd(update, context)
    async def vote_callback(update, context): await event_callback(update, context)
from handlers.logs import logs, logs_callback, logstats, logsearch, loguser, log_user_activity
from handlers.owner import (ownermode, owneraccess, ownersetlevel, ownersetstyle,
    ownergive, ownerreset, ownerban, ownerunban, ownermsg, ownerstats,
    ownerplayers, ownerplayers_callback, owner_godmode_active)
from handlers.maintenance import (
    maintenance, approveuser, unapproveuser, approvedlist,
    is_maintenance_on, is_approved_user
)
from handlers.upgrade import upgrade, upgradetoggle, upgrade_confirm_callback
from handlers.hybrid import hybrid, demonmark, hybridtoggle
from handlers.offer import offers, offer_buy_callback, addoffer
from handlers.broadcast import bcast, handle_broadcast_callback, announce_changes
from handlers.style_art import breathing, art, givestyle, giveart
from handlers.imgupload import setimage, listimages
from handlers.update import update_command, update_callback, recent_updates
from handlers.forge import forge_command, forge_callback
from handlers.pettrade import pettrade, petoffer, petaccept

from handlers.meditate import meditate, meditate_callback
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
from handlers.admin_tools import get_media_file_id

logger = logging.getLogger(__name__)
log = logger  # alias used in some handlers

async def post_init(application):
    """Called after app starts — log webhook info."""
    import os
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
    BOT_TOKEN_ENV = os.environ.get("BOT_TOKEN", "")
    await resume_bank_giveaways(application)
    await resume_sp_features(application)
    schedule_daily_bank_tax(application)
    if WEBHOOK_URL and BOT_TOKEN_ENV:
        info = await application.bot.get_webhook_info()
        logger.info(f"Webhook active: {info.url}")
        logger.info(f"Pending updates: {info.pending_update_count}")
    else:
        logger.info("Running in polling mode")

PRIVATE = filters.ChatType.PRIVATE
ANY = filters.ALL  # works everywhere

async def on_startup(app: Application):
    await app.bot.send_message(chat_id=-1003882841537, text="Bot has been started!")


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


async def _global_maintenance_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Global pre-filter: blocks all users except owner and approved users
    when maintenance mode is enabled. Runs at group=-2 (before everything).
    """
    if not is_maintenance_on():
        return  # Maintenance off — let everyone through

    user = update.effective_user
    if not user:
        return

    uid = user.id

    # Always allow owner and approved users through
    if uid == OWNER_ID or is_approved_user(uid):
        return

    # Allow maintenance management commands to pass (owner can turn it off)
    if update.message and update.message.text:
        cmd = update.message.text.split()[0].lstrip('/').split('@')[0].lower()
        if cmd in ('maintenance', 'approveuser', 'unapproveuser', 'approvedlist', 'start'):
            return

    # Block all callback queries with alert
    if update.callback_query:
        try:
            await update.callback_query.answer(
                "🔧 Bot is under maintenance. Please wait!",
                show_alert=True
            )
        except Exception as e:
            log.error("[EXCEPTION] %s", e)
        raise ApplicationHandlerStop

    # Block all messages/commands with maintenance message
    maintenance_msg = (
        "🔧 *Bot Under Maintenance*"
        "The bot is currently undergoing scheduled maintenance."
        "Please try again later! 🙏"
        "_We'll be back soon._"
    )
    if update.message:
        try:
            await update.message.reply_text(maintenance_msg, parse_mode="Markdown")
        except Exception as e:
            log.error("[EXCEPTION] %s", e)

    raise ApplicationHandlerStop


async def _global_ban_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Global pre-filter: runs before EVERY command and button press.
    Silently blocks banned players from interacting with the bot.
    Sends a one-time ban notice so they know why.
    """
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        return

    # Skip ban check for admin commands so admins can unban
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
        "YOU ARE BANNED\n"
        "----------------\n"
        f"Reason: {reason}\n"
        "Contact an admin if you believe this is a mistake."
    )
    try:
        if update.callback_query:
            await update.callback_query.answer(
                "You are banned from this game.", show_alert=True
            )
        elif update.message:
            await update.message.reply_text(msg, parse_mode=None)
    except Exception as e:
        log.error("[EXCEPTION] %s", e)

    raise ApplicationHandlerStop  # block all further handlers


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
    if not data:
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
    # These are handled by ConversationHandler — callback_router must NOT touch them
    conv_callbacks = ('faction_', 'story_')
    if any(data.startswith(p) for p in conv_callbacks):
        return  # Let ConversationHandler handle it

    battle_callbacks = (
        'fight', 'attack', 'technique', 'items_menu', 'flee', 'prize',
        'party_battle', 'form_', 'use_item_', 'art_', 'forminfo_',
        'dismiss_ally', 'ally_fainted', 'switch_ally_', 'choose_ally',
    )
    is_battle = any(data == b or data.startswith(b) for b in battle_callbacks)

    # Cross-user buttons (invites, rankings, etc.) — skip ownership check
    cross_user = (
        'duel_accept_', 'duel_decline_',
        'duel_attack_', 'duel_technique_', 'duel_art_', 'duel_view_', 'duel_surrender_', 'duel_surrender_me',
        'duel_items_', 'duel_form_', 'duel_useitem_', 'duel_wait',
        'clanaccept|', 'clanreject|', 'claninfo_',
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
        'mkt_sel_',
    )
    is_cross = any(data.startswith(p) or data == p for p in cross_user)

    # Ownership check: only in PRIVATE chat (DM)
    from telegram.constants import ChatType
    in_private = query.message.chat.type == ChatType.PRIVATE
    if not is_battle and not is_cross and in_private and query.from_user.id != query.message.chat_id:
        await query.answer("These buttons are not yours.", show_alert=True)
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
        'duel_wait': duel_back,  # waiting button = no-op
        'coop_attack': coop_attack, 'coop_technique': coop_technique,
        'coop_items': coop_items, 'coop_leave': coop_leave, 'coop_back': coop_back,
        # Skill tree
        'skilltree_main':  skilltree,
        'skilltree_owned': skilltree_owned,
        'skilltree':       skilltree,
    }

    if data in routes:
        await routes[data](update, context)
    elif data.startswith('mkt_sel_'):
        from handlers.market import cb_market_seller
        await cb_market_seller(update, context)
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
    elif data.startswith('pet_catch_'): await pet_catch_callback(update, context)
    elif data.startswith('pet_flee_'):  await pet_flee_callback(update, context)
    elif data.startswith('pet_hatch_'): await pet_hatch_callback(update, context)
    elif data == 'noop':               await update.callback_query.answer()
    elif data.startswith('inv_materials'): await inv_materials_callback(update, context)
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
    elif data.startswith('clanaccept|'):  await clan_accept_callback(update, context)
    elif data.startswith('clanreject|'):  await clan_reject_callback(update, context)
    elif data.startswith('coop_join_'):    await coop_join_callback(update, context)
    elif data.startswith('coop_form_'):    await coop_use_form(update, context)
    elif data.startswith('coop_useitem_'): await coop_use_item(update, context)
    elif data.startswith('coop_art_'):     await coop_art_callback(update, context)
    elif data.startswith('skillinfo_'):       await skill_detail(update, context)
    elif data.startswith('skillbuy_'):        await skilltree_buy_callback(update, context)
    elif data.startswith('skillpage_'):       await skilltree_page_callback(update, context)
    elif data.startswith('shop_'):             await shop_page_callback(update, context)
    elif data.startswith('myskills_'):          await myskills_callback(update, context)
    elif data == 'goto_start':                await start(update, context)
    elif data.startswith('know_'):               await know_callback(update, context)
    elif data.startswith('help_'):               await help_callback(update, context)
    elif data.startswith('ahelp_'):              await admin_help_callback(update, context)
    else:
        await query.answer("Unknown action.", show_alert=True)


async def _end_conv_passthrough(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    ConversationHandler fallback.
    If a user has an unfinished /start session (stuck at name entry)
    and presses any non-conversation button, this silently ends the
    conversation state so the global callback_router can handle it.
    """
    return ConversationHandler.END


def main():
    # Validate required environment variables before starting
    import sys
    missing = []
    if not BOT_TOKEN or BOT_TOKEN == 'YOUR_BOT_TOKEN_HERE' or ':' not in BOT_TOKEN:
        missing.append("BOT_TOKEN (set in Render Dashboard -> Environment)")
    from config import MONGO_URL
    if not MONGO_URL:
        missing.append("MONGO_URL (MongoDB connection string)")
    if missing:
        logger.error("=" * 60)
        logger.error("MISSING REQUIRED ENVIRONMENT VARIABLES:")
        for m in missing:
            logger.error(f"  - {m}")
        logger.error("=" * 60)
        logger.error("Set these in Render Dashboard -> Your Service -> Environment")
        sys.exit(1)

    init_db()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # ── Character creation — DM only ──────────────────────────────────────
    conv = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(start, pattern='^goto_start$'),
        ],
        states={
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

    # ── Maintenance check — runs BEFORE everything else (group=-2) ───────
    app.add_handler(MessageHandler(filters.ALL, _global_maintenance_check), group=-2)
    app.add_handler(CallbackQueryHandler(_global_maintenance_check), group=-2)

    # ── Global checks — runs before commands (group=-1) ──────────────────
    app.add_handler(MessageHandler(filters.ALL, _global_ban_check), group=-1)
    app.add_handler(CallbackQueryHandler(_global_ban_check), group=-1)

    # ── Works EVERYWHERE (Groups + DMs) ──────────────────────────────────
    everywhere = [
        ('profile',         profile),
        ('setbanner',       setbanner),
        ('clearbanner',     clearbanner),
        ('bannershow',      bannershow),
        ('bannerpending',   bannerpending),
        ('approvebanner',   approvebanner),
        ('gifstore',        gifstore),
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
        ('mytechnique',     mytechnique),
        ('myart',           myart),
        ('setstyleimage',   setstyleimage),
        ('upgrade',         upgrade),
        ('hybrid',          hybrid),
        ('re_hybrid',       rehybrid),
        ('offers',          offers),
        ('addoffer',        addoffer),
        ('setimage',        setimage),
        ('listimages',      listimages),
        ('meditate',        meditate),
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
        ('maintenance',     maintenance),
        ('approveuser',     approveuser),
        ('unapproveuser',   unapproveuser),
        ('approvedlist',    approvedlist),
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
        ('announce',        announce),
        ('pettrade',       pettrade),
        ('petoffer',      petoffer),
        ('petaccept',     petaccept),

        ('bcast',           bcast),
        ('ban',             ban),
        ('unban',           unban),
        ('givexp',          givexp),
        ('giveyen',         giveyen),
        ('giveitem',        giveitem),
        ('resetplayer',     resetplayer),
        ('givesp',          givesp),
        ('check',           check),
        ('pets',            pets),
        ('catch',           catch),
        ('pet',             pet),
        ('hatchegg',        hatchegg),
        ('feedpet',         feedpet),
        ('petskill',        petskill),
        ('petbattle',       petbattle),
        ('releasepet',      releasepet),
        ('inspect',         check),
        ('usersp',          user_givesp),
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
        ('addgifbanner',    addgifbanner),
        ('removegifbanner', removegifbanner),
        ('listgifbanners',  listgifbanners),
        ('setmygifbanner',  setmygifbanner),
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
        app.add_handler(CommandHandler(cmd, handler))  # no filter = works everywhere

    # ── DM Only — redirects groups to bot DM ─────────────────────────────
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

    # ── Reply keyboard button handler ────────────────────────────────────
    async def reply_kb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Route reply keyboard button presses to the right handler."""
        text = update.message.text.strip() if update.message and update.message.text else ""
        routes = {
            "Explore":    explore,
            "Profile":    profile,
            "Inventory":  inventory,
            "Shop":       shop,
            "Skills":     skilltree,
            "Close Menu": close_menu,
        }
        handler = routes.get(text)
        if handler:
            await handler(update, context)

    app.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.PRIVATE & ~filters.COMMAND,
        reply_kb_handler
    ), group=1)

    async def doc_restore_handler(update, context):
        """Handle JSON document uploads — trigger restore if caption says /restore or auto."""
        if update.message and update.message.document:
            fname = update.message.document.file_name or ""
            if fname.endswith(".json"):
                await restore(update, context)

    app.add_handler(MessageHandler(
        filters.Document.MimeType('application/json') & filters.ChatType.PRIVATE,
        doc_restore_handler
    ))
    app.add_handler(MessageHandler((filters.PHOTO | filters.VIDEO | filters.Sticker.ALL) & filters.ChatType.PRIVATE, get_media_file_id))
    # ── group=1: these must never be swallowed by the ConvHandler fallback ──
    app.add_handler(CallbackQueryHandler(banner_decision_callback, pattern=r'^banner_(approve|deny)_\d+$'), group=1)
    app.add_handler(CallbackQueryHandler(gifstore_page_callback, pattern=r'^gifstore_page_\d+$'), group=1)
    # ── Meditate callback handler ──
    app.add_handler(CallbackQueryHandler(meditate_callback, pattern=r'^meditate_'), group=1)

    # Command registration block moved into main()
    # Register owner-only listings commands via helper
    from handlers.listings import register_owner_listings
    register_owner_listings(app)
    # Register missions command
    register_missions(app)
    
    # Start APScheduler to refresh missions daily at midnight UTC
    scheduler = BackgroundScheduler()
    # Schedule job at 00:00 UTC daily
    scheduler.add_job(refresh_missions_job, 'cron', hour=0, minute=0, timezone='UTC')
    scheduler.start()
    # Ensure forge and updates are added only once
    app.add_handler(CommandHandler('forge', forge_command))
    app.add_handler(CallbackQueryHandler(forge_callback, pattern=r'^forge_'))
    app.add_handler(CommandHandler('updates', recent_updates))
    app.add_handler(CallbackQueryHandler(update_callback, pattern=r'^update_'))

    app.add_handler(PreCheckoutQueryHandler(_unified_pre_checkout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT & filters.ChatType.PRIVATE, _unified_successful_payment))
    app.add_handler(CallbackQueryHandler(callback_router))
    app.add_handler(MessageHandler(filters.COMMAND, _track_user_command_activity), group=2)
    app.add_handler(CallbackQueryHandler(_track_user_callback_activity), group=2)

    logger.info("🗡️ Demon Slayer RPG Bot starting...")
    app.post_init = on_startup
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


# ── Telegram Stars payment handlers ───────────────────────────────────
async def _unified_pre_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Single pre-checkout handler for all Stars payments."""
    query   = update.pre_checkout_query
    payload = query.invoice_payload
    if payload.startswith("gifstore_") or payload.startswith("gif_banner_"):
        await query.answer(ok=True)
    else:
        await query.answer(ok=False, error_message="Unknown payment.")


async def _unified_successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Route successful payments to the correct handler by payload prefix."""
    payload = update.message.successful_payment.invoice_payload
    if payload.startswith("gifstore_"):
        await gifstore_successful_payment(update, context)
    elif payload.startswith("gif_banner_"):
        await banner_successful_payment(update, context)


if __name__ == '__main__':
    import json
    import os
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

        def do_GET(self):  # <--- FIXED: Now perfectly aligned!
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
            else:
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
            log.error("[HEALTH ERROR] %s", e)
            _health_started.set()  # unblock main even if health fails

    t = threading.Thread(target=_run_health, daemon=True)
    t.start()
    _health_started.wait(timeout=3)
    print(f"[BOT] Render health server ready on {HOST}:{PORT}. Starting bot...", flush=True)

    import time as _time
    import urllib.request as _urllib_req
    import urllib.error   as _urllib_err

    _PING_TARGET   = (RENDER_URL + "/healthz") if RENDER_URL else f"http://127.0.0.1:{PORT}/healthz"
    _PING_INTERVAL = 8 * 60
    _PING_TIMEOUT  = 15

    def _keep_alive():
        """Pings the public URL on a fixed cadence with back-off on failure."""
        print(f"[KEEP-ALIVE] target={_PING_TARGET}  interval={_PING_INTERVAL//60}min", flush=True)
        _time.sleep(20)
        failures = 0
        while True:
            try:
                with _urllib_req.urlopen(_PING_TARGET, timeout=_PING_TIMEOUT) as r:
                    print(f"[KEEP-ALIVE] ✅ {r.status} OK", flush=True)
                    failures = 0
            except _urllib_err.URLError as exc:
                failures += 1
                print(f"[KEEP-ALIVE] ⚠️  attempt {failures} failed: {exc.reason}", flush=True)
            except Exception as exc:
                failures += 1
                log.error("[KEEP-ALIVE] %s", exc)

            wait = min(_PING_INTERVAL, _PING_INTERVAL * (2 ** max(0, failures - 1)))
            wait = min(wait, 13 * 60)
            _time.sleep(wait)

    _ka_thread = threading.Thread(target=_keep_alive, daemon=True, name="keep-alive")
    _ka_thread.start()

    _RESTART_DELAY = 10
    _MAX_RESTARTS  = 10

    _restart_count = 0
    while True:
        try:
            print(f"[BOT] Starting bot (restart #{_restart_count})...", flush=True)
            main()
            print("[BOT] main() exited normally — restarting in case of clean shutdown.", flush=True)
        except (KeyboardInterrupt, SystemExit):
            print("[BOT] Shutdown requested — exiting.", flush=True)
            break
        except Exception as _exc:
            _restart_count += 1
            print(f"[BOT] Crash #{_restart_count}: {_exc}", flush=True)
            if _restart_count >= _MAX_RESTARTS:
                print(f"[BOT] Too many crashes ({_MAX_RESTARTS}). Giving up.", flush=True)
                raise
            print(f"[BOT] Restarting in {_RESTART_DELAY}s…", flush=True)
            _time.sleep(_RESTART_DELAY)
