const byId = (id) => document.getElementById(id);

async function apiRequest(url, options = {}) {
  const response = await fetch(url, options);
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = text;
  }
  if (!response.ok) {
    const detail = typeof body === "object"
      ? body.detail || body.error?.message || JSON.stringify(body)
      : body;
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }
  return body;
}

function show(value, isError = false) {
  const result = byId("result");
  result.textContent = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  result.classList.toggle("error", isError);
}

function fill(config) {
  byId("playerFriendlyInjectionEnabled").checked = config.player_friendly_injection_enabled !== false;
  byId("enablePlayerInitiatedDialogue").checked = config.enable_player_initiated_dialogue !== false;
  byId("enableActionDialogue").checked = config.enable_action_dialogue !== false;
  byId("enableNpcInitiatedDialogue").checked = config.enable_npc_initiated_dialogue !== false;
}

async function load() {
  try {
    const config = await apiRequest("/admin/config");
    fill(config);
    show({
      status: "loaded",
      config_schema_version: config.config_schema_version,
      prompt_enabled: config.prompt_enabled,
      player_friendly_injection_enabled: config.player_friendly_injection_enabled,
      enable_player_initiated_dialogue: config.enable_player_initiated_dialogue,
      enable_action_dialogue: config.enable_action_dialogue,
      enable_npc_initiated_dialogue: config.enable_npc_initiated_dialogue,
    });
  } catch (error) {
    show(error.message, true);
  }
}

async function save() {
  const button = byId("saveBtn");
  button.disabled = true;
  try {
    const payload = {
      player_friendly_injection_enabled: byId("playerFriendlyInjectionEnabled").checked,
      enable_player_initiated_dialogue: byId("enablePlayerInitiatedDialogue").checked,
      enable_action_dialogue: byId("enableActionDialogue").checked,
      enable_npc_initiated_dialogue: byId("enableNpcInitiatedDialogue").checked,
    };
    const response = await apiRequest("/admin/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    fill(response.config || response);
    show(response);
  } catch (error) {
    show(error.message, true);
  } finally {
    button.disabled = false;
  }
}

byId("saveBtn").addEventListener("click", save);
load();
