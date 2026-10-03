"""
utils/spirits.py — Runtime spirit registry + battle spirit presence.

The base roster lives in config.GACHA_SPIRITS, but the owner can open rifts to
*other anime universes* and add spirits at runtime (handlers/gacha_admin.py via
/ownerspirits). Those are stored in the "gacha_spirits" Mongo collection so
they persist across restarts and instantly become summonable by everyone.

This module also powers the "spirit presence" in battle: equipped spirits show
up on the combat screen and occasionally react with flavour lines.
"""
import logging
log = logging.getLogger(__name__)

import random
import re

from utils.database import col, get_equipped_spirits

# In-process cache of the merged roster (config + DB-added spirits)
_cache = {"list": None, "by_name": {}}


def _normalize(doc: dict) -> dict:
    """Strip Mongo artefacts / ensure required keys."""
    s = {k: v for k, v in doc.items() if k != "_id"}
    s.setdefault("name", "")
    s.setdefault("emoji", "👻")
    s.setdefault("rarity", "Common")
    s.setdefault("universe", "Custom")
    s.setdefault("lore", "")
    s.setdefault("image", "")
    s.setdefault("move", "")
    s.setdefault("passive", {})
    return s


def get_all_spirits() -> list:
    """Full summonable roster: config defaults + everything the owner added.

    Spirits the owner removed via /spiritremove (or /spiritadd remove) are
    filtered out through the persistent "gacha_blocked" set — this works even
    for the config.GACHA_SPIRITS defaults, which live in code.
    """
    try:
        from config import GACHA_SPIRITS
        base = [dict(s) for s in GACHA_SPIRITS]
    except Exception:
        base = []
    try:
        extra = [_normalize(d) for d in col("gacha_spirits").find({})]
    except Exception as e:
        log.debug("gacha_spirits collection unavailable: %s", e)
        extra = []
    blocked = blocked_names()
    seen = set()
    roster = []
    for s in base + extra:
        if not s["name"] or s["name"] in seen:
            continue
        if s["name"] in blocked or s["name"].lower() in {b.lower() for b in blocked}:
            continue
        seen.add(s["name"])
        roster.append(s)
    _cache["list"] = roster
    _cache["by_name"] = {s["name"]: s for s in roster}
    return roster


def get_spirit_by_name(name: str) -> dict | None:
    if not _cache["by_name"]:
        get_all_spirits()
    s = _cache["by_name"].get(name)
    if s is None:
        get_all_spirits()
        s = _cache["by_name"].get(name)
    return s


def invalidate_cache():
    _cache["list"] = None
    _cache["by_name"] = {}


def add_spirit_to_pool(spirit: dict) -> bool:
    """Owner command: register a new cross-universe spirit in the gacha pool."""
    name = (spirit.get("name") or "").strip()
    if not name:
        return False
    doc = {
        "name": name,
        "emoji": spirit.get("emoji", "👻"),
        "rarity": spirit.get("rarity", "Rare"),
        "universe": spirit.get("universe", "Custom"),
        "lore": spirit.get("lore", ""),
        "image": spirit.get("image", ""),   # Telegram file_id or https URL
        "move": spirit.get("move", ""),     # signature attack shown in battle logs
        "passive": spirit.get("passive", {}),
    }
    col("gacha_spirits").update_one(
        {"name": name}, {"$set": doc}, upsert=True
    )
    invalidate_cache()
    return True


def get_spirit_image(name: str) -> str | None:
    """Return an owner-uploaded image (file_id or URL) for a spirit, if any."""
    s = get_spirit_by_name(name)
    if s and s.get("image"):
        return s["image"]
    return None


# ── Spirit active moves (shown in battle logs) ─────────────────────────────
_MOVE_FALLBACK = {
    "Common":    "{e} *{n}* lashes out with a spectral strike!",
    "Uncommon":  "{e} *{n}* lunges with a phantom fang!",
    "Rare":      "{e} *{n}* unleashes a piercing spirit blast!",
    "Epic":      "{e} *{n}* summons a devastating aura storm!",
    "Legendary": "{e} *{n}* manifests its ultimate technique — reality trembles!",
}

