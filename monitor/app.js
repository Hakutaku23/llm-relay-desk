const $ = (id) => document.getElementById(id);

const state = {
  socket: null,
  reconnectTimer: null,
  reconnectDelay: 700,
  requests: new Map(),
  order: [],
  selectedId: null,
};

const statusLabels = {
  streaming: "生成中",
  complete: "已完成",
  error: "错误",
  cancelled: "已取消",
  idle: "空闲",
};

function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.className = `toast show${isError ? " error" : ""}`;
  clearTimeout(window.__monitorToast);
  window.__monitorToast = setTimeout(() => {
    el.className = "toast";
  }, 2600);
}

function setConnection(status, text) {
  const pill = $("connectionPill");
  pill.className = `connection-pill ${status}`;
  $("connectionText").textContent = text;
}

function socketUrl() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${location.host}/ws/monitor`;
}

function connect() {
  clearTimeout(state.reconnectTimer);
  if (state.socket) {
    state.socket.onclose = null;
    state.socket.close();
  }

  setConnection("connecting", "正在连接");
  const socket = new WebSocket(socketUrl());
  state.socket = socket;

  socket.onopen = () => {
    state.reconnectDelay = 700;
    setConnection("connected", "已连接");
  };

  socket.onmessage = (message) => {
    let event;
    try {
      event = JSON.parse(message.data);
    } catch {
      return;
    }
    handleEvent(event);
  };

  socket.onerror = () => {
    setConnection("disconnected", "连接异常");
  };

  socket.onclose = () => {
    if (state.socket !== socket) return;
    setConnection("disconnected", "已断开，正在重连");
    state.reconnectTimer = setTimeout(connect, state.reconnectDelay);
    state.reconnectDelay = Math.min(5000, Math.round(state.reconnectDelay * 1.6));
  };
}

function normalizeRecord(record, fromSnapshot = false) {
  const content = String(record.content || "");
  const reasoning = String(record.reasoning || "");
  return {
    request_id: record.request_id,
    api: record.api || "",
    route: record.route || "",
    model: record.model || "未指定模型",
    source: record.source || "unknown",
    user_agent: record.user_agent || "",
    stream: Boolean(record.stream),
    started_at: record.started_at || new Date().toISOString(),
    finished_at: record.finished_at || null,
    elapsed_ms: record.elapsed_ms ?? null,
    status_code: record.status_code ?? null,
    status: record.status || "streaming",
    content,
    reasoning,
    displayContent: fromSnapshot ? content : "",
    displayReasoning: fromSnapshot ? reasoning : "",
    error: record.error || "",
  };
}

function applySnapshot(requests) {
  const previousSelection = state.selectedId;
  state.requests.clear();
  state.order = [];

  for (const raw of requests || []) {
    if (!raw?.request_id) continue;
    const record = normalizeRecord(raw, true);
    state.requests.set(record.request_id, record);
    state.order.push(record.request_id);
  }

  state.selectedId = previousSelection && state.requests.has(previousSelection)
    ? previousSelection
    : state.order[state.order.length - 1] || null;

  renderList();
  renderSelected();
}

function handleEvent(event) {
  switch (event.type) {
    case "snapshot":
      applySnapshot(event.requests);
      if (event.resync) toast("监视窗口已自动同步最新状态");
      break;
    case "monitor_cleared":
      state.requests.clear();
      state.order = [];
      state.selectedId = null;
      renderList();
      renderSelected();
      break;
    case "request_start":
      onRequestStart(event);
      break;
    case "content_delta":
      onDelta(event, "content");
      break;
    case "reasoning_delta":
      onDelta(event, "reasoning");
      break;
    case "request_done":
      onTerminal(event, "complete");
      break;
    case "request_error":
      onTerminal(event, "error");
      break;
    case "request_cancelled":
      onTerminal(event, "cancelled");
      break;
    default:
      break;
  }
}

function onRequestStart(event) {
  const record = normalizeRecord({ ...event, status: "streaming" });
  state.requests.set(record.request_id, record);
  state.order = state.order.filter((id) => id !== record.request_id);
  state.order.push(record.request_id);

  if ($("autoSelect").checked || !state.selectedId) {
    state.selectedId = record.request_id;
  }
  renderList();
  renderSelected();
}

function onDelta(event, field) {
  const record = state.requests.get(event.request_id);
  if (!record) return;
  record[field] += String(event.text || "");
  if (state.selectedId === event.request_id) {
    updateStats(record);
    updateStreamingState(record);
  }
}

function onTerminal(event, status) {
  const record = state.requests.get(event.request_id);
  if (!record) return;
  record.status = status;
  record.finished_at = event.finished_at || new Date().toISOString();
  record.elapsed_ms = event.elapsed_ms ?? record.elapsed_ms;
  record.status_code = event.status_code ?? record.status_code;
  record.error = event.error || record.error;
  renderList();
  if (state.selectedId === event.request_id) renderSelected();
}

function formatTime(value) {
  if (!value) return "--:--:--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

function formatDuration(ms) {
  if (ms === null || ms === undefined) return "生成中";
  if (ms < 1000) return `${ms} ms`;
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`;
}

