from telegram import Update
from telegram.ext import ContextTypes

from handlers.admin import _find_player, has_admin_access
from handlers.logs import log_action
from utils.database import add_item, canonical_item_name, col, update_player

# ── Known material-type drops (cannot be used directly, only crafted/sold) ──
_MATERIAL_ITEMS = {
    "demon blood", "slayer badge", "wolf fang", "boss shard",
    "void dust", "null fragment", "abyss stone", "shade cloth",
    "void core", "void shard", "muzan blood", "demon king core",
    "upper moon core", "kizuki blood", "rui thread", "akaza fist",
    "kokushibo shard", "demonic catalyst", "ancient whetstone",
    "rare ore fragment", "blood crystal", "sun blade fragment",
    "breath of the sun scroll",
}

_SCROLL_ITEMS = {
    "sun breathing tome", "moon breathing scroll",
    "breath of the sun scroll",
}

def _resolve_item_type(item_name: str) -> str:
    """Determine correct item_type from item name so inventory is tagged right."""
    lower = item_name.lower()
    if lower in _SCROLL_ITEMS or "scroll" in lower or "tome" in lower:
        return "scroll"
    if lower in _MATERIAL_ITEMS or "shard" in lower or "fragment" in lower \
            or "core" in lower or "fang" in lower or "blood" in lower \
            or "stone" in lower or "cloth" in lower or "dust" in lower \
            or "ore" in lower:
        return "material"
    return "item"


def _resolve_add_target(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.reply_to_message:
        return col("players").find_one({"user_id": update.message.reply_to_message.from_user.id}), list(context.args or [])
    if context.args:
        return _find_player(context.args[0]), list(context.args[1:])
    return None, []


async def add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not has_admin_access(update.effective_user.id):
        return

    target, args = _resolve_add_target(update, context)
    if not target or len(args) < 2:
        await update.message.reply_text(
            "Usage:\n"
            "`/add @username yen 500`\n"
            "`/add @username exp 1000`\n"
            "`/add @username items Boss Shard 2`\n"
            "`/add @username sp 5`\n"
            "or reply to a user with:\n"
            "`/add yen 500`\n"
            "`/add exp 1000`\n"
            "`/add items Boss Shard 2`\n"
            "`/add sp 5`",
            parse_mode="Markdown",
        )
        return

    mode = args[0].lower()

    # ── YEN ──────────────────────────────────────────────────────────────
    if mode == "yen":
        try:
            amount = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid Yen amount.")
            return
        update_player(target["user_id"], yen=target.get("yen", 0) + amount)
        log_action(update.effective_user.id, "giveyen", target["user_id"], target["name"], f"{amount:,} Yen")
        await update.message.reply_text(f"✅ Added *{amount:,} Yen* to *{target['name']}*.", parse_mode="Markdown")
        return

    # ── EXP ──────────────────────────────────────────────────────────────
    if mode in {"exp", "xp"}:
        try:
            amount = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid EXP amount.")
            return
        update_player(target["user_id"], xp=target.get("xp", 0) + amount)
        log_action(update.effective_user.id, "givexp", target["user_id"], target["name"], f"+{amount:,} XP")
        await update.message.reply_text(f"✅ Added *{amount:,} XP* to *{target['name']}*.", parse_mode="Markdown")
        return

    # ── SKILL POINTS (shorthand: /add sp 5) ──────────────────────────────
    if mode in {"sp", "skillpoints", "skill_points"}:
        try:
            amount = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid SP amount.")
            return
        current_sp = int(target.get("skill_points", 0) or 0)
        update_player(target["user_id"], skill_points=current_sp + amount)
        log_action(update.effective_user.id, "givesp", target["user_id"], target["name"], f"{amount} SP")
        await update.message.reply_text(f"✅ Added *{amount} SP* to *{target['name']}*.", parse_mode="Markdown")
        return

    # ── ITEMS ─────────────────────────────────────────────────────────────
    if mode in {"item", "items"}:
        if len(args) < 3:
            await update.message.reply_text(
                "❌ Usage: `/add @user items <item name> <amount>`", parse_mode="Markdown"
            )
            return

        # Last arg must be the quantity
        try:
            amount = int(args[-1])
            if amount <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ Item amount must be a positive number.", parse_mode="Markdown")
            return

        raw_name = " ".join(args[1:-1]).strip()
        if not raw_name:
            await update.message.reply_text("❌ Item name is required.", parse_mode="Markdown")
            return

        # Skill Points via items mode  (/add @user items skill points 5)
        if raw_name.lower() in {"skill points", "skill point", "skill pts", "skill pt"}:
            current_sp = int(target.get("skill_points", 0) or 0)
            update_player(target["user_id"], skill_points=current_sp + amount)
            log_action(update.effective_user.id, "givesp", target["user_id"], target["name"], f"{amount} SP")
            await update.message.reply_text(
                f"✅ Added *{amount} SP* to *{target['name']}*.", parse_mode="Markdown"
            )
            return

        item_name = canonical_item_name(raw_name)
        if not item_name:
            await update.message.reply_text("❌ Could not resolve item name.", parse_mode="Markdown")
            return

        item_type = _resolve_item_type(item_name)
        add_item(target["user_id"], item_name, item_type, amount)
        log_action(update.effective_user.id, "giveitem", target["user_id"], target["name"], f"{item_name} x{amount} [{item_type}]")
        await update.message.reply_text(
            f"✅ Added *{item_name} x{amount}* (`{item_type}`) to *{target['name']}*.",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "❌ Unknown type. Use `yen`, `exp`, `sp`, or `items`.", parse_mode="Markdown"
    )
