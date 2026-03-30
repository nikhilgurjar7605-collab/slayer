"""
MongoDB database layer for Demon Slayer RPG Bot.
Drop-in replacement for the SQLite version — all function signatures identical.
"""
import os as _os
import json
import re
from datetime import datetime, timedelta
import dns.resolver
from pymongo import MongoClient, DESCENDING
from pymongo.collection import Collection

# ── Connection ────────────────────────────────────────────────────────────

# Force Python to use Google/Cloudflare DNS to bypass the server timeout
dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
dns.resolver.default_resolver.nameservers = ['8.8.8.8', '1.1.1.1']

MONGO_URL = _os.environ.get("MONGO_URL", 
    "mongodb+srv://yesvashisht2005_db_user:rjuAwTHG8qO6545f@cluster0.nwvwqpj.mongodb.net/?appName=Cluster0")
DB_NAME   = "demon_slayer_rpg"

# Globals for connection reuse
_client = None
_db = None

ITEM_NAME_ALIASES = {
    "full recovery gourd": "Full Recovery Gourd",
    "stamina pill": "Stamina Pill",
    "wisteria antidote": "Wisteria Antidote",
    "blood crystal": "Blood Crystal",
    "demon blood": "Demon Blood",
    "skill points": "Skill Points",
    "skill point": "Skill Points",
    "skill pts": "Skill Points",
    "skill pt": "Skill Points",
}


def canonical_item_name(item_name: str) -> str:
    raw = " ".join(str(item_name or "").strip().split())
    if not raw:
        return raw
    return ITEM_NAME_ALIASES.get(raw.lower(), raw.title())


def get_raw_db():
    """Internal singleton for direct PyMongo database access."""
    global _client, _db
    if _client is None:
        _client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000,
                              connectTimeoutMS=15000, socketTimeoutMS=30000)
        _db = _client[DB_NAME]
    return _db


def col(name) -> Collection:
    """Helper to get a PyMongo collection easily."""
    return get_raw_db()[name]


# ── Init / Migrate ────────────────────────────────────────────────────────

