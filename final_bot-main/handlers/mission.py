from telegram.error import BadRequest, TimedOut
import random
from utils.guards import dm_only
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from utils.database import get_player, update_player, add_item, col
from utils.helpers import get_level
from config import SLAYER_MISSIONS, DEMON_MISSIONS

async def _safe_edit(query, text, **kwargs):
    """Edit a message safely, falling back to reply on failure."""
    try:
        await query.edit_message_text(text, **kwargs)
    except Exception as e:
        err = str(e)
        if "Message is not modified" in err:
            return
        try:
            await query.message.reply_text(text, **kwargs)
        except Exception:
            pass


def _custom_missions():
    missions = []
    docs = list(col("custom_missions").find({"active": 1}, {"_id": 0}).sort("id", 1))
    for index, doc in enumerate(docs, start=1):
        mission_id = doc.get("id")
        if mission_id is None:
            mission_id = 1000 + index
        missions.append({
            "id": int(mission_id),
            "difficulty": doc.get("difficulty", "CUSTOM"),
            "name": doc.get("name", "Custom Mission"),
            "emoji": doc.get("emoji", "📜"),
            "xp": int(doc.get("xp", 0) or 0),
            "yen": int(doc.get("yen", 0) or 0),
            "desc": doc.get("desc") or doc.get("description") or doc.get("name", "Custom mission"),
            "kills_required": int(doc.get("kills_required", 5) or 5),
            "party_required": bool(doc.get("party_required", False)),
        })
    return missions


def get_missions(faction):
    base = SLAYER_MISSIONS if faction == 'slayer' else DEMON_MISSIONS
    return list(base) + _custom_missions()


@dm_only
async def mission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await (update.message or update.callback_query.message).reply_text("❌ No character found.")
        return

    # Check active mission
    if player.get('active_mission'):
        try:
            import json
            am = json.loads(player['active_mission']) if isinstance(player['active_mission'], str) else player['active_mission']
        except Exception:
            am = None

        if am:
            progress = am.get('progress', 0)
            required = am.get('required', 5)
            pct      = int(progress / required * 100)
            bar      = '█' * int(pct/10) + '░' * (10 - int(pct/10))

            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("⚔️ Go Fight!", callback_data='goto_explore'),
                InlineKeyboardButton("❌ Abandon",   callback_data='mission_abandon'),
            ]])
            msg = update.message or update.callback_query.message
            await msg.reply_text(
                f"📜 *ACTIVE MISSION*\n\n"
                f"{am.get('emoji','⚔️')} *{am.get('name','Mission')}*\n"
                f"{am.get('difficulty','')}\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n"
                f"Progress: {progress}/{required} kills\n"
                f"`[{bar}]` {pct}%\n\n"
                f"⭐ Reward: *{am.get('xp',0):,} XP*  💰 *{am.get('yen',0):,}¥*\n\n"
                f"_Keep fighting to complete your mission!_",
                parse_mode='Markdown',
                reply_markup=keyboard
            )
            return

    missions = get_missions(player['faction'])
    fe       = '🗡️' if player['faction'] == 'slayer' else '👹'
    faction_label = 'SLAYER' if player['faction'] == 'slayer' else 'DEMON'

    lines = [
        f"╔══════════════════════╗",
        f"      📜 𝙈𝙄𝙎𝙎𝙄𝙊𝙉 𝘽𝙊𝘼𝙍𝘿",
        f"   {fe} {faction_label} CORPS",
        f"╚══════════════════════╝\n",
    ]

    buttons = []
    for m in missions:
        party_tag = " 👥" if m.get('party_required') else ""
        lines.append(f"{m['emoji']} *{m['name']}*{party_tag}")
        lines.append(f"   {m['difficulty']}  •  ⭐ {m['xp']:,} XP  •  💰 {m['yen']:,}¥")
        lines.append(f"   _{m['desc']}_\n")
        buttons.append([InlineKeyboardButton(
            f"{m['emoji']} {m['name']}",
            callback_data=f"mission_select_{m['id']}"
        )])

    msg = update.message or update.callback_query.message
    if update.callback_query:
        await update.callback_query.edit_message_text(
            '\n'.join(lines), parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    else:
        await msg.reply_text(
            '\n'.join(lines), parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons)
        )


async def select_mission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query      = update.callback_query
    await query.answer()
    user_id    = query.from_user.id
    player     = get_player(user_id)
    if not player:
        await query.answer("❌ No character found!", show_alert=True)
        return
    mission_id = int(query.data.split('_')[-1])
    missions   = get_missions(player['faction'])
    m = next((x for x in missions if x['id'] == mission_id), None)
    if not m:
        await query.answer("❌ Mission not found!", show_alert=True)
        return

    context.user_data['selected_mission'] = mission_id
    party_note = "\n\n👥 *Requires a full party of 3!*" if m.get('party_required') else ""

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Accept", callback_data='mission_confirm'),
        InlineKeyboardButton("🔙 Back",   callback_data='mission_back'),
    ]])

    await _safe_edit(query, 
        f"📜 *MISSION DETAILS*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{m['emoji']} *{m['name']}*\n\n"
        f"🎯 Difficulty:  {m['difficulty']}\n"
        f"⭐ XP Reward:   *{m['xp']:,}*\n"
        f"💰 Yen Reward:  *{m['yen']:,}¥*\n"
        f"⚔️ Kills needed: *{m.get('kills_required', 5)}*\n\n"
        f"_{m['desc']}_{party_note}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━",
        parse_mode='Markdown',
        reply_markup=keyboard
    )


async def confirm_mission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    player  = get_player(user_id)

    mission_id = context.user_data.get('selected_mission')
    if not mission_id:
        await _safe_edit(query, "❌ No mission selected.")
        return

    missions = get_missions(player['faction'])
    m = next((x for x in missions if x['id'] == mission_id), None)
    if not m:
        await _safe_edit(query, "❌ Mission not found.")
        return

    import json
    mission_data = {
        "id":       m['id'],
        "name":     m['name'],
        "emoji":    m['emoji'],
        "xp":       m['xp'],
        "yen":      m['yen'],
        "difficulty": m['difficulty'],
        "required": m.get('kills_required', 5),
        "progress": 0,
        "desc":     m['desc'],
    }
    update_player(user_id, active_mission=json.dumps(mission_data))

    await _safe_edit(query, 
        f"✅ *MISSION ACCEPTED!*\n\n"
        f"{m['emoji']} *{m['name']}*\n\n"
        f"⚔️ Kill *{m.get('kills_required',5)} enemies* to complete it!\n\n"
        f"💡 Use `/explore` to fight and track progress.",
        parse_mode='Markdown'
    )


async def abandon_mission(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    update_player(user_id, active_mission=None)
    await _safe_edit(query, "❌ Mission abandoned.\nUse /mission to pick a new one.")


async def mission_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await mission(update, context)