_MOVE_CHANCE = {"Common": 0.18, "Uncommon": 0.22, "Rare": 0.26,
                "Epic": 0.32, "Legendary": 0.40}


def spirit_move_line(user_id, chance_mult: float = 1.0) -> tuple[str, float] | None:
    """Roll one equipped spirit's signature move.

    Returns (log_line, damage_fraction_of_player_hit) or None when no spirit
    acts this turn. Stronger spirits (higher rarity + ATK passive) strike more
    often and hit harder — this is what makes spirits matter against bosses.
    """
    try:
        docs = get_equipped_spirits(user_id)
    except Exception:
        return None
    if not docs:
        return None
    d = random.choice(docs)
    rarity = d.get("rarity", "Common")
    base_chance = _MOVE_CHANCE.get(rarity, 0.2)
    atk_pct = float((d.get("passive") or {}).get("atk_pct", 0) or 0)
    chance = min(0.55, (base_chance + atk_pct * 0.5) * chance_mult)
    if random.random() > chance:
        return None
    move = d.get("move") or _MOVE_FALLBACK.get(rarity, _MOVE_FALLBACK["Common"])
    line = move.format(e=d.get("emoji", "👻"), n=d.get("name", "Spirit"))
    # Damage fraction of the player's own hit: Legendaries hit like a bonus ally.
    dmg_frac = {"Common": 0.10, "Uncommon": 0.15, "Rare": 0.22,
                "Epic": 0.32, "Legendary": 0.45}.get(rarity, 0.12) + atk_pct * 0.5
    return line, round(min(0.75, dmg_frac), 3)


def find_pool_spirit(name: str) -> dict | None:
    """Case-insensitive lookup of a spirit in the merged pool (config + runtime)."""
    if not name:
        return None
    target = name.strip().lower()
    for s in get_all_spirits():
        if (s.get("name") or "").strip().lower() == target:
            return s
    return None


def remove_spirit_from_pool(name: str) -> bool:
    """Remove a runtime-added spirit from the summon pool (case-insensitive).

    NOTE: config.GACHA_SPIRITS defaults live in code, not the DB — they cannot
    be deleted at runtime. Use block_spirit() to pull them out of the pool
    without touching config.py.
    """
    doc = None
    try:
        doc = col("gacha_spirits").find_one(
            {"name": {"$regex": f"^{re.escape(name.strip())}$", "$options": "i"}}
        )
    except Exception as e:
        log.debug("gacha_spirits remove lookup failed: %s", e)
    if not doc:
        return False
    res = col("gacha_spirits").delete_one({"_id": doc["_id"]})
    # Also drop any block flag so re-adding later works cleanly.
    try:
        col("gacha_blocked").delete_many({"name": doc["name"]})
    except Exception:
        pass
    invalidate_cache()
    return res.deleted_count > 0


# ── Blocking spirits (works for config defaults too) ───────────────────────
# Owner-added spirits are stored in Mongo and can simply be deleted. The base
# roster lives in config.GACHA_SPIRITS (code), so to remove one of *those*
# from gacha at runtime we keep its name in a small "gacha_blocked" collection
# that get_all_spirits() filters out. Persists across restarts.

def blocked_names() -> set:
    try:
        return {d.get("name", "") for d in col("gacha_blocked").find({})}
    except Exception as e:
        log.debug("gacha_blocked read failed: %s", e)
        return set()


def block_spirit(name: str) -> bool:
    """Pull a spirit out of the summon pool (works for config defaults too)."""
    name = (name or "").strip()
    if not name:
        return False
    col("gacha_blocked").update_one(
        {"name": name}, {"$set": {"name": name}}, upsert=True
    )
    invalidate_cache()
    return True


