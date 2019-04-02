const $ = (id) => document.getElementById(id);
const clear = (node) => node.replaceChildren();
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function error(message) {
  $("error").hidden = !message;
  $("error").textContent = message || "";
}
async function evaluate(params) {
  const response = await fetch("/api/evaluate", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Local-Request": "1" },
    body: JSON.stringify(params),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error);
  return result;
}
function download(name, value) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = element("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

let csv = "",
  result = null;
const money = (value) =>
  new Intl.NumberFormat("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
function chart() {
  const svg = $("chart");
  clear(svg);
  const width = Math.max(svg.clientWidth, 300),
    right = width - 20;
  svg.setAttribute("viewBox", "0 0 " + width + " 320");
  const series = [result.strategy.equity, result.baseline.equity];
  const values = series.flatMap((s) => s.map((p) => p.equity));
  let low = Math.min(...values),
    high = Math.max(...values);
  const pad = Math.max((high - low) * 0.1, 1);
  low -= pad;
  high += pad;
  const ns = "http://www.w3.org/2000/svg";
  function add(tag, attrs, text) {
    const node = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
    if (text !== undefined) node.textContent = text;
    svg.append(node);
  }
  const y = (value) => 272 - ((value - low) / (high - low)) * 248;
  for (let i = 0; i < 5; i++) {
    const value = low + ((high - low) * i) / 4;
    add("line", {
      x1: 64,
      y1: y(value),
      x2: right,
      y2: y(value),
      class: "gridline",
    });
    add(
      "text",
      { x: 52, y: y(value) + 4, "text-anchor": "end", class: "charttext" },
      Math.round(value).toLocaleString("en-US"),
    );
  }
  series.forEach((s, i) =>
    add("polyline", {
      points: s
        .map(
          (p, j) =>
            64 + (j / (s.length - 1)) * (right - 64) + "," + y(p.equity),
        )
        .join(" "),
      class: "chartline" + (i ? " baseline" : ""),
    }),
  );
  add("text", { x: 64, y: 304, class: "charttext" }, result.start);
  add(
    "text",
    { x: right, y: 304, "text-anchor": "end", class: "charttext" },
    result.end,
  );
}
function render() {
  chart();
  const s = result.strategy;
  $("return").textContent = (s.total_return * 100).toFixed(2) + "%";
  $("drawdown").textContent = (s.max_drawdown * 100).toFixed(2) + "%";
  $("fees").textContent = money(s.fees);
  $("period").textContent =
    result.start +
    " to " +
    result.end +
    " / " +
    result.bars +
    " observations / Starting capital 10,000";
  $("hash").textContent = "Input SHA-256 " + result.data_sha256;
  $("tradecount").textContent = s.trade_count + " fills";
  clear($("rows"));
  for (const t of s.trades) {
    const row = element("tr");
    row.append(
      element("td", t.date),
      element("td", t.side),
      element("td", t.quantity.toFixed(4), "number"),
      element("td", money(t.price), "number"),
      element("td", money(t.fee), "number"),
    );
    $("rows").append(row);
  }
  if (!s.trades.length) {
    const row = element("tr");
    const cell = element("td", "No trades for these settings");
    cell.colSpan = 5;
    row.append(cell);
    $("rows").append(row);
  }
}
$("run").onclick = async () => {
  error("");
  $("run").disabled = true;
  try {
    result = await evaluate({
      csv,
      lookback: Number($("lookback").value),
      fee_bps: Number($("fee").value),
      slippage_bps: Number($("slippage").value),
    });
    render();
  } catch (e) {
    error(e.message);
    result = null;
    clear($("chart"));
    clear($("rows"));
    for (const id of ["return", "drawdown", "fees"]) $(id).textContent = "—";
    $("period").textContent = "No result for these inputs";
    $("tradecount").textContent = "Not calculated";
    $("hash").textContent = "";
  } finally {
    $("run").disabled = false;
  }
};
$("file").onchange = async () => {
  const file = $("file").files[0];
  if (!file) return;
  if (file.size > 900000) {
    error("Choose a CSV file smaller than 900 KB");
    return;
  }
  csv = await file.text();
  $("source").textContent = "Imported file: " + file.name;
  result = null;
  clear($("chart"));
  clear($("rows"));
  $("period").textContent =
    "New input loaded. Run the study to calculate results.";
  for (const id of ["return", "drawdown", "fees"]) $(id).textContent = "—";
  $("hash").textContent = "";
  $("tradecount").textContent = "Not calculated";
};
$("export").onclick = () => {
  if (!result) {
    error("Run the study before exporting a result");
    return;
  }
  download("alphacairn-study.json", result);
};
fetch("/api/example")
  .then((r) => r.json())
  .then((data) => {
    csv = data.csv;
    $("source").textContent = data.source;
    $("run").click();
  })
  .catch((e) => error(e.message));

window.addEventListener("resize", () => {
  if (result) chart();
});
