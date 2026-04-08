# Changelog

## v0.2.1

- hardened the local bridge against path traversal
- restricted bridge origins to `chrome-extension://...` by default
- added explicit `--allow-origin` support for the bridge
- added content-script duplicate injection protection
- added retry and backoff for Likes API pagination
- added partial export support when pagination fails mid-run
- made large inline download fallback fail closed instead of silently breaking
- added:
  - [QUICKSTART.md](./QUICKSTART.md)
  - [SECURITY.md](./SECURITY.md)
  - [tests/test_obsidian_bridge.py](./tests/test_obsidian_bridge.py)

## v0.2.0

- initial public import of the standalone project
- packaged:
  - browser extension
  - local Obsidian bridge
  - example downstream integration
- generalized example names and paths for public release
- added MIT license