def unblock_spirit(name: str) -> bool:
    """Undo block_spirit() — the spirit becomes summonable again."""
    name = (name or "").strip()
    if not name:
        return False
    doc = col("gacha_blocked").find_one(
        {"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}
    )
    if not doc:
        return False
    col("gacha_blocked").delete_one({"_id": doc["_id"]})
    invalidate_cache()
    return True


# ── Guardian protection: spirits absorb part of incoming boss damage ───────
_GUARD_PCT = {"Common": 0.03, "Uncommon": 0.05, "Rare": 0.08,
              "Epic": 0.12, "Legendary": 0.18}


def spirit_guard_reduction(user_id) -> tuple[float, str | None]:
    """Return (damage_reduction_fraction, optional log line).

    Each equipped spirit shaves a slice off incoming enemy damage; strong
    (Epic/Legendary) spirits can fully guard a blow occasionally. This is the
    defensive half of why spirits matter against the now very-strong bosses.
    """
    try:
        docs = get_equipped_spirits(user_id)
    except Exception:
        return 0.0, None
    if not docs:
        return 0.0, None
    total = 0.0
    best = None
    for d in docs:
        pct = _GUARD_PCT.get(d.get("rarity", "Common"), 0.03)
        pct += float((d.get("passive") or {}).get("def_pct", 0) or 0) * 0.5
        total += pct
        if best is None or pct > best[0]:
            best = (pct, d)
    reduction = min(0.45, total)
    # Chance for a full guard (spirit tanks the hit): scales with rarity
    if best:
        guard_chance = min(0.20, best[0] * 0.6)
        if random.random() < guard_chance:
            d = best[1]
            line = (f"{d.get('emoji','👻')} *{d.get('name','Spirit')}* throws itself "
                    f"in front of the blow — damage nullified!")
            return 1.0, line
    return reduction, None


def get_universes() -> list:
    """All universes present in the roster (config starter list + runtime ones)."""
    universes = []
    try:
        from config import GACHA_UNIVERSES
        universes.extend(GACHA_UNIVERSES)
    except Exception:
        pass
    for s in get_all_spirits():
        u = s.get("universe") or "Custom"
        if u not in universes:
            universes.append(u)
    return universes


def spirits_in_universe(universe: str) -> list:
    return [s for s in get_all_spirits() if (s.get("universe") or "") == universe]


def cross_universe_spirits() -> list:
    """Spirits that are NOT from the game's home universe (Demon Slayer) —
    i.e. everything the owner has added from other anime universes at runtime,
    plus any config spirits tagged with another universe."""
    try:
        from config import GACHA_HOME_UNIVERSE
    except Exception:
        GACHA_HOME_UNIVERSE = "Demon Slayer"
    return [s for s in get_all_spirits()
            if (s.get("universe") or GACHA_HOME_UNIVERSE) != GACHA_HOME_UNIVERSE]


# ── Battle presence ────────────────────────────────────────────────────────
def equipped_spirit_names(user_id) -> list:
    """Short display entries for the combat header, e.g. ['🦊 Nine-Tailed Kitsune']."""
    try:
        docs = get_equipped_spirits(user_id)
    except Exception:
        return []
    out = []
    for d in docs:
        emoji = d.get("emoji") or "👻"
        uni = d.get("universe") or ""
        tag = f" · {uni}" if uni and uni != "Demon Slayer" else ""
        out.append(f"{emoji} {d.get('name', '?')}{tag}")
    return out


def spirit_battle_line(user_id, kind: str, chance: float = 0.35) -> str | None:
    """Occasional flavour line from one of the player's equipped spirits.
    Returns None when no spirit reacts this turn (keeps battle log clean)."""
    try:
        from config import SPIRIT_BATTLE_LINES
        lines = SPIRIT_BATTLE_LINES.get(kind)
        if not lines:
            return None
        docs = get_equipped_spirits(user_id)
        if not docs or random.random() > chance:
            return None
        d = random.choice(docs)
        tmpl = random.choice(lines)
        return tmpl.format(e=d.get("emoji", "👻"), n=d.get("name", "Spirit"))
    except Exception:
        return None
