import logging
import json
from telegram import Update
from telegram.ext import ContextTypes
from utils.guards import owner_only
from utils.database import col

log = logging.getLogger(__name__)

@owner_only
async def bulkaddspirits(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin command to add multiple spirits at once.
    Expects a JSON file to be attached or replied to.
    Format: [{"name": "...", "rarity": "Legendary", "emoji": "🔥", "atk": 10, "def": 5, "hp": 5}]
    """
    message = update.message
    if not message.reply_to_message and not message.document:
        await message.reply_text(
            "Please upload a `.json` file containing the spirits you want to add, or reply to a message containing the file.\n\n"
            "Format example:\n"
            "```json\n"
            "[\n"
            "  {\n"
            "    \"name\": \"Moon Rabbit\",\n"
            "    \"rarity\": \"Legendary\",\n"
            "    \"emoji\": \"🐇\",\n"
            "    \"atk\": 15,\n"
            "    \"def\": 10,\n"
            "    \"hp\": 20\n"
            "  }\n"
            "]\n"
            "```",
            parse_mode="Markdown"
        )
        return

    doc = message.document if message.document else message.reply_to_message.document
    if not doc or not doc.file_name.endswith('.json'):
        await message.reply_text("❌ Please provide a valid `.json` file.")
        return

    try:
        file = await context.bot.get_file(doc.file_id)
        content = await file.download_as_bytearray()
        data = json.loads(content.decode('utf-8'))

        if not isinstance(data, list):
            await message.reply_text("❌ The JSON file must contain a list of spirit objects.")
            return

        added_count = 0
        errors = []
        for index, item in enumerate(data):
            if 'name' not in item or 'rarity' not in item or 'emoji' not in item:
                errors.append(f"Row {index+1}: Missing required fields (name, rarity, emoji)")
                continue

            name = item['name'].strip()
            rarity = item['rarity'].strip().capitalize()
            emoji = item['emoji'].strip()
            atk_pct = int(item.get('atk', 0))
            def_pct = int(item.get('def', 0))
            hp_pct = int(item.get('hp', 0))

            # Check if exists
            existing = col("gacha_spirits").find_one({"name": {"$regex": f"^{name}$", "$options": "i"}})
            if existing:
                errors.append(f"Row {index+1}: Spirit '{name}' already exists.")
                continue

            new_spirit = {
                "name": name,
                "emoji": emoji,
                "rarity": rarity,
                "universe": item.get('universe', "Cross-Universe").strip(),
                "passives": {
                    "atk_pct": atk_pct,
                    "def_pct": def_pct,
                    "hp_pct": hp_pct,
                },
                "image": item.get('image', None)
            }
            col("gacha_spirits").insert_one(new_spirit)
            added_count += 1

        # Refresh the cache in utils.spirits
        try:
            from utils.spirits import _refresh_cross_cache
            _refresh_cross_cache()
        except ImportError:
            pass

        success_msg = f"✅ Successfully added {added_count} spirits!"
        if errors:
            success_msg += f"\n\n⚠️ Encountered {len(errors)} errors:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                success_msg += f"\n...and {len(errors) - 10} more."

        await message.reply_text(success_msg)

    except Exception as e:
        log.error(f"Error processing bulk spirits: {e}")
        await message.reply_text(f"❌ Error processing file: {str(e)}")
