"""
Character Skin Customisation — Accessory Layer System
─────────────────────────────────────────────────────────────
Accessory slots (all independent, all optional):
  weapon   — sword, blade, scythe …
  hat      — demon hat, hashira cap …
  cape     — cloak, haori pattern …
  mask     — demon mask, face guard …
  wings    — demon wings, angel wings …
  outfit   — full costume overlay …
  badge    — rank badge, title mark …
  aura     — glow / particle effect …

How it works:
  1. Player equips a base skin via /skins.
  2. Player uses /customise to open the accessory menu.
  3. Each slot shows owned accessories; player can equip one per slot.
  4. When /mycharacter (or profile) is called, all layers are downloaded
     from Telegram, composited with Pillow (RGBA alpha-over), and the
     result is sent as a single image.

Owner commands:
  /addaccessory <slot> <name> <rarity> <file_id>
      slot: weapon | hat | cape | mask | wings | outfit | badge | aura
      rarity: common | rare | legendary
  /removeaccessory <acc_id>
  /listaccessories [slot]
  /giveaccessory <user_id> <acc_id>

Player commands:
  /customise      — open accessory slot menu
  /mycharacter    — generate & send the composited character image
"""

import io
import logging
import asyncio
import aiohttp
from bson import ObjectId
from PIL import Image
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, col

log = logging.getLogger(__name__)

ACC_COL  = "accessories"
OWN_COL  = "player_accessories"

# ── Slot definitions ───────────────────────────────────────────────────────
SLOTS = {
    "weapon": {"emoji": "⚔️",  "label": "Weapon"},
    "hat":    {"emoji": "🎩",  "label": "Hat"},
    "cape":   {"emoji": "🧣",  "label": "Cape / Haori"},
    "mask":   {"emoji": "😷",  "label": "Mask"},
    "wings":  {"emoji": "🪽",  "label": "Wings"},
    "outfit": {"emoji": "👘",  "label": "Outfit"},
    "badge":  {"emoji": "🏅",  "label": "Badge"},
    "aura":   {"emoji": "✨",  "label": "Aura"},
}

SLOT_ORDER = ["outfit", "cape", "wings", "weapon", "hat", "mask", "badge", "aura"]

# ── Rarity prices ──────────────────────────────────────────────────────────
RARITIES = {
    "common":    {"label": "Common",    "emoji": "⚪", "price": 3_000},
    "rare":      {"label": "Rare",      "emoji": "🔵", "price": 12_000},
    "legendary": {"label": "Legendary", "emoji": "🟡", "price": 40_000},
}

# ── DB helpers ─────────────────────────────────────────────────────────────

def _all_accessories(slot: str | None = None) -> list:
    query = {"slot": slot} if slot else {}
    return list(col(ACC_COL).find(query))


def _get_acc(acc_id: str) -> dict | None:
    try:
        return col(ACC_COL).find_one({"_id": ObjectId(acc_id)})
    except Exception:
        return None


def _add_acc(slot: str, name: str, rarity: str, file_id: str) -> str:
    res = col(ACC_COL).insert_one({
        "slot": slot, "name": name,
        "rarity": rarity, "file_id": file_id,
    })
    return str(res.inserted_id)


def _remove_acc(acc_id: str) -> bool:
    try:
        return col(ACC_COL).delete_one({"_id": ObjectId(acc_id)}).deleted_count > 0
    except Exception:
        return False


def _owns_acc(user_id: int, acc_id: str) -> bool:
    return col(OWN_COL).find_one({"user_id": user_id, "acc_id": acc_id}) is not None


def _give_acc(user_id: int, acc_id: str):
    if not _owns_acc(user_id, acc_id):
        col(OWN_COL).insert_one({"user_id": user_id, "acc_id": acc_id})


def _owned_acc_ids(user_id: int) -> set:
    return {d["acc_id"] for d in col(OWN_COL).find({"user_id": user_id})}


def _get_equipped(player: dict) -> dict:
    """Return dict of slot -> acc_id currently equipped."""
    return player.get("equipped_accessories", {}) or {}


def _equip_acc(user_id: int, slot: str, acc_id: str | None):
    """Equip or unequip (acc_id=None) an accessory in a slot."""
    equipped = get_player(user_id).get("equipped_accessories", {}) or {}
    if acc_id is None:
        equipped.pop(slot, None)
    else:
        equipped[slot] = acc_id
    update_player(user_id, equipped_accessories=equipped)


