"""
score_sentiment.py — turns live headlines into the 0-100 Sentiment Index.

Changed 17-Nov-2026. What was wrong:
  * The Groq model (llama-3.1-8b-instant) was shut down for free/developer
    tiers on 16-Aug-2026. Every call since returned HTTP 404 and the code fell
    back to GDELT "tone", which was always 0.0, so every live sector scored
    exactly 50. The Actions run still showed green.
  * The macro overlay (40% of the index) was a keyword match on a theme
    string: one word ("conflict") set it to 38 for the whole market.

Now:
  * Models are tried in order from config.GROQ_MODELS; a 404/400 on one moves
    to the next, so a future retirement degrades instead of breaking.
  * The model gives every headline a polarity from -5 to +5 (stored in
    "tone", which drives the Positive/Negative badge on the site). A sector's
    0-100 score is the average polarity of its relevant headlines, mapped
    linearly (50 + 10 x mean), so every score can be traced to headlines.
  * The macro overlay is the model's score for the market's broad headlines
    (the "Market" bucket), not a keyword.
  * If no model answers, this RAISES. A market with no real read keeps
    yesterday's data and the Actions run goes red. There is no silent 50.
"""
import json
import re
import time

import config

try:
    import requests
except ImportError:
    requests = None

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_working_model = None
_low_effort = True


def _retry_after(r, attempt):
    """Seconds to wait after a 429: Retry-After header, else Groq's
    'try again in 12.3s' message, else exponential backoff."""
    h = r.headers.get("retry-after")
    if h:
        try:
            return min(90.0, float(h) + 1)
        except ValueError:
            pass
    m = re.search(r"try again in ([0-9.]+)(ms|s)", r.text)
    if m:
        v = float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)
        return min(90.0, v + 1)
    return min(90.0, 5 * 2 ** attempt)


def _post(model, prompt, low_effort):
    body = {"model": model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
            "max_completion_tokens": 2048}
    if low_effort:
        # gpt-oss is a reasoning model; low effort cuts tokens per call, which
        # is what the free tier's per-minute token limit is measured in.
        body["reasoning_effort"] = "low"
    for attempt in range(7):
        r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {config.GROQ_KEY}"},
                          json=body, timeout=90)
        if r.status_code != 429:
            return r
        wait = _retry_after(r, attempt)
        print(f"[groq] rate-limited; waiting {wait:.0f}s")
        time.sleep(wait)
    return r


def _chat(prompt):
    """Call Groq, walking config.GROQ_MODELS until one answers. Returns the
    parsed JSON object. Remembers the first model that works for the run.
    Retries on rate limits (HTTP 429) and spaces calls out, because the free
    tier is limited per minute."""
    global _working_model, _low_effort
    if not config.GROQ_KEY:
        raise RuntimeError("GROQ_KEY is not set")
    time.sleep(config.GROQ_CALL_SPACING_S)
    models = [_working_model] if _working_model else list(config.GROQ_MODELS)
    last = None
    for model in models:
        try:
            r = _post(model, prompt, _low_effort)
            if r.status_code == 400 and _low_effort and "reasoning" in r.text.lower():
                _low_effort = False          # model doesn't take the parameter
                r = _post(model, prompt, False)
        except Exception as e:
            last = e
            continue
        if r.status_code in (400, 404) and not _working_model:
            last = RuntimeError(f"{model}: HTTP {r.status_code} {r.text[:160]}")
            print(f"[groq] {last}; trying next model")
            continue
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"] or ""
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            raise ValueError(f"{model}: no JSON in reply")
        if _working_model is None:
            _working_model = model
            print(f"[groq] using {model}")
        return json.loads(m.group(0))
    raise RuntimeError(f"no Groq model answered ({last})")


