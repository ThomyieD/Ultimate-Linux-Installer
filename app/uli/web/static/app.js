const state = {
  lang: "de",
  i18n: {},
  step: 0,
  online: false,
  hasWifi: false,
  ethernet: null,
  devices: [],
  mode: "simple",
  selected: [],
  diskId: "",
  disks: [],
  partitions: [],
  password: "",
  install: null,
  installTimer: null,
  wifiSsid: "",
  hiddenSsid: false,
  busy: false,
};

let renderSeq = 0;

const STEPS = [
  { id: "network", labelKey: "step.network" },
  { id: "mode", labelKey: "step.mode" },
  { id: "distros", labelKey: "step.distros" },
  { id: "settings", labelKey: "step.settings" },
  { id: "storage", labelKey: "step.storage" },
  { id: "install", labelKey: "step.progress" },
  { id: "done", labelKey: "step.done" },
];

const FAMILY_KEYS = {
  debian: "distros.family.debian",
  redhat: "distros.family.redhat",
  arch: "distros.family.arch",
  special: "distros.family.special",
};

function t(key, vars = {}) {
  let s = state.i18n[key] || key;
  for (const [k, v] of Object.entries(vars)) {
    s = s.replaceAll(`{${k}}`, String(v));
  }
  return s;
}

async function api(path, opts = {}) {
  const init = {
    method: opts.method || "GET",
    headers: { ...(opts.headers || {}) },
  };
  if (opts.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = typeof opts.body === "string" ? opts.body : JSON.stringify(opts.body);
  }
  const res = await fetch(path, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return res.json();
  return res.text();
}

function showToast(title, body) {
  const el = document.getElementById("toast");
  document.getElementById("toastTitle").textContent = title;
  document.getElementById("toastBody").textContent = body;
  el.classList.add("show");
  clearTimeout(showToast._timer);
  showToast._timer = setTimeout(() => el.classList.remove("show"), 4200);
}

function signalLevel(signal) {
  if (signal >= 75) return 4;
  if (signal >= 50) return 3;
  if (signal >= 25) return 2;
  return 1;
}

function renderSteps() {
  const list = document.getElementById("stepList");
  list.innerHTML = STEPS.map((s, i) => {
    const cls = i === state.step ? "active" : i < state.step ? "done" : "";
    return `<li class="${cls}"><span class="n">${String(i + 1).padStart(2, "0")}</span>${t(s.labelKey)}</li>`;
  }).join("");
}

function setBusy(busy) {
  state.busy = busy;
  paintChrome();
}

function paintChrome() {
  document.documentElement.lang = state.lang;
  document.getElementById("appTitle").textContent = t("app.title");
  document.getElementById("appSub").textContent = t("app.subtitle");
  document.getElementById("railTitle").textContent = t("app.title");
  document.getElementById("btnBack").textContent = t("nav.back");
  document.getElementById("btnNext").textContent =
    state.step === STEPS.length - 1
      ? t("done.reboot")
      : STEPS[state.step].id === "storage"
        ? t("nav.install")
        : t("nav.next");
  const back = document.getElementById("btnBack");
  const onInstall = STEPS[state.step].id === "install";
  back.disabled = state.busy || state.step === 0 || (onInstall && state.install?.status === "running");
  document.getElementById("btnNext").disabled =
    state.busy ||
    (onInstall && state.install?.status !== "done");
  if (onInstall && state.install?.status === "error") {
    document.getElementById("btnNext").disabled = true;
  }
  renderSteps();
}

async function render() {
  const seq = ++renderSeq;
  paintChrome();

  const id = STEPS[state.step].id;
  const main = document.getElementById("main");
  let html = "";
  try {
    if (id === "network") html = await viewNetwork();
    else if (id === "mode") html = viewMode();
    else if (id === "distros") html = await viewDistros();
    else if (id === "settings") html = viewSettings();
    else if (id === "storage") html = await viewStorage();
    else if (id === "install") html = await viewInstall();
    else html = viewDone();
  } catch (err) {
    html = `
      <div class="eyebrow">${t(STEPS[state.step].labelKey)}</div>
      <h3>${t("dialog.attention")}</h3>
      <p class="lead">${String(err.message || err)}</p>
      <div class="panel"><div class="hint">${t("network.retry")}</div></div>`;
  }
  if (seq !== renderSeq) return;
  main.innerHTML = html;
  bindView(id);
}

async function viewNetwork() {
  const ethHint =
    state.ethernet === true
      ? t("network.guide_lan_up")
      : t("network.guide_lan");
  const wifiHint = state.hasWifi ? t("network.guide_wifi") : t("network.guide_no_wifi");
  const statusClass = state.online ? "online" : "offline";
  const statusText = state.online ? t("network.ok") : t("network.fail");
  const deviceLines = (state.devices || [])
    .filter((d) => d.type === "ethernet" || d.type === "wifi")
    .map((d) => `${d.name} · ${d.type} · ${d.state}`)
    .join("<br/>");

  return `
    <div class="eyebrow">${t("step.network")}</div>
    <h3>${t("network.title")}</h3>
    <p class="lead">${t("network.lead")}</p>
    <div class="panel">
      <div class="status ${statusClass}" id="netStatus"><span class="pulse"></span> ${statusText}</div>
      <div class="hint" id="netHint">
        ${t("network.guide_intro")}<br/>${ethHint}<br/>${wifiHint}
      </div>
      ${
        deviceLines
          ? `<div class="hint"><strong>${t("network.devices")}</strong><br/>${deviceLines}</div>`
          : ""
      }
      <div class="row" id="lanActions">
        <button class="btn primary" type="button" id="btnEthUp">${t("network.ethernet_up")}</button>
        <button class="btn ghost" type="button" id="btnRecheck2">${t("network.retry")}</button>
      </div>
      <div id="wifiBlock" class="${state.hasWifi && !state.online ? "" : "hidden"}">
        <div class="wifi-list" id="wifiList"></div>
        <div class="field">
          <label>${t("network.password")}</label>
          <input type="password" id="wifiPassword" autocomplete="off" />
        </div>
        <label class="check">
          <input type="checkbox" id="hiddenToggle" ${state.hiddenSsid ? "checked" : ""} />
          ${t("network.hidden")}
        </label>
        <div class="field ${state.hiddenSsid ? "" : "hidden"}" id="hiddenField">
          <label>${t("network.hidden_ssid")}</label>
          <input type="text" id="hiddenSsid" />
        </div>
        <div class="row">
          <button class="btn primary" type="button" id="btnConnect">${t("network.connect")}</button>
          <button class="btn ghost" type="button" id="btnScan">${t("network.scan")}</button>
          <button class="btn ghost" type="button" id="btnRecheck">${t("network.retry")}</button>
        </div>
        <div class="hint hidden" id="netAction"></div>
      </div>
      <div class="hint hidden" id="netActionLan"></div>
    </div>
  `;
}

function viewMode() {
  const modes = [
    ["simple", "mode.simple", "mode.simple.desc"],
    ["multiboot", "mode.multi", "mode.multi.desc"],
    ["add", "mode.add", "mode.add.desc"],
    ["remove", "mode.remove", "mode.remove.desc"],
  ];
  return `
    <div class="eyebrow">${t("step.mode")}</div>
    <h3>${t("mode.title")}</h3>
    <p class="lead">${t("mode.lead")}</p>
    <div class="modes panel">
      ${modes
        .map(
          ([id, title, desc]) => `
        <button type="button" class="mode ${state.mode === id ? "selected" : ""}" data-mode="${id}">
          <h4>${t(title)}</h4>
          <p>${t(desc)}</p>
        </button>`
        )
        .join("")}
    </div>
  `;
}

async function viewDistros() {
  const data = await api(`/api/catalog?mode=${encodeURIComponent(state.mode)}`);
  const groups = {};
  for (const item of data.items || []) {
    (groups[item.family] ||= []).push(item);
  }
  const multi = state.mode !== "simple";
  const selected = new Set(state.selected.map((s) => `${s.id}:${s.variant}`));
  let html = `
    <div class="eyebrow">${t("step.distros")}</div>
    <h3>${state.mode === "simple" ? t("distros.simple") : t("distros.multi")}</h3>
    <p class="lead">${multi ? t("distros.select_multi") : t("distros.select_one")}</p>
    <div class="panel">
  `;
  if (!Object.keys(groups).length) {
    html += `<div class="hint">${t("dialog.attention")}: catalog empty</div>`;
  }
  for (const [family, items] of Object.entries(groups)) {
    html += `<div class="distro-group"><h4>${t(FAMILY_KEYS[family] || family)}</h4>`;
    for (const item of items) {
      const key = `${item.id}:${item.variant}`;
      const on = selected.has(key);
      html += `
        <label class="chip ${on ? "selected" : ""}">
          <input type="${multi ? "checkbox" : "radio"}" name="distro" value="${key}"
            data-id="${item.id}" data-variant="${item.variant}" data-name="${item.display_name}"
            ${on ? "checked" : ""} />
          <span>${item.display_name}</span>
        </label>`;
    }
    html += `</div>`;
  }
  html += `</div>`;
  return html;
}

function viewSettings() {
  return `
    <div class="eyebrow">${t("step.settings")}</div>
    <h3>${t("settings.title")}</h3>
    <p class="lead">${t("mode.lead")}</p>
    <div class="panel">
      <div class="field">
        <label>${t("settings.username")}</label>
        <input type="text" id="username" value="${state.username || ""}" />
      </div>
      <div class="field">
        <label>${t("settings.password")}</label>
        <input type="password" id="password" />
      </div>
      <div class="field">
        <label>${t("settings.password_confirm")}</label>
        <input type="password" id="password2" />
      </div>
    </div>
  `;
}

async function viewStorage() {
  try {
    await api("/api/state", {
      method: "POST",
      body: { selected: state.selected, mode: state.mode },
    });
  } catch (_) {
    /* continue with local state */
  }
  const data = await api("/api/disks");
  state.disks = data.items || [];
  if (!state.diskId && state.disks.length) {
    state.diskId = state.disks[0].id;
  }
  let preview = { partitions: [], warnings: [] };
  if (state.diskId) {
    try {
      preview = await api(`/api/storage/preview?disk_id=${encodeURIComponent(state.diskId)}`);
    } catch (err) {
      preview = { partitions: [], warnings: [], error: String(err.message || err) };
    }
    state.partitions = preview.partitions || [];
  } else {
    state.partitions = [];
  }

  const diskButtons = state.disks.length
    ? state.disks
        .map((d) => {
          const selected = d.id === state.diskId ? "selected" : "";
          const model = d.model || d.path;
          return `
            <button type="button" class="disk ${selected}" data-disk="${d.id.replaceAll('"', "&quot;")}">
              <div>
                <strong>${model}</strong>
                <small>${d.path} · ${d.transport || "disk"}</small>
              </div>
              <span class="gib">${d.size_gib} GiB</span>
            </button>`;
        })
        .join("")
    : `<div class="hint">${t("error.no_disk")}</div>`;

  const warnHints = [];
  if (preview.error) {
    warnHints.push(`<div class="hint">${t("storage.disk_error", { error: preview.error })}</div>`);
  } else if ((preview.warnings || []).some((w) => String(w).startsWith("below_minimum"))) {
    warnHints.push(`<div class="hint">${t("storage.too_small")}</div>`);
  }

  const partLines = (state.partitions || [])
    .map((p) => {
      const gib = (p.size_mib / 1024).toFixed(p.size_mib >= 1024 ? 1 : 2);
      if (p.role === "root") {
        return `<li>${t("storage.root", { name: p.label || p.distribution || "root" })} — ${gib} GiB</li>`;
      }
      if (p.role === "esp") return `<li>${t("storage.esp")} — ${p.size_mib} MiB</li>`;
      if (p.role === "swap") return `<li>${t("storage.swap")} — ${gib} GiB</li>`;
      return `<li>${t("storage.data")} — ${gib} GiB</li>`;
    })
    .join("");

  return `
    <div class="eyebrow">${t("step.storage")}</div>
    <h3>${t("storage.title")}</h3>
    <p class="lead">${t("storage.warning")}</p>
    <div class="panel">
      <div class="hint">${t("storage.usb_excluded")}</div>
      ${warnHints.join("")}
      <div class="field">
        <label>${t("storage.disk")}</label>
        <div class="disk-list" id="diskList">${diskButtons}</div>
      </div>
      <div class="field">
        <label>${t("storage.summary")}</label>
        <ul class="part-list" id="partList">${partLines || `<li class="muted">${t("storage.select_disk")}</li>`}</ul>
      </div>
    </div>
  `;
}

function viewDone() {
  const job = state.install || {};
  return `
    <div class="eyebrow">${t("step.done")}</div>
    <h3>${t("done.title")}</h3>
    <p class="lead">${t("done.body")}</p>
    <div class="panel">
      <div class="status online"><span class="pulse"></span> ${t("progress.done_phase")}</div>
      ${
        job.artifact_dir
          ? `<div class="hint"><strong>${t("done.artifacts")}</strong><br/>${job.artifact_dir}</div>`
          : ""
      }
    </div>
  `;
}

async function viewInstall() {
  if (!state.install || state.install.status === "idle") {
    try {
      state.install = await api("/api/install/start", { method: "POST" });
    } catch (err) {
      state.install = { status: "error", error: String(err.message || err), percent: 0, downloads: [] };
    }
  } else {
    try {
      state.install = await api("/api/install/status");
    } catch (_) {
      /* keep last */
    }
  }
  const job = state.install || { status: "running", percent: 0, downloads: [] };
  const phaseKey = {
    prepare: "progress.prepare",
    download: "progress.download",
    artifacts: "progress.artifacts",
    partition: "progress.partition",
    bootloader: "progress.bootloader",
    done: "progress.done_phase",
  }[job.phase] || "progress.running";

  const downloads = (job.downloads || [])
    .map(
      (d) => `
      <div class="dl-row">
        <div>
          <strong>${d.name}</strong>
          <small>${d.status || ""} ${d.percent || 0}%</small>
        </div>
        <div class="bar"><i style="width:${d.percent || 0}%"></i></div>
      </div>`
    )
    .join("");

  return `
    <div class="eyebrow">${t("step.progress")}</div>
    <h3>${t("progress.title")}</h3>
    <p class="lead">${t("progress.lead")}</p>
    <div class="panel">
      <div class="status ${job.status === "error" ? "offline" : job.status === "done" ? "online" : "busy"}">
        <span class="pulse"></span>
        ${job.status === "error" ? t("progress.failed") : t(phaseKey)}
      </div>
      <div class="bar big"><i style="width:${job.percent || 0}%"></i></div>
      <div class="hint">${job.message || t("progress.running")}</div>
      ${job.error ? `<div class="hint">${job.error}</div>` : ""}
      <div class="dl-list">${downloads}</div>
      ${
        job.status === "error"
          ? `<button type="button" class="btn ghost" id="btnInstallRetry">${t("progress.retry")}</button>`
          : ""
      }
    </div>
  `;
}

function bindView(id) {
  if (id === "network") bindNetwork();
  if (id === "mode") {
    document.querySelectorAll(".mode").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.mode = btn.dataset.mode;
        state.selected = [];
        document.querySelectorAll(".mode").forEach((b) => {
          b.classList.toggle("selected", b.dataset.mode === state.mode);
        });
        api("/api/state", {
          method: "POST",
          body: { mode: state.mode, selected: [] },
        }).catch(() => {});
      });
    });
  }
  if (id === "distros") {
    document.querySelectorAll(".chip input").forEach((input) => {
      input.addEventListener("change", () => {
        const multi = state.mode !== "simple";
        if (!multi) {
          state.selected = [
            {
              id: input.dataset.id,
              variant: input.dataset.variant,
              display_name: input.dataset.name,
            },
          ];
        } else {
          state.selected = [...document.querySelectorAll(".chip input:checked")].map((el) => ({
            id: el.dataset.id,
            variant: el.dataset.variant,
            display_name: el.dataset.name,
          }));
        }
        document.querySelectorAll(".chip").forEach((chip) => {
          const inp = chip.querySelector("input");
          chip.classList.toggle("selected", !!inp?.checked);
        });
        api("/api/state", {
          method: "POST",
          body: { selected: state.selected, mode: state.mode },
        }).catch(() => {});
      });
    });
  }
  if (id === "storage") {
    document.querySelectorAll(".disk").forEach((btn) => {
      btn.addEventListener("click", async () => {
        state.diskId = btn.dataset.disk;
        document.querySelectorAll(".disk").forEach((b) => {
          b.classList.toggle("selected", b.dataset.disk === state.diskId);
        });
        try {
          const preview = await api(
            `/api/storage/preview?disk_id=${encodeURIComponent(state.diskId)}`
          );
          state.partitions = preview.partitions || [];
          const list = document.getElementById("partList");
          if (list) {
            list.innerHTML = (state.partitions || [])
              .map((p) => {
                const gib = (p.size_mib / 1024).toFixed(p.size_mib >= 1024 ? 1 : 2);
                if (p.role === "root") {
                  return `<li>${t("storage.root", { name: p.label || p.distribution || "root" })} — ${gib} GiB</li>`;
                }
                if (p.role === "esp") return `<li>${t("storage.esp")} — ${p.size_mib} MiB</li>`;
                if (p.role === "swap") return `<li>${t("storage.swap")} — ${gib} GiB</li>`;
                return `<li>${t("storage.data")} — ${gib} GiB</li>`;
              })
              .join("");
          }
          await api("/api/state", {
            method: "POST",
            body: {
              disk_id: preview.disk?.id || state.diskId,
              disk_path: preview.disk?.path || "",
              disk_size_bytes: Math.round((preview.disk?.size_gib || 0) * 1024 ** 3),
              selected: state.selected,
              mode: state.mode,
            },
          });
        } catch (err) {
          showToast(t("dialog.attention"), String(err.message || err));
        }
      });
    });
  }
  if (id === "install") {
    document.getElementById("btnInstallRetry")?.addEventListener("click", async () => {
      state.install = null;
      try {
        state.install = await api("/api/install/start", { method: "POST" });
      } catch (err) {
        state.install = { status: "error", error: String(err.message || err) };
      }
      await render();
    });
    if (state.installTimer) clearInterval(state.installTimer);
    if (state.install?.status === "running") {
      state.installTimer = setInterval(async () => {
        if (STEPS[state.step].id !== "install") {
          clearInterval(state.installTimer);
          state.installTimer = null;
          return;
        }
        try {
          state.install = await api("/api/install/status");
          paintChrome();
          const bar = document.querySelector(".bar.big > i");
          if (bar) bar.style.width = `${state.install.percent || 0}%`;
          const statusEl = document.querySelector("#main .status");
          const hint = document.querySelector("#main .hint");
          if (hint && state.install.message) hint.textContent = state.install.message;
          if (state.install.status === "done" || state.install.status === "error") {
            clearInterval(state.installTimer);
            state.installTimer = null;
            await render();
          }
        } catch (_) {
          /* ignore transient */
        }
      }, 1000);
    }
  }
}

