# AIラボ 15分類 AI News Notifier

discord-rss-notifier から**分離**した専用リポ。
分離理由: 同一リポで Crypto Bridge / 金融市場Bot が workflow_run で連鎖多発し、
GitHub Actions の枠を占有して本workflowの schedule が起動しなくなっていた(目詰まり)。

## 必要な Secrets (15本)
DISCORD_AILAB_WEBHOOK_{OPENAI,CLAUDE,GEMINI,XAI,COPILOT,META,CHINA,LOCAL,IMGVID,AUDIO,TOOLS,PAPERS,GENERAL,RELEASE,WORLD}

## 仕組み
- 記事の公開時刻でソートし、直近 FRESH_HOURS=48h の新しい順に拾う(速報化)
- 重複排除: ailab_seen_urls.json
- cron と workflow_dispatch の両方で起動