function renderList() {
  const container = $("requestList");
  container.replaceChildren();
  $("requestCount").textContent = `${state.order.length} 条`;

  if (!state.order.length) {
    const empty = document.createElement("div");
    empty.className = "empty-list";
    empty.textContent = "等待 API 请求。";
    container.appendChild(empty);
    return;
  }

  for (const id of [...state.order].reverse()) {
    const record = state.requests.get(id);
    if (!record) continue;

    const button = document.createElement("button");
    button.className = `request-item${state.selectedId === id ? " active" : ""}`;
    button.type = "button";

    const top = document.createElement("div");
    top.className = "request-item-top";

    const model = document.createElement("span");
    model.className = "request-item-model";
    model.textContent = record.model;
    model.title = record.model;

    const time = document.createElement("span");
    time.className = "request-item-time";
    time.textContent = formatTime(record.started_at);

    top.append(model, time);

    const meta = document.createElement("div");
    meta.className = "request-item-meta";

    const route = document.createElement("span");
    route.className = "request-item-route";
    route.textContent = `${record.api.toUpperCase()} · ${record.route}`;

    const status = document.createElement("span");
    status.className = `mini-status ${record.status}`;
    status.title = statusLabels[record.status] || record.status;

    meta.append(route, status);
    button.append(top, meta);
    button.addEventListener("click", () => {
      state.selectedId = id;
      record.displayContent = record.content;
      record.displayReasoning = record.reasoning;
      renderList();
      renderSelected();
    });
    container.appendChild(button);
  }
}

function renderSelected() {
  const record = state.selectedId ? state.requests.get(state.selectedId) : null;
  if (!record) {
    $("modelName").textContent = "尚无请求";
    $("requestStatus").className = "status-badge idle";
    $("requestStatus").textContent = "空闲";
    $("requestMetadata").textContent = "打开此窗口后，其他程序调用本地 API 不会被暂停或最小化。";
    $("requestId").textContent = "--";
    $("answerText").textContent = "等待模型响应。";
    $("reasoningText").textContent = "当前请求没有推理内容。";
    $("answerStats").textContent = "0 字符";
    $("reasoningStats").textContent = "0 字符";
    $("errorCard").hidden = true;
    $("streamCursor").hidden = true;
    updateStreamingState({ status: "idle" });
    return;
  }

  $("modelName").textContent = record.model;
  $("requestStatus").className = `status-badge ${record.status}`;
  $("requestStatus").textContent = statusLabels[record.status] || record.status;
  $("requestId").textContent = record.request_id;
  $("requestId").title = record.request_id;

  const metadata = [
    `${record.api.toUpperCase()} ${record.route}`,
    `来源 ${record.source}`,
    formatTime(record.started_at),
    record.stream ? "上游流式" : "上游非流式",
    formatDuration(record.elapsed_ms),
  ];
  if (record.status_code !== null) metadata.push(`HTTP ${record.status_code}`);
  if (record.user_agent) metadata.push(record.user_agent);
  $("requestMetadata").textContent = metadata.join(" · ");

  renderOutput(record);
  updateStats(record);
  updateStreamingState(record);

  $("errorCard").hidden = !record.error;
  $("errorText").textContent = record.error || "";
}

function renderOutput(record) {
  $("answerText").textContent = record.displayContent || (record.status === "streaming" ? "模型正在生成……" : "(回答内容为空)");
  $("reasoningText").textContent = record.displayReasoning || "当前请求没有推理内容。";
  $("streamCursor").hidden = record.status !== "streaming";
  scrollIfNeeded($("answerScroll"));
  if ($("reasoningCard").open) scrollIfNeeded($("reasoningScroll"));
}

function updateStats(record) {
  $("answerStats").textContent = `${record.content.length} 字符`;
  $("reasoningStats").textContent = `${record.reasoning.length} 字符`;
}

function updateStreamingState(record) {
  const indicator = $("streamIndicator");
  const status = record.status || "idle";
  indicator.className = `stream-indicator ${status}`;
  const labels = {
    streaming: "流式接收中",
    complete: "接收完成",
    error: "接收失败",
    cancelled: "连接已取消",
    idle: "等待",
  };
  indicator.lastChild.textContent = labels[status] || status;
}

function scrollIfNeeded(element) {
  if ($("autoScroll").checked) {
    element.scrollTop = element.scrollHeight;
  }
}

function advanceText(record, field, displayField) {
  const target = record[field];
  const current = record[displayField];
  const diff = target.length - current.length;
  if (diff <= 0) return false;

  let step = Math.max(1, Math.ceil(diff / 28));
  if (diff > 5000) step = Math.min(diff, 500);
  else if (diff > 1000) step = Math.min(diff, 120);
  record[displayField] = target.slice(0, current.length + step);
  return true;
}

setInterval(() => {
  let selectedChanged = false;
  for (const record of state.requests.values()) {
    const changed = advanceText(record, "content", "displayContent") |
      advanceText(record, "reasoning", "displayReasoning");
    if (changed && record.request_id === state.selectedId) selectedChanged = true;
  }
  if (selectedChanged) {
    const record = state.requests.get(state.selectedId);
    if (record) renderOutput(record);
  }
}, 24);

$("copyBtn").addEventListener("click", async () => {
  const record = state.selectedId ? state.requests.get(state.selectedId) : null;
  if (!record?.content) {
    toast("当前没有可复制的回答", true);
    return;
  }
  try {
    await navigator.clipboard.writeText(record.content);
    toast("回答已复制");
  } catch {
    toast("浏览器未允许访问剪贴板", true);
  }
});

$("clearBtn").addEventListener("click", async () => {
  if (!confirm("清空服务内存中的实时响应记录？此操作不会影响 API。")) return;
  try {
    const response = await fetch("/admin/monitor/history", { method: "DELETE" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    toast("记录已清空");
  } catch (error) {
    toast(`清空失败：${error.message}`, true);
  }
});

$("reconnectBtn").addEventListener("click", connect);
$("autoScroll").addEventListener("change", () => {
  if ($("autoScroll").checked) {
    scrollIfNeeded($("answerScroll"));
    scrollIfNeeded($("reasoningScroll"));
  }
});

connect();