async function bindNetwork() {
  const setAction = (text, show = true) => {
    const el = document.getElementById("netAction");
    if (!el) return;
    el.textContent = text || "";
    el.classList.toggle("hidden", !show || !text);
  };

  const paintWifi = (networks) => {
    const list = document.getElementById("wifiList");
    if (!list) return;
    if (!networks.length) {
      list.innerHTML = `<div class="hint">${t("network.scan_empty")}</div>`;
      return;
    }
    list.innerHTML = networks
      .map((n) => {
        const selected = n.ssid === state.wifiSsid ? "selected" : "";
        const level = signalLevel(n.signal || 0);
        return `
          <button type="button" class="wifi ${selected}" data-ssid="${n.ssid.replaceAll('"', "&quot;")}">
            <div>
              <strong>${n.ssid}</strong>
              <small>${n.security || "WLAN"} · ${n.signal || 0}%</small>
            </div>
            <div class="bars" data-level="${level}" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
          </button>`;
      })
      .join("");
    list.querySelectorAll(".wifi").forEach((btn) => {
      btn.addEventListener("click", () => {
        state.wifiSsid = btn.dataset.ssid;
        list.querySelectorAll(".wifi").forEach((b) => b.classList.toggle("selected", b === btn));
      });
    });
  };

  const applyStatus = (data) => {
    state.online = !!data.online;
    state.hasWifi = !!data.has_wifi;
    state.ethernet = data.ethernet;
    state.devices = data.devices || [];
  };

  const refreshStatus = async () => {
    setBusy(true);
    setAction(t("network.checking"));
    try {
      const data = await api("/api/network/check", { method: "POST" });
      applyStatus(data);
      await render();
      if (!data.online && data.has_wifi) {
        await scanWifi();
      }
    } catch (err) {
      showToast(t("dialog.attention"), String(err.message || err));
    } finally {
      setBusy(false);
    }
  };

  const ethernetUp = async () => {
    setBusy(true);
    const lanAction = document.getElementById("netActionLan");
    if (lanAction) {
      lanAction.textContent = t("network.ethernet_wait");
      lanAction.classList.remove("hidden");
    }
    try {
      const data = await api("/api/network/ethernet/up", { method: "POST" });
      applyStatus(data);
      await render();
    } catch (err) {
      showToast(t("dialog.attention"), String(err.message || err));
    } finally {
      setBusy(false);
    }
  };

  const scanWifi = async () => {
    setBusy(true);
    setAction(t("network.scanning"));
    try {
      const data = await api("/api/network/wifi?rescan=true");
      state.hasWifi = data.has_wifi;
      if (!data.has_wifi) {
        setAction(t("network.guide_no_wifi"));
        return;
      }
      paintWifi(data.networks || []);
      setAction(data.networks?.length ? "" : t("network.scan_empty"));
    } catch (err) {
      setAction(String(err.message || err));
      showToast(t("dialog.attention"), String(err.message || err));
    } finally {
      setBusy(false);
    }
  };

  document.getElementById("btnScan")?.addEventListener("click", scanWifi);
  document.getElementById("btnRecheck")?.addEventListener("click", refreshStatus);
  document.getElementById("btnRecheck2")?.addEventListener("click", refreshStatus);
  document.getElementById("btnEthUp")?.addEventListener("click", ethernetUp);
  document.getElementById("hiddenToggle")?.addEventListener("change", (e) => {
    state.hiddenSsid = e.target.checked;
    document.getElementById("hiddenField")?.classList.toggle("hidden", !e.target.checked);
  });
  document.getElementById("btnConnect")?.addEventListener("click", async () => {
    const ssid = state.hiddenSsid
      ? document.getElementById("hiddenSsid")?.value.trim()
      : state.wifiSsid;
    const password = document.getElementById("wifiPassword")?.value || "";
    if (!ssid) {
      showToast(t("dialog.attention"), t("network.need_ssid"));
      return;
    }
    setBusy(true);
    setAction(t("network.connecting", { ssid }));
    try {
      const data = await api("/api/network/wifi/connect", {
        method: "POST",
        body: { ssid, password },
      });
      if (!data.ok) {
        setAction(t("network.connect_fail") + (data.error ? `\n${data.error}` : ""));
        showToast(t("dialog.attention"), t("network.connect_fail"));
        return;
      }
      state.online = data.online;
      setAction(t("network.connect_ok"));
      await render();
    } catch (err) {
      showToast(t("dialog.attention"), String(err.message || err));
    } finally {
      setBusy(false);
    }
  });

  if (!state.online && state.hasWifi) {
    scanWifi();
  }
}

