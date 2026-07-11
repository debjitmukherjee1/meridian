# Data sources & free-tier limits (verified July 2026)

Every source below sits inside a free tier that's large relative to our usage
(~10–30 tickers, one refresh/day). Re-check limits periodically — they change.

| Source | Purpose | Free limit | Key needed? | Docs |
|---|---|---|---|---|
| **Yahoo Finance** (unofficial quote API) | Prices + fundamentals, all 4 markets | Best-effort, no published quota | No | none published — see caveat below |
| **GDELT** | News headlines, tone, macro/geo themes | Fully free | No | https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ |
| **Groq (Llama 3.1 8B Instant)** | AI headline scoring | 14,400 req/day | Yes (`GROQ_KEY`) | https://console.groq.com/docs/api-reference |

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

With **no key set**, the pipeline runs in MOCK_MODE and generates realistic
sample data — so you can test everything before signing up for anything.
