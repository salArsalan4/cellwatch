// CellWatch dashboard; vanilla JS, no build step, no framework.
//
// The app is a "query" over the fleet: pick one or more cells (top-left) and a
// set of KPIs (top-right), and the centre stage fills with one small-multiple
// chart per KPI, each overlaying a colored line per selected cell. The left
// sidebar carries fleet status + a fleet-wide alerts feed; the data source
// (static snapshot vs live API) is demoted to the footer.
//
// Two data backends sit behind one interface (see buildStaticApi / buildLiveApi):
//   - static: reads the bundled JSON snapshot in ./evidence/ (works from any
//             static host, including after the AWS account is gone)
//   - live:   calls the deployed query API directly from the browser
//
// There is no virtual-DOM/state-diffing layer, on purpose: every render*()
// function takes plain state and rebuilds its slice of the DOM.

const LS_KEYS = { mode: "cellwatch.mode", baseUrl: "cellwatch.baseUrl", apiKey: "cellwatch.apiKey" };

// Soft cap on simultaneously-compared cells: categorical palettes reliably
// distinguish ~8 hues, so we stop there (see dataviz palette validation).
const MAX_CELLS = 8;

// The 8 validated light-mode categorical slots, read from CSS custom properties
// so color lives in one place (style.css :root).
const SERIES_COLORS = Array.from({ length: MAX_CELLS }, (_, i) =>
  getComputedStyle(document.documentElement).getPropertyValue(`--series-${i + 1}`).trim()
);

// KPI catalog. `domain` drives the hybrid y-axis:
//   pct   → pinned 0–100 (honest context for a bounded percentage)
//   auto0 → auto-fit but floored at 0 (unbounded-but-non-negative measures)
//   auto  → free auto-fit (can go negative, e.g. dBm/dB)
const KPI_FIELDS = [
  { key: "prb_utilization_dl",   label: "PRB Util DL",      unit: "%",    domain: "pct" },
  { key: "prb_utilization_ul",   label: "PRB Util UL",      unit: "%",    domain: "pct" },
  { key: "rrc_connected_users",  label: "RRC Users",        unit: "",     domain: "auto0" },
  { key: "dl_throughput_mbps",   label: "DL Throughput",    unit: "Mbps", domain: "auto0" },
  { key: "ul_throughput_mbps",   label: "UL Throughput",    unit: "Mbps", domain: "auto0" },
  { key: "rsrp_dbm",             label: "RSRP",             unit: "dBm",  domain: "auto" },
  { key: "rsrq_db",              label: "RSRQ",             unit: "dB",   domain: "auto" },
  { key: "sinr_db",              label: "SINR",             unit: "dB",   domain: "auto" },
  { key: "handover_success_rate",label: "Handover Success", unit: "%",    domain: "pct" },
  { key: "call_drop_rate",       label: "Call Drop Rate",   unit: "%",    domain: "auto0" },
  { key: "prach_attempts",       label: "PRACH Attempts",   unit: "",     domain: "auto0" },
];
const KPI_BY_KEY = new Map(KPI_FIELDS.map((f) => [f.key, f]));

// ---------------------------------------------------------------- API clients

function buildStaticApi() {
  let bundlePromise = null;
  async function bundle() {
    if (!bundlePromise) {
      bundlePromise = Promise.all(
        ["meta", "cells", "kpis", "alerts", "health"].map((name) =>
          fetch(`evidence/${name}.json`).then((r) => {
            if (!r.ok) throw new Error(`evidence/${name}.json: HTTP ${r.status}`);
            return r.json();
          })
        )
      ).then(([meta, cells, kpis, alerts, health]) => ({ meta, cells, kpis, alerts, health }));
    }
    return bundlePromise;
  }
  return {
    kind: "static",
    async meta() { return (await bundle()).meta; },
    async cells() { return (await bundle()).cells; },
    async health(cellId) { return (await bundle()).health[cellId] ?? null; },
    async kpis(cellId, limit = 60) { return ((await bundle()).kpis[cellId] ?? []).slice(0, limit); },
    async alerts(activeOnly) {
      const all = (await bundle()).alerts;
      return activeOnly ? all.filter((a) => a.cleared_at === null) : all;
    },
  };
}

