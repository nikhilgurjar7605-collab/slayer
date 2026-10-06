"""Regression tests for the redesigned WILD ENCOUNTER card-style UI."""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")

import importlib.util as _ilu
_spec = _ilu.spec_from_file_location('config', os.path.join(os.path.dirname(__file__), '..', 'config.py'))
cfg = _ilu.module_from_spec(_spec)
sys.modules['config'] = cfg
_spec.loader.exec_module(cfg)

from handlers.explore import _encounter_unit_card, format_hp_bar_poke
from utils.combat_updates import encounter_preview


def build_encounter_lines(enemy, player, player_level, active_pet=None):
    """Mirror of the UI block in explore.spawn_encounter for validation."""
    p = encounter_preview(enemy, player_level)
    SEP = "⎯" * 37
    threat_icon = {'HIGH': '🔴', 'MODERATE': '🟡'}.get(p['threat'], '⚪')
    event_desc = p.get('event_description') or "The area is quiet..."
    footer = (f"🐾 {active_pet['name']}: Active" if active_pet else p['event_label'])
    footer += f"  //  ⭐ {enemy['xp']:,} XP  •  💰 {enemy['yen']:,}¥"
    return [
        f"🌲 *WILD ENCOUNTER*  //  {event_desc}",
        f"{threat_icon} Threat: *{p['threat']}*  •  Rec. Lv. {p['recommended_level']}",
        SEP, "",
        _encounter_unit_card(enemy['name'].upper(), p['recommended_level'], enemy['hp'], enemy['hp']),
        "",
        _encounter_unit_card(f"『{player['name']}』", player_level, player['hp'], player['max_hp']),
        "",
        SEP,
        footer,
    ]


def test_normal_encounter_layout():
    enemy = {'name': 'Rogue Demon', 'hp': 187, 'atk': 40, 'xp': 420, 'yen': 240, 'drops': []}
    player = {'name': 'Kasugai', 'hp': 285, 'max_hp': 285}
    text = "\n".join(build_encounter_lines(enemy, player, 5, {'name': 'Kasugai Crow'}))
    assert text.startswith("🌲 *WILD ENCOUNTER*  //  The area is quiet...")
    assert "⚪ Threat: *NORMAL*  •  Rec. Lv. 5" in text
    assert "⦿ ROGUE DEMON\n   Lv. 5  │  ❤️ 187/187\n   ████████████████████" in text
    assert "⦿ 『Kasugai』\n   Lv. 5  │  ❤️ 285/285\n   ████████████████████" in text
    assert text.endswith("🐾 Kasugai Crow: Active  //  ⭐ 420 XP  •  💰 240¥")
    # separators are full-width lines
    seps = [l for l in text.split("\n") if set(l) == {"⎯"}]
    assert len(seps) == 2 and all(len(s) == 37 for s in seps)


def test_boss_and_no_pet_variants():
    enemy = {'name': 'Spider Demon', 'hp': 900, 'atk': 80, 'xp': 1500, 'yen': 900,
             'drops': [], 'is_boss': True}
    player = {'name': 'Hana', 'hp': 120, 'max_hp': 400}
    lines = build_encounter_lines(enemy, player, 9)
    text = "\n".join(lines)
    assert "🔴 Threat: *HIGH*" in text
    assert "🌲 WILD ENCOUNTER  //  ⭐ 1,500 XP  •  💰 900¥" in text
    # damaged player bar must not exceed bar width (bars start with █ or end with ░)
    card = [l for l in "\n".join(lines).split("\n")
            if l.strip().startswith("█") or l.strip().endswith("░")]
    assert card, "expected at least one HP bar line"
    for c in card:
        assert len(c) == 3 + 20  # 3-space indent + 20-cell bar


def test_hp_bar_damage_shows_empty_cells():
    card = _encounter_unit_card("SLAYER", 3, 50, 200)
    assert "❤️ 50/200" in card
    bars = [l.strip() for l in card.split("\n") if set(l.strip()) <= set("█░")]
    assert len(bars[0]) == 20
    assert bars[0].count("█") == 5 and bars[0].count("░") == 15


if __name__ == "__main__":
    test_normal_encounter_layout()
    test_boss_and_no_pet_variants()
    test_hp_bar_damage_shows_empty_cells()
    print("All encounter UI tests passed ✓")
