"""
fetch_macro.py — MacroLens data: the macro backdrop (CPI, real GDP growth,
unemployment, central-bank policy rate, currency vs USD) for each of
Meridian's four markets. Writes one cross-market site/data/macro.json (unlike
the other fetch_*.py modules, which are per-market).

Sources, all free:
  - World Bank API (keyless) — CPI, GDP growth, unemployment. Annual, and it
    lags: the latest available year is usually 1-2 years behind today, which
    is why every indicator carries its own "as_of" rather than assuming "now".
  - Frankfurter (keyless, ECB reference rates) — daily FX vs USD, 1Y.
  - FRED (api.stlouisfed.org, needs FRED_KEY) — central-bank policy rate,
    monthly, for markets where a reliable series exists (US, UK, JP). India's
    RBI repo rate has no equivalent FRED series (it isn't part of the OECD
    Main Economic Indicators set FRED mirrors), so India always reads
    manual_rates.json instead of attempting FRED. That same file is also the
    fallback for US/UK/JP if FRED_KEY is unset or a call fails -- see
    manual_rates.json's own comment for the update process.

In MOCK_MODE (no GROQ_KEY -- the same flag every other fetch_*.py module
gates on) CPI/GDP/unemployment/FX are synthesized, deterministic per market.
The POLICY RATE IS THE ONE EXCEPTION: manual_rates.json holds real,
two-source-checked figures maintained by hand, not mock data, so it's read
as-is even in mock mode rather than faking a number we already have for real.

Each market also gets a 2-3 sentence "macro read" narrative via Groq -- same
guardrail as sector_signals.py/score_sentiment.py: the AI is handed the
already-fetched numbers and writes prose ONLY, explicitly told not to state
any other statistic or make a numeric forecast. If Groq is unavailable or
fails, a deterministic fallback narrative (plain restatement of the numbers)
takes over so the field is never empty.
"""
import json
import random
import time
from datetime import datetime, timedelta, timezone

import config

try:
    import requests
except ImportError:
    requests = None

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.1-8b-instant"


def _retry(fn, attempts=3, backoff=(1, 2)):
    """Call fn() up to `attempts` times, sleeping `backoff[i]` seconds between
    attempts, before letting the last exception propagate. World Bank/FRED/
    Frankfurter all occasionally time out or 502 on a single call under
    back-to-back requests -- same shape as fetch_market.py's helper for
    Yahoo, duplicated here rather than shared since every fetch_*.py module
    is self-contained by convention in this pipeline."""
    last_exc = None
    for i in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if i < attempts - 1:
                time.sleep(backoff[i])
    raise last_exc


# ---- manual policy-rate fallback ------------------------------------------
def _load_manual_rates():
    with open(config.MANUAL_RATES_PATH) as f:
        data = json.load(f)
    data.pop("_comment", None)
    return data


def _manual_policy_rate(market, manual, reason):
    m = manual.get(market)
    if not m:
        return None
    note = f"Manual, as of {m['as_of']} — {reason}."
    if m.get("note"):
        note += f" {m['note']}"
    return {
        "label": "Policy Rate", "frequency": "as announced", "unit": "%",
        "source": m["source"], "source_url": m.get("source_url"),
        "as_of": m["as_of"], "latest": m["rate_pct"],
        "series": [{"date": m["as_of"], "value": m["rate_pct"]}],
        "note": note,
    }


# ---- World Bank (CPI / GDP growth / unemployment) --------------------------
def _wb_indicator(market, key):
    ind = config.WORLD_BANK_INDICATORS[key]
    country = config.WORLD_BANK_COUNTRY[market]
    this_year = datetime.now(timezone.utc).year
    url = f"https://api.worldbank.org/v2/country/{country}/indicator/{ind['code']}"
    params = {"format": "json", "per_page": 100,
              "date": f"{this_year - config.MACRO_FETCH_YEARS}:{this_year}"}

    def _do():
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp

    r = _retry(_do)
    payload = r.json()
    rows = payload[1] if isinstance(payload, list) and len(payload) > 1 and payload[1] else []
    points = [(row["date"], row["value"]) for row in rows if row.get("value") is not None]
    points.sort(key=lambda p: p[0])
    points = points[-config.MACRO_YEARS:]
    if not points:
        raise RuntimeError(f"World Bank returned no {ind['code']} values for {country}")
    series = [{"date": d, "value": round(v, 2)} for d, v in points]
    return {
        "label": ind["label"], "frequency": "annual", "unit": ind["unit"],
        "source": f"World Bank ({ind['code']})",
        "as_of": series[-1]["date"], "latest": series[-1]["value"],
        "series": series,
    }


