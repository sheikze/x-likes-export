# Quick Start

This is the shortest path to a working export.

## 1. Load the extension

1. open your Chromium browser extensions page
2. enable `Developer mode`
3. choose `Load unpacked`
4. select:

```text
chrome_extension
```

## 2. Log in to X

Use the same browser profile where the extension is installed.

## 3. Export likes

Open the extension popup and click:

- `Export My Likes`

This produces:

- `x-likes-export-<timestamp>.md`
- `x-likes-export-<timestamp>.json`

## 4. Optional: write directly into an Obsidian vault

Run the local bridge:

```bash
python3 scripts/obsidian_bridge.py \
  --host 127.0.0.1 \
  --port 8767 \
  --allow-origin "chrome-extension://<your-extension-id>" \
  --target-dir "/path/to/your/vault/raw/X Likes/source"
```

Then export again from the extension.

## 5. Run the minimal regression test

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

This test suite currently checks:

- bridge filename sanitization
- output path confinement
- default origin policy
