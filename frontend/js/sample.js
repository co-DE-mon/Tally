import { createAccount, postTransaction, postTransfer } from "./api.js";
import { newRef } from "./dom.js";
import { addAccount } from "./store.js";

// Two accounts with a believable month of history, made through the real API.
export async function createSampleAccounts() {
  const everyday = await createAccount("test-Everyday");
  const savings = await createAccount("test-Savings");
  addAccount(everyday);
  addAccount(savings);

  const add = (account, type, amount, description) =>
    postTransaction(account.id, { type, amount, description, reference_id: newRef() });

  await add(savings, "credit", "40000.00", "Opening deposit");
  await add(everyday, "credit", "52000.00", "Salary");
  await add(everyday, "debit", "1450.00", "Groceries");
  await add(everyday, "debit", "380.50", "Coffee and lunch");
  await add(everyday, "debit", "2199.00", "Phone bill");
  await postTransfer({
    source_account_id: everyday.id,
    destination_account_id: savings.id,
    amount: "15000.00",
    description: "Monthly savings",
    reference_id: newRef(),
  });
  await add(everyday, "debit", "640.00", "Train tickets");
  await add(savings, "credit", "1200.75", "Interest");
}
