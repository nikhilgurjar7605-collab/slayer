import random
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest, TimedOut
from utils.database import (get_player, update_player, col, get_inventory,
                             remove_item, apply_status_effect,
                             get_status_effects, tick_status_effects, clear_status_effects)
from utils.helpers import get_level, hp_bar
from utils.guards import group_only, no_button_spam
from utils.pressure import calc_pressure, pressure_display
from config import TECHNIQUES, STATUS_EFFECTS_DATA, TECHNIQUE_STATUS_EFFECTS

# ═══════════════════════════════════════════════════════════════════════════
# ► LOGGING CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# ► BATTLE LOG SYSTEM - Expandable/Collapsible Format (Last 3 Moves)
# ═══════════════════════════════════════════════════════════════════════════

class DuelBattleLog:
    """Battle log with expandable/collapsible formatting."""
    
    def __init__(self, duel_id: str, challenger_id: int, target_id: int):
        self.duel_id = duel_id
        self.challenger_id = challenger_id
        self.target_id = target_id
        self.moves = []
        self.move_count = 0
        
    def add_move(self, actor_id: int, action_type: str, details: dict):
        """Add move to log (keeps last 3)."""
        try:
            actor = details.get("actor_name", "Unknown")
            action_info = self._get_action_info(action_type, details)
            
            move = {
                "move_number": self.move_count + 1,
                "timestamp": datetime.now(),
                "actor_id": actor_id,
                "actor_name": actor,
                "target_name": details.get("target_name", "Unknown"),
                "action_type": action_type,
                "action_emoji": self._get_emoji(action_type),
                "action_info": action_info,
                "details": details,
            }
            
            if len(self.moves) >= 3:
                self.moves.pop(0)
            
            self.moves.append(move)
            self.move_count += 1
            
            logger.info(f"📋 [{actor}] {action_type} vs {details.get('target_name')}")
            return True
        except Exception as e:
            logger.error(f"❌ Error adding move: {e}")
            return False
    
    @staticmethod
    def _get_emoji(action_type: str) -> str:
        """Get emoji for action type."""
        emojis = {
            'attack': '⚔️',
            'technique': '💨',
            'item': '🧪',
            'surrender': '🏳️',
            'draw': '🤝',
            'heal': '❤️',
        }
        return emojis.get(action_type, '⚡')
    
    @staticmethod
    def _get_action_info(action_type: str, details: dict) -> dict:
        """Extract action information."""
        try:
            if action_type == 'attack':
                dmg = details.get('damage', 0)
                return {
                    "type": "Basic Attack",
                    "damage": dmg,
                    "critical": details.get('critical', False),
                    "dodged": details.get('dodge', False),
                    "effects": []
                }
            
            elif action_type == 'technique':
                return {
                    "type": details.get('technique_name', 'Unknown'),
                    "form": details.get('form_number', '?'),
                    "damage": details.get('damage', 0),
                    "effects": [details.get('effects')] if details.get('effects') else [],
                }
            
            elif action_type == 'item':
                return {
                    "type": details.get('item_name', 'Item'),
                    "effect": details.get('effect', 'Used'),
                    "damage": 0,
                }
            
            elif action_type == 'heal':
                return {
                    "type": "Healing",
                    "damage": 0,
                    "heal_amount": details.get('heal_amount', 0),
                }
            
            elif action_type == 'surrender':
                return {
                    "type": "Surrender",
                    "damage": 0,
                }
            
            elif action_type == 'draw':
                return {
                    "type": "Draw Proposal",
                    "damage": 0,
                }
            
            else:
                return {"type": "Action", "damage": 0}
        except Exception as e:
            logger.error(f"❌ Error getting action info: {e}")
            return {"type": "Unknown", "damage": 0}
    
    def format_battle_log_compact(self) -> str:
        """Format as compact (collapsed) version - just one line per move."""
        try:
            if not self.moves:
                return "📋 *BATTLE LOG* (Last 3 Moves)\n━━━━━━━━━━━━━━━━━━━━━━━━\n_No moves yet_"
            
            lines = ["📋 *BATTLE LOG* (Last 3 Moves)"]
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
            
            for i, move in enumerate(self.moves, 1):
                emoji = move['action_emoji']
                actor = move['actor_name']
                target = move['target_name']
                action = move['action_info']
                
                if action.get('critical'):
                    info = f"*{action['damage']}* ⚡ CRITICAL"
                elif action.get('dodged'):
                    info = "DODGED 💨"
                elif action.get('damage'):
                    info = f"*{action['damage']}* dmg"
                elif action.get('heal_amount'):
                    info = f"*{action['heal_amount']}* ❤️ HP"
                else:
                    info = action['type']
                
                lines.append(f"Move {i} {emoji} | {actor} → {target} | {info}")
            
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("_Tap to expand ⬇️_")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"❌ Error formatting compact log: {e}")
            return "📋 *BATTLE LOG* _Error_"
    
    def format_battle_log_expanded(self) -> str:
        """Format as expanded (full details) version."""
        try:
            if not self.moves:
                return "📋 *BATTLE LOG* (Last 3 Moves)\n━━━━━━━━━━━━━━━━━━━━━━━━\n_No moves yet_"
            
            lines = ["📋 *BATTLE LOG* (Last 3 Moves)"]
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━")
            
            for i, move in enumerate(self.moves, 1):
                timestamp = move['timestamp'].strftime("%H:%M:%S")
                emoji = move['action_emoji']
                actor = move['actor_name']
                target = move['target_name']
                action = move['action_info']
                
                lines.append(f"\n*Move {i}* [{timestamp}] {emoji}")
                lines.append(f"👤 *{actor}* → *{target}*")
                
                if action['type'] == 'Basic Attack':
                    dmg = action.get('damage', 0)
                    if action.get('critical'):
                        lines.append(f"⚔️ Basic Attack")
                        lines.append(f"💥 Damage: *{dmg}* ⚡ *CRITICAL*")
                    elif action.get('dodged'):
                        lines.append(f"⚔️ Basic Attack")
                        lines.append(f"💨 *DODGED*")
                    else:
                        lines.append(f"⚔️ Basic Attack")
                        lines.append(f"💥 Damage: *{dmg}*")
                
                elif action['type'] != 'Basic Attack' and action.get('form'):
                    tech_name = action['type']
                    form = action['form']
                    dmg = action.get('damage', 0)
                    lines.append(f"💨 *{tech_name}* Form {form}")
                    lines.append(f"💥 Damage: *{dmg}*")
                    if action.get('effects'):
                        for effect in action['effects']:
                            if effect:
                                lines.append(f"✨ Effects: {effect}")
                
                elif action['type'] != 'Basic Attack' and not action.get('form'):
                    item_name = action['type']
                    effect = action.get('effect', 'Used')
                    lines.append(f"🧪 *{item_name}*")
                    lines.append(f"✨ {effect}")
                
                elif 'Healing' in action['type']:
                    heal = action.get('heal_amount', 0)
                    lines.append(f"❤️ Healing")
                    lines.append(f"💚 Recovered: *{heal}* HP")
                
                elif action['type'] == 'Surrender':
                    lines.append(f"🏳️ *SURRENDERED*")
                
                elif action['type'] == 'Draw Proposal':
                    lines.append(f"🤝 *Proposed DRAW*")
            
            lines.append("\n━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("_Tap to collapse ⬆️_")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"❌ Error formatting expanded log: {e}")
            return "📋 *BATTLE LOG* _Error_"

# ═══════════════════════════════════════════════════════════════════════════
# ► PRESS FORMAT LOG HELPER
# ═══════════════════════════════════════════════════════════════════════════

def _fmt_press(lines: list) -> str:
    """Collapse a raw log list into ONE compact press-format summary line."""
    if not lines:
        return "⚔️ Action executed"
    
    try:
        priority_keywords = [
            ("💀", "☠️ Defeat"),
            ("CRITICAL", "⚡ CRITICAL"),
            ("PHOENIX", "🔥 Rebirth"),
            ("RESISTS", "🌙 Resisted"),
            ("BURN", "🔥 Burn"),
            ("FREEZE", "❄️ Freeze"),
            ("POISON", "☠️ Poison"),
        ]
        
        import re as _re
        dmg_nums = _re.findall(r'\b(\d+) damage', " ".join(lines))
        total_dmg = sum(int(x) for x in dmg_nums) if dmg_nums else 0
        
        tags = []
        combined = " ".join(lines)
        for kw, label in priority_keywords:
            if kw.lower() in combined.lower():
                tags.append(label)
                break
        
        dmg_part = f"*{total_dmg:,} dmg*" if total_dmg else ""
        tag_part = tags[0] if tags else ""
        parts = [p for p in [dmg_part, tag_part] if p]
        
        return " — ".join(parts) if parts else "⚔️ Action"
    except Exception as e:
        logger.error(f"❌ Error in _fmt_press: {e}")
        return "⚔️ Action"

# ═══════════════════════════════════════════════════════════════════════════
# ► SAFE EDIT HELPER
# ═══════════════════════════════════════════════════════════════════════════

async def _safe_edit(query, text, **kwargs):
    """Safely edit message with error handling."""
    try:
        await query.edit_message_text(text, **kwargs)
        logger.debug(f"✅ Message edited for user {query.from_user.id}")
    except BadRequest as e:
        err = str(e)
        if "Message is not modified" in err:
            logger.debug("ℹ️ Message not modified")
            return
        elif any(x in err.lower() for x in ("can't be edited", "message to edit not found", "not found")):
            try:
                await query.message.reply_text(text, **kwargs)
                logger.info(f"📤 New message sent instead of edit")
            except Exception as reply_err:
                logger.error(f"❌ Failed to reply: {reply_err}")
        else:
            logger.error(f"❌ BadRequest: {err}")
            raise
    except TimedOut:
        logger.warning(f"⏱️ Request timed out")
    except Exception as ex:
        logger.error(f"❌ Unexpected error: {ex}")

# ═══════════════════════════════════════════════════════════════════════════
# ► HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def duel_hp_bar(hp, max_hp):
    """Generate HP bar visualization."""
    return hp_bar(hp, max_hp)

def build_duel_keyboard(user_id, challenger_id=None):
    """Build the duel action keyboard."""
    ch_id = challenger_id if challenger_id is not None else user_id
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⚔️ Attack", callback_data=f"duel_attack_{user_id}"),
            InlineKeyboardButton("💨 Technique", callback_data=f"duel_technique_{user_id}"),
        ],
        [
            InlineKeyboardButton("🧪 Items", callback_data=f"duel_items_{user_id}"),
            InlineKeyboardButton("🏳️ Surrender", callback_data="duel_surrender_me"),
        ],
        [
            InlineKeyboardButton("🤝 Draw", callback_data=f"duel_draw_{user_id}"),
            InlineKeyboardButton("📋 Logs", callback_data=f"duel_logs_{user_id}"),
        ],
    ])

