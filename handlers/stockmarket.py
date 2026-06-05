"""
handlers/stockmarket.py — Demon Slayer Stock Market
=====================================================
14 stocks: All independent & market-driven (Wall Street style).
No player-driven mechanics — prices move on market forces, sentiment, and events.
Commands: /market, /stockbuy, /stocksell, /portfolio, /stockhistory
Admin:    /marketcrash, /marketboom, /marketreset

Price engine runs every 5 minutes via APScheduler.
Image cards generated with Pillow.
"""
import io
import math
import random
import logging
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from utils.database import col, get_player, update_player

log = logging.getLogger(__name__)

# ── Font paths ────────────────────────────────────────────────────────────
_FONT_DIR = "/usr/share/fonts/truetype/liberation/"
_FONT_REG  = _FONT_DIR + "LiberationSans-Regular.ttf"
_FONT_BOLD = _FONT_DIR + "LiberationSans-Bold.ttf"

def _font(size: int, bold: bool = False):
    try:
        return ImageFont.truetype(_FONT_BOLD if bold else _FONT_REG, size)
    except Exception:
        return ImageFont.load_default()

# ── Stock definitions ─────────────────────────────────────────────────────
# All stocks are now INDEPENDENT — no player-driven mechanics
# Types: sector, growth, value, volatile, stable, momentum, cyclical, gamble
STOCKS = {
    # ── Sector Stocks (Industrial, Tech, Healthcare, etc.) ────────────────
    "DBS": {
        "name": "Demon Blood Supply Co.",
        "emoji": "🩸",
        "base_price": 1000,
        "volatility": 0.12,
        "type": "cyclical",
        "sector": "Healthcare",
        "color": (180, 40, 40),
        "desc": "Biotech firm. Prices cycle with market sentiment and R&D news.",
    },
    "WST": {
        "name": "Wisteria Corp",
        "emoji": "💜",
        "base_price": 1200,
        "volatility": 0.10,
        "type": "growth",
        "sector": "Technology",
        "color": (120, 60, 180),
        "desc": "Tech growth stock. Steady climb with occasional volatility.",
    },
    "MZN": {
        "name": "Muzan Industries",
        "emoji": "👁️",
        "base_price": 2500,
        "volatility": 0.15,
        "type": "volatile",
        "sector": "Conglomerate",
        "color": (40, 10, 60),
        "desc": "High-volatility conglomerate. Prone to sharp swings on earnings.",
    },
    "NFG": {
        "name": "Nichirin Forge Ltd",
        "emoji": "⚒️",
        "base_price": 1500,
        "volatility": 0.11,
        "type": "value",
        "sector": "Industrial",
        "color": (180, 120, 20),
        "desc": "Industrial value stock. Moves with manufacturing data and demand.",
    },
    "KZK": {
        "name": "Kizuki Cartel",
        "emoji": "☠️",
        "base_price": 3000,
        "volatility": 0.18,
        "type": "momentum",
        "sector": "Energy",
        "color": (60, 0, 80),
        "desc": "Momentum play. Trends strongly but reverses sharply.",
    },
    "CRC": {
        "name": "Corps Ration Co.",
        "emoji": "🍱",
        "base_price": 800,
        "volatility": 0.08,
        "type": "stable",
        "sector": "Consumer Staples",
        "color": (40, 100, 60),
        "desc": "Defensive staple. Low volatility, steady dividends.",
    },
    # ── Specialty & Thematic Stocks ───────────────────────────────────────
    "STC": {
        "name": "Sunrise Trading Co.",
        "emoji": "🌅",
        "base_price": 500,
        "volatility": 0.15,
        "type": "penny",
        "sector": "Trading",
        "color": (200, 140, 30),
        "desc": "Penny stock. High volatility, low price. Speculative play.",
    },
    "BEP": {
        "name": "Butterfly Estate Pharma",
        "emoji": "🦋",
        "base_price": 1800,
        "volatility": 0.11,
        "type": "healthcare",
        "sector": "Pharmaceuticals",
        "color": (160, 80, 160),
        "desc": "Pharma company. Moves on drug trial news and FDA approvals.",
    },
    "ICH": {
        "name": "Infinity Castle Holdings",
        "emoji": "🏯",
        "base_price": 2000,
        "volatility": 0.08,
        "type": "REIT",
        "sector": "Real Estate",
        "color": (30, 30, 80),
        "desc": "Real estate investment trust. Pays steady income to holders.",
    },
    "UFT": {
        "name": "Ubuyashiki Family Trust",
        "emoji": "🌸",
        "base_price": 5000,
        "volatility": 0.02,
        "type": "blue_chip",
        "sector": "Diversified",
        "color": (180, 100, 120),
        "desc": "Blue-chip dividend aristocrat. Pays 5% annual dividend.",
        "dividend": 0.05,
    },
    "SVA": {
        "name": "Swordsmith Village Arms",
        "emoji": "🗡️",
        "base_price": 900,
        "volatility": 0.20,
        "type": "defense",
        "sector": "Aerospace & Defense",
        "color": (100, 60, 20),
        "desc": "Defense contractor. Spikes on geopolitical tension.",
    },
    "TJV": {
        "name": "Tanjiro Ventures",
        "emoji": "🔥",
        "base_price": 300,
        "volatility": 0.04,
        "type": "startup",
        "sector": "Venture Capital",
        "color": (200, 60, 20),
        "desc": "Early-stage VC fund. Slow growth but long-term potential.",
    },
    "RFF": {
        "name": "Rengoku Flame Fund",
        "emoji": "🔆",
        "base_price": 1100,
        "volatility": 0.09,
        "type": "energy",
        "sector": "Oil & Gas",
        "color": (220, 100, 10),
        "desc": "Energy sector ETF. Tracks oil and gas market performance.",
    },
    "SFI": {
        "name": "Spider Forest Inc.",
        "emoji": "🕷️",
        "base_price": 400,
        "volatility": 0.30,
        "type": "biotech",
        "sector": "Biotechnology",
        "color": (60, 60, 60),
        "desc": "Clinical-stage biotech. Binary outcomes on trial results.",
    },
}

