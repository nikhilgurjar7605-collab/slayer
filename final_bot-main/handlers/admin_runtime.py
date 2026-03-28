from telegram import Update
from telegram.ext import ContextTypes

from handlers.admin import _find_player, has_admin_access
from handlers.logs import log_action
from utils.database import add_item, col


def _resolve_item_name_and_type(item_name: str):
    from config import DEMON_ENEMIES, REGION_ENEMIES, SHOP_ITEMS, SLAYER_ENEMIES

    raw_name = str(item_name or "").strip()
    query = raw_name.lower()
    if not query:
        return raw_name, "item"

    catalog = {}

    for cat, items in SHOP_ITEMS.items():
        item_type = "sword" if cat == "swords" else ("armor" if cat == "armor" else "item")
        for item in items:
            catalog[item["name"].lower()] = (item["name"], item_type)

    for region in REGION_ENEMIES.values():
        for enemy in region.get("enemies", []):
            for drop in enemy.get("drops", []):
                catalog.setdefault(drop.lower(), (drop, "material"))

    for enemy in SLAYER_ENEMIES + DEMON_ENEMIES:
        for drop in enemy.get("drops", []):
            catalog.setdefault(drop.lower(), (drop, "material"))

    if query in catalog:
        return catalog[query]

    if query.startswith("scroll:"):
        return raw_name, "scroll"

    for key, value in catalog.items():
        if query in key:
            return value

    return raw_name, "item"


def _next_custom_mission_id() -> int:
    existing_ids = [
        doc.get("id", 999)
        for doc in col("custom_missions").find({}, {"id": 1, "_id": 0})
    ]
    numeric_ids = [mid for mid in existing_ids if isinstance(mid, int)]
    return max(numeric_ids + [999]) + 1


def _difficulty_emoji(difficulty: str) -> str:
    label = str(difficulty or "").upper()
    if "EASY" in label:
        return "🟢"
    if "MEDIUM" in label:
        return "🟡"
    if "HARD" in label:
        return "🔴"
    if "EXTREME" in label:
        return "💀"
    return "📜"


async def giveitem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_admin_access(update.effective_user.id):
        return

    if len(context.args or []) < 2:
        await update.message.reply_text(
            "Usage: `/giveitem @user [item name]`\n"
            "Or: `/giveitem @user [item name] [qty]`",
            parse_mode="Markdown",
        )
        return

    target = _find_player(context.args[0])
    if not target:
        await update.message.reply_text("Player not found.", parse_mode="Markdown")
        return

    item_args = list(context.args[1:])
    quantity = 1
    if len(item_args) >= 2:
        try:
            quantity = int(item_args[-1])
            item_args = item_args[:-1]
        except ValueError:
            quantity = 1

    item_name = " ".join(item_args).strip()
    if not item_name:
        await update.message.reply_text("Item name is required.", parse_mode="Markdown")
        return

    quantity = max(1, min(quantity, 9999))
    real_name, item_type = _resolve_item_name_and_type(item_name)
    add_item(target["user_id"], real_name, item_type, quantity)

    detail = f"{real_name} x{quantity}" if quantity > 1 else real_name
    log_action(update.effective_user.id, "giveitem", target["user_id"], target["name"], detail)

    qty_text = f" x {quantity}" if quantity > 1 else ""
    await update.message.reply_text(
        f"Gave *{real_name}*{qty_text} to *{target['name']}*.\n"
        f"Type: `{item_type}`",
        parse_mode="Markdown",
    )


async def addmission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_admin_access(update.effective_user.id):
        return

    if len(context.args or []) < 4:
        await update.message.reply_text(
            "Usage: `/addmission [difficulty] [xp] [yen] [name]`",
            parse_mode="Markdown",
        )
        return

    try:
        difficulty = context.args[0]
        xp = int(context.args[1])
        yen = int(context.args[2])
    except ValueError:
        await update.message.reply_text("Invalid format.", parse_mode="Markdown")
        return

    name = " ".join(context.args[3:]).strip()
    if not name:
        await update.message.reply_text("Mission name is required.", parse_mode="Markdown")
        return

    mission_id = _next_custom_mission_id()
    col("custom_missions").insert_one(
        {
            "id": mission_id,
            "difficulty": difficulty,
            "name": name,
            "emoji": _difficulty_emoji(difficulty),
            "xp": xp,
            "yen": yen,
            "desc": name,
            "description": name,
            "kills_required": 5,
            "party_required": False,
            "added_by": update.effective_user.id,
            "active": 1,
        }
    )

    await update.message.reply_text(
        f"Mission added: *{name}*\n"
        f"ID: `{mission_id}`\n"
        "It is now available in `/mission`.",
        parse_mode="Markdown",
    )


async def removemission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_admin_access(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/removemission [mission name or #id]`",
            parse_mode="Markdown",
        )
        return

    raw_query = " ".join(context.args).strip()
    lookup = raw_query.lstrip("#")
    if lookup.isdigit():
        query = {"id": int(lookup)}
    else:
        query = {"name": {"$regex": raw_query, "$options": "i"}}

    result = col("custom_missions").update_one(query, {"$set": {"active": 0}})
    if not result.matched_count:
        await update.message.reply_text("Custom mission not found.", parse_mode="Markdown")
        return

    await update.message.reply_text(
        f"Mission removed: *{raw_query}*",
        parse_mode="Markdown",
    )


async def listmissions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_admin_access(update.effective_user.id):
        return

    missions = list(col("custom_missions").find({"active": 1}, {"_id": 0}).sort("id", 1))
    if not missions:
        await update.message.reply_text("No active custom missions.", parse_mode="Markdown")
        return

    lines = ["*CUSTOM MISSIONS*", ""]
    for mission in missions:
        mission_id = mission.get("id", "?")
        lines.append(
            f"`#{mission_id}` *{mission['name']}* - {mission['xp']} XP / {mission['yen']} Yen [{mission['difficulty']}]"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