function buildLiveApi(baseUrl, apiKey) {
  const base = baseUrl.replace(/\/+$/, "");
  async function get(path, params) {
    const url = new URL(base + path);
    for (const [k, v] of Object.entries(params ?? {})) url.searchParams.set(k, v);
    const res = await fetch(url, { headers: { "x-api-key": apiKey } });
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
    return res.json();
  }
  return {
    kind: "live",
    async ping() { return get("/health"); },
    async cells() { return get("/cells"); },
    async health(cellId) { return get(`/cells/${encodeURIComponent(cellId)}/health`); },
    async kpis(cellId, limit = 60) { return get(`/cells/${encodeURIComponent(cellId)}/kpis`, { limit }); },
    async alerts(activeOnly) { return get("/alerts", { active: activeOnly ? "true" : "false" }); },
  };
}

// ---------------------------------------------------------------- app state

const state = {
  api: buildStaticApi(),
  cells: [],                       // full fleet, from /cells
  healthByCell: new Map(),         // cellId -> health payload (or null)
  kpisByCell: new Map(),           // cellId -> KPI samples (newest-first), cached
  selectedCells: [],               // ordered cellIds currently plotted
  cellColor: new Map(),            // cellId -> hex, stable while selected
  colorInUse: new Array(MAX_CELLS).fill(null), // slot -> cellId (stable colors)
  enabledKpis: new Set(KPI_FIELDS.map((f) => f.key)), // all on by default
  cellMenuOpen: false,
};

const el = (id) => document.getElementById(id);

// ---------------------------------------------------------------- color slots

// Assign the lowest free palette slot so a cell keeps its color for as long as
// it stays selected; removing one cell never repaints the survivors (the
// dataviz rule: color follows the entity, not its rank).
function assignColor(cellId) {
  if (state.cellColor.has(cellId)) return state.cellColor.get(cellId);
  const slot = state.colorInUse.findIndex((v) => v === null);
  if (slot === -1) return null; // at cap
  state.colorInUse[slot] = cellId;
  const color = SERIES_COLORS[slot];
  state.cellColor.set(cellId, color);
  return color;
}
function releaseColor(cellId) {
  const slot = state.colorInUse.findIndex((v) => v === cellId);
  if (slot !== -1) state.colorInUse[slot] = null;
  state.cellColor.delete(cellId);
}

// ---------------------------------------------------------------- selection

async function ensureKpis(cellId) {
  if (state.kpisByCell.has(cellId)) return;
  try {
    state.kpisByCell.set(cellId, await state.api.kpis(cellId, 60));
  } catch {
    state.kpisByCell.set(cellId, []);
  }
}
async function ensureHealth(cellId) {
  if (state.healthByCell.has(cellId)) return;
  try {
    state.healthByCell.set(cellId, await state.api.health(cellId));
  } catch {
    state.healthByCell.set(cellId, null);
  }
}

async function selectCell(cellId, { focusKpi } = {}) {
  if (!state.selectedCells.includes(cellId)) {
    if (state.selectedCells.length >= MAX_CELLS) return; // soft cap
    assignColor(cellId);
    state.selectedCells.push(cellId);
    await Promise.all([ensureKpis(cellId), ensureHealth(cellId)]);
  }
  renderAll();
  if (focusKpi) flashKpi(focusKpi);
}

function deselectCell(cellId) {
  state.selectedCells = state.selectedCells.filter((c) => c !== cellId);
  releaseColor(cellId);
  renderAll();
}

// ---------------------------------------------------------------- formatting

function fmtValue(value, unit) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  const n = typeof value === "number" ? (Number.isInteger(value) ? value : value.toFixed(1)) : value;
  return unit ? `${n} ${unit}` : `${n}`;
}
function fmtNum(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  return Number.isInteger(value) ? String(value) : value.toFixed(1);
}

