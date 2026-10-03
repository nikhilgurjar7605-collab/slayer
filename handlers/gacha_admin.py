"""
handlers/gacha_admin.py — OWNER cross-universe spirit management

Two commands only:

  /spiritsadmin                     → owner control panel (buttons + help)
  /spiritadd                        → add a spirit from ANY anime universe.
        The owner types the command WITHOUT arguments; the bot then asks in
        plain language, one question at a time (conversation):
            Universe name  →  Emoji  →  Spirit name  →  Rarity  →  Passives
        No rigid syntax to memorise.

The added spirits are stored in the "gacha_spirits" Mongo collection via
utils.spirits, persist across restarts, and instantly become summonable by
every player through the cross-universe button in /summon. The label of that
player-facing button is set from the panel (owner decides the text himself).

Callback prefix: ospi_   (registered separately in bot.py)
"""
import logging
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


def _panel_keyboard() -> InlineKeyboardMarkup:
    pool = get_all_spirits()
    uni_counts = {}
    for s in pool:
        u = s.get("universe") or "Custom"
        uni_counts[u] = uni_counts.get(u, 0) + 1
    rows = [[InlineKeyboardButton(f"🌌 {u} ({c})", callback_data=f"ospi_view_{u.replace('_', '__')}")]
            for u, c in sorted(uni_counts.items())][:6]
    kb = [
        rows or [[InlineKeyboardButton("🌌 No universes yet", callback_data="ospi_noop")]],
        [InlineKeyboardButton("➕ Add Spirit (/spiritadd)", callback_data="ospi_addhelp")],
        [InlineKeyboardButton("🏷️ Set Summon Button Label", callback_data="ospi_labelhelp")],
        [InlineKeyboardButton("🔄 Refresh Panel", callback_data="ospi_refresh")],
    ]
    return InlineKeyboardMarkup(kb)


async def _send_panel(bot, chat_id, edit_msg=None):
    pool = get_all_spirits()
    text = (
        "🌌 *SPIRIT RIFT CONTROL — OWNER PANEL*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total summonable spirits: *{len(pool)}*\n"
        f"Player button label: *{get_btn_label()}*\n\n"
        "Tap a universe to inspect its spirits.\n\n"
        "➜ *Add* a spirit from any anime: use `/spiritadd` (guided)\n"
        "➜ *Remove:* `/spiritadd remove <Name>`\n"
        "➜ *Rename* the players' cross-universe summon button with the 🏷️ button below."
    )
    kb = _panel_keyboard()
    if edit_msg is not None:
        try:
            await edit_msg.edit_text(text, reply_markup=kb, parse_mode="Markdown")
            return
        except Exception:
            pass
    await bot.send_message(chat_id=chat_id, text=text, reply_markup=kb, parse_mode="Markdown")


# ═══════════════════════════════════════════════════════════════════════════
#  COMMAND 1 — /spiritsadmin  (owner panel)
# ═══════════════════════════════════════════════════════════════════════════
async def spiritsadmin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("👑 Owner only.")
        return
    await _send_panel(context.bot, update.effective_chat.id)


# ═══════════════════════════════════════════════════════════════════════════
#  COMMAND 2 — /spiritadd  (guided conversation, owner only)
#    "/spiritadd remove <Name>" also handled here as a quick sub-form.
# ═══════════════════════════════════════════════════════════════════════════
async def spiritadd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("👑 Owner only.")
        return ConversationHandler.END

    args = " ".join(context.args or []).strip()
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
        await _send_panel(context.bot, update.effective_chat.id)
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
    """Register the two owner commands. Call once from bot.py main()."""
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
        per_chat=False, per_user=True, per_args=False,
        conversation_timeout=300,
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler('spiritsadmin', spiritsadmin))
    app.add_handler(CallbackQueryHandler(spiritsadmin_callback, pattern=r'^ospi_(view_|noop|addhelp|labelhelp|refresh|full)'), group=1)


# ── Panel callbacks ────────────────────────────────────────────────────────
async def spiritsadmin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="ospi_refresh")]]),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await query.answer()
        return

    if data == "ospi_addhelp":
        try:
            await query.edit_message_text(
                "➕ *ADD A SPIRIT FROM ANY ANIME*\n\n"
                "Just type:\n`/spiritadd`\n\n"
                "The bot will ask you, one by one:\n"
                "1️⃣ Universe name (any anime — or invent your own!)\n"
                "2️⃣ Emoji\n"
                "3️⃣ Spirit name\n"
                "4️⃣ Rarity (buttons: Common → Legendary)\n"
                "5️⃣ Optional passives: `atk%, def%, hp%` e.g. `15,0,10` or `skip`\n\n"
                "The spirit is instantly summonable by every player!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="ospi_refresh")]]),
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await query.answer()
        return

    if data == "ospi_labelhelp":
        # Ask the owner to simply reply with the new label text.
        context.user_data["awaiting_label"] = True
        try:
            await query.edit_message_text(
                "🏷️ *SET THE PLAYER-FACING SUMMON BUTTON TEXT*\n\n"
                f"Current label: *{get_btn_label()}*\n\n"
                "Now *reply with the exact text* you want players to see on the "
                "cross-universe button in /summon (max 60 characters).\n\n"
                "_(You can also do it later with `/spiritadd label <text>`)_",
                parse_mode="Markdown",
            )
        except Exception:
            pass
        await query.answer()
        return

    if data in ("ospi_full", "ospi_refresh"):
        try:
            await query.answer()
        except Exception:
            pass
        await _send_panel(context.bot, query.message.chat_id, edit_msg=query.message)
        return

    await query.answer()


# ── Label capture (plain message after tapping 🏷️ Set Button Label) ───────
async def label_capture(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """If the owner tapped 'Set Button Label', their next plain text message
    becomes the new cross-universe button label."""
    if not context.user_data.get("awaiting_label"):
        return None
    text = (update.message.text or "").strip()
    if not text:
        return None
    context.user_data.pop("awaiting_label", None)
    label = text[:60]
    set_btn_label(label)
    await update.message.reply_text(
        f"🏷️ Done! Players now see this button in /summon:\n*{label}*\n\n"
        f"_Spirits from other universes summonable: {len(get_all_spirits())}_",
        parse_mode="Markdown",
    )
    return True
