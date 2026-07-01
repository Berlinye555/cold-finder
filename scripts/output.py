"""输出模块。
生成：index.md + 6 个分类文件 + RSS + GitHub Pages。
每日追加不覆盖，新内容标 🆕，7 天后去标记。
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom

import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "sources" / "feeds.yaml"
DATA_ENRICHED = ROOT / "data" / "enriched"
OUT = ROOT / "output"

SITE_URL = "https://berlinye555.github.io/cold-finder"

CATEGORIES = {
    "trending": ("01-开源趋势.md", "🔥 开源·趋势"),
    "tech":     ("02-技术.md",     "🖥 技术"),
    "ai":       ("03-AI.md",       "🤖 AI"),
    "product":  ("04-产品设计.md", "📦 产品·设计"),
    "thinking": ("05-深度思考.md", "💭 深度思考"),
    "life":     ("06-生活见闻.md", "✍️ 生活·见闻"),
}


def load_config() -> dict:
    with open(CFG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_enriched(date_str: str) -> list[dict]:
    path = DATA_ENRICHED / f"{date_str}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_all_enriched(days: int = 60) -> dict[str, list[dict]]:
    all_data = {}
    for i in range(days):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        articles = load_enriched(d)
        if articles:
            all_data[d] = articles
    return all_data


# ═══════ 分类文件 ═══════

def build_category_files(today: str, all_data: dict[str, list[dict]], new_days: int):
    """为每个分类生成/更新文件。新内容插在顶部。"""
    OUT.mkdir(parents=True, exist_ok=True)

    # 按分类分组
    by_cat = {}
    for date_str, articles in sorted(all_data.items(), reverse=True):
        for a in articles:
            cat = a.get("category", "tech")
            by_cat.setdefault(cat, []).append((date_str, a))

    for cat_key, (filename, cat_name) in CATEGORIES.items():
        items = by_cat.get(cat_key, [])
        content = _build_one_category(cat_name, items, today, new_days)
        (OUT / filename).write_text(content, encoding="utf-8")
        today_count = sum(1 for d, _ in items if d == today)
        print(f"[{cat_name}] {today_count}篇今日 → {filename}")


def _build_one_category(cat_name: str, items: list[tuple], today: str, new_days: int) -> str:
    """构建单个分类文件内容。"""
    nav_links = " | ".join(
        f"[{cn}]({fn})" for fn, cn in CATEGORIES.values()
    )
    lines = [f"# {cat_name}", f"[← 返回](index.md)", "", "---", ""]

    current_date = None
    for date_str, a in items:
        # 日期分隔
        if date_str != current_date:
            current_date = date_str
            is_new = (datetime.now() - datetime.strptime(date_str, "%Y-%m-%d")).days < new_days
            marker = " 🆕" if is_new else ""
            lines.append(f"## {date_str}{marker}")
            lines.append("")

        # 文章条目
        lines.append(f"### {a['title']}")
        lines.append("")

        # 来源描述（blog-list 已有 / github-daily 已有）
        if a.get("source_desc"):
            lines.append(f"> {a['source_desc'][:200]}")
            lines.append("")

        # AI 摘要
        if a.get("summary"):
            lines.append(f"💬 {a['summary']}")
            lines.append("")

        # 链接
        lines.append(f"📎 {a['url']}")
        lines.append(f"📌 来源：{a.get('source_name', '')}")
        lines.append("")

        # 多平台版本
        if a.get("wechat"):
            lines.append("<details><summary>📱 公众号版</summary>")
            lines.append("")
            lines.append(a["wechat"])
            lines.append("")
            lines.append("</details>")
            lines.append("")
        if a.get("jike"):
            lines.append("<details><summary>💬 即刻版</summary>")
            lines.append("")
            lines.append(a["jike"])
            lines.append("")
            lines.append("</details>")
            lines.append("")
        if a.get("xhs"):
            lines.append("<details><summary>📕 小红书版</summary>")
            lines.append("")
            lines.append(a["xhs"])
            lines.append("")
            lines.append("</details>")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ═══════ index.md ═══════

def build_index(today: str, all_data: dict[str, list[dict]], new_days: int):
    """生成总索引。"""
    cfg = load_config()

    lines = [
        "# 冷门精选",
        f"> 精选自 605 个中文博客 + GitHub 日榜 · 每日自动更新",
        "",
        f"📡 [RSS 订阅]({SITE_URL}/feed.xml) | [网页浏览]({SITE_URL})",
        "",
    ]

    # 今日新增
    today_articles = all_data.get(today, [])
    today_by_cat = {}
    for a in today_articles:
        cat = a.get("category", "tech")
        today_by_cat.setdefault(cat, []).append(a)

    lines.append(f"## 🆕 今日新增 · {today}")
    lines.append("")
    lines.append("| 分类 | 新增 | 跳转 |")
    lines.append("|------|:----:|------|")
    for cat_key, (filename, cat_name) in CATEGORIES.items():
        count = len(today_by_cat.get(cat_key, []))
        lines.append(f"| {cat_name} | +{count} | [→]({filename}) |")
    lines.append("")

    # 往期归档
    lines.append("## 📋 历史归档")
    lines.append("")
    dates = sorted(set(d for d in all_data if d != today), reverse=True)[:14]
    for d in dates:
        count = len(all_data[d])
        lines.append(f"- [{d}](index.md) — {count}篇")
    lines.append("")

    (OUT / "index.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[index] 今日 {len(today_articles)}篇")


# ═══════ RSS ═══════

def build_rss(all_data: dict[str, list[dict]]):
    """生成 RSS 2.0 Feed。"""
    rss_dir = OUT / "rss"
    rss_dir.mkdir(parents=True, exist_ok=True)

    rss = ET.Element("rss", version="2.0")
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "冷门精选"
    ET.SubElement(channel, "link").text = SITE_URL
    ET.SubElement(channel, "description").text = "精选自 605 个中文博客 + GitHub 日榜"
    ET.SubElement(channel, "language").text = "zh-CN"

    for date_str, articles in sorted(all_data.items(), reverse=True)[:30]:
        for a in articles:
            item = ET.SubElement(channel, "item")
            ET.SubElement(item, "title").text = a["title"]
            ET.SubElement(item, "link").text = a["url"]
            desc = a.get("source_desc", "") or a.get("summary", "")
            ET.SubElement(item, "description").text = desc
            ET.SubElement(item, "guid").text = a["url"]

    xml = minidom.parseString(ET.tostring(rss, encoding="unicode")).toprettyxml(indent="  ")
    (rss_dir / "feed.xml").write_text(xml, encoding="utf-8")
    print("[RSS] feed.xml 已更新")


# ═══════ GitHub Pages ═══════

def build_site(all_data: dict[str, list[dict]]):
    """生成 GitHub Pages 首页。"""
    site_dir = OUT / "site"
    site_dir.mkdir(parents=True, exist_ok=True)

    items = []
    for date_str, articles in sorted(all_data.items(), reverse=True)[:14]:
        for a in articles:
            items.append(f"""
    <article>
      <h3><a href="{a['url']}">{a['title']}</a></h3>
      <p class="desc">{a.get('source_desc', '') or a.get('summary', '')}</p>
      <small>📅 {date_str} · {a.get('source_name', '')} · {a.get('category', '')}</small>
    </article>""")

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>冷门精选</title>
<link rel="alternate" type="application/rss+xml" href="{SITE_URL}/feed.xml">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,sans-serif;background:#f8f9fa;color:#212529;line-height:1.6}}
.c{{max-width:720px;margin:0 auto;padding:20px}}
h1{{text-align:center;padding:30px 0 10px}}
.sub{{text-align:center;color:#6c757d;margin-bottom:20px}}
article{{background:#fff;border-radius:8px;padding:16px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
article h3{{font-size:1.1em;margin-bottom:6px}}
article h3 a{{color:#1a1a2e;text-decoration:none}}
article h3 a:hover{{color:#0d6efd}}
article .desc{{color:#495057;font-size:.9em;margin-bottom:6px}}
article small{{color:#adb5bd;font-size:.75em}}
footer{{text-align:center;padding:30px 0;color:#adb5bd;font-size:.85em}}
</style>
</head>
<body><div class="c">
<h1>🔍 冷门精选</h1>
<p class="sub">精选自 605 个中文博客 + GitHub 日榜 · 每日自动更新</p>
<p class="sub">📡 <a href="{SITE_URL}/feed.xml">RSS 订阅</a> | <a href="https://github.com/Berlinye555/cold-finder">GitHub</a></p>
{"".join(items)}
<footer>由 GitHub Actions 自动生成 · 零成本运行</footer>
</div></body></html>"""

    (site_dir / "index.html").write_text(html, encoding="utf-8")
    print("[站点] index.html 已更新")


# ═══════ 主入口 ═══════

def run(date_str: str | None = None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    cfg = load_config()
    new_days = cfg.get("output", {}).get("new_days", 7)

    today_articles = load_enriched(date_str)
    all_data = load_all_enriched(days=60)
    # 确保今天的在
    if today_articles and date_str not in all_data:
        all_data[date_str] = today_articles

    print(f"今日 {len(today_articles)} 篇\n")

    build_category_files(date_str, all_data, new_days)
    build_index(date_str, all_data, new_days)
    build_rss(all_data)
    build_site(all_data)

    print("\n[DONE] 全部输出已生成")


if __name__ == "__main__":
    run()
