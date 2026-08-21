"use strict";

const state = {
  lang: "de",
  i18n: {},
  step: 0,
  busy: false,
  health: { dry_run: false },
  csrfToken: "",

  online: false,
  networkChecked: false,
  networkChecking: false,
  hasWifi: false,
  ethernet: null,
  devices: [],
  wifiNetworks: [],
  wifiNetworksLoaded: false,
  wifiSsid: "",
  hiddenSsid: false,

  mode: "simple",
  catalog: [],
  catalogMode: "",
  selected: [],
  sources: [],
  sourcesSignature: "",
  sourceError: "",

  username: "",
  password: "",
  passwordConfirm: "",
  timezone: "Europe/Berlin",
  keyboard: "de",
  hostnames: {},
  sshImportUsername: "",
  sshKeys: [],
  manualSsh: "",
  sshImportBusy: false,
  installSshServer: true,
  disablePasswordAuth: false,
  theme: "uli-lenovo",
  bootTimeoutSeconds: 5,
  bootDefault: "",
  partitionStrategy: "equal",
  rootSizesMib: {},
  includeSwap: true,
  swapSizeMib: 8192,
  includeData: true,
  dataSizeMib: 65536,

  diskId: "",
  disks: [],
  preview: null,
  planFingerprint: "",
  reviewAcknowledged: false,
  acknowledgedFingerprint: "",

  install: null,
  installTimer: null,
  installStarted: false,
};

let renderSequence = 0;
let manualKeySequence = 0;
let manualKeyTimer = null;
const RESERVED_SYSTEM_USERNAMES = new Set([
  "_apt", "_chrony", "avahi", "avahi-autoipd", "backup", "bin", "colord", "cups-browsed",
  "cups-pk-helper", "daemon", "dnsmasq", "fwupd-refresh", "games", "gdm", "geoclue",
  "gnome-initial-setup", "gnome-remote-desktop", "gnats", "irc", "kernoops", "landscape", "list", "lp",
  "mail", "man", "messagebus", "nm-openvpn", "news", "nobody", "pollinate", "polkitd",
  "proxy", "pulse", "root", "rtkit", "saned", "speech-dispatcher", "sshd", "sssd", "statd", "sync", "tcpdump",
  "sys", "syslog", "systemd-coredump", "systemd-network", "systemd-oom", "systemd-resolve",
  "systemd-timesync", "tss", "usbmux", "uucp", "uuidd", "whoopsie", "www-data",
]);

const STEPS = [
  { id: "network", labelKey: "step.network" },
  { id: "mode", labelKey: "step.mode" },
  { id: "distros", labelKey: "step.distros" },
  { id: "sources", labelKey: "step.sources" },
  { id: "settings", labelKey: "step.settings" },
  { id: "storage", labelKey: "step.storage" },
  { id: "review", labelKey: "step.review" },
  { id: "install", labelKey: "step.progress" },
  { id: "done", labelKey: "step.done" },
];

const FAMILY_KEYS = {
  debian: "distros.family.debian",
  redhat: "distros.family.redhat",
  arch: "distros.family.arch",
  special: "distros.family.special",
};

const PHASE_KEYS = {
  prepare: "progress.prepare",
  download: "progress.download",
  verify: "progress.verify",
  artifacts: "progress.artifacts",
  partition: "progress.partition",
  partitioning: "progress.partition",
  install: "progress.installing_phase",
  installing: "progress.installing_phase",
  bootloader: "progress.bootloader",
  finalize: "progress.finalize",
  done: "progress.done_phase",
};

function t(key, vars = {}) {
  let value = String(state.i18n[key] ?? key);
  for (const [name, replacement] of Object.entries(vars)) {
    value = value.replaceAll(`{${name}}`, String(replacement));
  }
  return value;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttr(value) {
  return escapeHtml(value);
}

function th(key, vars = {}) {
  return escapeHtml(t(key, vars));
}

function clampNumber(value, minimum, maximum, fallback = minimum) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.min(maximum, Math.max(minimum, number));
}

function integer(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number) : fallback;
}

function formatGiB(sizeMib) {
  const gib = clampNumber(sizeMib, 0, Number.MAX_SAFE_INTEGER, 0) / 1024;
  return `${gib >= 10 ? gib.toFixed(0) : gib.toFixed(1)} GiB`;
}

function humanValue(value) {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.map(humanValue).join(", ");
  if (typeof value === "object") {
    return String(value.status ?? value.method ?? value.type ?? JSON.stringify(value));
  }
  return String(value);
}

function formatApiError(payload, fallback = "") {
  const detail =
    payload && typeof payload === "object" && !Array.isArray(payload)
      ? (payload.detail ?? payload.error ?? payload)
      : payload;
  if (Array.isArray(detail)) {
    const messages = detail.map((item) => {
      if (typeof item === "string") return item;
      if (!item || typeof item !== "object") return String(item || "");
      const location = Array.isArray(item.loc)
        ? item.loc.filter((part) => part !== "body").map(String).join(".")
        : "";
      const message = String(item.msg ?? item.message ?? item.type ?? "");
      return location && message ? `${location}: ${message}` : message;
    }).filter(Boolean);
    return messages.join(" · ") || fallback;
  }
  if (detail && typeof detail === "object") {
    return String(detail.message ?? detail.msg ?? detail.error ?? JSON.stringify(detail));
  }
  return String(detail || fallback);
}

async function api(path, options = {}) {
  const init = {
    method: options.method || "GET",
    headers: { ...(options.headers || {}) },
  };
  if (init.method !== "GET" && state.csrfToken) {
    init.headers["X-ULI-CSRF"] = state.csrfToken;
  }
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = typeof options.body === "string" ? options.body : JSON.stringify(options.body);
  }

  const response = await fetch(path, init);
  const contentType = response.headers.get("content-type") || "";
  let payload;
  if (contentType.includes("application/json")) {
    payload = await response.json().catch(() => ({}));
  } else {
    payload = await response.text();
  }
  if (!response.ok) {
    throw new Error(formatApiError(payload, response.statusText || String(response.status)));
  }
  return payload;
}

function showToast(title, body) {
  const toast = document.getElementById("toast");
  document.getElementById("toastTitle").textContent = String(title || "");
  document.getElementById("toastBody").textContent = String(body || "");
  toast.classList.add("show");
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => toast.classList.remove("show"), 4800);
}

function selectionKey(selection) {
  return `${String(selection?.id || "")}:${String(selection?.variant || "standard")}`;
}

function selectionSignature() {
  return `${state.mode}|${state.selected.map(selectionKey).sort().join("|")}`;
}

function catalogItemFor(selection) {
  const key = selectionKey(selection);
  return state.catalog.find((item) => selectionKey(item) === key);
}

function minimumRootGiB(selection) {
  const item = catalogItemFor(selection);
  return Math.max(4, integer(item?.minimum_root_gib, 20));
}

function defaultHostname(selection, index) {
  const base = String(selection?.id || `linux-${index + 1}`)
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "") || `linux-${index + 1}`;
  const duplicate = state.selected.filter((item) => item.id === selection.id).length > 1;
  const variant = String(selection?.variant || "standard")
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return duplicate && variant && variant !== "standard" ? `${base}-${variant}`.slice(0, 63) : base.slice(0, 63);
}

function ensureSelectionDefaults() {
  const validKeys = new Set(state.selected.map(selectionKey));
  Object.keys(state.rootSizesMib).forEach((key) => {
    if (!validKeys.has(key)) delete state.rootSizesMib[key];
  });
  Object.keys(state.hostnames).forEach((key) => {
    if (!validKeys.has(key)) delete state.hostnames[key];
  });
  for (const [index, selection] of state.selected.entries()) {
    const key = selectionKey(selection);
    const minimum = minimumRootGiB(selection);
    if (!Number.isFinite(Number(state.rootSizesMib[key]))) {
      state.rootSizesMib[key] = Math.max(minimum, state.mode === "simple" ? 64 : 40) * 1024;
    }
    if (!state.hostnames[key]) state.hostnames[key] = defaultHostname(selection, index);
  }
  if (!validKeys.has(state.bootDefault)) state.bootDefault = state.selected[0] ? selectionKey(state.selected[0]) : "";
}

function currentStepId() {
  return STEPS[state.step]?.id || STEPS[0].id;
}

function renderSteps() {
  const list = document.getElementById("stepList");
  list.innerHTML = STEPS.map((step, index) => {
    const className = index === state.step ? "active" : index < state.step ? "done" : "";
    const current = index === state.step ? ' aria-current="step"' : "";
    return `<li class="${className}"${current}><span class="n" aria-hidden="true">${String(index + 1).padStart(2, "0")}</span><span>${th(step.labelKey)}</span></li>`;
  }).join("");
}

function installIsSimulated(job = state.install || {}) {
  return job.dry_run === true || state.health.dry_run === true;
}

function installIsVerifiedComplete(job = state.install || {}) {
  if (String(job.status || "").toLowerCase() !== "done") return false;
  if (installIsSimulated(job)) return true;
  if (job.installation_complete === true || job.completed === true) return true;
  if (Array.isArray(job.completed)) return job.completed.length >= state.selected.length;
  if (Number.isFinite(Number(job.completed))) return Number(job.completed) >= state.selected.length;
  return false;
}

function installIsRunning(job = state.install || {}) {
  return ["idle", "pending", "accepted", "queued", "starting", "running", "working"].includes(String(job.status || "").toLowerCase());
}

function setBusy(busy) {
  state.busy = Boolean(busy);
  paintChrome();
}