TICKER_LIST = list(STOCKS.keys())
MIN_PRICE_RATIO = 0.20   # price can't fall below 20% of base
MAX_PRICE_RATIO = 5.00   # price can't rise above 500% of base
MAX_OWN_PCT     = 0.30   # can't own more than 30% of float
FLOAT_SHARES    = 10_000 # total shares per ticker in circulation
HISTORY_DAYS    = 7


# ── DB helpers ────────────────────────────────────────────────────────────

def _get_price(ticker: str) -> float:
    doc = col("stock_prices").find_one({"ticker": ticker})
    if doc:
        return float(doc["price"])
    return float(STOCKS[ticker]["base_price"])


def _set_price(ticker: str, price: float):
    base  = STOCKS[ticker]["base_price"]
    price = max(base * MIN_PRICE_RATIO, min(base * MAX_PRICE_RATIO, price))
    price = round(price, 2)
    col("stock_prices").update_one(
        {"ticker": ticker},
        {"$set": {"ticker": ticker, "price": price, "updated_at": datetime.utcnow()}},
        upsert=True
    )
    # Save to history
    col("stock_history").insert_one({
        "ticker": ticker,
        "price": price,
        "ts": datetime.utcnow()
    })
    return price


def _get_history(ticker: str, days: int = HISTORY_DAYS) -> list[float]:
    since = datetime.utcnow() - timedelta(days=days)
    docs  = list(col("stock_history").find(
        {"ticker": ticker, "ts": {"$gte": since}},
        sort=[("ts", 1)]
    ))
    prices = [d["price"] for d in docs]
    if not prices:
        prices = [float(STOCKS[ticker]["base_price"])]
    return prices


def _get_holding(user_id: int, ticker: str) -> dict:
    return col("stock_holdings").find_one({"user_id": user_id, "ticker": ticker}) or {}


def _get_portfolio(user_id: int) -> list[dict]:
    return list(col("stock_holdings").find({"user_id": user_id, "shares": {"$gt": 0}}))


def _total_shares_owned(ticker: str) -> int:
    agg = list(col("stock_holdings").aggregate([
        {"$match": {"ticker": ticker}},
        {"$group": {"_id": None, "total": {"$sum": "$shares"}}}
    ]))
    return agg[0]["total"] if agg else 0


def _count_events(event_type: str, since_hours: int = 4) -> int:
    since = datetime.utcnow() - timedelta(hours=since_hours)
    return col("stock_events").count_documents({"type": event_type, "ts": {"$gte": since}})


def log_stock_event(event_type: str, data: dict = None):
    """Call this from other handlers to drive player-based stocks."""
    col("stock_events").insert_one({
        "type": event_type,
        "data": data or {},
        "ts": datetime.utcnow()
    })


# ── Price engine ──────────────────────────────────────────────────────────

def update_stock_prices():
    """Run every 5 minutes via APScheduler.
    
    Wall Street-style price engine:
    - All stocks move independently based on market mechanics
    - No player-driven events affect prices
    - Each stock type has unique behavior (sector rotation, momentum, etc.)
    """
    log.info("[STOCK] Running price update tick.")
    
    # Market sentiment factor (random walk with mean reversion)
    market_sentiment = random.gauss(0, 0.02)
    
    # Sector rotation factors (each sector moves differently)
    sector_factors = {
        "Healthcare": random.gauss(0, 0.03),
        "Technology": random.gauss(0.01, 0.04),
        "Conglomerate": random.gauss(0, 0.035),
        "Industrial": random.gauss(-0.005, 0.025),
        "Energy": random.gauss(0.005, 0.04),
        "Consumer Staples": random.gauss(0.002, 0.015),
        "Trading": random.gauss(0, 0.05),
        "Pharmaceuticals": random.gauss(0.003, 0.03),
        "Real Estate": random.gauss(0.001, 0.02),
        "Diversified": random.gauss(0.002, 0.01),
        "Aerospace & Defense": random.gauss(0, 0.035),
        "Venture Capital": random.gauss(0.005, 0.02),
        "Oil & Gas": random.gauss(0, 0.03),
        "Biotechnology": random.gauss(0, 0.06),
    }

    for ticker, cfg in STOCKS.items():
        current = _get_price(ticker)
        delta   = 0.0
        vol     = cfg["volatility"]
        base    = cfg["base_price"]
        t       = cfg["type"]
        sector  = cfg.get("sector", "General")
        
        # Base market movement
        market_component = market_sentiment * random.uniform(0.5, 1.5)
        
        # Sector-specific movement
        sector_component = sector_factors.get(sector, 0)
        
        if t == "cyclical":
            # Cycles with economic sentiment
            cycle_phase = (datetime.utcnow().hour % 6) / 6.0
            cycle_delta = math.sin(cycle_phase * 2 * math.pi) * 0.03
            delta = market_component + sector_component + cycle_delta + random.gauss(0, vol)
            
        elif t == "growth":
            # Steady upward drift with volatility
            drift = 0.003  # 0.3% per tick upward bias
            delta = drift + sector_component + random.gauss(0, vol)
            
        elif t == "volatile":
            # High volatility, occasional big moves
            if random.random() < 0.15:
                delta = random.choice([-0.25, -0.20, 0.20, 0.30, 0.40])
            else:
                delta = market_component + sector_component + random.gauss(0, vol)
                
        elif t == "value":
            # Mean-reverting around fair value
            fair_value = base * (1 + market_sentiment * 2)
            deviation = (current - fair_value) / fair_value
            mean_reversion = -deviation * 0.1  # 10% reversion per tick
            delta = mean_reversion + sector_component + random.gauss(0, vol * 0.7)
            
        elif t == "momentum":
            # Trends strongly, reverses sharply
            momentum_factor = random.gauss(0.01, 0.05)
            if random.random() < 0.08:
                # Sharp reversal
                delta = -momentum_factor * 3
            else:
                delta = momentum_factor + market_component * 1.5
                
        elif t == "stable":
            # Low volatility, slight dividend yield baked in
            dividend_yield = 0.001  # Small constant return
            delta = dividend_yield + random.gauss(0, vol)
            
        elif t == "penny":
            # High volatility, no fundamental anchor
            delta = random.gauss(0, vol * 1.5)
            if random.random() < 0.1:
                delta *= random.uniform(2, 4)  # Occasional spikes
                
        elif t == "healthcare":
            # Moves on "news" events
            delta = sector_component + random.gauss(0.002, vol)
            if random.random() < 0.08:
                # FDA approval/rejection news
                delta += random.choice([-0.20, 0.35])
                
        elif t == "REIT":
            # Income-focused, interest rate sensitive
            rate_sensitivity = -random.gauss(0, 0.01)
            dividend_component = 0.0015
            delta = rate_sensitivity + dividend_component + random.gauss(0, vol)
            
        elif t == "blue_chip":
            # Stable growth with dividends
            steady_growth = 0.0015
            delta = steady_growth + market_component * 0.5 + random.gauss(0, vol)
            
        elif t == "defense":
            # Geopolitical risk premium
            risk_premium = random.gauss(0.002, 0.02)
            delta = risk_premium + sector_component + random.gauss(0, vol)
            
        elif t == "startup":
            # Early stage: slow growth, occasional funding pops
            base_growth = 0.001
            if random.random() < 0.05:
                # Funding round announcement
                delta = 0.15 + random.gauss(0, 0.05)
            else:
                delta = base_growth + random.gauss(0, vol)
                
        elif t == "energy":
            # Commodity-linked
            commodity_cycle = math.sin(datetime.utcnow().hour / 24 * 2 * math.pi) * 0.02
            delta = commodity_cycle + sector_component + random.gauss(0, vol)
            
        elif t == "biotech":
            # Binary outcomes on trials
            if random.random() < 0.04:
                # Trial results
                delta = random.choice([-0.40, -0.30, 0.50, 0.80])
            else:
                delta = random.gauss(0, vol)
        
        else:
            # Default: market-following with sector tilt
            delta = market_component + sector_component + random.gauss(0, vol)
        
        # Apply delta with additional noise
        noise = random.gauss(0, vol * 0.2)
        new_price = current * (1 + delta + noise)
        _set_price(ticker, new_price)

    # Pay UFT dividends to all holders
    _pay_dividends()
    log.info("[STOCK] Price update complete.")