def duel_status_text(p1, p1_hp, p1_max, p2, p2_hp, p2_max, turn_name, pressure=None, combo=0, last_press=None):
    """Generate formatted duel status display."""
    try:
        bar1 = duel_hp_bar(p1_hp, p1_max)
        bar2 = duel_hp_bar(p2_hp, p2_max)
        fe1 = '🗡️' if p1.get('faction') == 'slayer' else '👹'
        fe2 = '🗡️' if p2.get('faction') == 'slayer' else '👹'
        combo_line = f"\n🔥 *Combo ×{combo}!*" if combo >= 3 else ""
        pressure_line = f"\n{pressure_display(pressure)}" if pressure else ""
        log_line = f"\n⚡ *Last:* {last_press}" if last_press else ""
        
        return (
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"⚔️ *PvP DUEL*{pressure_line}{combo_line}{log_line}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{fe1} *{p1.get('name', 'Player 1')}*\n"
            f"❤️ {p1_hp}/{p1_max} {bar1}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{fe2} *{p2.get('name', 'Player 2')}*\n"
            f"❤️ {p2_hp}/{p2_max} {bar2}\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🎯 *{turn_name}'s turn*"
        )
    except Exception as e:
        logger.error(f"❌ Error in duel_status_text: {e}")
        return "⚔️ *DUEL IN PROGRESS*"

def get_active_duel(user_id):
    """Get active duel for user."""
    try:
        doc = col("duels").find_one({
            "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
            "status": "active"
        })
        if doc:
            doc.pop("_id", None)
        return doc
    except Exception as e:
        logger.error(f"❌ Error fetching duel: {e}")
        return None

def get_opponent_id(duel, user_id):
    """Get opponent ID from duel."""
    try:
        return duel.get('target_id') if duel.get('challenger_id') == user_id else duel.get('challenger_id')
    except Exception as e:
        logger.error(f"❌ Error getting opponent: {e}")
        return None

def _duel_hp_key(duel, user_id):
    """Get HP key tuple."""
    if duel.get('challenger_id') == user_id:
        return 'challenger_hp', 'target_hp', 'challenger_max_hp', 'target_max_hp'
    return 'target_hp', 'challenger_hp', 'target_max_hp', 'challenger_max_hp'