function paintChrome() {
  document.documentElement.lang = state.lang;
  document.getElementById("appTitle").textContent = t("app.title");
  document.getElementById("appSub").textContent = t("app.subtitle");
  document.getElementById("railTitle").textContent = t("app.steps");
  document.getElementById("langLabel").textContent = t("app.language");
  document.getElementById("stepRail").setAttribute("aria-label", t("app.steps"));
  document.getElementById("skipLink").textContent = t("app.skip");

  const id = currentStepId();
  const back = document.getElementById("btnBack");
  const next = document.getElementById("btnNext");
  back.textContent = t("nav.back");
  next.textContent =
    id === "storage"
      ? t("nav.review")
      : id === "review"
        ? t("nav.install")
        : id === "done"
          ? installIsSimulated()
            ? t("done.restart_simulation")
            : t("done.reboot")
          : t("nav.next");

  back.disabled =
    state.busy ||
    state.step === 0 ||
    (id === "install" && installIsRunning()) ||
    id === "done";

  let nextDisabled = state.busy;
  if (id === "review") {
    nextDisabled ||= !state.reviewAcknowledged || !state.planFingerprint || Boolean(state.preview?.error);
  }
  if (id === "install") nextDisabled ||= !installIsVerifiedComplete();
  if (id === "done") nextDisabled ||= !installIsVerifiedComplete();
  next.disabled = nextDisabled;
  renderSteps();
}

function clearInstallTimer() {
  if (state.installTimer) {
    clearTimeout(state.installTimer);
    state.installTimer = null;
  }
}

async function render(options = {}) {
  const sequence = ++renderSequence;
  const id = currentStepId();
  if (id !== "install") clearInstallTimer();
  paintChrome();

  const main = document.getElementById("main");
  main.setAttribute("aria-busy", "true");
  let html;
  try {
    if (id === "network") html = viewNetwork();
    else if (id === "mode") html = viewMode();
    else if (id === "distros") html = await viewDistros();
    else if (id === "sources") html = await viewSources();
    else if (id === "settings") html = viewSettings();
    else if (id === "storage") html = await viewStorage();
    else if (id === "review") html = await viewReview();
    else if (id === "install") html = await viewInstall();
    else html = viewDone();
  } catch (error) {
    html = `
      <div class="eyebrow">${th(STEPS[state.step].labelKey)}</div>
      <h3>${th("error.view_title")}</h3>
      <p class="lead">${escapeHtml(error?.message || error)}</p>
      <div class="panel"><div class="hint danger">${th("error.try_again")}</div></div>`;
  }
  if (sequence !== renderSequence) return;

  main.innerHTML = html;
  main.setAttribute("aria-busy", "false");
  bindView(id);
  paintChrome();
  if (options.focus !== false) {
    try {
      main.focus({ preventScroll: true });
    } catch (_) {
      main.focus();
    }
  }
}

function signalLevel(signal) {
  if (signal >= 75) return 4;
  if (signal >= 50) return 3;
  if (signal >= 25) return 2;
  return 1;
}

function wifiListHtml() {
  if (!state.wifiNetworksLoaded) return `<div class="hint">${th("network.scan_prompt")}</div>`;
  if (!state.wifiNetworks.length) return `<div class="hint">${th("network.scan_empty")}</div>`;
  return state.wifiNetworks.map((network, index) => {
    const selected = network.ssid === state.wifiSsid;
    const level = signalLevel(integer(network.signal, 0));
    return `
      <button type="button" class="wifi ${selected ? "selected" : ""}" data-wifi-index="${index}" aria-pressed="${selected}">
        <span><strong>${escapeHtml(network.ssid)}</strong><small>${escapeHtml(network.security || "WLAN")} · ${integer(network.signal, 0)}%</small></span>
        <span class="bars" data-level="${level}" aria-label="${th("network.signal", { signal: integer(network.signal, 0) })}"><i></i><i></i><i></i><i></i></span>
      </button>`;
  }).join("");
}

function viewNetwork() {
  const statusClass = state.networkChecking ? "busy" : state.online ? "online" : "offline";
  const statusText = state.networkChecking
    ? t("network.checking")
    : state.online
      ? t("network.ok")
      : t("network.fail");
  const deviceItems = state.devices
    .filter((device) => device && (device.type === "ethernet" || device.type === "wifi"))
    .map((device) => `<li><strong>${escapeHtml(device.name)}</strong><span>${escapeHtml(device.type)} · ${escapeHtml(device.state)}</span></li>`)
    .join("");
  const ethernetHint = state.ethernet === true ? t("network.guide_lan_up") : t("network.guide_lan");
  const wifiHint = state.hasWifi ? t("network.guide_wifi") : t("network.guide_no_wifi");

  return `
    <div class="eyebrow">${th("step.network")}</div>
    <h3>${th("network.title")}</h3>
    <p class="lead">${th(state.online ? "network.lead_ok" : "network.lead")}</p>
    <div class="panel">
      <div class="status ${statusClass}" role="status"><span class="pulse" aria-hidden="true"></span>${escapeHtml(statusText)}</div>
      <div class="hint">${th("network.guide_intro")}<br>${escapeHtml(ethernetHint)}<br>${escapeHtml(wifiHint)}</div>
      ${deviceItems ? `<ul class="device-list"><li class="list-title">${th("network.devices")}</li>${deviceItems}</ul>` : ""}
      <div class="row">
        <button class="btn primary" type="button" id="btnEthUp">${th("network.ethernet_up")}</button>
        <button class="btn ghost" type="button" id="btnNetworkCheck">${th("network.retry")}</button>
      </div>
      <section class="subpanel ${state.hasWifi && !state.online ? "" : "hidden"}" aria-labelledby="wifiHeading">
        <div class="section-heading"><div><h4 id="wifiHeading">${th("network.wifi")}</h4><p>${th("network.wifi_help")}</p></div><button class="btn ghost compact" type="button" id="btnScan">${th("network.scan")}</button></div>
        <div class="wifi-list" id="wifiList">${wifiListHtml()}</div>
        <div class="field">
          <label for="wifiPassword">${th("network.password")}</label>
          <input type="password" id="wifiPassword" autocomplete="off">
        </div>
        <label class="check" for="hiddenToggle"><input type="checkbox" id="hiddenToggle" ${state.hiddenSsid ? "checked" : ""}> <span>${th("network.hidden")}</span></label>
        <div class="field ${state.hiddenSsid ? "" : "hidden"}" id="hiddenField">
          <label for="hiddenSsid">${th("network.hidden_ssid")}</label>
          <input type="text" id="hiddenSsid" autocomplete="off">
        </div>
        <div class="row"><button class="btn primary" type="button" id="btnConnect">${th("network.connect")}</button></div>
        <div class="hint hidden" id="networkAction" role="status"></div>
      </section>
    </div>`;
}

function viewMode() {
  const modes = [
    ["simple", "mode.simple", "mode.simple.desc", false],
    ["multiboot", "mode.multi", "mode.multi.desc", false],
    ["add", "mode.add", "mode.add.desc", true],
    ["remove", "mode.remove", "mode.remove.desc", true],
  ];
  return `
    <div class="eyebrow">${th("step.mode")}</div>
    <h3>${th("mode.title")}</h3>
    <p class="lead">${th("mode.lead")}</p>
    <div class="modes panel" role="radiogroup" aria-label="${th("mode.title")}">
      ${modes.map(([id, title, description, disabled]) => `
        <button type="button" class="mode ${state.mode === id ? "selected" : ""} ${disabled ? "disabled" : ""}" data-mode="${id}" role="radio" aria-checked="${state.mode === id}" ${disabled ? "disabled aria-disabled=\"true\"" : ""}>
          <span class="mode-copy"><strong>${th(title)}</strong><span>${th(description)}</span></span>
          ${disabled ? `<span class="badge development">${th("mode.development")}</span>` : `<span class="mode-check" aria-hidden="true">✓</span>`}
        </button>`).join("")}
    </div>`;
}

async function loadCatalog() {
  if (state.catalogMode === state.mode && state.catalog.length) return;
  const data = await api(`/api/catalog?mode=${encodeURIComponent(state.mode)}`);
  state.catalog = Array.isArray(data?.items) ? data.items.filter(Boolean) : [];
  state.catalogMode = state.mode;
  ensureSelectionDefaults();
}

async function viewDistros() {
  await loadCatalog();
  const selectedKeys = new Set(state.selected.map(selectionKey));
  const groups = {};
  state.catalog.forEach((item, index) => {
    const family = String(item.family || "special");
    (groups[family] ||= []).push({ item, index });
  });
  const multiple = state.mode === "multiboot";
  let cards = "";
  for (const [family, entries] of Object.entries(groups)) {
    cards += `<section class="distro-group" aria-labelledby="family-${escapeAttr(family)}"><h4 id="family-${escapeAttr(family)}">${th(FAMILY_KEYS[family] || family)}</h4><div class="distro-grid">`;
    for (const { item, index } of entries) {
      const key = selectionKey(item);
      const selected = selectedKeys.has(key);
      const enabled = item.enabled !== false;
      const minimum = integer(item.minimum_root_gib, 20);
      cards += `
        <label class="distro-card ${selected ? "selected" : ""} ${enabled ? "" : "disabled"}" for="distro-${index}">
          <input id="distro-${index}" type="${multiple ? "checkbox" : "radio"}" name="distro" data-catalog-index="${index}" ${selected ? "checked" : ""} ${enabled ? "" : "disabled"}>
          <span class="distro-copy"><strong>${escapeHtml(item.display_name || item.id)}</strong><span>${escapeHtml(item.version || t("distros.latest"))} · ${th("storage.min_size", { gib: minimum })}</span>${!enabled && item.reason ? `<em>${escapeHtml(item.reason)}</em>` : ""}</span>
          <span class="select-indicator" aria-hidden="true"></span>
        </label>`;
    }
    cards += `</div></section>`;
  }
  return `
    <div class="eyebrow">${th("step.distros")}</div>
    <h3>${th("distros.title")}</h3>
    <p class="lead">${th(multiple ? "distros.select_multi" : "distros.select_one")}</p>
    <div class="panel distro-panel">
      ${cards || `<div class="hint danger">${th("distros.empty")}</div>`}
    </div>`;
}

