/* Meridian frontend — 100% static. Reads pre-computed per-market JSON.
   No API keys, no live calls, no per-visitor cost. */

const state = {
  manifest: null, market: null, currency: "$",
  sectors: null, companies: null, news: null, signals: null,
  k: 0.15, selected: null,
  macro: null, macroRendered: false,
};
let companyChart, sentimentChart;
const macroCharts = [];

// ---- safety: every field below that traces back to an external source
// (GDELT headline titles/URLs, Groq-generated notes/narratives) gets built
// via innerHTML template strings for convenience, so it must be escaped --
// GDELT titles are scraped from arbitrary third-party page <title> tags,
// not text we control, so this isn't a hypothetical.
const ESCAPE_MAP = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const escapeHtml = s => String(s ?? "").replace(/[&<>"']/g, ch => ESCAPE_MAP[ch]);
// Only ever emit an http(s) URL as an href -- blocks javascript:/data: etc.
const safeUrl = u => (typeof u === "string" && /^https?:\/\//i.test(u)) ? u : "#";

// ---- boot -----------------------------------------------------------------
async function boot() {
  try {
    state.manifest = await fetch("data/manifest.json").then(r => r.json());
    buildMarketSwitcher();
    state.market = state.manifest.default;
    document.getElementById("market-select").value = state.market;
    await loadMarket(state.market);
  } catch (e) {
    document.getElementById("macro-text").textContent =
      "Could not load data. If running locally, serve with `python -m http.server`.";
    console.error(e);
  }
  // MacroLens: cross-market, independent of the market switcher above, and
  // loaded in its own try/catch so a macro-only failure can't block the rest
  // of the site from rendering. Its tab renders lazily on first click (see
  // the tab-click handler below), not here, to avoid creating ~20 Chart.js
  // sparklines inside a still-hidden (display:none) panel.
  try {
    state.macro = await fetch("data/macro.json").then(r => r.json());
  } catch (e) {
    console.error("[macro] failed to load macro.json", e);
  }
}

function buildMarketSwitcher() {
  const sel = document.getElementById("market-select");
  sel.innerHTML = "";
  state.manifest.markets.forEach(m => {
    const o = document.createElement("option");
    o.value = m.code;
    o.textContent = `${m.name} · ${m.index}`;
    sel.appendChild(o);
  });
}

async function loadMarket(code) {
  state.market = code;
  const base = `data/${code}`;
  const [sectors, companies, news, signals] = await Promise.all([
    fetch(`${base}/sectors.json`).then(r => r.json()),
    fetch(`${base}/companies.json`).then(r => r.json()),
    fetch(`${base}/news.json`).then(r => r.json()),
    fetch(`${base}/signals.json`).then(r => r.json()),
  ]);
  state.sectors = sectors;
  state.companies = companies;
  state.news = news;
  state.signals = signals;
  state.currency = companies.currency || "$";
  state.selected = companies.companies[0].ticker;
  render();
}

// ---- helpers --------------------------------------------------------------
const fmt = n => state.currency + Number(n).toLocaleString(undefined, { maximumFractionDigits: 2 });
const sentColor = s => s >= 60 ? "var(--bull)" : s <= 40 ? "var(--bear)" : "var(--neutral)";
const readColor = label => label === "Bullish" ? "var(--bull)" : label === "Bearish" ? "var(--bear)" : "var(--neutral)";

function safv(bfv, si, k) { return bfv * (1 + k * ((si - 50) / 50)); }

// ---- physics: spring-eased number count-up ---------------------------------
// Critically-damped spring integrator rather than a plain tween, so values
// settle with a touch of natural momentum instead of a linear/eased slide.
// Tracks its OWN live position on the element (el._pos) rather than trusting
// a separately-cached "previous target" as the start point -- rapid
// re-triggering (e.g. clicking through tickers faster than a ~1s settle
// time) used to snap discontinuously because the old "from" was always the
// prior call's target, not wherever the animation had actually reached when
// interrupted.
function animateValue(el, to, { decimals = 2, prefix = "", suffix = "", stiffness = 170, damping = 26 } = {}) {
  cancelAnimationFrame(el._raf || 0);
  let pos = el._pos ?? to, vel = el._vel ?? 0, last = performance.now();
  function step(now) {
    const dt = Math.min((now - last) / 1000, 1 / 30);
    last = now;
    const force = -stiffness * (pos - to) - damping * vel;
    vel += force * dt;
    pos += vel * dt;
    const settled = Math.abs(pos - to) < 0.01 && Math.abs(vel) < 0.01;
    el._pos = settled ? to : pos;
    el._vel = settled ? 0 : vel;
    el.textContent = prefix + (settled ? to : pos).toLocaleString(undefined,
      { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + suffix;
    if (!settled) el._raf = requestAnimationFrame(step);
  }
  el._raf = requestAnimationFrame(step);
}

// ---- physics: pointer-tilt on cards -----------------------------------------
// Subtle 3D tilt following the cursor, spring-eased back to rest on leave.
function attachTilt(el, { max = 6 } = {}) {
  let raf;
  el.addEventListener("mousemove", e => {
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      el.style.transform = `translateY(-4px) rotateX(${(-py * max).toFixed(2)}deg) rotateY(${(px * max).toFixed(2)}deg)`;
    });
  });
  el.addEventListener("mouseleave", () => {
    cancelAnimationFrame(raf);
    el.style.transform = "";
  });
}
function attachTiltAll(selector) {
  document.querySelectorAll(selector).forEach(el => {
    if (el._tiltBound) return;
    el._tiltBound = true;
    el.style.transformStyle = "preserve-3d";
    attachTilt(el);
  });
}
function verdictText(bfv, adj) {
  const d = ((adj - bfv) / bfv) * 100;
  if (d > 3) return `Crowd optimism lifts value +${d.toFixed(1)}%`;
  if (d < -3) return `Crowd caution trims value ${d.toFixed(1)}%`;
  return "Sentiment roughly neutral vs. fundamentals";
}

// ---- render ---------------------------------------------------------------
function render() {
  document.getElementById("updated-at").textContent = state.companies.updated_at || "—";
  document.getElementById("ov-index").textContent = state.sectors.index || "";
  document.getElementById("macro-text").innerHTML =
    "<strong>Macro / Geo theme:</strong> " + escapeHtml(state.sectors.macro_theme || "Markets calm");
  renderHeatmap();
  renderSignals();
  renderTickerSelect();
  renderCompany();
  renderNews();
  const active = document.querySelector(".tab.active");
  if (active) moveTabIndicator(active);
}

function renderHeatmap() {
  const el = document.getElementById("heatmap");
  el.innerHTML = "";
  state.sectors.sectors.forEach((s, i) => {
    const c = sentColor(s.score);
    const cell = document.createElement("div");
    cell.className = "heat-cell";
    cell.style.setProperty("--i", i);
    cell.style.background = `linear-gradient(180deg, ${c}22, transparent)`;
    cell.style.borderColor = c;
    cell.innerHTML = `
      <div class="sector-name">${s.name}</div>
      <div class="sector-score" style="color:${c}">${s.score}</div>
      <div class="sector-sub" style="color:${c}">${s.label}</div>`;
    el.appendChild(cell);
  });
  attachTiltAll("#heatmap .heat-cell");
}

// The new Sector Signals tab: reasoning + forecast ranges, shown inline.
function renderSignals() {
  const el = document.getElementById("signals-list");
  el.innerHTML = "";
  state.signals.signals.forEach((sig, i) => {
    const rc = readColor(sig.read);
    const card = document.createElement("div");
    card.className = "signal-card";
    card.style.setProperty("--i", i);
    card.style.borderLeftColor = rc;

    let driversHtml = "";
    sig.drivers.forEach(d => {
      const roleLabel = d.role === "main" ? "Main impact" : "Supporting";
      const f = d.forecast;
      const fColor = f.direction === "-" ? "var(--bear)" : "var(--bull)";
      driversHtml += `
        <div class="driver ${d.role}">
          <div class="driver-role">${roleLabel}</div>
          <div class="driver-text">${escapeHtml(d.text)}</div>
          <div class="forecast">Historical analogue move:
            <span class="band" style="color:${fColor}">${escapeHtml(f.text)}</span></div>
        </div>`;
    });

    card.innerHTML = `
      <div class="signal-head">
        <span class="signal-sector">${escapeHtml(sig.sector)}</span>
        <span class="signal-read" style="color:${rc}; border:1px solid ${rc}">${escapeHtml(sig.read)} · ${escapeHtml(sig.score)}</span>
      </div>
      <div class="signal-event">Driving event type: ${escapeHtml(sig.event_type.replace(/_/g, " "))}</div>
      ${driversHtml}`;
    el.appendChild(card);
  });
}

function renderTickerSelect() {
  const sel = document.getElementById("ticker-select");
  sel.innerHTML = "";
  state.companies.companies.forEach(c => {
    const o = document.createElement("option");
    o.value = c.ticker;
    o.textContent = `${c.ticker} — ${c.name}`;
    sel.appendChild(o);
  });
  sel.value = state.selected;
}

function currentCompany() {
  return state.companies.companies.find(c => c.ticker === state.selected)
      || state.companies.companies[0];
}

function renderCompany() {
  const c = currentCompany();
  const adjusted = safv(c.base_fair_value, c.sentiment_index, state.k);

  animateValue(document.getElementById("price"), c.price, { decimals: 2, prefix: state.currency });
  animateValue(document.getElementById("bfv"), c.base_fair_value, { decimals: 2, prefix: state.currency });

  const si = document.getElementById("sent-index");
  animateValue(si, c.sentiment_index, { decimals: 1 });
  si.style.color = sentColor(c.sentiment_index);

  animateValue(document.getElementById("safv"), adjusted, { decimals: 2, prefix: state.currency });

  document.getElementById("verdict").textContent = verdictText(c.base_fair_value, adjusted);
  renderCompanyChart(c, adjusted);
  renderSentimentChart(c);
  renderSentimentBreakdown(c);
  attachTiltAll(".cards .card");
}

const CHART_ANIM = { duration: 650, easing: "easeOutQuint" };

// Chart.js's canvas fillStyle can't resolve CSS custom properties directly
// (var(--x) passed straight to a canvas context silently renders as black --
// this exact bug already shipped once). Every chart color reads through
// this helper instead of a hardcoded hex, so the charts can never drift out
// of sync with styles.css's actual palette again.
function cssVar(name) {
  return getComputedStyle(document.body).getPropertyValue(name).trim();
}
function resolvedSentColor(score) {
  return cssVar(score >= 60 ? "--bull" : score <= 40 ? "--bear" : "--neutral");
}

function renderCompanyChart(c, adjusted) {
  const ctx = document.getElementById("company-chart");
  ctx.setAttribute("aria-label",
    `Bar chart comparing current price ${fmt(c.price)}, Base Fair Value ${fmt(c.base_fair_value)}, ` +
    `and Sentiment-Adjusted Fair Value ${fmt(adjusted)} for ${c.ticker}.`);
  const data = {
    labels: ["Current Price", "Base Fair Value", "Sentiment-Adjusted"],
    datasets: [{
      label: state.currency,
      data: [c.price, c.base_fair_value, adjusted],
      backgroundColor: [cssVar("--price-neutral"), cssVar("--accent"), resolvedSentColor(c.sentiment_index)],
      borderRadius: 4,
    }]
  };
  if (companyChart) { companyChart.data = data; companyChart.update(); return; }
  companyChart = new Chart(ctx, {
    type: "bar", data,
    options: {
      animation: CHART_ANIM,
      plugins: { legend: { display: false } },
      scales: { y: { ticks: { color: cssVar("--ink-dim") }, grid: { color: cssVar("--line") } },
                x: { ticks: { color: cssVar("--ink-dim") }, grid: { color: "transparent" } } }
    }
  });
}

function sentimentBarClick(evt, elements) {
  if (!elements.length) return;
  const id = elements[0].index === 0 ? "acc-news" : "acc-macro";
  openAccordion(id, true);
  document.getElementById(id).scrollIntoView({ behavior: "smooth", block: "center" });
}
function sentimentBarHover(evt, elements) {
  evt.native.target.style.cursor = elements.length ? "pointer" : "default";
}

function renderSentimentChart(c) {
  const ctx = document.getElementById("sentiment-chart");
  const b = c.sentiment_breakdown;
  ctx.setAttribute("aria-label",
    `Bar chart of the Sentiment Index composition for ${c.ticker}: news tone ${b.news}, macro/geo ${b.macro}, out of 100.`);
  const data = {
    labels: ["News tone", "Macro / Geo"],
    datasets: [{
      label: "Contribution (0-100)",
      data: [b.news, b.macro],
      backgroundColor: [cssVar("--accent"), cssVar("--ink-dim")],
      borderRadius: 4,
    }]
  };
  if (sentimentChart) {
    sentimentChart.data = data;
    sentimentChart.update();
    return;
  }
  sentimentChart = new Chart(ctx, {
    type: "bar", data,
    options: {
      animation: CHART_ANIM,
      onClick: sentimentBarClick,
      onHover: sentimentBarHover,
      plugins: { legend: { display: false } },
      scales: { y: { min: 0, max: 100, ticks: { color: cssVar("--ink-dim") }, grid: { color: cssVar("--line") } },
                x: { ticks: { color: cssVar("--ink-dim") }, grid: { color: "transparent" } } }
    }
  });
}

// ---- Sentiment tab: the "why" behind each bar ------------------------------
function openAccordion(id, forceOpen) {
  const acc = document.getElementById(id);
  const body = acc.querySelector(".accordion-body");
  const open = forceOpen === undefined ? !acc.classList.contains("open") : forceOpen;
  acc.classList.toggle("open", open);
  body.style.maxHeight = open ? body.scrollHeight + "px" : "0px";
}

function renderSentimentBreakdown(c) {
  document.getElementById("news-score-label").textContent = c.sentiment_breakdown.news.toFixed(1);
  document.getElementById("news-sector-label").textContent = c.sector;

  const relevant = state.news.items.filter(n => n.sector === c.sector || n.sector === "Market");
  const list = document.getElementById("news-breakdown-list");
  list.innerHTML = "";
  if (relevant.length === 0) {
    list.innerHTML = '<p class="muted small">No sector-specific headlines in today’s pull.</p>';
  } else {
    relevant.forEach((n, i) => {
      const cls = n.tone > 1 ? "tone-pos" : n.tone < -1 ? "tone-neg" : "tone-neu";
      const label = n.tone > 1 ? "Positive" : n.tone < -1 ? "Negative" : "Neutral";
      const item = document.createElement("div");
      item.className = "news-item";
      item.style.setProperty("--i", i);
      item.innerHTML = `
        <div class="news-item-main">
          <a href="${escapeHtml(safeUrl(n.url))}" target="_blank" rel="noopener">${escapeHtml(n.title)}<span class="sr-only"> (opens in new tab)</span></a>
          <div class="news-note">${escapeHtml(n.note || "")}</div>
        </div>
        <span class="tone-badge ${cls}">${label}</span>`;
      list.appendChild(item);
    });
  }

  document.getElementById("macro-score-label").textContent = state.sectors.macro_score;
  document.getElementById("macro-theme-label").textContent =
    "Today's macro/geo theme: " + (state.sectors.macro_theme || "—");
  document.getElementById("macro-explanation-label").textContent = state.sectors.macro_explanation || "";

  resyncOpenAccordions();
}

function renderNews() {
  const el = document.getElementById("news-list");
  el.innerHTML = "";
  state.news.items.forEach((n, i) => {
    const cls = n.tone > 1 ? "tone-pos" : n.tone < -1 ? "tone-neg" : "tone-neu";
    const label = n.tone > 1 ? "Positive" : n.tone < -1 ? "Negative" : "Neutral";
    const item = document.createElement("div");
    item.className = "news-item";
    item.style.setProperty("--i", i);
    item.innerHTML = `
      <a href="${escapeHtml(safeUrl(n.url))}" target="_blank" rel="noopener">${escapeHtml(n.title)} <span class="muted">· ${escapeHtml(n.sector)}</span><span class="sr-only"> (opens in new tab)</span></a>
      <span class="tone-badge ${cls}">${label}</span>`;
    el.appendChild(item);
  });
}

// ---- MACRO (MacroLens) -----------------------------------------------------
// Rendered lazily on first visit to the tab (see the tab-click handler
// below) rather than during boot(), so its ~20 small Chart.js sparklines
// are never created while the panel is still display:none.
const MACRO_INDICATORS = [
  { key: "cpi", color: "--bear" },
  { key: "gdp_growth", color: "--bull" },
  { key: "unemployment", color: "--neutral" },
  { key: "policy_rate", color: "--accent" },
  { key: "fx", color: "--price-neutral" },
];

function macroFreqLabel(freq) {
  return { annual: "Annual", daily: "Daily", monthly: "Monthly",
            "as announced": "As announced", "n/a": "N/A" }[freq] || freq;
}
function macroAsOfLabel(ind) {
  if (!ind || !ind.as_of) return "";
  return `${macroFreqLabel(ind.frequency)} · as of ${ind.as_of}`;
}
function macroValueText(ind) {
  if (!ind || ind.latest === null || ind.latest === undefined) return "N/A";
  return ind.unit === "%" ? `${ind.latest}%` : `${ind.latest} ${ind.unit || ""}`.trim();
}

function renderMacro() {
  if (!state.macro || !state.macro.markets) {
    document.getElementById("macro-cards").innerHTML =
      '<p class="muted">Macro data unavailable.</p>';
    document.getElementById("macro-compare").innerHTML = "";
    return;
  }
  document.getElementById("macro-updated").textContent =
    `Refreshed ${state.macro.updated_at}.`;
  renderMacroCompare();
  renderMacroCards();
}

// One mini bar chart per indicator, all four markets on the same axis --
// each market keeps its OWN as-of date (World Bank lag differs by country,
// e.g. the US's latest CPI year can trail the others), surfaced in the
// tooltip and the sub-line rather than implying every bar is the same
// vintage.
function renderMacroCompare() {
  const el = document.getElementById("macro-compare");
  el.innerHTML = "";
  MACRO_INDICATORS.forEach(({ key }, i) => {
    const codes = Object.keys(state.macro.markets);
    const isFx = key === "fx";
    let rows = codes
      .map(code => ({ code, ind: state.macro.markets[code][key] }))
      .filter(r => r.ind && r.ind.latest !== null && r.ind.latest !== undefined);

    // Raw FX levels use different quote conventions per market (INR per USD,
    // USD per GBP, JPY per USD) -- not comparable on one linear axis (the
    // USD/GBP bar would sit at ~1.3 next to JPY/USD's ~160 and be invisible).
    // Show 1Y % change vs USD instead, which genuinely IS apples-to-apples
    // across markets; the per-market cards below still carry each one's real
    // level + sparkline in its own native quote.
    if (isFx) {
      rows = rows
        .map(r => {
          const s = r.ind.series;
          if (!s || s.length < 2 || !s[0].value) return null;
          let pctChange = ((s[s.length - 1].value - s[0].value) / s[0].value) * 100;
          // Quote convention differs by market: "INR per USD"/"JPY per USD"
          // have USD as the base, so a RISING number means the local
          // currency DEPRECIATED -- negate so positive consistently means
          // "the local currency strengthened" everywhere. "USD per GBP"
          // already has GBP as the base, so rising already means GBP
          // strengthened; no negation there (unit === "USD" marks that case).
          if (r.ind.unit !== "USD") pctChange = -pctChange;
          return { ...r, displayValue: Math.round(pctChange * 100) / 100 };
        })
        .filter(Boolean);
    } else {
      rows = rows.map(r => ({ ...r, displayValue: r.ind.latest }));
    }
    if (rows.length === 0) return;

    const wrap = document.createElement("div");
    wrap.className = "macro-compare-card";
    wrap.style.setProperty("--i", i);
    const label = isFx ? "Currency vs USD (1Y % change)" : rows[0].ind.label;
    const subText = isFx
      ? "1-year % change vs USD from Frankfurter daily rates — positive means the currency strengthened. Raw levels use different quote conventions per market; see the cards below for those."
      : "Each market's own latest reading — as-of dates differ; hover a bar, or see the cards below.";
    wrap.innerHTML = `
      <div class="macro-compare-label">${escapeHtml(label)}</div>
      <div class="chart-wrap macro-compare-chart"><canvas></canvas></div>
      <div class="macro-compare-sub muted small">${escapeHtml(subText)}</div>`;
    el.appendChild(wrap);

    const ctx = wrap.querySelector("canvas");
    const unit = rows[0].ind.unit || "";
    const chart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: rows.map(r => r.code),
        datasets: [{
          data: rows.map(r => r.displayValue),
          backgroundColor: cssVar("--accent"),
          borderRadius: 4,
        }],
      },
      options: {
        animation: CHART_ANIM,
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: item => {
            const r = rows[item.dataIndex];
            return isFx
              ? `${r.displayValue > 0 ? "+" : ""}${r.displayValue}% vs USD over 1Y (${r.ind.label}, as of ${r.ind.as_of})`
              : `${r.ind.latest}${unit === "%" ? "%" : " " + unit} (as of ${r.ind.as_of})`;
          } } },
        },
        scales: {
          y: { ticks: { color: cssVar("--ink-dim") }, grid: { color: cssVar("--line") } },
          x: { ticks: { color: cssVar("--ink-dim") }, grid: { color: "transparent" } },
        },
      },
    });
    macroCharts.push(chart);
  });
}

