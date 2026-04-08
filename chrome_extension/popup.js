const button = document.getElementById("exportBtn");
const statusEl = document.getElementById("status");
let statusPoller = null;
let autorunTriggered = false;

function setStatus(message) {
  statusEl.textContent = message;
}

async function refreshStatus() {
  const { xlikesStatus } = await chrome.storage.local.get(["xlikesStatus"]);
  if (!xlikesStatus) return;

  const lines = [];
  if (xlikesStatus.state) {
    lines.push(`State: ${xlikesStatus.state}`);
  }
  if (xlikesStatus.detail) {
    lines.push(xlikesStatus.detail);
  }
  if (typeof xlikesStatus.itemCount === "number") {
    lines.push(`Items: ${xlikesStatus.itemCount}`);
  }
  if (xlikesStatus.updatedAt) {
    lines.push(`Updated: ${xlikesStatus.updatedAt}`);
  }
  if (xlikesStatus.debugPreview) {
    lines.push("");
    lines.push("Debug:");
    lines.push(xlikesStatus.debugPreview);
  }

  if (lines.length) {
    setStatus(lines.join("\n"));
  }
}

async function startPollingStatus() {
  await refreshStatus();
  if (statusPoller) clearInterval(statusPoller);
  statusPoller = setInterval(() => {
    refreshStatus().catch(() => {});
  }, 1000);
}

startPollingStatus().catch(() => {});

async function startExport() {
  button.disabled = true;
  setStatus("Resolving current account...");

  try {
    const response = await chrome.runtime.sendMessage({
      type: "XLIKES_EXPORT_MY_LIKES"
    });

    if (!response?.ok) {
      throw new Error(response?.error || "Export did not start.");
    }

    await refreshStatus();
  } catch (error) {
    setStatus(`Failed: ${error.message}`);
  } finally {
    button.disabled = false;
  }
}

button.addEventListener("click", startExport);

const params = new URLSearchParams(window.location.search);
if (params.get("autorun") === "1" && !autorunTriggered) {
  autorunTriggered = true;
  window.addEventListener("load", () => {
    setTimeout(() => {
      startExport().catch(() => {});
    }, 300);
  });
}