async function loadSources() {
  const signature = selectionSignature();
  if (state.sourcesSignature === signature && (state.sources.length || state.sourceError)) return;
  state.sourceError = "";
  state.sources = [];
  try {
    await persistState();
    const data = await api(`/api/sources?mode=${encodeURIComponent(state.mode)}`);
    state.sources = Array.isArray(data?.items)
      ? data.items.filter(Boolean)
      : Array.isArray(data?.sources)
        ? data.sources.filter(Boolean)
        : [];
  } catch (error) {
    state.sourceError = String(error?.message || error);
  }
  state.sourcesSignature = signature;
}

function sourceForSelection(selection) {
  const key = selectionKey(selection);
  return state.sources.find((source) => selectionKey(source) === key);
}

async function viewSources() {
  await loadSources();
  const rows = state.selected.map((selection) => {
    const source = sourceForSelection(selection);
    if (!source) {
      return `<article class="source-card error"><div><strong>${escapeHtml(selection.display_name || selection.id)}</strong><span>${th("sources.missing")}</span></div></article>`;
    }
    const enabled = source.enabled !== false;
    return `
      <article class="source-card ${enabled ? "verified" : "error"}">
        <div class="source-head"><div><strong>${escapeHtml(source.display_name || selection.display_name || selection.id)}</strong><span>${escapeHtml(source.version || t("distros.latest"))}</span></div><span class="badge ${enabled ? "ok" : "danger"}">${th(enabled ? "sources.ready" : "sources.unavailable")}</span></div>
        <dl class="source-details">
          <div><dt>${th("sources.url")}</dt><dd><code>${escapeHtml(source.url || "—")}</code></dd></div>
          <div><dt>${th("sources.verification")}</dt><dd>${escapeHtml(humanValue(source.verification))}</dd></div>
        </dl>
        ${!enabled && source.reason ? `<div class="hint danger">${escapeHtml(source.reason)}</div>` : ""}
      </article>`;
  }).join("");
  return `
    <div class="eyebrow">${th("step.sources")}</div>
    <h3>${th("sources.title")}</h3>
    <p class="lead">${th("sources.lead")}</p>
    <div class="panel">
      ${state.sourceError ? `<div class="hint danger">${th("sources.error", { error: state.sourceError })}</div><button class="btn ghost" type="button" id="btnSourcesRetry">${th("sources.retry")}</button>` : rows || `<div class="hint danger">${th("sources.empty")}</div>`}
      <div class="hint">${th("sources.official_only")}</div>
    </div>`;
}

function sshKeyDescription(key) {
  const parts = String(key || "").trim().split(/\s+/);
  if (parts.length < 2) return t("settings.ssh_invalid");
  return parts.length > 2 ? `${parts[0]} · ${parts.slice(2).join(" ")}` : parts[0];
}

function sshKeyListHtml() {
  if (!state.sshKeys.length) return `<div class="empty-state">${th("settings.ssh_none")}</div>`;
  return state.sshKeys.map((entry, index) => {
    const valid = entry.valid !== false;
    return `
      <label class="key-row ${valid ? "" : "invalid"}" for="ssh-key-${index}">
        <input id="ssh-key-${index}" type="checkbox" data-key-index="${index}" ${entry.selected !== false && valid ? "checked" : ""} ${valid ? "" : "disabled"}>
        <span><strong>${escapeHtml(sshKeyDescription(entry.key))}</strong><code>${escapeHtml(entry.fingerprint || (entry.pending ? t("settings.ssh_fingerprint_pending") : t("settings.ssh_invalid")))}</code></span>
        <span class="badge">${escapeHtml(entry.source || t("settings.ssh_manual_short"))}</span>
      </label>`;
  }).join("");
}

function themePreview(theme) {
  const names = state.selected.length
    ? state.selected.slice(0, 3).map((item) => escapeHtml(item.display_name || item.id))
    : ["Linux"];
  return `<span class="theme-screen ${theme === "uli-lenovo" ? "lenovo" : "uli"}" aria-hidden="true"><b>${theme === "uli-lenovo" ? "Lenovo" : "ULI"}</b><small>${th("settings.theme.choose_os")}</small>${names.map((name, index) => `<i class="${index === 0 ? "active" : ""}">${name}</i>`).join("")}</span>`;
}

function viewSettings() {
  ensureSelectionDefaults();
  const hostnameFields = state.selected.map((selection, index) => {
    const key = selectionKey(selection);
    return `
      <div class="field">
        <label for="hostname-${index}">${th("settings.hostname_for", { name: selection.display_name || selection.id })}</label>
        <input id="hostname-${index}" data-hostname-index="${index}" type="text" value="${escapeAttr(state.hostnames[key] || "")}" maxlength="63" spellcheck="false">
      </div>`;
  }).join("");
  const defaultOptions = state.selected.map((selection) => {
    const key = selectionKey(selection);
    return `<option value="${escapeAttr(key)}" ${state.bootDefault === key ? "selected" : ""}>${escapeHtml(selection.display_name || selection.id)}</option>`;
  }).join("");
  const rootRows = state.selected.map((selection, index) => {
    const key = selectionKey(selection);
    const minimum = minimumRootGiB(selection);
    const current = Math.max(minimum, integer(state.rootSizesMib[key] / 1024, minimum));
    return `
      <div class="range-row">
        <div><label for="root-size-${index}">${escapeHtml(selection.display_name || selection.id)}</label><small>${th("storage.min_size", { gib: minimum })}</small></div>
        <input id="root-size-${index}" data-root-index="${index}" type="range" min="${minimum}" max="256" step="1" value="${current}" ${state.partitionStrategy === "equal" ? "disabled" : ""}>
        <output id="root-size-output-${index}" for="root-size-${index}">${current} GiB</output>
      </div>`;
  }).join("");
  const timeout = clampNumber(state.bootTimeoutSeconds, 1, 60, 5);
  const swapGiB = clampNumber(state.swapSizeMib / 1024, 1, 64, 8);
  const dataGiB = clampNumber(state.dataSizeMib / 1024, 1, 512, 64);

  return `
    <div class="eyebrow">${th("step.settings")}</div>
    <h3>${th("settings.title")}</h3>
    <p class="lead">${th("settings.lead")}</p>
    <div class="panel settings-panel">
      <fieldset class="settings-section">
        <legend>${th("settings.account")}</legend>
        <div class="form-grid two">
          <div class="field"><label for="username">${th("settings.username")}</label><input type="text" id="username" value="${escapeAttr(state.username)}" autocomplete="username" spellcheck="false"></div>
          <div class="field"><label for="timezone">${th("settings.timezone")}</label><input type="text" id="timezone" value="${escapeAttr(state.timezone)}" list="timezoneOptions" autocomplete="off"><datalist id="timezoneOptions"><option value="Europe/Berlin"><option value="Europe/Vienna"><option value="Europe/Zurich"><option value="Europe/London"><option value="America/New_York"><option value="Asia/Tokyo"><option value="UTC"></datalist></div>
          <div class="field"><label for="password">${th("settings.password")}</label><input type="password" id="password" value="${escapeAttr(state.password)}" minlength="8" autocomplete="new-password" aria-describedby="passwordHelp"><small id="passwordHelp">${th("settings.password_minimum")}</small></div>
          <div class="field"><label for="passwordConfirm">${th("settings.password_confirm")}</label><input type="password" id="passwordConfirm" value="${escapeAttr(state.passwordConfirm)}" minlength="8" autocomplete="new-password"></div>
          <div class="field"><label for="keyboard">${th("settings.keyboard")}</label><select id="keyboard"><option value="de" ${state.keyboard === "de" ? "selected" : ""}>Deutsch (DE)</option><option value="de-nodeadkeys" ${state.keyboard === "de-nodeadkeys" ? "selected" : ""}>Deutsch – ohne Akzenttasten</option><option value="us" ${state.keyboard === "us" ? "selected" : ""}>English (US)</option><option value="gb" ${state.keyboard === "gb" ? "selected" : ""}>English (UK)</option><option value="ch" ${state.keyboard === "ch" ? "selected" : ""}>Schweiz</option></select></div>
        </div>
        <div class="hostname-grid">${hostnameFields}</div>
      </fieldset>

      <fieldset class="settings-section">
        <legend>${th("settings.ssh_keys")}</legend>
        <p class="section-help">${th("settings.ssh_help")}</p>
        <div class="import-row">
          <div class="field grow"><label for="sshImportUsername">${th("settings.ssh_account")}</label><input type="text" id="sshImportUsername" value="${escapeAttr(state.sshImportUsername)}" autocomplete="off" spellcheck="false"></div>
          <button class="btn ghost" type="button" id="btnLaunchpadImport" ${state.sshImportBusy ? "disabled" : ""}>${th("settings.ssh_launchpad")}</button>
          <button class="btn ghost" type="button" id="btnGithubImport" ${state.sshImportBusy ? "disabled" : ""}>${th("settings.ssh_github")}</button>
        </div>
        <div class="field"><label for="manualSsh">${th("settings.ssh_manual")}</label><textarea id="manualSsh" rows="4" spellcheck="false" placeholder="ssh-ed25519 AAAA… user@example">${escapeHtml(state.manualSsh)}</textarea></div>
        <div class="key-list" id="sshKeyList">${sshKeyListHtml()}</div>
        <div class="toggle-grid">
          <label class="toggle-card" for="installSshServer"><input type="checkbox" id="installSshServer" ${state.installSshServer ? "checked" : ""}><span><strong>${th("settings.ssh_server")}</strong><small>${th("settings.ssh_server_desc")}</small></span></label>
          <label class="toggle-card ${state.installSshServer ? "" : "disabled"}" for="disablePasswordAuth"><input type="checkbox" id="disablePasswordAuth" ${state.installSshServer && state.disablePasswordAuth ? "checked" : ""} ${state.installSshServer ? "" : "disabled"}><span><strong>${th("settings.disable_password_auth")}</strong><small>${th("settings.disable_password_auth_desc")}</small></span></label>
        </div>
      </fieldset>

      <fieldset class="settings-section">
        <legend>${th("settings.bootmenu")}</legend>
        <div class="theme-grid" role="radiogroup" aria-label="${th("settings.theme")}">
          <label class="theme-card ${state.theme === "uli-lenovo" ? "selected" : ""}" for="themeLenovo"><input type="radio" id="themeLenovo" name="theme" value="uli-lenovo" ${state.theme === "uli-lenovo" ? "checked" : ""}>${themePreview("uli-lenovo")}<strong>${th("settings.theme.lenovo")}</strong></label>
          <label class="theme-card ${state.theme === "uli-dark" ? "selected" : ""}" for="themeUli"><input type="radio" id="themeUli" name="theme" value="uli-dark" ${state.theme === "uli-dark" ? "checked" : ""}>${themePreview("uli-dark")}<strong>${th("settings.theme.uli")}</strong></label>
        </div>
        <div class="form-grid two">
          <div class="range-field"><div><label for="bootTimeout">${th("settings.boot_timeout")}</label><output id="bootTimeoutOutput" for="bootTimeout">${timeout} s</output></div><input type="range" id="bootTimeout" min="1" max="60" value="${timeout}"></div>
          <div class="field"><label for="bootDefault">${th("settings.boot_default")}</label><select id="bootDefault">${defaultOptions}</select></div>
        </div>
      </fieldset>

      <fieldset class="settings-section">
        <legend>${th("settings.partitioning")}</legend>
        <div class="choice-row" role="radiogroup" aria-label="${th("settings.partition_strategy")}">
          <label for="partitionEqual" class="choice ${state.partitionStrategy === "equal" ? "selected" : ""}"><input id="partitionEqual" type="radio" name="partitionStrategy" value="equal" ${state.partitionStrategy === "equal" ? "checked" : ""}><span><strong>${th("settings.equal_size")}</strong><small>${th("settings.equal_size_desc")}</small></span></label>
          <label for="partitionCustom" class="choice ${state.partitionStrategy === "individual" ? "selected" : ""}"><input id="partitionCustom" type="radio" name="partitionStrategy" value="individual" ${state.partitionStrategy === "individual" ? "checked" : ""}><span><strong>${th("settings.custom_size")}</strong><small>${th("settings.custom_size_desc")}</small></span></label>
        </div>
        <div class="range-list ${state.partitionStrategy === "equal" ? "disabled" : ""}">${rootRows}</div>
        <div class="toggle-size-grid">
          <div class="toggle-size"><label class="check" for="includeSwap"><input type="checkbox" id="includeSwap" ${state.includeSwap ? "checked" : ""}><span><strong>${th("settings.swap_enable")}</strong><small>${th("settings.swap_desc")}</small></span></label><div class="range-field"><div><label for="swapSize">${th("settings.size")}</label><output id="swapSizeOutput" for="swapSize">${swapGiB} GiB</output></div><input id="swapSize" type="range" min="1" max="64" step="1" value="${swapGiB}" ${state.includeSwap ? "" : "disabled"}></div></div>
          <div class="toggle-size"><label class="check" for="includeData"><input type="checkbox" id="includeData" ${state.includeData ? "checked" : ""}><span><strong>${th("settings.data_enable")}</strong><small>${th("settings.data_desc")}</small></span></label><div class="range-field"><div><label for="dataSize">${th("settings.size")}</label><output id="dataSizeOutput" for="dataSize">${dataGiB} GiB</output></div><input id="dataSize" type="range" min="1" max="512" step="1" value="${dataGiB}" ${state.includeData ? "" : "disabled"}></div></div>
        </div>
      </fieldset>
    </div>`;
}