function macroSparkline(canvas, series, color) {
  return new Chart(canvas, {
    type: "line",
    data: {
      labels: series.map(p => p.date),
      datasets: [{
        data: series.map(p => p.value),
        borderColor: color, borderWidth: 1.5, pointRadius: 0, tension: .25, fill: false,
      }],
    },
    options: {
      // Sparklines are fixed-height (see .macro-spark-wrap in CSS). Without
      // maintainAspectRatio:false, Chart.js ignores the CSS height and forces
      // a 2:1 aspect ratio off the card width — which rendered these ~130px+
      // tall and blew the By-market cards out of proportion.
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: { legend: { display: false }, tooltip: { enabled: false } },
      scales: { x: { display: false }, y: { display: false } },
    },
  });
}

function renderMacroCards() {
  const el = document.getElementById("macro-cards");
  el.innerHTML = "";
  Object.entries(state.macro.markets).forEach(([code, m], i) => {
    const meta = (state.manifest.markets || []).find(mm => mm.code === code) || {};
    const card = document.createElement("div");
    card.className = "macro-card";
    card.style.setProperty("--i", i);

    const statsHtml = MACRO_INDICATORS.map(({ key }) => {
      const ind = m[key];
      const label = ind ? ind.label : key;
      const sub = (ind && ind.as_of) ? macroAsOfLabel(ind) : (ind && ind.note) || "";
      const hasSeries = ind && ind.series && ind.series.length >= 2;
      return `
        <div class="macro-stat">
          <div class="macro-stat-label">${escapeHtml(label)}</div>
          <div class="macro-stat-value${ind && ind.latest != null ? "" : " muted"}">${escapeHtml(macroValueText(ind))}</div>
          <div class="macro-stat-sub">${escapeHtml(sub)}</div>
          ${hasSeries ? `<div class="macro-spark-wrap"><canvas class="macro-spark" data-key="${key}"></canvas></div>` : ""}
        </div>`;
    }).join("");

    card.innerHTML = `
      <div class="macro-card-head">
        <span class="macro-card-market">${escapeHtml(meta.name || code)}</span>
        <span class="macro-card-index muted">${escapeHtml(meta.index || "")}</span>
      </div>
      <div class="macro-stats">${statsHtml}</div>
      <p class="macro-narrative">${escapeHtml(m.narrative || "")}</p>`;
    el.appendChild(card);

    MACRO_INDICATORS.forEach(({ key, color }) => {
      const ind = m[key];
      if (!ind || !ind.series || ind.series.length < 2) return;
      const canvas = card.querySelector(`canvas[data-key="${key}"]`);
      if (!canvas) return;
      macroCharts.push(macroSparkline(canvas, ind.series, cssVar(color)));
    });
  });
  attachTiltAll(".macro-card");
}

