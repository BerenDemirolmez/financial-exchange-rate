const chart = document.getElementById("chart");
const legend = document.getElementById("legend");
const viewSelect = document.getElementById("viewSelect");
const countrySelect = document.getElementById("countrySelect");
const metricSelect = document.getElementById("metric");
const sectorSelect = document.getElementById("sectorSelect");
const summaryTable = document.getElementById("summaryTable");
const chartTitle = document.getElementById("chartTitle");
const chartSubtitle = document.getElementById("chartSubtitle");
const downloadCsvButton = document.getElementById("downloadCsv");
const downloadPngButton = document.getElementById("downloadPng");
const dataPath = document.body?.dataset?.ferDataPath || "./data/fer_data.json";

const metricLabels = {
  asset_index: "Asset FER debt",
  liability_index: "Liability FER debt",
  net_index: "Net FER",
  asset_coverage: "Asset coverage",
  liability_coverage: "Liability coverage",
  net_coverage: "Net coverage",
};

const metricStyles = {
  asset_index: { shortLabel: "Asset", dash: "" },
  liability_index: { shortLabel: "Liability", dash: "8 6" },
  net_index: { shortLabel: "Net", dash: "2 6" },
  asset_coverage: { shortLabel: "Asset coverage", dash: "" },
  liability_coverage: { shortLabel: "Liability coverage", dash: "8 6" },
  net_coverage: { shortLabel: "Net coverage", dash: "2 6" },
};

const palette = ["#0b5cab", "#c04b00", "#0e8a5f", "#9c2f7f", "#996c00", "#0083a3", "#6b52c8", "#8d4f23"];
const colors = { grid: "#d8ccb9", axis: "#5f6d66" };

let currentView = null;
let debugStage = "startup";

function normalizeData(raw) {
  const legacyView = {
    other_debt: {
      aggregate: raw.aggregate || raw.series || {},
      sector: raw.sector || {},
    },
  };
  return {
    ...raw,
    views: raw.views || legacyView,
    aggregate: raw.aggregate || raw.series || {},
    sectors: raw.sectors || [],
    sector: raw.sector || {},
  };
}

function showMessage(title, subtitle) {
  chart.innerHTML = "";
  legend.innerHTML = "";
  chartTitle.textContent = title;
  chartSubtitle.textContent = subtitle;
  summaryTable.innerHTML = "";

  const ns = "http://www.w3.org/2000/svg";
  const text = document.createElementNS(ns, "text");
  text.setAttribute("x", "490");
  text.setAttribute("y", "210");
  text.setAttribute("text-anchor", "middle");
  text.setAttribute("fill", "#66756d");
  text.setAttribute("font-size", "22");
  text.textContent = title;
  chart.appendChild(text);

  const sub = document.createElementNS(ns, "text");
  sub.setAttribute("x", "490");
  sub.setAttribute("y", "242");
  sub.setAttribute("text-anchor", "middle");
  sub.setAttribute("fill", "#66756d");
  sub.setAttribute("font-size", "14");
  sub.textContent = subtitle;
  chart.appendChild(sub);
}

function makeOption(item) {
  const option = document.createElement("option");
  option.value = item.code;
  option.textContent = `${item.name} (${item.code})`;
  return option;
}

function linePath(points) {
  let path = "";
  let drawing = false;
  points.forEach((point) => {
    if (point.y == null) {
      drawing = false;
      return;
    }
    path += `${drawing ? "L" : "M"} ${point.x} ${point.y} `;
    drawing = true;
  });
  return path.trim();
}

function formatValue(metric, value) {
  if (value == null || !Number.isFinite(value)) {
    return "NA";
  }
  if (metric.includes("coverage")) {
    return `${Math.round(value * 100)}%`;
  }
  return value.toFixed(2);
}

function sanitizeValues(values) {
  return values.map((value) => (typeof value === "number" && Number.isFinite(value) ? value : null));
}

