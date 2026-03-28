"""
/upgrade - Player command to craft stronger gear from rare materials.
Admin can enable or disable it via /upgradetoggle.
"""
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import (
    add_item,
    col,
    get_inventory,
    get_player,
    remove_item,
    update_player,
)
from utils.guards import dm_only


UPGRADE_RECIPES = {
    "Crimson Nichirin Blade": {
        "slot": "sword",
        "materials": {"Demon Blood": 5, "Wolf Fang": 3},
        "cost_yen": 500,
        "replaces": "Basic Nichirin Blade",
        "desc": "Blood-forged starter blade with a permanent STR boost.",
    },
    "Jet Black Nichirin Blade": {
        "slot": "sword",
        "materials": {"Blood Crystal": 3, "Boss Shard": 1, "Demon Blood": 10},
        "cost_yen": 2000,
        "replaces": "Crimson Nichirin Blade",
        "desc": "Mid-tier forged blade powered by Boss Shards.",
    },
    "Scarlet Crimson Blade": {
        "slot": "sword",
        "materials": {
            "Blood Crystal": 5,
            "Boss Shard": 2,
            "Hashira Badge": 1,
            "Ancient Whetstone": 1,
        },
        "cost_yen": 8000,
        "replaces": "Jet Black Nichirin Blade",
        "desc": "Hashira-forged crimson edge with a large STR jump.",
    },
    "Transparent Nichirin Blade": {
        "slot": "sword",
        "materials": {
            "Rare Ore Fragment": 2,
            "Boss Shard": 3,
            "Titan Core": 1,
            "Ancient Whetstone": 1,
        },
        "cost_yen": 20000,
        "replaces": "Scarlet Crimson Blade",
        "desc": "Rare ore fusion blade tuned for late-game sword growth.",
    },
    "Sun Nichirin Blade": {
        "slot": "sword",
        "materials": {
            "Sun Breathing Tome": 1,
            "Boss Shard": 5,
            "King Blade": 1,
            "Rengoku Shard": 1,
        },
        "cost_yen": 60000,
        "replaces": "Transparent Nichirin Blade",
        "desc": "Endgame Sun blade forged with the Sun Breathing Tome.",
    },
    "Reinforced Haori": {
        "slot": "armor",
        "materials": {"Spider Silk": 3, "Demon Blood": 5},
        "cost_yen": 400,
        "replaces": "Corps Uniform",
        "desc": "Silk-reinforced armor with solid DEF and HP growth.",
    },
    "Hashira Haori": {
        "slot": "armor",
        "materials": {"Boss Shard": 2, "Spider Silk": 5, "Blood Crystal": 2},
        "cost_yen": 1500,
        "replaces": "Reinforced Haori",
        "desc": "Hashira-grade protection built around Boss Shards.",
    },
    "Demon Slayer Uniform EX": {
        "slot": "armor",
        "materials": {
            "Boss Shard": 3,
            "Blood Crystal": 4,
            "Titan Core": 1,
            "Rare Ore Fragment": 1,
        },
        "cost_yen": 7000,
        "replaces": "Hashira Haori",
        "desc": "Enhanced corps armor with heavier permanent bulk.",
    },
    "Flame Haori": {
        "slot": "armor",
        "materials": {
            "Boss Shard": 4,
            "Flame Core": 1,
            "Hashira Badge": 1,
            "Ancient Whetstone": 1,
        },
        "cost_yen": 18000,
        "replaces": "Demon Slayer Uniform EX",
        "desc": "High-rank armor woven with flame-core protection.",
    },
    "Yoriichi Haori": {
        "slot": "armor",
        "materials": {
            "Sun Breathing Tome": 1,
            "Boss Shard": 5,
            "Rengoku Shard": 1,
            "Hashira Badge": 2,
        },
        "cost_yen": 50000,
        "replaces": "Flame Haori",
        "desc": "Top-tier haori infused with Sun Breathing knowledge.",
    },
}


STAT_BOOSTS = {
    "Crimson Nichirin Blade": {"str_stat": 8},
    "Jet Black Nichirin Blade": {"str_stat": 18},
    "Scarlet Crimson Blade": {"str_stat": 30},
    "Transparent Nichirin Blade": {"str_stat": 50},
    "Sun Nichirin Blade": {"str_stat": 80},
    "Reinforced Haori": {"def_stat": 5, "max_hp": 20},
    "Hashira Haori": {"def_stat": 12, "max_hp": 40},
    "Demon Slayer Uniform EX": {"def_stat": 20, "max_hp": 60},
    "Flame Haori": {"def_stat": 32, "max_hp": 100},
    "Yoriichi Haori": {"def_stat": 50, "max_hp": 150},
}