def _score_bucket(market_name, sector, headlines):
    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
    who = "the overall stock market" if sector == "Market" else f"the {sector} sector"
    prompt = (
        f"You are an equity sentiment analyst covering {who} in {market_name}. "
        f"Headlines from the last few days:\n{numbered}\n\n"
        f"1) Rate current investor sentiment toward {who} in {market_name} from 0 "
        f"(very bearish) to 100 (very bullish), based ONLY on these headlines. "
        f"50 means genuinely balanced, not 'unsure'.\n"
        f"2) For EACH headline, in the SAME order, give a polarity from -5 (clearly "
        f"bearish for {who}) to +5 (clearly bullish), and ONE clause under 16 words "
        f"on why. Headlines irrelevant to {who} get 0.\n"
        f'Return JSON exactly: {{"score": 62, "items": [{{"polarity": 2, "note": "..."}}, ...]}} '
        f"with exactly {len(headlines)} items."
    )
    obj = _chat(prompt)
    model_score = max(0, min(100, int(round(float(obj.get("score", 50))))))
    raw = obj.get("items") if isinstance(obj.get("items"), list) else []
    parsed = []
    for it in raw:
        if isinstance(it, dict):
            try:
                pol = max(-5.0, min(5.0, float(it.get("polarity", 0))))
            except (TypeError, ValueError):
                pol = 0.0
            note = it.get("note") if isinstance(it.get("note"), str) else ""
            parsed.append((pol, note))
    # The bucket score is BUILT from the per-headline polarities, not taken
    # from the model's own overall number: on the first live run (17-Nov)
    # gpt-oss-20b returned 62 for every US sector while scoring the Nvidia
    # headlines -3 to -5. Headlines it judged irrelevant (polarity 0) are left
    # out of the average. Polarity -5..+5 maps linearly to 0..100.
    relevant = [pol for pol, _ in parsed if pol != 0]
    if relevant:
        # Shrink toward neutral: the average counts config.SENTIMENT_PRIOR_N
        # imaginary neutral headlines, so a handful of one-sided headlines on
        # a quiet day can't pin a sector near 0 or 100 (India Healthcare read
        # 98 on 22-Nov). Six headlines all at +4 now read 80, not 90.
        k = config.SENTIMENT_PRIOR_N
        score = int(round(50 + 10 * sum(relevant) / (len(relevant) + k)))
    elif parsed:
        score = 50                       # every headline judged irrelevant
    else:
        score = model_score              # model returned no per-headline reads
    return max(0, min(100, score)), parsed


def news_scores(market, news_items):
    """Per-bucket 0-100 score. Mutates news_items in place: sets "tone"
    (model polarity, -5..+5) and "note" for every headline."""
    market_name = config.MARKETS[market]["name"]
    by_sector = {}
    for n in news_items:
        by_sector.setdefault(n["sector"], []).append(n)
    out = {}
    for sector, items in by_sector.items():
        subset = items[:config.NEWS_PER_SECTOR]
        score, parsed = _score_bucket(market_name, sector, [it["title"] for it in subset])
        out[sector] = score
        for it, (pol, note) in zip(subset, parsed):
            it["tone"], it["note"] = pol, note
        for it in subset[len(parsed):]:
            it["note"] = "Model returned no read for this headline."
    return out


def macro_explanation(market_score):
    mood = "bullish" if market_score >= 60 else "bearish" if market_score <= 40 else "balanced"
    return (f"Broad-market headlines scored {market_score}/100 by the model "
            f"({mood}); this is the macro overlay.")


def build_sentiment(market, companies, news_items):
    """Combine sector news + broad-market read into the per-company index."""
    w = config.SENTIMENT_WEIGHTS
    news_by_sector = news_scores(market, news_items)
    macro = news_by_sector.get("Market")
    if macro is None:
        raise RuntimeError(f"{market}: no broad-market headlines were scored")

    enriched = []
    for c in companies:
        news = news_by_sector.get(c["sector"], macro)  # no sector headlines -> market read
        index = round(w["news"] * news + w["macro"] * macro, 1)
        c = dict(c)
        c["sentiment_index"] = index
        c["sentiment_breakdown"] = {"news": round(news, 1), "macro": round(macro, 1)}
        enriched.append(c)
    return enriched, macro


if __name__ == "__main__":
    print("Run via run_all.py")