# ── Owner guard ────────────────────────────────────────────────────────────

def _is_owner(user_id: int) -> bool:
    from config import OWNER_ID
    return user_id == OWNER_ID


def _is_owner_or_admin(user_id: int) -> bool:
    from utils.database import is_admin
    return _is_owner(user_id) or is_admin(user_id)


# ── Owner commands ─────────────────────────────────────────────────────────

async def addaccessory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addaccessory <slot> <name> <rarity> <file_id>
    slot: weapon | hat | cape | mask | wings | outfit | badge | aura
    """
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return

    args = context.args
    if not args or len(args) < 4:
        slots_str = " | ".join(SLOTS.keys())
        await update.message.reply_text(
            "Usage: `/addaccessory <slot> <name> <rarity> <file_id>`\n\n"
            f"Slots: `{slots_str}`\n"
            "Rarity: `common` | `rare` | `legendary`\n\n"
            "Example:\n"
            "`/addaccessory cape Water_Haori rare AgACAgIA...`",
            parse_mode="Markdown"
        )
        return

    file_id = args[-1].strip()
    rarity  = args[-2].strip().lower()
    slot    = args[0].strip().lower()
    name    = " ".join(args[1:-2]).replace("_", " ").strip()

    if slot not in SLOTS:
        await update.message.reply_text(
            f"❌ Invalid slot `{slot}`.\nValid: `{' | '.join(SLOTS.keys())}`",
            parse_mode="Markdown"
        )
        return

    if rarity not in RARITIES:
        await update.message.reply_text(
            f"❌ Invalid rarity `{rarity}`.\nMust be: `common` | `rare` | `legendary`",
            parse_mode="Markdown"
        )
        return

    if not name:
        await update.message.reply_text("Please provide a name.")
        return

    acc_id = _add_acc(slot, name, rarity, file_id)
    r = RARITIES[rarity]
    s = SLOTS[slot]
    log.info("[ACC] Added %s '%s' rarity=%s id=%s", slot, name, rarity, acc_id)

    caption = (
        f"✅ Accessory Added!\n\n"
        f"{s['emoji']} Slot: *{s['label']}*\n"
        f"Name: *{name}*\n"
        f"{r['emoji']} Rarity: *{r['label']}*\n"
        f"Price: *{r['price']:,} ¥*\n"
        f"ID: `{acc_id}`"
    )
    try:
        await context.bot.send_photo(chat_id=user_id, photo=file_id, caption=caption, parse_mode="Markdown")
    except Exception:
        await update.message.reply_text(caption + "\n\n_(Preview failed — check file\\_id)_", parse_mode="Markdown")


async def removeaccessory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner only. /removeaccessory <acc_id>"""
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: `/removeaccessory <acc_id>`", parse_mode="Markdown")
        return
    acc_id = context.args[0].strip()
    if _remove_acc(acc_id):
        await update.message.reply_text(f"✅ Accessory `{acc_id}` removed.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Not found: `{acc_id}`", parse_mode="Markdown")


async def listaccessories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner/admin only. /listaccessories [slot]"""
    user_id = update.effective_user.id
    if not _is_owner_or_admin(user_id):
        await update.message.reply_text("Admin only.")
        return
    slot = context.args[0].lower() if context.args else None
    accs = _all_accessories(slot)
    if not accs:
        await update.message.reply_text("No accessories found.")
        return
    lines = [f"🎒 Accessories ({len(accs)})\n"]
    for a in accs:
        s = SLOTS.get(a.get("slot", ""), {"emoji": "❓", "label": "?"})
        r = RARITIES.get(a.get("rarity", "common"), RARITIES["common"])
        lines.append(
            f"{s['emoji']} *{a['name']}* — {r['emoji']} {r['label']}\n"
            f"  Slot: `{a.get('slot')}` | ID: `{str(a['_id'])}`"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def giveaccessory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner only. /giveaccessory <user_id> <acc_id>"""
    user_id = update.effective_user.id
    if not _is_owner(user_id):
        await update.message.reply_text("Owner only.")
        return
    if not context.args or len(context.args) < 2:
        await update.message.reply_text("Usage: `/giveaccessory <user_id> <acc_id>`", parse_mode="Markdown")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return
    acc_id = context.args[1].strip()
    acc    = _get_acc(acc_id)
    if not acc:
        await update.message.reply_text(f"❌ Accessory `{acc_id}` not found.", parse_mode="Markdown")
        return
    target = get_player(target_id)
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return
    _give_acc(target_id, acc_id)
    await update.message.reply_text(
        f"✅ Gave *{acc['name']}* to *{target['name']}*!", parse_mode="Markdown"
    )
    try:
        s = SLOTS.get(acc.get("slot", ""), {"emoji": "🎒", "label": acc.get("slot", "")})
        await context.bot.send_message(
            chat_id=target_id,
            text=f"🎁 You received *{acc['name']}* ({s['emoji']} {s['label']}) accessory!\nUse /customise to equip it.",
            parse_mode="Markdown"
        )
    except Exception:
        pass


