const state = {
  data: {},
  report: {},
  project: {},
  previewUrl: "",
  outputs: null,
};

const trimOptions = {
  pb: [
    "custom",
    "5x7.4",
    "5x8",
    "5.06x7.81",
    "5.25x8",
    "5.5x8.5",
    "6x9",
    "6.14x9.21",
    "6.69x9.61",
    "7x10",
    "7.44x9.69",
    "7.5x9.25",
    "8x10",
    "8.25x6",
    "8.25x8.25",
    "8.27x11.69",
    "8.5x8.5",
    "8.5x11",
  ],
  hc: ["custom", "5.5x8.5", "6x9", "6.14x9.21", "7x10", "8.25x11"],
};

const choices = {
  binding_type: [
    ["pb", "Paperback"],
    ["hc", "Hardcover"],
  ],
  interior_type: [
    ["black_white", "Black & white"],
    ["standard_color", "Standard color"],
    ["premium_color", "Premium color"],
  ],
  paper_type: [
    ["white", "White"],
    ["cream", "Cream"],
  ],
  reading_direction: [
    ["ltr", "Left to right"],
    ["rtl", "Right to left"],
  ],
  ui_units: [
    ["in", "Inches"],
    ["mm", "Millimeters"],
    ["cm", "Centimeters"],
  ],
};

function binding() {
  return state.data.binding_type === "hc" ? "hc" : "pb";
}

function presetMode() {
  return state.data.platform_preset !== false;
}

function units() {
  return ["in", "mm", "cm"].includes(state.data.ui_units) ? state.data.ui_units : "in";
}

function keyFor(rawKey) {
  return rawKey.replace("BINDING", binding());
}

function optionLabel(value) {
  if (value === "custom") return "Custom size";
  const [w, h] = value.split("x").map(Number);
  if (Number.isFinite(w) && Number.isFinite(h)) {
    return `${w} x ${h} in / ${Math.round(w * 25.4)} x ${Math.round(h * 25.4)} mm`;
  }
  return value.replace("x", " x ") + " in";
}

function isInchField(key) {
  return key.endsWith("_inches");
}

function fromInches(value) {
  const number = Number(value || 0);
  if (units() === "mm") return number * 25.4;
  if (units() === "cm") return number * 2.54;
  return number;
}

function toInches(value) {
  if (String(value ?? "").trim() === "") return "";
  const number = Number(value || 0);
  if (units() === "mm") return number / 25.4;
  if (units() === "cm") return number / 2.54;
  return number;
}

function unitStep() {
  if (units() === "mm") return "0.25";
  if (units() === "cm") return "0.025";
  return "0.01";
}

function displayNumber(value) {
  const number = Number(value || 0);
  return Number.isInteger(number) ? String(number) : number.toFixed(units() === "in" ? 3 : 2).replace(/0+$/, "").replace(/\.$/, "");
}

function formatLength(inches) {
  const converted = fromInches(inches);
  return `${displayNumber(converted)} ${units()}`;
}

function normalizeHexColor(value, fallback = "#000000") {
  const text = String(value || "").trim();
  if (/^#[0-9a-fA-F]{6}$/.test(text)) return text.toLowerCase();
  return fallback;
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "Request failed");
  }
  return payload;
}

async function load() {
  state.project = await api("/api/project");
  document.getElementById("projectPath").textContent = state.project.metadata_path;
  await refreshData();
  await renderPreview();
}

async function refreshData() {
  const payload = await api("/api/load");
  state.data = payload.data;
  state.report = payload.report;
  document.getElementById("yamlView").value = payload.yaml;
  fillControls();
  renderStatus(state.outputs);
}

function fillSelect(select, options, value) {
  select.replaceChildren();
  for (const option of options) {
    const [key, label] = Array.isArray(option) ? option : [option, optionLabel(option)];
    const node = document.createElement("option");
    node.value = key;
    node.textContent = label;
    select.appendChild(node);
  }
  select.value = value;
}

function fillControls() {
  const trim = document.querySelector('[data-key="trim_size"]');
  if (!presetMode()) {
    state.data.trim_size = "custom";
  }
  fillSelect(trim, trimOptions[binding()], state.data.trim_size);
  if (!trimOptions[binding()].includes(state.data.trim_size)) {
    state.data.trim_size = "custom";
    trim.value = "custom";
  }

  for (const [key, options] of Object.entries(choices)) {
    const control = document.querySelector(`[data-key="${key}"]`);
    if (control) fillSelect(control, options, state.data[key]);
  }

  for (const control of document.querySelectorAll("[data-key]")) {
    const actualKey = keyFor(control.dataset.key);
    if (control.tagName === "SELECT") continue;
    if (control.type === "checkbox") {
      control.checked = Boolean(state.data[actualKey]);
    } else if (control.type === "color") {
      control.value = normalizeHexColor(state.data[actualKey], control.value || "#000000");
    } else {
      if (control.type === "number" && isInchField(actualKey)) {
        control.step = unitStep();
        control.value = String(state.data[actualKey] ?? "").trim() === "" ? "" : displayNumber(fromInches(state.data[actualKey]));
      } else {
        control.value = state.data[actualKey] ?? "";
      }
    }
  }
  document.getElementById("customSizePanel").classList.toggle("active", state.data.trim_size === "custom" || !presetMode());
  document.querySelectorAll(".preset-only").forEach((node) => {
    node.classList.toggle("hidden", !presetMode());
  });
}

