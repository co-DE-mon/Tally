import { createAccount, fetchBalance } from "../api.js";
import { h } from "../dom.js";
import { friendlyError } from "../errors.js";
import { formatAmount, formatMinor, roll, toMinor } from "../money.js";
import { createSampleAccounts } from "../sample.js";
import { addAccount, displayName, getAccounts, removeAccount } from "../store.js";

export function renderAccounts({ hero, view, user, reload }) {
  const accounts = getAccounts();

  const total = h("div", { class: "figure" }, formatMinor(0n));
  hero.append(
    h("h1", {}, `Hello, ${user}`),
    total,
    h("p", { class: "lede" }, accounts.length ? `Across ${accounts.length} ${accounts.length === 1 ? "account" : "accounts"}` : "No accounts yet"),
  );

  const list = h("ul", { class: "accounts" });
  view.append(h("h2", {}, "Your accounts"), list);

  if (!accounts.length) {
    list.replaceWith(h("p", { class: "empty" }, "No accounts on this device yet. Open one below, or add two sample accounts that come with some history."));
  }

  const rows = accounts.map((account) => {
    const balance = h("span", { class: "money" }, "…");
    const row = h("li", {},
      h("a", { class: "account-row", href: `#/account/${account.id}` },
        h("span", { class: "account-name" }, displayName(account.name)),
        h("span", { class: "account-id" }, account.id.slice(0, 8)),
        balance,
      ),
    );
    list.append(row);
    return { account, balance, row };
  });

  let sum = 0n;
  for (const { account, balance, row } of rows) {
    fetchBalance(account.id).then(
      (result) => {
        balance.textContent = formatAmount(result.balance);
        sum += toMinor(result.balance);
        roll(total, 0n, sum);
      },
      (error) => {
        balance.textContent = error.code === "ACCOUNT_NOT_FOUND" ? "Not on this server" : "Unavailable";
        if (error.code === "ACCOUNT_NOT_FOUND") {
          row.append(h("button", { class: "quiet small", onclick: () => { removeAccount(account.id); reload(); } }, "Remove from list"));
        }
      },
    );
  }

  const name = h("input", { id: "new-name", required: true, maxlength: 100, autocomplete: "off", placeholder: "For example, Holiday fund" });
  const status = h("p", { class: "status", role: "status" });
  const sampleButton = h("button", { type: "button", class: "quiet", onclick: async () => {
    sampleButton.disabled = true;
    status.className = "status";
    status.textContent = "Creating sample accounts…";
    try {
      await createSampleAccounts();
      reload();
    } catch (error) {
      status.className = "status bad";
      status.textContent = friendlyError(error);
      sampleButton.disabled = false;
    }
  } }, "Add sample accounts");

  view.append(
    h("h2", {}, "Open an account"),
    h("form", { class: "panel", onsubmit: async (event) => {
      event.preventDefault();
      try {
        const account = await createAccount(name.value.trim());
        addAccount(account);
        location.hash = `#/account/${account.id}`;
      } catch (error) {
        status.className = "status bad";
        status.textContent = friendlyError(error);
      }
    } },
      h("label", { htmlFor: "new-name" }, "Account name", name),
      h("div", { class: "actions" }, h("button", { class: "primary" }, "Open account"), sampleButton),
      status,
    ),
  );
}
