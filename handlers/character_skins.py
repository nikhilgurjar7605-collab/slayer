"""
Character Skin System
─────────────────────────────────────────────────────────────
Owner commands:
  /addskin <name> <rarity> <file_id> [gif]
      Add a character skin. Rarity: common | rare | legendary
      Append 'gif' at the end if the file_id is an animation.
      Example: /addskin Giyu rare CgACAgIA... gif
      Example: /addskin Tanjiro common AgACAgIA...

  /removeskin <skin_id>
      Remove a skin by its MongoDB _id (shown in /listskins).

  /listskins
      List all skins in the database (owner/admin only).

  /giveskin <user_id> <skin_id>
      Give a skin to a player for free.

Player commands:
  /skins
      Browse all available skins. Shows one at a time with
      Prev / Next / Buy / Equip / Remove buttons.

Rarity tiers & default prices (editable below):
  Common    →  5,000 ¥
  Rare      → 20,000 ¥
  Legendary → 75,000 ¥

The equipped skin's image/GIF is shown whenever the player
uses /skins — it acts as their "character card".
"""

import logging
from bson import ObjectId
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup
)
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, col

log = logging.getLogger(__name__)

SKIN_COL = "character_skins"

# ── Rarity config ──────────────────────────────────────────────────────────
RARITIES = {
    "common":    {"label": "Common",    "emoji": "⚪", "price": 5_000},
    "rare":      {"label": "Rare",      "emoji": "🔵", "price": 20_000},
    "legendary": {"label": "Legendary", "emoji": "🟡", "price": 75_000},
}

# ── Default hardcoded skins (added to DB on first run if missing) ──────────
# Format: (name, rarity, file_id, is_gif)
# Replace file_id values with your actual Telegram file IDs.
DEFAULT_SKINS = [
    ("Standard",  "common",    "YOUR_STANDARD_FILE_ID",  False),
    ("Tanjiro",   "rare",      "YOUR_TANJIRO_FILE_ID",   False),
    ("Giyu",      "rare",      "YOUR_GIYU_FILE_ID",      False),
    ("Sanemi",    "rare",      "YOUR_SANEMI_FILE_ID",    False),
    ("Zenitsu",   "rare",      "YOUR_ZENITSU_FILE_ID",   False),
    ("Inosuke",   "rare",      "YOUR_INOSUKE_FILE_ID",   False),
    ("Muzan",     "legendary", "YOUR_MUZAN_FILE_ID",     False),
    ("Akaza",     "legendary", "YOUR_AKAZA_FILE_ID",     False),
]


def _ensure_defaults():
    """Insert default skins into DB if they don't exist yet."""
    for name, rarity, file_id, is_gif in DEFAULT_SKINS:
        if file_id.startswith("YOUR_"):
            continue  # skip placeholder entries
        existing = col(SKIN_COL).find_one({"name": name, "default": True})
        if not existing:
            col(SKIN_COL).insert_one({
                "name":    name,
                "rarity":  rarity,
                "file_id": file_id,
                "is_gif":  is_gif,
                "default": True,
            })


# ── DB helpers ─────────────────────────────────────────────────────────────

def _all_skins() -> list:
    _ensure_defaults()
    order = {"common": 0, "rare": 1, "legendary": 2}
    skins = list(col(SKIN_COL).find({}))
    skins.sort(key=lambda s: order.get(s.get("rarity", "common"), 0))
    return skins


def _get_skin(skin_id: str) -> dict | None:
    try:
        return col(SKIN_COL).find_one({"_id": ObjectId(skin_id)})
    except Exception:
        return None


def _add_skin(name: str, rarity: str, file_id: str, is_gif: bool) -> str:
    result = col(SKIN_COL).insert_one({
        "name":    name,
        "rarity":  rarity,
        "file_id": file_id,
        "is_gif":  is_gif,
        "default": False,
    })
    return str(result.inserted_id)


def _remove_skin(skin_id: str) -> bool:
    try:
        res = col(SKIN_COL).delete_one({"_id": ObjectId(skin_id)})
        return res.deleted_count > 0
    except Exception:
        return False


