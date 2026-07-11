# Meridian — Executable Plan

**Name:** Meridian *("Fair value, read against the mood of the market.")*
**Author:** Debjit Mukherjee
**Goal:** A public, GitHub-hosted market-research house that valuates companies using *both* traditional finance *and* investor sentiment, across **four markets (India · USA · UK · Japan)**, refreshed daily, at **~zero running cost and zero Claude tokens**.
**Status:** Plan + working scaffold (this repo)

---

## 0. Does this cost Claude tokens each day? (read this first)

**No.** Once deployed, Meridian runs entirely independently of Claude/Anthropic:

- The daily job runs on **GitHub's servers** via GitHub Actions on a cron schedule — not on anything of Anthropic's, and not by "asking Claude" each day.
- The AI sentiment/reasoning step uses **Groq's free API** (14,400 calls/day free on Llama 3.1 8B Instant), *not* Claude. So there is **no Anthropic token cost** in daily operation.
- Claude (me) was only involved during the **build**. After you push this to GitHub, you could delete the chat and the site keeps updating forever. Daily Claude cost = **0 tokens, $0**.
- (If you ever *preferred* Claude as the reasoning engine over Groq, that would use Anthropic API credits — but the design deliberately uses free Groq so you never pay.)

---

## 1. The one-paragraph pitch

Most valuation tools tell you what a company is *worth on paper* (DCF, multiples, book value). They ignore the fact that markets are moved by *what people feel*. Meridian fuses the two: a classic fair-value estimate is adjusted by a **live, sector-level Sentiment Index** built from news tone and a macro/geo-political risk overlay. Crucially, a dedicated **Sector Signals** view explains *why* each sector reads the way it does — a main impact plus supporting drivers — with each carrying a forecast **range anchored to how that sector has historically moved** in events of that type (e.g. a Gulf supply shock → Energy). Everything is scoped to a chosen market (India by default; USA, UK, Japan on a top-right switch) and runs as a static website that rebuilds itself once a day via a free automated job. **That fusion — plus transparent, history-anchored sector reasoning — is the differentiator.**

---

## 2. Why this is genuinely near-zero-cost (the numbers)

The entire cost constraint ("keep daily maintenance under 5% of total, ideally $0") is met because **every moving part sits inside a free tier that is large relative to our usage.** Below is the real usage math for a starter watchlist of ~30 tickers across ~8 sectors, refreshed once per day.

| Component | Provider (free tier) | Free limit | Our daily use | Headroom |
|---|---|---|---|---|
| Hosting | **GitHub Pages** | 100 GB bandwidth/mo (soft), unlimited static | A few MB of JSON + static assets | Enormous |
| Automation (the daily job) | **GitHub Actions** | **Unlimited minutes for public repos** | ~2–4 min/day | Effectively infinite |
| Stock prices & fundamentals | **Yahoo Finance** (unofficial quote API) | Best-effort, no published quota | ~30 tickers, 1 batched quote call/market + 1 FCF call/ticker | Large in practice |
| News + macro/geo-political tone | **GDELT** | Fully free (file downloads / BigQuery) | 1–2 pulls/day | Unlimited |
| AI sentiment scoring | **Groq (Llama 3.1 8B Instant)** free tier | **14,400 requests/day** | ~30–60 calls/day (batched) | ~240× headroom |

**Sources for these limits are listed in §11.** The key architectural insight: because GitHub Actions is *unlimited for public repos*, the "server" that does the daily work is free forever, and because we cache results as static JSON, the website itself never calls a paid API at runtime — visitors just read pre-computed files. **Marginal cost per extra visitor ≈ $0.**

> **The "5% of total cost" constraint:** With total running cost at $0, any conceivable maintenance (e.g. an optional custom domain at ~$10/yr, or a paid data upgrade later) is a deliberate choice, not a requirement. The baseline is genuinely free.

---

## 3. Architecture (how "self-sufficient" works)

The magic word in your brief was **"self-sufficient by linking it to news and broker platforms."** Here's how that's achieved without a backend server:

