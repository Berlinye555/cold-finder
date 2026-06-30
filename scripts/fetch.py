"""RSS + 网页抓取模块。
读取 feeds.yaml，逐个抓取，去重，存入 data/raw/YYYY-MM-DD.json。
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources" / "feeds.yaml"
DATA_RAW = ROOT / "data" / "raw"

REQUEST_TIMEOUT = 15  # 秒
USER_AGENT = "ColdFinder/1.0 (RSS Reader; github.com/berlinye/cold-finder)"


def load_sources() -> list[dict]:
    """加载 feeds.yaml 中的订阅源列表。"""
    with open(SOURCES_FILE, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("sources", [])


def fetch_feed(source: dict, client: httpx.Client) -> list[dict]:
    """抓取单个 RSS/Atom 源，返回标准化文章列表。"""
    articles = []
    name = source["name"]
    url = source["url"]
    category = source.get("category", "unknown")

    try:
        resp = client.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        print(f"[WARN] 抓取失败 {name} ({url}): {exc}")
        return articles

    feed = feedparser.parse(resp.text)

    if feed.bozo and not feed.entries:
        print(f"[WARN] 解析失败 {name}: {feed.bozo_exception}")
        return articles

    for entry in feed.entries:
        article = {
            "title": (entry.get("title") or "").strip(),
            "url": (entry.get("link") or "").strip(),
            "summary": _clean_html(entry.get("summary") or entry.get("description") or ""),
            "content": _clean_html(
                _first_content(entry) or entry.get("summary") or entry.get("description") or ""
            ),
            "author": (entry.get("author") or "").strip(),
            "published": _parse_date(entry),
            "source_name": name,
            "source_url": url,
            "category": category,
        }

        # 跳过无标题或无链接的条目
        if not article["title"] or not article["url"]:
            continue

        articles.append(article)

    print(f"[OK] {name}: {len(articles)} 篇")
    return articles


def _clean_html(text: str) -> str:
    """去除 HTML 标签，保留纯文本。"""
    if not text:
        return ""
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "lxml").get_text(separator="\n", strip=True)


def _first_content(entry) -> str | None:
    """从 feed entry 中提取正文内容。"""
    for field in ("content", "content:encoded", "description", "summary"):
        val = entry.get(field)
        if val:
            if isinstance(val, list):
                return val[0].get("value", "")
            return val
    return None


def _parse_date(entry) -> str:
    """解析发布时间，统一为 ISO 8601 字符串。"""
    for field in ("published_parsed", "updated_parsed"):
        tp = entry.get(field)
        if tp:
            try:
                from time import mktime
                return datetime.fromtimestamp(mktime(tp), tz=timezone.utc).isoformat()
            except Exception:
                pass
    return datetime.now(timezone.utc).isoformat()


def deduplicate(articles: list[dict]) -> list[dict]:
    """按 URL 去重，保留首次出现的条目。"""
    seen = set()
    unique = []
    for a in articles:
        url = a["url"]
        if url not in seen:
            seen.add(url)
            unique.append(a)
    print(f"[去重] {len(articles)} → {len(unique)} 篇")
    return unique


def run():
    """主入口：抓取全部源 → 去重 → 存入 JSON。"""
    DATA_RAW.mkdir(parents=True, exist_ok=True)

    sources = load_sources()
    print(f"共 {len(sources)} 个订阅源，开始抓取...\n")

    all_articles = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        for src in sources:
            articles = fetch_feed(src, client)
            all_articles.extend(articles)
            time.sleep(0.5)  # 礼貌延迟

    all_articles = deduplicate(all_articles)

    today = datetime.now().strftime("%Y-%m-%d")
    out_path = DATA_RAW / f"{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] {len(all_articles)} 篇 → {out_path}")


if __name__ == "__main__":
    run()
