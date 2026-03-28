"""
/sqlview — Admin command to view data from a SQLite backup database.
Lets admins query their old bot.db or any SQLite file for data recovery.

Usage:
  /sqlview tables                     — List all tables
  /sqlview players                    — Show all players
  /sqlview players @username          — Find player by username
  /sqlview inventory [user_id]        — Show inventory
  /sqlview clans                      — List all clans
  /sqlview [table] [id]               — Show record by user_id or id
  /sqlview raw [SQL query]            — Run a raw SELECT query (read-only)
"""

import sqlite3
import os
from telegram import Update
from telegram.ext import ContextTypes
from handlers.admin import has_admin_access

# Path to your SQLite backup file — change this if different
SQLITE_PATHS = [
    "data/game.db",
    "data/bot.db",
    "bot.db",
    "game.db",
    "demon_slayer.db",
    "data/demon_slayer.db",
]

def find_sqlite():
    for path in SQLITE_PATHS:
        if os.path.exists(path):
            return path
    return None

def query_sqlite(sql, params=()):
    """Execute a read-only query on the SQLite DB. Returns (cols, rows) or error string."""
    db_path = find_sqlite()
    if not db_path:
        return None, f"❌ No SQLite file found.\nSearched: {', '.join(SQLITE_PATHS)}"
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur  = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        conn.close()
        return cols, rows
    except Exception as e:
        return None, f"❌ Query error: {e}"


def fmt_row(cols, row):
    """Format a single row as readable text."""
    lines = []
    for col, val in zip(cols, row):
        if val is not None and str(val) != '':
            lines.append(f"  *{col}:* `{str(val)[:60]}`")
    return '\n'.join(lines)


