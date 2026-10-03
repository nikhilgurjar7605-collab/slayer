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
    spirits_in_universe, invalidate_cache,
)

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
ASK_UNIVERSE, ASK_EMOJI, ASK_NAME, ASK_RARITY, ASK_PASSIVE = range(5)


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


def _is_owner(uid) -> bool:
    return uid == OWNER_ID


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
        "📖 *HOW TO USE* — one command, `/spiritadd`:",
        "• `/spiritadd` → guided: asks Universe → Emoji → Name → Rarity → Passives",
        "• `/spiritadd list` → this pool view",
        "• `/spiritadd label <text>` → rename the players' summon button",
        "• `/spiritadd remove <Name>` → delete a runtime-added spirit",
    ])
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
#  THE ONE COMMAND — /spiritadd  (guided conversation, owner only)
#    Sub-forms handled here too: list / label <text> / remove <Name>
# ═══════════════════════════════════════════════════════════════════════════
async def spiritadd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("👑 Owner only.")
        return ConversationHandler.END

    args = " ".join(context.args or []).strip()

    if args.lower() in ("list", "pool", "show"):
        await update.message.reply_text(_list_pool_text(), parse_mode="Markdown")
        return ConversationHandler.END

    if args.lower().startswith("remove "):
        name = args[len("remove "):].strip()
        if not name:
            await update.message.reply_text("Usage: `/spiritadd remove <Spirit Name>`", parse_mode="Markdown")
            return ConversationHandler.END
        if remove_spirit_from_pool(name):
            await update.message.reply_text(f"🗑️ *{name}* removed from the summon pool.", parse_mode="Markdown")
        else:
            await update.message.reply_text(
                f"⚠️ *{name}* is not in the runtime pool.\n"
                f"(Config default spirits cannot be removed — edit config.py for those.)",
                parse_mode="Markdown")
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
        "🌌 *1/4* — Which universe does this spirit come from?\n"
        "_Example: Naruto, Jujutsu Kaisen, Bleach, or invent your own!_",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_UNIVERSE


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
        "🎭 *2/4* — Pick an emoji for the spirit.\n"
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
        "👻 *3/4* — What is the spirit's name?\n"
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
        "⭐ *4/4a* — Choose its rarity:",
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
    if not _is_owner(query.from_user.id):
        await query.answer("👑 Owner only.", show_alert=True)
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
            "📈 *4/4b* — Passive bonuses? Send three numbers:\n"
            "`atk%, def%, hp%`\n"
            "_Example:_ `15,0,10`  ·  or send *skip* for none.",
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
    passive = {}
    if msg_text.lower() not in ("skip", "cancel", "none", "-", "0", ""):
        keys = ["atk_pct", "def_pct", "hp_pct", "sta_pct", "spd_pct"]
        nums = [x.strip() for x in msg_text.split(",")]
        for i, n in enumerate(nums[:5]):
            try:
                v = float(n)
                if v:
                    passive[keys[i]] = round(v / 100.0, 4)
            except ValueError:
                pass
    if msg_text.lower() == "cancel":
        await update.message.reply_text("🚫 Cancelled.")
        return ConversationHandler.END

    universe = ns.get("universe", "Custom")
    ok = add_spirit_to_pool({
        "name": ns.get("name", ""),
        "emoji": ns.get("emoji", "👻"),
        "rarity": ns.get("rarity", "Rare"),
        "universe": universe,
        "lore": f"Summoned from the {universe} universe.",
        "passive": passive,
    })
    if ok:
        await update.message.reply_text(
            f"✅ Rift opened! *{ns.get('emoji')} {ns.get('name')}* ({ns.get('rarity')}) "
            f"from *{universe}* is now summonable by ALL players!\n\n"
            f"They appear under the cross-universe button in /summon and fight beside "
            f"players who equip them.\n"
            + (f"Passive: {_fmt_passive(passive)}" if passive else ""),
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("❌ Could not add spirit (empty name?). Try /spiritadd again.")
    context.user_data.pop("new_spirit", None)
    return ConversationHandler.END


def _fmt_passive(passive: dict) -> str:
    labels = {"atk_pct": "⚔️ATK", "def_pct": "🛡️DEF", "hp_pct": "❤️HP", "sta_pct": "🌀STA", "spd_pct": "⚡SPD"}
    parts = [f"{labels.get(k, k)} +{int(round(v * 100))}%" for k, v in passive.items()]
    return " | ".join(parts) if parts else "—"


async def spiritadd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Spirit creation cancelled.")
    return ConversationHandler.END


def register_spirit_admin(app):
    """Register the ONE owner command (/spiritadd) + its rarity picker.
    Call once from bot.py main()."""
    conv = ConversationHandler(
        entry_points=[CommandHandler('spiritadd', spiritadd_start)],
        states={
            ASK_UNIVERSE: [MessageHandler(filters.TEXT & ~filters.COMMAND, spiritadd_universe)],
            ASK_EMOJI:    [MessageHandler(filters.TEXT & ~filters.COMMAND, spiritadd_emoji)],
            ASK_NAME:     [MessageHandler(filters.TEXT & ~filters.COMMAND, spiritadd_name)],
            ASK_RARITY:   [CallbackQueryHandler(spiritadd_rarity_cb, pattern=r'^ospi_rar_')],
            ASK_PASSIVE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, spiritadd_passive)],
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


# ── (legacy panel callbacks kept as no-ops for old messages still on screen) ─
async def spiritsadmin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles taps on any older /spiritsadmin panel messages that may still
    exist in chats after the upgrade to the single-command design."""
    query = update.callback_query
    data = query.data or ""
    if not _is_owner(query.from_user.id):
        await query.answer("👑 Owner only.", show_alert=True)
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