def _player_owns_skin(user_id: int, skin_id: str) -> bool:
    return col("player_skins").find_one({"user_id": user_id, "skin_id": skin_id}) is not None


def _give_skin_to_player(user_id: int, skin_id: str):
    if not _player_owns_skin(user_id, skin_id):
        col("player_skins").insert_one({"user_id": user_id, "skin_id": skin_id})


def _player_owned_skin_ids(user_id: int) -> set:
    return {doc["skin_id"] for doc in col("player_skins").find({"user_id": user_id})}


# ── Owner guard ────────────────────────────────────────────────────────────

def _is_owner(user_id: int) -> bool:
    from config import OWNER_ID
    return user_id == OWNER_ID


def _is_owner_or_admin(user_id: int) -> bool:
    from utils.database import is_admin
    return _is_owner(user_id) or is_admin(user_id)


# ── /addskin ───────────────────────────────────────────────────────────────

async def addskin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Owner only.
    /addskin <name> <rarity> <file_id> [gif]
    Rarity: common | rare | legendary
    Add 'gif' at end for animated skins.
    """
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    args = context.args
    if not args or len(args) < 3:
        await update.message.reply_text(
            "Usage: `/addskin <name> <rarity> <file_id> [gif]`\n\n"
            "Rarity options: `common` | `rare` | `legendary`\n\n"
            "Examples:\n"
            "`/addskin Giyu rare AgACAgIA...`\n"
            "`/addskin Zenitsu legendary CgACAgIA... gif`",
            parse_mode="Markdown"
        )
        return

    # Check if last arg is 'gif'
    is_gif = args[-1].lower() == "gif"
    if is_gif:
        args = args[:-1]

    if len(args) < 3:
        await update.message.reply_text("Not enough arguments. Need: name, rarity, file_id.")
        return

    file_id = args[-1].strip()
    rarity  = args[-2].strip().lower()
    name    = " ".join(args[:-2]).replace("_", " ").strip()

    if rarity not in RARITIES:
        await update.message.reply_text(
            f"❌ Invalid rarity `{rarity}`.\nMust be: `common`, `rare`, or `legendary`",
            parse_mode="Markdown"
        )
        return

    if not name:
        await update.message.reply_text("Please provide a name for the skin.")
        return

    skin_id = _add_skin(name, rarity, file_id, is_gif)
    r = RARITIES[rarity]
    log.info("[SKINS] Added skin '%s' rarity=%s id=%s by owner", name, rarity, skin_id)

    caption = (
        f"✅ Character Skin Added!\n\n"
        f"Name: {name}\n"
        f"Rarity: {r['emoji']} {r['label']}\n"
        f"Price: {r['price']:,} ¥\n"
        f"Type: {'GIF' if is_gif else 'Photo'}\n"
        f"ID: {skin_id}\n\n"
        f"Players can browse it with /skins."
    )

    try:
        if is_gif:
            await context.bot.send_animation(chat_id=user_id, animation=file_id, caption=caption)
        else:
            await context.bot.send_photo(chat_id=user_id, photo=file_id, caption=caption)
    except Exception as e:
        log.error("[SKINS] Preview failed: %s", e)
        await update.message.reply_text(caption + "\n\n(Preview failed — check file_id.)")


# ── /removeskin ────────────────────────────────────────────────────────────

async def removeskin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner only. /removeskin <skin_id>"""
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/removeskin <skin_id>`\n\nUse /listskins to see IDs.",
            parse_mode="Markdown"
        )
        return

    skin_id = context.args[0].strip()
    ok = _remove_skin(skin_id)
    if ok:
        await update.message.reply_text(f"✅ Skin `{skin_id}` removed.", parse_mode="Markdown")
    else:
        await update.message.reply_text(
            f"❌ No skin found with ID: `{skin_id}`\n\nUse /listskins to see valid IDs.",
            parse_mode="Markdown"
        )


# ── /listskins ─────────────────────────────────────────────────────────────

async def listskins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner/admin only."""
    user_id = update.effective_user.id
    if not _is_owner_or_admin(user_id):
        await update.message.reply_text("Admin only.")
        return

    skins = _all_skins()
    if not skins:
        await update.message.reply_text("No skins in the database yet.\n\nAdd with /addskin.")
        return

    lines = [f"🎭 Character Skins ({len(skins)} total)\n"]
    for s in skins:
        r    = RARITIES.get(s.get("rarity", "common"), RARITIES["common"])
        sid  = str(s["_id"])
        name = s.get("name", "?")
        gif  = " [GIF]" if s.get("is_gif") else ""
        lines.append(f"{r['emoji']} *{name}* — {r['label']}{gif}\n  `{sid}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /giveskin ──────────────────────────────────────────────────────────────

