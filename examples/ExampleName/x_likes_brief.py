#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

sys.dont_write_bytecode = True


ROOT = Path(os.environ.get("XLIKES_EXAMPLE_ROOT", "~/path/to/your/vault")).expanduser()
SOURCE_DIR = ROOT / "raw" / "X Likes" / "source"
OUTPUT_DIR = ROOT / "outputs" / "x-briefs"
OUTPUT_PATH = OUTPUT_DIR / "X Likes 每日简报.md"
CACHE_PATH = OUTPUT_DIR / ".x_likes_enrichment_cache.json"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
X_KEYCHAIN_ENV = "XLIKES_ALLOW_X_KEYCHAIN"
_X_CLIENT = None


def list_snapshots() -> list[Path]:
    return sorted(SOURCE_DIR.glob("x-likes-export-*.json"))


def load_snapshot(path: Path) -> dict:
    return json.loads(path.read_text())


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except Exception:
        return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


def parse_exported_at(snapshot: dict) -> datetime:
    value = snapshot.get("exportedAt") or snapshot.get("exported_at")
    if not value:
        return datetime.now(timezone.utc)
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=LOCAL_TZ)
    return dt


def parse_post_time(value: str) -> datetime:
    if not value:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    try:
        return parsedate_to_datetime(value)
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)


def cleaned_lines(text: str) -> list[str]:
    raw_lines = []
    for line in (text or "").splitlines():
        line = re.sub(r"https?://\S+", "", line).strip()
        if not line:
            continue
        raw_lines.append(line)
    return raw_lines


def extract_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://\S+", text or "")
    cleaned = []
    for url in urls:
        url = url.rstrip(").,，。!！?？】」\"'")
        if url:
            cleaned.append(url)
    return list(dict.fromkeys(cleaned))


def x_enrichment_enabled() -> bool:
    return os.environ.get(X_KEYCHAIN_ENV) == "1"


def get_x_client():
    global _X_CLIENT
    if _X_CLIENT is not None:
        return _X_CLIENT
    if not x_enrichment_enabled():
        return None
    try:
        import sys

        sys.path.insert(0, str(ROOT / "scripts"))
        import x_likes_pull  # type: ignore

        handle, likes_page = x_likes_pull.resolve_likes_page()
        _, likes_html = x_likes_pull.fetch_text(likes_page, x_likes_pull.LIKES_PAGE_WAIT_HEADERS)
        main_js_url = x_likes_pull.parse_main_js_url(likes_html)
        _, main_js = x_likes_pull.fetch_text(main_js_url, {"user-agent": "Mozilla/5.0"})
        bearer = x_likes_pull.resolve_bearer_token(main_js)
        auth = x_likes_pull.get_cookie_value("auth_token")
        ct0 = x_likes_pull.get_cookie_value("ct0")
        headers = dict(x_likes_pull.API_HEADERS_BASE)
        headers.update(
            {
                "authorization": f"Bearer {bearer}",
                "cookie": f"auth_token={auth}; ct0={ct0}",
                "x-csrf-token": ct0,
            }
        )
        _X_CLIENT = {
            "mod": x_likes_pull,
            "headers": headers,
            "tweet_query_id": "tmhPpO5sDermwYmq3h034A",
            "features": {
                "longform_notetweets_consumption_enabled": True,
                "longform_notetweets_inline_media_enabled": True,
                "longform_notetweets_rich_text_read_enabled": True,
                "responsive_web_twitter_article_tweet_consumption_enabled": True,
                "tweetypie_unmention_optimization_enabled": True,
                "view_counts_everywhere_api_enabled": True,
                "responsive_web_edit_tweet_api_enabled": True,
                "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
                "responsive_web_enhance_cards_enabled": False,
            },
        }
    except Exception:
        _X_CLIENT = None
    return _X_CLIENT