```
                    ┌─────────────────────────────────────────────┐
                    │   GitHub Actions (cron: once daily, free)    │
                    │                                              │
   Yahoo    ───────▶│  fetch_market.py   → prices, fundamentals    │
   GDELT    ───────▶│  fetch_news.py     → headlines + tone + geo  │
                    │  score_sentiment.py (Groq) → sector scores   │
                    │  build_valuation.py → fair value + adjustment│
                    │                                              │
                    │           writes  ▼                          │
                    │   site/data/*.json  (committed to repo)      │
                    └───────────────────┬──────────────────────────┘
                                        │  git push
                                        ▼
                    ┌─────────────────────────────────────────────┐
                    │   GitHub Pages (static hosting, free)        │
                    │   index.html reads site/data/*.json          │
                    │   → renders tabs, charts, valuation cards    │
                    └─────────────────────────────────────────────┘
                                        │
                                        ▼
                              Visitors (LinkedIn / your site)
```

**Why no server:** the frontend is 100% static. It never holds an API key and never calls a paid service live. All the "linking to news and broker platforms" happens *inside the daily job*, and the result is frozen into JSON files. This is what keeps it free and also fast (no cold starts, no rate-limit errors for visitors).

**Trade-off (be honest about it):** data is **daily, not real-time**. That's a deliberate choice to stay free. Intraday would require a live backend and paid feeds. For a research/analysis tool aimed at LinkedIn + portfolio, daily is the right call — and you can add a "last updated" timestamp so it's transparent.

---

## 4. The differentiator: how sentiment actually enters the valuation

This is the intellectual core. Keep it **explainable** — a black box impresses nobody and invites "how do you know?" This design is defensible in a comment section.

### 4a. Base (traditional) fair value
For each company, compute a simple, transparent blend so the number is reproducible:
- **P/E anchor:** sector-median P/E applied to the company's EPS → an implied price.
- **EV/EBITDA anchor:** each company's own EV/EBITDA is computed from parts already shown elsewhere (price + net debt per share, over EBITDA per share) rather than trusting a pre-computed ratio; the *sector median* of those is then applied to the company's own EBITDA, and de-levered back to an equity value per share by subtracting its own net debt. Skipped (not defaulted to zero) for companies where EBITDA isn't a meaningful figure, e.g. banks.
- **Optional DCF-lite:** a simplified 5-year FCF projection with a conservative terminal growth (only where FCF data is clean; otherwise skip and note it).
- Whichever anchors are actually computable for a given company are averaged; a company with zero computable anchors falls back to its current price rather than a fabricated number.
- Output: **Base Fair Value (BFV)** with the assumptions shown.

### 4b. Sentiment Index (0–100, per sector and per stock)
Two ingredients, each normalized to 0–100, then weighted. (A retail social-mood
signal — StockTwits bull/bear tagging — was in the original design, but
StockTwits' public endpoint is now behind a Cloudflare bot challenge with no
free way through it; see §7 for why that was dropped rather than worked around.)

| Signal | Source | What it captures | Default weight |
|---|---|---|---|
| **News tone** | GDELT tone score + Groq scoring of top headlines | Media narrative | 60% |
| **Macro/Geo overlay** | GDELT event themes (conflict, trade, policy) → sector risk multiplier | Systemic mood | 40% |

`SentimentIndex = 0.60·News + 0.40·Macro`

50 = neutral. >50 = bullish; <50 = bearish.

### 4c. The fusion — Sentiment-Adjusted Fair Value (SAFV)
```
adjustment = (SentimentIndex − 50) / 50      →  ranges −1 … +1
SAFV = BFV × (1 + k · adjustment)
```
`k` is a **capped tilt factor (default 0.15)** so sentiment can move the number by at most ±15%. This is the honest design choice: sentiment *tilts* a fundamentally-grounded value, it doesn't *replace* it. You can expose `k` as a slider so power users see the sensitivity.

**Why this is smart, not gimmicky:** it separates "what the numbers say" (BFV) from "what the crowd feels" (SentimentIndex) and shows both, plus the blended result. A user who distrusts sentiment can set `k=0` and get pure fundamentals. That transparency is itself a selling point on LinkedIn.

### 4d. The "dynamic sector map" (your crowd angle)
Because sentiment is computed **per sector**, the homepage shows a live heatmap: Tech +, Energy −, Financials neutral, etc. This is the "taking people's sentiments in each sector makes it more dynamic" idea, made concrete. It updates daily and is visually shareable — great for LinkedIn posts.

