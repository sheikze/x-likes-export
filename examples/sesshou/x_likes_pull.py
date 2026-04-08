#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

sys.dont_write_bytecode = True


ROOT = Path("/Volumes/Huis/Sesshou")
SOURCE_DIR = ROOT / "raw" / "X Likes" / "source"
BRIEF_SCRIPT = ROOT / "scripts" / "x_likes_brief.py"

PROFILE_DIR = "Profile 1"
COOKIE_DB = Path.home() / "Library/Application Support/Google/Chrome" / PROFILE_DIR / "Cookies"
CHROME_SAFE_STORAGE_SERVICE = "Chrome Safe Storage"
X_DOMAIN = ".x.com"
LIKES_QUERY_NAME = "Likes"
LIKES_PAGE_WAIT_HEADERS = {
    "user-agent": "Mozilla/5.0",
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
API_HEADERS_BASE = {
    "user-agent": "Mozilla/5.0",
    "accept": "*/*",
    "x-twitter-active-user": "yes",
    "x-twitter-auth-type": "OAuth2Session",
    "x-twitter-client-language": "zh-cn",
}
API_PAGE_WAIT_MS = 1.2
MAX_API_PAGES = 400
ALLOW_ENV = "SESSHOU_ALLOW_X_KEYCHAIN"


def run(cmd: list[str], *, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(cmd, input=input_bytes, capture_output=True, check=True)
    return result.stdout


def get_safe_storage_secret() -> str:
    return run(
        ["security", "find-generic-password", "-s", CHROME_SAFE_STORAGE_SERVICE, "-w"]
    ).decode().strip()


def decrypt_cookie(encrypted_value: bytes, safe_storage_secret: str) -> str:
    if not encrypted_value.startswith(b"v10"):
        raise ValueError("Unsupported Chrome cookie format.")

    key = hashlib.pbkdf2_hmac("sha1", safe_storage_secret.encode(), b"saltysalt", 1003, dklen=16)
    iv_hex = ("20" * 16)

    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(encrypted_value[3:])
        tmp_path = tmp.name

    try:
        decrypted = run(
            [
                "openssl",
                "enc",
                "-d",
                "-aes-128-cbc",
                "-K",
                key.hex(),
                "-iv",
                iv_hex,
                "-in",
                tmp_path,
            ]
        )
    finally:
        os.unlink(tmp_path)

    # Chrome prefixes the decrypted value with a 32-byte host hash.
    return decrypted[32:].decode()


def get_cookie_value(name: str) -> str:
    secret = get_safe_storage_secret()
    con = sqlite3.connect(f"file:{COOKIE_DB}?mode=ro", uri=True)
    try:
        row = con.execute(
            "select encrypted_value from cookies where host_key=? and name=?",
            (X_DOMAIN, name),
        ).fetchone()
    finally:
        con.close()

    if not row:
        raise RuntimeError(f"Missing Chrome cookie: {name}")
    return decrypt_cookie(row[0], secret)


def fetch_text(url: str, headers: dict[str, str]) -> tuple[str, str]:
    request = urllib.request.Request(url, headers=headers)
    errors: list[str] = []
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8", "ignore")
                return response.geturl(), body
        except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError) as error:
            errors.append(f"{type(error).__name__}: {error}")
            if attempt == 3:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch {url}: {' | '.join(errors)}")


def fetch_json(url: str, headers: dict[str, str]) -> dict:
    request = urllib.request.Request(url, headers=headers)
    errors: list[str] = []
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8", "ignore"))
        except (urllib.error.URLError, http.client.RemoteDisconnected, TimeoutError, json.JSONDecodeError) as error:
            errors.append(f"{type(error).__name__}: {error}")
            if attempt == 3:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"Failed to fetch JSON from {url}: {' | '.join(errors)}")


def latest_snapshot() -> Path | None:
    candidates = sorted(SOURCE_DIR.glob("x-likes-export-*.json"))
    return candidates[-1] if candidates else None


def latest_snapshot_payload() -> dict | None:
    path = latest_snapshot()
    if not path:
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def resolve_likes_page() -> tuple[str, str]:
    latest = latest_snapshot()
    if latest:
        snapshot = json.loads(latest.read_text())
        source_page = snapshot.get("sourcePage") or snapshot.get("source_page")
        if source_page:
            parsed = urllib.parse.urlparse(source_page)
            handle = parsed.path.strip("/").split("/")[0]
            if handle:
                return handle, f"https://x.com/{handle}/likes"
    raise RuntimeError("Could not resolve current X likes page from existing snapshots.")


