"""
fetch_news.py — market-specific headlines from Google News RSS (free, keyless).

Why not GDELT any more (changed 17-Nov-2026):
  * GDELT's DOC API rate-limits GitHub's shared runner IPs; most days since at
    least 8-Oct-2026 it returned HTTP 429 and the pipeline silently published
    the hard-coded sample headlines instead.
  * One global query ("stocks OR earnings OR market") fed all four markets the
    same 12 headlines, so India was scored on US news and vice versa.
  * The artlist endpoint carries no 'tone' field, so every live headline had a
    tone of 0.0 and the fallback scorer returned exactly 50 (Neutral).

Now each market runs its own queries (Google News RSS, with Bing News
RSS as a per-query fallback) (config.NEWS_QUERIES): one broad-market
query plus one per sector, localised with Google News' hl/gl/ceid parameters.
A headline's sector is the sector of the query that found it, so there is no
substring tagging (the old tagger matched Visa's ticker "V" inside "Nvidia"
and filed it under Financials).

There is NO mock fallback here. If a market's news cannot be fetched, this
raises; run_all.py then leaves that market's previous data untouched and the
Actions run goes red. Publishing sample headlines as if they were today's news
is the failure this file exists to prevent.
"""
import email.utils
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import config

try:
    import requests
except ImportError:
    requests = None

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
BING_NEWS_RSS = "https://www.bing.com/news/search"
UA = {"User-Agent": "Mozilla/5.0 (compatible; MeridianBot/1.0; +https://github.com/debjitmukherjee1/meridian)"}

EVENT_KEYWORDS = {
    "geopolitical_supply": ["conflict", "war", "geopolit", "sanction", "supply", "gulf", "strait"],
    "rates": ["rate", "inflation", "central bank", "fed", "rbi", "boe", "boj", "yield"],
    "regulatory": ["regulat", "probe", "policy", "antitrust", "tariff", "ban", "curb", "export control", "scandal", "investigation"],
    "demand_shock": ["demand", "spending", "recession", "growth", "consumer"],
}
EVENT_THEME_LABEL = {
    "geopolitical_supply": "Geopolitical conflict raises energy-sector risk",
    "rates": "Rate-policy commentary dominates headlines",
    "regulatory": "Regulatory scrutiny dominates today's headlines",
    "demand_shock": "Consumer demand signals dominate headlines",
}


def _word_pattern(w):
    # Stems (geopolit, regulat) match as prefixes; whole words allow a plural.
    if w in ("geopolit", "regulat"):
        return re.compile(r"\b" + re.escape(w))
    return re.compile(r"\b" + re.escape(w) + r"(s|es)?\b")


_PATTERNS = {w: _word_pattern(w) for ws in EVENT_KEYWORDS.values() for w in ws}


def _dominant_event_theme(items):
    # Whole-word matching: plain substring tests made "ban" fire on "bank"
    # and "rate" on "corporate", so every market read "regulatory".
    counts = {k: 0 for k in EVENT_KEYWORDS}
    for it in items:
        t = it["title"].lower()
        for event_type, words in EVENT_KEYWORDS.items():
            if any(_PATTERNS[w].search(t) for w in words):
                counts[event_type] += 1
    best = max(counts, key=counts.get)
    return EVENT_THEME_LABEL[best] if counts[best] > 0 else "Mixed macro signals; no single theme dominates"


# Stock-pick listicles and evergreen explainers are not news about a sector's
# mood; the model scores them as mildly positive ("3 Undervalued Tech Stocks"),
# which propped US Technology up on 20-Nov while the real headlines were
# negative. They are dropped before scoring.
_LISTICLE = re.compile(
    r"^\s*(\d+|three|four|five|six|seven|eight|nine|ten)\s+"
    r"([a-z&'-]+\s+){0,4}(stocks?|shares|picks|etfs?|funds|names|reasons|things|ways)\b"
    r"|\bstocks? to (buy|own|watch|hold)\b|\b(should you|is it time to) buy\b"
    r"|\btop \d+\b|\bbest .{0,25}stocks?\b|\bmillionaire|\bforever\b"
    r"|\bindex today\b|\blive (updates|blog)\b",
    re.I)


def is_listicle(title):
    return bool(_LISTICLE.search(title))


def _clean_title(title):
    # Google News appends " - Publisher"; keep the publisher separately.
    if " - " in title:
        head, _, src = title.rpartition(" - ")
        return head.strip(), src.strip()
    return title.strip(), ""


