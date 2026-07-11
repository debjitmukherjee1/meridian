"""
score_sentiment.py — turns raw signals into the 0-100 Sentiment Index.

The AI step (Groq, free tier 14,400 req/day on Llama 3.1 8B Instant)
re-scores the top news headlines per sector for nuance, because GDELT's
dictionary tone is blunt on financial language. We BATCH one call per
sector, so ~8 calls/day << 14,400.

Groq API (OpenAI-compatible): https://console.groq.com/docs/api-reference
"""
import json
import config

try:
    import requests
except ImportError:
    requests = None

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"


def _news_tone_by_sector(news_items):
    """Fallback: average GDELT tone per sector, mapped to 0-100."""
    buckets = {}
    for n in news_items:
        buckets.setdefault(n["sector"], []).append(n["tone"])
    out = {}
    for sector, tones in buckets.items():
        avg = sum(tones) / len(tones)
        out[sector] = max(0, min(100, 50 + avg * 8))  # tone ~[-10,10] -> 0-100
    return out


def _groq_sector_score(sector, headlines):
    """One batched call: ask Groq for a 0-100 sentiment for a sector."""
    prompt = (
        f"You are a financial sentiment analyst. Rate overall investor sentiment "
        f"for the {sector} sector from 0 (very bearish) to 100 (very bullish) "
        f"based ONLY on these headlines. Reply with just the integer.\n\n"
        + "\n".join(f"- {h}" for h in headlines)
    )
    body = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}]}
    r = requests.post(GROQ_URL,
                      headers={"Authorization": f"Bearer {config.GROQ_KEY}"},
                      json=body, timeout=30)
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    digits = "".join(ch for ch in text if ch.isdigit())
    return max(0, min(100, int(digits[:3]))) if digits else 50


def news_scores(news_items):
    """Per-sector news sentiment 0-100. Uses Groq if available, else tone avg."""
    if config.MOCK_MODE or config.GROQ_KEY is None:
        return _news_tone_by_sector(news_items)
    by_sector = {}
    for n in news_items:
        by_sector.setdefault(n["sector"], []).append(n["title"])
    out = {}
    for sector, heads in by_sector.items():
        try:
            out[sector] = _groq_sector_score(sector, heads[:8])
        except Exception as e:
            print(f"[groq] {sector} failed ({e}); tone fallback")
            out.update(_news_tone_by_sector([n for n in news_items if n["sector"] == sector]))
    return out


def macro_score(macro_theme):
    """Crude 0-100 macro overlay from the theme string (kept transparent)."""
    t = macro_theme.lower()
    if any(w in t for w in ["easing", "lift", "steadies", "resilient", "calm"]):
        return 62
    if any(w in t for w in ["tension", "conflict", "risk-off", "probe", "squeeze"]):
        return 38
    return 50


def build_sentiment(companies, news_items, macro_theme):
    """Combine news + macro into the per-company Sentiment Index."""
    w = config.SENTIMENT_WEIGHTS
    news_by_sector = news_scores(news_items)
    macro = macro_score(macro_theme)

    enriched = []
    for c in companies:
        news = news_by_sector.get(c["sector"], 50)
        index = round(w["news"] * news + w["macro"] * macro, 1)
        c = dict(c)
        c["sentiment_index"] = index
        c["sentiment_breakdown"] = {
            "news": round(news, 1),
            "macro": round(macro, 1),
        }
        enriched.append(c)
    return enriched, macro


if __name__ == "__main__":
    print("Run via run_all.py")