def _pay_dividends():
    """Pay UFT 5% daily dividend to holders who have held for 24h+."""
    cfg      = STOCKS["UFT"]
    price    = _get_price("UFT")
    cutoff   = datetime.utcnow() - timedelta(hours=24)
    holders  = list(col("stock_holdings").find({
        "ticker": "UFT",
        "shares": {"$gt": 0},
        "bought_at": {"$lte": cutoff}
    }))
    for h in holders:
        dividend = round(h["shares"] * price * cfg["dividend"] / 6, 2)  # 4h tick = 1/6 of daily
        if dividend > 0:
            player = get_player(h["user_id"])
            if player:
                update_player(h["user_id"], yen=player["yen"] + int(dividend))
                col("stock_holdings").update_one(
                    {"_id": h["_id"]},
                    {"$inc": {"total_dividends": dividend}}
                )


def nudge_price(ticker: str, pct: float):
    """Instant small nudge when player does an action. pct = e.g. 0.005 for 0.5%."""
    if ticker not in STOCKS:
        return
    current = _get_price(ticker)
    _set_price(ticker, current * (1 + pct))


# ── Image generation ──────────────────────────────────────────────────────

# Theme colors
BG_DARK   = (12, 12, 20)
BG_CARD   = (20, 22, 35)
BG_PANEL  = (28, 30, 48)
WHITE     = (255, 255, 255)
GRAY      = (160, 160, 180)
DIMGRAY   = (80, 85, 110)
GREEN     = (40, 200, 100)
RED       = (220, 60, 60)
GOLD      = (220, 180, 50)
ACCENT    = (100, 120, 255)


