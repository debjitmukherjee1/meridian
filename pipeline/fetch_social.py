"""
fetch_social.py — retail social sentiment.

Primary: StockTwits public symbol stream (users tag messages Bullish/Bearish).
Secondary: Reddit (optional; free tier behind approval form as of 2026).

Returns a per-ticker social score 0-100 (50 = neutral).
StockTwits: https://api.stocktwits.com/developers/docs
"""
import random
import config

try:
    import requests
except ImportError:
    requests = None

ST_URL = "https://api.stocktwits.com/api/2/streams/symbol/{sym}.json"


def _mock_social(ticker):
    random.seed(ticker + "social")
    return round(random.uniform(30, 75), 1)


def _live_social(ticker):
    """Fraction of tagged messages that are Bullish -> 0-100."""
    r = requests.get(ST_URL.format(sym=ticker), timeout=15)
    r.raise_for_status()
    msgs = r.json().get("messages", [])
    bull = bear = 0
    for m in msgs:
        s = (m.get("entities", {}) or {}).get("sentiment") or {}
        basic = s.get("basic")
        if basic == "Bullish":
            bull += 1
        elif basic == "Bearish":
            bear += 1
    total = bull + bear
    if total == 0:
        return 50.0
    return round(100 * bull / total, 1)


def fetch_all(tickers):
    scores = {}
    for t in tickers:
        if config.MOCK_MODE:
            scores[t] = _mock_social(t)
        else:
            try:
                scores[t] = _live_social(t)
            except Exception as e:
                print(f"[social] {t} failed ({e}); mock fallback")
                scores[t] = _mock_social(t)
    return scores


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_all([t for t, _, _ in config.WATCHLIST]), indent=2))