def _parse_rss(content, source_fallback=""):
    root = ET.fromstring(content)
    out = []
    for it in root.findall(".//item"):
        title, source = _clean_title(it.findtext("title") or "")
        pub = it.findtext("pubDate")
        try:
            dt = email.utils.parsedate_to_datetime(pub) if pub else None
            if dt is not None and dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            dt = None
        out.append({"title": title, "source": source or source_fallback,
                    "url": it.findtext("link") or "#",
                    "published": dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if dt else None,
                    "_dt": dt})
    return out


def _get(url, params):
    """GET with backoff on HTTP 429 (Google News throttles bursts)."""
    for wait in (0, 10, 25):
        if wait:
            time.sleep(wait)
        r = requests.get(url, params=params, headers=UA, timeout=20)
        if r.status_code != 429:
            r.raise_for_status()
            return r.content
    r.raise_for_status()


def _google(query, market):
    loc = config.NEWS_LOCALE[market]
    return _parse_rss(_get(GOOGLE_NEWS_RSS, {"q": f"{query} when:{config.NEWS_LOOKBACK_DAYS}d",
                                              "hl": loc["hl"], "gl": loc["gl"], "ceid": loc["ceid"]}))


BING_MKT = {"IN": "en-IN", "US": "en-US", "UK": "en-GB", "JP": "en-US"}
_google_failures = 0          # consecutive Google failures this run
GOOGLE_BREAKER = 3            # after this many in a row, skip Google for the run


def _bing(query, market):
    """Bing News RSS ignores OR-syntax, so search each OR-term on its own
    (in the market's Bing edition) and merge. 23-Nov-2026: Google returned
    503 for every query and a single first-term Bing search found only 3-4
    UK/Japan headlines; per-term searching finds several times more."""
    out, seen = [], set()
    for term in [t.replace('"', "").strip() for t in query.split(" OR ")][:6]:
        try:
            items = _parse_rss(_get(BING_NEWS_RSS, {"q": term, "format": "rss",
                                                    "setmkt": BING_MKT[market]}), "Bing News")
        except Exception as e:
            print(f"[news] {market} Bing failed for '{term[:30]}' ({e})")
            continue
        for it in items:
            k = it["title"].lower()[:80]
            if k not in seen:
                seen.add(k)
                it["_bing"] = True
                out.append(it)
        time.sleep(0.5)
    return out


def _rss(query, market):
    """Google News first; Bing News if Google fails or returns nothing.
    A run that sees GOOGLE_BREAKER Google failures in a row stops asking it
    (otherwise 28 refused queries each wait out their retries)."""
    global _google_failures
    if _google_failures < GOOGLE_BREAKER:
        try:
            found = _google(query, market)
            _google_failures = 0
            if found:
                return found
        except Exception as e:
            _google_failures += 1
            note = "; skipping Google for the rest of this run" if _google_failures >= GOOGLE_BREAKER else ""
            print(f"[news] {market} Google failed for '{query[:40]}' ({e}){note}")
    return _bing(query, market)


def fetch_all(market):
    if requests is None:
        raise RuntimeError("requests is not installed")
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.NEWS_LOOKBACK_DAYS + 1)
    seen, items, failures = set(), [], []
    for sector, query in config.NEWS_QUERIES[market].items():
        try:
            found = _rss(query, market)
        except Exception as e:  # one bad query shouldn't sink the market
            failures.append(f"{sector}: {e}")
            continue
        finally:
            time.sleep(2.5)  # Google News throttles bursts
        bing_cutoff = cutoff - timedelta(days=config.NEWS_BING_EXTRA_DAYS)
        found = [f for f in found if f["_dt"] is None
                 or f["_dt"] >= (bing_cutoff if f.get("_bing") else cutoff)]
        found.sort(key=lambda f: f["_dt"] or cutoff, reverse=True)
        kept = 0
        for f in found:
            key = f["title"].lower()[:80]
            if key in seen or not f["title"] or is_listicle(f["title"]):
                continue
            seen.add(key)
            f.pop("_dt", None)
            f.pop("_bing", None)
            f["sector"] = sector
            f["tone"] = 0.0          # filled in by score_sentiment (model polarity)
            items.append(f)
            kept += 1
            if kept >= config.NEWS_PER_SECTOR:
                break
    for f in failures:
        print(f"[news] {market} query failed -> {f}")
    sectors_with_news = {i["sector"] for i in items}
    if "Market" not in sectors_with_news or len(sectors_with_news) < 3:
        raise RuntimeError(f"{market}: too little live news ({len(items)} headlines across "
                           f"{len(sectors_with_news)} buckets); refusing to publish a thin read")
    return items, _dominant_event_theme(items)


if __name__ == "__main__":
    import json, sys
    m = sys.argv[1] if len(sys.argv) > 1 else "US"
    items, theme = fetch_all(m)
    print(theme)
    print(json.dumps(items, indent=2)[:4000])