function statusInfo(health) {
  if (!health) return { text: "Unknown", cls: "status-unknown" };
  if (health.degraded) return { text: "RDS down", cls: "status-unknown" };
  if (health.status === "healthy") return { text: "Healthy", cls: "status-healthy" };
  const hasCritical = (health.active_alerts || []).some((a) => a.severity === "critical");
  const n = health.active_alert_count ?? (health.active_alerts || []).length;
  return hasCritical
    ? { text: `Critical · ${n}`, cls: "status-degraded-critical" }
    : { text: `Warning · ${n}`, cls: "status-degraded-warning" };
}

// ---------------------------------------------------------------- query bar: cells

function renderCellChips() {
  const wrap = el("cell-chips");
  wrap.innerHTML = "";
  for (const cellId of state.selectedCells) {
    const color = state.cellColor.get(cellId);
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.innerHTML = `
      <span class="chip-swatch" style="background:${color}"></span>
      <span>${cellId}</span>
      <button class="chip-x" type="button" aria-label="Remove ${cellId}">×</button>
    `;
    chip.querySelector(".chip-x").addEventListener("click", () => deselectCell(cellId));
    wrap.appendChild(chip);
  }
}

function renderCellMenu() {
  const list = el("cell-options");
  const query = el("cell-search").value.trim().toLowerCase();
  const atCap = state.selectedCells.length >= MAX_CELLS;
  el("cell-cap-note").hidden = !atCap;
  el("cell-cap-note").textContent = atCap ? `Comparing the max of ${MAX_CELLS} cells; remove one to add another.` : "";

  list.innerHTML = "";
  const matches = state.cells.filter((c) => {
    if (!query) return true;
    return c.id.toLowerCase().includes(query) || (c.site || "").toLowerCase().includes(query);
  });
  if (matches.length === 0) {
    list.innerHTML = `<li class="loading-row">No cells match “${query}”.</li>`;
    return;
  }
  for (const cell of matches) {
    const selected = state.selectedCells.includes(cell.id);
    const disabled = !selected && atCap;
    const status = statusInfo(state.healthByCell.get(cell.id));
    const li = document.createElement("li");
    li.className = `cell-option${selected ? " is-selected" : ""}${disabled ? " is-disabled" : ""}`;
    li.setAttribute("role", "option");
    li.setAttribute("aria-selected", String(selected));
    const dotColor =
      status.cls === "status-healthy" ? "var(--status-good)" :
      status.cls === "status-degraded-critical" ? "var(--status-critical)" :
      status.cls === "status-degraded-warning" ? "var(--status-warning)" : "var(--baseline)";
    li.innerHTML = `
      <span class="co-check">${selected ? "✓" : ""}</span>
      <span class="co-id">${cell.id}</span>
      <span class="co-status" style="background:${dotColor}" title="${status.text}"></span>
      <span class="co-site">${cell.site}</span>
    `;
    li.addEventListener("click", () => {
      if (selected) deselectCell(cell.id);
      else if (!disabled) selectCell(cell.id);
      renderCellMenu(); // keep the open menu in sync
    });
    list.appendChild(li);
  }
}

function toggleCellMenu(open) {
  state.cellMenuOpen = open;
  el("cell-menu").hidden = !open;
  el("cell-add-btn").setAttribute("aria-expanded", String(open));
  if (open) {
    renderCellMenu();
    el("cell-search").focus();
  }
}

// ---------------------------------------------------------------- query bar: KPIs

function renderKpiToggles() {
  const wrap = el("kpi-toggles");
  wrap.innerHTML = "";
  for (const field of KPI_FIELDS) {
    const on = state.enabledKpis.has(field.key);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = `kpi-toggle${on ? " is-on" : ""}`;
    btn.setAttribute("aria-pressed", String(on));
    btn.textContent = field.label;
    btn.addEventListener("click", () => {
      if (state.enabledKpis.has(field.key)) {
        if (state.enabledKpis.size > 1) state.enabledKpis.delete(field.key); // keep ≥1
      } else {
        state.enabledKpis.add(field.key);
      }
      renderKpiToggles();
      renderChartGrid();
    });
    wrap.appendChild(btn);
  }
}

// ---------------------------------------------------------------- sidebar: fleet

