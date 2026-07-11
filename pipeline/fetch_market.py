"""
fetch_market.py — prices + fundamentals from Finnhub (free tier: 60 calls/min).
In MOCK_MODE (no key) it returns deterministic sample numbers so the whole
pipeline runs offline.

Docs: https://finnhub.io/docs/api
"""
import random
import config

try:
    import requests
except ImportError:
    requests = None

BASE = "https://finnhub.io/api/v1"


def _mock_company(ticker, name, sector):
    random.seed(ticker)  # deterministic per ticker
    price = round(random.uniform(40, 400), 2)
    pe = round(random.uniform(12, 35), 1)
    eps = round(price / pe, 2)
    return {
        "ticker": ticker, "name": name, "sector": sector,
        "price": price, "eps": eps, "pe": pe,
        "ebitda_per_share": round(eps * random.uniform(1.3, 2.2), 2),
        "fcf_per_share": round(eps * random.uniform(0.6, 1.1), 2),
    }


def _live_company(ticker, name, sector):
    key = config.FINNHUB_KEY
    quote = requests.get(f"{BASE}/quote", params={"symbol": ticker, "token": key}, timeout=15).json()
    metric = requests.get(f"{BASE}/stock/metric",
                          params={"symbol": ticker, "metric": "all", "token": key}, timeout=15).json()
    m = metric.get("metric", {})
    price = quote.get("c") or 0
    eps = m.get("epsTTM") or 0
    pe = (price / eps) if eps else None
    return {
        "ticker": ticker, "name": name, "sector": sector,
        "price": price, "eps": eps, "pe": pe,
        "ebitda_per_share": m.get("ebitdaPerShareTTM"),
        "fcf_per_share": m.get("freeCashFlowPerShareTTM"),
    }


def fetch_all(market):
    out = []
    for ticker, name, sector in config.WATCHLISTS[market]:
        if config.MOCK_MODE:
            out.append(_mock_company(ticker, name, sector))
        else:
            try:
                out.append(_live_company(ticker, name, sector))
            except Exception as e:
                print(f"[market] {ticker} failed ({e}); using mock fallback")
                out.append(_mock_company(ticker, name, sector))
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_all(config.DEFAULT_MARKET), indent=2))
