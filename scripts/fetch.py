"""RSS + JSON API 抓取模块。
读取 feeds.yaml，按类型分发抓取，去重，存入 data/raw/YYYY-MM-DD.json。

支持类型：
  rss     — 标准 RSS/Atom feed
  hn      — Hacker News Firebase API
  github  — GitHub Search API
  reddit  — Reddit .json API
  devto   — Dev.to Forem API
  lobsters— Lobsters JSON API
"""

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources" / "feeds.yaml"
DATA_RAW = ROOT / "data" / "raw"

REQUEST_TIMEOUT = 20
USER_AGENT = "ColdFinder/1.0 (Content Finder; github.com/berlinye/cold-finder)"


def load_sources() -> list[dict]:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("sources", [])


# ═══════ RSS 抓取 ═══════

def fetch_rss(source: dict, client: httpx.Client) -> list[dict]:
    """标准 RSS/Atom 抓取。"""
    articles = []
    name, url, category = source["name"], source["url"], source.get("category", "unknown")

    try:
        resp = client.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        print(f"[WARN] RSS {name}: {exc}")
        return articles

    feed = feedparser.parse(resp.text)
    if feed.bozo and not feed.entries:
        print(f"[WARN] RSS 解析失败 {name}: {feed.bozo_exception}")
        return articles

    for entry in feed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        articles.append(_make_article(
            title=title, url=link, source_name=name, source_url=url,
            category=category,
            content=_clean_html(
                _rss_content(entry) or entry.get("summary") or entry.get("description") or ""
            ),
            summary=_clean_html(entry.get("summary") or entry.get("description") or ""),
            author=(entry.get("author") or "").strip(),
            published=_rss_date(entry),
        ))
    print(f"[RSS] {name}: {len(articles)} 篇")
    return articles


# ═══════ JSON API 抓取 ═══════

def fetch_json_api(source: dict, client: httpx.Client) -> list[dict]:
    """按 type 分发到具体 API 处理函数。"""
    api_type = source.get("type", "rss")
    handlers = {
        "hn":      _fetch_hn,
        "github":  _fetch_github,
        "reddit":  _fetch_reddit,
        "devto":   _fetch_devto,
        "lobsters": _fetch_lobsters,
    }
    handler = handlers.get(api_type)
    if handler is None:
        print(f"[WARN] 未知 API 类型: {api_type}")
        return []
    try:
        articles = handler(source, client)
        print(f"[API] {source['name']}: {len(articles)} 篇")
        return articles
    except Exception as exc:
        print(f"[WARN] API {source['name']}: {exc}")
        return []


def _fetch_hn(source: dict, client: httpx.Client) -> list[dict]:
    """Hacker News: 拿 top 30 条 story。"""
    name, url, cat = source["name"], source["url"], source.get("category", "unknown")
    ids = client.get(url, timeout=REQUEST_TIMEOUT).json()[:30]

    articles = []
    for item_id in ids:
        try:
            item = client.get(
                f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
                timeout=REQUEST_TIMEOUT,
            ).json()
        except Exception:
            continue
        # 只取有 URL 的 story（跳过 Ask HN 等纯文本）
        item_url = item.get("url", "")
        title = item.get("title", "").strip()
        if not title or not item_url:
            continue
        articles.append(_make_article(
            title=title,
            url=item_url,
            source_name=name,
            source_url=f"https://news.ycombinator.com/item?id={item_id}",
            category=cat,
            content=(item.get("text") or "")[:2000],
            summary=f"HN {item.get('score', 0)} 分 | {item.get('descendants', 0)} 评论",
            author=item.get("by", ""),
            published=datetime.fromtimestamp(item.get("time", 0), tz=timezone.utc).isoformat(),
        ))
        time.sleep(0.05)  # HN API 礼貌间隔
    return articles


def _fetch_github(source: dict, client: httpx.Client) -> list[dict]:
    """GitHub Search: 高星新仓库。"""
    name, url, cat = source["name"], source["url"], source.get("category", "unknown")
    try:
        data = client.get(url, timeout=REQUEST_TIMEOUT,
                          headers={"Accept": "application/vnd.github+json"}).json()
    except Exception:
        return []
    items = data.get("items", [])[:15]

    articles = []
    for repo in items:
        desc = repo.get("description") or ""
        repo_url = repo.get("html_url", "")
        repo_name = repo.get("full_name", "")
        if not repo_name:
            continue
        articles.append(_make_article(
            title=f"{repo_name} — {desc}" if desc else repo_name,
            url=repo_url,
            source_name=name,
            source_url="https://github.com/trending",
            category=cat,
            content=f"语言: {repo.get('language', 'N/A')} | Stars: {repo.get('stargazers_count', 0)} | Forks: {repo.get('forks_count', 0)}\n{desc}",
            summary=desc,
            author=repo.get("owner", {}).get("login", ""),
            published=repo.get("created_at", ""),
        ))
    return articles


