from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, get_inventory, remove_item

async def use(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "💊 *USE ITEM*\n\n"
            "Usage: `/use [item name]`\n\n"
            "🔤 *Examples:*\n"
            "  `/use gourd` — Full Recovery Gourd\n"
            "  `/use stamina` — Stamina Pill\n"
            "  `/use wisteria` — Wisteria Antidote\n\n"
            "Use /inventory to see your items.",
            parse_mode='Markdown'
        )
        return

    item_name = ' '.join(args)
    # Support codenames
    codemap = {'gourd': 'Full Recovery Gourd', 'stamina': 'Stamina Pill', 'wisteria': 'Wisteria Antidote'}
    item_name = codemap.get(item_name.lower(), item_name)

    inv = get_inventory(user_id)
    owned = next((i for i in inv if i['item_name'].lower() == item_name.lower()), None)

    if not owned:
        await update.message.reply_text(
            f"❌ *Not in inventory:* `{item_name}`\n\n"
            f"Use /inventory to see what you own.",
            parse_mode='Markdown'
        )
        return

    if owned['item_type'] != 'item':
        await update.message.reply_text(
            f"❌ *{owned['item_name']}* can't be used directly.\n"
            f"💸 Sell it with `/sell {owned['item_name']}`",
            parse_mode='Markdown'
        )
        return

    result = ""
    if 'Recovery Gourd' in owned['item_name']:
        if player['hp'] >= player['max_hp']:
            await update.message.reply_text("❤️ Your HP is already full!")
            return
        update_player(user_id, hp=player['max_hp'])
        result = f"❤️ HP fully restored!  *{player['max_hp']}/{player['max_hp']}*"

    elif 'Stamina Pill' in owned['item_name']:
        if player['sta'] >= player['max_sta']:
            await update.message.reply_text("🌀 Your Stamina is already full!")
            return
        new_sta = min(player['max_sta'], player['sta'] + 50)
        update_player(user_id, sta=new_sta)
        result = f"🌀 STA restored:  *+50* → {new_sta}/{player['max_sta']}"

    elif 'Wisteria' in owned['item_name']:
        result = "☘️ Poison & status effects cured!"
    else:
        result = f"✨ Used {owned['item_name']}."

    remove_item(user_id, owned['item_name'])
    await update.message.reply_text(
        f"✅ *ITEM USED!*\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💊 *{owned['item_name']}*\n\n"
        f"{result}",
        parse_mode='Markdown'
    )
