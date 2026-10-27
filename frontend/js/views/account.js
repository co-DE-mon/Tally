import { createAccount, fetchBalance, fetchHistory, postTransaction, postTransfer } from "../api.js";
import { formatWhen, h, newRef } from "../dom.js";
import { friendlyError } from "../errors.js";
import { formatAmount, formatMinor, roll, toMinor } from "../money.js";
import { addAccount, displayName, getAccounts } from "../store.js";

const PAGE_SIZE = 10;
const MODES = [
  { key: "credit", tab: "Add money", submit: "Add money" },
  { key: "debit", tab: "Withdraw", submit: "Withdraw" },
  { key: "transfer", tab: "Send", submit: "Send money" },
];
const FILTERS = [
  { key: "", label: "All" },
  { key: "credit", label: "Money in" },
  { key: "debit", label: "Money out" },
];

const signed = (row) => (row.type === "credit" ? 1n : -1n) * toMinor(row.amount);

function title(row) {
  if (row.description) return row.description;
  if (row.transfer_id) return row.type === "credit" ? "Transfer received" : "Transfer sent";
  return row.type === "credit" ? "Money added" : "Money withdrawn";
}

export async function renderAccount({ hero, view, id }) {
  const account = getAccounts().find((a) => a.id === id);
  let others = getAccounts().filter((a) => a.id !== id);
  const state = { filter: "", rows: [], page: 0, totalPages: 0, total: 0, balance: null, mode: "credit", ref: newRef() };

  const figure = h("div", { class: "figure", "aria-live": "polite" }, "…");
  const copy = h("button", { type: "button", class: "ghost tiny", onclick: async () => {
    try { await navigator.clipboard.writeText(id); copy.textContent = "Copied"; } catch { copy.textContent = "Copy failed"; }
    setTimeout(() => { copy.textContent = "Copy ID"; }, 1500);
  } }, "Copy ID");
  hero.append(
    h("a", { class: "back ghost", href: "#/" }, "Back to accounts"),
    h("h1", {}, account ? displayName(account.name) : "Account"),
    figure,
    h("p", { class: "lede mono" }, id.slice(0, 8), " ", copy),
  );

  // ---- money form -------------------------------------------------------
  const amount = h("input", { id: "amount", class: "mono", inputMode: "decimal", autocomplete: "off", placeholder: "0.00", required: true });
  const note = h("input", { id: "note", maxlength: 255, autocomplete: "off", placeholder: "What is this for?" });
  const to = h("select", { id: "to" });
  const toField = h("label", { htmlFor: "to" }, "Send to", to);
  function loadRecipients() {
    others = getAccounts().filter((a) => a.id !== id);
    to.replaceChildren(...others.map((a) => h("option", { value: a.id }, displayName(a.name))));
  }
  loadRecipients();
  // For trying transfers: a throwaway account to send to. Stored as "test-..." like the sample accounts.
  const addRecipient = h("button", { type: "button", class: "quiet", onclick: async () => {
    addRecipient.disabled = true;
    try {
      const account = await createAccount(`test-Recipient ${others.length + 1}`);
      addAccount(account);
      loadRecipients();
      to.value = account.id;
      status.className = "status good";
      status.textContent = `Added ${displayName(account.name)} and selected it. It starts at ₹0.00.`;
    } catch (error) {
      status.className = "status bad";
      status.textContent = friendlyError(error);
    } finally {
      addRecipient.disabled = false;
    }
  } }, "Add test recipient");
  const submit = h("button", { class: "primary" });
  const status = h("p", { class: "status", role: "status" });
  const tabs = MODES.map((mode) => h("button", { type: "button", class: "seg", onclick: () => { state.mode = mode.key; syncForm(); } }, mode.tab));

  function syncForm() {
    MODES.forEach((mode, i) => tabs[i].setAttribute("aria-pressed", String(mode.key === state.mode)));
    submit.textContent = MODES.find((m) => m.key === state.mode).submit;
    toField.hidden = state.mode !== "transfer";
    addRecipient.hidden = state.mode !== "transfer";
    status.textContent = "";
    status.className = "status";
    if (state.mode === "transfer" && !others.length) {
      status.textContent = "There is no other account to send to yet. Add a test recipient to try it.";
    }
  }

  const form = h("form", { class: "panel", onsubmit: async (event) => {
    event.preventDefault();
    if (state.mode === "transfer" && !others.length) return;
    submit.disabled = true;
    const value = amount.value.trim();
    try {
      const result = state.mode === "transfer"
        ? await postTransfer({ source_account_id: id, destination_account_id: to.value, amount: value, description: note.value, reference_id: state.ref })
        : await postTransaction(id, { type: state.mode, amount: value, description: note.value, reference_id: state.ref });
      const after = state.mode === "transfer" ? result.debit.balance : result.balance;
      state.ref = newRef();
      amount.value = "";
      note.value = "";
      status.className = "status good";
      status.textContent = `Done. Balance is now ${formatAmount(after)}.`;
      await refresh();
    } catch (error) {
      status.className = "status bad";
      status.textContent = friendlyError(error, { balance: state.balance, amount: value });
      if (error.code === "DUPLICATE_REFERENCE") {
        // The first attempt did apply, so start a fresh attempt and show what it did.
        state.ref = newRef();
        await refresh();
      }
    } finally {
      submit.disabled = false;
    }
  } },
    h("div", { class: "segmented", role: "group", "aria-label": "Kind of transaction" }, tabs),
    h("label", { htmlFor: "amount" }, "Amount (₹)", amount),
    toField,
    h("label", { htmlFor: "note" }, "Note (optional)", note),
    h("div", { class: "actions" }, submit, addRecipient),
    status,
  );

  // ---- feed -------------------------------------------------------------
  const chips = FILTERS.map((f) => h("button", { type: "button", class: "chip", onclick: async () => { state.filter = f.key; await refresh(); } }, f.label));
  const feed = h("div", { class: "ledger" });
  const more = h("button", { type: "button", class: "quiet", onclick: loadMore }, "Show older");
  const count = h("p", { class: "fine" });

  function renderFeed() {
    FILTERS.forEach((f, i) => chips[i].setAttribute("aria-pressed", String(f.key === state.filter)));
    feed.className = "ledger" + (state.filter ? " no-running" : "");
    feed.replaceChildren();
    if (!state.rows.length) {
      feed.append(h("p", { class: "empty" }, state.filter ? "Nothing matches this filter." : "No transactions yet. Add money to see the first entry here."));
    } else {
      feed.append(h("div", { class: "entry head" }, h("span", {}, "When"), h("span", {}, "Details"), h("span", { class: "num" }, "Amount"), h("span", { class: "num run" }, "Balance")));
      // Latest first, so each row's balance is the current balance minus everything newer.
      let running = state.balance;
      for (const row of state.rows) {
        const change = signed(row);
        feed.append(h("div", { class: `entry ${row.type}` },
          h("span", { class: "when" }, formatWhen(row.created_at)),
          h("span", { class: "what" }, h("span", { class: "title" }, title(row)), h("span", { class: "ref", title: row.reference_id }, row.transfer_id ? "Transfer · " : "", row.reference_id.slice(0, 14) + "…")),
          h("span", { class: "num amt" }, formatMinor(change, { sign: true })),
          h("span", { class: "num run" }, formatMinor(running)),
        ));
        running -= change;
      }
    }
    count.textContent = state.total ? `Showing ${state.rows.length} of ${state.total}` : "";
    more.hidden = state.page >= state.totalPages;
  }

  function apply(history, append) {
    state.rows = append ? state.rows.concat(history.data) : history.data;
    state.page = history.page;
    state.totalPages = history.total_pages;
    state.total = history.total_records;
  }

  async function refresh() {
    try {
      const [balance, history] = await Promise.all([
        fetchBalance(id),
        fetchHistory(id, { type: state.filter, page: 1, limit: PAGE_SIZE }),
      ]);
      const next = toMinor(balance.balance);
      roll(figure, state.balance, next);
      state.balance = next;
      apply(history, false);
      renderFeed();
    } catch (error) {
      figure.textContent = "—";
      feed.replaceChildren(h("p", { class: "empty bad" }, friendlyError(error)));
      more.hidden = true;
    }
  }

  async function loadMore() {
    more.disabled = true;
    try {
      apply(await fetchHistory(id, { type: state.filter, page: state.page + 1, limit: PAGE_SIZE }), true);
      renderFeed();
    } catch (error) {
      count.textContent = friendlyError(error);
    } finally {
      more.disabled = false;
    }
  }

  view.append(
    h("div", { class: "split" },
      h("section", {}, h("h2", {}, "Move money"), form),
      h("section", {},
        h("div", { class: "feed-head" }, h("h2", {}, "Transactions"), h("div", { class: "chips", role: "group", "aria-label": "Filter" }, chips)),
        feed, h("div", { class: "actions" }, more, count),
      ),
    ),
  );
  syncForm();
  await refresh();
}