def _fetch_reddit(source: dict, client: httpx.Client) -> list[dict]:
    """Reddit .json: 热门帖子。"""
    name, url, cat = source["name"], source["url"], source.get("category", "unknown")
    try:
        data = client.get(url, timeout=REQUEST_TIMEOUT,
                          headers={"User-Agent": USER_AGENT}).json()
    except Exception:
        return []
    children = data.get("data", {}).get("children", [])

    articles = []
    for child in children:
        post = child.get("data", {})
        title = post.get("title", "").strip()
        post_url = post.get("url", "")
        permalink = f"https://www.reddit.com{post.get('permalink', '')}"
        if not title:
            continue
        articles.append(_make_article(
            title=title,
            url=post_url if post_url.startswith("http") else permalink,
            source_name=name,
            source_url=permalink,
            category=cat,
            content=(post.get("selftext") or "")[:2000],
            summary=f"👍 {post.get('score', 0)} | 💬 {post.get('num_comments', 0)} 评论",
            author=post.get("author", ""),
            published=datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc).isoformat(),
        ))
    return articles


def _fetch_devto(source: dict, client: httpx.Client) -> list[dict]:
    """Dev.to API: 开发者文章。"""
    name, url, cat = source["name"], source["url"], source.get("category", "unknown")
    try:
        data = client.get(url, timeout=REQUEST_TIMEOUT).json()
    except Exception:
        return []

    articles = []
    for post in data[:20]:
        title = post.get("title", "").strip()
        post_url = post.get("url", "")
        if not title or not post_url:
            continue
        tags = ",".join(post.get("tag_list", []))
        articles.append(_make_article(
            title=title,
            url=post_url,
            source_name=name,
            source_url="https://dev.to",
            category=cat,
            content=(post.get("description") or "")[:1500],
            summary=f"🏷 {tags} | ❤️ {post.get('positive_reactions_count', 0)} | 💬 {post.get('comments_count', 0)}",
            author=post.get("user", {}).get("name", ""),
            published=post.get("published_at", ""),
        ))
    return articles


def _fetch_lobsters(source: dict, client: httpx.Client) -> list[dict]:
    """Lobsters JSON: 技术精选。"""
    name, url, cat = source["name"], source["url"], source.get("category", "unknown")
    try:
        data = client.get(url, timeout=REQUEST_TIMEOUT).json()
    except Exception:
        return []

    articles = []
    for story in data[:20]:
        title = story.get("title", "").strip()
        story_url = story.get("url", "")
        short_id = story.get("short_id", "")
        if not title:
            continue
        tags = ",".join(story.get("tags", []))
        articles.append(_make_article(
            title=title,
            url=story_url if story_url else f"https://lobste.rs/s/{short_id}",
            source_name=name,
            source_url=f"https://lobste.rs/s/{short_id}",
            category=cat,
            content=(story.get("description") or "")[:1500],
            summary=f"🏷 {tags} | 👍 {story.get('score', 0)} | 💬 {story.get('comment_count', 0)}",
            author=story.get("submitter_user", {}).get("username", ""),
            published=story.get("created_at", ""),
        ))
    return articles


# ═══════ 工具函数 ═══════

def _make_article(title, url, source_name, source_url, category,
                  content="", summary="", author="", published=""):
    return {
        "title": title,
        "url": url,
        "summary": summary,
        "content": content,
        "author": author,
        "published": published,
        "source_name": source_name,
        "source_url": source_url,
        "category": category,
    }


def _clean_html(text: str) -> str:
    if not text:
        return ""
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "lxml").get_text(separator="\n", strip=True)


def _rss_content(entry) -> str | None:
    for field in ("content", "content:encoded", "description", "summary"):
        val = entry.get(field)
        if val:
            if isinstance(val, list):
                return val[0].get("value", "")
            return val
    return None


def _rss_date(entry) -> str:
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
    seen = set()
    unique = []
    for a in articles:
        url = a["url"]
        if url not in seen:
            seen.add(url)
            unique.append(a)
    print(f"[去重] {len(articles)} → {len(unique)} 篇")
    return unique


# ═══════ 主入口 ═══════

def run():
    DATA_RAW.mkdir(parents=True, exist_ok=True)

    sources = load_sources()
    rss_sources = [s for s in sources if s.get("type") in ("rss", None)]
    api_sources = [s for s in sources if s.get("type") not in ("rss", None)]

    print(f"RSS {len(rss_sources)} 源 + API {len(api_sources)} 源\n")

    all_articles = []

    with httpx.Client(headers={"User-Agent": USER_AGENT}) as client:
        # RSS 源
        for src in rss_sources:
            all_articles.extend(fetch_rss(src, client))
            time.sleep(0.3)
        # API 源
        for src in api_sources:
            all_articles.extend(fetch_json_api(src, client))
            time.sleep(0.5)

    all_articles = deduplicate(all_articles)

    today = datetime.now().strftime("%Y-%m-%d")
    out_path = DATA_RAW / f"{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] {len(all_articles)} 篇 → {out_path}")


if __name__ == "__main__":
    run()