function renderFleet() {
  const rows = el("fleet-rows");
  rows.innerHTML = "";
  el("fleet-count").textContent = `${state.cells.length}`;

  for (const cell of state.cells) {
    const health = state.healthByCell.get(cell.id);
    const status = statusInfo(health);

    const selected = state.selectedCells.includes(cell.id);
    const color = selected ? state.cellColor.get(cell.id) : null;
    // Short one-word status keeps the narrow sidebar column tidy; the exact
    // alert count lives in the stat strip + alerts feed.
    const shortStatus =
      status.cls === "status-healthy" ? "Healthy" :
      status.cls === "status-degraded-critical" ? "Critical" :
      status.cls === "status-degraded-warning" ? "Warning" : status.text;
    const tr = document.createElement("tr");
    if (selected) tr.classList.add("is-selected");
    tr.innerHTML = `
      <td><span class="fleet-cell-id"><span class="row-swatch${color ? "" : " is-empty"}"
            style="${color ? `background:${color}` : ""}"></span>${cell.id}</span></td>
      <td>${cell.site}</td>
      <td>${cell.sector ?? "–"}</td>
      <td><span class="status-pill ${status.cls}" title="${status.text}">${shortStatus}</span></td>
    `;
    rows.appendChild(tr);
  }
}

// ---------------------------------------------------------------- sidebar: alerts

const SEV_RANK = { critical: 0, serious: 1, warning: 2 };

