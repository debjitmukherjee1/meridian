"""
fetch_news.py — news headlines + tone + macro/geo themes from GDELT (fully free).

GDELT DOC 2.0 API returns articles with a 'tone' score. There's no cheap way
to get per-sector news from a single broad query, so headlines are tagged by
scanning for a watchlist company/ticker mention first, then a coarse
industry-keyword fallback, with "Market" (broad/unsectored) only as a last
resort -- see _tag_sector().

In MOCK_MODE returns curated sample headlines.
"""
import config

try:
    import requests
except ImportError:
    requests = None

GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"

MOCK_HEADLINES = [
    ("Chipmakers rally as AI demand outpaces supply", "Technology", 3.4),
    ("Regulators open probe into big-tech ad practices", "Technology", -2.1),
    ("Consumer spending softens amid rate uncertainty", "Consumer Discretionary", -1.8),
    ("EV price war squeezes automaker margins", "Consumer Discretionary", -2.6),
    ("Banks post resilient quarterly earnings", "Financials", 2.2),
    ("Payment networks expand into emerging markets", "Financials", 1.9),
    ("Oil steadies as supply concerns ease", "Energy", 0.6),
    ("Staples firms hold pricing power through inflation", "Consumer Staples", 1.4),
    ("Drugmaker wins approval for key therapy", "Healthcare", 3.1),
    ("Geopolitical tension lifts safe-haven demand", "Energy", -1.2),
]

# Broad industry-keyword fallback for headlines that don't name a specific
# watchlist company -- deliberately coarse, just needs to beat a blanket
# "Market" default, not be exhaustive.
SECTOR_KEYWORDS = {
    "Technology": ["chip", "semiconductor", "software", "artificial intelligence",
                   " ai ", "cloud computing", "big-tech", "big tech"],
    "Energy": ["oil", "crude", "opec", "energy sector", "refinery", "drilling", "gas price"],
    "Financials": ["bank", "lender", "interest rate", "fed ", "rbi ", "boe ", "boj ",
                   "credit", "loan", "payment network"],
    "Healthcare": ["drug", "pharma", "therapy", "fda", "vaccine", "biotech", "hospital"],
    "Consumer Discretionary": ["automaker", "ev price", "retailer", "e-commerce"],
    "Consumer Staples": ["staples firm", "grocery", "packaged food", "beverage"],
    "Materials": ["mining", "metals", "commodity", "steel"],
    "Industrials": ["manufacturing", "factory", "industrial output", "logistics"],
}

# Same vocabulary sector_signals.classify_event() uses -- kept here too so
# _dominant_event_theme() can generate a theme string that actually round
# trips back through it correctly, instead of the generic tone-only phrasing
# that used to always fall through to "default" event typing.
EVENT_KEYWORDS = {
    "geopolitical_supply": ["conflict", "war", "geopolit", "sanction", "supply", "gulf", "strait"],
    "rates": ["rate", "inflation", "central bank", "fed", "rbi", "boe", "boj", "yield"],
    "regulatory": ["regulat", "probe", "policy", "antitrust", "tariff", "ban"],
    "demand_shock": ["demand", "spending", "recession", "growth", "consumer"],
}
EVENT_THEME_LABEL = {
    "geopolitical_supply": "Geopolitical conflict raises energy-sector risk",
    "rates": "Rate-policy commentary dominates headlines",
    "regulatory": "Regulatory scrutiny dominates today's headlines",
    "demand_shock": "Consumer demand signals dominate headlines",
}


def _tag_sector(title, market):
    t = title.lower()
    for ticker, name, sector in config.WATCHLISTS.get(market, []):
        if ticker.lower() in t or name.lower() in t:
            return sector
    for sector, words in SECTOR_KEYWORDS.items():
        if any(w in t for w in words):
            return sector
    return "Market"


def _dominant_event_theme(items):
    """Scan real headline titles for the same keyword vocabulary
    classify_event() uses. Returns a theme string that genuinely reflects
    what's in today's news (and correctly classifies downstream) if one
    category clearly dominates, else None -- caller falls back to the
    tone-only phrasing, which honestly IS "default" when nothing specific
    stands out rather than a forced, possibly-wrong category."""
    counts = {k: 0 for k in EVENT_KEYWORDS}
    for it in items:
        t = it["title"].lower()
        for event_type, words in EVENT_KEYWORDS.items():
            if any(w in t for w in words):
                counts[event_type] += 1
    best = max(counts, key=counts.get)
    return EVENT_THEME_LABEL[best] if counts[best] > 0 else None


def _mock_news(market="US"):
    items = []
    for title, sector, tone in MOCK_HEADLINES:
        items.append({
            "title": title, "sector": sector, "tone": tone,
            "url": "https://www.gdeltproject.org/",  # placeholder link
        })
    # Deterministic geopolitical theme for the demo so the Energy example
    # ("war -> crude -> bearish energy sentiment") is visible out of the box.
    theme = "Geopolitical conflict raises energy-sector risk"
    return items, theme


# The raw GDELT response is shared across all 4 markets -- the query isn't
# market-specific, and GDELT rate-limits to one request per 5 seconds, so
# fetching it once per process (not once per market) both avoids needless
# 429s and means sector-tagging below can be redone per-market against the
# SAME headlines without re-fetching.
_raw_articles_cache = None


def _fetch_raw_articles():
    global _raw_articles_cache
    if _raw_articles_cache is None:
        params = {
            "query": "(stocks OR earnings OR market) sourcelang:english",
            "mode": "artlist", "maxrecords": 40, "format": "json", "sort": "hybridrel",
        }
        r = requests.get(GDELT_DOC, params=params, timeout=20)
        r.raise_for_status()
        articles = r.json().get("articles", [])
        if not articles:
            # A valid-but-empty response (GDELT returns HTTP 200 + "{}" for
            # a quiet news window) must NOT be accepted as "today has no
            # news" -- that would silently flatten every company's news
            # score to neutral with no error signal. Treat it as a failure
            # so the caller's mock fallback engages instead.
            raise RuntimeError("GDELT returned zero articles")
        _raw_articles_cache = articles
    return _raw_articles_cache


def _live_news(market):
    articles = _fetch_raw_articles()
    items = []
    for art in articles[:40]:
        title = art.get("title", "").strip()
        items.append({
            "title": title,
            "sector": _tag_sector(title, market),
            "tone": float(art.get("tone", 0) or 0),
            "url": art.get("url", "#"),
        })
    items = items[:12]
    theme = _dominant_event_theme(items)
    if theme is None:
        avg = sum(i["tone"] for i in items) / max(len(items), 1)
        theme = ("Easing conditions lift broad sentiment" if avg > 1 else
                 "Risk-off tone across headlines" if avg < -1 else
                 "Mixed macro signals; markets range-bound")
    return items, theme


def fetch_all(market="US"):
    if config.MOCK_MODE:
        return _mock_news(market)
    try:
        return _live_news(market)
    except Exception as e:
        print(f"[news] GDELT failed ({e}); using mock fallback")
        return _mock_news(market)


if __name__ == "__main__":
    import json
    items, theme = fetch_all()
    print(theme)
    print(json.dumps(items, indent=2))
