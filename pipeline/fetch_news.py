"""
fetch_news.py — news headlines + tone + macro/geo themes from GDELT (fully free).

GDELT DOC 2.0 API returns articles with a 'tone' score and supports theme
filtering (e.g. ECON_*, MILITARY, TRADE) — this is what powers the
macro/geo-political overlay. Docs: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/

In MOCK_MODE returns curated sample headlines.
"""
import random
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

# Themes GDELT tracks that we map to a macro/geo mood tag
MACRO_THEMES = [
    "Trade tensions dominate headlines — risk-off tone",
    "Central-bank commentary steadies markets",
    "Geopolitical conflict raises energy-sector risk",
    "Easing inflation data lifts broad sentiment",
]


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


def _live_news():
    """One broad query per run keeps us well within GDELT's free access."""
    items = []
    params = {
        "query": "(stocks OR earnings OR market) sourcelang:english",
        "mode": "artlist", "maxrecords": 40, "format": "json", "sort": "hybridrel",
    }
    data = requests.get(GDELT_DOC, params=params, timeout=20).json()
    for art in data.get("articles", []):
        items.append({
            "title": art.get("title", "").strip(),
            "sector": "Market",  # TODO: map keyword->sector for finer tagging
            "tone": float(art.get("tone", 0) or 0),
            "url": art.get("url", "#"),
        })
    # macro theme: average tone -> plain-English tag
    avg = sum(i["tone"] for i in items) / max(len(items), 1)
    theme = ("Easing conditions lift broad sentiment" if avg > 1 else
             "Risk-off tone across headlines" if avg < -1 else
             "Mixed macro signals; markets range-bound")
    return items[:12], theme


def fetch_all(market="US"):
    if config.MOCK_MODE:
        return _mock_news(market)
    try:
        return _live_news()
    except Exception as e:
        print(f"[news] GDELT failed ({e}); using mock fallback")
        return _mock_news(market)


if __name__ == "__main__":
    import json
    items, theme = fetch_all()
    print(theme)
    print(json.dumps(items, indent=2))
