// CellWatch static dashboard — vanilla JS, no build step, no framework.
//
// Two data backends behind one interface (see buildApiClient below):
//   - static:  reads the bundled JSON snapshot in ./evidence/ (works from
//              any static host, including after the AWS account is gone)
//   - live:    calls the deployed query API directly from the browser
//              (needs CORS on the API — see infra/modules/control-plane/
//              api_gateway.tf — and a base URL + API key from the user)
//
// Every render function takes plain data and touches the DOM; there is no
// virtual-DOM/state-diffing layer, on purpose, to keep this framework-free.

const LS_KEYS = { mode: "cellwatch.mode", baseUrl: "cellwatch.baseUrl", apiKey: "cellwatch.apiKey" };

const KPI_FIELDS = [
  { key: "prb_utilization_dl", label: "PRB Util DL", unit: "%" },
  { key: "prb_utilization_ul", label: "PRB Util UL", unit: "%" },
  { key: "rrc_connected_users", label: "RRC Users", unit: "" },
  { key: "dl_throughput_mbps", label: "DL Throughput", unit: "Mbps" },
  { key: "ul_throughput_mbps", label: "UL Throughput", unit: "Mbps" },
  { key: "rsrp_dbm", label: "RSRP", unit: "dBm" },
  { key: "rsrq_db", label: "RSRQ", unit: "dB" },
  { key: "sinr_db", label: "SINR", unit: "dB" },
  { key: "handover_success_rate", label: "Handover Success", unit: "%" },
  { key: "call_drop_rate", label: "Call Drop Rate", unit: "%" },
  { key: "prach_attempts", label: "PRACH Attempts", unit: "" },
];

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
    async meta() {
      return (await bundle()).meta;
    },
    async cells() {
      return (await bundle()).cells;
    },
    async health(cellId) {
      return (await bundle()).health[cellId] ?? null;
    },
    async kpis(cellId, limit = 60) {
      return ((await bundle()).kpis[cellId] ?? []).slice(0, limit);
    },
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
    async ping() {
      return get("/health");
    },
    async cells() {
      return get("/cells");
    },
    async health(cellId) {
      return get(`/cells/${encodeURIComponent(cellId)}/health`);
    },
    async kpis(cellId, limit = 60) {
      return get(`/cells/${encodeURIComponent(cellId)}/kpis`, { limit });
    },
    async alerts(activeOnly) {
      return get("/alerts", { active: activeOnly ? "true" : "false" });
    },
  };
}

// ---------------------------------------------------------------- app state

const state = {
  api: buildStaticApi(),
  cells: [],
  healthByCell: new Map(),
  selectedCellId: null,
  selectedKpi: "prb_utilization_dl",
  alertsFilter: "active",
};

const el = (id) => document.getElementById(id);

function setModeBadge(mode, detail) {
  const badge = el("mode-badge");
  badge.classList.remove("badge-muted", "badge-live", "badge-static", "badge-error");
  if (mode === "live") {
    badge.textContent = "Live API";
    badge.classList.add("badge-live");
  } else if (mode === "static") {
    badge.textContent = "Static evidence";
    badge.classList.add("badge-static");
  } else {
    badge.textContent = detail || "Unavailable";
    badge.classList.add("badge-error");
  }
}

async function activateStaticMode() {
  state.api = buildStaticApi();
  setModeBadge("static");
  el("mode-static").checked = true;
  const meta = await state.api.meta();
  const note = el("evidence-note");
  const captured = new Date(meta.captured_at).toLocaleString();
  note.textContent = meta.synthetic
    ? `Sample data (not a real capture) — generated ${captured}`
    : `Captured from live deployment — ${captured}`;
  note.hidden = false;
  await loadEverything();
}

