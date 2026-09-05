#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ================================================================
# ailab_news_bot.py — AIラボ鯖 15分類AIニュース自動配信（GitHub配布用・独立スクリプト）
# ----------------------------------------------------------------
# 方式: 朝活/激裏型。Google News検索RSS＋実証済みニュース母体を分類別クエリで切って投稿。
#       AI分類は使わず route_id / source で分類を固定（IC倶楽部方式）。
# 設計の正本: 自分/AIニュース15分類_取得クエリ設計_完全再設計版 1.md（2026-07-08）
# 2026-07-09: 初期実運用で「量は出るが質が荒い」ことを確認。
#   方針変更: 公式RSS/GitHub release/APIを主水路にしない。
#   トレンド朝活で効いているニュース母体を15分類のクエリ違いで使い回す。
#
# 使い方:
#   1) pip install feedparser
#   2) Webhookを環境変数で（GitHub Actionsは Secrets 推奨）:
#        DISCORD_AILAB_WEBHOOK_{OPENAI,CLAUDE,GEMINI,XAI,COPILOT,META,CHINA,
#                              LOCAL,IMGVID,AUDIO,TOOLS,PAPERS,GENERAL,RELEASE,WORLD}
#   3) ローカルテストは環境変数が無ければ同ディレクトリ ailab_webhooks.json を fallback（配布時 .gitignore）
#   4) python ailab_news_bot.py
#   5) 自動化: .github/workflows で cron '15,45 * * * *'
# 重複排除: 同ディレクトリ ailab_seen_urls.json / 投稿POSTには User-Agent 必須(無いとCloudflare403)
# ================================================================
import os, sys, io, json, time, re, calendar, urllib.parse, urllib.request, urllib.error
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
try:
    import feedparser
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "feedparser"])
    import feedparser

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(HERE, "ailab_seen_urls.json")
WEBHOOKS_JSON = os.path.join(HERE, "ailab_webhooks.json")
PER_SOURCE = 3        # ★速報化: 1ソースから拾う上限
PER_CHANNEL = 4       # ★速報化: 1chの1回あたり投稿上限
FRESH_HOURS = 48      # ★速報化: 直近48hの記事だけを速報として拾う(窓外の古い既出は対象外)
NOW = time.time()     # 実行開始時刻(UTC epoch)。時間窓判定の基準
UA = "AILabNewsBot/1.0 (+https://discord.com)"
COL_BIZ, COL_FIELD, COL_SUM = 0x00E5FF, 0x00FF9C, 0xFF7A1A

GLOBAL_EXCLUDE = [
    "PR TIMES", "プレスリリース", "アットプレス", "valuepress",
    "株価", "決算", "ホールド評価", "求人", "採用", "セミナー", "イベント開催",
    "ライブ配信", "ウェビナー", "講座", "Investing.com", "ファイナンス", "金融ニュース",
    "使ってみた", "とは？", "とは何か", "徹底解説", "始め方", "初心者", "AIsmiley", "ai-market.jp",
    "キャンペーン", "無料公開", "広告", "Sponsored",
    "料金はいくら", "全プラン比較", "最適な選び方", "おすすめランキング", "資料請求",
    "日記", "使い倒し", "仕事術", "入門",
]

def rss(url, include=None, exclude=None, label=None, title_include=None, title_exclude=None):
    return {"type": "rss", "url": url, "include": include or [], "exclude": exclude or [],
            "label": label, "title_include": title_include or [], "title_exclude": title_exclude or []}

def gn(q, include=None, exclude=None, label=None, title_include=None, title_exclude=None):
    return {"type": "gn", "q": q, "include": include or [], "exclude": exclude or [],
            "label": label, "title_include": title_include or [], "title_exclude": title_exclude or []}

def sitemap(url, include=None, exclude=None, label=None, path_prefix=None, title_include=None, title_exclude=None):
    return {"type": "sitemap", "url": url, "include": include or [], "exclude": exclude or [],
            "label": label, "path_prefix": path_prefix or [], "title_include": title_include or [],
            "title_exclude": title_exclude or []}

