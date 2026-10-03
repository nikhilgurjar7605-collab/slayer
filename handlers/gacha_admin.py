"""
handlers/gacha_admin.py — OWNER cross-universe spirit management

ONE command only:

  /spiritadd                        → add a spirit from ANY anime universe.
        The owner types the command WITHOUT arguments; the bot then asks in
        plain language, one question at a time (conversation):
            Universe name  →  Emoji  →  Spirit name  →  Rarity  →  Passives
        No rigid syntax to memorise.

Quick sub-forms of the same command:
  /spiritadd list                   → show every universe & spirit in the pool
  /spiritadd label <text>           → rename the players' cross-universe
                                       summon button (owner decides the text)
  /spiritadd remove <Name>          → delete a runtime-added spirit

The added spirits are stored in the "gacha_spirits" Mongo collection via
utils.spirits, persist across restarts, and instantly become summonable by
every player through the cross-universe button in /summon.

Callback prefix: ospi_   (rarity picker inside the conversation)
"""
import logging
import os
log = logging.getLogger(__name__)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ContextTypes, ConversationHandler, CommandHandler,
    CallbackQueryHandler, MessageHandler, filters,
)

from config import OWNER_ID
from utils.database import col
from utils.spirits import (
    get_all_spirits, add_spirit_to_pool, remove_spirit_from_pool,
    spirits_in_universe, invalidate_cache, find_pool_spirit,
    block_spirit, unblock_spirit, blocked_names,
)


def _admin_gate(uid) -> bool:
    """Admin/owner access check that NEVER raises.

    Every sub-call is individually guarded so a failure in one path (e.g. the
    Mongo lookup inside has_admin_access) can't abort the whole command with an
    unhandled exception — that was why /spiritadd appeared to 'do nothing'.
    """
    try:
        if _is_owner(uid):
            return True
    except Exception:
        log.exception("gacha admin gate (_is_owner) failed")
    try:
        from handlers.temp_owner import is_temp_owner
        if is_temp_owner(int(uid)):
            return True
    except Exception:
        pass
    try:
        from handlers.admin import has_admin_access
        if has_admin_access(int(uid)):
            return True
    except Exception:
        log.debug("has_admin_access lookup failed", exc_info=True)
    return False

# ── Boss difficulty scaling (single source of truth) ───────────────────────
# Bosses are intentionally brutal — players NEED strong spirits to win.
# explore.py, raid_manager.py and clan_raid.py all import these so every
# boss path scales identically.
BOSS_HP_MULT      = 6     # boss HP multiplier            (was 3)
BOSS_ATK_MULT     = 2.2   # boss ATK multiplier           (was 1.5)
BOSS_XP_MULT      = 4     # reward XP multiplier          (was 3)
BOSS_YEN_MULT     = 4     # reward Yen multiplier         (was 3)
BOSS_LEVEL_HP_K   = 0.10  # +10% boss HP per player level (was 0.05)
BOSS_LEVEL_ATK_K  = 0.06  # +6%  boss ATK per player level (was 0.03)


def spirit_level_multiplier(level: int) -> float:
    """Combat-relevant spirit passives grow ~2% per player level (capped x2.5).

    This is what lets spirits keep pace against the heavily-scaled bosses —
    a Lv-100 player's Legendary Phoenix grants far more than at Lv-10.
    """
    return min(2.5, 1.0 + max(0, int(level or 1) - 1) * 0.02)


# ── Robust owner check: OWNER_ID + temp owner + env override + sudo admins ─
def _owner_ids() -> set:
    ids = {OWNER_ID}
    try:
        extra = os.environ.get("EXTRA_OWNER_IDS", "")
        for tok in extra.replace(";", ",").split(","):
            tok = tok.strip()
            if tok.lstrip("-").isdigit():
                ids.add(int(tok))
    except Exception:
        pass
    try:
        from config import SUDO_ADMIN_IDS
        ids.update(SUDO_ADMIN_IDS)
    except Exception:
        pass
    return ids


def _is_owner(uid) -> bool:
    """Owner (or temp owner / sudo admin) — same rules as the rest of the bot."""
    try:
        uid = int(uid)
    except (TypeError, ValueError):
        return False
    if uid in _owner_ids():
        return True
    try:
        from handlers.admin import is_owner as _bot_is_owner
        if _bot_is_owner(uid):
            return True
    except Exception:
        pass
    try:
        from handlers.admin import has_admin_access
        if has_admin_access(uid):
            return True
    except Exception:
        pass
    return False

VALID_RARITIES = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]

