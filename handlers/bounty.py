from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
import json
from utils.database import get_player, update_player, col, get_inventory

BOUNTY_LOADOUT_LIMIT = 3

async def _safe_edit(query, text, **kwargs):
    try:
        await query.edit_message_text(text, **kwargs)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise

async def target_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate a hunt against a target user. Command must be a reply to a target."""
    message = update.message
    if not message.reply_to_message:
        await message.reply_text("❌ You must reply to the message of the player you want to target.")
        return

    hunter = update.effective_user
    target_user = message.reply_to_message.from_user

    if hunter.id == target_user.id:
        await message.reply_text("❌ You can't put a bounty on yourself!")
        return

    if target_user.is_bot:
        await message.reply_text("❌ You can't target a bot.")
        return

    target_player = get_player(target_user.id)
    if not target_player:
        await message.reply_text("❌ That user has not started the game.")
        return

    hunter_player = get_player(hunter.id)
    if not hunter_player:
        await message.reply_text("❌ You must start the game first.")
        return

    # Check if a hunt is already active
    battle = col("bounty_hunts").find_one({"hunter_id": hunter.id, "status": "loadout"})
    if battle:
        await message.reply_text("❌ You are already preparing a hunt. Finish it first!")
        return

    # Initialize hunt state
    hunt_state = {
        "hunter_id": hunter.id,
        "target_id": target_user.id,
        "status": "loadout",
        "loadout": []
    }
    col("bounty_hunts").update_one(
        {"hunter_id": hunter.id},
        {"$set": hunt_state},
        upsert=True
    )

    await _show_loadout_menu(update, context, hunter.id, target_player)

async def _show_loadout_menu(update, context, hunter_id, target_player, query=None):
    hunt = col("bounty_hunts").find_one({"hunter_id": hunter_id, "status": "loadout"})
    if not hunt:
        if query:
            await query.answer("Hunt expired or not found.", show_alert=True)
        return

    loadout = hunt.get("loadout", [])

    inv = get_inventory(hunter_id)
    consumables = [i for i in inv if i.get("item_type") == "item"]

    text = (
        f"🎯 *TARGET ACQUIRED: {target_player['name']}*\n"
        f"💰 Current Bounty: *{target_player.get('bounty', 5000):,}* Marks\n\n"
        f"Prepare for the assassination.\n"
        f"Choose up to {BOUNTY_LOADOUT_LIMIT} consumable items to bring.\n\n"
        f"📦 *Your Loadout ({len(loadout)}/{BOUNTY_LOADOUT_LIMIT}):*\n"
    )
    if loadout:
        for item in loadout:
            text += f" - {item}\n"
    else:
        text += " - Empty\n"

    keyboard = []

    for item in consumables:
        name = item["item_name"]
        qty = item["quantity"]
        # Only show items they have enough of for their loadout selection
        count_in_loadout = loadout.count(name)
        if count_in_loadout < qty:
             keyboard.append([InlineKeyboardButton(f"Add {name} (x{qty - count_in_loadout})", callback_data=f"bl_add|{name}")])

    if loadout:
        keyboard.append([InlineKeyboardButton("❌ Clear Loadout", callback_data="bl_clear")])
        keyboard.append([InlineKeyboardButton("⚔️ COMMENCE HUNT", callback_data="bl_start")])
    else:
        keyboard.append([InlineKeyboardButton("⚔️ COMMENCE HUNT (No Items)", callback_data="bl_start")])

    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="bl_cancel")])

    markup = InlineKeyboardMarkup(keyboard)

    if query:
        await _safe_edit(query, text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

async def bounty_loadout_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    hunt = col("bounty_hunts").find_one({"hunter_id": user_id, "status": "loadout"})
    if not hunt:
        await query.answer("No active hunt preparation found.", show_alert=True)
        return

    if data.startswith("bl_add|"):
        if len(hunt["loadout"]) >= BOUNTY_LOADOUT_LIMIT:
            await query.answer(f"Loadout full! Max {BOUNTY_LOADOUT_LIMIT} items.", show_alert=True)
            return

        item_name = data.split("|")[1]

        # Verify they actually own it and haven't over-added
        inv = get_inventory(user_id)
        owned = next((i for i in inv if i["item_name"] == item_name), None)
        if not owned:
            await query.answer("You don't own this item.", show_alert=True)
            return

        count_in_loadout = hunt["loadout"].count(item_name)
        if count_in_loadout >= owned["quantity"]:
             await query.answer("You don't have enough of this item.", show_alert=True)
             return

        hunt["loadout"].append(item_name)
        col("bounty_hunts").update_one(
            {"hunter_id": user_id},
            {"$set": {"loadout": hunt["loadout"]}}
        )
        await query.answer(f"Added {item_name} to loadout.")
        target_player = get_player(hunt["target_id"])
        await _show_loadout_menu(update, context, user_id, target_player, query)

    elif data == "bl_clear":
        col("bounty_hunts").update_one(
            {"hunter_id": user_id},
            {"$set": {"loadout": []}}
        )
        await query.answer("Loadout cleared.")
        target_player = get_player(hunt["target_id"])
        await _show_loadout_menu(update, context, user_id, target_player, query)

    elif data == "bl_cancel":
        col("bounty_hunts").delete_one({"hunter_id": user_id})
        await _safe_edit(query, "❌ Hunt canceled.", parse_mode="Markdown")

    elif data == "bl_start":
        await query.answer("Beginning assassination...", show_alert=False)
        await _start_hunt_combat(update, context, user_id, hunt)


async def _start_hunt_combat(update, context, hunter_id, hunt):
    query = update.callback_query

    target_player = get_player(hunt["target_id"])
    hunter_player = get_player(hunter_id)

    # Convert the target player into an "enemy" object for the battle engine
    enemy_data = {
        "name": f"{target_player['name']} (Bounty)",
        "emoji": "🎯",
        "hp": target_player["max_hp"],
        "atk": target_player["str_stat"],
        "threat": "💀 BOUNTY TARGET",
        "xp": 0,
        "yen": 0,
        "drops": [],
        "faction_type": target_player["faction"],
        "event_key": "bounty",
        "event_label": "🎯 ASSASSINATION TARGET",
        "is_elite": True,
        "is_boss": False
    }

    # Set up the battle state using existing combat engine tools
    from utils.database import set_battle_state, clear_battle_log
    set_battle_state(hunter_id, enemy_data, in_combat=True)
    clear_battle_log(hunter_id)

    # Consume the loadout items from the hunter's inventory
    from utils.database import remove_item
    for item in hunt["loadout"]:
        remove_item(hunter_id, item, 1)

    # We will track this is a bounty fight and store the target_id
    context.user_data[f"bounty_target_{hunter_id}"] = hunt["target_id"]

    from handlers.explore import build_combat_keyboard
    from utils.helpers import combat_status
    import logging

    col("bounty_hunts").update_one(
        {"hunter_id": hunter_id},
        {"$set": {"status": "active"}}
    )

    state = col("battle_state").find_one({"user_id": hunter_id, "active": 1})

    text = combat_status(hunter_player, state, None, log_lines=[f"🎯 Target Acquired: {target_player['name']}"], turn=1)

    markup = build_combat_keyboard(has_ally=False)

    await _safe_edit(query, text, reply_markup=markup, parse_mode="Markdown")


async def bountyshop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View the bounty shop."""
    user = update.effective_user
    player = get_player(user.id)
    if not player:
        return await update.message.reply_text("❌ Start the game first.")

    bounty_marks = player.get("bounty_marks", 0)

    # Initialize standard stock if it doesn't exist
    items = list(col("bounty_shop").find())
    if not items:
        default_items = [
            {"name": "Assassin's Blade", "price": 10000, "type": "sword"},
            {"name": "Vampiric Cloak", "price": 10000, "type": "armor"},
            {"name": "Moon Breathing Scroll", "price": 25000, "type": "item"},
            {"name": "Shadow Demon Art", "price": 25000, "type": "item"},
            {"name": "Permanent HP Elixir", "price": 50000, "type": "item"},
        ]
        col("bounty_shop").insert_many(default_items)
        items = list(col("bounty_shop").find())

    text = (
        f"🌑 *THE UNDERGROUND BOUNTY SHOP* 🌑\n"
        f"Your Marks: 💰 *{bounty_marks:,}*\n\n"
        f"Spend your hard-earned Bounty Marks here for exclusive gear.\n\n"
    )

    keyboard = []
    for item in items:
        name = item["name"]
        price = item["price"]
        text += f"▪️ *{name}* — 💰 {price:,} Marks\n"
        keyboard.append([InlineKeyboardButton(f"Buy {name} (💰 {price:,})", callback_data=f"bb_buy|{str(item['_id'])}")])

    markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

