(() => {
  const PROVIDERS = {
    "chat.deepseek.com": "deepseek",
    "www.doubao.com": "doubao",
    "doubao.com": "doubao",
    "gemini.google.com": "gemini",
    "chatgpt.com": "chatgpt",
  };

  const SELECTORS = {
    gemini: ["user-query", "model-response", "message-content"],
    deepseek: [
      "[data-role='user']",
      "[data-role='assistant']",
      "[class*='user-message']",
      "[class*='assistant-message']",
      "[class*='message-item']",
      ".ds-message",
    ],
    doubao: [
      "[data-testid*='message']",
      "[class*='send-message']",
      "[class*='receive-message']",
      "[class*='message-item']",
      "[class*='message-content']",
    ],
    chatgpt: [
      "[data-message-author-role]",
      "article[data-testid^='conversation-turn']",
    ],
  };

  const HISTORY_SELECTORS = {
    gemini: [
      "a[href*='/app/']",
      "a[href*='/chat/']",
      "[data-test-id*='conversation'] a",
    ],
    deepseek: [
      "a[href*='/a/chat/s/']",
      "a[href*='/chat/']",
      "[class*='history'] a",
    ],
    doubao: [
      "a[href*='/chat/']",
      "[class*='conversation'] a",
      "[class*='history'] a",
    ],
    chatgpt: ["a[href^='/c/']", "a[href*='/c/']"],
  };

  const provider = PROVIDERS[location.hostname];
  if (!provider) return;

  let lastQueuedHash = null;
  let queueTimer = null;
  let overlay = null;

  function cleanNodeText(node) {
    const clone = node.cloneNode(true);
    clone
      .querySelectorAll(
        "button, svg, script, style, noscript, [aria-hidden='true'], [data-testid*='copy']",
      )
      .forEach((element) => element.remove());
    return (clone.innerText || clone.textContent || "")
      .replace(/\u00a0/g, " ")
      .replace(/[ \t]+\n/g, "\n")
      .replace(/\n{4,}/g, "\n\n\n")
      .trim();
  }

  function roleOf(element) {
    const explicit = (
      element.getAttribute("data-message-author-role") ||
      element.getAttribute("data-role") ||
      element.getAttribute("role") ||
      ""
    ).toLowerCase();
    if (/user|human|query/.test(explicit)) return "user";
    if (/assistant|model|ai/.test(explicit)) return "assistant";
    const token = `${element.tagName} ${element.className} ${element.id}`.toLowerCase();
    if (/user-query|user.query|query-text|send-message|message-user/.test(token)) {
      return "user";
    }
    if (
      /model-response|assistant|receive-message|message-ai|response-container/.test(token)
    ) {
      return "assistant";
    }
    return null;
  }

  function findMessageNodes() {
    if (provider === "gemini") {
      const result = [];
      for (const turn of document.querySelectorAll(".conversation-container")) {
        const user = turn.querySelector("user-query");
        const model = turn.querySelector("model-response");
        if (user) {
          const node = user.querySelector(".query-text") || user;
          const text = cleanNodeText(node);
          if (text) result.push({ element: user, role: "user", text });
        }
        if (model) {
          const node =
            model.querySelector(".markdown.markdown-main-panel") || model;
          const text = cleanNodeText(node);
          if (text) result.push({ element: model, role: "assistant", text });
        }
      }
      return result;
    }

    if (provider === "doubao") {
      return [...document.querySelectorAll('[data-testid="message_content"]')]
        .map((element) => ({
          element,
          role: element.closest(".justify-end") ? "user" : "assistant",
          text: cleanNodeText(element),
        }))
        .filter((item) => item.text.length > 1);
    }

    if (provider === "deepseek") {
      return [...document.querySelectorAll(".ds-message")]
        .map((element) => {
          const finalAnswer = element.querySelector(
            ".ds-assistant-message-main-content",
          );
          return {
            element,
            role: finalAnswer ? "assistant" : "user",
            text: cleanNodeText(finalAnswer || element),
          };
        })
        .filter((item) => item.text.length > 1);
    }

    const ordered = [];
    const seen = new Set();
    for (const selector of SELECTORS[provider] || []) {
      for (const element of document.querySelectorAll(selector)) {
        if (seen.has(element)) continue;
        const text = cleanNodeText(element);
        if (text.length < 2) continue;
        const role = roleOf(element);
        if (!role) continue;
        seen.add(element);
        ordered.push({ element, role, text });
      }
    }
    const unique = [];
    for (const item of ordered) {
      const duplicate = unique.some(
        (other) =>
          other.role === item.role &&
          (other.text === item.text ||
            (other.element.contains(item.element) &&
              item.text.length < other.text.length * 0.72)),
      );
      if (!duplicate) unique.push(item);
    }
    unique.sort((left, right) => {
      if (left.element === right.element) return 0;
      return left.element.compareDocumentPosition(right.element) &
        Node.DOCUMENT_POSITION_FOLLOWING
        ? -1
        : 1;
    });
    return unique;
  }

  function findConversationId() {
    const path = location.pathname.replace(/\/+$/, "");
    const match =
      path.match(/\/(?:a\/chat\/s|c|chat|app)\/([A-Za-z0-9_-]{6,})/) ||
      location.hash.match(/([A-Za-z0-9_-]{8,})/);
    return match ? match[1] : null;
  }

  function findTitle() {
    const activeLink = [...document.querySelectorAll("a")].find(
      (anchor) => anchor.href === location.href,
    );
    const activeTitle = activeLink?.textContent
      ?.replace(/\s*(归档对话|更多)\s*$/, "")
      .replace(/\s+/g, " ")
      .trim();
    if (activeTitle) return activeTitle.slice(0, 160);
    const selectors = [
      "main h1",
      "[data-testid='conversation-title']",
      "[class*='conversation-title']",
      "header h1",
      "h1",
    ];
    for (const selector of selectors) {
      const text = document.querySelector(selector)?.textContent?.trim();
      if (text && text.length < 160) return text;
    }
    return document.title
      .replace(/\s*[-|]\s*(DeepSeek|豆包|Gemini|ChatGPT).*$/i, "")
      .trim();
  }

  function findModel() {
    const candidates = document.querySelectorAll(
      "[data-testid*='model'], [class*='model-name'], [aria-label*='model'], [class*='model-selector']",
    );
    for (const element of candidates) {
      const text = element.textContent?.trim();
      if (text && text.length < 80) return text;
    }
    return null;
  }

  async function sha256(value) {
    const bytes = new TextEncoder().encode(value);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    return [...new Uint8Array(digest)]
      .map((byte) => byte.toString(16).padStart(2, "0"))
      .join("");
  }

  async function capture() {
    const found = findMessageNodes();
    if (!found.length) {
      throw new Error("没有识别到用户可见的对话消息；页面结构可能已变化。");
    }
    const messages = found.map((item, index) => ({
      seq: index,
      role: item.role,
      kind: "message",
      text: item.text,
      timestamp: null,
      metadata: {},
    }));
    let title = findTitle() || `${provider} 会话`;
    if (provider === "doubao") {
      const firstUser = messages.find((message) => message.role === "user");
      if (firstUser?.text) title = firstUser.text.slice(0, 80);
    }
    const contentHash = await sha256(
      `${provider}\n${title}\n${messages.map((item) => item.text).join("\n---\n")}`,
    );
    const conversationId =
      findConversationId() ||
      (await sha256(`${title}\n${messages[0]?.text || ""}`)).slice(0, 24);
    return {
      provider,
      conversation_id: conversationId,
      title,
      url: location.href,
      model: findModel(),
      captured_at: new Date().toISOString(),
      messages,
      snapshot_hash: contentHash,
      complete: true,
    };
  }

  function discoverHistory() {
    const links = new Map();
    const origin = location.origin;
    for (const selector of HISTORY_SELECTORS[provider] || []) {
      for (const anchor of document.querySelectorAll(selector)) {
        const href = anchor.href;
        const title = (anchor.textContent || "").replace(/\s+/g, " ").trim();
        if (!href || !title || title.length < 1) continue;
        if (href === location.href) continue;
        try {
          const url = new URL(href, origin);
          if (!url.hostname.endsWith(location.hostname.replace(/^www\./, ""))) continue;
          links.set(url.href, title.slice(0, 160));
        } catch {
          // Ignore malformed anchors.
        }
      }
    }
    return [...links.entries()].map(([url, title]) => ({ url, title })).slice(0, 250);
  }

  async function queueCapture(showError = false) {
    try {
      const snapshot = await capture();
      if (snapshot.snapshot_hash === lastQueuedHash) {
        return { status: "unchanged", snapshot };
      }
      await chrome.runtime.sendMessage({ type: "QUEUE_CAPTURE", snapshot });
      lastQueuedHash = snapshot.snapshot_hash;
      return { status: "queued", snapshot };
    } catch (error) {
      if (showError) throw error;
      return { status: "error", error: error.message };
    }
  }

  function ensureOverlay() {
    if (overlay?.isConnected) return overlay;
    overlay = document.createElement("div");
    overlay.dataset.aiContextHub = "capture";
    overlay.style.cssText = [
      "position:fixed",
      "right:20px",
      "bottom:20px",
      "z-index:2147483647",
      "display:flex",
      "align-items:center",
      "gap:8px",
      "padding:9px 12px",
      "border:1px solid rgba(17,106,104,.35)",
      "border-radius:8px",
      "background:#f8faf8",
      "color:#0b4d4c",
      "box-shadow:0 8px 25px rgba(20,43,42,.18)",
      "font:600 12px/1.4 'Microsoft YaHei UI','Aptos',sans-serif",
    ].join(";");

    const dot = document.createElement("span");
    dot.style.cssText =
      "width:8px;height:8px;border-radius:50%;background:#116a68;flex:0 0 auto";
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "收进 AI 中枢";
    button.style.cssText =
      "border:0;padding:0;background:transparent;color:inherit;font:inherit;cursor:pointer";
    button.addEventListener("click", async () => {
      button.disabled = true;
      button.textContent = "正在同步…";
      try {
        const result = await queueCapture(true);
        if (result.status === "error") throw new Error(result.error);
        const sent = await chrome.runtime.sendMessage({ type: "SEND_PENDING" });
        if (sent?.error) throw new Error(sent.error);
        button.textContent = sent.failed
          ? "部分快照未发送"
          : `已同步 ${result.snapshot.messages.length} 条消息`;
        setTimeout(() => {
          button.textContent = "收进 AI 中枢";
          button.disabled = false;
        }, 3500);
      } catch (error) {
        button.textContent = "同步失败，点击重试";
        button.title = error.message;
        button.disabled = false;
      }
    });
    overlay.append(dot, button);
    document.documentElement.append(overlay);
    return overlay;
  }

  function scheduleCapture() {
    clearTimeout(queueTimer);
    queueTimer = setTimeout(() => queueCapture(false), 1400);
  }

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "CAPTURE_CURRENT") {
      queueCapture(true)
        .then(sendResponse)
        .catch((error) => sendResponse({ status: "error", error: error.message }));
      return true;
    }
    if (message.type === "DISCOVER_HISTORY") {
      sendResponse({ items: discoverHistory() });
      return false;
    }
    return false;
  });

  setTimeout(() => {
    ensureOverlay();
    scheduleCapture();
  }, 1800);
  const observer = new MutationObserver(scheduleCapture);
  observer.observe(document.documentElement, { childList: true, subtree: true });
})();