async function validateStep() {
  const id = STEPS[state.step].id;
  if (id === "network" && !state.online) {
    showToast(t("dialog.attention"), t("network.need_online"));
    return false;
  }
  if (id === "distros" && !state.selected.length) {
    showToast(t("dialog.attention"), t("error.no_distro"));
    return false;
  }
  if (id === "storage") {
    if (!state.diskId || !state.disks.length) {
      showToast(t("dialog.attention"), t("error.no_disk"));
      return false;
    }
    // Persist disk choice before install
    const disk = state.disks.find((d) => d.id === state.diskId) || state.disks[0];
    try {
      await api("/api/state", {
        method: "POST",
        body: {
          disk_id: disk.id,
          disk_path: disk.path,
          disk_size_bytes: disk.size_bytes,
          selected: state.selected,
          mode: state.mode,
          username: state.username,
          password: state.password || "",
        },
      });
    } catch (_) {
      /* continue */
    }
  }
  if (id === "install") {
    if (state.install?.status !== "done") {
      showToast(t("dialog.attention"), t("progress.running"));
      return false;
    }
  }
  if (id === "settings") {
    const username = document.getElementById("username")?.value.trim() || "";
    const p1 = document.getElementById("password")?.value || "";
    const p2 = document.getElementById("password2")?.value || "";
    if (!username) {
      showToast(t("dialog.attention"), t("error.username_required"));
      return false;
    }
    if (p1 !== p2) {
      showToast(t("dialog.attention"), t("error.password_mismatch"));
      return false;
    }
    state.username = username;
    state.password = p1;
    try {
      await api("/api/state", {
        method: "POST",
        body: {
          username,
          password: p1,
          selected: state.selected,
          mode: state.mode,
        },
      });
    } catch (_) {
      /* local state is enough to continue */
    }
  }
  return true;
}