# ---- 15分類（2026-07-09 ノイズ削減版）----
OPENAI_TERMS = ["OpenAI", "ChatGPT", "GPT", "Sora", "Codex", "Responses API", "API"]
CLAUDE_TERMS = ["Anthropic", "Claude", "Claude Code", "Claude API", "Claude Sonnet", "Claude Opus", "Claude Haiku"]
GEMINI_TERMS = ["Gemini", "DeepMind", "NotebookLM", "Veo", "Imagen", "Gemma", "Gemini API"]
XAI_TERMS = ["xAI", "Grok"]
COPILOT_TERMS = ["Copilot", "GitHub Copilot", "Microsoft 365 Copilot", "Copilot Studio", "Azure AI"]
META_TERMS = ["Meta AI", "Meta Llama", "Llama", "Llama 4"]
CHINA_TERMS = ["DeepSeek", "Qwen", "Kimi", "Zhipu", "GLM", "MiniMax", "Moonshot"]
LOCAL_TERMS = ["Hugging Face", "Ollama", "llama.cpp", "GGUF", "LM Studio", "vLLM", "ローカルLLM"]
IMGVID_TERMS = ["Midjourney", "Sora", "Runway", "Kling", "Veo", "Imagen", "Stable Diffusion", "Flux", "Luma AI", "Pika", "画像生成", "動画生成",
                "Seedance", "Hailuo", "nano banana", "Black Forest", "Wan", "AI画像", "AI動画", "Qwen-Image"]
# ★2026-09-05 実叩きで出た誤ヒットを名指しで潰す。⑨の語は一般語と衝突するため必須。
#   Runway→ファッションのランウェイ / Sora→ときのそら・空 / Flux→eスポーツのチーム名
IMGVID_EXCLUDE = ["訴訟", "裁判", "著作権訴訟", "提訴", "係争", "映画スタジオ",
                  "UNIVERSAL MUSIC", "VITURE", "スマートグラス", "医療", "サウナ", "超音波", "Spa",
                  "COLLECTION", "コレクション", "ファッション", "ランウェイ", "伊勢丹",
                  "Marc Jacobs", "マーク ジェイコブス", "デザイナー",
                  "ホロライブ", "ときのそら", "VTuber", "Vtuber", "shorts",
                  "Esports", "esports", "Sofascore", "ライブスコア",
                  "天気", "tenki.jp", "ウォーターキッズ",
                  "絶対領域", "ミニスカ", "グラビア", "ｄメニュー", "配信者"]
AUDIO_TERMS = ["ElevenLabs", "Suno", "Udio", "Whisper", "VOICEVOX", "音声生成", "音楽生成", "音声合成", "TTS", "voice", "speech"]
TOOL_TERMS = ["Claude Code", "Codex", "Cursor", "GitHub Copilot", "n8n", "MCP", "LangChain", "Devin", "AIエージェント"]
PAPER_TERMS = ["LLM", "language model", "agent", "reasoning", "RAG", "GPT", "diffusion", "multimodal", "transformer", "benchmark"]
MODEL_RELEASE_TERMS = ["新モデル", "モデル公開", "オープンウェイト", "提供開始", "generally available", "open weights", "GPT", "Claude", "Gemini", "Grok", "Llama", "Qwen", "DeepSeek", "Mistral"]
POLICY_TERMS = ["AI規制", "AI政策", "AI法", "AI著作権", "AI safety", "AI regulation", "AI Act", "export controls", "semiconductor", "半導体"]

