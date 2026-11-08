const DB_NAME = "ai-context-hub-capture";
const STORE = "pending";
try {
  importScripts("config.local.js");
} catch {
  // The options page can still configure a server and token manually.
}

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: "key" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function putPending(snapshot) {
  const db = await openDb();
  const key = `${snapshot.provider}:${snapshot.conversation_id}`;
  await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    tx.objectStore(STORE).put({ key, snapshot, queuedAt: new Date().toISOString() });
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

async function listPending() {
  const db = await openDb();
  const items = await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readonly");
    const request = tx.objectStore(STORE).getAll();
    request.onsuccess = () => resolve(request.result || []);
    request.onerror = () => reject(request.error);
  });
  db.close();
  return items;
}

async function deletePending(keys) {
  if (!keys.length) return;
  const db = await openDb();
  await new Promise((resolve, reject) => {
    const tx = db.transaction(STORE, "readwrite");
    for (const key of keys) tx.objectStore(STORE).delete(key);
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
  db.close();
}

async function getSettings() {
  const localConfig = globalThis.AI_CONTEXT_LOCAL_CONFIG || {};
  const value = await chrome.storage.local.get({
    serverUrl: localConfig.serverUrl || "http://127.0.0.1:8765",
    token: localConfig.token || "",
  });
  return value;
}

async function sendPending() {
  const items = await listPending();
  if (!items.length) return { sent: 0, failed: 0, remaining: 0 };
  const settings = await getSettings();
  if (!settings.token) {
    throw new Error("尚未配置本地配对令牌。请打开扩展设置。");
  }
  const succeeded = [];
  const errors = [];
  for (const item of items) {
    try {
      const response = await fetch(`${settings.serverUrl}/api/v1/capture`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-AI-Context-Token": settings.token,
        },
        body: JSON.stringify(item.snapshot),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `HTTP ${response.status}`);
      }
      succeeded.push(item.key);
    } catch (error) {
      errors.push(`${item.snapshot.title}: ${error.message}`);
    }
  }
  await deletePending(succeeded);
  const remaining = (await listPending()).length;
  return {
    sent: succeeded.length,
    failed: errors.length,
    remaining,
    errors: errors.slice(0, 6),
  };
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function sendToTab(tabId, message) {
  return chrome.tabs.sendMessage(tabId, message);
}

function waitForTab(tabId) {
  return new Promise((resolve) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(false);
    }, 30000);
    const listener = (updatedTabId, info) => {
      if (updatedTabId === tabId && info.status === "complete") {
        clearTimeout(timeout);
        chrome.tabs.onUpdated.removeListener(listener);
        setTimeout(() => resolve(true), 1800);
      }
    };
    chrome.tabs.onUpdated.addListener(listener);
  });
}

async function importHistory(urls) {
  const created = [];
  const errors = [];
  let captured = 0;
  for (let index = 0; index < urls.length; index += 1) {
    let tab;
    try {
      tab = await chrome.tabs.create({ url: urls[index], active: false });
      created.push(tab.id);
      const ready = await waitForTab(tab.id);
      if (!ready) {
        errors.push(`${urls[index]}: 页面加载超时`);
        continue;
      }
      const result = await sendToTab(tab.id, { type: "CAPTURE_CURRENT" });
      if (result?.status === "queued" || result?.status === "unchanged") {
        captured += 1;
      } else {
        errors.push(`${urls[index]}: ${result?.error || "未捕获到消息"}`);
      }
      await chrome.storage.local.set({
        historyProgress: {
          current: index + 1,
          total: urls.length,
          captured,
          errors: errors.slice(-4),
        },
      });
    } catch (error) {
      errors.push(`${urls[index]}: ${error.message}`);
    } finally {
      if (tab?.id) await chrome.tabs.remove(tab.id).catch(() => {});
    }
  }
  return { captured, failed: errors.length, total: urls.length, errors: errors.slice(0, 8) };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    if (message.type === "QUEUE_CAPTURE") {
      await putPending(message.snapshot);
      sendResponse({ ok: true, pending: (await listPending()).length });
      return;
    }
    if (message.type === "PENDING_COUNT") {
      sendResponse({ count: (await listPending()).length });
      return;
    }
    if (message.type === "SEND_PENDING") {
      sendResponse(await sendPending());
      return;
    }
    if (message.type === "CAPTURE_ACTIVE") {
      const tab = await activeTab();
      if (!tab?.id) throw new Error("没有活动标签页");
      sendResponse(await sendToTab(tab.id, { type: "CAPTURE_CURRENT" }));
      return;
    }
    if (message.type === "DISCOVER_ACTIVE") {
      const tab = await activeTab();
      if (!tab?.id) throw new Error("没有活动标签页");
      sendResponse(await sendToTab(tab.id, { type: "DISCOVER_HISTORY" }));
      return;
    }
    if (message.type === "IMPORT_HISTORY") {
      sendResponse(await importHistory(message.urls || []));
      return;
    }
    throw new Error("未知扩展消息");
  })().catch((error) => sendResponse({ error: error.message }));
  return true;
});
