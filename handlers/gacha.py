"""
handlers/gacha.py — Spirit Summon (Gacha) System

Commands:
  /summon        — Open the summon menu (first-time users get 20 free shards)
  /spirits       — View your spirit collection & equip up to 3 for battle
  /shards        — Show your shard balance and how to earn more

Callbacks:
  gacha_pull_1 / gacha_pull_10   — spend shards, sealed scroll appears
  gacha_reveal_<token>           — "Check what's inside!" reveal (message edit)
  gacha_rates                    — transparent drop-rate table
  spirit_equip_<name>            — toggle equip (max GACHA_MAX_EQUIPPED slots)

Economy (fair, no pay-to-win):
  - Shards are NOT purchasable with Yen and NOT tradeable.
  - Earned only via: one-time starter gift (20), rare explore finds, boss rewards (max 5).
  - 1x pull = 10 shards, 10x pull = 90 shards (discounted).
  - Pity: Epic guaranteed every 30 pulls, Legendary guaranteed every 80 pulls.
  - Only EQUIPPED spirits grant bonuses (max 3 slots) — everyone plays on equal footing.
"""
import logging
log = logging.getLogger(__name__)

import random
import secrets

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import (
    get_player, update_player, col,
    add_shards, spend_shards, add_spirit, get_spirit_bonuses,
    get_spirit_collection, set_spirit_equipped, get_equipped_spirits,
)
from utils.guards import dm_only
from config import (
    GACHA_COST_SINGLE, GACHA_COST_TEN, GACHA_FREE_STARTER_SHARDS,
    GACHA_PITY_EPIC, GACHA_PITY_LEGEND, GACHA_MAX_EQUIPPED,
    GACHA_RARITY_WEIGHTS, GACHA_RARITY_EMOJI, GACHA_SPIRITS,
)

RARITY_ORDER = ["Common", "Uncommon", "Rare", "Epic", "Legendary"]
_SPIRIT_BY_NAME = {s["name"]: s for s in GACHA_SPIRITS}

# Reveal cache: token -> {"user_id": int, "results": [spirit dict, ...], "pity_line": str}
_pending_reveals = {}


# ── Core pull logic (pure, testable) ───────────────────────────────────────
def roll_rarity(pity_after: int, rng=random) -> str:
    """Weighted rarity roll with pity guarantees."""
    if pity_after >= GACHA_PITY_LEGEND:
        return "Legendary"
    if pity_after >= GACHA_PITY_EPIC:
        return rng.choices(
            ["Epic", "Legendary"], weights=[GACHA_RARITY_WEIGHTS["Epic"], GACHA_RARITY_WEIGHTS["Legendary"]]
        )[0]
    rarities = list(GACHA_RARITY_WEIGHTS.keys())
    weights = list(GACHA_RARITY_WEIGHTS.values())
    return rng.choices(rarities, weights=weights)[0]


def pick_spirit(rarity: str, rng=random) -> dict:
    pool = [s for s in GACHA_SPIRITS if s["rarity"] == rarity] or GACHA_SPIRITS
    return rng.choice(pool)


def perform_pulls(count: int, pity: int, rng=random) -> tuple[list, int]:
    """Roll `count` spirits starting from current pity counter.
    Returns (list of spirit dicts, new pity counter)."""
    results = []
    cur_pity = pity
    for _ in range(count):
        cur_pity += 1
        rarity = roll_rarity(cur_pity, rng=rng)
        if rarity == "Legendary":
            cur_pity = 0  # reset legendary pity on hit
        results.append(pick_spirit(rarity, rng=rng))
    return results, cur_pity


def grant_explore_shards(user_id: int) -> int:
    """Called after /explore starts a normal encounter: rare chance to find shards.
    Base 8% for +1 shard; equipped spirits with shard_bonus raise the odds.
    Returns number of shards granted (0 or 1)."""
    chance = 0.08
    try:
        chance += get_spirit_bonuses(user_id).get("shard_bonus", 0.0)
    except Exception:
        pass
    if random.random() < chance:
        add_shards(user_id, 1)
        return 1
    return 0


def roll_boss_shards(enemy_name: str = "") -> int:
    """Boss reward: max 5 shards. Legendary bosses give 5, other bosses 2-4."""
    legendary_bosses = ("yoriichi", "kokushibo", "muzan")
    name_l = (enemy_name or "").lower()
    if any(b in name_l for b in legendary_bosses):
        return 5
    return random.randint(2, 4)


