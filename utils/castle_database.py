"""MongoDB persistence and progression helpers for Infinity Castle.

This module is intentionally separate from the main database module to keep
castle data isolated while reusing the project's existing player and inventory
systems. It adds no currency, consumables, crafting materials, or duplicate
player-level/rank systems.
"""
from datetime import datetime
from math import sqrt
from uuid import uuid4


PLAYER_DEFAULTS = {
    "castle_highest_floor": 0,
    "castle_total_clears": 0,
}
DEMON_DEFAULTS = {
    "demon_level": 1,
    "demon_xp": 0,
    "demon_abilities": [],
    "demon_regen_bonus": 0.0,
    "demon_art_bonus": 0.0,
}

# Equipment-only reward catalogue. These are definitions, not owned inventory.
CASTLE_EQUIPMENT = [
    {"item_id": "castle_scout_blade", "name": "Castle Scout Blade",
     "slot": "weapon", "rarity": "common", "faction": "slayer",
     "min_floor": 1, "min_level": 1, "stats": {"atk_bonus": 3},
     "passive": {}},
    {"item_id": "worn_guard_vest", "name": "Worn Guard Vest",
     "slot": "armor", "rarity": "common", "faction": "any",
     "min_floor": 1, "min_level": 1, "stats": {"def_bonus": 3},
     "passive": {}},
    {"item_id": "castle_forged_nichirin", "name": "Castle-forged Nichirin",
     "slot": "weapon", "rarity": "uncommon", "faction": "slayer",
     "min_floor": 1, "min_level": 5, "stats": {"atk_bonus": 8},
     "passive": {"type": "demon_damage", "value": 0.04}},
    {"item_id": "crimson_moon_blade", "name": "Crimson Moon Blade",
     "slot": "weapon", "rarity": "epic", "faction": "slayer",
     "min_floor": 31, "min_level": 25, "stats": {"atk_bonus": 24},
     "passive": {"type": "critical_chance", "value": 0.06}},
    {"item_id": "upper_moon_katana", "name": "Upper Moon Katana",
     "slot": "weapon", "rarity": "legendary", "faction": "any",
     "min_floor": 61, "min_level": 50, "stats": {"atk_bonus": 38},
     "passive": {"type": "elite_damage", "value": 0.08}},
    {"item_id": "demon_kings_armor", "name": "Demon King's Armor",
     "slot": "armor", "rarity": "legendary", "faction": "demon",
     "min_floor": 61, "min_level": 50,
     "stats": {"def_bonus": 32, "hp_bonus": 80},
     "passive": {"type": "damage_reduction", "value": 0.05}},
    {"item_id": "wisteria_guard_haori", "name": "Wisteria Guard Haori",
     "slot": "armor", "rarity": "epic", "faction": "slayer",
     "min_floor": 31, "min_level": 25, "stats": {"def_bonus": 20},
     "passive": {"type": "poison_resistance", "value": 0.20}},
    {"item_id": "infinity_veil", "name": "Infinity Veil",
     "slot": "armor", "rarity": "mythic", "faction": "any",
     "min_floor": 91, "min_level": 75,
     "stats": {"def_bonus": 45, "hp_bonus": 120},
     "passive": {"type": "damage_reduction", "value": 0.08}},
    {"item_id": "nakimes_resonance_charm", "name": "Nakime's Resonance Charm",
     "slot": "accessory", "rarity": "rare", "faction": "any",
     "min_floor": 21, "min_level": 15, "stats": {"def_bonus": 5},
     "passive": {"type": "trap_avoidance", "value": 0.10}},
    {"item_id": "akazas_battle_ring", "name": "Akaza's Battle Ring",
     "slot": "accessory", "rarity": "legendary", "faction": "any",
     "min_floor": 61, "min_level": 50, "stats": {"atk_bonus": 12},
     "passive": {"type": "combat_damage", "value": 0.05}},
    {"item_id": "muzans_blood_seal", "name": "Muzan's Blood Seal",
     "slot": "accessory", "rarity": "mythic", "faction": "demon",
     "min_floor": 100, "min_level": 80,
     "stats": {"atk_bonus": 20, "hp_bonus": 100},
     "passive": {"type": "demon_art_power", "value": 0.10}},
]

