import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

log = logging.getLogger(__name__)

# Define forge items data
FORGE_ITEMS = [
    {
        "name": "Crimson Nichirin Blade",
        "cost": 500,
        "str": 8,
        "requirements": {
            "Basic Nichirin Blade": 1,
            "Demon Blood": 0,
            "Wolf Fang": 0,
        },
        "locked": True,
    },
    {
        "name": "Jet Black Nichirin Blade",
        "cost": 2000,
        "str": 18,
        "requirements": {
            "Crimson Nichirin Blade": 1,
            "Blood Crystal": 0,
            "Boss Shard": 0,
            "Demon Blood": 0,
        },
        "locked": True,
    },
    {
        "name": "Scarlet Crimson Blade",
        "cost": 8000,
        "str": 30,
        "requirements": {
            "Jet Black Nichirin Blade": 1,
            "Blood Crystal": 0,
            "Boss Shard": 0,
            "Hashira Badge": 0,
            "Ancient Whetstone": 0,
        },
        "locked": True,
    },
    {
        "name": "Transparent Nichirin Blade",
        "cost": 20000,
        "str": 50,
        "requirements": {
            "Scarlet Crimson Blade": 1,
            "Rare Ore Fragment": 0,
            "Boss Shard": 0,
            "Titan Core": 0,
            "Ancient Whetstone": 0,
        },
        "locked": True,
    },
    {
        "name": "Sun Nichirin Blade",
        "cost": 60000,
        "str": 80,
        "requirements": {
            "Transparent Nichirin Blade": 1,
            "Sun Breathing Tome": 0,
            "Boss Shard": 0,
            "King Blade": 0,
            "Rengoku Shard": 0,
        },
        "locked": True,
    },
    # Armor path items (example subset)
    {
        "name": "Reinforced Haori",
        "cost": 400,
        "def": 5,
        "hp": 20,
        "requirements": {
            "Corps Uniform": 1,
            "Spider Silk": 0,
            "Demon Blood": 0,
        },
        "locked": True,
    },
    {
        "name": "Hashira Haori",
        "cost": 1500,
        "def": 12,
        "hp": 40,
        "requirements": {
            "Reinforced Haori": 1,
            "Boss Shard": 0,
            "Spider Silk": 0,
            "Blood Crystal": 0,
        },
        "locked": True,
    },
    # Additional items can be added similarly
]

def _build_forge_keyboard():
    """Create an inline keyboard with a button for each forge item."""
    buttons = []
    for idx, item in enumerate(FORGE_ITEMS):
        label = f"🔒 {item['name']}" if item.get("locked", False) else item['name']
        buttons.append([InlineKeyboardButton(label, callback_data=f"forge_{idx}")])
    return InlineKeyboardMarkup(buttons)

async def forge_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/forge – Show the upgrade UI with all items as buttons."""
    try:
        await update.effective_message.reply_text(
            "*⚒️ Upgrade Forge*\nSelect an item to view its requirements and costs.",
            parse_mode="Markdown",
            reply_markup=_build_forge_keyboard(),
        )
    except Exception as e:
        log.error("[FORGE] Failed to send forge UI: %s", e)

async def forge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button presses from the forge UI and show item details."""
    query = update.callback_query
    await query.answer()
    data = query.data
    if not data.startswith("forge_"):
        return
    idx = int(data.split("_")[1])
    if idx < 0 or idx >= len(FORGE_ITEMS):
        await query.edit_message_text("Invalid selection.")
        return
    item = FORGE_ITEMS[idx]
    lines = []
    lines.append(f"*{item['name']}* ➜ Cost: {item['cost']}¥")
    if "str" in item:
        lines.append(f"📈 +{item['str']} STR")
    if "def" in item:
        lines.append(f"🛡️ +{item['def']} DEF")
    if "hp" in item:
        lines.append(f"❤️ +{item['hp']} Max HP")
    lines.append("\n*Requirements:*")
    for req, amt in item["requirements"].items():
        # Show bar representation based on required amount (placeholder logic)
        bar = "✅" if amt == 0 else f"❌ {amt}/?"
        lines.append(f"{bar} {req}")
    text = "\n".join(lines)
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=_build_forge_keyboard())
    # Stop further callback routing
    from telegram.ext import ApplicationHandlerStop
    raise ApplicationHandlerStop

__all__ = ["forge_command", "forge_callback"]