# ── Battle flavour: equipped spirits act like companions ───────────────────
_SPIRIT_SHOUTS = {
    "Common":    ["whispers encouragement", "glows faintly beside you"],
    "Uncommon":  ["cries out with you", "flares at your side"],
    "Rare":      ["roars alongside your strike", "surges around your blade"],
    "Epic":      ["unleashes a spectral howl", "blazes beside you in battle"],
    "Legendary": ["manifests in a burst of otherworldly light",
                  "shatters the air with a divine war-cry"],
}


def spirit_battle_lines(user_id: int, action: str = "attack") -> list:
    """Return 0..N short flavour lines showing equipped spirits fighting with
    the player. Pure display helper — never raises (safe to call anywhere)."""
    try:
        equipped = get_equipped_spirits(user_id)
    except Exception:
        return []
    lines = []
    for s in equipped[:3]:
        shouts = _SPIRIT_SHOUTS.get(s.get("rarity", "Common"), _SPIRIT_SHOUTS["Common"])
        shout = random.choice(shouts)
        em = s.get("emoji", "👻")
        name = s.get("name", "Spirit")
        uni = s.get("universe", "Demon Slayer")
        if action == "attack":
            lines.append(f"{em} *{name}* _(from {uni})_ {shout}!")
        elif action == "defend":
            lines.append(f"{em} *{name}* shields you with a spectral barrier!")
        else:  # victory
            lines.append(f"{em} *{name}* rejoices at your victory!")
    return lines


# ── Formatting helpers ─────────────────────────────────────────────────────
def passive_text(spirit: dict) -> str:
    labels = {
        "atk_pct": ("⚔️", "ATK"), "def_pct": ("🛡️", "DEF"), "hp_pct": ("❤️", "Max HP"),
        "sta_pct": ("🌀", "STA"), "spd_pct": ("⚡", "SPD"),
        "xp_pct": ("⭐", "XP gain"), "yen_pct": ("💰", "Yen gain"), "shard_bonus": ("🔮", "Shard luck"),
    }
    parts = []
    for key, val in spirit.get("passive", {}).items():
        em, name = labels.get(key, ("✨", key))
        parts.append(f"{em} +{int(round(val * 100))}% {name}")
    return " | ".join(parts) if parts else "—"


def result_line(idx: int, spirit: dict, is_new: bool) -> str:
    r = spirit["rarity"]
    tag = " 🆕" if is_new else ""
    uni = f"  ·  _{spirit.get('universe', 'Demon Slayer')}_" if spirit.get("universe") else ""
    return f"{idx:>2}. {GACHA_RARITY_EMOJI[r]} {spirit['emoji']} *{spirit['name']}* _({r})_{tag}{uni}"


def spirit_card(spirit: dict, is_new: bool) -> str:
    """Pretty single-spirit reveal card (used for 1x pulls)."""
    r = spirit["rarity"]
    em = GACHA_RARITY_EMOJI.get(r, "✨")
    banner = {"Legendary": "🌟🔥🌟", "Epic": "💜✨💜"}.get(r, "✨")
    lines = [
        f"{banner} *SUMMON RESULT* {banner}",
        "",
        f"{em} {spirit['emoji']} *{spirit['name']}*",
        f"🎴 Rarity: *{r}*   ·   🌌 Universe: _{spirit.get('universe', 'Demon Slayer')}_",
        f"📜 Passive: {passive_text(spirit)}",
    ]
    if spirit.get("lore"):
        lines.append(f"💬 _\"{spirit['lore']}\"_")
    if is_new:
        lines.append("🆕 *New spirit added to your shrine!*")
    else:
        lines.append("🔁 Duplicate — count increased (tap /spirits to see it).")
    lines += [
        "",
        "_Your equipped spirits fight beside you in battle ⚔️_",
        f"{banner}",
    ]
    return "\n".join(lines)


def build_scroll_keyboard(token: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🎁 Check what's inside!", callback_data=f"gacha_reveal_{token}")
    ]])


def build_main_keyboard(shards: int) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(f"🎴 1x Pull ({GACHA_COST_SINGLE} 🔮)", callback_data="gacha_pull_1"),
        InlineKeyboardButton(f"🎴 10x Pull ({GACHA_COST_TEN} 🔮)", callback_data="gacha_pull_10"),
    ]
    return InlineKeyboardMarkup([
        row,
        [InlineKeyboardButton("📊 Drop Rates", callback_data="gacha_rates"),
         InlineKeyboardButton("👻 My Spirits", callback_data="gacha_my_spirits")],
    ])


