"""
handlers/pets.py — Full Pet System for Demon Slayer RPG Bot

Commands:
  /pets           — View your stable (Pokédex)
  /pet <name>     — Activate pet + view stats
  /hatchegg       — Hatch an egg from inventory
  /feedpet        — Feed active pet (uses Pet Food)
  /petbattle @u   — Challenge someone's active pet
  /releasepet <n> — Release a pet
  /petskill       — Use active pet's skill in battle

Wild encounter callbacks: pet_catch_<uid>, pet_flee_<uid>
"""
import random
import json
from datetime import date

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import (
    get_player, update_player, col, add_item
)
from utils.guards import owner_only_button, no_button_spam

# ── Pet data imports ───────────────────────────────────────────────────────
from config import (
    PETS, PET_EVOLUTIONS, PET_EGGS, PET_BOND_NAMES, PET_BOND_XP,
    PET_RARITY_EMOJI, PET_IMAGES,
    PET_WILD_ENCOUNTER_CHANCE, PET_EGG_DROP,
)

# ══════════════════════════════════════════════════════════════════════════
# DATABASE HELPERS
# ══════════════════════════════════════════════════════════════════════════

def get_pet_stable(user_id: int) -> list:
    """Return list of all owned pet docs for this user."""
    return list(col("pets").find({"user_id": user_id}, {"_id": 0}))


def get_pet(user_id: int, pet_name: str) -> dict | None:
    """Return a specific pet doc (case-insensitive match)."""
    return col("pets").find_one(
        {"user_id": user_id, "name": {"$regex": f"^{pet_name}$", "$options": "i"}},
        {"_id": 0}
    )


def get_active_pet(user_id: int) -> dict | None:
    """Return the currently active pet doc, or None."""
    return col("pets").find_one(
        {"user_id": user_id, "active": True},
        {"_id": 0}
    )


def add_pet(user_id: int, pet_name: str) -> bool:
    """
    Add a pet to the stable. Returns False if already owned (adds bond XP instead).
    """
    existing = col("pets").find_one({"user_id": user_id, "name": pet_name})
    if existing:
        # Duplicate — give +20 bond XP as consolation
        col("pets").update_one(
            {"user_id": user_id, "name": pet_name},
            {"$inc": {"bond_xp": 20}}
        )
        return False
    col("pets").insert_one({
        "user_id":    user_id,
        "name":       pet_name,
        "bond_xp":    0,
        "bond_level": 0,
        "active":     False,
        "skill_used": False,   # reset each battle
    })
    return True


def set_active_pet(user_id: int, pet_name: str):
    """Deactivate all pets then activate the chosen one."""
    col("pets").update_many({"user_id": user_id}, {"$set": {"active": False}})
    col("pets").update_one(
        {"user_id": user_id, "name": pet_name},
        {"$set": {"active": True}}
    )


def add_pet_bond_xp(user_id: int, pet_name: str, xp: int) -> dict:
    """Add bond XP and level up if threshold reached. Returns updated pet doc."""
    pet = col("pets").find_one({"user_id": user_id, "name": pet_name})
    if not pet:
        return {}
    new_xp = pet["bond_xp"] + xp
    new_level = pet["bond_level"]
    while new_level < 4 and new_xp >= PET_BOND_XP[new_level + 1]:
        new_level += 1
    col("pets").update_one(
        {"user_id": user_id, "name": pet_name},
        {"$set": {"bond_xp": new_xp, "bond_level": new_level}}
    )
    return col("pets").find_one({"user_id": user_id, "name": pet_name}, {"_id": 0})


def evolve_pet(user_id: int, pet_name: str) -> str | None:
    """Evolve pet at bond 4 (Soulbound). Returns evolved name or None."""
    data = PETS.get(pet_name)
    if not data:
        return None
    evo_name = data.get("evolution")
    if not evo_name:
        return None
    pet = col("pets").find_one({"user_id": user_id, "name": pet_name})
    if not pet or pet["bond_level"] < 4:
        return None
    was_active = pet.get("active", False)
    col("pets").delete_one({"user_id": user_id, "name": pet_name})
    col("pets").insert_one({
        "user_id":    user_id,
        "name":       evo_name,
        "bond_xp":    pet["bond_xp"],
        "bond_level": 4,
        "active":     was_active,
        "skill_used": False,
        "evolved":    True,
    })
    return evo_name


