const PROVIDERS = {
  all: { name: "全部来源", color: "#116a68" },
  codex: { name: "Codex", color: "#116a68" },
  chatgpt: { name: "ChatGPT", color: "#397b62" },
  gemini: { name: "Gemini", color: "#3b6488" },
  deepseek: { name: "DeepSeek", color: "#ad5a35" },
  deepseek_harness: { name: "DeepSeek Harness", color: "#9c5936" },
  doubao: { name: "豆包", color: "#8c4b74" },
  generic: { name: "通用导入", color: "#6f766f" },
};

const state = {
  provider: "all",
  query: "",
  conversations: [],
  selected: new Set(),
  currentId: null,
  current: null,
  previewReady: false,
  packPath: null,
};

const elements = {
  providerList: document.querySelector("#provider-list"),
  threadList: document.querySelector("#thread-list"),
  threadCount: document.querySelector("#thread-count"),
  selectAll: document.querySelector("#select-all"),
  search: document.querySelector("#search"),
  refresh: document.querySelector("#refresh"),
  syncState: document.querySelector("#sync-state"),
  emptyReader: document.querySelector("#empty-reader"),
  reader: document.querySelector("#reader"),
  readerSource: document.querySelector("#reader-source"),
  readerTitle: document.querySelector("#reader-title"),
  readerMeta: document.querySelector("#reader-meta"),
  messages: document.querySelector("#messages"),
  sourceLink: document.querySelector("#source-link"),
  selectCurrent: document.querySelector("#select-current"),
  selectionCount: document.querySelector("#selection-count"),
  clearSelection: document.querySelector("#clear-selection"),
  createPack: document.querySelector("#create-pack"),
  publishPublic: document.querySelector("#publish-public"),
  packMode: document.querySelector("#pack-mode"),
  packBudget: document.querySelector("#pack-budget"),
  downloadPack: document.querySelector("#download-pack"),
  openSync: document.querySelector("#open-sync"),
  syncDialog: document.querySelector("#sync-dialog"),
  previewPanel: document.querySelector("#preview-panel"),
  runPreview: document.querySelector("#run-preview"),
  runSync: document.querySelector("#run-sync"),
  includeCodex: document.querySelector("#include-codex"),
  includeDsh: document.querySelector("#include-dsh"),
  publishGithub: document.querySelector("#publish-github"),
  acceptRedactions: document.querySelector("#accept-redactions"),
  chatgptPath: document.querySelector("#chatgpt-path"),
  importChatgpt: document.querySelector("#import-chatgpt"),
  gitSummary: document.querySelector("#git-summary"),
  toast: document.querySelector("#toast"),
};

let toastTimer;

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatDate(value) {
  if (!value) return "未知时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function providerMeta(provider) {
  return PROVIDERS[provider] || { name: provider, color: "#667675" };
}

function toast(message, error = false) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.className = `toast visible${error ? " error" : ""}`;
  toastTimer = setTimeout(() => {
    elements.toast.className = "toast";
  }, 4200);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Keep the HTTP status when the response is not JSON.
    }
    throw new Error(detail);
  }
  return response.json();
}

function renderProviders(counts) {
  elements.providerList.innerHTML = "";
  for (const [key, meta] of Object.entries(PROVIDERS)) {
    if (key === "generic" && !(counts[key] > 0)) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "provider-button";
    button.dataset.provider = key;
    button.setAttribute("aria-current", String(state.provider === key));
    button.style.setProperty("--dot-color", meta.color);
    button.innerHTML = `
      <span class="provider-dot"></span>
      <span>${escapeHtml(meta.name)}</span>
      <small>${counts[key] || 0}</small>
    `;
    button.addEventListener("click", () => {
      state.provider = key;
      loadConversations();
      loadStatus();
    });
    elements.providerList.append(button);
  }
}

