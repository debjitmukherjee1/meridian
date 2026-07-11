# Data sources & free-tier limits (verified July 2026)

Every source below sits inside a free tier that's large relative to our usage
(~10–30 tickers, one refresh/day). Re-check limits periodically — they change.

| Source | Purpose | Free limit | Key needed? | Docs |
|---|---|---|---|---|
| **Finnhub** | Prices + fundamentals | 60 calls/min | Yes (`FINNHUB_KEY`) | https://finnhub.io/docs/api |
| **GDELT** | News headlines, tone, macro/geo themes | Fully free | No | https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ |
| **Groq (Llama 3.1 8B Instant)** | AI headline scoring | 14,400 req/day | Yes (`GROQ_KEY`) | https://console.groq.com/docs/api-reference |

## Why NOT these
- **Alpha Vantage** — free tier dropped to **25 requests/day** in 2026. Too tight.
- **Twitter/X API** — expensive in 2026.
- **StockTwits** — was the planned retail-social source, but its public endpoint is now
  behind a Cloudflare bot challenge (confirmed July 2026), not a plain rate limit or
  auth requirement. No free workaround; dropped rather than built on top of a bot-block.
- **Reddit** — considered as a secondary social source, but with StockTwits gone there's
  no primary to pair it with, and Reddit coverage for non-US small/mid-caps (India, UK,
  Japan watchlist names) is thin anyway. Dropped; Meridian is a news+macro sentiment
  index, not social.
- **Paid sentiment aggregators** — unnecessary; Finnhub + GDELT + Groq covers the
  signal that's actually free to get, at $0.

## Keys as GitHub Actions secrets
Repo → Settings → Secrets and variables → Actions → New repository secret:
- `FINNHUB_KEY`
- `GROQ_KEY`

With **no keys set**, the pipeline runs in MOCK_MODE and generates realistic
sample data — so you can test everything before signing up for anything.