# ══════════════════════════════════════════════════════════════════════════
# PASSIVE BONUS HELPERS  (called from explore.py / challenge.py)
# ══════════════════════════════════════════════════════════════════════════

def get_pet_passives(user_id: int) -> dict:
    """
    Return combined passive bonus dict from active pet (scaled by bond level).
    Keys: xp_pct, yen_pct, drop_pct, atk_pct, def_pct, hp_pct, dodge_pct
    """
    pet = get_active_pet(user_id)
    if not pet:
        return {}

    name = pet["name"]
    # Check evolved first
    if name in PET_EVOLUTIONS:
        raw = PET_EVOLUTIONS[name].get("passive", {})
        scale = 1.0   # evolutions have flat bonuses already boosted
    elif name in PETS:
        raw = PETS[name].get("passive", {})
        level = pet.get("bond_level", 0)
        scale = PETS[name]["bond_scale"][level]
    else:
        return {}

    return {k: v * scale for k, v in raw.items()}


def apply_pet_passives_to_rewards(user_id: int, xp: int, yen: int) -> tuple[int, int]:
    """Scale XP and Yen rewards by active pet passive bonuses."""
    p = get_pet_passives(user_id)
    if p.get("xp_pct"):
        xp = int(xp * (1 + p["xp_pct"]))
    if p.get("yen_pct"):
        yen = int(yen * (1 + p["yen_pct"]))
    return xp, yen


def get_pet_drop_bonus(user_id: int) -> float:
    """Return drop rate bonus (0.0–1.0) from active pet."""
    return get_pet_passives(user_id).get("drop_pct", 0.0)


def get_pet_atk_bonus(user_id: int) -> float:
    return get_pet_passives(user_id).get("atk_pct", 0.0)


def get_pet_def_bonus(user_id: int) -> float:
    return get_pet_passives(user_id).get("def_pct", 0.0)


def get_pet_hp_bonus(user_id: int) -> float:
    return get_pet_passives(user_id).get("hp_pct", 0.0)


def get_pet_dodge_bonus(user_id: int) -> float:
    return get_pet_passives(user_id).get("dodge_pct", 0.0)


# ══════════════════════════════════════════════════════════════════════════
# WILD ENCOUNTER SYSTEM
# ══════════════════════════════════════════════════════════════════════════

def roll_wild_pet_encounter() -> str | None:
    """
    Roll whether a wild pet appears. Returns pet name or None.
    Weighted by catch_rate (rarer pets appear less).
    """
    if random.random() > PET_WILD_ENCOUNTER_CHANCE:
        return None
    # Weight by rarity: common=4, uncommon=3, rare=2, epic=1, legendary=0.3
    rarity_weight = {"common": 4, "uncommon": 3, "rare": 2, "epic": 1, "legendary": 0.3}
    pool = [(name, rarity_weight.get(d["rarity"], 1)) for name, d in PETS.items()]
    names, weights = zip(*pool)
    return random.choices(names, weights=weights, k=1)[0]


def roll_egg_drop() -> str | None:
    """Roll whether an enemy drops an egg. Returns egg name or None."""
    r = random.random()
    if r < PET_EGG_DROP["Legendary Egg"]:
        return "Legendary Egg"
    if r < PET_EGG_DROP["Rare Egg"]:
        return "Rare Egg"
    if r < PET_EGG_DROP["Basic Egg"]:
        return "Basic Egg"
    return None


async def trigger_wild_encounter(update_or_query, user_id: int, context, pet_name: str):
    """
    Send wild pet encounter message with Catch/Flee buttons.
    Stores pet_name in context.user_data for callback.
    """
    data = PETS[pet_name]
    rarity_e = PET_RARITY_EMOJI[data["rarity"]]
    img_url = PET_IMAGES.get(pet_name, "")

    context.user_data[f"wild_pet_{user_id}"] = pet_name

    text = (
        f"🌿 *A WILD PET APPEARS!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{data['emoji']}  *{pet_name}*  {rarity_e} {data['rarity'].upper()}\n\n"
        f"_{data['desc']}_\n\n"
        f"🎯 Catch rate: *{int(data['catch_rate']*100)}%*\n"
        f"🪤 Needs: *Pet Trap* in inventory\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Act fast before it escapes!"
    )

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🪤 Catch!", callback_data=f"pet_catch_{user_id}"),
            InlineKeyboardButton("🏃 Flee",   callback_data=f"pet_flee_{user_id}"),
        ]
    ])

    send = getattr(update_or_query, "message", None) or update_or_query
    if img_url:
        try:
            await send.reply_photo(photo=img_url, caption=text, parse_mode="Markdown", reply_markup=kb)
            return
        except Exception:
            pass
    await send.reply_text(text, parse_mode="Markdown", reply_markup=kb)


