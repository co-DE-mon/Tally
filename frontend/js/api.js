// The API's address. The API only accepts browser calls from this page's origin (see app/main.py).
export const BASE = "http://localhost:8000";

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function call(method, path, body) {
  const options = { method };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(BASE + path, options);
  } catch {
    throw new ApiError(0, "NETWORK", `Can't reach the API at ${BASE}.`);
  }
  let json = null;
  try { json = await response.json(); } catch { /* not JSON */ }
  if (!response.ok) {
    throw new ApiError(response.status, json?.error?.code ?? "UNKNOWN", json?.error?.message ?? response.statusText);
  }
  return json;
}

const enc = encodeURIComponent;

export const createAccount = (name) => call("POST", "/accounts", { name });
export const fetchBalance = (id) => call("GET", `/accounts/${enc(id)}/balance`);
export const postTransaction = (id, body) => call("POST", `/accounts/${enc(id)}/transactions`, body);
export const postTransfer = (body) => call("POST", "/transfers", body);

export function fetchHistory(id, { type, page, limit }) {
  const query = new URLSearchParams({ page, limit });
  if (type) query.set("type", type);
  return call("GET", `/accounts/${enc(id)}/transactions?${query}`);
}
