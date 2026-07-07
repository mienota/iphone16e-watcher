# iPhone 16e 整備済製品ウォッチャー

Apple 日本の[整備済製品ストア](https://www.apple.com/jp/shop/refurbished/iphone)を
30分ごとにチェックし、**iPhone 16e** が登場したらメールで通知します。GitHub Actions 上で無料で動きます。

## 仕組み
- `check.py` がページを取得し、商品タイル URL (`.../product/<code>/a/iphone-16e-...`) を探す
- 見つかったらメール送信し、`state.json` に商品コードを記録（同じ商品で二重通知しない）
- GitHub Actions が `.github/workflows/watch.yml` の cron で定期実行

## セットアップ

### 1. GitHubに置く
```bash
cd iphone16e-watcher
git init
git add .
git commit -m "iPhone 16e watcher"
gh repo create iphone16e-watcher --private --source=. --push
```

### 2. Gmailアプリパスワードを作成
1. Googleアカウントで2段階認証を有効化
2. https://myaccount.google.com/apppasswords で16桁のアプリパスワードを発行

### 3. GitHubにシークレットを登録
リポジトリの Settings → Secrets and variables → Actions → New repository secret：

| 名前 | 値 | 必須 |
|------|-----|------|
| `GMAIL_ADDRESS` | 送信元Gmailアドレス | ○ |
| `GMAIL_APP_PASSWORD` | 発行した16桁アプリパスワード | ○ |
| `NOTIFY_TO` | 通知先アドレス（省略時は送信元と同じ） | 任意 |
| `NTFY_TOPIC` | ntfy.sh のトピック名（スマホプッシュ用） | 任意 |

CLIなら（値はダミー、自分のものに置換）:
```bash
gh secret set GMAIL_ADDRESS --body "you@gmail.com"
gh secret set GMAIL_APP_PASSWORD --body "xxxxxxxxxxxxxxxx"
gh secret set NOTIFY_TO --body "you@gmail.com"
gh secret set NTFY_TOPIC --body "your-secret-topic"
```

> 秘密情報はコードに書かず、必ず GitHub Secrets に入れること。この公開リポジトリには一切含めない。

### 4. スマホプッシュ（ntfy）
1. スマホに **ntfy** アプリ（iOS/Android）をインストール
2. `NTFY_TOPIC` に設定したトピック名を購読
3. 16e登場時に音付きの緊急プッシュが届く

### 5. 動作確認
Actions タブ → "Watch iPhone 16e refurbished" → Run workflow で手動実行。
`model` に `15-plus` など在庫のあるモデルを入れると通知経路のテストになる。

## ローカルテスト
```bash
WATCH_MODEL=15-plus GMAIL_ADDRESS=you@gmail.com GMAIL_APP_PASSWORD=xxxx \
  NOTIFY_TO=you@gmail.com NTFY_TOPIC=your-topic python check.py
```

## 費用
**publicリポジトリなら GitHub Actions は無制限で無料**（10分ごとでもOK）。
privateだと無料枠2,000分/月・1回=最低1分課金なので、10分ごと(月約4,320分)は超過する点に注意。
Gmail送信・ntfyも無料。
