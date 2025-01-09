"use strict";

const byId = (id) => document.getElementById(id);
const state = {
  project: "local",
  study: null,
  trial: null,
  epoch: 0,
  viewEpoch: 0,
  data: null,
  controls: null,
  busy: false,
  pending: null,
};
const terminal = new Set(["succeeded", "incomplete", "failed", "interrupted"]);
const pendingKey = "alphacairn-research-pending";

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined && text !== null) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}
function amount(value, currency = "") {
  if (value === undefined || value === null) return "Unavailable";
  const text = String(value);
  const match = text.match(/^(-?)(\d+)(?:\.(\d+))?$/);
  if (!match) return text;
  const fraction = (match[3] || "").replace(/0+$/, "").padEnd(2, "0");
  return `${match[1]}${BigInt(match[2]).toLocaleString("en-US")}.${fraction}${currency ? ` ${currency}` : ""}`;
}
function error(message) {
  byId("desk-error").textContent = message || "";
  byId("desk-error").hidden = !message;
}
function status(message) {
  byId("desk-status").textContent = message;
}
function handler(fn) {
  return async (event) => {
    event?.preventDefault();
    error("");
    try {
      await fn(event);
    } catch (failure) {
      error(failure.message);
    }
  };
}
async function request(params) {
  const response = await fetch("/api/research", {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Local-Request": "1" },
    body: JSON.stringify(params),
  });
  let value;
  try {
    value = await response.json();
  } catch (_) {
    throw new Error(
      "Response could not be read. Recover the saved response before retrying.",
    );
  }
  if (!response.ok) {
    const failure = new Error(
      value.error || `Request failed (${response.status})`,
    );
    failure.rejected = true;
    throw failure;
  }
  return value;
}
function pendingDisplay(meta) {
  if (meta) sessionStorage.setItem(pendingKey, JSON.stringify(meta));
  else sessionStorage.removeItem(pendingKey);
  state.pending = meta;
  byId("pending-recovery").hidden = !meta;
}
function requireHoldout(partition) {
  if (partition === "holdout" && !byId("open-holdout").checked)
    throw new Error("Acknowledge holdout access before opening these data.");
}
function operator() {
  return {
    actor: byId("actor").value.trim(),
    reason: byId("reason").value.trim(),
  };
}
function busy(value) {
  state.busy = value;
  document.querySelectorAll("[data-mutation]").forEach((button) => {
    button.disabled = value;
  });
}
async function execute(action, fields = {}, holdout = false) {
  if (state.busy) throw new Error("Wait for the current operation to finish.");
  if (state.pending)
    throw new Error(
      "Recover the pending response before submitting another operation.",
    );
  if (holdout) requireHoldout("holdout");
  const epoch = state.epoch;
  const params = {
    action,
    project: state.project,
    request_key: crypto.randomUUID(),
    ...fields,
  };
  if (fields.trial) params.study = state.study;
  if (holdout) params.acknowledge_holdout = true;
  const meta = {
    project: state.project,
    study: state.study,
    trial: fields.trial || null,
    request_key: params.request_key,
    action,
    holdout,
    request: params,
  };
  pendingDisplay(meta);
  busy(true);
  status("Saving research operation");
  try {
    const value = await request(params);
    pendingDisplay(null);
    if (state.epoch !== epoch) {
      status(
        "Operation saved in the previous study. Open it to review the result.",
      );
      return null;
    }
    await refresh();
    status("Research operation saved");
    return value;
  } catch (failure) {
    if (failure.rejected) pendingDisplay(null);
    throw failure;
  } finally {
    busy(false);
  }
}
function download(value, filename) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2) + "\n"], {
      type: "application/json",
    }),
  );
  const link = element("a");
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function renderStudies(value) {
  const root = byId("studies");
  root.replaceChildren();
  if (!value.studies.length)
    root.append(element("p", "No saved studies in this project", "muted"));
  for (const study of value.studies) {
    const button = element("button");
    button.type = "button";
    button.setAttribute("aria-pressed", String(study.id === state.study));
    button.append(
      element("span", study.name),
      element(
        "small",
        `${study.family} / ${study.trial_count} attempts / ${study.unsuccessful_count} unsuccessful`,
      ),
    );
    button.addEventListener(
      "click",
      handler(() => selectStudy(study.id)),
    );
    root.append(button);
  }
}
function actionButton(text, callback) {
  const button = element("button", text);
  button.type = "button";
  button.dataset.mutation = "1";
  button.disabled = state.busy;
  button.addEventListener("click", handler(callback));
  return button;
}
function renderComparison(comparison) {
  const body = byId("attempts").querySelector("tbody");
  body.replaceChildren();
  const context = state.data.context;
  const unresolved = context.trials.some(
    (trial) =>
      trial.partition === "development" &&
      ["registered", "running"].includes(trial.status),
  );
  for (const item of comparison.comparisons) {
    const trial = item.record;
    const row = element("tr");
    row.dataset.trial = trial.id;
    row.append(
      element("td", trial.label),
      element("td", trial.partition),
      element("td", trial.status, `status-${trial.status}`),
    );
    const summary = item.summary;
    row.append(
      element(
        "td",
        item.withheld
          ? "Withheld"
          : summary
            ? amount(summary.equity, summary.base_currency)
            : "—",
        "number",
      ),
    );
    row.append(
      element(
        "td",
        item.withheld
          ? "Withheld"
          : summary?.worst_declared_stress_pnl !== undefined
            ? amount(summary.worst_declared_stress_pnl, summary.base_currency)
            : "—",
        "number",
      ),
    );
    const actions = element("td");
    const show = async (action) => {
      requireHoldout(trial.partition);
      state.trial = trial.id;
      const value = await execute(
        action,
        { trial: trial.id, ...operator() },
        trial.partition === "holdout",
      );
      if (value) renderResult(value);
    };
    if (trial.status === "registered")
      actions.append(
        actionButton(
          trial.partition === "holdout" ? "Run holdout" : "Run",
          () => show("run"),
        ),
      );
    if (terminal.has(trial.status))
      actions.append(
        actionButton(
          trial.partition === "holdout" ? "Open holdout" : "Inspect",
          () => show("inspect"),
        ),
      );
    if (
      trial.partition === "development" &&
      trial.status === "succeeded" &&
      !context.selection &&
      !unresolved
    )
      actions.append(
        actionButton("Lock selection", () =>
          execute("select", {
            study: state.study,
            trial: trial.id,
            ...operator(),
          }),
        ),
      );
    if (trial.status === "running" && trial.lease_until * 1000 <= Date.now())
      actions.append(
        actionButton("Recover interrupted", () =>
          execute("recover", {
            trial: trial.id,
            generation: trial.generation,
            ...operator(),
          }),
        ),
      );
    row.append(actions);
    body.append(row);
  }
  byId("empty-attempts").hidden = comparison.comparisons.length !== 0;
}
function renderEvents(items, append = false) {
  const root = byId("events");
  if (!append) root.replaceChildren();
  for (const event of items) {
    const item = element("li", event.kind.replaceAll("_", " "));
    item.append(
      element(
        "small",
        `${event.sequence} / ${new Date(event.created * 1000).toISOString()}${event.payload.actor ? ` / ${event.payload.actor}` : ""}`,
      ),
    );
    root.append(item);
  }
}
function renderView(value) {
  state.data = value;
  const context = value.context;
  byId("study-content").hidden = false;
  byId("study-title").textContent = context.definition.name;
  byId("hypothesis").textContent = context.definition.hypothesis;
  const windowText = (window) =>
    `${window.start.slice(0, 10)} to ${window.end.slice(0, 10)} (UTC)`;
  byId("development-window").textContent = windowText(
    context.definition.development,
  );
  byId("holdout-window").textContent = windowText(context.definition.holdout);
  byId("attempt-count").textContent =
    `${context.registered_trial_count} attempts / ${context.failed_trial_count} unsuccessful`;
  byId("selection-state").textContent = context.selection
    ? "Development selection locked"
    : "Development selection open";
  byId("holdout-state").textContent =
    `${context.holdout_access_attempts} recorded holdout accesses`;
  byId("audit-state").textContent = value.audit.passed
    ? "Complete registry audit passed"
    : "Registry audit requires review";
  renderComparison(value.comparison);
  renderEvents(value.events);
  byId("more-events").hidden = !value.has_more;
}
async function refresh() {
  const epoch = state.epoch;
  const viewEpoch = ++state.viewEpoch;
  const project = state.project;
  const study = state.study;
  const [listing, view] = await Promise.all([
    request({ action: "list", project }),
    study ? request({ action: "view", project, study }) : Promise.resolve(null),
  ]);
  if (epoch !== state.epoch || viewEpoch !== state.viewEpoch) return;
  renderStudies(listing);
  if (view) renderView(view);
}
async function selectStudy(study) {
  state.epoch++;
  state.study = study;
  state.trial = null;
  state.data = null;
  byId("open-holdout").checked = false;
  byId("trial-detail").hidden = true;
  byId("study-content").hidden = true;
  byId("study-title").textContent = "Loading study";
  sessionStorage.setItem(
    "alphacairn-research-scope",
    JSON.stringify({ project: state.project, study }),
  );
  await refresh();
}
async function openProject(preferred = null) {
  state.epoch++;
  state.project = byId("project").value.trim();
  state.study = null;
  state.trial = null;
  state.data = null;
  byId("study-content").hidden = true;
  byId("trial-detail").hidden = true;
  byId("study-title").textContent = "Saved experiments";
  byId("hypothesis").textContent =
    "Declare a study before registering risk or strategy attempts";
  byId("project-context").textContent = `Project ${state.project}`;
  const epoch = state.epoch;
  const listing = await request({ action: "list", project: state.project });
  if (epoch !== state.epoch) return;
  renderStudies(listing);
  if (listing.studies.length)
    await selectStudy(
      listing.studies.find((study) => study.id === preferred)?.id ||
        listing.studies[0].id,
    );
  else byId("new-study").open = true;
}
function renderResult(value) {
  if (
    value.record?.id !== state.trial ||
    value.record?.study_id !== state.study
  )
    return;
  byId("trial-detail").hidden = false;
  byId("trial-title").textContent = value.record.label;
  byId("trial-meta").textContent =
    `${value.record.partition} / ${value.record.status} / input ${value.record.input_sha256}`;
  byId("trial-error").textContent =
    value.error?.message ||
    (value.record.status === "interrupted"
      ? "Interrupted attempt; no completed result retained"
      : "");
  const result = value.result;
  byId("result-json").textContent = JSON.stringify(result, null, 2);
  byId("risk-results").hidden = result?.format !== "alphacairn.risk-report.v1";
  if (!result || result.format !== "alphacairn.risk-report.v1") return;
  const root = byId("risk-summary");
  root.replaceChildren();
  const stats = [
    ["Portfolio equity", amount(result.valuation.equity, result.base_currency)],
    ["Coverage", result.complete ? "Complete" : "Incomplete"],
    [
      "Historical shocks",
      result.statistics.historical_tail?.observations ?? "Unavailable",
    ],
  ];
  for (const [label, value] of stats) {
    const item = element("span", label);
    item.append(element("strong", value));
    root.append(item);
  }
  const stresses = byId("stress-results");
  stresses.replaceChildren();
  const maximum = Math.max(
    1,
    ...result.stresses
      .filter((item) => item.complete)
      .map((item) => Math.abs(Number(item.pnl))),
  );
  for (const stress of result.stresses) {
    const row = element("div", null, "stress-row");
    row.dataset.loss = String(Number(stress.pnl) < 0);
    row.append(element("span", stress.id));
    const track = element("div", null, "stress-track");
    track.setAttribute("aria-hidden", "true");
    const bar = element("div", null, "stress-bar");
    bar.style.width = `${stress.complete ? Math.min(100, (Math.abs(Number(stress.pnl)) / maximum) * 100) : 0}%`;
    track.append(bar);
    row.append(
      track,
      element(
        "span",
        stress.complete
          ? amount(stress.pnl, result.base_currency)
          : "Incomplete",
        "number",
      ),
    );
    stresses.append(row);
  }
  const positions = byId("positions").querySelector("tbody");
  positions.replaceChildren();
  for (const position of result.exposures) {
    const row = element("tr");
    row.append(
      element("td", position.instrument || position.id),
      element(
        "td",
        amount(position.base_value, result.base_currency),
        "number",
      ),
      element(
        "td",
        position.base_value === null ? "Missing valuation" : "Valued",
      ),
    );
    positions.append(row);
  }
  byId("coverage").textContent = JSON.stringify(
    { history: result.history, warnings: result.warnings, scope: result.scope },
    null,
    2,
  );
}

