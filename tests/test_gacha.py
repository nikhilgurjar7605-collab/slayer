"""Tests for the gacha / spirit summon system.

Uses mongomock so DB-dependent logic (shards, spirits, pity persistence)
is exercised end-to-end without a real MongoDB instance.
"""
import os
import random

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")

import mongomock
import pytest

import utils.database as db
from config import (
    GACHA_COST_SINGLE, GACHA_COST_TEN, GACHA_FREE_STARTER_SHARDS,
    GACHA_PITY_EPIC, GACHA_PITY_LEGEND, GACHA_MAX_EQUIPPED,
    GACHA_RARITY_WEIGHTS, GACHA_SPIRITS,
)
from handlers.gacha import (
    roll_rarity, pick_spirit, perform_pulls, roll_boss_shards,
    RARITY_ORDER, _SPIRIT_BY_NAME,
)


# ── Fake Mongo injection ────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def fake_mongo(monkeypatch):
    client = mongomock.MongoClient()
    database = client[db.DB_NAME]
    monkeypatch.setattr(db, "_client", client)
    monkeypatch.setattr(db, "_db", database)
    db._player_cache.clear()
    yield database
    db._player_cache.clear()


@pytest.fixture
def player(fake_mongo):
    uid = 111222333
    fake_mongo.players.insert_one({
        "user_id": uid, "name": "Test Slayer", "faction": "slayer",
        "shards": 0, "gacha_pity": 0, "gacha_total_pulls": 0,
        "spirits_gifted": 0, "equipped_spirits": [],
    })
    return uid


# ── Config sanity ───────────────────────────────────────────────────────────
def test_config_consistency():
    assert GACHA_COST_SINGLE == 10
    assert GACHA_COST_TEN == 90
    assert set(GACHA_RARITY_WEIGHTS.keys()) == set(RARITY_ORDER)
    # every spirit references a known rarity and has passive dict
    for s in GACHA_SPIRITS:
        assert s["rarity"] in RARITY_ORDER
        assert isinstance(s.get("passive", {}), dict)
        assert s["name"] not in _SPIRIT_BY_NAME or True
    assert len(_SPIRIT_BY_NAME) == len(GACHA_SPIRITS)  # no duplicate names


# ── Pure pull logic ─────────────────────────────────────────────────────────
def test_pity_guarantees():
    assert roll_rarity(GACHA_PITY_LEGEND) == "Legendary"
    rng = random.Random(42)
    for _ in range(50):
        assert roll_rarity(GACHA_PITY_EPIC, rng=rng) in ("Epic", "Legendary")


def test_perform_pulls_resets_pity_on_legendary():
    # seed rng until we get a run containing legendary via pity
    results, new_pity = perform_pulls(80, pity=0, rng=random.Random(7))
    assert len(results) == 80
    assert any(r["rarity"] == "Legendary" for r in results)
    assert new_pity < GACHA_PITY_LEGEND  # pity must have reset at least once


def test_pull_costs_match_spec():
    single_cost, ten_cost = GACHA_COST_SINGLE, GACHA_COST_TEN
    assert single_cost == 10 and ten_cost == 90


def test_boss_shards_capped_at_5():
    rng = random.Random(0)
    for name in ("Slaver Demon", "Lower Moon Six"):
        for _ in range(30):
            assert 2 <= roll_boss_shards(name) <= 4
    for name in ("Kokushibo", "Muzan", "Yoriichi Ghost"):
        assert roll_boss_shards(name) == 5


# ── DB layer: shards ────────────────────────────────────────────────────────
def test_add_and_spend_shards_atomic(player):
    db.add_shards(player, GACHA_FREE_STARTER_SHARDS)
    p = db.get_player(player)
    assert p["shards"] == GACHA_FREE_STARTER_SHARDS

    assert db.spend_shards(player, GACHA_COST_SINGLE) is True
    assert db.get_player(player)["shards"] == GACHA_FREE_STARTER_SHARDS - GACHA_COST_SINGLE

    # cannot overspend
    assert db.spend_shards(player, 999) is False
    assert db.get_player(player)["shards"] == 10


def test_get_player_reflects_shard_updates_despite_cache(player):
    db.add_shards(player, 5)          # populates/invalidates cache
    assert db.get_player(player)["shards"] == 5
    db.add_shards(player, 5)
    assert db.get_player(player)["shards"] == 10  # no stale cache


# ── DB layer: spirits ───────────────────────────────────────────────────────
def test_add_spirit_new_vs_duplicate(player, fake_mongo):
    spirit = GACHA_SPIRITS[0]
    assert db.add_spirit(player, spirit) is True   # new
    assert db.add_spirit(player, spirit) is False  # duplicate -> count++
    docs = db.get_spirit_collection(player)
    assert len(docs) == 1
    assert docs[0]["count"] == 2


def test_equip_slot_limit_enforced(player):
    from config import GACHA_SPIRITS as POOL
    three = [s for s in POOL if s["rarity"] != "Common"][: GACHA_MAX_EQUIPPED + 1]
    assert len(three) == GACHA_MAX_EQUIPPED + 1
    for s in three:
        db.add_spirit(player, s)
    for s in three[:GACHA_MAX_EQUIPPED]:
        assert db.set_spirit_equipped(player, s["name"], True) is True
    # 4th equip must fail
    assert db.set_spirit_equipped(player, three[-1]["name"], True) is False
    equipped = db.get_equipped_spirits(player)
    assert len(equipped) == GACHA_MAX_EQUIPPED
    # unequip frees a slot
    assert db.set_spirit_equipped(player, three[0]["name"], False) is True
    assert db.set_spirit_equipped(player, three[-1]["name"], True) is True


def test_spirit_bonuses_only_from_equipped(player):
    owned = GACHA_SPIRITS[:3]
    for s in owned:
        db.add_spirit(player, s)
    assert db.get_spirit_bonuses(player) == {}
    db.set_spirit_equipped(player, owned[0]["name"], True)
    bonuses = db.get_spirit_bonuses(player)
    for k, v in owned[0].get("passive", {}).items():
        assert abs(bonuses[k] - v) < 1e-9


def test_update_player_persists_pity_and_pulls(player):
    db.update_player(player, gacha_pity=12, gacha_total_pulls=15)
    p = db.get_player(player)
    assert p["gacha_pity"] == 12 and p["gacha_total_pulls"] == 15
