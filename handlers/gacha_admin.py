"""
handlers/gacha_admin.py — OWNER cross-universe spirit management

The owner can open rifts to OTHER ANIME UNIVERSES and add new summonable
spirits at runtime (no code changes / restarts needed). Players see a button
in the summon shrine whose LABEL the owner decides themselves.

Commands (owner only):
  /ownerspirits                                → admin panel (buttons + help)
  /ownergacha add <Universe> | <Emoji> | <Name> | <Rarity> | <atk%,def%,hp%>
        Example: /ownergacha add Naruto | 🦊 | Nine-Tailed Fox Spirit | Legendary | 15,0,10
  /ownergacha remove <Spirit Name>             → delete from the summon pool
  /ownergacha label <your own button text>     → rename the cross-universe
        button that players tap in /summon ("Spirits of Different Universe")
  /ownergacha list [Universe]                  → show current roster

Callback prefix: ospi_   (rendered by gacha_callback via utils.spirits)
"""
import logging
log = logging.getLogger(__name__)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import OWNER_ID
from utils.database import col
from utils.spirits import (
    get_all_spirits, add_spirit_to_pool, remove_spirit_from_pool,
    get_universes, spirits_in_universe,
)

VALID_RARITIES = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]

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


def _is_owner(uid) -> bool:
    return uid == OWNER_ID