function renderList() {
  elements.threadList.innerHTML = "";
  elements.threadCount.textContent = `${state.conversations.length} 个会话`;
  if (!state.conversations.length) {
    const empty = document.createElement("div");
    empty.style.padding = "28px 18px";
    empty.style.color = "var(--muted)";
    empty.style.fontSize = "13px";
    empty.textContent = "没有匹配的会话。先导入或同步一个来源。";
    elements.threadList.append(empty);
    updateSelectAllState();
    return;
  }
  for (const item of state.conversations) {
    const meta = providerMeta(item.provider);
    const row = document.createElement("div");
    row.className = "thread-item";
    row.style.setProperty("--provider-color", meta.color);
    row.dataset.id = item.id;
    row.setAttribute("role", "listitem");
    row.setAttribute("aria-current", String(state.currentId === item.id));
    row.tabIndex = 0;
    row.setAttribute("aria-label", `打开会话：${item.title}`);

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selected.has(item.id);
    checkbox.setAttribute("aria-label", `选择 ${item.title}`);
    checkbox.addEventListener("click", (event) => event.stopPropagation());
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selected.add(item.id);
      else state.selected.delete(item.id);
      updateSelectionUi();
    });

    const content = document.createElement("div");
    content.innerHTML = `
      <span class="thread-title">${escapeHtml(item.title)}</span>
      <span class="thread-meta">
        <span class="provider-pill">${escapeHtml(meta.name)}</span>
        <span>${escapeHtml(formatDate(item.updated_at || item.imported_at))}</span>
        <span>${item.message_count} 条</span>
      </span>
      ${
        item.snippet && item.snippet !== item.title
          ? `<p class="thread-snippet">${escapeHtml(item.snippet.slice(0, 150))}</p>`
          : ""
      }
    `;
    row.append(checkbox, content);
    row.addEventListener("click", () => openConversation(item.id));
    row.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openConversation(item.id);
      }
    });
    elements.threadList.append(row);
  }
  updateSelectAllState();
}

function updateSelectAllState() {
  const total = state.conversations.length;
  const selected = state.conversations.filter((item) => state.selected.has(item.id)).length;
  elements.selectAll.disabled = total === 0;
  elements.selectAll.checked = total > 0 && selected === total;
  elements.selectAll.indeterminate = selected > 0 && selected < total;
}

function renderMessageBody(container, text) {
  const chunks = String(text).split(/(```[\s\S]*?```)/g);
  for (const chunk of chunks) {
    if (chunk.startsWith("```") && chunk.endsWith("```")) {
      const pre = document.createElement("pre");
      const code = document.createElement("code");
      code.textContent = chunk.slice(3, -3).replace(/^[^\n]*\n/, "");
      pre.append(code);
      container.append(pre);
    } else if (chunk) {
      container.append(document.createTextNode(chunk));
    }
  }
}

async function openConversation(id) {
  try {
    const item = await api(`/api/v1/conversations/${encodeURIComponent(id).replaceAll("%3A", ":")}`);
    state.currentId = id;
    state.current = item;
    const targetHash = `#${encodeURIComponent(id)}`;
    if (location.hash !== targetHash) {
      history.replaceState(null, "", targetHash);
    }
    renderList();
    const meta = providerMeta(item.provider);
    elements.emptyReader.hidden = true;
    elements.reader.hidden = false;
    elements.readerSource.textContent = `${meta.name} · ${item.source_type}`;
    elements.readerSource.style.color = meta.color;
    elements.readerTitle.textContent = item.title;
    elements.readerMeta.innerHTML = `
      <span>模型 ${escapeHtml(item.model || "未标注")}</span>
      <span>更新 ${escapeHtml(formatDate(item.updated_at || item.created_at))}</span>
      <span>${item.messages.length} 条记录</span>
    `;
    elements.selectCurrent.checked = state.selected.has(item.id);
    if (/^https?:\/\//i.test(item.source_ref || "")) {
      elements.sourceLink.href = item.source_ref;
      elements.sourceLink.hidden = false;
    } else {
      elements.sourceLink.hidden = true;
    }
    elements.messages.innerHTML = "";
    for (const message of item.messages) {
      const article = document.createElement("section");
      article.className = "message";
      article.dataset.role = message.role;
      const labels = { user: "用户", assistant: "助手", tool: "工具", system: "系统" };
      const header = document.createElement("div");
      header.className = "message-label";
      header.innerHTML = `
        <span>${escapeHtml(labels[message.role] || message.role)}</span>
        <span class="message-time">${escapeHtml(formatDate(message.timestamp))}</span>
      `;
      const body = document.createElement("pre");
      body.className = "message-text";
      renderMessageBody(body, message.text);
      article.append(header, body);
      elements.messages.append(article);
    }
  } catch (error) {
    toast(`无法读取会话：${error.message}`, true);
  }
}

async function loadConversations() {
  const params = new URLSearchParams({ limit: "500" });
  if (state.query) params.set("q", state.query);
  if (state.provider !== "all") params.set("provider", state.provider);
  elements.syncState.textContent = "正在搜索会话…";
  try {
    const data = await api(`/api/v1/conversations?${params}`);
    state.conversations = data.items;
    renderList();
  } catch (error) {
    toast(`读取会话失败：${error.message}`, true);
  }
}

