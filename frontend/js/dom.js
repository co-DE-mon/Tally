// Tiny element builder. Text goes in as text nodes, never as HTML, so nothing the API returns is parsed as markup.
export function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value == null || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key in el) el[key] = value;
    else el.setAttribute(key, value === true ? "" : value);
  }
  el.append(...children.flat().filter((child) => child != null && child !== false));
  return el;
}

export function newRef() {
  // One reference per attempt: a retry of the same attempt is recognised by the API as a duplicate.
  const unique = crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2);
  return "tally-" + unique;
}

export function formatWhen(iso) {
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }).format(new Date(iso));
}
