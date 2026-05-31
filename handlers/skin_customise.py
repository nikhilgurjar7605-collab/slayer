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

    # If this is the equipped skin and not a GIF, composite accessories on top
    composited_buf = None
    acc_note       = ""
    if equipped and not is_gif:
        try:
            from handlers.skin_customise import _build_character_image
            buf = await _build_character_image(context.bot, player)
            if buf:
                composited_buf = buf
                equipped_accs = player.get("equipped_accessories", {}) or {}
                eq_count = len([v for v in equipped_accs.values() if v])
                if eq_count:
                    acc_note = f"\n🎒 Accessories: *{eq_count} equipped*"
        except Exception as e:
            log.warning("[SKINS] Could not composite accessories: %s", e)

    caption = (
        f"🎭 *Character Skins*\n\n"
        f"👤 Name: *{name}*\n"
        f"{r['emoji']} Rarity: *{r['label']}*\n"
        f"Status: {status_line}"
        f"{acc_note}\n\n"
        f"({index + 1} / {total})"
    )

    async def _send(chat_id=None, reply_to=None):
        if composited_buf:
            composited_buf.seek(0)
            if chat_id:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=composited_buf,
                    caption=caption, parse_mode="Markdown", reply_markup=keyboard
                )
            else:
                await reply_to.reply_photo(
                    photo=composited_buf,
                    caption=caption, parse_mode="Markdown", reply_markup=keyboard
                )
        elif is_gif:
            if chat_id:
                await context.bot.send_animation(
                    chat_id=chat_id, animation=file_id,
                    caption=caption, parse_mode="Markdown", reply_markup=keyboard
                )
            else:
                await reply_to.reply_animation(
                    animation=file_id, caption=caption,
                    parse_mode="Markdown", reply_markup=keyboard
                )
        else:
            if chat_id:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=file_id,
                    caption=caption, parse_mode="Markdown", reply_markup=keyboard
                )
            else:
                await reply_to.reply_photo(
                    photo=file_id, caption=caption,
                    parse_mode="Markdown", reply_markup=keyboard
                )

    try:
        if edit:
            if update.callback_query and update.callback_query.message:
                chat_id = update.callback_query.message.chat_id
                try:
                    await update.callback_query.message.delete()
                except Exception:
                    pass
            else:
                chat_id = update.effective_chat.id
            await _send(chat_id=chat_id)
        else:
            msg = update.message or (
                update.callback_query.message if update.callback_query else None
            )
            await _send(reply_to=msg)
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


# ═══════════════════════════════════════════════════════════════════════════
# ACCESSORY / CHARACTER-CUSTOMISE SYSTEM
# ═══════════════════════════════════════════════════════════════════════════
"""
Accessory system appended to skin_customise.py
────────────────────────────────────────────────────────────────────────────
Owner / Admin commands:
  /addaccessory <slot> <name> <rarity> <file_id>
      Slots: hat | weapon | cape | mask | badge
  /removeaccessory <acc_id>
  /listaccessories
  /giveaccessory <user_id> <acc_id>

Player commands:
  /customise     — browse & equip accessories per slot
  /mycharacter   — preview current character with all equipped accessories
"""

import io
import logging

from bson import ObjectId
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, col

log = logging.getLogger(__name__)

ACC_COL   = "accessories"
ACC_SLOTS = ["hat", "weapon", "cape", "mask", "badge"]

ACC_RARITIES = {
    "common":    {"label": "Common",    "emoji": "⚪", "price": 3_000},
    "rare":      {"label": "Rare",      "emoji": "🔵", "price": 12_000},
    "legendary": {"label": "Legendary", "emoji": "🟡", "price": 40_000},
}


# ── DB helpers ─────────────────────────────────────────────────────────────

def _all_accessories(slot: str | None = None) -> list:
    query = {"slot": slot} if slot else {}
    return list(col(ACC_COL).find(query))


def _get_accessory(acc_id: str) -> dict | None:
    try:
        return col(ACC_COL).find_one({"_id": ObjectId(acc_id)})
    except Exception:
        return None


def _player_owns_acc(user_id: int, acc_id: str) -> bool:
    return col("player_accessories").find_one(
        {"user_id": user_id, "acc_id": acc_id}
    ) is not None