async function init() {
  const langSelect = document.getElementById("langSelect");
  langSelect.value = state.lang;
  state.i18n = await api(`/api/i18n/${state.lang}`);

  langSelect.addEventListener("change", async () => {
    const next = langSelect.value;
    state.lang = next;
    try {
      state.i18n = await api(`/api/i18n/${next}`);
    } catch (err) {
      showToast(t("dialog.attention"), String(err.message || err));
      return;
    }
    api("/api/language", {
      method: "POST",
      body: { language: next },
    }).catch(() => {});
    await render();
  });

  document.getElementById("btnBack").addEventListener("click", async () => {
    if (state.step > 0) {
      state.step -= 1;
      await render();
    }
  });
  document.getElementById("btnNext").addEventListener("click", async () => {
    const id = STEPS[state.step].id;
    if (id === "done") {
      try {
        await api("/api/system/reboot", { method: "POST" });
        showToast(t("done.reboot"), "…");
      } catch (err) {
        showToast(t("dialog.attention"), String(err.message || err));
      }
      return;
    }
    if (!(await validateStep())) return;
    if (state.step < STEPS.length - 1) {
      state.step += 1;
      await render();
    }
  });

  try {
    const status = await api("/api/network/check", { method: "POST" });
    state.online = !!status.online;
    state.hasWifi = !!status.has_wifi;
    state.ethernet = status.ethernet;
    state.devices = status.devices || [];
  } catch (_) {
    try {
      const status = await api("/api/network/status");
      state.online = status.online;
      state.hasWifi = status.has_wifi;
      state.ethernet = status.ethernet;
    } catch (_) {
      /* first paint */
    }
  }
  await render();
}

init();
