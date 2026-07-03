const state = {
  config: null,
  prompts: null,
};

const tabMeta = {
  status: ["服务状态", "检查本地代理、上游服务和实时监视器。"],
  config: ["转发配置", "配置上游端口、模型、密钥和推理参数。"],
  prompts: ["提示词管理", "保存、加载并随时切换系统提示词。"],
  test: ["API 测试", "直接验证 OpenAI 兼容接口和提示词效果。"],
};

function $(id) {
  return document.getElementById(id);
}

function pretty(value) {
  return JSON.stringify(value, null, 2);
}

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast show${isError ? " error" : ""}`;
  clearTimeout(window.__toastTimer);
  window.__toastTimer = setTimeout(() => {
    el.className = "toast";
  }, 3200);
}

async function request(url, options = {}) {
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
      ? body.detail || body.error?.message || pretty(body)
      : body;
    throw new Error(`${response.status} ${response.statusText}: ${detail}`);
  }

  return body;
}

function setTab(tab) {
  document.querySelectorAll(".nav-item[data-tab]").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === `tab-${tab}`);
  });
  $("pageTitle").textContent = tabMeta[tab][0];
  $("pageSubtitle").textContent = tabMeta[tab][1];
}

async function loadHealth() {
  try {
    const health = await request("/health");
    $("localApiValue").textContent = health.openai_base_url;
    $("upstreamValue").textContent = health.upstream;
    $("activePromptValue").textContent = health.active_prompt || "未启用";
    $("promptLengthValue").textContent = `${health.active_prompt_length} 字符`;
    $("recommendedBaseUrl").textContent = health.openai_base_url;
    $("recommendedModel").textContent = health.model;
    $("sidebarDot").className = "status-dot ok";
    $("sidebarStatus").textContent = "本地代理运行正常";
    return health;
  } catch (error) {
    $("sidebarDot").className = "status-dot bad";
    $("sidebarStatus").textContent = "本地代理异常";
    throw error;
  }
}

async function loadConfig() {
  state.config = await request("/admin/config");
  $("upstreamBaseUrl").value = state.config.upstream_base_url || "";
  $("upstreamApiKey").value = state.config.upstream_api_key || "";
  $("localApiKey").value = state.config.local_api_key || "";
  $("defaultModel").value = state.config.default_model || "";
  $("requestTimeout").value = state.config.request_timeout_seconds || 600;
  $("promptEnabled").checked = Boolean(state.config.prompt_enabled);
  $("recommendedApiKey").textContent = state.config.local_api_key || "无需密钥";
  $("recommendedModel").textContent = state.config.default_model || "--";
  $("testModel").value = state.config.default_model || "";
}

async function saveConfig() {
  const payload = {
    upstream_base_url: $("upstreamBaseUrl").value.trim(),
    upstream_api_key: $("upstreamApiKey").value.trim(),
    local_api_key: $("localApiKey").value.trim(),
    default_model: $("defaultModel").value.trim(),
    request_timeout_seconds: Number($("requestTimeout").value),
    prompt_enabled: $("promptEnabled").checked,
  };

  $("saveConfigBtn").disabled = true;
  try {
    const result = await request("/admin/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    $("configResult").textContent = pretty(result);
    toast("配置已保存并立即生效");
    await refreshAll();
  } catch (error) {
    $("configResult").textContent = error.message;
    toast(error.message, true);
  } finally {
    $("saveConfigBtn").disabled = false;
  }
}

function renderPromptList(preferredName = null) {
  const select = $("promptSelect");
  select.innerHTML = "";
  const names = state.prompts?.names || [];

  for (const name of names) {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name === state.prompts.active ? `${name}（当前）` : name;
    select.appendChild(option);
  }

  const selected = preferredName && names.includes(preferredName)
    ? preferredName
    : state.prompts?.active || names[0] || "";

  select.value = selected;
  loadSelectedPrompt();
  $("activePromptBanner").textContent = `当前启用：${state.prompts?.active || "无"}`;
}

function loadSelectedPrompt() {
  const name = $("promptSelect").value;
  $("promptName").value = name;
  $("promptContent").value = state.prompts?.profiles?.[name] || "";
  updatePromptStats();
}

async function loadPrompts(preferredName = null) {
  state.prompts = await request("/admin/prompts");
  renderPromptList(preferredName);
}

async function savePrompt() {
  const name = $("promptName").value.trim();
  if (!name) {
    toast("请输入提示词名称", true);
    return;
  }
  const content = $("promptContent").value;

  $("savePromptBtn").disabled = true;
  try {
    const result = await request(`/admin/prompts/${encodeURIComponent(name)}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
    $("promptResult").textContent = pretty(result);
    await loadPrompts(result.name);
    toast("提示词已保存");
  } catch (error) {
    $("promptResult").textContent = error.message;
    toast(error.message, true);
  } finally {
    $("savePromptBtn").disabled = false;
  }
}