# ── /summon command ────────────────────────────────────────────────────────
@dm_only
async def summon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return

    # One-time starter gift: 20 free shards on first /summon
    gifted = player.get("spirits_gifted", 0) or 0
    if gifted < 1:
        add_shards(user_id, GACHA_FREE_STARTER_SHARDS)
        update_player(user_id, spirits_gifted=1)
        player = get_player(user_id)
        await update.message.reply_text(
            f"🎁 *WELCOME GIFT!* — The spirit realm acknowledges you!\n"
            f"+{GACHA_FREE_STARTER_SHARDS} 🔮 *Spirit Shards* added to your account!"
        )

    shards = player.get("shards", 0) or 0
    pity = player.get("gacha_pity", 0) or 0
    total_pulls = player.get("gacha_total_pulls", 0) or 0
    owned = len(get_spirit_collection(user_id))
    equipped = get_equipped_spirits(user_id)

    text = (
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎴 *SPIRIT SUMMON SHRINE* ⛩️\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Summon companion spirits to fight by your side!\n\n"
        f"🔮 Your Shards: *{shards}*\n"
        f"🎴 Total Summons: *{total_pulls}*  |  👻 Owned: *{owned}* spirits\n"
        f"⚔️ Equipped: *{len(equipped)}/{GACHA_MAX_EQUIPPED}* slots  _(use /spirits)_\n\n"
        f"🎴 *1x Pull* — {GACHA_COST_SINGLE} 🔮\n"
        f"🎴 *10x Pull* — {GACHA_COST_TEN} 🔮 _(save {GACHA_COST_SINGLE * 10 - GACHA_COST_TEN}!)_\n\n"
        f"🛡️ *Pity:* Epic in *{max(0, GACHA_PITY_EPIC - pity)}* pulls · "
        f"Legendary in *{max(0, GACHA_PITY_LEGEND - pity)}* pulls\n\n"
        f"_Shards from:_ 🔍 exploration finds · ☠️ boss rewards (up to 5)\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
    )
    await update.message.reply_text(text, reply_markup=build_main_keyboard(shards), parse_mode="Markdown")


# ── Pull callbacks ─────────────────────────────────────────────────────────
async def _do_pull(query, user_id: int, count: int):
    player = get_player(user_id)
    if not player:
        await query.answer("Character not found. Use /start.", show_alert=True)
        return

    cost = GACHA_COST_SINGLE if count == 1 else GACHA_COST_TEN
    shards = player.get("shards", 0) or 0
    if shards < cost:
        await query.answer(
            f"🔮 Not enough shards! Need {cost}, you have {shards}.\n"
            f"Earn them via exploration and boss fights!",
            show_alert=True,
        )
        return

    if not spend_shards(user_id, cost):
        await query.answer("⚠️ Shard balance changed — try again!", show_alert=True)
        return

    pity = player.get("gacha_pity", 0) or 0
    results, new_pity = perform_pulls(count, pity)

    # Persist results
    new_count = 0
    for s in results:
        if add_spirit(user_id, s):
            new_count += 1
    total_pulls = (player.get("gacha_total_pulls", 0) or 0) + count
    update_player(user_id, gacha_pity=new_pity, gacha_total_pulls=total_pulls)

    # Cache reveal payload; the scroll stays sealed until user taps the button
    token = secrets.token_hex(6)
    _pending_reveals[token] = {"user_id": user_id, "results": results, "new_count": new_count}

    remaining = get_player(user_id).get("shards", 0) or 0
    sealed = (
        f"🎴 *SEALED BLESSING SCROLL...*\n\n"
        f"{'🕯️' * min(count, 10)}\n\n"
        f"The shrine maiden seals your {'scroll' if count == 1 else 'ten-fold blessing'}...\n"
        f"Cost: *{cost} 🔮*  ·  Remaining: *{remaining} 🔮*\n\n"
        f"_Tap below to reveal your spirits!_"
    )
    try:
        await query.edit_message_text(sealed, reply_markup=build_scroll_keyboard(token), parse_mode="Markdown")
    except Exception:
        await query.message.reply_text(sealed, reply_markup=build_scroll_keyboard(token), parse_mode="Markdown")
    await query.answer()


