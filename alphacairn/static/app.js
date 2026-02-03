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
let inputRevision = 0;
let fileRevision = 0;
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
  $("hash").textContent = "Dataset SHA-256 " + result.data_sha256;
  $("tradecount").textContent = s.trade_count + " fills";
  $("assumptions").textContent =
    s.assumptions +
    " Annualization uses " +
    result.parameters.periods_per_year +
    " daily bars per year. The bundled input is synthetic; imported files are user-supplied. Walk-forward selection does not reserve a final untouched holdout.";
  clear($("risk-rows"));
  const metrics = [
    ["Annualized compound return", "annualized_compound_return", true],
    ["Annualized volatility", "annualized_volatility", true],
    ["Sharpe ratio", "sharpe", false],
    ["Sortino ratio", "sortino", false],
    ["Historical 5% loss quantile", "historical_var_loss", true],
    [
      "Historical mean loss in the lower tail",
      "historical_expected_shortfall_loss",
      true,
    ],
  ];
  const format = (value, percent = false) =>
    value === null || value === undefined
      ? "—"
      : percent
        ? (value * 100).toFixed(2) + "%"
        : value.toFixed(2);
  for (const [label, key, percent] of metrics) {
    const row = element("tr");
    row.append(
      element("td", label),
      element("td", format(result.strategy_metrics[key], percent), "number"),
      element("td", format(result.baseline_metrics[key], percent), "number"),
    );
    $("risk-rows").append(row);
  }
  $("risk-frequency").textContent =
    result.parameters.periods_per_year + " bars per year";
  $("comparison").textContent = result.comparison
    ? "Baseline beta " +
      format(result.comparison.beta) +
      " / Annualized tracking error " +
      format(result.comparison.tracking_error, true)
    : "At least two observations are needed for a paired comparison";
  $("windows").hidden = !result.windows.length;
  $("window-count").textContent = result.windows.length + " sequential windows";
  clear($("window-rows"));
  for (const window of result.windows) {
    const row = element("tr");
    row.append(
      element("td", window.train_start + " to " + window.train_end),
      element("td", window.test_start + " to " + window.test_end),
      element("td", String(window.selected_lookback), "number"),
      element("td", format(window.test_metrics.total_return, true), "number"),
      element("td", money(window.fees), "number"),
    );
    $("window-rows").append(row);
  }
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
function resetStudy(message) {
  inputRevision += 1;
  result = null;
  clear($("chart"));
  clear($("rows"));
  clear($("risk-rows"));
  clear($("window-rows"));
  $("windows").hidden = true;
  for (const id of ["return", "drawdown", "fees"]) $(id).textContent = "—";
  $("period").textContent = message;
  $("tradecount").textContent = "Not calculated";
  $("risk-frequency").textContent = "Not calculated";
  $("comparison").textContent = "Run a study to compare paired returns";
  $("hash").textContent = "";
  $("assumptions").textContent =
    "Run the study to inspect the assumptions for the selected method";
}

$("run").onclick = async () => {
  error("");
  $("run").disabled = true;
  resetStudy("Calculating study");
  const revision = inputRevision;
  try {
    const calculated = await evaluate({
      csv,
      mode: $("mode").value,
      periods_per_year: Number($("frequency").value),
      train_size: Number($("train-size").value),
      test_size: Number($("test-size").value),
      candidates: $("candidates")
        .value.split(",")
        .map((value) => Number(value.trim())),
      score: $("score").value,
      lookback: Number($("lookback").value),
      fee_bps: Number($("fee").value),
      slippage_bps: Number($("slippage").value),
    });
    if (revision !== inputRevision) return;
    result = calculated;
    render();
  } catch (e) {
    if (revision !== inputRevision) return;
    error(e.message);
    resetStudy("No result for these inputs");
  } finally {
    $("run").disabled = false;
  }
};
$("file").onchange = async () => {
  const file = $("file").files[0];
  if (!file) return;
  const selectedFileRevision = ++fileRevision;
  resetStudy("Reading selected input");
  if (file.size > 900000) {
    error("Choose a CSV file smaller than 900 KB");
    $("file").value = "";
    return;
  }
  try {
    const content = await file.text();
    if (selectedFileRevision !== fileRevision) return;
    csv = content;
    $("source").textContent = "Imported file: " + file.name;
    resetStudy("New input loaded. Run the study to calculate results.");
  } catch (e) {
    if (selectedFileRevision !== fileRevision) return;
    error(e.message);
    resetStudy("Could not read the selected input");
  }
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
    loadPortfolioExample(data.portfolio);
    $("source").textContent = data.source;
    $("run").click();
  })
  .catch((e) => error(e.message));

window.addEventListener("resize", () => {
  if (result) chart();
});

$("mode").onchange = () => {
  const sequential = $("mode").value === "walk_forward";
  $("sequential-settings").hidden = !sequential;
  $("lookback").disabled = sequential;
  $("period").textContent =
    "Method changed. Run the study to calculate a result for the new method.";
};

for (const id of [
  "mode",
  "lookback",
  "fee",
  "slippage",
  "train-size",
  "test-size",
  "candidates",
  "score",
  "frequency",
]) {
  $(id).addEventListener("input", () =>
    resetStudy("Settings changed. Run the study to calculate results."),
  );
}

