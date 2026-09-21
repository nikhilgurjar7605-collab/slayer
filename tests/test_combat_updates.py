import random

from utils.combat_updates import (
    apply_exploration_event,
    boss_phase_for,
    boss_phase_transition,
    choose_enemy_action,
    encounter_preview,
    reward_multiplier,
    roll_exploration_event,
    validate_enemy_catalog,
)


def test_event_roll_is_deterministic_and_weighted():
    assert roll_exploration_event(random.Random(0)).key == "ambush"
    assert roll_exploration_event(random.Random(1)).key == "normal"
    assert roll_exploration_event(random.Random(0), boss=True).key == "mystery"


def test_normalize_and_apply_event():
    enemy = apply_exploration_event(
        {"name": "Wolf", "hp": 100, "atk": 10, "xp": 100, "yen": 50},
        roll_exploration_event(random.Random(1)),
    )
    assert enemy["id"] == "wolf"
    assert enemy["hp"] == 100
    assert enemy["xp"] == 100
    assert "event_label" in enemy


def test_boss_phase_transitions():
    assert boss_phase_for(1000, 1000, True)[0] == 1
    assert boss_phase_for(700, 1000, True)[0] == 2
    transition = boss_phase_transition(800, 700, 1000, True)
    assert transition["phase"] == 2
    assert boss_phase_transition(650, 600, 1000, True) is None


def test_enemy_ai_priorities():
    action, _ = choose_enemy_action({"abilities": ["regeneration"]}, 20, 100, random.Random(1))
    assert action == "regenerate"
    action, _ = choose_enemy_action({"abilities": ["freeze"]}, 80, 100, random.Random(1))
    assert action == "status_attack"


def test_preview_and_reward_bonuses():
    enemy = {"name": "Boss", "hp": 1000, "atk": 100, "xp": 100, "yen": 100, "drops": ["Shard"], "is_boss": True}
    preview = encounter_preview(enemy, 10)
    assert preview["threat"] == "HIGH"
    multiplier, bonuses = reward_multiplier(enemy, 3, 90, 100)
    assert multiplier > 1.0
    assert bonuses


def test_catalog_validation():
    errors = validate_enemy_catalog([
        {"name": "A", "hp": 1, "atk": 1, "xp": 1, "yen": 1},
        {"name": "A", "hp": 1, "atk": 1, "xp": 1, "yen": 1},
    ])
    assert any("duplicate" in error for error in errors)