async def giveskin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner only. /giveskin <user_id> <skin_id>"""
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/giveskin <user_id> <skin_id>`",
            parse_mode="Markdown"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    skin_id = context.args[1].strip()
    skin    = _get_skin(skin_id)
    if not skin:
        await update.message.reply_text(f"❌ Skin `{skin_id}` not found.", parse_mode="Markdown")
        return

    target = get_player(target_id)
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    _give_skin_to_player(target_id, skin_id)
    await update.message.reply_text(
        f"✅ Gave *{skin['name']}* skin to *{target['name']}*!",
        parse_mode="Markdown"
    )
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"🎁 You received the *{skin['name']}* character skin!\nUse /skins to equip it.",
            parse_mode="Markdown"
        )
    except Exception:
        pass


# ── /skins — player UI ─────────────────────────────────────────────────────

def _skins_keyboard(
    index: int, total: int,
    skin_id: str, owned: bool, equipped: bool, price: int
) -> InlineKeyboardMarkup:
    rows = []

    # Nav row
    nav = []
    if index > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"skin_page|{index - 1}"))
    if index < total - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"skin_page|{index + 1}"))
    if nav:
        rows.append(nav)

    # Action row
    if equipped:
        rows.append([InlineKeyboardButton("✅ Equipped", callback_data="skin_noop")])
        rows.append([InlineKeyboardButton("🗑 Remove Skin", callback_data="skin_remove")])
    elif owned:
        rows.append([InlineKeyboardButton("👘 Equip", callback_data=f"skin_equip|{skin_id}")])
    else:
        rows.append([InlineKeyboardButton(f"🛒 Buy — {price:,} ¥", callback_data=f"skin_buy|{skin_id}")])

    rows.append([InlineKeyboardButton("🔙 Close", callback_data="skin_close")])
    return InlineKeyboardMarkup(rows)


async def skins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Entry point: /skins"""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    all_skins = _all_skins()
    if not all_skins:
        await update.message.reply_text(
            "🎭 No character skins available yet.\nCheck back later!"
        )
        return

    await _show_skin_page(update, context, all_skins, player, index=0, edit=False)


async def _show_skin_page(update, context, all_skins: list, player: dict, index: int, edit: bool):
    skin      = all_skins[index]
    skin_id   = str(skin["_id"])
    name      = skin.get("name", "Skin")
    rarity    = skin.get("rarity", "common")
    is_gif    = skin.get("is_gif", False)
    file_id   = skin["file_id"]
    total     = len(all_skins)
    user_id   = player["user_id"]

    r        = RARITIES.get(rarity, RARITIES["common"])
    price    = r["price"]
    owned    = _player_owns_skin(user_id, skin_id)
    equipped = player.get("equipped_skin_id") == skin_id

    keyboard = _skins_keyboard(index, total, skin_id, owned, equipped, price)

    status_line = "✅ Equipped" if equipped else ("✔ Owned" if owned else f"💰 {price:,} ¥")
    caption = (
        f"🎭 *Character Skins*\n\n"
        f"👤 Name: *{name}*\n"
        f"{r['emoji']} Rarity: *{r['label']}*\n"
        f"Status: {status_line}\n\n"
        f"({index + 1} / {total})"
    )

    try:
        if edit:
            # Delete old message and send new one
            msg = None
            if update.callback_query and update.callback_query.message:
                chat_id = update.callback_query.message.chat_id
                try:
                    await update.callback_query.message.delete()
                except Exception:
                    pass
            else:
                chat_id = update.effective_chat.id

            if is_gif:
                await context.bot.send_animation(
                    chat_id=chat_id, animation=file_id,
                    caption=caption, parse_mode="Markdown", reply_markup=keyboard
                )
            else:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=file_id,
                    caption=caption, parse_mode="Markdown", reply_markup=keyboard
                )
        else:
            msg = update.message or (
                update.callback_query.message if update.callback_query else None
            )
            if is_gif:
                await msg.reply_animation(
                    animation=file_id, caption=caption,
                    parse_mode="Markdown", reply_markup=keyboard
                )
            else:
                await msg.reply_photo(
                    photo=file_id, caption=caption,
                    parse_mode="Markdown", reply_markup=keyboard
                )
    except Exception as e:
        log.error("[SKINS] Could not send skin page: %s", e)
        err = "❌ Failed to load this skin. It may have been removed."
        if update.callback_query:
            await update.callback_query.answer(err, show_alert=True)
        else:
            await update.message.reply_text(err)


