# X Likes Export

`x-likes-export` exports liked posts from a logged-in X/Twitter browser session to:

- `Markdown`
- `JSON`

It is designed for local-first workflows. The default path is:

1. use a Chromium extension to read the current logged-in X session
2. call X's Likes GraphQL endpoint
3. export snapshots locally
4. optionally POST the results into a local bridge for Obsidian or other downstream processing

## What This Repo Contains

### 1. Browser extension

Path:

- [chrome_extension](./chrome_extension)

Responsibilities:

- detect the current logged-in account
- resolve the current account's Likes page
- capture the Likes API request blueprint
- paginate through liked posts
- export `md/json`
- optionally send results to a local bridge

### 2. Local bridge

Path:

- [scripts/obsidian_bridge.py](./scripts/obsidian_bridge.py)

Responsibilities:

- listen on `http://127.0.0.1:8767`
- receive exported files from the extension
- write them into a target directory
- optionally run a post-import hook

### 3. Example downstream integration

Path:

- [examples/ExampleName](./examples/ExampleName)

These files are examples, not the core project:

- [x_likes_pull.py](./examples/ExampleName/x_likes_pull.py)
- [x_likes_brief.py](./examples/ExampleName/x_likes_brief.py)

They show how one Obsidian-based knowledge workflow can:

- pull snapshots directly
- rebuild a daily brief
- enrich research output downstream

## Quick Start

### Option A: export to local downloads

1. open your Chromium browser extensions page
2. enable `Developer mode`
3. choose `Load unpacked`
4. select:

```text
chrome_extension
```

Then:

1. log in to X in the same browser profile
2. open the extension popup
3. click `Export My Likes`

The extension will export:

- `x-likes-export-<timestamp>.md`
- `x-likes-export-<timestamp>.json`

### Option B: export directly into an Obsidian vault

Start the bridge:

```bash
python3 scripts/obsidian_bridge.py \
  --host 127.0.0.1 \
  --port 8767 \
  --allow-origin "chrome-extension://<your-extension-id>" \
  --target-dir "/path/to/your/vault/raw/X Likes/source"
```

If you want to trigger a downstream hook after import:

```bash
python3 scripts/obsidian_bridge.py \
  --allow-origin "chrome-extension://<your-extension-id>" \
  --target-dir "/path/to/your/vault/raw/X Likes/source" \
  --post-import-cmd "python3 /path/to/your/vault/scripts/x_likes_brief.py"
```

If you omit `--allow-origin`, the bridge accepts any `chrome-extension://...` origin but rejects normal web page origins.

## Extension Permissions

The extension currently requests:

- `tabs`
- `windows`
- `storage`
- `downloads`
- `scripting`
- `webRequest`

Host permissions:

- `https://x.com/*`
- `https://twitter.com/*`
- `http://127.0.0.1:8767/*`

Reasoning:

- `tabs` / `windows`: open and manage the hidden or helper pages used during export
- `storage`: persist export status and incremental state
- `downloads`: save exported files locally
- `scripting`: inject runtime logic into X pages
- `webRequest`: capture the Likes request blueprint from X
- `127.0.0.1:8767`: optional local bridge target

## Security Boundary

Read this before using the project:

- the extension relies on an already logged-in X browser session
- it does **not** ask you to type your X password into this repo
- it does **not** ship with any external server component
- the optional bridge writes only to `127.0.0.1`
- the bridge rejects ordinary web page origins by default

Important:

- the extension can access X requests from the browser profile where it is installed
- the example direct-pull scripts may read local browser session material when explicitly enabled
- those example scripts are not the default path of the project

For details, see:

- [SECURITY.md](./SECURITY.md)

## Project Scope

This repository is intentionally small:

- core export logic lives in the extension
- local writing/sync lives in the bridge
- knowledge-base-specific reporting stays in downstream repos

This means:

- if you only want `md/json` export, you only need the extension
- if you want vault sync, add the bridge
- if you want briefs, research reports, or topic pages, keep those in your own repo

## ExampleName Example

The example integration is intentionally generic and parameterized:

- root path comes from `XLIKES_EXAMPLE_ROOT`
- Chrome profile comes from `XLIKES_CHROME_PROFILE`
- direct keychain/cookie access is gated behind `XLIKES_ALLOW_X_KEYCHAIN`

That example is useful if you want:

- direct snapshot pulls without a browser popup
- daily brief regeneration
- downstream enrichment or research workflows

It is not intended to be copied blindly into another repo without review.

## Limitations

- the project depends on X's current internal request shape
- if X changes its GraphQL structure, the extension will need updates
- export quality depends on the current browser session being valid
- the example direct-pull path is intentionally more sensitive than the extension path
- large exports should use the local bridge instead of the inline `downloads` fallback

## Recommended Use

For most users:

1. use the extension as the default export path
2. add the local bridge only if you need vault sync
3. keep briefs, reports, and domain-specific rules in a separate downstream repository

## License

This repository is released under the [MIT License](./LICENSE).