async function loadStatus() {
  try {
    const status = await api("/api/v1/status");
    const counts = status.counts;
    renderProviders(counts);
    const git = status.git;
    const publicRepo = status.public_repo;
    const remote = git.remote ? "已连接私有远端" : "未连接 GitHub";
    elements.syncState.textContent = `${counts.all || 0} 个会话 · ${remote}`;
    elements.gitSummary.textContent = git.remote
      ? `私有库分支 ${git.branch || "未命名"}，待发布 ${git.change_count || 0} 项。公开项目：${publicRepo?.url || "未配置"}`
      : `尚未配置私有 GitHub 远端；公开项目：${publicRepo?.url || "未配置"}`;
  } catch (error) {
    elements.syncState.textContent = "本地服务连接失败";
    toast(`状态读取失败：${error.message}`, true);
  }
}

function updateSelectionUi() {
  const count = state.selected.size;
  elements.selectionCount.textContent = count
    ? `已选择 ${count} 个会话`
    : "尚未选择会话";
  elements.clearSelection.hidden = count === 0;
  elements.createPack.disabled = count === 0;
  elements.publishPublic.disabled = count === 0;
  if (state.current) {
    elements.selectCurrent.checked = state.selected.has(state.current.id);
  }
  renderList();
}

function previewStats(preview) {
  const codex = preview.codex || {};
  const exported = preview.export || {};
  const findings = exported.findings || {};
  const redactions = Object.values(findings).reduce((sum, value) => sum + value, 0);
  const stats = [
    [codex.new || 0, "Codex 新增"],
    [codex.updated || 0, "Codex 更新"],
    [exported.conversations || exported.would_write || 0, "将导出"],
    [redactions, "脱敏项"],
  ];
  return `
    <div class="preview-summary">
      ${stats
        .map(
          ([value, label]) =>
            `<div class="preview-stat"><strong>${value}</strong><span>${label}</span></div>`,
        )
        .join("")}
    </div>
    ${
      preview.status === "blocked"
        ? `<p class="field-note">发现高风险内容。请检查下方脱敏预览；勾选允许后再次预检。</p>
           <pre>${escapeHtml(
             JSON.stringify(exported.redaction_samples || [], null, 2),
           )}</pre>`
        : `<p class="field-note">预检通过。${elements.publishGithub.checked ? "确认后会在导出变化存在时提交并推送到 origin。" : "确认后只生成本地脱敏导出。"}</p>`
    }
  `;
}

async function runPreview() {
  elements.runPreview.disabled = true;
  elements.runSync.disabled = true;
  elements.previewPanel.hidden = false;
  elements.previewPanel.textContent = "正在预检…";
  try {
    const preview = await api("/api/v1/sync/preview", {
      method: "POST",
      body: JSON.stringify({
        include_codex: elements.includeCodex.checked,
        include_deepseek_harness: elements.includeDsh.checked,
        publish: elements.publishGithub.checked,
        accept_redactions: elements.acceptRedactions.checked,
      }),
    });
    state.previewReady = preview.status !== "blocked";
    elements.previewPanel.innerHTML = previewStats(preview);
    elements.runSync.disabled = !state.previewReady;
  } catch (error) {
    elements.previewPanel.innerHTML = `<p class="field-note">预检失败：${escapeHtml(error.message)}</p>`;
    toast(`预检失败：${error.message}`, true);
  } finally {
    elements.runPreview.disabled = false;
  }
}

async function runSync() {
  elements.runSync.disabled = true;
  elements.runSync.textContent = "正在同步…";
  try {
    const result = await api("/api/v1/sync/commit", {
      method: "POST",
      body: JSON.stringify({
        include_codex: elements.includeCodex.checked,
        include_deepseek_harness: elements.includeDsh.checked,
        publish: elements.publishGithub.checked,
        accept_redactions: elements.acceptRedactions.checked,
      }),
    });
    elements.previewPanel.innerHTML = `<pre>${escapeHtml(JSON.stringify(result, null, 2))}</pre>`;
    toast("同步完成。");
    await Promise.all([loadConversations(), loadStatus()]);
  } catch (error) {
    toast(`同步失败：${error.message}`, true);
  } finally {
    elements.runSync.disabled = false;
    elements.runSync.textContent = "确认同步";
  }
}

async function importChatgpt() {
  const path = elements.chatgptPath.value.trim();
  if (!path) {
    toast("请填写 ChatGPT 导出 ZIP 的本地路径。", true);
    return;
  }
  elements.importChatgpt.disabled = true;
  try {
    const result = await api("/api/v1/imports", {
      method: "POST",
      body: JSON.stringify({ kind: "chatgpt", path }),
    });
    toast(`ChatGPT 导入完成：${result.new || 0} 个新增，${result.updated || 0} 个更新。`);
    await Promise.all([loadConversations(), loadStatus()]);
  } catch (error) {
    toast(`ChatGPT 导入失败：${error.message}`, true);
  } finally {
    elements.importChatgpt.disabled = false;
  }
}