RARITY_ORDER = ("common", "uncommon", "rare", "epic", "legendary", "mythic")
FLOOR_REWARD_BANDS = (
    (1, 10, ("common", "uncommon")),
    (11, 20, ("uncommon", "rare")),
    (21, 30, ("rare",)),
    (31, 40, ("rare", "epic")),
    (41, 50, ("epic",)),
    (51, 60, ("epic", "legendary")),
    (61, 70, ("legendary",)),
    (71, 80, ("legendary",)),
    (81, 90, ("legendary", "mythic")),
    (91, 99, ("legendary", "mythic")),
    (100, 100, ("mythic",)),
)


def initialize_castle_database(db):
    """Create indexes and safely seed castle data; safe to run on every boot."""
    db.castle_runs.create_index("run_id", unique=True)
    db.castle_runs.create_index([("user_id", 1), ("status", 1)])
    db.castle_runs.create_index([("party_id", 1), ("status", 1)])
    db.castle_parties.create_index("party_id", unique=True)
    db.castle_parties.create_index([("member_ids", 1), ("status", 1)])
    db.castle_encounters.create_index(
        [("run_id", 1), ("floor", 1), ("room_id", 1)], unique=True
    )
    db.castle_equipment.create_index("instance_id", unique=True)
    db.castle_equipment.create_index([("user_id", 1), ("equipped", 1)])
    db.castle_item_catalog.create_index("item_id", unique=True)
    db.castle_leaderboards.create_index([("mode", 1), ("highest_floor", -1)])
    db.castle_reward_claims.create_index("claim_key", unique=True)

    # Only fill missing fields. Never reset existing progress in other fields.
    for field, default in PLAYER_DEFAULTS.items():
        db.players.update_many(
            {field: {"$exists": False}}, {"$set": {field: default}}
        )
    # Demon progression fields belong only to Demon-faction characters.
    for field, default in DEMON_DEFAULTS.items():
        db.players.update_many(
            {"faction": "demon", field: {"$exists": False}},
            {"$set": {field: default}}
        )

    now = datetime.utcnow()
    for definition in CASTLE_EQUIPMENT:
        item = dict(definition)
        item["updated_at"] = now
        db.castle_item_catalog.update_one(
            {"item_id": item["item_id"]},
            {"$set": item, "$setOnInsert": {"created_at": now}},
            upsert=True,
        )


def _col(name):
    from utils.database import col
    return col(name)


def _player_level(player):
    """Use the game's existing XP-to-level formula when level is not stored."""
    if not player:
        return 1
    if player.get("level"):
        return max(1, int(player["level"]))
    try:
        from utils.helpers import get_level
        return max(1, int(get_level(int(player.get("xp", 0) or 0))))
    except Exception:
        return 1