TOPICS = [
 # 🏢 企業別 ①〜⑦：主水路はGoogle News検索RSS。公式RSS/changelogは後順位の補助。
 {"num":"①","name":"チャッピー速報","env":"OPENAI","color":COL_BIZ,"sources":[
     gn('(OpenAI OR ChatGPT OR Codex OR Sora OR GPT) (発表 OR 公開 OR 提供開始 OR 新機能 OR 新モデル OR 料金 OR API) -求人 -株価 -広告',
        include=OPENAI_TERMS, exclude=["広告運用", "導入事例", "customer", "case study"]),
     rss("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", include=OPENAI_TERMS),
     rss("https://gigazine.net/news/rss_2.0/", include=OPENAI_TERMS),
     rss("https://zenn.dev/topics/ai/feed", include=OPENAI_TERMS)]},
 {"num":"②","name":"クロード速報","env":"CLAUDE","color":COL_BIZ,"sources":[
     gn('(Anthropic OR Claude OR "Claude Code" OR "Claude API") (発表 OR 公開 OR 提供開始 OR 新機能 OR 新モデル OR 料金 OR API) -MCPサーバ -脆弱性',
        include=CLAUDE_TERMS, exclude=["中转站", "プロキシ", "非公式", "ProductZine", "MVP", "PMF", "コミュニティアンバサダー"]),
     rss("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", include=CLAUDE_TERMS),
     rss("https://gigazine.net/news/rss_2.0/", include=CLAUDE_TERMS),
     rss("https://zenn.dev/topics/claude/feed", include=CLAUDE_TERMS),
     sitemap("https://www.anthropic.com/sitemap.xml",
        include=["claude", "sonnet", "opus", "haiku", "model", "api", "code", "safety"],
        exclude=["events/", "careers/", "legal/", "learn/", "pricing", "jobs", "interviewer",
                 "golden-gate", "persona-selection", "economic-index"],
        path_prefix=["/news/", "/engineering/"], label="Anthropic official sitemap")]},
 {"num":"③","name":"ジェミニ速報","env":"GEMINI","color":COL_BIZ,"sources":[
     gn('(Gemini OR "Gemini API" OR DeepMind OR NotebookLM OR Veo OR Imagen OR Gemma) (発表 OR 公開 OR 提供開始 OR 新機能 OR 新モデル OR API OR アップデート) -Pixel -写真',
        include=GEMINI_TERMS),
     rss("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", include=GEMINI_TERMS),
     rss("https://gigazine.net/news/rss_2.0/", include=GEMINI_TERMS),
     rss("https://blog.google/technology/ai/rss/", include=GEMINI_TERMS, exclude=["Pixel", "Google Photos", "写真"]),
     rss("https://deepmind.google/blog/rss.xml", include=GEMINI_TERMS),
     rss("https://zenn.dev/topics/gemini/feed", include=GEMINI_TERMS, title_include=["Gemini"])]},
 {"num":"④","name":"グロック速報","env":"XAI","color":COL_BIZ,"sources":[
     # ★2026-09-03 実叩き: 旧クエリは後置の限定語(発表 OR 公開…)がANDで効き、48h以内0件だった。
     #   'Grok OR xAI' の広めクエリは実測10件、reddit r/grok は実測5件。
     gn('Grok OR xAI OR "Grok 4" OR "Grok 5" -SpaceXAI -スペースXAI',
        include=XAI_TERMS, exclude=["スペースXAI", "カーサー共同", "買収直後のCursor", "note", "AIイラストクリエイター"]),
     rss("https://www.reddit.com/r/grok/top/.rss?t=day&limit=15", include=XAI_TERMS),
     rss("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", include=XAI_TERMS),
     rss("https://gigazine.net/news/rss_2.0/", include=XAI_TERMS),
     rss("https://hnrss.org/frontpage", include=XAI_TERMS)]},
 {"num":"⑤","name":"コパイロット速報","env":"COPILOT","color":COL_BIZ,"sources":[
     gn('("Microsoft Copilot" OR "GitHub Copilot" OR "Copilot Studio" OR "Azure AI" OR "M365 Copilot") (発表 OR 公開 OR 提供開始 OR 新機能 OR 料金 OR アップデート)',
        include=COPILOT_TERMS, exclude=["保険", "library", "farming", "school"]),
     rss("https://www.publickey1.jp/atom.xml", include=COPILOT_TERMS),
     rss("https://zenn.dev/topics/ai/feed", include=COPILOT_TERMS, title_include=["Copilot"]),
     rss("https://github.blog/changelog/label/copilot/feed/", include=COPILOT_TERMS, title_include=["Copilot"])]},
 {"num":"⑥","name":"メタAI速報","env":"META","color":COL_BIZ,"sources":[
     # ★2026-09-03 実叩き: 後置の限定語(発表 OR 公開…)がANDで効き48h以内0件だった。外すと実測1件。
     #   新ソースは全滅(ai.meta.com/blog=404 / theverge・techmeme・hnrss=0)のため追加せずクエリのみ広げる。
     gn('"Meta AI" OR "Meta Llama" OR Llama OR "Meta Superintelligence" -"MUSIC FAIR" -音楽',
        include=META_TERMS, exclude=["MUSIC FAIR", "Garmin", "AIグラス"]),
     rss("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", include=META_TERMS),
     rss("https://gigazine.net/news/rss_2.0/", include=META_TERMS),
     rss("https://hnrss.org/frontpage", include=META_TERMS)]},
 {"num":"⑦","name":"中国AI速報","env":"CHINA","color":COL_BIZ,"sources":[
     gn('(DeepSeek OR Qwen OR Kimi OR Zhipu OR GLM OR MiniMax OR Moonshot) (発表 OR 公開 OR 提供開始 OR 新機能 OR 新モデル OR API OR オープンソース OR benchmark)',
        include=CHINA_TERMS, exclude=["BigGo ファイナンス"]),
     rss("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", include=CHINA_TERMS),
     rss("https://gigazine.net/news/rss_2.0/", include=CHINA_TERMS),
     rss("https://hnrss.org/frontpage", include=CHINA_TERMS)]},
 # 🔬 分野別 ⑧〜⑫
 {"num":"⑧","name":"ローカルLLM速報","env":"LOCAL","color":COL_FIELD,"sources":[
     gn('(ローカルLLM OR Ollama OR "Hugging Face" OR llama.cpp OR GGUF OR "LM Studio" OR vLLM) (発表 OR 公開 OR 提供開始 OR 新モデル OR GPU OR 推論 OR 高速化)',
        include=LOCAL_TERMS),
     rss("https://huggingface.co/blog/feed.xml", include=LOCAL_TERMS + ["model", "agents", "inference"]),
     rss("https://hnrss.org/frontpage", include=LOCAL_TERMS),
     rss("https://www.reddit.com/r/LocalLLaMA/top/.rss?t=day&limit=10", include=LOCAL_TERMS + ["LLM", "model"]),
     rss("https://ollama.com/blog/rss.xml", include=LOCAL_TERMS + ["Gemma", "model", "MLX"])]},
 {"num":"⑨","name":"画像・動画AI速報","env":"IMGVID","color":COL_FIELD,"sources":[
     # ★2026-09-05 実叩きで確定（⑩④は9/3に直したが⑨だけ限定語が残っていた）。
     #   現行 '(...) (発表 OR 公開 OR ...)' は Googleが生100件返すのに【48h窓に0件】。
     #   ★ただし限定語を外すだけでは駄目: Runway=ファッションのランウェイ6件 /
     #     Sora=ときのそら・空4件 / Flux=eスポーツ4件 と一般語衝突する → 固有名詞化する。
     #   ★21語を1本のORにまとめると Google の返却が 100→74件 に落ちる → 3本に割る。
     #   実測: 現行 0件 → 修正後 6件/48h（英語固有名詞2 + 日本語一般語3 + 新興モデル名1・ノイズ0）
     gn('"Stable Diffusion" OR Midjourney OR "Sora 2" OR "Runway Gen" OR RunwayML OR "Luma AI" OR "Pika Labs" OR "Flux.1" OR "Black Forest Labs"',
        include=IMGVID_TERMS, exclude=IMGVID_EXCLUDE),
     gn('"画像生成AI" OR "動画生成AI" OR "AI画像生成" OR "AI動画生成" OR "生成AI 動画"',
        include=IMGVID_TERMS, exclude=IMGVID_EXCLUDE),
     gn('Kling OR "Veo 3" OR Imagen OR Seedance OR Hailuo OR "nano banana" OR "Qwen-Image"',
        include=IMGVID_TERMS, exclude=IMGVID_EXCLUDE),
     rss("https://gigazine.net/news/rss_2.0/", include=IMGVID_TERMS, exclude=IMGVID_EXCLUDE),
     rss("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", include=IMGVID_TERMS, exclude=IMGVID_EXCLUDE),
     rss("https://hnrss.org/frontpage", include=IMGVID_TERMS, exclude=IMGVID_EXCLUDE)]},
 {"num":"⑩","name":"音声・音楽AI速報","env":"AUDIO","color":COL_FIELD,"sources":[
     # ★2026-09-03 実叩き: 後置の限定語(発表 OR 公開…)がANDで効き48h以内0件だった。外すと実測3件。
     #   新ソースは全滅(elevenlabs blog=404 / engadgetは"voice"の誤ヒット / reddit=429)のため追加しない。
     gn('ElevenLabs OR Suno OR Udio OR "音声生成AI" OR "音楽生成AI" OR "AI音声" OR "AI音楽" OR VOICEVOX -薬歴 -薬局 -医療 -銀行',
        include=AUDIO_TERMS, exclude=["Moomoo", "Marble", "Sakana", "薬歴", "薬局"]),
     rss("https://gigazine.net/news/rss_2.0/", include=AUDIO_TERMS),
     rss("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", include=AUDIO_TERMS),
     rss("https://hnrss.org/frontpage", include=AUDIO_TERMS)]},
 {"num":"⑪","name":"AIツール・エージェント速報","env":"TOOLS","color":COL_FIELD,"sources":[
     gn('("Claude Code" OR Codex OR Cursor OR n8n OR MCP OR LangChain OR Devin OR AIエージェント) (発表 OR 公開 OR 提供開始 OR 新機能 OR リリース OR 事例) -PR',
        include=TOOL_TERMS, exclude=["認定試験", "講座"]),
     rss("https://zenn.dev/topics/ai/feed", include=TOOL_TERMS),
     rss("https://hnrss.org/frontpage", include=TOOL_TERMS),
     rss("https://www.publickey1.jp/atom.xml", include=TOOL_TERMS),
     rss("https://cursor.com/changelog/rss.xml", include=["Cursor", "agent", "MCP"]),
     rss("https://blog.n8n.io/rss", include=["n8n", "AI", "agent", "workflow", "MCP"])]},
 {"num":"⑫","name":"論文速報","env":"PAPERS","color":COL_FIELD,"sources":[
     rss("http://export.arxiv.org/rss/cs.AI", include=PAPER_TERMS),
     rss("http://export.arxiv.org/rss/cs.CL", include=PAPER_TERMS),
     rss("https://hnrss.org/frontpage", include=PAPER_TERMS)]},
 # 🌐 総合 ⑬〜⑮
 {"num":"⑬","name":"AI最新速報（日本語）","env":"GENERAL","color":COL_SUM,"sources":[
     gn('(生成AI OR AIエージェント OR ChatGPT OR Claude OR Gemini OR ローカルLLM) (発表 OR 公開 OR 提供開始 OR 導入 OR 活用 OR 事例) -求人 -株価',
        include=["AI", "生成AI", "ChatGPT", "Claude", "Gemini", "LLM", "エージェント"]),
     rss("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml"),
     rss("https://gigazine.net/news/rss_2.0/", include=["AI","LLM","ChatGPT","Claude","Gemini","生成","OpenAI","Grok"]),
     rss("https://www.publickey1.jp/atom.xml", include=["AI","LLM","Claude","GPT","Copilot","生成","Gemini","エージェント"]),
     rss("https://zenn.dev/topics/ai/feed", include=["AI", "LLM", "ChatGPT", "Claude", "Gemini", "エージェント"])]},
 {"num":"⑭","name":"新モデルリリース速報","env":"RELEASE","color":COL_SUM,"sources":[
     gn('("新モデル" OR "モデル公開" OR "オープンウェイト" OR "提供開始" OR "generally available" OR "open weights") (OpenAI OR Anthropic OR Google OR Gemini OR Meta OR DeepSeek OR Qwen OR xAI OR Grok OR Mistral) -株 -決算 -Benchmark',
        include=MODEL_RELEASE_TERMS, exclude=["決算", "株", "ホールド評価", "限定公開", "グロービス", "学び放題", "政府が「待った」", "Межа", "Новини України"]),
     rss("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", include=MODEL_RELEASE_TERMS),
     rss("https://gigazine.net/news/rss_2.0/", include=MODEL_RELEASE_TERMS),
     rss("https://hnrss.org/frontpage", include=MODEL_RELEASE_TERMS)]},
 {"num":"⑮","name":"世界のAI動向・規制","env":"WORLD","color":COL_SUM,"sources":[
     gn('(AI規制 OR AI政策 OR AI法 OR AI著作権 OR "EU AI Act" OR "AI safety" OR "AI regulation" OR "AI export controls") (政府 OR EU OR 米国 OR 中国 OR 日本 OR 法案 OR 規制 OR policy OR regulation) -データセンター -イベント',
        include=POLICY_TERMS, exclude=["Data Center Japan", "出展", "展示会", "ライブ配信", "無料公開"]),
     rss("https://www3.nhk.or.jp/rss/news/cat6.xml", include=POLICY_TERMS + ["AI", "半導体", "中国", "米国"]),
     rss("https://www3.nhk.or.jp/rss/news/cat5.xml", include=POLICY_TERMS + ["AI", "半導体", "経済安全保障"]),
     rss("https://feeds.bbci.co.uk/news/world/rss.xml", include=POLICY_TERMS + ["AI", "semiconductor"]),
     rss("https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", include=POLICY_TERMS)]},
]