def init_db():
    """Create indexes and seed starter data."""
    db = get_raw_db()

    # Indexes
    db.players.create_index("user_id", unique=True)
    db.players.create_index("faction")
    db.players.create_index("xp")
    db.players.create_index("yen")
    db.players.create_index("demons_slain")

    db.inventory.create_index([("user_id", 1), ("item_name", 1)])
    db.battle_state.create_index("user_id", unique=True)
    db.duels.create_index("challenger_id")
    db.duels.create_index("target_id")
    db.market_listings.create_index("status")
    db.market_listings.create_index("seller_id")
    db.bank_accounts.create_index("user_id", unique=True)
    db.bank_giveaways.create_index("status")
    db.bank_giveaways.create_index("ends_at")
    db.sp_bank_users.create_index("user_id", unique=True)
    db.sp_giveaways.create_index("id", unique=True)
    db.sp_giveaways.create_index("status")
    db.sp_giveaways.create_index("ends_at")
    db.sp_tournaments.create_index("id", unique=True)
    db.sp_tournaments.create_index("status")
    db.sp_tournaments.create_index("ends_at")
    # ── Tournament system ──────────────────────────────────────────────────
    db.tournaments.create_index("tour_id", unique=True)
    db.tournaments.create_index("status")
    db.tournaments.create_index("created_at")
    db.user_activity_logs.create_index([("user_id", 1), ("timestamp", DESCENDING)])
    db.user_activity_logs.create_index("timestamp")
    db.captcha_guard.create_index("user_id", unique=True)

    # ── skill_tree collection indexes ─────────────────────────────────────
    db.skill_tree.create_index("user_id", unique=True)
    db.skill_tree.create_index([("user_id", 1), ("skill_name", 1)], unique=True)
    db.referrals.create_index("referred_id", unique=True)
    db.referrals.create_index("referrer_id")
    db.clans.create_index("name", unique=True)
    db.admins.create_index("user_id", unique=True)

    # Seed Black Market
    if db.black_market.count_documents({"status": "active"}) == 0:
        expires = datetime.now() + timedelta(days=30)
        bm_items = [
            # Rare materials
            ("Muzan Blood",                    150000, 1),
            ("Demon King Core",                100000, 1),
            ("Upper Moon Core",                 50000, 2),
            ("Kizuki Blood",                    25000, 3),
            ("Boss Shard",                      15000, 5),
            ("Rui Thread",                      18000, 2),
            ("Akaza Fist",                      35000, 1),
            ("Kokushibo Shard",                 55000, 1),
            # Technique Scrolls — let users learn extra arts in battle
            ("Demonic Catalyst",               50000, 1),
            ("Ancient Whetstone",             35000, 2),
            ("Rare Ore Fragment",             25000, 2),
            # Sun/Moon tomes
            ("Sun Breathing Tome",             200000, 1),
            ("Moon Breathing Scroll",           80000, 1),
        ]
        db.black_market.insert_many([
            {"item_name": n, "price": p, "stock": s,
             "expires_at": expires, "status": "active", "item_type": "scroll" if "Scroll" in n or "Tome" in n else "material"}
            for n, p, s in bm_items
        ])

    # Seed Player Market
    if db.market_listings.count_documents({"status": "active", "seller_id": 0}) == 0:
        # NPC market seed — seller_id=0 = Shop NPC
        # Format: (seller_id, item_name, item_type, price, quantity)
        mkt_items = [
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # CONSUMABLES — BASIC
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            (0, "Stamina Pill",                 "item",       250,  15),
            (0, "Full Recovery Gourd",          "item",       600,  12),
            (0, "Wisteria Antidote",            "item",       300,  12),
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # ADVANCED POTIONS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            (0, "Demon Blood Elixir",           "item",      3000,   8),
            (0, "Hashira Tonic",                "item",      6000,   6),
            (0, "Iron Body Brew",               "item",      6000,   6),
            (0, "Thunder Flash Serum",          "item",      9500,   4),
            (0, "Muzan Blood Vial",             "item",     18000,   3),
            (0, "Sun Breathing Pill",           "item",     30000,   2),
            (0, "Infinity Draught",             "item",     60000,   1),
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # SWORDS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            (0, "Basic Nichirin Blade",         "sword",      950,   4),
            (0, "Crimson Nichirin Blade",       "sword",     4800,   3),
            (0, "Jet Black Nichirin Blade",     "sword",    17000,   2),
            (0, "Scarlet Crimson Blade",        "sword",    40000,   1),
            (0, "Transparent Nichirin Blade",   "sword",    85000,   1),
            (0, "Sun Nichirin Blade",           "sword",   170000,   1),
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # ARMOR
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            (0, "Corps Uniform",                "armor",      600,   4),
            (0, "Reinforced Haori",             "armor",     3000,   3),
            (0, "Hashira Haori",                "armor",     9500,   2),
            (0, "Demon Slayer Uniform EX",      "armor",    23000,   1),
            (0, "Flame Haori",                  "armor",    52000,   1),
            (0, "Yoriichi Haori",               "armor",   135000,   1),
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # UPGRADE ITEMS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            (0, "Strength Stone",               "item",      3500,   5),
            (0, "Speed Crystal",                "item",      3500,   5),
            (0, "Defense Shard",                "item",      3500,   5),
            (0, "Vitality Core",                "item",      6000,   5),
            (0, "Stamina Core",                 "item",      6000,   5),
            (0, "Demon Blood Infusion",         "item",     14000,   3),
            (0, "Kizuki Essence",               "item",     23000,   2),
            (0, "Upper Moon Core",              "item",     58000,   1),
            (0, "Muzan Cell Injection",         "item",    115000,   1),
            (0, "Skill Point Scroll",           "item",     12000,   5),
            (0, "Grand Skill Tome",             "item",     35000,   2),
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # COMMON MATERIALS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            (0, "Demon Blood",                  "material",   600,   8),
            (0, "Wolf Fang",                    "material",   450,   8),
            (0, "Goblin Claw",                  "material",   350,  10),
            (0, "Spirit Ash",                   "material",   700,   6),
            (0, "Slayer Badge",                 "material",   550,   6),
            (0, "Vampire Fang",                 "material",   800,   5),
            (0, "Demon Claw",                   "material",   750,   5),
            (0, "Shadow Shard",                 "material",   900,   4),
            (0, "Blood Crystal",                "material",  2000,   4),
            (0, "Ice Crystal",                  "material",  1200,   4),
            (0, "Spider Silk",                  "material",  1500,   3),
            (0, "Butterfly Wing",               "material",  1200,   4),
            (0, "Ogre Horn",                    "material",  1100,   4),
            (0, "Storm Crystal",                "material",  1800,   3),
            (0, "Thunder Fang",                 "material",  1600,   3),
            (0, "Titan Core",                   "material",  8000,   2),
            (0, "Poison Sac",                   "material",   950,   4),
            (0, "Venom Gland",                  "material",  1100,   3),
            (0, "Eagle Talon",                  "material",  1300,   3),
            (0, "Frost Shard",                  "material",  1000,   4),
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            # RARE MATERIALS
            # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            (0, "Boss Shard",                   "material", 14000,   3),
            (0, "Kizuki Blood",                 "material", 24000,   2),
            (0, "Upper Moon Shard",             "material", 35000,   1),
            (0, "Hashira Badge",                "material", 20000,   2),
            (0, "Rui Thread",                   "material", 19000,   2),
            (0, "Muzan Blood",                  "material", 85000,   1),
            (0, "Demon King Core",              "material",160000,   1),
            (0, "Akaza Fist",                   "material", 45000,   1),
            (0, "Doma Shard",                   "material", 38000,   1),
            (0, "Queen Wing",                   "material", 16000,   2),
            (0, "King Blade",                   "material", 30000,   1),
            # ━━ 10 new items ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
            (0, "Demon Blood Elixir",           "item",      3500,   5),
            (0, "Hashira Tonic",                "item",      6500,   4),
            (0, "Iron Body Brew",               "item",      6500,   4),
            (0, "Skill Point Scroll",           "item",    165000,   2),
            (0, "Strength Stone",               "item",     55000,   3),
            (0, "Vitality Core",                "item",     88000,   3),
            (0, "Scarlet Crimson Blade",        "sword",    42000,   1),
            (0, "Demon Slayer Uniform EX",      "armor",    25000,   1),
            (0, "Muzan Blood",                  "material", 90000,   1),
            (0, "Lava Stone",                   "material",  2200,   4),
        ]
        db.market_listings.insert_many([
            {"seller_id": sid, "item_name": n, "item_type": t,
             "price": p, "quantity": q, "status": "active",
             "listed_at": datetime.now()}
            for sid, n, t, p, q in mkt_items
        ])

    # Seed admins from config
    try:
        from config import SUDO_ADMIN_IDS
        for uid in (SUDO_ADMIN_IDS or []):
            db.admins.update_one(
                {"user_id": uid},
                {"$setOnInsert": {"user_id": uid, "added_at": datetime.now()}},
                upsert=True
            )
    except Exception:
        pass


