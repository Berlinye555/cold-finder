"""AI 评分 + 摘要模块。
读取候选池，调用 DeepSeek API 对每篇文章评分，选出 Top N。
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "sources" / "feeds.yaml"
DATA_SCORED = ROOT / "data" / "scored"

SCORING_PROMPT = """You are an editor who finds undervalued content. Score this article (1-10) on:

1. originality — unique ideas, not rehashing common knowledge
2. density — how much new knowledge/perspective per paragraph
3. uniqueness — unconventional angle, challenges mainstream views

Then write:
- A one-line Chinese summary (about 20 words)
- A one-line hook in Chinese (about 15 words, make readers click)

Article:
- Title: {title}
- Source: {source}
- Summary: {content}

Return ONLY this JSON, nothing else:
{{"originality":8,"density":7,"uniqueness":6,"summary":"20字中文摘要","hook":"15字中文推荐语"}}"""


def load_config() -> dict:
    with open(SOURCES_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_candidates(date_str: str) -> list[dict]:
    path = DATA_SCORED / f"{date_str}_candidates.json"
    if not path.exists():
        print(f"[ERROR] 候选池不存在: {path}")
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _call_llm(client: httpx.Client, prompt: str, model: str) -> str | None:
    """直接通过 HTTP 调用智谱/OpenAI 兼容 API。"""
    url = f"{os.getenv('DEEPSEEK_BASE_URL', 'https://api.deepseek.com')}/chat/completions"
    # 去掉可能的双斜杠
    url = url.replace("v4//chat", "v4/chat")

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 200,
    }
    headers = {
        "Authorization": f"Bearer {os.getenv('DEEPSEEK_API_KEY')}",
        "Content-Type": "application/json",
    }
    resp = client.post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def score_article(client: httpx.Client, article: dict, dimensions: list[dict]) -> dict | None:
    """对单篇文章调用 AI 评分。返回评分结果或 None（失败时）。"""
    content = (article.get("content") or article.get("summary") or "")[:1500]
    title = article.get("title", "")
    source = article.get("source_name", "")
    model = os.getenv("DEEPSEEK_MODEL", "GLM-4-Flash")

    prompt = SCORING_PROMPT.format(title=title, source=source, content=content)

    try:
        raw = _call_llm(client, prompt, model)

        # 清理可能的 markdown 代码块包裹
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("\n```", 1)[0]

        result = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[WARN] AI 返回非 JSON: {raw[:100]}... ({exc})")
        return None
    except Exception as exc:
        print(f"[WARN] API 调用失败: {exc}")
        return None

    # 计算加权总分
    weights = {d["key"]: d["weight"] for d in dimensions}
    total = (
        result.get("originality", 5) * weights.get("originality", 0.4)
        + result.get("density", 5) * weights.get("density", 0.35)
        + result.get("uniqueness", 5) * weights.get("uniqueness", 0.25)
    )

    # 应用冷门加成
    boost = article.get("cold_boost", 0)
    total += boost * 0.5  # 每个 boost 加 0.5 分

    return {
        "title": title,
        "url": article.get("url"),
        "source": source,
        "category": article.get("category"),
        "originality": result.get("originality"),
        "density": result.get("density"),
        "uniqueness": result.get("uniqueness"),
        "score": round(total, 1),
        "summary": result.get("summary", ""),
        "hook": result.get("hook", ""),
        "cold_boost": boost,
    }


def run(date_str: str | None = None):
    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    config = load_config()
    scoring_cfg = config.get("scoring", {})
    dimensions = scoring_cfg.get("dimensions", [])
    min_score = scoring_cfg.get("min_total_score", 7.0)
    daily_picks = scoring_cfg.get("daily_picks", 3)

    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("[ERROR] 请设置环境变量 DEEPSEEK_API_KEY")
        return

    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    model = os.getenv("DEEPSEEK_MODEL", "GLM-4-Flash")
    http_client = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))

    candidates = load_candidates(date_str)
    if not candidates:
        print("没有候选文章可供评分。")
        return

    # 限制候选数量：按内容长度排序，取前 50 篇，控制 API 消耗
    MAX_CANDIDATES = 50
    candidates.sort(key=lambda a: len(a.get("content") or a.get("summary") or ""), reverse=True)
    if len(candidates) > MAX_CANDIDATES:
        skipped = len(candidates) - MAX_CANDIDATES
        candidates = candidates[:MAX_CANDIDATES]
        print(f"[LIMIT] 候选池截断: {len(candidates)} 篇 (跳过 {skipped} 篇短内容)")

    # API 连通性测试
    print(f"API: {base_url} | model: {model}")
    try:
        test_url = f"{base_url}/chat/completions".replace("v4//chat", "v4/chat")
        test_resp = http_client.post(
            test_url,
            json={"model": model, "messages": [{"role": "user", "content": "回复OK"}], "max_tokens": 5},
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        test_resp.raise_for_status()
        test_data = test_resp.json()
        print(f"[CONNECT OK] {test_data['choices'][0]['message']['content']}")
    except Exception as exc:
        print(f"[CONNECT FAIL] {type(exc).__name__}: {exc}")
        return

    print(f"\n开始评分 {len(candidates)} 篇候选文章...\n")

    scored = []
    for i, article in enumerate(candidates):
        print(f"[{i+1}/{len(candidates)}] {article.get('title', '')[:40]}...", end=" ")
        result = score_article(http_client, article, dimensions)
        if result:
            scored.append(result)
            print(f"→ {result['score']}分")
        else:
            print("→ 跳过")
        time.sleep(0.3)  # API 调用间隔

    # 按分数排序
    scored.sort(key=lambda x: x["score"], reverse=True)

    # 筛选达标文章
    qualified = [s for s in scored if s["score"] >= min_score]
    picks = qualified[:daily_picks]

    print(f"\n评分完成: {len(scored)} 篇有效, {len(qualified)} 篇达标, 入选 {len(picks)} 篇")

    for p in picks:
        print(f"  ★ {p['score']}分 | {p['title'][:50]}")

    # 保存评分结果
    out_path = DATA_SCORED / f"{date_str}_scored.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(scored, f, ensure_ascii=False, indent=2)

    picks_path = DATA_SCORED / f"{date_str}_picks.json"
    with open(picks_path, "w", encoding="utf-8") as f:
        json.dump(picks, f, ensure_ascii=False, indent=2)

    print(f"\n[DONE] 全部评分 → {out_path}")
    print(f"[DONE] 今日精选 → {picks_path}")


if __name__ == "__main__":
    run()
