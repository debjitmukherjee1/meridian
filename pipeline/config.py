"""
Central configuration for the Meridian pipeline.
Multi-market: India (default), USA, UK, Japan.
Everything tunable lives here so you never hunt through the scripts.
"""
import os

# --- Markets ---------------------------------------------------------------
# 'default' controls which market the site opens on.
DEFAULT_MARKET = "IN"
MARKETS = {
    "IN": {"name": "India",          "index": "NIFTY 50",   "currency": "₹", "suffix": ".NS"},
    "US": {"name": "United States",  "index": "S&P 500",    "currency": "$", "suffix": ""},
    "UK": {"name": "United Kingdom", "index": "FTSE 100",   "currency": "£", "suffix": ".L"},
    "JP": {"name": "Japan",          "index": "Nikkei 225", "currency": "¥", "suffix": ".T"},
}

# --- Watchlists per market: (ticker, company, sector) ----------------------
# Small, representative baskets. Yahoo Finance's quote endpoint handles all
# four markets in one batched call per market.
WATCHLISTS = {
    "IN": [
        ("RELIANCE",  "Reliance Industries", "Energy"),
        ("TCS",       "Tata Consultancy",    "Technology"),
        ("INFY",      "Infosys",             "Technology"),
        ("HDFCBANK",  "HDFC Bank",           "Financials"),
        ("ICICIBANK", "ICICI Bank",          "Financials"),
        ("HINDUNILVR","Hindustan Unilever",  "Consumer Staples"),
        ("TMPV",      "Tata Motors Passenger Vehicles", "Consumer Discretionary"),
        ("SUNPHARMA", "Sun Pharma",          "Healthcare"),
    ],
    "US": [
        ("AAPL", "Apple",          "Technology"),
        ("MSFT", "Microsoft",      "Technology"),
        ("JPM",  "JPMorgan Chase", "Financials"),
        ("V",    "Visa",           "Financials"),
        ("XOM",  "Exxon Mobil",    "Energy"),
        ("AMZN", "Amazon",         "Consumer Discretionary"),
        ("KO",   "Coca-Cola",      "Consumer Staples"),
        ("PFE",  "Pfizer",         "Healthcare"),
    ],
    "UK": [
        ("SHEL", "Shell",          "Energy"),
        ("BP",   "BP",             "Energy"),
        ("HSBA", "HSBC",           "Financials"),
        ("LLOY", "Lloyds Banking", "Financials"),
        ("AZN",  "AstraZeneca",    "Healthcare"),
        ("ULVR", "Unilever",       "Consumer Staples"),
        ("RIO",  "Rio Tinto",      "Materials"),
        ("VOD",  "Vodafone",       "Technology"),
    ],
    "JP": [
        ("7203", "Toyota Motor",    "Consumer Discretionary"),
        ("6758", "Sony Group",      "Technology"),
        ("9984", "SoftBank Group",  "Technology"),
        ("8306", "Mitsubishi UFJ",  "Financials"),
        ("9432", "NTT",             "Technology"),
        ("4502", "Takeda Pharma",   "Healthcare"),
        ("6501", "Hitachi",         "Industrials"),
        ("8058", "Mitsubishi Corp", "Energy"),
    ],
}

def sectors_for(market):
    return sorted({s for _, _, s in WATCHLISTS[market]})

# --- Sentiment Index weights (must sum to 1.0) -----------------------------
# No retail-social component: StockTwits' public feed is now behind a
# Cloudflare bot challenge, so this is a news+macro sentiment index.
SENTIMENT_WEIGHTS = {
    "news":  0.60,   # GDELT tone + Groq scoring
    "macro": 0.40,   # GDELT geo-political / macro theme overlay
}

# --- Valuation fusion ------------------------------------------------------
SENTIMENT_TILT_K = 0.15
NEUTRAL_SENTIMENT = 50.0

# --- Base fair value assumptions -------------------------------------------
DCF_TERMINAL_GROWTH = 0.025
DCF_DISCOUNT_RATE   = 0.09
DCF_YEARS           = 5

# --- Historical sector volatility baselines --------------------------------
# HOW the reasoning stays honest: each sector has a typical event-driven move
# band derived from historical behaviour. The forecast RANGE shown to users is
# anchored to these numbers (scaled by event severity), NOT invented by the AI.
# The AI decides DIRECTION (bullish/bearish) and writes the narrative; the
# MAGNITUDE band is fixed here from history.
#
# SECTOR_EVENT_VOL[sector][event_type] = (low%, high%) typical move in a MAJOR
# event of that type.
EVENT_TYPES = ["geopolitical_supply", "rates", "demand_shock", "regulatory", "default"]

