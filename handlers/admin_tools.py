from telegram import Update
from telegram.ext import ContextTypes
from config import OWNER_ID
from utils.database import col

def is_admin(user_id: int) -> bool:
    if user_id == OWNER_ID:
        return True
    return col("admins").find_one({"user_id": user_id}) is not None

async def get_media_file_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat or update.effective_chat.type != "private":
        return

    user = update.effective_user
    if not user or not is_admin(user.id):
        return

    message = update.message
    if not message:
        return

    file_id = None
    media_type = ""

    if message.photo:
        file_id = message.photo[-1].file_id
        media_type = "Photo"
    elif message.video:
        file_id = message.video.file_id
        media_type = "Video"
    elif message.sticker:
        file_id = message.sticker.file_id
        media_type = "Sticker"

    if file_id:
        await message.reply_text(
            f"*{media_type} File ID:*\n`{file_id}`\n\n_(Tap the ID to copy)_", 
            parse_mode='Markdown'
        )
