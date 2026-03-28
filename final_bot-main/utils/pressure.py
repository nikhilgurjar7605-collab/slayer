"""
Spiritual Pressure System
Randomly generated each battle based on player stats + region modifier.
"""
import random

# Region pressure modifiers
REGION_PRESSURE_MOD = {
    "asakusa":    0,
    "butterfly":  10,
    "mtsagiri":   5,
    "swordsmith": 5,
    "yoshiwara":  0,   # handled as chaos (random ±10 each turn)
    "natagumo":  -10,
    "infinity":  -15,
}

REGION_FLAVOR = {
    "asakusa":   "🏙️ City air — neutral ground",
    "butterfly": "🌸 Healing aura flows through this estate",
    "mtsagiri":  "🏔️ Mountain winds sharpen your focus",
    "swordsmith":"⚒️ The forges fuel your fighting spirit",
    "yoshiwara": "🎭 Chaotic energy swirls unpredictably",
    "natagumo":  "🕸️ Spider curse weakens your resolve",
    "infinity":  "🏰 Muzan's overwhelming presence crushes the weak",
}

PRESSURE_TIERS = [
    {"min": 20,  "max": 999, "name": "🔥 OVERWHELMING",  "emoji": "🔥",
     "atk_mult": 1.25, "def_mult": 1.15, "tech_mult": 1.20,
     "flavor": "Your presence dominates the battlefield!"},
    {"min": 10,  "max": 19,  "name": "💪 DOMINANT",      "emoji": "💪",
     "atk_mult": 1.15, "def_mult": 1.10, "tech_mult": 1.10,
     "flavor": "Your will overpowers the enemy!"},
    {"min": 1,   "max": 9,   "name": "⚡ STABLE",        "emoji": "⚡",
     "atk_mult": 1.05, "def_mult": 1.00, "tech_mult": 1.05,
     "flavor": "You hold your ground steadily."},
    {"min": 0,   "max": 0,   "name": "⚪ NEUTRAL",       "emoji": "⚪",
     "atk_mult": 1.00, "def_mult": 1.00, "tech_mult": 1.00,
     "flavor": "Neither advantage nor disadvantage."},
    {"min": -9,  "max": -1,  "name": "😰 SUPPRESSED",    "emoji": "😰",
     "atk_mult": 0.95, "def_mult": 1.00, "tech_mult": 0.95,
     "flavor": "Something weighs on your spirit..."},
    {"min": -19, "max": -10, "name": "😨 OVERWHELMED",   "emoji": "😨",
     "atk_mult": 0.85, "def_mult": 0.90, "tech_mult": 0.85,
     "flavor": "The enemy's pressure is immense!"},
    {"min": -999,"max": -20, "name": "💀 CRUSHED",       "emoji": "💀",
     "atk_mult": 0.75, "def_mult": 0.85, "tech_mult": 0.80,
     "flavor": "Their overwhelming power is crushing your spirit!"},
]


def calc_pressure(player, location="asakusa"):
    """
    Generate spiritual pressure for a battle.
    Based on player stats + randomness + region modifier.
    Returns a pressure dict with tier info and multipliers.
    """
    str_stat = player.get('str_stat', 20)
    spd      = player.get('spd', 18)
    def_stat = player.get('def_stat', 15)
    hp_pct   = player.get('hp', 200) / max(player.get('max_hp', 200), 1)

    # Stat-based bias: high stats push toward positive pressure
    stat_avg    = (str_stat + spd + def_stat) / 3
    stat_bias   = (stat_avg - 20) * 0.3   # 0 at starting stats, grows with level

    # HP affects pressure: low HP = more likely negative
    hp_bias = (hp_pct - 0.5) * 10  # -5 at 0% HP, +5 at 100% HP

    # SPD reduces variance (more stable)
    variance = max(10, 30 - int(spd * 0.3))

    # Random roll
    roll = random.randint(-variance, variance)

    # Region modifier
    region_mod = REGION_PRESSURE_MOD.get(location, 0)

    # Yoshiwara extra chaos
    if location == "yoshiwara":
        region_mod += random.randint(-10, 10)

    # Final pressure value
    pressure_val = int(roll + stat_bias + hp_bias + region_mod)
    pressure_val = max(-30, min(30, pressure_val))  # clamp

    # Find tier
    tier = PRESSURE_TIERS[-2]  # default suppressed
    for t in PRESSURE_TIERS:
        if t['min'] <= pressure_val <= t['max']:
            tier = t
            break

    return {
        "value":      pressure_val,
        "name":       tier['name'],
        "emoji":      tier['emoji'],
        "atk_mult":   tier['atk_mult'],
        "def_mult":   tier['def_mult'],
        "tech_mult":  tier['tech_mult'],
        "flavor":     tier['flavor'],
        "region_flavor": REGION_FLAVOR.get(location, ""),
        "is_chaos":   location == "yoshiwara",
    }


def get_chaos_modifier():
    """Yoshiwara: each turn a random ±20% modifier applies."""
    return random.uniform(0.80, 1.20)


def pressure_display(pressure, location="asakusa"):
    """Format the pressure block shown at battle start."""
    val_str = f"+{pressure['value']}" if pressure['value'] > 0 else str(pressure['value'])
    lines = [
        f"🌡️ *Spiritual Pressure: {pressure['name']}* `[{val_str}]`",
    ]
    if pressure['region_flavor']:
        lines.append(f"   _{pressure['region_flavor']}_")
    lines.append(f"   _{pressure['flavor']}_")

    # Show multiplier effects if not neutral
    effects = []
    if pressure['atk_mult'] != 1.0:
        sign = "+" if pressure['atk_mult'] > 1 else ""
        effects.append(f"⚔️ ATK {sign}{int((pressure['atk_mult']-1)*100)}%")
    if pressure['def_mult'] != 1.0:
        sign = "+" if pressure['def_mult'] > 1 else ""
        effects.append(f"🛡️ DEF {sign}{int((pressure['def_mult']-1)*100)}%")
    if pressure['tech_mult'] != 1.0:
        sign = "+" if pressure['tech_mult'] > 1 else ""
        effects.append(f"💨 Tech {sign}{int((pressure['tech_mult']-1)*100)}%")
    if pressure['is_chaos']:
        effects.append("🌀 Chaos: DMG varies ±20% per turn")

    if effects:
        lines.append(f"   {' | '.join(effects)}")

    return '\n'.join(lines)