async def gacha_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    user_id = query.from_user.id

    if data in ("gacha_pull_1", "gacha_pull_10"):
        await _do_pull(query, user_id, 1 if data.endswith("1") else 10)
        return

    if data.startswith("gacha_reveal_"):
        token = data.split("_", 2)[2]
        payload = _pending_reveals.pop(token, None)
        if not payload or payload["user_id"] != user_id:
            await query.answer("❌ This scroll has expired. Use /summon again!", show_alert=True)
            return
        results = payload["results"]
        player = get_player(user_id)
        pity = player.get("gacha_pity", 0) or 0

        if len(results) == 1:
            s = results[0]
            header = spirit_card(s, payload.get("new_count", 0) > 0)
        else:
            lines = "\n".join(result_line(i, s, False) for i, s in enumerate(results, 1))
            best = max(results, key=lambda x: RARITY_ORDER.index(x["rarity"]))
            header = (
                f"✨ *TENFOLD SUMMON RESULTS* ✨\n\n{lines}\n\n"
                f"🏆 Best pull: {GACHA_RARITY_EMOJI[best['rarity']]} {best['emoji']} *{best['name']}* "
                f"_(from {best.get('universe', 'Demon Slayer')})_ — {passive_text(best)}\n"
                f"🆕 New spirits: *{payload['new_count']}*"
            )
        footer = (
            f"\n\n🔮 Shards left: *{player.get('shards', 0) or 0}*\n"
            f"🛡️ Pity: Epic in *{max(0, GACHA_PITY_EPIC - pity)}* · Legendary in *{max(0, GACHA_PITY_LEGEND - pity)}*"
        )
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🎴 Summon Again", callback_data="gacha_back"),
            InlineKeyboardButton("👻 Equip Spirits", callback_data="gacha_my_spirits"),
        ]])
        await query.edit_message_text(header + footer, reply_markup=kb, parse_mode="Markdown")
        await query.answer()
        # Server-wide hype for legendaries
        for s in results:
            if s["rarity"] == "Legendary":
                try:
                    log.info("LEGENDARY PULL: user %s got %s", user_id, s["name"])
                except Exception:
                    pass
        return

    if data == "gacha_back":
        player = get_player(user_id)
        if player:
            shards = player.get("shards", 0) or 0
            await query.edit_message_text(
                f"🎴 *SPIRIT SUMMON SHRINE* ⛩️\n\n🔮 Your Shards: *{shards}*",
                reply_markup=build_main_keyboard(shards), parse_mode="Markdown",
            )
        await query.answer()
        return

    if data == "gacha_rates":
        rows = []
        for r in RARITY_ORDER:
            n = sum(1 for s in GACHA_SPIRITS if s["rarity"] == r)
            rows.append(f"{GACHA_RARITY_EMOJI[r]} *{r:9}* — {GACHA_RARITY_WEIGHTS[r]}%  _({n} spirits)_")
        await query.edit_message_text(
            "📊 *SUMMON DROP RATES*\n━━━━━━━━━━━━━━━━━━\n"
            + "\n".join(rows)
            + f"\n\n🛡️ *Guarantees:* Epic every {GACHA_PITY_EPIC} pulls · "
              f"Legendary every {GACHA_PITY_LEGEND} pulls (counter resets on hit)"
            + "\n\n_Fair play: shards cannot be bought with ¥ or traded._",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="gacha_back")]]),
            parse_mode="Markdown",
        )
        await query.answer()
        return

    if data == "gacha_my_spirits":
        await _render_spirits(query)
        await query.answer()
        return

    if data.startswith("spirit_equip_"):
        name = data[len("spirit_equip_"):]
        spirit = _SPIRIT_BY_NAME.get(name)
        if not spirit:
            await query.answer("Unknown spirit.", show_alert=True)
            return
        doc = col("spirits").find_one({"user_id": user_id, "name": name}, {"_id": 0})
        if not doc:
            await query.answer("You don't own this spirit yet!", show_alert=True)
            return
        currently_equipped = get_equipped_spirits(user_id)
        names_eq = {d["name"] for d in currently_equipped}
        if doc.get("equipped"):
            set_spirit_equipped(user_id, name, False)
            await query.answer(f"Unequipped {spirit['emoji']} {name}.")
        elif len(names_eq) >= GACHA_MAX_EQUIPPED:
            await query.answer(
                f"⚠️ All {GACHA_MAX_EQUIPPED} spirit slots are full!\nUnequip one first via /spirits.",
                show_alert=True,
            )
        else:
            set_spirit_equipped(user_id, name, True)
            await query.answer(f"✅ {spirit['emoji']} {name} now fights by your side!")
        await _render_spirits(query)
        return