def calculate_player_power(player):
    """Estimate strength from level AND actual combat stats/equipment bonuses."""
    if not player:
        return 1
    level = _player_level(player)
    atk = max(0, float(player.get("str_stat", player.get("atk", player.get("attack", 0))) or 0))
    defense = max(0, float(player.get("def_stat", player.get("defense", 0)) or 0))
    try:
        from config import SHOP_ITEMS
        for item in SHOP_ITEMS.get("swords", []):
            if item.get("name") == player.get("equipped_sword"):
                atk += max(0, float(item.get("atk_bonus", 0)))
                break
        for item in SHOP_ITEMS.get("armor", []):
            if item.get("name") == player.get("equipped_armor"):
                defense += max(0, float(item.get("def_bonus", 0)))
                break
    except Exception:
        pass
    hp = max(1, float(player.get("max_hp", player.get("hp", 1)) or 1))
    stamina = max(0, float(player.get("max_sta", player.get("sta", 0)) or 0))
    skill_bonuses = {}
    if player.get("user_id") is not None:
        try:
            from handlers.skilltree import get_player_skills, get_active_skill_bonuses
            skill_bonuses = get_active_skill_bonuses(
                get_player_skills(int(player["user_id"])),
                user_id=int(player["user_id"]),
            )
            atk *= 1 + float(skill_bonuses.get("atk_pct", 0) or 0)
            defense *= 1 + float(skill_bonuses.get("def_pct", 0) or 0)
            hp += max(0, float(skill_bonuses.get("max_hp", 0) or 0))
        except Exception:
            skill_bonuses = {}
    power = level * 5 + atk * 2.0 + defense * 1.5 + hp * 0.08 + stamina * 0.04
    power += max(0, float(skill_bonuses.get("crit_bonus", 0) or 0)) * 20
    # Include equipped Castle gear in the adaptive power calculation.
    user_id = player.get("user_id")
    if user_id is not None:
        try:
            for gear in _col("castle_equipment").find({"user_id": int(user_id), "equipped": True}):
                stats = gear.get("stats", {})
                power += max(0, float(stats.get("atk_bonus", 0))) * 2
                power += max(0, float(stats.get("def_bonus", 0))) * 1.5
                power += max(0, float(stats.get("hp_bonus", 0))) * 0.08
        except Exception:
            pass
    if str(player.get("faction", "")).lower() == "demon":
        power += max(1, int(player.get("demon_level") or 1)) * 3
    return max(1, int(power))


def calculate_party_power(players):
    """Return total and average squad power; squad scaling uses average strength."""
    powers = [calculate_player_power(p) for p in (players or []) if p]
    if not powers:
        return {"total": 0, "average": 1, "size": 0}
    return {
        "total": sum(powers),
        "average": int(sum(powers) / len(powers)),
        "size": len(powers),
    }


def calculate_enemy_level(player, floor, party_players=None):
    """Adaptive enemy level: floor + player level + real stats + squad strength.

    The enemy is not scaled by a fixed floor-only formula. A well-equipped
    player faces stronger enemies than a same-level under-equipped player.
    Party scaling is soft and capped, preventing 4-player groups from causing
    a fourfold enemy-level jump.
    """
    player = player or {}
    level = _player_level(player)
    floor = max(1, min(100, int(floor or 1)))
    own_power = calculate_player_power(player)
    # A fresh level-1 character with starter gear is roughly 125 power.
    # Raise the expected baseline gradually with player level; this prevents
    # starter characters from being matched against level-70 enemies.
    reference_power = 125 + max(0, level - 1) * 24
    strength_ratio = own_power / max(1, reference_power)
    floor_bonus = (floor - 1) // 8
    strength_bonus = max(-5, min(10, round((strength_ratio - 1.0) * 6)))

    party_players = [p for p in (party_players or [player]) if p]
    party = calculate_party_power(party_players)
    # Co-op challenge uses the whole roster: average level, strongest member,
    # average power and team size. Adding members meaningfully raises enemy level.
    levels = [_player_level(p) for p in party_players] or [level]
    average_level = sum(levels) / len(levels)
    strongest_level = max(levels)
    average_reference = 125 + max(0, average_level - 1) * 24
    party_strength_ratio = party["average"] / max(1, average_reference)
    party_strength_bonus = max(-3, min(16, round((party_strength_ratio - 1.0) * 8)))
    level_spread_bonus = max(0, strongest_level - round(average_level)) // 3
    team_bonus = max(0, len(party_players) - 1) * 3
    return max(
        1,
        min(
            500,
            round(average_level) + floor_bonus + party_strength_bonus
            + level_spread_bonus + team_bonus,
        ),
    )