def migrate_db():
    """No-op for MongoDB — schemaless, no migrations needed."""
    pass


# ── Player helpers ────────────────────────────────────────────────────────

def _player_defaults(faction="slayer"):
    """Base stats. Demons are slightly stronger but slayers have equipment bonuses."""
    if faction == "demon":
        # Demons: higher raw stats, no equipment dependency, slightly more power
        return {
            "username": None, "name": None, "faction": "demon",
            "style": None, "style_emoji": None, "story": None, "story_bonus": None,
            "rank": None, "rank_kanji": None,
            "xp": 0, "level": 1,
            "hp": 280, "max_hp": 280, "sta": 160, "max_sta": 160,
            "str_stat": 26, "spd": 20, "def_stat": 14, "potential": 0,
            "yen": 1000, "demons_slain": 0, "missions_done": 0, "deaths": 0,
            "location": "asakusa",
            "equipped_sword": None,
            "equipped_armor": None,
            "demon_mark": 0, "slayer_mark": 0, "active_mission": None,
            "party_id": None, "clan_id": None, "clan_role": None, "title": None,
            "last_daily": None, "daily_streak": 0, "last_streak_day": None,
            "banned": 0, "ban_reason": None, "skill_points": 0,
            "devour_stacks": 0, "explore_count": 0, "explores_since_boss": 20,
            "created_at": datetime.now(),
        }
    else:
        # Slayers: balanced stats, equipment boosts their effective power
        return {
            "username": None, "name": None, "faction": "slayer",
            "style": None, "style_emoji": None, "story": None, "story_bonus": None,
            "rank": None, "rank_kanji": None,
            "xp": 0, "level": 1,
            "hp": 240, "max_hp": 240, "sta": 170, "max_sta": 170,
            "str_stat": 22, "spd": 20, "def_stat": 18, "potential": 0,
            "yen": 1000, "demons_slain": 0, "missions_done": 0, "deaths": 0,
            "location": "asakusa",
            "equipped_sword": "Basic Nichirin Blade",
            "equipped_armor": "Corps Uniform",
            "slayer_mark": 0, "demon_mark": 0, "active_mission": None,
            "party_id": None, "clan_id": None, "clan_role": None, "title": None,
            "last_daily": None, "daily_streak": 0, "last_streak_day": None,
            "banned": 0, "ban_reason": None, "skill_points": 0,
            "devour_stacks": 0, "explore_count": 0, "explores_since_boss": 20,
            "created_at": datetime.now(),
        }


def get_player(user_id):
    doc = col("players").find_one({"user_id": user_id})
    if doc:
        doc.pop("_id", None)
        return doc
    return None