def _sparkline_points(prices: list[float], x0: int, y0: int, w: int, h: int) -> list[tuple]:
    if len(prices) < 2:
        return [(x0, y0 + h // 2), (x0 + w, y0 + h // 2)]
    mn, mx = min(prices), max(prices)
    rng = mx - mn or 1
    pts = []
    for i, p in enumerate(prices):
        x = x0 + int(i / (len(prices) - 1) * w)
        y = y0 + h - int((p - mn) / rng * h)
        pts.append((x, y))
    return pts


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill, outline=None):
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle([x1, y1, x2, y2], radius=radius, fill=fill, outline=outline)


def generate_market_image(tickers: list[str] = None) -> io.BytesIO:
    """Generate full market overview image."""
    tickers = tickers or TICKER_LIST
    cols_n  = 2
    rows_n  = math.ceil(len(tickers) / cols_n)

    CARD_W, CARD_H = 320, 120
    PAD = 12
    HEADER_H = 70
    W = cols_n * CARD_W + (cols_n + 1) * PAD
    H = HEADER_H + rows_n * (CARD_H + PAD) + PAD

    img  = Image.new("RGB", (W, H), BG_DARK)
    draw = ImageDraw.Draw(img)

    # Header
    _rounded_rect(draw, (PAD, PAD, W - PAD, HEADER_H - PAD // 2), 10, BG_CARD)
    draw.text((PAD + 16, PAD + 8),  "📈  DEMON SLAYER STOCK EXCHANGE", font=_font(18, bold=True), fill=GOLD)
    now_str = datetime.utcnow().strftime("Updated %d %b %Y  %H:%M UTC")
    draw.text((PAD + 16, PAD + 34), now_str, font=_font(12), fill=DIMGRAY)

    for i, ticker in enumerate(tickers):
        cfg     = STOCKS[ticker]
        history = _get_history(ticker)
        price   = history[-1] if history else cfg["base_price"]
        prev    = history[-2] if len(history) >= 2 else price
        chg     = price - prev
        chg_pct = (chg / prev * 100) if prev else 0
        is_up   = chg >= 0
        clr_chg = GREEN if is_up else RED
        arrow   = "▲" if is_up else "▼"

        row = i // cols_n
        col_idx = i % cols_n
        cx = PAD + col_idx * (CARD_W + PAD)
        cy = HEADER_H + row * (CARD_H + PAD) + PAD // 2

        # Card background
        _rounded_rect(draw, (cx, cy, cx + CARD_W, cy + CARD_H), 10, BG_CARD)
        # Left accent bar in stock's color
        _rounded_rect(draw, (cx, cy, cx + 4, cy + CARD_H), 2, cfg["color"])

        # Ticker + name
        draw.text((cx + 14, cy + 10), ticker, font=_font(20, bold=True), fill=WHITE)
        name_short = cfg["name"][:26] + ("…" if len(cfg["name"]) > 26 else "")
        draw.text((cx + 14, cy + 36), name_short, font=_font(11), fill=GRAY)
        draw.text((cx + 14, cy + 52), cfg["emoji"] + "  " + cfg["type"].upper(),
                  font=_font(10), fill=DIMGRAY)

        # Price + change
        price_str = f"¥{price:,.0f}"
        chg_str   = f"{arrow} {abs(chg_pct):.1f}%"
        draw.text((cx + CARD_W - 110, cy + 10), price_str, font=_font(18, bold=True), fill=WHITE)
        draw.text((cx + CARD_W - 90,  cy + 36), chg_str,   font=_font(14, bold=True), fill=clr_chg)

        # Sparkline
        sp_x, sp_y, sp_w, sp_h = cx + 14, cy + 70, CARD_W - 28, 38
        pts = _sparkline_points(history[-24:], sp_x, sp_y, sp_w, sp_h)
        if len(pts) >= 2:
            # Filled area under sparkline
            poly = [(sp_x, sp_y + sp_h)] + pts + [(pts[-1][0], sp_y + sp_h)]
            fill_color = (int(clr_chg[0] * 0.3), int(clr_chg[1] * 0.3), int(clr_chg[2] * 0.3))
            draw.polygon(poly, fill=fill_color)
            draw.line(pts, fill=clr_chg, width=2)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def generate_stock_detail_image(ticker: str) -> io.BytesIO:
    """Generate a detailed card for a single stock."""
    cfg     = STOCKS[ticker]
    history = _get_history(ticker, days=7)
    price   = history[-1] if history else cfg["base_price"]
    open_p  = history[0]  if history else price
    high_p  = max(history) if history else price
    low_p   = min(history) if history else price
    chg     = price - open_p
    chg_pct = (chg / open_p * 100) if open_p else 0
    is_up   = chg >= 0
    clr_chg = GREEN if is_up else RED
    arrow   = "▲" if is_up else "▼"

    W, H = 540, 340
    img  = Image.new("RGB", (W, H), BG_DARK)
    draw = ImageDraw.Draw(img)

    # Background card
    _rounded_rect(draw, (8, 8, W - 8, H - 8), 14, BG_CARD)
    # Top accent bar in stock color
    _rounded_rect(draw, (8, 8, W - 8, 6 + 8), 4, cfg["color"])

    # Ticker badge
    badge_w = 80
    _rounded_rect(draw, (20, 20, 20 + badge_w, 52), 6, cfg["color"])
    draw.text((20 + badge_w // 2, 36), ticker, font=_font(18, bold=True),
              fill=WHITE, anchor="mm")

    # Name + emoji
    draw.text((116, 20), cfg["emoji"] + " " + cfg["name"], font=_font(16, bold=True), fill=WHITE)
    draw.text((116, 44), cfg["desc"][:55] + ("…" if len(cfg["desc"]) > 55 else ""),
              font=_font(11), fill=GRAY)

    # Price
    draw.text((20, 68), f"¥{price:,.2f}", font=_font(30, bold=True), fill=WHITE)
    draw.text((20, 104), f"{arrow}  {abs(chg):,.2f}  ({abs(chg_pct):.2f}%)",
              font=_font(14, bold=True), fill=clr_chg)

    # Stats row
    stats = [
        ("Open",  f"¥{open_p:,.0f}"),
        ("High",  f"¥{high_p:,.0f}"),
        ("Low",   f"¥{low_p:,.0f}"),
        ("Type",  cfg["type"].title()),
    ]
    for j, (label, val) in enumerate(stats):
        sx = 20 + j * 130
        _rounded_rect(draw, (sx, 126, sx + 120, 170), 6, BG_PANEL)
        draw.text((sx + 10, 132), label, font=_font(10), fill=DIMGRAY)
        draw.text((sx + 10, 148), val,   font=_font(13, bold=True), fill=WHITE)

    # Sparkline — 7-day
    sp_x, sp_y, sp_w, sp_h = 20, 180, W - 40, 100
    pts = _sparkline_points(history, sp_x, sp_y, sp_w, sp_h)
    if len(pts) >= 2:
        poly = [(sp_x, sp_y + sp_h)] + pts + [(pts[-1][0], sp_y + sp_h)]
        fc = (int(clr_chg[0]*0.15), int(clr_chg[1]*0.15), int(clr_chg[2]*0.15))
        draw.polygon(poly, fill=fc)
        draw.line(pts, fill=clr_chg, width=2)
        # Dot on last price
        lx, ly = pts[-1]
        draw.ellipse([lx - 4, ly - 4, lx + 4, ly + 4], fill=clr_chg)

    # X-axis day labels
    if len(history) >= 2:
        for k in range(min(7, len(history))):
            day = (datetime.utcnow() - timedelta(days=6 - k)).strftime("%a")
            lx  = sp_x + int(k / 6 * sp_w)
            draw.text((lx, sp_y + sp_h + 6), day, font=_font(10), fill=DIMGRAY, anchor="mt")

    # Footer
    draw.text((20, H - 24), "Use /stockbuy or /stocksell to trade",
              font=_font(11), fill=DIMGRAY)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


def generate_portfolio_image(user_id: int) -> io.BytesIO:
    """Generate portfolio summary image for a player."""
    holdings = _get_portfolio(user_id)
    player   = get_player(user_id) or {}

    total_val  = 0.0
    total_cost = 0.0
    rows = []
    for h in holdings:
        tk    = h["ticker"]
        if tk not in STOCKS:
            continue
        price = _get_price(tk)
        val   = h["shares"] * price
        cost  = h.get("avg_cost", price) * h["shares"]
        pnl   = val - cost
        pnl_p = (pnl / cost * 100) if cost else 0
        total_val  += val
        total_cost += cost
        rows.append((tk, h["shares"], price, val, pnl, pnl_p))

    total_pnl   = total_val - total_cost
    total_pnl_p = (total_pnl / total_cost * 100) if total_cost else 0

    ROW_H  = 46
    HEAD_H = 130
    FOOT_H = 50
    W      = 520
    H      = HEAD_H + max(len(rows), 1) * ROW_H + FOOT_H + 20

    img  = Image.new("RGB", (W, H), BG_DARK)
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (8, 8, W - 8, H - 8), 14, BG_CARD)

    # Header
    draw.text((20, 18), "📊  MY PORTFOLIO", font=_font(18, bold=True), fill=GOLD)
    name = player.get("name", "Player")
    draw.text((20, 46), name, font=_font(13), fill=GRAY)

    # Summary metrics
    metrics = [
        ("Total Value", f"¥{total_val:,.0f}"),
        ("Total P&L",   f"{'▲' if total_pnl >= 0 else '▼'} ¥{abs(total_pnl):,.0f}"),
        ("Return",      f"{'+' if total_pnl_p >= 0 else ''}{total_pnl_p:.1f}%"),
    ]
    for j, (lbl, val) in enumerate(metrics):
        sx = 20 + j * 165
        _rounded_rect(draw, (sx, 68, sx + 155, 110), 6, BG_PANEL)
        draw.text((sx + 10, 74), lbl, font=_font(10), fill=DIMGRAY)
        clr = GREEN if ("▲" in val or "+" in val) else (RED if ("▼" in val or val.startswith("-")) else WHITE)
        draw.text((sx + 10, 90), val, font=_font(13, bold=True), fill=clr)

    # Column headers
    draw.line([(12, HEAD_H), (W - 12, HEAD_H)], fill=DIMGRAY, width=1)
    for lbl, x in [("TICKER", 20), ("SHARES", 120), ("PRICE", 210), ("VALUE", 310), ("P&L", 410)]:
        draw.text((x, HEAD_H + 6), lbl, font=_font(10, bold=True), fill=DIMGRAY)

    if not rows:
        draw.text((W // 2, HEAD_H + ROW_H), "No holdings yet — use /stockbuy",
                  font=_font(13), fill=DIMGRAY, anchor="mt")
    else:
        for idx, (tk, shares, price, val, pnl, pnl_p) in enumerate(rows):
            ry = HEAD_H + 30 + idx * ROW_H
            if idx % 2 == 0:
                _rounded_rect(draw, (12, ry - 4, W - 12, ry + ROW_H - 8), 4, BG_PANEL)
            clr = GREEN if pnl >= 0 else RED
            cfg = STOCKS.get(tk, {})
            draw.text((20,  ry + 6), tk,                  font=_font(14, bold=True), fill=WHITE)
            draw.text((20,  ry + 24), cfg.get("emoji",""),  font=_font(10), fill=GRAY)
            draw.text((120, ry + 6), str(shares),           font=_font(13), fill=WHITE)
            draw.text((210, ry + 6), f"¥{price:,.0f}",      font=_font(13), fill=WHITE)
            draw.text((310, ry + 6), f"¥{val:,.0f}",        font=_font(13), fill=WHITE)
            draw.text((410, ry + 6), f"{'+' if pnl>=0 else ''}{pnl_p:.1f}%",
                      font=_font(13, bold=True), fill=clr)

    # Footer
    draw.line([(12, H - FOOT_H - 4), (W - 12, H - FOOT_H - 4)], fill=DIMGRAY, width=1)
    draw.text((20, H - FOOT_H + 8),
              datetime.utcnow().strftime("Snapshot: %d %b %Y %H:%M UTC"),
              font=_font(11), fill=DIMGRAY)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf


# ── Command handlers ──────────────────────────────────────────────────────

async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/market — Show full market overview as text with inline buttons."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ Use /start first.")
        return

    # Build market lines with profit/loss info
    lines = ["Select an index to inspect financial parameters:", ""]
    
    for i, ticker in enumerate(TICKER_LIST, 1):
        cfg = STOCKS[ticker]
        history = _get_history(ticker)
        price = history[-1] if history else cfg["base_price"]
        prev = history[-2] if len(history) >= 2 else price
        chg_pct = ((price - prev) / prev * 100) if prev else 0
        arrow = "📈" if chg_pct >= 0 else "📉"
        sign = "+" if chg_pct >= 0 else ""
        
        lines.append(f"{i}) {arrow} {cfg['name']} ({ticker}) - {int(price)} 💠 ({sign}{chg_pct:.0f}%)")
    
    # Create inline keyboard with stock buttons
    keyboard = []
    for i, ticker in enumerate(TICKER_LIST, 1):
        keyboard.append([InlineKeyboardButton(f"{i}) {ticker}", callback_data=f"stock_select_{ticker}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("\n".join(lines), reply_markup=reply_markup)



async def stockhistory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stockhistory TICKER — Detailed 7-day stats for one stock (text format)."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ Use /start first.")
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "📖 Usage: `/stockhistory TICKER`\nExample: `/stockhistory DBS`",
            parse_mode="Markdown"
        )
        return

    ticker = args[0].upper()
    if ticker not in STOCKS:
        valid = "  ".join(TICKER_LIST)
        await update.message.reply_text(
            f"❌ Unknown ticker `{ticker}`\n\nValid tickers:\n`{valid}`",
            parse_mode="Markdown"
        )
        return

    cfg = STOCKS[ticker]
    history = _get_history(ticker, days=7)
    price   = history[-1] if history else cfg["base_price"]
    open_p  = history[0]  if history else price
    chg_pct = ((price - open_p) / open_p * 100) if len(history) >= 2 else 0
    arrow   = "📈" if chg_pct >= 0 else "📉"
    sign    = "+" if chg_pct >= 0 else ""
    
    # Get min/max for the period
    min_price = min(history) if history else price
    max_price = max(history) if history else price
    
    # Build history lines
    history_lines = []
    for i, p in enumerate(history):
        day_label = f"Day {i+1}" if i < len(history) - 1 else "Today"
        prev = history[i-1] if i > 0 else p
        daily_chg = ((p - prev) / prev * 100) if prev else 0
        daily_arrow = "📈" if daily_chg >= 0 else "📉"
        daily_sign = "+" if daily_chg >= 0 else ""
        history_lines.append(f"  {day_label}: {int(p)} 💠 ({daily_arrow}{daily_sign}{daily_chg:.1f}%)")
    
    history_text = "\n".join(history_lines)
    
    detail_text = (
        f"{cfg['emoji']} *{cfg['name']}* (`{ticker}`)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Current Price:  *¥{price:,.2f}*\n"
        f"📊 7-Day Change:   *{arrow} {sign}{abs(chg_pct):.1f}%*\n"
        f"📈 Period High:    *¥{max_price:,.2f}*\n"
        f"📉 Period Low:     *¥{min_price:,.2f}*\n"
        f"🏷️  Type:          `{cfg['type']}`\n"
        f"📦 Sector:         `{cfg.get('sector', 'N/A')}`\n\n"
        f"_7-Day History:_\n"
        f"{history_text}\n\n"
        f"_{cfg['desc']}_"
    )
    
    await update.message.reply_text(detail_text, parse_mode="Markdown")


async def stockbuy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stockbuy TICKER shares — Buy shares in a stock."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ Use /start first.")
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "📖 *Usage:* `/stockbuy TICKER shares`\n"
            "Example: `/stockbuy DBS 10`\n\n"
            "Use `/market` to see all tickers and prices.",
            parse_mode="Markdown"
        )
        return

    ticker = args[0].upper()
    if ticker not in STOCKS:
        await update.message.reply_text(f"❌ Unknown ticker `{ticker}`", parse_mode="Markdown")
        return

    try:
        shares = int(args[1])
        if shares <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Shares must be a positive number.")
        return

    cfg   = STOCKS[ticker]
    price = _get_price(ticker)

    # Night-only restriction for RFF
    if cfg["type"] == "night_only":
        hour = datetime.utcnow().hour
        if not (hour >= 22 or hour < 6):
            await update.message.reply_text(
                f"🔒 *{cfg['name']}* only trades during Black Market hours (10pm–6am UTC).",
                parse_mode="Markdown"
            )
            return

    # Ownership cap
    total_owned = _total_shares_owned(ticker)
    holding     = _get_holding(user_id, ticker)
    my_shares   = holding.get("shares", 0)
    if (my_shares + shares) > FLOAT_SHARES * MAX_OWN_PCT:
        max_can_buy = int(FLOAT_SHARES * MAX_OWN_PCT) - my_shares
        await update.message.reply_text(
            f"❌ Can't own more than *{int(MAX_OWN_PCT*100)}%* of float.\n"
            f"You can buy at most *{max(0, max_can_buy)}* more shares of `{ticker}`.",
            parse_mode="Markdown"
        )
        return

    cost = round(price * shares)
    if player["yen"] < cost:
        await update.message.reply_text(
            f"❌ *Not enough yen!*\n\n"
            f"💰 Cost:   *¥{cost:,}*\n"
            f"👛 Wallet: *¥{player['yen']:,}*\n"
            f"💸 Short:  *¥{cost - player['yen']:,}*",
            parse_mode="Markdown"
        )
        return

    # Execute buy
    update_player(user_id, yen=player["yen"] - cost)

    existing   = _get_holding(user_id, ticker)
    old_shares = existing.get("shares", 0)
    old_avg    = existing.get("avg_cost", price)
    new_shares = old_shares + shares
    new_avg    = ((old_avg * old_shares) + (price * shares)) / new_shares

    col("stock_holdings").update_one(
        {"user_id": user_id, "ticker": ticker},
        {"$set": {
            "user_id":   user_id,
            "ticker":    ticker,
            "shares":    new_shares,
            "avg_cost":  round(new_avg, 2),
            "bought_at": existing.get("bought_at") or datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }},
        upsert=True
    )

    # Tiny upward nudge on buy
    nudge_price(ticker, 0.001 * shares / 100)

    await update.message.reply_text(
        f"✅ *SHARES PURCHASED!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{cfg['emoji']} *{cfg['name']}* (`{ticker}`)\n\n"
        f"📦 Shares bought: *{shares}*\n"
        f"💰 Price/share:   *¥{price:,.2f}*\n"
        f"💸 Total spent:   *¥{cost:,}*\n"
        f"👛 Balance left:  *¥{player['yen'] - cost:,}*\n"
        f"📊 You now own:   *{new_shares} shares*",
        parse_mode="Markdown"
    )


async def stocksell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/stocksell TICKER shares — Sell shares."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ Use /start first.")
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "📖 *Usage:* `/stocksell TICKER shares`\n"
            "Example: `/stocksell DBS 5`\n"
            "Use `/portfolio` to see your holdings.",
            parse_mode="Markdown"
        )
        return

    ticker = args[0].upper()
    if ticker not in STOCKS:
        await update.message.reply_text(f"❌ Unknown ticker `{ticker}`", parse_mode="Markdown")
        return

    try:
        shares = int(args[1])
        if shares <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Shares must be a positive number.")
        return

    holding = _get_holding(user_id, ticker)
    owned   = holding.get("shares", 0)
    if owned < shares:
        await update.message.reply_text(
            f"❌ You only own *{owned}* shares of `{ticker}`.",
            parse_mode="Markdown"
        )
        return

    cfg      = STOCKS[ticker]
    price    = _get_price(ticker)
    avg_cost = holding.get("avg_cost", price)
    proceeds = round(price * shares)
    cost_b   = round(avg_cost * shares)
    pnl      = proceeds - cost_b
    pnl_pct  = (pnl / cost_b * 100) if cost_b else 0

    update_player(user_id, yen=player["yen"] + proceeds)

    new_shares = owned - shares
    if new_shares == 0:
        col("stock_holdings").delete_one({"user_id": user_id, "ticker": ticker})
    else:
        col("stock_holdings").update_one(
            {"user_id": user_id, "ticker": ticker},
            {"$set": {"shares": new_shares, "updated_at": datetime.utcnow()}}
        )

    # Tiny downward nudge on sell
    nudge_price(ticker, -0.001 * shares / 100)

    pnl_str = f"{'▲ +' if pnl >= 0 else '▼ '}¥{abs(pnl):,} ({'+' if pnl >= 0 else ''}{pnl_pct:.1f}%)"
    pnl_clr_hint = "📈" if pnl >= 0 else "📉"

    await update.message.reply_text(
        f"✅ *SHARES SOLD!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{cfg['emoji']} *{cfg['name']}* (`{ticker}`)\n\n"
        f"📦 Shares sold:  *{shares}*\n"
        f"💰 Price/share:  *¥{price:,.2f}*\n"
        f"💸 Proceeds:     *¥{proceeds:,}*\n"
        f"{pnl_clr_hint} P&L:         *{pnl_str}*\n"
        f"📊 Remaining:    *{new_shares} shares*",
        parse_mode="Markdown"
    )


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/portfolio — View your holdings as text."""
    user_id = update.effective_user.id
    player  = get_player(user_id)
    if not player:
        await update.message.reply_text("❌ Use /start first.")
        return

    holdings = _get_portfolio(user_id)
    
    if not holdings:
        await update.message.reply_text(
            "📊 *YOUR PORTFOLIO*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "_No holdings yet._\n\n"
            "Use `/market` to browse stocks and `/stockbuy` to purchase shares.",
            parse_mode="Markdown"
        )
        return
    
    total_val = sum(_get_price(h["ticker"]) * h["shares"] for h in holdings if h["ticker"] in STOCKS)
    
    # Build holdings lines with profit/loss
    lines = ["📊 *YOUR PORTFOLIO*", "━━━━━━━━━━━━━━━━━━━━━", ""]
    
    for h in holdings:
        ticker = h["ticker"]
        if ticker not in STOCKS:
            continue
        cfg = STOCKS[ticker]
        shares = h["shares"]
        avg_cost = h.get("avg_cost", 0)
        current_price = _get_price(ticker)
        current_val = current_price * shares
        cost_basis = avg_cost * shares
        profit_loss = current_val - cost_basis
        profit_pct = ((current_val - cost_basis) / cost_basis * 100) if cost_basis > 0 else 0
        
        arrow = "📈" if profit_loss >= 0 else "📉"
        sign = "+" if profit_loss >= 0 else ""
        
        lines.append(f"{cfg['emoji']} *{cfg['name']}* (`{ticker}`)")
        lines.append(f"  📦 Shares: {shares} | Avg: ¥{avg_cost:,.2f} | Current: ¥{current_price:,.2f}")
        lines.append(f"  💰 Value: ¥{current_val:,.0f} | P/L: {arrow} ¥{abs(profit_loss):,.0f} ({sign}{profit_pct:.1f}%)")
        lines.append("")
    
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"💼 Positions: *{len(holdings)}*")
    lines.append(f"💰 Total value: *¥{total_val:,.0f}*")
    lines.append("")
    lines.append("_Use `/stockbuy` or `/stocksell` to trade._")
    
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── Admin commands ────────────────────────────────────────────────────────

async def marketcrash(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📉 /marketcrash [ticker] — Crash a stock or all stocks. Notifies holders via DM."""
    from utils.guards import is_owner
    if not is_owner(update.effective_user.id):
        return
    args    = context.args or []
    targets = [args[0].upper()] if args and args[0].upper() in STOCKS else TICKER_LIST
    
    notified_users = set()
    
    for t in targets:
        p = _get_price(t)
        new_price = p * random.uniform(0.45, 0.65)
        _set_price(t, new_price)
        
        # Find all holders of this stock and notify them
        holders = list(col("stock_holdings").find({"ticker": t, "shares": {"$gt": 0}}))
        for h in holders:
            user_id = h["user_id"]
            if user_id not in notified_users:
                notified_users.add(user_id)
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"📉 *MARKET CRASH ALERT!*\n\n"
                            f"The market has experienced a significant downturn!\n\n"
                            f"Your portfolio may be affected.\n"
                            f"Check your holdings with /portfolio\n\n"
                            f"_Trade wisely!_"
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    log.warning(f"Could not notify user {user_id}: {e}")
    
    names = ", ".join(f"`{t}`" for t in targets)
    await update.message.reply_text(
        f"📉 *MARKET CRASH triggered!*\n{names} dropped 35–55%.\n"
        f"📩 Notified {len(notified_users)} affected investors.",
        parse_mode="Markdown"
    )