# Conversation states for /spiritadd
ASK_UNIVERSE, ASK_EMOJI, ASK_NAME, ASK_RARITY, ASK_PASSIVE, ASK_MOVE, ASK_IMAGE = range(7)


# ── Runtime settings stored in Mongo ("gacha_settings" collection) ─────────
def get_btn_label() -> str:
    try:
        doc = col("gacha_settings").find_one({"key": "cross_btn_label"})
        if doc and doc.get("value"):
            return doc["value"]
    except Exception as e:
        log.debug("gacha_settings read failed: %s", e)
    from config import GACHA_CROSS_BTN_LABEL
    return GACHA_CROSS_BTN_LABEL


def set_btn_label(label: str):
    col("gacha_settings").update_one(
        {"key": "cross_btn_label"},
        {"$set": {"key": "cross_btn_label", "value": label}},
        upsert=True,
    )
    invalidate_cache()


def _list_pool_text() -> str:
    """Owner-friendly overview of every universe & spirit in the pool."""
    pool = get_all_spirits()
    uni_counts = {}
    for s in pool:
        u = s.get("universe") or "Custom"
        uni_counts.setdefault(u, [])
        uni_counts[u].append(s)
    lines = [
        "🌌 *SUMMON POOL*",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"Total spirits: *{len(pool)}*  ·  Button label: *{get_btn_label()}*",
        "",
    ]
    for u in sorted(uni_counts):
        spirits = uni_counts[u]
        lines.append(f"*{u}* ({len(spirits)})")
        for s in spirits[:12]:
            lines.append(f"  {s.get('emoji','👻')} {s.get('name','?')} [{s.get('rarity','Common')}]")
        if len(spirits) > 12:
            lines.append(f"  …and {len(spirits)-12} more")
        lines.append("")
    lines.extend([
        "📖 *HOW TO USE* — gacha admin commands:",
        "• `/spiritadd` → guided: asks Universe → Emoji → Name → Rarity → Passives",
        "• `/spiritadd list` → this pool view",
        "• `/spiritadd label <text>` → rename the players' summon button",
        "• `/spiritremove <Name>` → remove ANY spirit from gacha",
        "   (runtime spirits are deleted; config defaults get blocked)",
        "• `/spiritunblock <Name>` → put a removed/blocked spirit back in the pool",
    ])
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
#  THE ONE COMMAND — /spiritadd  (guided conversation, owner only)
#    Sub-forms handled here too: list / label <text> / remove <Name>
# ═══════════════════════════════════════════════════════════════════════════
async def spiritadd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _admin_gate(user_id):
        await update.message.reply_text("👑 Owner/admin only.")
        return ConversationHandler.END

    args = " ".join(context.args or []).strip()

    if args.lower() in ("list", "pool", "show"):
        await update.message.reply_text(_list_pool_text(), parse_mode="Markdown")
        return ConversationHandler.END

    if args.lower().startswith("remove "):
        await _do_remove(update, args[len("remove "):].strip())
        return ConversationHandler.END

    if args.lower().startswith("label "):
        label = args[len("label "):].strip()[:60]
        if label:
            set_btn_label(label)
            await update.message.reply_text(f"🏷️ Player button renamed to:\n*{label}*", parse_mode="Markdown")
        else:
            await update.message.reply_text("Usage: `/spiritadd label <button text>`", parse_mode="Markdown")
        return ConversationHandler.END

    context.user_data["new_spirit"] = {}
    await update.message.reply_text(
        "✨ *ADD A SPIRIT FROM ANY ANIME UNIVERSE*\n\n"
        "I'll guide you step by step. Type *cancel* anytime to stop.\n\n"
        "🌌 *1/6* — Which universe does this spirit come from?\n"
        "_Example: Naruto, Jujutsu Kaisen, Bleach, or invent your own!_",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_UNIVERSE


async def _do_remove(update: Update, name: str):
    """Shared removal logic for /spiritremove and `/spiritadd remove <Name>`.

    • Runtime-added spirits are deleted from the pool permanently.
    • config.GACHA_SPIRITS defaults cannot be deleted from code, so they get
      *blocked* — instantly pulled out of every player's gacha (persisted in
      Mongo). Undo with `/spiritunblock <Name>`.
    """
    if not name:
        await update.message.reply_text(
            "Usage: `/spiritremove <Spirit Name>`\n"
            "Example: `/spiritremove Nine-Tailed Fox Spirit`",
            parse_mode="Markdown")
        return
    target = find_pool_spirit(name)          # case-insensitive, merged pool
    if remove_spirit_from_pool(name):        # runtime (DB) spirit → deleted
        await update.message.reply_text(
            f"🗑️ *{name}* removed from the summon pool.", parse_mode="Markdown")
        return
    if target:                               # config default → block it
        block_spirit(target["name"])
        await update.message.reply_text(
            f"🚫 *{target['name']}* blocked from the summon pool!\n"
            f"It no longer appears in anyone's /summon rolls.\n"
            f"_It lives in config.py, so it was blocked (not deleted). "
            f"Undo anytime with_ `/spiritunblock {target['name']}`",
            parse_mode="Markdown")
        return
    already = {b.lower() for b in blocked_names()}
    if name.lower() in already:
        await update.message.reply_text(
            f"⚠️ *{name}* is already blocked from the pool.\n"
            f"Undo with `/spiritunblock {name}`", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"❓ No spirit named *{name}* in the pool.\n"
            f"Check exact spelling with `/spiritadd list`.", parse_mode="Markdown")


async def spiritremove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/spiritremove <Name> — admin command to remove any spirit from gacha."""
    if not update.message:
        return
    user_id = update.effective_user.id
    if not _admin_gate(user_id):
        await update.message.reply_text("👑 Owner/admin only.")
        return
    await _do_remove(update, " ".join(context.args or []).strip())


async def spiritunblock_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/spiritunblock <Name> — re-enable a previously removed/blocked spirit."""
    if not update.message:
        return
    user_id = update.effective_user.id
    if not _admin_gate(user_id):
        await update.message.reply_text("👑 Owner/admin only.")
        return
    name = " ".join(context.args or []).strip()
    if not name:
        await update.message.reply_text("Usage: `/spiritunblock <Spirit Name>`", parse_mode="Markdown")
        return
    if unblock_spirit(name):
        await update.message.reply_text(
            f"✅ *{name}* is back in the summon pool!", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"⚠️ *{name}* was not blocked. Nothing to undo.", parse_mode="Markdown")


async def spiritadd_universe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text.lower() == "cancel":
        await update.message.reply_text("🚫 Cancelled.")
        return ConversationHandler.END
    if len(text) > 40:
        text = text[:40]
    context.user_data["new_spirit"]["universe"] = text
    await update.message.reply_text(
        f"🌌 Universe: *{text}*\n\n"
        "🎭 *2/6* — Pick an emoji for the spirit.\n"
        "_Example: 🦊 👁️ ⭐ 🔥 🐉 (just send the emoji)_",
        parse_mode="Markdown",
    )
    return ASK_EMOJI


async def spiritadd_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text.lower() == "cancel":
        await update.message.reply_text("🚫 Cancelled.")
        return ConversationHandler.END
    emoji = text[:8] if text else "👻"
    context.user_data["new_spirit"]["emoji"] = emoji
    await update.message.reply_text(
        f"🎭 Emoji: {emoji}\n\n"
        "👻 *3/6* — What is the spirit's name?\n"
        "_Example: Nine-Tailed Fox Spirit, Cursed Spirit of the Abyss..._",
        parse_mode="Markdown",
    )
    return ASK_NAME


async def spiritadd_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text.lower() == "cancel":
        await update.message.reply_text("🚫 Cancelled.")
        return ConversationHandler.END
    if not text:
        await update.message.reply_text("Please type a spirit name (or *cancel*).", parse_mode="Markdown")
        return ASK_NAME
    context.user_data["new_spirit"]["name"] = text[:60]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{get_rarity_emoji(r)} {r}", callback_data=f"ospi_rar_{r}") for r in VALID_RARITIES[:3]],
        [InlineKeyboardButton(f"{get_rarity_emoji(r)} {r}", callback_data=f"ospi_rar_{r}") for r in VALID_RARITIES[3:]],
    ])
    await update.message.reply_text(
        f"👻 Spirit: *{text[:60]}*\n\n"
        "⭐ *4/6* — Choose its rarity:",
        parse_mode="Markdown", reply_markup=kb,
    )
    return ASK_RARITY