def create_player(user_id, username, name, faction, style, style_emoji,
                  story, story_bonus, rank, rank_kanji):
    d = _player_defaults(faction=faction)
    d.update({
        "user_id": user_id, "username": username, "name": name,
        "faction": faction, "style": style, "style_emoji": style_emoji,
        "story": story, "story_bonus": story_bonus,
        "rank": rank, "rank_kanji": rank_kanji,
    })
    col("players").update_one(
        {"user_id": user_id},
        {"$setOnInsert": d},
        upsert=True
    )


def update_player(user_id, **kwargs):
    col("players").update_one({"user_id": user_id}, {"$set": kwargs})


def get_all_players():
    return [{k: v for k, v in d.items() if k != "_id"}
            for d in col("players").find()]


# ── Inventory ─────────────────────────────────────────────────────────────

def get_inventory(user_id):
    merged = {}
    for d in col("inventory").find({"user_id": user_id}):
        item_name = canonical_item_name(d.get("item_name", ""))
        item_type = d.get("item_type", "item")
        key = (item_name.lower(), item_type)
        if key not in merged:
            merged[key] = {
                "user_id": user_id,
                "item_name": item_name,
                "item_type": item_type,
                "quantity": 0,
            }
        merged[key]["quantity"] += int(d.get("quantity", 0) or 0)
    return [v for v in merged.values() if v["quantity"] > 0]


def add_item(user_id, item_name, item_type, quantity=1):
    item_name = canonical_item_name(item_name)
    pattern = f"^{re.escape(item_name)}$"
    col("inventory").update_one(
        {"user_id": user_id, "item_name": {"$regex": pattern, "$options": "i"}},
        {"$inc": {"quantity": quantity},
         "$set": {"item_name": item_name, "item_type": item_type},
         "$setOnInsert": {"user_id": user_id}},
        upsert=True
    )


def remove_item(user_id, item_name, quantity=1):
    item_name = canonical_item_name(item_name)
    pattern = f"^{re.escape(item_name)}$"
    doc = col("inventory").find_one(
        {"user_id": user_id, "item_name": {"$regex": pattern, "$options": "i"}}
    )
    if not doc:
        return
    if doc.get("quantity", 1) <= quantity:
        col("inventory").delete_one({"_id": doc["_id"]})
    else:
        col("inventory").update_one(
            {"_id": doc["_id"]},
            {"$inc": {"quantity": -quantity}}
        )


# ── Arts ──────────────────────────────────────────────────────────────────

def get_arts(user_id):
    return [{k: v for k, v in d.items() if k != "_id"}
            for d in col("arts").find({"user_id": user_id})]


def add_art(user_id, art_name, art_emoji, source):
    col("arts").insert_one({
        "user_id": user_id, "art_name": art_name,
        "art_emoji": art_emoji, "source": source
    })


# ── Battle State ──────────────────────────────────────────────────────────

def set_battle_state(user_id, enemy, in_combat=False):
    drops = enemy.get("drops", [])
    if isinstance(drops, str):
        try: drops = json.loads(drops)
        except: drops = []
    col("battle_state").update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "enemy_name":    enemy["name"],
            "enemy_emoji":   enemy.get("emoji", "👹"),
            "enemy_hp":      enemy["hp"],
            "enemy_max_hp":  enemy["hp"],
            "enemy_atk":     enemy["atk"],
            "threat":        enemy.get("threat", "🟢 LOW"),
            "prize_xp":      enemy["xp"],
            "prize_yen":     enemy["yen"],
            "prize_drops":   json.dumps(drops),
            "faction_type":  enemy.get("faction_type", ""),
            "is_boss":       1 if enemy.get("is_boss") else 0,
            "active":        1,
            "in_combat":     1 if in_combat else 0,
            "active_ally_id": None,
            "ally_hp":       None,
            "ally_max_hp":   None,
            "battle_log":    "[]",
        }},
        upsert=True
    )


def get_battle_state(user_id):
    doc = col("battle_state").find_one({"user_id": user_id, "active": 1})
    if doc:
        doc.pop("_id", None)
        return doc
    return None


def clear_battle_state(user_id):
    col("battle_state").update_one({"user_id": user_id}, {"$set": {"active": 0}})


def update_battle_enemy_hp(user_id, new_hp):
    col("battle_state").update_one({"user_id": user_id}, {"$set": {"enemy_hp": new_hp}})


def set_battle_state_in_combat(user_id):
    col("battle_state").update_one({"user_id": user_id}, {"$set": {"in_combat": 1}})


# ── Ally ──────────────────────────────────────────────────────────────────