function collectControls() {
  const data = {};
  for (const control of document.querySelectorAll("[data-key]")) {
    const actualKey = keyFor(control.dataset.key);
    if (control.type === "checkbox") {
      data[actualKey] = control.checked;
    } else if (control.type === "color") {
      data[actualKey] = normalizeHexColor(control.value);
    } else if (control.type === "number" && isInchField(actualKey)) {
      data[actualKey] = toInches(control.value);
    } else {
      data[actualKey] = control.value;
    }
  }
  return data;
}

async function save() {
  const payload = await api("/api/save", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ data: collectControls() }),
  });
  state.data = payload.data;
  state.report = payload.report;
  document.getElementById("yamlView").value = payload.yaml;
  fillControls();
  renderStatus(state.outputs);
}

async function renderPreview() {
  await save();
  const guides = document.getElementById("guides").checked;
  const payload = await api(`/api/preview?width=1300&guides=${guides}`);
  state.previewUrl = `${payload.url}&t=${Date.now()}`;
  document.getElementById("previewImage").src = state.previewUrl;
}

async function exportCover() {
  document.getElementById("guides").checked = false;
  await save();
  const payload = await api("/api/export", { method: "POST" });
  state.report = payload;
  state.outputs = payload.outputs;
  renderStatus(state.outputs);
  await renderPreview();
}

function renderStatus(outputs = null) {
  const summary = state.report.issue_summary || { error: 0, warning: 0, info: 0 };
  const badge = document.getElementById("statusBadge");
  badge.textContent = summary.error ? `${summary.error} Error` : "Ready";
  badge.classList.toggle("error", Boolean(summary.error));

  const geometry = state.report.geometry;
  const metrics = document.getElementById("metrics");
  metrics.replaceChildren();
  if (geometry) {
    const rows = [
      `Cover ${formatLength(geometry.total_width_inches)} x ${formatLength(geometry.total_height_inches)}`,
      `Front ${formatLength(geometry.front_width_inches)} x ${formatLength(geometry.front_height_inches)}`,
      `Spine ${formatLength(geometry.spine_width_inches)}`,
      `${geometry.total_width_px} x ${geometry.total_height_px} px`,
    ];
    for (const row of rows) {
      const item = document.createElement("div");
      item.textContent = row;
      metrics.appendChild(item);
    }
  }

  const issues = document.getElementById("issues");
  issues.replaceChildren();
  for (const issue of state.report.issues || []) {
    const pill = document.createElement("span");
    pill.className = `issue ${issue.severity}`;
    pill.textContent = `${issue.field}: ${issue.message}`;
    issues.appendChild(pill);
  }
  if (outputs) {
    for (const [label, path] of Object.entries(outputs)) {
      const pill = document.createElement("span");
      pill.className = "issue";
      pill.textContent = `${label}: ${path}`;
      issues.appendChild(pill);
    }
  }
}

function wireEvents() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((node) => node.classList.remove("active"));
      document.querySelectorAll(".panel").forEach((node) => node.classList.remove("active"));
      button.classList.add("active");
      document.getElementById(button.dataset.panel).classList.add("active");
    });
  });

  document.getElementById("saveButton").addEventListener("click", save);
  document.getElementById("previewButton").addEventListener("click", renderPreview);
  document.getElementById("exportButton").addEventListener("click", exportCover);
  document.getElementById("fitButton").addEventListener("click", () => {
    document.getElementById("previewImage").scrollIntoView({ block: "center", inline: "center" });
  });
  document.getElementById("guides").addEventListener("change", renderPreview);
  document.querySelector('[data-key="binding_type"]').addEventListener("change", () => {
    state.data.binding_type = document.querySelector('[data-key="binding_type"]').value;
    if (!trimOptions[binding()].includes(state.data.trim_size)) {
      state.data.trim_size = "custom";
    }
    fillControls();
  });
  document.querySelector('[data-key="trim_size"]').addEventListener("change", () => {
    state.data.trim_size = document.querySelector('[data-key="trim_size"]').value;
    fillControls();
  });
  document.querySelector('[data-key="platform_preset"]').addEventListener("change", () => {
    state.data.platform_preset = document.querySelector('[data-key="platform_preset"]').checked;
    if (!presetMode()) {
      state.data.trim_size = "custom";
    }
    fillControls();
    renderStatus(state.outputs);
  });
  document.querySelector('[data-key="ui_units"]').addEventListener("change", () => {
    state.data.ui_units = document.querySelector('[data-key="ui_units"]').value;
    fillControls();
    renderStatus(state.outputs);
  });
}

wireEvents();
load().catch((error) => {
  document.getElementById("statusBadge").textContent = "Error";
  document.getElementById("statusBadge").classList.add("error");
  document.getElementById("issues").textContent = error.message;
});