# ── /customise — slot menu ─────────────────────────────────────────────────

def _customise_keyboard(player: dict, owned_ids: set) -> InlineKeyboardMarkup:
    equipped = _get_equipped(player)
    rows = []
    for slot in SLOT_ORDER:
        s        = SLOTS[slot]
        eq_id    = equipped.get(slot)
        eq_acc   = _get_acc(eq_id) if eq_id else None
        eq_label = f" → {eq_acc['name']}" if eq_acc else " → None"
        rows.append([InlineKeyboardButton(
            f"{s['emoji']} {s['label']}{eq_label}",
            callback_data=f"cust_slot|{slot}|0"
        )])
    rows.append([InlineKeyboardButton("🖼 Preview Character", callback_data="cust_preview")])
    rows.append([InlineKeyboardButton("🔙 Close", callback_data="cust_close")])
    return InlineKeyboardMarkup(rows)


async def customise(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/customise — open the accessory customisation menu."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start first.")
        return

    owned_ids = _owned_acc_ids(user_id)
    keyboard  = _customise_keyboard(player, owned_ids)

    skin_id  = player.get("equipped_skin_id")
    skin_doc = None
    if skin_id:
        from bson import ObjectId as _OID
        try:
            skin_doc = col("character_skins").find_one({"_id": _OID(skin_id)})
        except Exception:
            pass

    skin_name = skin_doc["name"] if skin_doc else "None"
    equipped  = _get_equipped(player)
    eq_count  = len([v for v in equipped.values() if v])

    text = (
        f"🎨 *Character Customisation*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👘 Base Skin: *{skin_name}*\n"
        f"🎒 Accessories Equipped: *{eq_count}/{len(SLOTS)}*\n\n"
        f"Tap a slot to browse & equip accessories.\n"
        f"Tap *Preview Character* to generate your full look!"
    )

    if update.message:
        await update.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        try:
            await update.callback_query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            await update.callback_query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


# ── Slot browser ───────────────────────────────────────────────────────────

def _slot_keyboard(slot: str, accs: list, index: int, user_id: int, owned_ids: set, equipped_id: str | None) -> InlineKeyboardMarkup:
    rows = []
    total = len(accs)

    if total == 0:
        rows.append([InlineKeyboardButton("No accessories in this slot yet", callback_data="cust_noop")])
    else:
        acc    = accs[index]
        acc_id = str(acc["_id"])
        owned  = acc_id in owned_ids
        is_eq  = acc_id == equipped_id
        r      = RARITIES.get(acc.get("rarity", "common"), RARITIES["common"])

        # Nav
        nav = []
        if index > 0:
            nav.append(InlineKeyboardButton("◀", callback_data=f"cust_slot|{slot}|{index-1}"))
        nav.append(InlineKeyboardButton(f"{index+1}/{total}", callback_data="cust_noop"))
        if index < total - 1:
            nav.append(InlineKeyboardButton("▶", callback_data=f"cust_slot|{slot}|{index+1}"))
        rows.append(nav)

        # Action
        if is_eq:
            rows.append([InlineKeyboardButton("✅ Equipped", callback_data="cust_noop")])
            rows.append([InlineKeyboardButton("🗑 Unequip", callback_data=f"cust_unequip|{slot}")])
        elif owned:
            rows.append([InlineKeyboardButton("👘 Equip", callback_data=f"cust_equip|{slot}|{acc_id}")])
        else:
            rows.append([InlineKeyboardButton(
                f"🛒 Buy {r['price']:,} ¥", callback_data=f"cust_buy|{acc_id}"
            )])

    rows.append([InlineKeyboardButton("🔙 Back to Slots", callback_data="cust_back")])
    return InlineKeyboardMarkup(rows)


