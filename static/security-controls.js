(() => {
  "use strict";

  const nativeFetch = window.fetch.bind(window);

  // The management test page no longer needs the local API key in JavaScript.
  // Redirect only this same-origin UI request to an internal test endpoint.
  window.fetch = (input, init = {}) => {
    const url = typeof input === "string" ? input : input?.url;
    if (url === "/v1/chat/completions" && location.pathname.startsWith("/ui")) {
      const sourceHeaders = init.headers || (input instanceof Request ? input.headers : undefined);
      const headers = new Headers(sourceHeaders || {});
      headers.delete("Authorization");
      headers.set("X-Relay-Admin-Test", "1");
      return nativeFetch("/admin/test-chat", { ...init, headers });
    }
    return nativeFetch(input, init);
  };

  function createActionButton(text, action) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary secret-action-button";
    button.textContent = text;
    button.addEventListener("click", action);
    return button;
  }

  function ensureStyle() {
    if (document.getElementById("secure-secret-style")) return;
    const style = document.createElement("style");
    style.id = "secure-secret-style";
    style.textContent = `
      .secret-security-row { display:flex; align-items:center; gap:8px; flex-wrap:wrap; margin-top:8px; }
      .secret-security-status { font-size:12px; color:#64748b; }
      .secret-security-status.ok { color:#15803d; }
      .secret-security-status.warn { color:#b45309; }
      .secret-action-button { padding:6px 10px; min-height:30px; }
    `;
    document.head.appendChild(style);
  }

  async function jsonRequest(url, options = {}) {
    const response = await nativeFetch(url, options);
    const text = await response.text();
    let body = {};
    try { body = text ? JSON.parse(text) : {}; } catch { body = { detail: text }; }
    if (!response.ok) throw new Error(body.detail || body.error || `${response.status}`);
    return body;
  }

  function sourceLabel(source) {
    return {
      environment: "环境变量",
      os_keyring: "系统凭据库",
      encrypted_file: "加密文件",
      missing: "未配置",
    }[source] || source || "未知";
  }

  function addSecretControls(inputId, secretName, allowReveal = false) {
    const input = document.getElementById(inputId);
    if (!input || input.dataset.secureControls === "1") return;
    input.dataset.secureControls = "1";
    input.value = "";
    input.autocomplete = "new-password";
    input.placeholder = "已配置时留空可保持原值";

    const row = document.createElement("div");
    row.className = "secret-security-row";
    const status = document.createElement("span");
    status.className = "secret-security-status";
    status.textContent = "正在读取安全存储状态…";
    row.appendChild(status);

    if (allowReveal) {
      row.appendChild(createActionButton("显示/复制本地 Key", async () => {
        try {
          const result = await jsonRequest("/admin/secrets/local_api_key/reveal", { method: "POST" });
          input.value = result.value || "";
          input.type = "text";
          if (navigator.clipboard && result.value) {
            await navigator.clipboard.writeText(result.value);
            status.textContent = "本地 Key 已显示并复制到剪贴板";
          } else {
            status.textContent = "本地 Key 已显示";
          }
        } catch (error) {
          status.textContent = error.message;
          status.className = "secret-security-status warn";
        }
      }));
    }

    row.appendChild(createActionButton("清除", async () => {
      if (!window.confirm("确定清除此 API Key？清除后相关请求可能立即失败。")) return;
      try {
        await jsonRequest(`/admin/secrets/${secretName}`, { method: "DELETE" });
        input.value = "";
        status.textContent = "已清除";
        status.className = "secret-security-status warn";
      } catch (error) {
        status.textContent = error.message;
        status.className = "secret-security-status warn";
      }
    }));

    input.insertAdjacentElement("afterend", row);
    return status;
  }

  async function refreshSecretStatus() {
    const upstreamStatus = addSecretControls("upstreamApiKey", "upstream_api_key", false);
    const localStatus = addSecretControls("localApiKey", "local_api_key", true);
    try {
      const result = await jsonRequest("/admin/secrets/status");
      const pairs = [
        [upstreamStatus, result.upstream_api_key],
        [localStatus, result.local_api_key],
      ];
      for (const [node, info] of pairs) {
        if (!node || !info) continue;
        node.textContent = info.configured
          ? `已安全保存 · ${sourceLabel(info.source)}${info.webui_writable ? "" : " · WebUI 只读"}`
          : "未配置";
        node.className = `secret-security-status ${info.configured ? "ok" : "warn"}`;
      }
      const recommended = document.getElementById("recommendedApiKey");
      if (recommended && result.local_api_key?.configured) {
        recommended.textContent = "已安全保存（在转发配置中点击显示）";
      }
    } catch (error) {
      for (const node of [upstreamStatus, localStatus]) {
        if (!node) continue;
        node.textContent = `安全存储状态读取失败：${error.message}`;
        node.className = "secret-security-status warn";
      }
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    ensureStyle();
    setTimeout(refreshSecretStatus, 0);
    const save = document.getElementById("saveConfigBtn");
    if (save) save.addEventListener("click", () => setTimeout(refreshSecretStatus, 700));
    const refresh = document.getElementById("refreshAllBtn");
    if (refresh) refresh.addEventListener("click", () => setTimeout(refreshSecretStatus, 500));
  });
})();
