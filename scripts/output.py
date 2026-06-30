"""多渠道输出模块。
读取今日精选，生成：
1. output/wechat/YYYY-MM-DD.md  — 公众号排版（复制粘贴到公众号后台）
2. output/rss/feed.xml           — RSS Feed（用户导入阅读器）
3. output/site/                  — GitHub Pages 存档页
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources" / "feeds.yaml"
DATA_SCORED = ROOT / "data" / "scored"
OUTPUT_WECHAT = ROOT / "output" / "wechat"
OUTPUT_RSS = ROOT / "output" / "rss"
OUTPUT_SITE = ROOT / "output" / "site"
ARCHIVE_DIR = ROOT / "data" / "archive"

FEED_TITLE = "冷门精选"
FEED_DESCRIPTION = "每天 3 篇被算法遗漏的好文章"
FEED_LINK = os.getenv("SITE_URL", "https://berlinye.github.io/cold-finder")


def load_config() -> dict:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_picks(date_str: str) -> list[dict]:
    path = DATA_SCORED / f"{date_str}_picks.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_all_picks(days: int = 30) -> dict[str, list[dict]]:
    """加载最近 N 天的所有精选。"""
    all_picks = {}
    for i in range(days):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        picks = load_picks(d)
        if picks:
            all_picks[d] = picks
    return all_picks


# ─── 公众号 Markdown ───────────────────────────────────────────

def generate_wechat_md(picks: list[dict], date_str: str) -> str:
    """生成公众号排版 Markdown。"""
    if not picks:
        return f"# 冷门精选 · {date_str}\n\n今日暂未发现符合条件的冷门好文，明天见。"

    lines = []
    lines.append(f"**冷门精选 · {date_str}**")
    lines.append("")
    lines.append("每天从上百个 RSS 源中挖出 3 篇被算法埋没的好文章。")
    lines.append("")
    lines.append("---")
    lines.append("")

    for i, p in enumerate(picks, 1):
        score = p["score"]
        stars = "⭐" * min(5, round(score / 2))
        lines.append(f"## {i}. {p['title']}")
        lines.append("")
        lines.append(f"**评分** {score}/10 {stars}")
        lines.append("")
        lines.append(f"> {p['summary']}")
        lines.append("")
        lines.append(f"💡 {p['hook']}")
        lines.append("")
        lines.append(f"📎 [阅读原文]({p['url']}) · 来源：{p['source']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("")
    lines.append("*本内容由 AI 自动筛选生成，人工审核后发布。*")
    lines.append(f"*订阅 RSS：[{FEED_LINK}/feed.xml]({FEED_LINK}/feed.xml)*")

    return "\n".join(lines)


def write_wechat(picks: list[dict], date_str: str):
    OUTPUT_WECHAT.mkdir(parents=True, exist_ok=True)
    markdown = generate_wechat_md(picks, date_str)
    path = OUTPUT_WECHAT / f"{date_str}.md"
    path.write_text(markdown, encoding="utf-8")
    print(f"[微信] {path}")


# ─── RSS Feed ──────────────────────────────────────────────────

def generate_rss(all_picks: dict[str, list[dict]]) -> str:
    """生成 RSS 2.0 Feed XML。"""
    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")

    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "link").text = FEED_LINK
    ET.SubElement(channel, "description").text = FEED_DESCRIPTION
    ET.SubElement(channel, "language").text = "zh-CN"
    ET.SubElement(channel, "lastBuildDate").text = datetime.now().strftime(
        "%a, %d %b %Y %H:%M:%S +0000"
    )

    for date_str, picks in sorted(all_picks.items(), reverse=True):
        for p in picks:
            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = f"[{p['score']}分] {p['title']}"
            ET.SubElement(item, "link").text = p["url"]
            desc = f"{p['summary']}\n\n💡 {p['hook']}\n\n📎 来源：{p['source']} | 评分：{p['score']}/10"
            ET.SubElement(item, "description").text = desc
            ET.SubElement(item, "author").text = p.get("source", "")
            ET.SubElement(item, "pubDate").text = datetime.now().strftime(
                "%a, %d %b %Y %H:%M:%S +0000"
            )
            ET.SubElement(item, "guid").text = p["url"]

    raw_xml = ET.tostring(rss, encoding="unicode")
    return minidom.parseString(raw_xml).toprettyxml(indent="  ")


def write_rss(all_picks: dict[str, list[dict]]):
    OUTPUT_RSS.mkdir(parents=True, exist_ok=True)
    xml_str = generate_rss(all_picks)
    path = OUTPUT_RSS / "feed.xml"
    path.write_text(xml_str, encoding="utf-8")
    print(f"[RSS] {path}")


# ─── GitHub Pages 存档 ─────────────────────────────────────────

def generate_site(all_picks: dict[str, list[dict]]):
    """生成静态 HTML 存档页。"""
    OUTPUT_SITE.mkdir(parents=True, exist_ok=True)

    # 首页
    index_items = []
    for date_str, picks in sorted(all_picks.items(), reverse=True):
        for p in picks:
            index_items.append(f"""
    <article class="card">
      <div class="score">⭐ {p['score']}</div>
      <h2><a href="{p['url']}" target="_blank">{p['title']}</a></h2>
      <p class="summary">{p['summary']}</p>
      <p class="hook">💡 {p['hook']}</p>
      <div class="meta">
        <span>📅 {date_str}</span>
        <span>📎 来源：{p['source']}</span>
        <span>📂 {p.get('category', '')}</span>
      </div>
    </article>""")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{FEED_TITLE} - 每天发现被算法遗漏的好文章</title>
<meta name="description" content="{FEED_DESCRIPTION}">
<link rel="alternate" type="application/rss+xml" title="{FEED_TITLE}" href="{FEED_LINK}/feed.xml">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f8f9fa;color:#212529;line-height:1.6}}
.container{{max-width:720px;margin:0 auto;padding:20px}}
header{{text-align:center;padding:40px 0 20px}}
header h1{{font-size:1.8em;color:#1a1a2e}}
header p{{color:#6c757d;margin-top:8px}}
.card{{background:#fff;border-radius:8px;padding:20px;margin-bottom:16px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.card .score{{display:inline-block;background:#fff3cd;color:#856404;padding:2px 10px;border-radius:12px;font-size:.85em;margin-bottom:8px}}
.card h2{{font-size:1.15em;margin-bottom:8px}}
.card h2 a{{color:#1a1a2e;text-decoration:none}}
.card h2 a:hover{{color:#0d6efd}}
.card .summary{{color:#495057;font-size:.95em;margin-bottom:6px}}
.card .hook{{color:#0d6efd;font-size:.9em;margin-bottom:8px}}
.card .meta{{color:#adb5bd;font-size:.8em;display:flex;gap:16px;flex-wrap:wrap}}
footer{{text-align:center;padding:40px 0;color:#adb5bd;font-size:.85em}}
.subscribe{{text-align:center;padding:20px;background:#e7f1ff;border-radius:8px;margin:20px 0}}
.subscribe a{{color:#0d6efd;font-weight:600}}
</style>
</head>
<body>
<div class="container">
<header>
  <h1>🔍 {FEED_TITLE}</h1>
  <p>{FEED_DESCRIPTION}</p>
</header>
<div class="subscribe">
  📡 订阅 RSS：<a href="{FEED_LINK}/feed.xml">{FEED_LINK}/feed.xml</a>（导入任意 RSS 阅读器）
</div>
{"".join(index_items)}
<footer>
  <p>由 AI + GitHub Actions 自动生成 · 零成本运行 · <a href="{FEED_LINK}">GitHub</a></p>
</footer>
</div>
</body>
</html>"""

    (OUTPUT_SITE / "index.html").write_text(html, encoding="utf-8")
    print(f"[站点] {OUTPUT_SITE / 'index.html'}")


# ─── 归档 ──────────────────────────────────────────────────────

def archive_picks(picks: list[dict], date_str: str):
    """将今日精选存入 archive 目录。"""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = ARCHIVE_DIR / f"{date_str}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(picks, f, ensure_ascii=False, indent=2)
    print(f"[归档] {path}")


# ─── 主入口 ────────────────────────────────────────────────────

def run(date_str: str | None = None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    picks = load_picks(date_str)
    all_picks = load_all_picks(days=30)

    print(f"今日精选 {len(picks)} 篇\n")

    # 1. 公众号 Markdown
    write_wechat(picks, date_str)

    # 2. RSS Feed（包含最近 30 天）
    write_rss(all_picks)

    # 3. GitHub Pages 存档
    generate_site(all_picks)

    # 4. 归档今日
    if picks:
        archive_picks(picks, date_str)

    print("\n[DONE] 全部输出已生成")


if __name__ == "__main__":
    run()
