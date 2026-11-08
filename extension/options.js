const server = document.querySelector("#server");
const token = document.querySelector("#token");
const status = document.querySelector("#status");
const localConfig = globalThis.AI_CONTEXT_LOCAL_CONFIG || {};

chrome.storage.local
  .get({
    serverUrl: localConfig.serverUrl || "http://127.0.0.1:8765",
    token: localConfig.token || "",
  })
  .then((settings) => {
    server.value = settings.serverUrl;
    token.value = settings.token;
  });

document.querySelector("#save").addEventListener("click", async () => {
  const serverUrl = server.value.trim().replace(/\/+$/, "");
  const tokenValue = token.value.trim();
  if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(serverUrl)) {
    status.textContent = "服务地址必须是本机 HTTP 地址。";
    return;
  }
  await chrome.storage.local.set({ serverUrl, token: tokenValue });
  status.textContent = "已保存。";
  setTimeout(() => {
    status.textContent = "";
  }, 2200);
});