function selectedSshKeys() {
  return state.sshKeys
    .filter((entry) => entry.valid !== false && entry.selected !== false && String(entry.key || "").trim())
    .map((entry) => String(entry.key).trim());
}

function buildStatePayload() {
  ensureSelectionDefaults();
  const payload = {
    language: state.lang,
    mode: state.mode,
    selected: state.selected.map((selection) => ({
      id: String(selection.id || ""),
      variant: String(selection.variant || "standard"),
      display_name: String(selection.display_name || selection.id || ""),
    })),
    username: state.username,
    timezone: state.timezone,
    keyboard: state.keyboard,
    hostnames: { ...state.hostnames },
    ssh_keys: selectedSshKeys(),
    install_ssh_server: state.installSshServer,
    disable_password_auth: state.installSshServer && state.disablePasswordAuth,
    theme: state.theme,
    boot_timeout_seconds: integer(state.bootTimeoutSeconds, 5),
    boot_default: state.bootDefault,
    partition_strategy: state.partitionStrategy,
    root_sizes_mib: Object.fromEntries(Object.entries(state.rootSizesMib).map(([key, value]) => [key, integer(value, 0)])),
    include_swap: state.includeSwap,
    swap_size_mib: integer(state.swapSizeMib, 8192),
    include_data: state.includeData,
    data_size_mib: integer(state.dataSizeMib, 65536),
  };
  if (state.password) payload.password = state.password;
  if (state.diskId) payload.disk_id = state.diskId;
  return payload;
}

async function persistState() {
  return api("/api/state", { method: "POST", body: buildStatePayload() });
}

async function loadDisks() {
  const data = await api("/api/disks");
  state.disks = Array.isArray(data?.items) ? data.items.filter(Boolean) : [];
  if (!state.disks.some((disk) => String(disk.id) === String(state.diskId))) {
    state.diskId = state.disks[0]?.id ? String(state.disks[0].id) : "";
    state.reviewAcknowledged = false;
  }
}

async function loadPreview() {
  if (!state.diskId) {
    state.preview = { disk: null, partitions: [], error: "no_disk", warnings: [] };
    state.planFingerprint = "";
    return state.preview;
  }
  await persistState();
  const preview = await api(`/api/storage/preview?disk_id=${encodeURIComponent(state.diskId)}`);
  const nextFingerprint = String(preview?.plan_fingerprint || "");
  if (state.planFingerprint && state.planFingerprint !== nextFingerprint) {
    state.reviewAcknowledged = false;
    state.acknowledgedFingerprint = "";
  }
  state.preview = preview && typeof preview === "object" ? preview : { partitions: [] };
  state.planFingerprint = nextFingerprint;
  return state.preview;
}

function selectedDisk() {
  return state.disks.find((disk) => String(disk.id) === String(state.diskId)) || null;
}

function partitionName(partition) {
  if (partition.role === "esp") return t("storage.esp");
  if (partition.role === "swap") return t("storage.swap");
  if (partition.role === "data") return t("storage.data");
  const selection = state.selected.find((item) =>
    selectionKey(item) === partition.distribution || item.id === partition.distribution
  );
  return t("storage.root", { name: selection?.display_name || partition.label || partition.distribution || "root" });
}

function partitionPlanHtml(partitions, options = {}) {
  const list = Array.isArray(partitions) ? partitions : [];
  if (!list.length) return `<div class="empty-state">${th("storage.empty")}</div>`;
  const total = list.reduce((sum, partition) => sum + Math.max(0, Number(partition.size_mib) || 0), 0) || 1;
  const bar = list.map((partition) => {
    const role = ["esp", "root", "swap", "data"].includes(partition.role) ? partition.role : "other";
    const width = clampNumber(((Number(partition.size_mib) || 0) / total) * 100, 0.5, 100, 1);
    const label = `${partitionName(partition)}, ${formatGiB(partition.size_mib)}`;
    return `<span class="partition-segment ${role}" style="width:${width.toFixed(3)}%" title="${escapeAttr(label)}" aria-label="${escapeAttr(label)}"><i>${escapeHtml(partitionName(partition))}</i></span>`;
  }).join("");
  const rows = list.map((partition) => `
    <li><span><i class="partition-dot ${["esp", "root", "swap", "data"].includes(partition.role) ? partition.role : "other"}" aria-hidden="true"></i><strong>${escapeHtml(partitionName(partition))}</strong><small>${escapeHtml(partition.filesystem || "")}${partition.label ? ` · ${escapeHtml(partition.label)}` : ""}</small></span><b>${escapeHtml(formatGiB(partition.size_mib))}</b></li>`).join("");
  return `<div class="partition-visual" role="img" aria-label="${th("storage.visual_label")}">${bar}</div><ul class="partition-list ${options.compact ? "compact" : ""}">${rows}</ul>`;
}

function warningText(warning) {
  const raw = String(warning || "");
  if (raw.startsWith("below_minimum:")) {
    const [, distro, minimum] = raw.split(":");
    return t("storage.warning_below_minimum", { distro, gib: minimum });
  }
  if (raw === "swap_reduced") return t("storage.warning_swap_reduced");
  if (raw === "swap_disabled") return t("storage.warning_swap_disabled");
  return raw;
}