def _challenge_keyboard(challenger_id):
    """Challenge acceptance keyboard."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Accept", callback_data=f"duel_accept_{challenger_id}"),
            InlineKeyboardButton("❌ Decline", callback_data=f"duel_decline_{challenger_id}"),
        ],
        [InlineKeyboardButton("⚙️ Settings", callback_data=f"duel_settings_{challenger_id}")]
    ])

def _challenge_text(player, settings=None):
    """Format challenge text."""
    if not player:
        return "⚔️ *DUEL CHALLENGE!*\n❌ Player data unavailable."
    
    fe = "🗡️" if player.get("faction") == "slayer" else "👹"
    level = get_level(player.get("xp", 0))
    tags = []
    if settings:
        if settings.get("no_items"): tags.append("🚫 No Items")
        if settings.get("techniques_only"): tags.append("🌀 Techniques Only")
        hpm = settings.get("hp_multiplier", 1.0)
        if hpm != 1.0: tags.append(f"❤️ HP ×{hpm}")
    
    rules = f"\n⚙️ *Rules:* {' | '.join(tags)}" if tags else ""
    return (
        f"⚔️ *DUEL CHALLENGE!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{fe} *{player.get('name', 'Unknown')}* (Lv.{level})\n"
        f"🏅 Rank: {player.get('rank', 'N/A')} {player.get('rank_kanji', '')}"
        f"{rules}\n\n"
        f"Do you accept?"
    )

# ═══════════════════════════════════════════════════════════════════════════
# ► /CHALLENGE COMMAND
# ═══════════════════════════════════════════════════════════════════════════

@group_only
async def challenge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiate a duel challenge."""
    user_id = update.effective_user.id
    player = get_player(user_id)
    
    if not player:
        logger.warning(f"⚠️ No character for user {user_id}")
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    if get_active_duel(user_id):
        logger.info(f"ℹ️ User {user_id} already in duel")
        await update.message.reply_text(
            "⚔️ *You are already in a duel!*\n\nFinish it first or use /unstuck.",
            parse_mode='Markdown'
        )
        return

    target = None
    if update.message.reply_to_message:
        replied_user = update.message.reply_to_message.from_user
        if replied_user.is_bot:
            await update.message.reply_text("❌ You can't challenge a bot!")
            return
        target = col("players").find_one({"user_id": replied_user.id})
        if not target:
            await update.message.reply_text(
                f"❌ *{replied_user.first_name}* hasn't created a character yet!",
                parse_mode='Markdown'
            )
            return
    elif context.args:
        username = context.args[0].lstrip('@')
        target = col("players").find_one({"username": {"$regex": f"^{username}$", "$options": "i"}})
        if not target:
            await update.message.reply_text(f"❌ Player *@{username}* not found.", parse_mode='Markdown')
            return
    else:
        await update.message.reply_text(
            "⚔️ *HOW TO DUEL*\n\n"
            "📌 Reply to someone's message → `/challenge`\n"
            "📌 Or: `/challenge @username`\n\n"
            "_Duel plays out right here in the group!_",
            parse_mode='Markdown'
        )
        return

    if target.get('user_id') == user_id:
        await update.message.reply_text("❌ You can't challenge yourself!")
        return
    
    if get_active_duel(target.get('user_id')):
        await update.message.reply_text(f"❌ *{target.get('name')}* is already in a duel!", parse_mode='Markdown')
        return

    col("duels").update_many(
        {"challenger_id": user_id, "status": "pending"},
        {"$set": {"status": "expired"}}
    )

    from datetime import datetime as _dt
    col("duels").insert_one({
        "challenger_id": user_id,
        "target_id": target.get('user_id'),
        "status": "pending",
        "created_at": _dt.now()
    })

    fe = '🗡️' if player.get('faction') == 'slayer' else '👹'
    fe2 = '🗡️' if target.get('faction') == 'slayer' else '👹'
    lv = get_level(player.get('xp', 0))

    logger.info(f"✅ Challenge: {player.get('name')} → {target.get('name')}")
    
    await update.message.reply_text(
        f"⚔️ *DUEL CHALLENGE!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{fe} *{player.get('name')}* (Lv.{lv}) challenges {fe2} *{target.get('name')}*!\n"
        f"🏅 Rank: {player.get('rank')} {player.get('rank_kanji')}\n\n"
        f"*{target.get('name')}*, do you accept?",
        parse_mode='Markdown',
        reply_markup=_challenge_keyboard(user_id)
    )

# ═══════════════════════════════════════════════════════════════════════════
# ► DUEL ACCEPT CALLBACK
# ═══════════════════════════════════════════════════════════════���═══════════

@no_button_spam
async def duel_accept_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Accept a duel challenge."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    try:
        challenger_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"❌ Invalid challenge ID")
        await query.answer("❌ Invalid challenge.", show_alert=True)
        return

    if user_id == challenger_id:
        await query.answer("❌ You can't accept your own challenge!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "challenger_id": challenger_id,
        "target_id": user_id,
        "status": "pending"
    })
    
    if not duel_doc:
        await _safe_edit(query, "❌ This challenge has expired or was already handled.")
        return

    challenger = get_player(challenger_id)
    target = get_player(user_id)
    
    if not challenger or not target:
        logger.error(f"❌ Player data missing")
        await _safe_edit(query, "❌ Player data not found.")
        return

    try:
        settings = context.user_data.get(f"duel_settings_{challenger_id}", {})
        hp_mult = settings.get("hp_multiplier", 1.0)
        ch_faction_mult = 1.15 if challenger.get('faction') == 'slayer' else 1.0
        tg_faction_mult = 1.15 if target.get('faction') == 'slayer' else 1.0
        
        ch_hp = int(challenger.get('hp', 100) * hp_mult * ch_faction_mult)
        ch_max_hp = int(challenger.get('max_hp', 100) * hp_mult * ch_faction_mult)
        tg_hp = int(target.get('hp', 100) * hp_mult * tg_faction_mult)
        tg_max_hp = int(target.get('max_hp', 100) * hp_mult * tg_faction_mult)

        first = challenger_id if challenger.get('spd', 0) >= target.get('spd', 0) else user_id
        first_player = challenger if first == challenger_id else target

        col("duels").update_one({"_id": duel_doc["_id"]}, {"$set": {
            "status": "active",
            "turn_user_id": first,
            "challenger_hp": ch_hp,
            "challenger_max_hp": ch_max_hp,
            "target_hp": tg_hp,
            "target_max_hp": tg_max_hp,
            "settings": settings,
        }})

        duel_key = str(duel_doc["_id"])
        pressure = calc_pressure(challenger)
        context.bot_data[f"duel_pressure_{duel_key}"] = pressure
        context.bot_data[f"duel_combo_{duel_key}"] = 0
        context.bot_data[f"duel_last_press_{duel_key}"] = "⚔️ Duel started!"
        
        # Initialize battle log
        context.bot_data[f"duel_battle_log_{duel_key}"] = DuelBattleLog(duel_key, challenger_id, user_id)
        context.bot_data[f"duel_log_expanded_{duel_key}"] = False  # Collapsed by default
        logger.info(f"📋 Battle log initialized for duel {duel_key}")

        status = duel_status_text(
            challenger, ch_hp, ch_max_hp,
            target, tg_hp, tg_max_hp,
            first_player.get('name', 'Unknown'),
            pressure,
            last_press=context.bot_data[f"duel_last_press_{duel_key}"]
        )

        logger.info(f"✅ Duel accepted: {challenger.get('name')} vs {target.get('name')}")
        
        await _safe_edit(
            query,
            f"✅ *DUEL ACCEPTED!*\n\n"
            f"⚡ _{first_player.get('name', 'Unknown')} moves first (SPD: {first_player.get('spd', 0)})_\n\n"
            f"{status}",
            parse_mode='Markdown',
            reply_markup=build_duel_keyboard(first, challenger_id=challenger_id)
        )
    except Exception as e:
        logger.error(f"❌ Error accepting duel: {e}")
        await _safe_edit(query, f"❌ Error starting duel")

