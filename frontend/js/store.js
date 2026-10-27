// Demo-only state kept in this browser. The API has no login and no "list accounts" call,
// so the app remembers who is "signed in" and which account IDs were opened here.
const USER = "tally.user";
const ACCOUNTS = "tally.accounts";

function read(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}

export const getUser = () => read(USER, null);
export const setUser = (name) => localStorage.setItem(USER, JSON.stringify(name));
export const clearUser = () => localStorage.removeItem(USER);

export const getAccounts = () => read(ACCOUNTS, []);

export function addAccount(account) {
  const accounts = getAccounts().filter((a) => a.id !== account.id);
  localStorage.setItem(ACCOUNTS, JSON.stringify([...accounts, { id: account.id, name: account.name }]));
}

export function removeAccount(id) {
  localStorage.setItem(ACCOUNTS, JSON.stringify(getAccounts().filter((a) => a.id !== id)));
}

// Sample accounts are stored as "test-..." so the test suite's cleanup can remove them; people never see the prefix.
export const displayName = (name) => name.replace(/^test-/, "");
