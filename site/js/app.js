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
}

function renderHeatmap() {
  const el = document.getElementById("heatmap");
  el.innerHTML = "";
  state.sectors.sectors.forEach(s => {
    const c = sentColor(s.score);
    const cell = document.createElement("div");
    cell.className = "heat-cell";
    cell.style.background = `linear-gradient(180deg, ${c}22, transparent)`;
    cell.style.borderColor = c;
    cell.innerHTML = `
      <div class="sector-name">${s.name}</div>
      <div class="sector-score" style="color:${c}">${s.score}</div>
      <div class="sector-sub" style="color:${c}">${s.label}</div>`;
    el.appendChild(cell);
  });
}

// The new Sector Signals tab: reasoning + forecast ranges, shown inline.
function renderSignals() {
  const el = document.getElementById("signals-list");
  el.innerHTML = "";
  state.signals.signals.forEach(sig => {
    const rc = readColor(sig.read);
    const card = document.createElement("div");
    card.className = "signal-card";
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
  document.getElementById("bfv").textContent = fmt(c.base_fair_value);
  const si = document.getElementById("sent-index");
  si.textContent = c.sentiment_index;
  si.style.color = sentColor(c.sentiment_index);
  document.getElementById("safv").textContent = fmt(adjusted);
  document.getElementById("verdict").textContent = verdictText(c.base_fair_value, adjusted);
  renderCompanyChart(c, adjusted);
  renderSentimentChart(c);
}

function renderCompanyChart(c, adjusted) {
  const ctx = document.getElementById("company-chart");
  const data = {
    labels: ["Current Price", "Base Fair Value", "Sentiment-Adjusted"],
    datasets: [{
      label: state.currency,
      data: [c.price, c.base_fair_value, adjusted],
      backgroundColor: ["#6b6250", "#3d6a86", sentColor(c.sentiment_index)],
    }]
  };
  if (companyChart) { companyChart.data = data; companyChart.update(); return; }
  companyChart = new Chart(ctx, {
    type: "bar", data,
    options: {
      plugins: { legend: { display: false } },
      scales: { y: { ticks: { color: "#b9b09b" }, grid: { color: "#2c4055" } },
                x: { ticks: { color: "#b9b09b" }, grid: { color: "transparent" } } }
    }
  });
}

function renderSentimentChart(c) {
  const ctx = document.getElementById("sentiment-chart");
  const b = c.sentiment_breakdown;
  const data = {
    labels: ["Social mood", "News tone", "Macro / Geo"],
    datasets: [{
      label: "Contribution (0-100)",
      data: [b.social, b.news, b.macro],
      backgroundColor: "rgba(201,162,39,.25)",
      borderColor: "#c9a227", pointBackgroundColor: "#c9a227",
    }]
  };
  if (sentimentChart) { sentimentChart.data = data; sentimentChart.update(); return; }
  sentimentChart = new Chart(ctx, {
    type: "radar", data,
    options: {
      scales: { r: { min: 0, max: 100, ticks: { color: "#b9b09b", backdropColor: "transparent" },
                     grid: { color: "#2c4055" }, angleLines: { color: "#2c4055" },
                     pointLabels: { color: "#f3ecdd", font: { size: 13 } } } },
      plugins: { legend: { labels: { color: "#f3ecdd" } } }
    }
  });
}

function renderNews() {
  const el = document.getElementById("news-list");
  el.innerHTML = "";
  state.news.items.forEach(n => {
    const cls = n.tone > 1 ? "tone-pos" : n.tone < -1 ? "tone-neg" : "tone-neu";
    const label = n.tone > 1 ? "Positive" : n.tone < -1 ? "Negative" : "Neutral";
    const item = document.createElement("div");
    item.className = "news-item";
    item.innerHTML = `
      <a href="${n.url}" target="_blank" rel="noopener">${n.title} <span class="muted">· ${n.sector}</span></a>
      <span class="tone-badge ${cls}">${label}</span>`;
    el.appendChild(item);
  });
}

// ---- interactions ---------------------------------------------------------
document.querySelectorAll(".tab").forEach(t => {
  t.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    t.classList.add("active");
    document.getElementById(t.dataset.tab).classList.add("active");
  });
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