def get_rarity_emoji(r: str) -> str:
    try:
        from config import GACHA_RARITY_EMOJI
        return GACHA_RARITY_EMOJI.get(r, "✨")
    except Exception:
        return "✨"


async def spiritadd_rarity_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not _admin_gate(query.from_user.id):
        await query.answer("👑 Owner/admin only.", show_alert=True)
        return ASK_RARITY
    data = query.data or ""
    if not data.startswith("ospi_rar_"):
        await query.answer()
        return ASK_RARITY
    rarity = data[len("ospi_rar_"):]
    if rarity not in VALID_RARITIES:
        rarity = "Rare"
    context.user_data["new_spirit"]["rarity"] = rarity
    try:
        await query.edit_message_text(
            f"⭐ Rarity: *{rarity}*\n\n"
            "📈 *5/6* — Passive bonuses? Send three numbers:\n"
            "`atk%, def%, hp%`\n"
            "_Example:_ `15,0,10`  ·  or send *skip* for none.\n"
            "_Tip: Epic/Legendary spirits can carry big numbers (e.g. `30,25,20`)._",
            parse_mode="Markdown", reply_markup=None,
        )
    except Exception:
        await query.message.reply_text(
            f"⭐ Rarity: *{rarity}*\n\nSend passives as `atk%, def%, hp%` (e.g. `15,0,10`) or *skip*.",
            parse_mode="Markdown")
    await query.answer()
    return ASK_PASSIVE