### 4e. Sector Signals — the "why", anchored in history (the new centrepiece)
The heatmap tells you *that* Energy is bearish; the **Sector Signals** tab tells you *why*, defensibly. For each sector it produces:
- a **main impact** (the dominant driver, e.g. *"Supply-route risk from conflict pushes crude higher; refiners and upstream diverge"*),
- **2–3 supporting drivers** — but only when the picture is genuinely complex,
- and for each, a **forecast range** rather than a fake single number.

The honest part is the split of labour:
- **The AI (Groq) decides *direction* and writes the *narrative*** from that day's headlines.
- **The *magnitude* is NOT invented by the AI.** It comes from a historical volatility table (`pipeline/config.py → SECTOR_EVENT_VOL`): how each sector has *actually* moved during a major event of that type. A Gulf/war supply shock maps Energy to an ~8–18% historical band; the same shock barely moves Consumer Staples (~2–5%). That band is then scaled by how one-sided today's mood is (event severity), and shown as a range — e.g. *"Historical analogue move: −8% to −15%"*.

This directly answers your requirement: reasoning that isn't nonsense, is backed by past sector volatility in response to major events, and expresses uncertainty as a **range** rather than false precision. Every forecast on the site is therefore auditable back to a documented historical band.

### 4f. Multi-market scope
Everything above is computed **per market**. A top-right switcher toggles **India (default) · USA · UK · Japan**, each with its own index (NIFTY 50, S&P 500, FTSE 100, Nikkei 225), watchlist, currency, and sector reads. UK was chosen partly because the City-of-London context fits Meridian's old-money framing; Japan adds a genuinely different sentiment regime in Asia.

---

## 5. The tabs (what the user sees)

1. **Overview** — sector sentiment heatmap + market macro/geo banner (today's dominant theme from GDELT), scoped to the selected market.
2. **Sector Signals** — the "why" per sector: main impact + supporting drivers, each with a history-anchored forecast range (see §4e). This is the credibility centrepiece.
3. **Company** — pick a ticker → Base Fair Value, Sentiment Index, Sentiment-Adjusted Fair Value, the `k` slider, and a one-line plain-English verdict.
4. **Financial News** — top headlines with tone badges (from GDELT + Groq).
5. **Sentiment** — the composition of the index: news tone, macro/geo. Each is a click-to-expand accordion, not just a bar: "News tone" reveals the actual headlines behind that sector's score, each with a one-line Groq-generated note on how that specific headline reads (falls back to a tone-grounded deterministic note if Groq is unavailable); "Macro/Geo" reveals which keyword actually matched today's theme to produce that score, so neither number is asserted without a way to check it.
6. **Methodology** — a static page explaining the model in plain English (pre-empts "is this legit?").

**Top-right:** a **Market switcher** (India · USA · UK · Japan) and a "last updated" stamp.

---

## 6. Tech stack (chosen for zero-cost + your existing conventions)

Matches your `portfolio` folder style (static `index.html` + `css/` + `js/`, `favicon.svg`):

- **Frontend:** plain HTML + vanilla JS + Chart.js (CDN). No build step, no framework — deploys to Pages instantly and stays maintainable. (Upgrade path to React later if you want.)
- **Pipeline:** Python 3 (`requests`, `pandas`). Runs only inside Actions, never in the browser.
- **Data store:** flat JSON files in `site/data/`, committed by the bot each day. This *is* your database — free, versioned, and diff-able (you can literally see sentiment history in git).
- **AI:** Groq (Llama 3.1 8B Instant) via free API key stored as a GitHub Actions Secret (never in the repo).
- **Automation:** one GitHub Actions workflow on a `cron` schedule.

---

## 7. Data-source decision (what was tried, what actually shipped)

The original plan called for a retail-social ingredient (StockTwits primary,
Reddit as enrichment) alongside news and macro. In practice:

- **Prices & fundamentals: Finnhub → Yahoo Finance.** The original plan
  assumed Finnhub's free tier covered all four markets. It doesn't — it's
  US-listed-only. Confirmed via direct API test:
  `GET /quote?symbol=RELIANCE.NS` returned `{"error":"You don't have access
  to this resource."}`, which meant every India/UK/Japan ticker was silently
  getting a ₹0/£0/¥0 fair value in production while looking like it "worked."
  Swapped for Yahoo Finance's unofficial quote API (cookie+crumb handshake,
  no key) which covers all four markets in one batched call per market. It's
  undocumented and not a stable product, so `fetch_market.py` retries with
  backoff and a host fallback, then falls back to mock data per-ticker (or
  per-market on a full batch failure) rather than risk another silent-zero
  incident. See `pipeline/SOURCES.md` for the full trade-off.
