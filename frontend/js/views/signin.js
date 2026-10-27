import { h } from "../dom.js";
import { setUser } from "../store.js";

export function renderSignIn({ hero, view, reload }) {
  hero.append(
    h("h1", {}, "Welcome to Tally"),
    h("p", { class: "lede" }, "A small banking app on a real ledger API: exact money, no overdrafts, no double charges."),
  );

  const name = h("input", { id: "who", required: true, maxlength: 60, autocomplete: "off", placeholder: "Your first name" });
  view.append(
    h("form", { class: "panel narrow", onsubmit: (event) => {
      event.preventDefault();
      setUser(name.value.trim());
      location.hash = "#/";
      reload();
    } },
      h("label", { htmlFor: "who" }, "What should we call you?", name),
      h("button", { class: "primary" }, "Continue to the demo"),
      h("p", { class: "fine" }, "This is a demo sign-in. There are no passwords and nothing is secured. The name is only kept in this browser."),
    ),
  );
}
