from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, col
from utils.guards import dm_only
from datetime import datetime


@dm_only
async def auction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    auctions = list(col("auctions").find({"status": "active"}).sort("ends_at", 1))
    for a in auctions:
        a.pop("_id", None)

    if not auctions:
        await update.message.reply_text(
            "🏛️ *AUCTION HOUSE*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            "_No active auctions right now._\n\n"
            "_Check back later!_",
            parse_mode='Markdown'
        )
        return

    lines = [
        "🏛️ *AUCTION HOUSE*",
        "━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for i, a in enumerate(auctions, 1):
        ends = a.get('ends_at', '')
        if isinstance(ends, datetime):
            ends_str = ends.strftime('%m/%d %H:%M')
        else:
            ends_str = str(ends)[:16]
        emoji = a.get('item_emoji', '🎁')
        lines.append(
            f"*[{i}]* {emoji} *{a['item_name']}*\n"
            f"   💰 Current bid: *{a.get('current_bid', 0):,}¥*\n"
            f"   ⏰ Ends: _{ends_str}_"
        )
    lines += [
        "",
        "━━━━━━━━━━━━━━━━━━━━━",
        f"💰 Your wallet: *{player['yen']:,}¥*",
        "",
        "💡 `/bid [id] [amount]` — Place a bid",
    ]
    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')


@dm_only
async def bid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    if len(context.args or []) < 2:
        await update.message.reply_text("Usage: `/bid [id] [amount]`", parse_mode='Markdown')
        return

    try:
        auction_idx = int(context.args[0])
        bid_amount  = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid format. Use `/bid [id] [amount]`", parse_mode='Markdown')
        return

    auctions = list(col("auctions").find({"status": "active"}).sort("ends_at", 1))
    if auction_idx < 1 or auction_idx > len(auctions):
        await update.message.reply_text(f"❌ No auction #{auction_idx}. Use /auction to see current listings.", parse_mode='Markdown')
        return

    a = auctions[auction_idx - 1]
    current_bid = a.get('current_bid', 0)

    if bid_amount <= current_bid:
        await update.message.reply_text(f"❌ Bid must exceed *{current_bid:,}¥*!", parse_mode='Markdown')
        return

    if player['yen'] < bid_amount:
        await update.message.reply_text(f"❌ Not enough Yen! You have *{player['yen']:,}¥*", parse_mode='Markdown')
        return

    # Refund previous highest bidder
    prev_bidder = a.get('highest_bidder')
    if prev_bidder and prev_bidder != user_id:
        prev = get_player(prev_bidder)
        if prev:
            update_player(prev_bidder, yen=prev['yen'] + current_bid)

    # Deduct from bidder
    update_player(user_id, yen=player['yen'] - bid_amount)

    # Update auction
    col("auctions").update_one(
        {"_id": a["_id"]},
        {"$set": {"current_bid": bid_amount, "highest_bidder": user_id}}
    )

    await update.message.reply_text(
        f"✅ *BID PLACED!*\n\n"
        f"🎁 *{a['item_name']}*\n"
        f"💰 Your bid: *{bid_amount:,}¥*\n"
        f"👛 Remaining: *{player['yen']-bid_amount:,}¥*\n\n"
        f"_You'll be notified if outbid!_",
        parse_mode='Markdown'
    )
