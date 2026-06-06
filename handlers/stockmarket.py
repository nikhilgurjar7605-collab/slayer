"""
╔══════════════════════════════════════════════════════════════════╗
║           DEMON SLAYER STOCK EXCHANGE — stockmarket.py          ║
║                                                                  ║
║  Player commands:                                                ║
║    /market           — Browse all stocks (paginated)            ║
║    /stockbuy         — Alias to open market                     ║
║    /stocksell        — Open your portfolio to sell              ║
║    /portfolio        — View your holdings + P/L                 ║
║    /stockhistory     — Your last 20 transactions                ║
║                                                                  ║
║  Admin commands:                                                 ║
║    /addstock <ticker> <name> <price> <supply> [emoji]           ║
║    /removestock <ticker>                                        ║
║    /marketcrash      — Drop all prices 10-40%                   ║
║    /marketboom       — Boost all prices 10-35%                  ║
║    /marketreset      — Reset prices to base                     ║
║    /nudgeprice <ticker> <±%>  — Fine-tune one stock             ║
║                                                                  ║
║  Anti-exploit rules enforced:                                    ║
║    • Buy cooldown: 60s per stock per user                       ║
║    • Max shares per user per stock: configurable per stock      ║
║    • Price impact: large buys/sells move the price              ║
║    • Sell cooldown: must hold for MIN_HOLD_SECONDS              ║
║    • Daily buy limit: MAX_DAILY_BUYS per user                   ║
║    • Sandwich protection: can't buy+sell same stock same minute ║
╚══════════════════════════════════════════════════════════════════╝
"""

import logging
import random
from datetime import datetime, timedelta
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import get_player, update_player, col
from utils.guards import dm_only
from handlers.admin import has_admin_access

log = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
STOCKS_COL      = "stocks"
PORTFOLIO_COL   = "stock_portfolio"
HISTORY_COL     = "stock_history"
COOLDOWN_COL    = "stock_cooldowns"
LIQUIDITY_COL   = "liquidity_pools"

ITEMS_PER_PAGE      = 6          # stocks shown per page in /market
BUY_COOLDOWN_SECS   = 0          # No cooldown between buying the same stock (instant trades)
MIN_HOLD_SECONDS    = 0          # No hold requirement - can sell immediately
MAX_DAILY_BUYS      = 100        # Total buy actions per user per day (increased limit)
PRICE_IMPACT_PCT    = 0.002      # each share bought/sold moves price 0.2%
MAX_PRICE_IMPACT    = 0.15       # single trade can't move price more than 15%
CURRENCY_EMOJI      = "💎"
CURRENCY_NAME       = "Yen"

# AMM / Uniswap-style constants
AMM_FEE_PCT         = 0.003      # 0.3% fee on trades (Uniswap standard)
SLIPPAGE_TOLERANCE  = 0.05       # 5% max slippage warning threshold
MIN_LIQUIDITY       = 1000       # Minimum liquidity to prevent manipulation

# Default in-memory STOCKS dict (also mirrored in DB) — admins can expand via /addstock
STOCKS: dict[str, dict] = {}  # populated from DB at runtime
_stock_cache_time = 0  # timestamp when STOCKS was last loaded
_STOCK_CACHE_TTL = 10  # cache stocks for 10 seconds


# ══════════════════════════════════════════════════════════════════════════
#  DB HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _load_stocks() -> dict:
    """Pull all stocks from MongoDB into the STOCKS cache with TTL caching."""
    global STOCKS, _stock_cache_time
    import time
    
    # Return cached data if still valid
    if STOCKS and (time.time() - _stock_cache_time) < _STOCK_CACHE_TTL:
        return STOCKS
    
    # Cache miss or expired - fetch from DB
    docs = list(col(STOCKS_COL).find({}))
    STOCKS = {}
    for d in docs:
        ticker = d["ticker"]
        STOCKS[ticker] = {
            "ticker":    ticker,
            "name":      d.get("name", ticker),
            "emoji":     d.get("emoji", "📈"),
            "price":     float(d.get("price", 100)),
            "base_price":float(d.get("base_price", 100)),
            "supply":    int(d.get("supply", 1000)),
            "max_per_user": int(d.get("max_per_user", 50)),
            "change_pct":float(d.get("change_pct", 0.0)),
        }
    _stock_cache_time = time.time()
    return STOCKS


def _save_stock(ticker: str, data: dict):
    col(STOCKS_COL).update_one(
        {"ticker": ticker},
        {"$set": data},
        upsert=True
    )


# ─────────────────────────────────────────────────────────────────────────────
#  AMM / LIQUIDITY POOL HELPERS (Uniswap-style)
# ─────────────────────────────────────────────────────────────────────────────

