import random
from telegram import Update
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, add_item, col
from utils.guards import dm_only


def get_active_raid():
    doc = col("raids").find_one({"status": {"$in": ["waiting", "active"]}})
    if doc:
        doc.pop("_id", None)
        return doc
    return None


@dm_only
async def joinraid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    raid = get_active_raid()
    if not raid:
        await update.message.reply_text(
            "🌕 *No active raid right now.*\n\n"
            "_Wait for an admin to start a raid!_",
            parse_mode='Markdown'
        )
        return

    # Check already joined
    existing = col("raid_participants").find_one({"raid_id": raid["id"], "user_id": user_id})
    if existing:
        count = col("raid_participants").count_documents({"raid_id": raid["id"]})
        await update.message.reply_text(
            f"⚔️ *Already joined the raid!*\n\n"
            f"👥 Current participants: *{count}*\n"
            f"💀 Boss: *{raid['boss_name']}*\n"
            f"❤️ HP: *{raid['boss_hp']:,}*",
            parse_mode='Markdown'
        )
        return

    col("raid_participants").update_one(
        {"raid_id": raid["id"], "user_id": user_id},
        {"$setOnInsert": {"raid_id": raid["id"], "user_id": user_id, "damage_dealt": 0}},
        upsert=True
    )

    count = col("raid_participants").count_documents({"raid_id": raid["id"]})

    # Activate raid if enough players
    if raid["status"] == "waiting" and count >= raid.get("min_players", 20):
        col("raids").update_one({"id": raid["id"]}, {"$set": {"status": "active"}})
        raid["status"] = "active"

    await update.message.reply_text(
        f"✅ *JOINED THE RAID!*\n\n"
        f"💀 Boss: *{raid['boss_name']}*\n"
        f"❤️ HP: *{raid['boss_hp']:,}*\n"
        f"👥 Participants: *{count}*\n"
        f"{'⚔️ *RAID IS ACTIVE!* Use /raidattack!' if raid['status'] == 'active' else f'⏳ Waiting for {raid.get(chr(109)+chr(105)+chr(110)+chr(95)+chr(112)+chr(108)+chr(97)+chr(121)+chr(101)+chr(114)+chr(115), 20)} players...'}",
        parse_mode='Markdown'
    )


@dm_only
async def raidattack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    raid = get_active_raid()
    if not raid or raid["status"] != "active":
        await update.message.reply_text("❌ No active raid. Use /joinraid first!")
        return

    participant = col("raid_participants").find_one({"raid_id": raid["id"], "user_id": user_id})
    if not participant:
        await update.message.reply_text("❌ You haven't joined this raid! Use /joinraid.")
        return

    # Calculate damage
    dmg = player['str_stat'] * 3 + random.randint(20, 60)
    new_hp = max(0, raid["boss_hp"] - dmg)

    col("raids").update_one({"id": raid["id"]}, {"$set": {"boss_hp": new_hp}})
    col("raid_participants").update_one(
        {"raid_id": raid["id"], "user_id": user_id},
        {"$inc": {"damage_dealt": dmg}}
    )

    if new_hp <= 0:
        # Raid complete — give rewards
        col("raids").update_one({"id": raid["id"]}, {"$set": {"status": "completed"}})

        top = list(col("raid_participants").find({"raid_id": raid["id"]}).sort("damage_dealt", -1).limit(5))
        top_lines = []
        medals = ['🥇', '🥈', '🥉', '4.', '5.']
        for i, p in enumerate(top):
            pp = get_player(p["user_id"])
            name = pp['name'] if pp else f"Player {p['user_id']}"
            top_lines.append(f"{medals[i]} *{name}* — {p['damage_dealt']:,} dmg")

        # Reward all participants
        all_parts = list(col("raid_participants").find({"raid_id": raid["id"]}))
        for part in all_parts:
            pp = get_player(part["user_id"])
            if pp:
                xp_reward  = 5000 + part["damage_dealt"] // 10
                yen_reward = 2000 + part["damage_dealt"] // 20
                update_player(part["user_id"], xp=pp["xp"] + xp_reward, yen=pp["yen"] + yen_reward)
                add_item(part["user_id"], "Boss Shard", "material")

        await update.message.reply_text(
            f"🎉 *RAID COMPLETE!*\n\n"
            f"💀 *{raid['boss_name']}* has been slain!\n\n"
            f"🏆 *Top Damage:*\n" + '\n'.join(top_lines) + "\n\n"
            f"✅ All participants rewarded!\n"
            f"⭐ XP + 💰 Yen + 🔸 Boss Shard",
            parse_mode='Markdown'
        )
        return

    from utils.helpers import hp_bar
    bar = hp_bar(new_hp, raid["boss_max_hp"])
    part_count = col("raid_participants").count_documents({"raid_id": raid["id"]})

    await update.message.reply_text(
        f"⚔️ *RAID ATTACK!*\n\n"
        f"💥 *{player['name']}* deals *{dmg:,}* damage!\n\n"
        f"💀 *{raid['boss_name']}*\n"
        f"❤️ {new_hp:,}/{raid['boss_max_hp']:,} {bar}\n\n"
        f"👥 {part_count} warriors fighting",
        parse_mode='Markdown'
    )