async def _render_spirits(query):
    user_id = query.from_user.id
    owned = get_spirit_collection(user_id)
    if not owned:
        await query.edit_message_text(
            "👻 *Your spirit shrine is empty!*\n\nUse /summon to summon your first spirit 🎴",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎴 Summon", callback_data="gacha_back")]]),
            parse_mode="Markdown",
        )
        return
    owned.sort(key=lambda d: (RARITY_ORDER.index(d.get("rarity", "Common")), d.get("name", "")))
    equipped = [d for d in owned if d.get("equipped")]
    player = get_player(user_id)
    shards = (player.get("shards", 0) or 0) if player else 0

    # Group by anime universe for a clean, readable shrine
    universes: dict[str, list] = {}
    for d in owned:
        universes.setdefault(d.get("universe") or "Demon Slayer", []).append(d)

    lines = []
    for uni, spirits in universes.items():
        lines.append(f"🌌 *{uni}*")
        for d in spirits:
            slot = "✅" if d.get("equipped") else "▫️"
            dup = f" ×{d.get('count', 1)}" if d.get("count", 1) > 1 else ""
            rar_em = GACHA_RARITY_EMOJI.get(d.get("rarity"), "")
            lines.append(f"  {slot} {rar_em} {d.get('emoji')} *{d['name']}*{dup}")
        lines.append("")
    bonus_parts = []
    for d in equipped:
        p = passive_text(d)
        if p != "—":
            bonus_parts.append(f"{d.get('emoji')} {p}")
    total_battle = "\n     ".join(bonus_parts) if bonus_parts else "None equipped — your blades strike alone!"
    text = (
        f"👻 *SPIRIT SHRINE COLLECTION*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚔️ Equipped: *{len(equipped)}/{GACHA_MAX_EQUIPPED}*   ·   🔮 Shards: *{shards}*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n" + "\n".join(lines) +
        f"\n⚔️ *Battle bonuses active:*\n     {total_battle}\n\n"
        f"_Spirits fight beside you — tap one below to equip/unequip it._"
    )
    kb_rows = []
    for d in owned:
        mark = "✅ " if d.get("equipped") else ""
        kb_rows.append([InlineKeyboardButton(f"{mark}{d.get('emoji')} {d['name']}", callback_data=f"spirit_equip_{d['name']}")])
    kb_rows.append([InlineKeyboardButton("🎴 Back to Shrine", callback_data="gacha_back")])
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb_rows), parse_mode="Markdown")


# ── /spirits command ───────────────────────────────────────────────────────
@dm_only
async def spirits_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = await update.message.reply_text("👻 Loading your spirit shrine...")
    fake_query = _FakeQuery(msg, update.effective_user.id)
    try:
        await _render_spirits(fake_query)
    except Exception as e:
        log.exception("spirits_cmd failed")
        await msg.edit_text(f"❌ Error: {e}")


class _FakeQuery:
    """Minimal shim so /spirits reuses the callback renderer."""
    def __init__(self, message, user_id):
        self.message = message
        self._user_id = user_id

    @property
    def from_user(self):
        class U: id = self._user_id
        return U()

    async def edit_message_text(self, text, **kwargs):
        await self.message.edit_text(text, **kwargs)

    async def answer(self, *a, **k):
        pass


# ── /shards command ────────────────────────────────────────────────────────
@dm_only
async def shards_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    player = get_player(update.effective_user.id)
    if not player:
        await update.message.reply_text("❌ No character found. Use /start to create one.")
        return
    shards = player.get("shards", 0) or 0
    await update.message.reply_text(
        f"🔮 *SPIRIT SHARDS*\n━━━━━━━━━━━━━━━━━━\n"
        f"Balance: *{shards} 🔮*\n\n"
        f"*How to earn (all players compete equally):*\n"
        f"• 🎁 First /summon ever → +{GACHA_FREE_STARTER_SHARDS} free shards\n"
        f"• 🔍 Rare find while exploring → +1 shard\n"
        f"• ☠️ Boss victory → up to 5 shards\n\n"
        f"*Spending:* 1x pull = {GACHA_COST_SINGLE} · 10x pull = {GACHA_COST_TEN}\n"
        f"_Shards cannot be bought with ¥ or traded — pure gameplay currency._",
        parse_mode="Markdown",
    )
