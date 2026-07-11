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


def _tone_note(tone, sector):
    """Deterministic fallback note (no AI call) grounded in the real GDELT
    tone number -- used in mock mode and whenever the Groq call fails, so a
    headline never ships with no reasoning at all."""
    if tone > 1:
        return f"Tone {tone:+.1f} — reads positive, supports bullish sentiment in {sector}."
    if tone < -1:
        return f"Tone {tone:+.1f} — reads negative, weighs on sentiment in {sector}."
    return f"Tone {tone:+.1f} — roughly neutral, limited effect on {sector} sentiment."


def _groq_sector_analysis(sector, headlines):
    """One batched call: ask Groq for a 0-100 sentiment score for the sector
    AND a one-line note per headline (same order/count) explaining how it
    reads. Returns (score, notes_list); notes_list may be shorter than
    headlines if the model drops one -- caller pads with the tone fallback."""
    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
    prompt = (
        f"You are a financial sentiment analyst covering the {sector} sector. "
        f"Given these headlines:\n{numbered}\n\n"
        f"1) Rate overall investor sentiment for {sector} from 0 (very bearish) "
        f"to 100 (very bullish), based ONLY on these headlines.\n"
        f"2) For EACH headline, in the SAME order, write ONE short clause "
        f"(under 16 words) on how that specific headline affects market "
        f"sentiment for {sector}. Be specific to the headline, not generic.\n"
        f'Return JSON exactly like: {{"score": 62, "notes": ["...", "...", ...]}} '
        f"with exactly {len(headlines)} entries in notes, same order as the headlines."
    )
    body = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}}
    r = requests.post(GROQ_URL,
                      headers={"Authorization": f"Bearer {config.GROQ_KEY}"},
                      json=body, timeout=30)
    r.raise_for_status()
    obj = json.loads(r.json()["choices"][0]["message"]["content"])
    score = max(0, min(100, int(obj.get("score", 50))))
    notes = obj.get("notes") or []
    # Defensive: a small model can return "notes" as something other than a
    # flat list of strings (a single string -- which Python would otherwise
    # iterate character-by-character into single-letter "notes" -- or a list
    # of dicts, whose str() would leak a Python repr into user-facing text).
    # Anything not cleanly a list of strings is discarded, not coerced, so
    # the caller's existing "pad missing notes with the tone fallback" path
    # engages instead of shipping garbage.
    if not isinstance(notes, list):
        notes = []
    notes = [n for n in notes if isinstance(n, str)]
    return score, notes


def news_scores(news_items):
    """Per-sector news sentiment 0-100. Uses Groq if available, else tone avg.
    Also attaches a "note" to every item in news_items (mutated in place) --
    the same list is written verbatim to news.json by run_all.py, so this is
    how the per-headline reasoning shown on the Sentiment tab gets there."""
    by_sector = {}
    for n in news_items:
        by_sector.setdefault(n["sector"], []).append(n)

    if config.MOCK_MODE or config.GROQ_KEY is None:
        for n in news_items:
            n["note"] = _tone_note(n["tone"], n["sector"])
        return _news_tone_by_sector(news_items)

    out = {}
    for sector, items in by_sector.items():
        subset = items[:8]
        try:
            score, notes = _groq_sector_analysis(sector, [it["title"] for it in subset])
            out[sector] = score
            for it, note in zip(subset, notes):
                it["note"] = note
            for it in subset[len(notes):]:  # model returned fewer notes than asked
                it["note"] = _tone_note(it["tone"], it["sector"])
        except Exception as e:
            print(f"[groq] {sector} failed ({e}); tone fallback")
            out.update(_news_tone_by_sector(items))
            for it in subset:
                it["note"] = _tone_note(it["tone"], it["sector"])
        for it in items[8:]:  # beyond the batch Groq saw -- still needs a note
            it["note"] = _tone_note(it["tone"], it["sector"])
    return out


MACRO_KEYWORDS = {
    62: ["easing", "lift", "steadies", "resilient", "calm"],
    38: ["tension", "conflict", "risk-off", "probe", "squeeze"],
}


def macro_score(macro_theme):
    """Crude 0-100 macro overlay from the theme string (kept transparent)."""
    t = macro_theme.lower()
    for score, words in MACRO_KEYWORDS.items():
        for w in words:
            if w in t:
                return score
    return 50


def macro_explanation(macro_theme):
    """Which keyword (if any) actually drove macro_score, for the UI to show
    its work rather than just asserting a number."""
    t = macro_theme.lower()
    for score, words in MACRO_KEYWORDS.items():
        for w in words:
            if w in t:
                mood = "bullish" if score > 50 else "bearish"
                return f'Matched keyword "{w}" in the macro theme → {mood} overlay ({score}).'
    return "No strong macro keyword matched today's theme → neutral overlay (50)."


def build_sentiment(companies, news_items, macro_theme):
    """Combine news + macro into the per-company Sentiment Index."""
    w = config.SENTIMENT_WEIGHTS
    news_by_sector = news_scores(news_items)
    macro = macro_score(macro_theme)

    enriched = []
    for c in companies:
        # Fall back to the shared "Market" bucket (broad/unsectored
        # headlines) before defaulting to a flat neutral 50 -- matches the
        # same fallback sector_signals.py already uses. Without this, any
        # sector with zero headlines tagged to it specifically (common even
        # with real sector-tagging, since not every headline names a
        # watchlist company) got a hardcoded neutral score instead of the
        # genuinely-scored broad-market read.
        news = news_by_sector.get(c["sector"])
        if news is None:
            news = news_by_sector.get("Market", 50)
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