def _mock_indicator(market, key):
    ind = config.WORLD_BANK_INDICATORS[key]
    random.seed(f"{market}-{key}")
    base = {"cpi": 4.5, "gdp_growth": 3.0, "unemployment": 5.5}[key]
    # World Bank annual data always lags -- mock the same lag so the UI's
    # honesty labeling gets exercised in mock mode too, not just live.
    last_year = datetime.now(timezone.utc).year - 1
    years = list(range(last_year - config.MACRO_YEARS + 1, last_year + 1))
    series = []
    val = base
    for y in years:
        val = max(-2.0, val + random.uniform(-1.2, 1.2))
        series.append({"date": str(y), "value": round(val, 2)})
    return {
        "label": ind["label"], "frequency": "annual", "unit": ind["unit"],
        "source": f"World Bank ({ind['code']}) [MOCK]",
        "as_of": series[-1]["date"], "latest": series[-1]["value"],
        "series": series,
    }


# ---- Frankfurter (FX vs USD, 1Y) -------------------------------------------
def _frankfurter_series(pair):
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=config.FX_LOOKBACK_DAYS)
    url = f"https://api.frankfurter.app/{start.isoformat()}..{end.isoformat()}"
    params = {"from": pair["from"], "to": pair["to"]}

    def _do():
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        return resp

    r = _retry(_do)
    rates = r.json().get("rates", {})
    rows = sorted(rates.items())
    series = [{"date": d, "value": round(v[pair["to"]], 4)} for d, v in rows if pair["to"] in v]
    if not series:
        raise RuntimeError(f"Frankfurter returned no {pair['from']}->{pair['to']} rates")
    return {
        "label": pair["label"], "frequency": "daily", "unit": pair["to"],
        "source": "Frankfurter (ECB reference rates)",
        "as_of": series[-1]["date"], "latest": series[-1]["value"],
        "series": series,
    }


def _mock_fx(market):
    pair = config.FX_PAIRS[market]
    random.seed(f"fx-{market}")
    base = {"IN": 87.0, "UK": 1.27, "JP": 148.0}[market]
    end = datetime.now(timezone.utc).date()
    series = []
    val = base
    for days_ago in range(config.FX_LOOKBACK_DAYS, -1, -7):  # weekly mock points
        d = end - timedelta(days=days_ago)
        val = max(0.01, val + random.uniform(-base * 0.01, base * 0.01))
        series.append({"date": d.isoformat(), "value": round(val, 4)})
    return {
        "label": pair["label"], "frequency": "daily", "unit": pair["to"],
        "source": "Frankfurter (ECB reference rates) [MOCK]",
        "as_of": series[-1]["date"], "latest": series[-1]["value"],
        "series": series,
    }


def _no_fx_note():
    return {
        "label": "Currency vs USD", "frequency": "n/a", "unit": None, "source": None,
        "as_of": None, "latest": None, "series": [],
        "note": "USD is Meridian's reference currency for this comparison; no vs-USD series applies.",
    }


# ---- FRED (policy rate) -----------------------------------------------------
def _fred_series(series_id):
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=365 * config.MACRO_YEARS)
    params = {"series_id": series_id, "api_key": config.FRED_KEY, "file_type": "json",
              "observation_start": start.isoformat(), "observation_end": end.isoformat()}

    def _do():
        resp = requests.get(config.FRED_URL, params=params, timeout=20)
        resp.raise_for_status()
        return resp

    r = _retry(_do)
    obs = r.json().get("observations", [])
    points = [{"date": o["date"], "value": round(float(o["value"]), 2)}
              for o in obs if o.get("value") not in (None, ".")]
    if not points:
        raise RuntimeError(f"FRED returned no observations for {series_id}")
    # A series can return real data that's simply stopped updating (found
    # live: IRSTCB01JPM156N's most recent point was Dec 2023 -- 2.5 years
    # stale, silently showing 0.3% while BOJ's actual rate had since hiked to
    # 1.00%). "Has any data" isn't the same as "current" -- reject anything
    # older than the staleness budget so a dead-but-not-empty series falls
    # back to the manually-verified rate instead of quietly lying.
    latest_date = datetime.strptime(points[-1]["date"], "%Y-%m-%d").date()
    age_days = (datetime.now(timezone.utc).date() - latest_date).days
    if age_days > config.FRED_MAX_STALENESS_DAYS:
        raise RuntimeError(
            f"FRED {series_id} latest observation is {age_days}d old "
            f"({points[-1]['date']}) -- treating as stale")
    return points


