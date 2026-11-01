(() => {
  "use strict";
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const token = I18N.token;
  const PLATFORM_NAMES = { bilibili: "哔哩哔哩", youtube: "YouTube", missevan: "猫耳FM" };

  let state = null;
  let page = "home";
  let tab = "翻译";
  let lastHeadId = null;
  let editingPresets = {};
  let editingPresetName = "";
  let qrTimer = null;
  let qrId = "";
  let youtubeImport = null;
  let roomTimer = null;
  let draftTimer = null;
  let dialogCallbacks = { ok: null, secondary: null };

  class ApiError extends Error {
    constructor(title, message, action = "") {
      super(message);
      this.title = title;
      this.action = action;
    }
  }

  // ------------------------------------------------------------------ helpers
  async function api(path, body) {
    let response;
    try {
      response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Token": token },
        body: JSON.stringify(body || {}),
      });
    } catch (error) {
      throw new ApiError("连接中断", "与程序的连接中断，正在重新连接…");
    }
    let data = null;
    try { data = await response.json(); } catch (error) { /* handled below */ }
    if (!response.ok || !data || data.ok === false) {
      const info = (data && data.error) || {};
      throw new ApiError(info.title || "出错了", info.message || "发生了意外错误，请重试。", info.action || "");
    }
    if (data.state) applyState(data.state);
    return data;
  }

  async function get(path) {
    const response = await fetch(path, { headers: { "X-Token": token } });
    if (!response.ok) throw new ApiError("出错了", "发生了意外错误，请重试。");
    return response.json();
  }

  function source(text) { return text.replace(/\\n/g, "\n"); }

  function applyI18n(root = document) {
    $$("[data-i18n]", root).forEach((el) => {
      el.dataset.src = el.dataset.src || source(el.dataset.i18n);
      el.textContent = t(el.dataset.src);
    });
    [["i18nPh", "placeholder"], ["i18nTitle", "title"], ["i18nAria", "aria-label"], ["i18nEmpty", "data-empty"]].forEach(([key, attr]) => {
      const dataAttr = key.replace(/[A-Z]/g, (c) => "-" + c.toLowerCase());
      $$(`[data-${dataAttr}]`, root).forEach((el) => el.setAttribute(attr, t(el.dataset[key])));
    });
  }

  function setValue(el, value) {
    if (el === document.activeElement && el.tagName !== "SELECT") return;
    if (el.value !== String(value)) el.value = value;
  }

  function fillSelect(el, items, selected, label = (item) => t(item)) {
    const signature = JSON.stringify([items, I18N.language]);
    if (el.dataset.signature !== signature) {
      el.dataset.signature = signature;
      el.textContent = "";
      items.forEach((item) => {
        const option = document.createElement("option");
        option.value = item;
        option.textContent = label(item);
        el.appendChild(option);
      });
    }
    if (selected !== undefined && el.value !== selected) el.value = selected;
  }

  function toast(message, kind = "") {
    const el = document.createElement("div");
    el.className = "toast " + kind;
    el.textContent = message;
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), kind === "error" ? 7000 : 4000);
  }

  function hide(id) { $(id).hidden = true; }
  function show(id) { $(id).hidden = false; }

  function dialog({ title, message, ok = "好的", onOk = null, secondary = "", onSecondary = null }) {
    $("#message-title").textContent = t(title);
    $("#message-body").textContent = t(message);
    $("#message-ok").textContent = t(ok);
    const second = $("#message-secondary");
    second.hidden = !secondary;
    second.textContent = secondary ? t(secondary) : "";
    dialogCallbacks = { ok: onOk, secondary: onSecondary };
    show("#modal-message");
    $("#message-ok").focus();
  }

  function showError(error) {
    if (!(error instanceof ApiError)) error = new ApiError("出错了", "发生了意外错误，请重试。");
    const options = { title: error.title, message: error.message };
    if (error.action === "settings") {
      Object.assign(options, { secondary: "设置", onSecondary: () => showPage("settings", "翻译") });
    } else if (error.action === "login") {
      Object.assign(options, { secondary: "登录 / 导入 Cookie", onSecondary: openLogin });
    } else if (error.action === "confirm_auto") {
      Object.assign(options, { ok: "继续", onOk: () => start(true), secondary: "取消" });
    } else if (error.action === "room_url") {
      options.onOk = () => $("#room-url").focus();
    }
    dialog(options);
  }

  async function run(button, task) {
    if (button) button.disabled = true;
    try { return await task(); } catch (error) { showError(error); } finally { if (button) button.disabled = false; }
  }

  // ------------------------------------------------------------------- render
  function applyState(next) {
    const notices = state && state.startup_notices;
    state = next;
    if (notices && !state.startup_notices) state.startup_notices = notices;
    render();
  }

  function applyInterface() {
    const ui = state.interface;
    I18N.language = ui.resolved_language;
    document.documentElement.lang = ui.resolved_language;
    document.documentElement.dataset.theme = ui.theme;
    document.title = t("同传字幕");
    ["#theme-button", "#theme-button-2"].forEach((id) => { $(id).textContent = t(ui.theme === "light" ? "深色" : "浅色"); });
    ["#language-select", "#language-select-2"].forEach((id) => {
      fillSelect($(id), Object.keys(ui.languages), ui.resolved_language, (code) => ui.languages[code]);
    });
    applyI18n();
  }

  function loginLabels() {
    const platform = state.room.platform;
    const site = PLATFORM_NAMES[platform];
    const name = state.login[platform];
    const status = $("#login-status");
    status.textContent = site + " · " + (name ? t("聊天账号：") + name : t("聊天账号：未登录"));
    status.classList.toggle("ok", Boolean(name));
    $("#login-button").textContent = site + " · " + t("登录 / 导入 Cookie");
  }

  function renderReview() {
    const retention = $("#queue-retention");
    if (document.activeElement !== retention) {
      retention.value = state.subtitle_settings.retained_sentences;
    }
    const pending = state.pending;
    $("#review-title").textContent = t("待发送队列") + " · " + pending.length + " " + t("条待处理");

    const head = pending[0];
    const text = $("#draft-text");
    if (!head) {
      lastHeadId = null;
      text.value = "";
      $("#draft-original").textContent = t("等待翻译…");
    } else {
      if (head.id !== lastHeadId) {
        lastHeadId = head.id;
        text.value = state.draft;
      }
      $("#draft-original").textContent =
        (head.target_language ? "[" + head.target_language + "]\n" : "") +
        (head.received_at ? t("[音频接收 ") + head.received_at + "]\n" : "") + head.original;
    }
    text.disabled = !head || state.sending;
    $("#send-button").disabled = !head || state.sending || !head.can_send;
    $("#send-button").textContent = t(state.sending ? "正在发送…" : "发送到直播间");
    $("#skip-button").disabled = !head || state.sending;

    const status = state.chat_status;
    const statusEl = $("#chat-status");
    statusEl.textContent = status.message ? t(status.message) : "";
    statusEl.className = "chat-status " + (status.message ? (status.success ? "ok" : "error") : "");

    const upcoming = pending.slice(1);
    $("#queue").hidden = upcoming.length === 0;
    $("#queue-title").textContent = t("待发送队列") + " · " + upcoming.length;
    const list = $("#queue-list");
    list.textContent = "";
    upcoming.forEach((item, index) => {
      const row = document.createElement("div");
      row.className = "queue-item";
      const original = document.createElement("div");
      original.className = "orig";
      const clock = item.received_at ? " [" + item.received_at.slice(11, 19) + "]" : "";
      original.textContent = (index + 1) + "." + clock + t(" 原文：") + item.original;
      const translated = document.createElement("div");
      translated.className = "trans";
      translated.textContent = (item.target_language ? "[" + item.target_language + "] " : "") + t("译文：") + item.message;
      row.append(original, translated);
      list.appendChild(row);
    });
  }

  function renderHome() {
    const s = state;
    $("#status-dot").className = "dot " + s.status.kind;
    $("#status-title").textContent = t(s.status.title);
    $("#status-detail").textContent = t(s.status.detail);

    const locked = s.running;
    fillSelect($("#platform-select"), Object.keys(s.room.platforms), s.room.platform, (key) => s.room.platforms[key]);
    fillSelect($("#audio-input"), s.audio_inputs, s.audio_input);
    fillSelect($("#microphone-select"), s.microphones, s.microphone);
    fillSelect($("#source-language"), s.source_languages, s.source_language);
    const languages = $("#target-language");
    if (languages.dataset.signature !== JSON.stringify(s.target_languages)) {
      languages.dataset.signature = JSON.stringify(s.target_languages);
      languages.replaceChildren(...s.target_languages.map(name => {
        const label = document.createElement("label");
        label.className = "check";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = name;
        const text = document.createElement("span");
        text.dataset.i18n = name;
        text.textContent = t(name);
        label.append(input, text);
        return label;
      }));
    }
    const selected = s.selected_target_languages || [s.target_language];
    languages.querySelectorAll("input").forEach(input => {
      input.checked = selected.includes(input.value);
      input.disabled = locked;
    });
    const codes = { "简体中文": "zh-CN", "繁體中文": "zh-TW", "英语": "en", "日语": "ja", "韩语": "ko" };
    fillSelect($("#chat-language"), selected.map(name => codes[name]),
      s.chat_delivery ? s.chat_delivery.language : codes[selected[0]],
      code => t(Object.keys(codes).find(name => codes[name] === code) || code));
    $("#chat-language").disabled = locked;
    if (document.activeElement !== $("#chat-template")) {
      $("#chat-template").value = s.subtitle_settings.chat_template || "【{translation}】";
    }
    const delivery = s.chat_delivery;
    $("#chat-limit-hint").textContent = delivery
      ? t("超长自动拆分 · 每条上限 ") + delivery.max_length + t(" · 至少间隔 ") + delivery.interval +
        t(" 秒。应用使用保守限制；房间慢速模式或账号限制可能更严格，网站拒绝时停止发送。")
      : "";
    setValue($("#room-url"), s.room.url);
    $("#microphone-row").hidden = s.audio_input !== "麦克风";
    renderDesktopOverlay();
    const automatic = s.chat_mode === "自动发送";
    const mode = $("#chat-mode");
    mode.textContent = t(automatic ? "自动发送" : "手动发送");
    mode.setAttribute("aria-pressed", String(automatic));
    ["#room-url", "#platform-select", "#audio-input", "#microphone-select", "#refresh-microphones", "#chat-mode", "#login-button"]
      .forEach((id) => { $(id).disabled = locked; });
    loginLabels();

    const start = $("#start-button");
    start.className = "btn big " + (locked && !s.busy ? "stop" : "primary");
    start.disabled = s.busy;
    start.textContent = t(s.stopping ? "正在停止…" : s.busy ? "正在结束…" : locked ? "■  停止字幕" : "▶  开始字幕");
    $("#service-summary").textContent = t(s.api.summary);
    renderReview();
  }

  function renderDesktopOverlay() {
    const overlay = state.desktop_overlay || { available: false, open: false, locked: false };
    const toggle = $("#desktop-overlay-toggle");
    toggle.hidden = !overlay.available;
    toggle.textContent = t(overlay.open ? "关闭字幕悬浮窗" : "打开字幕悬浮窗");
    toggle.className = "btn grow " + (overlay.open ? "" : "primary");
    $("#desktop-overlay-unlock").hidden = !(overlay.open && overlay.locked);
    $("#desktop-overlay-hint").textContent = t(
      !overlay.available ? "字幕悬浮窗在此模式下不可用，请使用下面的浏览器字幕页。"
        : overlay.open && overlay.locked ? "字幕悬浮窗已锁定（鼠标可穿透）。点「解锁悬浮窗」恢复拖动和工具栏。"
          : "悬浮窗始终置顶，可拖动、右下角调整大小；鼠标移入显示工具栏。"
    );
    const pause = $("#pause-toggle");
    pause.hidden = !state.running;
    pause.textContent = t(state.paused ? "继续字幕" : "暂停字幕");
  }

  function renderSettingsStatic() {
    $("#records-folder").value = state.records_folder;
    $("#opt-display-mode").value = state.subtitle_settings.display_mode;
    const keyStatus = $("#key-status");
    keyStatus.textContent = t(state.api.key_saved ? "已有密钥已保存；留空会继续使用。" : "API Key 可选；无 Key 的服务可以留空。");
    keyStatus.style.color = `var(--${state.api.key_saved ? "ok" : "warn"})`;
  }

  function render() {
    if (!state) return;
    if (state.startup_error) {
      $("#startup-error-title").textContent = t(state.startup_error.title);
      $("#startup-error-message").textContent = t(state.startup_error.message);
      applyI18n();
      show("#startup-error");
      hide("#app");
      return;
    }
    hide("#startup-error");
    show("#app");
    applyInterface();
    renderHome();
    renderSettingsStatic();
    const url = location.origin + "/overlay?t=" + encodeURIComponent(token);
    $("#overlay-url").value = url;
  }

  // -------------------------------------------------------------------- pages
  function showPage(name, tabName) {
    page = name;
    if (tabName) tab = tabName;
    $("#page-home").hidden = name !== "home";
    $("#page-settings").hidden = name !== "settings";
    if (name === "settings") {
      loadSettingsForm();
      selectTab(tab);
    }
    window.scrollTo(0, 0);
  }

  function selectTab(name) {
    tab = name;
    $$(".tab").forEach((button) => button.setAttribute("aria-selected", String(button.dataset.tab === name)));
    $$("[data-panel]").forEach((panel) => { panel.hidden = panel.dataset.panel !== name; });
    if (name === "记录") loadExportSessions();
  }

  // ------------------------------------------------------------ home actions
  async function postHome(values) {
    return api("/api/home", values);
  }

  async function flushRoom() {
    clearTimeout(roomTimer);
    roomTimer = null;
    await postHome({ room_url: $("#room-url").value });
  }

  async function start(confirmAuto = false) {
    clearTimeout(roomTimer);
    const values = {
      room_url: $("#room-url").value,
      audio_input: $("#audio-input").value,
      microphone: $("#microphone-select").value,
      source_language: $("#source-language").value,
      selected_target_languages: Array.from($("#target-language").querySelectorAll("input:checked"), input => input.value),
      chat_mode: state.chat_mode,
      confirm_auto: confirmAuto,
    };
    await run($("#start-button"), () => api("/api/start", values));
  }

  async function openLogin() {
    try { await flushRoom(); } catch (error) { showError(error); return; }
    const platform = state.room.platform;
    $("#login-title").textContent = t("连接 ") + PLATFORM_NAMES[platform] + t(" 聊天账号");
    $("#qr-button").hidden = platform !== "bilibili";
    $("#cookie-text").value = "";
    setLoginResult("");
    show("#modal-login");
    $("#cookie-text").focus();
  }

  function setLoginResult(message, kind = "") {
    const el = $("#login-result");
    el.textContent = message ? t(message) : "";
    el.className = "result " + kind;
  }

  async function submitCookies(firefox) {
    const platform = state.room.platform;
    const text = $("#cookie-text").value;
    if (!firefox && !text.trim()) { setLoginResult("请先粘贴 Cookie 内容。", "error"); return; }
    $("#cookie-text").value = "";
    const button = firefox ? $("#firefox-button") : $("#cookie-verify");
    setLoginResult(firefox ? "请稍候，正在读取 Firefox Cookie 并验证登录…" : "正在验证登录…");
    button.disabled = true;
    try {
      const result = await api(firefox ? "/api/login/firefox" : "/api/login/cookies", { platform, text });
      handleLoginResult(result);
    } catch (error) {
      setLoginResult((error.message && t(error.message)) || "", "error");
    } finally {
      button.disabled = false;
    }
  }

  function handleLoginResult(result) {
    if (result.stage === "choose") {
      openYoutubeChoice(result);
      return;
    }
    hide("#modal-login");
    toast(result.name + t(" 已登录；Cookie 仅保存在内存中"));
  }

  function openYoutubeChoice(result) {
    youtubeImport = result;
    const box = $("#youtube-choices");
    box.textContent = "";
    result.channels.forEach((label, index) => {
      const row = document.createElement("label");
      row.className = "choice";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "youtube-channel";
      input.value = String(index);
      input.checked = result.preselect === index;
      const text = document.createElement("span");
      text.textContent = label;
      row.append(input, text);
      box.appendChild(row);
    });
    $("#youtube-hint").className = "small";
    $("#youtube-hint").textContent = t("选择用于发送聊天的 YouTube 账号或频道。");
    show("#modal-youtube");
  }

  async function confirmYoutube() {
    const chosen = $("input[name=youtube-channel]:checked");
    if (!chosen) {
      $("#youtube-hint").style.color = "var(--error)";
      return;
    }
    $("#youtube-hint").style.color = "";
    try {
      const result = await api("/api/login/youtube/confirm", { import_id: youtubeImport.import_id, index: Number(chosen.value) });
      youtubeImport = null;
      hide("#modal-youtube");
      hide("#modal-login");
      toast(result.name + t(" 已登录；Cookie 仅保存在内存中"));
    } catch (error) {
      showError(error);
    }
  }

  async function cancelYoutube() {
    youtubeImport = null;
    hide("#modal-youtube");
    try { await api("/api/login/youtube/cancel"); } catch (error) { /* nothing to undo */ }
  }

  async function startQr() {
    show("#modal-qr");
    $("#qr-image").hidden = true;
    $("#qr-status").textContent = t("正在生成二维码…");
    try {
      const result = await api("/api/login/qr/start");
      qrId = result.id;
      $("#qr-image").src = result.image;
      $("#qr-image").hidden = false;
      $("#qr-status").textContent = t(result.message);
      pollQr();
    } catch (error) {
      $("#qr-status").textContent = t(error.message);
    }
  }

  function pollQr() {
    clearTimeout(qrTimer);
    qrTimer = setTimeout(async () => {
      if ($("#modal-qr").hidden) return;
      try {
        const status = await get("/api/login/qr/status?id=" + encodeURIComponent(qrId));
        if (status.state === "done") {
          closeQr(false);
          hide("#modal-login");
          toast(status.message + t(" 已登录；Cookie 仅保存在内存中"));
          return;
        }
        $("#qr-status").textContent = t(status.message);
        if (status.state === "expired" || status.state === "failed") return;
      } catch (error) { /* keep polling; the banner shows lost connections */ }
      pollQr();
    }, 1500);
  }

  async function closeQr(cancel = true) {
    clearTimeout(qrTimer);
    hide("#modal-qr");
    if (cancel) { try { await api("/api/login/qr/cancel"); } catch (error) { /* ignore */ } }
  }

  async function copy(inputId) {
    const input = $(inputId);
    try {
      await navigator.clipboard.writeText(input.value);
    } catch (error) {
      input.select();
      document.execCommand("copy");
    }
    toast(t("已复制网址"));
  }

  // ---------------------------------------------------------------- settings
  function loadSettingsForm() {
    const settings = state.subtitle_settings;
    editingPresets = JSON.parse(JSON.stringify(settings.presets));
    fillSelect($("#opt-display-mode"), ["边听边出", "说完再出"], settings.display_mode);
    fillSelect($("#opt-preset"), Object.keys(editingPresets), settings.preset);
    $$("[data-opt]").forEach((el) => {
      const value = settings[el.dataset.opt];
      if (value === undefined) return;
      if (el.type === "checkbox") el.checked = value;
      else el.value = value;
    });
    $$("[data-slider]").forEach((slider) => { slider.value = settings[slider.dataset.slider]; });
    $("#api-base").value = state.api.base;
    $("#api-model").value = state.api.model;
    $("#api-model").hidden = false;
    $("#model-select").hidden = true;
    $("#api-key").value = "";
    $("#api-result").textContent = "";
    $("#export-result").textContent = "";
    if (state.api.base) detectModels(true);
  }

  let settingsSave = Promise.resolve();
  const optionTimers = new Map();

  function saveOptions(values) {
    settingsSave = settingsSave.then(() => api("/api/settings/subtitle", values)).catch(showError);
    return settingsSave;
  }

  function saveOption(el) {
    const name = el.dataset.opt;
    const value = el.type === "checkbox" ? el.checked
      : el.type === "number" ? (el.value === "" ? null : Number(el.value)) : el.value;
    if (name === "distinguish_speakers" && value) {
      el.checked = false;
      dialog({
        title: "区分说话人",
        message: "首次开启将下载约 28 MB 本机声纹模型。音频不上传，下载期间请等待。标签不加入弹幕。继续吗？",
        ok: "继续", secondary: "取消",
        onOk: async () => {
          el.disabled = true;
          setResult("#speaker-download-result", t("正在下载并校验说话人模型，请等待…"));
          try {
            settingsSave = settingsSave.then(() => api("/api/settings/subtitle", {
              distinguish_speakers: true, confirm_speaker_download: true,
            }));
            await settingsSave;
            el.checked = true;
            setResult("#speaker-download-result", t("说话人模型已就绪，区分说话人已开启。"), "success");
          } catch (error) {
            settingsSave = Promise.resolve();
            el.checked = false;
            setResult("#speaker-download-result", t("说话人模型下载失败，未开启。请检查网络后重试。"), "error");
            showError(error);
          } finally {
            el.disabled = false;
          }
        },
      });
      return;
    }
    return saveOptions({ [name]: value });
  }

  function setResult(id, message, kind = "") {
    const el = $(id);
    el.textContent = message;
    el.className = "result " + kind;
  }

  const MANUAL_MODEL = "__manual__";

  function fillModelSelect(models) {
    const select = $("#model-select");
    const input = $("#api-model");
    const current = input.value.trim();
    select.textContent = "";
    models.forEach((id) => {
      const option = document.createElement("option");
      option.value = id;
      option.textContent = id;
      select.appendChild(option);
    });
    const manual = document.createElement("option");
    manual.value = MANUAL_MODEL;
    manual.textContent = t("其他（手动输入）…");
    select.appendChild(manual);
    select.hidden = models.length === 0;
    if (models.includes(current)) select.value = current;
    else if (current) select.value = MANUAL_MODEL;
    else { select.value = models[0]; input.value = models[0]; }
    input.hidden = !select.hidden && select.value !== MANUAL_MODEL;
  }

  function onModelSelect() {
    const select = $("#model-select");
    const input = $("#api-model");
    if (select.value === MANUAL_MODEL) {
      input.hidden = false;
      input.focus();
    } else {
      input.value = select.value;
      input.hidden = true;
    }
  }

  async function detectModels(silent = false) {
    const button = $("#detect-models");
    button.disabled = true;
    button.textContent = t("正在检测…");
    if (!silent) setResult("#api-result", t("正在读取模型列表…"));
    try {
      const result = await api("/api/models/detect", { base: $("#api-base").value, key: $("#api-key").value });
      fillModelSelect(result.models);
      if (!silent) setResult("#api-result", t("检测完成，请从下拉列表选择模型。模型数量：") + result.models.length, "ok");
    } catch (error) {
      if (!silent) setResult("#api-result", t("检测失败：") + t(error.message), "error");
    } finally {
      button.disabled = false;
      button.textContent = t("检测模型");
    }
  }

  async function saveApi(test = false) {
    const body = { base: $("#api-base").value, model: $("#api-model").value, key: $("#api-key").value };
    const button = test ? $("#test-api") : $("#save-api");
    button.disabled = true;
    try {
      if (test) {
        setResult("#api-result", t("正在连接翻译服务…"));
        const result = await api("/api/settings/test", body);
        $("#api-key").value = "";
        setResult("#api-result", result.connected ? t("连接成功，翻译服务可以正常使用。") : t("连接失败：") + t(result.error),
          result.connected ? "ok" : "error");
      } else {
        await api("/api/settings/api", body);
        $("#api-key").value = "";
        setResult("#api-result", t("设置已保存。"), "ok");
      }
    } catch (error) {
      setResult("#api-result", "", "");
      showError(error);
    } finally {
      button.disabled = false;
    }
  }

  function clearKey() {
    if (!state.api.key_saved) return;
    dialog({
      title: "清除 API Key",
      message: "清除这台电脑上已保存的 API Key？",
      ok: "清除已保存的 Key",
      onOk: async () => {
        try {
          await api("/api/settings/clear-key");
          $("#api-key").value = "";
          setResult("#api-result", t("已清除 API Key。"), "warn");
        } catch (error) { showError(error); }
      },
      secondary: "取消",
    });
  }

  function editPreset() {
    editingPresetName = $("#opt-preset").value;
    const content = editingPresets[editingPresetName] || { background: "", glossary: "" };
    $("#preset-title").textContent = t(editingPresetName);
    $("#preset-background").value = content.background;
    $("#preset-glossary").value = content.glossary;
    show("#modal-preset");
  }

  let recordsInfo = { enabled: true, title: "", message: "" };

  async function loadExportSessions() {
    try {
      const { sessions, records } = await get("/api/records");
      if (records) recordsInfo = records;
      const select = $("#export-session");
      const previous = select.value;
      select.dataset.signature = "";
      fillSelect(select, sessions, undefined, (name) => name);
      select.value = sessions.includes(previous) ? previous : (sessions[sessions.length - 1] || "");
      select.disabled = !sessions.length;
      $("#export-sent").disabled = !sessions.length;
      if (!sessions.length) {
        const message = recordsInfo.enabled ? "还没有已发送或已跳过的字幕，请先发送或跳过一条字幕。" : recordsInfo.message;
        const option = document.createElement("option");
        option.value = "";
        option.textContent = t(message);
        select.append(option);
        setResult("#export-result", t(message), "error");
      } else {
        setResult("#export-result", "", "");
      }
    } catch (error) { showError(error); }
  }

  async function exportSent() {
    const button = $("#export-sent");
    const session = $("#export-session").value;
    if (!session) {
      setResult("#export-result", t(recordsInfo.enabled ? "请选择有已发送或已跳过字幕的会话。" : recordsInfo.message), "error");
      return;
    }
    button.disabled = true;
    try {
      const result = await api("/api/records/export", { session });
      const name = (path) => path.split(/[\\/]/).pop();
      setResult("#export-result", t("已导出：") + name(result.srt) + "\n" + name(result.csv) + "\n" + t("保存位置：") + result.folder, "ok");
      $("#export-result").style.whiteSpace = "pre-line";
    } catch (error) {
      setResult("#export-result", t(error.title) + "：" + t(error.message), "error");
    } finally {
      button.disabled = false;
    }
  }

  // -------------------------------------------------------------- wiring
  function wire() {
    $("#message-ok").addEventListener("click", () => {
      hide("#modal-message");
      const callback = dialogCallbacks.ok;
      dialogCallbacks = { ok: null, secondary: null };
      if (callback) callback();
    });
    $("#message-secondary").addEventListener("click", () => {
      hide("#modal-message");
      const callback = dialogCallbacks.secondary;
      dialogCallbacks = { ok: null, secondary: null };
      if (callback) callback();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      if (!$("#modal-message").hidden) $("#message-ok").click();
      else if (!$("#modal-youtube").hidden) cancelYoutube();
      else if (!$("#modal-qr").hidden) closeQr();
      else if (!$("#modal-preset").hidden) hide("#modal-preset");
      else if (!$("#modal-login").hidden) hide("#modal-login");
      else if (!$("#modal-quit").hidden) hide("#modal-quit");
    });

    const interfaceChange = (values) => run(null, () => api("/api/interface", values));
    ["#theme-button", "#theme-button-2"].forEach((id) => $(id).addEventListener("click", () => {
      interfaceChange({ theme: state.interface.theme === "light" ? "dark" : "light" });
    }));
    ["#language-select", "#language-select-2"].forEach((id) => $(id).addEventListener("change", (event) => {
      interfaceChange({ language: event.target.value });
    }));
    $("#settings-button").addEventListener("click", () => showPage("settings"));
    $("#back-button").addEventListener("click", () => showPage("home"));
    $$(".tab").forEach((button) => button.addEventListener("click", () => selectTab(button.dataset.tab)));

    $("#room-url").addEventListener("input", () => {
      clearTimeout(roomTimer);
      roomTimer = setTimeout(() => run(null, () => postHome({ room_url: $("#room-url").value })), 350);
    });
    $("#room-url").addEventListener("keydown", (event) => { if (event.key === "Enter") start(); });
    $("#platform-select").addEventListener("change", (event) => run(null, () => postHome({ platform: event.target.value })));
    $("#audio-input").addEventListener("change", async (event) => {
      await run(null, () => postHome({ audio_input: event.target.value }));
      if (event.target.value === "麦克风" && state.microphones.length <= 1) refreshMicrophones();
    });
    $("#microphone-select").addEventListener("change", (event) => run(null, () => postHome({ microphone: event.target.value })));
    $("#source-language").addEventListener("change", (event) => run(null, () => postHome({ source_language: event.target.value })));
    $("#target-language").addEventListener("change", () => {
      const selected = Array.from($("#target-language").querySelectorAll("input:checked"), input => input.value);
      run(null, async () => {
        try { await postHome({ selected_target_languages: selected }); }
        finally { renderHome(); }
      });
      $("#reset-chat-template").addEventListener("click", () => saveOptions({ chat_template_custom: false }));
    });
    $("#chat-mode").addEventListener("click", () => {
      run(null, () => postHome({ chat_mode: state.chat_mode === "自动发送" ? "手动确认" : "自动发送" }));
    });
    $("#refresh-microphones").addEventListener("click", refreshMicrophones);
    $("#login-button").addEventListener("click", openLogin);
    $("#start-button").addEventListener("click", () => {
      if (state.running) run($("#start-button"), () => api("/api/stop"));
      else start();
    });
    $("#send-button").addEventListener("click", () => {
      clearTimeout(draftTimer);
      run($("#send-button"), () => api("/api/chat/send", { text: $("#draft-text").value }));
    });
    $("#skip-button").addEventListener("click", () => {
      clearTimeout(draftTimer);
      run($("#skip-button"), () => api("/api/chat/skip", { text: $("#draft-text").value }));
    });
    $("#draft-text").addEventListener("input", () => {
      clearTimeout(draftTimer);
      draftTimer = setTimeout(() => api("/api/draft", { text: $("#draft-text").value }).catch(() => {}), 400);
    });
    $("#copy-overlay").addEventListener("click", () => copy("#overlay-url"));
    $("#open-overlay").addEventListener("click", () => window.open("/overlay?t=" + encodeURIComponent(token), "subtitle-overlay"));
    $("#desktop-overlay-toggle").addEventListener("click", () => {
      const overlay = state.desktop_overlay || {};
      run($("#desktop-overlay-toggle"), () => api(overlay.open ? "/api/overlay/close" : "/api/overlay/open"));
    });
    $("#desktop-overlay-unlock").addEventListener("click", () => run($("#desktop-overlay-unlock"), () => api("/api/overlay/unlock")));
    $("#pause-toggle").addEventListener("click", () => run($("#pause-toggle"), () => api("/api/pause")));
    $("#quit-button").addEventListener("click", () => show("#modal-quit"));
    $("#quit-cancel").addEventListener("click", () => hide("#modal-quit"));
    $("#quit-confirm").addEventListener("click", async () => {
      hide("#modal-quit");
      try { await api("/api/quit"); } catch (error) { /* the server may already be closing */ }
      quitting = true;
      if (events) events.close();
      hide("#app");
      hide("#disconnected");
      applyI18n();
      show("#goodbye");
    });

    $("#login-close").addEventListener("click", () => hide("#modal-login"));
    $("#cookie-verify").addEventListener("click", () => submitCookies(false));
    $("#firefox-button").addEventListener("click", () => submitCookies(true));
    $("#qr-button").addEventListener("click", startQr);
    $("#qr-close").addEventListener("click", () => closeQr());
    $("#youtube-confirm").addEventListener("click", confirmYoutube);
    $("#youtube-cancel").addEventListener("click", cancelYoutube);

    $$("[data-slider]").forEach((slider) => {
      const number = $(`[data-opt="${slider.dataset.slider}"]`);
      slider.addEventListener("input", () => {
        number.value = slider.value;
        clearTimeout(optionTimers.get(number.dataset.opt));
        optionTimers.set(number.dataset.opt, setTimeout(() => saveOption(number), 150));
      });
      slider.addEventListener("change", () => {
        clearTimeout(optionTimers.get(number.dataset.opt));
        saveOption(number);
      });
      number.addEventListener("input", () => { if (number.value !== "") slider.value = number.value; });
    });
    $$("[data-opt]").forEach((el) => el.addEventListener("change", () => {
      clearTimeout(optionTimers.get(el.dataset.opt));
      saveOption(el);
    }));
    $("#edit-preset").addEventListener("click", editPreset);
    $("#preset-cancel").addEventListener("click", () => hide("#modal-preset"));
    $("#preset-apply").addEventListener("click", () => {
      editingPresets[editingPresetName] = {
        background: $("#preset-background").value,
        glossary: $("#preset-glossary").value,
      };
      hide("#modal-preset");
      saveOptions({ presets: editingPresets });
    });
    $("#detect-models").addEventListener("click", () => detectModels());
    $("#model-select").addEventListener("change", onModelSelect);
    $("#toggle-key").addEventListener("click", () => {
      const input = $("#api-key");
      const shown = input.type === "text";
      input.type = shown ? "password" : "text";
      $("#toggle-key").textContent = t(shown ? "显示" : "隐藏");
    });
    $("#clear-key").addEventListener("click", clearKey);
    $("#save-api").addEventListener("click", () => saveApi(false));
    $("#test-api").addEventListener("click", () => saveApi(true));
    $("#open-records").addEventListener("click", () => run($("#open-records"), () => api("/api/records/open")));
    $("#choose-records-folder").addEventListener("click", () => run($("#choose-records-folder"), () => api("/api/records/folder")));
    $("#export-sent").addEventListener("click", exportSent);
  }

  async function refreshMicrophones() {
    const result = await run($("#refresh-microphones"), () => api("/api/microphones/refresh"));
    if (result && result.warning) dialog(result.warning);
  }

  // -------------------------------------------------------------------- events
  let events = null;
  let quitting = false;

  function connectEvents() {
    events = new EventSource("/api/events?t=" + encodeURIComponent(token));
    events.onopen = () => hide("#disconnected");
    events.onerror = () => { if (!quitting) show("#disconnected"); };
    events.onmessage = (message) => {
      const event = JSON.parse(message.data);
      if (event.type === "state") applyState(event.state);
      else if (event.type === "error") showError(new ApiError(event.title, event.message));
      else if (event.type === "notice") toast(t(event.message), "error");
      else if (event.type === "resync") get("/api/snapshot").then(applyState);
    };
  }

  async function init() {
    wire();
    try {
      await I18N.load();
      applyState(await get("/api/snapshot"));
    } catch (error) {
      document.body.textContent = "";
      const message = document.createElement("p");
      message.style.padding = "24px";
      message.textContent = "Could not connect to the app. Please reopen it from Start Translation.bat.";
      document.body.appendChild(message);
      return;
    }
    if (state.startup_error) return;
    (state.startup_notices || []).forEach((notice) => dialog(notice));
    connectEvents();
  }

  init();
})();