- **StockTwits — dropped.** Its public sentiment endpoint, which the original
  design relied on as the "cleanest free retail-sentiment source," is now
  sitting behind a full Cloudflare bot challenge (confirmed July 2026) — not a
  rate limit or an auth requirement, an actual JS challenge page. There's no
  free, legitimate way through that, and building around anti-bot protection
  isn't something this project does. Every ticker fell back to mock data
  silently, which meant 40% of the published Sentiment Index was random noise
  dressed up as a real signal — worse than not having the ingredient at all.
- **Reddit — never built, then dropped too.** It was scoped as a *secondary*
  signal that only made sense paired with a StockTwits backbone. With that
  backbone gone, and with Reddit coverage for non-US small/mid-caps (the
  India/UK/Japan watchlist names) being thin anyway, it wasn't worth building
  just to prop up a corner case. Also considered Polymarket as an alternative
  social-style signal — ruled out on two grounds: it's a prediction-market
  price (event probabilities), not per-stock retail sentiment, so it has
  almost no coverage for individual tickers; and its API appears to
  geo-block non-browser/US-cloud traffic, which would likely break inside a
  GitHub Actions runner anyway.
- **News + macro/geo: GDELT.** Still the quiet winner, unaffected by any of
  the above. Fully free, updates every 15 min, and *already encodes* article
  tone and geo-political event themes (conflict, trade, sanctions) in the
  CAMEO/GKG schema — directly satisfies the "macro-economic and
  geo-political aspects" requirement without building that from scratch.
