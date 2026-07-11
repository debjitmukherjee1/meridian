"""
sector_signals.py — the "why" behind each sector's sentiment.

For every sector it produces:
  - a bullish/bearish/neutral read
  - a MAIN impact (the dominant driver)
  - 2-3 SUPPORTING drivers when the picture is complex
  - each driver carries a forecast RANGE anchored to HISTORICAL volatility
    (config.SECTOR_EVENT_VOL), scaled by event severity — never a made-up
    single number.

Direction + narrative come from the AI (Gemini). Magnitude comes from history.
That split is what keeps the reasoning defensible.
"""
import json
import config

try:
    import requests
except ImportError:
    requests = None

GEMINI_URL = ("https://generativelanguage.googleapis.com/v1beta/"
              "models/gemini-2.5-flash:generateContent")


def classify_event(macro_theme):
    """Map today's macro theme string to an event_type used for vol lookup."""
    t = (macro_theme or "").lower()
    if any(w in t for w in ["conflict", "war", "geopolit", "sanction", "supply", "gulf", "strait"]):
        return "geopolitical_supply"
    if any(w in t for w in ["rate", "inflation", "central bank", "fed", "rbi", "boe", "boj", "yield"]):
        return "rates"
    if any(w in t for w in ["regulat", "probe", "policy", "antitrust", "tariff", "ban"]):
        return "regulatory"
    if any(w in t for w in ["demand", "spending", "recession", "growth", "consumer"]):
        return "demand_shock"
    return "default"


def severity_from_sentiment(score):
    """Distance from neutral (50) => how severe/one-sided the mood is (0..1)."""
    return min(1.0, abs(score - 50) / 50)


def forecast_range(sector, event_type, score):
    """Historical vol band, scaled by severity, signed by bullish/bearish read."""
    lo, hi = config.vol_band(sector, event_type)
    sev = severity_from_sentiment(score)
    # scale the band by severity so a mildly-off sector shows a tighter range
    lo_s = round(lo * (0.5 + 0.5 * sev), 1)
    hi_s = round(hi * (0.5 + 0.5 * sev), 1)
    sign = "-" if score < 50 else "+"
    return {"low": lo_s, "high": hi_s, "direction": sign,
            "text": f"{sign}{lo_s}% to {sign}{hi_s}%"}


# ---- narrative (AI in live mode, template in mock) ------------------------
_MOCK_DRIVERS = {
    ("Energy", "geopolitical_supply"): [
        "Supply-route risk from conflict pushes crude higher; refiners and upstream names diverge",
        "Freight and insurance costs rising on shipping-lane threats",
        "Strategic-reserve releases could cap upside, adding two-way risk",
    ],
    ("Financials", "rates"): [
        "Rate path drives net-interest-margin expectations",
        "Credit-cost worries if growth slows alongside tightening",
        "Bond-portfolio mark-to-market swings add volatility",
    ],
    ("Technology", "rates"): [
        "Long-duration cash flows discounted harder as yields rise",
        "Enterprise IT budgets sensitive to macro slowdown",
    ],
}


def _mock_narrative(sector, event_type, score):
    key = (sector, event_type)
    if key in _MOCK_DRIVERS:
        drivers = _MOCK_DRIVERS[key]
    else:
        read = "supported by" if score >= 50 else "pressured by"
        drivers = [f"{sector} sentiment {read} the prevailing {event_type.replace('_',' ')} backdrop"]
    return drivers[0], drivers[1:3]


def _ai_narrative(sector, event_type, score, headlines):
    read = "bullish" if score >= 55 else "bearish" if score <= 45 else "mixed"
    prompt = (
        f"You are a sell-side sector strategist. The {sector} sector currently reads "
        f"{read} (sentiment {score}/100) driven by a {event_type.replace('_',' ')} event. "
        f"Using ONLY these headlines, write:\n"
        f"1) ONE sentence naming the MAIN impact on the sector.\n"
        f"2) Up to THREE short supporting drivers, only if the picture is genuinely complex.\n"
        f"Be specific and factual. Do NOT invent numbers. Return JSON: "
        f'{{"main": "...", "supporting": ["...", "..."]}}\n\nHeadlines:\n'
        + "\n".join(f"- {h}" for h in headlines[:8])
    )
    body = {"contents": [{"parts": [{"text": prompt}]}]}
    r = requests.post(GEMINI_URL, params={"key": config.GEMINI_KEY}, json=body, timeout=30)
    r.raise_for_status()
    txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    start, end = txt.find("{"), txt.rfind("}")
    obj = json.loads(txt[start:end + 1])
    return obj.get("main", ""), obj.get("supporting", [])[:3]


def build_signals(market, sectors, macro_theme, news_items):
    """Return list of per-sector signal objects for the Sector Signals tab."""
    event_type = classify_event(macro_theme)
    signals = []
    for s in sectors:
        name, score = s["name"], s["score"]
        heads = [n["title"] for n in news_items if n.get("sector") in (name, "Market")]
        if config.MOCK_MODE or config.GEMINI_KEY is None:
            main, supporting = _mock_narrative(name, event_type, score)
        else:
            try:
                main, supporting = _ai_narrative(name, event_type, score, heads)
            except Exception as e:
                print(f"[signals] {name} AI failed ({e}); template fallback")
                main, supporting = _mock_narrative(name, event_type, score)

        drivers = [{"role": "main", "text": main,
                    "forecast": forecast_range(name, event_type, score)}]
        for sup in supporting:
            drivers.append({"role": "supporting", "text": sup,
                            "forecast": forecast_range(name, event_type, score)})

        signals.append({
            "sector": name,
            "read": s["label"],
            "score": score,
            "event_type": event_type,
            "drivers": drivers,
        })
    return signals


if __name__ == "__main__":
    print("Run via run_all.py")