SECTOR_EVENT_VOL = {
    "Energy": {
        "geopolitical_supply": (8, 18),   # Gulf / war supply shock
        "demand_shock":        (5, 12),
        "rates":               (2, 5),
        "regulatory":          (3, 8),
        "default":             (3, 7),
    },
    "Financials": {
        "rates":               (4, 10),   # most rate-sensitive
        "geopolitical_supply": (2, 6),
        "regulatory":          (3, 9),
        "demand_shock":        (3, 7),
        "default":             (2, 5),
    },
    "Technology": {
        "rates":               (5, 12),   # long-duration, rate-sensitive
        "regulatory":          (4, 10),
        "demand_shock":        (4, 9),
        "geopolitical_supply": (2, 6),
        "default":             (3, 7),
    },
    "Consumer Discretionary": {
        "demand_shock":        (5, 11),
        "rates":               (4, 9),
        "geopolitical_supply": (3, 7),
        "regulatory":          (2, 6),
        "default":             (3, 7),
    },
    "Consumer Staples": {
        "demand_shock":        (2, 5),    # defensive, low beta
        "rates":               (2, 4),
        "geopolitical_supply": (2, 5),
        "regulatory":          (2, 5),
        "default":             (1, 4),
    },
    "Healthcare": {
        "regulatory":          (4, 10),   # policy / approval driven
        "demand_shock":        (2, 5),
        "rates":               (2, 5),
        "geopolitical_supply": (1, 4),
        "default":             (2, 5),
    },
    "Materials": {
        "geopolitical_supply": (6, 14),
        "demand_shock":        (5, 11),
        "rates":               (3, 7),
        "regulatory":          (3, 7),
        "default":             (3, 8),
    },
    "Industrials": {
        "demand_shock":        (4, 9),
        "geopolitical_supply": (3, 8),
        "rates":               (3, 7),
        "regulatory":          (2, 6),
        "default":             (3, 6),
    },
}

def vol_band(sector, event_type):
    s = SECTOR_EVENT_VOL.get(sector, {})
    return s.get(event_type, s.get("default", (2, 6)))

# --- Output location -------------------------------------------------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "site", "data")

# --- API keys (None => mock mode) ------------------------------------------
GROQ_KEY = os.environ.get("GROQ_KEY")
FRED_KEY = os.environ.get("FRED_KEY")

# Market data (Yahoo Finance) needs no key. GROQ_KEY is the only remaining
# "do we have real credentials" signal, so it alone gates mock mode.
MOCK_MODE = GROQ_KEY is None

# --- MacroLens (World Bank / Frankfurter / FRED) ----------------------------
# World Bank's ISO2 country code for the UK is "GB", not our internal "UK".
WORLD_BANK_COUNTRY = {"IN": "IN", "US": "US", "UK": "GB", "JP": "JP"}

# World Bank indicator codes, keyless, annual.
WORLD_BANK_INDICATORS = {
    "cpi":          {"code": "FP.CPI.TOTL.ZG",     "label": "CPI Inflation (YoY)", "unit": "%"},
    "gdp_growth":   {"code": "NY.GDP.MKTP.KD.ZG",  "label": "Real GDP Growth",      "unit": "%"},
    "unemployment": {"code": "SL.UEM.TOTL.ZS",     "label": "Unemployment",         "unit": "%"},
}
MACRO_YEARS = 5              # target number of annual points per indicator
MACRO_FETCH_YEARS = 10       # years of history requested, to absorb World Bank's reporting lag

# FRED series per market for the central-bank policy rate. None => always use
# manual_rates.json (no FRED series exists for India's RBI repo rate — it
# isn't part of the OECD Main Economic Indicators set FRED mirrors).
FRED_POLICY_RATE_SERIES = {
    "IN": None,
    "US": "FEDFUNDS",           # Effective Federal Funds Rate, monthly
    # UK: BOERUKM was tried first but the Bank of England discontinued it in
    # January 2017 (confirmed live: a real API call returns zero
    # observations for any recent window, every single day, forever) — set
    # to None rather than retry a call that can never succeed.
    "UK": None,
    "JP": "IRSTCB01JPM156N",    # Immediate Rates: Central Bank Rate, OECD MEI, monthly
}
FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
# A FRED series can have real data that's simply stopped updating (found
# live: IRSTCB01JPM156N's most recent point was ~2.5 years old, silently
# showing a stale rate). Reject anything older than this many days.
FRED_MAX_STALENESS_DAYS = 180

# Frankfurter (ECB reference rates, keyless) FX pair per market, vs USD.
# US has none: USD is Meridian's own reference currency for this comparison.
FX_PAIRS = {
    "IN": {"from": "USD", "to": "INR", "label": "INR per USD"},
    "UK": {"from": "GBP", "to": "USD", "label": "USD per GBP"},
    "JP": {"from": "USD", "to": "JPY", "label": "JPY per USD"},
}
FX_LOOKBACK_DAYS = 365

MANUAL_RATES_PATH = os.path.join(os.path.dirname(__file__), "manual_rates.json")
