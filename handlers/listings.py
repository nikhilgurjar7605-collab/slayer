import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler
import config
from utils.guards import owner_only

def _build_inline_keyboard(items, prefix, cols=2):
    """Helper to build an inline keyboard.
    items: list of (label, value) tuples.
    prefix: callback data prefix.
    Spaces in values are replaced with '-' to avoid Telegram callback_data issues.
    """
    buttons = []
    row = []
    for label, value in items:
        safe_value = str(value).replace(" ", "-")
        row.append(InlineKeyboardButton(label, callback_data=f"{prefix}_{safe_value}"))
        if len(row) == cols:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons)

# ----- Breathing Styles -----
async def list_styles(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only command that displays all breathing styles as buttons."""
    items = [(style["name"], style["name"]) for style in config.BREATHING_STYLES]
    if not items:
        await update.effective_chat.send_message("No breathing styles defined.")
        return
    keyboard = _build_inline_keyboard(items, "ownstyle")
    await update.effective_chat.send_message(
        "*Breathing Styles* (tap to view forms):",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

async def style_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Decode: "ownstyle_Water-Breathing" → "Water Breathing"
    style_name = query.data.split("_", 1)[1].replace("-", " ")
    forms = config.TECHNIQUES.get(style_name, [])
    if not forms:
        text = f"*{style_name}* has no forms registered."
    else:
        lines = [f"*{style_name} – Forms:*"]
        for f in forms:
            lines.append(f"- Form {f.get('form')}: {f.get('name')} (STA {f.get('sta_cost')})")
        text = "\n".join(lines)
    await query.edit_message_text(text, parse_mode="Markdown")

# ----- Demon Arts -----
async def list_arts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only command that displays all demon arts as buttons."""
    items = [(art["name"], art["name"]) for art in config.DEMON_ARTS]
    if not items:
        await update.effective_chat.send_message("No demon arts defined.")
        return
    keyboard = _build_inline_keyboard(items, "ownart")
    await update.effective_chat.send_message(
        "*Demon Arts* (tap to view forms):",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

async def art_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Decode: "ownart_Love-Breathing" → "Love Breathing"
    art_name = query.data.split("_", 1)[1].replace("-", " ")
    forms = config.TECHNIQUES.get(art_name, [])
    if not forms:
        text = f"*{art_name}* has no forms registered."
    else:
        lines = [f"*{art_name} – Forms:*"]
        for f in forms:
            lines.append(f"- Form {f.get('form')}: {f.get('name')} (STA {f.get('sta_cost')})")
        text = "\n".join(lines)
    await query.edit_message_text(text, parse_mode="Markdown")

# ----- Enemies -----
async def list_enemies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner-only command that lists all enemies with buttons for details."""
    items = []
    # Region enemies
    for region, data in getattr(config, "REGION_ENEMIES", {}).items():
        # REGION_ENEMIES values may be a dict with an 'enemies' key
        enemy_list = data.get("enemies", data) if isinstance(data, dict) else data
        for enemy in enemy_list:
            label = f"{region}: {enemy.get('name', 'Unnamed')}"
            # Use pipe separator; spaces replaced with '-' per _build_inline_keyboard
            value = f"region|{region}|{enemy.get('name', '')}"
            items.append((label, value))
    # Slayer enemies
    for enemy in getattr(config, "SLAYER_ENEMIES", []):
        items.append((enemy.get('name', 'Unnamed'), f"slayer|{enemy.get('name', '')}"))
    # Demon enemies
    for enemy in getattr(config, "DEMON_ENEMIES", []):
        items.append((enemy.get('name', 'Unnamed'), f"demon|{enemy.get('name', '')}"))
    if not items:
        await update.effective_chat.send_message("No enemies defined.")
        return
    keyboard = _build_inline_keyboard(items, "ownenemy")
    await update.effective_chat.send_message(
        "*Enemies* (tap for details):",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )

async def enemy_info_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    # Decode: "ownenemy_region|asakusa|Swamp-Demon" → restore spaces in name
    raw = query.data.split("_", 1)[1]
    # Only the name portion (after last |) had spaces replaced with '-'
    parts = raw.split("|")
    if len(parts) >= 1:
        parts[-1] = parts[-1].replace("-", " ")

    if parts[0] == "region" and len(parts) == 3:
        _, region, name = parts
        region = region.replace("-", " ")
        data = getattr(config, "REGION_ENEMIES", {}).get(region, {})
        enemy_list = data.get("enemies", data) if isinstance(data, dict) else data
        enemy = next((e for e in enemy_list if e.get('name') == name), None)
    elif parts[0] == "slayer" and len(parts) == 2:
        _, name = parts
        enemy = next((e for e in getattr(config, "SLAYER_ENEMIES", []) if e.get('name') == name), None)
    elif parts[0] == "demon" and len(parts) == 2:
        _, name = parts
        enemy = next((e for e in getattr(config, "DEMON_ENEMIES", []) if e.get('name') == name), None)
    else:
        enemy = None

    if not enemy:
        await query.edit_message_text("Enemy not found.")
        return

    lines = [
        f"*{enemy.get('name', 'Enemy')}*",
        f"HP: {enemy.get('hp', '—')}",
        f"ATK: {enemy.get('atk', '—')}",
    ]
    desc = enemy.get('desc') or enemy.get('description')
    if desc:
        lines.append(f"_{desc}_")
    await query.edit_message_text("\n".join(lines), parse_mode="Markdown")

# ----- Registration helper -----
def register_owner_listings(app):
    app.add_handler(CommandHandler('liststyles', list_styles))
    app.add_handler(CallbackQueryHandler(style_info_callback, pattern=r'^ownstyle_'))
    app.add_handler(CommandHandler('listarts', list_arts))
    app.add_handler(CallbackQueryHandler(art_info_callback, pattern=r'^ownart_'))
    app.add_handler(CommandHandler('listenemies', list_enemies))
    app.add_handler(CallbackQueryHandler(enemy_info_callback, pattern=r'^ownenemy_'))