function getSelectedCountryCodes() {
  return Array.from(countrySelect.selectedOptions).map((option) => option.value);
}

function getSelectedMetrics() {
  return Array.from(metricSelect.selectedOptions).map((option) => option.value);
}

function getSeries(data, countryCode) {
  const selectedView = viewSelect?.value || "other_debt";
  const selectedSector = sectorSelect?.value || "aggregate";
  const view = data.views?.[selectedView] || data.views?.other_debt || { aggregate: {}, sector: {} };
  if (selectedSector !== "aggregate") {
    return view.sector?.[countryCode]?.[selectedSector];
  }
  return view.aggregate?.[countryCode];
}

function renderLegend(items, colorMap, dashMap = {}) {
  legend.innerHTML = "";
  items.forEach((entry) => {
    const item = document.createElement("span");
    item.className = "legend-item";
    const dash = dashMap[entry.key];
    const swatchStyle = dash
      ? `background:${colorMap[entry.key]}; background-image: repeating-linear-gradient(to right, transparent 0 6px, rgba(255,255,255,0.85) 6px 10px);`
      : `background:${colorMap[entry.key]}`;
    item.innerHTML = `<i class="swatch" style="${swatchStyle}"></i>${entry.label}`;
    legend.appendChild(item);
  });
}

function renderSummary(periods, rows) {
  summaryTable.innerHTML = "";
  const head = document.createElement("div");
  head.className = "summary-row summary-head";
  head.innerHTML = "<span>Series</span><span>Latest / Range</span>";
  summaryTable.appendChild(head);

  rows.forEach((row) => {
    const finiteValues = row.values.filter((value) => value != null && Number.isFinite(value));
    const latest = [...row.values].reverse().find((value) => value != null && Number.isFinite(value));
    const min = finiteValues.length ? Math.min(...finiteValues) : null;
    const max = finiteValues.length ? Math.max(...finiteValues) : null;
    const line = document.createElement("div");
    line.className = "summary-row";
    line.innerHTML = `<span>${row.label}</span><strong>${periods[periods.length - 1]}: ${formatValue(row.metric, latest)} | ${formatValue(row.metric, min)} to ${formatValue(row.metric, max)}</strong>`;
    summaryTable.appendChild(line);
  });
}

