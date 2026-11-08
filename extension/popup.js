const el = {
  provider: document.querySelector("#provider-name"),
  capture: document.querySelector("#capture"),
  send: document.querySelector("#send"),
  pending: document.querySelector("#pending"),
  settings: document.querySelector("#settings"),
  historyList: document.querySelector("#history-list"),
  importHistory: document.querySelector("#import-history"),
  message: document.querySelector("#message"),
};

const providerNames = {
  "chat.deepseek.com": "DeepSeek",
  "www.doubao.com": "豆包",
  "doubao.com": "豆包",
  "gemini.google.com": "Gemini",
  "chatgpt.com": "ChatGPT",
};

function setMessage(value, error = false) {
  el.message.textContent = value;
  el.message.className = `message${error ? " error" : ""}`;
}

function send(message) {
  return chrome.runtime.sendMessage(message);
}

async function refreshPending() {
  const result = await send({ type: "PENDING_COUNT" });
  el.pending.textContent = `${result.count || 0} 个快照等待发送。发送不会自动发布到 GitHub。`;
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function init() {
  const tab = await activeTab();
  const host = tab?.url ? new URL(tab.url).hostname : "";
  el.provider.textContent = providerNames[host] || "当前页面不在支持范围";
  const supported = Boolean(providerNames[host]);
  el.capture.disabled = !supported;
  el.historyList.innerHTML = "";
  if (!supported) {
    setMessage("请先打开 DeepSeek、豆包、Gemini 或 ChatGPT 的对话页面。", true);
  }
  await refreshPending();
}

el.settings.addEventListener("click", () => chrome.runtime.openOptionsPage());

el.capture.addEventListener("click", async () => {
  el.capture.disabled = true;
  setMessage("正在读取页面中可见的消息…");
  try {
    const result = await send({ type: "CAPTURE_ACTIVE" });
    if (result?.error) throw new Error(result.error);
    setMessage(
      result?.status === "unchanged"
        ? "页面内容与此前快照一致。"
        : `已加入扩展队列：${result?.snapshot?.messages?.length || 0} 条消息。`,
    );
    await refreshPending();
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    el.capture.disabled = false;
  }
});

el.send.addEventListener("click", async () => {
  el.send.disabled = true;
  setMessage("正在发送到本机 AI 会话中枢…");
  try {
    const result = await send({ type: "SEND_PENDING" });
    if (result?.error) throw new Error(result.error);
    const suffix = result.failed ? `，${result.failed} 个失败` : "";
    setMessage(`已发送 ${result.sent} 个快照${suffix}。`);
    if (result.errors?.length) setMessage(result.errors.join("\n"), true);
    await refreshPending();
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    el.send.disabled = false;
  }
});

document.querySelector("#history-panel").addEventListener("toggle", async (event) => {
  if (!event.target.open) return;
  setMessage("正在读取当前页面侧栏中的历史会话…");
  try {
    const result = await send({ type: "DISCOVER_ACTIVE" });
    if (result?.error) throw new Error(result.error);
    const items = result.items || [];
    el.historyList.innerHTML = "";
    if (!items.length) {
      setMessage("没有发现可枚举的历史链接。可打开侧栏后再试。", true);
      el.importHistory.disabled = true;
      return;
    }
    for (const item of items) {
      const label = document.createElement("label");
      label.className = "history-item";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = item.url;
      const title = document.createElement("span");
      title.textContent = item.title;
      label.append(checkbox, title);
      el.historyList.append(label);
    }
    el.importHistory.disabled = false;
    setMessage(`发现 ${items.length} 个候选历史会话。`);
  } catch (error) {
    setMessage(error.message, true);
  }
});

el.importHistory.addEventListener("click", async () => {
  const urls = [...el.historyList.querySelectorAll("input:checked")].map(
    (input) => input.value,
  );
  if (!urls.length) {
    setMessage("请先勾选要导入的历史会话。", true);
    return;
  }
  el.importHistory.disabled = true;
  setMessage(`正在逐个打开并捕获 ${urls.length} 个会话，请保持浏览器运行…`);
  try {
    const result = await send({ type: "IMPORT_HISTORY", urls });
    if (result?.error) throw new Error(result.error);
    setMessage(
      `历史导入完成：${result.captured} 个成功，${result.failed} 个失败。点击“发送到中枢”提交。`,
      result.failed > 0,
    );
    await refreshPending();
  } catch (error) {
    setMessage(error.message, true);
  } finally {
    el.importHistory.disabled = false;
  }
});

init().catch((error) => setMessage(error.message, true));
