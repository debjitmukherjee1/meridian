"""
fetch_market.py — prices + fundamentals from Yahoo Finance's unofficial
quote API (cookie+crumb handshake). Covers all four markets; Finnhub was
dropped because its free tier only covers US-listed tickers (confirmed live:
non-US suffixed symbols returned "You don't have access to this resource.").
See pipeline/SOURCES.md for the full trade-off writeup.

This is an undocumented endpoint, not a registered API product (the crumb
endpoint literally has "/test/" in its path) — usable but not bulletproof.
In MOCK_MODE (no GROQ_KEY) it returns deterministic sample numbers so the
whole pipeline runs offline.
"""
import random
import time
import config

try:
    import requests
except ImportError:
    requests = None

# A browser-like User-Agent is load-bearing, not cosmetic: the crumb endpoint
# returns 429 "Edge: Too Many Requests" for the default python-requests UA.
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
HEADERS = {"User-Agent": USER_AGENT}

# query1 first, query2 as a fallback host if query1 fails outright.
QUOTE_HOSTS = ["query1.finance.yahoo.com", "query2.finance.yahoo.com"]

# (session, crumb) is fetched lazily once per process and reused across every
# fetch_all() call (run_all.py calls this once per market == 4x per run).
_session_crumb = None


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
        # net debt can go either way -- some companies are net-cash
        "net_debt_per_share": round(price * random.uniform(-0.1, 0.3), 2),
    }


def _retry(fn, attempts=3, backoff=(1, 2)):
    """Call fn() up to `attempts` times total, sleeping `backoff[i]` seconds
    between attempts, before letting the last exception propagate."""
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if i < attempts - 1:
                time.sleep(backoff[i])
    raise last_exc


def _request_with_host_fallback(path, params, session):
    """GET `path` against query1 then query2, each attempt retried with
    backoff, before giving up."""
    last_exc = None
    for host in QUOTE_HOSTS:
        url = f"https://{host}{path}"

        def _do(url=url):
            r = session.get(url, params=params, headers=HEADERS, timeout=15)
            r.raise_for_status()
            return r

        try:
            return _retry(_do)
        except Exception as e:
            last_exc = e
    raise last_exc


def _handshake():
    """GET https://fc.yahoo.com to set a cookie (its 404 body is expected and
    ignored), then GET /v1/test/getcrumb on the same session for the crumb.
    Returns (session, crumb)."""
    session = requests.Session()

    def _set_cookie():
        session.get("https://fc.yahoo.com", headers=HEADERS, timeout=15)

    _retry(_set_cookie)

    r = _request_with_host_fallback("/v1/test/getcrumb", {}, session)
    crumb = r.text.strip()
    if not crumb:
        raise RuntimeError("empty crumb from Yahoo handshake")
    # Yahoo's crumb endpoint returns HTTP 200 (not an error status) with the
    # literal body "Edge: Too Many Requests" when rate-limited -- a non-empty
    # string that would otherwise sail past the check above and get cached
    # as if it were a real, usable crumb, burning retries against a crumb
    # that can never succeed until the reset-on-failure path eventually
    # catches it downstream.
    if "too many requests" in crumb.lower():
        raise RuntimeError(f"Yahoo crumb endpoint rate-limited: {crumb!r}")
    return session, crumb


def _get_session_crumb():
    global _session_crumb
    if _session_crumb is None:
        _session_crumb = _handshake()  # not cached on failure -> retried next call
    return _session_crumb


def _yahoo_symbol(ticker, market):
    return f"{ticker}{config.MARKETS[market]['suffix']}"


def _fetch_quotes(symbols, session, crumb):
    """Batch quote call. Returns {yahoo_symbol: quote_dict}."""
    params = {"symbols": ",".join(symbols), "crumb": crumb}
    r = _request_with_host_fallback("/v7/finance/quote", params, session)
    results = (r.json().get("quoteResponse") or {}).get("result") or []
    return {item["symbol"]: item for item in results if "symbol" in item}


def _raw(field):
    """Yahoo's quoteSummary wraps numeric fields as {"raw": ..., "fmt": ...}."""
    return field.get("raw") if isinstance(field, dict) else None