async def cust_slot_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Browse accessories in a slot."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    try:
        _, slot, idx_str = query.data.split("|")
        index = int(idx_str)
    except (ValueError, IndexError):
        return

    player    = get_player(user_id)
    owned_ids = _owned_acc_ids(user_id)
    equipped  = _get_equipped(player)
    eq_id     = equipped.get(slot)
    accs      = _all_accessories(slot)
    s         = SLOTS.get(slot, {"emoji": "🎒", "label": slot})
    r_info    = ""

    if accs:
        index  = max(0, min(index, len(accs) - 1))
        acc    = accs[index]
        acc_id = str(acc["_id"])
        r      = RARITIES.get(acc.get("rarity", "common"), RARITIES["common"])
        owned  = acc_id in owned_ids
        is_eq  = acc_id == eq_id
        status = "✅ Equipped" if is_eq else ("✔ Owned" if owned else f"💰 {r['price']:,} ¥")
        r_info = (
            f"\n\n*{acc['name']}*\n"
            f"{r['emoji']} {r['label']} | {status}"
        )

    keyboard = _slot_keyboard(slot, accs, index, user_id, owned_ids, eq_id)
    text = (
        f"{s['emoji']} *{s['label']} Accessories*"
        f"{r_info}\n\n"
        f"_Browse and equip accessories for this slot._"
    )

    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=keyboard)
    except Exception:
        await query.message.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)


async def cust_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Buy an accessory with Yen."""
    query   = update.callback_query
    user_id = query.from_user.id

    try:
        acc_id = query.data.split("|")[1]
    except IndexError:
        await query.answer("Invalid.", show_alert=True)
        return

    acc = _get_acc(acc_id)
    if not acc:
        await query.answer("❌ Accessory no longer available.", show_alert=True)
        return

    if _owns_acc(user_id, acc_id):
        await query.answer("You already own this!", show_alert=True)
        return

    player = get_player(user_id)
    r      = RARITIES.get(acc.get("rarity", "common"), RARITIES["common"])
    price  = r["price"]

    if player.get("yen", 0) < price:
        needed = price - player.get("yen", 0)
        await query.answer(f"❌ Need {needed:,} ¥ more!", show_alert=True)
        return

    update_player(user_id, yen=player["yen"] - price)
    _give_acc(user_id, acc_id)
    log.info("[ACC] User %s bought acc '%s' for %s yen", user_id, acc.get("name"), price)
    await query.answer(f"✅ Bought {acc['name']} for {price:,} ¥!", show_alert=False)

    # Re-open the slot browser at this item
    slot  = acc.get("slot", "weapon")
    accs  = _all_accessories(slot)
    index = next((i for i, a in enumerate(accs) if str(a["_id"]) == acc_id), 0)
    # Simulate slot callback
    query.data = f"cust_slot|{slot}|{index}"
    await cust_slot_callback(update, context)


async def cust_equip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Equip an owned accessory."""
    query   = update.callback_query
    user_id = query.from_user.id

    try:
        _, slot, acc_id = query.data.split("|")
    except (ValueError, IndexError):
        await query.answer("Invalid.", show_alert=True)
        return

    if not _owns_acc(user_id, acc_id):
        await query.answer("❌ You don't own this.", show_alert=True)
        return

    acc = _get_acc(acc_id)
    _equip_acc(user_id, slot, acc_id)
    await query.answer(f"✅ {acc['name']} equipped!", show_alert=False)

    accs  = _all_accessories(slot)
    index = next((i for i, a in enumerate(accs) if str(a["_id"]) == acc_id), 0)
    query.data = f"cust_slot|{slot}|{index}"
    await cust_slot_callback(update, context)


async def cust_unequip_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unequip accessory from a slot."""
    query   = update.callback_query
    user_id = query.from_user.id

    try:
        slot = query.data.split("|")[1]
    except IndexError:
        await query.answer("Invalid.", show_alert=True)
        return

    _equip_acc(user_id, slot, None)
    await query.answer(f"✅ {SLOTS.get(slot, {}).get('label', slot)} unequipped.", show_alert=False)

    query.data = f"cust_slot|{slot}|0"
    await cust_slot_callback(update, context)


async def cust_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Back to main slot menu."""
    query = update.callback_query
    await query.answer()
    await customise(update, context)