function renderAlertItem(alert) {
  const li = document.createElement("li");
  li.className = `alert-item severity-${alert.severity}${alert.cleared_at ? " cleared" : ""}`;
  const opened = new Date(alert.opened_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const kpi = KPI_BY_KEY.get(alert.kpi_name);
  const kpiLabel = kpi ? kpi.label : alert.kpi_name;
  const statusText = alert.cleared_at
    ? `cleared ${new Date(alert.cleared_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`
    : `opened ${opened}`;
  li.innerHTML = `
    <span class="alert-severity-badge severity-${alert.severity}">${alert.severity}</span>
    <div class="alert-item-body">
      <div class="alert-item-kpi"><span class="a-cell">${alert.cell_id}</span> · ${kpiLabel}</div>
      <div class="alert-item-meta">${fmtValue(alert.value, kpi?.unit || "")} · ${statusText}</div>
    </div>
  `;
  // Clicking an alert makes it a navigation control: select its cell (if room)
  // and jump to that KPI's chart.
  li.addEventListener("click", async () => {
    if (state.enabledKpis.size && !state.enabledKpis.has(alert.kpi_name)) {
      state.enabledKpis.add(alert.kpi_name);
      renderKpiToggles();
    }
    await selectCell(alert.cell_id, { focusKpi: alert.kpi_name });
  });
  return li;
}

async function renderAlertsFeed() {
  const list = el("alerts-feed");
  list.innerHTML = '<li class="loading-row">Loading…</li>';
  let alerts = await state.api.alerts(true); // active alerts only (demo view)
  list.innerHTML = "";
  el("alerts-count").textContent = alerts.length ? `${alerts.length} active` : "";
  if (alerts.length === 0) {
    list.innerHTML = '<li class="empty-alerts">No active alerts.</li>';
    return;
  }
  // Most severe, then most recent, first.
  alerts = alerts.slice().sort((a, b) => {
    const s = (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9);
    if (s !== 0) return s;
    return new Date(b.opened_at) - new Date(a.opened_at);
  });
  for (const alert of alerts) list.appendChild(renderAlertItem(alert));
}

// ---------------------------------------------------------------- stat strip

function renderStatStrip() {
  const strip = el("stat-strip");
  // Only meaningful for exactly one selected cell.
  if (state.selectedCells.length !== 1) {
    strip.hidden = true;
    strip.innerHTML = "";
    return;
  }
  const cellId = state.selectedCells[0];
  const cell = state.cells.find((c) => c.id === cellId);
  const health = state.healthByCell.get(cellId);
  const latest = health?.latest_kpi ?? null;
  const breached = new Set((health?.active_alerts || []).map((a) => a.kpi_name));

  strip.hidden = false;
  strip.innerHTML = `
    <div class="stat-strip-head">
      <span class="ss-title">${cellId}</span>
      <span class="ss-sub">${cell?.site ?? ""} · band ${cell?.band ?? "–"} · sector ${cell?.sector ?? "–"}</span>
    </div>
  `;
  for (const field of KPI_FIELDS) {
    const value = latest ? latest[field.key] : null;
    const isBreach = breached.has(field.key);
    const tile = document.createElement("div");
    tile.className = `stat-tile${isBreach ? " breach" : ""}`;
    const num = fmtNum(value);
    tile.innerHTML = `
      <span class="stat-tile-label">${field.label}</span>
      <span class="stat-tile-value${isBreach ? " breach" : ""}">${num}${field.unit && num !== "–" ? `<span class="unit">${field.unit}</span>` : ""}</span>
    `;
    strip.appendChild(tile);
  }
}

// ---------------------------------------------------------------- chart grid

function seriesForKpi(field) {
  const series = [];
  for (const cellId of state.selectedCells) {
    const samples = state.kpisByCell.get(cellId) || [];
    // API returns newest-first; charts read left(old) → right(new).
    const points = samples
      .slice()
      .reverse()
      .map((s) => ({ t: s.timestamp, v: s[field.key] }))
      .filter((p) => typeof p.v === "number" && !Number.isNaN(p.v));
    series.push({ cellId, color: state.cellColor.get(cellId), points });
  }
  return series;
}

function cellsBreaching(kpiKey) {
  const out = [];
  for (const cellId of state.selectedCells) {
    const health = state.healthByCell.get(cellId);
    if ((health?.active_alerts || []).some((a) => a.kpi_name === kpiKey)) out.push(cellId);
  }
  return out;
}

function renderChartGrid() {
  const grid = el("chart-grid");
  grid.innerHTML = "";

  if (state.selectedCells.length === 0) {
    el("grid-empty").hidden = false;
    return;
  }
  el("grid-empty").hidden = true;

  for (const field of KPI_FIELDS) {
    if (!state.enabledKpis.has(field.key)) continue;
    const series = seriesForKpi(field);
    const breaching = cellsBreaching(field.key);

    const card = document.createElement("div");
    card.className = `chart-card${breaching.length ? " is-breached" : ""}`;
    card.dataset.kpi = field.key;
    card.innerHTML = `
      <div class="chart-card-head">
        <span class="chart-card-title">${field.label}</span>
        <span class="chart-card-unit">${field.unit || ""}</span>
        ${breaching.length ? `<span class="chart-breach-badge" title="${breaching.join(", ")}">⚠ ${breaching.length}</span>` : ""}
      </div>
      <div class="chart-wrap">
        <svg class="chart-svg" viewBox="0 0 320 176" preserveAspectRatio="none"
             role="img" aria-label="${field.label} over time"></svg>
        <div class="chart-tooltip" hidden></div>
      </div>
    `;
    grid.appendChild(card);
    renderMultiChart(card.querySelector("svg"), card.querySelector(".chart-tooltip"), series, field);
  }
}

// Briefly ring a KPI card and scroll it into view (alert-click navigation).
function flashKpi(kpiKey) {
  requestAnimationFrame(() => {
    const card = document.querySelector(`.chart-card[data-kpi="${kpiKey}"]`);
    if (!card) return;
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.add("is-flash");
    setTimeout(() => card.classList.remove("is-flash"), 1400);
  });
}

// ---------------------------------------------------------------- chart engine

const CHART = { w: 320, h: 176, padL: 40, padR: 12, padT: 12, padB: 22 };

function niceTicks(min, max, count = 4) {
  if (min === max) { min -= 1; max += 1; }
  const rawStep = (max - min) / count;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const residual = rawStep / magnitude;
  const niceResidual = residual >= 5 ? 10 : residual >= 2 ? 5 : residual >= 1 ? 2 : 1;
  const step = niceResidual * magnitude;
  const niceMin = Math.floor(min / step) * step;
  const niceMax = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = niceMin; v <= niceMax + step / 2; v += step) ticks.push(Math.round(v * 1000) / 1000);
  return ticks;
}

