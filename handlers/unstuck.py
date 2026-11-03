from telegram import Update
from telegram.ext import ContextTypes
from utils.database import (get_player, get_battle_state, clear_battle_state,
                             update_player, col)
from utils.guards import dm_only
from handlers.admin import has_admin_access


def _clear_castle_state(user_id):
    """Release a player from a stuck Castle run without deleting squad progress.

    If the player is in a running co-op squad, the shared expedition is safely
    abandoned and the squad returns to its open lobby so the team can retry.
    Open squad membership and its invite code are preserved.
    """
    from datetime import datetime

    user_id = int(user_id)
    fixed = []

    # Clear stale or stuck Infinity Castle solo/co-op run state.
    fixed.extend(_clear_castle_state(user_id))
    party = col("castle_parties").find_one({
        "$or": [{"member_ids": user_id}, {"leader_id": user_id}],
        "status": {"$in": ["open", "running"]},
    }, sort=[("updated_at", -1)])

    run_query = {"user_id": user_id, "status": "active"}
    if party and party.get("status") == "running":
        party_id = str(party.get("party_id", ""))
        if party_id:
            run_query = {"party_id": party_id, "status": "active"}

    result = col("castle_runs").update_many(
        run_query,
        {"$set": {
            "status": "abandoned",
            "abandoned_at": datetime.utcnow(),
            "abandoned_reason": "player_used_unstuck",
            "updated_at": datetime.utcnow(),
        }},
    )
    if result.modified_count:
        fixed.append("🏯 Stuck Infinity Castle battle cleared")

    if party and party.get("status") == "running":
        col("castle_parties").update_one(
            {"party_id": party["party_id"], "status": "running"},
            {"$set": {
                "status": "open",
                "ready_ids": [],
                "updated_at": datetime.utcnow(),
            }},
        )
        fixed.append("👥 Squad returned to its lobby; members can ready up and retry")

    return fixed


@dm_only
async def unstuck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    fixed = []

    # Clear battle state
    state = get_battle_state(user_id)
    if state:
        clear_battle_state(user_id)
        fixed.append("⚔️ Battle state cleared")

    # Abandon active duel
    duel = col("duels").find_one({"$or": [{"challenger_id": user_id}, {"target_id": user_id}], "status": "active"})
    if duel:
        col("duels").update_one({"_id": duel["_id"]}, {"$set": {"status": "abandoned"}})
        fixed.append("🗡️ Active duel abandoned")

    # Abandon coop as guest
    coop_guest = col("coop_battles").find_one({"guest_id": user_id, "status": "active"})
    if coop_guest:
        col("coop_battles").update_one({"_id": coop_guest["_id"]}, {"$set": {"status": "abandoned"}})
        fixed.append("👥 Co-op (guest) abandoned")

    # Abandon coop as host
    for row in col("coop_battles").find({"host_id": user_id, "status": "active"}):
        col("coop_battles").update_one({"_id": row["_id"]}, {"$set": {"status": "abandoned"}})
    fixed.append("👥 Co-op (host) cleared")

    # Restore HP/STA
    update_player(user_id, hp=player['max_hp'], sta=player['max_sta'])
    fixed.append("❤️ HP and STA restored")

    if fixed:
        await update.message.reply_text(
            f"✅ *UNSTUCK COMPLETE*\n\n" + "\n".join(f"• {f}" for f in fixed) +
            "\n\nYou're free! Use /explore to continue.",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(
            "✅ Nothing to fix — you don't appear to be stuck!\n\nUse /explore to continue.",
            parse_mode='Markdown'
        )


async def forceunstuck(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: `/forceunstuck [user_id]`", parse_mode='Markdown')
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    target = col("players").find_one({"user_id": target_id})
    if not target:
        await update.message.reply_text("❌ Player not found.")
        return

    # Same cleanup
    _clear_castle_state(target_id)
    clear_battle_state(target_id)
    col("duels").update_many({"$or": [{"challenger_id": target_id}, {"target_id": target_id}], "status": "active"}, {"$set": {"status": "abandoned"}})
    col("coop_battles").update_many({"$or": [{"host_id": target_id}, {"guest_id": target_id}], "status": "active"}, {"$set": {"status": "abandoned"}})
    update_player(target_id, hp=target['max_hp'], sta=target['max_sta'])

    await update.message.reply_text(
        f"✅ *Force unstuck* applied to *{target['name']}* (ID: {target_id})",
        parse_mode='Markdown'
    )