def _give_acc_to_player(user_id: int, acc_id: str):
    if not _player_owns_acc(user_id, acc_id):
        col("player_accessories").insert_one({"user_id": user_id, "acc_id": acc_id})


# ── Character image composer (stub — works even without PIL) ───────────────

async def _build_character_image(bot, player: dict):
    """
    Composite the equipped skin + accessories into one image.
    Returns a BytesIO buffer or None if PIL isn't available / skin is a GIF.
    """
    try:
        from PIL import Image, ImageDraw
        import requests, io as _io
    except ImportError:
        return None

    skin_id = player.get("equipped_skin_id")
    if not skin_id:
        return None

    skin = _get_skin(skin_id)
    if not skin or skin.get("is_gif"):
        return None

    try:
        file = await bot.get_file(skin["file_id"])
        resp = requests.get(file.file_path, timeout=10)
        base = Image.open(_io.BytesIO(resp.content)).convert("RGBA")
    except Exception as e:
        log.warning("[CUSTOMISE] Could not load base skin: %s", e)
        return None

    # Overlay each equipped accessory
    equipped_accs = player.get("equipped_accessories", {}) or {}
    for slot, acc_id in equipped_accs.items():
        if not acc_id:
            continue
        acc = _get_accessory(str(acc_id))
        if not acc:
            continue
        try:
            f   = await bot.get_file(acc["file_id"])
            r2  = requests.get(f.file_path, timeout=10)
            overlay = Image.open(_io.BytesIO(r2.content)).convert("RGBA")
            overlay = overlay.resize(base.size, Image.LANCZOS)
            base    = Image.alpha_composite(base, overlay)
        except Exception as e:
            log.warning("[CUSTOMISE] Could not overlay accessory %s: %s", slot, e)

    buf = _io.BytesIO()
    base.save(buf, format="PNG")
    buf.seek(0)
    return buf


# ── Guard helpers ──────────────────────────────────────────────────────────

def _acc_is_owner(user_id: int) -> bool:
    from config import OWNER_ID
    return user_id == OWNER_ID


def _acc_is_owner_or_admin(user_id: int) -> bool:
    from utils.database import is_admin
    return _acc_is_owner(user_id) or is_admin(user_id)


# ── /addaccessory ──────────────────────────────────────────────────────────