def gn_url(q):
    return "https://news.google.com/rss/search?q=" + urllib.parse.quote(q) + "&hl=ja&gl=JP&ceid=JP:ja"

def entry_epoch(e):
    # 記事の公開時刻(UTC epoch)。無ければNone。速報化(時刻ソート・時間窓)の心臓部。
    for k in ("published_parsed", "updated_parsed"):
        tm = e.get(k)
        if tm:
            try:
                return calendar.timegm(tm)
            except Exception:
                pass
    return None

def clean(t):
    t = re.sub(r"<[^>]+>", " ", t or "")
    t = t.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", t).strip()

def contains_any(text, terms):
    if not terms: return True
    low = text.lower()
    for term in terms:
        needle = str(term).lower()
        if not needle:
            continue
        if len(needle) <= 2 and needle.isascii() and needle.isalnum():
            if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", low):
                return True
            continue
        if needle in low:
            return True
    return False

def is_release_version_noise(title):
    t = title.strip()
    low = t.lower()
    if any(x.lower() in low for x in MODEL_RELEASE_TERMS + ["codex", "claude", "gemini", "grok", "llama", "qwen", "deepseek"]):
        return False
    return bool(re.fullmatch(r"v?\d+(\.\d+){1,4}([._-]?(alpha|beta|rc)\.?\d*)?", low) or low in {"stable", "nightly"})

