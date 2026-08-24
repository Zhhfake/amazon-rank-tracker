# Amazon 自然位排名自动追踪 — 可复用 Skill

> 给任何 AI Agent（Claude Code / Codex / Cursor 等）用的自动化模板。
> 改配置 → 部署 → 每天自动查排名、写飞书、发日报。

---

## 这套系统做什么

1. **每天自动查询** 你的 Amazon 产品在指定关键词下的自然搜索排名
2. **写入飞书电子表格**，自动找到正确的日期列、断点续传
3. **涨跌上色**（绿涨红跌白不变），一眼看趋势
4. **覆盖率补查**：低于 85% 自动重试漏掉的词
5. **飞书机器人日报**：跑完自动推送汇总卡片
6. **本地优先 + 云端兜底**：本地 Playwright 跑主力，GitHub Actions 做备胎

---

## 快速上手（3 步）

### Step 1: 复制文件

把 `skills/amazon-organic-rank-tracker/` 整个目录复制到你自己的项目里：

```
your-repo/
├── rank_to_feishu.py          # 主脚本（从 template/ 复制并改配置）
├── .github/workflows/
│   └── daily-rank.yml         # GitHub Actions（从 template/ 复制并改配置）
└── ...
```

### Step 2: 改配置

打开 `config_template.py`，只改 `=== 你需要改的部分 ===` 标注的内容：

| 配置项 | 说明 | 在哪改 |
|--------|------|--------|
| `FEISHU_APP_ID` | 飞书自建应用 App ID | config 顶部 |
| `FEISHU_APP_SECRET` | 飞书自建应用 App Secret | config 顶部 |
| `SPREADSHEET_TOKEN` | 飞书电子表格 token（URL 里的那串） | config 顶部 |
| `FEISHU_WEBHOOK` | 飞书群机器人 webhook URL | config 顶部 |
| `PRODUCTS` | 你的产品列表（ASIN、sheet、关键词范围） | config 中部 |
| `ZIPCODE` | 美国邮编（影响搜索结果本地化） | config 中部 |

### Step 3: 部署

```bash
# 本地跑一次测试
pip install playwright && playwright install chromium
python rank_to_feishu.py --sheet "你的产品名"

# 推到 GitHub，Actions 自动按 cron 触发
git push
```

---

## 文件说明

```
skills/amazon-organic-rank-tracker/
├── README.md                  # 你正在看的文档
├── config_template.py         # 配置模板（只改这个文件的上半部分）
├── rank_tracker_core.py       # 核心逻辑（不需要改）
├── workflow_template.yml      # GitHub Actions 模板
└── AGENT_INSTRUCTIONS.md      # 给 AI Agent 的指令（让 Agent 帮你部署）
```

---

## 飞书表格要求

你的飞书电子表格需要这样的结构：

```
     A(或B)列        C列      D列      E列 ...
行1  (标题或空)
行2  (日期行)                  5/19     5/20    ← 脚本自动写日期
行3  关键词1                   Page 1·#5  Page 1·#3
行4  关键词2                   Page 2·#28 —
行5  关键词3                   ...
...
```

- **关键词列**：放你要查的搜索词，一行一个
- **日期行**：脚本自动在最右边追加新日期列
- 每个产品一个 sheet（同一个表格文件里的不同 sheet tab）

---

## 常见问题

**Q: 被 Amazon 反爬了怎么办？**
脚本有自动重试、浏览器重启、60秒冷却、补查机制。如果经常被封，可以：
- 增大 `DELAY_BETWEEN_KEYWORDS`（默认3秒）
- 减少 `MAX_PAGES`（默认7页）
- 换 `ZIPCODE`

**Q: 可以查多个站点吗（不只是 amazon.com）？**
目前只支持 amazon.com。改其他站需要改 `AmazonRanker` 类里的 URL。

**Q: GitHub Actions 怎么做备胎？**
workflow 里有 `pre-check` job：先查飞书今天有没有数据，有就跳过，没有才跑。
本地 launchd/crontab 先跑（早上），云端下午补。