@owner_only_button
@no_button_spam
async def pet_catch_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle catch attempt button."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    pet_name = context.user_data.pop(f"wild_pet_{user_id}", None)

    if not pet_name:
        await query.edit_message_text("❌ The pet already escaped!")
        return

    player = get_player(user_id)
    if not player:
        return

    # Check for Pet Trap in inventory
    trap = col("inventory").find_one(
        {"user_id": user_id, "item_name": {"$regex": "^Pet Trap$", "$options": "i"}}
    )
    if not trap or trap.get("quantity", 0) < 1:
        await query.edit_message_text(
            f"❌ You don't have a *Pet Trap*!\n"
            f"Buy one from the shop and come back.\n\n"
            f"_{pet_name} escaped..._",
            parse_mode="Markdown"
        )
        return

    # Consume trap
    if trap["quantity"] <= 1:
        col("inventory").delete_one({"_id": trap["_id"]})
    else:
        col("inventory").update_one({"_id": trap["_id"]}, {"$inc": {"quantity": -1}})

    data = PETS[pet_name]
    caught = random.random() < data["catch_rate"]

    if caught:
        is_new = add_pet(user_id, pet_name)
        rarity_e = PET_RARITY_EMOJI[data["rarity"]]
        if is_new:
            msg = (
                f"🎉 *CAUGHT!*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"{data['emoji']}  *{pet_name}*  {rarity_e}\n"
                f"_{data['desc']}_\n\n"
                f"✅ Added to your stable!\n"
                f"Use `/pet {pet_name}` to activate it."
            )
        else:
            msg = (
                f"📚 You already own *{pet_name}*!\n"
                f"It struggled free — but left behind bond energy.\n"
                f"💠 *+20 Bond XP* added to your existing pet!"
            )
    else:
        msg = (
            f"💨 *{pet_name} escaped!*\n"
            f"The trap snapped shut but it was too quick.\n"
            f"_(Pet Trap consumed)_"
        )

    await query.edit_message_text(msg, parse_mode="Markdown")


@owner_only_button
async def pet_flee_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle flee button — dismiss wild encounter."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    pet_name = context.user_data.pop(f"wild_pet_{user_id}", None)
    name = pet_name or "The wild pet"
    await query.edit_message_text(f"🏃 You fled from {name}.")


# ══════════════════════════════════════════════════════════════════════════
# /pets — STABLE VIEW
# ══════════════════════════════════════════════════════════════════════════

async def pets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pets — View your full pet stable."""
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character. Use /start.")
        return

    stable = get_pet_stable(user_id)
    if not stable:
        await update.message.reply_text(
            "🐾 *Your stable is empty!*\n\n"
            "Pets can be:\n"
            "• 🥚 Hatched from eggs (found while exploring)\n"
            "• 🪤 Caught wild during explore\n\n"
            "Get a *Pet Trap* from the shop to start catching!",
            parse_mode="Markdown"
        )
        return

    lines = [f"🐾 *{player['name']}'s Pet Stable* ({len(stable)}/10)\n━━━━━━━━━━━━━━━━━━━━━"]
    for p in stable:
        name = p["name"]
        # Get pet data (check evolutions first)
        if name in PET_EVOLUTIONS:
            d = {"rarity": PETS[PET_EVOLUTIONS[name]["base"]]["rarity"],
                 "emoji": PET_EVOLUTIONS[name]["emoji"]}
        else:
            d = PETS.get(name, {"rarity": "common", "emoji": "🐾"})

        rarity_e = PET_RARITY_EMOJI[d["rarity"]]
        bond_name = PET_BOND_NAMES[p["bond_level"]]
        active_tag = " ✅ *ACTIVE*" if p.get("active") else ""
        lines.append(
            f"{d['emoji']} *{name}* {rarity_e}{active_tag}\n"
            f"   ❤️ Bond: *{bond_name}* (Lv{p['bond_level']+1}) | XP: {p['bond_xp']}"
        )

    lines.append(
        f"\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"Commands:\n"
        f"`/pet <name>` — Activate & view stats\n"
        f"`/feedpet` — Feed active pet\n"
        f"`/hatchegg` — Hatch an egg\n"
        f"`/petbattle @user` — Pet duel"
    )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════
# /pet <name> — ACTIVATE + STATS
# ══════════════════════════════════════════════════════════════════════════

async def pet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/pet <name> — Activate a pet and view its stats."""
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    if not context.args:
        active = get_active_pet(user_id)
        if active:
            await _show_pet_stats(update, user_id, active["name"])
        else:
            await update.message.reply_text(
                "Usage: `/pet <name>` — activate and view a pet's stats.\n"
                "Use `/pets` to see your stable.",
                parse_mode="Markdown"
            )
        return

    pet_name = " ".join(context.args)
    owned = get_pet(user_id, pet_name)
    if not owned:
        await update.message.reply_text(
            f"❌ You don't own a pet called *{pet_name}*.\n"
            f"Use `/pets` to see your stable.",
            parse_mode="Markdown"
        )
        return

    # Activate it
    set_active_pet(user_id, owned["name"])
    await _show_pet_stats(update, user_id, owned["name"])


