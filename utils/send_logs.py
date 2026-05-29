from config import LOG_CHANNEL
from datetime import datetime
import traceback

async def send_error(context, error: Exception):
    error_text = (
            f"*ERROR LOG*\n\n"
            f"Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
            f"Error: `{str(error)}`\n"
        )

    await context.bot.send_message(
            chat_id=LOG_CHANNEL,
            text=error_text,
            parse_mode="Markdown"
        )
