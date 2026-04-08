const statusEl = document.getElementById("status");
let statusPoller = null;
let started = false;
let finished = false;
const MAX_START_ATTEMPTS = 4;

function setStatus(message) {
  statusEl.textContent = message;
}

async function refreshStatus() {
  const { xlikesStatus } = await chrome.storage.local.get(["xlikesStatus"]);
  if (!xlikesStatus) return;

  const lines = [];
  if (xlikesStatus.state) lines.push(`State: ${xlikesStatus.state}`);
  if (xlikesStatus.detail) lines.push(xlikesStatus.detail);
  if (typeof xlikesStatus.itemCount === "number") lines.push(`Items: ${xlikesStatus.itemCount}`);
  if (xlikesStatus.updatedAt) lines.push(`Updated: ${xlikesStatus.updatedAt}`);
  setStatus(lines.join("\n"));

  if (!finished && (xlikesStatus.state === "done" || xlikesStatus.state === "failed")) {
    finished = true;
    if (statusPoller) clearInterval(statusPoller);
    setTimeout(async () => {
      try {
        const currentWindow = await chrome.windows.getCurrent();
        if (currentWindow?.id) {
          await chrome.windows.remove(currentWindow.id);
          return;
        }
      } catch {}
      try {
        const currentTab = await chrome.tabs.getCurrent();
        if (currentTab?.id) {
          await chrome.tabs.remove(currentTab.id);
        }
      } catch {}
    }, 2000);
  }
}

async function startPollingStatus() {
  await refreshStatus();
  if (statusPoller) clearInterval(statusPoller);
  statusPoller = setInterval(() => {
    refreshStatus().catch(() => {});
  }, 1000);
}

async function startExport() {
  if (started) return;
  started = true;
  setStatus("Starting scheduled export...");
  for (let attempt = 1; attempt <= MAX_START_ATTEMPTS; attempt += 1) {
    try {
      await chrome.storage.local.set({
        xlikesStatus: {
          startedAt: new Date().toISOString(),
          updatedAt: new Date().toISOString(),
          state: "starting",
          detail:
            attempt === 1
              ? "Starting autorun export."
              : `Retrying autorun export (${attempt}/${MAX_START_ATTEMPTS}).`
        }
      });
    } catch {}

    try {
      const response = await chrome.runtime.sendMessage({ type: "XLIKES_EXPORT_MY_LIKES" });
      if (!response?.ok) {
        throw new Error(response?.error || "Scheduled export did not start.");
      }
      return;
    } catch (error) {
      if (attempt === MAX_START_ATTEMPTS) {
        setStatus(`Failed: ${error.message}`);
        try {
          await chrome.storage.local.set({
            xlikesStatus: {
              startedAt: new Date().toISOString(),
              updatedAt: new Date().toISOString(),
              state: "failed",
              detail: `Autorun failed: ${error.message}`
            }
          });
        } catch {}
        return;
      }
      await new Promise((resolve) => setTimeout(resolve, 1200 * attempt));
    }
  }
}

(async () => {
  await startPollingStatus();
  await startExport();
})();
