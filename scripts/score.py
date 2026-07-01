"""内容增强模块。
不评分不排名——只做两件事：
1. 为文章生成一句话中文摘要 + 多平台版本
2. 源头已有的描述原样保留，不调 AI
"""

import json
import os
from datetime import datetime
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = ROOT / "sources" / "feeds.yaml"
DATA_RAW = ROOT / "data" / "raw"
DATA_ENRICHED = ROOT / "data" / "enriched"

PROMPT = """给这篇文章写三样东西（中文，各一句话）：

文章：{title}
内容：{content}

返回 JSON：
{{"summary":"30字摘要","wechat":"公众号版推荐语 40字","jike":"即刻版一句话 25字","xhs":"小红书版 20字+3个#tag"}}"""


def load_config() -> dict:
    with open(CFG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_articles(date_str: str) -> list[dict]:
    path = DATA_RAW / f"{date_str}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def enrich(client: httpx.Client, article: dict, model: str, base_url: str) -> dict:
    """为单篇文章添加 AI 摘要和平台版本。"""
    title = article.get("title", "")
    content = (article.get("content") or article.get("source_desc", ""))[:1200]

    # 内容太短，直接用 source_desc 作为摘要
    if len(content) < 60:
        article["summary"] = article.get("source_desc", "")[:100]
        article["wechat"] = article["source_desc"][:120] if article.get("source_desc") else title
        article["jike"] = f"{title} {article.get('url', '')}"
        article["xhs"] = f"#{article.get('category', '')} #{title[:20]}"
        return article

    try:
        api_key = os.getenv("DEEPSEEK_API_KEY")
        resp = client.post(
            f"{base_url}/chat/completions".replace("v4//chat", "v4/chat"),
            json={
                "model": model,
                "messages": [{"role": "user", "content": PROMPT.format(title=title, content=content)}],
                "temperature": 0.5,
                "max_tokens": 250,
            },
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"].strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]
        result = json.loads(raw)
    except Exception as exc:
        print(f"  [WARN] AI失败: {exc}")
        result = {}

    article["summary"] = result.get("summary", title)
    article["wechat"] = result.get("wechat", article.get("source_desc", title)[:120])
    article["jike"] = result.get("jike", f"{title} {article['url']}")
    article["xhs"] = result.get("xhs", f"#{article.get('category', 'tech')} #{title[:20]}")
    return article


def run(date_str: str | None = None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    cfg = load_config()
    summary_cfg = cfg.get("summary", {})
    model = summary_cfg.get("model", "GLM-4-Flash")
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    articles = load_articles(date_str)
    if not articles:
        print("没有文章。")
        return

    print(f"增强 {len(articles)} 篇文章...\n")

    enriched = []
    with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
        for i, a in enumerate(articles):
            print(f"[{i+1}/{len(articles)}] {a.get('title','')[:50]}...", end=" ")
            a = enrich(client, a, model, base_url)
            enriched.append(a)
            print("✓")

    DATA_ENRICHED.mkdir(parents=True, exist_ok=True)
    out_path = DATA_ENRICHED / f"{date_str}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    # 统计分类
    from collections import Counter
    cats = Counter(a.get("category", "other") for a in enriched)
    print(f"\n[DONE] {len(enriched)} 篇 → {out_path}")
    for c, n in cats.most_common():
        print(f"  {c}: {n}篇")


if __name__ == "__main__":
    run()
