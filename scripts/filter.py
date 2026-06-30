"""冷门过滤模块。
读入原始抓取数据，根据规则过滤掉热门/低质内容，输出候选池。
"""

import json
import re
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources" / "feeds.yaml"
DATA_RAW = ROOT / "data" / "raw"
DATA_SCORED = ROOT / "data" / "scored"


def load_filter_rules() -> dict:
    """加载 feeds.yaml 里的过滤配置。"""
    with open(SOURCES_FILE, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config.get("filter", {})


def load_raw_articles(date_str: str | None = None) -> list[dict]:
    """加载指定日期的原始抓取数据。"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
    path = DATA_RAW / f"{date_str}.json"
    if not path.exists():
        print(f"[ERROR] 原始数据不存在: {path}")
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def apply_rules(articles: list[dict], rules: dict) -> tuple[list[dict], list[dict]]:
    """应用过滤规则，返回 (候选池, 被过滤掉的)。"""
    hot_domains = set(rules.get("hot_domains", []))
    hot_keywords = [kw.lower() for kw in rules.get("hot_keywords", [])]
    min_length = rules.get("min_content_length", 300)

    passed = []
    dropped = []

    for a in articles:
        reason = _check_one(a, hot_domains, hot_keywords, min_length)
        if reason is None:
            passed.append(a)
        else:
            dropped.append({"article": a, "reason": reason})

    print(f"[过滤] {len(passed)} 篇通过 / {len(dropped)} 篇丢弃")
    return passed, dropped


def _check_one(
    a: dict, hot_domains: set, hot_keywords: list, min_length: int
) -> str | None:
    """检查单篇文章是否应被丢弃。返回 None 表示通过，否则返回丢弃原因。"""
    url = a.get("url", "")
    title = (a.get("title") or "").lower()
    content = a.get("content") or a.get("summary") or ""

    # 1. 热门域名
    for domain in hot_domains:
        if domain in url:
            return f"hot_domain:{domain}"

    # 2. 热门关键词
    combined = f"{title} {content[:500]}".lower()
    for kw in hot_keywords:
        if kw in combined:
            return f"hot_keyword:{kw}"

    # 3. 内容过短（灌水）
    if len(content) < min_length:
        return f"too_short({len(content)}<{min_length})"

    # 4. 纯转载/聚合页面（简单启发）
    if re.search(r"(转载|转自|来源：|原文链接)", title):
        # 标题含转载标记，倾向于丢弃（原创性低）
        pass  # 不强制丢弃，交给 AI 评分判断

    return None


def apply_cold_boost(articles: list[dict], rules: dict) -> list[dict]:
    """对冷门来源的文章标记 boost，后续评分可加权。"""
    cold_domains = rules.get("cold_boost_domains", [])
    for a in articles:
        url = a.get("url", "")
        boost = 0
        for domain in cold_domains:
            if domain in url:
                boost += 1
        a["cold_boost"] = boost
    return articles


def run(date_str: str | None = None):
    """主入口：加载 → 过滤 → 保存候选池。"""
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    rules = load_filter_rules()
    articles = load_raw_articles(date_str)

    if not articles:
        print("没有可过滤的文章。")
        return

    passed, dropped = apply_rules(articles, rules)
    passed = apply_cold_boost(passed, rules)

    # 保存
    DATA_SCORED.mkdir(parents=True, exist_ok=True)

    out_path = DATA_SCORED / f"{date_str}_candidates.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(passed, f, ensure_ascii=False, indent=2)

    # 也保存被丢弃的，方便调试
    dump_path = DATA_SCORED / f"{date_str}_dropped.json"
    with open(dump_path, "w", encoding="utf-8") as f:
        json.dump(dropped, f, ensure_ascii=False, indent=2, default=str)

    print(f"[DONE] 候选池 {len(passed)} 篇 → {out_path}")


if __name__ == "__main__":
    run()