def canonical_title(title):
    t = re.sub(r"\s+-\s+[^|]+(?:\s+\|.*)?$", "", title or "")
    t = re.sub(r"\s*\([^)]{2,50}\)\s*$", "", t)
    t = re.sub(r"\s*（[^）]{2,50}）\s*$", "", t)
    return re.sub(r"\s+", " ", t).strip().lower()

def title_from_url(url):
    path = urllib.parse.urlparse(url).path.strip("/")
    slug = path.split("/")[-1] if path else urllib.parse.urlparse(url).netloc
    slug = urllib.parse.unquote(slug)
    return re.sub(r"[-_]+", " ", slug).strip().title()

def fetch_sitemap(src):
    try:
        req = urllib.request.Request(src["url"], headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml = resp.read(500000).decode("utf-8", "replace")
    except Exception as e:
        print("    sitemap失敗:", src["url"][:50], e); return []
    include = src.get("include") or []
    exclude = GLOBAL_EXCLUDE + (src.get("exclude") or [])
    title_include = src.get("title_include") or []
    title_exclude = src.get("title_exclude") or []
    seen_titles = set()
    prefixes = src.get("path_prefix") or []
    entries = []
    for block in re.findall(r"<url>(.*?)</url>", xml, re.S):
        loc_m = re.search(r"<loc>(.*?)</loc>", block, re.S)
        if not loc_m: continue
        loc = clean(loc_m.group(1))
        parsed = urllib.parse.urlparse(loc)
        path = parsed.path or "/"
        if prefixes and not any(path.startswith(prefix) for prefix in prefixes): continue
        title = title_from_url(loc)
        lastmod_m = re.search(r"<lastmod>(.*?)</lastmod>", block, re.S)
        lastmod = clean(lastmod_m.group(1)) if lastmod_m else ""
        filter_text = " ".join([title, path])
        if title_include and not contains_any(title, title_include): continue
        if title_exclude and contains_any(title, title_exclude): continue
        if include and not contains_any(filter_text, include): continue
        if exclude and contains_any(filter_text, exclude): continue
        summ = f"official page updated: {lastmod[:10]}" if lastmod else ""
        entries.append((lastmod, title, loc, summ, src.get("label") or parsed.netloc))
    entries.sort(key=lambda x: x[0], reverse=True)
    return [(title, loc, summ, label) for lastmod, title, loc, summ, label in entries[:PER_SOURCE]]

# ---- 日本語化（英語タイトル/要約をGoogle翻訳で和訳・失敗時は原文＝重要ニュースは英語でも可）----
# ★deep_translator(内部でrequests使用)はライブラリ側にtimeoutを渡す口が無く、
#   GitHub Actionsのクラウド側IPからだと接続がハングして戻ってこないことがある
#   （ローカルでは問題なくAction上でだけ無限待ちした実例2026-07-08）。
#   スレッド+timeoutで包んでも、ワーカースレッド自体が本当にハングした場合は
#   Pythonプロセス終了時のスレッドjoin待ちで結局終わらない恐れがある。
#   なので外部ライブラリを経由せず urllib.request.urlopen(timeout=...) で
#   Google翻訳の非公式エンドポイントを直接叩く＝ソケットレベルの本物のタイムアウトにする。
_JP_RE = re.compile(r"[ぁ-んァ-ヶ一-龠]")
_TR_TIMEOUT_SEC = 8
_TR_MAX_FAIL = 3          # 1エンジンがこの回数連続で失敗したら、そのエンジンだけ以後スキップ(他は生かす)

def is_ja(t):
    if not t: return True
    return len(_JP_RE.findall(t)) >= max(3, int(len(t) * 0.12))   # 既に日本語なら翻訳しない

# ---- 翻訳（★GIT内で完結。外部の翻訳APIサービスを実行時に一切叩かない）----
# 2026-09-03 Hikârư制約: 「GIT+Discord完結」。外部翻訳API(Google非公式/MyMemory/Gemini等)は使わない。
#   旧実装は Google翻訳の非公式endpointを叩いていたが、GitHub ActionsのIPから弾かれ
#   (ログ実物「翻訳サーバー応答なし(6s×3回連続) → 以後は原文のまま投稿」)、
#   実機で英語のまま98件・論文は21件中14件が未翻訳という状態を作っていた。
#   → argostranslate(CTranslate2ベース)でrunner内ローカル推論に変更。
#     実測: モデル準備10.9s、翻訳は1件目7.1s(ロード込)、2件目以降 0.06〜0.10s。
_ARGOS = None   # None=未初期化 / True=使える / False=使えない

def _argos_ready():
    global _ARGOS
    if _ARGOS is not None:
        return _ARGOS
    try:
        import argostranslate.package as P
        import argostranslate.translate as T
        codes = {l.code for l in T.get_installed_languages()}
        if not ("en" in codes and "ja" in codes):
            P.update_package_index()
            pkgs = [p for p in P.get_available_packages()
                    if p.from_code == "en" and p.to_code == "ja"]
            if not pkgs:
                print("    argostranslate: en->ja パッケージが見つからない")
                _ARGOS = False
                return _ARGOS
            P.install_from_path(pkgs[0].download())
        _ARGOS = True
    except Exception as e:
        print(f"    argostranslate 準備失敗: {type(e).__name__}: {str(e)[:80]}")
        _ARGOS = False
    return _ARGOS

def to_ja(t):
    """英文を日本語へ。runner内のローカル推論のみを使い、外部APIは叩かない。
       失敗時は原文のまま返す(重要ニュースは英語でも出す)。"""
    if not t or is_ja(t):
        return t
    if not _argos_ready():
        return t
    try:
        import argostranslate.translate as T
        out = T.translate(t[:1500], "en", "ja")
        return out if (out and is_ja(out)) else t
    except Exception:
        return t

def load_webhooks():
    m = {}
    for k, v in os.environ.items():
        if k.startswith("DISCORD_AILAB_WEBHOOK_"):
            m[k.replace("DISCORD_AILAB_WEBHOOK_", "")] = v
    if not m and os.path.exists(WEBHOOKS_JSON):
        for r in json.load(io.open(WEBHOOKS_JSON, encoding="utf-8")):
            if r.get("webhook_url"):
                m[r["env"].replace("DISCORD_AILAB_WEBHOOK_", "")] = r["webhook_url"]
    return m

def load_seen():
    try: return set(json.load(io.open(SEEN_FILE, encoding="utf-8")))
    except Exception: return set()

def save_seen(s):
    io.open(SEEN_FILE, "w", encoding="utf-8").write(json.dumps(sorted(s), ensure_ascii=False))

def fetch(src):
    if src["type"] == "sitemap":
        return fetch_sitemap(src)
    url = gn_url(src["q"]) if src["type"] == "gn" else src["url"]
    try:
        f = feedparser.parse(url)
    except Exception as e:
        print("    fetch失敗:", url[:50], e); return []
    feed_label = clean((f.feed.get("title", "") if getattr(f, "feed", None) else "")) or urllib.parse.urlparse(url).netloc
    include = src.get("include") or src.get("must") or []
    exclude = GLOBAL_EXCLUDE + (src.get("exclude") or [])
    title_include = src.get("title_include") or []
    title_exclude = src.get("title_exclude") or []
    # ★速報化: 全エントリを公開時刻で新しい順にソート(先頭 f.entries[:PER_SOURCE*5] 固定を廃止)。
    #          時刻が取れないものは後ろに回す(フィード順)。
    dated = [(entry_epoch(e), e) for e in (getattr(f, "entries", []) or [])]
    dated.sort(key=lambda x: (x[0] is not None, x[0] or 0.0), reverse=True)
    out = []
    seen_titles = set()
    for ts, e in dated:
        # ★時間窓: 公開時刻が分かるものは直近 FRESH_HOURS 時間だけを速報として通す。古いものは捨てる。
        if ts is not None and (NOW - ts) > FRESH_HOURS * 3600:
            continue
        title = clean(e.get("title", ""))
        if not title: continue
        summ = clean(e.get("summary", "") or e.get("description", ""))
        entry_source = e.get("source", {})
        if isinstance(entry_source, dict):
            entry_source = clean(entry_source.get("title", ""))
        else:
            entry_source = ""
        filter_text = " ".join([title, summ, entry_source])
        if is_release_version_noise(title): continue
        title_key = canonical_title(title)
        if title_key in seen_titles: continue
        if title_include and not contains_any(title, title_include): continue
        if title_exclude and contains_any(title, title_exclude): continue
        if include and not contains_any(filter_text, include): continue
        if exclude and contains_any(filter_text, exclude): continue
        seen_titles.add(title_key)
        if len(summ) < 25 or summ[:18] == title[:18]: summ = ""
        summ = summ[:160] + ("…" if len(summ) > 160 else "")
        out.append((title, e.get("link", ""), summ, src.get("label") or entry_source or feed_label))
        if len(out) >= PER_SOURCE: break
    return out

def collect_topic_items(t, seen, sleep_sec=0.4):
    source_hits = []
    keys = set()
    for src in t["sources"]:
        rows = []
        for title, link, summ, srclabel in fetch(src):
            title_key = canonical_title(title)
            # ★2026-09-05 実測: Google Newsは同じ記事に【URLを3種類】振ってくる。
            #   seenがlinkしか持っていなかったため、同じ記事が媒体違いで何度も流れていた。
            #   実測(直近100件×15CH): URLだけ=121件しか止まらない / タイトルも見る=256件(+135)。
            #   誤爆の確認: 同じキーで原文が違った81組は【全部が媒体名の違いだけ】=同じ記事。
            #              12字未満の短いキーで重複扱いになったのは1組のみ(それも原文1種類)。
            if (not link or link in seen or title_key in seen
                    or link in keys or title_key in keys):
                continue
            keys.add(link)
            keys.add(title_key)
            rows.append((title, link, summ, srclabel))
        if rows:
            source_hits.append(rows)
        if sleep_sec:
            time.sleep(sleep_sec)

    picked = []
    picked_keys = set()
    def add_item(item):
        key = item[1] or canonical_title(item[0])
        if key in picked_keys:
            return
        picked_keys.add(key)
        picked.append(item)

    # Google Newsだけで枠を埋めない。朝活方式として、実証済み母体を分類別に混ぜる。
    for rows in source_hits:
        if len(picked) >= PER_CHANNEL:
            break
        add_item(rows[0])

    if len(picked) < PER_CHANNEL:
        for rows in source_hits:
            for item in rows[1:]:
                if len(picked) >= PER_CHANNEL:
                    break
                add_item(item)
            if len(picked) >= PER_CHANNEL:
                break
    return picked[:PER_CHANNEL]

def post(url, header, items, color):
    embeds = []
    for title, link, summ, src in items:
        emb = {"title": title[:250], "url": link, "color": color, "footer": {"text": src[:100]}}
        if summ: emb["description"] = summ
        embeds.append(emb)
    body = {"content": header, "embeds": embeds[:10]}
    r = urllib.request.Request(url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": UA}, method="POST")
    # ★2026-09-03: 旧実装は while True で429を無限リトライしており、Discord側のレート制限が
    #   続くと run が終わらなくなる(実測: 1runが16分以上 in_progress のまま残り、concurrencyで
    #   後続の【自動起動run】が cancelled になった＝自動配信が殺された)。
    #   リトライ回数・1回の待ち・累計待ちの3つに上限を入れて必ず抜ける。
    MAX_RETRY = 5
    total_wait = 0.0
    for attempt in range(MAX_RETRY):
        try:
            with urllib.request.urlopen(r, timeout=20) as x: return x.status
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try: retry = float(json.loads(e.read()).get("retry_after", 1.0))
                except Exception: retry = 1.0
                retry = min(retry, 10.0)                      # 1回の待ちの上限
                total_wait += retry + 0.3
                if attempt >= MAX_RETRY - 1 or total_wait > 30:
                    return f"429:give_up(try{attempt+1},wait{total_wait:.0f}s)"
                time.sleep(retry + 0.3); continue
            return f"{e.code}:{e.read().decode('utf-8','replace')[:120]}"
        except Exception as e:
            return f"ERR:{type(e).__name__}"
    return "429:give_up"

def main():
    hooks = load_webhooks(); seen = load_seen()
    print(f"webhooks={len(hooks)} seen={len(seen)} topics={len(TOPICS)}")
    for t in TOPICS:
        url = hooks.get(t["env"])
        if not url:
            print(f"{t['num']} {t['name']} … webhook未設定スキップ"); continue
        picked = collect_topic_items(t, seen)
        if not picked:
            print(f"{t['num']} {t['name']} … 新規なし"); continue
        # ★翻訳の【前】のキーを先に取る。to_ja後に取ると日本語で保存して英語で照合するズレが出る。
        keys_before = [canonical_title(ti) for (ti, _, _, _) in picked]
        picked = [(to_ja(ti), li, to_ja(su), sr) for (ti, li, su, sr) in picked]  # 英語→日本語（失敗時は原文）
        st = post(url, f"**{t['num']}｜{t['name']}**", picked, t["color"])
        for (ti, link, _, _), k0 in zip(picked, keys_before):
            seen.add(link)
            seen.add(k0)                      # ★翻訳前（同じ英語記事が別フィードから来た時に効く）
            seen.add(canonical_title(ti))     # ★翻訳後（Discordに実際に出ている形と一致させる）
        print(f"{t['num']} {t['name']} … {len(picked)}件 ({st})")
        time.sleep(1.3)
    save_seen(seen); print("seen保存:", len(seen))

if __name__ == "__main__":
    main()
