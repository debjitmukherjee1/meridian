/* Meridian frontend — 100% static. Reads pre-computed per-market JSON.
   No API keys, no live calls, no per-visitor cost. */

const state = {
  manifest: null, market: null, currency: "$",
  sectors: null, companies: null, news: null, signals: null,
  k: 0.15, selected: null,
};
let companyChart, sentimentChart;

// ---- boot -----------------------------------------------------------------
async function boot() {
  try {
    state.manifest = await fetch("data/manifest.json").then(r => r.json());
    buildMarketSwitcher();
    state.market = state.manifest.default;
    document.getElementById("market-select").value = state.market;
    await loadMarket(state.market);
  } catch (e) {
    document.getElementById("macro-banner").textContent =
      "Could not load data. If running locally, serve with `python -m http.server`.";
    console.error(e);
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
function animateValue(el, from, to, { decimals = 2, prefix = "", suffix = "", stiffness = 170, damping = 26 } = {}) {
  cancelAnimationFrame(el._raf || 0);
  let pos = from, vel = 0, last = performance.now();
  function step(now) {
    const dt = Math.min((now - last) / 1000, 1 / 30);
    last = now;
    const force = -stiffness * (pos - to) - damping * vel;
    vel += force * dt;
    pos += vel * dt;
    const settled = Math.abs(pos - to) < 0.01 && Math.abs(vel) < 0.01;
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
  document.getElementById("macro-banner").innerHTML =
    "🌍 <strong>Macro / Geo theme:</strong> " + (state.sectors.macro_theme || "Markets calm");
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
          <div class="driver-text">${d.text}</div>
          <div class="forecast">Historical analogue move:
            <span class="band" style="color:${fColor}">${f.text}</span></div>
        </div>`;
    });

    card.innerHTML = `
      <div class="signal-head">
        <span class="signal-sector">${sig.sector}</span>
        <span class="signal-read" style="color:${rc}; border:1px solid ${rc}">${sig.read} · ${sig.score}</span>
      </div>
      <div class="signal-event">Driving event type: ${sig.event_type.replace(/_/g, " ")}</div>
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

  const bfvEl = document.getElementById("bfv");
  animateValue(bfvEl, parseFloat(bfvEl.dataset.raw || c.base_fair_value), c.base_fair_value,
    { decimals: 2, prefix: state.currency });
  bfvEl.dataset.raw = c.base_fair_value;

  const si = document.getElementById("sent-index");
  animateValue(si, parseFloat(si.dataset.raw || c.sentiment_index), c.sentiment_index, { decimals: 1 });
  si.dataset.raw = c.sentiment_index;
  si.style.color = sentColor(c.sentiment_index);

  const safvEl = document.getElementById("safv");
  animateValue(safvEl, parseFloat(safvEl.dataset.raw || adjusted), adjusted,
    { decimals: 2, prefix: state.currency });
  safvEl.dataset.raw = adjusted;

  document.getElementById("verdict").textContent = verdictText(c.base_fair_value, adjusted);
  renderCompanyChart(c, adjusted);
  renderSentimentChart(c);
  attachTiltAll(".cards .card");
}

const CHART_ANIM = { duration: 650, easing: "easeOutQuint" };

function resolvedSentColor(score) {
  return getComputedStyle(document.body).getPropertyValue(
    score >= 60 ? "--bull" : score <= 40 ? "--bear" : "--neutral").trim();
}

function renderCompanyChart(c, adjusted) {
  const ctx = document.getElementById("company-chart");
  const data = {
    labels: ["Current Price", "Base Fair Value", "Sentiment-Adjusted"],
    datasets: [{
      label: state.currency,
      data: [c.price, c.base_fair_value, adjusted],
      backgroundColor: ["#a89a7c", "#9c6b2e", resolvedSentColor(c.sentiment_index)],
      borderRadius: 4,
    }]
  };
  if (companyChart) { companyChart.data = data; companyChart.update(); return; }
  companyChart = new Chart(ctx, {
    type: "bar", data,
    options: {
      animation: CHART_ANIM,
      plugins: { legend: { display: false } },
      scales: { y: { ticks: { color: "#6b6153" }, grid: { color: "#ddd0b3" } },
                x: { ticks: { color: "#6b6153" }, grid: { color: "transparent" } } }
    }
  });
}

function renderSentimentChart(c) {
  const ctx = document.getElementById("sentiment-chart");
  const b = c.sentiment_breakdown;
  const data = {
    labels: ["News tone", "Macro / Geo"],
    datasets: [{
      label: "Contribution (0-100)",
      data: [b.news, b.macro],
      backgroundColor: ["#9c6b2e", "#6b6153"],
      borderRadius: 4,
    }]
  };
  if (sentimentChart) { sentimentChart.data = data; sentimentChart.update(); return; }
  sentimentChart = new Chart(ctx, {
    type: "bar", data,
    options: {
      animation: CHART_ANIM,
      plugins: { legend: { display: false } },
      scales: { y: { min: 0, max: 100, ticks: { color: "#6b6153" }, grid: { color: "#ddd0b3" } },
                x: { ticks: { color: "#6b6153" }, grid: { color: "transparent" } } }
    }
  });
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
      <a href="${n.url}" target="_blank" rel="noopener">${n.title} <span class="muted">· ${n.sector}</span></a>
      <span class="tone-badge ${cls}">${label}</span>`;
    el.appendChild(item);
  });
}

// ---- interactions ---------------------------------------------------------
function moveTabIndicator(tab) {
  const indicator = document.getElementById("tab-indicator");
  const nav = tab.parentElement;
  const navRect = nav.getBoundingClientRect();
  const tabRect = tab.getBoundingClientRect();
  indicator.style.left = (tabRect.left - navRect.left + nav.scrollLeft) + "px";
  indicator.style.width = tabRect.width + "px";
}

document.querySelectorAll(".tab").forEach(t => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    t.classList.add("active");
    document.getElementById(t.dataset.tab).classList.add("active");
    moveTabIndicator(t);
  });
});
window.addEventListener("resize", () => {
  const active = document.querySelector(".tab.active");
  if (active) moveTabIndicator(active);
});
window.addEventListener("load", () => {
  const active = document.querySelector(".tab.active");
  if (active) moveTabIndicator(active);
});

document.getElementById("market-select").addEventListener("change", e => loadMarket(e.target.value));
document.getElementById("ticker-select").addEventListener("change", e => {
  state.selected = e.target.value; renderCompany();
});
document.getElementById("k-slider").addEventListener("input", e => {
  state.k = parseFloat(e.target.value);
  document.getElementById("k-val").textContent = state.k.toFixed(2);
  renderCompany();
});

boot();