async function viewStorage() {
  await loadDisks();
  if (state.diskId) {
    try {
      await loadPreview();
    } catch (error) {
      state.preview = { partitions: [], warnings: [], error: String(error?.message || error) };
      state.planFingerprint = "";
    }
  } else {
    state.preview = { disk: null, partitions: [], warnings: [], error: "no_disk" };
    state.planFingerprint = "";
  }
  const disksHtml = state.disks.length
    ? state.disks.map((disk, index) => {
        const selected = String(disk.id) === String(state.diskId);
        return `
          <button type="button" class="disk ${selected ? "selected" : ""}" data-disk-index="${index}" aria-pressed="${selected}">
            <span><strong>${escapeHtml(disk.model || disk.path || t("storage.unknown_disk"))}</strong><small>${escapeHtml(disk.path || "")} · ${escapeHtml(disk.transport || t("storage.disk_type"))}${disk.serial ? ` · S/N ${escapeHtml(disk.serial)}` : ""}</small></span>
            <b>${escapeHtml(`${disk.size_gib ?? ((Number(disk.size_bytes) || 0) / 1024 ** 3).toFixed(1)} GiB`)}</b>
          </button>`;
      }).join("")
    : `<div class="hint danger">${th("error.no_disk")}</div>`;
  const warnings = (state.preview?.warnings || []).map((warning) => `<div class="hint warning">${escapeHtml(warningText(warning))}</div>`).join("");
  const previewError = state.preview?.error
    ? `<div class="hint danger">${th("storage.disk_error", { error: state.preview.error })}</div>`
    : "";
  return `
    <div class="eyebrow">${th("step.storage")}</div>
    <h3>${th("storage.title")}</h3>
    <p class="lead">${th("storage.lead")}</p>
    <div class="panel storage-layout">
      <section class="settings-section" aria-labelledby="diskHeading"><div class="section-heading"><div><h4 id="diskHeading">${th("storage.disk")}</h4><p>${th("storage.usb_excluded")}</p></div></div><div class="disk-list">${disksHtml}</div></section>
      <section class="settings-section" aria-labelledby="planHeading"><div class="section-heading"><div><h4 id="planHeading">${th("storage.summary")}</h4><p>${th(state.partitionStrategy === "equal" ? "storage.equal_summary" : "storage.custom_summary")}</p></div></div>${previewError}${warnings}${partitionPlanHtml(state.preview?.partitions)}</section>
    </div>`;
}

async function viewReview() {
  if (!state.disks.length) await loadDisks();
  try {
    await loadPreview();
  } catch (error) {
    state.preview = { partitions: [], warnings: [], error: String(error?.message || error) };
    state.planFingerprint = "";
  }
  const listedDisk = selectedDisk() || {};
  const previewDisk = state.preview?.disk || {};
  const target = { ...listedDisk, ...previewDisk };
  const error = state.preview?.error
    ? `<div class="hint danger">${th("storage.disk_error", { error: state.preview.error })}</div>`
    : "";
  const warnings = (state.preview?.warnings || []).map((warning) => `<div class="hint warning">${escapeHtml(warningText(warning))}</div>`).join("");
  return `
    <div class="eyebrow">${th("step.review")}</div>
    <h3>${th("review.title")}</h3>
    <p class="lead">${th("review.lead")}</p>
    <div class="panel review-layout">
      <section class="danger-card" aria-labelledby="eraseHeading">
        <span class="danger-icon" aria-hidden="true">!</span>
        <div><h4 id="eraseHeading">${th("review.erase_title")}</h4><p>${th("review.erase_body")}</p></div>
        <dl class="target-details">
          <div><dt>${th("review.model")}</dt><dd>${escapeHtml(target.model || t("storage.unknown_disk"))}</dd></div>
          <div><dt>${th("review.path")}</dt><dd><code>${escapeHtml(target.path || "—")}</code></dd></div>
          <div><dt>${th("review.serial")}</dt><dd><code>${escapeHtml(target.serial || "—")}</code></dd></div>
          <div><dt>${th("review.size")}</dt><dd>${escapeHtml(`${target.size_gib ?? ((Number(target.size_bytes) || 0) / 1024 ** 3).toFixed(1)} GiB`)}</dd></div>
        </dl>
      </section>
      <section class="settings-section" aria-labelledby="reviewPlanHeading"><div class="section-heading"><div><h4 id="reviewPlanHeading">${th("review.plan")}</h4><p>${th("review.plan_fixed")}</p></div></div>${error}${warnings}${partitionPlanHtml(state.preview?.partitions, { compact: true })}${state.planFingerprint ? `<div class="fingerprint"><span>${th("review.fingerprint")}</span><code>${escapeHtml(state.planFingerprint)}</code></div>` : `<div class="hint danger">${th("review.no_fingerprint")}</div>`}</section>
      <label class="acknowledgement ${state.reviewAcknowledged ? "checked" : ""}" for="ackDelete"><input type="checkbox" id="ackDelete" ${state.reviewAcknowledged ? "checked" : ""} ${state.planFingerprint && !state.preview?.error ? "" : "disabled"}><span><strong>${th("review.acknowledge")}</strong><small>${th("review.acknowledge_detail", { model: target.model || target.path || t("storage.unknown_disk") })}</small></span></label>
    </div>`;
}

function progressPercent(job) {
  return clampNumber(job?.percent ?? job?.progress ?? 0, 0, 100, 0);
}

function installStatusLabel(job) {
  const status = String(job?.status || "running").toLowerCase();
  if (status === "error" || status === "failed") return t("progress.failed");
  if (status === "done") {
    if (installIsSimulated(job)) return t("progress.simulation_done");
    if (installIsVerifiedComplete(job)) return t("progress.done_phase");
    return t("progress.unverified_done");
  }
  return PHASE_KEYS[job?.phase] ? t(PHASE_KEYS[job.phase]) : job?.phase ? String(job.phase) : t("progress.running");
}

function installLogs(job) {
  const raw = job?.log ?? job?.logs ?? [];
  const lines = Array.isArray(raw) ? raw.map(String) : String(raw || "").split("\n");
  return lines.filter(Boolean).slice(-80);
}

async function viewInstall() {
  if (!state.install) {
    try {
      state.install = await api("/api/install/status");
    } catch (error) {
      state.install = { status: "error", error: String(error?.message || error), percent: 0 };
    }
  }
  const job = state.install || {};
  const percent = progressPercent(job);
  const status = String(job.status || "running").toLowerCase();
  const statusClass = status === "error" || status === "failed" ? "offline" : status === "done" && installIsVerifiedComplete(job) ? "online" : "busy";
  const currentDistribution = job.current_distribution || job.distro || job.distribution || "";
  const downloads = (Array.isArray(job.downloads) ? job.downloads : []).map((download) => {
    const downloadPercent = clampNumber(download?.percent, 0, 100, 0);
    return `<div class="download-row"><div><strong>${escapeHtml(download?.name || download?.display_name || "ISO")}</strong><small>${escapeHtml(download?.status || "")} · ${downloadPercent.toFixed(0)}%</small></div><div class="bar" role="progressbar" aria-label="${escapeAttr(download?.name || "ISO")}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${downloadPercent.toFixed(0)}"><i style="width:${downloadPercent.toFixed(2)}%"></i></div></div>`;
  }).join("");
  const logs = installLogs(job);
  const unverified = status === "done" && !installIsVerifiedComplete(job);
  return `
    <div class="eyebrow">${th("step.progress")}</div>
    <h3>${th("progress.title")}</h3>
    <p class="lead">${th(installIsSimulated(job) ? "progress.simulation_lead" : "progress.lead")}</p>
    <div class="panel progress-layout">
      ${installIsSimulated(job) ? `<div class="simulation-banner"><strong>${th("progress.simulation")}</strong><span>${th("progress.simulation_notice")}</span></div>` : ""}
      <div class="progress-card">
        <div class="progress-head"><div class="status ${statusClass}" role="status"><span class="pulse" aria-hidden="true"></span>${escapeHtml(installStatusLabel(job))}</div><strong>${percent.toFixed(0)}%</strong></div>
        <div class="bar big" role="progressbar" aria-label="${th("progress.overall")}" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${percent.toFixed(0)}"><i style="width:${percent.toFixed(2)}%"></i></div>
        ${currentDistribution ? `<div class="current-distro"><span>${th("progress.current_distribution")}</span><strong>${escapeHtml(currentDistribution)}</strong></div>` : ""}
        <div class="hint ${status === "error" || status === "failed" || unverified ? "danger" : ""}">${escapeHtml(unverified ? t("progress.unverified_explanation") : job.message || installStatusLabel(job))}</div>
        ${job.error ? `<div class="hint danger">${escapeHtml(job.error)}</div>` : ""}
      </div>
      ${downloads ? `<section class="download-list" aria-label="${th("download.overview")}">${downloads}</section>` : ""}
      ${logs.length ? `<details class="log-panel" ${status === "error" || status === "failed" ? "open" : ""}><summary>${th("progress.log")}</summary><pre>${escapeHtml(logs.join("\n"))}</pre></details>` : ""}
      ${status === "error" || status === "failed" || unverified ? `<button type="button" class="btn ghost" id="btnInstallRetry">${th("progress.back_to_review")}</button>` : ""}
    </div>`;
}