// ---- interactions ---------------------------------------------------------
function moveTabIndicator(tab) {
  const indicator = document.getElementById("tab-indicator");
  const nav = tab.parentElement;
  const navRect = nav.getBoundingClientRect();
  const tabRect = tab.getBoundingClientRect();
  const x = tabRect.left - navRect.left + nav.scrollLeft;
  indicator.style.transform = `translateX(${x}px) scaleX(${tabRect.width})`;
}

// Recompute any OPEN accordion's max-height. Without this, resizing the
// window (or rotating a phone, or an OS text-size change) while an
// accordion is expanded leaves it pinned to whatever scrollHeight it had at
// click-time -- content that now needs more room (e.g. headlines wrapping
// to more lines at a narrower width) gets silently clipped under
// overflow:hidden with no scrollbar and no visual cue more exists.
function resyncOpenAccordions() {
  document.querySelectorAll(".accordion.open").forEach(acc => {
    const body = acc.querySelector(".accordion-body");
    body.style.maxHeight = body.scrollHeight + "px";
  });
}

document.querySelectorAll(".tab").forEach(t => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => {
      x.classList.remove("active");
      x.setAttribute("aria-selected", "false");
    });
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    t.classList.add("active");
    t.setAttribute("aria-selected", "true");
    document.getElementById(t.dataset.tab).classList.add("active");
    moveTabIndicator(t);
    // Charts created while their panel was display:none never get a real
    // draw buffer (Chart.js can't size a canvas inside a hidden parent) --
    // force a resize now that the panel is actually visible.
    requestAnimationFrame(() => {
      if (companyChart) companyChart.resize();
      if (sentimentChart) sentimentChart.resize();
      if (t.dataset.tab === "macro") {
        if (!state.macroRendered) { renderMacro(); state.macroRendered = true; }
        else macroCharts.forEach(c => c.resize());
      }
    });
  });
});

document.querySelectorAll(".accordion-head").forEach(btn => {
  btn.addEventListener("click", () => {
    openAccordion(btn.parentElement.id);
    const open = btn.parentElement.classList.contains("open");
    btn.setAttribute("aria-expanded", String(open));
  });
});
window.addEventListener("resize", () => {
  const active = document.querySelector(".tab.active");
  if (active) moveTabIndicator(active);
  resyncOpenAccordions();
});
window.addEventListener("load", () => {
  const active = document.querySelector(".tab.active");
  if (active) moveTabIndicator(active);
});

document.getElementById("market-select").addEventListener("change", e => loadMarket(e.target.value));
document.getElementById("ticker-select").addEventListener("change", e => {
  state.selected = e.target.value; renderCompany();
});
function updateSliderFill(el) {
  const pct = ((el.value - el.min) / (el.max - el.min)) * 100;
  el.style.setProperty("--pct", pct + "%");
}
const kSlider = document.getElementById("k-slider");
kSlider.addEventListener("input", e => {
  state.k = parseFloat(e.target.value);
  document.getElementById("k-val").textContent = state.k.toFixed(2);
  updateSliderFill(e.target);
  renderCompany();
});
updateSliderFill(kSlider);

boot();
