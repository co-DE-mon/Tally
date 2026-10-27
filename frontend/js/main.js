import { h } from "./dom.js";
import { clearUser, getUser } from "./store.js";
import { renderAccount } from "./views/account.js";
import { renderAccounts } from "./views/accounts.js";
import { renderSignIn } from "./views/signin.js";

const heroSlot = document.getElementById("hero");
const viewSlot = document.getElementById("view");
const userSlot = document.getElementById("user");

function route() {
  // Each route draws into fresh containers, so a slow response from a page we left can't write into the new one.
  const hero = h("div", { class: "hero-inner" });
  const view = h("div", { class: "view-inner" });
  heroSlot.replaceChildren(hero);
  viewSlot.replaceChildren(view);

  const user = getUser();
  userSlot.replaceChildren(...(user ? [h("span", {}, user), h("button", { class: "ghost", onclick: () => { clearUser(); location.hash = "#/"; route(); } }, "Sign out")] : []));
  window.scrollTo(0, 0);

  const context = { hero, view, user, reload: route };
  const account = location.hash.match(/^#\/account\/([0-9a-f-]{36})$/i);
  if (!user) renderSignIn(context);
  else if (account) renderAccount({ ...context, id: account[1].toLowerCase() });
  else renderAccounts(context);
}

window.addEventListener("hashchange", route);
route();