// Resolve the y-domain per the hybrid rule (field.domain).
function yTicksFor(field, values) {
  if (field.domain === "pct") return [0, 25, 50, 75, 100];
  if (values.length === 0) return [0, 1];
  let lo = Math.min(...values);
  let hi = Math.max(...values);
  if (field.domain === "auto0") lo = Math.min(0, lo);
  return niceTicks(lo, hi);
}

function svgEl(tag, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function renderMultiChart(svg, tooltip, series, field) {
  svg.innerHTML = "";
  tooltip.hidden = true;

  const withData = series.filter((s) => s.points.length > 0);
  if (withData.length === 0) {
    const t = svgEl("text", { x: CHART.w / 2, y: CHART.h / 2, fill: "var(--text-muted)", "text-anchor": "middle", "font-size": 11 });
    t.textContent = "No data";
    svg.appendChild(t);
    return;
  }

  const { w, h, padL, padR, padT, padB } = CHART;
  const allValues = withData.flatMap((s) => s.points.map((p) => p.v));
  const ticks = yTicksFor(field, allValues);
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const tMin = Math.min(...withData.flatMap((s) => s.points.map((p) => p.t)));
  const tMax = Math.max(...withData.flatMap((s) => s.points.map((p) => p.t)));

  const x = (t) => padL + (tMax === tMin ? 0 : ((t - tMin) / (tMax - tMin)) * (w - padL - padR));
  const y = (v) => padT + (1 - (v - yMin) / (yMax - yMin || 1)) * (h - padT - padB);

  // gridlines + y labels
  for (const tick of ticks) {
    const ty = y(tick);
    svg.appendChild(svgEl("line", { x1: padL, x2: w - padR, y1: ty, y2: ty, stroke: "var(--gridline)", "stroke-width": 1 }));
    const label = svgEl("text", { x: padL - 6, y: ty + 3.5, fill: "var(--text-muted)", "text-anchor": "end", "font-size": 9 });
    label.textContent = tick;
    svg.appendChild(label);
  }

  // x labels (start/end only)
  const fmtTime = (t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const xStart = svgEl("text", { x: padL, y: h - 6, fill: "var(--text-muted)", "text-anchor": "start", "font-size": 9 });
  xStart.textContent = fmtTime(tMin);
  const xEnd = svgEl("text", { x: w - padR, y: h - 6, fill: "var(--text-muted)", "text-anchor": "end", "font-size": 9 });
  xEnd.textContent = fmtTime(tMax);
  svg.appendChild(xStart);
  svg.appendChild(xEnd);

  const single = withData.length === 1;

  // one line (+ wash only when single, to avoid muddy overlap) per series
  for (const s of withData) {
    const linePath = s.points.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t)},${y(p.v)}`).join(" ");
    if (single) {
      const last = s.points[s.points.length - 1];
      const areaPath = `${linePath} L${x(last.t)},${h - padB} L${x(s.points[0].t)},${h - padB} Z`;
      svg.appendChild(svgEl("path", { d: areaPath, fill: s.color, "fill-opacity": 0.10, stroke: "none" }));
    }
    svg.appendChild(svgEl("path", {
      d: linePath, fill: "none", stroke: s.color, "stroke-width": 2,
      "stroke-linejoin": "round", "stroke-linecap": "round",
    }));
    // end marker with a surface ring so overlapping ends stay legible
    const last = s.points[s.points.length - 1];
    svg.appendChild(svgEl("circle", { cx: x(last.t), cy: y(last.v), r: 3.2, fill: s.color, stroke: "var(--surface-1)", "stroke-width": 2 }));
  }

  // Direct end-label only when a single series (the color-chip row is the legend
  // for multi-series; stacked end-labels would collide).
  if (single) {
    const s = withData[0];
    const last = s.points[s.points.length - 1];
    const label = svgEl("text", {
      x: x(last.t) - 6, y: y(last.v) - 7,
      fill: "var(--text-primary)", "text-anchor": "end", "font-size": 10.5, "font-weight": 600,
    });
    label.textContent = fmtValue(last.v, field.unit);
    svg.appendChild(label);
  }

  // hover crosshair + shared tooltip listing every series at the nearest time
  const crosshair = svgEl("line", { x1: 0, x2: 0, y1: padT, y2: h - padB, stroke: "var(--baseline)", "stroke-width": 1, visibility: "hidden" });
  svg.appendChild(crosshair);
  const hoverDots = withData.map((s) => {
    const dot = svgEl("circle", { r: 3.4, fill: s.color, stroke: "var(--surface-1)", "stroke-width": 2, visibility: "hidden" });
    svg.appendChild(dot);
    return dot;
  });

  const hit = svgEl("rect", { x: padL, y: padT, width: w - padL - padR, height: h - padT - padB, fill: "transparent" });
  hit.addEventListener("mousemove", (evt) => {
    const rect = svg.getBoundingClientRect();
    const chartX = (evt.clientX - rect.left) * (w / rect.width);
    const frac = Math.min(1, Math.max(0, (chartX - padL) / (w - padL - padR)));
    const targetT = tMin + frac * (tMax - tMin);

    crosshair.setAttribute("visibility", "visible");
    const rows = [];
    let anchorPx = padL, anchorPy = padT;
    withData.forEach((s, i) => {
      let nearest = s.points[0], best = Infinity;
      for (const p of s.points) {
        const d = Math.abs(p.t - targetT);
        if (d < best) { best = d; nearest = p; }
      }
      const px = x(nearest.t), py = y(nearest.v);
      hoverDots[i].setAttribute("cx", px);
      hoverDots[i].setAttribute("cy", py);
      hoverDots[i].setAttribute("visibility", "visible");
      if (i === 0) { anchorPx = px; anchorPy = py; }
      rows.push({ color: s.color, name: s.cellId, val: fmtValue(nearest.v, field.unit), t: nearest.t });
    });
    crosshair.setAttribute("x1", anchorPx);
    crosshair.setAttribute("x2", anchorPx);

    const when = new Date(rows[0].t).toLocaleString();
    tooltip.innerHTML =
      `<div class="tt-time">${when}</div>` +
      rows.map((r) => `<div class="tt-row"><span class="tt-swatch" style="background:${r.color}"></span><span class="tt-name">${r.name}</span><span class="tt-val">${r.val}</span></div>`).join("");
    // position within the chart-wrap (tooltip is translated up-left in CSS)
    const wrapRect = svg.parentElement.getBoundingClientRect();
    tooltip.style.left = `${(anchorPx / w) * rect.width + (rect.left - wrapRect.left)}px`;
    tooltip.style.top = `${(anchorPy / h) * rect.height + (rect.top - wrapRect.top)}px`;
    tooltip.hidden = false;
  });
  hit.addEventListener("mouseleave", () => {
    crosshair.setAttribute("visibility", "hidden");
    hoverDots.forEach((d) => d.setAttribute("visibility", "hidden"));
    tooltip.hidden = true;
  });
  svg.appendChild(hit);
}

// ---------------------------------------------------------------- orchestration

function renderAll() {
  renderCellChips();
  renderFleet();
  renderStatStrip();
  renderChartGrid();
  if (state.cellMenuOpen) renderCellMenu();
}

// ---------------------------------------------------------------- data source (footer)

function setModeBadge(mode, detail) {
  const badge = el("mode-badge");
  badge.classList.remove("badge-muted", "badge-live", "badge-static", "badge-error");
  if (mode === "live") { badge.textContent = "Live API"; badge.classList.add("badge-live"); }
  else if (mode === "static") { badge.textContent = "Static evidence"; badge.classList.add("badge-static"); }
  else { badge.textContent = detail || "Unavailable"; badge.classList.add("badge-error"); }
}

async function loadEverything() {
  el("fleet-rows").innerHTML = '<tr><td colspan="4" class="loading-row">Loading fleet…</td></tr>';
  state.cells = await state.api.cells();
  state.healthByCell.clear();
  state.kpisByCell.clear();

  // Fetch health for the whole fleet up front so the table + alert counts are
  // populated immediately, and we can pick the most-alerting cell as default.
  await Promise.all(
    state.cells.map(async (cell) => {
      try { state.healthByCell.set(cell.id, await state.api.health(cell.id)); }
      catch { state.healthByCell.set(cell.id, null); }
    })
  );

  // Keep prior selection valid across a source switch; otherwise default to the
  // most-alerting cell so the demo opens on real anomalies.
  state.selectedCells = state.selectedCells.filter((id) => state.cells.some((c) => c.id === id));
  if (state.selectedCells.length === 0 && state.cells.length > 0) {
    const worst = state.cells
      .map((c) => ({ id: c.id, n: state.healthByCell.get(c.id)?.active_alert_count ?? 0 }))
      .sort((a, b) => b.n - a.n)[0];
    state.colorInUse.fill(null);
    state.cellColor.clear();
    assignColor(worst.id);
    state.selectedCells = [worst.id];
  }
  await Promise.all(state.selectedCells.map(ensureKpis));

  renderAll();
  await renderAlertsFeed();
}

async function activateStaticMode() {
  state.api = buildStaticApi();
  setModeBadge("static");
  el("mode-static").checked = true;
  const meta = await state.api.meta();
  const note = el("evidence-note");
  const captured = new Date(meta.captured_at).toLocaleString();
  note.textContent = meta.synthetic
    ? `Sample data (not a real capture); generated ${captured}`
    : `Captured from live deployment; ${captured}`;
  note.hidden = false;
  await loadEverything();
}

async function activateLiveMode(baseUrl, apiKey, { save } = { save: true }) {
  const api = buildLiveApi(baseUrl, apiKey);
  await api.ping(); // throws if unreachable; caller decides how to handle
  state.api = api;
  setModeBadge("live");
  el("mode-live").checked = true;
  el("evidence-note").hidden = true;
  if (save) {
    localStorage.setItem(LS_KEYS.mode, "live");
    localStorage.setItem(LS_KEYS.baseUrl, baseUrl);
    localStorage.setItem(LS_KEYS.apiKey, apiKey);
  }
  await loadEverything();
}

// ---------------------------------------------------------------- wiring

function wireCellSelect() {
  el("cell-add-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    toggleCellMenu(el("cell-menu").hidden);
  });
  el("cell-search").addEventListener("input", renderCellMenu);
  el("cell-menu").addEventListener("click", (e) => e.stopPropagation());
  // Click-away closes the menu.
  document.addEventListener("click", () => { if (state.cellMenuOpen) toggleCellMenu(false); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && state.cellMenuOpen) toggleCellMenu(false); });
}

function wireSource() {
  el("mode-static").addEventListener("change", () => {
    localStorage.setItem(LS_KEYS.mode, "static");
    activateStaticMode();
  });
  el("mode-live").addEventListener("change", () => el("base-url").focus());
  el("test-connection").addEventListener("click", async () => {
    const baseUrl = el("base-url").value.trim();
    const apiKey = el("api-key").value.trim();
    const result = el("connection-result");
    if (!baseUrl || !apiKey) {
      result.textContent = "Base URL and API key are both required.";
      result.className = "connection-result fail";
      return;
    }
    result.textContent = "Testing…";
    result.className = "connection-result";
    try {
      await activateLiveMode(baseUrl, apiKey);
      result.textContent = "Connected.";
      result.className = "connection-result ok";
    } catch (err) {
      result.textContent = `Could not reach the API (${err.message}). Falling back to static evidence.`;
      result.className = "connection-result fail";
      el("mode-static").checked = true;
      await activateStaticMode();
    }
  });
}

async function init() {
  renderKpiToggles();
  wireCellSelect();
  wireSource();

  const savedMode = localStorage.getItem(LS_KEYS.mode);
  const savedBaseUrl = localStorage.getItem(LS_KEYS.baseUrl);
  const savedApiKey = localStorage.getItem(LS_KEYS.apiKey);
  el("base-url").value = savedBaseUrl ?? "";
  el("api-key").value = savedApiKey ?? "";

  if (savedMode === "live" && savedBaseUrl && savedApiKey) {
    try {
      await activateLiveMode(savedBaseUrl, savedApiKey, { save: false });
      return;
    } catch {
      // Lab account is probably gone; expected long-term; fall through.
    }
  }
  await activateStaticMode();
}

init();
