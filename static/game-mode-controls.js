(() => {
  "use strict";

  const nativeFetch = window.fetch.bind(window);
  const MODE_NORMAL = "normal";
  const MODE_BANNERLORD = "bannerlord";
  const TASK_NPC = "player_npc_dialogue";
  const TASK_SYSTEM_EVENT = "dynamic_event_world_state";

  let selectedMode = MODE_NORMAL;
  let selectedTestTask = TASK_NPC;

  function byId(id) {
    return document.getElementById(id);
  }

  function notify(message, isError = false) {
    if (typeof window.toast === "function") {
      window.toast(message, isError);
      return;
    }
    if (isError) console.error(message);
    else console.info(message);
  }

  async function jsonRequest(url, options = {}) {
    const response = await nativeFetch(url, options);
    const text = await response.text();
    let body;
    try {
      body = text ? JSON.parse(text) : {};
    } catch {
      body = text;
    }
    if (!response.ok) {
      const detail = typeof body === "object" && body !== null
        ? body.detail || body.error?.message || JSON.stringify(body)
        : String(body || response.statusText);
      throw new Error(`${response.status} ${response.statusText}: ${detail}`);
    }
    return body;
  }

  function setButtonSelected(button, selected) {
    button.classList.toggle("primary", selected);
    button.classList.toggle("secondary", !selected);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  }

  function updateModeUi() {
    document.querySelectorAll("[data-prompt-mode]").forEach((button) => {
      setButtonSelected(button, button.dataset.promptMode === selectedMode);
    });

    const detail = byId("promptModeDetail");
    if (detail) {
      detail.textContent = selectedMode === MODE_BANNERLORD
        ? "游戏模式：启用骑马与砍杀 2：霸主任务隔离。仅玩家与 NPC 直接交互注入提示词，外交、动态事件、世界分析等后台任务保持原样。"
        : "普通模式：所有聊天与生成请求都注入当前提示词，不区分 NPC 对话、系统事件或其他任务。";
    }

    const testDetail = byId("testTaskModeDetail");
    if (testDetail) {
      testDetail.textContent = selectedMode === MODE_BANNERLORD
        ? "当前为游戏模式。NPC 对话会注入提示词；系统/世界事件不会注入。"
        : "当前为普通模式。两个测试类型都会注入提示词；任务按钮仅用于验证请求元数据。";
    }
  }

  function updateTestTaskUi() {
    document.querySelectorAll("[data-test-task]").forEach((button) => {
      setButtonSelected(button, button.dataset.testTask === selectedTestTask);
    });
    const value = byId("testTaskTypeValue");
    if (value) value.textContent = selectedTestTask;
  }

  async function saveMode(mode) {
    selectedMode = mode === MODE_BANNERLORD ? MODE_BANNERLORD : MODE_NORMAL;
    updateModeUi();
    document.querySelectorAll("[data-prompt-mode]").forEach((button) => {
      button.disabled = true;
    });
    try {
      const result = await jsonRequest("/admin/config", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt_injection_mode: selectedMode }),
      });
      const returned = result?.config?.prompt_injection_mode;
      if (returned) selectedMode = returned === MODE_BANNERLORD
        ? MODE_BANNERLORD
        : MODE_NORMAL;
      updateModeUi();
      notify(selectedMode === MODE_BANNERLORD
        ? "已切换到游戏模式：骑马与砍杀 2：霸主"
        : "已切换到普通模式：全局提示词注入");
    } catch (error) {
      notify(error.message, true);
      await loadMode();
    } finally {
      document.querySelectorAll("[data-prompt-mode]").forEach((button) => {
        button.disabled = false;
      });
    }
  }

  async function loadMode() {
    try {
      const config = await jsonRequest("/admin/config");
      selectedMode = config.prompt_injection_mode === MODE_BANNERLORD
        ? MODE_BANNERLORD
        : MODE_NORMAL;
      updateModeUi();
    } catch (error) {
      notify(`读取运行模式失败：${error.message}`, true);
    }
  }

  function createButton(text, dataName, dataValue) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = text;
    button.dataset[dataName] = dataValue;
    return button;
  }

  function injectConfigModeControls() {
    if (byId("promptModeControls")) return;
    const promptToggle = byId("promptEnabled");
    const anchor = promptToggle?.closest(".field");
    const grid = anchor?.parentElement;
    if (!anchor || !grid) return;

    const field = document.createElement("div");
    field.className = "field span-two";
    field.id = "promptModeControls";

    const label = document.createElement("label");
    label.textContent = "提示词运行模式";

    const actions = document.createElement("div");
    actions.className = "actions";
    actions.style.marginTop = "8px";
    actions.style.marginBottom = "8px";

    const normalButton = createButton("普通模式", "promptMode", MODE_NORMAL);
    const gameButton = createButton(
      "游戏模式 · 骑马与砍杀 2：霸主",
      "promptMode",
      MODE_BANNERLORD,
    );
    normalButton.addEventListener("click", () => saveMode(MODE_NORMAL));
    gameButton.addEventListener("click", () => saveMode(MODE_BANNERLORD));
    actions.append(normalButton, gameButton);

    const detail = document.createElement("small");
    detail.id = "promptModeDetail";

    field.append(label, actions, detail);
    anchor.insertAdjacentElement("afterend", field);
  }

  function injectTestTaskControls() {
    if (byId("testTaskModeControls")) return;
    const grid = document.querySelector("#tab-test .form-grid.two");
    const messageField = byId("testMessage")?.closest(".field");
    if (!grid || !messageField) return;

    const field = document.createElement("div");
    field.className = "field span-two";
    field.id = "testTaskModeControls";

    const label = document.createElement("label");
    label.textContent = "模拟请求类型";

    const actions = document.createElement("div");
    actions.className = "actions";
    actions.style.marginTop = "8px";
    actions.style.marginBottom = "8px";

    const npcButton = createButton("模拟 NPC 对话", "testTask", TASK_NPC);
    const systemButton = createButton(
      "模拟系统 / 世界事件",
      "testTask",
      TASK_SYSTEM_EVENT,
    );
    npcButton.addEventListener("click", () => {
      selectedTestTask = TASK_NPC;
      updateTestTaskUi();
    });
    systemButton.addEventListener("click", () => {
      selectedTestTask = TASK_SYSTEM_EVENT;
      updateTestTaskUi();
    });
    actions.append(npcButton, systemButton);

    const valueLine = document.createElement("small");
    valueLine.innerHTML = "请求将携带 <code>relay_task_type</code>：<code id=\"testTaskTypeValue\"></code>";

    const detail = document.createElement("small");
    detail.id = "testTaskModeDetail";
    detail.style.marginTop = "4px";

    field.append(label, actions, valueLine, detail);
    grid.insertBefore(field, messageField);
  }

  function installTestRequestInterceptor() {
    window.fetch = async (input, init = {}) => {
      const url = typeof input === "string" ? input : input?.url || "";
      const isTestChat = url.includes("/v1/chat/completions")
        && Boolean(byId("testTaskModeControls"))
        && Boolean(byId("tab-test")?.classList.contains("active"));

      if (!isTestChat || typeof init.body !== "string") {
        return nativeFetch(input, init);
      }

      try {
        const payload = JSON.parse(init.body);
        if (payload && Array.isArray(payload.messages)) {
          payload.relay_task_type = selectedTestTask;
          init = { ...init, body: JSON.stringify(payload) };
        }
      } catch {
        // Keep the original request body if it is not JSON.
      }
      return nativeFetch(input, init);
    };
  }

  async function init() {
    injectConfigModeControls();
    injectTestTaskControls();
    installTestRequestInterceptor();
    updateTestTaskUi();
    updateModeUi();
    await loadMode();

    byId("refreshAllBtn")?.addEventListener("click", () => {
      window.setTimeout(loadMode, 250);
    });
    byId("saveConfigBtn")?.addEventListener("click", () => {
      window.setTimeout(loadMode, 350);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init, { once: true });
  } else {
    init();
  }
})();
