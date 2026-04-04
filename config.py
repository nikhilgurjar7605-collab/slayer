import os
from pathlib import Path


def _bootstrap_env() -> None:
    """Load local .env values for direct runs without overriding host env vars."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if (
                not line
                or line.startswith("#")
                or line.startswith("<<<<<<<")
                or line.startswith("=======")
                or line.startswith(">>>>>>>")
                or "=" not in line
            ):
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            if any(ch.isspace() for ch in key):
                continue
            if "\x00" in key:
                continue
            os.environ.setdefault(key, value.strip().strip('"').strip("'"))
        return

    load_dotenv(env_path, override=False)


_bootstrap_env()

BOT_TOKEN    = os.environ.get("BOT_TOKEN",    "8712603093:AAFf_CtiohzHfwzxjhHT9xlgdm_34hM7MDQ")
BOT_USERNAME = os.environ.get("BOT_USERNAME", "DemonSlayerXbot")
MONGO_URL    = os.environ.get("MONGO_URL",    "mongodb+srv://yesvashisht2005_db_user:rjuAwTHG8qO6545f@cluster0.nwvwqpj.mongodb.net/?appName=Cluster0")
DB_PATH = None  # Legacy — not used with MongoDB

# ═══════════════════════════════════════════════════
# ADMIN SETUP — FILL THESE IN BEFORE RUNNING THE BOT
# ═══════════════════════════════════════════════════
#
# HOW TO GET YOUR TELEGRAM USER ID:
#   1. Open Telegram and message @userinfobot
#   2. It will reply with your numeric user ID (e.g. 123456789)
#   3. Paste that number below as OWNER_ID
#
# OWNER_ID = The bot owner (you). Full control over everything.
# SUDO_ADMIN_IDS = List of trusted admins. Can use admin commands
#                  but cannot ban/reset players or add more admins.
#
# Example:
#   OWNER_ID = 123456789
#   SUDO_ADMIN_IDS = [987654321, 111222333]
#
OWNER_ID = int(os.environ.get("OWNER_ID", 1214273889))  # Set env var or replace 0
SUDO_ADMIN_IDS = []     # <-- Add trusted admin IDs here, e.g. [123456789, 987654321]
# ═══════════════════════════════════════════════════

# Game Settings
MAX_PARTY_SIZE = 3
MIN_RAID_PLAYERS = 20
STARTING_YEN = 1000
STARTING_HP = 200
STARTING_STA = 150
STARTING_STR = 20
STARTING_SPD = 18
STARTING_DEF = 15

# Breathing Styles for gacha
# Rarity weights for gacha: COMMON=50%, RARE=30%, LEGENDARY=15%, ULTRA=5%
# Stone Breathing: extremely rare — only one true user can exist
BREATHING_STYLES = [
    # ── COMMON ────────────────────────────────────────────────────────────
    {"name": "Water Breathing",   "emoji": "💧", "rarity": "⭐⭐ COMMON",          "gacha_weight": 18, "image": "images/breathing/water.jpg",   "image_url": "",  "description": "Calm as still water, fierce as a raging river."},
    {"name": "Wind Breathing",    "emoji": "🌬️", "rarity": "⭐⭐ COMMON",          "gacha_weight": 18, "image": "images/breathing/wind.jpg",    "image_url": "",  "description": "Wild, unpredictable, fierce as a howling storm."},
    {"name": "Insect Breathing",  "emoji": "🦋", "rarity": "⭐⭐ COMMON",          "gacha_weight": 16, "image": "images/breathing/insect.jpg",  "image_url": "",  "description": "Swift and precise, like a butterfly's deadly sting."},
    {"name": "Flame Breathing",   "emoji": "🔥", "rarity": "⭐⭐ COMMON",          "gacha_weight": 16, "image": "images/breathing/flame.jpg",   "image_url": "",  "description": "Burn bright, burn fierce, never be extinguished."},
    {"name": "Flower Breathing",  "emoji": "🌸", "rarity": "⭐⭐ COMMON",          "gacha_weight": 14, "image": "images/breathing/flower.jpg",  "image_url": "",  "description": "Graceful yet lethal, blooming with deadly precision."},
    # ── RARE ──────────────────────────────────────────────────────────────
    {"name": "Thunder Breathing", "emoji": "⚡", "rarity": "⭐⭐⭐ RARE",          "gacha_weight": 8,  "image": "images/breathing/thunder.jpg", "image_url": "",  "description": "Strike like lightning before the enemy can blink."},
    {"name": "Mist Breathing",    "emoji": "🌫️", "rarity": "⭐⭐⭐ RARE",          "gacha_weight": 7,  "image": "images/breathing/mist.jpg",    "image_url": "",  "description": "Elusive, mysterious, impossible to grasp."},
    {"name": "Serpent Breathing", "emoji": "🐍", "rarity": "⭐⭐⭐ RARE",          "gacha_weight": 6,  "image": "images/breathing/serpent.jpg", "image_url": "",  "description": "Twisted, cunning, deceptive as a coiling serpent."},
    {"name": "Love Breathing",    "emoji": "💗", "rarity": "⭐⭐⭐ RARE",          "gacha_weight": 5,  "image": "images/breathing/love.jpg",    "image_url": "",  "description": "Passionate and fierce, fueled by overwhelming emotion."},
    {"name": "Sound Breathing",   "emoji": "🔊", "rarity": "⭐⭐⭐ RARE",          "gacha_weight": 5,  "image": "images/breathing/sound.jpg",   "image_url": "",  "description": "Explosive, overwhelming, shatters everything."},
    {"name": "Beast Breathing",   "emoji": "🐗", "rarity": "⭐⭐⭐ RARE",          "gacha_weight": 5,  "image": "images/breathing/beast.jpg",   "image_url": "",  "description": "Wild and ferocious, mimicking the raw power of beasts."},
    # ── LEGENDARY ─────────────────────────────────────────────────────────
    {"name": "Stone Breathing",   "emoji": "🪨", "rarity": "⭐⭐⭐⭐⭐ LEGENDARY",  "gacha_weight": 3,  "stat_bonus": {"str_stat": 8, "def_stat": 10, "max_hp": 50},  "image": "images/breathing/stone.jpg",   "image_url": "",  "description": "The strongest Hashira breathing. Immovable, unstoppable."},
    {"name": "Moon Breathing",    "emoji": "🌙", "rarity": "⭐⭐⭐⭐⭐ LEGENDARY",  "gacha_weight": 2,  "stat_bonus": {"str_stat": 6, "spd": 8, "max_hp": 30},  "image": "images/breathing/moon.jpg",    "image_url": "",  "description": "Mysterious, sweeping, deadly as the night itself."},
    {"name": "Sun Breathing",     "emoji": "☀️", "rarity": "⭐⭐⭐⭐⭐ LEGENDARY",  "gacha_weight": 1,  "stat_bonus": {"str_stat": 10, "spd": 10, "def_stat": 5, "max_hp": 80},  "image": "images/breathing/sun.jpg",     "image_url": "",  "description": "The origin of all breathing. The pinnacle of the blade."},
]

# Demon Arts for gacha
# Demon Arts for gacha
# ULTRA LEGENDARY: Absolute Biokinesis — only ONE player can hold it at a time
DEMON_ARTS = [
    # ── COMMON ────────────────────────────────────────────────────────────
    {"name": "Blood Whip",            "emoji": "🩸", "rarity": "⭐⭐ COMMON",         "gacha_weight": 18, "description": "Manipulate your own blood as a razor-sharp weapon."},
    {"name": "Spider Manipulation",   "emoji": "🕸️", "rarity": "⭐⭐ COMMON",         "gacha_weight": 17, "description": "Control threads of steel and manipulate others."},
    {"name": "Water Manipulation",    "emoji": "🌊", "rarity": "⭐⭐ COMMON",         "gacha_weight": 16, "description": "Control water as a deadly weapon."},
    {"name": "Ink Manipulation",      "emoji": "🖤", "rarity": "⭐⭐ COMMON",         "gacha_weight": 15, "description": "Control dark ink that blinds and suffocates foes."},
    # ── RARE ──────────────────────────────────────────────────────────────
    {"name": "Explosive Flames",      "emoji": "💥", "rarity": "⭐⭐⭐ RARE",         "gacha_weight": 10, "description": "Detonate anything you touch with deadly force."},
    {"name": "Corpse Puppeteering",   "emoji": "💀", "rarity": "⭐⭐⭐ RARE",         "gacha_weight": 9,  "description": "Reanimate the dead to fight in your place."},
    {"name": "Poison Demon Art",      "emoji": "☠️", "rarity": "⭐⭐⭐ RARE",         "gacha_weight": 8,  "description": "Corrode and rot the enemy from within with lethal venom."},
    {"name": "Biokinesis",            "emoji": "🧬", "rarity": "⭐⭐⭐ RARE",         "gacha_weight": 7,  "description": "Reshape flesh and bone — lower-level body manipulation."},
    # ── LEGENDARY ─────────────────────────────────────────────────────────
    {"name": "Spatial Warping",       "emoji": "🌀", "rarity": "⭐⭐⭐⭐⭐ LEGENDARY", "gacha_weight": 2,  "stat_bonus": {"spd": 10, "str_stat": 5, "max_sta": 40},  "description": "Bend and twist dimensions to disorient and destroy."},
    {"name": "Ice Manipulation",      "emoji": "❄️", "rarity": "⭐⭐⭐⭐⭐ LEGENDARY", "gacha_weight": 2,  "stat_bonus": {"def_stat": 8, "str_stat": 6, "max_hp": 40},  "description": "Freeze and shatter enemies with absolute zero cold."},
    {"name": "Shockwave Martial Art", "emoji": "👊", "rarity": "⭐⭐⭐⭐⭐ LEGENDARY", "gacha_weight": 2,  "stat_bonus": {"str_stat": 12, "spd": 8, "max_hp": 60},  "description": "Akaza-style — devastating shockwave fists of a demon god."},
    # ── ULTRA LEGENDARY ───────────────────────────────────────────────────
    {"name": "Absolute Biokinesis",   "emoji": "👁️", "rarity": "🌑 ULTRA LEGENDARY", "gacha_weight": 0,  "stat_bonus": {"str_stat": 20, "spd": 15, "def_stat": 15, "max_hp": 150, "max_sta": 80},  "description": "Muzan's Blood Demon Art. The pinnacle of all demon power. Only one being in the world can wield this."},
]

# TECHNIQUES — forms for each art/style used in battle
TECHNIQUES = {
    "Water Breathing": [
        {"form": 1,  "name": "Water Surface Slash", "dmg_min": 28, "dmg_max": 38,  "sta_cost": 15, "type": "opener",    "effect": "flow_start",
         "desc": "Grants Flow if used first in battle (once per battle)."},
        {"form": 2,  "name": "Water Wheel",         "dmg_min": 22, "dmg_max": 32,  "sta_cost": 19, "type": "linker",    "effect": "flow_boost",   "hits": 2,
         "desc": "Hits twice. Strengthens Flow if Flow is active."},
        {"form": 3,  "name": "Flowing Dance",       "dmg_min": 22, "dmg_max": 32,  "sta_cost": 18, "type": "defensive", "effect": "flow_defense", "max_uses": 2, "cooldown": 3,
         "desc": "Evasion bonus; reduces dmg from next 2 hits. (3-turn CD; max 2 uses)"},
        {"form": 4,  "name": "Striking Tide",       "dmg_min": 34, "dmg_max": 46,  "sta_cost": 22, "type": "punish",    "effect": "flow_punish",
         "desc": "Extra damage if used after a defensive Water form in the previous turn."},
        {"form": 5,  "name": "Blessed Rain",        "dmg_min": 40, "dmg_max": 43,  "sta_cost": 34, "type": "sustain",   "effect": "flow_sustain",
         "desc": "Self-heal, stamina recovery, and cleanses 1 bleed stack."},
        {"form": 6,  "name": "Whirlpool",           "dmg_min": 46, "dmg_max": 48,  "sta_cost": 40, "type": "control",   "effect": "flow_control",  "unlock_rank": "Kinoe",
         "desc": "Staggers 1 action; removes enemy dodge/escape capabilities."},
        {"form": 10, "name": "Constant Flux",       "dmg_min": 57, "dmg_max": 64,  "sta_cost": 60, "type": "finisher",  "effect": "flow_finisher", "unlock_rank": "Hashira",
         "desc": "60% power raw. Full power only if Sustain + Defensive forms were used prior."},
    ],
    "Flame Breathing": [
        {"form": 1, "name": "Unknowing Fire",            "dmg_min": 34, "dmg_max": 48,  "sta_cost": 15, "type": "opener",    "effect": "burn_apply",   "burn_chance": 90,
         "desc": "90% chance to apply Burn (5-6 turns; stops regen)."},
        {"form": 2, "name": "Rising Scorching Sun",      "dmg_min": 32, "dmg_max": 44,  "sta_cost": 20, "type": "chase",     "effect": "burn_chase",
         "desc": "Bonus damage if target is already Burning."},
        {"form": 3, "name": "Blazing Universe",          "dmg_min": 42, "dmg_max": 46,  "sta_cost": 25, "type": "mid_burst", "effect": "burn_burst",
         "desc": "Higher crit pressure if used after another Flame form."},
        {"form": 4, "name": "Blooming Flame Undulation", "dmg_min": 41, "dmg_max": 54,  "sta_cost": 30, "type": "punish",    "effect": "burn_punish",   "unlock_rank": "Kinoe",
         "desc": "Removes combo stack; reduces next incoming attack dmg by 20%."},
        {"form": 9, "name": "Rengoku",                   "dmg_min": 58, "dmg_max": 71, "sta_cost": 65, "type": "finisher",  "effect": "burn_execute",  "unlock_rank": "Hashira",
         "desc": "Extra damage if target below 50% HP and Burning."},
    ],
    # Demon arts
    "Blood Whip": [
        {"form": 1, "name": "Blood Lash",      "dmg_min": 34, "dmg_max": 48, "sta_cost": 18, "type": "opener",   "effect": "bleed_apply",  "vulnerable_chance": 40,
         "desc": "Applies Bleed 1; 40% chance Vulnerable (removed after 1 hit)."},
        {"form": 2, "name": "Crimson Cage",    "dmg_min": 40, "dmg_max": 43, "sta_cost": 24, "type": "trap",     "effect": "bleed_extend",
         "desc": "+1 Bleed stack; extends bleed duration; halves enemy dodge/escape."},
        {"form": 3, "name": "Scarlet Torrent", "dmg_min": 44, "dmg_max": 59, "sta_cost": 38, "type": "finisher", "effect": "bleed_payoff",
         "desc": "Bonus dmg per Bleed stack; self-heal; stamina refund; stagger chance."},
    ],

    # ── NEW BREATHING STYLES ──────────────────────────────────────────────

    # ── NEW DEMON ARTS ────────────────────────────────────────────────────
    "Ice Manipulation": [
        {"form": 1,  "name": "Frost Strike",              "dmg_min": 45,  "dmg_max": 49,  "sta_cost": 18,  "effect": "freeze_apply"},
        {"form": 2,  "name": "Ice Lance Barrage",         "dmg_min": 44,  "dmg_max": 58,  "sta_cost": 24,  "hits": 2},
        {"form": 3,  "name": "Glacier Crush",             "dmg_min": 54,  "dmg_max": 61,  "sta_cost": 32,  "effect": "freeze_apply"},
        {"form": 4,  "name": "Absolute Zero Field",       "dmg_min": 61,  "dmg_max": 78, "sta_cost": 50,  "unlock_rank": "Lower Moon 3"},
        {"form": 5,  "name": "Crystal Lotus Bloom",       "dmg_min": 60,  "dmg_max": 66,  "sta_cost": 42,  "effect": "ice_shatter",  "desc": "AOE — Reduces enemy DEF by 15 for 3 turns"},
        {"form": 6,  "name": "Blizzard Veil",             "dmg_min": 40,  "dmg_max": 44,  "sta_cost": 38,  "effect": "ice_blind",    "desc": "30% chance enemy misses next physical attack"},
        {"form": 7,  "name": "Frozen Spine Impalement",   "dmg_min": 64,  "dmg_max": 82, "sta_cost": 55,  "effect": "ice_bleed",    "desc": "Bleed: 12 DOT for 2 turns"},
        {"form": 8,  "name": "Arctic Soul Devourer",      "dmg_min": 77, "dmg_max": 94, "sta_cost": 70,  "effect": "frostburn",    "desc": "Frostburn: drains 10 STA/turn", "unlock_rank": "Upper Moon 6"},
        {"form": 9,  "name": "Mirror of the Ice Queen",   "dmg_min": 87, "dmg_max": 105, "sta_cost": 85,  "effect": "ice_counter",  "desc": "Reflects 20% incoming DMG for 1 turn"},
        {"form": 10, "name": "Permafrost Calamity",       "dmg_min": 112, "dmg_max": 147, "sta_cost": 115, "effect": "deep_freeze",  "desc": "Deep Freeze: skip next 2 enemy turns (100%)", "unlock_rank": "Upper Moon 4"},
        {"form": 11, "name": "Absolute Glacier Prison",   "dmg_min": 129, "dmg_max": 168, "sta_cost": 130, "effect": "freeze_apply",  "desc": "Freeze + 30% dmg bonus on next form", "unlock_rank": "Upper Moon 4", "hits": 2},
        {"form": 12, "name": "Thousand Ice Needles",      "dmg_min": 140, "dmg_max": 182, "sta_cost": 145, "effect": "ice_bleed",     "desc": "Bleed: 15 DOT × 3 turns + 12% crit bonus this battle", "unlock_rank": "Upper Moon 3", "hits": 3},
        {"form": 13, "name": "Eternal Winter Domain",     "dmg_min": 154, "dmg_max": 199, "sta_cost": 160, "effect": "ice_shatter",   "desc": "AOE: DEF -20 for 4 turns + Frostburn applied", "unlock_rank": "Upper Moon 3"},
        {"form": 14, "name": "Soul of the Glacier",       "dmg_min": 175, "dmg_max": 224, "sta_cost": 185, "effect": "frostburn",     "desc": "Frostburn 15 STA/t × 4 turns + 20% crit boost", "unlock_rank": "Upper Moon 2"},
        {"form": 15, "name": "Absolute Zero: World End",  "dmg_min": 210, "dmg_max": 280, "sta_cost": 220, "effect": "deep_freeze",   "desc": "ULTIMATE: Deep Freeze + Frostburn + Shatter simultaneously", "unlock_rank": "Upper Moon 1"},
    ],
    "Shockwave Martial Art": [
        {"form": 1, "name": "Destructive Death: Compass Needle",  "dmg_min": 48, "dmg_max": 62, "sta_cost": 22},
        {"form": 2, "name": "Destructive Death: Annihilation",    "dmg_min": 56, "dmg_max": 62, "sta_cost": 30},
        {"form": 3, "name": "Destructive Death: Frenzy",          "dmg_min": 56, "dmg_max": 71, "sta_cost": 38, "hits": 2},
        {"form": 4, "name": "Eight Layered Demon Core",           "dmg_min": 70, "dmg_max": 89, "sta_cost": 55, "unlock_rank": "Upper Moon 6"},
    ],
    "Poison Demon Art": [
        {"form": 1, "name": "Venom Slash",              "dmg_min": 38, "dmg_max": 41, "sta_cost": 16, "poison": True, "effect": "poison_apply"},
        {"form": 2, "name": "Toxic Cloud",              "dmg_min": 45, "dmg_max": 48, "sta_cost": 22, "poison": True, "effect": "poison_aoe"},
        {"form": 3, "name": "Necrotic Flood",           "dmg_min": 46, "dmg_max": 60, "sta_cost": 28, "poison": True},
        {"form": 4, "name": "Death Miasma",             "dmg_min": 60, "dmg_max": 67, "sta_cost": 40, "poison": True, "unlock_rank": "Lower Moon 3"},
    ],

    # ── ULTRA LEGENDARY ──────────────────────────────────────────────────
    "Absolute Biokinesis": [
        {"form": 1, "name": "Blood Cell Reconstruction",  "dmg_min": 62,  "dmg_max": 80, "sta_cost": 30, "effect": "regen"},
        {"form": 2, "name": "Flesh Fortress",             "dmg_min": 70, "dmg_max": 91, "sta_cost": 35, "effect": "barrier"},
        {"form": 3, "name": "Cellular Annihilation",      "dmg_min": 84, "dmg_max": 108, "sta_cost": 45, "effect": "poison_apply"},
        {"form": 4, "name": "Morphic Catastrophe",        "dmg_min": 98, "dmg_max": 125, "sta_cost": 55, "unlock_rank": "Upper Moon 3"},
        {"form": 5, "name": "Demon King's Domain",        "dmg_min": 125, "dmg_max": 161, "sta_cost": 80, "unlock_rank": "Upper Moon 1"},
    ],

    # ── EXPANDED FORMS ────────────────────────────────────────────────────

    # Thunder Breathing (add Forms 5, 7)
    "Thunder Breathing": [
        {"form": 1, "name": "Thunderclap and Flash",     "dmg_min": 40, "dmg_max": 52, "sta_cost": 20, "type": "opener",
         "desc": "Blinding speed strike — 20% chance to Stun enemy."},
        {"form": 2, "name": "Rice Spirit",               "dmg_min": 40, "dmg_max": 44, "sta_cost": 18, "type": "multi",   "hits": 2,
         "desc": "Two rapid slashes — each hit stacks pressure."},
        {"form": 3, "name": "Thunder Swarm",             "dmg_min": 35, "dmg_max": 40, "sta_cost": 22, "type": "barrage", "hits": 3,
         "desc": "Three rapid hits — deals bonus damage against stunned enemies."},
        {"form": 5, "name": "Heat Lightning",            "dmg_min": 48, "dmg_max": 62, "sta_cost": 32, "type": "punish",  "unlock_rank": "Kinoe",
         "desc": "Unleashes lightning pressure — reduces enemy SPD for 2 turns."},
        {"form": 6, "name": "Rumble and Flash",          "dmg_min": 56, "dmg_max": 62, "sta_cost": 45, "type": "finisher","unlock_rank": "Kinoe",
         "desc": "Thunder + speed combo — 40% Stun chance on hit.", "effect": "stun_chance"},
        {"form": 7, "name": "Honoikazuchi no Kami",      "dmg_min": 66, "dmg_max": 84,"sta_cost": 65, "type": "ultimate","unlock_rank": "Hashira",
         "desc": "God of Thunder — guaranteed Stun + massive lightning damage.", "effect": "stun_apply"},
    ],

    # Wind Breathing (add Forms 4-7)
    "Wind Breathing": [
        {"form": 1, "name": "Dust Whirlwind Cutter",     "dmg_min": 35, "dmg_max": 48, "sta_cost": 18, "type": "opener",
         "desc": "Wide slashing arc — hits all (single target in bot)."},
        {"form": 2, "name": "Claws Purifying Wind",      "dmg_min": 30, "dmg_max": 45, "sta_cost": 15, "type": "multi",  "hits": 2,
         "desc": "Twin-blade slash — each claw hits separately."},
        {"form": 3, "name": "Clean Storm Wind Tree",     "dmg_min": 40, "dmg_max": 44, "sta_cost": 22, "type": "control",
         "desc": "Spinning wind strike — 30% chance to Exhaust enemy.", "effect": "exhaust_chance"},
        {"form": 4, "name": "Rising Winds",              "dmg_min": 40, "dmg_max": 52, "sta_cost": 28, "type": "chase",   "unlock_rank": "Kinoe",
         "desc": "Ascending storm — bonus damage if used after Form 3."},
        {"form": 5, "name": "Gale Storm Slash",          "dmg_min": 48, "dmg_max": 62, "sta_cost": 35, "type": "barrage", "hits": 3, "unlock_rank": "Kinoe",
         "desc": "Three-hit storm barrage — each hit deals wind pressure damage."},
        {"form": 9, "name": "Idaten Typhoon",            "dmg_min": 59, "dmg_max": 73,"sta_cost": 60, "type": "ultimate","unlock_rank": "Hashira",
         "desc": "God of Wind — hurricane damage with 50% Exhaust.", "effect": "exhaust_apply"},
    ],

    # Stone Breathing (add Forms 3-7)
    "Stone Breathing": [
        {"form": 1, "name": "Serpentinite Bipolar",      "dmg_min": 45, "dmg_max": 46, "sta_cost": 20, "type": "opener",
         "desc": "Two-direction split strike — high base damage."},
        {"form": 2, "name": "Volcanic Rock Rapid Conquest","dmg_min": 40, "dmg_max": 44,"sta_cost": 18, "type": "barrage","hits": 2,
         "desc": "Rapid stone strikes — each hit reduces enemy DEF."},
        {"form": 3, "name": "Stone Skin",                "dmg_min": 35, "dmg_max": 40, "sta_cost": 22, "type": "defensive",
         "desc": "Harden skin — reduce all incoming damage by 20% for 3 turns.", "effect": "def_buff"},
        {"form": 4, "name": "Crushing Boulder",         "dmg_min": 44, "dmg_max": 57, "sta_cost": 28, "type": "punish",  "unlock_rank": "Kinoe",
         "desc": "Massive impact — 35% chance to Stagger enemy.", "effect": "stagger_chance"},
        {"form": 5, "name": "Arcs of Justice",          "dmg_min": 60, "dmg_max": 66, "sta_cost": 50, "type": "finisher","unlock_rank": "Kinoe",
         "desc": "Devastating arc slash — extra damage when enemy is staggered."},
        {"form": 6, "name": "Mountainous Avalanche",    "dmg_min": 62, "dmg_max": 80,"sta_cost": 60, "type": "ultimate","unlock_rank": "Hashira",
         "desc": "Unleash a mountain's force — guaranteed Stagger + massive damage.", "effect": "stagger_apply"},
    ],

    # Serpent Breathing (add Forms 4-6)
    "Serpent Breathing": [
        {"form": 1, "name": "Winding Serpent Slash",    "dmg_min": 38, "dmg_max": 41, "sta_cost": 18, "type": "opener",
         "desc": "Deceptive curved strike — applies Vulnerable 25%."},
        {"form": 2, "name": "Venom Fangs of Narrow Eyes","dmg_min": 42, "dmg_max": 44,"sta_cost": 22, "type": "poison",   "effect": "poison_apply",
         "desc": "Venomous stab — applies Poison (5 turns)."},
        {"form": 3, "name": "Coil Choke",               "dmg_min": 35, "dmg_max": 48, "sta_cost": 20, "type": "control",  "effect": "stagger_apply",
         "desc": "Binding coil attack — Stagger enemy 1 turn."},
        {"form": 4, "name": "Twin Headed Reptile",      "dmg_min": 41, "dmg_max": 54, "sta_cost": 28, "type": "multi",    "hits": 2, "unlock_rank": "Kinoe",
         "desc": "Double-headed strike — 2 hits, each can apply Poison."},
        {"form": 5, "name": "Slithering Viper",         "dmg_min": 52, "dmg_max": 57, "sta_cost": 38, "type": "finisher", "unlock_rank": "Kinoe",
         "desc": "Rapid serpent lunge — bonus damage per Poison stack active."},
        {"form": 6, "name": "King Cobra",               "dmg_min": 59, "dmg_max": 73,"sta_cost": 55, "type": "ultimate", "effect": "deep_poison", "unlock_rank": "Hashira",
         "desc": "Lethal bite — applies Deep Poison (5%/turn × 4 turns).", },
    ],

    # Mist Breathing (add Forms 3-7)
    "Mist Breathing": [
        {"form": 1, "name": "Low Clouds Distant Haze",  "dmg_min": 35, "dmg_max": 40, "sta_cost": 15, "type": "opener",
         "desc": "Deceptive invisible slash — 25% Confusion chance.", "effect": "confuse_chance"},
        {"form": 2, "name": "Eight Layered Mist",       "dmg_min": 40, "dmg_max": 44, "sta_cost": 20, "type": "multi",    "hits": 2,
         "desc": "Layered phantom strikes — hard to dodge."},
        {"form": 3, "name": "Scattering Mist Splash",   "dmg_min": 45, "dmg_max": 48, "sta_cost": 25, "type": "control",  "effect": "confuse_apply",
         "desc": "Disorienting mist — applies Confusion (2 turns).", "unlock_rank": "Kinoe"},
        {"form": 4, "name": "Shifting Flow Slash",      "dmg_min": 44, "dmg_max": 57, "sta_cost": 30, "type": "evasive",  "unlock_rank": "Kinoe",
         "desc": "Strike from the mist — +20% dodge rate this turn."},
        {"form": 5, "name": "Sea of Mist and Mountains","dmg_min": 52, "dmg_max": 58, "sta_cost": 38, "type": "control",  "unlock_rank": "Kinoe",
         "desc": "Dense mist — Confuses enemy and reduces their ATK 15%."},
        {"form": 6, "name": "Scattering Mist Slash",    "dmg_min": 56, "dmg_max": 61, "sta_cost": 45, "type": "finisher", "unlock_rank": "Kinoe"},
        {"form": 7, "name": "Obscuring Clouds",         "dmg_min": 56, "dmg_max": 70,"sta_cost": 55, "type": "ultimate", "effect": "confuse_apply", "unlock_rank": "Hashira",
         "desc": "Total obscurity — Confusion + Exhaust combo."},
    ],

    # Love Breathing (add Forms 3-8)
    "Love Breathing": [
        {"form": 1, "name": "Shivers of First Love",    "dmg_min": 40, "dmg_max": 52, "sta_cost": 22, "type": "opener",
         "desc": "Passionate opener — applies Vulnerable 30%."},
        {"form": 2, "name": "Love Pangs",               "dmg_min": 44, "dmg_max": 56, "sta_cost": 25, "type": "multi",    "hits": 2,
         "desc": "Double heartbeat — two strikes with fire intent."},
        {"form": 3, "name": "Anguish",                  "dmg_min": 48, "dmg_max": 62, "sta_cost": 30, "type": "punish",
         "desc": "Channel grief into power — bonus dmg if HP below 50%."},
        {"form": 4, "name": "Burning Passion",          "dmg_min": 52, "dmg_max": 58, "sta_cost": 35, "type": "buff",     "unlock_rank": "Kinoe",
         "desc": "Fiery resolve — +15% ATK for next 3 turns.", "effect": "atk_buff"},
        {"form": 5, "name": "Joyful Dance",             "dmg_min": 56, "dmg_max": 61, "sta_cost": 40, "type": "barrage",  "hits": 3, "unlock_rank": "Kinoe",
         "desc": "Spinning triple strike — dance of destruction."},
        {"form": 6, "name": "Cat Legged Winds of Love", "dmg_min": 60, "dmg_max": 66, "sta_cost": 48, "type": "finisher", "unlock_rank": "Hashira",
         "desc": "Ultimate love technique — inflicts Confusion on hit.", "effect": "confuse_apply"},
    ],

    # Sound Breathing (add Forms 2-4)
    "Sound Breathing": [
        {"form": 1, "name": "Roar",                     "dmg_min": 44, "dmg_max": 57, "sta_cost": 25, "type": "opener",   "effect": "exhaust_chance",
         "desc": "Ear-splitting roar — 30% chance to Exhaust enemy."},
        {"form": 2, "name": "Explosive Rush",           "dmg_min": 48, "dmg_max": 62, "sta_cost": 30, "type": "barrage",  "hits": 2,
         "desc": "Dual explosive slashes — shockwave with each hit."},
        {"form": 3, "name": "Warcry",                   "dmg_min": 40, "dmg_max": 54, "sta_cost": 28, "type": "buff",
         "desc": "Battle shout — raises own ATK +20% and Exhausts enemy.", "effect": "exhaust_apply"},
        {"form": 4, "name": "Constant Resounding Slashes","dmg_min": 52, "dmg_max": 57,"sta_cost": 35,"type": "barrage",  "hits": 3,
         "desc": "Three rapid sonic slashes — each reduces enemy STA."},
        {"form": 5, "name": "String Performance",       "dmg_min": 56, "dmg_max": 70,"sta_cost": 50, "type": "ultimate", "effect": "exhaust_apply", "unlock_rank": "Hashira",
         "desc": "Ultimate music of battle — massive damage + Exhaust enemy."},
    ],

    # Insect Breathing (add Forms 3-5)
    "Insect Breathing": [
        {"form": 1, "name": "Butterfly Dance Caprice",  "dmg_min": 30, "dmg_max": 45, "sta_cost": 15, "type": "opener",   "effect": "poison_apply", "poison": True,
         "desc": "Fluttering venomous strike — applies Poison."},
        {"form": 2, "name": "Dance of the Bee Sting",   "dmg_min": 35, "dmg_max": 40, "sta_cost": 18, "type": "multi",    "hits": 2, "effect": "poison_apply", "poison": True,
         "desc": "Double sting — both hits can apply Poison."},
        {"form": 3, "name": "Dance of the Centipede",   "dmg_min": 40, "dmg_max": 44, "sta_cost": 22, "type": "barrage",  "hits": 3, "effect": "poison_apply", "poison": True,
         "desc": "Rapid multi-hit — each hit has poison chance."},
        {"form": 4, "name": "Dragonfly Dance",          "dmg_min": 45, "dmg_max": 48, "sta_cost": 25, "type": "evasive",  "poison": True,
         "desc": "Swift aerial — +20% dodge this turn, poisons on hit."},
        {"form": 5, "name": "Compound Eye Hexagon",     "dmg_min": 44, "dmg_max": 57, "sta_cost": 35, "type": "ultimate", "effect": "deep_poison",  "poison": True, "unlock_rank": "Hashira",
         "desc": "Full insect assault — applies Deep Poison.", },
    ],

    # Moon Breathing (add Forms 3-9)
    "Moon Breathing": [
        {"form": 1, "name": "Dark Moon Evening Palace", "dmg_min": 44, "dmg_max": 56, "sta_cost": 25, "type": "opener",   "effect": "freeze_apply",
         "desc": "Cold moonlit slash — 40% Freeze chance."},
        {"form": 2, "name": "Pearl Flower Moongazing",  "dmg_min": 48, "dmg_max": 60, "sta_cost": 28, "type": "multi",    "hits": 2,
         "desc": "Twin moon strikes — both can Freeze."},
        {"form": 3, "name": "Loathsome Moon Wolfbane",  "dmg_min": 52, "dmg_max": 57, "sta_cost": 32, "type": "control",  "effect": "freeze_apply",
         "desc": "Howling freeze — Freezes enemy (no techniques 2t)."},
        {"form": 4, "name": "Shifting Universe",        "dmg_min": 56, "dmg_max": 61, "sta_cost": 36, "type": "evasive",  "unlock_rank": "Kinoe",
         "desc": "Dimensional slash — +20% evasion this turn."},
        {"form": 5, "name": "Moon Spirit Calamitous Eddy","dmg_min": 56, "dmg_max": 70,"sta_cost": 50,"type": "finisher","unlock_rank": "Kinoe",
         "desc": "Spiraling moon energy — bonus damage if Freeze active."},
        {"form": 9, "name": "Waning Moonlit Slumber",   "dmg_min": 73,"dmg_max": 91,"sta_cost": 70, "type": "ultimate", "effect": "freeze_apply", "unlock_rank": "Hashira",
         "desc": "The ultimate moon form — guaranteed Freeze + massive cold damage."},
    ],

    # Sun Breathing (add Forms 4-12)
    "Sun Breathing": [
        {"form": 1, "name": "Dance",                    "dmg_min": 48, "dmg_max": 62, "sta_cost": 25, "type": "opener",
         "desc": "Flowing solar opener — cleanses 1 debuff on self."},
        {"form": 2, "name": "Clear Blue Sky",           "dmg_min": 52, "dmg_max": 57, "sta_cost": 28, "type": "multi",    "hits": 2,
         "desc": "Twin solar strikes — heavenly light."},
        {"form": 3, "name": "Raging Sun",               "dmg_min": 56, "dmg_max": 61, "sta_cost": 32, "type": "control",  "effect": "burn_apply",
         "desc": "Solar heat strike — applies Burn (90% chance)."},
        {"form": 4, "name": "Fake Rainbow",             "dmg_min": 60, "dmg_max": 65, "sta_cost": 36, "type": "evasive",  "unlock_rank": "Kinoe",
         "desc": "Illusory solar arc — +30% dodge this turn."},
        {"form": 5, "name": "Setting Sun Transformation","dmg_min": 56,"dmg_max": 70,"sta_cost": 42, "type": "punish",   "unlock_rank": "Kinoe",
         "desc": "Sunset slash — bonus damage if enemy HP below 60%."},
        {"form": 6, "name": "Solar Heat Haze",          "dmg_min": 59, "dmg_max": 73,"sta_cost": 48, "type": "control",  "effect": "confuse_apply", "unlock_rank": "Kinoe",
         "desc": "Mirage of the sun — Confusion on hit."},
        {"form": 7, "name": "Beneficent Radiance",      "dmg_min": 62, "dmg_max": 78,"sta_cost": 54, "type": "sustain",  "unlock_rank": "Kinoe",
         "desc": "Radiant light — heal 8% HP + cleanse 1 debuff."},
        {"form": 10, "name": "Sunflower Thrust",        "dmg_min": 66, "dmg_max": 84,"sta_cost": 58, "type": "barrage",  "hits": 3, "unlock_rank": "Hashira",
         "desc": "Piercing solar barrage — 3 hits of pure solar energy."},
        {"form": 12, "name": "Flame Dance",             "dmg_min": 70,"dmg_max": 91,"sta_cost": 70, "type": "ultimate", "effect": "burn_apply",    "unlock_rank": "Hashira",
         "desc": "The pinnacle Sun form — guaranteed Burn + execute damage."},
    ],

    # Flower Breathing (keep existing, add Forms 7+)
    "Flower Breathing": [
        {"form": 1, "name": "Scarlet Windflower",       "dmg_min": 38, "dmg_max": 41, "sta_cost": 16, "type": "opener"},
        {"form": 2, "name": "Honorable Shadow Plum",    "dmg_min": 42, "dmg_max": 46, "sta_cost": 20, "type": "multi",    "hits": 2},
        {"form": 3, "name": "Peonies of Futility",      "dmg_min": 48, "dmg_max": 52, "sta_cost": 24, "type": "control",  "effect": "confuse_chance"},
        {"form": 4, "name": "Crimson Hanagoromo",       "dmg_min": 44, "dmg_max": 57, "sta_cost": 30, "type": "punish",   "unlock_rank": "Kinoe"},
        {"form": 5, "name": "Peonies of Futility EX",  "dmg_min": 52, "dmg_max": 59, "sta_cost": 38, "type": "barrage",  "hits": 2, "unlock_rank": "Kinoe"},
        {"form": 6, "name": "Whirling Peach",           "dmg_min": 57, "dmg_max": 73,"sta_cost": 55, "type": "ultimate", "effect": "confuse_apply", "unlock_rank": "Hashira"},
    ],

    # Beast Breathing (keep existing, add Forms 7-10)
    "Beast Breathing": [
        {"form": 1, "name": "Sudden Throwing Strike",   "dmg_min": 40, "dmg_max": 44, "sta_cost": 18, "type": "opener"},
        {"form": 2, "name": "Hilt Strike",              "dmg_min": 38, "dmg_max": 41, "sta_cost": 16, "type": "stagger",  "effect": "stagger_chance"},
        {"form": 3, "name": "Devour",                   "dmg_min": 45, "dmg_max": 48, "sta_cost": 22, "type": "sustain",
         "desc": "Devour enemy life force — self-heal 5% HP."},
        {"form": 4, "name": "Slice and Dice",           "dmg_min": 40, "dmg_max": 52, "sta_cost": 25, "type": "barrage",  "hits": 2},
        {"form": 5, "name": "Crazy Cutting",            "dmg_min": 44, "dmg_max": 57, "sta_cost": 28, "type": "barrage",  "hits": 2, "unlock_rank": "Kinoe"},
        {"form": 6, "name": "Palisade Bite",            "dmg_min": 56, "dmg_max": 62, "sta_cost": 45, "type": "punish",   "unlock_rank": "Kinoe",
         "desc": "Savage bite — applies Bleed.", "effect": "bleed_apply"},
        {"form": 8, "name": "Explosive Rush",           "dmg_min": 56, "dmg_max": 70,"sta_cost": 55, "type": "chase",    "unlock_rank": "Kinoe"},
        {"form": 10, "name": "Whirling Fangs",          "dmg_min": 64, "dmg_max": 82,"sta_cost": 65, "type": "ultimate", "unlock_rank": "Hashira",
         "desc": "Berserk spinning fangs — guaranteed Bleed + Stagger.", "effect": "bleed_apply"},
    ],

    # ── DEMON ARTS — EXPANDED ─────────────────────────────────────────────

    "Spider Manipulation": [
        {"form": 1, "name": "Steel Thread Slash",       "dmg_min": 43, "dmg_max": 49, "sta_cost": 15, "type": "opener"},
        {"form": 2, "name": "Web Cocoon",               "dmg_min": 37, "dmg_max": 41, "sta_cost": 18, "type": "control",  "effect": "stagger_apply",
         "desc": "Encase in web — Staggers enemy."},
        {"form": 3, "name": "Spider Fang Barrage",      "dmg_min": 40, "dmg_max": 54, "sta_cost": 22, "type": "barrage",  "hits": 3,
         "desc": "Triple fang strike — each can apply Poison."},
        {"form": 4, "name": "Thread Manipulation",      "dmg_min": 44, "dmg_max": 58, "sta_cost": 28, "type": "control",  "effect": "freeze_apply",
         "desc": "Thread bind — prevents enemy technique use."},
        {"form": 5, "name": "Thousand Spider Army",     "dmg_min": 56, "dmg_max": 62, "sta_cost": 40, "type": "ultimate",
         "desc": "Unleash a swarm — massive multi-hit + Poison.", "effect": "poison_apply"},
    ],

    "Explosive Flames": [
        {"form": 1, "name": "Finger Bomb",              "dmg_min": 44, "dmg_max": 60, "sta_cost": 20, "type": "opener",   "effect": "burn_apply"},
        {"form": 2, "name": "Chain Explosion",          "dmg_min": 54, "dmg_max": 62, "sta_cost": 28, "type": "barrage",  "hits": 2, "effect": "burn_apply"},
        {"form": 3, "name": "Hellfire Blast",           "dmg_min": 60, "dmg_max": 78,"sta_cost": 40, "type": "finisher", "effect": "burn_apply",
         "desc": "Massive explosion — guaranteed Burn + max fire."},
        {"form": 4, "name": "Detonation Field",         "dmg_min": 60, "dmg_max": 66, "sta_cost": 35, "type": "control",  "effect": "exhaust_apply",
         "desc": "Explosive pressure — Exhausts enemy from shockwave."},
        {"form": 5, "name": "Armageddon Blast",         "dmg_min": 70,"dmg_max": 91,"sta_cost": 60, "type": "ultimate", "effect": "burn_apply",
         "desc": "Total annihilation — Burn + Stagger + execute chance."},
    ],

    "Corpse Puppeteering": [
        {"form": 1, "name": "Dead Man Slash",           "dmg_min": 47, "dmg_max": 52, "sta_cost": 18, "type": "opener"},
        {"form": 2, "name": "Puppet Barrage",           "dmg_min": 44, "dmg_max": 60, "sta_cost": 25, "type": "barrage",  "hits": 3},
        {"form": 3, "name": "Army of the Dead",         "dmg_min": 60, "dmg_max": 70,"sta_cost": 38, "type": "sustain",
         "desc": "Raise the dead — 10% HP regen per turn for 3 turns.", "effect": "regen_apply"},
        {"form": 4, "name": "Corpse Shield",            "dmg_min": 40, "dmg_max": 44, "sta_cost": 22, "type": "defensive",
         "desc": "Shield yourself with corpses — block next 2 hits."},
        {"form": 5, "name": "Death March",              "dmg_min": 62, "dmg_max": 80,"sta_cost": 55, "type": "ultimate",  "effect": "curse_apply",
         "desc": "Send the army — Curse + heavy damage."},
    ],

    "Water Manipulation": [
        {"form": 1, "name": "Water Whip",               "dmg_min": 43, "dmg_max": 48, "sta_cost": 15, "type": "opener"},
        {"form": 2, "name": "Tidal Crush",              "dmg_min": 44, "dmg_max": 60, "sta_cost": 22, "type": "punish",   "effect": "stagger_chance"},
        {"form": 3, "name": "Tsunami Strike",           "dmg_min": 57, "dmg_max": 65, "sta_cost": 35, "type": "finisher",
         "desc": "Wave crash — bonus damage if enemy Staggered."},
        {"form": 4, "name": "Water Prison",             "dmg_min": 48, "dmg_max": 62, "sta_cost": 30, "type": "control",  "effect": "freeze_apply",
         "desc": "Water prison orb — Freezes enemy."},
        {"form": 5, "name": "Maelstrom",                "dmg_min": 59, "dmg_max": 77,"sta_cost": 50, "type": "ultimate", "effect": "exhaust_apply",
         "desc": "Raging vortex — Exhausts + Staggers enemy."},
    ],

    "Ink Manipulation": [
        {"form": 1, "name": "Ink Slash",                "dmg_min": 40, "dmg_max": 45, "sta_cost": 15, "type": "opener"},
        {"form": 2, "name": "Blind Flood",              "dmg_min": 47, "dmg_max": 52, "sta_cost": 20, "type": "control",  "effect": "confuse_apply",
         "desc": "Ink flood blinds enemy — Confusion 2 turns."},
        {"form": 3, "name": "Black Ocean",              "dmg_min": 49, "dmg_max": 56, "sta_cost": 30, "type": "control",  "effect": "exhaust_apply",
         "desc": "Drown in ink — Exhaust + bonus damage."},
        {"form": 4, "name": "Suffocation Wave",         "dmg_min": 56, "dmg_max": 62, "sta_cost": 38, "type": "barrage",  "hits": 2,
         "desc": "Ink barrage — dual smothering hits."},
        {"form": 5, "name": "Ink Dimension",            "dmg_min": 61, "dmg_max": 78,"sta_cost": 52, "type": "ultimate", "effect": "confuse_apply",
         "desc": "Inky void — Confusion + Exhaust + damage."},
    ],

    "Biokinesis": [
        {"form": 1, "name": "Flesh Blade",              "dmg_min": 54, "dmg_max": 60, "sta_cost": 25, "type": "opener"},
        {"form": 2, "name": "Body Spike Barrage",       "dmg_min": 60, "dmg_max": 67, "sta_cost": 30, "type": "barrage",  "hits": 3},
        {"form": 3, "name": "True Form Unleash",        "dmg_min": 74,"dmg_max": 95,"sta_cost": 55, "type": "finisher",
         "desc": "Unleash demon body — massive dmg."},
        {"form": 4, "name": "Cell Regeneration",        "dmg_min": 40, "dmg_max": 44, "sta_cost": 20, "type": "sustain",
         "desc": "Regenerate cells — heal 12% HP.", "effect": "regen_apply"},
        {"form": 5, "name": "Flesh Fortress",           "dmg_min": 59, "dmg_max": 77,"sta_cost": 50, "type": "defensive",
         "desc": "Armored flesh — reduce incoming damage 25% for 2 turns."},
    ],

    "Spatial Warping": [
        {"form": 1, "name": "Dimensional Slash",        "dmg_min": 49, "dmg_max": 59, "sta_cost": 25, "type": "opener",   "effect": "confuse_chance"},
        {"form": 2, "name": "Space Collapse",           "dmg_min": 60, "dmg_max": 67, "sta_cost": 32, "type": "control",  "effect": "confuse_apply",
         "desc": "Collapse space — Confusion 2 turns."},
        {"form": 3, "name": "Void Rend",                "dmg_min": 65, "dmg_max": 82,"sta_cost": 45, "type": "finisher",
         "desc": "Tear open reality — bonus vs Confused enemies."},
        {"form": 4, "name": "Dimensional Prison",       "dmg_min": 56, "dmg_max": 72,"sta_cost": 40, "type": "control",  "effect": "freeze_apply",
         "desc": "Trap in space — Freeze enemy.", "unlock_rank": "Upper Moon 6"},
        {"form": 5, "name": "Reality Erasure",          "dmg_min": 77,"dmg_max": 98,"sta_cost": 65, "type": "ultimate", "effect": "confuse_apply",
         "desc": "Erase from space — guaranteed Confusion + execute.", "unlock_rank": "Upper Moon 3"},
    ],

}

# Ensure every technique form can carry its own image or URL metadata.
for _style_ref in (BREATHING_STYLES + DEMON_ARTS):
    _style_ref.setdefault("image", "")
    _style_ref.setdefault("image_url", "")

_TECHNIQUE_STYLE_LOOKUP = {style["name"]: style for style in (BREATHING_STYLES + DEMON_ARTS)}
for _art_name, _forms in TECHNIQUES.items():
    _style_ref = _TECHNIQUE_STYLE_LOOKUP.get(_art_name, {})
    for _form in _forms:
        _form.setdefault("image_url", _style_ref.get("image_url", ""))
        _form.setdefault("image", _style_ref.get("image", ""))

# SKILL TREE — buyable with SP
SKILLS = {
    # ══════════════════════════════════════════════════════════════════
    # COMBAT
    # ══════════════════════════════════════════════════════════════════
    "Combat": [
        {"name": "Iron Body",          "sp_cost": 5,  "type": "passive",
         "description": "-10% damage taken",
         "bonus": {"dmg_reduce": 0.10}},
        {"name": "Battle Instinct",    "sp_cost": 5,  "type": "passive",
         "description": "+10% attack damage",
         "bonus": {"atk_pct": 0.10}},
        {"name": "Sharp Eye",          "sp_cost": 8,  "type": "passive",
         "description": "+12% crit chance",
         "bonus": {"crit_bonus": 0.12}},
        {"name": "Swift Feet",         "sp_cost": 8,  "type": "passive",
         "description": "+12% dodge chance",
         "bonus": {"dodge_bonus": 0.12}},
        {"name": "Endurance",          "sp_cost": 8,  "type": "passive",
         "description": "+30 Max HP",
         "bonus": {"max_hp": 30}},
        {"name": "Stamina Mastery",    "sp_cost": 8,  "type": "passive",
         "description": "+30 Max STA",
         "bonus": {"max_sta": 30}},
        {"name": "Bloodlust",          "sp_cost": 10, "type": "passive",
         "description": "+20% ATK when below 40% HP. Backlash: -5% DEF always",
         "bonus": {"low_hp_dmg": 0.20, "def_pct": -0.05}},
        {"name": "Berserker",          "sp_cost": 13, "type": "passive",
         "description": "+20% ATK. Backlash: -15% DEF",
         "bonus": {"atk_pct": 0.20, "def_pct": -0.15}},
        {"name": "Executioner",        "sp_cost": 13, "type": "passive",
         "description": "+35% dmg when enemy <20% HP",
         "bonus": {"executioner": 0.35}},
        {"name": "Second Wind",        "sp_cost": 13, "type": "once_per_battle",
         "description": "Once: 30% chance survive fatal hit at 1 HP",
         "bonus": {"second_wind": 0.30}},
        {"name": "War Cry",            "sp_cost": 14, "type": "once_per_battle",
         "description": "Once: gain +80 HP at battle start. Backlash: -8% DEF",
         "bonus": {"battle_hp_boost": 80, "def_pct": -0.08}},
        {"name": "Devour Soul",        "sp_cost": 16, "type": "passive",
         "description": "+8% regen per turn + +20 HP at battle start. Backlash: -5 MaxSTA",
         "bonus": {"regen_pct": 0.08, "battle_hp_boost": 20, "max_sta": -5}},
        {"name": "Precision Strike",   "sp_cost": 10, "type": "passive",
         "description": "+15% crit. Backlash: -8% dodge",
         "bonus": {"crit_bonus": 0.15, "dodge_bonus": -0.08}},
        {"name": "Titan Grip",         "sp_cost": 10, "type": "passive",
         "description": "+15% ATK, +10 MaxHP. Backlash: -5 MaxSTA",
         "bonus": {"atk_pct": 0.15, "max_hp": 10, "max_sta": -5}},
        {"name": "Fortress",           "sp_cost": 10, "type": "passive",
         "description": "-12% dmg taken, +10 MaxHP. Backlash: -8% ATK",
         "bonus": {"dmg_reduce": 0.12, "max_hp": 10, "atk_pct": -0.08}},
        {"name": "Glass Cannon",       "sp_cost": 13, "type": "passive",
         "description": "+35% ATK. Backlash: -25% DEF",
         "bonus": {"atk_pct": 0.35, "def_pct": -0.25}},
        {"name": "Steel Nerves",       "sp_cost": 12, "type": "passive",
         "description": "+50 HP at battle start, +8% crit",
         "bonus": {"battle_hp_boost": 50, "crit_bonus": 0.08}},
    ],
    # ══════════════════════════════════════════════════════════════════
    # TECHNIQUE
    # ══════════════════════════════════════════════════════════════════
    "Technique": [
        {"name": "Form Mastery",       "sp_cost": 8,  "type": "passive",
         "description": "+12% technique damage",
         "bonus": {"tech_pct": 0.12}},
        {"name": "Quick Form",         "sp_cost": 8,  "type": "passive",
         "description": "-4 STA per form use",
         "bonus": {"sta_reduce": 4}},
        {"name": "Combo Master",       "sp_cost": 12, "type": "passive",
         "description": "+15% combo damage",
         "bonus": {"combo_pct": 0.15}},
        {"name": "Multi Art",          "sp_cost": 15, "type": "passive",
         "description": "Unlock using scroll arts in battle",
         "bonus": {"multi_art": True}},
        {"name": "Finisher",           "sp_cost": 20, "type": "passive",
         "description": "+30% dmg when enemy <20% HP",
         "bonus": {"finish_pct": 0.30}},
        {"name": "Art Prodigy",        "sp_cost": 12, "type": "passive",
         "description": "+20% technique damage. Backlash: -5% dodge",
         "bonus": {"tech_pct": 0.20, "dodge_bonus": -0.05}},
        {"name": "Endless Stamina",    "sp_cost": 15, "type": "passive",
         "description": "+40 MaxSTA, -5 STA per form",
         "bonus": {"max_sta": 40, "sta_reduce": 5}},
        {"name": "Death Blow",         "sp_cost": 20, "type": "once_per_battle",
         "description": "Once: +50% form damage on activation",
         "bonus": {"finish_pct": 0.50}},
        {"name": "Flow State",         "sp_cost": 15, "type": "passive",
         "description": "+15% TECH, +10% combo. Backlash: +3 STA cost",
         "bonus": {"tech_pct": 0.15, "combo_pct": 0.10, "sta_reduce": -3}},
        {"name": "STA Saver",          "sp_cost": 12, "type": "passive",
         "description": "-7 STA per form use",
         "bonus": {"sta_reduce": 7}},
        {"name": "Art Awakening",      "sp_cost": 18, "type": "once_per_battle",
         "description": "Once: +30% TECH + gain 60 HP at battle start",
         "bonus": {"tech_pct": 0.30, "battle_hp_boost": 60}},
    ],
    # ══════════════════════════════════════════════════════════════════
    # SURVIVAL
    # ══════════════════════════════════════════════════════════════════
    "Survival": [
        {"name": "Regeneration",       "sp_cost": 8,  "type": "passive",
         "description": "Regenerate 4% MaxHP per turn",
         "bonus": {"regen_pct": 0.04}},
        {"name": "Demon Regen",        "sp_cost": 12, "type": "passive",
         "description": "+6 flat HP per turn. Backlash: -5 MaxSTA",
         "bonus": {"regen_hp": 6, "max_sta": -5}},
        {"name": "Last Stand",         "sp_cost": 12, "type": "once_per_battle",
         "description": "Once: survive fatal blow at 1 HP",
         "bonus": {"last_stand": True}},
        {"name": "Counter Strike",     "sp_cost": 12, "type": "passive",
         "description": "+20% counter chance. Backlash: -5% crit",
         "bonus": {"counter_chance": 0.20, "crit_bonus": -0.05}},
        {"name": "Focus",              "sp_cost": 8,  "type": "passive",
         "description": "+12% XP from battles",
         "bonus": {"xp_pct": 0.12}},
        {"name": "Treasure Hunter",    "sp_cost": 8,  "type": "passive",
         "description": "+20% item drop chance",
         "bonus": {"drop_pct": 0.20}},
        {"name": "Merchant Eye",       "sp_cost": 5,  "type": "passive",
         "description": "+8% Yen from battles",
         "bonus": {"yen_pct": 0.08}},
        {"name": "Null Status",        "sp_cost": 16, "type": "passive",
         "description": "Immune to all status effects. Backlash: -10% ATK",
         "bonus": {"null_status": True, "atk_pct": -0.10}},
        {"name": "First Strike",       "sp_cost": 12, "type": "passive",
         "description": "+15% dmg on first attack",
         "bonus": {"first_strike": 0.15}},
        {"name": "Fortune",            "sp_cost": 12, "type": "passive",
         "description": "+15% Yen, +12% XP",
         "bonus": {"yen_pct": 0.15, "xp_pct": 0.12}},
        {"name": "Iron Lungs",         "sp_cost": 8,  "type": "passive",
         "description": "+35 MaxSTA",
         "bonus": {"max_sta": 35}},
        {"name": "Vital Core",         "sp_cost": 8,  "type": "passive",
         "description": "+35 MaxHP",
         "bonus": {"max_hp": 35}},
        {"name": "Scavenger",          "sp_cost": 12, "type": "passive",
         "description": "+30% item drops",
         "bonus": {"drop_pct": 0.30}},
        {"name": "Quick Recovery",     "sp_cost": 12, "type": "passive",
         "description": "+6% HP regen per turn. Backlash: -4% dodge",
         "bonus": {"regen_pct": 0.06, "dodge_bonus": -0.04}},
        {"name": "Battle Hardened",    "sp_cost": 16, "type": "passive",
         "description": "-15% dmg taken, +20 MaxHP. Backlash: -10% ATK",
         "bonus": {"dmg_reduce": 0.15, "max_hp": 20, "atk_pct": -0.10}},
        {"name": "Aura Shield",        "sp_cost": 14, "type": "once_per_battle",
         "description": "Once: gain +100 HP at battle start + -10% dmg taken",
         "bonus": {"battle_hp_boost": 100, "dmg_reduce": 0.10}},
    ],
    # ══════════════════════════════════════════════════════════════════
    # ELITE
    # ══════════════════════════════════════════════════════════════════
    "Elite": [
        {"name": "Hashira Resolve",    "sp_cost": 30, "type": "passive",
         "description": "+12% ATK/DEF/TECH each. Backlash: -15 MaxSTA",
         "bonus": {"atk_pct": 0.12, "def_pct": 0.12, "tech_pct": 0.12, "max_sta": -15}},
        {"name": "God Speed",          "sp_cost": 30, "type": "passive",
         "description": "+25% dodge, +15% crit. Backlash: -10% DEF",
         "bonus": {"dodge_bonus": 0.25, "crit_bonus": 0.15, "def_pct": -0.10}},
        {"name": "Demon King Body",    "sp_cost": 40, "type": "passive",
         "description": "+50 MaxHP, +10 HP/turn regen, Last Stand",
         "bonus": {"max_hp": 50, "regen_hp": 10, "last_stand": True}},
        {"name": "Absolute Form",      "sp_cost": 40, "type": "passive",
         "description": "+30% TECH, -8 STA/form. Backlash: -10% dodge",
         "bonus": {"tech_pct": 0.30, "sta_reduce": 8, "dodge_bonus": -0.10}},
        {"name": "Slaughter Instinct", "sp_cost": 26, "type": "passive",
         "description": "+30% executioner, +8% regen/turn. Backlash: -8% DEF",
         "bonus": {"executioner": 0.30, "regen_pct": 0.08, "def_pct": -0.08}},
        {"name": "Iron Will",          "sp_cost": 22, "type": "once_per_battle",
         "description": "Once: survive fatal hit. -15% dmg taken passively",
         "bonus": {"second_wind": 0.99, "dmg_reduce": 0.15}},
        {"name": "Arcane Bloodline",   "sp_cost": 35, "type": "passive",
         "description": "+25% ATK, +20% TECH, +20% drops. Backlash: -10 MaxSTA",
         "bonus": {"atk_pct": 0.25, "tech_pct": 0.20, "drop_pct": 0.20, "max_sta": -10}},
        {"name": "Limitless",          "sp_cost": 50, "type": "passive",
         "description": "Status immune, +15% ATK/TECH. Backlash: -20 MaxHP",
         "bonus": {"null_status": True, "atk_pct": 0.15, "tech_pct": 0.15, "max_hp": -20}},
        {"name": "Soul Eater",         "sp_cost": 30, "type": "passive",
         "description": "+15% XP/Yen, +8% regen/turn. Backlash: -8% ATK",
         "bonus": {"xp_pct": 0.15, "yen_pct": 0.15, "regen_pct": 0.08, "atk_pct": -0.08}},
        {"name": "Phantom Step",       "sp_cost": 26, "type": "passive",
         "description": "+20% dodge, +20% low-HP dmg, first strike. Backlash: -8% DEF",
         "bonus": {"dodge_bonus": 0.20, "low_hp_dmg": 0.20, "first_strike": 0.20, "def_pct": -0.08}},
        {"name": "Crimson Tide",       "sp_cost": 30, "type": "passive",
         "description": "+20% ATK, +20% low-HP dmg, +6% regen/turn. Backlash: -5% DEF",
         "bonus": {"atk_pct": 0.20, "low_hp_dmg": 0.20, "regen_pct": 0.06, "def_pct": -0.05}},
        {"name": "Warlord",            "sp_cost": 35, "type": "passive",
         "description": "+20% ATK, +18% TECH, +15% crit. Backlash: -12% dodge",
         "bonus": {"atk_pct": 0.20, "tech_pct": 0.18, "crit_bonus": 0.15, "dodge_bonus": -0.12}},
        {"name": "Undying",            "sp_cost": 40, "type": "once_per_battle",
         "description": "Once: +40 MaxHP, regen 8%/turn, Last Stand. Backlash: -10% ATK",
         "bonus": {"max_hp": 40, "regen_pct": 0.08, "last_stand": True, "atk_pct": -0.10}},
        {"name": "Apex Predator",      "sp_cost": 45, "type": "passive",
         "description": "+30% ATK, executioner+20%, +6% regen/turn. Backlash: -15% DEF",
         "bonus": {"atk_pct": 0.30, "executioner": 0.20, "regen_pct": 0.06, "def_pct": -0.15}},
        {"name": "Shadow King",        "sp_cost": 50, "type": "passive",
         "description": "+20% dodge, status immune, +20% TECH. Backlash: -15% ATK",
         "bonus": {"dodge_bonus": 0.20, "null_status": True, "tech_pct": 0.20, "atk_pct": -0.15}},
        {"name": "Dragon Form",        "sp_cost": 60, "type": "once_per_battle",
         "description": "Once: +35% ATK/TECH + 150 HP at battle start. Backlash: -20% DEF",
         "bonus": {"atk_pct": 0.35, "tech_pct": 0.35, "battle_hp_boost": 150, "def_pct": -0.20}},
        {"name": "Juggernaut",         "sp_cost": 32, "type": "passive",
         "description": "+120 HP at battle start, +12% ATK. Backlash: -10% dodge",
         "bonus": {"battle_hp_boost": 120, "atk_pct": 0.12, "dodge_bonus": -0.10}},
    ],
    # ══════════════════════════════════════════════════════════════════
    # DEMON PATH — Powerful demon-exclusive skills
    # ══════════════════════════════════════════════════════════════════
    "Demon Path": [
        {"name": "Blood Hunger",       "sp_cost": 8,  "type": "passive",
         "description": "+15% ATK, +8% regen/turn. Backlash: -5% DEF",
         "bonus": {"atk_pct": 0.15, "regen_pct": 0.08, "def_pct": -0.05}},
        {"name": "Thick Hide",         "sp_cost": 12, "type": "passive",
         "description": "-20% dmg taken, +40 MaxHP. Backlash: -8% ATK",
         "bonus": {"dmg_reduce": 0.20, "max_hp": 40, "atk_pct": -0.08}},
        {"name": "Predator Sense",     "sp_cost": 12, "type": "passive",
         "description": "+20% crit, +15% dodge. Backlash: -5 MaxSTA",
         "bonus": {"crit_bonus": 0.20, "dodge_bonus": 0.15, "max_sta": -5}},
        {"name": "Cell Regeneration",  "sp_cost": 5,  "type": "passive",
         "description": "+12 HP/turn, +5% regen. Backlash: -5% ATK",
         "bonus": {"regen_hp": 12, "regen_pct": 0.05, "atk_pct": -0.05}},
        {"name": "Devourer",           "sp_cost": 18, "type": "passive",
         "description": "+10% regen/turn, +25% crit. Backlash: -10% DEF",
         "bonus": {"regen_pct": 0.10, "crit_bonus": 0.25, "def_pct": -0.10}},
        {"name": "Flesh Fortress",     "sp_cost": 20, "type": "passive",
         "description": "+100 HP at battle start, -15% dmg taken",
         "bonus": {"battle_hp_boost": 100, "dmg_reduce": 0.15}},
        {"name": "True Demon",         "sp_cost": 28, "type": "passive",
         "description": "+25% ATK, -20% dmg, +15 HP/turn. Backlash: -20 MaxSTA",
         "bonus": {"atk_pct": 0.25, "dmg_reduce": 0.20, "regen_hp": 15, "max_sta": -20}},
        {"name": "Demon Surge",        "sp_cost": 25, "type": "once_per_battle",
         "description": "Once: +200 HP at battle start + +25% ATK",
         "bonus": {"battle_hp_boost": 200, "atk_pct": 0.25}},
        {"name": "Muzan Blessing",     "sp_cost": 40, "type": "once_per_battle",
         "description": "Once: +30% ATK, status immune, +20 HP/turn, +150 HP at start",
         "bonus": {"atk_pct": 0.30, "null_status": True, "regen_hp": 20, "battle_hp_boost": 150}},
        {"name": "Blood Frenzy",       "sp_cost": 30, "type": "passive",
         "description": "+30% ATK, +12% regen/turn, +15% crit. Backlash: -15% DEF",
         "bonus": {"atk_pct": 0.30, "regen_pct": 0.12, "crit_bonus": 0.15, "def_pct": -0.15}},
        {"name": "Oni Regeneration",   "sp_cost": 35, "type": "passive",
         "description": "+20 HP/turn, +8% regen, +50 MaxHP. Backlash: -10% ATK",
         "bonus": {"regen_hp": 20, "regen_pct": 0.08, "max_hp": 50, "atk_pct": -0.10}},
        {"name": "Infinity Fortress",  "sp_cost": 50, "type": "passive",
         "description": "+80 MaxHP, -25% dmg, +300 HP at battle start. Backlash: -15% ATK/TECH",
         "bonus": {"max_hp": 80, "dmg_reduce": 0.25, "battle_hp_boost": 300, "atk_pct": -0.15, "tech_pct": -0.15}},
        {"name": "Demon Lord Aura",    "sp_cost": 45, "type": "passive",
         "description": "+35% ATK, +20% TECH, +15 HP/turn. Backlash: -15% dodge",
         "bonus": {"atk_pct": 0.35, "tech_pct": 0.20, "regen_hp": 15, "dodge_bonus": -0.15}},
        {"name": "Muzan's Wrath",      "sp_cost": 55, "type": "once_per_battle",
         "description": "Once: +40% ATK/TECH, +250 HP at start, +20 HP/turn, status immune",
         "bonus": {"atk_pct": 0.40, "tech_pct": 0.40, "battle_hp_boost": 250, "regen_hp": 20, "null_status": True}},
    ],
    # ══════════════════════════════════════════════════════════════════
    # SLAYER PATH
    # ══════════════════════════════════════════════════════════════════
    "Slayer Path": [
        {"name": "Breathing Mastery",  "sp_cost": 8,  "type": "passive",
         "description": "+15% TECH, -4 STA/form",
         "bonus": {"tech_pct": 0.15, "sta_reduce": 4}},
        {"name": "Nichirin Bond",      "sp_cost": 12, "type": "passive",
         "description": "+12% ATK, +8% crit. Backlash: -4% dodge",
         "bonus": {"atk_pct": 0.12, "crit_bonus": 0.08, "dodge_bonus": -0.04}},
        {"name": "Corps Training",     "sp_cost": 12, "type": "passive",
         "description": "+15% DEF, +25 MaxHP. Backlash: -8% ATK",
         "bonus": {"def_pct": 0.15, "max_hp": 25, "atk_pct": -0.08}},
        {"name": "Total Concentration","sp_cost": 20, "type": "passive",
         "description": "+20% TECH, +12% ATK, +50 MaxSTA. Backlash: -15 MaxHP",
         "bonus": {"tech_pct": 0.20, "atk_pct": 0.12, "max_sta": 50, "max_hp": -15}},
        {"name": "Mark Resonance",     "sp_cost": 28, "type": "once_per_battle",
         "description": "Once: +25% ATK, +15% TECH (Slayer Mark synergy)",
         "bonus": {"atk_pct": 0.25, "tech_pct": 0.15}},
        {"name": "Constant Breathing", "sp_cost": 35, "type": "passive",
         "description": "+40 MaxSTA, -10 STA/form, +8% regen. Backlash: -10% crit",
         "bonus": {"max_sta": 40, "sta_reduce": 10, "regen_pct": 0.08, "crit_bonus": -0.10}},
        {"name": "Hashira Ascension",  "sp_cost": 42, "type": "once_per_battle",
         "description": "Once: +30% ATK/TECH, Last Stand, +80 HP at start. Backlash: -20 MaxSTA",
         "bonus": {"atk_pct": 0.30, "tech_pct": 0.30, "last_stand": True, "battle_hp_boost": 80, "max_sta": -20}},
        {"name": "Sun Breathing Aura", "sp_cost": 55, "type": "once_per_battle",
         "description": "Once: +40% TECH/ATK, status immune, +100 HP at start. Backlash: -20% DEF",
         "bonus": {"tech_pct": 0.40, "atk_pct": 0.40, "null_status": True, "battle_hp_boost": 100, "def_pct": -0.20}},
    ],
    # ══════════════════════════════════════════════════════════════════
    # UTILITY
    # ══════════════════════════════════════════════════════════════════
    "Utility": [
        {"name": "Yen Magnet",         "sp_cost": 15, "type": "passive",
         "description": "+20% Yen from battles",
         "bonus": {"yen_pct": 0.20}},
        {"name": "XP Surge",           "sp_cost": 15, "type": "passive",
         "description": "+20% XP from battles",
         "bonus": {"xp_pct": 0.20}},
        {"name": "Lucky Drop",         "sp_cost": 15, "type": "passive",
         "description": "+25% item drop chance",
         "bonus": {"drop_pct": 0.25}},
        {"name": "Hoarder",            "sp_cost": 20, "type": "passive",
         "description": "+30% Yen, +20% drops",
         "bonus": {"yen_pct": 0.30, "drop_pct": 0.20}},
        {"name": "Scholar",            "sp_cost": 20, "type": "passive",
         "description": "+30% XP, +15% Yen",
         "bonus": {"xp_pct": 0.30, "yen_pct": 0.15}},
        {"name": "Gold Rush",          "sp_cost": 30, "type": "passive",
         "description": "+50% Yen, +30% drops",
         "bonus": {"yen_pct": 0.50, "drop_pct": 0.30}},
        {"name": "Master Looter",      "sp_cost": 50, "type": "passive",
         "description": "+50% XP, +50% Yen, +40% drops — endgame grind",
         "bonus": {"xp_pct": 0.50, "yen_pct": 0.50, "drop_pct": 0.40}},
        {"name": "Survivor's Bounty",  "sp_cost": 22, "type": "passive",
         "description": "+25% XP, +20% Yen, +60 HP at battle start",
         "bonus": {"xp_pct": 0.25, "yen_pct": 0.20, "battle_hp_boost": 60}},
    ],
    # ══════════════════════════════════════════════════════════════════
    # PASSIVE
    # ══════════════════════════════════════════════════════════════════
    "Passive": [
        {"name": "Keen Eye",           "sp_cost": 20, "type": "passive",
         "description": "+22% crit. Backlash: -5% dodge",
         "bonus": {"crit_bonus": 0.22, "dodge_bonus": -0.05}},
        {"name": "Ghost Step",         "sp_cost": 20, "type": "passive",
         "description": "+22% dodge. Backlash: -5% crit",
         "bonus": {"dodge_bonus": 0.22, "crit_bonus": -0.05}},
        {"name": "Thick Skin",         "sp_cost": 25, "type": "passive",
         "description": "-22% dmg taken. Backlash: -12% ATK",
         "bonus": {"dmg_reduce": 0.22, "atk_pct": -0.12}},
        {"name": "Killing Blow",       "sp_cost": 25, "type": "passive",
         "description": "+22% dmg <30% HP. Backlash: -5% DEF",
         "bonus": {"low_hp_dmg": 0.22, "def_pct": -0.05}},
        {"name": "Relentless",         "sp_cost": 30, "type": "passive",
         "description": "+18% ATK, -15% dmg. Backlash: -8% crit",
         "bonus": {"atk_pct": 0.18, "dmg_reduce": 0.15, "crit_bonus": -0.08}},
        {"name": "Adrenaline Rush",    "sp_cost": 30, "type": "once_per_battle",
         "description": "Once: 25% survive fatal hit",
         "bonus": {"second_wind": 0.25}},
        {"name": "War Machine",        "sp_cost": 35, "type": "passive",
         "description": "+25% ATK, +22% crit. Backlash: -15% dodge, -8% DEF",
         "bonus": {"atk_pct": 0.25, "crit_bonus": 0.22, "dodge_bonus": -0.15, "def_pct": -0.08}},
        {"name": "Phantom Dodge",      "sp_cost": 35, "type": "passive",
         "description": "+28% dodge, first strike. Backlash: -12% ATK",
         "bonus": {"dodge_bonus": 0.28, "first_strike": 0.15, "atk_pct": -0.12}},
        {"name": "Death's Door",       "sp_cost": 40, "type": "passive",
         "description": "+30% ATK <30% HP, +8% regen/turn. Backlash: -10% DEF",
         "bonus": {"low_hp_dmg": 0.30, "regen_pct": 0.08, "def_pct": -0.10}},
        {"name": "Thousand Cuts",      "sp_cost": 50, "type": "passive",
         "description": "+28% TECH, +22% ATK, +15% combo. Backlash: -12% dodge",
         "bonus": {"tech_pct": 0.28, "atk_pct": 0.22, "combo_pct": 0.15, "dodge_bonus": -0.12, "def_pct": -0.05}},
        {"name": "Resilient Core",     "sp_cost": 28, "type": "passive",
         "description": "+80 HP at battle start, -12% dmg taken, +5% regen",
         "bonus": {"battle_hp_boost": 80, "dmg_reduce": 0.12, "regen_pct": 0.05}},
    ],
    # ══════════════════════════════════════════════════════════════════
    # LEGENDARY
    # ══════════════════════════════════════════════════════════════════
    "Legendary": [
        {"name": "Blood of the Twelve", "sp_cost": 60,  "type": "passive",
         "description": "+30% ATK, +20% DEF, +10% regen/turn. Backlash: -15% TECH, -20 MaxSTA",
         "bonus": {"atk_pct": 0.30, "def_pct": 0.20, "regen_pct": 0.10, "tech_pct": -0.15, "max_sta": -20}},
        {"name": "Hashira's Will",      "sp_cost": 75,  "type": "once_per_battle",
         "description": "Once: +40% TECH, status immune, +100 MaxHP, +200 HP at start. Backlash: -20% ATK",
         "bonus": {"tech_pct": 0.40, "null_status": True, "max_hp": 100, "battle_hp_boost": 200, "atk_pct": -0.20}},
        {"name": "Oni King",            "sp_cost": 80,  "type": "once_per_battle",
         "description": "Once: +35% ATK, +25 HP/turn, +200 HP at start. Backlash: -20% TECH, -20% DEF",
         "bonus": {"atk_pct": 0.35, "regen_hp": 25, "battle_hp_boost": 200, "tech_pct": -0.20, "def_pct": -0.20}},
        {"name": "Sun Dancer",          "sp_cost": 90,  "type": "once_per_battle",
         "description": "Once: +40% TECH, +30% ATK, +150 MaxHP, +250 HP at start, status immune. Backlash: -25% DEF",
         "bonus": {"tech_pct": 0.40, "atk_pct": 0.30, "max_hp": 150, "battle_hp_boost": 250, "null_status": True, "def_pct": -0.25}},
        {"name": "Muzan's Chosen",      "sp_cost": 100, "type": "once_per_battle",
         "description": "Once: +30% ATK/TECH/DEF, immune, +200 MaxHP, +300 HP at start",
         "bonus": {"atk_pct": 0.30, "tech_pct": 0.30, "def_pct": 0.30, "null_status": True, "max_hp": 200, "battle_hp_boost": 300}},
    ],
    # ══════════════════════════════════════════════════════════════════
    # FORBIDDEN
    # ══════════════════════════════════════════════════════════════════
    "Forbidden": [
        {"name": "Eye of Destruction",  "sp_cost": 50,  "type": "passive",
         "description": "+40% ATK, +25% crit, execute+20%. Backlash: -25% DEF, -10% dodge",
         "bonus": {"atk_pct": 0.40, "crit_bonus": 0.25, "executioner": 0.20, "def_pct": -0.25, "dodge_bonus": -0.10}},
        {"name": "Void Walker",         "sp_cost": 60,  "type": "passive",
         "description": "+35% dodge, first strike+25%, +20% ATK. Backlash: -20% TECH, -10% DEF",
         "bonus": {"dodge_bonus": 0.35, "first_strike": 0.25, "atk_pct": 0.20, "tech_pct": -0.20, "def_pct": -0.10}},
        {"name": "Crimson Reaper",      "sp_cost": 70,  "type": "passive",
         "description": "+35% low-HP dmg, +20% ATK, status immune. Backlash: -20% DEF",
         "bonus": {"low_hp_dmg": 0.35, "atk_pct": 0.20, "null_status": True, "def_pct": -0.20}},
        {"name": "Eternal Devour",      "sp_cost": 80,  "type": "passive",
         "description": "+15% regen/turn, +25 HP/turn, execute+30%. Backlash: -20% ATK, -15% TECH",
         "bonus": {"regen_pct": 0.15, "regen_hp": 25, "executioner": 0.30, "atk_pct": -0.20, "tech_pct": -0.15}},
        {"name": "Transcendence",       "sp_cost": 100, "type": "once_per_battle",
         "description": "Once: +50% TECH/ATK, survive fatal hit, status immune, +300 HP at start. Backlash: -30% DEF",
         "bonus": {"tech_pct": 0.50, "atk_pct": 0.50, "second_wind": 0.99, "null_status": True, "battle_hp_boost": 300, "def_pct": -0.30}},
        {"name": "Ruination",           "sp_cost": 120, "type": "once_per_battle",
         "description": "Once: +60% ATK/TECH, execute at 40%, +400 HP at start. Backlash: -40% DEF, -30% dodge",
         "bonus": {"atk_pct": 0.60, "tech_pct": 0.60, "executioner": 0.40, "battle_hp_boost": 400, "def_pct": -0.40, "dodge_bonus": -0.30}},
        {"name": "Absolute Obliteration", "sp_cost": 110, "type": "once_per_battle",
         "description": "Once: +55% ATK, +300 HP at start, +20 HP/turn, status immune. Backlash: -35% DEF, -20% TECH",
         "bonus": {"atk_pct": 0.55, "battle_hp_boost": 300, "regen_hp": 20, "null_status": True, "def_pct": -0.35, "tech_pct": -0.20}},
    ],
}

# Remove one-time skills from the live pool until their battle-start logic is rebuilt.
SKILLS = {
    category: [skill for skill in skills if skill.get("type") != "once_per_battle"]
    for category, skills in SKILLS.items()
}

# Ranks
SLAYER_ENEMIES = [
    {"name": "Lesser Demon",  "emoji": "👹", "threat": "🟢 LOW",     "hp": 180,  "atk": 18, "xp": 400,  "yen": 250,  "drops": ["Demon Blood"],      "image": ""},
    {"name": "Vampire",       "emoji": "🧛", "threat": "🟡 MEDIUM",  "hp": 350,  "atk": 32, "xp": 600,  "yen": 350,  "drops": ["Vampire Fang"],     "image": ""},
    {"name": "Goblin Horde",  "emoji": "👺", "threat": "🟢 LOW",     "hp": 140,  "atk": 15, "xp": 300,  "yen": 200,  "drops": ["Goblin Claw"],      "image": ""},
    {"name": "Lower Moon 6",  "emoji": "👹", "threat": "🔴 HIGH",    "hp": 1000, "atk": 60, "xp": 2000, "yen": 1000, "drops": ["Kizuki Blood"],     "image": ""},
    {"name": "Upper Moon 4",  "emoji": "☠️", "threat": "💀 EXTREME", "hp": 3500, "atk": 95, "xp": 5000, "yen": 2500, "drops": ["Upper Moon Shard"], "image": ""},
]

DEMON_ENEMIES = [
    {"name": "Demon Slayer", "emoji": "🗡️", "threat": "🔴 HIGH",    "hp": 250,  "atk": 45, "xp": 750,  "yen": 450,  "drops": ["Nichirin Fragment"], "image": ""},
    {"name": "Vampire",      "emoji": "🧛", "threat": "🟡 MEDIUM",  "hp": 350,  "atk": 32, "xp": 600,  "yen": 350,  "drops": ["Vampire Fang"],      "image": ""},
    {"name": "Goblin",       "emoji": "👺", "threat": "🟢 LOW",     "hp": 140,  "atk": 15, "xp": 300,  "yen": 200,  "drops": ["Goblin Claw"],        "image": ""},
    {"name": "Rival Demon",  "emoji": "😈", "threat": "🟡 MEDIUM",  "hp": 400,  "atk": 40, "xp": 700,  "yen": 400,  "drops": ["Demon Core"],         "image": ""},
    {"name": "Hashira",      "emoji": "⚔️", "threat": "💀 EXTREME", "hp": 3000, "atk": 90, "xp": 4500, "yen": 2000, "drops": ["Hashira Badge"],      "image": ""},
]

# ── REGION ENEMIES — 15 per zone + 1 boss (8% chance) ───────────────────
REGION_ENEMIES = {
    "asakusa": {
        "pressure_mod": 0,
        "enemies": [
            {"name": "Street Thug",       "emoji": "🥊", "threat": "🟢 LOW",     "hp": 120,  "atk": 12, "xp": 200,  "yen": 120,  "drops": ["Stolen Coin"],        "faction_type": "neutral", "is_boss": False},
            {"name": "Rogue Demon",       "emoji": "👹", "threat": "🟢 LOW",     "hp": 150,  "atk": 16, "xp": 280,  "yen": 160,  "drops": ["Demon Blood"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Cursed Spirit",     "emoji": "👻", "threat": "🟢 LOW",     "hp": 130,  "atk": 14, "xp": 240,  "yen": 140,  "drops": ["Spirit Ash"],          "faction_type": "neutral", "is_boss": False},
            {"name": "Dire Wolf",         "emoji": "🐺", "threat": "🟢 LOW",     "hp": 160,  "atk": 18, "xp": 300,  "yen": 170,  "drops": ["Wolf Fang"],           "faction_type": "neutral", "is_boss": False},
            {"name": "Hungry Demon",      "emoji": "😈", "threat": "🟡 MEDIUM",  "hp": 200,  "atk": 22, "xp": 360,  "yen": 200,  "drops": ["Human Flesh"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Shadow Stalker",    "emoji": "🌑", "threat": "🟡 MEDIUM",  "hp": 220,  "atk": 25, "xp": 400,  "yen": 220,  "drops": ["Shadow Shard"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Corrupt Guard",     "emoji": "🪖", "threat": "🟡 MEDIUM",  "hp": 240,  "atk": 28, "xp": 420,  "yen": 240,  "drops": ["Guard Badge"],         "faction_type": "slayer",  "is_boss": False},
            {"name": "Blood Demon",       "emoji": "🩸", "threat": "🟡 MEDIUM",  "hp": 260,  "atk": 30, "xp": 460,  "yen": 260,  "drops": ["Blood Crystal"],       "faction_type": "demon",   "is_boss": False},
            {"name": "Night Crawler",     "emoji": "🦎", "threat": "🟡 MEDIUM",  "hp": 280,  "atk": 32, "xp": 500,  "yen": 280,  "drops": ["Crawler Scale"],       "faction_type": "demon",   "is_boss": False},
            {"name": "Demon Cultist",     "emoji": "🧟", "threat": "🟡 MEDIUM",  "hp": 300,  "atk": 34, "xp": 540,  "yen": 300,  "drops": ["Cult Relic"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Asakusa Demon",     "emoji": "👿", "threat": "🔴 HIGH",    "hp": 400,  "atk": 40, "xp": 700,  "yen": 400,  "drops": ["Demon Claw"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Twin Demon",        "emoji": "👥", "threat": "🔴 HIGH",    "hp": 420,  "atk": 42, "xp": 720,  "yen": 420,  "drops": ["Twin Fang"],           "faction_type": "demon",   "is_boss": False},
            {"name": "Elder Demon",       "emoji": "🧓", "threat": "🔴 HIGH",    "hp": 500,  "atk": 48, "xp": 850,  "yen": 480,  "drops": ["Ancient Bone"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Corps Traitor",     "emoji": "🗡️", "threat": "🔴 HIGH",    "hp": 550,  "atk": 52, "xp": 900,  "yen": 500,  "drops": ["Traitor Badge"],       "faction_type": "slayer",  "is_boss": False},
            {"name": "Asakusa Warlord",   "emoji": "👺", "threat": "💀 BOSS",    "hp": 2000, "atk": 75, "xp": 3000, "yen": 1500, "drops": ["Warlord Fang", "Boss Shard"], "faction_type": "demon", "is_boss": True},
            {"name": "Water Hashira",        "emoji": "💧", "threat": "💀 BOSS",    "hp": 3500, "atk": 95, "xp": 4000, "yen": 2000, "drops": ["Hashira Badge", "Boss Shard", "Wisteria Antidote"], "faction_type": "slayer", "is_boss": True},
        ]
    },
    "butterfly": {
        "pressure_mod": 10,
        "enemies": [
            {"name": "Stray Demon",        "emoji": "👹", "threat": "🟢 LOW",    "hp": 180,  "atk": 20, "xp": 320,  "yen": 180,  "drops": ["Demon Blood"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Poison Sprite",      "emoji": "🧪", "threat": "🟢 LOW",    "hp": 160,  "atk": 18, "xp": 300,  "yen": 170,  "drops": ["Poison Sac"],          "faction_type": "neutral", "is_boss": False},
            {"name": "Corrupted Butterfly","emoji": "🦋", "threat": "🟡 MEDIUM", "hp": 220,  "atk": 26, "xp": 420,  "yen": 240,  "drops": ["Butterfly Wing"],      "faction_type": "neutral", "is_boss": False},
            {"name": "Venom Demon",        "emoji": "🐍", "threat": "🟡 MEDIUM", "hp": 260,  "atk": 30, "xp": 480,  "yen": 270,  "drops": ["Venom Gland"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Miasma Fiend",       "emoji": "☁️", "threat": "🟡 MEDIUM", "hp": 280,  "atk": 32, "xp": 500,  "yen": 290,  "drops": ["Miasma Orb"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Toxic Beast",        "emoji": "🐊", "threat": "🟡 MEDIUM", "hp": 300,  "atk": 35, "xp": 540,  "yen": 310,  "drops": ["Toxic Spine"],         "faction_type": "neutral", "is_boss": False},
            {"name": "Plague Demon",       "emoji": "🤢", "threat": "🟡 MEDIUM", "hp": 320,  "atk": 36, "xp": 570,  "yen": 330,  "drops": ["Plague Bone"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Corrupted Medic",    "emoji": "🩺", "threat": "🔴 HIGH",   "hp": 400,  "atk": 44, "xp": 750,  "yen": 420,  "drops": ["Medical Badge"],       "faction_type": "slayer",  "is_boss": False},
            {"name": "Needle Demon",       "emoji": "🪡", "threat": "🔴 HIGH",   "hp": 440,  "atk": 48, "xp": 800,  "yen": 450,  "drops": ["Bone Needle"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Rot Fiend",          "emoji": "🧫", "threat": "🔴 HIGH",   "hp": 480,  "atk": 52, "xp": 860,  "yen": 480,  "drops": ["Rot Crystal"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Soul Parasite",      "emoji": "🪱", "threat": "🔴 HIGH",   "hp": 500,  "atk": 54, "xp": 900,  "yen": 500,  "drops": ["Parasite Core"],       "faction_type": "demon",   "is_boss": False},
            {"name": "Venomous Elder",     "emoji": "🧙", "threat": "🔴 HIGH",   "hp": 550,  "atk": 58, "xp": 950,  "yen": 530,  "drops": ["Elder Venom"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Toxic Slayer",       "emoji": "😷", "threat": "🔴 HIGH",   "hp": 580,  "atk": 60, "xp": 1000, "yen": 560,  "drops": ["Corrupt Blade"],       "faction_type": "slayer",  "is_boss": False},
            {"name": "Miasma Lord",        "emoji": "💀", "threat": "🔴 HIGH",   "hp": 650,  "atk": 65, "xp": 1100, "yen": 600,  "drops": ["Lord Fang"],           "faction_type": "demon",   "is_boss": False},
            {"name": "Queen Butterfly",    "emoji": "🦋", "threat": "💀 BOSS",   "hp": 3000, "atk": 90, "xp": 4000, "yen": 2000, "drops": ["Queen Wing", "Boss Shard"], "faction_type": "demon", "is_boss": True},
            {"name": "Insect Hashira",        "emoji": "🦋", "threat": "💀 BOSS",   "hp": 4000, "atk": 100,"xp": 5000, "yen": 2500, "drops": ["Hashira Badge", "Boss Shard", "Butterfly Wing"], "faction_type": "slayer", "is_boss": True},
        ]
    },
    "mtsagiri": {
        "pressure_mod": 5,
        "enemies": [
            {"name": "Mountain Ogre",      "emoji": "👹", "threat": "🟡 MEDIUM", "hp": 300,  "atk": 35, "xp": 550,  "yen": 310,  "drops": ["Ogre Horn"],           "faction_type": "neutral", "is_boss": False},
            {"name": "Ice Demon",          "emoji": "🧊", "threat": "🟡 MEDIUM", "hp": 320,  "atk": 37, "xp": 580,  "yen": 330,  "drops": ["Ice Crystal"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Rock Golem",         "emoji": "🪨", "threat": "🟡 MEDIUM", "hp": 500,  "atk": 30, "xp": 600,  "yen": 340,  "drops": ["Stone Core"],          "faction_type": "neutral", "is_boss": False},
            {"name": "Wind Demon",         "emoji": "🌬️", "threat": "🟡 MEDIUM", "hp": 280,  "atk": 40, "xp": 620,  "yen": 350,  "drops": ["Wind Essence"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Frost Fiend",        "emoji": "❄️", "threat": "🟡 MEDIUM", "hp": 340,  "atk": 38, "xp": 640,  "yen": 360,  "drops": ["Frost Shard"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Thunder Beast",      "emoji": "⚡", "threat": "🔴 HIGH",   "hp": 450,  "atk": 50, "xp": 800,  "yen": 450,  "drops": ["Thunder Fang"],        "faction_type": "neutral", "is_boss": False},
            {"name": "Blizzard Demon",     "emoji": "🌨️", "threat": "🔴 HIGH",   "hp": 480,  "atk": 52, "xp": 840,  "yen": 470,  "drops": ["Blizzard Core"],       "faction_type": "demon",   "is_boss": False},
            {"name": "Stone Slayer",       "emoji": "🪖", "threat": "🔴 HIGH",   "hp": 520,  "atk": 55, "xp": 900,  "yen": 500,  "drops": ["Stone Badge"],         "faction_type": "slayer",  "is_boss": False},
            {"name": "Avalanche Demon",    "emoji": "🏔️", "threat": "🔴 HIGH",   "hp": 560,  "atk": 58, "xp": 950,  "yen": 530,  "drops": ["Avalanche Bone"],      "faction_type": "demon",   "is_boss": False},
            {"name": "Glacier Fiend",      "emoji": "🧊", "threat": "🔴 HIGH",   "hp": 600,  "atk": 60, "xp": 1000, "yen": 560,  "drops": ["Glacier Core"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Peak Stalker",       "emoji": "🦅", "threat": "🔴 HIGH",   "hp": 640,  "atk": 64, "xp": 1050, "yen": 580,  "drops": ["Eagle Talon"],         "faction_type": "neutral", "is_boss": False},
            {"name": "Mountain Demon",     "emoji": "🏔️", "threat": "🔴 HIGH",   "hp": 680,  "atk": 66, "xp": 1100, "yen": 600,  "drops": ["Mountain Fang"],       "faction_type": "demon",   "is_boss": False},
            {"name": "Storm Demon",        "emoji": "⛈️", "threat": "🔴 HIGH",   "hp": 720,  "atk": 70, "xp": 1150, "yen": 630,  "drops": ["Storm Crystal"],       "faction_type": "demon",   "is_boss": False},
            {"name": "Thunder Slayer",     "emoji": "⚡", "threat": "🔴 HIGH",   "hp": 760,  "atk": 72, "xp": 1200, "yen": 660,  "drops": ["Thunder Badge"],       "faction_type": "slayer",  "is_boss": False},
            {"name": "Mt. Sagiri Titan",   "emoji": "🗿", "threat": "💀 BOSS",   "hp": 5000, "atk": 110,"xp": 5000, "yen": 2500, "drops": ["Titan Core", "Boss Shard"], "faction_type": "neutral", "is_boss": True},
            {"name": "Stone Hashira",         "emoji": "🪨", "threat": "💀 BOSS",   "hp": 6000, "atk": 120,"xp": 6500, "yen": 3200, "drops": ["Hashira Badge", "Boss Shard", "Stone Core"], "faction_type": "slayer", "is_boss": True},
        ]
    },
    "swordsmith": {
        "pressure_mod": 5,
        "enemies": [
            {"name": "Forge Demon",        "emoji": "🔥", "threat": "🟡 MEDIUM", "hp": 360,  "atk": 42, "xp": 680,  "yen": 380,  "drops": ["Forge Coal"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Iron Golem",         "emoji": "🤖", "threat": "🟡 MEDIUM", "hp": 600,  "atk": 38, "xp": 700,  "yen": 390,  "drops": ["Iron Core"],           "faction_type": "neutral", "is_boss": False},
            {"name": "Blade Fiend",        "emoji": "⚔️", "threat": "🟡 MEDIUM", "hp": 380,  "atk": 45, "xp": 720,  "yen": 400,  "drops": ["Broken Blade"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Cursed Smith",       "emoji": "🧙", "threat": "🔴 HIGH",   "hp": 450,  "atk": 52, "xp": 850,  "yen": 470,  "drops": ["Cursed Steel"],        "faction_type": "neutral", "is_boss": False},
            {"name": "Lava Demon",         "emoji": "🌋", "threat": "🔴 HIGH",   "hp": 500,  "atk": 55, "xp": 900,  "yen": 500,  "drops": ["Lava Stone"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Steel Slayer",       "emoji": "🛡️", "threat": "🔴 HIGH",   "hp": 540,  "atk": 58, "xp": 950,  "yen": 530,  "drops": ["Steel Badge"],         "faction_type": "slayer",  "is_boss": False},
            {"name": "Slag Demon",         "emoji": "🔩", "threat": "🔴 HIGH",   "hp": 580,  "atk": 60, "xp": 1000, "yen": 560,  "drops": ["Slag Core"],           "faction_type": "demon",   "is_boss": False},
            {"name": "Anvil Beast",        "emoji": "⚒️", "threat": "🔴 HIGH",   "hp": 640,  "atk": 64, "xp": 1050, "yen": 580,  "drops": ["Anvil Shard"],         "faction_type": "neutral", "is_boss": False},
            {"name": "Furnace Demon",      "emoji": "🔴", "threat": "🔴 HIGH",   "hp": 680,  "atk": 66, "xp": 1100, "yen": 600,  "drops": ["Furnace Core"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Molten Fiend",       "emoji": "💧", "threat": "🔴 HIGH",   "hp": 720,  "atk": 70, "xp": 1150, "yen": 630,  "drops": ["Molten Drop"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Steel Demon",        "emoji": "🗡️", "threat": "🔴 HIGH",   "hp": 760,  "atk": 72, "xp": 1200, "yen": 650,  "drops": ["Steel Fang"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Iron Slayer",        "emoji": "⚙️", "threat": "🔴 HIGH",   "hp": 800,  "atk": 74, "xp": 1250, "yen": 680,  "drops": ["Iron Badge"],          "faction_type": "slayer",  "is_boss": False},
            {"name": "Forge Master Demon", "emoji": "🔨", "threat": "🔴 HIGH",   "hp": 850,  "atk": 78, "xp": 1300, "yen": 700,  "drops": ["Master Fang"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Cursed Blade Demon", "emoji": "🗡️", "threat": "🔴 HIGH",   "hp": 900,  "atk": 80, "xp": 1350, "yen": 720,  "drops": ["Cursed Blade Shard"],  "faction_type": "demon",   "is_boss": False},
            {"name": "Swordsmith King",    "emoji": "👑", "threat": "💀 BOSS",   "hp": 7000, "atk": 130,"xp": 6000, "yen": 3000, "drops": ["King Blade", "Boss Shard"], "faction_type": "demon", "is_boss": True},
            {"name": "Love Hashira",          "emoji": "💗", "threat": "💀 BOSS",   "hp": 8000, "atk": 140,"xp": 7500, "yen": 3800, "drops": ["Hashira Badge", "Boss Shard", "Love Crystal"], "faction_type": "slayer", "is_boss": True},
        ]
    },
    "yoshiwara": {
        "pressure_mod": 0,
        "enemies": [
            {"name": "Pleasure Demon",     "emoji": "🎭", "threat": "🟡 MEDIUM", "hp": 420,  "atk": 50, "xp": 800,  "yen": 450,  "drops": ["Silk Cloth"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Illusion Fiend",     "emoji": "🌀", "threat": "🟡 MEDIUM", "hp": 400,  "atk": 52, "xp": 820,  "yen": 460,  "drops": ["Illusion Shard"],      "faction_type": "demon",   "is_boss": False},
            {"name": "Shadow Dancer",      "emoji": "💃", "threat": "🔴 HIGH",   "hp": 480,  "atk": 58, "xp": 950,  "yen": 530,  "drops": ["Shadow Cloth"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Cursed Geisha",      "emoji": "🎎", "threat": "🔴 HIGH",   "hp": 500,  "atk": 60, "xp": 1000, "yen": 560,  "drops": ["Cursed Fan"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Nightmare Demon",    "emoji": "😱", "threat": "🔴 HIGH",   "hp": 540,  "atk": 62, "xp": 1050, "yen": 580,  "drops": ["Nightmare Core"],      "faction_type": "demon",   "is_boss": False},
            {"name": "Chaos Slayer",       "emoji": "🌪️", "threat": "🔴 HIGH",   "hp": 580,  "atk": 65, "xp": 1100, "yen": 600,  "drops": ["Chaos Badge"],         "faction_type": "slayer",  "is_boss": False},
            {"name": "Mirage Demon",       "emoji": "🔮", "threat": "🔴 HIGH",   "hp": 620,  "atk": 68, "xp": 1150, "yen": 630,  "drops": ["Mirage Stone"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Lust Demon",         "emoji": "💋", "threat": "🔴 HIGH",   "hp": 660,  "atk": 70, "xp": 1200, "yen": 650,  "drops": ["Demon Heart"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Puppet Demon",       "emoji": "🎪", "threat": "🔴 HIGH",   "hp": 700,  "atk": 72, "xp": 1250, "yen": 680,  "drops": ["Puppet String"],       "faction_type": "demon",   "is_boss": False},
            {"name": "Deception Demon",    "emoji": "🃏", "threat": "🔴 HIGH",   "hp": 740,  "atk": 74, "xp": 1300, "yen": 700,  "drops": ["Deception Core"],      "faction_type": "demon",   "is_boss": False},
            {"name": "Carnival Demon",     "emoji": "🎡", "threat": "🔴 HIGH",   "hp": 780,  "atk": 76, "xp": 1350, "yen": 720,  "drops": ["Carnival Gem"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Chaos Dancer",       "emoji": "🌊", "threat": "🔴 HIGH",   "hp": 820,  "atk": 78, "xp": 1400, "yen": 750,  "drops": ["Chaos Shard"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Phantom Demon",      "emoji": "👻", "threat": "🔴 HIGH",   "hp": 860,  "atk": 80, "xp": 1450, "yen": 780,  "drops": ["Phantom Core"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Illusion Master",    "emoji": "🧿", "threat": "🔴 HIGH",   "hp": 900,  "atk": 84, "xp": 1500, "yen": 800,  "drops": ["Master Illusion"],     "faction_type": "demon",   "is_boss": False},
            {"name": "Doma — Upper Moon 2","emoji": "🌸", "threat": "💀 BOSS",   "hp": 12000,"atk": 160,"xp": 8000, "yen": 4000, "drops": ["Doma Shard", "Boss Shard", "Upper Moon Core"], "faction_type": "demon", "is_boss": True},
            {"name": "Sound Hashira",         "emoji": "🔊", "threat": "💀 BOSS",   "hp": 10000,"atk": 155,"xp": 8500, "yen": 4200, "drops": ["Hashira Badge", "Boss Shard", "Sound Drum"], "faction_type": "slayer", "is_boss": True},
        ]
    },
    "natagumo": {
        "pressure_mod": -10,
        "enemies": [
            {"name": "Giant Spider",       "emoji": "🕷️", "threat": "🟡 MEDIUM", "hp": 500,  "atk": 60, "xp": 1000, "yen": 560,  "drops": ["Spider Silk"],         "faction_type": "neutral", "is_boss": False},
            {"name": "Spider Demon",       "emoji": "🕸️", "threat": "🔴 HIGH",   "hp": 580,  "atk": 66, "xp": 1100, "yen": 600,  "drops": ["Spider Fang"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Venom Spider",       "emoji": "🧪", "threat": "🔴 HIGH",   "hp": 620,  "atk": 70, "xp": 1150, "yen": 640,  "drops": ["Venom Sac"],           "faction_type": "demon",   "is_boss": False},
            {"name": "Spider Slayer",      "emoji": "🕷️", "threat": "🔴 HIGH",   "hp": 660,  "atk": 72, "xp": 1200, "yen": 660,  "drops": ["Slayer Silk"],         "faction_type": "slayer",  "is_boss": False},
            {"name": "Web Demon",          "emoji": "🌐", "threat": "🔴 HIGH",   "hp": 700,  "atk": 74, "xp": 1250, "yen": 680,  "drops": ["Web Crystal"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Cocoon Fiend",       "emoji": "🫙", "threat": "🔴 HIGH",   "hp": 740,  "atk": 76, "xp": 1300, "yen": 700,  "drops": ["Cocoon Core"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Poison Spider",      "emoji": "💀", "threat": "🔴 HIGH",   "hp": 780,  "atk": 78, "xp": 1350, "yen": 720,  "drops": ["Poison Fang"],         "faction_type": "demon",   "is_boss": False},
            {"name": "Trapped Slayer",     "emoji": "⛓️", "threat": "🔴 HIGH",   "hp": 820,  "atk": 80, "xp": 1400, "yen": 750,  "drops": ["Broken Chain"],        "faction_type": "slayer",  "is_boss": False},
            {"name": "Elder Spider",       "emoji": "🦕", "threat": "🔴 HIGH",   "hp": 900,  "atk": 84, "xp": 1500, "yen": 800,  "drops": ["Elder Fang"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Curse Weaver",       "emoji": "🧵", "threat": "🔴 HIGH",   "hp": 950,  "atk": 86, "xp": 1550, "yen": 830,  "drops": ["Curse Thread"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Spider Patriarch",   "emoji": "🕷️", "threat": "🔴 HIGH",   "hp": 1000, "atk": 88, "xp": 1600, "yen": 860,  "drops": ["Patriarch Fang"],      "faction_type": "demon",   "is_boss": False},
            {"name": "Silk Demon",         "emoji": "🎀", "threat": "🔴 HIGH",   "hp": 1050, "atk": 90, "xp": 1650, "yen": 890,  "drops": ["Demon Silk"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Death Spider",       "emoji": "💀", "threat": "🔴 HIGH",   "hp": 1100, "atk": 94, "xp": 1700, "yen": 920,  "drops": ["Death Fang"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Venom Lord",         "emoji": "☠️", "threat": "🔴 HIGH",   "hp": 1200, "atk": 98, "xp": 1800, "yen": 960,  "drops": ["Venom Core"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Rui — Lower Moon 5", "emoji": "🕸️", "threat": "💀 BOSS",   "hp": 15000,"atk": 180,"xp": 10000,"yen": 5000, "drops": ["Rui Thread", "Boss Shard", "Kizuki Blood"], "faction_type": "demon", "is_boss": True},
            {"name": "Mist Hashira",          "emoji": "🌫️", "threat": "💀 BOSS",   "hp": 13000,"atk": 175,"xp": 10500,"yen": 5200, "drops": ["Hashira Badge", "Boss Shard", "Mist Orb"], "faction_type": "slayer", "is_boss": True},
        ]
    },
    "infinity": {
        "pressure_mod": -15,
        "enemies": [
            {"name": "Castle Demon",       "emoji": "🏰", "threat": "🔴 HIGH",   "hp": 1500, "atk": 110,"xp": 2000, "yen": 1100, "drops": ["Castle Stone"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Infinity Guard",     "emoji": "⚔️", "threat": "🔴 HIGH",   "hp": 1600, "atk": 115,"xp": 2100, "yen": 1150, "drops": ["Guard Shard"],         "faction_type": "slayer",  "is_boss": False},
            {"name": "Spatial Demon",      "emoji": "🌀", "threat": "🔴 HIGH",   "hp": 1700, "atk": 120,"xp": 2200, "yen": 1200, "drops": ["Spatial Core"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Void Stalker",       "emoji": "🌑", "threat": "🔴 HIGH",   "hp": 1800, "atk": 125,"xp": 2300, "yen": 1250, "drops": ["Void Shard"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Warp Demon",         "emoji": "🔀", "threat": "🔴 HIGH",   "hp": 1900, "atk": 128,"xp": 2400, "yen": 1300, "drops": ["Warp Crystal"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Dimensional Fiend",  "emoji": "🎑", "threat": "🔴 HIGH",   "hp": 2000, "atk": 132,"xp": 2500, "yen": 1350, "drops": ["Dimension Shard"],     "faction_type": "demon",   "is_boss": False},
            {"name": "Upper Moon 6",       "emoji": "👹", "threat": "💀 EXTREME","hp": 3500, "atk": 95, "xp": 5000, "yen": 2500, "drops": ["Upper Moon Shard"],    "faction_type": "demon",   "is_boss": False},
            {"name": "Infinity Slayer",    "emoji": "🗡️", "threat": "💀 EXTREME","hp": 3000, "atk": 90, "xp": 4500, "yen": 2000, "drops": ["Infinity Badge"],      "faction_type": "slayer",  "is_boss": False},
            {"name": "Upper Moon 4",       "emoji": "☠️", "threat": "💀 EXTREME","hp": 5000, "atk": 130,"xp": 7000, "yen": 3500, "drops": ["Upper Moon Core"],     "faction_type": "demon",   "is_boss": False},
            {"name": "Upper Moon 3",       "emoji": "💀", "threat": "💀 EXTREME","hp": 6000, "atk": 145,"xp": 8000, "yen": 4000, "drops": ["Moon 3 Shard"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Akaza — UM3",        "emoji": "🔥", "threat": "💀 EXTREME","hp": 7000, "atk": 155,"xp": 9000, "yen": 4500, "drops": ["Akaza Fist", "Boss Shard"], "faction_type": "demon", "is_boss": False},
            {"name": "Kokushibo — UM1",    "emoji": "🌙", "threat": "💀 EXTREME","hp": 8000, "atk": 165,"xp": 10000,"yen": 5000, "drops": ["Moon Breathing Scroll", "Boss Shard"], "faction_type": "demon", "is_boss": False},
            {"name": "Nakime",             "emoji": "🎻", "threat": "💀 EXTREME","hp": 6500, "atk": 150,"xp": 8500, "yen": 4200, "drops": ["Biwa Shard"],          "faction_type": "demon",   "is_boss": False},
            {"name": "Douma — UM2",        "emoji": "🌸", "threat": "💀 EXTREME","hp": 9000, "atk": 170,"xp": 11000,"yen": 5500, "drops": ["Ice Lotus", "Upper Moon Core"], "faction_type": "demon", "is_boss": False},
            {"name": "Muzan Kibutsuji",    "emoji": "🩸", "threat": "💀 BOSS",   "hp": 50000,"atk": 220,"xp": 20000,"yen": 10000,"drops": ["Muzan Blood", "Boss Shard", "Demon King Core"], "faction_type": "demon", "is_boss": True},
            {"name": "Flame Hashira — Rengoku","emoji": "🔥","threat": "💀 BOSS",   "hp": 35000,"atk": 200,"xp": 18000,"yen": 9000, "drops": ["Hashira Badge", "Boss Shard", "Flame Core", "Rengoku Shard"], "faction_type": "slayer", "is_boss": True},
        ]
    },
    "void": {
        "pressure_mod": -20,
        "enemies": [
            {"name": "Void Drifter",       "emoji": "ðŸŒŒ", "threat": "ðŸ’€ EXTREME","hp": 9500, "atk": 180,"xp": 12000,"yen": 6000, "drops": ["Void Dust"],             "faction_type": "neutral", "is_boss": False},
            {"name": "Null Reaper",        "emoji": "ðŸ•³ï¸", "threat": "ðŸ’€ EXTREME","hp": 10500,"atk": 188,"xp": 12800,"yen": 6400, "drops": ["Null Fragment"],        "faction_type": "demon",   "is_boss": False},
            {"name": "Abyss Walker",       "emoji": "ðŸŒ‘", "threat": "ðŸ’€ EXTREME","hp": 11200,"atk": 194,"xp": 13600,"yen": 6800, "drops": ["Abyss Stone"],          "faction_type": "neutral", "is_boss": False},
            {"name": "Lost Hashira Shade", "emoji": "ðŸ‘¤", "threat": "ðŸ’€ EXTREME","hp": 12000,"atk": 200,"xp": 14500,"yen": 7200, "drops": ["Shade Cloth"],          "faction_type": "slayer",  "is_boss": False},
            {"name": "Void Tyrant",        "emoji": "ðŸ•¸ï¸", "threat": "ðŸ’€ EXTREME","hp": 13500,"atk": 210,"xp": 16000,"yen": 8000, "drops": ["Void Core", "Boss Shard"], "faction_type": "demon",   "is_boss": False},
            {"name": "Yoriichi Tsugikuni", "emoji": "☀️", "threat": "💀 LEGENDARY", "hp": 1500000, "atk": 280, "xp": 80000, "yen": 40000, "drops": ["Sun Blade Fragment", "Breath of the Sun Scroll", "Boss Shard", "Sun Nichirin Blade"], "faction_type": "slayer", "is_boss": True, "yoriichi": True},
        # ── Kokushibo — Demon-side void legendary boss (near-invincible for demons) ──
        ]
    },
}

# Ranks
# ── Slayer Corps Rankings (lowest → highest) ──────────────────────────────
# Canon 10 stems of the Japanese calendar system used as corps ranks
# XP gaps widen significantly in higher tiers — Hashira is endgame
REGION_ENEMIES["void"] = {
    "pressure_mod": -20,
    "enemies": [
        {"name": "Void Drifter", "emoji": "VD", "threat": "EXTREME", "hp": 9500, "atk": 180, "xp": 12000, "yen": 6000, "drops": ["Void Dust"], "faction_type": "neutral", "is_boss": False},
        {"name": "Null Reaper", "emoji": "NR", "threat": "EXTREME", "hp": 10500, "atk": 188, "xp": 12800, "yen": 6400, "drops": ["Null Fragment"], "faction_type": "demon", "is_boss": False},
        {"name": "Abyss Walker", "emoji": "AW", "threat": "EXTREME", "hp": 11200, "atk": 194, "xp": 13600, "yen": 6800, "drops": ["Abyss Stone"], "faction_type": "neutral", "is_boss": False},
        {"name": "Lost Hashira Shade", "emoji": "HS", "threat": "EXTREME", "hp": 12000, "atk": 200, "xp": 14500, "yen": 7200, "drops": ["Shade Cloth"], "faction_type": "slayer", "is_boss": False},
        {"name": "Void Tyrant", "emoji": "VT", "threat": "EXTREME", "hp": 13500, "atk": 210, "xp": 16000, "yen": 8000, "drops": ["Void Core", "Boss Shard"], "faction_type": "demon", "is_boss": False},
        {"name": "Yoriichi Tsugikuni", "emoji": "☀️", "threat": "💀 LEGENDARY", "hp": 1500000, "atk": 280, "xp": 80000, "yen": 40000, "drops": ["Sun Blade Fragment", "Breath of the Sun Scroll", "Boss Shard", "Sun Nichirin Blade"], "faction_type": "neutral", "is_boss": True, "yoriichi": True},
        # ── Kokushibo — Demon-side void legendary boss (near-invincible for demons) ──
        {"name": "Kokushibo", "emoji": "🌙", "threat": "💀 LEGENDARY", "hp": 2000000, "atk": 320, "xp": 80000, "yen": 40000, "drops": ["Moon Blade Shard", "Upper Moon Core", "Boss Shard", "Kokushibo Shard"], "faction_type": "demon", "is_boss": True, "kokushibo": True, "demon_resist": True},
    ],
}

def _yoriichi_hp_for_level(level: int) -> int:
    """Yoriichi HP: 1,500,000 at Lv80, +10,000 per level above 80."""
    return 1_500_000 + max(0, level - 80) * 10_000

SLAYER_RANKS = [
    {"name": "Mizunoto",      "kanji": "癸",    "xp_needed": 0},        # rank 10 (lowest)
    {"name": "Mizunoe",       "kanji": "壬",    "xp_needed": 2000},     # rank 9
    {"name": "Kanoto",        "kanji": "辛",    "xp_needed": 6000},     # rank 8
    {"name": "Kanoe",         "kanji": "庚",    "xp_needed": 15000},    # rank 7
    {"name": "Tsuchinoto",    "kanji": "己",    "xp_needed": 30000},    # rank 6
    {"name": "Tsuchinoe",     "kanji": "戊",    "xp_needed": 55000},    # rank 5
    {"name": "Hinoto",        "kanji": "丁",    "xp_needed": 90000},    # rank 4
    {"name": "Hinoe",         "kanji": "丙",    "xp_needed": 140000},   # rank 3
    {"name": "Kinoto",        "kanji": "乙",    "xp_needed": 220000},   # rank 2
    {"name": "Kinoe",         "kanji": "甲",    "xp_needed": 350000},   # rank 1 (elite)
    {"name": "Hashira",       "kanji": "柱",    "xp_needed": 600000},   # Pillar rank
    {"name": "Breath of the Sun", "kanji": "日の呼吸", "xp_needed": 1000000}, # Legendary
]

# ── Demon Rankings (lowest → highest) ─────────────────────────────────────
# All 6 Lower Moons + all 6 Upper Moons + pinnacle ranks
DEMON_RANKS = [
    {"name": "Stray Demon",   "kanji": "迷鬼",   "xp_needed": 0},       # weakest
    {"name": "Lesser Demon",  "kanji": "下鬼",   "xp_needed": 2000},
    {"name": "Demon",         "kanji": "鬼",     "xp_needed": 8000},
    {"name": "Demon General", "kanji": "鬼将軍", "xp_needed": 20000},
    {"name": "Lower Moon 6",  "kanji": "下弦陸", "xp_needed": 40000},
    {"name": "Lower Moon 5",  "kanji": "下弦伍", "xp_needed": 70000},
    {"name": "Lower Moon 4",  "kanji": "下弦肆", "xp_needed": 110000},
    {"name": "Lower Moon 3",  "kanji": "下弦参", "xp_needed": 165000},
    {"name": "Lower Moon 2",  "kanji": "下弦弐", "xp_needed": 240000},
    {"name": "Lower Moon 1",  "kanji": "下弦壱", "xp_needed": 340000},
    {"name": "Upper Moon 6",  "kanji": "上弦陸", "xp_needed": 480000},
    {"name": "Upper Moon 5",  "kanji": "上弦伍", "xp_needed": 660000},
    {"name": "Upper Moon 4",  "kanji": "上弦肆", "xp_needed": 880000},
    {"name": "Upper Moon 3",  "kanji": "上弦参", "xp_needed": 1150000},
    {"name": "Upper Moon 2",  "kanji": "上弦弐", "xp_needed": 1500000},
    {"name": "Upper Moon 1",  "kanji": "上弦壱", "xp_needed": 2000000},
    {"name": "Demon King",    "kanji": "鬼王",   "xp_needed": 3000000}, # Muzan-tier
]

# Origin Stories
TRAVEL_ZONES = [
    {"id": "asakusa", "name": "Asakusa", "emoji": "🏙️", "level_req": 1, "desc": "Starting city, Corps HQ"},
    {"id": "butterfly", "name": "Butterfly Estate", "emoji": "🌸", "level_req": 10, "desc": "Rest and heal fully"},
    {"id": "mtsagiri", "name": "Mt. Sagiri", "emoji": "🏔️", "level_req": 15, "desc": "Sword training mountain"},
    {"id": "swordsmith", "name": "Swordsmith Village", "emoji": "⚒️", "level_req": 20, "desc": "Upgrade your sword"},
    {"id": "yoshiwara", "name": "Yoshiwara", "emoji": "🎭", "level_req": 25, "desc": "Entertainment District"},
    {"id": "natagumo", "name": "Natagumo Mountain", "emoji": "🌲", "level_req": 30, "desc": "Spider demon territory"},
    {"id": "infinity", "name": "Infinity Castle", "emoji": "🏰", "level_req": 50, "desc": "Endgame raid zone"},
]

# Shop Items — lowered prices with short codenames for easy buying
TRAVEL_ZONES.append({"id": "void", "name": "Void Map", "emoji": "ðŸŒŒ", "level_req": 80, "desc": "Late-game void zone"})

TRAVEL_ZONES[-1]["emoji"] = "VOID"

SHOP_ITEMS = {
    "swords": [
        {"name": "Basic Nichirin Blade",    "code": "basic",    "price": 800,   "atk_bonus": 8,  "emoji": "⚔️"},
        {"name": "Crimson Nichirin Blade",  "code": "crimson",  "price": 4000,  "atk_bonus": 25, "emoji": "🔴"},
        {"name": "Jet Black Nichirin Blade","code": "jetblack", "price": 15000, "atk_bonus": 50, "emoji": "⬛"},
    ],
    "items": [
        {"name": "Wisteria Antidote",    "code": "wisteria", "price": 150,  "effect": "cure_poison",    "emoji": "🌿"},
        {"name": "Stamina Pill",         "code": "stamina",  "price": 120,  "effect": "restore_sta_50", "emoji": "💊"},
        {"name": "Full Recovery Gourd",  "code": "gourd",    "price": 350,  "effect": "restore_hp_full","emoji": "🍶"},
    ],
    "armor": [
        {"name": "Corps Uniform",      "code": "uniform",  "price": 500,   "def_bonus": 5,  "emoji": "👘"},
        {"name": "Reinforced Haori",   "code": "haori",    "price": 2500,  "def_bonus": 15, "emoji": "🥋"},
        {"name": "Hashira Haori",      "code": "hashira",  "price": 8000,  "def_bonus": 30, "emoji": "👑"},
    ]
}

# Origin Stories
STORIES = [
    {"id": 1, "emoji": "😢", "name": "Lost Family to Demons", "description": "Revenge burns hotter than any flame.", "bonus_text": "+10% damage vs enemies", "bonus_type": "dmg_bonus", "bonus_value": 0.10},
    {"id": 2, "emoji": "🏯", "name": "Noble Clan Duty", "description": "Born and trained for this purpose.", "bonus_text": "+10% defense", "bonus_type": "def_bonus", "bonus_value": 0.10},
    {"id": 3, "emoji": "🌾", "name": "Village Protector", "description": "You fight for the innocent.", "bonus_text": "+10% HP", "bonus_type": "hp_bonus", "bonus_value": 0.10},
    {"id": 4, "emoji": "🗡️", "name": "Wandering Warrior", "description": "No past. Only the blade.", "bonus_text": "+10% XP gain", "bonus_type": "xp_bonus", "bonus_value": 0.10},
]

# Missions
SLAYER_MISSIONS = [
    {"id": 1, "difficulty": "🟢 EASY", "name": "Track demon near the river", "emoji": "🐾", "xp": 100, "yen": 80, "desc": "A demon was spotted near the Asakusa river. Track it down."},
    {"id": 2, "difficulty": "🟡 MEDIUM", "name": "Rescue villagers from demon attack", "emoji": "🏘️", "xp": 300, "yen": 200, "desc": "A village near Asakusa is under attack. Civilians are trapped. Move fast."},
    {"id": 3, "difficulty": "🟡 MEDIUM", "name": "Slay 3 demons before dawn", "emoji": "🗡️", "xp": 280, "yen": 180, "desc": "Three demons spotted in the area. Eliminate them all before sunrise."},
    {"id": 4, "difficulty": "🔴 HARD", "name": "Hunt a Lower Moon demon", "emoji": "👹", "xp": 800, "yen": 500, "desc": "A Twelve Kizuki Lower Moon has been spotted. This will be a deadly fight."},
    {"id": 5, "difficulty": "💀 EXTREME", "name": "Infinity Castle Raid", "emoji": "🏰", "xp": 3000, "yen": 2000, "desc": "Enter the Infinity Castle. Party of 3 required. Few who enter return.", "party_required": True},
]

DEMON_MISSIONS = [
    {"id": 1, "difficulty": "🟢 EASY", "name": "Feed on a villager undetected", "emoji": "🌙", "xp": 100, "yen": 80, "desc": "Feed without alerting the Demon Slayer Corps. Stay hidden."},
    {"id": 2, "difficulty": "🟡 MEDIUM", "name": "Ambush a lone Demon Slayer", "emoji": "🗡️", "xp": 300, "yen": 200, "desc": "A lone slayer patrols the eastern road. Ambush them before they call for backup."},
    {"id": 3, "difficulty": "🟡 MEDIUM", "name": "Devour 3 humans before dawn", "emoji": "💀", "xp": 280, "yen": 180, "desc": "Muzan demands results. Feed on three humans before sunrise."},
    {"id": 4, "difficulty": "🔴 HARD", "name": "Kill a Demon Slayer Corps member", "emoji": "☠️", "xp": 800, "yen": 500, "desc": "A high ranking Corps member is in the area. Eliminate them."},
    {"id": 5, "difficulty": "💀 EXTREME", "name": "Siege a Demon Slayer base", "emoji": "🏯", "xp": 3000, "yen": 2000, "desc": "Launch a full assault on a Demon Slayer stronghold. Party of 3 required.", "party_required": True},
]

# OWNER_ID already set above from env

# Bank levels
BANK_LEVELS = [
    {"level": 1, "max_deposit": 10000, "interest_rate": 0.02, "upgrade_cost": 0},
    {"level": 2, "max_deposit": 50000, "interest_rate": 0.04, "upgrade_cost": 5000},
    {"level": 3, "max_deposit": 200000, "interest_rate": 0.06, "upgrade_cost": 20000},
    {"level": 4, "max_deposit": 1000000, "interest_rate": 0.08, "upgrade_cost": 100000},
    {"level": 5, "max_deposit": 999999999, "interest_rate": 0.10, "upgrade_cost": 500000},
]

# Skill Trees
SKILL_TREES = {
    "slayer": {
        "⚔️ Warrior": [
            {"name": "Blade Mastery 1", "desc": "+5% basic attack damage", "cost": 1},
            {"name": "Blade Mastery 2", "desc": "+10% basic attack damage", "cost": 2, "requires": "Blade Mastery 1"},
            {"name": "Blade Mastery 3", "desc": "+20% basic attack damage", "cost": 3, "requires": "Blade Mastery 2"},
            {"name": "Critical Eye", "desc": "+10% crit chance", "cost": 2},
            {"name": "Executioner", "desc": "+50% dmg when enemy below 20% HP", "cost": 3},
        ],
        "💨 Breathing": [
            {"name": "Deep Breathing 1", "desc": "-10% STA cost all techniques", "cost": 1},
            {"name": "Deep Breathing 2", "desc": "-20% STA cost all techniques", "cost": 2, "requires": "Deep Breathing 1"},
            {"name": "Total Focus", "desc": "Total Concentration lasts 2 turns", "cost": 3},
            {"name": "Form Master", "desc": "+15% technique damage", "cost": 3},
            {"name": "Style Mastery", "desc": "Unlock hidden form of your style", "cost": 5},
        ],
        "🛡️ Endurance": [
            {"name": "Iron Skin 1", "desc": "+10 max HP", "cost": 1},
            {"name": "Iron Skin 2", "desc": "+25 max HP", "cost": 2, "requires": "Iron Skin 1"},
            {"name": "Iron Skin 3", "desc": "+50 max HP", "cost": 3, "requires": "Iron Skin 2"},
            {"name": "Second Wind", "desc": "20% chance to survive fatal hit with 1 HP", "cost": 4},
            {"name": "Regeneration", "desc": "Restore 5% HP after each kill", "cost": 3},
        ],
        "⚡ Speed": [
            {"name": "Swift Feet 1", "desc": "+5 SPD", "cost": 1},
            {"name": "Swift Feet 2", "desc": "+10 SPD", "cost": 2, "requires": "Swift Feet 1"},
            {"name": "Evasion Master", "desc": "+15% dodge chance", "cost": 3},
            {"name": "First Strike", "desc": "Always go first in battles", "cost": 4},
            {"name": "Counter Attack", "desc": "25% chance to counter when dodging", "cost": 3},
        ],
    },
    "demon": {
        "🩸 Predator": [
            {"name": "Blood Hunger 1", "desc": "+5% dmg after each kill", "cost": 1},
            {"name": "Blood Hunger 2", "desc": "+10% dmg after each kill", "cost": 2, "requires": "Blood Hunger 1"},
            {"name": "Devour", "desc": "Heal 10% HP on kill", "cost": 3},
            {"name": "Bloodlust", "desc": "+30% dmg when below 30% HP", "cost": 3},
            {"name": "True Form", "desc": "Unlock True Form ability", "cost": 5},
        ],
        "🧬 Regeneration": [
            {"name": "Demon Regen 1", "desc": "Restore 3 HP per turn", "cost": 1},
            {"name": "Demon Regen 2", "desc": "Restore 8 HP per turn", "cost": 2, "requires": "Demon Regen 1"},
            {"name": "Immortal Body", "desc": "Revive once per battle with 30% HP", "cost": 5},
            {"name": "Thick Hide", "desc": "-15% damage taken", "cost": 3},
            {"name": "Null Weakness", "desc": "Immune to status effects", "cost": 4},
        ],
        "🎭 Demon Art": [
            {"name": "Art Mastery 1", "desc": "+10% demon art damage", "cost": 1},
            {"name": "Art Mastery 2", "desc": "+20% demon art damage", "cost": 2, "requires": "Art Mastery 1"},
            {"name": "Blood Empowerment", "desc": "Arts cost no STA when HP below 50%", "cost": 4},
            {"name": "Art Evolution", "desc": "Unlock evolved version of your art", "cost": 5},
            {"name": "Multi Art", "desc": "Use two arts in one turn", "cost": 5},
        ],
    }
}

# Status effects data
STATUS_EFFECTS_DATA = {
    # ── DoT effects ───────────────────────────────────────────────────────
    "🔥 Burn":          {"dmg_pct": 0.05, "turns": 5,  "stop_regen": True, "desc": "5% HP/turn, stops regen (5t)"},
    "🧪 Poison":        {"dmg_pct": 0.03, "turns": 5,  "desc": "3% HP/turn (5t)"},
    "🩸 Bleed":         {"dmg_pct": 0.06, "turns": 3,  "desc": "6% HP/turn, stacks (3t)"},
    "☠️ DeepPoison":    {"dmg_pct": 0.05, "turns": 4,  "desc": "5% HP/turn (4t)"},
    "🩸 IceBleed":      {"dmg_flat": 12,  "turns": 2,  "desc": "12 flat DMG/turn (2t) — Frozen Spine"},
    "🌡️ Frostburn":     {"sta_drain": 10, "turns": 3,  "desc": "Drain 10 STA/turn (3t) — Arctic Soul"},
    # ── Control effects ───────────────────────────────────────────────────
    "⚡ Stun":          {"skip_turn": True,  "turns": 1, "desc": "Skip next turn"},
    "❄️ Freeze":        {"no_technique": True, "turns": 2, "desc": "Cannot use techniques (2t)"},
    "❄️ DeepFreeze":    {"skip_turn": True, "no_technique": True, "turns": 2, "desc": "Skip 2 turns completely (Permafrost)"},
    "🌀 Confusion":     {"self_atk_chance": 0.40, "turns": 2, "desc": "40% self-hit chance (2t)"},
    "😵 Exhaust":       {"no_sta_regen": True, "sta_dmg_pct": 0.10, "turns": 3, "desc": "No STA regen, -10% STA/turn"},
    "🔒 Stagger":       {"skip_turn": True, "turns": 1, "desc": "Lose next action"},
    "🙈 Blind":         {"miss_chance": 0.30, "turns": 1, "desc": "30% chance to miss physical attack (1t)"},
    # ── Debuff effects ────────────────────────────────────────────────────
    "💀 Curse":         {"heal_reduce": 0.50, "turns": 3, "desc": "All healing -50% (3t)"},
    "😰 Vulnerable":    {"dmg_taken_pct": 0.30, "turns": 1, "desc": "Take 30% more damage (1 hit)"},
    "🧊 Shattered":     {"def_reduce": 15, "turns": 3, "desc": "DEF -15 for 3 turns (Crystal Lotus)"},
    "🪞 IceCounter":    {"reflect_pct": 0.20, "turns": 1, "desc": "Reflect 20% damage for 1 turn (Ice Queen)"},
    # ── Buff effects (player-side) ────────────────────────────────────────
    "💧 Flow":          {"atk_pct": 0.10, "def_pct": 0.10, "turns": 5, "desc": "ATK+DEF +10% (Water synergy)"},
    "🛡️ WaterShield":   {"dmg_block": 2,  "turns": 2, "desc": "Block next 2 hits"},
    "🩹 Cleanse":       {"cleanse": True,  "turns": 1, "desc": "Remove 1 debuff"},
    "⚡ Overcharge":    {"atk_pct": 0.20,  "turns": 2, "desc": "ATK +20% for 2 turns"},
    "🌀 Phantomstep":   {"dodge_bonus": 0.30, "turns": 2, "desc": "Dodge +30% for 2 turns"},
    "🧱 Fortress":      {"dmg_reduce": 0.35, "turns": 2, "desc": "DMG taken -35% for 2 turns"},
    "☠️ Deathmark":     {"execute_threshold": 0.30, "turns": 3, "desc": "Instant kill if enemy <30% HP (3t)"},
}

# Which techniques apply which status effects
TECHNIQUE_STATUS_EFFECTS = {
    "Flame Breathing": "🔥 Burn",
    "Explosive Flames": "🔥 Burn",
    "Insect Breathing": "🧪 Poison",
    "Spider Manipulation": "🧪 Poison",
    "Blood Whip": "🩸 Bleed",
    "Serpent Breathing": "🩸 Bleed",
    "Spatial Warping": "🌀 Confusion",
    "Mist Breathing": "🌀 Confusion",
    "Moon Breathing": "❄️ Freeze",
    "Corpse Puppeteering": "💀 Curse",
    "Sound Breathing": "😵 Exhaust",
}

# Lottery tiers
LOTTERY_TIERS = [
    {"name": "Basic", "cost": 50, "prize": 500, "emoji": "🎟️"},
    {"name": "Silver", "cost": 200, "prize": 2000, "emoji": "🥈"},
    {"name": "Gold", "cost": 500, "prize": 10000, "emoji": "🥇"},
    {"name": "Diamond", "cost": 1000, "prize": 25000, "emoji": "💎"},
]
