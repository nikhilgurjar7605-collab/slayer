import logging
from telegram import Update
from telegram.ext import ContextTypes
from config import SLAYER_ENEMIES, DEMON_ENEMIES, REGION_ENEMIES, TRAVEL_ZONES
from handlers.explore import get_image_url
from utils.guards import owner_only

log = logging.getLogger(__name__)

@owner_only
async def checkimages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command to check which enemies are missing images."""
    missing_enemies = []

    # Collect all enemy names across all categories
    all_enemies = set()
    for e in SLAYER_ENEMIES: all_enemies.add(e['name'])
    for e in DEMON_ENEMIES: all_enemies.add(e['name'])
    for e in REGION_ENEMIES: all_enemies.add(e['name'])
    for zone in TRAVEL_ZONES.values():
        for e in zone.get('enemies', []):
            all_enemies.add(e['name'])

    # Check each enemy for an image URL
    for name in all_enemies:
        url = get_image_url("enemies", name)
        if not url:
            missing_enemies.append(name)

    if missing_enemies:
        missing_list = "\n".join(f"- {name}" for name in sorted(missing_enemies))
        text = f"🖼️ *Missing Enemy Images ({len(missing_enemies)}):*\n\n{missing_list}"
    else:
        text = "✅ All enemies have images configured!"

    # Split text if it's too long for a single message
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i+4000], parse_mode="Markdown")
