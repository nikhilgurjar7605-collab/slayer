"""
migrate_sqlite_to_mongo.py
Run this ONCE to copy your old SQLite bot.db into MongoDB Atlas.

Usage:
    python migrate_sqlite_to_mongo.py

Put this file in the same folder as bot.py.
Point SQLITE_PATH to your old .db file below.
"""

import sqlite3
import json
from datetime import datetime
from pymongo import MongoClient

# ── CONFIG ────────────────────────────────────────────────────────────────
SQLITE_PATH = "data/game.db"       # ← change this if your db file is elsewhere
                                    #   common names: bot.db, game.db, demon_slayer.db
MONGO_URL   = "mongodb+srv://yesvashisht2005_db_user:rjuAwTHG8qO6545f@cluster0.nwvwqpj.mongodb.net/?appName=Cluster0"
DB_NAME     = "demon_slayer_rpg"
# ─────────────────────────────────────────────────────────────────────────

def sqlite_rows_to_dicts(cursor, table):
    try:
        cursor.execute(f"SELECT * FROM {table}")
        cols = [d[0] for d in cursor.description]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]
    except Exception as e:
        print(f"  ⚠️  Could not read {table}: {e}")
        return []


def migrate():
    print(f"\n🔄 Connecting to SQLite: {SQLITE_PATH}")
    try:
        sqlite = sqlite3.connect(SQLITE_PATH)
        sqlite.row_factory = sqlite3.Row
        cur = sqlite.cursor()
    except Exception as e:
        print(f"❌ Could not open SQLite DB: {e}")
        print(f"   Make sure SQLITE_PATH is correct. Common locations:")
        print(f"   - data/game.db")
        print(f"   - bot.db")
        print(f"   - demon_slayer.db")
        return

    print(f"✅ SQLite connected")
    print(f"🔄 Connecting to MongoDB Atlas...")

    try:
        client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
        client.server_info()
        mdb = client[DB_NAME]
        print(f"✅ MongoDB connected — database: {DB_NAME}\n")
    except Exception as e:
        print(f"❌ MongoDB connection failed: {e}")
        return

    # Tables to migrate — in order
    TABLES = [
        "players",
        "inventory",
        "arts",
        "battle_state",
        "parties",
        "party_invites",
        "clans",
        "clan_invites",
        "admins",
        "gift_log",
        "skill_tree",
        "market_listings",
        "custom_missions",
        "vote_missions",
        "vote_records",
        "black_market",
        "bank_accounts",
        "status_effects",
        "coop_battles",
        "referrals",
        "raids",
        "raid_participants",
        "auctions",
        "duels",
    ]

    total_migrated = 0

    for table in TABLES:
        rows = sqlite_rows_to_dicts(cur, table)
        if not rows:
            print(f"  ⏭️  {table}: empty or not found — skipped")
            continue

        collection = mdb[table]

        # Clear existing data in MongoDB collection first
        deleted = collection.delete_many({}).deleted_count
        if deleted:
            print(f"  🗑️  {table}: cleared {deleted} existing MongoDB docs")

        # Add sequential id field to each row if not present
        for i, row in enumerate(rows):
            if "id" not in row and "user_id" not in row:
                row["id"] = i + 1
            # Convert members/treasury JSON strings to lists
            for field in ["members", "treasury", "prize_drops", "battle_log"]:
                if field in row and isinstance(row[field], str):
                    try:
                        row[field] = json.loads(row[field])
                    except Exception:
                        pass

        try:
            result = collection.insert_many(rows, ordered=False)
            count = len(result.inserted_ids)
            print(f"  ✅ {table}: {count} records migrated")
            total_migrated += count
        except Exception as e:
            print(f"  ❌ {table}: insert failed — {e}")

    sqlite.close()
    print(f"\n{'='*50}")
    print(f"✅ MIGRATION COMPLETE")
    print(f"📊 Total records migrated: {total_migrated}")
    print(f"🎮 Your bot data is now in MongoDB Atlas!")
    print(f"{'='*50}\n")
    print("You can now run: python bot.py")


if __name__ == "__main__":
    # Auto-detect SQLite file location
    import os
    possible_paths = [
        "data/game.db", "data/bot.db", "data/demon_slayer.db",
        "bot.db", "game.db", "demon_slayer.db",
        "data/database.db", "database.db"
    ]
    if not os.path.exists(SQLITE_PATH):
        print(f"⚠️  Default path '{SQLITE_PATH}' not found. Searching...")
        for path in possible_paths:
            if os.path.exists(path):
                SQLITE_PATH = path
                print(f"✅ Found SQLite DB at: {SQLITE_PATH}")
                break
        else:
            print("\n❌ Could not find your SQLite database file.")
            print("Please set SQLITE_PATH at the top of this script.")
            print("\nSearched in:")
            for p in possible_paths:
                print(f"  - {p}")
            exit(1)

    migrate()