def calculate_difficulty(player, floor, party_players=None):
    """Return a persisted-friendly difficulty breakdown for UI and balancing."""
    enemy_level = calculate_enemy_level(player, floor, party_players)
    party_size = max(1, len(party_players or [player]))
    base_level = _player_level(player)
    if enemy_level <= base_level + 2:
        tier = "Normal"
    elif enemy_level <= base_level + 8:
        tier = "Hard"
    elif enemy_level <= base_level + 16:
        tier = "Extreme"
    else:
        tier = "Nightmare"
    return {
        "enemy_level": enemy_level,
        "tier": tier,
        "party_size": party_size,
        "floor": int(floor),
        "player_power": calculate_player_power(player),
        "party_power": calculate_party_power(party_players or [player])["total"],
    }


def create_castle_run(user_id, mode="solo", party_id=None):
    if mode not in ("solo", "squad"):
        raise ValueError("mode must be 'solo' or 'squad'")
    run_id = uuid4().hex
    now = datetime.utcnow()
    doc = {
        "run_id": run_id, "user_id": int(user_id), "mode": mode,
        "party_id": party_id, "floor": 1, "room_id": "entrance",
        "checkpoint_floor": 1, "status": "active",
        "created_at": now, "updated_at": now,
    }
    _col("castle_runs").insert_one(doc)
    return doc


def get_active_castle_run(user_id):
    doc = _col("castle_runs").find_one(
        {"user_id": int(user_id), "status": "active"},
        sort=[("updated_at", -1)],
    )
    if doc:
        doc.pop("_id", None)
    return doc


def save_castle_run(run_id, updates):
    allowed = {
        "floor", "room_id", "checkpoint_floor", "status", "party_id",
        "power_score", "difficulty", "current_enemy", "room_history",
        "player_hp_by_user", "room_type", "room_notice",
    }
    safe = {k: v for k, v in dict(updates or {}).items() if k in allowed}
    safe["updated_at"] = datetime.utcnow()
    return _col("castle_runs").update_one(
        {"run_id": run_id, "status": "active"}, {"$set": safe}
    ).modified_count == 1


def apply_castle_enemy_damage(run_id, expected_hp, damage):
    """Compare-and-swap enemy HP so duplicate Telegram taps cannot double-hit."""
    result = _col("castle_runs").update_one(
        {
            "run_id": str(run_id), "status": "active",
            "current_enemy.hp": int(expected_hp),
        },
        {
            "$inc": {"current_enemy.hp": -max(1, int(damage))},
            "$set": {"updated_at": datetime.utcnow()},
        },
    )
    return result.modified_count == 1


def save_castle_encounter(run_id, floor, room_id, enemy_data):
    doc = {
        "run_id": run_id, "floor": int(floor), "room_id": str(room_id),
        "enemy": dict(enemy_data or {}), "updated_at": datetime.utcnow(),
    }
    _col("castle_encounters").update_one(
        {"run_id": run_id, "floor": int(floor), "room_id": str(room_id)},
        {"$set": doc}, upsert=True,
    )
    return doc


def create_castle_party(leader_id):
    party_id = uuid4().hex[:12]
    now = datetime.utcnow()
    # The owner is the first squad member automatically; no separate
    # self-join operation should be required.
    party = {
        "party_id": party_id, "leader_id": int(leader_id),
        "member_ids": [int(leader_id)], "status": "open",
        "created_at": now, "updated_at": now,
    }
    _col("castle_parties").insert_one(party)
    return party


def get_castle_party(party_id):
    party = _col("castle_parties").find_one({"party_id": str(party_id)})
    if party:
        party.pop("_id", None)
    return party


def add_castle_party_member(party_id, user_id, max_members=4):
    col = _col("castle_parties")
    party = col.find_one({"party_id": str(party_id), "status": "open"})
    if not party:
        return False
    members = party.get("member_ids", [])
    user_id = int(user_id)
    if user_id in members:
        return True
    if len(members) >= max(1, min(4, int(max_members))):
        return False
    result = col.update_one(
        {"party_id": str(party_id), "status": "open",
         "member_ids": members},
        {"$push": {"member_ids": user_id},
         "$set": {"updated_at": datetime.utcnow()}},
    )
    return result.modified_count == 1


