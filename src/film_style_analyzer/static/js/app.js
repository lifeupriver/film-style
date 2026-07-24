// app.js — hash router + data fetcher.

import {
  el,
  renderCorpus,
  renderFilm,
  renderGuide,
  renderCraft,
  renderShotProfile,
  renderHandoff,
  renderCompareIntro,
  renderCompareResult,
  renderSettings,
} from "./views.js";

// ----- density toggle -----------------------------------------------------

const DENSITY_KEY = "atelier:density";
const DENSITY_CYCLE = ["spacious", "default", "compact"];

function applyDensity(value) {
  const html = document.documentElement;
  if (value === "default" || !value) {
    html.removeAttribute("data-density");
  } else {
    html.setAttribute("data-density", value);
  }
}

async function applyBranding() {
  try {
    const res = await fetch("/api/config");
    if (!res.ok) return;
    const cfg = await res.json();
    if (cfg.brand_name) {
      const node = document.querySelector('[data-id="brand-name"]');
      if (node) node.textContent = cfg.brand_name;
      document.title = `${cfg.brand_name} — film-style-analyzer`;
    }
    const sub = document.querySelector('[data-id="brand-sub"]');
    if (sub && cfg.genre_display_name) {
      sub.textContent = `Style Atelier · ${cfg.genre_display_name}`;
    }
    const badge = document.querySelector('[data-id="genre-badge"]');
    if (badge && cfg.active_genre) {
      badge.textContent = cfg.active_genre;
      badge.hidden = false;
    }
  } catch {}
}

function bindDensityToggle() {
  const btn = document.querySelector('[data-id="density-toggle"]');
  if (!btn) return;
  const stored = localStorage.getItem(DENSITY_KEY) || "default";
  applyDensity(stored);
  btn.addEventListener("click", () => {
    const current = document.documentElement.getAttribute("data-density") || "default";
    const idx = DENSITY_CYCLE.indexOf(current);
    const next = DENSITY_CYCLE[(idx + 1) % DENSITY_CYCLE.length];
    applyDensity(next);
    localStorage.setItem(DENSITY_KEY, next);
  });
}

const APP = document.getElementById("app");
const NAV_LINKS = Array.from(document.querySelectorAll(".masthead__nav a"));

const ROUTES = [
  { test: /^\/?$/, name: "/", render: viewCorpus },
  { test: /^\/film\/(.+)$/, name: "/film", render: viewFilm },
  { test: /^\/guide\/?$/, name: "/guide", render: viewGuide },
  { test: /^\/shot-profile\/?$/, name: "/shot-profile", render: viewShotProfile },
  { test: /^\/craft(?:\/.*)?$/, name: "/craft", render: viewCraft },
  { test: /^\/handoff\/?$/, name: "/handoff", render: viewHandoff },
  { test: /^\/compare\/?$/, name: "/compare", render: viewCompare },
  { test: /^\/settings\/?$/, name: "/settings", render: viewSettings },
];

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { Accept: "application/json" },
    ...opts,
  });
  if (!res.ok) throw new Error(`request failed: ${res.status}`);
  const ct = res.headers.get("Content-Type") || "";
  return ct.includes("json") ? res.json() : res.text();
}

function loading() {
  const s = document.createElement("section");
  s.className = "state state--loading";
  const k = document.createElement("p");
  k.className = "state__kicker";
  k.textContent = "Pulling reels from the vault";
  const t = document.createElement("p");
  t.className = "state__title cursor";
  t.textContent = "One moment";
  s.appendChild(k);
  s.appendChild(t);
  return s;
}

function setActiveNav(name) {
  NAV_LINKS.forEach((a) => {
    const route = a.getAttribute("data-route");
    a.classList.toggle("is-active", route === name);
  });
}

function mount(node) {
  APP.replaceChildren(node);
  // Reset scroll only on top-level route changes; not when result of compare upload.
  window.scrollTo({ top: 0 });
}