def _get_liquidity_pool(ticker: str) -> Optional[dict]:
    """Get liquidity pool data for a stock. Auto-creates pool if missing."""
    pool = col(LIQUIDITY_COL).find_one({"ticker": ticker})
    
    # Auto-create default liquidity pool if none exists
    if not pool:
        stocks = _load_stocks()
        stock_data = stocks.get(ticker, {})
        # Create initial pool with default reserves based on stock price and supply
        default_yen_reserve = 100000  # 100k Yen initial liquidity
        default_stock_reserve = max(1000, stock_data.get("supply", 1000) // 10)  # 10% of supply
        _create_liquidity_pool(ticker, default_stock_reserve, default_yen_reserve)
        pool = col(LIQUIDITY_COL).find_one({"ticker": ticker})
    
    return pool


def _get_liquidity_status(pool: Optional[dict]) -> str:
    """Get human-readable liquidity status indicator."""
    if not pool:
        return "⚪ No Pool"
    
    total_value = pool.get("yen_reserve", 0)  # Simplified: use yen reserve as liquidity indicator
    
    if total_value >= 50000:
        return "⬆️ High (Stable)"
    elif total_value >= 20000:
        return "➡️ Medium"
    elif total_value >= 5000:
        return "⬇️ Low (Volatile)"
    else:
        return "⚠️ Very Low (Risky)"


def _create_liquidity_pool(ticker: str, stock_reserve: float, yen_reserve: float):
    """Create a new liquidity pool for a stock."""
    col(LIQUIDITY_COL).update_one(
        {"ticker": ticker},
        {
            "$set": {
                "ticker": ticker,
                "stock_reserve": stock_reserve,
                "yen_reserve": yen_reserve,
                "total_shares": 0,
                "created_at": datetime.utcnow()
            }
        },
        upsert=True
    )


def _calculate_slippage(ticker: str, trade_type: str, amount: float) -> tuple[float, float, float]:
    """
    Calculate price impact and slippage using Uniswap AMM formula.
    Returns: (effective_price, price_impact_pct, fee_amount)
    
    Formula: x * y = k (constant product)
    - For buy: new_stock_price = (yen_reserve + amount) / (stock_reserve - shares_bought)
    - For sell: new_stock_price = (yen_reserve - amount) / (stock_reserve + shares_sold)
    """
    pool = _get_liquidity_pool(ticker)
    if not pool:
        # No pool yet, use base stock price with no slippage
        stocks = _load_stocks()
        base_price = stocks.get(ticker, {}).get("price", 100)
        fee = amount * AMM_FEE_PCT
        return base_price, 0.0, fee
    
    stock_reserve = pool["stock_reserve"]
    yen_reserve = pool["yen_reserve"]
    
    if trade_type == "buy":
        # How many shares can be bought with 'amount' Yen?
        # (yen_reserve + amount) * (stock_reserve - shares) = yen_reserve * stock_reserve
        # Simplified: shares = stock_reserve - (k / (yen_reserve + amount))
        k = stock_reserve * yen_reserve
        new_yen = yen_reserve + amount
        new_stock = k / new_yen if new_yen > 0 else stock_reserve
        shares_received = stock_reserve - new_stock
        
        if shares_received <= 0:
            return 0, 1.0, amount * AMM_FEE_PCT
        
        effective_price = amount / shares_received
        base_price = yen_reserve / stock_reserve if stock_reserve > 0 else effective_price
        price_impact = (effective_price - base_price) / base_price if base_price > 0 else 0
    else:  # sell
        # How much Yen received for selling 'amount' shares?
        # (yen_reserve - yen_out) * (stock_reserve + amount) = k
        k = stock_reserve * yen_reserve
        new_stock = stock_reserve + amount
        new_yen = k / new_stock if new_stock > 0 else yen_reserve
        yen_received = yen_reserve - new_yen
        
        if yen_received <= 0:
            return 0, 1.0, 0
        
        effective_price = yen_received / amount
        base_price = yen_reserve / stock_reserve if stock_reserve > 0 else effective_price
        price_impact = (base_price - effective_price) / base_price if base_price > 0 else 0
    
    fee = amount * AMM_FEE_PCT if trade_type == "buy" else yen_received * AMM_FEE_PCT if trade_type == "sell" else 0
    return max(0.01, effective_price), max(0, price_impact), fee


def _add_liquidity(user_id: int, ticker: str, stock_amount: float, yen_amount: float) -> tuple[bool, str, float]:
    """
    Add liquidity to a pool and receive LP tokens.
    Returns: (success, message, lp_tokens_received)
    """
    pool = _get_liquidity_pool(ticker)
    
    if not pool:
        # Create initial pool
        _create_liquidity_pool(ticker, stock_amount, yen_amount)
        # Mint LP tokens to user (1:1 with initial liquidity)
        lp_tokens = min(stock_amount, yen_amount)
        portfolio_doc = col(PORTFOLIO_COL).find_one({"user_id": user_id}) or {}
        holdings = portfolio_doc.get("holdings", {})
        lp_key = f"LP_{ticker}"
        current_lp = holdings.get(lp_key, {}).get("shares", 0) if isinstance(holdings.get(lp_key), dict) else 0
        col(PORTFOLIO_COL).update_one(
            {"user_id": user_id},
            {"$set": {f"holdings.{lp_key}": {"shares": current_lp + lp_tokens, "avg_buy": yen_amount / lp_tokens if lp_tokens > 0 else 0}}},
            upsert=True
        )
        return True, f"✅ Created liquidity pool for {ticker}! Received {lp_tokens:.2f} LP tokens.", lp_tokens
    
    # Adding to existing pool
    total_shares = pool.get("total_shares", 0)
    stock_reserve = pool["stock_reserve"]
    yen_reserve = pool["yen_reserve"]
    
    # Calculate proportional LP tokens
    if total_shares > 0:
        lp_tokens = min(
            (stock_amount / stock_reserve) * total_shares,
            (yen_amount / yen_reserve) * total_shares
        )
    else:
        lp_tokens = min(stock_amount, yen_amount)
    
    # Update pool reserves
    col(LIQUIDITY_COL).update_one(
        {"ticker": ticker},
        {
            "$inc": {"stock_reserve": stock_amount, "yen_reserve": yen_amount, "total_shares": lp_tokens},
            "$set": {"last_updated": datetime.utcnow()}
        }
    )
    
    # Credit LP tokens to user
    lp_key = f"LP_{ticker}"
    portfolio_doc = col(PORTFOLIO_COL).find_one({"user_id": user_id}) or {}
    holdings = portfolio_doc.get("holdings", {})
    current_lp_data = holdings.get(lp_key, {})
    current_lp = current_lp_data.get("shares", 0) if isinstance(current_lp_data, dict) else 0
    current_avg = current_lp_data.get("avg_buy", 0) if isinstance(current_lp_data, dict) else 0
    
    # Calculate new average buy price for LP tokens
    total_value = (current_lp * current_avg) + (lp_tokens * (yen_amount / lp_tokens if lp_tokens > 0 else 0))
    new_avg = total_value / (current_lp + lp_tokens) if (current_lp + lp_tokens) > 0 else 0
    
    col(PORTFOLIO_COL).update_one(
        {"user_id": user_id},
        {"$set": {f"holdings.{lp_key}": {"shares": current_lp + lp_tokens, "avg_buy": new_avg}}},
        upsert=True
    )
    
    return True, f"✅ Added liquidity to {ticker}! Received {lp_tokens:.2f} LP tokens.", lp_tokens


def _remove_liquidity(user_id: int, ticker: str, lp_amount: float) -> tuple[bool, str, float, float]:
    """
    Remove liquidity from a pool by burning LP tokens.
    Returns: (success, message, stock_returned, yen_returned)
    """
    pool = _get_liquidity_pool(ticker)
    if not pool:
        return False, "❌ No liquidity pool found for this stock.", 0, 0
    
    total_shares = pool.get("total_shares", 0)
    if total_shares <= 0:
        return False, "❌ No liquidity in this pool.", 0, 0
    
    if lp_amount > total_shares:
        return False, f"❌ You can't remove more liquidity than exists ({total_shares:.2f} LP tokens available).", 0, 0
    
    # Calculate share of reserves
    share = lp_amount / total_shares
    stock_returned = pool["stock_reserve"] * share
    yen_returned = pool["yen_reserve"] * share
    
    # Update pool
    col(LIQUIDITY_COL).update_one(
        {"ticker": ticker},
        {
            "$inc": {"stock_reserve": -stock_returned, "yen_reserve": -yen_returned, "total_shares": -lp_amount},
            "$set": {"last_updated": datetime.utcnow()}
        }
    )
    
    # Burn LP tokens from user
    lp_key = f"LP_{ticker}"
    portfolio_doc = col(PORTFOLIO_COL).find_one({"user_id": user_id}) or {}
    holdings = portfolio_doc.get("holdings", {})
    current_lp_data = holdings.get(lp_key, {})
    current_lp = current_lp_data.get("shares", 0) if isinstance(current_lp_data, dict) else 0
    
    if current_lp < lp_amount:
        return False, f"❌ Insufficient LP tokens. You have {current_lp:.2f}.", 0, 0
    
    new_lp = current_lp - lp_amount
    if new_lp <= 0:
        col(PORTFOLIO_COL).update_one(
            {"user_id": user_id},
            {"$unset": {f"holdings.{lp_key}": ""}},
            upsert=True
        )
    else:
        col(PORTFOLIO_COL).update_one(
            {"user_id": user_id},
            {"$set": {f"holdings.{lp_key}": {"shares": new_lp, "avg_buy": current_lp_data.get("avg_buy", 0)}}},
            upsert=True
        )
    
    return True, f"✅ Removed liquidity from {ticker}! Received {stock_returned:.2f} shares + {yen_returned:.2f} Yen.", stock_returned, yen_returned


def _get_portfolio(user_id: int) -> dict:
    doc = col(PORTFOLIO_COL).find_one({"user_id": user_id}) or {}
    return doc.get("holdings", {})


def _set_holding(user_id: int, ticker: str, shares: int, avg_buy: float):
    if shares <= 0:
        col(PORTFOLIO_COL).update_one(
            {"user_id": user_id},
            {"$unset": {f"holdings.{ticker}": ""}},
            upsert=True,
        )
    else:
        col(PORTFOLIO_COL).update_one(
            {"user_id": user_id},
            {"$set": {f"holdings.{ticker}": {"shares": shares, "avg_buy": avg_buy}}},
            upsert=True,
        )


def _log_trade(user_id: int, ticker: str, action: str, shares: int, price: float, total: int):
    col(HISTORY_COL).insert_one({
        "user_id":  user_id,
        "ticker":   ticker,
        "action":   action,
        "shares":   shares,
        "price":    price,
        "total":    total,
        "at":       datetime.utcnow(),
    })


def log_stock_event(event: str, data: dict = None):
    col("stock_events").insert_one({
        "event": event,
        "data":  data or {},
        "at":    datetime.utcnow(),
    })
    log.info("[STOCK] %s | %s", event, data)


# ══════════════════════════════════════════════════════════════════════════
#  ANTI-EXPLOIT GUARDS
# ══════════════════════════════════════════════════════════════════════════

# In-memory cache for cooldowns to reduce DB hits
_cooldown_cache: dict[tuple[int, str, str], datetime] = {}

def _check_buy_cooldown(user_id: int, ticker: str) -> Optional[int]:
    """Returns seconds remaining on cooldown, or None if clear."""
    cache_key = (user_id, ticker, "buy")
    
    # Check cache first
    if cache_key in _cooldown_cache:
        doc_at = _cooldown_cache[cache_key]
        elapsed = (datetime.utcnow() - doc_at).total_seconds()
        remaining = BUY_COOLDOWN_SECS - elapsed
        if remaining > 0:
            return int(remaining)
        else:
            # Cache expired, remove it
            _cooldown_cache.pop(cache_key, None)
            return None
    
    # Cache miss - fetch from DB
    doc = col(COOLDOWN_COL).find_one({"user_id": user_id, "ticker": ticker, "type": "buy"})
    if not doc:
        return None
    elapsed = (datetime.utcnow() - doc["at"]).total_seconds()
    remaining = BUY_COOLDOWN_SECS - elapsed
    if remaining > 0:
        # Cache the result
        _cooldown_cache[cache_key] = doc["at"]
        return int(remaining)
    return None


def _set_buy_cooldown(user_id: int, ticker: str):
    now = datetime.utcnow()
    col(COOLDOWN_COL).update_one(
        {"user_id": user_id, "ticker": ticker, "type": "buy"},
        {"$set": {"at": now}},
        upsert=True,
    )
    # Update cache
    _cooldown_cache[(user_id, ticker, "buy")] = now


def _check_sell_cooldown(user_id: int, ticker: str) -> Optional[int]:
    """Returns seconds until user can sell (must hold MIN_HOLD_SECONDS)."""
    cache_key = (user_id, ticker, "last_buy_time")
    
    # Check cache first
    if cache_key in _cooldown_cache:
        doc_at = _cooldown_cache[cache_key]
        elapsed = (datetime.utcnow() - doc_at).total_seconds()
        remaining = MIN_HOLD_SECONDS - elapsed
        if remaining > 0:
            return int(remaining)
        else:
            # Cache expired, remove it
            _cooldown_cache.pop(cache_key, None)
            return None
    
    # Cache miss - fetch from DB
    doc = col(COOLDOWN_COL).find_one({"user_id": user_id, "ticker": ticker, "type": "last_buy_time"})
    if not doc:
        return None
    elapsed = (datetime.utcnow() - doc["at"]).total_seconds()
    remaining = MIN_HOLD_SECONDS - elapsed
    if remaining > 0:
        # Cache the result
        _cooldown_cache[cache_key] = doc["at"]
        return int(remaining)
    return None


def _set_last_buy_time(user_id: int, ticker: str):
    now = datetime.utcnow()
    col(COOLDOWN_COL).update_one(
        {"user_id": user_id, "ticker": ticker, "type": "last_buy_time"},
        {"$set": {"at": now}},
        upsert=True,
    )
    # Update cache
    _cooldown_cache[(user_id, ticker, "last_buy_time")] = now


def _check_daily_limit(user_id: int) -> bool:
    """Returns True if user has NOT exceeded daily buy limit."""
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count = col(HISTORY_COL).count_documents({
        "user_id": user_id,
        "action": "buy",
        "at": {"$gte": today_start},
    })
    return count < MAX_DAILY_BUYS


def _check_sandwich(user_id: int, ticker: str) -> bool:
    """Returns True if user bought this stock in the last 60s (sandwich block)."""
    one_min_ago = datetime.utcnow() - timedelta(seconds=60)
    count = col(HISTORY_COL).count_documents({
        "user_id": user_id,
        "ticker": ticker,
        "action": "buy",
        "at": {"$gte": one_min_ago},
    })
    return count > 0


# ══════════════════════════════════════════════════════════════════════════
#  PRICE ENGINE
# ══════════════════════════════════════════════════════════════════════════

def _apply_price_impact(ticker: str, shares: int, direction: str) -> float:
    """Apply market impact after a trade. Returns new price."""
    stocks = _load_stocks()
    if ticker not in stocks:
        return 0.0
    stock = stocks[ticker]
    impact = min(shares * PRICE_IMPACT_PCT, MAX_PRICE_IMPACT)
    if direction == "buy":
        new_price = stock["price"] * (1 + impact)
    else:
        new_price = stock["price"] * (1 - impact)
    new_price = max(1.0, round(new_price, 2))
    old_price  = stock["price"]
    change_pct = ((new_price - stock["base_price"]) / stock["base_price"]) * 100
    _save_stock(ticker, {"price": new_price, "change_pct": round(change_pct, 2)})
    log.info("[STOCK] %s price impact %s: %.2f → %.2f", ticker, direction, old_price, new_price)
    return new_price


def update_stock_prices():
    """Called by scheduler every 5 min — random drift to simulate market."""
    stocks = _load_stocks()
    for ticker, stock in stocks.items():
        drift = random.uniform(-0.04, 0.045)  # ±4% max per tick
        new_price = max(1.0, round(stock["price"] * (1 + drift), 2))
        base = stock["base_price"]
        # Mean-revert toward base slowly so prices don't runaway
        revert = (base - new_price) * 0.02
        new_price = round(max(1.0, new_price + revert), 2)
        change_pct = ((new_price - base) / base) * 100
        _save_stock(ticker, {"price": new_price, "change_pct": round(change_pct, 2)})
    log.info("[STOCK] Prices updated for %d stocks.", len(stocks))


def nudge_price(ticker: str, pct: float):
    """Admin: manually move one stock by ±pct percent."""
    stocks = _load_stocks()
    if ticker not in stocks:
        return
    stock = stocks[ticker]
    new_price = max(1.0, round(stock["price"] * (1 + pct / 100), 2))
    change_pct = ((new_price - stock["base_price"]) / stock["base_price"]) * 100
    _save_stock(ticker, {"price": new_price, "change_pct": round(change_pct, 2)})
    log.info("[STOCK] Admin nudge %s by %.1f%% → %.2f", ticker, pct, new_price)


# ══════════════════════════════════════════════════════════════════════════
#  UI HELPERS
# ══════════════════════════════════════════════════════════════════════════

def _change_arrow(pct: float) -> str:
    if pct > 5:   return "🚀"
    if pct > 0:   return "📈"
    if pct < -5:  return "💀"
    if pct < 0:   return "📉"
    return "➖"


def _change_str(pct: float) -> str:
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def _market_page_text(stocks: dict, page: int) -> tuple[str, InlineKeyboardMarkup]:
    """Build paginated market listing."""
    items   = list(stocks.values())
    total   = len(items)
    pages   = max(1, (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)
    page    = max(0, min(page, pages - 1))
    start   = page * ITEMS_PER_PAGE
    chunk   = items[start:start + ITEMS_PER_PAGE]

    lines = [
        "⚔️ *DEMON SLAYER STOCK EXCHANGE*",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 *{total} Companies Listed*  |  🕐 Updates every 5 min",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    for s in chunk:
        arrow  = _change_arrow(s["change_pct"])
        chg    = _change_str(s["change_pct"])
        lines.append(
            f"{s['emoji']} *{s['name']}* `[{s['ticker']}]`\n"
            f"   {CURRENCY_EMOJI} *{s['price']:,.2f}* {CURRENCY_NAME}  "
            f"{arrow} `{chg}`  📦 {s['supply']:,} left\n"
        )
    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📄 Page *{page+1}*/*{pages}*  |  Tap a stock to trade",
    ]

    # Build keyboard: stock buttons
    kb = []
    for s in chunk:
        arrow = _change_arrow(s["change_pct"])
        kb.append([InlineKeyboardButton(
            f"{s['emoji']} {s['ticker']}  {CURRENCY_EMOJI}{s['price']:,.0f}  {arrow}",
            callback_data=f"stock_view_{s['ticker']}"
        )])

    # Pagination row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"market_page_{page-1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"market_page_{page+1}"))
    if nav:
        kb.append(nav)
    kb.append([InlineKeyboardButton("💼 My Portfolio", callback_data="stock_portfolio")])

    return "\n".join(lines), InlineKeyboardMarkup(kb)


def _stock_detail_text(ticker: str, user_id: int) -> tuple[str, InlineKeyboardMarkup]:
    """Detailed view of one stock with buy/sell options."""
    stocks = _load_stocks()
    if ticker not in stocks:
        return "❌ Stock not found.", InlineKeyboardMarkup([[]])
    s = stocks[ticker]
    arrow = _change_arrow(s["change_pct"])
    chg   = _change_str(s["change_pct"])

    holdings = _get_portfolio(user_id)
    held     = holdings.get(ticker, {})
    held_qty = held.get("shares", 0)
    avg_buy  = held.get("avg_buy", 0.0)
    pnl      = (s["price"] - avg_buy) * held_qty if held_qty else 0.0
    pnl_sign = "+" if pnl >= 0 else ""

    lines = [
        f"{'━'*26}",
        f"{s['emoji']} *{s['name']}* `[{s['ticker']}]`",
        f"{'━'*26}",
        f"{CURRENCY_EMOJI} Price: *{s['price']:,.2f}* {CURRENCY_NAME}",
        f"{arrow} Change: *{chg}* (from base {s['base_price']:,.0f})",
        f"📦 Available supply: *{s['supply']:,}*",
        f"🔒 Max per user: *{s['max_per_user']}* shares",
        "",
        f"💧 Liquidity Pool: {_get_liquidity_status(_get_liquidity_pool(ticker))}",
        "",
        f"*Your Holdings:*",
        f"  Shares: *{held_qty}*"
        + (f"\n  Avg buy: *{avg_buy:.2f}* {CURRENCY_NAME}"
           f"\n  P/L: *{pnl_sign}{pnl:,.0f}* {CURRENCY_NAME}"
           if held_qty else ""),
        f"{'━'*26}",
    ]

    remaining = s["max_per_user"] - held_qty
    kb = []

    if s["supply"] > 0 and remaining > 0:
        buy_options = []
        for qty in [1, 5, 10]:
            if qty <= remaining and qty <= s["supply"]:
                cost = int(s["price"] * qty)
                buy_options.append(InlineKeyboardButton(
                    f"Buy {qty}  ({CURRENCY_EMOJI}{cost:,})",
                    callback_data=f"stock_buy_{ticker}_{qty}"
                ))
        if buy_options:
            kb.append(buy_options)

    if held_qty > 0:
        sell_options = []
        for qty in [1, held_qty // 2, held_qty]:
            qty = int(qty)
            if qty > 0:
                revenue = int(s["price"] * qty)
                sell_options.append(InlineKeyboardButton(
                    f"Sell {qty}  ({CURRENCY_EMOJI}{revenue:,})",
                    callback_data=f"stock_sell_{ticker}_{qty}"
                ))
        # deduplicate
        seen = set()
        sell_options = [b for b in sell_options if not (b.callback_data in seen or seen.add(b.callback_data))]
        if sell_options:
            kb.append(sell_options)

    kb.append([InlineKeyboardButton("◀ Back to Market", callback_data="stock_back")])
    return "\n".join(lines), InlineKeyboardMarkup(kb)


# ══════════════════════════════════════════════════════════════════════════
#  PLAYER COMMANDS
# ══════════════════════════════════════════════════════════════════════════

@dm_only
async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return
    stocks = _load_stocks()
    if not stocks:
        await update.message.reply_text(
            "📊 *DEMON SLAYER STOCK EXCHANGE*\n\n"
            "_No stocks are listed yet._\n"
            "_Ask an admin to add some with_ `/addstock`.",
            parse_mode="Markdown"
        )
        return
    text, kb = _market_page_text(stocks, 0)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)


@dm_only
async def stockbuy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Alias to open market for buying stocks."""
    await market(update, context)


@dm_only
async def stocksell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open portfolio for selling."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return
    holdings = _get_portfolio(user_id)
    if not holdings:
        await update.message.reply_text(
            "💼 *Your Portfolio*\n\n_You own no stocks yet._\n\nUse /market to browse.",
            parse_mode="Markdown"
        )
        return
    stocks = _load_stocks()
    lines = ["💼 *YOUR PORTFOLIO — Tap to sell*", "━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    kb = []
    total_value = 0
    for ticker, h in holdings.items():
        # Skip LP tokens in regular portfolio view
        if ticker.startswith("LP_"):
            continue
        # Handle both dict and legacy int formats
        if not isinstance(h, dict):
            continue
        s = stocks.get(ticker, {})
        cur_price = s.get("price", 0)
        val = h["shares"] * cur_price
        total_value += val
        pnl = (cur_price - h["avg_buy"]) * h["shares"]
        pnl_sign = "+" if pnl >= 0 else ""
        arrow = _change_arrow(s.get("change_pct", 0))
        lines.append(
            f"{s.get('emoji','📊')} *{ticker}* x{h['shares']} @ {CURRENCY_EMOJI}{cur_price:,.0f} {arrow}\n"
            f"   Value: *{val:,.0f}*  P/L: *{pnl_sign}{pnl:,.0f}* {CURRENCY_NAME}\n"
        )
        kb.append([InlineKeyboardButton(
            f"📉 Sell {ticker} ({h['shares']} shares)",
            callback_data=f"stock_view_{ticker}"
        )])
    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📊 Total value: *{total_value:,.0f}* {CURRENCY_NAME}",
        f"💰 Wallet: *{player['yen']:,}* {CURRENCY_NAME}",
    ]
    kb.append([InlineKeyboardButton("📊 View Market", callback_data="stock_back")])
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(kb)
    )


@dm_only
async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ No character found.")
        return
    holdings = _get_portfolio(user_id)
    stocks = _load_stocks()
    if not holdings:
        await update.message.reply_text(
            "💼 *YOUR PORTFOLIO*\n\n_No holdings yet._\n\nUse /market to start investing.",
            parse_mode="Markdown"
        )
        return
    lines = ["💼 *YOUR PORTFOLIO*", "━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    total_invested = 0
    total_value    = 0
    for ticker, h in holdings.items():
        # Skip LP tokens in regular portfolio view
        if ticker.startswith("LP_"):
            continue
        # Handle both dict and legacy int formats
        if not isinstance(h, dict):
            continue
        s = stocks.get(ticker, {})
        cur = s.get("price", 0)
        invested = h["avg_buy"] * h["shares"]
        val  = cur * h["shares"]
        pnl  = val - invested
        pnl_sign = "+" if pnl >= 0 else ""
        arrow = _change_arrow(s.get("change_pct", 0))
        total_invested += invested
        total_value    += val
        lines.append(
            f"{s.get('emoji','📊')} *{ticker}* — *{h['shares']}* shares\n"
            f"   Avg buy: *{h['avg_buy']:.2f}*  Now: *{cur:.2f}* {arrow}\n"
            f"   Value: *{val:,.0f}*  P/L: *{pnl_sign}{pnl:,.0f}* {CURRENCY_NAME}\n"
        )
    total_pnl      = total_value - total_invested
    total_pnl_sign = "+" if total_pnl >= 0 else ""
    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📈 Total invested: *{total_invested:,.0f}* {CURRENCY_NAME}",
        f"💰 Portfolio value: *{total_value:,.0f}* {CURRENCY_NAME}",
        f"{'⬆️' if total_pnl >= 0 else '⬇️'} Net P/L: *{total_pnl_sign}{total_pnl:,.0f}* {CURRENCY_NAME}",
        f"💵 Wallet: *{player['yen']:,}* {CURRENCY_NAME}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@dm_only
async def stockhistory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    records = list(col(HISTORY_COL).find({"user_id": user_id}).sort("at", -1).limit(20))
    if not records:
        await update.message.reply_text("📜 No trade history yet.", parse_mode="Markdown")
        return
    lines = ["📜 *TRADE HISTORY* (last 20)", "━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    for r in records:
        dt  = r["at"].strftime("%m/%d %H:%M")
        act = "🟢 BUY " if r["action"] == "buy" else "🔴 SELL"
        lines.append(
            f"`{dt}` {act} *{r['ticker']}* x{r['shares']} @ {r['price']:.2f} = *{r['total']:,}* {CURRENCY_NAME}"
        )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════
#  CALLBACK HANDLERS
# ══════════════════════════════════════════════════════════════════════════

async def market_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    page = int(query.data.split("_")[-1])
    stocks = _load_stocks()
    text, kb = _market_page_text(stocks, page)
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass


async def stock_view_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()
    ticker = query.data.replace("stock_view_", "")
    text, kb = _stock_detail_text(ticker, user_id)
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass


async def stock_back_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    stocks = _load_stocks()
    text, kb = _market_page_text(stocks, 0)
    try:
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass


async def stock_buy_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    # Parse: stock_buy_<TICKER>_<QTY>
    parts  = query.data.split("_")
    # stock_buy_TICKER_QTY  →  parts = ['stock', 'buy', 'TICKER', 'QTY']
    if len(parts) < 4:
        await query.answer("❌ Invalid action.", show_alert=True)
        return

    ticker = parts[2]
    try:
        qty = int(parts[3])
    except ValueError:
        await query.answer("❌ Invalid quantity.", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await query.answer("❌ No character found.", show_alert=True)
        return

    stocks = _load_stocks()
    if ticker not in stocks:
        await query.answer("❌ Stock no longer exists.", show_alert=True)
        return

    stock = stocks[ticker]

    # ── Anti-exploit checks ──────────────────────────────────────────
    # 1) Buy cooldown
    cd = _check_buy_cooldown(user_id, ticker)
    if cd:
        await query.answer(f"⏳ Buy cooldown: {cd}s remaining.", show_alert=True)
        return

    # 2) Daily buy limit
    if not _check_daily_limit(user_id):
        await query.answer(f"🚫 Daily buy limit ({MAX_DAILY_BUYS} trades) reached. Come back tomorrow.", show_alert=True)
        return

    # 3) Supply check
    if stock["supply"] < qty:
        await query.answer(f"❌ Only {stock['supply']} shares available.", show_alert=True)
        return

    # 4) Per-user max
    holdings = _get_portfolio(user_id)
    held     = holdings.get(ticker, {})
    held_qty = held.get("shares", 0)
    if held_qty + qty > stock["max_per_user"]:
        await query.answer(
            f"🚫 Max {stock['max_per_user']} shares of {ticker} per user. You own {held_qty}.",
            show_alert=True
        )
        return

    # 5) Wallet check
    total_cost = int(stock["price"] * qty)
    if player["yen"] < total_cost:
        await query.answer(
            f"❌ Need {total_cost:,} {CURRENCY_NAME}. You have {player['yen']:,}.",
            show_alert=True
        )
        return

    # ── Execute buy ──────────────────────────────────────────────────
    # Weighted average buy price
    new_avg = ((held.get("avg_buy", 0) * held_qty) + (stock["price"] * qty)) / (held_qty + qty)
    _set_holding(user_id, ticker, held_qty + qty, round(new_avg, 4))

    # Deduct yen
    update_player(user_id, yen=player["yen"] - total_cost)

    # Reduce supply
    _save_stock(ticker, {"supply": stock["supply"] - qty})

    # Price impact (buying pushes price up)
    new_price = _apply_price_impact(ticker, qty, "buy")

    # Cooldown + last-buy-time
    _set_buy_cooldown(user_id, ticker)
    _set_last_buy_time(user_id, ticker)

    # Log
    _log_trade(user_id, ticker, "buy", qty, stock["price"], total_cost)
    log_stock_event("buy", {"user_id": user_id, "ticker": ticker, "qty": qty, "price": stock["price"]})

    # Refresh detail view
    text, kb = _stock_detail_text(ticker, user_id)
    stocks_fresh = _load_stocks()
    try:
        await query.edit_message_text(
            f"✅ *Bought {qty}x {ticker}* for *{total_cost:,}* {CURRENCY_NAME}!\n\n" + text,
            parse_mode="Markdown",
            reply_markup=kb
        )
    except Exception:
        pass


async def stock_sell_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask for confirmation before selling."""
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    parts = query.data.split("_")  # stock_sell_TICKER_QTY
    if len(parts) < 4:
        await query.answer("❌ Invalid action.", show_alert=True)
        return

    ticker = parts[2]
    try:
        qty = int(parts[3])
    except ValueError:
        await query.answer("❌ Invalid quantity.", show_alert=True)
        return

    stocks = _load_stocks()
    if ticker not in stocks:
        await query.answer("❌ Stock not found.", show_alert=True)
        return

    stock = stocks[ticker]
    revenue = int(stock["price"] * qty)

    # Sell cooldown check (show in confirm step)
    cd = _check_sell_cooldown(user_id, ticker)
    cd_warning = f"\n⏳ _Hold requirement: {cd}s remaining_" if cd else ""

    confirm_text = (
        f"⚠️ *Confirm Sell*\n\n"
        f"Sell *{qty}x {stock['emoji']} {ticker}*?\n"
        f"You'll receive: *{revenue:,}* {CURRENCY_NAME}"
        f"{cd_warning}"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm Sell", callback_data=f"stock_sell_confirm_{ticker}_{qty}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"stock_view_{ticker}"),
        ]
    ])
    try:
        await query.edit_message_text(confirm_text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        pass


async def stock_sell_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    parts = query.data.split("_")  # stock_sell_confirm_TICKER_QTY
    if len(parts) < 5:
        await query.answer("❌ Invalid action.", show_alert=True)
        return

    ticker = parts[3]
    try:
        qty = int(parts[4])
    except ValueError:
        await query.answer("❌ Invalid quantity.", show_alert=True)
        return

    player = get_player(user_id)
    if not player:
        await query.answer("❌ No character found.", show_alert=True)
        return

    stocks = _load_stocks()
    if ticker not in stocks:
        await query.answer("❌ Stock not found.", show_alert=True)
        return

    stock = stocks[ticker]

    # ── Anti-exploit: hold time ───────────────────────────────────────
    cd = _check_sell_cooldown(user_id, ticker)
    if cd:
        await query.answer(
            f"⏳ Must hold for {MIN_HOLD_SECONDS//60}min before selling. {cd}s left.",
            show_alert=True
        )
        return

    # ── Anti-exploit: sandwich guard ─────────────────────────────────
    if _check_sandwich(user_id, ticker):
        await query.answer(
            "🚫 Sandwich trading detected! Wait 60s after buying before selling.",
            show_alert=True
        )
        return

    # ── Holdings check ────────────────────────────────────────────────
    holdings = _get_portfolio(user_id)
    held     = holdings.get(ticker, {})
    held_qty = held.get("shares", 0)
    if held_qty < qty:
        await query.answer(f"❌ You only own {held_qty} shares of {ticker}.", show_alert=True)
        return

    # ── Execute sell ──────────────────────────────────────────────────
    revenue = int(stock["price"] * qty)
    update_player(user_id, yen=player["yen"] + revenue)

    new_qty = held_qty - qty
    _set_holding(user_id, ticker, new_qty, held.get("avg_buy", 0))

    # Restore supply
    _save_stock(ticker, {"supply": stock["supply"] + qty})

    # Price impact (selling pushes price down)
    _apply_price_impact(ticker, qty, "sell")

    # Log
    _log_trade(user_id, ticker, "sell", qty, stock["price"], revenue)
    log_stock_event("sell", {"user_id": user_id, "ticker": ticker, "qty": qty, "price": stock["price"]})

    text, kb = _stock_detail_text(ticker, user_id)
    try:
        await query.edit_message_text(
            f"✅ *Sold {qty}x {ticker}* for *{revenue:,}* {CURRENCY_NAME}!\n\n" + text,
            parse_mode="Markdown",
            reply_markup=kb
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════
#  ADMIN COMMANDS
# ══════════════════════════════════════════════════════════════════════════

async def addstock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /addstock <TICKER> <Full Name> <price> <supply> [emoji] [max_per_user]
    Example: /addstock TANJ Tanjiro_Corp 500 1000 🗡️ 20
    """
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    args = context.args or []
    if len(args) < 4:
        await update.message.reply_text(
            "*Usage:* `/addstock TICKER Name price supply [emoji] [max_per_user]`\n\n"
            "Example:\n`/addstock TANJ Tanjiro_Corp 500 1000 🗡️ 20`\n\n"
            "• Use underscores in name for spaces\n"
            "• max\\_per\\_user defaults to 50",
            parse_mode="Markdown"
        )
        return

    ticker = args[0].upper()
    name   = args[1].replace("_", " ")
    try:
        price  = float(args[2])
        supply = int(args[3])
    except ValueError:
        await update.message.reply_text("❌ Price and supply must be numbers.")
        return

    emoji        = args[4] if len(args) > 4 else "📊"
    max_per_user = int(args[5]) if len(args) > 5 else 50

    if supply <= 0 or price <= 0:
        await update.message.reply_text("❌ Price and supply must be > 0.")
        return
    if len(ticker) > 8:
        await update.message.reply_text("❌ Ticker must be ≤ 8 characters.")
        return

    data = {
        "ticker":       ticker,
        "name":         name,
        "emoji":        emoji,
        "price":        round(price, 2),
        "base_price":   round(price, 2),
        "supply":       supply,
        "max_per_user": max_per_user,
        "change_pct":   0.0,
        "added_by":     user_id,
        "added_at":     datetime.utcnow(),
    }
    _save_stock(ticker, data)
    _load_stocks()
    log_stock_event("addstock", {"ticker": ticker, "by": user_id})

    await update.message.reply_text(
        f"✅ *Stock Added!*\n\n"
        f"{emoji} *{name}* `[{ticker}]`\n"
        f"{CURRENCY_EMOJI} Price: *{price:,.2f}* {CURRENCY_NAME}\n"
        f"📦 Supply: *{supply:,}*\n"
        f"🔒 Max/user: *{max_per_user}*",
        parse_mode="Markdown"
    )


async def removestock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /removestock <TICKER>
    """
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text("Usage: `/removestock TICKER`", parse_mode="Markdown")
        return

    ticker = args[0].upper()
    result = col(STOCKS_COL).delete_one({"ticker": ticker})
    if result.deleted_count:
        _load_stocks()
        log_stock_event("removestock", {"ticker": ticker, "by": user_id})
        await update.message.reply_text(f"✅ Stock *{ticker}* removed.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ No stock with ticker *{ticker}*.", parse_mode="Markdown")


async def marketcrash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: crash all stock prices by 10-40%."""
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    stocks = _load_stocks()
    if not stocks:
        await update.message.reply_text("No stocks to crash.")
        return

    for ticker, stock in stocks.items():
        drop = random.uniform(0.10, 0.40)
        new_price = max(1.0, round(stock["price"] * (1 - drop), 2))
        change_pct = ((new_price - stock["base_price"]) / stock["base_price"]) * 100
        _save_stock(ticker, {"price": new_price, "change_pct": round(change_pct, 2)})

    _load_stocks()
    log_stock_event("market_crash", {"by": user_id})
    await update.message.reply_text(
        "💥 *MARKET CRASH!*\n\nAll stock prices have dropped 10-40%! 📉",
        parse_mode="Markdown"
    )


async def marketboom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: boom all stock prices by 10-35%."""
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    stocks = _load_stocks()
    if not stocks:
        await update.message.reply_text("No stocks to boom.")
        return

    for ticker, stock in stocks.items():
        boost = random.uniform(0.10, 0.35)
        new_price = round(stock["price"] * (1 + boost), 2)
        change_pct = ((new_price - stock["base_price"]) / stock["base_price"]) * 100
        _save_stock(ticker, {"price": new_price, "change_pct": round(change_pct, 2)})

    _load_stocks()
    log_stock_event("market_boom", {"by": user_id})
    await update.message.reply_text(
        "🚀 *MARKET BOOM!*\n\nAll stock prices surged 10-35%! 📈",
        parse_mode="Markdown"
    )


async def marketreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin: reset all prices to their base_price."""
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    stocks = _load_stocks()
    for ticker, stock in stocks.items():
        _save_stock(ticker, {"price": stock["base_price"], "change_pct": 0.0})

    _load_stocks()
    log_stock_event("market_reset", {"by": user_id})
    await update.message.reply_text(
        "🔄 *Market Reset* — All prices restored to base values.",
        parse_mode="Markdown"
    )


# Note: nudge_price is already defined above as a utility function.
# Bot registers it as /nudgeprice via a wrapper:

async def nudgeprice_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    /nudgeprice <TICKER> <±percent>
    Example: /nudgeprice TANJ +15   or   /nudgeprice TANJ -10
    """
    user_id = update.effective_user.id
    if not has_admin_access(user_id):
        await update.message.reply_text("❌ Admin only.")
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "Usage: `/nudgeprice TICKER ±percent`\n\nExample: `/nudgeprice TANJ +15`",
            parse_mode="Markdown"
        )
        return

    ticker = args[0].upper()
    try:
        pct = float(args[1].replace("+", ""))
    except ValueError:
        await update.message.reply_text("❌ Invalid percent value.")
        return

    stocks = _load_stocks()
    if ticker not in stocks:
        await update.message.reply_text(f"❌ No stock with ticker *{ticker}*.", parse_mode="Markdown")
        return

    old_price = stocks[ticker]["price"]
    nudge_price(ticker, pct)
    new_stocks = _load_stocks()
    new_price  = new_stocks.get(ticker, {}).get("price", old_price)
    sign       = "+" if pct >= 0 else ""
    log_stock_event("nudge_price", {"ticker": ticker, "pct": pct, "by": user_id})

    await update.message.reply_text(
        f"✅ *{ticker}* nudged {sign}{pct:.1f}%\n"
        f"Price: *{old_price:.2f}* → *{new_price:.2f}* {CURRENCY_NAME}",
        parse_mode="Markdown"
    )


# ── Portfolio callback (from inline button) ────────────────────────────────
async def stock_portfolio_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query   = update.callback_query
    user_id = query.from_user.id
    await query.answer()

    player   = get_player(user_id)
    holdings = _get_portfolio(user_id)
    stocks   = _load_stocks()

    if not holdings:
        try:
            await query.edit_message_text(
                "💼 *YOUR PORTFOLIO*\n\n_No holdings yet._\n\nUse the buttons to buy stocks.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("◀ Back to Market", callback_data="stock_back")
                ]])
            )
        except Exception:
            pass
        return

    lines = ["💼 *YOUR PORTFOLIO*", "━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
    total_value = 0
    for ticker, h in holdings.items():
        # Skip LP tokens in regular portfolio view
        if ticker.startswith("LP_"):
            continue
        # Handle both dict and legacy int formats
        if not isinstance(h, dict):
            continue
        s = stocks.get(ticker, {})
        cur  = s.get("price", 0)
        val  = h["shares"] * cur
        pnl  = (cur - h["avg_buy"]) * h["shares"]
        sign = "+" if pnl >= 0 else ""
        arrow = _change_arrow(s.get("change_pct", 0))
        total_value += val
        lines.append(
            f"{s.get('emoji','📊')} *{ticker}* x{h['shares']} {arrow}\n"
            f"   Value: *{val:,.0f}*  P/L: *{sign}{pnl:,.0f}* {CURRENCY_NAME}\n"
        )
    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 Total: *{total_value:,.0f}* {CURRENCY_NAME}",
        f"💵 Wallet: *{player['yen']:,}* {CURRENCY_NAME}",
    ]
    try:
        await query.edit_message_text(
            "\n".join(lines),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("◀ Back to Market", callback_data="stock_back")
            ]])
        )
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════════════════
#  AMM / LIQUIDITY POOL COMMANDS
# ══════════════════════════════════════════════════════════════════════════

async def addliquidity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Add liquidity to a stock pool and earn LP tokens.
    Usage: /addliquidity <ticker> <stock_amount> <yen_amount>
    """
    user_id = update.effective_user.id
    player = get_player(user_id)
    
    if len(context.args) != 3:
        await update.message.reply_text(
            "❌ *Usage:* `/addliquidity <ticker> <stock_amount> <yen_amount>`\n\n"
            "Example: `/addliquidity AAPL 100 50000`\n"
            "This adds 100 shares of AAPL + 50,000 Yen to the liquidity pool.",
            parse_mode="Markdown"
        )
        return
    
    ticker = context.args[0].upper()
    try:
        stock_amount = float(context.args[1])
        yen_amount = int(context.args[2])
    except ValueError:
        await update.message.reply_text("❌ Invalid amounts. Please use numbers.")
        return
    
    if stock_amount <= 0 or yen_amount <= 0:
        await update.message.reply_text("❌ Amounts must be positive.")
        return
    
    # Check if user has enough stocks
    portfolio = _get_portfolio(user_id)
    current_shares = portfolio.get(ticker, {}).get("shares", 0) if isinstance(portfolio.get(ticker), dict) else 0
    
    if current_shares < stock_amount:
        await update.message.reply_text(
            f"❌ Insufficient {ticker} shares.\n"
            f"You have: {current_shares}\nRequired: {stock_amount}"
        )
        return
    
    # Check if user has enough Yen
    if player["yen"] < yen_amount:
        await update.message.reply_text(
            f"❌ Insufficient Yen.\n"
            f"You have: {player['yen']:,}\nRequired: {yen_amount:,}"
        )
        return
    
    # Deduct from user
    col(PORTFOLIO_COL).update_one(
        {"user_id": user_id},
        {"$set": {f"holdings.{ticker}.shares": current_shares - stock_amount}}
    )
    update_player(user_id, {"yen": player["yen"] - yen_amount})
    
    # Add to liquidity pool
    success, msg, lp_tokens = _add_liquidity(user_id, ticker, stock_amount, yen_amount)
    
    await update.message.reply_text(msg, parse_mode="Markdown")
    
    log_stock_event("ADD_LIQUIDITY", {
        "user_id": user_id,
        "ticker": ticker,
        "stock_amount": stock_amount,
        "yen_amount": yen_amount,
        "lp_tokens": lp_tokens
    })


async def removeliquidity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Remove liquidity from a pool by burning LP tokens.
    Usage: /removeliquidity <ticker> <lp_amount>
    """
    user_id = update.effective_user.id
    
    if len(context.args) != 2:
        await update.message.reply_text(
            "❌ *Usage:* `/removeliquidity <ticker> <lp_amount>`\n\n"
            "Example: `/removeliquidity AAPL 50`\n"
            "This removes 50 LP tokens from the AAPL pool.",
            parse_mode="Markdown"
        )
        return
    
    ticker = context.args[0].upper()
    try:
        lp_amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid LP amount. Please use a number.")
        return
    
    if lp_amount <= 0:
        await update.message.reply_text("❌ LP amount must be positive.")
        return
    
    # Remove liquidity
    success, msg, stock_returned, yen_returned = _remove_liquidity(user_id, ticker, lp_amount)
    
    if success:
        # Credit back to user
        player = get_player(user_id)
        
        # Add shares back to portfolio
        portfolio = _get_portfolio(user_id)
        current_shares = portfolio.get(ticker, {}).get("shares", 0) if isinstance(portfolio.get(ticker), dict) else 0
        col(PORTFOLIO_COL).update_one(
            {"user_id": user_id},
            {"$set": {f"holdings.{ticker}.shares": current_shares + stock_returned}}
        )
        
        # Add Yen back
        update_player(user_id, {"yen": player["yen"] + yen_returned})
    
    await update.message.reply_text(msg, parse_mode="Markdown")
    
    if success:
        log_stock_event("REMOVE_LIQUIDITY", {
            "user_id": user_id,
            "ticker": ticker,
            "lp_amount": lp_amount,
            "stock_returned": stock_returned,
            "yen_returned": yen_returned
        })


async def viewliquidity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    View liquidity pool info for a stock.
    Usage: /viewliquidity <ticker>
    """
    if len(context.args) != 1:
        await update.message.reply_text(
            "❌ *Usage:* `/viewliquidity <ticker>`\n\n"
            "Example: `/viewliquidity AAPL`",
            parse_mode="Markdown"
        )
        return
    
    ticker = context.args[0].upper()
    pool = _get_liquidity_pool(ticker)
    stocks = _load_stocks()
    stock_info = stocks.get(ticker, {})
    
    if not pool:
        await update.message.reply_text(
            f"📊 *{ticker}* Liquidity Pool\n\n"
            f"❌ No liquidity pool exists yet.\n"
            f"Be the first to add liquidity with `/addliquidity {ticker} <amount> <yen>`!",
            parse_mode="Markdown"
        )
        return
    
    stock_reserve = pool["stock_reserve"]
    yen_reserve = pool["yen_reserve"]
    total_shares = pool.get("total_shares", 0)
    
    current_price = yen_reserve / stock_reserve if stock_reserve > 0 else 0
    
    lines = [
        f"💧 *{ticker}* LIQUIDITY POOL",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📈 Stock Reserve: *{stock_reserve:,.2f}* shares",
        f"💰 Yen Reserve: *{yen_reserve:,.0f}* {CURRENCY_NAME}",
        f"💵 Current Price: *{current_price:,.2f}* {CURRENCY_NAME}/share",
        f"🎫 Total LP Tokens: *{total_shares:,.2f}",
        "",
        f"📊 Base Price: *{stock_info.get('price', 0):,.2f}* {CURRENCY_NAME}",
        f"📈 24h Change: {_change_arrow(stock_info.get('change_pct', 0))} {stock_info.get('change_pct', 0):.2f}%",
    ]
    
    keyboard = [[
        InlineKeyboardButton("➕ Add Liquidity", callback_data=f"amm_add_{ticker}"),
        InlineKeyboardButton("➖ Remove Liquidity", callback_data=f"amm_remove_{ticker}")
    ]]
    
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
