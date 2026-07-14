# Meridian — Sentiment-Adjusted Valuation

*Fair value, read against the mood of the market.*

A market-research tool that valuates companies using **both** traditional finance
(multiples + DCF-lite) **and** live investor sentiment (news + macro/geo
overlay), across **four markets — India · USA · UK · Japan**. Refreshed daily.
Runs entirely on free tiers.

> **The differentiator:** every other free tool gives you a fair-value number.
> Meridian shows you the news-driven mood per sector, blends it into the
> valuation transparently (with a slider for how much sentiment matters), and —
> on the **Sector Signals** tab — explains *why* each sector moves, with forecast
> **ranges anchored to how that sector has historically behaved** in similar
> events. The AI writes the narrative; history fixes the numbers.

**→ Full plan & methodology:** [`docs/EXECUTABLE_PLAN.md`](docs/EXECUTABLE_PLAN.md)

## Does it cost Claude tokens each day? No.
The daily job runs on **GitHub's servers** (GitHub Actions cron), and the AI step
uses **Groq's free tier** — not Claude. After you deploy it, there is
**zero Anthropic token cost** and **$0/day** to keep it running. Claude was only
used to build it.

## How it stays free
- **Hosting:** GitHub Pages (static, free)
- **Daily job:** GitHub Actions (unlimited minutes for public repos)
- **Data:** Yahoo Finance (unofficial, no key), GDELT (free), Groq Llama 3.1 8B (14,400/day),
  World Bank + Frankfurter (both keyless) and FRED (free key) for the **Macro** tab
- The website only reads pre-computed JSON — **never calls a paid API at runtime**,
  so every extra visitor costs $0.

## Run it locally (no API keys needed)
```bash
# 1. generate sample data for all 4 markets (MOCK_MODE, no keys)
cd pipeline
pip install -r requirements.txt
python run_all.py

# 2. serve the site
cd ../site
python -m http.server 8000
# open http://localhost:8000
```

## Go live (real data)
1. Push this repo to GitHub (public).
2. Add repo secrets: `GROQ_KEY` and `FRED_KEY` (free, instant signup — see
   [`pipeline/SOURCES.md`](pipeline/SOURCES.md)). Without `FRED_KEY`, the
   **Macro** tab still runs live for CPI/GDP/unemployment/FX and falls back
   to hand-maintained figures (`pipeline/manual_rates.json`) for policy rates.
3. Settings → Pages → deploy from `main` → `/site`.
4. The `daily-update.yml` workflow refreshes all markets every morning.

## Structure
```
docs/    → the executable plan
site/    → static website (GitHub Pages root); data/ is per-market
pipeline/→ the daily Python job (runs only in Actions)
.github/ → the free cron automation
```

⚠️ Educational / research tool. Data is daily, not real-time. Forecast ranges are
historical-analogue estimates, not predictions. **Not financial advice.**