async function route() {
  const path = (location.hash || "#/").replace(/^#/, "") || "/";
  for (const r of ROUTES) {
    const m = path.match(r.test);
    if (m) {
      setActiveNav(r.name);
      mount(loading());
      try {
        const view = await r.render(m);
        APP.replaceChildren(view);
      } catch (err) {
        console.error(err);
        APP.replaceChildren(errorState(err));
      }
      return;
    }
  }
  APP.replaceChildren(notFound(path));
}

function notFound(path) {
  return el("section", { class: "state" }, [
    el("p", { class: "state__kicker" }, ["404 · No such reel"]),
    el("p", { class: "state__title" }, [path]),
    el("p", { class: "state__lede" }, [
      "Return to the ",
      el("a", { href: "#/", style: { color: "var(--amber-soft)" } }, ["Archive"]),
      ".",
    ]),
  ]);
}

function errorState(err) {
  return el("section", { class: "state" }, [
    el("p", { class: "state__kicker" }, ["Something jammed in the gate"]),
    el("p", { class: "state__title" }, ["A request failed."]),
    el("p", { class: "state__lede" }, [String(err.message || err)]),
  ]);
}

// ----- views ---------------------------------------------------------------

async function viewCorpus() {
  const [stats, films] = await Promise.all([
    api("/api/stats").catch(() => ({})),
    api("/api/films").then((r) => r.films || []).catch(() => []),
  ]);
  return renderCorpus(stats, films);
}

async function viewFilm(match) {
  const stem = decodeURIComponent(match[1]);
  const analysis = await api(`/api/films/${encodeURIComponent(stem)}`);
  return renderFilm(analysis);
}

async function viewGuide() {
  const payload = await api("/api/guide").catch(() => ({ exists: false }));
  return renderGuide(payload);
}

async function viewCraft() {
  const payload = await api("/api/edit-craft").catch(() => ({
    exists: false,
    files: [],
  }));
  return renderCraft(payload);
}

async function viewShotProfile() {
  const payload = await api("/api/shot-profile").catch(() => ({
    exists: false,
    profile: null,
  }));
  return renderShotProfile(payload);
}

async function viewHandoff() {
  const payload = await api("/api/handoff").catch(() => ({
    exists: false,
    files: [],
    file_count: 0,
    total_bytes: 0,
  }));
  return renderHandoff(payload);
}

async function viewCompare() {
  const page = renderCompareIntro();
  // Wire up dropzone after mount.
  setTimeout(() => bindDropzone(page), 0);
  return page;
}

async function viewSettings() {
  const cfg = await api("/api/config");
  const page = renderSettings(cfg);
  setTimeout(() => bindSettings(page), 0);
  return page;
}

// ----- dropzone (compare) -------------------------------------------------

function bindDropzone(page) {
  const dz = page.querySelector('[data-id="dropzone"]');
  const input = page.querySelector('[data-id="file-input"]');
  const result = page.querySelector('[data-id="compare-result"]');
  if (!dz || !input || !result) return;

  const handle = async (file) => {
    if (!file) return;
    result.replaceChildren(loading());
    try {
      const buf = await file.arrayBuffer();
      const res = await fetch("/api/compare", {
        method: "POST",
        headers: {
          "Content-Type": "application/xml",
          "X-Filename": file.name,
        },
        body: buf,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.error || `request failed: ${res.status}`);
      }
      const data = await res.json();
      result.replaceChildren(renderCompareResult(data));
    } catch (err) {
      result.replaceChildren(errorState(err));
    }
  };

  dz.addEventListener("click", () => input.click());
  dz.addEventListener("keypress", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      input.click();
    }
  });
  input.addEventListener("change", (e) => handle(e.target.files?.[0]));

  ["dragover"].forEach((ev) =>
    dz.addEventListener(ev, (e) => {
      e.preventDefault();
      dz.classList.add("is-active");
    })
  );
  dz.addEventListener("dragleave", () => dz.classList.remove("is-active"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("is-active");
    const file = e.dataTransfer?.files?.[0];
    handle(file);
  });
}

// ----- settings save -------------------------------------------------------

function bindSettings(page) {
  const form = page.querySelector('[data-id="settings-form"]');
  const btn = page.querySelector('[data-id="save-config"]');
  const status = page.querySelector('[data-id="save-status"]');
  if (!form || !btn || !status) return;

  btn.addEventListener("click", async () => {
    const inputs = Array.from(form.querySelectorAll("[data-key]"));
    const payload = {};
    for (const inp of inputs) {
      const key = inp.dataset.key;
      if (inp.type === "checkbox") {
        payload[key] = inp.checked;
      } else if (inp.type === "number") {
        const v = inp.value.trim();
        payload[key] = v === "" ? null : Number(v);
      } else {
        payload[key] = inp.value;
      }
    }
    status.textContent = "Saving…";
    try {
      const res = await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("save failed");
      status.textContent = "Saved.";
      setTimeout(() => (status.textContent = ""), 2200);
    } catch (err) {
      status.textContent = `Failed: ${err.message || err}`;
    }
  });
}

// ----- bootstrap -----------------------------------------------------------

window.addEventListener("hashchange", route);
window.addEventListener("DOMContentLoaded", () => {
  applyBranding();
  bindDensityToggle();
  route();
});
// In case DOMContentLoaded already fired (script parsed late):
if (document.readyState !== "loading") {
  applyBranding();
  bindDensityToggle();
  route();
}
