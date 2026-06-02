/* GridClean console — talks to the live API on the same origin (/v1/...).
   DOM is built with a tiny safe hyperscript helper `h()` (text becomes text
   nodes, so values from the API can never inject markup). No innerHTML. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === "class") e.className = v;
    else if (k === "style") e.style.cssText = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid == null) continue;
    e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return e;
}
const fill = (node, ...kids) => { node.replaceChildren(...kids.flat().filter((x) => x != null)); };

// ── skeletons ───────────────────────────────────────────────────────────
// Shimmer placeholders that match each component's real layout 1:1, so data
// swaps in with zero layout shift. Shown the instant a load starts (incl. on
// every region change) and cleared by the matching render — or reset on error.
const skBlock = (w, ht) => h("span", { class: "sk", style: `display:block;width:${w};height:${ht}` });
const skLine = (w = "100%") => h("li", {}, skBlock(w, "10px"));
const fuelSkRow = () =>
  h("li", { class: "fuel-row" },
    skBlock("80%", "10px"),
    h("span", { class: "fuel-track" }, h("span", { class: "fuel-fill sk", style: `width:${20 + Math.random() * 60}%` })),
    skBlock("70%", "10px"));
const cmpSkRow = () =>
  h("li", { class: "cmp-row" },
    skBlock("70%", "12px"),
    h("span", { class: "cmp-track" }, h("span", { class: "cmp-fill sk", style: `width:${30 + Math.random() * 60}%` })),
    skBlock("60%", "14px"));
const rankSkRow = () =>
  h("li", { class: "flex items-center gap-2" },
    h("span", { class: "sk", style: "width:8px;height:8px;border-radius:999px" }),
    skBlock("7rem", "10px"), skBlock("2rem", "10px"));

// Fixed text fields: skeleton placeholder (sized like real content) ↔ dash.
const NOW_FIELDS = {
  "#now-region": ["Region Name", "—"], "#now-sub": ["CODE · Jan 0, 00:00 AM", "—"],
  "#now-badge": ["moderate", "—"], "#now-value": ["888", "––"],
  "#now-renew": ["00%", "—"], "#now-cfree": ["00%", "—"],
};
const CLEAN_FIELDS = { "#clean-when": ["Mon 00:00", "—"], "#clean-value": ["888", "––"] };

function fieldsState(map, mode) {
  // mode: "sk" → skeleton, "reset" → dash, "clear" → just drop the class
  for (const [sel, [ph, dash]] of Object.entries(map)) {
    const e = $(sel);
    // Clear any inline color/background a prior render set (e.g. the badge fill
    // or the big-number color) so the shimmer shows through on a re-skeleton.
    if (mode === "sk") { e.classList.add("skeleton"); e.textContent = ph; e.style.color = ""; e.style.background = ""; }
    else { e.classList.remove("skeleton"); if (mode === "reset") e.textContent = dash; }
  }
}
function nowSkeleton(on) {
  if (on) {
    fieldsState(NOW_FIELDS, "sk");
    fill($("#now-fuels"), Array.from({ length: 5 }, fuelSkRow));
    fill($("#now-caveats"), [skLine("70%"), skLine("55%")]);
  } else { fieldsState(NOW_FIELDS, "reset"); fill($("#now-fuels")); fill($("#now-caveats")); }
}
function cleanSkeleton(on) {
  if (on) {
    fieldsState(CLEAN_FIELDS, "sk");
    $("#clean-msg").textContent = "";
    fill($("#clean-ranked"), Array.from({ length: 6 }, rankSkRow));
  } else { fieldsState(CLEAN_FIELDS, "reset"); fill($("#clean-ranked")); }
}
function compareSkeleton(on) {
  fill($("#cmp-bars"), on ? Array.from({ length: state.compare.length || 5 }, cmpSkRow) : []);
}
const chartBox = () => document.querySelector(".chart-box");
function chartSkeleton(on) {
  const box = chartBox();
  const existing = box.querySelector(".chart-sk");
  if (on && !existing) box.append(h("div", { class: "sk chart-sk" }));
  else if (!on && existing) existing.remove();
}

// ── carbon → color scale (the visual signature) ──────────────────────────
function carbonColor(g) {
  if (g == null) return "#7c8aa5";
  if (g < 80) return "#2fe08f";
  if (g < 160) return "#7fe06a";
  if (g < 260) return "#e8d44a";
  if (g < 380) return "#f5a142";
  return "#f2545b";
}
function carbonLabel(g) {
  if (g < 80) return "very clean";
  if (g < 160) return "clean";
  if (g < 260) return "moderate";
  if (g < 380) return "dirty";
  return "very dirty";
}
const FUEL_COLOR = {
  COL: "#f2545b", NG: "#f5a142", OIL: "#d98c5f", NUC: "#8b9cf5",
  WAT: "#35c9e0", WND: "#5fe0b0", SUN: "#e8d44a", GEO: "#9be05f", OTH: "#7c8aa5",
};

const fmtHour = (iso) =>
  new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const pct = (x) => `${Math.round(x * 100)}%`;

// ── fetch helper ──────────────────────────────────────────────────────────
let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 4000);
}

async function api(path, opts = {}) {
  try {
    const res = await fetch(path, opts);
    if (res.status === 304) return null;
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof body.detail === "string" ? body.detail : body.detail?.message || res.statusText;
      throw new Error(detail || `HTTP ${res.status}`);
    }
    $("#live-dot").classList.add("on");
    $("#status").textContent = "live";
    return body;
  } catch (err) {
    toast(err.message || "request failed");
    return null;
  }
}

// ── state ───────────────────────────────────────────────────────────────
const state = { region: "CISO", zip: null, compare: ["CISO", "ERCO", "PJM", "MISO", "ISNE"] };
let regions = [];
let chart;

// ── NOW panel ─────────────────────────────────────────────────────────────
function renderNow(d) {
  fieldsState(NOW_FIELDS, "clear"); // drop skeleton; real values fill in below
  const g = d.gco2_per_kwh;
  const color = carbonColor(g);
  $("#now-region").textContent = d.region_name;
  $("#now-sub").textContent = `${d.region_code}${d.zip ? " · " + d.zip : ""} · ${fmtHour(d.period)}`;
  const val = $("#now-value");
  val.textContent = Math.round(g);
  val.style.color = color;
  const badge = $("#now-badge");
  badge.textContent = carbonLabel(g);
  badge.style.background = color;
  $("#now-renew").textContent = pct(d.renewable_share);
  $("#now-cfree").textContent = pct(d.carbon_free_share);

  fill($("#now-fuels"), d.fuel_mix.map((f) =>
    h("li", { class: "fuel-row" },
      h("span", { class: "text-mute" }, f.fuel_name),
      h("span", { class: "fuel-track" },
        h("span", { class: "fuel-fill", style: `width:${(f.share * 100).toFixed(1)}%;background:${FUEL_COLOR[f.fuel_code] || "#7c8aa5"}` })),
      h("span", { class: "text-right tabular-nums" }, pct(f.share)))));

  fill($("#now-caveats"), d.caveats.map((c) => h("li", {}, `› ${c}`)));
}

// ── forecast chart (history + forecast band) ───────────────────────────────
async function loadChart(region) {
  chartSkeleton(true);
  const [hist, fc] = await Promise.all([
    api(`/v1/carbon/history?region=${region}&limit=48`),
    api(`/v1/carbon/forecast?region=${region}&horizon=24`),
  ]);
  if (!hist || !fc) { chartSkeleton(false); return; }

  const hData = [...hist.data].reverse(); // ascending
  const labels = [...hData.map((p) => fmtHour(p.period)), ...fc.data.map((p) => fmtHour(p.period))];
  const nH = hData.length;
  const histVals = [...hData.map((p) => p.gco2_per_kwh), ...fc.data.map(() => null)];
  const mean = [...hData.map(() => null), ...fc.data.map((p) => p.mean_gco2_per_kwh)];
  const lower = [...hData.map(() => null), ...fc.data.map((p) => p.lower_gco2_per_kwh)];
  const upper = [...hData.map(() => null), ...fc.data.map((p) => p.upper_gco2_per_kwh)];
  if (nH) mean[nH - 1] = hData[nH - 1].gco2_per_kwh; // connect history → forecast

  const cfg = {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "history", data: histVals, borderColor: "#e6ebf4", borderWidth: 2, pointRadius: 0, tension: 0.3 },
        { label: "lower", data: lower, borderColor: "transparent", pointRadius: 0 },
        { label: "interval", data: upper, borderColor: "transparent", pointRadius: 0, backgroundColor: "rgba(53,224,216,0.13)", fill: "-1" },
        { label: "forecast", data: mean, borderColor: "#35e0d8", borderWidth: 2, borderDash: [5, 4], pointRadius: 0, tension: 0.3 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: { duration: 500 },
      interaction: { mode: "index", intersect: false },
      scales: {
        x: { grid: { color: "#1a2030" }, ticks: { color: "#7c8aa5", maxTicksLimit: 8, font: { family: "IBM Plex Mono", size: 10 } } },
        y: { grid: { color: "#1a2030" }, ticks: { color: "#7c8aa5", font: { family: "IBM Plex Mono", size: 10 } }, title: { display: true, text: "gCO₂/kWh", color: "#7c8aa5", font: { family: "IBM Plex Mono", size: 10 } } },
      },
      plugins: {
        legend: { labels: { color: "#7c8aa5", filter: (i) => ["history", "forecast"].includes(i.text), font: { family: "IBM Plex Mono", size: 11 } } },
        tooltip: { backgroundColor: "#161c2a", borderColor: "#232c3d", borderWidth: 1, titleColor: "#e6ebf4", bodyColor: "#e6ebf4", titleFont: { family: "IBM Plex Mono" }, bodyFont: { family: "IBM Plex Mono" } },
      },
    },
  };
  chartSkeleton(false);
  if (chart) chart.destroy();
  chart = new Chart($("#chart"), cfg);
  const bt = fc.backtest;
  $("#chart-meta").textContent =
    `model ${fc.model} · ${fc.history_hours}h history · backtest MAE ${bt.mae_gco2_per_kwh} gCO₂/kWh (${bt.holdout_hours}h holdout)`;
}

// ── cleanest hour ───────────────────────────────────────────────────────
async function loadCleanest(region) {
  cleanSkeleton(true);
  const d = await api(`/v1/carbon/cleanest-hour?region=${region}&horizon=24`);
  if (!d) { cleanSkeleton(false); return; }
  fieldsState(CLEAN_FIELDS, "clear");
  $("#clean-when").textContent = d.cleanest.period_local;
  const cv = $("#clean-value");
  cv.textContent = Math.round(d.cleanest.gco2_per_kwh);
  cv.style.color = carbonColor(d.cleanest.gco2_per_kwh);
  $("#clean-msg").textContent =
    `Running a load then instead of the dirtiest hour (${Math.round(d.dirtiest.gco2_per_kwh)} gCO₂/kWh) cuts emissions by ~${d.potential_savings_pct}%.`;
  fill($("#clean-ranked"), d.ranked.slice(0, 6).map((hr) => {
    const c = carbonColor(hr.gco2_per_kwh);
    return h("li", { class: "flex items-center gap-2 font-mono text-xs" },
      h("span", { class: "inline-block w-2 h-2 rounded-full", style: `background:${c}` }),
      h("span", { class: "text-mute w-28" }, hr.period_local.split(" ").slice(0, 3).join(" ")),
      h("span", { class: "tabular-nums", style: `color:${c}` }, Math.round(hr.gco2_per_kwh)));
  }));
}

// ── compare ───────────────────────────────────────────────────────────────
function renderCompareChips() {
  fill($("#cmp-chips"), regions.map((r) =>
    h("button", {
      class: `chip ${state.compare.includes(r.code) ? "active" : ""}`,
      onclick: () => {
        const i = state.compare.indexOf(r.code);
        if (i >= 0) state.compare.splice(i, 1); else state.compare.push(r.code);
        renderCompareChips();
        loadCompare();
      },
    }, r.code)));
}
async function loadCompare() {
  if (!state.compare.length) { fill($("#cmp-bars")); return; }
  compareSkeleton(true);
  const d = await api(`/v1/carbon/compare?regions=${state.compare.join(",")}`);
  if (!d) { compareSkeleton(false); return; }
  const max = Math.max(...d.items.map((i) => i.gco2_per_kwh), 1);
  fill($("#cmp-bars"), d.items.map((it) => {
    const c = carbonColor(it.gco2_per_kwh);
    return h("li", { class: "cmp-row" },
      h("span", { class: "font-mono text-xs text-mute" }, `#${it.rank} ${it.region_code}`),
      h("span", { class: "cmp-track" },
        h("span", { class: "cmp-fill", style: `width:${(it.gco2_per_kwh / max) * 100}%;background:${c}` })),
      h("span", { class: "font-mono text-sm tabular-nums", style: `color:${c}` }, Math.round(it.gco2_per_kwh)));
  }));
}

// ── AI: ask ───────────────────────────────────────────────────────────────
const EXAMPLES = [
  "Which 3 regions are cleanest right now?",
  "Average carbon intensity for CISO over the last 7 days?",
  "How much wind did ERCOT produce in the last 24 hours?",
  "Which region was dirtiest in the last 3 days?",
];
function renderExamples() {
  fill($("#ask-examples"), EXAMPLES.map((q) =>
    h("button", { class: "ex-chip", type: "button", onclick: () => { $("#ask-input").value = q; runAsk(); } }, q)));
}
async function runAsk() {
  const q = $("#ask-input").value.trim();
  if (!q) return;
  const btn = $("#ask-btn");
  btn.disabled = true; btn.textContent = "…";
  const d = await api("/v1/ai/ask", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ question: q }),
  });
  btn.disabled = false; btn.textContent = "Run";
  if (!d) return;

  $("#ask-out").classList.remove("hidden");
  $("#ask-sql").textContent = d.sql;
  $("#ask-conf").textContent = `${d.confidence} confidence${d.repaired ? " · repaired" : ""}`;

  const tbl = $("#ask-table");
  if (!d.rows.length) {
    fill(tbl, h("tr", {}, h("td", { class: "text-mute" }, "no rows")));
  } else {
    const cols = Object.keys(d.rows[0]);
    fill(tbl,
      h("thead", {}, h("tr", {}, cols.map((c) => h("th", {}, c)))),
      h("tbody", {}, d.rows.slice(0, 50).map((r) =>
        h("tr", {}, cols.map((c) => h("td", {}, fmtCell(r[c])))))));
  }
  $("#ask-note").textContent = `${d.row_count} row(s) · ${d.caveats[0]}`;
}
function fmtCell(v) {
  if (v == null) return "—";
  if (typeof v === "string" && /^-?\d/.test(v) && !isNaN(Number(v))) {
    const n = Number(v);
    return Number.isInteger(n) ? String(n) : n.toFixed(2);
  }
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(2);
  if (typeof v === "string" && v.includes("T") && !isNaN(Date.parse(v))) return fmtHour(v);
  return v;
}

// ── AI: insights ───────────────────────────────────────────────────────────
const STAT_LABELS = {
  mean_gco2_per_kwh: "mean gCO₂/kWh", min_gco2_per_kwh: "min", max_gco2_per_kwh: "max",
  trend_delta: "trend Δ", mean_renewable_share: "avg renewable", renewable_intensity_correlation: "renew↔CO₂ corr",
};
async function runInsights() {
  const region = $("#ins-region").value;
  const hours = $("#ins-window").value;
  const btn = $("#ins-btn");
  btn.disabled = true; btn.textContent = "…";
  const d = await api(`/v1/ai/insights?region=${region}&hours=${hours}`);
  btn.disabled = false; btn.textContent = "Summarize";
  if (!d) return;
  $("#ins-out").classList.remove("hidden");
  $("#ins-text").textContent = d.narrative;
  const s = d.stats;
  fill($("#ins-stats"), Object.keys(STAT_LABELS).filter((k) => k in s).map((k) => {
    const v = k === "mean_renewable_share" ? pct(s[k]) : s[k];
    return h("div", { class: "stat-tile" },
      h("div", { class: "k" }, STAT_LABELS[k]),
      h("div", { class: "v" }, v));
  }));
}

// ── init / wiring ───────────────────────────────────────────────────────
async function refreshLocation() {
  // Skeleton all three dependent panels at once, before any request resolves.
  nowSkeleton(true);
  chartSkeleton(true);
  cleanSkeleton(true);
  const q = state.zip ? `zip=${state.zip}` : `region=${state.region}`;
  const now = await api(`/v1/carbon/now?${q}`);
  if (!now) { nowSkeleton(false); chartSkeleton(false); cleanSkeleton(false); return; }
  state.region = now.region_code;
  $("#region-select").value = state.region;
  renderNow(now);
  loadChart(state.region);
  loadCleanest(state.region);
}

// Populate the region/insights selectors + compare chips once /regions lands.
// Kept off the critical path: the carbon panels don't wait on it.
async function loadRegions() {
  regions = (await api("/v1/regions")) || [];
  if (!regions.length) { $("#status").textContent = "API offline"; return; }
  const opts = regions.map((r) => h("option", { value: r.code }, `${r.code} — ${r.name}`));
  fill($("#region-select"), opts.map((o) => o.cloneNode(true)));
  fill($("#ins-region"), opts.map((o) => o.cloneNode(true)));
  $("#region-select").value = state.region;
  $("#ins-region").value = state.region;
  renderCompareChips();
}

function wireEvents() {
  $("#region-select").addEventListener("change", (e) => {
    state.region = e.target.value; state.zip = null; $("#zip").value = "";
    refreshLocation();
  });
  $("#loc-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const z = $("#zip").value.trim();
    if (/^\d{5}$/.test(z)) { state.zip = z; refreshLocation(); }
    else toast("enter a 5-digit ZIP");
  });
  $("#ask-form").addEventListener("submit", (e) => { e.preventDefault(); runAsk(); });
  $("#ins-btn").addEventListener("click", runInsights);
}

function init() {
  // Listeners + static UI first — interactive immediately, no data needed.
  wireEvents();
  renderExamples();
  // Fire the data-critical requests in parallel right away (no /regions gate).
  refreshLocation();
  loadCompare();
  // Selectors/chips fill in alongside, off the critical path.
  loadRegions();
}

init();
