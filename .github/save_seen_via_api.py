# -*- coding: utf-8 -*-
"""
git push が通らなかった時に呼ばれる【別経路】。

★なぜ別経路が要るか（2026-09-05 実測）
  git push が死んだ原因は2つで、どちらも「作業ツリーとブランチ」に紐づいている:
    ① actions/checkout がブランチ先端でないSHAを取ると detached HEAD になり
       "fatal: You are not currently on a branch." で push できない
    ② その状態で git pull --rebase すると seen が単一行JSONなので必ず衝突し
       "Exiting because of an unresolved conflict." で以後すべて失敗する
  → Contents API は作業ツリーもブランチも使わないので、①②のどちらにも当たらない。
    ＝「同じ穴に落ちないルート」

★なぜ exit 1 で落とさないか
  同一リポの複数workflowが push で衝突して job failure になり、
  GitHubのエラーメールが連続した事故が 2026-07-30 / 2026-07-31 に起きている。
  落とすとその通知地獄を呼び戻すので、落とさずに別経路で通す。

★衝突しない理由
  rebase しない。毎回「リモートの今の中身」を取り直して和集合にしてから書く。
  409(sha不一致)が返ったら、取り直して同じことをやり直すだけ。
"""
import io, json, os, sys, time, base64, urllib.request, urllib.error

REPO = os.environ.get('GITHUB_REPOSITORY', '')
TOKEN = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN') or ''
PATH = 'ailab_seen_urls.json'
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCAL = os.path.join(HERE, PATH)


def api(method, url, body=None):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode('utf-8') if body else None, method=method,
        headers={'Authorization': 'token ' + TOKEN,
                 'Accept': 'application/vnd.github+json',
                 'Content-Type': 'application/json',
                 'User-Agent': 'ailab-news-bot'})
    with urllib.request.urlopen(req, timeout=60) as x:
        return json.loads(x.read().decode('utf-8')), x.status


def main():
    if not REPO or not TOKEN:
        print('別経路: GITHUB_REPOSITORY / トークンが無いので何もしない')
        return 0
    try:
        mine = set(json.load(io.open(LOCAL, encoding='utf-8')))
    except Exception as e:
        print(f'別経路: ローカルの {PATH} が読めない({type(e).__name__})ので何もしない')
        return 0
    base = f'https://api.github.com/repos/{REPO}/contents/{PATH}'

    for attempt in range(1, 6):
        try:
            cur, _ = api('GET', base)
            remote = set(json.loads(base64.b64decode(cur['content']).decode('utf-8')))
            sha = cur['sha']
        except Exception as e:
            print(f'別経路: 取得失敗 {type(e).__name__} (試行{attempt})')
            time.sleep(2 * attempt)
            continue

        merged = remote | mine
        if merged == remote:
            print(f'別経路: 追加ぶんは既にリモートに在る（{len(remote)}件）。何もしない')
            return 0

        payload = json.dumps(sorted(merged), ensure_ascii=False)
        try:
            res, _ = api('PUT', base, {
                'message': 'chore: update ailab_seen_urls.json (via Contents API fallback)',
                'content': base64.b64encode(payload.encode('utf-8')).decode('ascii'),
                'sha': sha, 'branch': 'main'})
            print(f'★別経路で保存した: {len(remote)} → {len(merged)}件 '
                  f'(+{len(merged)-len(remote)})  commit {res["commit"]["sha"][:7]}')
            return 0
        except urllib.error.HTTPError as e:
            if e.code == 409:
                print(f'別経路: 409（他が先に書いた）→ 取り直してやり直す (試行{attempt})')
                time.sleep(2 * attempt)
                continue
            print(f'別経路: PUT失敗 {e.code} (試行{attempt})')
            time.sleep(2 * attempt)
        except Exception as e:
            print(f'別経路: PUT例外 {type(e).__name__} (試行{attempt})')
            time.sleep(2 * attempt)

    print('::warning::別経路でも保存できなかった。次回の実行で重複が出る可能性がある')
    return 0        # ★落とさない（メール通知を呼び戻さないため）


if __name__ == '__main__':
    sys.exit(main())