async def bountyshop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id

    if data.startswith("bb_buy|"):
        item_id = data.split("|")[1]
        from bson.objectid import ObjectId
        try:
            item = col("bounty_shop").find_one({"_id": ObjectId(item_id)})
        except Exception:
            item = None

        if not item:
            await query.answer("Item not found.", show_alert=True)
            return

        player = get_player(user_id)
        if player.get("bounty_marks", 0) < item["price"]:
            await query.answer("You don't have enough Bounty Marks!", show_alert=True)
            return

        # Deduct cost and add item
        update_player(user_id, bounty_marks=player["bounty_marks"] - item["price"])
        from utils.database import add_item
        add_item(user_id, item["name"], item["type"], 1)

        await query.answer(f"Successfully bought {item['name']}!")
        await _safe_edit(query, f"✅ You purchased *{item['name']}* for {item['price']:,} Bounty Marks.", parse_mode="Markdown")


from utils.guards import owner_only

@owner_only
async def addbountyitem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner command to add item to bounty shop. Usage: /addbountyitem [type] [price] [name]"""
    args = context.args
    if len(args) < 3:
        await update.message.reply_text("Usage: /addbountyitem [type] [price] [name]\nTypes: item, material, sword, armor")
        return

    item_type = args[0].lower()
    try:
        price = int(args[1])
    except ValueError:
        return await update.message.reply_text("Price must be a number.")

    name = " ".join(args[2:])

    col("bounty_shop").insert_one({
        "name": name,
        "price": price,
        "type": item_type
    })

    await update.message.reply_text(f"✅ Added {name} to bounty shop for {price} marks.")

@owner_only
async def removebountyitem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Owner command to remove item from bounty shop. Usage: /removebountyitem [name]"""
    name = " ".join(context.args)
    if not name:
        return await update.message.reply_text("Usage: /removebountyitem [name]")

    res = col("bounty_shop").delete_one({"name": {"$regex": f"^{name}$", "$options": "i"}})
    if res.deleted_count > 0:
        await update.message.reply_text(f"✅ Removed {name} from bounty shop.")
    else:
        await update.message.reply_text(f"❌ Item {name} not found in bounty shop.")
