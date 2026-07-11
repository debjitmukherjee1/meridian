"""
run_all.py — orchestrates the daily pipeline for ALL markets and writes
site/data/<MARKET>/*.json plus a manifest.json.

Runs end-to-end in MOCK_MODE (no API keys) so you can test offline, and in
live mode inside GitHub Actions when secrets are set. Every source has a mock
fallback, so one failing API never breaks the daily build.

Output layout:
  site/data/manifest.json                 -> markets list + default + updated_at
  site/data/IN/companies.json             -> per-market company valuations
  site/data/IN/sectors.json               -> per-market sector heatmap
  site/data/IN/signals.json               -> per-market sector-signal reasoning
  site/data/IN/news.json                  -> per-market news
  (same for US, UK, JP)

Usage:  python run_all.py
"""
import json
import os
from datetime import datetime, timezone

import config
import fetch_market
import fetch_news
import fetch_social
import score_sentiment
import build_valuation
import sector_signals


def _label(score):
    if score >= 60:
        return "Bullish"
    if score <= 40:
        return "Bearish"
    return "Neutral"


def run_market(market, updated):
    companies = fetch_market.fetch_all(market)
    news_items, macro_theme = fetch_news.fetch_all(market)
    social = fetch_social.fetch_all([c["ticker"] for c in companies])

    companies, macro = score_sentiment.build_sentiment(
        companies, social, news_items, macro_theme)
    companies = build_valuation.base_fair_value(companies)
    companies = build_valuation.sentiment_adjust(companies)

    # sector rollup
    bucket = {}
    for c in companies:
        bucket.setdefault(c["sector"], []).append(c["sentiment_index"])
    sectors = [{"name": s, "score": round(sum(v) / len(v)), "label": _label(sum(v) / len(v))}
               for s, v in sorted(bucket.items())]

    # the new sector-signals reasoning (main + supporting + vol-anchored range)
    signals = sector_signals.build_signals(market, sectors, macro_theme, news_items)

    mkt_dir = os.path.join(config.DATA_DIR, market)
    os.makedirs(mkt_dir, exist_ok=True)
    _write(mkt_dir, "companies.json",
           {"updated_at": updated, "market": market,
            "currency": config.MARKETS[market]["currency"], "companies": companies})
    _write(mkt_dir, "sectors.json",
           {"updated_at": updated, "market": market, "index": config.MARKETS[market]["index"],
            "macro_theme": macro_theme, "macro_score": macro, "sectors": sectors})
    _write(mkt_dir, "signals.json",
           {"updated_at": updated, "market": market,
            "macro_theme": macro_theme, "signals": signals})
    _write(mkt_dir, "news.json", {"updated_at": updated, "market": market, "items": news_items})

    return len(companies), len(sectors), len(signals)


def main():
    mode = "MOCK" if config.MOCK_MODE else "LIVE"
    print(f"=== Meridian pipeline ({mode} mode) ===")
    updated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    manifest = {"updated_at": updated, "default": config.DEFAULT_MARKET, "markets": []}
    for code, meta in config.MARKETS.items():
        nc, ns, nsig = run_market(code, updated)
        manifest["markets"].append({"code": code, "name": meta["name"],
                                    "index": meta["index"], "currency": meta["currency"]})
        print(f"  {code} ({meta['name']}): {nc} companies, {ns} sectors, {nsig} signals")

    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(os.path.join(config.DATA_DIR, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"Wrote manifest with {len(manifest['markets'])} markets -> "
          f"{os.path.normpath(config.DATA_DIR)}")


def _write(folder, name, obj):
    with open(os.path.join(folder, name), "w") as f:
        json.dump(obj, f, indent=2)


if __name__ == "__main__":
    main()