async def sqlview(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    db_path = find_sqlite()
    args    = context.args or []

    # No args — show help + db status
    if not args:
        status = f"✅ Found: `{db_path}`" if db_path else "❌ No SQLite file found"
        await update.message.reply_text(
            f"🗄️ *SQLITE VIEWER*\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f"📁 DB Status: {status}\n\n"
            f"*Commands:*\n"
            f"`/sqlview tables` — List all tables\n"
            f"`/sqlview players` — All players\n"
            f"`/sqlview players @user` — Find player\n"
            f"`/sqlview inventory [id]` — User inventory\n"
            f"`/sqlview clans` — All clans\n"
            f"`/sqlview [table]` — Browse any table\n"
            f"`/sqlview raw [SQL]` — Custom SELECT\n\n"
            f"_Read-only. SELECT queries only._",
            parse_mode='Markdown'
        )
        return

    cmd = args[0].lower()

    # ── /sqlview tables ─────────────────────────────────────────────────
    if cmd == 'tables':
        cols, rows = query_sqlite("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        if cols is None:
            await update.message.reply_text(rows)
            return
        names = [r[0] for r in rows]
        lines = ["🗄️ *SQLITE TABLES*\n"]
        for name in names:
            cnt_cols, cnt_rows = query_sqlite(f"SELECT COUNT(*) FROM {name}")
            count = cnt_rows[0][0] if cnt_rows else 0
            lines.append(f"  📋 `{name}` — {count} records")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    # ── /sqlview raw [SQL] ──────────────────────────────────────────────
    if cmd == 'raw':
        if len(args) < 2:
            await update.message.reply_text("Usage: `/sqlview raw SELECT * FROM players LIMIT 5`", parse_mode='Markdown')
            return
        sql = ' '.join(args[1:])
        # Safety: only allow SELECT
        if not sql.strip().upper().startswith('SELECT'):
            await update.message.reply_text("❌ Only SELECT queries allowed.")
            return
        cols, rows = query_sqlite(sql)
        if cols is None:
            await update.message.reply_text(rows)
            return
        if not rows:
            await update.message.reply_text("_No results._", parse_mode='Markdown')
            return
        lines = [f"🔍 *Query Results* ({len(rows)} rows)\n"]
        for row in rows[:5]:
            lines.append(fmt_row(cols, row))
            lines.append("─────────────────")
        if len(rows) > 5:
            lines.append(f"_...and {len(rows)-5} more rows_")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    # ── /sqlview players ────────────────────────────────────────────────
    if cmd == 'players':
        if len(args) >= 2:
            search = args[1].lstrip('@')
            try:
                uid = int(search)
                cols, rows = query_sqlite("SELECT * FROM players WHERE user_id=?", (uid,))
            except ValueError:
                cols, rows = query_sqlite("SELECT * FROM players WHERE LOWER(username)=LOWER(?)", (search,))
        else:
            cols, rows = query_sqlite("SELECT user_id, name, username, faction, rank, xp, yen, location FROM players ORDER BY xp DESC LIMIT 10")

        if cols is None:
            await update.message.reply_text(rows)
            return
        if not rows:
            await update.message.reply_text("_No players found._", parse_mode='Markdown')
            return

        lines = [f"👥 *PLAYERS* ({len(rows)} shown)\n"]
        for row in rows[:8]:
            lines.append(fmt_row(cols, row))
            lines.append("─────────────────")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    # ── /sqlview inventory [user_id] ────────────────────────────────────
    if cmd == 'inventory':
        if len(args) < 2:
            await update.message.reply_text("Usage: `/sqlview inventory [user_id]`", parse_mode='Markdown')
            return
        try:
            uid = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Provide a user_id number.")
            return
        cols, rows = query_sqlite("SELECT item_name, item_type, quantity FROM inventory WHERE user_id=?", (uid,))
        if cols is None:
            await update.message.reply_text(rows)
            return
        if not rows:
            await update.message.reply_text(f"_No inventory for user {uid}._", parse_mode='Markdown')
            return
        lines = [f"🎒 *INVENTORY — {uid}*\n"]
        for row in rows:
            lines.append(f"  ╰➤ *{row[0]}* × {row[2]}  _({row[1]})_")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    # ── /sqlview clans ──────────────────────────────────────────────────
    if cmd == 'clans':
        cols, rows = query_sqlite("SELECT id, name, leader_id, xp FROM clans ORDER BY xp DESC LIMIT 10")
        if cols is None:
            await update.message.reply_text(rows)
            return
        if not rows:
            await update.message.reply_text("_No clans._", parse_mode='Markdown')
            return
        lines = [f"🏯 *CLANS*\n"]
        for row in rows:
            lines.append(f"  🏯 *{row[1]}*  ID:`{row[0]}`  XP:{row[3]:,}")
        await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
        return

    # ── /sqlview [any table] [optional id] ─────────────────────────────
    table = cmd
    # Validate table name (alphanumeric + underscore only)
    import re
    if not re.match(r'^[a-z_]+$', table):
        await update.message.reply_text(f"❌ Invalid table name: `{table}`", parse_mode='Markdown')
        return

    if len(args) >= 2:
        try:
            rid = int(args[1])
            # Try user_id first, then id
            cols, rows = query_sqlite(f"SELECT * FROM {table} WHERE user_id=? OR id=? LIMIT 5", (rid, rid))
        except ValueError:
            await update.message.reply_text("❌ Provide a numeric ID.")
            return
    else:
        cols, rows = query_sqlite(f"SELECT * FROM {table} LIMIT 10")

    if cols is None:
        await update.message.reply_text(rows)
        return
    if not rows:
        await update.message.reply_text(f"_No records in `{table}`._", parse_mode='Markdown')
        return

    lines = [f"📋 *{table.upper()}* ({len(rows)} shown)\n"]
    for row in rows[:5]:
        lines.append(fmt_row(cols, row))
        lines.append("─────────────────")
    if len(rows) > 5:
        lines.append(f"_...and {len(rows)-5} more_")

    await update.message.reply_text('\n'.join(lines), parse_mode='Markdown')