function viewDone() {
  const job = state.install || {};
  const simulated = installIsSimulated(job);
  const verified = installIsVerifiedComplete(job);
  if (!verified) {
    return `<div class="eyebrow">${th("step.done")}</div><h3>${th("progress.unverified_done")}</h3><p class="lead">${th("progress.unverified_explanation")}</p><div class="panel"><div class="hint danger">${th("done.not_confirmed")}</div></div>`;
  }
  return `
    <div class="eyebrow">${th("step.done")}</div>
    <h3>${th(simulated ? "done.simulation_title" : "done.title")}</h3>
    <p class="lead">${th(simulated ? "done.simulation_body" : "done.body")}</p>
    <div class="panel done-panel">
      <div class="status ${simulated ? "busy" : "online"}"><span class="pulse" aria-hidden="true"></span>${th(simulated ? "done.simulation_status" : "done.success_status")}</div>
      ${job.artifact_dir ? `<div class="hint"><strong>${th("done.artifacts")}</strong><br><code>${escapeHtml(job.artifact_dir)}</code></div>` : ""}
    </div>`;
}

function setNetworkAction(message, danger = false) {
  const action = document.getElementById("networkAction");
  if (!action) return;
  action.textContent = String(message || "");
  action.classList.toggle("hidden", !message);
  action.classList.toggle("danger", danger);
}

function applyNetworkStatus(data) {
  state.online = Boolean(data?.online);
  state.hasWifi = Boolean(data?.has_wifi);
  state.ethernet = data?.ethernet ?? null;
  state.devices = Array.isArray(data?.devices) ? data.devices : [];
  state.networkChecked = true;
}

async function checkNetwork(usePreparation = true) {
  state.networkChecking = true;
  paintChrome();
  if (currentStepId() === "network") await render({ focus: false });
  try {
    const data = await api(usePreparation ? "/api/network/check" : "/api/network/status", {
      method: usePreparation ? "POST" : "GET",
    });
    applyNetworkStatus(data);
  } catch (error) {
    state.networkChecked = true;
    showToast(t("dialog.attention"), String(error?.message || error));
  } finally {
    state.networkChecking = false;
    if (currentStepId() === "network" && state.online) {
      state.step = STEPS.findIndex((step) => step.id === "mode");
      await render();
    } else if (currentStepId() === "network") {
      await render({ focus: false });
    }
  }
}

async function scanWifi() {
  setBusy(true);
  setNetworkAction(t("network.scanning"));
  try {
    const data = await api("/api/network/wifi?rescan=true");
    state.hasWifi = Boolean(data?.has_wifi);
    state.wifiNetworks = Array.isArray(data?.networks) ? data.networks.filter((item) => item?.ssid) : [];
    state.wifiNetworksLoaded = true;
    await render({ focus: false });
  } catch (error) {
    setNetworkAction(String(error?.message || error), true);
    showToast(t("dialog.attention"), String(error?.message || error));
  } finally {
    setBusy(false);
  }
}

async function connectWifi() {
  const ssid = state.hiddenSsid
    ? document.getElementById("hiddenSsid")?.value.trim()
    : state.wifiSsid;
  const password = document.getElementById("wifiPassword")?.value || "";
  if (!ssid) {
    showToast(t("dialog.attention"), t("network.need_ssid"));
    return;
  }
  setBusy(true);
  setNetworkAction(t("network.connecting", { ssid }));
  try {
    const data = await api("/api/network/wifi/connect", { method: "POST", body: { ssid, password } });
    if (!data?.ok) {
      throw new Error(data?.error || t("network.connect_fail"));
    }
    state.online = Boolean(data.online);
    setNetworkAction(t("network.connect_ok"));
    await render({ focus: false });
  } catch (error) {
    setNetworkAction(String(error?.message || error), true);
    showToast(t("dialog.attention"), t("network.connect_fail"));
  } finally {
    setBusy(false);
  }
}

async function bringEthernetUp() {
  setBusy(true);
  setNetworkAction(t("network.ethernet_wait"));
  try {
    const data = await api("/api/network/ethernet/up", { method: "POST" });
    applyNetworkStatus(data);
    await render({ focus: false });
  } catch (error) {
    setNetworkAction(String(error?.message || error), true);
    showToast(t("dialog.attention"), String(error?.message || error));
  } finally {
    setBusy(false);
  }
}

function bindNetwork() {
  document.getElementById("btnNetworkCheck")?.addEventListener("click", () => checkNetwork(true));
  document.getElementById("btnEthUp")?.addEventListener("click", bringEthernetUp);
  document.getElementById("btnScan")?.addEventListener("click", scanWifi);
  document.getElementById("btnConnect")?.addEventListener("click", connectWifi);
  document.getElementById("hiddenToggle")?.addEventListener("change", (event) => {
    state.hiddenSsid = event.target.checked;
    document.getElementById("hiddenField")?.classList.toggle("hidden", !state.hiddenSsid);
  });
  document.querySelectorAll("[data-wifi-index]").forEach((button) => {
    button.addEventListener("click", () => {
      const network = state.wifiNetworks[integer(button.dataset.wifiIndex, -1)];
      if (!network) return;
      state.wifiSsid = String(network.ssid || "");
      document.querySelectorAll("[data-wifi-index]").forEach((item) => {
        const selected = item === button;
        item.classList.toggle("selected", selected);
        item.setAttribute("aria-pressed", String(selected));
      });
    });
  });
  if (state.hasWifi && !state.online && !state.wifiNetworksLoaded && !state.busy) {
    setTimeout(scanWifi, 0);
  }
}

function bindMode() {
  document.querySelectorAll(".mode:not(:disabled)").forEach((button) => {
    button.addEventListener("click", async () => {
      const mode = button.dataset.mode;
      if (!['simple', 'multiboot'].includes(mode)) return;
      if (state.mode !== mode) {
        state.mode = mode;
        state.selected = [];
        state.catalog = [];
        state.catalogMode = "";
        state.sources = [];
        state.sourcesSignature = "";
        state.preview = null;
        state.planFingerprint = "";
        state.reviewAcknowledged = false;
      }
      await api("/api/state", { method: "POST", body: { mode, selected: [] } }).catch(() => {});
      await render({ focus: false });
    });
  });
}

function bindDistros() {
  document.querySelectorAll("[data-catalog-index]").forEach((input) => {
    input.addEventListener("change", () => {
      const item = state.catalog[integer(input.dataset.catalogIndex, -1)];
      if (!item || item.enabled === false) return;
      if (state.mode === "simple") {
        state.selected = [{ id: item.id, variant: item.variant, display_name: item.display_name }];
      } else {
        state.selected = [...document.querySelectorAll("[data-catalog-index]:checked")]
          .map((element) => state.catalog[integer(element.dataset.catalogIndex, -1)])
          .filter((catalogItem) => catalogItem && catalogItem.enabled !== false)
          .map((catalogItem) => ({ id: catalogItem.id, variant: catalogItem.variant, display_name: catalogItem.display_name }));
      }
      state.sources = [];
      state.sourcesSignature = "";
      state.sourceError = "";
      state.preview = null;
      state.planFingerprint = "";
      state.reviewAcknowledged = false;
      ensureSelectionDefaults();
      document.querySelectorAll(".distro-card").forEach((card) => card.classList.toggle("selected", Boolean(card.querySelector("input")?.checked)));
    });
  });
}

async function fingerprintSshKey(key) {
  try {
    const parts = String(key || "").trim().split(/\s+/);
    if (parts.length < 2 || !/^(ssh-|ecdsa-)/.test(parts[0])) return "";
    const binary = atob(parts[1]);
    const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const encoded = btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/=+$/g, "");
    return `SHA256:${encoded}`;
  } catch (_) {
    return "";
  }
}

async function updateManualSshKeys(text, updateDom = true) {
  const sequence = ++manualKeySequence;
  const imported = state.sshKeys.filter((entry) => entry.source !== "manual");
  const lines = [...new Set(String(text || "").split(/\r?\n/).map((line) => line.trim()).filter(Boolean))];
  const manual = lines.map((key) => ({ key, fingerprint: "", source: "manual", selected: true, pending: true, valid: true }));
  state.sshKeys = [...imported, ...manual];
  if (updateDom) {
    const list = document.getElementById("sshKeyList");
    if (list) list.innerHTML = sshKeyListHtml();
  }
  const fingerprints = await Promise.all(lines.map(fingerprintSshKey));
  if (sequence !== manualKeySequence) return;
  manual.forEach((entry, index) => {
    entry.fingerprint = fingerprints[index];
    entry.pending = false;
    entry.valid = Boolean(fingerprints[index]);
    if (!entry.valid) entry.selected = false;
  });
  state.sshKeys = [...imported, ...manual];
  if (updateDom) {
    const list = document.getElementById("sshKeyList");
    if (list) {
      list.innerHTML = sshKeyListHtml();
      bindSshKeyCheckboxes();
    }
  }
}

function bindSshKeyCheckboxes() {
  document.querySelectorAll("[data-key-index]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const entry = state.sshKeys[integer(checkbox.dataset.keyIndex, -1)];
      if (entry) entry.selected = checkbox.checked;
    });
  });
}

async function importSshKeys(provider) {
  captureSettingsForm();
  const username = state.sshImportUsername.trim();
  if (!username) {
    showToast(t("dialog.attention"), t("settings.ssh_account_required"));
    return;
  }
  state.sshImportBusy = true;
  setBusy(true);
  document.getElementById("btnLaunchpadImport")?.setAttribute("disabled", "");
  document.getElementById("btnGithubImport")?.setAttribute("disabled", "");
  try {
    const data = await api("/api/ssh/import", { method: "POST", body: { provider, username } });
    const incoming = Array.isArray(data?.keys) ? data.keys : [];
    const imported = [];
    for (const item of incoming) {
      const key = String(typeof item === "string" ? item : item?.key || "").trim();
      if (!key) continue;
      const fingerprint = String(typeof item === "object" && item?.fingerprint ? item.fingerprint : await fingerprintSshKey(key));
      imported.push({ key, fingerprint, source: provider, selected: typeof item === "object" ? item.selected !== false : true, valid: Boolean(fingerprint) });
    }
    const keys = new Map(state.sshKeys.map((entry) => [entry.key, entry]));
    imported.forEach((entry) => keys.set(entry.key, entry));
    state.sshKeys = [...keys.values()];
    showToast(t("settings.ssh_imported"), t("settings.ssh_imported_count", { count: imported.length }));
    state.sshImportBusy = false;
    await render({ focus: false });
  } catch (error) {
    showToast(t("dialog.attention"), String(error?.message || error));
  } finally {
    state.sshImportBusy = false;
    document.getElementById("btnLaunchpadImport")?.removeAttribute("disabled");
    document.getElementById("btnGithubImport")?.removeAttribute("disabled");
    setBusy(false);
  }
}

