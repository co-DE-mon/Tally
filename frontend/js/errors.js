import { formatAmount, formatMinor } from "./money.js";

// Turns the API's error code into a sentence that says what happened and what to do.
// `balance` (BigInt paise) and `amount` (string) are optional context for the balance message.
export function friendlyError(error, { balance, amount } = {}) {
  switch (error.code) {
    case "INSUFFICIENT_BALANCE":
      return balance != null && amount && /^[0-9]+(\.[0-9]+)?$/.test(amount)
        ? `Not enough balance. You have ${formatMinor(balance)} and this needs ${formatAmount(amount)}.`
        : "Not enough balance for this.";
    case "DUPLICATE_REFERENCE":
      return "Already processed. This exact request went through earlier, so it was not applied a second time.";
    case "ACCOUNT_NOT_FOUND":
      return "That account no longer exists on the server.";
    case "SAME_ACCOUNT":
      return "Pick a different account to send to.";
    case "BALANCE_LIMIT_EXCEEDED":
      return "That would take the balance past the largest amount an account can hold.";
    case "VALIDATION_ERROR":
      // The API's own wording for a bad amount talks about JSON strings, which means nothing to someone typing.
      return /^amount\b/i.test(error.message)
        ? "Enter the amount as digits with up to two decimals, like 250.50."
        : `That wasn't accepted: ${error.message.replace(/^(\w+): Value error, /, "$1: ")}`;
    case "SERVICE_UNAVAILABLE":
      return "The server is busy. Try again in a moment.";
    case "NETWORK":
      return `${error.message} Start the API, then try again.`;
    default:
      return "Something went wrong on the server.";
  }
}
