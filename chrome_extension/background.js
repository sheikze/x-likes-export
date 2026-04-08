function normalizeLikesUrl(handle) {
  const raw = String(handle || "").trim().replace(/^@/, "");
  if (!raw) {
    throw new Error("Missing handle.");
  }
  return `https://x.com/${raw}/likes`;
}

async function setExportStatus(patch) {
  const current = await chrome.storage.local.get(["xlikesStatus"]);
  const next = {
    startedAt: current?.xlikesStatus?.startedAt || new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    state: "idle",
    detail: "",
    itemCount: null,
    ...current?.xlikesStatus,
    ...patch
  };
  await chrome.storage.local.set({ xlikesStatus: next });
}

function filterCapturedHeaders(headers) {
  const keep = new Set([
    "authorization",
    "x-client-transaction-id",
    "x-csrf-token",
    "x-twitter-active-user",
    "x-twitter-auth-type",
    "x-twitter-client-language"
  ]);
  const out = {};
  for (const header of headers || []) {
    const name = String(header?.name || "").toLowerCase();
    if (!keep.has(name)) continue;
    if (header?.value) out[name] = header.value;
  }
  return out;
}

function captureLikesBlueprintForTab(tabId, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    let finished = false;

    const finish = (fn, value) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      chrome.webRequest.onBeforeSendHeaders.removeListener(listener);
      fn(value);
    };

    const listener = (details) => {
      if (details.tabId !== tabId) return;
      if (!/\/i\/api\/graphql\/[^/]+\/Likes(?:\?|$)/i.test(details.url)) return;

      finish(resolve, {
        url: details.url,
        headers: filterCapturedHeaders(details.requestHeaders)
      });
    };

    const timer = setTimeout(() => {
      finish(reject, new Error("Timed out waiting for the Likes API request blueprint."));
    }, timeoutMs);

    chrome.webRequest.onBeforeSendHeaders.addListener(
      listener,
      { urls: ["https://x.com/i/api/graphql/*", "https://twitter.com/i/api/graphql/*"] },
      ["requestHeaders", "extraHeaders"]
    );
  });
}

async function waitForContentScript(tabId, timeoutMs = 30000) {
  const startedAt = Date.now();
  let lastError = null;

  while (Date.now() - startedAt < timeoutMs) {
    try {
      const response = await chrome.tabs.sendMessage(tabId, {
        type: "XLIKES_PING"
      });
      if (response?.ok) {
        return true;
      }
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 600));
  }

  throw new Error(lastError?.message || "Timed out waiting for the content script to become available.");
}

async function ensureContentScript(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: "XLIKES_PING" });
    return;
  } catch {}

  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content.js"]
  });
}

async function createBackgroundTab(url) {
  const tab = await chrome.tabs.create({
    url,
    active: false
  });
  await awaitTabComplete(tab.id);
  await new Promise((resolve) => setTimeout(resolve, 1800));
  await ensureContentScript(tab.id);
  await waitForContentScript(tab.id);
  return tab;
}

async function resolveCurrentHandle() {
  const cached = await chrome.storage.local.get(["currentAccountHandle"]);
  const cachedHandle = String(cached?.currentAccountHandle || "").trim().replace(/^@/, "");
  if (cachedHandle) {
    await setExportStatus({
      state: "resolved_handle",
      detail: `Using cached current account @${cachedHandle}.`
    });
    return cachedHandle;
  }

  await setExportStatus({
    state: "resolving_handle",
    detail: "Opening X home and resolving the current logged-in account."
  });
  const tab = await createBackgroundTab("https://x.com/home");
  try {
    const response = await chrome.tabs.sendMessage(tab.id, {
      type: "XLIKES_RESOLVE_SELF"
    });
    if (!response?.ok || !response.handle) {
      throw new Error(response?.error || "Could not resolve the current logged-in X account.");
    }
    await chrome.storage.local.set({
      currentAccountHandle: String(response.handle || "").trim().replace(/^@/, "")
    });
    return response.handle;
  } finally {
    if (tab.id) {
      chrome.tabs.remove(tab.id).catch?.(() => {});
    }
  }
}