# ── Skin callbacks ─────────────────────────────────────────────────────────

async def skin_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prev / Next navigation."""
    query = update.callback_query
    await query.answer()

    try:
        index = int(query.data.split("|")[1])
    except (ValueError, IndexError):
        return

    user_id   = query.from_user.id
    player    = get_player(user_id)
    all_skins = _all_skins()
    if not all_skins or not player:
        return

    index = max(0, min(index, len(all_skins) - 1))
    await _show_skin_page(update, context, all_skins, player, index=index, edit=True)


async def skin_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Player buys a skin with Yen."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        skin_id = query.data.split("|")[1]
    except IndexError:
        return

    skin = _get_skin(skin_id)
    if not skin:
        await query.answer("❌ Skin no longer available.", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await query.answer("❌ Player not found.", show_alert=True)
        return

    if _player_owns_skin(user_id, skin_id):
        await query.answer("You already own this skin!", show_alert=True)
        return

    rarity = skin.get("rarity", "common")
    price  = RARITIES.get(rarity, RARITIES["common"])["price"]

    if player.get("yen", 0) < price:
        needed = price - player.get("yen", 0)
        await query.answer(
            f"❌ Not enough Yen!\nNeed {needed:,} ¥ more.",
            show_alert=True
        )
        return

    # Deduct yen and give skin
    update_player(user_id, yen=player["yen"] - price)
    _give_skin_to_player(user_id, skin_id)
    log.info("[SKINS] User %s bought skin '%s' for %s yen", user_id, skin.get("name"), price)

    # Refresh page to show Equip button
    player  = get_player(user_id)
    all_skins = _all_skins()
    index   = next((i for i, s in enumerate(all_skins) if str(s["_id"]) == skin_id), 0)
    await _show_skin_page(update, context, all_skins, player, index=index, edit=True)

    await query.answer(f"✅ Bought {skin['name']} for {price:,} ¥!", show_alert=False)


async def skin_equip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Player equips an owned skin."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        skin_id = query.data.split("|")[1]
    except IndexError:
        return

    skin = _get_skin(skin_id)
    if not skin:
        await query.answer("❌ Skin not found.", show_alert=True)
        return

    if not _player_owns_skin(user_id, skin_id):
        await query.answer("❌ You don't own this skin.", show_alert=True)
        return

    update_player(user_id, equipped_skin_id=skin_id)
    log.info("[SKINS] User %s equipped skin '%s'", user_id, skin.get("name"))

    player    = get_player(user_id)
    all_skins = _all_skins()
    index     = next((i for i, s in enumerate(all_skins) if str(s["_id"]) == skin_id), 0)
    await _show_skin_page(update, context, all_skins, player, index=index, edit=True)
    await query.answer(f"✅ {skin['name']} equipped!", show_alert=False)


async def skin_remove_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Player removes their equipped skin."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    update_player(user_id, equipped_skin_id=None)
    log.info("[SKINS] User %s removed equipped skin", user_id)

    player    = get_player(user_id)
    all_skins = _all_skins()
    await _show_skin_page(update, context, all_skins, player, index=0, edit=True)
    await query.answer("✅ Skin removed.", show_alert=False)


async def skin_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close the skins menu."""
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass


async def skin_noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """No-op for the 'Equipped' button."""
    await update.callback_query.answer("Already equipped!", show_alert=False)
