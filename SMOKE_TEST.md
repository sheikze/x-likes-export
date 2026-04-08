# Smoke Test

This is the minimum manual validation flow for the project.

## Goal

Verify that:

1. the extension loads
2. a logged-in X session can export likes
3. the local bridge accepts extension-origin requests
4. files land where expected

## A. Extension-only export

1. load the unpacked extension from:

```text
chrome_extension
```

2. log in to X in the same Chromium profile
3. open the extension popup
4. click `Export My Likes`
5. confirm that both files are produced:
   - `x-likes-export-<timestamp>.md`
   - `x-likes-export-<timestamp>.json`

Expected result:

- status page reaches `done`
- item count is non-zero
- exported files are readable

## B. Bridge export

1. start the bridge:

```bash
python3 scripts/obsidian_bridge.py \
  --host 127.0.0.1 \
  --port 8767 \
  --allow-origin "chrome-extension://<your-extension-id>" \
  --target-dir "/tmp/x-likes-test"
```

2. repeat the export from the extension
3. confirm files are written to `/tmp/x-likes-test`

Expected result:

- bridge returns `ok: true`
- exported files exist only under the target directory
- no browser-origin request from a normal web page is accepted

## C. Minimal automated check

Run:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

Expected result:

- tests pass
- bridge path confinement and origin policy remain intact
