/**
 * Folding cards for every dashboard page (window.FoldCards).
 *
 * What it does: a settings card (fieldset.cfg-card with a <legend>, or a section.cfg-card with an
 * h3.card-legend) gets a fold button in its title. Folded, the card shows only its title and a short
 * line ("6 settings", "4 buttons", or the first line of its help text); a click opens it. Which cards
 * are open or folded is remembered in this browser (localStorage STORE_KEY), per page and card.
 * Each page gets "Open all · Fold all" above its first group of cards. Cards with WIDE_AT settings or
 * more take the whole row once open (.fc-wide). Folded card bodies use hidden="until-found", so the
 * browser's own Ctrl+F still finds text in them and opens the card (the "beforematch" event).
 *
 * Who decides how a card starts:
 *   - Setup pages (menu groups with data-mode="setup" in index.html): cards start folded.
 *   - Live pages: cards start open (LIVE_STARTS_OPEN); they can still be folded by hand, and that is
 *     remembered too. Mode comes from admin.js window.AdminNav.modeOf(tab, sub).
 *   - A page part (an .acc sub-page, or the whole panel) with only one card is left alone:
 *     folding the only thing on a page just adds a click.
 *   - data-fold="no" on a card: never fold it. data-fold="open": it starts open on Setup pages too.
 *   - Cards inside another card are left alone.
 *
 * Who calls it:
 *   - Itself: a MutationObserver on <main> re-runs scan() after any page draws or redraws cards
 *     (admin.js renders the Status, plugin and chat games cards from strings), so new cards fold too.
 *   - admin.js openHit() (sidebar search, Ctrl+K) calls FoldCards.reveal(el) so a search hit inside a
 *     folded card opens it before scrolling there.
 *   - admin/rooms-setup.js draws its Stream Rooms settings cards already in this markup (it needs its
 *     own "N settings · M changed" line and opens cards while its Find box has text) and uses
 *     isOpen() / remember() / setOpen() and the shared click handling below.
 *
 * Card markup after scan() (rooms-setup.js writes the same classes; admin.css "Folding cards"):
 *   <fieldset class="cfg-card fc-card [fc-wide] [fc-open]" data-fc-id="config/core:Kick">
 *     <legend><button type="button" class="fc-fold" aria-expanded="false">Kick</button></legend>
 *     <p class="fc-sum muted">6 settings</p>
 *     <div class="fc-body" hidden="until-found"> ...the card's own content, untouched... </div>
 *   </fieldset>
 * Element ids inside the card do not change, so admin.js code that fills the fields keeps working.
 */
