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
    s.setdefault("passive", {})
    return s


def get_all_spirits() -> list:
    """Full summonable roster: config defaults + everything the owner added."""
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
    seen = set()
    roster = []
    for s in base + extra:
        if s["name"] and s["name"] not in seen:
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
        "passive": spirit.get("passive", {}),
    }
    col("gacha_spirits").update_one(
        {"name": name}, {"$set": doc}, upsert=True
    )
    invalidate_cache()
    return True


def remove_spirit_from_pool(name: str) -> bool:
    res = col("gacha_spirits").delete_one({"name": name})
    invalidate_cache()
    return res.deleted_count > 0


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
