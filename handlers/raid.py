import random
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, add_item, col
from utils.guards import dm_only


def get_active_raid():
    doc = col("raids").find_one({"status": {"$in": ["waiting", "active"]}})
    if doc:
        doc.pop("_id", None)
        return doc
    return None


def calculate_boss_hp(player_count, avg_level):
    """Calculate boss HP based on player count and average level"""
    base_hp = 500000
    hp_per_player = 150000
    hp_per_level = 5000
    return int(base_hp + (player_count * hp_per_player) + (avg_level * hp_per_level * player_count))


def get_player_combat_stats(player):
    """Get player's combat stats including equipped items and buffs"""
    str_stat = player.get('str_stat', 0)
    equipped_sword = player.get('equipped_sword', '')
    equipped_armor = player.get('equipped_armor', '')
    
    # Sword damage bonuses
    sword_bonus = {
        'Basic Nichirin Blade': 8, 'Crimson Nichirin Blade': 25,
        'Jet Black Nichirin Blade': 50, 'Scarlet Crimson Blade': 80,
        'Transparent Nichirin Blade': 120, 'Sun Nichirin Blade': 200,
        "Muzan's Crimson Fang": 280, 'Moon-Breathing Cursed Blade': 350,
        'Demon Heart Blade': 160, 'Fragment of the First Breath': 450,
        "Akaza's Martial Gauntlet": 100, "Doma's Soul Cracker": 120,
    }
    
    # Armor defense bonuses
    armor_bonus = {
        'Basic Armor': 5, 'Reinforced Armor': 15,
        'Ice Lotus Haori': 60, 'Void Tyrant\'s Cloak': 90,
        "Rui's Spider-Thread Haori": 70, 'Upper Moon Shell': 80,
    }
    
    s_bonus = sword_bonus.get(equipped_sword, 0)
    a_bonus = armor_bonus.get(equipped_armor, 0)
    
    return {
        'str': str_stat,
        'sword_bonus': s_bonus,
        'armor_bonus': a_bonus,
        'total_damage_bonus': s_bonus,
        'total_defense_bonus': a_bonus
    }


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

    # Check if raid timer has expired
    current_time = time.time()
    if raid.get("end_time") and current_time > raid["end_time"]:
        col("raids").update_one({"id": raid["id"]}, {"$set": {"status": "expired"}})
        await update.message.reply_text(
            "⏰ *Raid has expired!*\n\n"
            "The time limit for this raid has ended.",
            parse_mode='Markdown'
        )
        return

    # Check if already defeated in this raid
    if raid.get("defeated_players") and user_id in raid["defeated_players"]:
        await update.message.reply_text(
            "💀 *You have been defeated!*\n\n"
            "You cannot rejoin this raid after being defeated.",
            parse_mode='Markdown'
        )
        return

    # Check already joined
    existing = col("raid_participants").find_one({"raid_id": raid["id"], "user_id": user_id})
    if existing:
        count = col("raid_participants").count_documents({"raid_id": raid["id"]})
        time_remaining = max(0, int((raid.get('end_time', current_time) - current_time) / 60))
        await update.message.reply_text(
            f"⚔️ *Already joined the raid!*\n\n"
            f"👥 Current participants: *{count}*\n"
            f"💀 Boss: *{raid['boss_name']}*\n"
            f"❤️ HP: *{raid['boss_hp']:,}*\n"
            f"⏱️ Time remaining: *{time_remaining} min*",
            parse_mode='Markdown'
        )
        return

    # Calculate and scale boss HP when first player joins
    if not raid.get("start_time"):
        all_players = list(col("players").find({}, {"level": 1}))
        avg_level = sum(p.get("level", 1) for p in all_players) / max(len(all_players), 1)
        
        # Get initial participant count (will be 1 after this join)
        initial_count = col("raid_participants").count_documents({"raid_id": raid["id"]}) + 1
        
        new_boss_hp = calculate_boss_hp(initial_count, avg_level)
        col("raids").update_one(
            {"id": raid["id"]}, 
            {
                "$set": {
                    "boss_hp": new_boss_hp,
                    "boss_max_hp": new_boss_hp,
                    "start_time": current_time
                }
            }
        )
        raid["boss_hp"] = new_boss_hp
        raid["boss_max_hp"] = new_boss_hp

    col("raid_participants").update_one(
        {"raid_id": raid["id"], "user_id": user_id},
        {"$setOnInsert": {"raid_id": raid["id"], "user_id": user_id, "damage_dealt": 0, "defeated": False}},
        upsert=True
    )

    count = col("raid_participants").count_documents({"raid_id": raid["id"]})

    # Activate raid if enough players
    if raid["status"] == "waiting" and count >= raid.get("min_players", 5):
        col("raids").update_one({"id": raid["id"]}, {"$set": {"status": "active"}})
        raid["status"] = "active"

    # Create keyboard for raid actions
    keyboard = [
        [InlineKeyboardButton("⚔️ Attack", callback_data="raid_attack")],
        [InlineKeyboardButton("🎯 Technique", callback_data="raid_technique")],
        [InlineKeyboardButton("🎒 Items", callback_data="raid_items")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    time_remaining = max(0, int((raid.get('end_time', current_time) - current_time) / 60))
    
    await update.message.reply_text(
        f"✅ *JOINED THE RAID!*\n\n"
        f"💀 Boss: *{raid['boss_name']}*\n"
        f"❤️ HP: *{raid['boss_hp']:,}*\n"
        f"👥 Participants: *{count}*\n"
        f"⏱️ Time remaining: *{time_remaining} min*\n"
        f"{'⚔️ *RAID IS ACTIVE!* Choose your action below!' if raid['status'] == 'active' else f'⏳ Waiting for more warriors...'}",
        parse_mode='Markdown',
        reply_markup=reply_markup
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

    # Check if raid timer has expired
    current_time = time.time()
    if raid.get("end_time") and current_time > raid["end_time"]:
        col("raids").update_one({"id": raid["id"]}, {"$set": {"status": "expired"}})
        await update.message.reply_text("⏰ Raid has expired!")
        return

    # Check if player is defeated
    if raid.get("defeated_players") and user_id in raid["defeated_players"]:
        await update.message.reply_text("💀 You are defeated and cannot attack!")
        return

    participant = col("raid_participants").find_one({"raid_id": raid["id"], "user_id": user_id})
    if not participant:
        await update.message.reply_text("❌ You haven't joined this raid! Use /joinraid.")
        return

    if participant.get("defeated"):
        await update.message.reply_text("💀 You are defeated and cannot attack!")
        return

    # Calculate damage with equipment bonuses
    stats = get_player_combat_stats(player)
    dmg = player['str_stat'] * 3 + random.randint(20, 60) + stats['sword_bonus']
    
    # Boss attacks back
    boss_dmg = max(0, raid.get("boss_atk", 150) - stats['armor_bonus'])
    player_hp = player.get('hp', 100)
    new_player_hp = max(0, player_hp - boss_dmg)
    
    # Check if player is defeated
    if new_player_hp <= 0:
        col("raid_participants").update_one(
            {"raid_id": raid["id"], "user_id": user_id},
            {"$set": {"defeated": True}}
        )
        col("raids").update_one(
            {"id": raid["id"]},
            {"$addToSet": {"defeated_players": user_id}}
        )
        update_player(user_id, hp=0)
        
        await update.message.reply_text(
            f"💀 *DEFEATED!*\n\n"
            f"The boss dealt *{boss_dmg}* damage to you!\n"
            f"You can no longer participate in this raid.\n"
            f"Your damage dealt: *{participant.get('damage_dealt', 0):,}*",
            parse_mode='Markdown'
        )
        return
    
    # Update player HP
    update_player(user_id, hp=new_player_hp)
    
    new_hp = max(0, raid["boss_hp"] - dmg)
    col("raids").update_one({"id": raid["id"]}, {"$set": {"boss_hp": new_hp}})
    col("raid_participants").update_one(
        {"raid_id": raid["id"], "user_id": user_id},
        {"$inc": {"damage_dealt": dmg}}
    )

    if new_hp <= 0:
        # Raid complete — give rewards
        await handle_raid_completion(context, raid)
        return

    from utils.helpers import hp_bar
    bar = hp_bar(new_hp, raid["boss_max_hp"])
    part_count = col("raid_participants").count_documents({"raid_id": raid["id"]})
    time_remaining = max(0, int((raid.get('end_time', current_time) - current_time) / 60))

    # Create keyboard for continued fighting
    keyboard = [
        [InlineKeyboardButton("⚔️ Attack Again", callback_data="raid_attack")],
        [InlineKeyboardButton("🎯 Technique", callback_data="raid_technique")],
        [InlineKeyboardButton("🎒 Items", callback_data="raid_items")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"⚔️ *RAID ATTACK!*\n\n"
        f"💥 *{player['name']}* deals *{dmg:,}* damage!\n"
        f"💢 Boss counterattacks: *{boss_dmg}* damage!\n"
        f"❤️ Your HP: *{new_player_hp}*\n\n"
        f"💀 *{raid['boss_name']}*\n"
        f"❤️ {new_hp:,}/{raid['boss_max_hp']:,} {bar}\n\n"
        f"👥 {part_count} warriors fighting\n"
        f"⏱️ Time remaining: *{time_remaining} min*",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def handle_raid_completion(context, raid):
    """Handle raid completion and distribute rewards"""
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
    
    # Sort by damage for reward distribution
    all_parts_sorted = sorted(all_parts, key=lambda x: x.get("damage_dealt", 0), reverse=True)
    
    for idx, part in enumerate(all_parts_sorted):
        pp = get_player(part["user_id"])
        if pp:
            base_xp = 5000
            base_yen = 2000
            
            # Bonus based on ranking
            if idx == 0:
                bonus_mult = 1.5  # +50% for MVP
                bonus_items = ["Legendary Forge Hammer", "Demon Blood Essence"]
            elif idx == 1:
                bonus_mult = 1.3  # +30% for 2nd
                bonus_items = ["Rare Forge Material", "Spirit Crystal"]
            elif idx == 2:
                bonus_mult = 1.2  # +20% for 3rd
                bonus_items = ["Forge Material", "Moon Shard"]
            else:
                bonus_mult = 1.0
                bonus_items = ["Boss Shard"]
            
            xp_reward = int((base_xp + part["damage_dealt"] // 10) * bonus_mult)
            yen_reward = int((base_yen + part["damage_dealt"] // 20) * bonus_mult)
            
            update_player(part["user_id"], xp=pp["xp"] + xp_reward, yen=pp["yen"] + yen_reward)
            
            # Give bonus items
            for item in bonus_items:
                add_item(part["user_id"], item, "material")

    # Send leaderboard to clan group
    owner_player = get_player(raid.get("owner_id"))
    if owner_player and owner_player.get("clan"):
        clan_doc = col("clans").find_one({"name": owner_player["clan"]})
        if clan_doc and clan_doc.get("group_id"):
            try:
                result_msg = (
                    f"🎉 *RAID COMPLETE!*\n\n"
                    f"💀 *{raid['boss_name']}* has been slain!\n\n"
                    f"🏆 *Damage Leaderboard:*\n" + '\n'.join(top_lines) + "\n\n"
                    f"✅ All participants rewarded!\n"
                    f"⭐ XP + 💰 Yen + 🔸 Special Forge Materials"
                )
                await context.bot.send_message(
                    chat_id=clan_doc["group_id"],
                    text=result_msg,
                    parse_mode='Markdown'
                )
            except:
                pass

    # Notify all participants
    for part in all_parts:
        try:
            pp = get_player(part["user_id"])
            if pp:
                rank = next((i for i, p in enumerate(all_parts_sorted) if p["user_id"] == part["user_id"]), -1) + 1
                rank_str = f"#{rank}"
                if rank == 1:
                    rank_str = "🥇 MVP"
                elif rank == 2:
                    rank_str = "🥈 2nd"
                elif rank == 3:
                    rank_str = "🥉 3rd"
                
                await context.bot.send_message(
                    chat_id=part["user_id"],
                    text=(
                        f"🎉 *RAID VICTORY!*\n\n"
                        f"💀 *{raid['boss_name']}* defeated!\n\n"
                        f"📊 Your Rank: *{rank_str}*\n"
                        f"⚔️ Damage Dealt: *{part['damage_dealt']:,}*\n\n"
                        f"🎁 Rewards received:\n"
                        f"⭐ XP + 💰 Yen + Special Items"
                    ),
                    parse_mode='Markdown'
                )
        except:
            pass


# Callback handlers for raid buttons
async def raid_attack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle attack button callback"""
    query = update.callback_query
    await query.answer()
    # Simulate a message to trigger attack logic
    query.message.text = "/raidattack"
    await raidattack(query, context)


async def raid_technique_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle technique button callback - uses player's techniques in raid"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    player = get_player(user_id)
    if not player:
        await query.edit_message_text("❌ No character found.")
        return
    
    raid = get_active_raid()
    if not raid or raid["status"] != "active":
        await query.edit_message_text("❌ No active raid.")
        return
    
    # Check if defeated
    if raid.get("defeated_players") and user_id in raid["defeated_players"]:
        await query.edit_message_text("💀 You are defeated!")
        return
    
    participant = col("raid_participants").find_one({"raid_id": raid["id"], "user_id": user_id})
    if not participant or participant.get("defeated"):
        await query.edit_message_text("💀 You cannot use techniques!")
        return
    
    # Get player techniques
    techniques = player.get("techniques", [])
    if not techniques:
        await query.edit_message_text("❌ You have no techniques!")
        return
    
    # Use first available technique for bonus damage
    tech_name = techniques[0] if isinstance(techniques[0], str) else techniques[0].get("name", "Technique")
    tech_bonus = 50 + (player.get('level', 1) * 10)
    
    stats = get_player_combat_stats(player)
    dmg = int((player['str_stat'] * 4 + random.randint(30, 80) + stats['sword_bonus']) * (1 + tech_bonus/100))
    
    # Boss counterattacks harder for technique use
    boss_dmg = max(0, raid.get("boss_atk", 150) * 1.2 - stats['armor_bonus'])
    player_hp = player.get('hp', 100)
    new_player_hp = max(0, player_hp - boss_dmg)
    
    if new_player_hp <= 0:
        col("raid_participants").update_one(
            {"raid_id": raid["id"], "user_id": user_id},
            {"$set": {"defeated": True}}
        )
        col("raids").update_one(
            {"id": raid["id"]},
            {"$addToSet": {"defeated_players": user_id}}
        )
        update_player(user_id, hp=0)
        
        await query.edit_message_text(
            f"💀 *DEFEATED!*\\n\\n"
            f"Your technique *{tech_name}* provoked the boss!\\n"
            f"Boss dealt *{boss_dmg}* damage!\\n"
            f"You can no longer participate.",
            parse_mode='Markdown'
        )
        return
    
    update_player(user_id, hp=new_player_hp)
    
    new_hp = max(0, raid["boss_hp"] - dmg)
    col("raids").update_one({"id": raid["id"]}, {"$set": {"boss_hp": new_hp}})
    col("raid_participants").update_one(
        {"raid_id": raid["id"], "user_id": user_id},
        {"$inc": {"damage_dealt": dmg}}
    )
    
    if new_hp <= 0:
        await handle_raid_completion(context, raid)
        return
    
    from utils.helpers import hp_bar
    bar = hp_bar(new_hp, raid["boss_max_hp"])
    
    keyboard = [
        [InlineKeyboardButton("⚔️ Attack", callback_data="raid_attack")],
        [InlineKeyboardButton("🎯 Technique", callback_data="raid_technique")],
        [InlineKeyboardButton("🎒 Items", callback_data="raid_items")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        f"🎯 *TECHNIQUE ATTACK!*\\n\\n"
        f"✨ *{player['name']}* uses *{tech_name}*!\\n"
        f"💥 Deals *{dmg:,}* damage!\\n"
        f"💢 Boss counterattacks: *{boss_dmg}* damage!\\n"
        f"❤️ Your HP: *{new_player_hp}*\\n\\n"
        f"💀 *{raid['boss_name']}*\\n"
        f"❤️ {new_hp:,}/{raid['boss_max_hp']:,} {bar}",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def raid_items_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle items button callback"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    player = get_player(user_id)
    if not player:
        await query.edit_message_text("❌ No character found.")
        return
    
    # Get player inventory
    items = player.get("inventory", [])
    if not items:
        await query.edit_message_text("🎒 Your inventory is empty!")
        return
    
    # Show usable items
    keyboard = []
    for item in items[:10]:  # Limit to 10 items
        item_name = item.get("name", item) if isinstance(item, dict) else item
        keyboard.append([InlineKeyboardButton(f"🎁 {item_name}", callback_data=f"raid_use_{item_name}")])
    
    keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="raid_back")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "🎒 *Select an item to use:*\\n\\n"
        "_Items may restore HP or provide bonuses_",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def raid_use_item_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle using an item in raid"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    item_name = query.data.replace("raid_use_", "")
    
    player = get_player(user_id)
    raid = get_active_raid()
    
    if not raid or raid["status"] != "active":
        await query.edit_message_text("❌ No active raid.")
        return
    
    # Simple item effects
    heal_amount = 0
    damage_bonus = 0
    
    if "potion" in item_name.lower() or "heal" in item_name.lower():
        heal_amount = 50
    elif "elixir" in item_name.lower():
        heal_amount = 100
    elif "bomb" in item_name.lower() or "explosive" in item_name.lower():
        damage_bonus = 100
    else:
        heal_amount = 25  # Default small heal
    
    if heal_amount > 0:
        current_hp = player.get('hp', 100)
        max_hp = player.get('max_hp', 100)
        new_hp = min(max_hp, current_hp + heal_amount)
        update_player(user_id, hp=new_hp)
        
        await query.edit_message_text(
            f"💊 Used *{item_name}*!\\n"
            f"❤️ Restored *{heal_amount}* HP!\\n"
            f"Current HP: *{new_hp}*",
            parse_mode='Markdown'
        )
        return
    
    # Remove item from inventory (simplified)
    await query.edit_message_text(f"🎁 Used *{item_name}*! Effect applied.", parse_mode='Markdown')


async def raid_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle back button in raid"""
    query = update.callback_query
    await query.answer()
    
    raid = get_active_raid()
    if not raid:
        await query.edit_message_text("❌ No active raid.")
        return
    
    keyboard = [
        [InlineKeyboardButton("⚔️ Attack", callback_data="raid_attack")],
        [InlineKeyboardButton("🎯 Technique", callback_data="raid_technique")],
        [InlineKeyboardButton("🎒 Items", callback_data="raid_items")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    current_time = time.time()
    time_remaining = max(0, int((raid.get('end_time', current_time) - current_time) / 60))
    
    await query.edit_message_text(
        f"⚔️ *RAID IN PROGRESS*\\n\\n"
        f"💀 Boss: *{raid['boss_name']}*\\n"
        f"❤️ HP: *{raid['boss_hp']:,}/{raid['boss_max_hp']:,}*\\n"
        f"⏱️ Time remaining: *{time_remaining} min*\\n\\n"
        f"Choose your action:",
        parse_mode='Markdown',
        reply_markup=reply_markup
    )


async def raid_retreat_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle retreat from raid"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    raid = get_active_raid()
    
    if not raid:
        await query.edit_message_text("❌ No active raid.")
        return
    
    # Mark as defeated
    col("raid_participants").update_one(
        {"raid_id": raid["id"], "user_id": user_id},
        {"$set": {"defeated": True, "retreated": True}}
    )
    col("raids").update_one(
        {"id": raid["id"]},
        {"$addToSet": {"defeated_players": user_id}}
    )
    
    await query.edit_message_text(
        "🏃 *RETIRED FROM RAID!*\\n\\n"
        "You have retreated from the battle.\\n"
        "You will receive reduced rewards based on damage dealt.",
        parse_mode='Markdown'
    )