def set_active_ally(user_id, ally_id, ally_hp, ally_max_hp):
    col("battle_state").update_one(
        {"user_id": user_id},
        {"$set": {"active_ally_id": ally_id, "ally_hp": ally_hp, "ally_max_hp": ally_max_hp}}
    )


def update_ally_hp(user_id, new_hp):
    col("battle_state").update_one({"user_id": user_id}, {"$set": {"ally_hp": new_hp}})


def clear_ally(user_id):
    col("battle_state").update_one(
        {"user_id": user_id},
        {"$set": {"active_ally_id": None, "ally_hp": None, "ally_max_hp": None}}
    )


# ── Battle Log ────────────────────────────────────────────────────────────

def append_battle_log(user_id, entries):
    doc = col("battle_state").find_one({"user_id": user_id, "active": 1})
    if doc:
        try:
            existing = json.loads(doc.get("battle_log") or "[]")
        except Exception:
            existing = []
        existing.extend(entries)
        if len(existing) > 60:
            existing = existing[-60:]
        col("battle_state").update_one(
            {"user_id": user_id},
            {"$set": {"battle_log": json.dumps(existing)}}
        )


def get_battle_log(user_id):
    doc = col("battle_state").find_one({"user_id": user_id, "active": 1})
    if doc and doc.get("battle_log"):
        try:
            return json.loads(doc["battle_log"])
        except Exception:
            pass
    return []


def clear_battle_log(user_id):
    col("battle_state").update_one({"user_id": user_id}, {"$set": {"battle_log": "[]"}})


# ── Party ─────────────────────────────────────────────────────────────────

def get_party(user_id):
    doc = col("parties").find_one({
        "$or": [
            {"leader_id": user_id},
            {"members": {"$in": [user_id]}}
        ]
    })
    if doc:
        doc.pop("_id", None)
        return doc
    return None


def get_party_by_id(party_id):
    doc = col("parties").find_one({"id": party_id})
    if doc:
        doc.pop("_id", None)
        return doc
    return None


def create_party(leader_id):
    import time
    party_id = int(time.time() * 1000)
    col("parties").insert_one({
        "id": party_id,
        "leader_id": leader_id,
        "members": [leader_id],
        "created_at": datetime.now()
    })
    col("players").update_one({"user_id": leader_id}, {"$set": {"party_id": party_id}})
    return party_id


def add_to_party(party_id, user_id):
    result = col("parties").update_one(
        {"id": party_id},
        {"$addToSet": {"members": user_id}}
    )
    if result.modified_count:
        col("players").update_one({"user_id": user_id}, {"$set": {"party_id": party_id}})
        return True
    return False


def send_party_invite(from_id, to_id):
    col("party_invites").delete_many({"from_id": from_id, "to_id": to_id, "status": "pending"})
    col("party_invites").insert_one({
        "from_id": from_id, "to_id": to_id,
        "status": "pending", "created_at": datetime.now()
    })


def get_pending_invite(to_id):
    doc = col("party_invites").find_one(
        {"to_id": to_id, "status": "pending"},
        sort=[("_id", DESCENDING)]
    )
    if doc:
        doc.pop("_id", None)
        return doc
    return None


def resolve_invite(from_id, to_id, status):
    col("party_invites").update_one(
        {"from_id": from_id, "to_id": to_id},
        {"$set": {"status": status}}
    )


# ── Clans ─────────────────────────────────────────────────────────────────

def get_clan(clan_id):
    doc = col("clans").find_one({"id": clan_id})
    if doc:
        doc.pop("_id", None)
        # Ensure members is a list
        if isinstance(doc.get("members"), str):
            try: doc["members"] = json.loads(doc["members"])
            except: doc["members"] = []
        return doc
    return None


def get_clan_by_name(name):
    doc = col("clans").find_one({"name": {"$regex": f"^{name}$", "$options": "i"}})
    if doc:
        doc.pop("_id", None)
        if isinstance(doc.get("members"), str):
            try: doc["members"] = json.loads(doc["members"])
            except: doc["members"] = []
        return doc
    return None


def get_player_clan(user_id):
    player = get_player(user_id)
    if player and player.get("clan_id"):
        return get_clan(player["clan_id"])
    return None


def get_clan_members(clan_data):
    members = clan_data.get("members", [])
    if isinstance(members, str):
        try: return json.loads(members)
        except: return []
    return members if isinstance(members, list) else []


# ── Clan Treasury ─────────────────────────────────────────────────────────

def get_clan_treasury(clan_id):
    doc = col("clans").find_one({"id": clan_id})
    if not doc:
        return []
    treasury = doc.get("treasury", [])
    if isinstance(treasury, str):
        try: return json.loads(treasury)
        except: return []
    return treasury if isinstance(treasury, list) else []