async function createPack() {
  if (!state.selected.size) return;
  elements.createPack.disabled = true;
  elements.createPack.textContent = "正在生成…";
  try {
    const result = await api("/api/v1/packs", {
      method: "POST",
      body: JSON.stringify({
        conversation_ids: [...state.selected],
        budget: Number(elements.packBudget.value) || 32000,
        mode: elements.packMode.value,
      }),
    });
    if (result.status === "blocked") {
      toast("上下文包被脱敏规则阻止，请检查同步预检。", true);
      return;
    }
    state.packPath = result.path;
    const filename = result.filename || result.path.split(/[\\/]/).pop();
    elements.downloadPack.href =
      result.download_url || `/api/v1/packs/${encodeURIComponent(filename)}`;
    elements.downloadPack.hidden = false;
    toast(`Context Pack 已生成，约 ${result.token_count} tokens。`);
  } catch (error) {
    toast(`生成失败：${error.message}`, true);
  } finally {
    elements.createPack.disabled = false;
    elements.createPack.textContent = "生成 Context Pack";
  }
}

async function publishToPublic() {
  if (!state.selected.size) return;
  const preview = await api("/api/v1/status");
  const target = preview.public_repo?.url || "公开 GitHub 项目";
  if (
    !window.confirm(
      `将把 ${state.selected.size} 个已脱敏会话发布到公开项目：\n${target}\n\n公开后任何人都能看到这些内容，是否继续？`,
    )
  ) {
    return;
  }
  elements.publishPublic.disabled = true;
  elements.publishPublic.textContent = "正在发布…";
  try {
    let result = await api("/api/v1/publish/public", {
      method: "POST",
      body: JSON.stringify({
        conversation_ids: [...state.selected],
        accept_redactions: false,
      }),
    });
    if (result.status === "blocked") {
      const proceed = window.confirm(
        "检测到高风险敏感内容。继续会先替换为脱敏占位符再公开，是否继续？",
      );
      if (!proceed) return;
      result = await api("/api/v1/publish/public", {
        method: "POST",
        body: JSON.stringify({
          conversation_ids: [...state.selected],
          accept_redactions: true,
        }),
      });
    }
    toast(
      result.status === "unchanged"
        ? "公开项目内容已是最新。"
        : `已发布 ${result.published || 0} 个会话到公开项目。`,
    );
    if (result.url) window.open(result.url, "_blank", "noopener");
  } catch (error) {
    toast(`公开同步失败：${error.message}`, true);
  } finally {
    elements.publishPublic.disabled = state.selected.size === 0;
    elements.publishPublic.textContent = "发布选中到公开项目";
  }
}

let searchTimer;
elements.search.addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.query = elements.search.value.trim();
    loadConversations();
  }, 260);
});
elements.selectAll.addEventListener("change", () => {
  if (elements.selectAll.checked) {
    for (const item of state.conversations) state.selected.add(item.id);
  } else {
    for (const item of state.conversations) state.selected.delete(item.id);
  }
  updateSelectionUi();
});
elements.refresh.addEventListener("click", () => {
  Promise.all([loadConversations(), loadStatus()]);
});
elements.openSync.addEventListener("click", () => {
  elements.previewPanel.hidden = true;
  elements.runSync.disabled = true;
  elements.syncDialog.showModal();
});
elements.runPreview.addEventListener("click", runPreview);
elements.runSync.addEventListener("click", runSync);
elements.importChatgpt.addEventListener("click", importChatgpt);
elements.acceptRedactions.addEventListener("change", () => {
  elements.runSync.disabled = true;
  elements.previewPanel.hidden = true;
});
elements.publishGithub.addEventListener("change", () => {
  elements.runSync.disabled = true;
});
elements.selectCurrent.addEventListener("change", () => {
  if (!state.current) return;
  if (elements.selectCurrent.checked) state.selected.add(state.current.id);
  else state.selected.delete(state.current.id);
  updateSelectionUi();
});
elements.clearSelection.addEventListener("click", () => {
  state.selected.clear();
  updateSelectionUi();
});
elements.createPack.addEventListener("click", createPack);
elements.publishPublic.addEventListener("click", publishToPublic);

Promise.all([loadStatus(), loadConversations()]).then(() => {
  updateSelectionUi();
  const requestedId = location.hash ? decodeURIComponent(location.hash.slice(1)) : "";
  if (requestedId) openConversation(requestedId);
});