async def marketboom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """📈 /marketboom [ticker] — Boom a stock or all stocks. Notifies holders via DM."""
    from utils.guards import is_owner
    if not is_owner(update.effective_user.id):
        return
    args    = context.args or []
    targets = [args[0].upper()] if args and args[0].upper() in STOCKS else TICKER_LIST
    
    notified_users = set()
    
    for t in targets:
        p = _get_price(t)
        new_price = p * random.uniform(1.35, 1.75)
        _set_price(t, new_price)
        
        # Find all holders of this stock and notify them
        holders = list(col("stock_holdings").find({"ticker": t, "shares": {"$gt": 0}}))
        for h in holders:
            user_id = h["user_id"]
            if user_id not in notified_users:
                notified_users.add(user_id)
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"📈 *MARKET BOOM ALERT!*\n\n"
                            f"The market is surging! Great news for your portfolio!\n\n"
                            f"Your stocks have increased significantly in value.\n"
                            f"Check your holdings with /portfolio\n\n"
                            f"_Consider taking profits or holding for more gains!_"
                        ),
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    log.warning(f"Could not notify user {user_id}: {e}")
    
    names = ", ".join(f"`{t}`" for t in targets)
    await update.message.reply_text(
        f"📈 *MARKET BOOM triggered!*\n{names} surged 35–75%.\n"
        f"📩 Notified {len(notified_users)} affected investors.",
        parse_mode="Markdown"
    )