byId("connect").addEventListener(
  "click",
  handler(() => openProject()),
);
byId("refresh").addEventListener(
  "click",
  handler(async () => {
    byId("trial-detail").hidden = true;
    byId("open-holdout").checked = false;
    await refresh();
    status("Saved view refreshed; holdout figures withheld");
  }),
);
byId("create-study").addEventListener(
  "submit",
  handler(async () => {
    const definition = {
      version: 1,
      name: byId("study-name").value.trim(),
      family: byId("family").value,
      hypothesis: byId("study-hypothesis").value,
      development: {
        start: byId("dev-start").value,
        end: byId("dev-end").value,
      },
      holdout: { start: byId("hold-start").value, end: byId("hold-end").value },
    };
    const value = await execute("create", { definition });
    if (value) {
      byId("new-study").open = false;
      await selectStudy(value.id);
    }
  }),
);
byId("load-control").addEventListener(
  "click",
  handler(async () => {
    if (state.busy)
      throw new Error("Wait for the current operation to finish.");
    busy(true);
    try {
      if (!state.controls)
        state.controls = (await request({ action: "examples" })).controls;
      const control = byId("control").value;
      byId("inputs").value = JSON.stringify(state.controls[control], null, 2);
      byId("partition").value =
        control === "holdout" ? "holdout" : "development";
      byId("trial-label").value =
        byId("control").selectedOptions[0].textContent;
      status("Synthetic control loaded; register it to retain the attempt");
    } finally {
      busy(false);
    }
  }),
);
byId("inputs-file").addEventListener(
  "change",
  handler(async (event) => {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 4 * 1024 * 1024)
      throw new Error(
        "Browser inputs support at most 4 MiB; use the CLI for larger inputs.",
      );
    if (state.busy)
      throw new Error("Wait for the current operation to finish.");
    busy(true);
    try {
      const text = await file.text();
      JSON.parse(text);
      byId("inputs").value = text;
      status(`Loaded ${file.name}; not registered yet`);
    } finally {
      busy(false);
    }
  }),
);
byId("register-trial").addEventListener(
  "submit",
  handler(async () => {
    if (!state.study) throw new Error("Create or open a study first.");
    let inputs;
    try {
      inputs = JSON.parse(byId("inputs").value);
    } catch (_) {
      throw new Error(
        "Load or import valid frozen input JSON before registering.",
      );
    }
    await execute("register", {
      study: state.study,
      inputs,
      partition: byId("partition").value,
      label: byId("trial-label").value,
    });
  }),
);
byId("compare-holdout").addEventListener(
  "click",
  handler(async () => {
    const value = await execute(
      "compare",
      { study: state.study, include_holdout: true, ...operator() },
      true,
    );
    if (value) renderComparison(value);
  }),
);
byId("export-trial").addEventListener(
  "click",
  handler(async () => {
    const trial = state.data?.context.trials.find(
      (item) => item.id === state.trial,
    );
    if (!trial) throw new Error("Inspect an attempt before exporting.");
    const value = await execute(
      "export",
      { trial: trial.id, ...operator() },
      trial.partition === "holdout",
    );
    if (value) download(value, `alphacairn-${trial.id}-evidence.json`);
  }),
);
byId("more-events").addEventListener(
  "click",
  handler(async () => {
    const epoch = state.epoch;
    const after = state.data.next_after;
    const value = await request({
      action: "view",
      project: state.project,
      study: state.study,
      after,
      limit: 50,
    });
    if (epoch !== state.epoch || after !== state.data.next_after) return;
    renderEvents(value.events, true);
    state.data.next_after = value.next_after;
    byId("more-events").hidden = !value.has_more;
  }),
);
byId("recover-response").addEventListener(
  "click",
  handler(async () => {
    const meta = state.pending;
    if (!meta) return;
    if (meta.holdout) requireHoldout("holdout");
    let value;
    let retried = false;
    try {
      value = await request({
        action: "receipt",
        project: meta.project,
        request_key: meta.request_key,
      });
    } catch (failure) {
      if (
        !failure.rejected ||
        !failure.message.includes("receipt not found") ||
        !meta.request
      )
        throw failure;
      retried = true;
      try {
        value = await request(meta.request);
      } catch (retryFailure) {
        if (retryFailure.rejected) pendingDisplay(null);
        throw retryFailure;
      }
    }
    pendingDisplay(null);
    if (
      meta.project !== state.project ||
      (meta.study && meta.study !== state.study)
    ) {
      status(
        "Saved response recovered for another study. Open that study to inspect it.",
      );
      return;
    }
    if (meta.action === "create") await selectStudy(value.id);
    else {
      await refresh();
      if (meta.trial) {
        state.trial = meta.trial;
        if (meta.action === "export")
          download(value, `alphacairn-${meta.trial}-evidence.json`);
        else renderResult(value);
      }
    }
    status(
      retried
        ? "Original request resolved with its retained identity"
        : "Saved response recovered without repeating the operation",
    );
  }),
);

for (const button of document.querySelectorAll(
  "button[type='submit'], #compare-holdout, #export-trial",
))
  button.dataset.mutation = "1";
handler(async () => {
  const pending = sessionStorage.getItem(pendingKey);
  if (pending) pendingDisplay(JSON.parse(pending));
  const scope = JSON.parse(
    sessionStorage.getItem("alphacairn-research-scope") || "null",
  );
  if (scope?.project) byId("project").value = scope.project;
  await openProject(scope?.study);
})();