function captureSettingsForm() {
  if (currentStepId() !== "settings") return;
  state.username = document.getElementById("username")?.value.trim() ?? state.username;
  state.password = document.getElementById("password")?.value ?? state.password;
  state.passwordConfirm = document.getElementById("passwordConfirm")?.value ?? state.passwordConfirm;
  state.timezone = document.getElementById("timezone")?.value.trim() || "Europe/Berlin";
  state.keyboard = document.getElementById("keyboard")?.value || "de";
  state.sshImportUsername = document.getElementById("sshImportUsername")?.value.trim() ?? state.sshImportUsername;
  state.manualSsh = document.getElementById("manualSsh")?.value ?? state.manualSsh;
  state.installSshServer = document.getElementById("installSshServer")?.checked ?? state.installSshServer;
  state.disablePasswordAuth = document.getElementById("disablePasswordAuth")?.checked ?? state.disablePasswordAuth;
  if (!state.installSshServer) state.disablePasswordAuth = false;
  state.theme = document.querySelector('input[name="theme"]:checked')?.value || state.theme;
  state.bootTimeoutSeconds = integer(document.getElementById("bootTimeout")?.value, state.bootTimeoutSeconds);
  state.bootDefault = document.getElementById("bootDefault")?.value || state.bootDefault;
  state.partitionStrategy = document.querySelector('input[name="partitionStrategy"]:checked')?.value || state.partitionStrategy;
  state.includeSwap = document.getElementById("includeSwap")?.checked ?? state.includeSwap;
  state.swapSizeMib = integer(document.getElementById("swapSize")?.value, state.swapSizeMib / 1024) * 1024;
  state.includeData = document.getElementById("includeData")?.checked ?? state.includeData;
  state.dataSizeMib = integer(document.getElementById("dataSize")?.value, state.dataSizeMib / 1024) * 1024;
  document.querySelectorAll("[data-hostname-index]").forEach((input) => {
    const selection = state.selected[integer(input.dataset.hostnameIndex, -1)];
    if (selection) state.hostnames[selectionKey(selection)] = input.value.trim().toLowerCase();
  });
  document.querySelectorAll("[data-root-index]").forEach((input) => {
    const selection = state.selected[integer(input.dataset.rootIndex, -1)];
    if (selection) state.rootSizesMib[selectionKey(selection)] = integer(input.value, minimumRootGiB(selection)) * 1024;
  });
}

function bindSettings() {
  const bindValue = (id, property, transform = (value) => value) => {
    document.getElementById(id)?.addEventListener("input", (event) => { state[property] = transform(event.target.value); });
  };
  bindValue("username", "username", (value) => value.trim());
  bindValue("password", "password");
  bindValue("passwordConfirm", "passwordConfirm");
  bindValue("timezone", "timezone");
  bindValue("sshImportUsername", "sshImportUsername");
  document.getElementById("keyboard")?.addEventListener("change", (event) => { state.keyboard = event.target.value; });
  document.querySelectorAll("[data-hostname-index]").forEach((input) => input.addEventListener("input", () => {
    const selection = state.selected[integer(input.dataset.hostnameIndex, -1)];
    if (selection) state.hostnames[selectionKey(selection)] = input.value.trim().toLowerCase();
  }));
  document.getElementById("manualSsh")?.addEventListener("input", (event) => {
    state.manualSsh = event.target.value;
    clearTimeout(manualKeyTimer);
    manualKeyTimer = setTimeout(() => updateManualSshKeys(state.manualSsh), 280);
  });
  bindSshKeyCheckboxes();
  document.getElementById("btnLaunchpadImport")?.addEventListener("click", () => importSshKeys("launchpad"));
  document.getElementById("btnGithubImport")?.addEventListener("click", () => importSshKeys("github"));
  document.getElementById("installSshServer")?.addEventListener("change", async (event) => {
    captureSettingsForm();
    state.installSshServer = event.target.checked;
    if (!state.installSshServer) state.disablePasswordAuth = false;
    await render({ focus: false });
  });
  document.getElementById("disablePasswordAuth")?.addEventListener("change", (event) => { state.disablePasswordAuth = event.target.checked; });
  document.querySelectorAll('input[name="theme"]').forEach((input) => input.addEventListener("change", async () => {
    captureSettingsForm();
    state.theme = input.value;
    await render({ focus: false });
  }));
  document.getElementById("bootTimeout")?.addEventListener("input", (event) => {
    state.bootTimeoutSeconds = integer(event.target.value, 5);
    document.getElementById("bootTimeoutOutput").textContent = `${state.bootTimeoutSeconds} s`;
  });
  document.getElementById("bootDefault")?.addEventListener("change", (event) => { state.bootDefault = event.target.value; });
  document.querySelectorAll('input[name="partitionStrategy"]').forEach((input) => input.addEventListener("change", async () => {
    captureSettingsForm();
    state.partitionStrategy = input.value;
    await render({ focus: false });
  }));
  document.querySelectorAll("[data-root-index]").forEach((input) => input.addEventListener("input", () => {
    const index = integer(input.dataset.rootIndex, -1);
    const selection = state.selected[index];
    if (!selection) return;
    state.rootSizesMib[selectionKey(selection)] = integer(input.value, minimumRootGiB(selection)) * 1024;
    document.getElementById(`root-size-output-${index}`).textContent = `${integer(input.value)} GiB`;
  }));
  document.getElementById("includeSwap")?.addEventListener("change", async (event) => {
    captureSettingsForm();
    state.includeSwap = event.target.checked;
    await render({ focus: false });
  });
  document.getElementById("swapSize")?.addEventListener("input", (event) => {
    state.swapSizeMib = integer(event.target.value, 8) * 1024;
    document.getElementById("swapSizeOutput").textContent = `${integer(event.target.value)} GiB`;
  });
  document.getElementById("includeData")?.addEventListener("change", async (event) => {
    captureSettingsForm();
    state.includeData = event.target.checked;
    await render({ focus: false });
  });
  document.getElementById("dataSize")?.addEventListener("input", (event) => {
    state.dataSizeMib = integer(event.target.value, 64) * 1024;
    document.getElementById("dataSizeOutput").textContent = `${integer(event.target.value)} GiB`;
  });
  if (state.manualSsh && !state.sshKeys.some((entry) => entry.source === "manual")) updateManualSshKeys(state.manualSsh);
}

function bindStorage() {
  document.querySelectorAll("[data-disk-index]").forEach((button) => {
    button.addEventListener("click", async () => {
      const disk = state.disks[integer(button.dataset.diskIndex, -1)];
      if (!disk) return;
      state.diskId = String(disk.id || "");
      state.reviewAcknowledged = false;
      state.acknowledgedFingerprint = "";
      state.planFingerprint = "";
      setBusy(true);
      try {
        await render({ focus: false });
      } finally {
        setBusy(false);
      }
    });
  });
}

function bindReview() {
  document.getElementById("ackDelete")?.addEventListener("change", (event) => {
    state.reviewAcknowledged = event.target.checked;
    state.acknowledgedFingerprint = event.target.checked ? state.planFingerprint : "";
    event.target.closest(".acknowledgement")?.classList.toggle("checked", event.target.checked);
    paintChrome();
  });
}

async function pollInstall() {
  clearInstallTimer();
  if (currentStepId() !== "install" || !installIsRunning()) return;
  state.installTimer = setTimeout(async () => {
    if (currentStepId() !== "install") return;
    try {
      state.install = await api("/api/install/status");
      await render({ focus: false });
    } catch (_) {
      pollInstall();
    }
  }, 1200);
}

function bindInstall() {
  document.getElementById("btnInstallRetry")?.addEventListener("click", async () => {
    clearInstallTimer();
    state.reviewAcknowledged = false;
    state.acknowledgedFingerprint = "";
    state.planFingerprint = "";
    state.step = STEPS.findIndex((step) => step.id === "review");
    await render();
  });
  if (installIsRunning()) pollInstall();
}

function bindView(id) {
  if (id === "network") bindNetwork();
  else if (id === "mode") bindMode();
  else if (id === "distros") bindDistros();
  else if (id === "sources") {
    document.getElementById("btnSourcesRetry")?.addEventListener("click", async () => {
      state.sourcesSignature = "";
      state.sourceError = "";
      await render({ focus: false });
    });
  }
  else if (id === "settings") bindSettings();
  else if (id === "storage") bindStorage();
  else if (id === "review") bindReview();
  else if (id === "install") bindInstall();
}