def add_to_clan_treasury(clan_id, item_name, quantity=1):
    clan = col("clans").find_one({"id": clan_id})
    if not clan:
        return
    treasury = get_clan_treasury(clan_id)
    existing = next((i for i in treasury if i["item_name"] == item_name), None)
    if existing:
        existing["quantity"] += quantity
    else:
        treasury.append({"item_name": item_name, "quantity": quantity})
    col("clans").update_one({"id": clan_id}, {"$set": {"treasury": treasury}})


def remove_from_clan_treasury(clan_id, item_name, quantity=1):
    treasury = get_clan_treasury(clan_id)
    item = next((i for i in treasury if i["item_name"] == item_name), None)
    if not item or item["quantity"] < quantity:
        return False
    item["quantity"] -= quantity
    treasury = [i for i in treasury if i["quantity"] > 0]
    col("clans").update_one({"id": clan_id}, {"$set": {"treasury": treasury}})
    return True


def add_clan_xp(clan_id, xp):
    col("clans").update_one({"id": clan_id}, {"$inc": {"xp": xp}})


# ── Duels ─────────────────────────────────────────────────────────────────

def get_db_raw():
    """Return raw pymongo db for handlers that use get_db_raw() directly."""
    return get_raw_db()


# ── Admin ─────────────────────────────────────────────────────────────────

def is_admin(user_id):
    return col("admins").find_one({"user_id": user_id}) is not None


# ── Leaderboard ───────────────────────────────────────────────────────────

def get_leaderboard(category, limit=10):
    if category == "slayers":
        docs = col("players").find({"faction": "slayer"}).sort("demons_slain", DESCENDING).limit(limit)
    elif category == "demons":
        docs = col("players").find({"faction": "demon"}).sort("demons_slain", DESCENDING).limit(limit)
    elif category == "richest":
        docs = col("players").find().sort("yen", DESCENDING).limit(limit)
    elif category == "kills":
        docs = col("players").find().sort("demons_slain", DESCENDING).limit(limit)
    elif category == "level":
        docs = col("players").find().sort("xp", DESCENDING).limit(limit)
    elif category == "sp":
        docs = col("players").find().sort("skill_points", DESCENDING).limit(limit)
    else:
        return []
    result = []
    for d in docs:
        d.pop("_id", None)
        result.append(d)
    return result


# ── Raid ──────────────────────────────────────────────────────────────────

def get_active_raid():
    doc = col("raids").find_one({"status": {"$in": ["waiting", "active"]}},
                                sort=[("_id", DESCENDING)])
    if doc:
        doc.pop("_id", None)
        return doc
    return None


def get_raid_participants(raid_id):
    return [{k: v for k, v in d.items() if k != "_id"}
            for d in col("raid_participants").find({"raid_id": raid_id})]


# ── Daily / Gift ──────────────────────────────────────────────────────────

def get_gift_count_today(from_id):
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return col("gift_log").count_documents({
        "from_id": from_id,
        "gifted_at": {"$gte": today}
    })


# ── Bank ──────────────────────────────────────────────────────────────────

def get_bank(user_id):
    doc = col("bank_accounts").find_one({"user_id": user_id})
    if doc:
        doc.pop("_id", None)
        return doc
    return None


def ensure_bank(user_id):
    col("bank_accounts").update_one(
        {"user_id": user_id},
        {"$setOnInsert": {
            "user_id": user_id, "balance": 0,
            "bank_level": 1, "last_interest": datetime.now(),
            "daily_deposit_total": 0, "daily_tax_paid": 0,
            "daily_deposit_date": datetime.now().strftime("%Y-%m-%d"),
            "bank_level": 1, "last_interest": datetime.now()
        }},
        upsert=True
    )


# ── Skill Tree ────────────────────────────────────────────────────────────

def get_player_skills(user_id):
    """
    Read skills from the new schema: {"user_id": x, "owned_skills": [...]}
    Falls back to old per-row schema for backwards compatibility.
    """
    doc = col("skill_tree").find_one({"user_id": user_id, "owned_skills": {"$exists": True}})
    if doc:
        owned = doc.get("owned_skills", [])
        return owned if isinstance(owned, list) else []
    # Old schema fallback — migrate on read
    old_rows = list(col("skill_tree").find({"user_id": user_id, "skill_name": {"$exists": True}}))
    if old_rows:
        skills = [r["skill_name"] for r in old_rows if r.get("skill_name")]
        if skills:
            # Migrate to new schema
            col("skill_tree").delete_many({"user_id": user_id, "skill_name": {"$exists": True}})
            col("skill_tree").update_one(
                {"user_id": user_id},
                {"$set": {"user_id": user_id, "owned_skills": skills}},
                upsert=True
            )
        return skills
    return []


