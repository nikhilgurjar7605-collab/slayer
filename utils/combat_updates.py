"""Pure helpers for Combat & Exploration v2.

These helpers deliberately avoid Telegram and MongoDB imports so they can be
unit-tested independently from the bot runtime.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
import random


@dataclass(frozen=True)
class ExplorationEvent:
    key: str
    label: str
    description: str
    xp_multiplier: float = 1.0
    yen_multiplier: float = 1.0
    attack_multiplier: float = 1.0
    damage_on_start: int = 0


EXPLORATION_EVENTS = (
    ExplorationEvent("normal", "🌲 WILD ENCOUNTER", "The area is quiet... for now."),
    ExplorationEvent("elite", "⚔️ ELITE ENCOUNTER", "A stronger enemy blocks your path.", 1.35, 1.25, 1.10),
    ExplorationEvent("treasure", "🎁 TREASURE TRAIL", "The enemy is guarding a valuable cache.", 1.20, 1.60),
    ExplorationEvent("ambush", "🩸 AMBUSH", "The enemy strikes before you can prepare.", 1.10, 1.10, 1.0, 5),
    ExplorationEvent("mystery", "❓ MYSTERY EVENT", "Strange signs hint at a rare encounter.", 1.50, 1.35, 1.05),
)

BOSS_PHASES = (
    (0.70, 2, "ENRAGED", 1.20, "The boss roars and its attacks become stronger!"),
    (0.35, 3, "DESPERATE", 1.45, "The boss enters a desperate final phase!"),
)

ENEMY_ACTIONS = {
    "aggressive": ("heavy_attack", "The enemy commits to a heavy strike."),
    "defensive": ("guard", "The enemy raises its guard."),
    "regenerator": ("regenerate", "The enemy attempts to recover HP."),
    "control": ("status_attack", "The enemy prepares a status attack."),
    "normal": ("basic_attack", "The enemy attacks."),
}


def event_by_key(key: str) -> ExplorationEvent:
    return next((e for e in EXPLORATION_EVENTS if e.key == key), EXPLORATION_EVENTS[0])


def roll_exploration_event(rng: random.Random | None = None, boss: bool = False) -> ExplorationEvent:
    rng = rng or random
    if boss:
        return event_by_key("mystery")
    roll = rng.random()
    if roll < 0.50:
        return event_by_key("normal")
    if roll < 0.65:
        return event_by_key("elite")
    if roll < 0.75:
        return event_by_key("treasure")
    if roll < 0.90:
        return event_by_key("ambush")
    return event_by_key("mystery")


def normalize_enemy(enemy: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(enemy)
    result.setdefault("id", str(result.get("name", "unknown_enemy")).lower().replace(" ", "_"))
    result.setdefault("defense", 0)
    result.setdefault("abilities", [])
    result.setdefault("drops", [])
    result.setdefault("is_boss", False)
    result.setdefault("faction_type", "neutral")
    result.setdefault("threat", "🟢 LOW")
    result["hp"] = int(result.get("hp", 100))
    result["atk"] = int(result.get("atk", 10))
    result["xp"] = int(result.get("xp", 0))
    result["yen"] = int(result.get("yen", 0))
    if isinstance(result["abilities"], str):
        result["abilities"] = [result["abilities"]]
    if not result["abilities"]:
        name = str(result.get("name", "")).lower()
        if result.get("is_boss"):
            result["abilities"] = ["berserk"]
        elif any(word in name for word in ("ice", "doma", "freeze")):
            result["abilities"] = ["freeze"]
        elif any(word in name for word in ("spider", "web", "poison")):
            result["abilities"] = ["poison"]
        else:
            result["abilities"] = ["basic_attack"]
    return result


def apply_exploration_event(enemy: Mapping[str, Any], event: ExplorationEvent) -> dict[str, Any]:
    result = normalize_enemy(enemy)
    result["event_key"] = event.key
    result["event_label"] = event.label
    result["event_description"] = event.description
    result["xp"] = int(result["xp"] * event.xp_multiplier)
    result["yen"] = int(result["yen"] * event.yen_multiplier)
    result["atk"] = max(1, int(result["atk"] * event.attack_multiplier))
    if event.key == "elite":
        result["threat"] = "🟠 ELITE"
        result["is_elite"] = True
    elif event.key == "treasure":
        result["bonus_drop_chance"] = 0.25
    elif event.key == "ambush":
        result["ambush_damage"] = event.damage_on_start
    return result


def boss_phase_for(current_hp: int, max_hp: int, is_boss: bool) -> tuple[int, str, float]:
    if not is_boss or max_hp <= 0:
        return 1, "NORMAL", 1.0
    ratio = current_hp / max_hp
    for threshold, phase, name, multiplier, _ in BOSS_PHASES:
        if ratio <= threshold:
            return phase, name, multiplier
    return 1, "NORMAL", 1.0


def boss_phase_transition(previous_hp: int, current_hp: int, max_hp: int, is_boss: bool) -> dict[str, Any] | None:
    old_phase, _, _ = boss_phase_for(previous_hp, max_hp, is_boss)
    new_phase, name, multiplier = boss_phase_for(current_hp, max_hp, is_boss)
    if new_phase <= old_phase:
        return None
    message = next(text for threshold, phase, _, _, text in BOSS_PHASES if phase == new_phase)
    return {"phase": new_phase, "name": name, "attack_multiplier": multiplier, "message": message}


def choose_enemy_action(enemy: Mapping[str, Any], enemy_hp: int, enemy_max_hp: int, rng: random.Random | None = None) -> tuple[str, str]:
    rng = rng or random
    abilities = set(enemy.get("abilities", []) or [])
    ratio = enemy_hp / max(1, enemy_max_hp)
    if ratio <= 0.30 and ({"regeneration", "regenerator"} & abilities):
        return ENEMY_ACTIONS["regenerator"]
    if "guard" in abilities and ratio <= 0.55 and rng.random() < 0.35:
        return ENEMY_ACTIONS["defensive"]
    if {"status_attack", "poison", "freeze"} & abilities:
        return ENEMY_ACTIONS["control"]
    if "berserk" in abilities or ratio <= 0.35:
        return ENEMY_ACTIONS["aggressive"]
    return ENEMY_ACTIONS["normal"]


def status_summary(effects: list[Mapping[str, Any]] | None) -> list[str]:
    lines = []
    for effect in effects or []:
        name = effect.get("effect", effect.get("name", "Effect"))
        turns = effect.get("turns_left", effect.get("turns", "?"))
        stacks = effect.get("stacks")
        suffix = f" ×{stacks}" if stacks and stacks != 1 else ""
        lines.append(f"{name}{suffix} ({turns} turns)")
    return lines


def reward_multiplier(enemy: Mapping[str, Any], turns: int, player_hp: int, player_max_hp: int, used_items: int = 0) -> tuple[float, list[str]]:
    multiplier = 1.0
    bonuses: list[str] = []
    if enemy.get("is_boss"):
        multiplier *= 1.25
        bonuses.append("Boss victory +25%")
    if enemy.get("is_elite"):
        multiplier *= 1.15
        bonuses.append("Elite victory +15%")
    if turns <= 5:
        multiplier *= 1.15
        bonuses.append("Quick victory +15%")
    if player_max_hp and player_hp / player_max_hp >= 0.80:
        multiplier *= 1.10
        bonuses.append("High HP +10%")
    if used_items == 0:
        multiplier *= 1.10
        bonuses.append("No-item victory +10%")
    return multiplier, bonuses


def encounter_preview(enemy: Mapping[str, Any], player_level: int) -> dict[str, Any]:
    enemy = normalize_enemy(enemy)
    threat = "HIGH" if enemy.get("is_boss") else ("MODERATE" if enemy.get("is_elite") else "NORMAL")
    return {
        "name": enemy["name"],
        "threat": threat,
        "hp": enemy["hp"],
        "attack": enemy["atk"],
        "recommended_level": max(1, int(enemy["hp"] / 35)),
        "player_level": player_level,
        "drops": list(enemy.get("drops", [])),
        "event_label": enemy.get("event_label", "🌲 WILD ENCOUNTER"),
        "event_description": enemy.get("event_description", ""),
    }


def validate_enemy_catalog(enemies: list[Mapping[str, Any]]) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for enemy in enemies:
        name = str(enemy.get("name", "")).strip()
        if not name:
            errors.append("enemy is missing name")
            continue
        key = name.lower()
        if key in seen:
            errors.append(f"duplicate enemy: {name}")
        seen.add(key)
        for field in ("hp", "atk", "xp", "yen"):
            if int(enemy.get(field, 0)) < 0:
                errors.append(f"{name}: {field} must be non-negative")
    return errors