let portfolioExample = null;
let portfolioResult = null;
let portfolioRevision = 0;
function loadPortfolioExample(example) {
  portfolioExample = example;
  if (!portfolioRevision) {
    $("portfolio-events").value = JSON.stringify(example.events, null, 2);
    $("portfolio-quotes").value = JSON.stringify(example.quotes, null, 2);
    $("portfolio-statement").value = JSON.stringify(example.statement, null, 2);
  }
  $("portfolio-run").disabled = false;
}
function resetPortfolio(message) {
  portfolioRevision += 1;
  portfolioResult = null;
  $("portfolio-export").disabled = true;
  $("portfolio-status").textContent = message;
  $("portfolio-error").hidden = true;
  for (const id of ["portfolio-equity", "portfolio-count", "portfolio-match"])
    $(id).textContent = "—";
  for (const id of [
    "portfolio-cash",
    "portfolio-audit",
    "portfolio-issues",
    "portfolio-hash",
  ])
    $(id).textContent = "";
  clear($("portfolio-positions"));
  clear($("portfolio-settlement-cash"));
  clear($("portfolio-pending"));
  $("portfolio-settlement").hidden = true;
}
for (const id of [
  "portfolio-events",
  "portfolio-quotes",
  "portfolio-statement",
  "portfolio-missing",
  "portfolio-mismatch",
]) {
  $(id).addEventListener("input", () =>
    resetPortfolio("Inputs changed. Run ledger checks again."),
  );
}
$("portfolio-run").onclick = async () => {
  resetPortfolio("Checking journal");
  const revision = portfolioRevision;
  $("portfolio-error").hidden = true;
  $("portfolio-run").disabled = true;
  try {
    if (!portfolioExample)
      throw new Error("Wait for the account example to load");
    const calculated = await evaluate({
      mode: "portfolio",
      account: portfolioExample.account,
      statement: JSON.parse($("portfolio-statement").value),
      events: JSON.parse($("portfolio-events").value),
      quotes: JSON.parse($("portfolio-quotes").value),
      omit_crypto_mark: $("portfolio-missing").checked,
      inject_statement_mismatch: $("portfolio-mismatch").checked,
    });
    if (revision !== portfolioRevision) return;
    portfolioResult = calculated;
    const valuation = calculated.valuation;
    $("portfolio-equity").textContent = valuation.equity ?? "Incomplete";
    $("portfolio-count").textContent = String(calculated.state.last_sequence);
    $("portfolio-match").textContent = calculated.reconciliation.matched
      ? "Matched"
      : "Difference";
    $("portfolio-status").textContent = calculated.passed
      ? "All ledger checks passed"
      : "Review the unresolved inputs below";
    $("portfolio-audit").textContent = calculated.audit.passed
      ? "Journal balances and full event replay agree"
      : "Journal audit found differences";
    $("portfolio-cash").textContent =
      "Cash: " +
      Object.entries(calculated.state.cash)
        .map(([currency, amount]) => currency + " " + amount)
        .join("; ");
    const issues = [
      ...valuation.missing_inputs.map(
        (item) =>
          (item.instrument || item.currency) +
          ": " +
          item.reason +
          " " +
          item.kind,
      ),
      ...calculated.reconciliation.differences.map(
        (item) =>
          item.key +
          ": expected " +
          (typeof item.expected === "object"
            ? JSON.stringify(item.expected)
            : item.expected) +
          ", observed " +
          (typeof item.observed === "object"
            ? JSON.stringify(item.observed)
            : item.observed),
      ),
      ...calculated.audit.issues.map((item) => item.code),
    ];
    $("portfolio-issues").textContent = issues.join("; ");
    $("portfolio-hash").textContent =
      "Input SHA-256 " + calculated.input_sha256;
    for (const position of valuation.positions) {
      const row = element("tr");
      for (const [index, value] of [
        position.instrument,
        position.quote_currency,
        position.quantity,
        position.basis,
        position.market_value,
        position.unrealized_quote_pnl,
      ].entries()) {
        row.append(
          element("td", value ?? "Missing", index >= 2 ? "number" : ""),
        );
      }
      $("portfolio-positions").append(row);
    }
    if (calculated.state.settlement) {
      $("portfolio-settlement").hidden = false;
      for (const cash of calculated.state.settlement.cash) {
        const row = element("tr");
        for (const key of ["currency", "settled", "reserved", "available"])
          row.append(element("td", cash[key]));
        $("portfolio-settlement-cash").append(row);
      }
      for (const item of calculated.state.settlement.pending) {
        const row = element("tr");
        for (const key of [
          "trade_id",
          "instrument",
          "kind",
          "currency",
          "amount",
          "settles_at",
        ])
          row.append(element("td", item[key]));
        $("portfolio-pending").append(row);
      }
      if (!calculated.state.settlement.pending.length) {
        const row = element("tr");
        const cell = element("td", "No pending cash settlements");
        cell.colSpan = 6;
        row.append(cell);
        $("portfolio-pending").append(row);
      }
    }
    $("portfolio-export").disabled = false;
  } catch (exception) {
    if (revision !== portfolioRevision) return;
    $("portfolio-error").textContent = exception.message;
    $("portfolio-error").hidden = false;
    $("portfolio-status").textContent = "Journal could not be checked";
  } finally {
    $("portfolio-run").disabled = false;
  }
};
$("portfolio-export").onclick = () => {
  if (portfolioResult) download("alphacairn-portfolio.json", portfolioResult);
};
