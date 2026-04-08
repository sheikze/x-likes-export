# Security Notes

This repository has two different trust levels:

## 1. Default path: browser extension export

The default workflow is:

- install the unpacked Chromium extension
- stay logged in to X in that browser profile
- export likes from the popup or status page

In this mode:

- you do **not** type your X password into this project
- exports are generated from the browser's existing logged-in session
- files are either downloaded locally or POSTed to a local bridge on `127.0.0.1`

This is the intended primary path.

## 2. More sensitive path: direct-pull example scripts

The example scripts in:

- [examples/ExampleName](./examples/ExampleName)

may read:

- local Chromium cookie storage
- local keychain material needed to decrypt Chromium cookies

That path is more sensitive because it bypasses the extension and talks to X directly from a local script.

It is therefore:

- example-only
- opt-in
- gated behind environment variables such as `XLIKES_ALLOW_X_KEYCHAIN`

If you do not want any local cookie/keychain access, do not run those example scripts.

## Local bridge

The bridge:

- listens on `127.0.0.1`
- writes received content into a local target directory
- may optionally run a post-import shell command

Operational implications:

- do not expose the bridge to a public interface
- review any `--post-import-cmd` carefully before enabling it
- treat the bridge as a local automation tool, not as a network service

## What this repo does not do

- it does not include a hosted backend
- it does not upload your browser session to a remote server by default
- it does not include your X password, tokens, or cookie values in the repository

## Operational recommendation

If you are packaging this for broader use:

1. keep the extension path as the default
2. document the example scripts as advanced/opt-in tooling
3. avoid shipping personal vault paths, profile names, or private repo conventions
