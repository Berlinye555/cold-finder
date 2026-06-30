# 冷门精选 · Cold Finder

每天从上百个 RSS 源中，用 AI 挖出 3 篇被算法埋没的好文章。

## 工作原理

```
RSS 源（50+） → 抓取 → 过滤热门 → AI 评分 → 每日精选 3 篇
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
              公众号 Markdown             RSS Feed                 网页存档
           （复制粘贴发送）          （导入阅读器订阅）          （GitHub Pages）
```

## 零成本栈

| 环节 | 方案 | 费用 |
|------|------|:--:|
| 定时抓取 | GitHub Actions | ¥0 |
| AI 评分 | DeepSeek API | ¥0 |
| 网页托管 | GitHub Pages | ¥0 |
| 主分发 | 微信公众号（个人订阅号） | ¥0 |

## 快速开始

1. Fork 本仓库
2. 在 Settings → Secrets 中添加 `DEEPSEEK_API_KEY`
3. 启用 GitHub Pages（Settings → Pages → Source: GitHub Actions）
4. 手动触发一次 Actions 测试
5. 每天早上 8:00 自动运行

## 每日操作

```bash
# GitHub Actions 自动跑完后
# 打开 output/wechat/YYYY-MM-DD.md
# 复制 → 微信公众号后台 → 粘贴 → 发送
# 全程 2 分钟
```

## 目录结构

```
├── .github/workflows/digest.yml   # 定时任务
├── scripts/
│   ├── fetch.py                   # RSS 抓取
│   ├── filter.py                  # 冷门过滤
│   ├── score.py                   # AI 评分
│   └── output.py                  # 多渠道输出
├── sources/feeds.yaml             # 订阅源 + 规则配置
├── data/                          # 抓取/评分数据
├── output/
│   ├── wechat/                    # 公众号 Markdown
│   ├── rss/feed.xml              # RSS Feed
│   └── site/                      # 网页存档
└── requirements.txt
```

## 定制

编辑 `sources/feeds.yaml`：
- `sources` — 增删 RSS 订阅源
- `filter` — 调整冷门过滤规则
- `scoring` — 修改 AI 评分维度与阈值