function drawChart(periods, rows, colorMap, dashMap = {}) {
  const width = 980;
  const height = 420;
  const margin = { top: 24, right: 24, bottom: 56, left: 64 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const coverageOnly = rows.every((row) => row.metric.includes("coverage"));
  const allValues = rows.flatMap((row) => row.values).filter((value) => value != null && Number.isFinite(value));
  if (!allValues.length) {
    showMessage("No finite values for this selection", "Try another country or sector");
    return;
  }
  const minValue = Math.min(...allValues);
  const maxValue = Math.max(...allValues);
  const padding = (maxValue - minValue || 1) * 0.12;
  const yMin = coverageOnly ? Math.max(0, minValue - padding) : minValue - padding;
  const yMax = coverageOnly ? Math.min(1, maxValue + padding) : maxValue + padding;
  const x = (index) => margin.left + (index / Math.max(1, periods.length - 1)) * plotWidth;
  const y = (value) => margin.top + ((yMax - value) / (yMax - yMin || 1)) * plotHeight;
  const yTicks = 5;
  const xTicks = Math.min(8, periods.length);
  const xStep = Math.max(1, Math.floor((periods.length - 1) / Math.max(1, xTicks - 1)));

  chart.innerHTML = "";
  const ns = "http://www.w3.org/2000/svg";
  const add = (name, attrs) => {
    const el = document.createElementNS(ns, name);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
    chart.appendChild(el);
    return el;
  };

  for (let i = 0; i < yTicks; i += 1) {
    const tickValue = yMin + ((yMax - yMin) * i) / (yTicks - 1);
    const yPos = y(tickValue);
    add("line", { x1: margin.left, y1: yPos, x2: width - margin.right, y2: yPos, stroke: colors.grid, "stroke-width": 1 });
    const text = add("text", { x: margin.left - 12, y: yPos + 4, "text-anchor": "end", fill: colors.axis, "font-size": 12 });
    text.textContent = coverageOnly ? `${Math.round(tickValue * 100)}%` : tickValue.toFixed(1);
  }

  add("line", { x1: margin.left, y1: margin.top, x2: margin.left, y2: height - margin.bottom, stroke: colors.axis, "stroke-width": 1.2 });
  add("line", { x1: margin.left, y1: height - margin.bottom, x2: width - margin.right, y2: height - margin.bottom, stroke: colors.axis, "stroke-width": 1.2 });

  for (let i = 0; i < periods.length; i += xStep) {
    const xPos = x(i);
    add("line", { x1: xPos, y1: height - margin.bottom, x2: xPos, y2: height - margin.bottom + 6, stroke: colors.axis, "stroke-width": 1 });
    const text = add("text", { x: xPos, y: height - margin.bottom + 20, "text-anchor": "middle", fill: colors.axis, "font-size": 12 });
    text.textContent = periods[i];
  }
  if ((periods.length - 1) % xStep !== 0) {
    const xPos = x(periods.length - 1);
    const text = add("text", { x: xPos, y: height - margin.bottom + 20, "text-anchor": "middle", fill: colors.axis, "font-size": 12 });
    text.textContent = periods[periods.length - 1];
  }

  if (!coverageOnly) {
    const yBase = y(100);
    add("line", { x1: margin.left, y1: yBase, x2: width - margin.right, y2: yBase, stroke: "#999999", "stroke-dasharray": "4 4", "stroke-width": 1.2 });
  }

  rows.forEach((row) => {
    const points = row.values.map((value, index) => ({ x: x(index), y: value == null ? null : y(value) }));
    const path = linePath(points);
    if (!path) {
      return;
    }
    add("path", {
      d: path,
      fill: "none",
      stroke: colorMap[row.key],
      "stroke-width": 2.6,
      "stroke-linecap": "round",
      "stroke-linejoin": "round",
      "stroke-dasharray": dashMap[row.key] || "",
    });
  });
}

function buildCsv(view) {
  const header = ["period", ...view.rows.map((row) => row.csvLabel)];
  const rows = [header];
  view.periods.forEach((period, index) => {
    rows.push([period, ...view.rows.map((row) => row.values[index] ?? "")]);
  });
  return rows.map((row) => row.join(",")).join("\n");
}

function downloadCsv(view) {
  const blob = new Blob([buildCsv(view)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${view.mode}_${view.metric}_${view.rows.map((row) => row.country.code).join("_")}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function downloadPng() {
  const serializer = new XMLSerializer();
  const svgText = serializer.serializeToString(chart);
  const svgBlob = new Blob([svgText], { type: "image/svg+xml;charset=utf-8" });
  const url = URL.createObjectURL(svgBlob);
  const image = new Image();
  image.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = 980;
    canvas.height = 420;
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#fffaf2";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(image, 0, 0);
    URL.revokeObjectURL(url);
    const pngUrl = canvas.toDataURL("image/png");
    const link = document.createElement("a");
    link.href = pngUrl;
    link.download = "fer_chart.png";
    link.click();
  };
  image.src = url;
}

function render(data) {
  const selectedCodes = getSelectedCountryCodes();
  const selectedMetrics = getSelectedMetrics();
  const selectedView = viewSelect?.value || "other_debt";
  const selectedSector = sectorSelect?.value || "aggregate";
  const scopeBase = selectedView === "debt_asset" ? "Debt asset" : "Other debt";
  const scopeLabel = selectedSector === "aggregate" ? `Aggregate ${scopeBase.toLowerCase()}` : `${scopeBase} • ${selectedSector}`;

  if (!selectedCodes.length) {
    showMessage("Select at least one country", scopeLabel);
    return;
  }

  if (!selectedMetrics.length) {
    showMessage("Select at least one metric", scopeLabel);
    return;
  }

  const selectedCountries = selectedCodes
    .map((code) => data.countries.find((country) => country.code === code))
    .filter(Boolean);
  const rows = [];
  selectedCountries.forEach((country) => {
    const series = getSeries(data, country.code);
    if (!series) {
      return;
    }
    selectedMetrics.forEach((metric) => {
      const style = metricStyles[metric] || { shortLabel: metricLabels[metric] || metric, dash: "" };
      rows.push({
        key: `${country.code}_${metric}`,
        country,
        metric,
        label: `${country.name} (${country.code}) - ${style.shortLabel}`,
        csvLabel: `${country.code}_${metric}`,
        dash: style.dash,
        values: sanitizeValues(series[metric]),
        period: series.period,
      });
    });
  });

  if (!rows.length) {
    showMessage("No data for this view", scopeLabel);
    return;
  }

  const periods = rows[0].period;
  const alignedRows = rows.map((row) => ({
    key: row.key,
    country: row.country,
    metric: row.metric,
    label: row.label,
    csvLabel: row.csvLabel,
    dash: row.dash,
    values: row.values,
  }));
  const colorMap = Object.fromEntries(
    alignedRows.map((row) => [row.key, palette[selectedCountries.findIndex((country) => country.code === row.country.code) % palette.length]])
  );
  const dashMap = Object.fromEntries(alignedRows.map((row) => [row.key, row.dash]));

  currentView = {
    mode: `${selectedView}_${selectedSector}`,
    metric: selectedMetrics.join("_"),
    periods,
    rows: alignedRows,
  };

  chartTitle.textContent = selectedCountries.map((country) => country.name).join(", ");
  chartSubtitle.textContent = `${selectedMetrics.map((metric) => metricLabels[metric]).join(" • ")} • ${scopeLabel}`;
  renderLegend(
    alignedRows.map((row) => ({ key: row.key, label: row.label })),
    colorMap,
    dashMap,
  );
  drawChart(periods, alignedRows, colorMap, dashMap);
  renderSummary(periods, alignedRows);
}

async function init() {
  debugStage = "loading message";
  showMessage("Loading data...", "Reading FER website data");
  debugStage = "fetch";
  const response = await fetch(dataPath, { cache: "no-store" });
  if (!response.ok) {
    showMessage("Could not load website data", `HTTP ${response.status}`);
    return;
  }
  debugStage = "parse json";
  const data = normalizeData(await response.json());
  debugStage = "validate data";
  if (!data.countries?.length || !Object.keys(data.aggregate || {}).length) {
    showMessage("Website data are empty", "Try rebuilding website/data/fer_data.json");
    return;
  }

  debugStage = "build country options";
  data.countries.forEach((country) => countrySelect.appendChild(makeOption(country)));

  debugStage = "set defaults";
  Array.from(countrySelect.options).forEach((option) => {
    option.selected = ["DE", "FR", "ES"].includes(option.value);
  });
  Array.from(metricSelect.options).forEach((option) => {
    option.selected = ["asset_index", "liability_index", "net_index"].includes(option.value);
  });

  debugStage = "bind events";
  const update = () => {
    debugStage = "update";
    render(data);
  };

  [viewSelect, countrySelect, metricSelect, sectorSelect].forEach((element) => {
    element.addEventListener("change", update);
  });
  downloadCsvButton.addEventListener("click", () => currentView && downloadCsv(currentView));
  downloadPngButton.addEventListener("click", downloadPng);
  debugStage = "initial render";
  update();
}

init().catch((error) => {
  console.error(error);
  const detail = `${String(error && error.message ? error.message : error)} | stage: ${debugStage}`;
  showMessage("Website error", detail);
});
