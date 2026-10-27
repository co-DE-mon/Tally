// Money is handled as BigInt paise, never as a JS number, so nothing is ever rounded.
const SYMBOL = "₹";

export function toMinor(text) {
  // The API sends amounts as strings such as "1250.50".
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = text.replace("-", "").split(".");
  const minor = BigInt(whole + (fraction + "00").slice(0, 2));
  return negative ? -minor : minor;
}

function group(digits) {
  // Indian grouping: the last three digits, then pairs (12,34,567).
  if (digits.length <= 3) return digits;
  return digits.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + digits.slice(-3);
}

export function formatMinor(minor, { sign = false } = {}) {
  const negative = minor < 0n;
  const absolute = negative ? -minor : minor;
  const text = `${SYMBOL}${group((absolute / 100n).toString())}.${(absolute % 100n).toString().padStart(2, "0")}`;
  if (negative) return "−" + text;
  return sign ? "+" + text : text;
}

export const formatAmount = (text) => formatMinor(toMinor(text));

// Counts a figure from one value to another, so a change in balance is visible. Skipped for reduced motion.
const running = new WeakMap();
export function roll(element, from, to) {
  cancelAnimationFrame(running.get(element));
  if (from === to || from == null || matchMedia("(prefers-reduced-motion: reduce)").matches) {
    element.textContent = formatMinor(to);
    return;
  }
  const start = performance.now();
  const duration = 650;
  const step = (now) => {
    const t = Math.min(1, (now - start) / duration);
    const eased = 1 - (1 - t) ** 3;
    element.textContent = formatMinor(from + (to - from) * BigInt(Math.round(eased * 1000)) / 1000n);
    if (t < 1) running.set(element, requestAnimationFrame(step));
    else element.textContent = formatMinor(to);
  };
  running.set(element, requestAnimationFrame(step));
}
