"""数据抓取模块。
两个数据源：
1. blog-list — GitHub API 读取分类文件 → 提取 RSS → 抓取文章
2. github-daily — 解析每日 Markdown 表格 → 趋势项目
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "sources" / "feeds.yaml"
DATA_RAW = ROOT / "data" / "raw"

TIMEOUT = 20
UA = "ColdFinder/2.0"
GH_API = "https://api.github.com"
GH_RAW = "https://raw.githubusercontent.com"


def load_config() -> dict:
    with open(CFG, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ═══════ 源 1：blog-list ═══════

def fetch_blog_list(client: httpx.Client) -> list[dict]:
    """从 blog-list 仓库提取 RSS URL，抓取文章。"""
    cfg = load_config()["sources"]["blog_list"]
    categories = cfg["categories"]
    max_feeds = cfg["max_feeds"]
    all_articles = []

    # 步骤 1：从每个分类文件提取博客 RSS
    rss_entries = []
    for cat_key, filenames in categories.items():
        for fname in filenames:
            entries = _parse_blog_list_file(client, fname, cat_key)
            rss_entries.extend(entries)
            time.sleep(0.3)

    # 去重（按 RSS URL）
    seen = set()
    unique_rss = []
    for e in rss_entries:
        if e["rss"] and e["rss"] not in seen:
            seen.add(e["rss"])
            unique_rss.append(e)

    print(f"blog-list: {len(rss_entries)} 个博客, {len(unique_rss)} 个有 RSS\n")

    # 步骤 2：抓取每个 RSS（限制数量）
    for i, entry in enumerate(unique_rss[:max_feeds]):
        articles = _fetch_blog_rss(client, entry)
        all_articles.extend(articles)
        if articles:
            print(f"[{i+1}/{min(len(unique_rss), max_feeds)}] {entry['name']}: {len(articles)} 篇")
        time.sleep(0.3)

    return all_articles


def _parse_blog_list_file(client: httpx.Client, filename: str, category: str) -> list[dict]:
    """解析 blog-list 的一个分类文件，提取博客名/URL/RSS/描述。"""
    url = f"{GH_API}/repos/qianguyihao/blog-list/contents/{filename}"
    try:
        resp = client.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        import base64
        content = base64.b64decode(resp.json()["content"]).decode("utf-8")
    except Exception as exc:
        print(f"[WARN] blog-list/{filename}: {exc}")
        return []

    entries = []
    # 匹配 ### 标题开头的博客条目
    blocks = re.split(r"\n(?=### )", content)
    for block in blocks:
        name_match = re.match(r"###\s*(.+)", block)
        if not name_match:
            continue
        name = name_match.group(1).strip()

        # 提取 URL
        url_match = re.search(r"(?:博客地址|地址|网站)[：:]\s*(https?://[^\s\n]+)", block)
        if not url_match:
            url_match = re.search(r"-\s*(?:博客地址|地址|网站)[：:]*\s*<?(https?://[^\s>\n]+)", block)
        if not url_match:
            url_match = re.search(r"https?://[^\s)\n]+", block)
        blog_url = url_match.group(1).rstrip(">").rstrip(")") if url_match else ""

        # 提取 RSS
        rss_match = re.search(r"\[RSS[^\]]*\]\s*\(?(https?://[^\s)\]]+)", block)
        if not rss_match:
            rss_match = re.search(r"https?://[^\s)]*(?:feed|rss|atom|\.xml)[^\s)]*", block, re.I)
        rss_url = rss_match.group(1) if rss_match else ""

        # 提取描述（### 标题之后、下一段之前的内容）
        desc_match = re.search(r"###\s*.+\n+(.+?)(?:\n###|\n##|\Z)", block, re.S)
        desc = desc_match.group(1).strip() if desc_match else ""
        # 清理 URL 和 RSS 行
        desc = re.sub(r"^[-\s]*(?:博客地址|地址|RSS地址|RSS)[：:].*$", "", desc, flags=re.M)
        desc = re.sub(r"\[RSS[^\]]*\]\([^)]+\)", "", desc)
        desc = re.sub(r"https?://\S+", "", desc)
        desc = desc.strip()
        # 限制长度
        if len(desc) > 300:
            desc = desc[:300] + "..."

        entries.append({
            "name": name,
            "url": blog_url,
            "rss": rss_url,
            "desc": desc,
            "category": category,
        })

    return entries


def _fetch_blog_rss(client: httpx.Client, entry: dict) -> list[dict]:
    """抓取一个博客的 RSS，返回文章列表。"""
    articles = []
    try:
        resp = client.get(entry["rss"], timeout=TIMEOUT)
        resp.raise_for_status()
    except Exception:
        return articles

    feed = feedparser.parse(resp.text)
    if feed.bozo and not feed.entries:
        return articles

    for item in feed.entries[:3]:  # 每个博客最多取 3 篇
        title = (item.get("title") or "").strip()
        link = (item.get("link") or "").strip()
        if not title or not link:
            continue
        content = ""
        for f in ("content", "content:encoded", "description", "summary"):
            v = item.get(f)
            if isinstance(v, list) and v:
                content = v[0].get("value", "")
                break
            elif isinstance(v, str) and v:
                content = v
                break
        articles.append({
            "title": title,
            "url": link,
            "source_name": entry["name"],
            "source_url": entry["url"],
            "source_desc": entry["desc"],
            "category": entry["category"],
            "content": _clean_html(content)[:2000],
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        })
    return articles


# ═══════ 源 2：github-daily-rank ═══════

def fetch_github_daily(client: httpx.Client) -> list[dict]:
    """解析今日 GitHub 日榜 Markdown，提取 Top 10 项目。"""
    today = datetime.now()
    path = f"{today.year}/{today.month:02d}/{today.strftime('%Y%m%d')}.md"
    url = f"{GH_RAW}/opengithubs/github-daily-rank/main/{path}"

    try:
        resp = client.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        content = resp.text
    except Exception as exc:
        print(f"[WARN] github-daily: {exc}")
        return []

    articles = []
    # 解析表格行：| 1 | [owner/repo](url) | 67k | 🔺5436 |
    rows = re.findall(
        r"\|\s*(\d+)\s*\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([\d.]+)k?\s*\|\s*🔺(\d+)",
        content
    )
    for rank, name, repo_url, stars_str, growth in rows[:10]:
        # 尝试找项目描述
        desc = ""
        desc_match = re.search(
            rf"{re.escape(name)}.*?</h3>.*?项目描述[：:]\s*(.+?)(?:<br|\n|<h3|\Z)",
            content, re.S | re.I
        )
        if desc_match:
            desc = _clean_html(desc_match.group(1))[:300]
        if not desc:
            # 备用：从页面其他位置找
            desc_match = re.search(
                rf"📝\s*项目描述[：:]\s*(.+?)(?:\n\n|\n<h|\Z)",
                content, re.S
            )
            if desc_match:
                desc = desc_match.group(1).strip()[:300]

        articles.append({
            "title": name,
            "url": repo_url,
            "source_name": "GitHub 日榜",
            "source_url": f"https://github.com/opengithubs/github-daily-rank",
            "source_desc": f"#{rank} 今日增长 +{growth}⭐ | 总计 {stars_str}k⭐ | {desc}",
            "category": "trending",
            "content": desc,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        })

    print(f"github-daily: {len(articles)} 个项目")
    return articles


# ═══════ 工具 ═══════

def _clean_html(text: str) -> str:
    if not text:
        return ""
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "lxml").get_text(separator="\n", strip=True)


def deduplicate(articles: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for a in articles:
        u = a["url"]
        if u not in seen:
            seen.add(u)
            unique.append(a)
    print(f"[去重] {len(articles)} → {len(unique)}")
    return unique


# ═══════ 主入口 ═══════

def run():
    DATA_RAW.mkdir(parents=True, exist_ok=True)

    with httpx.Client(headers={"User-Agent": UA}, timeout=TIMEOUT) as client:
        print("═══ blog-list ═══")
        blog_articles = fetch_blog_list(client)

        print("\n═══ github-daily ═══")
        daily_articles = fetch_github_daily(client)

    all_articles = deduplicate(blog_articles + daily_articles)

    today = datetime.now().strftime("%Y-%m-%d")
    out_path = DATA_RAW / f"{today}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] {len(all_articles)} 篇 → {out_path}")


if __name__ == "__main__":
    run()
