const state = {
  config: null,
  subtitle: null,
  prompts: null,
};

const tabMeta = {
  status: ["服务状态", "检查本地代理、上游服务和实时监视器。"],
  config: ["转发配置", "配置上游端口、模型、密钥和推理参数。"],
  subtitle: ["字幕设置", "配置字幕外观、位置、拖动保存和单窗口行为。"],
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
    if (!health.native_popup_enabled) {
      $("nativePopupStatus").textContent = "已关闭";
      $("nativePopupDetail").textContent = "可在字幕设置中开启";
    } else if (health.native_popup_worker_alive) {
      $("nativePopupStatus").textContent = "字幕浮层运行中";
      const interaction = health.native_popup_click_through ? "鼠标穿透" : "可交互";
      $("nativePopupDetail").textContent = `${interaction} · ${health.native_popup_position || "bottom_center"} · 完成后 ${health.native_popup_close_seconds} 秒关闭`;
    } else {
      $("nativePopupStatus").textContent = "桌面窗口不可用";
      $("nativePopupDetail").textContent = "请检查 tkinter 或桌面会话";
    }
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

function updateSubtitleColorPreview() {
  const preview = $("subtitleColorPreview");
  if (!preview) return;
  preview.style.background = $("nativePopupBackgroundColor").value;
  preview.style.color = $("nativePopupTextColor").value;
  preview.style.borderColor = $("nativePopupBorderColor").value;
  preview.querySelector("small").style.color = $("nativePopupMutedColor").value;
}

async function loadSubtitleConfig() {
  state.subtitle = await request("/admin/subtitle-config");
  const config = state.subtitle || {};
  $("nativePopupEnabled").checked = config.native_popup_enabled !== false;
  $("nativePopupCloseSeconds").value = config.native_popup_close_seconds || 30;
  $("nativePopupPosition").value = config.native_popup_position || "bottom_center";
  $("nativePopupOffsetX").value = config.native_popup_offset_x ?? 0;
  $("nativePopupOffsetY").value = config.native_popup_offset_y ?? 0;
  $("nativePopupCustomX").value = config.native_popup_custom_x ?? 120;
  $("nativePopupCustomY").value = config.native_popup_custom_y ?? 120;
  $("nativePopupWidth").value = config.native_popup_width || 960;
  $("nativePopupHeight").value = config.native_popup_height || 220;
  $("nativePopupFontSize").value = config.native_popup_font_size || 24;
  $("nativePopupOpacity").value = config.native_popup_opacity ?? 0.88;
  $("nativePopupShowReasoning").checked = Boolean(config.native_popup_show_reasoning);
  $("nativePopupClickThrough").checked = config.native_popup_click_through === true;
  $("nativePopupBackgroundColor").value = config.native_popup_background_color || "#101318";
  $("nativePopupTextColor").value = config.native_popup_text_color || "#f7f8fa";
  $("nativePopupMutedColor").value = config.native_popup_muted_color || "#aeb6c2";
  $("nativePopupBorderColor").value = config.native_popup_border_color || "#343a46";
  $("nativePopupErrorColor").value = config.native_popup_error_color || "#ff8f9b";
  updateSubtitleColorPreview();
}

function subtitlePayload() {
  return {
    native_popup_enabled: $("nativePopupEnabled").checked,
    native_popup_close_seconds: Number($("nativePopupCloseSeconds").value),
    native_popup_position: $("nativePopupPosition").value,
    native_popup_offset_x: Number($("nativePopupOffsetX").value),
    native_popup_offset_y: Number($("nativePopupOffsetY").value),
    native_popup_custom_x: Number($("nativePopupCustomX").value),
    native_popup_custom_y: Number($("nativePopupCustomY").value),
    native_popup_width: Number($("nativePopupWidth").value),
    native_popup_height: Number($("nativePopupHeight").value),
    native_popup_font_size: Number($("nativePopupFontSize").value),
    native_popup_opacity: Number($("nativePopupOpacity").value),
    native_popup_show_reasoning: $("nativePopupShowReasoning").checked,
    native_popup_click_through: $("nativePopupClickThrough").checked,
    native_popup_background_color: $("nativePopupBackgroundColor").value,
    native_popup_text_color: $("nativePopupTextColor").value,
    native_popup_muted_color: $("nativePopupMutedColor").value,
    native_popup_border_color: $("nativePopupBorderColor").value,
    native_popup_error_color: $("nativePopupErrorColor").value,
  };
}

async function saveSubtitleConfig({ silent = false } = {}) {
  $("saveSubtitleBtn").disabled = true;
  try {
    const result = await request("/admin/subtitle-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(subtitlePayload()),
    });
    state.subtitle = result.config;
    $("subtitleResult").textContent = pretty(result);
    if (!silent) toast("字幕设置已保存并立即生效");
    await Promise.all([loadHealth(), loadSubtitleConfig()]);
    return result;
  } catch (error) {
    $("subtitleResult").textContent = error.message;
    toast(error.message, true);
    throw error;
  } finally {
    $("saveSubtitleBtn").disabled = false;
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

function textFromDelta(value) {
  if (typeof value === "string") return value;
  if (!Array.isArray(value)) return "";
  return value.map((item) => {
    if (typeof item === "string") return item;
    if (!item || typeof item !== "object") return "";
    if (typeof item.text === "string") return item.text;
    if (typeof item.text?.value === "string") return item.text.value;
    if (typeof item.content === "string") return item.content;
    return "";
  }).join("");
}

function reasoningFromDelta(delta) {
  if (!delta || typeof delta !== "object") return "";
  for (const key of ["reasoning_content", "reasoning", "thinking"]) {
    const text = textFromDelta(delta[key]);
    if (text) return text;
  }
  return "";
}

function parseSseBlock(block) {
  const data = block
    .replace(/\r\n/g, "\n")
    .split("\n")
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n")
    .trim();
  if (!data || data === "[DONE]") return null;
  return JSON.parse(data);
}

function renderStreamSummary(summary) {
  const message = {
    role: "assistant",
    content: summary.content,
  };
  if (summary.reasoning) message.reasoning = summary.reasoning;
  return {
    id: summary.id,
    object: "chat.completion",
    model: summary.model,
    relay_request_id: summary.relayRequestId,
    choices: [
      {
        index: 0,
        message,
        finish_reason: summary.finishReason,
      },
    ],
    usage: summary.usage,
    stream_events: summary.eventCount,
  };
}

async function readStreamingChat(response) {
  if (!response.body) throw new Error("浏览器未提供可读取的响应流");

  const summary = {
    id: null,
    model: null,
    relayRequestId: response.headers.get("X-Relay-Request-ID"),
    content: "",
    reasoning: "",
    finishReason: null,
    usage: null,
    eventCount: 0,
  };
  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let answerStarted = false;

  const processBlock = (block) => {
    let event;
    try {
      event = parseSseBlock(block);
    } catch (error) {
      throw new Error(`无法解析上游 SSE：${error.message}`);
    }
    if (!event) return;

    summary.eventCount += 1;
    summary.id = summary.id || event.id || null;
    summary.model = summary.model || event.model || null;
    summary.usage = event.usage || summary.usage;

    const choice = event.choices?.[0];
    const delta = choice?.delta || choice?.message || {};
    const reasoning = reasoningFromDelta(delta);
    const content = textFromDelta(delta.content ?? delta.text);

    if (reasoning) {
      summary.reasoning += reasoning;
      if (!answerStarted) {
        $("testAnswer").textContent = "模型正在思考……";
      }
    }
    if (content) {
      if (!answerStarted) {
        $("testAnswer").textContent = "";
        answerStarted = true;
      }
      summary.content += content;
      $("testAnswer").textContent += content;
      $("testAnswer").scrollTop = $("testAnswer").scrollHeight;
    }
    if (choice?.finish_reason != null) {
      summary.finishReason = choice.finish_reason;
    }
    $("testRaw").textContent = pretty(renderStreamSummary(summary));
  };

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    while (true) {
      const match = /\r?\n\r?\n/.exec(buffer);
      if (!match || match.index == null) break;
      const block = buffer.slice(0, match.index);
      buffer = buffer.slice(match.index + match[0].length);
      processBlock(block);
    }

    if (done) break;
  }

  if (buffer.trim()) processBlock(buffer);
  if (!summary.content) {
    $("testAnswer").textContent = summary.reasoning
      ? "(模型仅返回推理内容，没有正文)"
      : "(content 为空)";
  }
  $("testRaw").textContent = pretty(renderStreamSummary(summary));
  return summary;
}

async function sendNonStreamingTest(payload, headers) {
  const result = await request("/v1/chat/completions", {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  const message = result?.choices?.[0]?.message || {};
  $("testAnswer").textContent = message.content || "(content 为空)";
  $("testRaw").textContent = pretty(result);
}

async function sendTest() {
  if (!state.config) await loadConfig();

  const useStream = $("testStream").checked;
  const payload = {
    model: $("testModel").value.trim() || state.config.default_model,
    messages: [
      {
        role: "user",
        content: $("testMessage").value,
      },
    ],
    stream: useStream,
    max_tokens: Number($("testMaxTokens").value) || 4096,
  };
  const headers = {
    "Content-Type": "application/json",
    "Authorization": `Bearer ${state.config.local_api_key || ""}`,
  };

  $("sendTestBtn").disabled = true;
  $("testAnswer").textContent = useStream ? "正在建立流式连接..." : "模型正在生成...";
  $("testRaw").textContent = "等待响应...";
  try {
    if (!useStream) {
      await sendNonStreamingTest(payload, headers);
    } else {
      const response = await fetch("/v1/chat/completions", {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const text = await response.text();
        let detail = text;
        try {
          const body = JSON.parse(text);
          detail = body.detail || body.error?.message || pretty(body);
        } catch {
          // Keep raw error text.
        }
        throw new Error(`${response.status} ${response.statusText}: ${detail}`);
      }

      const contentType = response.headers.get("content-type") || "";
      if (!contentType.includes("text/event-stream")) {
        const text = await response.text();
        const result = JSON.parse(text);
        const message = result?.choices?.[0]?.message || {};
        $("testAnswer").textContent = message.content || "(content 为空)";
        $("testRaw").textContent = pretty(result);
        toast("上游未返回 SSE，已按完整 JSON 显示", true);
      } else {
        await readStreamingChat(response);
      }
    }
    toast(useStream ? "流式 API 测试完成" : "API 测试完成");
  } catch (error) {
    $("testAnswer").textContent = error.message;
    $("testRaw").textContent = error.stack || error.message;
    toast(error.message, true);
  } finally {
    $("sendTestBtn").disabled = false;
  }
}

async function finishSubtitlePositioning({ silent = false } = {}) {
  clearInterval(window.__subtitlePositionWatch);
  try {
    await request("/admin/subtitle-positioning/finish", { method: "POST" });
    if (!silent) toast("已结束定位模式，字幕恢复当前穿透设置");
  } catch (error) {
    if (!silent) toast(error.message, true);
  }
}

function startSubtitlePositionWatch(previous) {
  clearInterval(window.__subtitlePositionWatch);
  const deadline = Date.now() + 65_000;
  window.__subtitlePositionWatch = setInterval(async () => {
    if (Date.now() > deadline) {
      clearInterval(window.__subtitlePositionWatch);
      await finishSubtitlePositioning({ silent: true });
      toast("定位模式已超时，字幕已恢复当前穿透设置");
      return;
    }
    try {
      const latest = await request("/admin/subtitle-config");
      const changed = latest.native_popup_position === "custom" && (
        latest.native_popup_custom_x !== previous.x ||
        latest.native_popup_custom_y !== previous.y ||
        previous.position !== "custom"
      );
      if (!changed) return;
      $("nativePopupPosition").value = "custom";
      $("nativePopupCustomX").value = latest.native_popup_custom_x;
      $("nativePopupCustomY").value = latest.native_popup_custom_y;
      $("nativePopupOffsetX").value = latest.native_popup_offset_x ?? 0;
      $("nativePopupOffsetY").value = latest.native_popup_offset_y ?? 0;
      state.subtitle = { ...(state.subtitle || {}), ...latest };
      clearInterval(window.__subtitlePositionWatch);
      await finishSubtitlePositioning({ silent: true });
      toast(`字幕位置已保存：${latest.native_popup_custom_x}, ${latest.native_popup_custom_y}；已恢复穿透设置`);
    } catch {
      // The manual reload button remains available if polling is interrupted.
    }
  }, 800);
}

async function previewPopup() {
  $("previewPopupBtn").disabled = true;
  try {
    await saveSubtitleConfig({ silent: true });
    const previous = {
      position: $("nativePopupPosition").value,
      x: Number($("nativePopupCustomX").value),
      y: Number($("nativePopupCustomY").value),
    };
    await request("/admin/subtitle-positioning/start", { method: "POST" });
    startSubtitlePositionWatch(previous);
    toast("定位模式已开启；拖动字幕并松开鼠标即可自动保存位置");
  } catch (error) {
    if (!error?.message) toast("无法打开字幕预览", true);
  } finally {
    $("previewPopupBtn").disabled = false;
  }
}

async function refreshAll() {
  $("refreshAllBtn").disabled = true;
  try {
    await Promise.all([loadHealth(), loadConfig(), loadSubtitleConfig(), loadPrompts()]);
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
$("saveSubtitleBtn").addEventListener("click", () => {
  saveSubtitleConfig().catch(() => {});
});
$("reloadSubtitleBtn").addEventListener("click", async () => {
  try {
    await loadSubtitleConfig();
    toast("已读取字幕进程保存的位置");
  } catch (error) {
    toast(error.message, true);
  }
});
$("previewPopupBtn").addEventListener("click", previewPopup);
$("finishPositioningBtn").addEventListener("click", () => {
  finishSubtitlePositioning().catch(() => {});
});
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
[
  "nativePopupBackgroundColor",
  "nativePopupTextColor",
  "nativePopupMutedColor",
  "nativePopupBorderColor",
  "nativePopupErrorColor",
].forEach((id) => $(id).addEventListener("input", updateSubtitleColorPreview));
$("sendTestBtn").addEventListener("click", sendTest);

refreshAll();