def save_castle_leaderboard(user_id, mode, highest_floor, clears=0):
    if mode not in ("solo", "squad"):
        raise ValueError("mode must be 'solo' or 'squad'")
    _col("castle_leaderboards").update_one(
        {"user_id": int(user_id), "mode": mode},
        {"$max": {"highest_floor": int(highest_floor)},
         "$inc": {"clears": max(0, int(clears))},
         "$set": {"updated_at": datetime.utcnow()}},
        upsert=True,
    )


def grant_castle_equipment(user_id, item_id, claim_key, source_floor,
                           source_enemy=None):
    """Idempotent reward ledger + owned item record; no currency or materials."""
    catalog = _col("castle_item_catalog").find_one({"item_id": str(item_id)})
    if not catalog:
        return None
    now = datetime.utcnow()
    instance_id = uuid4().hex
    claim = {
        "claim_key": str(claim_key), "user_id": int(user_id),
        "item_id": str(item_id), "instance_id": instance_id,
        "source_floor": int(source_floor), "source_enemy": source_enemy,
        "claimed_at": now,
    }
    try:
        _col("castle_reward_claims").insert_one(claim)
    except Exception:
        # Duplicate claim key means Telegram callback/retry already granted it.
        return None

    instance = {
        "instance_id": instance_id, "user_id": int(user_id),
        "item_id": catalog["item_id"], "name": catalog["name"],
        "item_type": catalog["slot"], "rarity": catalog["rarity"],
        "faction": catalog.get("faction", "any"),
        "stats": catalog.get("stats", {}),
        "passive": catalog.get("passive", {}),
        "equipped": False, "source_floor": int(source_floor),
        "source_enemy": source_enemy, "obtained_at": now,
    }
    _col("castle_equipment").insert_one(instance)
    return instance


def add_demon_xp(user_id, amount):
    """Demon-only progression, separate from the existing player XP/level."""
    from utils.database import get_player
    player = get_player(int(user_id))
    if not player or str(player.get("faction", "")).lower() != "demon":
        return None
    amount = max(0, int(amount))
    xp = max(0, int(player.get("demon_xp", 0))) + amount
    # Level N requires 25 * (N-1) * N cumulative Demon XP.
    demon_level = min(100, max(1, int((1 + sqrt(1 + 8 * xp / 50)) // 2)))
    milestones = {
        5: "Blood Sense", 10: "Rapid Regeneration",
        20: "Blood Demon Art I", 35: "Enhanced Physiology",
        50: "Blood Demon Art II", 75: "Superior Regeneration",
        100: "Demon King's Evolution",
    }
    unlocked = [name for level, name in milestones.items() if demon_level >= level]
    from utils.database import update_player
    update_player(
        int(user_id), demon_xp=xp, demon_level=demon_level,
        demon_abilities=unlocked,
        demon_regen_bonus=min(0.12, (demon_level // 10) * 0.015),
        demon_art_bonus=min(0.25, (demon_level // 10) * 0.025),
    )
    return {
        "demon_level": demon_level, "demon_xp": xp,
        "unlocked_abilities": unlocked,
    }


def record_castle_progress(user_id, floor, mode="solo"):
    """Track the best reached floor without counting it as a full clear."""
    floor = max(1, min(100, int(floor)))
    _col("players").update_one(
        {"user_id": int(user_id)}, {"$max": {"castle_highest_floor": floor}}
    )
    _col("castle_leaderboards").update_one(
        {"user_id": int(user_id), "mode": mode},
        {"$max": {"highest_floor": floor},
         "$set": {"updated_at": datetime.utcnow()}},
        upsert=True,
    )


def record_castle_clear(user_id, floor, mode="solo"):
    """Update best floor and clear totals without changing normal XP or Yen."""
    floor = max(1, min(100, int(floor)))
    _col("players").update_one(
        {"user_id": int(user_id)},
        {"$max": {"castle_highest_floor": floor},
         "$inc": {"castle_total_clears": 1}},
    )
    save_castle_leaderboard(user_id, mode, floor, 1)
    return True