async def cust_close_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Close customisation menu."""
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass


async def cust_noop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


# ── Image compositing ──────────────────────────────────────────────────────

async def _download_tg_image(bot, file_id: str) -> Image.Image | None:
    """Download a Telegram photo file_id and return a PIL Image (RGBA)."""
    try:
        tg_file = await bot.get_file(file_id)
        url     = tg_file.file_path
        # file_path is already a full URL in newer python-telegram-bot
        if not url.startswith("http"):
            url = f"https://api.telegram.org/file/bot{bot.token}/{url}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    return None
                data = await resp.read()

        img = Image.open(io.BytesIO(data)).convert("RGBA")
        return img
    except Exception as e:
        log.error("[COMPOSITE] Download failed for file_id=%s: %s", file_id, e)
        return None


def _composite_layers(layers: list[Image.Image]) -> Image.Image:
    """
    Alpha-composite a list of RGBA images.
    All are resized to match the first (base) image size.
    """
    if not layers:
        return Image.new("RGBA", (512, 512), (30, 30, 40, 255))

    base_size = layers[0].size
    result    = layers[0].copy()

    for layer in layers[1:]:
        if layer.size != base_size:
            layer = layer.resize(base_size, Image.LANCZOS)
        result = Image.alpha_composite(result, layer)

    return result


async def _build_character_image(bot, player: dict) -> io.BytesIO | None:
    """
    Download base skin + all equipped accessory layers,
    composite them, and return a BytesIO PNG.
    Returns None if no base skin is set.
    """
    skin_id  = player.get("equipped_skin_id")
    equipped = _get_equipped(player)

    # Load base skin
    base_img = None
    if skin_id:
        try:
            skin_doc = col("character_skins").find_one({"_id": ObjectId(skin_id)})
        except Exception:
            skin_doc = None

        if skin_doc and not skin_doc.get("is_gif"):
            base_img = await _download_tg_image(bot, skin_doc["file_id"])

    if base_img is None:
        return None

    layers = [base_img]

    # Load accessory layers in defined order
    for slot in SLOT_ORDER:
        acc_id = equipped.get(slot)
        if not acc_id:
            continue
        acc = _get_acc(acc_id)
        if not acc:
            continue
        acc_img = await _download_tg_image(bot, acc["file_id"])
        if acc_img:
            layers.append(acc_img)

    composited = _composite_layers(layers)

    buf = io.BytesIO()
    composited.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


async def cust_preview_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generate and send the composited character image."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer("Generating your character…", show_alert=False)

    player = get_player(user_id)
    if not player:
        await query.answer("Player not found.", show_alert=True)
        return

    await mycharacter_send(context.bot, user_id, player, query.message.chat_id)


async def mycharacter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mycharacter — generate and send the composited character image."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start first.")
        return

    msg = await update.message.reply_text("🎨 Generating your character image…")
    await mycharacter_send(context.bot, user_id, player, update.effective_chat.id)
    try:
        await msg.delete()
    except Exception:
        pass


async def mycharacter_send(bot, user_id: int, player: dict, chat_id: int):
    """Build composite image and send it to chat_id."""
    equipped  = _get_equipped(player)
    skin_id   = player.get("equipped_skin_id")

    if not skin_id:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "❌ *No base skin equipped!*\n\n"
                "Use /skins to browse and equip a character skin first,\n"
                "then come back to /customise to add accessories."
            ),
            parse_mode="Markdown"
        )
        return

    buf = await _build_character_image(bot, player)
    if buf is None:
        await bot.send_message(
            chat_id=chat_id,
            text=(
                "❌ Could not generate character image.\n"
                "Make sure your base skin is a photo (not a GIF) and try again."
            )
        )
        return

    # Build caption
    skin_doc  = None
    try:
        skin_doc = col("character_skins").find_one({"_id": ObjectId(skin_id)})
    except Exception:
        pass

    skin_name = skin_doc["name"] if skin_doc else "Unknown"
    acc_lines = []
    for slot in SLOT_ORDER:
        acc_id = equipped.get(slot)
        s      = SLOTS[slot]
        if acc_id:
            acc = _get_acc(acc_id)
            acc_lines.append(f"{s['emoji']} {s['label']}: *{acc['name'] if acc else '?'}*")
        else:
            acc_lines.append(f"{s['emoji']} {s['label']}: _None_")

    caption = (
        f"🎭 *{player.get('name', 'Character')}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👘 Base: *{skin_name}*\n\n"
        + "\n".join(acc_lines)
    )

    await bot.send_photo(
        chat_id=chat_id,
        photo=buf,
        caption=caption,
        parse_mode="Markdown"
    )