def _fetch_extra_financials(yahoo_symbol, shares_out, session, crumb):
    """FCF, EBITDA and net debt aren't on the quote endpoint; one per-symbol
    quoteSummary call (financialData module) covers all three -- no extra
    request needed beyond what FCF alone already required. Returns a dict
    with fcf_per_share / ebitda_per_share / net_debt_per_share, each a float
    or None if unavailable. Never raises on missing data, only on
    request-level failure (caller catches)."""
    empty = {"fcf_per_share": None, "ebitda_per_share": None, "net_debt_per_share": None}
    if not shares_out:
        return empty
    params = {"modules": "financialData", "crumb": crumb}
    r = _request_with_host_fallback(f"/v10/finance/quoteSummary/{yahoo_symbol}",
                                     params, session)
    result = ((r.json().get("quoteSummary") or {}).get("result") or [])
    if not result:
        return empty
    fd = result[0].get("financialData") or {}

    fcf_raw = _raw(fd.get("freeCashflow"))
    ebitda_raw = _raw(fd.get("ebitda"))
    debt_raw = _raw(fd.get("totalDebt"))
    cash_raw = _raw(fd.get("totalCash"))

    net_debt_per_share = None
    if debt_raw is not None and cash_raw is not None:
        net_debt_per_share = (debt_raw - cash_raw) / shares_out

    return {
        "fcf_per_share": (fcf_raw / shares_out) if fcf_raw is not None else None,
        "ebitda_per_share": (ebitda_raw / shares_out) if ebitda_raw is not None else None,
        "net_debt_per_share": net_debt_per_share,
    }


def _quote_to_company(ticker, name, sector, yahoo_symbol, quote, session, crumb):
    price = quote.get("regularMarketPrice") or 0
    # LSE tickers report price in pence (GBp) but EPS in whole GBP.
    if quote.get("currency") == "GBp" and price:
        price = price / 100
    eps = quote.get("epsTrailingTwelveMonths") or 0
    pe = quote.get("trailingPE")  # used directly, not recomputed
    shares_out = quote.get("sharesOutstanding")

    try:
        extra = _fetch_extra_financials(yahoo_symbol, shares_out, session, crumb)
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        if status in (401, 403):
            # This specific request failing with an auth error means the
            # CRUMB itself is bad, not just this one ticker -- reset the
            # module-level cache so the next ticker (and, since the crumb
            # is cached for the whole process, every later market too) gets
            # a fresh handshake instead of quietly repeating the same
            # failure for the rest of the run.
            global _session_crumb
            _session_crumb = None
        print(f"[market] {ticker} extra-financials lookup failed ({e}); "
              f"leaving fcf/ebitda/net_debt per-share as None")
        extra = {"fcf_per_share": None, "ebitda_per_share": None, "net_debt_per_share": None}

    return {
        "ticker": ticker, "name": name, "sector": sector,
        "price": price, "eps": eps, "pe": pe,
        **extra,
    }


def fetch_all(market):
    watchlist = config.WATCHLISTS[market]
    if config.MOCK_MODE:
        return [_mock_company(t, n, s) for t, n, s in watchlist]

    out = []
    symbol_map = {_yahoo_symbol(t, market): (t, n, s) for t, n, s in watchlist}

    try:
        session, crumb = _get_session_crumb()
        quotes = _fetch_quotes(list(symbol_map.keys()), session, crumb)
    except Exception as e:
        # Whole batch failed after retries/host-fallback -> mock every ticker
        # in this market, matching the per-ticker fallback logging style.
        # Drop the cached crumb too: if it went bad mid-run, later markets in
        # this same process get a fresh handshake instead of repeating the
        # same failure for the rest of the run.
        global _session_crumb
        _session_crumb = None
        for ticker, name, sector in watchlist:
            print(f"[market] {ticker} failed ({e}); using mock fallback")
            out.append(_mock_company(ticker, name, sector))
        return out

    for yahoo_symbol, (ticker, name, sector) in symbol_map.items():
        quote = quotes.get(yahoo_symbol)
        if quote is None:
            print(f"[market] {ticker} failed (missing from Yahoo quote response); "
                  f"using mock fallback")
            out.append(_mock_company(ticker, name, sector))
            continue
        try:
            out.append(_quote_to_company(ticker, name, sector, yahoo_symbol,
                                          quote, session, crumb))
        except Exception as e:
            print(f"[market] {ticker} failed ({e}); using mock fallback")
            out.append(_mock_company(ticker, name, sector))
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(fetch_all(config.DEFAULT_MARKET), indent=2))
