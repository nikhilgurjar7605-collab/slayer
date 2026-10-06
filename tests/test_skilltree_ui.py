"""Tests for the compact card-style Skill Tree UI (handlers/skilltree._build_page)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")

from handlers.skilltree import _build_page, TOTAL_SKILL_COUNT, PAGE_SIZE


def test_mockup_layout():
    """Reproduces the reference UI: 12 SP, nothing owned, page 1."""
    text, kb, tp = _build_page([], 0, sp=12)
    lines = text.splitlines()
    assert lines[0] == "⚔️ SKILL TREE"
    assert lines[1] == f"💠 12 SP  •  🧠 0/{TOTAL_SKILL_COUNT}"
    assert set(lines[2]) == {"─"}
    assert "🟢 Iron Body        5 SP" in text
    assert "   🛡 DMG −10%" in text
    # Locked skills show 🔒 + how much more SP is needed
    assert "🔒 Berserker        13 SP" in text
    assert "🔸 +1 SP required" in text
    assert "🔒 Devour Soul      16 SP" in text
    assert "🔸 +4 SP required" in text
    # Backlash marked with ⚠
    assert "⚠ 🛡 DEF −5%" in text
    # Pagination footer
    assert f"─────── 1 / {tp} ───────" in text
    print("TEST 1 PASS: mockup layout reproduced")


def test_badges_and_buttons():
    # Affordable → 🟢, owned → ✅ (no buy button), unaffordable → 🔒
    text, kb, _ = _build_page(["Iron Body"], 0, sp=12)
    assert "✅ Iron Body" in text and "🟢 Sharp Eye" in text and "🔒 Berserker" in text
    btn_texts = [b.text for row in kb.inline_keyboard for b in row]
    assert not any("Iron Body" in t for t in btn_texts), "owned skill must have no buy button"
    assert any(t.startswith("💠 Bloodlust — 10 SP") for t in btn_texts)
    assert any("Berserker" in t and "🔒" in t for t in btn_texts)
    print("TEST 2 PASS: badges & buy buttons correct")


def test_navigation_rows():
    _, kb, tp = _build_page([], 0, sp=50)
    rows = [[b.text for b in r] for r in kb.inline_keyboard]
    nav = next(r for r in rows if "◀ PREV" in r or "NEXT ▶" in r or "•" in r)
    assert nav[0] == "•"                      # first page: prev disabled
    assert nav[-1] == "NEXT ▶"
    assert nav[1] == f"1/{tp}"
    # Last page clamps and disables NEXT
    _, kb_last, _ = _build_page([], 999, sp=50)
    last_nav = [b.text for b in kb_last.inline_keyboard][-3:-2][0] if False else \
        next([b.text for b in r] for r in kb_last.inline_keyboard if any(b.text == "◀ PREV" for b in r))
    assert last_nav[0] == "◀ PREV" and last_nav[2] == "•"
    print("TEST 3 PASS: prev/next navigation rows")


def test_all_pages_fit_telegram_limits():
    for sp in (0, 12, 50, 100):
        _, _, tp = _build_page([], 0, sp=sp)
        for p in range(tp):
            t, kb, _ = _build_page(["Iron Body", "Bloodlust"], p, sp=sp)
            assert len(t) < 4096, f"page {p} too long ({len(t)})"
            max_cards = 4 + PAGE_SIZE * 5  # header(3)+blank + worst-case 4-line card + blank
            assert len(t.splitlines()) <= max_cards, "cards exceed line budget"
            for row in kb.inline_keyboard:
                assert len(row) <= 3
                for b in row:
                    assert b.callback_data and len(b.callback_data) <= 64
    print("TEST 4 PASS: all pages within Telegram limits")


def test_category_filter_still_works():
    t, kb, tp = _build_page([], 0, sp=50, category_filter="Combat")
    assert "Iron Body" in t and f"1 / {tp}" in t
    print("TEST 5 PASS: category filter renders")


if __name__ == "__main__":
    test_mockup_layout()
    test_badges_and_buttons()
    test_navigation_rows()
    test_all_pages_fit_telegram_limits()
    test_category_filter_still_works()
    print("\nALL SKILL TREE UI TESTS PASSED ✔")
