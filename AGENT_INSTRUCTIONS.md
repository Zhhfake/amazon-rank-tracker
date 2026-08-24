# Agent 指令 — Amazon 自然位排名自动追踪部署

> 这份文档是给 AI Agent（Claude Code / Codex / Cursor / Copilot 等）看的。
> 把这个文件喂给你的 Agent，它就能帮你完成部署。

---

## 你是谁

你是一个帮助亚马逊卖家部署"自然位排名自动追踪"系统的 AI 助手。这套系统每天自动查询 Amazon 搜索结果中产品的自然排名，写入飞书电子表格，并发送日报通知。

## 系统架构

```
本地电脑 (launchd/crontab)     GitHub Actions (云端备胎)
        │                              │
        ▼                              ▼
  rank_tracker_core.py ──→ Playwright 浏览器 ──→ Amazon 搜索
        │
        ▼
  飞书电子表格（写入排名 + 上色）
        │
        ▼
  飞书群机器人（发送日报卡片）
```

## 部署步骤

### 1. 准备飞书

帮用户确认以下信息（如果用户没提供，逐一询问）：

- [ ] 飞书自建应用的 `App ID` 和 `App Secret`
  - 在 https://open.feishu.cn/app 创建
  - 需要开通权限：`sheets:spreadsheet`（电子表格读写）
- [ ] 飞书电子表格的 `token`
  - 打开表格 URL 里 `/sheets/` 后面那串
- [ ] 每个产品对应的飞书 sheet tab 的 `sheet_id`
  - 通过飞书 API 获取：`GET /sheets/v2/spreadsheets/{token}/sheets`
- [ ] 飞书群机器人的 `webhook URL`
  - 群设置 → 群机器人 → 添加自定义机器人

### 2. 准备产品信息

帮用户整理每个产品的配置：

- [ ] 产品 ASIN（Amazon 产品页 URL 里 `/dp/` 后面的10位码）
- [ ] 关键词在飞书表格的哪一列（通常是 A 列）
- [ ] 关键词从第几行开始、到第几行结束
- [ ] 日期行在第几行（通常是第2行）
- [ ] 需要搜索几页（默认7页，大词库产品可以10页）

### 3. 生成配置文件

根据用户提供的信息，把 `config_template.py` 复制为 `config.py` 并填入实际值。

### 4. 本地测试

```bash
# 安装依赖
pip install playwright
playwright install chromium

# 先跑一个产品测试
python rank_tracker_core.py --sheet "产品名"

# 确认飞书表格有数据后，跑全部
python rank_tracker_core.py
```

### 5. 设置定时任务

**macOS (launchd):**
创建 `~/Library/LaunchAgents/com.rank-tracker.daily.plist`，设置每天早上触发。

**Linux (crontab):**
```bash
crontab -e
# 每天北京时间 10:30 跑
30 2 * * * cd /path/to/repo && python3 rank_tracker_core.py >> /tmp/rank.log 2>&1
```

### 6. 部署 GitHub Actions 备胎

1. 把 `workflow_template.yml` 复制到 `.github/workflows/daily-rank.yml`
2. 根据产品数量复制/删除 job
3. 调整 `--sheet` 参数和 `timeout-minutes`
4. 推到 GitHub

## 注意事项

- **凭证安全**：飞书 App Secret 和 Webhook URL 是敏感信息。本地跑可以直接写在 config.py 里（.gitignore 掉），云端跑建议用 GitHub Secrets
- **反爬**：Amazon 会封频繁请求的 IP。脚本有内置的重试/冷却/补查机制，但如果经常被封，建议增大 `DELAY_BETWEEN_KEYWORDS`
- **飞书表格结构**：关键词列 + 日期行的位置必须和 config 里的一致，否则数据会写错地方
- **断点续传**：脚本会检查已有数据，中断后重跑不会覆盖已查到的结果

## 常见排错

| 问题 | 原因 | 解决 |
|------|------|------|
| 飞书 API 401 | Token 过期或权限不足 | 检查 App ID/Secret，确认应用有 sheets 权限 |
| 覆盖率低于 50% | Amazon 反爬 | 增大延迟，或换邮编，或等几小时后重跑 |
| GitHub Actions 超时 | 关键词太多 | 增大 timeout-minutes，或把产品拆成更多 job 并行跑 |
| 数据写错列 | 表格结构变了 | 检查 date_row、kw_col、kw_start_row 是否正确 |
