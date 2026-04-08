(function () {
  const state = {
    running: false,
    blueprint: null,
    injectorInstalled: false
  };

  const BLUEPRINT_EVENT = "XLIKES_BLUEPRINT_CAPTURED";
  const BLUEPRINT_TIMEOUT_MS = 20000;
  const PAGE_SETTLE_MS = 2500;
  const API_PAGE_WAIT_MS = 1200;
  const MAX_API_PAGES = 400;
  const LIKES_PATH_RE = /\/i\/api\/graphql\/[^/]+\/Likes(?:\?|$)/i;
  const CAPTURE_HEADER_NAMES = [
    "authorization",
    "x-client-transaction-id",
    "x-csrf-token",
    "x-twitter-active-user",
    "x-twitter-auth-type",
    "x-twitter-client-language"
  ];

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  async function reportProgress(patch) {
    try {
      const current = await chrome.storage.local.get(["xlikesStatus"]);
      const next = {
        ...current?.xlikesStatus,
        updatedAt: new Date().toISOString(),
        ...patch
      };
      await chrome.storage.local.set({ xlikesStatus: next });
    } catch {}
  }

  function safePreview(value, maxLen = 5000) {
    try {
      const text = JSON.stringify(value, null, 2);
      return text.length > maxLen ? `${text.slice(0, maxLen)}\n...<truncated>` : text;
    } catch {
      return String(value);
    }
  }

  function isLikesPage() {
    return /\/likes\/?$/.test(window.location.pathname);
  }

  function isHomeLikePage() {
    return /^\/(?:home)?\/?$/.test(window.location.pathname) || /\/home\/?$/.test(window.location.pathname);
  }

  function extractHandleFromHref(href) {
    try {
      const url = new URL(href, window.location.origin);
      const parts = url.pathname.split("/").filter(Boolean);
      if (parts.length !== 1) return "";
      const handle = parts[0];
      if (!handle || ["home", "explore", "notifications", "messages", "i", "settings"].includes(handle)) {
        return "";
      }
      return handle;
    } catch {
      return "";
    }
  }

  function resolveCurrentHandleOnce() {
    const directSelectors = [
      'a[data-testid="AppTabBar_Profile_Link"]',
      'a[aria-label*="Profile"]',
      'a[href^="/"][role="link"][data-testid]'
    ];

    for (const selector of directSelectors) {
      const links = document.querySelectorAll(selector);
      for (const link of links) {
        const handle = extractHandleFromHref(link.getAttribute("href") || link.href || "");
        if (handle) return handle;
      }
    }

    const sidebarLinks = document.querySelectorAll('nav a[href^="/"], aside a[href^="/"]');
    for (const link of sidebarLinks) {
      const handle = extractHandleFromHref(link.getAttribute("href") || link.href || "");
      if (handle) return handle;
    }

    return "";
  }

  async function resolveCurrentHandle() {
    const startedAt = Date.now();
    while (Date.now() - startedAt < 15000) {
      const handle = resolveCurrentHandleOnce();
      if (handle) return handle;
      await sleep(500);
    }
    throw new Error("Could not determine the current logged-in X handle from the page.");
  }

  function normalizeStatusUrl(handle, id) {
    if (!handle || !id) return null;
    return `${window.location.origin}/${handle}/status/${id}`;
  }

  function installBlueprintListener() {
    if (state.injectorInstalled) return;
    state.injectorInstalled = true;

    window.addEventListener("message", (event) => {
      if (event.source !== window) return;
      const data = event.data;
      if (!data || data.type !== BLUEPRINT_EVENT || !data.payload?.url) return;
      state.blueprint = data.payload;
    });

    const script = document.createElement("script");
    script.dataset.xlikesInjector = "1";
    script.textContent = `(() => {
      const EVENT = ${JSON.stringify(BLUEPRINT_EVENT)};
      const URL_RE = ${LIKES_PATH_RE.toString()};
      const HEADER_NAMES = ${JSON.stringify(CAPTURE_HEADER_NAMES)};
      let sent = false;

      function normalizeHeaders(input) {
        const out = {};
        if (!input) return out;

        if (input instanceof Headers) {
          for (const [key, value] of input.entries()) {
            out[key.toLowerCase()] = value;
          }
          return out;
        }

        if (Array.isArray(input)) {
          for (const pair of input) {
            if (Array.isArray(pair) && pair.length >= 2) {
              out[String(pair[0]).toLowerCase()] = String(pair[1]);
            }
          }
          return out;
        }

        if (typeof input === "object") {
          for (const [key, value] of Object.entries(input)) {
            out[String(key).toLowerCase()] = String(value);
          }
        }

        return out;
      }

      function filterHeaders(headers) {
        const out = {};
        for (const name of HEADER_NAMES) {
          if (headers[name]) out[name] = headers[name];
        }
        return out;
      }

      function maybeEmit(url, headers) {
        if (sent) return;
        if (!url || !URL_RE.test(url)) return;
        sent = true;
        window.postMessage({
          type: EVENT,
          payload: {
            url,
            headers: filterHeaders(headers)
          }
        }, "*");
      }

      const originalFetch = window.fetch;
      window.fetch = async function(...args) {
        try {
          const input = args[0];
          const init = args[1] || {};
          const url = typeof input === "string" ? input : input?.url;
          const reqHeaders = normalizeHeaders(input?.headers);
          const initHeaders = normalizeHeaders(init?.headers);
          maybeEmit(url, { ...reqHeaders, ...initHeaders });
        } catch {}
        return originalFetch.apply(this, args);
      };

      const originalOpen = XMLHttpRequest.prototype.open;
      const originalSetRequestHeader = XMLHttpRequest.prototype.setRequestHeader;
      const originalSend = XMLHttpRequest.prototype.send;

      XMLHttpRequest.prototype.open = function(method, url, ...rest) {
        this.__xlikes_url = url;
        this.__xlikes_headers = {};
        return originalOpen.call(this, method, url, ...rest);
      };

      XMLHttpRequest.prototype.setRequestHeader = function(name, value) {
        try {
          this.__xlikes_headers = this.__xlikes_headers || {};
          this.__xlikes_headers[String(name).toLowerCase()] = String(value);
        } catch {}
        return originalSetRequestHeader.call(this, name, value);
      };

      XMLHttpRequest.prototype.send = function(...args) {
        try {
          maybeEmit(this.__xlikes_url, this.__xlikes_headers || {});
        } catch {}
        return originalSend.apply(this, args);
      };
    })();`;

    (document.documentElement || document.head || document.body).appendChild(script);
    script.remove();
  }

  async function waitForBlueprint() {
    await reportProgress({
      state: "capturing_blueprint",
      detail: "Capturing the Likes GraphQL request blueprint from X."
    });
    const startedAt = Date.now();
    while (Date.now() - startedAt < BLUEPRINT_TIMEOUT_MS) {
      if (state.blueprint?.url) {
        return state.blueprint;
      }
      await sleep(400);
    }
    throw new Error("Could not capture the Likes API request blueprint from the X page.");
  }

  function buildHeaders(blueprint) {
    const headers = {
      accept: "*/*",
      "content-type": "application/json",
      "x-twitter-active-user": "yes",
      "x-twitter-client-language": navigator.language || "en"
    };

    for (const [key, value] of Object.entries(blueprint.headers || {})) {
      if (value) headers[key] = value;
    }

    return headers;
  }

  function buildRequestTemplate(blueprint) {
    const url = new URL(blueprint.url, window.location.origin);
    const features = JSON.parse(url.searchParams.get("features") || "{}");
    const fieldToggles = JSON.parse(url.searchParams.get("fieldToggles") || "{}");
    const variables = JSON.parse(url.searchParams.get("variables") || "{}");

    return {
      origin: url.origin,
      pathname: url.pathname,
      features,
      fieldToggles,
      baseVariables: variables
    };
  }

  function buildLikesRequestUrl(template, cursor) {
    const url = new URL(template.pathname, template.origin);
    const variables = { ...template.baseVariables };

    if (cursor) {
      variables.cursor = cursor;
    } else {
      delete variables.cursor;
    }

    if (!variables.count || Number(variables.count) < 40) {
      variables.count = 100;
    }

    url.searchParams.set("variables", JSON.stringify(variables));
    if (Object.keys(template.features || {}).length) {
      url.searchParams.set("features", JSON.stringify(template.features));
    }
    if (Object.keys(template.fieldToggles || {}).length) {
      url.searchParams.set("fieldToggles", JSON.stringify(template.fieldToggles));
    }
    return url.toString();
  }

  function pickTweetResult(node) {
    if (!node || typeof node !== "object") return null;
    if (node.tweet_results?.result) return node.tweet_results.result;
    if (node.result?.legacy && node.result?.core) return node.result;
    if (node.legacy && node.core) return node;

    for (const value of Object.values(node)) {
      const found = pickTweetResult(value);
      if (found) return found;
    }
    return null;
  }

  function collectObjectsByKey(root, key, out = []) {
    if (!root || typeof root !== "object") return out;

    if (Array.isArray(root)) {
      for (const item of root) {
        collectObjectsByKey(item, key, out);
      }
      return out;
    }

    if (Object.prototype.hasOwnProperty.call(root, key)) {
      out.push(root[key]);
    }

    for (const value of Object.values(root)) {
      collectObjectsByKey(value, key, out);
    }

    return out;
  }

  function collectCursorValues(root, out = []) {
    if (!root || typeof root !== "object") return out;

    if (Array.isArray(root)) {
      for (const item of root) {
        collectCursorValues(item, out);
      }
      return out;
    }

    if (root.cursorType === "Bottom" && root.value) {
      out.push(root.value);
    }

    for (const value of Object.values(root)) {
      collectCursorValues(value, out);
    }

    return out;
  }

  function extractText(result) {
    return (
      result?.note_tweet?.note_tweet_results?.result?.text ||
      result?.legacy?.full_text ||
      result?.legacy?.text ||
      ""
    ).trim();
  }

  function dedupe(values) {
    return [...new Set((values || []).filter(Boolean))];
  }

  function extractExpandedUrls(result) {
    const urls = [];
    const legacyUrls = result?.legacy?.entities?.urls || [];
    for (const item of legacyUrls) {
      if (item?.expanded_url) urls.push(item.expanded_url);
      else if (item?.url) urls.push(item.url);
    }
    const noteUrls = result?.note_tweet?.note_tweet_results?.result?.entity_set?.urls || [];
    for (const item of noteUrls) {
      if (item?.expanded_url) urls.push(item.expanded_url);
      else if (item?.url) urls.push(item.url);
    }
    const media = result?.legacy?.entities?.media || [];
    for (const item of media) {
      if (item?.expanded_url) urls.push(item.expanded_url);
    }
    return dedupe(urls);
  }

  function findNestedTweetResult(root, seen = new Set()) {
    if (!root || typeof root !== "object") return null;
    if (seen.has(root)) return null;
    seen.add(root);

    if (root?.__typename === "Tweet" && (root?.rest_id || root?.legacy?.id_str)) {
      return root;
    }

    for (const value of Object.values(root)) {
      const direct = value?.result?.__typename === "Tweet" ? value.result : null;
      if (direct) return direct;
      const found = findNestedTweetResult(value, seen);
      if (found) return found;
    }
    return null;
  }

  function extractTweetItem(result) {
    const userResult = result?.core?.user_results?.result;
    const legacy = result?.legacy;
    const userLegacy = userResult?.legacy;
    const userCore = userResult?.core;
    const userHandle = userLegacy?.screen_name || userCore?.screen_name || "";
    const displayName = userLegacy?.name || userCore?.name || "";
    const id = result?.rest_id || legacy?.id_str || "";
    const url = normalizeStatusUrl(userHandle, id);

    if (!url) return null;

    const quotedResult =
      result?.quoted_status_result?.result ||
      findNestedTweetResult(result?.quoted_status_result) ||
      findNestedTweetResult(result?.legacy?.quoted_status_result);
    const retweetedResult =
      result?.legacy?.retweeted_status_result?.result ||
      findNestedTweetResult(result?.legacy?.retweeted_status_result);

    return {
      id,
      url,
      handle: userHandle ? `@${userHandle}` : "",
      displayName,
      publishedAt: legacy?.created_at || "",
      text: extractText(result),
      links: extractExpandedUrls(result),
      quotedTweet: quotedResult ? extractTweetItem(quotedResult) : null,
      retweetedTweet: retweetedResult ? extractTweetItem(retweetedResult) : null
    };
  }

  function extractEntriesAndCursor(payload) {
    const entryList = [];
    const instructions = collectObjectsByKey(payload, "instructions");

    function consumeEntry(entry) {
      if (!entry || typeof entry !== "object") return;
      entryList.push(entry);

      const content = entry.content || {};
      if (Array.isArray(content.items)) {
        for (const item of content.items) {
          entryList.push(item);
        }
      }
    }

    for (const instructionGroup of instructions) {
      if (!Array.isArray(instructionGroup)) continue;
      for (const instruction of instructionGroup) {
        if (Array.isArray(instruction?.entries)) {
          instruction.entries.forEach(consumeEntry);
        }
        if (instruction?.entry) {
          consumeEntry(instruction.entry);
        }
      }
    }

    const cursors = collectCursorValues(payload);
    const cursor = cursors.length ? cursors[cursors.length - 1] : null;

    const items = [];
    for (const entry of entryList) {
      const tweetResult = pickTweetResult(entry);
      if (!tweetResult) continue;
      const item = extractTweetItem(tweetResult);
      if (item) items.push(item);
    }

    return { items, cursor };
  }

  async function collectLikesViaApi(blueprint) {
    const headers = buildHeaders(blueprint);
    const template = buildRequestTemplate(blueprint);
    const seen = new Map();
    const cached = await chrome.storage.local.get(["lastExport"]);
    const frontierUrls = new Set((cached?.lastExport?.frontierUrls || []).filter(Boolean));
    let cursor = null;
    let pages = 0;
    let stagnantPages = 0;
    let frontierReached = false;

    while (pages < MAX_API_PAGES) {
      await reportProgress({
        state: "fetching_api",
        detail: `Fetching Likes API page ${pages + 1}.`,
        itemCount: seen.size
      });

      const requestUrl = buildLikesRequestUrl(template, cursor);
      const response = await fetch(requestUrl, {
        method: "GET",
        credentials: "include",
        headers
      });

      if (!response.ok) {
        throw new Error(`Likes API returned ${response.status} ${response.statusText}`);
      }

      const payload = await response.json();
      const { items, cursor: nextCursor } = extractEntriesAndCursor(payload);

      if (pages === 0) {
        const instructionGroups = collectObjectsByKey(payload, "instructions");
        await reportProgress({
          state: "fetching_api",
          detail: `Fetching Likes API page 1. instructionGroups=${instructionGroups.length}, parsedItems=${items.length}`,
          itemCount: seen.size,
          debugPreview: safePreview({
            topLevelKeys: Object.keys(payload || {}),
            instructionGroups: instructionGroups.length,
            firstInstructionGroupType: Array.isArray(instructionGroups[0]) ? "array" : typeof instructionGroups[0],
            firstInstructionGroupPreview: instructionGroups[0],
            firstCursor: nextCursor,
            parsedItems: items.slice(0, 3)
          })
        });
      }

      let added = 0;
      let frontierHits = 0;
      for (const item of items) {
        if (frontierUrls.has(item.url)) {
          frontierHits += 1;
        }
        if (!item.url || seen.has(item.url)) continue;
        seen.set(item.url, item);
        added += 1;
      }

      pages += 1;
      stagnantPages = added === 0 ? stagnantPages + 1 : 0;
      if (frontierHits > 0) {
        frontierReached = true;
      }

      if (!nextCursor || nextCursor === cursor) {
        break;
      }
      if (frontierReached) {
        break;
      }
      if (stagnantPages >= 4) {
        break;
      }

      cursor = nextCursor;
      await sleep(API_PAGE_WAIT_MS);
    }

    await reportProgress({
      state: "fetched_api",
      detail: frontierReached
        ? `Fetched ${seen.size} liked posts and stopped at the previous export frontier.`
        : `Fetched ${seen.size} liked posts from the Likes API.`,
      itemCount: seen.size
    });

    return [...seen.values()];
  }

  function escapeInline(text) {
    return String(text || "").replace(/\|/g, "\\|");
  }

  function buildMarkdown(items) {
    const exportedAt = new Date().toISOString();
    const lines = [
      "---",
      "type: x_likes_export",
      `exported_at: ${exportedAt}`,
      `source_page: ${window.location.href}`,
      `item_count: ${items.length}`,
      "---",
      "",
      "# X Likes Export",
      ""
    ];

    items.forEach((item, index) => {
      lines.push(`## ${index + 1}. ${item.handle || item.displayName || item.url}`);
      lines.push("");
      if (item.displayName) lines.push(`- 作者：${escapeInline(item.displayName)}`);
      if (item.handle) lines.push(`- 账号：${escapeInline(item.handle)}`);
      if (item.publishedAt) lines.push(`- 时间：${item.publishedAt}`);
      lines.push(`- 链接：${item.url}`);
      lines.push("");
      lines.push(item.text || "_No tweet text extracted._");
      lines.push("");
    });

    return lines.join("\n");
  }

  function buildBaseName() {
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const ts = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
    return `x-likes-export-${ts}`;
  }

  async function saveDebugPayload(baseName, payload) {
    const compact = JSON.stringify(payload, null, 2);
    await chrome.runtime.sendMessage({
      type: "XLIKES_DOWNLOAD_FILES",
      baseName: `${baseName}-debug`,
      files: [
        {
          extension: "json",
          mime: "application/json;charset=utf-8",
          content: compact
        }
      ]
    });
  }

  async function runExport(externalBlueprint = null) {
    if (!isLikesPage()) {
      throw new Error("Background tab is not on an X Likes page.");
    }
    if (state.running) {
      throw new Error("An export is already running.");
    }

    state.running = true;
    try {
      installBlueprintListener();
      let blueprint = externalBlueprint;
      if (!blueprint?.url) {
        await sleep(PAGE_SETTLE_MS);
        blueprint = await waitForBlueprint();
      } else {
        await reportProgress({
          state: "captured_blueprint",
          detail: "Captured the Likes API blueprint from browser network requests."
        });
      }
      const items = await collectLikesViaApi(blueprint);

      if (!items.length) {
        const baseName = buildBaseName();
        await saveDebugPayload(baseName, {
          blueprint,
          page: window.location.href,
          note: "No items parsed from Likes API. Use this payload snapshot to adapt the parser."
        });
        throw new Error("No liked posts were extracted from the Likes API.");
      }

      await reportProgress({
        state: "saving_files",
        detail: `Saving ${items.length} liked posts to Markdown and JSON.`,
        itemCount: items.length
      });

      const baseName = buildBaseName();
      const markdown = buildMarkdown(items);
      const json = JSON.stringify(
        {
          exportedAt: new Date().toISOString(),
          sourcePage: window.location.href,
          itemCount: items.length,
          items
        },
        null,
        2
      );

      const downloadResult = await chrome.runtime.sendMessage({
        type: "XLIKES_DOWNLOAD_FILES",
        baseName,
        files: [
          {
            extension: "md",
            mime: "text/markdown;charset=utf-8",
            content: markdown
          },
          {
            extension: "json",
            mime: "application/json;charset=utf-8",
            content: json
          }
        ]
      });

      if (!downloadResult?.ok) {
        throw new Error(downloadResult?.error || "Failed to save export files.");
      }

      const saveDetail =
        downloadResult?.mode === "obsidian_bridge"
          ? `Saved ${items.length} liked posts directly to Obsidian at ${downloadResult.target_dir || "bridge target"}`
          : `Saved ${items.length} liked posts as ${baseName}.md and ${baseName}.json`;

      await chrome.storage.local.set({
        lastExport: {
          at: new Date().toISOString(),
          page: window.location.href,
          itemCount: items.length,
          baseName,
          mode: downloadResult?.mode || "downloads",
          frontierUrls: items.slice(0, 50).map((item) => item.url).filter(Boolean)
        }
      });

      await reportProgress({
        state: "saved_files",
        detail: saveDetail,
        itemCount: items.length
      });

      return { itemCount: items.length, baseName };
    } finally {
      state.running = false;
    }
  }

  installBlueprintListener();

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "XLIKES_PING") {
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "XLIKES_RESOLVE_SELF") {
      if (!isHomeLikePage()) {
        sendResponse({ ok: false, error: "Background tab is not on an X home page." });
        return;
      }

      resolveCurrentHandle()
        .then((handle) => sendResponse({ ok: true, handle }))
        .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
      return true;
    }

    if (message?.type !== "XLIKES_EXPORT_START") {
      return;
    }

    runExport(message?.blueprint || null)
      .then((result) => {
        sendResponse({
          ok: true,
          message: `Done. Exported ${result.itemCount} liked posts as ${result.baseName}.md and ${result.baseName}.json`
        });
      })
      .catch((error) => {
        sendResponse({
          ok: false,
          error: error.message || String(error)
        });
      });

    return true;
  });
})();
