"""
/help  — User command guide with category buttons
/helpadmin — Full admin command reference
"""
from telegram.error import BadRequest, TimedOut
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
import config


async def _safe_edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        try:
            await query.message.reply_text(text, **kwargs)
        except Exception:
            pass
    except TimedOut:
        pass


# ── HELP PAGES ────────────────────────────────────────────────────────────

def _help_pages():
    total_skills = sum(len(skills) for skills in config.SKILLS.values())
    return {
        "home": (
            "🗡️ *DEMON SLAYER RPG — HELP*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Choose a category to see all commands:\n\n"
            "⚔️ *Combat* — Explore, duel, raids\n"
            "🧬 *Character* — Profile, style, skills\n"
            "🏪 *Economy* — Shop, market, bank\n"
            "🏯 *Clan* — Clan raids, roles, members\n"
            "👥 *Party* — Co-op, travel, party\n"
            "📖 *Info* — Guides, ranks, status effects\n"
            "⚙️ *Settings* — Toggles, deactivate skills\n\n"
            "🔒 = DM only for `/explore` and `/menu`\n"
            "💡 Use /know for the full game guide"
        ),
        "combat": (
            "⚔️ *COMBAT COMMANDS*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🗺️ *Explore* 🔒DM\n"
            "  `/explore` — Enter battle with an enemy\n"
            "  _Use menu buttons: Attack, Technique, Items, Flee_\n"
            "  _Type /explore to unstuck if stuck in battle_\n\n"
            "⚔️ *PvP Duel*\n"
            "  `/challenge @user` — Challenge someone to a duel\n"
            "  _Works in groups and DM_\n"
            "  _Settings: HP multiplier, Techniques Only, No Items_\n\n"
            "💨 *Breathing / Art*\n"
            "  `/breathing` — Your breathing style & forms\n"
            "  `/art` — Your demon art & forms\n"
            "  `/info [name]` — View any style's full form list\n\n"
            "⚡ *Marks & Power*\n"
            "  `/slayermark` — Activate Slayer Mark (+25% ATK)\n"
            "  `/demonmark` — Activate Demon Mark (+20% ATK)\n"
            "  `/hybrid` — Unlock Hybrid Mode (2 arts in battle)\n\n"
            "🏰 *Raids*\n"
            "  `/joinraid` — Join world boss raid\n"
            "  `/raidattack` — Attack the boss\n\n"
            "👥 *Co-op*\n"
            "  `/joinbattle` — Join party co-op battle\n"
        ),
        "character": (
            "🧬 *CHARACTER COMMANDS*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📊 *Profile*\n"
            "  `/profile` — Your full character card\n"
            "  `/rankings` — Leaderboards (XP, Yen, Kills, SP)\n"
            "  `/myid` — Your Telegram ID\n"
            "  `/referral` — Your referral link (+bonus if used)\n\n"
            "🗡️ *Style & Art*\n"
            "  `/breathing` — Spin for a breathing style (slayer)\n"
            "  `/art` — Spin for a demon art (demon)\n"
            "  `/changestyle` — Change your equipped style\n"
            "  `/info [name]` — Details on any style/art\n"
            "  `/know` → Styles tab — all breathing styles\n\n"
            "🌳 *Skills* (SP = Skill Points from PvP wins)\n"
            f"  `/skilltree` — Browse all {total_skills} skills by category\n"
            "  `/skills` — Your owned skills with buttons\n"
            "  `/skillbuy [name]` — Buy a skill\n"
            "  `/skillinfo [name]` — Detailed skill info\n"
            "  `/skilllist` — List all skills\n"
            "  `/deactivate [name]` — Turn off a skill\n"
            "  `/reactivate [name]` — Turn on a skill\n"
            "  `/deactivateall` — Disable all skills\n"
            "  `/reactivateall` — Enable all skills\n\n"
            "🔨 *Gear*\n"
            "  `/equip [item]` — Equip sword/armor\n"
            "  `/upgrade` — Craft better gear (stat boost!)\n"
        ),
        "economy": (
            "🏪 *ECONOMY COMMANDS*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "💰 *Daily Income*\n"
            "  `/daily` — Claim daily Yen reward\n"
            "  `/streak` — View your daily streak\n\n"
            "🏪 *Shop*\n"
            "  `/shop` — Browse shop by category\n"
            "  `/buy [code]` — Buy item by code\n"
            "  `/buy [name]` — Buy item by name\n"
            "  `/sell [item]` — Sell item for Yen\n"
            "  `/use [item]` — Use a consumable\n"
            "  `/inventory` — View your items\n\n"
            "🏷️ *Player Market*\n"
            "  `/market` — Browse player listings\n"
            "  `/market [search]` — Search listings\n"
            "  `/buy market [item] [qty]` — Buy from market\n"
            "  `/list [item] [price]` — List item for sale\n"
            "  `/list [item] [qty] [price]` — List multiple\n"
            "  `/unlist [item]` — Remove your listing\n"
            "  `/markethistory` — Your trade history\n\n"
            "🌑 *Black Market* (10pm–6am UTC)\n"
            "  `/blackmarket` — Browse rare items\n"
            "  `/bmbuy [id or name]` — Buy item\n\n"
            "🏦 *Bank*\n"
            "  `/bank` — View balance & tiers\n"
            "  `/deposit [amount]` — Deposit Yen\n"
            "  `/withdraw [amount]` — Withdraw Yen\n"
            "  `/bankupgrade` — Upgrade bank tier\n\n"
            "💸 *Transfers*\n"
            "  `/give @user [amount]` — Send Yen to someone\n"
            "  `/gift @user [item]` — Gift an item\n\n"
            "🎰 *Gambling*\n"
            "  `/lottery` — Buy lottery tickets\n"
            "  `/auction` — View active auctions\n"
            "  `/bid [id] [amount]` — Bid on auction\n"
            "  `/offers` — Limited time offers\n"
        ),
        "clan": (
            "🏯 *CLAN COMMANDS*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🏯 *Clan Management*\n"
            "  `/clan` — Clan menu & info\n"
            "  `/claninfo` — Detailed clan info\n"
            "  `/createclan [name]` — Create clan (50,000¥)\n"
            "  `/joinclan [name]` — Request to join\n"
            "  `/joinclan [leader ID]` — Join by Telegram ID\n"
            "  `/leaveclan` — Leave your clan\n"
            "  `/clandisband` — Disband clan (leader only)\n"
            "  `/clan_list` — Browse all clans\n\n"
            "👑 *Roles & Members*\n"
            "  `/clanrole @user [chief|deputy|officer|member]`\n"
            "  `/promotevice @user` — Promote to vice leader\n"
            "  `/demote @user` — Demote member\n"
            "  `/kick @user` — Kick member\n"
            "  `/clanmembers` — View all members\n"
            "  `/renameclan [name]` — Rename clan\n"
            "  `/setclanlink [url]` — Set group link\n"
            "  `/clanannounce [msg]` — Announce to clan\n"
            "  `/clandeposit [item]` — Deposit to clan vault\n"
            "  `/clanleaderboard` — Top clans ranking\n\n"
            "⚔️ *Clan Raids*\n"
            "  `/clanraid bosses` — List raid bosses\n"
            "  `/clanraid start [boss]` — Start a raid\n"
            "  `/clanraid join` — Join active raid (fee: 500¥)\n"
            "  `/clanraid attack` — Attack boss (5min cooldown)\n"
            "  `/clanraid status` — Boss HP + damage board\n"
            "  `/clanraid end` — End raid & distribute rewards\n"
            "  _Cooldown: 3 days between raids_\n"
            "  _Rewards based on damage dealt_\n"
        ),
        "party": (
            "👥 *PARTY & TRAVEL*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "👥 *Party*\n"
            "  `/party` — Party menu\n"
            "  `/invite @user` — Invite to party\n"
            "  `/joinbattle` — Join co-op battle\n\n"
            "🗺️ *Travel*\n"
            "  `/travel` — Change region\n"
            "  _Regions: Asakusa, Butterfly Estate,_\n"
            "  _Mt. Sagiri, Swordsmith Village,_\n"
            "  _Yoshiwara, Mugen Train, Infinity Castle_\n"
            "  _Each region has different enemies & pressure_\n\n"
            "📊 *Rankings*\n"
            "  `/rankings` — Main leaderboard\n"
            "  _Tabs: XP/Level, Yen, Kills, SP_\n\n"
            "📣 *Social*\n"
            "  `/suggest [idea]` — Submit a suggestion\n"
            "  `/is [id]` — View a suggestion\n"
            "  `/referral` — Get your referral link\n"
        ),
        "info": (
            "📖 *INFO & GUIDE COMMANDS*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📖 *Game Guides*\n"
            "  `/guide` — Full gameplay guide with buttons\n"
            "  `/know` — Game encyclopedia (styles, ranks, economy)\n"
            "  `/help` — This command list\n\n"
            "🔍 *Lookups*\n"
            "  `/info [style name]` — Any breathing style or art\n"
            "  `/info water` — Water Breathing forms & effects\n"
            "  `/info ice` — Ice Manipulation (15 forms!)\n"
            "  `/skillinfo [name]` — Skill details & bonuses\n"
            "  `/infoall` — All styles overview (owner)\n\n"
            "🏅 *Rank System*\n"
            "  Slayer: Mizunoto → Mizunoe → … → Kinoe → Hashira\n"
            "  Demon: Stray → Lesser → … → Upper Moon 1 → Demon King\n"
            "  _Higher rank = more forms unlocked in battle_\n"
            "  _Earn XP from /explore to rank up_\n\n"
            "💊 *Status Effects*\n"
            "  `/know` → Status tab — all 24 effects explained\n\n"
            "📋 *Logs* (admin)\n"
            "  `/logs` — Recent admin actions\n"
            "  `/logstats` — Log statistics\n"
            "  `/logsearch [term]` — Search logs\n"
            "  `/loguser @user` — Actions on a player\n"
        ),
        "settings": (
            "⚙️ *SETTINGS & MISC*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🌳 *Skill Management*\n"
            "  `/deactivate` — View active/deactivated skills\n"
            "  `/deactivate [name]` — Turn off a skill\n"
            "  `/reactivate [name]` — Turn on a skill\n"
            "  `/deactivateall` — Disable ALL skills\n"
            "  `/reactivateall` — Enable ALL skills\n\n"
            "🔧 *Misc*\n"
            "  `/unstuck` — Fix stuck battle state\n"
            "  `/menu` — Open quick menu 🔒DM\n"
            "  `/myid` — Your Telegram user ID\n\n"
            "📱 *Commands that work in GROUPS*\n"
            "  /profile /rankings /help /daily /streak /mission\n"
            "  /challenge /clan /claninfo /shop /buy /sell\n"
            "  /inventory /market /give /gift /skills /skilltree\n"
            "  /info /know /breathing /art /guide /upgrade\n"
            "  /travel /bank /deposit /withdraw /party /invite\n"
            "  /joinbattle /joinraid /raidattack /list /unlist\n"
            "  /markethistory /blackmarket /bmbuy /lottery /bid\n"
            "  /clanraid /clanrole /unstuck\n\n"
            "🔒 *DM Only commands*\n"
            "  /explore /menu\n"
        ),
    }