- **AI layer: Groq (Llama 3.1 8B Instant)**, not the originally-planned
  Gemini — Gemini's free tier returned zero quota on every model for this
  account (confirmed against two separate keys/projects), so it was a dead
  end regardless of code. Groq re-scores the *top* headlines per sector for
  nuance (GDELT's dictionary tone is decent but blunt on financial text).
  Batching keeps us to ~30–60 calls/day, far under the 14,400 free-tier limit.
  `response_format: json_object` is required on the narrative call — the 8B
  model doesn't reliably emit strict JSON otherwise.

**Net result:** Meridian ships as a **news + macro/geo sentiment index**, not
a social one. See §4b for the reweighted formula.

**Avoid:** paid social-sentiment aggregators and Twitter/X API (expensive in
2026). GDELT + Groq covers the signal that's actually free to get, at $0.

**Legal/ToS note:** use official APIs and public endpoints, respect rate limits, and don't republish raw third-party content wholesale — store *derived* scores and short headline snippets with source links. Add a disclaimer: *"Educational/research tool. Not financial advice."*

---

## 8. Phased build plan

### Phase 0 — Repo setup (½ day)
- Create public GitHub repo, push this scaffold.
- Enable GitHub Pages (Settings → Pages → deploy from `main`, `/site` folder or a Pages Action).
- Get a free API key: Groq. (Yahoo Finance needs none.)
- Add the key as a **repository secret** (`GROQ_KEY`).

### Phase 1 — Static shell with sample data (1 day)
- Ship the frontend reading the **sample JSON** already in this scaffold. Site is live and shareable on day one, even before real data flows.
- Tabs render, heatmap works, `k` slider works — all off mock data.

### Phase 2 — Market data pipeline (1–2 days)
- Wire `fetch_market.py` to Yahoo Finance for prices + fundamentals.
- Implement `build_valuation.py` Base Fair Value (multiples first, DCF-lite later).
- Job writes real `companies.json`.

### Phase 3 — Sentiment pipeline (2–3 days)
- `fetch_news.py` (GDELT).
- `score_sentiment.py` (Groq) → sentiment embedded in `companies.json`, plus `sectors.json`.
- Compute SAFV, wire into frontend.

### Phase 4 — Automate (½ day)
- Enable the daily `cron` in the Actions workflow.
- Add "last updated" stamp + graceful fallback (if a source fails, keep yesterday's data and flag it).

### Phase 5 — Polish & launch (1–2 days)
- Methodology page, disclaimer, favicon, OpenGraph tags for nice LinkedIn preview cards.
- Write the LinkedIn launch post (tie into your existing posting schedule).

**Total: ~1–1.5 focused weeks** to a launchable v1.

---

## 9. Risks & honest limitations

| Risk | Mitigation |
|---|---|
| Free API limits change (they did in 2026 — Alpha Vantage dropped to 25/day; Finnhub turned out US-only) | Abstract each source behind one function; document limits/caveats in `pipeline/SOURCES.md`; Yahoo Finance/GDELT/Groq chosen for generous headroom |
| Free social-data sources vanish (StockTwits went behind a bot challenge; Gemini's free tier turned out to have zero quota) | Rather than fake it with a mock fallback dressed as live data, dropped the social ingredient and reweighted the formula (§4b) so every published number is real |
| Sentiment ≠ truth (crowds are often wrong) | Capped `k`, always show BFV alongside; Methodology page is explicit; "not advice" disclaimer |
| Data only daily, not real-time | Deliberate, disclosed via timestamp; framed as a *research* tool not a trading terminal |
| Look-back bias / cherry-picking | git history preserves every day's JSON → you can later show the tool's calls vs. reality (great content) |

---

## 10. What's in this scaffold (so you can run it today)

```
meridian/
├── docs/
│   └── EXECUTABLE_PLAN.md        ← this file
├── site/                         ← the static website (GitHub Pages root)
│   ├── index.html                ← 6 tabs, market switcher, k-slider
│   ├── css/styles.css            ← warm beige/cream theme, spring-physics motion
│   ├── js/app.js                 ← loads manifest → per-market data → renders
│   └── data/                     ← sample JSON so the site works NOW
│       ├── manifest.json         ← markets list + default (India)
│       ├── IN/  {sectors,companies,news,signals}.json
│       ├── US/  {sectors,companies,news,signals}.json
│       ├── UK/  {sectors,companies,news,signals}.json
│       └── JP/  {sectors,companies,news,signals}.json
├── pipeline/                     ← the daily job (Python)
│   ├── config.py                 ← markets, watchlists, weights, k, and the
│   │                                SECTOR_EVENT_VOL historical-vol table
│   ├── fetch_market.py           ← Yahoo Finance prices/fundamentals (per market)
│   ├── fetch_news.py             ← GDELT headlines + tone + macro theme
│   ├── score_sentiment.py        ← Groq sector scoring → Sentiment Index
│   ├── sector_signals.py         ← main/supporting drivers + vol-anchored range
│   ├── build_valuation.py        ← Base Fair Value + Sentiment-Adjusted value
│   ├── run_all.py                ← loops ALL markets, writes data/<MKT>/*.json
│   ├── requirements.txt
│   └── SOURCES.md                ← every API, its free limit, its docs link
├── .github/workflows/
│   ├── daily-update.yml          ← the free cron automation: pipeline + Pages deploy
│   └── pages.yml                 ← Pages redeploy on any direct push to site/**
└── README.md
```

The frontend is fully functional against the sample data immediately — all four markets, all six tabs, the Sector Signals reasoning with forecast ranges. The pipeline runs end-to-end in **mock mode** without any API keys (it generates realistic sample data), so you can test the entire flow offline before signing up for anything. Verified: `python run_all.py` produces all 4 markets; the SAFV formula, the Sentiment Index weighting, and the forecast-range anchoring all reconcile exactly.

---

## 11. Sources (free-tier limits verified July 2026)

- Yahoo Finance quote API (unofficial; no published rate limit — see `pipeline/SOURCES.md` for the reliability caveat and the cookie+crumb mechanism): https://github.com/ranaroussi/yfinance (community reference for the same undocumented endpoints)
- Alpha Vantage free tier now 25/day (why we avoided it): https://www.macroption.com/alpha-vantage-api-limits/
- Finnhub free tier is US-listed-only (why it was dropped after initially being planned): https://finnhub.io/docs/api/rate-limit
- GDELT (fully free, tone + geo events): https://dataresearchtools.com/gdelt-project-for-news-data-2026-free-alternative-to-newsapi/
- Groq free tier (14,400 req/day on Llama 3.1 8B Instant, verified via API rate-limit headers): https://console.groq.com/docs/rate-limits
- GitHub Pages limits: https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
- GitHub Actions free & unlimited for public repos: https://docs.github.com/en/actions/concepts/billing-and-usage