def _slot_field(slot: str) -> str:
    return "equipped_sword" if slot == "sword" else "equipped_armor"


def _equipped_item(player: dict, slot: str) -> str:
    return player.get(_slot_field(slot), "")


def _find_recipe(name: str):
    query = name.strip().lower()
    exact = next((item for item in UPGRADE_RECIPES if item.lower() == query), None)
    if exact:
        return exact, UPGRADE_RECIPES[exact]

    partial = next((item for item in UPGRADE_RECIPES if query in item.lower()), None)
    if partial:
        return partial, UPGRADE_RECIPES[partial]

    return None, None


def _missing_materials(inv_map: dict, recipe: dict) -> dict:
    return {
        mat: (inv_map.get(mat, 0), qty)
        for mat, qty in recipe["materials"].items()
        if inv_map.get(mat, 0) < qty
    }


def _has_required_base(player: dict, recipe: dict) -> bool:
    return _equipped_item(player, recipe["slot"]) == recipe["replaces"]


def _ready_for_upgrade(player: dict, inv_map: dict, recipe: dict) -> bool:
    return (
        _has_required_base(player, recipe)
        and player.get("yen", 0) >= recipe["cost_yen"]
        and not _missing_materials(inv_map, recipe)
    )


def _boost_summary(item_name: str) -> str:
    labels = {
        "str_stat": "STR",
        "def_stat": "DEF",
        "max_hp": "Max HP",
        "max_sta": "Max STA",
        "spd": "SPD",
    }
    boosts = STAT_BOOSTS.get(item_name, {})
    if not boosts:
        return "No stat boost"
    return ", ".join(f"+{value} {labels.get(stat, stat)}" for stat, value in boosts.items())


def is_upgrade_enabled():
    doc = col("settings").find_one({"key": "upgrade_enabled"})
    return doc.get("value", True) if doc else True


@dm_only
async def upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("No character found.")
        return

    if not is_upgrade_enabled():
        await update.message.reply_text(
            "*Upgrade system is currently disabled.*\n_Check back later!_",
            parse_mode="Markdown",
        )
        return

    inv_map = {item["item_name"]: item["quantity"] for item in get_inventory(user_id)}

    if not context.args:
        lines = [
            "*UPGRADE FORGE*",
            f"Balance: *{player['yen']:,} Yen*",
            f"Sword: *{player.get('equipped_sword', 'None')}*",
            f"Armor: *{player.get('equipped_armor', 'None')}*",
            "---------------------",
        ]

        buttons = []
        current_slot = None
        for result, recipe in UPGRADE_RECIPES.items():
            if recipe["slot"] != current_slot:
                current_slot = recipe["slot"]
                lines.append("")
                lines.append("*SWORD PATH*" if current_slot == "sword" else "*ARMOR PATH*")

            has_base = _has_required_base(player, recipe)
            has_yen = player["yen"] >= recipe["cost_yen"]
            missing = _missing_materials(inv_map, recipe)
            ready = _ready_for_upgrade(player, inv_map, recipe)

            status = "READY" if ready else "NEEDS BASE" if not has_base else "LOCKED"
            lines.append(f"{status} *{result}*")
            lines.append(f"  _{recipe['desc']}_")
            lines.append(f"  Replaces: _{recipe['replaces']}_")
            lines.append(f"  Cost: *{recipe['cost_yen']:,} Yen*")
            lines.append(f"  Bonus: _{_boost_summary(result)}_")
            if not has_base:
                lines.append(f"  Equip *{recipe['replaces']}* first.")
            elif not has_yen:
                lines.append(f"  Need *{recipe['cost_yen'] - player['yen']:,}* more Yen.")

            for mat, qty in recipe["materials"].items():
                have = inv_map.get(mat, 0)
                marker = "OK" if have >= qty else "NO"
                lines.append(f"  {marker} {mat}: {have}/{qty}")
            lines.append("")

            if ready:
                buttons.append(
                    [InlineKeyboardButton(f"Upgrade -> {result}", callback_data=f"upgrade_confirm_{result.replace(' ', '_')}")]
                )

        lines.append("---------------------")
        if not buttons:
            lines.append("_Collect more drops and equip the required base gear to upgrade._")
        else:
            lines.append("_Tap a button below to forge an available upgrade._")

        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(buttons) if buttons else None,
        )
        return

    item_name, recipe = _find_recipe(" ".join(context.args))
    if not recipe:
        await update.message.reply_text(
            f"No upgrade recipe for *{' '.join(context.args)}*.",
            parse_mode="Markdown",
        )
        return

    await _do_upgrade(update.message, user_id, player, item_name, recipe, inv_map)