async function activateLiveMode(baseUrl, apiKey, { save } = { save: true }) {
  const api = buildLiveApi(baseUrl, apiKey);
  await api.ping(); // throws if unreachable — caller decides how to handle
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

// ---------------------------------------------------------------- rendering

function statusInfo(health) {
  if (!health) return { text: "Unknown", cls: "status-unknown" };
  if (health.degraded) return { text: "Unknown (RDS down)", cls: "status-unknown" };
  if (health.status === "healthy") return { text: "Healthy", cls: "status-healthy" };
  const hasCritical = (health.active_alerts || []).some((a) => a.severity === "critical");
  return hasCritical
    ? { text: `Degraded (${health.active_alert_count})`, cls: "status-degraded-critical" }
    : { text: `Degraded (${health.active_alert_count})`, cls: "status-degraded-warning" };
}

function renderFleet() {
  const rows = el("fleet-rows");
  rows.innerHTML = "";
  el("fleet-count").textContent = `${state.cells.length} cells`;

  for (const cell of state.cells) {
    const health = state.healthByCell.get(cell.id);
    const status = statusInfo(health);
    const tr = document.createElement("tr");
    tr.dataset.cellId = cell.id;
    if (cell.id === state.selectedCellId) tr.classList.add("selected");
    tr.innerHTML = `
      <td class="fleet-cell-id">${cell.id}</td>
      <td>${cell.site}</td>
      <td>${cell.band ?? "—"} / ${cell.sector ?? "—"}</td>
      <td><span class="status-dot ${status.cls}">${status.text}</span></td>
    `;
    tr.addEventListener("click", () => selectCell(cell.id));
    rows.appendChild(tr);
  }
}

function fmtValue(value, unit) {
  if (value === null || value === undefined) return "—";
  const n = typeof value === "number" ? (Number.isInteger(value) ? value : value.toFixed(1)) : value;
  return unit ? `${n} ${unit}` : `${n}`;
}

function renderAlertItem(alert) {
  const li = document.createElement("li");
  li.className = `alert-item severity-${alert.severity}${alert.cleared_at ? " cleared" : ""}`;
  const opened = new Date(alert.opened_at).toLocaleString();
  const statusText = alert.cleared_at ? `cleared ${new Date(alert.cleared_at).toLocaleTimeString()}` : "active";
  li.innerHTML = `
    <span class="alert-severity-badge severity-${alert.severity}">${alert.severity}</span>
    <div class="alert-item-body">
      <div class="alert-item-kpi">${alert.cell_id} · ${alert.kpi_name}</div>
      <div class="alert-item-meta">${alert.alert_type} · value ${alert.value} · opened ${opened} · ${statusText}</div>
    </div>
  `;
  return li;
}

async function renderAlertsFeed() {
  const list = el("alerts-feed");
  list.innerHTML = '<li class="loading-row">Loading alerts…</li>';
  const alerts = await state.api.alerts(state.alertsFilter === "active");
  list.innerHTML = "";
  if (alerts.length === 0) {
    list.innerHTML = '<li class="empty-alerts">No alerts.</li>';
    return;
  }
  for (const alert of alerts) list.appendChild(renderAlertItem(alert));
}

function renderStatTiles(latestKpi) {
  const grid = el("stat-grid");
  grid.innerHTML = "";
  const health = state.healthByCell.get(state.selectedCellId);
  const breached = new Set((health?.active_alerts || []).map((a) => a.kpi_name));
  for (const field of KPI_FIELDS) {
    const tile = document.createElement("div");
    tile.className = "stat-tile";
    const value = latestKpi ? latestKpi[field.key] : null;
    tile.innerHTML = `
      <span class="stat-tile-label">${field.label}</span>
      <span class="stat-tile-value${breached.has(field.key) ? " breach" : ""}">${fmtValue(value, field.unit)}</span>
    `;
    grid.appendChild(tile);
  }
}

function populateKpiSelect() {
  const select = el("kpi-select");
  if (select.options.length) return;
  for (const field of KPI_FIELDS) {
    const opt = document.createElement("option");
    opt.value = field.key;
    opt.textContent = field.label;
    select.appendChild(opt);
  }
  select.value = state.selectedKpi;
  select.addEventListener("change", () => {
    state.selectedKpi = select.value;
    renderChartForSelectedCell();
  });
}

async function selectCell(cellId) {
  state.selectedCellId = cellId;
  renderFleet();
  el("detail-empty").hidden = true;
  el("detail-content").hidden = false;

  const cell = state.cells.find((c) => c.id === cellId);
  el("detail-title").textContent = cellId;
  el("detail-subtitle").textContent = `${cell?.site ?? ""} · band ${cell?.band ?? "—"} sector ${cell?.sector ?? "—"}`;

  const health = await state.api.health(cellId);
  state.healthByCell.set(cellId, health);
  renderFleet();
  renderStatTiles(health?.latest_kpi ?? null);

  const alertList = el("detail-alert-list");
  alertList.innerHTML = "";
  const active = health?.active_alerts ?? [];
  if (active.length === 0) {
    alertList.innerHTML = '<li class="empty-alerts">No active alerts for this cell.</li>';
  } else {
    for (const alert of active) alertList.appendChild(renderAlertItem(alert));
  }

  populateKpiSelect();
  await renderChartForSelectedCell();
}

async function renderChartForSelectedCell() {
  if (!state.selectedCellId) return;
  const samples = await state.api.kpis(state.selectedCellId, 60);
  const field = KPI_FIELDS.find((f) => f.key === state.selectedKpi);
  // API returns newest-first; the chart reads left(old) -> right(new).
  const points = samples
    .slice()
    .reverse()
    .map((s) => ({ t: s.timestamp, v: s[field.key] }));
  renderLineChart(el("kpi-chart"), points, field);
}

// ---------------------------------------------------------------- chart

const CHART = { w: 640, h: 220, padL: 46, padR: 14, padT: 16, padB: 26 };

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

function svgEl(tag, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function renderLineChart(svg, points, field) {
  svg.innerHTML = "";
  const tooltip = el("chart-tooltip");
  tooltip.hidden = true;

  if (points.length === 0) {
    svg.appendChild(
      svgEl("text", { x: CHART.w / 2, y: CHART.h / 2, fill: "var(--text-muted)", "text-anchor": "middle", "font-size": 12 })
    ).textContent = "No data";
    return;
  }

  const { w, h, padL, padR, padT, padB } = CHART;
  const values = points.map((p) => p.v);
  const ticks = niceTicks(Math.min(...values), Math.max(...values));
  const yMin = ticks[0];
  const yMax = ticks[ticks.length - 1];
  const tMin = points[0].t;
  const tMax = points[points.length - 1].t;

  const x = (t) => padL + (tMax === tMin ? 0 : ((t - tMin) / (tMax - tMin)) * (w - padL - padR));
  const y = (v) => padT + (1 - (v - yMin) / (yMax - yMin || 1)) * (h - padT - padB);

  // gridlines + y labels
  for (const tick of ticks) {
    const ty = y(tick);
    svg.appendChild(svgEl("line", { x1: padL, x2: w - padR, y1: ty, y2: ty, stroke: "var(--gridline)", "stroke-width": 1 }));
    const label = svgEl("text", { x: padL - 8, y: ty + 4, fill: "var(--text-muted)", "text-anchor": "end", "font-size": 10 });
    label.textContent = tick;
    svg.appendChild(label);
  }

  // x labels (start/end only)
  const fmtTime = (t) => new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const xStart = svgEl("text", { x: padL, y: h - 8, fill: "var(--text-muted)", "text-anchor": "start", "font-size": 10 });
  xStart.textContent = fmtTime(tMin);
  const xEnd = svgEl("text", { x: w - padR, y: h - 8, fill: "var(--text-muted)", "text-anchor": "end", "font-size": 10 });
  xEnd.textContent = fmtTime(tMax);
  svg.appendChild(xStart);
  svg.appendChild(xEnd);

  // area + line
  const linePath = points.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.t)},${y(p.v)}`).join(" ");
  const areaPath = `${linePath} L${x(points[points.length - 1].t)},${h - padB} L${x(points[0].t)},${h - padB} Z`;
  svg.appendChild(svgEl("path", { d: areaPath, fill: "var(--series-1-wash)", stroke: "none" }));
  svg.appendChild(svgEl("path", { d: linePath, fill: "none", stroke: "var(--series-1)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));

  // end marker + direct label (value at the end, per mark spec)
  const last = points[points.length - 1];
  svg.appendChild(svgEl("circle", { cx: x(last.t), cy: y(last.v), r: 4, fill: "var(--series-1)", stroke: "var(--surface-1)", "stroke-width": 2 }));
  const endLabel = svgEl("text", {
    x: x(last.t) - 10,
    y: y(last.v) - 8,
    fill: "var(--text-primary)",
    "text-anchor": "end",
    "font-size": 11,
    "font-weight": 600,
  });
  endLabel.textContent = `${fmtValue(last.v, field.unit)}`;
  svg.appendChild(endLabel);

  // hover crosshair + tooltip
  const crosshair = svgEl("line", { x1: 0, x2: 0, y1: padT, y2: h - padB, stroke: "var(--baseline)", "stroke-width": 1, visibility: "hidden" });
  const hoverDot = svgEl("circle", { r: 4, fill: "var(--series-1)", stroke: "var(--surface-1)", "stroke-width": 2, visibility: "hidden" });
  svg.appendChild(crosshair);
  svg.appendChild(hoverDot);

  const hitArea = svgEl("rect", { x: padL, y: padT, width: w - padL - padR, height: h - padT - padB, fill: "transparent" });
  hitArea.addEventListener("mousemove", (evt) => {
    const rect = svg.getBoundingClientRect();
    const scaleX = w / rect.width;
    const chartX = (evt.clientX - rect.left) * scaleX;
    const frac = Math.min(1, Math.max(0, (chartX - padL) / (w - padL - padR)));
    const targetT = tMin + frac * (tMax - tMin);
    let nearest = points[0];
    let best = Infinity;
    for (const p of points) {
      const d = Math.abs(p.t - targetT);
      if (d < best) { best = d; nearest = p; }
    }
    const px = x(nearest.t);
    const py = y(nearest.v);
    crosshair.setAttribute("x1", px);
    crosshair.setAttribute("x2", px);
    crosshair.setAttribute("visibility", "visible");
    hoverDot.setAttribute("cx", px);
    hoverDot.setAttribute("cy", py);
    hoverDot.setAttribute("visibility", "visible");

    const screenX = (px / w) * rect.width + rect.left;
    const screenY = (py / h) * rect.height + rect.top;
    const wrapRect = svg.parentElement.getBoundingClientRect();
    tooltip.style.left = `${screenX - wrapRect.left}px`;
    tooltip.style.top = `${screenY - wrapRect.top}px`;
    tooltip.innerHTML = `<div class="tt-value">${fmtValue(nearest.v, field.unit)}</div><div class="tt-time">${new Date(nearest.t).toLocaleString()}</div>`;
    tooltip.hidden = false;
  });
  hitArea.addEventListener("mouseleave", () => {
    crosshair.setAttribute("visibility", "hidden");
    hoverDot.setAttribute("visibility", "hidden");
    tooltip.hidden = true;
  });
  svg.appendChild(hitArea);
}

// ---------------------------------------------------------------- load / init

async function loadEverything() {
  el("fleet-rows").innerHTML = '<tr><td colspan="4" class="loading-row">Loading fleet…</td></tr>';
  state.cells = await state.api.cells();
  state.healthByCell.clear();

  // Fetch health for the whole fleet up front so the table can show status
  // immediately, not just on row click.
  await Promise.all(
    state.cells.map(async (cell) => {
      try {
        state.healthByCell.set(cell.id, await state.api.health(cell.id));
      } catch {
        state.healthByCell.set(cell.id, null);
      }
    })
  );
  renderFleet();
  await renderAlertsFeed();

  if (state.selectedCellId && state.cells.some((c) => c.id === state.selectedCellId)) {
    await selectCell(state.selectedCellId);
  } else if (state.cells.length > 0) {
    await selectCell(state.cells[0].id);
  }
}

function wireSettingsPanel() {
  const toggle = el("settings-toggle");
  const panel = el("settings-panel");
  toggle.addEventListener("click", () => {
    const open = panel.hidden;
    panel.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
  });

  el("mode-static").addEventListener("change", () => {
    localStorage.setItem(LS_KEYS.mode, "static");
    activateStaticMode();
  });

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

  el("mode-live").addEventListener("change", () => {
    // Selecting the radio alone doesn't test the connection — require the
    // explicit "Test & save" click so a bad URL/key doesn't silently drop
    // the dashboard into an error state.
    el("base-url").focus();
  });

  document.querySelectorAll('input[name="alerts-filter"]').forEach((input) => {
    input.addEventListener("change", async () => {
      state.alertsFilter = input.value;
      await renderAlertsFeed();
    });
  });
}

async function init() {
  wireSettingsPanel();

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
      // Lab account is probably gone — this is the expected long-term
      // outcome, not a bug. Fall through to static evidence below.
    }
  }
  await activateStaticMode();
}

init();