def buy_skill(user_id, skill_name, sp_cost):
    """Legacy buy_skill — kept for compatibility. New code uses skilltree.py."""
    player = get_player(user_id)
    if not player or player.get("skill_points", 0) < sp_cost:
        return False
    owned = get_player_skills(user_id)
    if skill_name in owned:
        return False
    owned.append(skill_name)
    col("skill_tree").update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "owned_skills": owned}},
        upsert=True
    )
    col("players").update_one({"user_id": user_id}, {"$inc": {"skill_points": -sp_cost}})
    return True


# ── Status Effects ────────────────────────────────────────────────────────

def get_status_effects(user_id):
    return [{k: v for k, v in d.items() if k != "_id"}
            for d in col("status_effects").find({"user_id": user_id})]


def apply_status_effect(user_id, effect, turns):
    col("status_effects").update_one(
        {"user_id": user_id, "effect": effect},
        {"$set": {"user_id": user_id, "effect": effect, "turns_left": turns}},
        upsert=True
    )


def tick_status_effects(user_id):
    col("status_effects").update_many(
        {"user_id": user_id},
        {"$inc": {"turns_left": -1}}
    )
    col("status_effects").delete_many({"user_id": user_id, "turns_left": {"$lte": 0}})
    return get_status_effects(user_id)


def clear_status_effects(user_id):
    col("status_effects").delete_many({"user_id": user_id})


# ── Market ────────────────────────────────────────────────────────────────

def get_market_listings(search=None):
    query = {"status": "active"}
    if search:
        query["item_name"] = {"$regex": search, "$options": "i"}
    # Keep _id so market_buy can do atomic updates
    results = []
    for d in col("market_listings").find(query).sort("_id", DESCENDING):
        row = dict(d)  # keeps _id as ObjectId
        results.append(row)
    return results


def get_listing(listing_id):
    try:
        lid = int(listing_id)
    except Exception:
        lid = listing_id
    doc = col("market_listings").find_one({"id": lid})
    if not doc:
        # fallback: try by _id position
        docs = list(col("market_listings").find({"status": "active"}))
        if 0 < lid <= len(docs):
            doc = docs[lid - 1]
    if doc:
        # Inject sequential id if missing
        if "id" not in doc:
            doc["id"] = lid
        doc.pop("_id", None)
        return doc
    return None


# ── Referrals ─────────────────────────────────────────────────────────────

def add_referral(referrer_id, referred_id):
    if referrer_id == referred_id:
        return False
    try:
        col("referrals").insert_one({
            "referrer_id": referrer_id,
            "referred_id": referred_id,
            "rewarded": 0,
            "created_at": datetime.now()
        })
        return True
    except Exception:
        return False


def get_referral_count(user_id):
    return col("referrals").count_documents({"referrer_id": user_id})


def get_referral_earnings(user_id):
    count = get_referral_count(user_id)
    return count * 500, count * 500


def was_referred(user_id):
    return col("referrals").find_one({"referred_id": user_id}) is not None


def get_referrer(user_id):
    doc = col("referrals").find_one({"referred_id": user_id})
    return doc["referrer_id"] if doc else None


# ── Compatibility shims ───────────────────────────────────────────────────
# Some handlers call get_db() directly and use .execute(SQL).
# This shim wraps MongoDB so those calls work transparently.

class _MongoCompat:
    """
    Shim that intercepts raw SQL calls from handlers and routes
    them to MongoDB operations.
    """
    def __init__(self):
        self._db = get_raw_db()

    def execute(self, sql, params=()):
        sql = sql.strip()
        return _MongoResult(sql, params, self._db)

    def commit(self): pass
    def close(self):  pass

    def __getitem__(self, key):
        return self._db[key]


