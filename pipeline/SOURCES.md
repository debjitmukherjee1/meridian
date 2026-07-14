# Data sources & free-tier limits (verified July 2026)

Every source below sits inside a free tier that's large relative to our usage
(~10–30 tickers, one refresh/day). Re-check limits periodically — they change.

| Source | Purpose | Free limit | Key needed? | Docs |
|---|---|---|---|---|
| **Yahoo Finance** (unofficial quote API) | Prices + fundamentals, all 4 markets | Best-effort, no published quota | No | none published — see caveat below |
| **GDELT** | News headlines, tone, macro/geo themes | Fully free | No | https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ |
| **Groq (Llama 3.1 8B Instant)** | AI headline scoring | 14,400 req/day | Yes (`GROQ_KEY`) | https://console.groq.com/docs/api-reference |
| **World Bank API** | MacroLens: CPI, real GDP growth, unemployment — annual, all 4 markets | Fully free, no published quota | No | https://datahelpdesk.worldbank.org/knowledgebase/articles/889392 |
| **Frankfurter** (ECB reference rates) | MacroLens: FX vs USD, daily, 1Y | Fully free | No | https://www.frankfurter.dev/ |
| **FRED** (St. Louis Fed) | MacroLens: central-bank policy rate (US/UK/JP only — see caveat below) | Free, generous published limits | Yes (`FRED_KEY`) | https://fred.stlouisfed.org/docs/api/fred/ |

**Yahoo Finance caveat (be honest about it):** this is an *unofficial* endpoint
— a cookie+crumb handshake (`fc.yahoo.com` → `/v1/test/getcrumb` →
`/v7/finance/quote`), not a registered API product. No signup, no key. It's
not a documented, stable product: the crumb endpoint literally has `/test/`
in its path, and this exact mechanism has broken before historically (why the
`yfinance` library has patched its auth logic repeatedly over the years). It
requires an explicit browser-like `User-Agent` on every request or the crumb
endpoint 429s. Treat it as best-effort market data, not a guarantee — `pipeline/fetch_market.py`
retries with backoff and falls back to mock data per-ticker (or per-market, if
the whole batch call fails) rather than silently serving stale/wrong numbers.

**FRED / India caveat:** FRED mirrors the OECD's Main Economic Indicators
central-bank-rate series, and India isn't in that set — there's no FRED
series for the RBI's repo rate. `fetch_macro.py` never guesses at one; India's
policy rate always comes from the hand-maintained, two-source-checked
`pipeline/manual_rates.json` instead. That same file is also the fallback for
US/UK/JP if `FRED_KEY` is unset or a specific call fails, so MacroLens's
policy-rate card never goes empty or scrapes an unofficial source for it.

**FRED / UK caveat (found live, not in docs anywhere):** the obvious series,
`BOERUKM` ("Bank of England Policy Rate in the United Kingdom"), looks right
by name but the Bank of England discontinued it in **January 2017** — a real
API call returns zero observations for any recent window, every day, forever.
Confirmed by fetching it directly rather than trusting the series name.
`config.FRED_POLICY_RATE_SERIES["UK"]` is `None`, same treatment as India, so
the pipeline doesn't waste a call on a series that can never succeed.

**FRED staleness caveat (also found live):** `IRSTCB01JPM156N` (Japan) *does*
return data — its API call succeeds — but its most recent point was ~2.5
years old (Dec 2023, 0.3%) while the real BOJ rate had since hiked to 1.00%.
"Has any data" isn't "is current." `fetch_macro.py` now rejects any FRED
observation older than `FRED_MAX_STALENESS_DAYS` (180 days) and falls back to
`manual_rates.json` instead of silently serving a stale-but-present number.

## Why NOT these
- **Finnhub** — was the original prices/fundamentals source, but its free
  tier only covers **US-listed tickers**. Confirmed live: `curl
  "https://finnhub.io/api/v1/quote?symbol=RELIANCE.NS&token=..."` returns
  `{"error":"You don't have access to this resource."}` for NSE/LSE/Tokyo-
  suffixed symbols — it was silently producing ₹0/£0/¥0 fair values for every
  India/UK/Japan ticker in production. Swapped for Yahoo Finance, which
  covers all four markets in one batched call.
- **Alpha Vantage** — free tier dropped to **25 requests/day** in 2026. Too tight.
- **Twitter/X API** — expensive in 2026.
- **StockTwits** — was the planned retail-social source, but its public endpoint is now
  behind a Cloudflare bot challenge (confirmed July 2026), not a plain rate limit or
  auth requirement. No free workaround; dropped rather than built on top of a bot-block.
- **Reddit** — considered as a secondary social source, but with StockTwits gone there's
  no primary to pair it with, and Reddit coverage for non-US small/mid-caps (India, UK,
  Japan watchlist names) is thin anyway. Dropped; Meridian is a news+macro sentiment
  index, not social.
- **Paid sentiment aggregators** — unnecessary; Yahoo Finance + GDELT + Groq covers
  the signal that's actually free to get, at $0.

## Keys as GitHub Actions secrets
Repo → Settings → Secrets and variables → Actions → New repository secret:
- `GROQ_KEY`
- `FRED_KEY` — free, instant signup: https://fred.stlouisfed.org/docs/api/api_key.html

With **no key set**, the pipeline runs in MOCK_MODE and generates realistic
sample data — so you can test everything before signing up for anything.
Without `FRED_KEY` specifically (but with `GROQ_KEY` set, i.e. otherwise
live), MacroLens still runs live for World Bank/Frankfurter and falls back to
`manual_rates.json` for every market's policy rate, not just India's.