def parse_user_id_from_likes_html(html: str, handle: str) -> str:
    patterns = [
        rf'"screen_name":"{re.escape(handle)}","id_str":"(\d+)"',
        rf'"name":"[^"]*","screen_name":"{re.escape(handle)}","id_str":"(\d+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)
    raise RuntimeError(f"Could not resolve user id for @{handle} from likes page HTML.")


def parse_main_js_url(html: str) -> str:
    match = re.search(r'href="(https://abs\.twimg\.com/responsive-web/client-web/main\.[^"]+\.js)"', html)
    if not match:
        raise RuntimeError("Could not locate X main.js bundle URL.")
    return match.group(1)


def parse_likes_query_id(js_text: str) -> str:
    match = re.search(r'queryId:"([^"]+)",operationName:"Likes"', js_text)
    if not match:
        raise RuntimeError("Could not locate X Likes GraphQL query id.")
    return match.group(1)


def collect_objects_by_key(root, key: str, out: list | None = None) -> list:
    if out is None:
        out = []
    if not isinstance(root, (dict, list)):
        return out
    if isinstance(root, list):
        for item in root:
            collect_objects_by_key(item, key, out)
        return out
    if key in root:
        out.append(root[key])
    for value in root.values():
        collect_objects_by_key(value, key, out)
    return out


def collect_cursor_values(root, out: list[str] | None = None) -> list[str]:
    if out is None:
        out = []
    if not isinstance(root, (dict, list)):
        return out
    if isinstance(root, list):
        for item in root:
            collect_cursor_values(item, out)
        return out
    if root.get("cursorType") == "Bottom" and root.get("value"):
        out.append(root["value"])
    for value in root.values():
        collect_cursor_values(value, out)
    return out


def pick_tweet_result(node):
    if not isinstance(node, dict):
        return None
    if isinstance(node.get("tweet_results"), dict) and isinstance(node["tweet_results"].get("result"), dict):
        return node["tweet_results"]["result"]
    if node.get("legacy") and node.get("core"):
        return node
    for value in node.values():
        found = pick_tweet_result(value)
        if found:
            return found
    if isinstance(node, list):
        for item in node:
            found = pick_tweet_result(item)
            if found:
                return found
    return None


def dedupe(values: list[str]) -> list[str]:
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return seen


def normalize_status_url(handle: str, tweet_id: str) -> str | None:
    if not handle or not tweet_id:
        return None
    return f"https://x.com/{handle}/status/{tweet_id}"


def extract_text(result: dict) -> str:
    return (
        (((result.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}).get("text")
        or ((result.get("legacy") or {}).get("full_text"))
        or ((result.get("legacy") or {}).get("text"))
        or ""
    ).strip()


def extract_expanded_urls(result: dict) -> list[str]:
    urls: list[str] = []
    for item in (((result.get("legacy") or {}).get("entities") or {}).get("urls") or []):
        if item.get("expanded_url"):
            urls.append(item["expanded_url"])
        elif item.get("url"):
            urls.append(item["url"])
    note_urls = ((((result.get("note_tweet") or {}).get("note_tweet_results") or {}).get("result") or {}).get("entity_set") or {}).get("urls") or []
    for item in note_urls:
        if item.get("expanded_url"):
            urls.append(item["expanded_url"])
        elif item.get("url"):
            urls.append(item["url"])
    for item in ((((result.get("legacy") or {}).get("entities") or {}).get("media") or [])):
        if item.get("expanded_url"):
            urls.append(item["expanded_url"])
    return dedupe(urls)


def find_nested_tweet_result(root, seen: set[int] | None = None):
    if seen is None:
        seen = set()
    if not isinstance(root, dict):
        return None
    marker = id(root)
    if marker in seen:
        return None
    seen.add(marker)
    if root.get("__typename") == "Tweet" and (root.get("rest_id") or ((root.get("legacy") or {}).get("id_str"))):
        return root
    for value in root.values():
        if isinstance(value, dict) and isinstance(value.get("result"), dict) and value["result"].get("__typename") == "Tweet":
            return value["result"]
        if isinstance(value, dict):
            found = find_nested_tweet_result(value, seen)
            if found:
                return found
        elif isinstance(value, list):
            for item in value:
                found = find_nested_tweet_result(item, seen)
                if found:
                    return found
    return None


def extract_tweet_item(result: dict) -> dict | None:
    user_result = (((result.get("core") or {}).get("user_results") or {}).get("result")) or {}
    legacy = result.get("legacy") or {}
    user_legacy = user_result.get("legacy") or {}
    user_core = user_result.get("core") or {}
    handle = user_legacy.get("screen_name") or user_core.get("screen_name") or ""
    display_name = user_legacy.get("name") or user_core.get("name") or ""
    tweet_id = result.get("rest_id") or legacy.get("id_str") or ""
    url = normalize_status_url(handle, tweet_id)
    if not url:
        return None

    quoted_result = (
        ((result.get("quoted_status_result") or {}).get("result"))
        or find_nested_tweet_result(result.get("quoted_status_result"))
        or find_nested_tweet_result((legacy.get("quoted_status_result")))
    )
    retweeted_result = (
        (((legacy.get("retweeted_status_result") or {}).get("result")))
        or find_nested_tweet_result(legacy.get("retweeted_status_result"))
    )

    return {
        "id": tweet_id,
        "url": url,
        "handle": f"@{handle}" if handle else "",
        "displayName": display_name,
        "publishedAt": legacy.get("created_at", ""),
        "text": extract_text(result),
        "links": extract_expanded_urls(result),
        "quotedTweet": extract_tweet_item(quoted_result) if quoted_result else None,
        "retweetedTweet": extract_tweet_item(retweeted_result) if retweeted_result else None,
    }


def extract_entries_and_cursor(payload: dict) -> tuple[list[dict], str | None]:
    entry_list: list[dict] = []
    instructions = collect_objects_by_key(payload, "instructions")

    def consume_entry(entry):
        if not isinstance(entry, dict):
            return
        entry_list.append(entry)
        content = entry.get("content") or {}
        if isinstance(content.get("items"), list):
            for item in content["items"]:
                if isinstance(item, dict):
                    entry_list.append(item)

    for instruction_group in instructions:
        if not isinstance(instruction_group, list):
            continue
        for instruction in instruction_group:
            if isinstance(instruction.get("entries"), list):
                for entry in instruction["entries"]:
                    consume_entry(entry)
            if isinstance(instruction.get("entry"), dict):
                consume_entry(instruction["entry"])

    cursors = collect_cursor_values(payload)
    cursor = cursors[-1] if cursors else None

    items: list[dict] = []
    for entry in entry_list:
        tweet_result = pick_tweet_result(entry)
        if not tweet_result:
            continue
        item = extract_tweet_item(tweet_result)
        if item:
            items.append(item)

    return items, cursor


def escape_inline(text: str) -> str:
    return str(text or "").replace("|", "\\|")


def build_markdown(items: list[dict], source_page: str, exported_at: str) -> str:
    lines = [
        "---",
        "type: x_likes_export",
        f"exported_at: {exported_at}",
        f"source_page: {source_page}",
        f"item_count: {len(items)}",
        "---",
        "",
        "# X Likes Export",
        "",
    ]
    for index, item in enumerate(items, start=1):
        lines.append(f"## {index}. {item.get('handle') or item.get('displayName') or item.get('url')}")
        lines.append("")
        if item.get("displayName"):
            lines.append(f"- 作者：{escape_inline(item['displayName'])}")
        if item.get("handle"):
            lines.append(f"- 账号：{escape_inline(item['handle'])}")
        lines.append(f"- 链接：{item['url']}")
        if item.get("publishedAt"):
            lines.append(f"- 时间：{item['publishedAt']}")
        lines.append("")
        lines.append(item.get("text") or "_No tweet text extracted._")
        lines.append("")
    return "\n".join(lines)


def build_base_name(now: datetime) -> str:
    return now.strftime("x-likes-export-%Y%m%d-%H%M%S")


def collect_frontier_urls() -> set[str]:
    latest = latest_snapshot()
    if not latest:
        return set()
    try:
        snapshot = json.loads(latest.read_text())
    except Exception:
        return set()
    urls = [item.get("url") for item in snapshot.get("items", [])[:50] if item.get("url")]
    return set(urls)


def resolve_bearer_token(main_js_text: str) -> str:
    match = re.search(r"Bearer (AAAAAAAAAAAAAAAAAAAAA[^\"']+)", main_js_text)
    if not match:
        raise RuntimeError("Could not resolve X bearer token from main.js.")
    return match.group(1)


def fetch_likes_snapshot() -> tuple[str, list[dict]]:
    handle, likes_page = resolve_likes_page()
    auth_token = get_cookie_value("auth_token")
    ct0 = get_cookie_value("ct0")

    page_headers = {
        **LIKES_PAGE_WAIT_HEADERS,
        "cookie": f"auth_token={auth_token}; ct0={ct0}",
        "x-csrf-token": ct0,
    }
    _, likes_html = fetch_text(likes_page, page_headers)
    user_id = parse_user_id_from_likes_html(likes_html, handle)

    main_js_url = parse_main_js_url(likes_html)
    _, main_js_text = fetch_text(main_js_url, {"user-agent": "Mozilla/5.0"})
    query_id = parse_likes_query_id(main_js_text)
    bearer = resolve_bearer_token(main_js_text)

    frontier_urls = collect_frontier_urls()
    seen: dict[str, dict] = {}
    cursor = None
    stagnant_pages = 0
    frontier_reached = False

    headers = {
        **API_HEADERS_BASE,
        "authorization": f"Bearer {bearer}",
        "x-csrf-token": ct0,
        "cookie": f"auth_token={auth_token}; ct0={ct0}",
    }

    for _ in range(MAX_API_PAGES):
        variables = {
            "userId": user_id,
            "count": 100,
            "includePromotedContent": False,
        }
        if cursor:
            variables["cursor"] = cursor

        params = {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": "{}",
            "fieldToggles": "{}",
        }
        request_url = f"https://x.com/i/api/graphql/{query_id}/{LIKES_QUERY_NAME}?{urllib.parse.urlencode(params)}"
        payload = fetch_json(request_url, headers)

        items, next_cursor = extract_entries_and_cursor(payload)
        added = 0
        frontier_hits = 0
        for item in items:
            if item["url"] in frontier_urls:
                frontier_hits += 1
            if item["url"] in seen:
                continue
            seen[item["url"]] = item
            added += 1

        stagnant_pages = stagnant_pages + 1 if added == 0 else 0
        if frontier_hits > 0:
            frontier_reached = True

        if not next_cursor or next_cursor == cursor or frontier_reached or stagnant_pages >= 4:
            break
        cursor = next_cursor

    return likes_page, list(seen.values())


def write_snapshot(source_page: str, items: list[dict]) -> tuple[Path, Path]:
    now = datetime.now().astimezone()
    exported_at = now.isoformat(timespec="seconds")
    base_name = build_base_name(now)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)

    md_path = SOURCE_DIR / f"{base_name}.md"
    json_path = SOURCE_DIR / f"{base_name}.json"

    md_path.write_text(build_markdown(items, source_page, exported_at))
    json_path.write_text(
        json.dumps(
            {
                "exportedAt": exported_at,
                "sourcePage": source_page,
                "itemCount": len(items),
                "items": items,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return md_path, json_path


def rebuild_brief() -> None:
    run(["python3", str(BRIEF_SCRIPT)])


def main() -> None:
    if os.environ.get(ALLOW_ENV) != "1":
        raise SystemExit(
            "Direct X pull is disabled by default because it requires Chrome cookie/keychain access. "
            "Use the browser extension manual export path unless you explicitly opt in."
        )
    source_page, items = fetch_likes_snapshot()
    latest = latest_snapshot_payload()
    if latest:
        latest_urls = [item.get("url") for item in latest.get("items", []) if item.get("url")]
        current_urls = [item.get("url") for item in items if item.get("url")]
        if current_urls == latest_urls:
            print(json.dumps({"ok": True, "skipped": True, "reason": "no_new_likes", "itemCount": len(items)}, ensure_ascii=False))
            return
    md_path, json_path = write_snapshot(source_page, items)
    rebuild_brief()
    print(json.dumps({"ok": True, "itemCount": len(items), "md": str(md_path), "json": str(json_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