# ═══════════════════════════════════════════════════════════════════════════
# ► DUEL DECLINE CALLBACK
# ═══════════════════════════════════════════════════════════════════════════

async def duel_decline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Decline a duel challenge."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    try:
        challenger_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"❌ Invalid challenge ID")
        await query.answer("❌ Invalid.", show_alert=True)
        return
    
    try:
        col("duels").update_one(
            {"challenger_id": challenger_id, "target_id": user_id, "status": "pending"},
            {"$set": {"status": "declined"}}
        )
        decliner = get_player(user_id)
        logger.info(f"ℹ️ Duel declined by {user_id}")
        await _safe_edit(
            query,
            f"❌ *{decliner.get('name') if decliner else 'Player'}* declined the duel.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ Error declining duel: {e}")
        await _safe_edit(query, "❌ Error processing decline")

# ═══════════════════════════════════════════════════════════════════════════
# ► DUEL BACK
# ═══════════════════════════════════════════════════════════════════════════

async def duel_back(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Back button handler."""
    query = update.callback_query
    await query.answer("⏳ Wait for your turn!", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════════
# ► DUEL VIEW
# ═══════════════════════════════════════════════════════════════════════════

async def duel_view(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current duel status."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    
    if not duel_doc:
        await _safe_edit(query, "⚔️ No active duel found.", parse_mode='Markdown')
        return

    try:
        duel = dict(duel_doc)
        duel_oid = duel_doc["_id"]
        duel.pop("_id", None)
        duel_key = str(duel_oid)
        
        opp_id = get_opponent_id(duel, user_id)
        c_player = get_player(duel.get('challenger_id'))
        t_player = get_player(duel.get('target_id'))
        turn_player = get_player(duel.get('turn_user_id'))
        
        pressure = context.bot_data.get(f"duel_pressure_{duel_key}") or calc_pressure(c_player)
        combo = context.bot_data.get(f"duel_combo_{duel_key}", 0)
        last_press = context.bot_data.get(f"duel_last_press_{duel_key}", "")

        status = duel_status_text(
            c_player, duel.get('challenger_hp', 0), duel.get('challenger_max_hp', 0),
            t_player, duel.get('target_hp', 0), duel.get('target_max_hp', 0),
            turn_player.get('name', '?') if turn_player else "?",
            pressure, combo, last_press
        )
        
        turn_id = duel.get('turn_user_id')
        await _safe_edit(query, status, parse_mode='Markdown',
                        reply_markup=build_duel_keyboard(turn_id))
        logger.debug(f"✅ Duel view shown for {user_id}")
    except Exception as e:
        logger.error(f"❌ Error displaying duel view: {e}")
        await _safe_edit(query, f"❌ Error displaying duel")

# ═══════════════════════════════════════════════════════════════════════════
# ► DUEL LOGS - Toggle Expanded/Compact
# ═══════════════════════════════════════════════════════════════════════════

async def duel_logs_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle between expanded and compact battle log view."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    
    if not duel_doc:
        await query.answer("❌ No active duel found!", show_alert=True)
        return

    try:
        duel_key = str(duel_doc["_id"])
        battle_log = context.bot_data.get(f"duel_battle_log_{duel_key}")
        
        if not battle_log:
            await query.answer("❌ No battle log found!", show_alert=True)
            return
        
        # Toggle expanded state
        is_expanded = context.bot_data.get(f"duel_log_expanded_{duel_key}", False)
        context.bot_data[f"duel_log_expanded_{duel_key}"] = not is_expanded
        
        if not is_expanded:
            # Show expanded
            log_text = battle_log.format_battle_log_expanded()
        else:
            # Show compact
            log_text = battle_log.format_battle_log_compact()
        
        # Add back button
        back_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🔙 Back to Duel", callback_data=f"duel_view_{user_id}")
        ]])
        
        await _safe_edit(query, log_text, parse_mode='Markdown', reply_markup=back_kb)
        logger.info(f"📋 Battle log toggled: {'expanded' if not is_expanded else 'compact'}")
        
    except Exception as e:
        logger.error(f"❌ Error showing logs: {e}")
        await query.answer(f"❌ Error: {str(e)[:50]}", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════════
# ► FINISH DUEL
# ═══════════════════════════════════════════════════════════════════════════

async def _finish_duel(query, duel_doc, winner_id, loser_id, context, reason="KO"):
    """Finish duel and award prizes."""
    try:
        col("duels").update_one({"_id": duel_doc["_id"]}, {"$set": {"status": "finished"}})

        winner = get_player(winner_id)
        loser = get_player(loser_id)
        
        if not winner or not loser:
            logger.error(f"❌ Player data missing")
            await _safe_edit(query, "⚔️ *Duel ended.*", parse_mode='Markdown')
            return

        xp_win = 300
        yen_win = 150
        xp_loss = 100

        from datetime import datetime as _dt
        today_key = f"pvp_sp_{winner_id}_{loser_id}_{_dt.utcnow().strftime('%Y%m%d')}"
        sp_today = context.bot_data.get(today_key, 0)
        SP_PER_PERSON_LIMIT = 7
        sp_win = 0
        
        if sp_today < SP_PER_PERSON_LIMIT:
            sp_win = min(1, SP_PER_PERSON_LIMIT - sp_today)
            context.bot_data[today_key] = sp_today + sp_win

        update_player(winner_id, xp=winner['xp'] + xp_win, yen=winner['yen'] + yen_win,
                      skill_points=winner.get('skill_points', 0) + sp_win)
        update_player(loser_id, xp=max(0, loser['xp'] - xp_loss), deaths=loser['deaths'] + 1)

        wf = get_player(winner_id)
        lf = get_player(loser_id)
        update_player(winner_id, hp=wf['max_hp'], sta=wf['max_sta'])
        update_player(loser_id, hp=int(lf['max_hp'] * 0.5), sta=lf['max_sta'])

        fe_w = '🗡️' if winner['faction'] == 'slayer' else '👹'
        fe_l = '🗡️' if loser['faction'] == 'slayer' else '👹'
        
        duel_key = str(duel_doc["_id"])
        battle_log = context.bot_data.get(f"duel_battle_log_{duel_key}")
        battle_log_text = battle_log.format_battle_log_compact() if battle_log else ""

        sp_text = f"  +{sp_win} SP" if sp_win else "  _(SP limit)_"
        
        logger.info(f"✅ Duel finished: {winner.get('name')} wins ({reason})")
        
        await _safe_edit(
            query,
            f"🏆 *DUEL OVER!*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"{fe_w} *{winner.get('name')}* wins! _({reason})_\n\n"
            f"✅ *{winner.get('name')}:* +{xp_win} XP  +{yen_win}¥{sp_text}\n"
            f"{fe_l} 💔 *{loser.get('name')}:* -{xp_loss} XP\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{battle_log_text}\n\n"
            f"_Rematch? Use /challenge_",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"❌ Error finishing duel: {e}")
        await _safe_edit(query, f"⚔️ *Duel ended.*")

# ═══════════════════════════════════════════════════════════════════════════
# ► ATTACK ACTION
# ═══════════════════════════════════════════════════════════════════════════

@no_button_spam
async def duel_attack(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Perform attack action."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    try:
        attacker_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        logger.error(f"❌ Invalid attack ID")
        await query.answer("❌ Invalid action.", show_alert=True)
        return

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    
    if not duel_doc or duel_doc['turn_user_id'] != user_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    try:
        duel = dict(duel_doc)
        duel_oid = duel_doc["_id"]
        duel.pop("_id", None)
        duel_key = str(duel_oid)
        
        attacker = get_player(user_id)
        opp_id = get_opponent_id(duel, user_id)
        defender = get_player(opp_id)

        if not attacker or not defender:
            logger.error(f"❌ Player data missing")
            await query.answer("❌ Error: Player data missing", show_alert=True)
            return

        my_hp_key, opp_hp_key, my_max_key, opp_max_key = _duel_hp_key(duel, user_id)
        my_hp = duel[my_hp_key]
        opp_hp = duel[opp_hp_key]

        pressure = context.bot_data.get(f"duel_pressure_{duel_key}") or calc_pressure(attacker)
        combo = context.bot_data.get(f"duel_combo_{duel_key}", 0)

        if duel.get("settings", {}).get("techniques_only"):
            await query.answer("🌀 Techniques Only mode! Use 💨 Technique.", show_alert=True)
            return

        try:
            from handlers.explore import _safe_get_skills, _safe_get_bonuses
            owned_skills = _safe_get_skills(user_id)
            bonuses = _safe_get_bonuses(user_id, context)
        except:
            bonuses = {}

        dmg = int(attacker.get('str_stat', 10) * 1.2) + random.randint(2, 6)
        dmg = int(dmg * pressure.get('atk_mult', 1.0))
        if combo >= 3: dmg = int(dmg * 1.15)
        if bonuses.get('atk_pct'):
            dmg = int(dmg * (1 + bonuses['atk_pct']))
        if bonuses.get('story_bonus') == 'dmg_bonus':
            dmg = int(dmg * 1.10)
        if attacker.get('slayer_mark'): dmg = int(dmg * 1.15)
        if attacker.get('demon_mark'): dmg = int(dmg * 1.12)

        crit_chance = 0.12 + bonuses.get('crit_bonus', 0)
        dodge_chance = 0.08 + bonuses.get('dodge_bonus', 0)
        crit = random.random() < crit_chance
        dodge = random.random() < dodge_chance
        if crit: dmg = int(dmg * 1.5)

        log_lines = []
        if dodge:
            log_lines.append(f"💨 *{defender['name']}* dodges!")
            combo = 0
            new_opp_hp = opp_hp
        else:
            new_opp_hp = max(0, opp_hp - dmg)
            log_lines.append(f"⚔️ *{attacker['name']}* attacks!")
            log_lines.append(f"💥 *CRITICAL!* {dmg} damage!" if crit else f"💥 {dmg} damage!")
            combo += 1

        # Log to battle log
        battle_log = context.bot_data.get(f"duel_battle_log_{duel_key}")
        if battle_log:
            battle_log.add_move(user_id, 'attack', {
                'actor_name': attacker.get('name', 'Unknown'),
                'target_name': defender.get('name', 'Unknown'),
                'damage': dmg,
                'critical': crit,
                'dodge': dodge,
            })

        if new_opp_hp <= 0:
            context.bot_data[f"duel_combo_{duel_key}"] = 0
            col("duels").update_one({"_id": duel_oid}, {"$set": {opp_hp_key: 0}})
            logger.info(f"✅ {attacker.get('name')} KO'd {defender.get('name')}")
            await _finish_duel(query, duel_doc, user_id, opp_id, context, "KO")
            return

        context.bot_data[f"duel_combo_{duel_key}"] = combo
        press_line = _fmt_press(log_lines)
        context.bot_data[f"duel_last_press_{duel_key}"] = press_line
        col("duels").update_one({"_id": duel_oid}, {"$set": {opp_hp_key: new_opp_hp, "turn_user_id": opp_id}})

        c_hp = my_hp if duel['challenger_id'] == user_id else new_opp_hp
        t_hp = new_opp_hp if duel['challenger_id'] == user_id else my_hp

        status = duel_status_text(
            get_player(duel['challenger_id']), c_hp, duel['challenger_max_hp'],
            get_player(duel['target_id']), t_hp, duel['target_max_hp'],
            defender['name'], pressure, combo, press_line
        )

        await _safe_edit(
            query,
            f"{status}",
            parse_mode='Markdown',
            reply_markup=build_duel_keyboard(opp_id)
        )
        logger.info(f"⚔️ {attacker.get('name')} attacked for {dmg} damage")

    except Exception as e:
        logger.error(f"❌ Error during attack: {e}")
        await query.answer(f"❌ Error", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════════
# ► TECHNIQUE - MENU
# ═══════════════════════════════════════════════════════════════════════════

@no_button_spam
async def duel_technique_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show art selection."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    try:
        attacker_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await query.answer("❌ Invalid.", show_alert=True)
        return

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    
    if not duel_doc or duel_doc['turn_user_id'] != user_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await query.answer("❌ No character!", show_alert=True)
        return

    try:
        buttons = []

        buttons.append([InlineKeyboardButton(
            f"{player.get('style_emoji', '💨')} {player['style']} (Primary)",
            callback_data=f"duel_art_{user_id}_{player['style'].replace(' ', '_')}"
        )])

        if player.get('hybrid_style'):
            hs = player['hybrid_style']
            he = player.get('hybrid_emoji', '⚡')
            buttons.append([InlineKeyboardButton(
                f"{he} {hs} ⚡ (Hybrid)",
                callback_data=f"duel_art_{user_id}_{hs.replace(' ', '_')}"
            )])

        buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"duel_view_{user_id}")])

        if not player.get('hybrid_style'):
            await _show_duel_forms(query, user_id, player, player['style'])
            return

        await _safe_edit(
            query,
            f"💨 *CHOOSE ART*\n\nWhich art?",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"❌ Error in technique menu: {e}")
        await query.answer(f"❌ Error", show_alert=True)

async def _show_duel_forms(query, user_id, player, art_name):
    """Show form selection."""
    try:
        level = get_level(player.get('xp', 0))
        from utils.helpers import get_unlocked_forms
        forms = get_unlocked_forms(art_name, level)

        if not forms:
            await query.answer(f"❌ No forms for {art_name}!", show_alert=True)
            return

        buttons = []
        for f in forms[:9]:
            buttons.append([InlineKeyboardButton(
                f"Form {f['form']} — {f['name']} | {f.get('dmg_min', '?')}-{f.get('dmg_max', '?')} DMG",
                callback_data=f"duel_form_{user_id}_{f['form']}_{art_name.replace(' ', '_')}"
            )])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"duel_technique_{user_id}")])

        await _safe_edit(
            query,
            f"💨 *{art_name.upper()}*\n\nChoose form:",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"❌ Error showing forms: {e}")
        await query.answer(f"❌ Error", show_alert=True)

@no_button_spam
async def duel_art_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle art selection."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    try:
        parts = query.data.split('_', 3)
        attacker_id = int(parts[2])
        art_name = parts[3].replace('_', ' ')
    except (ValueError, IndexError):
        await query.answer("❌ Invalid.", show_alert=True)
        return

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await query.answer("❌ No character!", show_alert=True)
        return

    valid_arts = [player.get('style', '')]
    if player.get('hybrid_style'):
        valid_arts.append(player['hybrid_style'])

    if art_name not in valid_arts:
        await query.answer(f"❌ No access to {art_name}!", show_alert=True)
        return

    await _show_duel_forms(query, user_id, player, art_name)

@no_button_spam
async def duel_use_form(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use a technique form."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    try:
        parts = query.data.split('_')
        attacker_id = int(parts[2])
        form_num = int(parts[3])
        art_name_raw = '_'.join(parts[4:]) if len(parts) > 4 else None
    except (ValueError, IndexError):
        await query.answer("❌ Invalid.", show_alert=True)
        return

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    
    if not duel_doc or duel_doc['turn_user_id'] != user_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    try:
        duel = dict(duel_doc)
        duel_oid = duel_doc["_id"]
        duel.pop("_id", None)
        duel_key = str(duel_oid)
        
        attacker = get_player(user_id)
        opp_id = get_opponent_id(duel, user_id)
        defender = get_player(opp_id)
        level = get_level(attacker.get('xp', 0))

        if art_name_raw:
            art_name = art_name_raw.replace('_', ' ')
        else:
            art_name = attacker.get('style', 'Unknown')

        from utils.helpers import get_unlocked_forms
        forms = get_unlocked_forms(art_name, level)
        form = next((f for f in forms if f['form'] == form_num), None)
        
        if not form:
            await query.answer("❌ Form not available!", show_alert=True)
            return

        pressure = context.bot_data.get(f"duel_pressure_{duel_key}") or calc_pressure(attacker)
        
        _, opp_hp_key, _, _ = _duel_hp_key(duel, user_id)
        opp_hp = duel[opp_hp_key]

        try:
            from handlers.explore import _safe_get_skills, _safe_get_bonuses, _calculate_form_hit_damage
            owned_skills = _safe_get_skills(user_id)
            bonuses = _safe_get_bonuses(user_id, context)
            dmg = _calculate_form_hit_damage(
                attacker, form,
                {"enemy_hp": opp_hp, "enemy_max_hp": duel.get(opp_hp_key.replace('_hp', '_max_hp'), 100)},
                owned_skills=owned_skills, user_id=user_id, context=context, bonuses=bonuses, log=[],
            )
        except:
            dmg = random.randint(form.get('dmg_min', 10), form.get('dmg_max', 20))

        dmg = int(dmg * 0.70)
        dmg = int(dmg * pressure.get('tech_mult', 1.0))

        max_tech_dmg = int(duel.get(opp_hp_key.replace('_hp', '_max_hp'), 100) * 0.40)
        if dmg > max_tech_dmg:
            dmg = max_tech_dmg

        new_opp = max(0, opp_hp - dmg)

        # Log to battle log
        battle_log = context.bot_data.get(f"duel_battle_log_{duel_key}")
        if battle_log:
            battle_log.add_move(user_id, 'technique', {
                'actor_name': attacker.get('name', 'Unknown'),
                'target_name': defender.get('name', 'Unknown') if defender else 'Unknown',
                'technique_name': art_name,
                'form_number': form_num,
                'damage': dmg,
                'effects': form.get('effect', ''),
            })

        if new_opp <= 0:
            col("duels").update_one({"_id": duel_oid}, {"$set": {opp_hp_key: 0}})
            logger.info(f"✅ {attacker.get('name')} KO'd with technique")
            await _finish_duel(query, duel_doc, user_id, opp_id, context, "Technique KO")
            return

        col("duels").update_one({"_id": duel_oid}, {"$set": {opp_hp_key: new_opp, "turn_user_id": opp_id}})

        c_hp = duel['challenger_hp'] if duel['challenger_id'] == user_id else new_opp
        t_hp = new_opp if duel['challenger_id'] == user_id else duel['target_hp']

        combo = context.bot_data.get(f"duel_combo_{duel_key}", 0) + 1
        context.bot_data[f"duel_combo_{duel_key}"] = combo
        press_line = _fmt_press([f"{art_name} Form {form_num} - {dmg} dmg"])
        context.bot_data[f"duel_last_press_{duel_key}"] = press_line

        opp_player = get_player(opp_id)
        status = duel_status_text(
            get_player(duel['challenger_id']), c_hp, duel['challenger_max_hp'],
            get_player(duel['target_id']), t_hp, duel['target_max_hp'],
            opp_player['name'] if opp_player else "Opponent", pressure, combo, press_line
        )

        await _safe_edit(
            query,
            f"{status}",
            parse_mode='Markdown',
            reply_markup=build_duel_keyboard(opp_id)
        )
        logger.info(f"💨 {attacker.get('name')} used {art_name} for {dmg} dmg")

    except Exception as e:
        logger.error(f"❌ Error using technique: {e}")
        await query.answer(f"❌ Error", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════════
# ► ITEMS
# ═══════════════════════════════════════════════════════════════════════════

@no_button_spam
async def duel_items_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show items menu."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    try:
        attacker_id = int(query.data.split('_')[-1])
    except (ValueError, IndexError):
        await query.answer("❌ Invalid.", show_alert=True)
        return

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    
    if duel_doc and duel_doc.get("settings", {}).get("no_items"):
        await query.answer("🚫 No Items mode active!", show_alert=True)
        return

    inv = get_inventory(user_id)
    usables = [i for i in inv if i['item_type'] == 'item'] if inv else []
    
    if not usables:
        await query.answer("❌ No items!", show_alert=True)
        return

    try:
        buttons = []
        for item in usables[:5]:
            buttons.append([InlineKeyboardButton(
                f"🧪 {item['item_name']} ×{item.get('quantity', 1)}",
                callback_data=f"duel_useitem_{user_id}_{item['item_name'].replace(' ', '_')}"
            )])
        buttons.append([InlineKeyboardButton("🔙 Back", callback_data=f"duel_view_{user_id}")])

        await _safe_edit(
            query, "🧪 *USE ITEM*\n\nChoose:",
            parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(buttons)
        )
    except Exception as e:
        logger.error(f"❌ Error in items menu: {e}")
        await query.answer(f"❌ Error", show_alert=True)

@no_button_spam
async def duel_use_item(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Use an item."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    try:
        parts = query.data.split('_')
        attacker_id = int(parts[2])
        item_name = ' '.join(parts[3:]).replace('_', ' ')
    except (ValueError, IndexError):
        await query.answer("❌ Invalid.", show_alert=True)
        return

    if user_id != attacker_id:
        await query.answer("❌ Not your turn!", show_alert=True)
        return

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    
    if not duel_doc:
        await query.answer("❌ No duel!", show_alert=True)
        return

    try:
        duel = dict(duel_doc)
        duel_oid = duel_doc["_id"]
        duel.pop("_id", None)
        duel_key = str(duel_oid)
        
        inv = get_inventory(user_id)
        owned = next((i for i in inv if i['item_name'].lower() == item_name.lower()), None)
        
        if not owned:
            await query.answer("❌ Item not found!", show_alert=True)
            return

        player = get_player(user_id)
        opp_id = get_opponent_id(duel, user_id)
        my_hp_k, opp_hp_k, my_max_k, _ = _duel_hp_key(duel, user_id)
        my_max = duel[my_max_k]

        result = ""
        if 'Gourd' in owned.get('item_name', ''):
            col("duels").update_one({"_id": duel_oid}, {"$set": {my_hp_k: my_max}})
            result = "❤️ HP restored!"
        elif 'Stamina' in owned.get('item_name', ''):
            result = "🌀 +50 STA!"

        remove_item(user_id, owned['item_name'])
        col("duels").update_one({"_id": duel_oid}, {"$set": {"turn_user_id": opp_id}})

        # Log to battle log
        battle_log = context.bot_data.get(f"duel_battle_log_{duel_key}")
        defender = get_player(opp_id)
        if battle_log:
            battle_log.add_move(user_id, 'item', {
                'actor_name': player.get('name', 'Unknown'),
                'target_name': defender.get('name', 'Unknown') if defender else 'Unknown',
                'item_name': owned['item_name'],
                'effect': result,
            })

        fresh = col("duels").find_one({"_id": duel_oid})
        c_hp = fresh['challenger_hp'] if fresh else 0
        t_hp = fresh['target_hp'] if fresh else 0
        opp = get_player(opp_id)
        pressure = context.bot_data.get(f"duel_pressure_{duel_key}")
        last_press = context.bot_data.get(f"duel_last_press_{duel_key}", "")

        status = duel_status_text(
            get_player(duel['challenger_id']), c_hp, duel['challenger_max_hp'],
            get_player(duel['target_id']), t_hp, duel['target_max_hp'],
            opp['name'] if opp else "Opponent", pressure, last_press=last_press
        )

        await _safe_edit(
            query,
            f"{status}",
            parse_mode='Markdown',
            reply_markup=build_duel_keyboard(opp_id)
        )
        logger.info(f"🧪 {player.get('name')} used {owned['item_name']}")

    except Exception as e:
        logger.error(f"❌ Error using item: {e}")
        await query.answer(f"❌ Error", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════════
# ► SURRENDER
# ═══════════════════════════════════════════════════════════════════════════

@no_button_spam
async def duel_surrender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Surrender from duel."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    
    if not duel_doc:
        await query.answer("❌ No duel!", show_alert=True)
        return
    
    try:
        opp_id = get_opponent_id(dict(duel_doc), user_id)
        logger.info(f"🏳️ {user_id} surrendered")
        await _finish_duel(query, duel_doc, opp_id, user_id, context, "Surrender")
    except Exception as e:
        logger.error(f"❌ Error surrendering: {e}")
        await query.answer(f"❌ Error", show_alert=True)

# ═══════════════════════════════════════════════════════════════════════════
# ► DUEL SETTINGS
# ═══════════════════════════════════════════════════════════════════════════

async def duel_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show duel settings."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    
    try:
        challenger_id = int(query.data.split("_")[-1])
    except (ValueError, IndexError):
        await query.answer("❌ Invalid.", show_alert=True)
        return

    if user_id != challenger_id:
        await query.answer("⚠️ Only challenger!", show_alert=True)
        return

    settings = context.user_data.get(f"duel_settings_{challenger_id}", {
        "no_items": False, "techniques_only": False, "hp_multiplier": 1.0,
    })
    ni = settings.get("no_items", False)
    to = settings.get("techniques_only", False)
    hpm = settings.get("hp_multiplier", 1.0)

    buttons = [
        [InlineKeyboardButton(("✅ " if ni else "⬜ ") + "No Items",
            callback_data=f"duel_toggle_noitems_{challenger_id}")],
        [InlineKeyboardButton(("✅ " if to else "⬜ ") + "Techniques Only",
            callback_data=f"duel_toggle_techonly_{challenger_id}")],
        [InlineKeyboardButton(f"❤️ HP: {hpm}x",
            callback_data=f"duel_toggle_hp_{challenger_id}")],
        [
            InlineKeyboardButton("🔙 Cancel", callback_data=f"duel_settings_back_{challenger_id}"),
            InlineKeyboardButton("✅ Save", callback_data=f"duel_settings_done_{challenger_id}"),
        ],
    ]
    await _safe_edit(
        query,
        f"⚙️ *DUEL SETTINGS*\n"
        f"🚫 No Items: {'*ON*' if ni else 'OFF'}\n"
        f"🌀 Techniques: {'*ON*' if to else 'OFF'}\n"
        f"❤️ HP: *{hpm}x*",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

async def duel_toggle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle setting."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split('_')
    ch_id = int(parts[-1])
    toggle = parts[2]

    if user_id != ch_id:
        await query.answer("❌ Only challenger!", show_alert=True)
        return

    settings = context.user_data.get(f'duel_settings_{ch_id}', {
        'no_items': False, 'techniques_only': False, 'hp_multiplier': 1.0,
    })
    
    if toggle == 'noitems':
        settings['no_items'] = not settings.get('no_items', False)
    elif toggle == 'techonly':
        settings['techniques_only'] = not settings.get('techniques_only', False)
    elif toggle == 'hp':
        cycle = [0.5, 1.0, 1.5, 2.0]
        cur = settings.get('hp_multiplier', 1.0)
        try:
            idx = cycle.index(cur)
        except ValueError:
            idx = 1
        settings['hp_multiplier'] = cycle[(idx + 1) % len(cycle)]

    context.user_data[f'duel_settings_{ch_id}'] = settings
    await duel_settings_callback(update, context)

async def duel_settings_back_callback(update, context):
    """Discard settings."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    ch_id = int(query.data.split('_')[-1])

    if user_id != ch_id:
        await query.answer("⚠️ Only challenger!", show_alert=True)
        return

    context.user_data.pop(f"duel_settings_{ch_id}", None)

    player = get_player(user_id)
    if not player:
        await _safe_edit(query, "❌ No character.")
        return

    await _safe_edit(
        query,
        _challenge_text(player),
        parse_mode="Markdown",
        reply_markup=_challenge_keyboard(ch_id)
    )

async def duel_settings_done_callback(update, context):
    """Save settings."""
    query = update.callback_query
    await query.answer("✅ Saved!")
    user_id = query.from_user.id
    ch_id = int(query.data.split('_')[-1])

    if user_id != ch_id:
        await query.answer("⚠️ Only challenger!", show_alert=True)
        return

    settings = context.user_data.get(f"duel_settings_{ch_id}", {
        "no_items": False, "techniques_only": False, "hp_multiplier": 1.0,
    })
    player = get_player(user_id)
    if not player:
        await _safe_edit(query, "❌ No character.")
        return

    await _safe_edit(
        query,
        _challenge_text(player, settings),
        parse_mode="Markdown",
        reply_markup=_challenge_keyboard(ch_id)
    )

# ═══════════════════════════════════════════════════════════════════════════
# ► DRAW
# ═══════════════════════════════════════════════════════════════════════════

@no_button_spam
async def duel_draw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Propose or accept draw."""
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    duel_doc = col("duels").find_one({
        "$or": [{"challenger_id": user_id}, {"target_id": user_id}],
        "status": "active"
    })
    
    if not duel_doc:
        await query.answer("❌ No duel!", show_alert=True)
        return

    try:
        opponent_id = get_opponent_id(dict(duel_doc), user_id)
        draw_proposed_by = duel_doc.get('draw_proposed_by')

        if draw_proposed_by == opponent_id:
            col("duels").update_one({"_id": duel_doc["_id"]}, {"$set": {"status": "finished", "result": "draw"}})
            player = get_player(user_id)
            opponent = get_player(opponent_id)
            xp_draw = 150
            update_player(user_id, xp=player['xp'] + xp_draw)
            update_player(opponent_id, xp=opponent['xp'] + xp_draw)

            fe_p = '🗡️' if player['faction'] == 'slayer' else '👹'
            fe_o = '🗡️' if opponent['faction'] == 'slayer' else '👹'
            
            logger.info(f"🤝 Draw accepted")
            
            await _safe_edit(
                query,
                f"🤝 *DRAW AGREED!*\n"
                f"{fe_p} *{player['name']}* and {fe_o} *{opponent['name']}*\n"
                f"Both: +{xp_draw} XP",
                parse_mode='Markdown'
            )
            return

        col("duels").update_one({"_id": duel_doc["_id"]}, {"$set": {"draw_proposed_by": user_id}})
        player = get_player(user_id)
        opponent = get_player(opponent_id)

        accept_kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🤝 Accept", callback_data=f"duel_draw_{opponent_id}"),
            InlineKeyboardButton("⚔️ Fight", callback_data=f"duel_attack_{opponent_id}"),
        ]])
        
        logger.info(f"🤝 {player.get('name')} proposed draw")
        
        await _safe_edit(
            query,
            f"🤝 *{player['name']}* proposes *DRAW*!\n"
            f"_{opponent['name'] if opponent else 'Opponent'}?_",
            parse_mode='Markdown',
            reply_markup=accept_kb
        )
    except Exception as e:
        logger.error(f"❌ Error in draw: {e}")
        await query.answer(f"❌ Error", show_alert=True)

logger.info("✅ ════════════════════════════════════════════════════════════════════════════")
logger.info("✅ challenge.py FULLY LOADED - Expandable Battle Logs Ready!")
logger.info("✅ ════════════════════════════════════════════════════════════════════════════")