async def marketreset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/marketreset — Reset all prices to base."""
    from utils.guards import is_owner
    if not is_owner(update.effective_user.id):
        return
    for ticker, cfg in STOCKS.items():
        _set_price(ticker, cfg["base_price"])
    await update.message.reply_text("✅ All stock prices reset to base values.")


async def stock_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks for stock selection and purchase."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await query.edit_message_text("❌ Use /start first.")
        return
    
    data = query.data
    if not data.startswith("stock_select_"):
        return
    
    ticker = data.replace("stock_select_", "")
    if ticker not in STOCKS:
        await query.edit_message_text("❌ Invalid ticker.")
        return
    
    cfg = STOCKS[ticker]
    history = _get_history(ticker)
    price = history[-1] if history else cfg["base_price"]
    prev = history[-2] if len(history) >= 2 else price
    chg_pct = ((price - prev) / prev * 100) if prev else 0
    arrow = "📈" if chg_pct >= 0 else "📉"
    sign = "+" if chg_pct >= 0 else ""
    
    # Get user's holding
    holding = _get_holding(user_id, ticker)
    owned = holding.get("shares", 0)
    
    # Calculate trend
    trend = "BULLISH" if chg_pct >= 0 else "BEARISH"
    
    # Risk tier based on volatility
    vol = cfg.get("volatility", 0.1)
    if vol < 0.08:
        risk_emoji = "🟢"
        risk_text = "Low Risk (Stable)"
    elif vol < 0.15:
        risk_emoji = "🟡"
        risk_text = "Medium Risk"
    else:
        risk_emoji = "🔴"
        risk_text = "High Risk (Volatile)"
    
    # Daily buy limit (50 shares max per day)
    daily_limit = 50
    
    # Build the detail message
    detail_text = (
        f"{cfg['emoji']} *{cfg['name']}* (`{ticker}`)\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 Current Valuation: {int(price)} 💠\n"
        f"📊 24h Direct Trend: {arrow} {trend}\n"
        f"⚠️ Risk Tier: {risk_emoji} {risk_text}\n"
        f"📅 Daily Buy Limit: 0/{daily_limit} shares\n"
        f"📥 Remaining Today: {daily_limit} shares\n"
        f"\n"
        f"💰 Price Change: {sign}{chg_pct:.1f}%\n"
        f"📦 You own: {owned} shares\n"
        f"\n"
        f"_Select quantity to buy:_"
    )
    
    # Create buttons for buying 1, 5, 10 shares
    keyboard = [
        [
            InlineKeyboardButton("1️⃣ 1 Share", callback_data=f"stock_buy_{ticker}_1"),
            InlineKeyboardButton("5️⃣ 5 Shares", callback_data=f"stock_buy_{ticker}_5"),
            InlineKeyboardButton("🔟 10 Shares", callback_data=f"stock_buy_{ticker}_10"),
        ],
        [InlineKeyboardButton("« Back to Market", callback_data="stock_back_to_market")]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(detail_text, parse_mode="Markdown", reply_markup=reply_markup)


async def stock_buy_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle stock purchase from inline buttons."""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await query.edit_message_text("❌ Use /start first.")
        return
    
    data = query.data
    if not data.startswith("stock_buy_"):
        return
    
    parts = data.replace("stock_buy_", "").split("_")
    if len(parts) != 2:
        await query.edit_message_text("❌ Invalid purchase request.")
        return
    
    ticker = parts[0]
    try:
        shares = int(parts[1])
    except ValueError:
        await query.edit_message_text("❌ Invalid share amount.")
        return
    
    # Max 10 shares per transaction
    if shares > 10 or shares < 1:
        await query.edit_message_text("❌ Can only buy 1-10 shares at a time.")
        return
    
    if ticker not in STOCKS:
        await query.edit_message_text("❌ Invalid ticker.")
        return
    
    cfg = STOCKS[ticker]
    price = _get_price(ticker)
    
    # Calculate cost with 1.5% fee
    fee_rate = 0.015
    base_cost = price * shares
    fee = base_cost * fee_rate
    total_cost = int(base_cost + fee)
    
    # Check if player has enough yen
    if player["yen"] < total_cost:
        await query.edit_message_text(
            f"❌ *Not enough yen!*\n\n"
            f"💰 Cost: *¥{total_cost:,}* (incl. 1.5% fee)\n"
            f"👛 Wallet: *¥{player['yen']:,}*",
            parse_mode="Markdown"
        )
        return
    
    # Execute buy
    update_player(user_id, yen=player["yen"] - total_cost)
    
    existing = _get_holding(user_id, ticker)
    old_shares = existing.get("shares", 0)
    old_avg = existing.get("avg_cost", price)
    new_shares = old_shares + shares
    new_avg = ((old_avg * old_shares) + (price * shares)) / new_shares
    
    col("stock_holdings").update_one(
        {"user_id": user_id, "ticker": ticker},
        {"$set": {
            "user_id": user_id,
            "ticker": ticker,
            "shares": new_shares,
            "avg_cost": round(new_avg, 2),
            "bought_at": existing.get("bought_at") or datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }},
        upsert=True
    )
    
    # Tiny upward nudge on buy
    nudge_price(ticker, 0.001 * shares / 100)
    
    # Confirmation message with back button
    confirm_text = (
        f"✅ *SHARES PURCHASED!*\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{cfg['emoji']} *{cfg['name']}* (`{ticker}`)\n\n"
        f"📦 Shares bought: *{shares}*\n"
        f"💰 Price/share: *¥{price:,.2f}*\n"
        f"💸 Total spent: *¥{total_cost:,}* (incl. 1.5% fee)\n"
        f"👛 Balance left: *¥{player['yen'] - total_cost:,}*\n"
        f"📊 You now own: *{new_shares} shares*"
    )
    
    keyboard = [[InlineKeyboardButton("« Back to Market", callback_data="stock_back_to_market")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(confirm_text, parse_mode="Markdown", reply_markup=reply_markup)


async def stock_back_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle back to market button."""
    query = update.callback_query
    await query.answer()
    
    # Just re-show the market
    user_id = update.effective_user.id
    player = get_player(user_id)
    if not player:
        await query.edit_message_text("❌ Use /start first.")
        return
    
    lines = ["Select an index to inspect financial parameters:", ""]
    
    for i, ticker in enumerate(TICKER_LIST, 1):
        cfg = STOCKS[ticker]
        history = _get_history(ticker)
        price = history[-1] if history else cfg["base_price"]
        prev = history[-2] if len(history) >= 2 else price
        chg_pct = ((price - prev) / prev * 100) if prev else 0
        arrow = "📈" if chg_pct >= 0 else "📉"
        sign = "+" if chg_pct >= 0 else ""
        
        lines.append(f"{i}) {arrow} {cfg['name']} ({ticker}) - {int(price)} 💠 ({sign}{chg_pct:.0f}%)")
    
    keyboard = []
    for i, ticker in enumerate(TICKER_LIST, 1):
        keyboard.append([InlineKeyboardButton(f"{i}) {ticker}", callback_data=f"stock_select_{ticker}")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text("\n".join(lines), reply_markup=reply_markup)