# ── /ownergacha command ────────────────────────────────────────────────────
async def ownergacha(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    if not _is_owner(user_id):
        await query.answer("👑 Owner only.", show_alert=True)
        return

    args = (context.args or [])
    sub = args[0].lower() if args else "help"
    rest = " ".join(args[1:])

    if sub == "add":
        # format: Universe | Emoji | Name | Rarity | atk%,def%,hp%
        parts = [p.strip() for p in rest.split("|")]
        if len(parts) < 3:
            await query.message.reply_text(
                "❌ Usage:\n"
                "`/ownergacha add Naruto | 🦊 | Nine-Tailed Fox Spirit | Legendary | 15,0,10`\n\n"
                "Fields: Universe | Emoji | Name | Rarity (Common/Uncommon/Rare/Epic/Legendary) | "
                "passives atk%,def%,hp% (optional)",
                parse_mode="Markdown",
            )
            await query.answer()
            return
        universe, emoji, name = parts[0], parts[1], parts[2]
        rarity = parts[3] if len(parts) > 3 and parts[3] in VALID_RARITIES else "Rare"
        passive = {}
        if len(parts) > 4:
            nums = [x.strip() for x in parts[4].split(",")]
            keys = ["atk_pct", "def_pct", "hp_pct", "sta_pct", "spd_pct"]
            for i, n in enumerate(nums[:5]):
                try:
                    v = float(n)
                    if v:
                        passive[keys[i]] = round(v / 100.0, 4)
                except ValueError:
                    pass
        ok = add_spirit_to_pool({
            "name": name, "emoji": emoji, "rarity": rarity,
            "universe": universe, "lore": f"Summoned from the {universe} universe.",
            "passive": passive,
        })
        if ok:
            await query.message.reply_text(
                f"✅ Rift opened! *{emoji} {name}* ({rarity}) from *{universe}* "
                f"is now summonable by all players.\n\n"
                f"Players will see it when they tap the cross-universe button in /summon."
                + (f"\nPassive: {passive}" if passive else ""),
                parse_mode="Markdown",
            )
        else:
            await query.message.reply_text("❌ Could not add spirit (empty name?).")
        await query.answer()
        return

    if sub == "remove":
        name = rest.strip()
        if not name:
            await query.answer("Usage: /ownergacha remove <Spirit Name>", show_alert=True)
            return
        removed = remove_spirit_from_pool(name)
        if removed:
            await query.message.reply_text(f"🗑️ *{name}* removed from the summon pool.", parse_mode="Markdown")
        else:
            await query.message.reply_text(
                f"⚠️ *{name}* is not in the runtime pool.\n"
                f"(Config default spirits cannot be removed — edit config.py for those.)",
                parse_mode="Markdown",
            )
        await query.answer()
        return

    if sub == "label":
        label = rest.strip()
        if not label:
            await query.answer("Usage: /ownergacha label <button text>", show_alert=True)
            return
        label = label[:60]  # Telegram button length limit
        set_btn_label(label)
        await query.message.reply_text(
            f"🏷️ Cross-universe button renamed to:\n*{label}*\n\nPlayers will see this in /summon.",
            parse_mode="Markdown",
        )
        await query.answer()
        return

    if sub == "list":
        universe = rest.strip()
        pool = spirits_in_universe(universe) if universe else get_all_spirits()
        if not pool:
            await query.message.reply_text("🈳 No spirits found for that filter.")
            await query.answer()
            return
        lines = []
        for s in pool[:40]:
            lines.append(f"• {s['emoji']} {s['name']} [{s['rarity']}] — {s.get('universe', '?')}")
        await query.message.reply_text(
            f"📖 *SPIRIT POOL* ({len(pool)} shown)\n" + "\n".join(lines),
            parse_mode="Markdown",
        )
        await query.answer()
        return

    # help / unknown
    await query.message.reply_text(
        "🌌 *OWNER SPIRIT RIFT COMMANDS*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        "`/ownergacha add Naruto | 🍥 | Kurama's Shadow | Legendary | 18,0,10`\n"
        "→ adds a spirit from another anime to the gacha pool\n\n"
        "`/ownergacha remove <Name>` → delete a runtime-added spirit\n"
        "`/ownergacha label <text>` → set YOUR OWN text on the cross-universe button\n"
        "`/ownergacha list [Universe]` → browse the pool\n\n"
        "Or use the buttons: /ownerspirits",
        parse_mode="Markdown",
    )
    await query.answer()


# ── /ownerspirits panel ────────────────────────────────────────────────────
async def ownerspirits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner control panel: universes overview + quick actions."""
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("👑 Owner only.")
        return

    pool = get_all_spirits()
    uni_counts = {}
    for s in pool:
        u = s.get("universe") or "Custom"
        uni_counts[u] = uni_counts.get(u, 0) + 1

    rows = []
    for u, c in sorted(uni_counts.items()):
        safe = u.replace("_", "__")  # simple escape for callback payload
        rows.append([InlineKeyboardButton(f"🌌 {u} ({c})", callback_data=f"ospi_view_{safe}")])
    kb = [
        rows[:6] or [[InlineKeyboardButton("🌌 No universes yet", callback_data="ospi_noop")]],
        [InlineKeyboardButton("➕ Add Spirit", callback_data="ospi_addhelp"),
         InlineKeyboardButton("🏷️ Set Button Label", callback_data="ospi_labelhelp")],
        [InlineKeyboardButton("📖 Full Pool", callback_data="ospi_full"),
         InlineKeyboardButton("🔄 Refresh", callback_data="ospi_refresh")],
    ]
    text = (
        "🌌 *SPIRIT RIFT CONTROL — OWNER PANEL*\n"
        "━━━━━━━━━━━━━━━━━━━━━\n"
        f"Total summonable spirits: *{len(pool)}*\n"
        f"Player button label: *{get_btn_label()}*\n\n"
        "Tap a universe to inspect its spirits, or use the buttons below.\n"
        "_Add spirits from any anime with:_\n"
        "`/ownergacha add <Universe> | <Emoji> | <Name> | <Rarity> | <atk,def,hp%>`"
    )
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")


async def ownerspirits_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    user_id = query.from_user.id
    if not _is_owner(user_id):
        await query.answer("👑 Owner only.", show_alert=True)
        return

    if data == "ospi_noop":
        await query.answer()
        return

    if data.startswith("ospi_view_"):
        universe = data[len("ospi_view_"):].replace("__", "_")
        spirits = spirits_in_universe(universe)
        if spirits:
            lines = [f"• {s['emoji']} *{s['name']}* [{s['rarity']}]" for s in spirits[:40]]
            body = "\n".join(lines)
        else:
            body = "_No spirits in this universe yet._\nUse `/ownergacha add ...` to create some."
        await query.edit_message_text(
            f"🌌 *UNIVERSE: {universe}*\n━━━━━━━━━━━━━━━━━━\n{body}\n\n"
            f"➕ Add more: `/ownergacha add {universe} | 👻 | Spirit Name | Rare | 5,5,0`",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="ospi_refresh")]]),
            parse_mode="Markdown",
        )
        await query.answer()
        return

    if data == "ospi_addhelp":
        await query.edit_message_text(
            "➕ *ADD A SPIRIT FROM ANY ANIME*\n\n"
            "Reply to this with the command (in DM):\n"
            "`/ownergacha add Jujutsu Kaisen | 👁️ | Cursed Spirit of the Abyss | Epic | 12,0,0`\n\n"
            "Format: `Universe | Emoji | Name | Rarity | atk%,def%,hp%`\n"
            f"Rarities: {', '.join(VALID_RARITIES)}\n"
            "You may invent your own universe names too!",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="ospi_refresh")]]),
            parse_mode="Markdown",
        )
        await query.answer()
        return

    if data == "ospi_labelhelp":
        await query.edit_message_text(
            "🏷️ *SET THE PLAYER-FACING BUTTON TEXT*\n\n"
            f"Current label: *{get_btn_label()}*\n\n"
            "Choose whatever you want displayed on the button players tap in /summon:\n"
            "`/ownergacha label 🌌 Spirits of Different Universe`\n"
            "`/ownergacha label ⭐ Summon Other Anime Legends`\n\n"
            "(max 60 characters)",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="ospi_refresh")]]),
            parse_mode="Markdown",
        )
        await query.answer()
        return

    if data in ("ospi_full", "ospi_refresh"):
        # Re-render the panel as a new message (editing loses formatting simply)
        from copy import deepcopy
        fake_update = deepcopy(update)
        try:
            await query.answer()
        except Exception:
            pass
        # Send fresh panel to the chat
        pool = get_all_spirits()
        uni_counts = {}
        for s in pool:
            u = s.get("universe") or "Custom"
            uni_counts[u] = uni_counts.get(u, 0) + 1
        rows = [[InlineKeyboardButton(f"🌌 {u} ({c})", callback_data=f"ospi_view_{u.replace('_', '__')}")]
                for u, c in sorted(uni_counts.items())][:6]
        kb = [
            rows or [[InlineKeyboardButton("🌌 No universes yet", callback_data="ospi_noop")]],
            [InlineKeyboardButton("➕ Add Spirit", callback_data="ospi_addhelp"),
             InlineKeyboardButton("🏷️ Set Button Label", callback_data="ospi_labelhelp")],
            [InlineKeyboardButton("📖 Full Pool", callback_data="ospi_full"),
             InlineKeyboardButton("🔄 Refresh", callback_data="ospi_refresh")],
        ]
        text = (
            "🌌 *SPIRIT RIFT CONTROL — OWNER PANEL*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            f"Total summonable spirits: *{len(pool)}*\n"
            f"Player button label: *{get_btn_label()}*\n\n"
            "Tap a universe to inspect its spirits.\n"
            "`/ownergacha add <Universe> | <Emoji> | <Name> | <Rarity> | <atk,def,hp%>`"
        )
        try:
            await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        except Exception:
            await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="Markdown")
        return

    await query.answer()