def fetch_x_primary_source(item: dict, cache: dict) -> dict | None:
    tweet_id = str(item.get("id") or parse_x_status_id(item.get("url", "")) or "").strip()
    if not tweet_id:
        return None
    cache_key = f"x_primary:{tweet_id}"
    if cache_key in cache:
        return cache[cache_key]

    client = get_x_client()
    if not client:
        return None

    try:
        variables = {
            "tweetId": tweet_id,
            "withCommunity": False,
            "includePromotedContent": False,
            "withVoice": False,
        }
        params = {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(client["features"], separators=(",", ":")),
        }
        url = (
            f"https://x.com/i/api/graphql/{client['tweet_query_id']}/TweetResultByRestId?"
            + urllib.parse.urlencode(params)
        )
        payload = client["mod"].fetch_json(url, client["headers"])
        result = (((payload.get("data") or {}).get("tweetResult") or {}).get("result")) or {}
        article = ((((result.get("article") or {}).get("article_results")) or {}).get("result")) or {}
        enriched = {
            "text": client["mod"].extract_text(result),
            "article_title": normalize_clause(article.get("title", "")),
            "article_preview": normalize_clause(article.get("preview_text", "")),
        }
        cache[cache_key] = enriched
        return enriched
    except Exception:
        return None


def normalize_clause(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip(" ：:;；，,。.!?！？")


def is_mostly_commentary(text: str) -> bool:
    commentary_markers = [
        "太干了",
        "终于",
        "觉悟",
        "不尊重",
        "谁下谁",
        "忍不住",
        "先分享一波",
    ]
    first_person = any(token in (text or "") for token in ["我觉得", "我已经", "我作为", "花了一周"])
    return first_person and any(marker in (text or "") for marker in commentary_markers)


def summarize_repo_roundup(lines: list[str], limit: int = 120) -> str | None:
    repos = []
    for line in lines:
        repos.extend(re.findall(r"\b[a-z0-9_.-]+/[a-z0-9_.-]+\b", line))
    repos = list(dict.fromkeys(repos))
    if len(repos) < 2:
        return None
    intro = "盘点了多个 GitHub 项目"
    if any("agent" in repo.lower() or "cod" in repo.lower() for repo in repos):
        intro = "盘点了多个 AI Agent / 编码相关项目"
    summary = f"{intro}，包括 " + "、".join(repos[:4])
    if len(repos) > 4:
        summary += " 等"
    if len(summary) > limit:
        summary = summary[:limit].rstrip(" ，,;；:：") + "…"
    return summary


def summarize_project_blocks(lines: list[str], limit: int = 120) -> str | None:
    projects: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = normalize_clause(lines[i])
        if line.endswith("skill") or line.endswith("Skills") or line.endswith("skills") or re.match(r"^[A-Za-z0-9_.-]{2,40}：?$", line):
            name = line.rstrip("：:")
            desc = ""
            for j in range(i + 1, min(i + 4, len(lines))):
                probe = normalize_clause(lines[j])
                if not probe or "🌟" in probe:
                    continue
                if len(probe) >= 8:
                    desc = probe
                    break
            if desc:
                projects.append((name, desc))
        i += 1
    if len(projects) < 2:
        return None
    parts = []
    for name, desc in projects[:4]:
        short = desc[:26].rstrip(" ，,;；:：") + ("…" if len(desc) > 26 else "")
        parts.append(f"{name}（{short}）")
    summary = f"汇总了 {len(projects)} 个项目，主要包括 " + "、".join(parts)
    if len(summary) > limit:
        summary = summary[:limit].rstrip(" ，,;；:：") + "…"
    return summary


def summarize_numbered_list(lines: list[str], limit: int = 120) -> str | None:
    numbered = []
    for line in lines:
        m = re.match(r"^[0-9]+(?:\uFE0F?\u20E3|[.)、])\s*(.+)$", line)
        if m:
            numbered.append(normalize_clause(m.group(1)))
    if len(numbered) < 2:
        return None
    intro = ""
    for line in lines[:4]:
        norm = normalize_clause(line)
        if norm and not re.match(r"^[0-9]+(?:\uFE0F?\u20E3|[.)、])\s*", norm):
            if norm in {"准备开始造轮子了", "先来个简单的产品原型交互看看效果"}:
                continue
            intro = norm
            break
    summary = intro + "，功能包括" if intro else "主要内容包括"
    summary += "、".join(numbered[:5])
    if len(summary) > limit:
        summary = summary[:limit].rstrip(" ，,;；:：") + "…"
    return summary


def summarize_informative_sentences(lines: list[str], limit: int = 120) -> str:
    informative = []
    for line in lines:
        norm = normalize_clause(line)
        if not norm:
            continue
        if re.fullmatch(r"[0-9]+🌟", norm):
            continue
        informative.append(norm)
    if not informative:
        return "正文未提取到可用内容。"
    summary = informative[0]
    if len(summary) < 36 and len(informative) > 1:
        summary = f"{summary}；{informative[1]}"
    if len(summary) > limit:
        summary = summary[:limit].rstrip(" ，,;；:：") + "…"
    return summary


def summarize_commentary_or_teaser(text: str, lines: list[str], limit: int = 120) -> str | None:
    merged = normalize_clause("；".join(lines))

    if "app store" in (text or "").lower() and "api" in (text or "").lower():
        summary = "API 工作流替代 App 堆砌，尽量不靠额外安装软件。"
        return summary[:limit].rstrip(" ，,;；:：") + ("…" if len(summary) > limit else "")

    if "花了一周" in (text or "") and "AI 的帮助下" in (text or ""):
        summary = "高密度长文，借助 AI 花一周才勉强通读，后面还要继续细读。"
        return summary[:limit].rstrip(" ，,;；:：") + ("…" if len(summary) > limit else "")

    if "北大教授" in (text or "") and "地震课" in (text or "") and "股市" in (text or ""):
        summary = "北大教授谈炒股，用地震课解释股市现象。"
        return summary[:limit].rstrip(" ，,;；:：") + ("…" if len(summary) > limit else "")

    if merged:
        if len(merged) > limit:
            merged = merged[:limit].rstrip(" ，,;；:：") + "…"
        return merged

    return None


def fetch_url(url: str) -> tuple[str, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", "replace")
        return response.geturl(), body


def parse_html_meta(html: str) -> dict:
    meta = {}
    title_match = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    if title_match:
        meta["title"] = normalize_clause(unescape(title_match.group(1)))
    for key, patterns in {
        "description": [
            r'<meta\s+name="description"\s+content="([^"]+)"',
            r'<meta\s+property="og:description"\s+content="([^"]+)"',
        ],
        "og_title": [
            r'<meta\s+property="og:title"\s+content="([^"]+)"',
        ],
    }.items():
        for pattern in patterns:
            match = re.search(pattern, html, re.I)
            if match:
                meta[key] = normalize_clause(unescape(match.group(1)))
                break
    return meta


def parse_x_status_id(url: str) -> str:
    match = re.search(r"/status/(\d+)", url or "")
    return match.group(1) if match else ""


def fetch_x_syndication(tweet_id: str) -> dict | None:
    if not tweet_id:
        return None
    endpoint = f"https://cdn.syndication.twimg.com/tweet-result?token=false&id={tweet_id}"
    try:
        _, body = fetch_url(endpoint)
        payload = json.loads(body)
    except Exception:
        return None
    text = normalize_clause(payload.get("text", ""))
    user = payload.get("user") or {}
    return {
        "kind": "x_status",
        "text": text,
        "title": normalize_clause(user.get("name", "")),
        "description": text,
        "final_url": f"https://x.com/{user.get('screen_name','')}/status/{tweet_id}" if user.get("screen_name") else "",
    }


def fetch_url_meta(url: str, cache: dict) -> dict:
    if not url:
        return {}
    cached = cache.get(url)
    if cached:
        return cached

    result = {"kind": "unknown", "source_url": url, "final_url": url}
    try:
        final_url, body = fetch_url(url)
        result["final_url"] = final_url
        status_id = parse_x_status_id(final_url)
        if "x.com/" in final_url or "twitter.com/" in final_url:
            x_meta = fetch_x_syndication(status_id)
            if x_meta:
                result.update(x_meta)
        elif "github.com/" in final_url:
            html_meta = parse_html_meta(body)
            result.update(
                {
                    "kind": "github",
                    "title": html_meta.get("og_title") or html_meta.get("title", ""),
                    "description": html_meta.get("description", ""),
                }
            )
        else:
            html_meta = parse_html_meta(body)
            result.update(
                {
                    "kind": "webpage",
                    "title": html_meta.get("og_title") or html_meta.get("title", ""),
                    "description": html_meta.get("description", ""),
                }
            )
    except Exception as error:
        result["error"] = str(error)

    cache[url] = result
    return result


def summarize_external_sources(item: dict, cache: dict, limit: int = 120) -> str | None:
    urls = []
    urls.extend(item.get("links") or [])
    urls.extend(extract_urls(item.get("text", "")))
    if item.get("url"):
        urls.append(item["url"])
    urls = list(dict.fromkeys([url for url in urls if url]))
    if not urls:
        return None

    metas = [fetch_url_meta(url, cache) for url in urls[:4]]
    metas = [meta for meta in metas if meta]
    if not metas:
        return None

    x_sources = [meta for meta in metas if meta.get("kind") == "x_status" and meta.get("text")]
    if x_sources:
        x_text = normalize_clause(re.sub(r"https?://\S+", "", x_sources[0]["text"]))
        own_text = normalize_clause(re.sub(r"https?://\S+", "", item.get("text", "")))
        if x_sources[0].get("final_url") == item.get("url") and x_text == own_text:
            return None
        summary = summarize_informative_sentences(cleaned_lines(x_text), limit=limit)
        if summary and summary != "正文未提取到可用内容。":
            return summary

    github_sources = [meta for meta in metas if meta.get("kind") == "github" and meta.get("description")]
    if github_sources:
        parts = []
        for meta in github_sources[:3]:
            title = normalize_clause(meta.get("title", "").replace("GitHub - ", ""))
            desc = normalize_clause(meta.get("description", ""))
            if title and desc:
                parts.append(f"{title}：{desc}")
            elif desc:
                parts.append(desc)
        if parts:
            summary = "；".join(parts)
            if len(summary) > limit:
                summary = summary[:limit].rstrip(" ，,;；:：") + "…"
            return summary

    webpage_sources = [meta for meta in metas if meta.get("description")]
    if webpage_sources:
        summary = webpage_sources[0].get("description", "")
        if summary:
            if len(summary) > limit:
                summary = summary[:limit].rstrip(" ，,;；:：") + "…"
            return summary

    return None


def is_teaser_style(text: str, lines: list[str]) -> bool:
    markers = [
        "火了",
        "讲透了",
        "谁也没想到",
        "终于实现了",
        "token自由",
        "横空出世",
    ]
    if len(lines) > 3:
        return False
    return any(marker in (text or "") for marker in markers)


def summarize_text(item: dict, cache: dict, limit: int = 120) -> str:
    text = item.get("text", "")
    x_primary = fetch_x_primary_source(item, cache)
    if x_primary:
        article_title = x_primary.get("article_title", "")
        article_preview = x_primary.get("article_preview", "")
        if article_title or article_preview:
            summary = "；".join([part for part in [article_title, article_preview] if part])
            if len(summary) > limit:
                summary = summary[:limit].rstrip(" ，,;；:：") + "…"
            return summary
        if x_primary.get("text"):
            enriched_lines = cleaned_lines(x_primary["text"])
            summary = summarize_informative_sentences(enriched_lines, limit=limit)
            if summary and summary != "正文未提取到可用内容。":
                return summary
    for nested_key in ["retweetedTweet", "quotedTweet"]:
        nested = item.get(nested_key) or {}
        nested_text = nested.get("text", "")
        if nested_text:
            nested_summary = summarize_informative_sentences(cleaned_lines(nested_text), limit=limit)
            if nested_summary and nested_summary != "正文未提取到可用内容。":
                return nested_summary
    clean = re.sub(r"\s+", " ", re.sub(r"https?://\S+", "", text or "")).strip()
    if not clean:
        external_summary = summarize_external_sources(item, cache, limit=limit)
        return external_summary or "原帖未提取到可读正文。"
    lines = cleaned_lines(text)
    if not lines:
        external_summary = summarize_external_sources(item, cache, limit=limit)
        return external_summary or "原帖未提取到可读正文。"

    summary = summarize_project_blocks(lines, limit=limit)
    if summary:
        return summary

    summary = summarize_repo_roundup(lines, limit=limit)
    if summary:
        return summary

    summary = summarize_numbered_list(lines, limit=limit)
    if summary:
        return summary

    if is_mostly_commentary(clean) and len(lines) <= 3:
        external_summary = summarize_external_sources(item, cache, limit=limit)
        if external_summary:
            return external_summary
        fallback = summarize_commentary_or_teaser(clean, lines, limit=limit)
        return fallback or summarize_informative_sentences(lines, limit=limit)

    if len(lines) <= 2 and ("https://t.co/" in (text or "") or "t.co/" in (text or "")):
        external_summary = summarize_external_sources(item, cache, limit=limit)
        if external_summary:
            return external_summary
        if is_teaser_style(clean, lines):
            fallback = summarize_commentary_or_teaser(clean, lines, limit=limit)
            if fallback:
                return fallback
        merged = "；".join(normalize_clause(line) for line in lines if normalize_clause(line))
        if len(merged) >= 16:
            return summarize_informative_sentences(lines, limit=limit)
        fallback = summarize_commentary_or_teaser(clean, lines, limit=limit)
        if fallback:
            return fallback
        return summarize_informative_sentences(lines, limit=limit)

    return summarize_informative_sentences(lines, limit=limit)


def build_baseline_section(snapshot_path: Path, snapshot: dict) -> tuple[datetime, str]:
    exported_at = parse_exported_at(snapshot)
    section = "\n".join(
        [
            f"_基线建立：`{snapshot_path.name}`，当前总量 ` {len(snapshot.get('items', []))} ` 条。_".replace(" ` ", "`"),
        ]
    )
    return exported_at, section


def build_incremental_section(previous_path: Path, previous: dict, latest_path: Path, latest: dict, cache: dict) -> tuple[datetime, str]:
    previous_urls = {item.get("url") for item in previous.get("items", []) if item.get("url")}
    new_items = [item for item in latest.get("items", []) if item.get("url") and item.get("url") not in previous_urls]
    new_items.sort(key=lambda item: parse_post_time(item.get("publishedAt", "")), reverse=True)

    exported_at = parse_exported_at(latest)
    lines = []

    if not new_items:
        lines.extend(["_本次无新增点赞。_"])
        return exported_at, "\n".join(lines)

    for item in new_items:
        handle = item.get("handle") or item.get("displayName") or item.get("url", "")
        published_at = item.get("publishedAt", "")
        summary = summarize_text(item, cache)
        url = item.get("url", "")
        lines.extend(
            [
                f"- **`{handle}`**",
                f"  - 摘要：{summary}",
                f"  - 原帖：[{url}]({url})" if url else "  - 原帖：缺失",
            ]
        )
    return exported_at, "\n".join(lines)


def render_all_sections() -> str:
    snapshots = list_snapshots()
    if not snapshots:
        raise SystemExit("No X Likes snapshots found.")

    cache = load_cache()
    sections: list[tuple[datetime, str]] = []
    if len(snapshots) == 1:
        latest_path = snapshots[0]
        latest = load_snapshot(latest_path)
        sections.append(build_baseline_section(latest_path, latest))
    else:
        first_path = snapshots[0]
        first_snapshot = load_snapshot(first_path)
        sections.append(build_baseline_section(first_path, first_snapshot))
        for previous_path, latest_path in zip(snapshots[:-1], snapshots[1:]):
            previous = load_snapshot(previous_path)
            latest = load_snapshot(latest_path)
            sections.append(build_incremental_section(previous_path, previous, latest_path, latest, cache))

    sections.sort(key=lambda item: item[0], reverse=True)
    grouped: dict[str, list[str]] = {}
    ordered_dates: list[str] = []
    for dt, section in sections:
        date_str = dt.astimezone(LOCAL_TZ).strftime("%Y-%m-%d")
        if date_str not in grouped:
            grouped[date_str] = []
            ordered_dates.append(date_str)
        grouped[date_str].append(section.rstrip())

    body = [
        "",
    ]
    for date_str in ordered_dates:
        body.append(f"<div align=\"center\"><strong>{date_str}</strong></div>")
        for section in grouped[date_str]:
            body.append(section)
        body.append("")
    if body[-1] == "":
        body.pop()
    save_cache(cache)
    return "\n".join(body).rstrip() + "\n"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(render_all_sections())
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