async def spiritadd_passive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = (update.message.text or "").strip()
    ns = context.user_data.get("new_spirit", {})
    if msg_text.lower() == "cancel":
        await update.message.reply_text("🚫 Cancelled.")
        return ConversationHandler.END
    passive = {}
    if msg_text.lower() not in ("skip", "none", "-", "0", ""):
        keys = ["atk_pct", "def_pct", "hp_pct", "sta_pct", "spd_pct"]
        nums = [x.strip() for x in msg_text.split(",")]
        for i, n in enumerate(nums[:5]):
            try:
                v = float(n)
                if v:
                    passive[keys[i]] = round(v / 100.0, 4)
            except ValueError:
                pass
    ns["passive"] = passive
    await update.message.reply_text(
        (_fmt_passive(passive) + "\n\n") if passive else "No passives.\n\n",
        "⚔️ *6/6a* — Signature battle move?\n"
        "Send the text shown in battle logs when the spirit attacks.\n"
        "Use `{e}` for its emoji and `{n}` for its name.\n"
        "_Example:_ `{e} {n} unleashes Rasengan: Spirit Fang!`\n"
        "Send *skip* for a default line based on rarity.",
        parse_mode="Markdown",
    )
    return ASK_MOVE


async def spiritadd_move(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_text = (update.message.text or "").strip()
    ns = context.user_data.get("new_spirit", {})
    if msg_text.lower() == "cancel":
        await update.message.reply_text("🚫 Cancelled.")
        return ConversationHandler.END
    if msg_text.lower() not in ("skip", "none", "-"):
        ns["move"] = msg_text[:200]
    await update.message.reply_text(
        "🖼️ *6/6b* — Spirit artwork (optional).\n"
        "Send a *photo* now and it will be stored with the spirit (shown when\n"
        "players summon it), or type an *image URL*, or send *skip* for none.",
        parse_mode="Markdown",
    )
    return ASK_IMAGE


def _extract_image_ref(msg) -> str:
    """Pull a file_id (photo/sticker/document) out of a Telegram message."""
    try:
        if msg.photo:
            return msg.photo[-1].file_id          # highest resolution
        if msg.sticker:
            return msg.sticker.file_id
        if msg.document:
            return msg.document.file_id
    except Exception:
        pass
    return ""


async def spiritadd_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalise spirit creation from whatever we collected (image optional)."""
    ns = context.user_data.get("new_spirit", {})
    universe = ns.get("universe", "Custom")
    ok = add_spirit_to_pool({
        "name": ns.get("name", ""),
        "emoji": ns.get("emoji", "👻"),
        "rarity": ns.get("rarity", "Rare"),
        "universe": universe,
        "lore": f"Summoned from the {universe} universe.",
        "passive": ns.get("passive", {}),
        "move": ns.get("move", ""),
        "image": ns.get("image", ""),
    })
    if ok:
        # If this name was previously blocked (e.g. a config default the owner
        # removed earlier), un-block it so the fresh spirit actually appears.
        try:
            unblock_spirit(ns.get("name", ""))
        except Exception:
            pass
        _caption = (
            f"✅ Rift opened! {ns.get('emoji','👻')} *{ns.get('name','')}* "
            f"({ns.get('rarity','Rare')}) from *{universe}* is now summonable by ALL players!\n\n"
            f"They appear under the cross-universe button in /summon and fight beside "
            f"players who equip them."
            + (f"\n⚔️ Move: {ns.get('move')}" if ns.get("move") else "")
            + (f"\nPassive: {_fmt_passive(ns.get('passive', {}))}" if ns.get("passive") else "")
        )
        try:
            if ns.get("image"):
                await update.message.reply_photo(photo=ns["image"], caption=_caption,
                                                 parse_mode="Markdown")
            else:
                raise ValueError("no image")
        except Exception:
            await update.message.reply_text(_caption, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Could not add spirit (empty name?). Try /spiritadd again.")
    context.user_data.pop("new_spirit", None)
    return ConversationHandler.END


async def spiritadd_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ASK_IMAGE state: accept a photo OR a URL text OR skip."""
    msg = update.message
    user_id = msg.from_user.id
    if not _admin_gate(user_id):
        return ASK_IMAGE
    ref = _extract_image_ref(msg)
    if ref:
        context.user_data.setdefault("new_spirit", {})["image"] = ref
        return await spiritadd_finish(update, context)
    text = (msg.text or "").strip()
    if not text:
        await msg.reply_text("Send a photo, an image URL, or *skip*.", parse_mode="Markdown")
        return ASK_IMAGE
    if text.lower() in ("skip", "cancel", "none", "-"):
        if text.lower() == "cancel":
            await msg.reply_text("🚫 Cancelled.")
            context.user_data.pop("new_spirit", None)
            return ConversationHandler.END
        return await spiritadd_finish(update, context)
    if text.startswith(("http://", "https://")):
        context.user_data.setdefault("new_spirit", {})["image"] = text
    return await spiritadd_finish(update, context)


def _fmt_passive(passive: dict) -> str:
    labels = {"atk_pct": "⚔️ATK", "def_pct": "🛡️DEF", "hp_pct": "❤️HP", "sta_pct": "🌀STA", "spd_pct": "⚡SPD"}
    parts = [f"{labels.get(k, k)} +{int(round(v * 100))}%" for k, v in passive.items()]
    return " | ".join(parts) if parts else "—"


async def spiritadd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Spirit creation cancelled.")
    return ConversationHandler.END


def register_spirit_admin(app):
    """Register the gacha admin commands + guided /spiritadd conversation.
    Call once from bot.py main()."""
    conv = ConversationHandler(
        entry_points=[CommandHandler('spiritadd', spiritadd_start)],
        states={
            ASK_UNIVERSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, spiritadd_universe)],
            ASK_EMOJI:    [MessageHandler(filters.TEXT & ~filters.COMMAND, spiritadd_emoji)],
            ASK_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, spiritadd_name)],
            ASK_RARITY:   [CallbackQueryHandler(spiritadd_rarity_cb, pattern=r'^ospi_rar_')],
            ASK_PASSIVE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, spiritadd_passive)],
            ASK_MOVE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, spiritadd_move)],
            ASK_IMAGE:    [MessageHandler((filters.PHOTO | filters.Sticker.ALL | filters.Document.ALL)
                                          | (filters.TEXT & ~filters.COMMAND), spiritadd_image)],
        },
        fallbacks=[
            CommandHandler('cancel', spiritadd_cancel),
            CommandHandler('spiritadd', spiritadd_start),
        ],
        per_chat=False, per_user=True,
        conversation_timeout=300,
    )
    # Priority group so the guided flow is never swallowed by global handlers.
    app.add_handler(conv, group=1)

    # ── Direct admin commands for removing spirits from gacha ─────────────
    # Registered in group=0 BEFORE callback_router etc., same as every other
    # command; plain CommandHandler works in DMs and groups.
    app.add_handler(CommandHandler('spiritremove', spiritremove_cmd))
    app.add_handler(CommandHandler('spiritunblock', spiritunblock_cmd))