class _MongoResult:
    """Wraps MongoDB query results to look like sqlite3 cursor results."""
    def __init__(self, sql, params, db):
        self._db    = db
        self._sql   = sql.upper()
        self._params= params
        self._rows  = []
        self._run()

    def _run(self):
        sql = self._sql
        p   = self._params
        db  = self._db

        # SELECT * FROM players WHERE user_id = ?
        if "FROM PLAYERS WHERE USER_ID" in sql:
            uid = p[0] if p else None
            doc = db.players.find_one({"user_id": uid})
            self._rows = [_DictRow(doc)] if doc else []

        elif "FROM PLAYERS WHERE LOWER(USERNAME)" in sql:
            uname = p[0] if p else ""
            doc = db.players.find_one({"username": {"$regex": f"^{uname}$", "$options": "i"}})
            self._rows = [_DictRow(doc)] if doc else []

        elif "FROM PLAYERS WHERE" in sql and "FACTION" in sql:
            faction = p[0] if p else None
            docs = list(db.players.find({"faction": faction}).sort("demons_slain", DESCENDING).limit(5))
            self._rows = [_DictRow(d) for d in docs]

        elif "FROM PLAYERS" in sql and "ORDER BY" in sql:
            if "YEN" in sql:
                docs = list(db.players.find().sort("yen", DESCENDING).limit(5))
            else:
                docs = list(db.players.find().sort("demons_slain", DESCENDING).limit(5))
            self._rows = [_DictRow(d) for d in docs]

        elif "FROM CLANS WHERE ID" in sql:
            cid = p[0] if p else None
            doc = db.clans.find_one({"id": cid})
            self._rows = [_DictRow(doc)] if doc else []

        elif "FROM CLANS WHERE LOWER(NAME)" in sql:
            name = p[0] if p else ""
            doc = db.clans.find_one({"name": {"$regex": f"^{name}$", "$options": "i"}})
            self._rows = [_DictRow(doc)] if doc else []

        elif "FROM DUELS WHERE" in sql:
            if "CHALLENGER_ID" in sql and "TARGET_ID" in sql and len(p) >= 2:
                doc = db.duels.find_one({
                    "$or": [
                        {"challenger_id": p[0], "target_id": p[1]},
                        {"challenger_id": p[1], "target_id": p[0]},
                    ],
                    "status": {"$in": ["pending", "active"]}
                })
            elif len(p) >= 2:
                doc = db.duels.find_one({
                    "$or": [{"challenger_id": p[0]}, {"target_id": p[0]}],
                    "status": "active"
                })
            else:
                doc = None
            self._rows = [_DictRow(doc)] if doc else []

        elif "COUNT(*)" in sql:
            self._rows = [_CountRow(0)]

        elif "UPDATE " in sql or "INSERT " in sql or "DELETE " in sql:
            self._rows = []

        else:
            self._rows = []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __iter__(self):
        return iter(self._rows)


class _DictRow(dict):
    """Dict that also supports integer index access."""
    def __init__(self, doc):
        if doc is None:
            super().__init__()
            self._vals = []
        else:
            clean = {k: v for k, v in doc.items() if k != "_id"}
            super().__init__(clean)
            self._vals = list(clean.values())

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return super().__getitem__(key)

    def __bool__(self):
        return bool(self._vals)


class _CountRow:
    def __init__(self, n):
        self._n = n
    def __getitem__(self, key):
        return self._n
    def get(self, key, default=None):
        return self._n


def get_db():
    """Returns the compat shim for handlers using raw SQL."""
    return _MongoCompat()


def get_listing_by_index(index):
    """Get market listing by sequential display index (1-based)."""
    items = list(col("market_listings").find({"status": "active"}).sort("_id", 1))
    idx = int(index) - 1
    if 0 <= idx < len(items):
        item = dict(items[idx])
        oid = item.pop("_id", None)
        item["_id_str"] = str(oid) if oid else None
        item["display_id"] = idx + 1
        return item
    return None


def ensure_player_fields():
    """Ensure all players have new fields (MongoDB schemaless — just update missing ones)."""
    col("players").update_many(
        {"hybrid_style": {"$exists": False}},
        {"$set": {"hybrid_style": None, "hybrid_emoji": None, "demon_mark": 0}}
    )


def ensure_referral_milestones():
    """Ensure players have referral_milestones_claimed field."""
    col("players").update_many(
        {"referral_milestones_claimed": {"$exists": False}},
        {"$set": {"referral_milestones_claimed": []}}
    )


def apply_style_stat_bonus(user_id, style_name):
    """Apply legendary/ultra legendary stat bonuses when style is assigned."""
    from config import BREATHING_STYLES, DEMON_ARTS
    all_styles = BREATHING_STYLES + DEMON_ARTS
    style = next((s for s in all_styles if s['name'] == style_name), None)
    if not style or not style.get('stat_bonus'):
        return
    player = get_player(user_id)
    if not player:
        return
    bonus = style['stat_bonus']
    updates = {}
    for stat, val in bonus.items():
        if stat == 'max_hp':
            updates['max_hp'] = player.get('max_hp', 200) + val
            updates['hp']     = player.get('hp', 200) + val
        elif stat == 'max_sta':
            updates['max_sta'] = player.get('max_sta', 150) + val
            updates['sta']     = player.get('sta', 150) + val
        else:
            updates[stat] = player.get(stat, 0) + val
    if updates:
        col("players").update_one({"user_id": user_id}, {"$set": updates})

