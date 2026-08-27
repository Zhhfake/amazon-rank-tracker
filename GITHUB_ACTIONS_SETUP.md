# GitHub 定时运行设置

这个项目已经准备好了 GitHub Actions 定时文件：

`.github/workflows/amazon-rank-tracker.yml`

## 运行时间

当前设置为每小时第 17 分钟自动运行一次，例如 10:17、11:17、12:17。

也可以在 GitHub 页面手动点 `Run workflow` 立即运行。

## 你需要在 GitHub 填的 Secrets

进入仓库：

`Settings` -> `Secrets and variables` -> `Actions` -> `New repository secret`

添加这 6 个：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_WEBHOOK`
- `FEISHU_PRIVATE_OPEN_ID`
- `SPREADSHEET_TOKEN`
- `SPREADSHEET_URL`

## 注意

`amazon_rank_tracker/local_secrets.py` 只给你本地双击运行使用，已经放进 `.gitignore`，不要上传到 GitHub。

如果 GitHub Actions 里频繁遇到 Amazon 503，说明 GitHub 服务器 IP 被 Amazon 限制了。那时建议改用 GitHub self-hosted runner，让 GitHub 定时任务实际跑在你自己的 Mac 上。