# ── (legacy panel callbacks kept as no-ops for old messages still on screen) ─
async def spiritsadmin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles taps on any older /spiritsadmin panel messages that may still
    exist in chats after the upgrade to the single-command design."""
    query = update.callback_query
    data = query.data or ""
    if not _admin_gate(query.from_user.id):
        await query.answer("👑 Owner/admin only.", show_alert=True)
        return

    if data == "ospi_noop":
        await query.answer("No universes yet — use /spiritadd to create one!")
        return

    if data.startswith("ospi_view_"):
        universe = data[len("ospi_view_"):].replace("__", "_")
        spirits = spirits_in_universe(universe)
        if spirits:
            lines = [f"• {s['emoji']} *{s['name']}* [{s['rarity']}]" for s in spirits[:40]]
            body = "\n".join(lines)
        else:
            body = "_No spirits in this universe yet._\nUse `/spiritadd` to create some."
        try:
            await query.edit_message_text(
                f"🌌 *UNIVERSE: {universe}*\n━━━━━━━━━━━━━━━━━━\n{body}\n\n"
                f"➕ Add more with `/spiritadd` · 🗑️ Remove: `/spiritadd remove <Name>`",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await query.answer()
        return

    # Everything else → just point the owner at the one command.
    try:
        await query.edit_message_text(_list_pool_text(), parse_mode="Markdown")
    except Exception:
        pass
    await query.answer()