async def addaccessory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Owner/admin only.
    /addaccessory <slot> <name> <rarity> <file_id>
    Slot: hat | weapon | cape | mask | badge
    """
    user_id = update.effective_user.id
    if not _acc_is_owner_or_admin(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    args = context.args or []
    if len(args) < 4:
        await update.message.reply_text(
            "Usage: `/addaccessory <slot> <name> <rarity> <file_id>`\n\n"
            f"Slots: {', '.join(f'`{s}`' for s in ACC_SLOTS)}\n"
            "Rarity: `common` | `rare` | `legendary`\n\n"
            "Example:\n`/addaccessory hat SamuraiHelmet rare AgACAgIA...`",
            parse_mode="Markdown"
        )
        return

    slot    = args[0].lower()
    file_id = args[-1].strip()
    rarity  = args[-2].strip().lower()
    name    = " ".join(args[1:-2]).replace("_", " ").strip()

    if slot not in ACC_SLOTS:
        await update.message.reply_text(
            f"❌ Invalid slot `{slot}`.\nValid slots: {', '.join(ACC_SLOTS)}",
            parse_mode="Markdown"
        )
        return

    if rarity not in ACC_RARITIES:
        await update.message.reply_text(
            f"❌ Invalid rarity `{rarity}`.\nMust be: `common`, `rare`, or `legendary`",
            parse_mode="Markdown"
        )
        return

    if not name:
        await update.message.reply_text("❌ Please provide a name for the accessory.")
        return

    result = col(ACC_COL).insert_one({
        "slot":    slot,
        "name":    name,
        "rarity":  rarity,
        "file_id": file_id,
    })
    acc_id = str(result.inserted_id)
    r = ACC_RARITIES[rarity]

    await update.message.reply_text(
        f"✅ *Accessory Added!*\n\n"
        f"Slot: `{slot}`\n"
        f"Name: *{name}*\n"
        f"Rarity: {r['emoji']} {r['label']}\n"
        f"Price: {r['price']:,} ¥\n"
        f"ID: `{acc_id}`",
        parse_mode="Markdown"
    )


# ── /removeaccessory ───────────────────────────────────────────────────────

async def removeaccessory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner/admin only. /removeaccessory <acc_id>"""
    user_id = update.effective_user.id
    if not _acc_is_owner_or_admin(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/removeaccessory <acc_id>`",
            parse_mode="Markdown"
        )
        return

    acc_id = context.args[0].strip()
    try:
        res = col(ACC_COL).delete_one({"_id": ObjectId(acc_id)})
        if res.deleted_count:
            await update.message.reply_text(f"✅ Accessory `{acc_id}` removed.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ No accessory found with ID `{acc_id}`.", parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ Invalid ID format.")


# ── /listaccessories ───────────────────────────────────────────────────────

async def listaccessories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner/admin only."""
    user_id = update.effective_user.id
    if not _acc_is_owner_or_admin(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    accs = _all_accessories()
    if not accs:
        await update.message.reply_text("No accessories in the database yet.\n\nAdd with /addaccessory.")
        return

    lines = [f"🎒 *Accessories* ({len(accs)} total)\n"]
    for a in accs:
        r    = ACC_RARITIES.get(a.get("rarity", "common"), ACC_RARITIES["common"])
        aid  = str(a["_id"])
        name = a.get("name", "?")
        slot = a.get("slot", "?")
        lines.append(f"{r['emoji']} *{name}* [{slot}] — {r['label']}\n  `{aid}`")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /giveaccessory ─────────────────────────────────────────────────────────

async def giveaccessory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner/admin only. /giveaccessory <user_id> <acc_id>"""
    user_id = update.effective_user.id
    if not _acc_is_owner_or_admin(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "Usage: `/giveaccessory <user_id> <acc_id>`",
            parse_mode="Markdown"
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    acc_id = context.args[1].strip()
    acc    = _get_accessory(acc_id)
    if not acc:
        await update.message.reply_text(f"❌ Accessory `{acc_id}` not found.", parse_mode="Markdown")
        return

    target = get_player(target_id)
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    _give_acc_to_player(target_id, acc_id)
    await update.message.reply_text(
        f"✅ Gave *{acc['name']}* accessory to *{target['name']}*!",
        parse_mode="Markdown"
    )
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"🎁 You received the *{acc['name']}* accessory!\nUse /customise to equip it.",
            parse_mode="Markdown"
        )
    except Exception:
        pass


# ── /customise — player UI ─────────────────────────────────────────────────

async def customise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/customise — browse accessories by slot"""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🎩 Hat",    callback_data="cust_slot|hat"),
         InlineKeyboardButton(f"⚔️ Weapon", callback_data="cust_slot|weapon")],
        [InlineKeyboardButton(f"🧣 Cape",   callback_data="cust_slot|cape"),
         InlineKeyboardButton(f"😷 Mask",   callback_data="cust_slot|mask")],
        [InlineKeyboardButton(f"🏅 Badge",  callback_data="cust_slot|badge")],
        [InlineKeyboardButton("🔙 Close",   callback_data="cust_close")],
    ])

    equipped = player.get("equipped_accessories", {}) or {}
    lines    = ["🎒 *Character Customisation*\n\nChoose a slot to browse accessories:\n"]
    for s in ACC_SLOTS:
        eid  = equipped.get(s)
        if eid:
            acc = _get_accessory(str(eid))
            lines.append(f"• `{s.capitalize()}`: ✅ *{acc['name'] if acc else 'Unknown'}*")
        else:
            lines.append(f"• `{s.capitalize()}`: _(none)_")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


async def _show_acc_slot_page(update, context, slot: str, index: int, edit: bool):
    """Show one accessory page within a slot."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        return

    accs = _all_accessories(slot)
    if not accs:
        txt = f"No accessories available for slot *{slot.capitalize()}* yet."
        if update.callback_query:
            await update.callback_query.message.reply_text(txt, parse_mode="Markdown")
        else:
            await update.message.reply_text(txt, parse_mode="Markdown")
        return

    index = max(0, min(index, len(accs) - 1))
    acc   = accs[index]
    aid   = str(acc["_id"])
    name  = acc.get("name", "?")
    rarity = acc.get("rarity", "common")
    r     = ACC_RARITIES.get(rarity, ACC_RARITIES["common"])
    price = r["price"]
    total = len(accs)

    owned    = _player_owns_acc(user_id, aid)
    equipped = (player.get("equipped_accessories", {}) or {}).get(slot) == aid

    # Build keyboard
    rows = []
    nav  = []
    if index > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"cust_page|{slot}|{index-1}"))
    if index < total - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"cust_page|{slot}|{index+1}"))
    if nav:
        rows.append(nav)

    if equipped:
        rows.append([InlineKeyboardButton("✅ Equipped", callback_data="cust_noop")])
        rows.append([InlineKeyboardButton("🗑 Unequip", callback_data=f"cust_unequip|{slot}")])
    elif owned:
        rows.append([InlineKeyboardButton("👘 Equip", callback_data=f"cust_equip|{slot}|{aid}")])
    else:
        rows.append([InlineKeyboardButton(f"🛒 Buy — {price:,} ¥", callback_data=f"cust_buy|{slot}|{aid}")])

    rows.append([InlineKeyboardButton("🔙 Back to Slots", callback_data="cust_back")])
    rows.append([InlineKeyboardButton("❌ Close",          callback_data="cust_close")])
    keyboard = InlineKeyboardMarkup(rows)

    status = "✅ Equipped" if equipped else ("✔ Owned" if owned else f"💰 {price:,} ¥")
    caption = (
        f"🎒 *{slot.capitalize()} Accessories*\n\n"
        f"Name: *{name}*\n"
        f"{r['emoji']} Rarity: *{r['label']}*\n"
        f"Status: {status}\n\n"
        f"({index+1} / {total})"
    )

    try:
        file_id = acc.get("file_id")
        if edit and update.callback_query:
            try:
                await update.callback_query.message.delete()
            except Exception:
                pass
            await context.bot.send_photo(
                chat_id=update.callback_query.message.chat_id,
                photo=file_id, caption=caption,
                parse_mode="Markdown", reply_markup=keyboard
            )
        else:
            msg = update.message or (update.callback_query.message if update.callback_query else None)
            await msg.reply_photo(
                photo=file_id, caption=caption,
                parse_mode="Markdown", reply_markup=keyboard
            )
    except Exception as e:
        log.error("[CUSTOMISE] Could not send acc page: %s", e)


# ── Accessory callbacks ─────────────────────────────────────────────────────

async def cust_slot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User tapped a slot button."""
    query = update.callback_query
    await query.answer()
    try:
        slot = query.data.split("|")[1]
    except IndexError:
        return
    await _show_acc_slot_page(update, context, slot, index=0, edit=True)


async def cust_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Prev / Next within a slot."""
    query = update.callback_query
    await query.answer()
    try:
        _, slot, idx = query.data.split("|")
        index = int(idx)
    except (ValueError, IndexError):
        return
    await _show_acc_slot_page(update, context, slot, index=index, edit=True)


async def cust_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buy an accessory."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        _, slot, acc_id = query.data.split("|")
    except (ValueError, IndexError):
        return

    acc = _get_accessory(acc_id)
    if not acc:
        await query.answer("❌ Accessory not found.", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await query.answer("❌ Player not found.", show_alert=True)
        return

    if _player_owns_acc(user_id, acc_id):
        await query.answer("You already own this!", show_alert=True)
        return

    rarity = acc.get("rarity", "common")
    price  = ACC_RARITIES.get(rarity, ACC_RARITIES["common"])["price"]

    if player.get("yen", 0) < price:
        needed = price - player.get("yen", 0)
        await query.answer(f"❌ Need {needed:,} ¥ more.", show_alert=True)
        return

    update_player(user_id, yen=player["yen"] - price)
    _give_acc_to_player(user_id, acc_id)

    player = get_player(user_id)
    await _show_acc_slot_page(update, context, slot, index=0, edit=True)
    await query.answer(f"✅ Bought {acc['name']} for {price:,} ¥!", show_alert=False)


async def cust_equip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Equip an owned accessory."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        _, slot, acc_id = query.data.split("|")
    except (ValueError, IndexError):
        return

    if not _player_owns_acc(user_id, acc_id):
        await query.answer("❌ You don't own this.", show_alert=True)
        return

    acc = _get_accessory(acc_id)
    # Merge into equipped_accessories dict
    player   = get_player(user_id)
    equipped = dict(player.get("equipped_accessories", {}) or {})
    equipped[slot] = acc_id
    update_player(user_id, equipped_accessories=equipped)

    player = get_player(user_id)
    await _show_acc_slot_page(update, context, slot, index=0, edit=True)
    await query.answer(f"✅ {acc['name'] if acc else 'Accessory'} equipped!", show_alert=False)


async def cust_unequip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unequip a slot."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        slot = query.data.split("|")[1]
    except IndexError:
        return

    player   = get_player(user_id)
    equipped = dict(player.get("equipped_accessories", {}) or {})
    equipped.pop(slot, None)
    update_player(user_id, equipped_accessories=equipped)

    await _show_acc_slot_page(update, context, slot, index=0, edit=True)
    await query.answer(f"✅ {slot.capitalize()} slot cleared.", show_alert=False)


async def cust_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Go back to slot selection."""
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass
    # Re-send the slot picker via a fake update
    user_id = query.from_user.id
    player  = get_player(user_id)
    if not player:
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎩 Hat",    callback_data="cust_slot|hat"),
         InlineKeyboardButton("⚔️ Weapon", callback_data="cust_slot|weapon")],
        [InlineKeyboardButton("🧣 Cape",   callback_data="cust_slot|cape"),
         InlineKeyboardButton("😷 Mask",   callback_data="cust_slot|mask")],
        [InlineKeyboardButton("🏅 Badge",  callback_data="cust_slot|badge")],
        [InlineKeyboardButton("🔙 Close",  callback_data="cust_close")],
    ])

    equipped = player.get("equipped_accessories", {}) or {}
    lines    = ["🎒 *Character Customisation*\n\nChoose a slot:\n"]
    for s in ACC_SLOTS:
        eid = equipped.get(s)
        if eid:
            acc = _get_accessory(str(eid))
            lines.append(f"• `{s.capitalize()}`: ✅ *{acc['name'] if acc else 'Unknown'}*")
        else:
            lines.append(f"• `{s.capitalize()}`: _(none)_")

    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="\n".join(lines),
        parse_mode="Markdown",
        reply_markup=keyboard
    )


async def cust_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close customise menu."""
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass


async def cust_noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer("Already equipped!", show_alert=False)


async def cust_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Preview character with all accessories."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    player  = get_player(user_id)
    if not player:
        return
    buf = await _build_character_image(context.bot, player)
    if buf:
        await context.bot.send_photo(
            chat_id=query.message.chat_id,
            photo=buf,
            caption="🧑 *Your Character*",
            parse_mode="Markdown"
        )
    else:
        await query.answer("❌ Could not generate preview (no skin equipped or PIL missing).", show_alert=True)


# ── /mycharacter ───────────────────────────────────────────────────────────

async def mycharacter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mycharacter — show character card with accessories"""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start.")
        return

    buf = await _build_character_image(context.bot, player)

    equipped_skin_id = player.get("equipped_skin_id")
    skin_name = "None"
    if equipped_skin_id:
        s = _get_skin(equipped_skin_id)
        if s:
            skin_name = s.get("name", "Unknown")

    equipped_accs = player.get("equipped_accessories", {}) or {}
    acc_lines = []
    for slot in ACC_SLOTS:
        eid = equipped_accs.get(slot)
        if eid:
            a = _get_accessory(str(eid))
            acc_lines.append(f"  • {slot.capitalize()}: *{a['name'] if a else 'Unknown'}*")
        else:
            acc_lines.append(f"  • {slot.capitalize()}: _(none)_")

    caption = (
        f"🧑 *{player['name']}*\n\n"
        f"🎭 Skin: *{skin_name}*\n"
        f"🎒 Accessories:\n" + "\n".join(acc_lines)
    )

    if buf:
        await update.message.reply_photo(
            photo=buf, caption=caption, parse_mode="Markdown"
        )
    elif equipped_skin_id:
        skin = _get_skin(equipped_skin_id)
        if skin:
            fn = context.bot.send_animation if skin.get("is_gif") else context.bot.send_photo
            field = "animation" if skin.get("is_gif") else "photo"
            await fn(**{
                "chat_id": update.effective_chat.id,
                field:     skin["file_id"],
                "caption": caption,
                "parse_mode": "Markdown"
            })
            return
    else:
        await update.message.reply_text(caption, parse_mode="Markdown")
