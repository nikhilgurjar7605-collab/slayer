from config import SLAYER_RANKS, DEMON_RANKS, TECHNIQUES

def get_rank(faction, xp):
    ranks = SLAYER_RANKS if faction == 'slayer' else DEMON_RANKS
    current = ranks[0]
    for rank in ranks:
        if xp >= rank['xp_needed']:
            current = rank
        else:
            break
    return current

def get_next_rank(faction, xp):
    ranks = SLAYER_RANKS if faction == 'slayer' else DEMON_RANKS
    for rank in ranks:
        if xp < rank['xp_needed']:
            return rank
    return None

def get_level(xp):
    # Max level: 500
    # Uses a formula: XP needed for level n = 100 * n^1.8
    if xp <= 0:
        return 1
    level = 1
    total = 0
    while level < 500:
        needed = int(100 * (level ** 1.8))
        if xp < total + needed:
            break
        total += needed
        level += 1
    return min(level, 500)


def _xp_threshold(level):
    """Total XP needed to reach a given level."""
    total = 0
    for lv in range(1, level):
        total += int(100 * (lv ** 1.8))
    return total


def xp_for_next_level(xp):
    """Returns (current_level, xp_needed_for_next, xp_into_current_level)."""
    level = get_level(xp)
    if level >= 500:
        thresh = _xp_threshold(500)
        return 500, 0, xp - thresh
    current_thresh = _xp_threshold(level)
    next_thresh    = _xp_threshold(level + 1)
    into_level     = xp - current_thresh
    needed         = next_thresh - current_thresh
    return level, needed, into_level

# Rank order maps — higher index = higher rank
_SLAYER_RANK_ORDER = [
    "Mizunoto","Mizunoe","Kanoto","Kanoe","Tsuchinoto",
    "Tsuchinoe","Hinoto","Hinoe","Kinoto","Kinoe",
    "Hashira","Breath of the Sun",
]
_DEMON_RANK_ORDER = [
    "Stray Demon","Lesser Demon","Demon","Demon General",
    "Lower Moon 6","Lower Moon 5","Lower Moon 4","Lower Moon 3","Lower Moon 2","Lower Moon 1",
    "Upper Moon 6","Upper Moon 5","Upper Moon 4","Upper Moon 3","Upper Moon 2","Upper Moon 1",
    "Demon King",
]

def _rank_index(rank_name: str, faction: str) -> int:
    """Return numeric rank index — higher = more powerful."""
    order = _SLAYER_RANK_ORDER if faction == 'slayer' else _DEMON_RANK_ORDER
    try:
        return order.index(rank_name)
    except ValueError:
        return 0

def _required_rank_index(req_rank: str) -> tuple:
    """Return (faction, index) for a required rank string."""
    if req_rank in _SLAYER_RANK_ORDER:
        return ('slayer', _SLAYER_RANK_ORDER.index(req_rank))
    if req_rank in _DEMON_RANK_ORDER:
        return ('demon', _DEMON_RANK_ORDER.index(req_rank))
    return (None, 0)


def get_unlocked_forms(style, level, player_rank: str = None, faction: str = None):
    """
    Return list of forms the player can use.
    Enforces BOTH level gates AND unlock_rank gates.
    
    Args:
        style:       Art/breathing style name
        level:       Player level (int)
        player_rank: Player's current rank name (e.g. "Kinoe", "Upper Moon 6")
        faction:     'slayer' or 'demon'
    """
    all_forms = TECHNIQUES.get(style, [])
    if not all_forms:
        return []

    # Pre-compute player's rank index
    if player_rank and faction:
        p_rank_idx = _rank_index(player_rank, faction)
        p_faction  = faction
    else:
        p_rank_idx = 999   # unknown — skip rank gate (backward compat)
        p_faction  = None

    unlocked = []
    for form in all_forms:
        form_num     = form['form']
        unlock_level = min(1 + (form_num - 1) * 3, 30)

        # Level gate
        if level < unlock_level:
            continue

        # Rank gate — if form requires a specific rank
        req_rank = form.get('unlock_rank')
        if req_rank and p_faction is not None:
            req_faction, req_idx = _required_rank_index(req_rank)
            # Only enforce if same faction (slayer forms need slayer rank, demon forms need demon rank)
            if req_faction == p_faction:
                if p_rank_idx < req_idx:
                    continue   # Player rank too low — skip this form

        unlocked.append(form)

    return unlocked if unlocked else all_forms[:1]

def hp_bar(current, max_hp, length=10):
    if max_hp == 0:
        return '░' * length
    filled = int((current / max_hp) * length)
    filled = max(0, min(filled, length))
    return '▓' * filled + '░' * (length - filled)

def medals(position):
    medals_map = {1: '🥇', 2: '🥈', 3: '🥉'}
    return medals_map.get(position, f'{position}.')

def faction_emoji(faction):
    return '🗡️' if faction == 'slayer' else '👹'
