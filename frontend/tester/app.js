// Manual tester for the Ledger API. No validation here on purpose: the API's answers are the test.
// Amounts stay strings so JS never turns them into floats.

const base = () => document.getElementById("base").value.replace(/\/+$/, "");
const out = document.getElementById("out");
const log = document.getElementById("log");

async function call(method, path, body) {
  const options = { method };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  let status = "network error";
  let text;
  let json = null;
  try {
    const response = await fetch(base() + path, options);
    status = response.status;
    text = await response.text();
    try { json = JSON.parse(text); } catch { /* not JSON, shown raw */ }
  } catch (error) {
    text = String(error);
  }
  show(method, path, status, json, text);
  return { status, json };
}

function show(method, path, status, json, text) {
  const outcome = typeof status === "number" && status < 400 ? "ok" : "bad";
  const statusEl = document.getElementById("status");
  statusEl.textContent = typeof status === "number" ? status : "ERR";
  statusEl.className = `status ${outcome}`;
  document.getElementById("request").textContent = `${method} ${path}`;
  out.textContent = json ? JSON.stringify(json, null, 2) : text;
  const item = document.createElement("li");
  item.textContent = `${status}  ${method} ${path}`;
  item.className = outcome;
  log.prepend(item);
}

// Plain strings out of the form; empty optional fields are left out of the body.
function fields(form, { keepEmpty = [] } = {}) {
  const result = {};
  for (const [key, value] of new FormData(form)) {
    if (value !== "" || keepEmpty.includes(key)) result[key] = value;
  }
  return result;
}

function onSubmit(id, handler) {
  document.getElementById(id).addEventListener("submit", (event) => {
    event.preventDefault();
    handler(event.target);
  });
}

function rememberAccount(id) {
  for (const input of document.querySelectorAll(".acct")) input.value = id;
}

onSubmit("create-account", async (form) => {
  const { status, json } = await call("POST", "/accounts", fields(form));
  if (status === 201) rememberAccount(json.id);
});

onSubmit("add-transaction", (form) => {
  const { account_id, ...body } = fields(form, { keepEmpty: ["description"] });
  return call("POST", `/accounts/${encodeURIComponent(account_id)}/transactions`, body);
});

onSubmit("balance", (form) => {
  const { account_id } = fields(form);
  return call("GET", `/accounts/${encodeURIComponent(account_id ?? "")}/balance`);
});

onSubmit("history", async (form) => {
  const { account_id, ...query } = fields(form);
  const qs = new URLSearchParams(query).toString();
  const { status, json } = await call(
    "GET",
    `/accounts/${encodeURIComponent(account_id ?? "")}/transactions${qs ? "?" + qs : ""}`
  );
  renderHistory(status === 200 ? json : null);
});

onSubmit("transfer", (form) => call("POST", "/transfers", fields(form, { keepEmpty: ["description"] })));

for (const button of document.querySelectorAll('[data-fill="ref"]')) {
  button.addEventListener("click", () => {
    button.form.elements.reference_id.value = "ref-" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  });
}

// Built with textContent only, so nothing the API returns is ever parsed as HTML.
function renderHistory(page) {
  const holder = document.getElementById("history-table");
  holder.replaceChildren();
  if (!page) return;
  const summary = document.createElement("div");
  summary.className = "summary";
  summary.textContent = page.total_records === 0
    ? "No transactions match."
    : `Page ${page.page} of ${page.total_pages}, ${page.limit} per page, ${page.total_records} in total`;
  const table = document.createElement("table");
  const columns = [["created_at", "When"], ["type", "Type"], ["amount", "Amount"], ["reference_id", "Reference"], ["description", "Description"]];
  const head = table.insertRow();
  for (const [key, label] of columns) {
    head.appendChild(Object.assign(document.createElement("th"), { textContent: label, className: key === "amount" ? "amount" : "" }));
  }
  for (const row of page.data) {
    const tr = table.insertRow();
    for (const [key] of columns) {
      const cell = tr.insertCell();
      if (key === "amount") {
        // The sign and colour carry the type, so a credit and a debit differ at a glance.
        cell.textContent = (row.type === "credit" ? "+" : "−") + row.amount;
        cell.className = `amount ${row.type}`;
      } else {
        cell.textContent = row[key];
      }
    }
  }
  holder.append(summary, table);
}