def _help_keyboard(current="home"):
    cats = [
        ("🏠 Home",      "home"),
        ("⚔️ Combat",    "combat"),
        ("🧬 Character", "character"),
        ("🏪 Economy",   "economy"),
        ("🏯 Clan",      "clan"),
        ("👥 Party",     "party"),
        ("📖 Info",      "info"),
        ("⚙️ Settings",  "settings"),
    ]
    buttons = []
    row = []
    for label, key in cats:
        marker = "·" if key == current else ""
        row.append(InlineKeyboardButton(f"{marker}{label}", callback_data=f"help_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/help — Full command guide with category buttons."""
    pages = _help_pages()
    text = pages["home"]
    msg = update.message or (update.callback_query.message if update.callback_query else None)
    if not msg:
        return
    await msg.reply_text(text, parse_mode="Markdown", reply_markup=_help_keyboard("home"))


async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help category button presses."""
    query = update.callback_query
    await query.answer()
    if not query.data.startswith("help_"):
        return
    key   = query.data[len("help_"):]
    pages = _help_pages()
    if key not in pages:
        await query.answer("❓ Unknown section.", show_alert=True)
        return
    text = pages[key]
    if len(text) > 4000:
        text = text[:3900] + "\n\n_...use /guide for more_"
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_help_keyboard(key))
    except Exception as e:
        if "not modified" not in str(e).lower():
            try:
                await query.message.reply_text(text, parse_mode="Markdown", reply_markup=_help_keyboard(key))
            except Exception:
                pass


# ── ADMIN HELP ────────────────────────────────────────────────────────────

ADMIN_HELP_PAGES = {
    "admin_home": (
        "⚙️ *ADMIN COMMAND REFERENCE*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Choose a category:\n\n"
        "👑 *Owner* — Sudo, ban, reset\n"
        "🎁 *Give* — XP, Yen, items, SP\n"
        "📢 *Broadcast* — Announce, events\n"
        "⚔️ *Raids* — World raids\n"
        "🌑 *Market* — Black market mgmt\n"
        "🔧 *Tools* — Logs, stats, toggles\n"
        "🏯 *Clan* — Clan management"
    ),
    "admin_owner": (
        "👑 *OWNER-ONLY COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔑 *Sudo Management*\n"
        "  `/addsudo @user` — Promote to admin\n"
        "  `/removesudo @user` — Remove admin\n"
        "  `/listadmins` — List all admins\n\n"
        "🚫 *Ban System*\n"
        "  `/ban @user [reason]` — Ban a player\n"
        "  `/unban @user` — Unban a player\n"
        "  _Banned players can't use ANY command_\n\n"
        "🔄 *Player Reset*\n"
        "  `/resetplayer @user` — Full reset (keeps ID)\n"
        "  `/adminunstuck @user` — Unstuck stuck battle\n\n"
        "👑 *Special Give*\n"
        "  `/giveultimate @user` — Give Absolute Biokinesis\n"
        "  `/giveslayermark @user` — Give Slayer Mark\n"
        "  `/givedemonmark @user` — Give Demon Mark\n"
        "  `/givestyle @user [style]` — Give any breathing style\n"
        "  `/giveart @user [art]` — Give any demon art\n\n"
        "🌟 *Master Command*\n"
        "  `/master @user` — Give EVERYTHING to a player\n"
        "  `/master @user [item] [amount]` — Give specific item\n\n"
        "💾 *Backup*\n"
        "  `/backup` — Export full DB as JSON\n"
        "  `/restore` — Import from JSON file\n\n"
        "👁️ *Owner Panel*\n"
        "  `/ownermode` — Toggle owner god mode\n"
        "  `/owneraccess [on|off]` — Toggle owner access\n"
        "  `/ownersetlevel @user [level]` — Set player level\n"
        "  `/ownersetstyle @user [style]` — Set player style\n"
        "  `/ownergive @user [yen] [xp] [sp]` — Bulk give\n"
        "  `/ownerreset @user` — Reset player\n"
        "  `/ownerban @user [reason]` — Owner ban\n"
        "  `/ownerunban @user` — Owner unban\n"
        "  `/ownermsg @user [msg]` — DM a player\n"
        "  `/ownerstats` — Full bot analytics\n"
        "  `/ownerplayers` — Browse all players\n"
    ),
    "admin_give": (
        "🎁 *GIVE COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "All give commands work by @username or Telegram ID.\n\n"
        "💰 *Economy*\n"
        "  `/giveyen @user [amount]` — Give Yen\n"
        "  `/givexp @user [amount]` — Give XP\n"
        "  `/givesp @user [amount]` — Give Skill Points\n\n"
        "📦 *Items*\n"
        "  `/giveitem @user [item name]` — Give 1 item\n"
        "  `/giveitem @user [item name] [qty]` — Give multiple\n"
        "  _Item types: sword, armor, item, material, scroll_\n\n"
        "📜 *Custom Missions*\n"
        "  `/addmission [difficulty] [xp] [yen] [name]`\n"
        "  `/removemission [mission name]`\n"
        "  `/listmissions` — View active custom missions\n\n"
        "⭐ *Style & Power*\n"
        "  `/givestyle @user [style name]` — Give breathing style\n"
        "  `/giveart @user [art name]` — Give demon art\n"
        "  `/giveultimate @user` — Give Absolute Biokinesis\n"
        "  `/giveslayermark @user` — Grant Slayer Mark\n"
        "  `/givedemonmark @user` — Grant Demon Mark\n\n"
        "👑 *Bulk Give*\n"
        "  `/master @user` — Give everything\n"
        "  _Gives: Max items, 999999 Yen, 1000 SP, all marks_\n"
    ),
    "admin_broadcast": (
        "📢 *BROADCAST & EVENTS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📢 *Announcements*\n"
        "  `/announce [message]`\n"
        "  _Sends to ALL active (non-banned) players_\n"
        "  _Message is sent as plain text exactly as typed_\n"
        "  _Rate limited: 25 msgs/sec safely_\n\n"
        "🎉 *Events*\n"
        "  `/event [name]` — Start an event\n"
        "  `/events` — View active events\n"
        "  `/eventend` — End current event\n"
        "  `/eventresults` — Show event results\n"
        "  `/eventlist` — List all events\n"
        "  `/vote [option]` — Vote on event\n\n"
        "🎯 *Offers*\n"
        "  `/addoffer [hrs] [price] [orig] [stock] [emoji] [item]`\n"
        "  _Example: `/addoffer 24 5000 9999 10 🗡️ Flame Sword`_\n"
        "  `/offers` — View current offers\n\n"
        "🎰 *Auctions*\n"
        "  `/addauction [hours] [item name]` — Create auction\n"
        "  _Players bid with /bid [amount]_\n"
    ),
    "admin_raids": (
        "⚔️ *RAID MANAGEMENT*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🏰 *World Raids (Admin-controlled)*\n"
        "  `/startraid [boss name]` — Start global boss raid\n"
        "  `/stopraid` — End the raid\n"
        "  _Players join with /joinraid and attack with /raidattack_\n\n"
        "⚔️ *Clan Raids (Leader-controlled)*\n"
        "  _Leaders start with /clanraid start [boss]_\n"
        "  Bosses: Muzan, Kokushibo, Doma, Akaza, Gyokko, Gyutaro\n"
        "  _Admin cannot directly control clan raids_\n"
        "  _3-day cooldown between raids per clan_\n\n"
        "📊 *Raid Stats*\n"
        "  `/botstats` — Shows active raids count\n"
        "  `/activeusers` — Recent active players\n"
    ),
    "admin_market": (
        "🌑 *BLACK MARKET MANAGEMENT*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🌑 *Black Market* (normally 10pm–6am UTC)\n"
        "  `/openblackmarket` — Force open NOW\n"
        "  `/closeblackmarket` — Force close\n"
        "  `/addblackmarket [price] [stock] [item name]`\n"
        "  _Example: `/addblackmarket 50000 3 Boss Shard`_\n"
        "  _Item type is auto-detected from shop catalog_\n\n"
        "🏪 *Player Market*\n"
        "  _Admin cannot directly remove player listings_\n"
        "  _Use /sqlview market_listings to inspect_\n\n"
        "🔨 *Upgrade System*\n"
        "  `/upgradetoggle` — Enable/disable /upgrade command\n"
        "  `/hybridtoggle` — Enable/disable /hybrid command\n\n"
        "📸 *Images*\n"
        "  `/setimage [style name]` — Upload battle image\n"
        "  _Reply to image with this command_\n"
        "  `/listimages` — See which styles have images\n"
    ),
    "admin_tools": (
        "🔧 *ADMIN TOOLS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📊 *Stats & Monitoring*\n"
        "  `/botstats` — Full bot statistics\n"
        "  `/activeusers` — Players active in last 24h\n"
        "  `/ownerstats` — Detailed analytics\n\n"
        "📋 *Logs*\n"
        "  `/logs` — Recent admin actions\n"
        "  `/logstats` — Log summary stats\n"
        "  `/logsearch [keyword]` — Search logs\n"
        "  `/loguser @user` — All actions on a player\n\n"
        "🗄️ *Database*\n"
        "  `/sqlview [table]` — View MongoDB collection\n"
        "  _Tables: players, market_listings, duels, clans_\n"
        "  _black_market, admin_logs, battle_state_\n"
        "  `/backup` — Export full DB as JSON file\n"
        "  `/restore` — Import DB from JSON file\n\n"
        "🔧 *Fixes*\n"
        "  `/adminunstuck @user` — Clear stuck battle\n"
        "  `/resetplayer @user` — Full player reset\n\n"
        "📋 *Suggestions*\n"
        "  `/suggestions` — View all pending suggestions\n"
        "  `/is [id]` — View specific suggestion\n"
        "  _Approve/dismiss via buttons on suggestion_\n"
    ),
    "admin_clan": (
        "🏯 *CLAN ADMIN*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📋 *View Clans*\n"
        "  `/clan_list` — Browse all clans with pagination\n"
        "  `/clanleaderboard` — Top clans ranking\n\n"
        "🔧 *Clan Management*\n"
        "  _Admins cannot forcefully edit clans_\n"
        "  _Players manage their own clans_\n"
        "  _Use /sqlview clans to inspect DB directly_\n\n"
        "👑 *Leader Commands* (for reference)\n"
        "  `/clanraid start [boss]` — Start raid\n"
        "  `/clanrole @user [chief|deputy|officer|member]`\n"
        "  `/promotevice @user` — Promote vice leader\n"
        "  `/kick @user` — Kick member\n"
        "  `/clandisband` — Disband clan\n"
        "  `/renameclan [name]` — Rename\n"
        "  `/clanannounce [msg]` — Clan announcement\n"
    ),
}


def _admin_help_keyboard(current="admin_home"):
    cats = [
        ("🏠 Home",      "admin_home"),
        ("👑 Owner",     "admin_owner"),
        ("🎁 Give",      "admin_give"),
        ("📢 Broadcast", "admin_broadcast"),
        ("⚔️ Raids",     "admin_raids"),
        ("🌑 Market",    "admin_market"),
        ("🔧 Tools",     "admin_tools"),
        ("🏯 Clan",      "admin_clan"),
    ]
    buttons = []
    row = []
    for label, key in cats:
        marker = "·" if key == current else ""
        row.append(InlineKeyboardButton(f"{marker}{label}", callback_data=f"ahelp_{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)


async def admin_help_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/helpadmin — Paginated admin command reference."""
    from handlers.admin import has_admin_access
    if not has_admin_access(update.effective_user.id):
        await update.message.reply_text("❌ Admin only.")
        return
    text = ADMIN_HELP_PAGES["admin_home"]
    await update.message.reply_text(
        text, parse_mode="Markdown",
        reply_markup=_admin_help_keyboard("admin_home")
    )


async def admin_help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin help category button presses."""
    query = update.callback_query
    await query.answer()
    from handlers.admin import has_admin_access
    if not has_admin_access(query.from_user.id):
        await query.answer("❌ Admin only.", show_alert=True)
        return
    if not query.data.startswith("ahelp_"):
        return
    key = query.data[len("ahelp_"):]
    if key not in ADMIN_HELP_PAGES:
        await query.answer("❓ Unknown section.", show_alert=True)
        return
    text = ADMIN_HELP_PAGES[key]
    try:
        await query.edit_message_text(
            text, parse_mode="Markdown",
            reply_markup=_admin_help_keyboard(key)
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            try:
                await query.message.reply_text(
                    text, parse_mode="Markdown",
                    reply_markup=_admin_help_keyboard(key)
                )
            except Exception:
                pass