function validateHostname(hostname) {
  return /^(?=.{1,63}$)[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$/.test(hostname);
}

function sourcesAreReady() {
  if (state.sourceError || !state.sources.length) return false;
  return state.selected.every((selection) => {
    const source = sourceForSelection(selection);
    return source && source.enabled !== false;
  });
}

async function validateSettings() {
  captureSettingsForm();
  if (state.manualSsh.trim()) await updateManualSshKeys(state.manualSsh, false);
  if (!state.username) {
    showToast(t("dialog.attention"), t("error.username_required"));
    return false;
  }
  if (!/^[a-z_][a-z0-9_-]{0,31}$/.test(state.username)) {
    showToast(t("dialog.attention"), t("error.username_invalid"));
    return false;
  }
  if (RESERVED_SYSTEM_USERNAMES.has(state.username)) {
    showToast(t("dialog.attention"), t("error.username_reserved"));
    return false;
  }
  if (!state.password) {
    showToast(t("dialog.attention"), t("error.password_required"));
    return false;
  }
  if (state.password.length < 8) {
    showToast(t("dialog.attention"), t("error.password_too_short"));
    return false;
  }
  if (state.password !== state.passwordConfirm) {
    showToast(t("dialog.attention"), t("error.password_mismatch"));
    return false;
  }
  const hostnames = state.selected.map((selection) => state.hostnames[selectionKey(selection)] || "");
  if (hostnames.some((hostname) => !validateHostname(hostname))) {
    showToast(t("dialog.attention"), t("error.hostname_invalid"));
    return false;
  }
  if (new Set(hostnames).size !== hostnames.length) {
    showToast(t("dialog.attention"), t("error.hostname_duplicate"));
    return false;
  }
  if (state.sshKeys.some((entry) => entry.source === "manual" && entry.valid === false)) {
    showToast(t("dialog.attention"), t("error.ssh_invalid"));
    return false;
  }
  if (state.installSshServer && state.disablePasswordAuth && selectedSshKeys().length === 0) {
    showToast(t("dialog.attention"), t("error.ssh_key_required"));
    return false;
  }
  await persistState();
  return true;
}

async function validateCurrentStep() {
  const id = currentStepId();
  if (id === "network") {
    if (!state.online) {
      showToast(t("dialog.attention"), t("network.need_online"));
      return false;
    }
  } else if (id === "mode") {
    if (!['simple', 'multiboot'].includes(state.mode)) return false;
    await api("/api/state", { method: "POST", body: { mode: state.mode } });
  } else if (id === "distros") {
    if (!state.selected.length) {
      showToast(t("dialog.attention"), t("error.no_distro"));
      return false;
    }
    if (state.mode === "simple" && state.selected.length !== 1) {
      showToast(t("dialog.attention"), t("distros.select_one"));
      return false;
    }
    ensureSelectionDefaults();
    await persistState();
  } else if (id === "sources") {
    if (!sourcesAreReady()) {
      showToast(t("dialog.attention"), t("error.sources_unavailable"));
      return false;
    }
    await persistState();
  } else if (id === "settings") {
    return validateSettings();
  } else if (id === "storage") {
    if (!state.diskId || !state.disks.length) {
      showToast(t("dialog.attention"), t("error.no_disk"));
      return false;
    }
    try {
      await loadPreview();
    } catch (error) {
      showToast(t("dialog.attention"), String(error?.message || error));
      return false;
    }
    if (state.preview?.error || !state.preview?.partitions?.length || !state.planFingerprint) {
      showToast(t("dialog.attention"), t("error.plan_invalid"));
      return false;
    }
    state.reviewAcknowledged = false;
    state.acknowledgedFingerprint = "";
  } else if (id === "install") {
    if (!installIsVerifiedComplete()) {
      showToast(t("dialog.attention"), t("progress.running"));
      return false;
    }
  }
  return true;
}

async function confirmAndStartInstall() {
  if (!state.reviewAcknowledged || state.acknowledgedFingerprint !== state.planFingerprint) {
    showToast(t("dialog.attention"), t("error.destructive_unconfirmed"));
    return;
  }
  if (!state.diskId || !state.planFingerprint || state.preview?.error) {
    showToast(t("dialog.attention"), t("error.plan_invalid"));
    return;
  }
  setBusy(true);
  try {
    const confirmation = await api("/api/install/confirm", {
      method: "POST",
      body: {
        disk_id: state.diskId,
        plan_fingerprint: state.planFingerprint,
        acknowledged: true,
      },
    });
    const token = String(confirmation?.confirmation_token || "");
    if (!token) throw new Error(t("error.confirmation_missing"));
    const started = await api("/api/install/start", {
      method: "POST",
      body: { confirmation_token: token },
    });
    state.install = started?.job && typeof started.job === "object" ? started.job : started;
    if (!state.install || typeof state.install !== "object") state.install = { status: "queued", percent: 0 };
    state.password = "";
    state.passwordConfirm = "";
    if (!state.install.status) state.install.status = "queued";
    state.installStarted = true;
    state.step = STEPS.findIndex((step) => step.id === "install");
    await render();
  } catch (error) {
    showToast(t("dialog.attention"), String(error?.message || error));
  } finally {
    setBusy(false);
  }
}

function hydrateWizard(data) {
  if (!data || typeof data !== "object") return;
  if (['simple', 'multiboot'].includes(data.mode)) state.mode = data.mode;
  if (Array.isArray(data.selected)) state.selected = data.selected.filter((item) => item?.id).map((item) => ({ id: String(item.id), variant: String(item.variant || "standard"), display_name: String(item.display_name || item.id) }));
  if (typeof data.username === "string") state.username = data.username;
  if (typeof data.timezone === "string") state.timezone = data.timezone;
  if (typeof data.keyboard === "string") state.keyboard = data.keyboard;
  if (typeof data.theme === "string") state.theme = data.theme;
  if (typeof data.disk_id === "string") state.diskId = data.disk_id;
  if (data.hostnames && typeof data.hostnames === "object") state.hostnames = { ...data.hostnames };
  if (data.root_sizes_mib && typeof data.root_sizes_mib === "object") state.rootSizesMib = { ...data.root_sizes_mib };
  if (typeof data.install_ssh_server === "boolean") state.installSshServer = data.install_ssh_server;
  if (typeof data.disable_password_auth === "boolean") state.disablePasswordAuth = data.disable_password_auth;
  if (!state.installSshServer) state.disablePasswordAuth = false;
  if (typeof data.boot_timeout_seconds === "number") state.bootTimeoutSeconds = data.boot_timeout_seconds;
  if (typeof data.boot_default === "string") state.bootDefault = data.boot_default;
  if (['equal', 'individual'].includes(data.partition_strategy)) state.partitionStrategy = data.partition_strategy;
  if (typeof data.include_swap === "boolean") state.includeSwap = data.include_swap;
  if (typeof data.swap_size_mib === "number") state.swapSizeMib = data.swap_size_mib;
  if (typeof data.include_data === "boolean") state.includeData = data.include_data;
  if (typeof data.data_size_mib === "number") state.dataSizeMib = data.data_size_mib;
  if (Array.isArray(data.ssh_keys)) state.sshKeys = data.ssh_keys.filter((key) => typeof key === "string").map((key) => ({ key, fingerprint: "", source: "saved", selected: true, valid: true, pending: true }));
  ensureSelectionDefaults();
}

async function resetSimulation() {
  clearInstallTimer();
  state.step = 0;
  state.install = null;
  state.installStarted = false;
  state.reviewAcknowledged = false;
  state.acknowledgedFingerprint = "";
  state.planFingerprint = "";
  await render();
}

async function init() {
  const language = document.getElementById("langSelect");
  language.value = state.lang;
  try {
    state.i18n = await api(`/api/i18n/${state.lang}`);
  } catch (_) {
    state.i18n = {};
  }

  const [wizardResult, healthResult] = await Promise.allSettled([api("/api/state"), api("/api/health")]);
  if (wizardResult.status === "fulfilled") hydrateWizard(wizardResult.value);
  if (healthResult.status === "fulfilled" && healthResult.value && typeof healthResult.value === "object") {
    state.health = healthResult.value;
    state.csrfToken = String(healthResult.value.csrf_token || "");
  }

  language.addEventListener("change", async () => {
    captureSettingsForm();
    const nextLanguage = language.value;
    try {
      const translations = await api(`/api/i18n/${nextLanguage}`);
      state.lang = nextLanguage;
      state.i18n = translations;
      await api("/api/language", { method: "POST", body: { language: nextLanguage } }).catch(() => {});
      await render();
    } catch (error) {
      language.value = state.lang;
      showToast(t("dialog.attention"), String(error?.message || error));
    }
  });

  document.getElementById("btnBack").addEventListener("click", async () => {
    if (state.busy || state.step <= 0) return;
    captureSettingsForm();
    if (currentStepId() === "review" || currentStepId() === "install") {
      state.reviewAcknowledged = false;
      state.acknowledgedFingerprint = "";
    }
    state.step -= 1;
    await render();
  });

  document.getElementById("btnNext").addEventListener("click", async () => {
    if (state.busy) return;
    const id = currentStepId();
    if (id === "review") {
      await confirmAndStartInstall();
      return;
    }
    if (id === "done") {
      if (installIsSimulated()) {
        await resetSimulation();
      } else {
        try {
          await api("/api/system/reboot", { method: "POST" });
          showToast(t("done.reboot"), t("done.reboot_wait"));
        } catch (error) {
          showToast(t("dialog.attention"), String(error?.message || error));
        }
      }
      return;
    }
    setBusy(true);
    try {
      if (!(await validateCurrentStep())) return;
      if (state.step < STEPS.length - 1) {
        state.step += 1;
        await render();
      }
    } catch (error) {
      showToast(t("dialog.attention"), String(error?.message || error));
    } finally {
      setBusy(false);
    }
  });

  state.networkChecking = true;
  await render();
  checkNetwork(false);

  if (state.sshKeys.length) {
    Promise.all(state.sshKeys.map(async (entry) => {
      entry.fingerprint = await fingerprintSshKey(entry.key);
      entry.pending = false;
      entry.valid = Boolean(entry.fingerprint);
      return entry;
    })).catch(() => {});
  }
}

init();