async function activatePrompt() {
  const name = $("promptName").value.trim();
  if (!name) {
    toast("请选择或填写提示词名称", true);
    return;
  }

  try {
    const result = await request(
      `/admin/prompts/${encodeURIComponent(name)}/activate`,
      { method: "POST" }
    );
    $("promptResult").textContent = pretty(result);
    await Promise.all([loadPrompts(name), loadHealth()]);
    toast(`已启用：${name}`);
  } catch (error) {
    $("promptResult").textContent = error.message;
    toast(error.message, true);
  }
}

async function deletePrompt() {
  const name = $("promptSelect").value;
  if (!name) return;
  if (!confirm(`确认删除提示词“${name}”？`)) return;

  try {
    const result = await request(`/admin/prompts/${encodeURIComponent(name)}`, {
      method: "DELETE",
    });
    $("promptResult").textContent = pretty(result);
    await Promise.all([loadPrompts(), loadHealth()]);
    toast("提示词已删除");
  } catch (error) {
    $("promptResult").textContent = error.message;
    toast(error.message, true);
  }
}

function updatePromptStats() {
  const content = $("promptContent").value;
  const lines = content ? content.split(/\r?\n/).length : 0;
  $("promptStats").textContent = `${content.length} 字符 · ${lines} 行`;
}

function exportPrompt() {
  const name = $("promptName").value.trim() || "system_prompt";
  const blob = new Blob([$("promptContent").value], {
    type: "text/plain;charset=utf-8",
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `${name}.txt`;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function importPromptFile(file) {
  if (!file) return;
  const content = await file.text();
  $("promptName").value = file.name.replace(/\.txt$/i, "");
  $("promptContent").value = content;
  updatePromptStats();
  toast("文件已载入编辑器，点击“保存”写入配置集");
}

async function testUpstream() {
  $("testUpstreamBtn").disabled = true;
  $("statusResult").textContent = "正在连接上游...";
  try {
    const result = await request("/admin/test-upstream", { method: "POST" });
    $("statusResult").textContent = pretty(result);
    $("sidebarDot").className = "status-dot ok";
    $("sidebarStatus").textContent = "上游连接正常";
    toast("上游连接测试成功");
  } catch (error) {
    $("statusResult").textContent = error.message;
    $("sidebarDot").className = "status-dot bad";
    $("sidebarStatus").textContent = "上游连接失败";
    toast(error.message, true);
  } finally {
    $("testUpstreamBtn").disabled = false;
  }
}

async function sendTest() {
  if (!state.config) await loadConfig();

  const payload = {
    model: $("testModel").value.trim() || state.config.default_model,
    messages: [
      {
        role: "user",
        content: $("testMessage").value,
      },
    ],
    stream: false,
    max_tokens: Number($("testMaxTokens").value) || 512,
  };

  $("sendTestBtn").disabled = true;
  $("testAnswer").textContent = "模型正在生成...";
  $("testRaw").textContent = "等待响应...";
  try {
    const result = await request("/v1/chat/completions", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${state.config.local_api_key || ""}`,
      },
      body: JSON.stringify(payload),
    });

    const message = result?.choices?.[0]?.message || {};
    $("testAnswer").textContent = message.content || "(content 为空)";
    $("testRaw").textContent = pretty(result);
    toast("API 测试完成");
  } catch (error) {
    $("testAnswer").textContent = error.message;
    $("testRaw").textContent = error.stack || error.message;
    toast(error.message, true);
  } finally {
    $("sendTestBtn").disabled = false;
  }
}

async function refreshAll() {
  $("refreshAllBtn").disabled = true;
  try {
    await Promise.all([loadHealth(), loadConfig(), loadPrompts()]);
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("refreshAllBtn").disabled = false;
  }
}

document.querySelectorAll(".nav-item[data-tab]").forEach((button) => {
  button.addEventListener("click", () => setTab(button.dataset.tab));
});

$("refreshAllBtn").addEventListener("click", refreshAll);
$("testUpstreamBtn").addEventListener("click", testUpstream);
$("saveConfigBtn").addEventListener("click", saveConfig);
$("promptSelect").addEventListener("change", loadSelectedPrompt);
$("promptContent").addEventListener("input", updatePromptStats);
$("savePromptBtn").addEventListener("click", savePrompt);
$("activatePromptBtn").addEventListener("click", activatePrompt);
$("deletePromptBtn").addEventListener("click", deletePrompt);
$("exportPromptBtn").addEventListener("click", exportPrompt);
$("importPromptBtn").addEventListener("click", () => $("promptFileInput").click());
$("promptFileInput").addEventListener("change", (event) => {
  importPromptFile(event.target.files?.[0]);
  event.target.value = "";
});
$("sendTestBtn").addEventListener("click", sendTest);

refreshAll();