async def upgrade_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    item_name = query.data.replace("upgrade_confirm_", "").replace("_", " ")
    player = get_player(user_id)
    recipe = UPGRADE_RECIPES.get(item_name)
    if not recipe or not player:
        await query.answer("Recipe not found.", show_alert=True)
        return

    inv_map = {item["item_name"]: item["quantity"] for item in get_inventory(user_id)}
    await _do_upgrade(query.message, user_id, player, item_name, recipe, inv_map)


async def _do_upgrade(msg, user_id: int, player: dict, item_name: str, recipe: dict, inv_map: dict):
    if not is_upgrade_enabled():
        await msg.reply_text("Upgrades are disabled.")
        return

    if not _has_required_base(player, recipe):
        slot_label = "sword" if recipe["slot"] == "sword" else "armor"
        equipped = _equipped_item(player, recipe["slot"]) or "None"
        await msg.reply_text(
            f"Equip *{recipe['replaces']}* first.\n"
            f"Current {slot_label}: *{equipped}*",
            parse_mode="Markdown",
        )
        return

    missing = _missing_materials(inv_map, recipe)
    if missing:
        await msg.reply_text(
            f"*Missing materials for {item_name}:*\n"
            + "\n".join(f"  {mat}: {have}/{need}" for mat, (have, need) in missing.items()),
            parse_mode="Markdown",
        )
        return

    if player["yen"] < recipe["cost_yen"]:
        await msg.reply_text(
            f"Need *{recipe['cost_yen']:,} Yen* but you have *{player['yen']:,} Yen*",
            parse_mode="Markdown",
        )
        return

    for mat, qty in recipe["materials"].items():
        remove_item(user_id, mat, qty)
    remove_item(user_id, recipe["replaces"], 1)
    add_item(user_id, item_name, recipe["slot"], 1)
    update_player(user_id, yen=player["yen"] - recipe["cost_yen"])

    boosts = STAT_BOOSTS.get(item_name, {})
    fresh = get_player(user_id)
    if fresh:
        updates = {_slot_field(recipe["slot"]): item_name}
        for stat, delta in boosts.items():
            updates[stat] = fresh.get(stat, 0) + delta
        if "max_hp" in boosts:
            new_max_hp = updates.get("max_hp", fresh.get("max_hp", 0))
            updates["hp"] = min(new_max_hp, fresh.get("hp", 0) + boosts["max_hp"])
        if "max_sta" in boosts:
            new_max_sta = updates.get("max_sta", fresh.get("max_sta", 0))
            updates["sta"] = min(new_max_sta, fresh.get("sta", 0) + boosts["max_sta"])
        update_player(user_id, **updates)
    else:
        update_player(user_id, **{_slot_field(recipe["slot"]): item_name})

    mat_list = ", ".join(f"{qty}x {mat}" for mat, qty in recipe["materials"].items())
    await msg.reply_text(
        f"*UPGRADE COMPLETE!*\n\n"
        f"*{item_name}*\n"
        f"_{recipe['desc']}_\n\n"
        f"Materials used: _{mat_list}_\n"
        f"Cost: *{recipe['cost_yen']:,} Yen*\n"
        f"Stats: *{_boost_summary(item_name)}*\n"
        f"Now equipped automatically.",
        parse_mode="Markdown",
    )


async def upgradetoggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from handlers.admin import has_admin_access

    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("Admin only.")
        return

    current = is_upgrade_enabled()
    new_val = not current
    col("settings").update_one(
        {"key": "upgrade_enabled"},
        {"$set": {"key": "upgrade_enabled", "value": new_val}},
        upsert=True,
    )
    status = "ENABLED" if new_val else "DISABLED"
    await update.message.reply_text(f"Upgrade system: *{status}*", parse_mode="Markdown")
