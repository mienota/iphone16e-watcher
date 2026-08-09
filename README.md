# 入荷ウォッチャー（汎用）

任意のサイトを定期チェックし、狙いの商品が **登場 / 再入荷** したらメールとスマホプッシュ（ntfy）で通知します。GitHub Actions 上で無料で動きます。

現在の監視対象:

| ターゲット | 監視先 | 何を検知するか | 通知 |
|---|---|---|---|
| `apple-16e` | [Apple 整備済製品ストア](https://www.apple.com/jp/shop/refurbished/iphone) | iPhone 16e の初登場 | 一回きり |
| `montbell` | [モンベル webshop](https://webshop.montbell.jp/goods/disp.php?product_id=1101606) | ライトアルパインダウン パーカ Men's **BK×XL** の再入荷 | 復活のたび |

### 実運用上の注意

- **GitHub Actions のスケジュールは当てにならない。** cron は `*/10` だが実測は平均1.7時間に1回まで間引かれる（混雑時にキューが捨てられるため）。数日の猶予がある入荷には十分間に合うが、**数秒で消える争奪戦には使えない**。
- **サイト側のブロックは一時的なことがある。** モンベルは 2026-08-08 に runner から 60 秒タイムアウト（ローカルは 0.4 秒）で「IPレベルで遮断された」と判断したが、**翌日には 1.8 秒で普通に取れた**。プロキシを立てる前に日を改めて試すこと。
- **「0件」と「取得失敗」を必ず区別する。** ブロックページを掴んでも各 `find_items()` は素直に0件を返すので、放っておくと「完売」と誤報し続ける。在庫を見る系のクラスは、商品ページなら必ずあるはずの要素（モンベルなら `<SIZE>_<COLOR>_num` の数量セレクト）が1つも無ければ例外で落とすようにしてある。
- 失敗したターゲットがあっても、ワークフローは残りを続行する。

## 仕組み（クラスをオーバーライドして汎用化）

サイト共通の処理（取得・状態管理・二重通知防止・メール/ntfy送信）は基底クラス `Watcher`（[`watcher.py`](watcher.py)）に集約。サイトごとに違うのは「**何を在庫ありと見なすか**」だけなので、そこを `find_items()` のオーバーライドで差し込みます。

```
watcher.py   … 基底クラス Watcher（共通処理。基本いじらない）
targets.py   … サイト別サブクラス＋レジストリ TARGETS
               ├ AppleRefurbWatcher … 整備済ストアに指定モデルが並んだか
               └ MontbellWatcher   … 指定カラー×サイズの在庫があるか
check.py     … エントリ。WATCH_TARGET で対象を選んで run() するだけ
state_<slug>.json … 通知済みキーの記録（サイトごとに独立。Actionsが自動コミット）
```

`find_items(html)` は「**今ある対象だけ**」を `{一意キー: URL}` で返す約束。空なら未登場。あとは基底が差分を取り、新規キーだけ通知します。

`sticky_state` で通知の繰り返し方を切り替えます:
- `True`（Apple）… 一度検知したら二度と通知しない（登場イベント向け）
- `False`（モンベル）… 在庫が切れて復活したら再通知する（再入荷監視向け）

### 新しいサイトを足す

1. `targets.py` に `Watcher` を継承したクラスを書き、`find_items()` を実装:

```python
from watcher import Watcher
import re

class MyShopWatcher(Watcher):
    slug = "myshop-sku123"                 # state ファイル名になる（英数字-）
    display = "MyShop の SKU123 が入荷"      # 通知本文の見出し（日本語OK）
    ascii_title = "MyShop SKU123 in stock!" # ntfy の Title（★ASCIIのみ）
    url = "https://example.com/item/123"    # 監視ページ兼クリック先
    sticky_state = False                    # 再入荷監視なら False

    def find_items(self, html: str) -> dict[str, str]:
        # 在庫ありのときだけ {キー: URL} を返す。無ければ {} 。
        return {"sku123": self.url} if "在庫あり" in html else {}
```

2. `targets.py` の `TARGETS` に登録:

```python
TARGETS = {
    "apple-16e": lambda: AppleRefurbWatcher("16e"),
    "montbell":  lambda: MontbellWatcher(),
    "myshop":    lambda: MyShopWatcher(),   # 追加
}
```

3. `.github/workflows/watch.yml` の `targets="${INPUT_TARGET:-apple-16e montbell}"` に `myshop` を足す。

必要に応じて `describe()`（本文の1行表示）、`fetch_url`（監視ページと取得ページが別なとき）、`headers()` もオーバーライドできます。

## セットアップ

### 1. GitHub に置く
```bash
cd iphone16e-watcher
git init
git add .
git commit -m "generic stock watcher"
gh repo create iphone16e-watcher --public --source=. --push
```
> **public 推奨**。Actions が無制限無料になります（後述）。

### 2. Gmail アプリパスワードを作成
1. Google アカウントで 2 段階認証を有効化
2. https://myaccount.google.com/apppasswords で 16 桁のアプリパスワードを発行

### 3. GitHub にシークレットを登録
リポジトリの Settings → Secrets and variables → Actions → New repository secret:

| 名前 | 値 | 必須 |
|------|-----|------|
| `GMAIL_ADDRESS` | 送信元 Gmail アドレス | ○ |
| `GMAIL_APP_PASSWORD` | 発行した 16 桁アプリパスワード | ○ |
| `NOTIFY_TO` | 通知先アドレス（省略時は送信元と同じ） | 任意 |
| `NTFY_TOPIC` | ntfy.sh のトピック名（スマホプッシュ用） | 任意 |
| `NTFY_SERVER` | 自前 ntfy サーバのURL（省略時は `https://ntfy.sh`） | 任意 |

CLI なら（値は自分のものに置換）:
```bash
gh secret set GMAIL_ADDRESS --body "you@gmail.com"
gh secret set GMAIL_APP_PASSWORD --body "xxxxxxxxxxxxxxxx"
gh secret set NOTIFY_TO --body "you@gmail.com"
gh secret set NTFY_TOPIC --body "your-secret-topic-name"
```
> 秘密情報はコードに書かず、必ず GitHub Secrets に。この public リポジトリには一切含めない。

## スマホプッシュ通知（ntfy）の設定

[ntfy.sh](https://ntfy.sh) は「トピック名（＝合言葉のURL）」に POST された内容を、そのトピックを購読している端末へ即プッシュする無料サービス。**アカウント登録も API キーも不要**で、トピック名さえ知っていれば誰でも送受信できます。

### 手順
1. **スマホに ntfy アプリを入れる**
   - iOS: App Store で「ntfy」
   - Android: Google Play か [F-Droid](https://f-droid.org/packages/io.heckel.ntfy/)
2. **トピック名を決める**
   - 誰でも購読できてしまうので、**推測されにくい長い文字列**にする
     （例: `montbell-restock-8f3k9x2q`）。短い名前は他人に覗かれる/送られる恐れあり。
3. **アプリでそのトピックを購読（Subscribe）** … 「＋」→ トピック名を入力
4. **同じトピック名を GitHub Secret `NTFY_TOPIC` に登録**（上の手順3）
5. これで在庫検知時に、音付き・緊急優先度（urgent）のプッシュがスマホに届く。
   通知をタップすると商品ページが開きます。

### 動作テスト
アプリで購読できたか確認するには、手元から直接投げてみるのが早い:
```bash
curl -d "テスト通知です" ntfy.sh/your-secret-topic-name
```
スマホに届けば購読設定はOK。

### 補足
- `NTFY_TOPIC` を **設定しなければ ntfy はスキップ**され、メール通知だけ動く。
- Title ヘッダは ASCII のみ対応なので、各 Watcher の `ascii_title`（英語）を使い、
  日本語の詳細は本文に載せています（`watcher.py` の `send_ntfy` 参照）。
- プライバシーを気にするなら `NTFY_SERVER` に自前サーバ（Docker で立てられる）を指定可。

## 手動実行 / ローカルテスト

GitHub 上: Actions タブ → "Stock watchers" → Run workflow。
`target` 欄に `apple-15-plus` など在庫のあるものを入れると通知経路のテストになる。

ローカル:
```bash
# モンベル（BK×XL が在庫あれば通知。通常は完売中で0件）
WATCH_TARGET=montbell python check.py

# Apple（在庫のある型番で通知経路をテスト）
WATCH_TARGET=apple-15-plus GMAIL_ADDRESS=you@gmail.com \
  GMAIL_APP_PASSWORD=xxxx NOTIFY_TO=you@gmail.com NTFY_TOPIC=your-topic \
  python check.py
```

## 費用
**public リポジトリなら GitHub Actions は無制限で無料**（10分ごとでもOK）。
private だと無料枠 2,000 分/月・1回 = 最低 1 分課金なので、10分ごと（月約 4,320 分）は超過する点に注意。
Gmail 送信・ntfy も無料。
