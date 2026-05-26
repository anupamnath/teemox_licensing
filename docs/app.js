/**
 * Teemox License Admin Portal — app.js
 *
 * All GitHub API calls use the PAT stored only in sessionStorage.
 * Nothing is sent to any third-party server.
 */

"use strict";

// ── Config (edit to match your repo) ─────────────────────────────────────────
const OWNER = "anupamnath";
const REPO  = "teemox_licensing";
const BRANCH = "main";

const APP_LABELS = {
  TEEMOX_MAILER:  { label: "Teemox Mailer",   badgeClass: "badge-tmx" },
  INFOMANIAK_API: { label: "Infomaniak API",   badgeClass: "badge-inf" },
  SHOPIFY_API:    { label: "Shopify API",      badgeClass: "badge-sho" },
};

// ── State ─────────────────────────────────────────────────────────────────────
let token = sessionStorage.getItem("gh_token") || "";
let machineCount = 1;

// ── GitHub API helper ─────────────────────────────────────────────────────────
async function api(endpoint, method = "GET", body = null) {
  const resp = await fetch(`https://api.github.com${endpoint}`, {
    method,
    headers: {
      Authorization: `token ${token}`,
      Accept: "application/vnd.github.v3+json",
      "Content-Type": "application/json",
      "X-GitHub-Api-Version": "2022-11-28",
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (resp.status === 204) return null;   // No Content
  if (resp.status === 404) return null;   // Not found

  const data = await resp.json().catch(() => null);
  if (!resp.ok) {
    const extra = data?.errors?.map(e => e.message || JSON.stringify(e)).join("; ");
    const msg   = data?.message || "GitHub API error";
    throw new Error(extra ? `${msg}: ${extra} (HTTP ${resp.status})` : `${msg} (HTTP ${resp.status})`);
  }
  return data;
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

// ── Auth ──────────────────────────────────────────────────────────────────────
async function login() {
  token = document.getElementById("tokenInput").value.trim();
  if (!token) return showAlert("loginAlert", "Please enter a GitHub Personal Access Token.", "warn");

  showAlert("loginAlert", '<span class="spinner"></span> Verifying token…', "info");
  try {
    // Use raw fetch so we can inspect the X-OAuth-Scopes response header
    const rawResp = await fetch("https://api.github.com/user", {
      headers: {
        Authorization: `token ${token}`,
        Accept: "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
    });
    if (!rawResp.ok) {
      const d = await rawResp.json().catch(() => null);
      throw new Error(d?.message || `HTTP ${rawResp.status}`);
    }
    const user = await rawResp.json();

    // Classic PATs return X-OAuth-Scopes; fine-grained PATs do not.
    const scopeHeader = rawResp.headers.get("X-OAuth-Scopes") || "";
    const scopes = scopeHeader.split(",").map(s => s.trim()).filter(Boolean);
    if (scopes.length > 0) {
      const missing = [];
      if (!scopes.includes("repo"))     missing.push("<code>repo</code>");
      if (!scopes.includes("workflow")) missing.push("<code>workflow</code>");
      if (missing.length > 0) {
        showAlert("loginAlert",
          `⚠️ Token is missing required scope(s): ${missing.join(" and ")}.<br>
          Scopes on this token: <code>${scopes.join(", ")}</code>.<br>
          Both <code>repo</code> and <code>workflow</code> scopes are required for workflow dispatch.<br>
          <a href="https://github.com/settings/tokens/new?scopes=repo,workflow&description=Teemox+License+Admin" target="_blank">Create a new token with the correct scopes ↗</a>`,
          "warn");
        return;
      }
    }

    sessionStorage.setItem("gh_token", token);
    document.getElementById("userInfo").textContent = `@${user.login}`;
    document.getElementById("loginScreen").classList.add("hidden");
    document.getElementById("appShell").classList.remove("hidden");
    loadDashboard();
  } catch (e) {
    showAlert("loginAlert", `Authentication failed: ${e.message}`, "danger");
  }
}

function logout() {
  sessionStorage.removeItem("gh_token");
  location.reload();
}

// ── Routing ───────────────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll(".tab-pane").forEach(p => p.classList.remove("active"));
  document.querySelectorAll(".sidebar nav a").forEach(a => a.classList.remove("active"));

  const pane = document.getElementById(`tab-${name}`);
  if (pane) pane.classList.add("active");

  const link = document.querySelector(`[data-tab="${name}"]`);
  if (link) link.classList.add("active");

  if (name === "dashboard") loadDashboard();
  if (name === "licenses")  loadLicenses();
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
async function loadDashboard() {
  const grid = document.getElementById("statsGrid");
  grid.innerHTML = '<p class="text-muted"><span class="spinner"></span> Loading…</p>';
  try {
    const files = await api(`/repos/${OWNER}/${REPO}/contents/licenses`) || [];
    const valid = await fetchValidLicenses();

    const counts = { total: 0, active: 0, revoked: 0, expired: 0 };
    const perApp = {};

    Object.keys(APP_LABELS).forEach(a => perApp[a] = { active: 0, revoked: 0 });

    for (const app of Object.keys(APP_LABELS)) {
      const v = valid?.[app] || { valid: [], revoked: [] };
      perApp[app].active  = v.valid.length;
      perApp[app].revoked = v.revoked.length;
      counts.active  += v.valid.length;
      counts.revoked += v.revoked.length;
    }
    counts.total = (Array.isArray(files) ? files.filter(f => f.name.endsWith(".json")).length : 0);

    grid.innerHTML = `
      <div class="stat-card"><div class="label">Total Licenses</div><div class="value">${counts.total}</div></div>
      <div class="stat-card success"><div class="label">Active</div><div class="value">${counts.active}</div></div>
      <div class="stat-card danger"><div class="label">Revoked</div><div class="value">${counts.revoked}</div></div>
      ${Object.entries(APP_LABELS).map(([app, info]) => `
        <div class="stat-card">
          <div class="label">${info.label}</div>
          <div class="value">${perApp[app].active}</div>
          <div class="sub">${perApp[app].revoked} revoked</div>
        </div>`).join("")}
    `;

    if (valid?.updated_at) {
      document.getElementById("lastSync").textContent =
        `Revocation list last updated: ${new Date(valid.updated_at).toLocaleString()}`;
    }
  } catch (e) {
    grid.innerHTML = `<div class="alert alert-danger">Failed to load dashboard: ${e.message}</div>`;
  }
}

async function fetchValidLicenses() {
  try {
    const resp = await fetch(
      `https://raw.githubusercontent.com/${OWNER}/${REPO}/${BRANCH}/public/valid_licenses.json`,
      { headers: { Authorization: `token ${token}` } }
    );
    return resp.ok ? resp.json() : null;
  } catch { return null; }
}

// ── Generate tab ──────────────────────────────────────────────────────────────
function initGenerateTab() {
  document.getElementById("licenseType").addEventListener("change", toggleLicenseType);
  toggleLicenseType();
}

// ── Expiry date/time helpers ──────────────────────────────────────────────────

function toggleNever() {
  const isNever = document.getElementById("genNever").checked;
  const wrap    = document.getElementById("expiryPickerWrap");
  const lbl     = document.getElementById("expiryToggleLabel");
  if (isNever) {
    wrap.classList.remove("open");
    lbl.textContent = "Lifetime License";
  } else {
    if (!document.getElementById("genExpiryDate").value) setQuickDate(365);
    wrap.classList.add("open");
    lbl.textContent = "Expires On";
  }
}

function setQuickDate(days) {
  const d    = new Date();
  d.setDate(d.getDate() + days);
  const yyyy = d.getFullYear();
  const mm   = String(d.getMonth() + 1).padStart(2, "0");
  const dd   = String(d.getDate()).padStart(2, "0");
  document.getElementById("genExpiryDate").value = `${yyyy}-${mm}-${dd}`;
  document.getElementById("genNever").checked = false;
  document.getElementById("expiryPickerWrap").classList.add("open");
  document.getElementById("expiryToggleLabel").textContent = "Expires On";
}

// ── License type toggle ───────────────────────────────────────────────────────

function toggleLicenseType() {
  const type     = document.getElementById("licenseType").value;
  const mSection = document.getElementById("machineSection");
  const fSection = document.getElementById("floatingSection");
  if (type === "machine") {
    mSection.classList.remove("hidden");
    fSection.classList.add("hidden");
  } else {
    mSection.classList.add("hidden");
    fSection.classList.remove("hidden");
  }
}

function addMachineRow() {
  const list = document.getElementById("machineInputs");
  const row  = document.createElement("div");
  row.className = "machine-row";
  row.innerHTML = `
    <input type="text" placeholder="16-char hex machine ID" maxlength="32" />
    <button class="btn btn-outline btn-sm" onclick="this.closest('.machine-row').remove()">✕</button>
  `;
  list.appendChild(row);
}

async function submitGenerate(e) {
  e.preventDefault();
  const btn  = document.getElementById("genBtn");
  const res  = document.getElementById("genResult");
  res.innerHTML = "";

  const app     = document.getElementById("genApp").value;
  const display = document.getElementById("genCustomer").value.trim();
  const isNever  = document.getElementById("genNever").checked;
  const expDate   = document.getElementById("genExpiryDate").value;
  const expiry    = isNever ? "never" : (expDate || "never");
  const type    = document.getElementById("licenseType").value;
  const maxMach = document.getElementById("genMaxMachines").value;
  const syncInt = document.getElementById("genSyncInterval").value || "90";
  const grace   = document.getElementById("genGrace").value || "24";
  const notes   = document.getElementById("genNotes").value.trim();

  if (!display) { res.innerHTML = alert_html("Customer name is required.", "danger"); return; }

  let machines = "*";
  if (type === "machine") {
    const ids = [...document.querySelectorAll("#machineInputs .machine-row input")]
      .map(i => i.value.trim().toLowerCase()).filter(Boolean);
    if (ids.length === 0) { res.innerHTML = alert_html("Add at least one machine ID.", "danger"); return; }
    machines = ids.join(",");
  }

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Generating…';
  res.innerHTML = alert_html('<span class="spinner"></span> Triggering GitHub Actions workflow…', "info");

  try {
    // Pre-check: confirm the workflow is enabled before attempting dispatch
    const wfInfo = await api(`/repos/${OWNER}/${REPO}/actions/workflows/generate_license.yml`);
    if (wfInfo && wfInfo.state !== "active") {
      throw new Error(
        `Workflow is disabled (state: "${wfInfo.state}"). ` +
        `Re-enable it at github.com/${OWNER}/${REPO}/actions/workflows/generate_license.yml`
      );
    }

    // Dispatch workflow
    await api(`/repos/${OWNER}/${REPO}/actions/workflows/generate_license.yml/dispatches`, "POST", {
      ref: BRANCH,
      inputs: {
        app_name:      app,
        display_name:  display,
        expiry:        expiry,
        machines:      machines,
        max_machines:  maxMach,
        sync_interval: syncInt,
        grace_hours:   grace,
        notes:         notes,
      },
    });

    res.innerHTML = alert_html('<span class="spinner"></span> Workflow dispatched. Waiting for run to start…', "info");
    await sleep(4000);

    // Find the latest run
    const runs = await api(`/repos/${OWNER}/${REPO}/actions/workflows/generate_license.yml/runs?per_page=5&branch=${BRANCH}`);
    const run  = runs?.workflow_runs?.[0];
    if (!run) throw new Error("Could not find the workflow run. Check Actions tab manually.");

    // Poll for completion
    let runData = run;
    let attempts = 0;
    while (runData.status !== "completed" && attempts < 60) {
      await sleep(4000);
      runData = await api(`/repos/${OWNER}/${REPO}/actions/runs/${run.id}`);
      attempts++;
      res.innerHTML = alert_html(
        `<span class="spinner"></span> Running… (${runData.status}) — <a href="${run.html_url}" target="_blank">View in Actions ↗</a>`,
        "info"
      );
    }

    if (runData.conclusion !== "success") {
      throw new Error(`Workflow ended with conclusion: ${runData.conclusion}. Check Actions logs.`);
    }

    res.innerHTML = alert_html('<span class="spinner"></span> Workflow succeeded. Reading license record…', "info");
    await sleep(3000);

    // Find new license file (sort by name desc to get latest)
    const files = (await api(`/repos/${OWNER}/${REPO}/contents/licenses`)) || [];
    const jsonFiles = files.filter(f => f.name.endsWith(".json")).sort((a, b) => b.name.localeCompare(a.name));
    if (!jsonFiles.length) throw new Error("License file not found after workflow.");

    const fileData  = await api(`/repos/${OWNER}/${REPO}/contents/${jsonFiles[0].path}`);
    const licMeta   = JSON.parse(atob(fileData.content.replace(/\n/g, "")));

    res.innerHTML = `
      <div class="result-card">
        <div class="result-header">
          <div class="result-icon">✅</div>
          <div>
            <div class="result-title">License Generated!</div>
            <div class="result-subtitle">Issued to <strong>${escHtml(display)}</strong></div>
          </div>
        </div>
        <div class="result-meta">
          <div class="meta-item"><span class="meta-label">License ID</span><code style="font-size:.78rem">${licMeta.id}</code></div>
          <div class="meta-item"><span class="meta-label">Expires</span><span>${licMeta.e === "never" ? "♾️ Lifetime" : licMeta.e}</span></div>
          <div class="meta-item"><span class="meta-label">Machines</span><span>${(licMeta.m||["*"]).join(", ")}</span></div>
          <div class="meta-item"><span class="meta-label">Max</span><span>${licMeta.n}</span></div>
        </div>
        <div class="key-label">🔑 License Key</div>
        <div class="key-box" id="generatedKey">${escHtml(licMeta.key)}</div>
        <div class="key-actions">
          <button class="btn btn-outline btn-sm" onclick="copyKey('generatedKey')">&#128203; Copy Key</button>
          <button class="btn btn-primary btn-sm" onclick="downloadKeyFromBox('generatedKey','${licMeta.id}','${escAttr(display)}')">&#11015;&#65039; Download .txt</button>
        </div>
        <p class="text-muted mt1" style="font-size:.8rem">⚠️ Send this key to the customer via a <strong>secure channel</strong>.</p>
      </div>
    `;
  } catch (err) {
    res.innerHTML = alert_html(`Generation failed: ${err.message}`, "danger");
  } finally {
    btn.disabled = false;
    btn.innerHTML = "🔑 Generate License";
  }
}

function downloadLicenseKey(key, id, customer) {
  const safe     = (customer || "customer").replace(/[^a-z0-9]/gi, "_");
  const shortId  = (id || "license").slice(0, 8);
  const filename = `teemox_license_${safe}_${shortId}.txt`;
  const content  = [
    "========================================",
    "  TEEMOX LICENSE KEY",
    "========================================",
    `  ID       : ${id}`,
    `  Customer : ${customer}`,
    `  Issued   : ${new Date().toISOString().slice(0, 10)}`,
    "----------------------------------------",
    "",
    key,
    "",
    "========================================",
    "  Keep this file secure.",
    "  Do NOT share publicly.",
    "========================================",
  ].join("\n");
  const blob = new Blob([content], { type: "text/plain" });
  const url  = URL.createObjectURL(blob);
  const a    = Object.assign(document.createElement("a"), { href: url, download: filename });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function downloadKeyFromBox(boxId, id, customer) {
  const key = document.getElementById(boxId).textContent.trim();
  downloadLicenseKey(key, id, customer);
}

function copyKey(elementId) {
  const box  = document.getElementById(elementId);
  const text = box.innerText.replace("Copy", "").trim();
  navigator.clipboard.writeText(text).then(() => {
    const btn = box.querySelector(".copy-btn");
    if (btn) { btn.textContent = "✓ Copied!"; setTimeout(() => (btn.textContent = "Copy"), 1800); }
  });
}

// ── Licenses tab ──────────────────────────────────────────────────────────────
let allLicenses = [];

async function loadLicenses() {
  const tbody  = document.getElementById("licensesTbody");
  const filter = document.getElementById("licFilter").value.toLowerCase();
  tbody.innerHTML = "<tr><td colspan='8' class='text-muted'><span class='spinner'></span> Loading…</td></tr>";

  try {
    const files = (await api(`/repos/${OWNER}/${REPO}/contents/licenses`)) || [];
    const jsonFiles = files.filter(f => f.name.endsWith(".json"));

    // Load all license records in parallel (batched to avoid rate limit)
    const records = [];
    const BATCH = 10;
    for (let i = 0; i < jsonFiles.length; i += BATCH) {
      const batch = jsonFiles.slice(i, i + BATCH);
      const loaded = await Promise.all(batch.map(async f => {
        try {
          const fd = await api(`/repos/${OWNER}/${REPO}/contents/${f.path}`);
          return JSON.parse(atob(fd.content.replace(/\n/g, "")));
        } catch { return null; }
      }));
      records.push(...loaded.filter(Boolean));
    }
    allLicenses = records.sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));

    renderLicenses(filter);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan='8' class='text-muted'>Error: ${e.message}</td></tr>`;
  }
}

function renderLicenses(filter = "") {
  const tbody = document.getElementById("licensesTbody");
  const items = filter
    ? allLicenses.filter(l =>
        l.d?.toLowerCase().includes(filter) ||
        l.id?.includes(filter) ||
        l.app?.toLowerCase().includes(filter)
      )
    : allLicenses;

  if (!items.length) {
    tbody.innerHTML = "<tr><td colspan='8' class='text-muted'>No licenses found.</td></tr>";
    return;
  }

  tbody.innerHTML = items.map(l => {
    const info   = APP_LABELS[l.app] || { label: l.app, badgeClass: "" };
    const status = l.status || "active";
    const expired = l.e !== "never" && new Date(l.e) < new Date() ? true : false;
    const statusBadge = status === "revoked"
      ? `<span class="badge badge-revoked">Revoked</span>`
      : expired
        ? `<span class="badge badge-expired">Expired</span>`
        : `<span class="badge badge-active">Active</span>`;

    return `
      <tr>
        <td class="mono">${l.id?.slice(0, 12)}…</td>
        <td><span class="badge ${info.badgeClass}">${info.label}</span></td>
        <td>${escHtml(l.d || "")}</td>
        <td>${l.e}</td>
        <td>${(l.m||["*"]).join(", ")}</td>
        <td>${l.n}</td>
        <td>${statusBadge}</td>
        <td>
          <div class="flex">
            ${status !== "revoked" ? `
              <button class="btn btn-outline btn-sm" onclick="showKeyModal('${l.id}','${escAttr(l.key)}','${escAttr(l.d)}')">🔑 Key</button>
              <button class="btn btn-danger btn-sm" onclick="confirmRevoke('${l.id}','${escAttr(l.d)}','${l.app}')">Revoke</button>
            ` : '<span class="text-muted">—</span>'}
          </div>
        </td>
      </tr>`;
  }).join("");
}

function filterLicenses() {
  renderLicenses(document.getElementById("licFilter").value.toLowerCase());
}

// ── Modal: show key ───────────────────────────────────────────────────────────
function showKeyModal(id, key, customer) {
  document.getElementById("modalTitle").textContent = `License Key — ${customer}`;
  document.getElementById("modalBody").innerHTML = `
    <p class="text-muted" style="margin-bottom:.6rem">License ID: <code>${id}</code></p>
    <div class="key-box" id="modalKey">${escHtml(key)}</div>
    <div class="key-actions" style="margin-top:.5rem">
      <button class="btn btn-outline btn-sm" onclick="copyKey('modalKey')">&#128203; Copy Key</button>
      <button class="btn btn-primary btn-sm" onclick="downloadKeyFromBox('modalKey','${escAttr(id)}','${escAttr(customer)}')">&#11015;&#65039; Download .txt</button>
    </div>
  `;
  document.getElementById("modal").classList.remove("hidden");
}

function closeModal() {
  document.getElementById("modal").classList.add("hidden");
}

// ── Revoke confirm ────────────────────────────────────────────────────────────
function confirmRevoke(id, customer, app) {
  if (!confirm(`Revoke the license for "${customer}" (${app})?\n\nThis will block the app at next sync.`)) return;
  doRevoke(id, customer, app);
}

async function doRevoke(id, customer, app) {
  const res = document.getElementById("licAlert");
  res.innerHTML = alert_html(`<span class="spinner"></span> Revoking ${customer}…`, "info");
  res.classList.remove("hidden");
  try {
    await api(`/repos/${OWNER}/${REPO}/actions/workflows/revoke_license.yml/dispatches`, "POST", {
      ref: BRANCH,
      inputs: { license_id: id, reason: "Revoked via admin portal" },
    });
    res.innerHTML = alert_html(`✅ Revocation workflow dispatched for <strong>${customer}</strong>. Reload licenses in ~30s.`, "success");
  } catch (e) {
    res.innerHTML = alert_html(`Revocation failed: ${e.message}`, "danger");
  }
}

// ── Alerts (helper) ───────────────────────────────────────────────────────────
function alert_html(msg, type) {
  return `<div class="alert alert-${type}">${msg}</div>`;
}

function showAlert(id, msg, type) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = alert_html(msg, type);
}

function escHtml(s) {
  return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function escAttr(s) {
  return String(s).replace(/'/g, "\\'");
}

// ── Settings tab ──────────────────────────────────────────────────────────────
function copyRepoConfig() {
  const cfg = `OWNER = "${OWNER}"\nREPO  = "${REPO}"\nBRANCH = "${BRANCH}"`;
  navigator.clipboard.writeText(cfg).then(() => alert("Copied!"));
}

// ── Init ──────────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  if (token) {
    // Auto-login if token already in sessionStorage
    login();
  }
  initGenerateTab();

  // Modal close on backdrop click
  document.getElementById("modal").addEventListener("click", e => {
    if (e.target === document.getElementById("modal")) closeModal();
  });
});
