# Data sources & free-tier limits (verified July 2026)

Every source below sits inside a free tier that's large relative to our usage
(~10–30 tickers, one refresh/day). Re-check limits periodically — they change.

| Source | Purpose | Free limit | Key needed? | Docs |
|---|---|---|---|---|
| **Finnhub** | Prices + fundamentals | 60 calls/min | Yes (`FINNHUB_KEY`) | https://finnhub.io/docs/api |
| **GDELT** | News headlines, tone, macro/geo themes | Fully free | No | https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ |
| **StockTwits** | Retail bull/bear sentiment | Public stream | No | https://api.stocktwits.com/developers/docs |
| **Reddit** (optional) | Extra social volume | ~100 q/min (approval form) | Yes (`REDDIT_ID`/`SECRET`) | https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki |
| **Groq (Llama 3.1 8B Instant)** | AI headline scoring | 14,400 req/day | Yes (`GROQ_KEY`) | https://console.groq.com/docs/api-reference |

## Why NOT these
- **Alpha Vantage** — free tier dropped to **25 requests/day** in 2026. Too tight.
- **Twitter/X API** — expensive in 2026; StockTwits gives cleaner finance sentiment free.
- **Paid sentiment aggregators** — unnecessary; the stack above covers ~90% of signal at $0.

## Keys as GitHub Actions secrets
Repo → Settings → Secrets and variables → Actions → New repository secret:
- `FINNHUB_KEY`
- `GROQ_KEY`
- `REDDIT_ID`, `REDDIT_SECRET` (optional)

With **no keys set**, the pipeline runs in MOCK_MODE and generates realistic
sample data — so you can test everything before signing up for anything.