async function exportLikesForHandle(handle) {
  const likesUrl = normalizeLikesUrl(handle);
  await setExportStatus({
    state: "opening_likes",
    detail: `Opening Likes for @${handle}.`
  });
  const tab = await chrome.tabs.create({
    url: likesUrl,
    active: false
  });
  const tabBlueprintPromise = captureLikesBlueprintForTab(tab.id);

  try {
    await awaitTabComplete(tab.id);
    await new Promise((resolve) => setTimeout(resolve, 1800));
    await ensureContentScript(tab.id);
    await waitForContentScript(tab.id);

    await setExportStatus({
      state: "exporting",
      detail: `Exporting likes for @${handle}.`
    });

    const blueprint = await tabBlueprintPromise;
    const response = await chrome.tabs.sendMessage(tab.id, {
      type: "XLIKES_EXPORT_START",
      blueprint
    });

    if (!response?.ok) {
      throw new Error(response?.error || "Export failed in background tab.");
    }

    return response.message || "Background export finished.";
  } finally {
    if (tab.id) {
      chrome.tabs.remove(tab.id).catch?.(() => {});
    }
  }
}

function awaitTabComplete(tabId, timeoutMs = 30000) {
  return new Promise((resolve, reject) => {
    let finished = false;
    const finish = (fn, value) => {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      fn(value);
    };

    const listener = (updatedTabId, changeInfo, tab) => {
      if (updatedTabId === tabId && changeInfo.status === "complete") {
        finish(resolve, tab);
      }
    };

    const timer = setTimeout(() => {
      finish(reject, new Error("Timed out waiting for the Likes tab to finish loading."));
    }, timeoutMs);

    chrome.tabs.onUpdated.addListener(listener);

    chrome.tabs.get(tabId).then((tab) => {
      if (tab?.status === "complete") {
        finish(resolve, tab);
      }
    }).catch(() => {});
  });
}

async function saveFiles(baseName, files) {
  const bridgeUrl = "http://127.0.0.1:8767";
  const maxInlineDownloadBytes = 1_500_000;

  try {
    const health = await fetch(`${bridgeUrl}/health`);
    if (health.ok) {
      const response = await fetch(`${bridgeUrl}/import`, {
        method: "POST",
        headers: {
          "content-type": "application/json"
        },
        body: JSON.stringify({
          baseName,
          files
        })
      });

      if (response.ok) {
        const payload = await response.json();
        return {
          ok: true,
          mode: payload.mode || "obsidian_bridge",
          target_dir: payload.target_dir || "",
          written: payload.written || []
        };
      }
    }
  } catch {}

  for (const file of files) {
    const mime = file.mime || "text/plain;charset=utf-8";
    const extension = file.extension || "txt";
    const content = String(file.content || "");
    const byteLength = new TextEncoder().encode(content).length;

    if (byteLength > maxInlineDownloadBytes) {
      throw new Error(
        `Export file ${baseName}.${extension} is too large for inline download fallback. Start the local bridge or reduce export size.`
      );
    }

    const dataUrl = `data:${mime};charset=utf-8,${encodeURIComponent(content)}`;

    await chrome.downloads.download({
      url: dataUrl,
      filename: `${baseName}.${extension}`,
      saveAs: false,
      conflictAction: "uniquify"
    });
  }

  return {
    ok: true,
    mode: "downloads"
  };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "XLIKES_OPEN_STATUS_PAGE") {
    chrome.tabs.create({
      url: chrome.runtime.getURL("status.html"),
      active: true
    }).then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  }

  if (message?.type === "XLIKES_DOWNLOAD_FILES") {
    const files = Array.isArray(message.files) ? message.files : [];
    const baseName = message.baseName || `x-likes-export-${Date.now()}`;

    saveFiles(baseName, files)
      .then((result) => sendResponse(result || { ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));

    return true;
  }

  if (message?.type !== "XLIKES_EXPORT_BACKGROUND_START") {
    if (message?.type !== "XLIKES_EXPORT_MY_LIKES") {
      return;
    }
  }

  (async () => {
    await setExportStatus({
      startedAt: new Date().toISOString(),
      state: "starting",
      detail: "Starting export."
    });

    const handle =
      message?.type === "XLIKES_EXPORT_MY_LIKES"
        ? await resolveCurrentHandle()
        : String(message.target || "").trim().replace(/^@/, "");

    await setExportStatus({
      state: "resolved_handle",
      detail: `Resolved current account as @${handle}.`
    });

    const exportMessage = await exportLikesForHandle(handle);

    await setExportStatus({
      state: "done",
      detail: exportMessage
    });

    sendResponse({
      ok: true,
      message: `@${handle}: ${exportMessage}`
    });
  })().catch((error) => {
    setExportStatus({
      state: "failed",
      detail: error.message || String(error)
    }).catch(() => {});
    sendResponse({
      ok: false,
      error: error.message || String(error)
    });
  });

  return true;
});
