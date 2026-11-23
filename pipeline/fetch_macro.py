"""
fetch_macro.py — MacroLens data: the macro backdrop (CPI, real GDP growth,
unemployment, central-bank policy rate, currency vs USD) for each of
Meridian's four markets. Writes one cross-market site/data/macro.json (unlike
the other fetch_*.py modules, which are per-market).

Sources, all free:
  - OECD SDMX API (keyless) — monthly CPI and unemployment, quarterly real GDP
    growth, from each national statistics office. Current to within 1-2 months.
  - MoSPI eSankhyiki API (keyless) — India's monthly PLFS unemployment rate.
  - World Bank API (keyless) — FALLBACK only for CPI, GDP growth and
    unemployment. Annual and 1-2 years behind; every indicator carries its own
    "as_of" so a fallback value is never presented as current.
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

# Groq calls go through score_sentiment._chat (config.GROQ_MODELS). The old
# hard-coded llama-3.1-8b-instant was shut down on 16-Aug-2026.


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
        "last_move": m.get("note"),
    }


# ---- Current official data: OECD SDMX (CPI, unemployment, GDP) + MoSPI ----
# Added 22-Nov-2026. The World Bank's annual series lag by one to two years:
# India's macro read said inflation was "comfortably low at 2.4%" (2025
# annual) while the RBI hiked in October 2026 on rising inflation (CPI was
# 5.6% in September). These sources are keyless and current:
#   OECD SDMX API  -- monthly CPI and unemployment, quarterly real GDP growth,
#                     compiled from each national statistics office.
#   MoSPI eSankhyiki API -- India's monthly PLFS unemployment rate (the OECD
#                     does not carry India's labour data).
# The World Bank stays as the fallback when a current source fails.
OECD_BASE = "https://sdmx.oecd.org/public/rest/data/"
OECD_FLOWS = {
    # metric: (dataflow, key template with {areas}, frequency, label)
    "cpi": ("OECD.SDD.TPS,DSD_PRICES@DF_PRICES_ALL,1.0",
            "{areas}.M.N.CPI.PA._T.N.GY", "monthly", "CPI Inflation (YoY)"),
    "unemployment": ("OECD.SDD.TPS,DSD_LFS@DF_IALFS_UNE_M,1.0",
                     "{areas}..._Z.Y._T.Y_GE15..M", "monthly", "Unemployment"),
    "gdp_growth": ("OECD.SDD.NAD,DSD_NAMAIN1@DF_QNA_EXPENDITURE_GROWTH_OECD,1.1",
                   "Q..{areas}.S1..B1GQ......GY.", "quarterly", "Real GDP Growth (YoY)"),
}
OECD_AREA = {"IN": "IND", "US": "USA", "UK": "GBR", "JP": "JPN"}
_oecd_cache = {}


def _oecd_metric(metric):
    """One request per metric for all four markets (the OECD API is
    rate-limited per IP, so 3 calls a run, not 12). Returns
    {market: [(period, value), ...]} sorted by period."""
    if metric in _oecd_cache:
        return _oecd_cache[metric]
    flow, key, _, _ = OECD_FLOWS[metric]
    areas = "+".join(OECD_AREA.values())
    start = f"{datetime.now(timezone.utc).year - 3}-01"
    url = f"{OECD_BASE}{flow}/{key.format(areas=areas)}"

    def _do():
        r = requests.get(url, params={"startPeriod": start,
                                      "dimensionAtObservation": "AllDimensions"},
                         headers={"Accept": "application/vnd.sdmx.data+csv; charset=utf-8",
                                  "User-Agent": "Meridian/1.0"}, timeout=40)
        r.raise_for_status()
        return r

    import csv, io
    rows = list(csv.DictReader(io.StringIO(_retry(_do).text)))
    back = {v: k for k, v in OECD_AREA.items()}
    out = {}
    for row in rows:
        mk = back.get(row.get("REF_AREA"))
        val = row.get("OBS_VALUE")
        if mk and val not in (None, ""):
            out.setdefault(mk, []).append((row["TIME_PERIOD"], float(val)))
    for mk in out:
        out[mk] = sorted(set(out[mk]))
    _oecd_cache[metric] = out
    return out


def _oecd_indicator(market, metric):
    pts = _oecd_metric(metric).get(market)
    if not pts:
        raise RuntimeError(f"OECD has no {metric} series for {market}")
    _, _, freq, label = OECD_FLOWS[metric]
    keep = 24 if freq == "monthly" else 8
    series = [{"date": d, "value": round(v, 2)} for d, v in pts[-keep:]]
    return {"label": label, "frequency": freq, "unit": "%",
            "source": "OECD (national statistics office data)",
            "as_of": series[-1]["date"], "latest": series[-1]["value"],
            "series": series}


_MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}


def _mospi_unemployment():
    """India's monthly PLFS unemployment rate: all India, age 15+, all
    persons, rural + urban (current weekly status)."""
    year = datetime.now(timezone.utc).year
    pts = []
    for y in (year - 1, year):
        def _do(y=y):
            r = requests.get("https://api.mospi.gov.in/api/plfs/getData",
                             params={"frequency_code": 3, "indicator_code": 3, "year": y,
                                     "gender_code": 3, "sector_code": 3, "age_code": 1},
                             headers={"Accept": "application/json", "User-Agent": "Meridian/1.0"},
                             timeout=30)
            r.raise_for_status()
            return r
        for row in _retry(_do).json().get("data", []):
            if (row.get("state") == "All India" and row.get("gender") == "person"
                    and row.get("sector") == "rural + urban"
                    and row.get("AgeGroup") == "15 years and above"):
                m = _MONTHS.get(row.get("month"))
                if m:
                    pts.append((f"{row['year']}-{m:02d}", float(row["value"])))
    pts = sorted(set(pts))[-24:]
    if not pts:
        raise RuntimeError("MoSPI returned no headline PLFS unemployment rows")
    series = [{"date": d, "value": round(v, 2)} for d, v in pts]
    return {"label": "Unemployment", "frequency": "monthly", "unit": "%",
            "source": "MoSPI, Periodic Labour Force Survey (monthly, CWS, age 15+)",
            "as_of": series[-1]["date"], "latest": series[-1]["value"],
            "series": series}


_ONS_MON = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def _ons_cpi():
    """UK CPI annual rate straight from the ONS (series D7G7). The OECD's
    figure for the same month can differ by a rounding step (Oct-2026:
    OECD 3.7%, ONS 3.6%); the ONS is the producer, so its figure is used."""
    def _do():
        r = requests.get("https://www.ons.gov.uk/economy/inflationandpriceindices/timeseries/d7g7/mm23/data",
                         headers={"User-Agent": "Meridian/1.0", "Accept": "application/json"}, timeout=30)
        r.raise_for_status()
        return r
    pts = []
    for row in _retry(_do).json().get("months", []):
        y, _, mon = row.get("date", "").partition(" ")
        if mon in _ONS_MON and row.get("value") not in (None, ""):
            pts.append((f"{y}-{_ONS_MON[mon]:02d}", float(row["value"])))
    pts = sorted(pts)[-24:]
    if not pts:
        raise RuntimeError("ONS returned no D7G7 months")
    series = [{"date": d, "value": round(v, 2)} for d, v in pts]
    return {"label": "CPI Inflation (YoY)", "frequency": "monthly", "unit": "%",
            "source": "ONS (CPI annual rate, D7G7)",
            "as_of": series[-1]["date"], "latest": series[-1]["value"], "series": series}


def _current_indicator(market, key):
    if market == "IN" and key == "unemployment":
        return _mospi_unemployment()
    if market == "UK" and key == "cpi":
        return _ons_cpi()
    return _oecd_indicator(market, key)


def _unavailable(market, key, why):
    ind = config.WORLD_BANK_INDICATORS[key]
    return {"label": ind["label"], "frequency": "n/a", "unit": ind["unit"],
            "source": "unavailable", "as_of": None, "latest": None,
            "series": [], "note": f"No source answered today ({why})."}


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


def _series_move(series):
    """Plain description of the latest change in a monthly policy-rate
    series, so the narrative can say 'raised' or 'held' correctly."""
    latest = series[-1]["value"]
    for pt in reversed(series[:-1]):
        if abs(pt["value"] - latest) >= 0.05:
            verb = "rose" if latest > pt["value"] else "fell"
            return (f"Rate {verb} from {pt['value']}% ({pt['date'][:7]}) to {latest}% "
                    f"({series[-1]['date'][:7]}).")
    return f"Rate unchanged at {latest}% across the last {len(series)} months."


def _fed_target_range():
    """Midpoint of the FOMC target range from FRED's daily lower/upper bound
    series. These step on the decision's effective date, so last_move names
    the actual hike or cut (FEDFUNDS, the monthly average, made a 16-Sep
    hike read as a September-to-October rise)."""
    lo = {p["date"]: p["value"] for p in _fred_series("DFEDTARL")}
    hi = {p["date"]: p["value"] for p in _fred_series("DFEDTARU")}
    days = sorted(set(lo) & set(hi))
    if not days:
        raise RuntimeError("no overlapping DFEDTARL/DFEDTARU observations")
    mids = [(d, round((lo[d] + hi[d]) / 2, 3)) for d in days]
    # chart: last value of each month, plus the latest day
    by_month = {}
    for d, v in mids:
        by_month[d[:7]] = (d, v)
    series = [{"date": d, "value": v} for d, v in sorted(by_month.values())]
    if series[-1]["date"] != mids[-1][0]:
        series.append({"date": mids[-1][0], "value": mids[-1][1]})
    d_last, v_last = mids[-1]
    move = f"Target range unchanged at {lo[d_last]:.2f}%-{hi[d_last]:.2f}% over the period shown."
    for (d0, v0), (d1, v1) in zip(reversed(mids[:-1]), reversed(mids[1:])):
        if v1 != v0:
            verb = "raised" if v1 > v0 else "cut"
            move = (f"FOMC {verb} the target range to {lo[d1]:.2f}%-{hi[d1]:.2f}% "
                    f"(effective {d1}); unchanged since.")
            break
    return {"label": "Policy Rate", "frequency": "as announced", "unit": "%",
            "source": "FRED (DFEDTARL/DFEDTARU, FOMC target range midpoint)",
            "as_of": d_last, "latest": v_last, "series": series[-60:],
            "last_move": move}


def _policy_rate(market, manual):
    if market == "US" and config.FRED_KEY and not config.MOCK_MODE:
        try:
            return _fed_target_range()
        except Exception as e:
            print(f"[macro] US Fed target range failed ({e}); trying FEDFUNDS")
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
            "last_move": _series_move(series),
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
    def bit(label, ind):
        return (f"{label} {ind['latest']}% ({ind['as_of']})" if ind.get("latest") is not None
                else f"{label} unavailable")
    return (f"{name}: {bit('CPI inflation', cpi)}, {bit('real GDP growth', gdp)}, "
            f"{bit('unemployment', une)}, {bit('policy rate', pr)}.{fx_bit}")


def _when(ind):
    """Value plus its period for the prompt. Annual figures are flagged so
    the narrative names the year instead of presenting them as current."""
    if ind.get("latest") is None:
        return "None (unavailable)"
    if ind.get("frequency") == "annual":
        return f"{ind['latest']}% (ANNUAL figure for {ind['as_of']}, not a recent month)"
    return f"{ind['latest']}% (as of {ind['as_of']})"


def _groq_macro_narrative(market, data):
    name = config.MARKETS[market]["name"]
    fx = data.get("fx", {})
    fx_line = (f"- Currency vs USD: {fx['latest']} ({fx['label']}, as of {fx['as_of']})"
               if fx.get("latest") is not None
               else "- Currency vs USD: not applicable, USD is the reference currency")
    prompt = (
        f"You are a macro analyst. Here is {name}'s current macro backdrop -- use ONLY these "
        f"figures, do not state any other numeric statistic and do not make a numeric forecast:\n"
        f"- CPI inflation (YoY): {_when(data['cpi'])}\n"
        f"- Real GDP growth: {_when(data['gdp_growth'])}\n"
        f"- Unemployment: {_when(data['unemployment'])}\n"
        f"- Central-bank policy rate: {data['policy_rate']['latest']}% (as of {data['policy_rate']['as_of']})\n"
        f"- Most recent policy action: {data['policy_rate'].get('last_move') or 'not given'}\n"
        f"{fx_line}\n\n"
        f"Write a 2-3 sentence plain-English 'macro read' describing the overall backdrop these "
        f"figures paint -- inflation trend, growth momentum, labor-market slack, policy stance. "
        f"The figures have different as-of dates; if one is more than a year older than the "
        f"others, say so rather than treating it as current. Ignore any figure shown as None. "
        f"Whenever you mention a figure marked ANNUAL, state its year in the same sentence "
        f"(e.g. '3.2% in 2025'). "
        f"Describe the policy stance from the 'most recent policy action' line: say raised, cut "
        f"or held as it states, and never say the rate was kept or held if that line says it was "
        f"raised or cut. "
        f'Return JSON exactly like: {{"narrative": "..."}}'
    )
    import score_sentiment  # shared caller: current model list, rate-limit retries
    obj = score_sentiment._chat(prompt)
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
        if config.MOCK_MODE:
            out[key] = _mock_indicator(market, key)
            continue
        # Current official source first, World Bank annual as the fallback.
        # Live runs never publish synthetic numbers: if both fail the
        # indicator is shown as unavailable rather than mocked.
        try:
            out[key] = _current_indicator(market, key)
            continue
        except Exception as e:
            print(f"[macro] {market}/{key} current source failed ({e}); trying World Bank")
        try:
            out[key] = _wb_indicator(market, key)
        except Exception as e:
            print(f"[macro] {market}/{key} World Bank failed too ({e}); marking unavailable")
            out[key] = _unavailable(market, key, str(e)[:80])

    out["policy_rate"] = _policy_rate(market, manual)

    if market in config.FX_PAIRS:
        try:
            out["fx"] = _mock_fx(market) if config.MOCK_MODE else _frankfurter_series(config.FX_PAIRS[market])
        except Exception as e:
            print(f"[macro] {market}/fx failed ({e}); marking unavailable")
            out["fx"] = {"label": config.FX_PAIRS[market]["label"], "frequency": "n/a",
                         "unit": "", "source": "unavailable", "as_of": None,
                         "latest": None, "series": [],
                         "note": f"Frankfurter did not answer today ({str(e)[:60]})."}
    else:
        out["fx"] = _no_fx_note()

    out["narrative"] = _narrative(market, out)
    return out


def fetch_all():
    manual = _load_manual_rates()
    return {market: fetch_market_macro(market, manual) for market in config.MARKETS}


if __name__ == "__main__":
    print(json.dumps(fetch_all(), indent=2))