async def _show_pet_stats(update: Update, user_id: int, pet_name: str):
    """Display full pet stat card, optionally with image."""
    pet_doc = get_pet(user_id, pet_name)
    if not pet_doc:
        return

    is_evolved = pet_name in PET_EVOLUTIONS
    if is_evolved:
        evo_data = PET_EVOLUTIONS[pet_name]
        base_data = PETS[evo_data["base"]]
        raw_passive = evo_data.get("passive", {})
        emoji = evo_data["emoji"]
        skill_name = base_data.get("skill")
        skill_desc = base_data.get("skill_desc", "")
        rarity = base_data["rarity"]
        desc = f"✨ Evolved form of {evo_data['base']}"
        scale = 1.0
    elif pet_name in PETS:
        base_data = PETS[pet_name]
        raw_passive = base_data.get("passive", {})
        emoji = base_data["emoji"]
        skill_name = base_data.get("skill")
        skill_desc = base_data.get("skill_desc", "")
        rarity = base_data["rarity"]
        desc = base_data["desc"]
        scale = base_data["bond_scale"][pet_doc["bond_level"]]
    else:
        await update.message.reply_text("❌ Pet data not found.")
        return

    bond_level = pet_doc["bond_level"]
    bond_name  = PET_BOND_NAMES[bond_level]
    bond_xp    = pet_doc["bond_xp"]
    next_xp    = PET_BOND_XP[bond_level + 1] if bond_level < 4 else "MAX"
    rarity_e   = PET_RARITY_EMOJI[rarity]
    active_tag = "✅ ACTIVE" if pet_doc.get("active") else "💤 Inactive"

    # Bond bar
    if bond_level < 4:
        progress = min(bond_xp, next_xp) / next_xp
    else:
        progress = 1.0
    bar_len = 10
    filled = int(progress * bar_len)
    bond_bar = "❤️" * filled + "░" * (bar_len - filled)

    # Scaled passives
    passive_lines = []
    for k, v in raw_passive.items():
        scaled = v * scale
        label = {
            "xp_pct": "⭐ XP Bonus", "yen_pct": "💰 Yen Bonus",
            "drop_pct": "🎁 Drop Rate", "atk_pct": "💪 ATK",
            "def_pct": "🛡️ DEF", "hp_pct": "❤️ Max HP",
            "dodge_pct": "🎯 Dodge",
        }.get(k, k)
        passive_lines.append(f"  {label}: *+{int(scaled*100)}%*")

    evo_hint = ""
    if not is_evolved and bond_level >= 4:
        evo_hint = f"\n✨ *Ready to evolve!* Use `/feedpet evolve`"
    elif not is_evolved:
        evo_hint = f"\n_(Evolves at Soulbound + Spirit Crystal)_"

    text = (
        f"{emoji} *{pet_name}*  {rarity_e} {rarity.upper()}\n"
        f"_{desc}_\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"❤️ Bond: *{bond_name}* (Lv{bond_level+1}/5)\n"
        f"{bond_bar}\n"
        f"XP: {bond_xp}/{next_xp}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 *Skill:* {skill_name or 'None'}\n"
        f"{('_' + skill_desc + '_') if skill_desc else ''}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 *Passives:*\n"
        + "\n".join(passive_lines) +
        f"\n━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ Status: *{active_tag}*"
        + evo_hint
    )

    img_url = PET_IMAGES.get(pet_name, "")
    if img_url:
        try:
            await update.message.reply_photo(photo=img_url, caption=text, parse_mode="Markdown")
            return
        except Exception:
            pass
    await update.message.reply_text(text, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════
# /hatchegg — HATCH AN EGG
# ══════════════════════════════════════════════════════════════════════════

async def hatchegg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/hatchegg — Hatch the first available egg in inventory."""
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return

    # Find an egg in inventory (prefer higher tier)
    egg_found = None
    for egg_name in ["Legendary Egg", "Rare Egg", "Basic Egg"]:
        doc = col("inventory").find_one(
            {"user_id": user_id, "item_name": {"$regex": f"^{egg_name}$", "$options": "i"}}
        )
        if doc and doc.get("quantity", 0) > 0:
            egg_found = (egg_name, doc)
            break

    if not egg_found:
        await update.message.reply_text(
            "❌ No eggs in inventory!\n\n"
            "🥚 Eggs drop from enemies while exploring.\n"
            "Keep exploring to find one!",
            parse_mode="Markdown"
        )
        return

    egg_name, egg_doc = egg_found
    egg_data = PET_EGGS[egg_name]

    # Consume egg
    if egg_doc["quantity"] <= 1:
        col("inventory").delete_one({"_id": egg_doc["_id"]})
    else:
        col("inventory").update_one({"_id": egg_doc["_id"]}, {"$inc": {"quantity": -1}})

    # Roll pet
    pet_name = random.choices(egg_data["pool"], weights=egg_data["weights"], k=1)[0]
    is_new = add_pet(user_id, pet_name)
    pet_data = PETS[pet_name]
    rarity_e = PET_RARITY_EMOJI[pet_data["rarity"]]

    hatch_text = (
        f"🥚 *Hatching {egg_name}...*\n\n"
        f"💥 *CRACK!*\n\n"
        f"{pet_data['emoji']} *{pet_name}* hatched!  {rarity_e} {pet_data['rarity'].upper()}\n"
        f"_{pet_data['desc']}_\n\n"
    )

    if is_new:
        hatch_text += f"✅ *Added to your stable!*\nUse `/pet {pet_name}` to activate."
    else:
        hatch_text += f"📚 You already own *{pet_name}*!\n💠 *+20 Bond XP* added instead."

    img_url = PET_IMAGES.get(pet_name, "")
    if img_url:
        try:
            await update.message.reply_photo(photo=img_url, caption=hatch_text, parse_mode="Markdown")
            return
        except Exception:
            pass
    await update.message.reply_text(hatch_text, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════
# /feedpet — FEED ACTIVE PET
# ══════════════════════════════════════════════════════════════════════════

async def feedpet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/feedpet [evolve] — Feed active pet or trigger evolution."""
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        return

    active = get_active_pet(user_id)
    if not active:
        await update.message.reply_text(
            "❌ No active pet! Use `/pet <name>` to activate one.",
            parse_mode="Markdown"
        )
        return

    pet_name = active["name"]
    args = context.args or []

    # Evolution attempt
    if args and args[0].lower() == "evolve":
        if active["bond_level"] < 4:
            await update.message.reply_text(
                f"❌ *{pet_name}* needs to be *Soulbound* (Bond Lv5) to evolve.\n"
                f"Current: *{PET_BOND_NAMES[active['bond_level']]}*",
                parse_mode="Markdown"
            )
            return
        # Check Spirit Crystal
        crystal = col("inventory").find_one(
            {"user_id": user_id, "item_name": {"$regex": "^Spirit Crystal$", "$options": "i"}}
        )
        if not crystal or crystal.get("quantity", 0) < 1:
            await update.message.reply_text(
                f"❌ You need a *Spirit Crystal* to evolve *{pet_name}*!\n"
                f"Find one from rare enemy drops or the Black Market.",
                parse_mode="Markdown"
            )
            return
        # Consume crystal
        if crystal["quantity"] <= 1:
            col("inventory").delete_one({"_id": crystal["_id"]})
        else:
            col("inventory").update_one({"_id": crystal["_id"]}, {"$inc": {"quantity": -1}})

        evo_name = evolve_pet(user_id, pet_name)
        if not evo_name:
            await update.message.reply_text("❌ This pet cannot evolve.")
            return

        evo_data = PET_EVOLUTIONS[evo_name]
        await update.message.reply_text(
            f"✨ *EVOLUTION!*\n\n"
            f"{evo_data['emoji']} *{pet_name}* evolved into *{evo_name}*!\n\n"
            f"All passives boosted. Use `/pet {evo_name}` to view stats.",
            parse_mode="Markdown"
        )
        return

    # Regular feeding with Pet Food
    food = col("inventory").find_one(
        {"user_id": user_id, "item_name": {"$regex": "^Pet Food$", "$options": "i"}}
    )
    if not food or food.get("quantity", 0) < 1:
        await update.message.reply_text(
            f"❌ No *Pet Food* in inventory!\n"
            f"Buy it from the shop or find it exploring.\n\n"
            f"Active pet: {PETS.get(pet_name, {}).get('emoji', '🐾')} *{pet_name}*",
            parse_mode="Markdown"
        )
        return

    # Consume food
    if food["quantity"] <= 1:
        col("inventory").delete_one({"_id": food["_id"]})
    else:
        col("inventory").update_one({"_id": food["_id"]}, {"$inc": {"quantity": -1}})

    bond_xp_gain = 30
    updated = add_pet_bond_xp(user_id, pet_name, bond_xp_gain)
    new_bond_level = updated.get("bond_level", 0)
    new_bond_name = PET_BOND_NAMES[new_bond_level]
    old_bond_level = active["bond_level"]

    leveled_up = new_bond_level > old_bond_level

    text = (
        f"🍖 Fed *{pet_name}*!\n"
        f"💠 *+{bond_xp_gain} Bond XP*\n\n"
        f"❤️ Bond: *{new_bond_name}* (Lv{new_bond_level+1})"
    )
    if leveled_up:
        text += f"\n\n🎊 *BOND LEVEL UP!* → *{new_bond_name}*\nPassive bonuses increased!"
    if new_bond_level >= 4 and pet_name in PETS and PETS[pet_name].get("evolution"):
        text += f"\n\n✨ *{pet_name}* is ready to evolve!\nUse `/feedpet evolve` + Spirit Crystal."

    await update.message.reply_text(text, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════
# /petskill — USE PET SKILL IN BATTLE
# ══════════════════════════════════════════════════════════════════════════

async def petskill(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/petskill — Use the active pet's combat skill during explore battle."""
    from utils.database import get_battle_state, update_battle_enemy_hp
    user_id = update.effective_user.id
    player = get_player(user_id)
    state = get_battle_state(user_id)

    if not state or not state.get("in_combat"):
        await update.message.reply_text("❌ You're not in a battle! Use /explore first.")
        return

    active = get_active_pet(user_id)
    if not active:
        await update.message.reply_text("❌ No active pet. Use `/pet <name>` to activate one.", parse_mode="Markdown")
        return

    pet_name = active["name"]
    is_evolved = pet_name in PET_EVOLUTIONS
    if is_evolved:
        base_name = PET_EVOLUTIONS[pet_name]["base"]
        base_data = PETS[base_name]
    else:
        base_data = PETS.get(pet_name, {})

    skill_name = base_data.get("skill")
    if not skill_name:
        await update.message.reply_text(f"❌ *{pet_name}* has no combat skill.", parse_mode="Markdown")
        return

    # Check if skill already used this battle
    pet_doc = col("pets").find_one({"user_id": user_id, "name": pet_name})
    battle_key = f"pet_skill_used_{user_id}"
    if context.user_data.get(battle_key):
        await update.message.reply_text(
            f"❌ *{pet_name}*'s skill already used this battle!\n"
            f"_(At Soulbound bond, skill resets once per battle)_",
            parse_mode="Markdown"
        )
        return

    bond_level = active.get("bond_level", 0)
    effect = base_data.get("skill_effect", {})
    emoji = base_data.get("emoji", "🐾")
    log_lines = [f"{emoji} *{pet_name}* uses *{skill_name}!*"]
    result_msg = ""

    enemy_hp = state["enemy_hp"]
    enemy_max = state.get("enemy_max_hp", enemy_hp)

    # Apply skill effect
    if skill_name == "Lunge":
        dmg = max(1, int(enemy_max * effect.get("bonus_dmg_pct", 0.08)))
        new_hp = max(0, enemy_hp - dmg)
        update_battle_enemy_hp(user_id, new_hp)
        result_msg = f"💥 Dealt *{dmg}* bonus damage!"
        log_lines.append(result_msg)

    elif skill_name == "Talon Strike":
        context.user_data[f"pet_crit_boost_{user_id}"] = effect.get("crit_bonus", 0.20)
        result_msg = f"🎯 Crit chance +20% this turn!"
        log_lines.append(result_msg)

    elif skill_name == "Distract":
        ctx = context.user_data.setdefault(f"battle_ctx_{user_id}", {})
        ctx["enemy_atk_reduce"] = effect.get("enemy_atk_reduce", 0.10)
        context.user_data[f"battle_ctx_{user_id}"] = ctx
        result_msg = f"😵 Enemy ATK reduced by 10% for 2 turns!"
        log_lines.append(result_msg)

    elif skill_name == "Intimidate":
        if random.random() < effect.get("skip_chance", 0.20):
            ctx = context.user_data.setdefault(f"battle_ctx_{user_id}", {})
            ctx["enemy_skip_turns"] = ctx.get("enemy_skip_turns", 0) + 1
            context.user_data[f"battle_ctx_{user_id}"] = ctx
            result_msg = f"💀 Enemy is *INTIMIDATED* — loses next turn!"
        else:
            result_msg = f"😤 Intimidate missed this time..."
        log_lines.append(result_msg)

    elif skill_name == "Fire Bite":
        if random.random() < effect.get("burn_chance", 0.40):
            ctx = context.user_data.setdefault(f"battle_ctx_{user_id}", {})
            ctx["enemy_burn"] = True
            ctx["enemy_burn_turns"] = 4
            ctx["enemy_burn_pct"] = 0.05
            context.user_data[f"battle_ctx_{user_id}"] = ctx
            result_msg = f"🔥 *BURN APPLIED!* 5% HP/turn × 4 turns!"
        else:
            result_msg = f"💨 Fire Bite missed..."
        log_lines.append(result_msg)

    elif skill_name == "Death Howl":
        if player["hp"] < player["max_hp"] * effect.get("hp_threshold", 0.30):
            context.user_data[f"pet_low_hp_boost_{user_id}"] = effect.get("low_hp_atk_boost", 0.30)
            result_msg = f"🐺 *DEATH HOWL!* ATK +30% this turn!"
        else:
            result_msg = f"_(HP must be below 30% to activate)_"
        log_lines.append(result_msg)

    elif skill_name == "Void Breath":
        pct_dmg = max(1, int(enemy_hp * effect.get("pct_dmg", 0.20)))
        new_hp = max(0, enemy_hp - pct_dmg)
        update_battle_enemy_hp(user_id, new_hp)
        result_msg = f"🌑 *VOID BREATH!* Dealt *{pct_dmg}* damage (20% current HP)!"
        log_lines.append(result_msg)

    elif skill_name == "Rebirth":
        context.user_data[f"pet_rebirth_{user_id}"] = True
        result_msg = f"🔥 *REBIRTH READIED!* You will survive once at 0 HP with 30% HP restored."
        log_lines.append(result_msg)

    # Mark skill used (Soulbound pets get 2 uses)
    uses = 2 if bond_level >= 4 else 1
    context.user_data[battle_key] = uses - 1  # 0 = no more uses

    await update.message.reply_text(
        "\n".join(log_lines),
        parse_mode="Markdown"
    )


# ══════════════════════════════════════════════════════════════════════════
# /petbattle @user — PET DUEL (auto-resolve)
# ══════════════════════════════════════════════════════════════════════════

async def petbattle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/petbattle @username — Auto-resolve pet fight."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        return

    # Resolve target
    target_player = None
    if update.message.reply_to_message:
        target_player = get_player(update.message.reply_to_message.from_user.id)
    elif context.args:
        raw = context.args[0].lstrip("@")
        if raw.isdigit():
            target_player = get_player(int(raw))
        else:
            target_player = col("players").find_one({"name": {"$regex": f"^{raw}$", "$options": "i"}})

    if not target_player:
        await update.message.reply_text(
            "❌ Couldn't find that player.\nUsage: `/petbattle @username` or reply to their message.",
            parse_mode="Markdown"
        )
        return

    opp_id = target_player["user_id"]
    if opp_id == user_id:
        await update.message.reply_text("❌ Can't battle your own pet!")
        return

    my_pet   = get_active_pet(user_id)
    opp_pet  = get_active_pet(opp_id)

    if not my_pet:
        await update.message.reply_text("❌ You have no active pet. Use `/pet <name>` first.", parse_mode="Markdown")
        return
    if not opp_pet:
        await update.message.reply_text(
            f"❌ *{target_player['name']}* has no active pet.",
            parse_mode="Markdown"
        )
        return

    # Calculate pet power scores
    def pet_power(pet_doc):
        name = pet_doc["name"]
        bond = pet_doc.get("bond_level", 0)
        rarity_scores = {"common": 1, "uncommon": 2, "rare": 3, "epic": 4, "legendary": 5}
        if name in PET_EVOLUTIONS:
            r = PETS[PET_EVOLUTIONS[name]["base"]]["rarity"]
        else:
            r = PETS.get(name, {}).get("rarity", "common")
        return rarity_scores.get(r, 1) * 10 + bond * 5 + random.randint(1, 15)

    my_score  = pet_power(my_pet)
    opp_score = pet_power(opp_pet)

    my_name   = my_pet["name"]
    opp_name  = opp_pet["name"]
    my_e      = PETS.get(my_name, PET_EVOLUTIONS.get(my_name, {".": "🐾"})).get("emoji", "🐾") if my_name in PETS else PET_EVOLUTIONS.get(my_name, {}).get("emoji", "🐾")
    opp_e     = PETS.get(opp_name, {}).get("emoji", "🐾") if opp_name in PETS else PET_EVOLUTIONS.get(opp_name, {}).get("emoji", "🐾")

    if my_score >= opp_score:
        winner_id, loser_id = user_id, opp_id
        winner_name, loser_name = player["name"], target_player["name"]
        win_pet, lose_pet = my_name, opp_name
        win_e, lose_e = my_e, opp_e
        result = f"🏆 *{player['name']}*'s *{my_name}* wins!"
    else:
        winner_id, loser_id = opp_id, user_id
        winner_name, loser_name = target_player["name"], player["name"]
        win_pet, lose_pet = opp_name, my_name
        win_e, lose_e = opp_e, my_e
        result = f"🏆 *{target_player['name']}*'s *{opp_name}* wins!"

    # Rewards
    add_pet_bond_xp(winner_id, win_pet, 25)
    add_pet_bond_xp(loser_id, lose_pet, 10)
    loser_player = get_player(loser_id)
    consolation = 200
    update_player(loser_id, yen=max(0, loser_player.get("yen", 0) + consolation))

    battle_text = (
        f"⚔️ *PET BATTLE!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{win_e} *{win_pet}* ({winner_name})\n"
        f"     VS\n"
        f"{lose_e} *{lose_pet}* ({loser_name})\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{result}\n\n"
        f"🏅 Winner: +25 Bond XP\n"
        f"💰 Loser: +{consolation}¥ consolation\n"
        f"📚 Loser pet: +10 Bond XP"
    )

    await update.message.reply_text(battle_text, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════
# /releasepet <name> — RELEASE A PET
# ══════════════════════════════════════════════════════════════════════════

async def releasepet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/releasepet <name> — Release a pet and receive some items."""
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("Usage: `/releasepet <name>`", parse_mode="Markdown")
        return

    pet_name = " ".join(context.args)
    owned = get_pet(user_id, pet_name)
    if not owned:
        await update.message.reply_text(f"❌ You don't own *{pet_name}*.", parse_mode="Markdown")
        return

    # Give back items based on bond level
    bond_level = owned.get("bond_level", 0)
    food_refund = bond_level * 2
    col("pets").delete_one({"user_id": user_id, "name": owned["name"]})
    if food_refund > 0:
        add_item(user_id, "Pet Food", "item", food_refund)

    await update.message.reply_text(
        f"🌿 *{owned['name']}* was released into the wild.\n"
        f"💚 It was a loyal companion.\n"
        + (f"🍖 Received *{food_refund}× Pet Food* back." if food_refund else ""),
        parse_mode="Markdown"
    )