(() => {
  // Remembered open (1) / folded (0) per card id. Ids look like "<panel>/<sub>:<card title>" for
  // generic cards and "<sub>:<card title>" for Stream Rooms cards (rooms-setup.js), so they never clash.
  const STORE_KEY = "stream_core_open_cards";
  // The Stream Rooms page used its own list of opened cards before this file existed; read once and merged.
  const OLD_ROOMS_KEY = "stream_core_rooms_open";
  // A card with this many settings (inputs, selects, text boxes) goes full width when open.
  // Keep in step with rooms-setup.js, which counts its setting rows against the same number.
  const WIDE_AT = 9;
  // Live pages (used mid-stream): cards start open so nothing you need on stream is hidden.
  // Sen picks this in the thread "Fold cards on all Core pages"; flip here if that changes.
  const LIVE_STARTS_OPEN = true;
  // What counts as a "setting" in a card's summary line.
  const SETTING_SEL = "input:not([type=hidden]):not([type=button]):not([type=submit]):not([type=file]), select, textarea";
  // Things that can't sit inside the fold <button> (a button may not hold other controls).
  const INTERACTIVE_SEL = "input, select, textarea, button, a[href]";

  const $main = () => document.querySelector("main.admin-main") || document.body;

  // ── Remembered state ────────────────────────────────────────────────────
  function load() {
    let map = {};
    try { map = JSON.parse(localStorage.getItem(STORE_KEY) || "{}") || {}; } catch (_) { map = {}; }
    try {
      const old = localStorage.getItem(OLD_ROOMS_KEY);
      if (old) {
        JSON.parse(old).forEach((id) => { if (!(id in map)) map[id] = 1; });
        localStorage.removeItem(OLD_ROOMS_KEY);
        localStorage.setItem(STORE_KEY, JSON.stringify(map));
      }
    } catch (_) { /* private window or bad JSON: start fresh */ }
    return map;
  }
  let remembered = load();
  function save() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(remembered)); } catch (_) { /* private window */ }
  }

  /** True when a card should show open: what you last did with it, else its page's default. */
  function isOpen(id, startOpen) {
    return id in remembered ? !!remembered[id] : !!startOpen;
  }
  /** Remember a card as open or folded (rooms-setup.js and the click handler below). */
  function remember(id, on) {
    remembered[id] = on ? 1 : 0;
    save();
  }

  /** Show one card open or folded: the class, the button's aria-expanded and the body's hidden. */
  function setOpen(card, on) {
    card.classList.toggle("fc-open", on);
    const b = card.querySelector(":scope > legend .fc-fold, :scope > .card-legend .fc-fold");
    if (b) b.setAttribute("aria-expanded", String(on));
    const body = card.querySelector(":scope > .fc-body");
    if (!body) return;
    if (on) body.removeAttribute("hidden");
    else if (body.getAttribute("hidden") !== "until-found") body.setAttribute("hidden", "until-found");
  }

  // ── Which cards fold, and how they start ────────────────────────────────
  /** "live" or "setup" for the page part a card sits in (admin.js AdminNav; Setup if unknown). */
  function modeOf(card) {
    const panel = card.closest(".panel");
    if (!panel || !window.AdminNav) return "setup";
    const tab = panel.id.replace(/^tab-/, "");
    const acc = card.closest(".acc[data-sub]");
    return window.AdminNav.modeOf(tab, acc && panel.contains(acc) ? acc.dataset.sub : null);
  }

  /** The page part whose cards count together: an .acc sub-page, else the panel. */
  function scopeOf(card) {
    return card.closest(".acc[data-sub]") || card.closest(".panel");
  }

  /** The card's title element: <legend> for a fieldset, h3.card-legend for a section. */
  function titleOf(card) {
    return card.querySelector(":scope > legend, :scope > .card-legend");
  }

  /** Title text without controls or badges inside it (used for the remembered id and the fold button). */
  function titleText(el) {
    const c = el.cloneNode(true);
    c.querySelectorAll("input, select, textarea, .pill-tag, .badge, .nav-badge").forEach((n) => n.remove());
    return c.textContent.replace(/\s+/g, " ").trim();
  }

  /** Stable id for remembering: explicit id / plugin id beat the title (some titles show live state). */
  function cardId(card) {
    const panel = card.closest(".panel");
    const acc = card.closest(".acc[data-sub]");
    const where = (panel ? panel.id.replace(/^tab-/, "") : "page") + "/" + (acc ? acc.dataset.sub : "");
    const own = card.dataset.foldId || card.id || (card.dataset.plugin ? "plugin-" + card.dataset.plugin : "");
    const title = titleOf(card);
    return where + ":" + (own || (title ? titleText(title) : ""));
  }

  function eligible(card) {
    if (card.dataset.fold === "no") return false;
    if (!titleOf(card)) return false;
    if (card.parentElement && card.parentElement.closest(".cfg-card")) return false;   // card inside a card
    return !!card.closest(".panel");
  }

  // ── Building a card ─────────────────────────────────────────────────────
  /** Wrap the card's content in .fc-body and put the fold button in its title (once per card element). */
  function build(card) {
    const title = titleOf(card);
    card.classList.add("fc-card");
    card.dataset.fcId = cardId(card);
    if (!title.querySelector(".fc-fold")) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "fc-fold";
      btn.setAttribute("aria-expanded", "false");
      btn.title = "Open or fold this card";
      if (title.querySelector(INTERACTIVE_SEL)) {
        // the title holds its own controls (an editable name): a small arrow button goes in front
        btn.classList.add("fc-fold-arrow");
        btn.setAttribute("aria-label", "Open or fold " + (titleText(title) || "this card"));
        title.prepend(btn);
      } else {
        while (title.firstChild) btn.appendChild(title.firstChild);
        title.appendChild(btn);
      }
    }
    wrapBody(card, title);
    setOpen(card, isOpen(card.dataset.fcId, startsOpen(card)));
  }

  /** Move everything after the title into .fc-body (again, if a redraw put content back outside it). */
  function wrapBody(card, title) {
    let body = card.querySelector(":scope > .fc-body");
    let sum = card.querySelector(":scope > .fc-sum");
    if (!sum) {
      sum = document.createElement("p");
      sum.className = "fc-sum muted";
      title.after(sum);
    }
    if (!body) {
      body = document.createElement("div");
      body.className = "fc-body";
      sum.after(body);
    }
    const stray = [...card.childNodes].filter((n) => n !== title && n !== sum && n !== body);
    if (stray.length) {
      stray.forEach((n) => body.appendChild(n));
      setOpen(card, card.classList.contains("fc-open"));
    }
  }

  function startsOpen(card) {
    if (card.dataset.fold === "open") return true;
    return modeOf(card) === "live" ? LIVE_STARTS_OPEN : false;
  }

  /** The folded line: "N settings", else "N buttons", else the start of the card's first help text. */
  function summarize(card) {
    const body = card.querySelector(":scope > .fc-body");
    const sum = card.querySelector(":scope > .fc-sum");
    if (!body || !sum) return;
    // a control inside something hidden (a "More" box, an off-state message) doesn't count
    // (only hiding inside the card counts: the body itself is hidden while folded, and the page or
    // sub-page around the card may be hidden while you look at another one)
    const shown = (el) => {
      for (let n = el.parentElement; n && n !== body; n = n.parentElement) if (n.hidden) return false;
      return true;
    };
    const controls = [...body.querySelectorAll(SETTING_SEL)].filter(shown);
    const n = controls.length;
    let text;
    if (n) {
      text = n + (n === 1 ? " setting" : " settings");
      // a card whose first setting is its on/off switch ("Credits on", "Kick on", "On") says which,
      // so you can see what's switched on without opening anything
      const first = controls[0];
      const lab = first.type === "checkbox" && first.closest("label");
      if (lab && /\bon\b|\benabled?\b/i.test(lab.textContent)) text = (first.checked ? "On" : "Off") + " · " + text;
    } else {
      const b = [...body.querySelectorAll("button")].filter(shown).length;
      if (b) text = b + (b === 1 ? " button" : " buttons");
      else {
        const p = body.querySelector("p, li");
        text = p ? p.textContent.replace(/\s+/g, " ").trim() : "";
        if (text.length > 90) text = text.slice(0, 88).replace(/\s+\S*$/, "") + "…";
      }
    }
    if (sum.textContent !== text) sum.textContent = text;
    const wide = n >= WIDE_AT;
    if (card.classList.contains("fc-wide") !== wide) card.classList.toggle("fc-wide", wide);
  }

  // ── Scanning pages ──────────────────────────────────────────────────────
  /**
   * Fold every eligible card under root (default: the whole dashboard). Safe to run any time and as
   * often as you like: a card already built is only re-checked (summary, wrapper).
   * Also: a page part's card holder becomes a grid (.fc-grid) when it isn't one already, so folded
   * cards sit side by side like the Live page, and the page part gets its Open all / Fold all bar.
   */
  function scan(root) {
    root = root || $main();
    const byScope = new Map();
    root.querySelectorAll(".cfg-card").forEach((card) => {
      if (card.classList.contains("rs-card")) return;   // rooms-setup.js builds and summarizes its own
      if (!eligible(card)) return;
      const sc = scopeOf(card);
      if (!byScope.has(sc)) byScope.set(sc, []);
      byScope.get(sc).push(card);
    });
    byScope.forEach((cards, sc) => {
      // count every eligible card in the whole page part, not just the ones under root
      const all = root === $main() ? cards : [...sc.querySelectorAll(".cfg-card")].filter((c) => !c.classList.contains("rs-card") && eligible(c));
      if (all.length < 2) return;
      cards.forEach((card) => {
        if (!card.classList.contains("fc-card") || !card.querySelector(":scope > .fc-body")) build(card);
        else wrapBody(card, titleOf(card));
        summarize(card);
        const holder = card.parentElement;
        // only plain stacks of cards (.acc-body) turn into grids; panels and special layouts keep theirs
        if (holder.classList.contains("acc-body") && !holder.classList.contains("fc-grid")) holder.classList.add("fc-grid");
      });
      addBar(sc, all[0]);
    });
  }

  /** "Open all · Fold all" for one page part, put just above its first card's holder. */
  function addBar(scope, firstCard) {
    if (scope.querySelector(":scope [data-fc-bar]")) return;
    const bar = document.createElement("div");
    bar.className = "fc-bar";
    bar.dataset.fcBar = "";
    bar.innerHTML = '<button type="button" class="link-btn" data-fc-all="1">Open all</button>' +
      '<button type="button" class="link-btn" data-fc-all="0">Fold all</button>';
    const holder = firstCard.parentElement;
    // above a grid of cards, not inside it as one more grid cell
    if (holder.classList.contains("fc-grid") || /grid|flex/.test(getComputedStyle(holder).display)) holder.before(bar);
    else firstCard.before(bar);
  }

  /** Open every folded card around el (a search hit), so it can be seen and scrolled to. */
  function reveal(el) {
    let card = el && el.closest ? el.closest(".fc-card") : null;
    while (card) {
      if (!card.classList.contains("fc-open")) {
        remember(card.dataset.fcId, true);
        setOpen(card, true);
      }
      card = card.parentElement && card.parentElement.closest(".fc-card");
    }
  }

  // ── Clicks ──────────────────────────────────────────────────────────────
  // One handler for every page (Stream Rooms cards too): the fold button toggles its card and
  // remembers it; Open all / Fold all do every card in the same page part ([data-fc-scope] on
  // Stream Rooms pages, else the .acc sub-page, else the panel).
  document.addEventListener("click", (ev) => {
    const t = ev.target;
    if (!t.closest) return;
    const fold = t.closest(".fc-fold");
    if (fold) {
      const card = fold.closest(".fc-card");
      if (!card) return;
      ev.preventDefault();
      const on = !card.classList.contains("fc-open");
      remember(card.dataset.fcId, on);
      setOpen(card, on);
      document.dispatchEvent(new CustomEvent("foldcards:change", { detail: { card } }));
      return;
    }
    const all = t.closest("[data-fc-all]");
    if (all) {
      const scope = all.closest("[data-fc-scope]") || all.closest(".acc[data-sub]") || all.closest(".panel");
      const on = all.dataset.fcAll === "1";
      (scope ? scope.querySelectorAll(".fc-card") : []).forEach((card) => {
        if (card.hidden) return;
        remember(card.dataset.fcId, on);
        setOpen(card, on);
      });
      document.dispatchEvent(new CustomEvent("foldcards:change", { detail: { scope } }));
    }
  });

  // Ctrl+F found text inside a folded card: the browser shows it; we mark the card open and remember it.
  document.addEventListener("beforematch", (ev) => {
    const card = ev.target.closest && ev.target.closest(".fc-card");
    if (!card) return;
    remember(card.dataset.fcId, true);
    setOpen(card, true);
  }, true);

  // ── Keeping up with redraws ─────────────────────────────────────────────
  // admin.js draws many cards from strings after data loads, and redraws some on a timer. The
  // observer runs before the browser paints, so a new card never flashes open. It only scans when a
  // change could matter (a card was added, or a built card got content outside its .fc-body), so
  // the busy Live page events feed doesn't trigger scans; the scan's own changes add nothing new,
  // so it doesn't keep itself running.
  const touchesCards = (rec) => {
    if (rec.target.classList && rec.target.classList.contains("fc-card")) return true;
    for (const n of rec.addedNodes) {
      if (n.nodeType === 1 && (n.classList.contains("cfg-card") || n.querySelector(".cfg-card"))) return true;
    }
    return false;
  };
  // admin.js fills fields after its data loads (field.checked = ..., which isn't a DOM change the
  // observer sees), so the folded lines on the open page are re-counted once a second, and right
  // away when you change a field. Only folded cards on the page showing now; cheap.
  function resummarize() {
    document.querySelectorAll(".panel.active .fc-card:not(.fc-open):not(.rs-card)").forEach(summarize);
  }
  document.addEventListener("change", (ev) => {
    const card = ev.target.closest && ev.target.closest(".fc-card:not(.rs-card)");
    if (card) summarize(card);
  });
  function start() {
    scan();
    setInterval(resummarize, 1000);
    new MutationObserver((recs) => { if (recs.some(touchesCards)) scan(); }).observe($main(), { childList: true, subtree: true });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();

  window.FoldCards = { WIDE_AT, isOpen, remember, setOpen, reveal, scan };
})();