def _policy_rate(market, manual):
    series_id = config.FRED_POLICY_RATE_SERIES.get(market)
    if not series_id:
        return _manual_policy_rate(market, manual, "no reliable FRED series for this market")
    if config.MOCK_MODE or not config.FRED_KEY:
        return _manual_policy_rate(market, manual, "FRED_KEY not set")
    try:
        series = _fred_series(series_id)
        return {
            "label": "Policy Rate", "frequency": "monthly", "unit": "%",
            "source": f"FRED ({series_id})",
            "as_of": series[-1]["date"], "latest": series[-1]["value"],
            "series": series,
        }
    except Exception as e:
        print(f"[macro] {market} FRED policy rate failed ({e}); using manual fallback")
        return _manual_policy_rate(market, manual, f"FRED fetch failed ({e})")


# ---- narrative (AI writes prose only, never numbers) ------------------------
def _fallback_narrative(market, data):
    """Deterministic restatement of the real fetched numbers -- used in mock
    mode and whenever Groq is unavailable/fails, so the field is never empty
    and never fabricated."""
    name = config.MARKETS[market]["name"]
    cpi, gdp, une, pr = data["cpi"], data["gdp_growth"], data["unemployment"], data["policy_rate"]
    fx = data.get("fx", {})
    fx_bit = (f" The currency stands at {fx['latest']} ({fx['label']}, as of {fx['as_of']})."
              if fx.get("latest") is not None else "")
    return (f"{name}: CPI inflation {cpi['latest']}% ({cpi['as_of']}), real GDP growth "
            f"{gdp['latest']}% ({gdp['as_of']}), unemployment {une['latest']}% ({une['as_of']}), "
            f"policy rate {pr['latest']}% ({pr['as_of']}).{fx_bit}")


def _groq_macro_narrative(market, data):
    name = config.MARKETS[market]["name"]
    fx = data.get("fx", {})
    fx_line = (f"- Currency vs USD: {fx['latest']} ({fx['label']}, as of {fx['as_of']})"
               if fx.get("latest") is not None
               else "- Currency vs USD: not applicable, USD is the reference currency")
    prompt = (
        f"You are a macro analyst. Here is {name}'s current macro backdrop -- use ONLY these "
        f"figures, do not state any other numeric statistic and do not make a numeric forecast:\n"
        f"- CPI inflation (YoY): {data['cpi']['latest']}% (as of {data['cpi']['as_of']})\n"
        f"- Real GDP growth: {data['gdp_growth']['latest']}% (as of {data['gdp_growth']['as_of']})\n"
        f"- Unemployment: {data['unemployment']['latest']}% (as of {data['unemployment']['as_of']})\n"
        f"- Central-bank policy rate: {data['policy_rate']['latest']}% (as of {data['policy_rate']['as_of']})\n"
        f"{fx_line}\n\n"
        f"Write a 2-3 sentence plain-English 'macro read' describing the overall backdrop these "
        f"figures paint -- inflation trend, growth momentum, labor-market slack, policy stance. "
        f'Return JSON exactly like: {{"narrative": "..."}}'
    )
    body = {"model": GROQ_MODEL, "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}}
    r = requests.post(GROQ_URL, headers={"Authorization": f"Bearer {config.GROQ_KEY}"},
                       json=body, timeout=30)
    r.raise_for_status()
    obj = json.loads(r.json()["choices"][0]["message"]["content"])
    text = obj.get("narrative")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("empty/invalid narrative from Groq")
    return text.strip()


def _narrative(market, data):
    if config.MOCK_MODE or not config.GROQ_KEY:
        return _fallback_narrative(market, data)
    try:
        return _groq_macro_narrative(market, data)
    except Exception as e:
        print(f"[macro] {market} Groq narrative failed ({e}); deterministic fallback")
        return _fallback_narrative(market, data)


# ---- orchestration ----------------------------------------------------------
def fetch_market_macro(market, manual):
    out = {}
    for key in config.WORLD_BANK_INDICATORS:
        try:
            out[key] = _mock_indicator(market, key) if config.MOCK_MODE else _wb_indicator(market, key)
        except Exception as e:
            print(f"[macro] {market}/{key} failed ({e}); using mock fallback")
            out[key] = _mock_indicator(market, key)

    out["policy_rate"] = _policy_rate(market, manual)

    if market in config.FX_PAIRS:
        try:
            out["fx"] = _mock_fx(market) if config.MOCK_MODE else _frankfurter_series(config.FX_PAIRS[market])
        except Exception as e:
            print(f"[macro] {market}/fx failed ({e}); using mock fallback")
            out["fx"] = _mock_fx(market)
    else:
        out["fx"] = _no_fx_note()

    out["narrative"] = _narrative(market, out)
    return out


def fetch_all():
    manual = _load_manual_rates()
    return {market: fetch_market_macro(market, manual) for market in config.MARKETS}


if __name__ == "__main__":
    print(json.dumps(fetch_all(), indent=2))
