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

| 名前 | 値 |
|------|-----|
| `GMAIL_ADDRESS` | 送信元Gmailアドレス |
| `GMAIL_APP_PASSWORD` | 発行した16桁アプリパスワード |
| `NOTIFY_TO` | 通知先アドレス（省略時は送信元と同じ） |

CLIなら:
```bash
gh secret set GMAIL_ADDRESS --body "you@gmail.com"
gh secret set GMAIL_APP_PASSWORD --body "xxxxxxxxxxxxxxxx"
gh secret set NOTIFY_TO --body "mieno.tk0909@gmail.com"
```

### 4. 動作確認
Actions タブ → "Watch iPhone 16e refurbished" → Run workflow で手動実行。

## ローカルテスト
```bash
GMAIL_ADDRESS=you@gmail.com GMAIL_APP_PASSWORD=xxxx NOTIFY_TO=you@gmail.com python check.py
```

## 費用
GitHub Actions はパブリック/プライベート問わず**個人の無料枠内**（30分ごと=月約1,440分、
1回数十秒なので月数十分程度）で収まります。Gmail送信も無料。
