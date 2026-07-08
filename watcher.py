#!/usr/bin/env python3
"""どのサイトでも使える汎用「入荷ウォッチャー」基底クラス。

使い方:
  1. Watcher を継承したサブクラスを作る
  2. クラス属性 (slug / display / ascii_title / url ...) を設定する
  3. find_items(html) をオーバーライドし、
     「対象が存在する / 在庫があるときだけ」その項目を返すよう実装する
  これだけで、取得・状態管理・二重通知防止・メール/ntfy通知は基底が面倒を見る。

find_items が返すのは {一意キー: 詳細URL} の dict。
  - 空 dict          -> まだ登場していない（通知しない）
  - 新規キーあり     -> その項目だけメール & ntfy 通知して state に記録
  - 既知キーのみ     -> 通知しない（同じ商品で繰り返さない）
状態は state_<slug>.json に保存される（サイトごとに独立）。
"""

import json
import os
import smtplib
import urllib.request
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class Watcher:
    """入荷ウォッチャーの基底クラス。サイトごとに継承して使う。"""

    # ---- サブクラスで必ず設定する属性 --------------------------------------
    slug: str = "watcher"          # 状態ファイル名/ターゲットID（英数字とハイフン）
    display: str = "ウォッチャー"   # 通知本文の見出し（日本語OK）
    ascii_title: str = "Watcher alert"  # ntfy の Title（★ASCIIのみ。日本語不可）
    url: str = ""                  # 監視ページ / 通知クリック先URL
    from_name: str = "Site Watcher"  # メール差出人の表示名
    emoji_tag: str = "tada"        # ntfy のアイコン絵文字タグ

    # 通知の繰り返し方:
    #   True  … 一度検知したら二度と通知しない（例: Apple整備済の初登場）
    #   False … 在庫が切れて復活したら再通知する（例: モンベルの再入荷監視）
    sticky_state: bool = True

    # ---- サブクラスでオーバーライドするメソッド ----------------------------
    def find_items(self, html: str) -> dict[str, str]:
        """監視対象を {一意キー: 詳細URL} で返す。存在するものだけ入れる。

        「まだ無い」なら空 dict を返す。ここがサイトごとの唯一の違い。
        """
        raise NotImplementedError

    def describe(self, key: str, url: str) -> str:
        """通知本文に出す1行の表示名。既定はURLをそのまま。必要なら整形。"""
        return url

    @property
    def fetch_url(self) -> str:
        """取得するURL。クリック先(url)と別ページを見たい場合だけ上書き。"""
        return self.url

    def headers(self) -> dict[str, str]:
        return {"User-Agent": DEFAULT_UA, "Accept-Language": "ja-JP,ja"}

    # ---- 共通処理（通常オーバーライド不要） --------------------------------
    def fetch(self) -> str:
        req = urllib.request.Request(self.fetch_url, headers=self.headers())
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def _state_file(self) -> Path:
        return Path(__file__).with_name(f"state_{self.slug}.json")

    def load_state(self) -> set[str]:
        f = self._state_file()
        if f.exists():
            try:
                return set(json.loads(f.read_text()).get("notified_keys", []))
            except Exception:
                return set()
        return set()

    def save_state(self, keys: set[str]) -> None:
        self._state_file().write_text(
            json.dumps({"notified_keys": sorted(keys)}, ensure_ascii=False, indent=2)
        )

    def _body_lines(self, items: dict[str, str]) -> list[str]:
        lines: list[str] = []
        for key, url in sorted(items.items()):
            lines.append(f"● {self.describe(key, url)}")
            lines.append(f"  {url}")
        return lines

    def send_email(self, items: dict[str, str]) -> None:
        sender = os.environ["GMAIL_ADDRESS"]
        password = os.environ["GMAIL_APP_PASSWORD"]
        recipient = os.environ.get("NOTIFY_TO", sender)

        body = "\n".join(
            [f"{self.display} を検知しました！\n", *self._body_lines(items), "", self.url]
        )
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = f"🎉 {self.display}"
        msg["From"] = formataddr((self.from_name, sender))
        msg["To"] = recipient

        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        print(f"メール送信済み -> {recipient}")

    def send_ntfy(self, items: dict[str, str]) -> None:
        """ntfy.sh へスマホプッシュ。NTFY_TOPIC 未設定なら何もしない。"""
        topic = os.environ.get("NTFY_TOPIC", "").strip()
        if not topic:
            return
        server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")

        body = "\n".join([f"{self.display}\n", *self._body_lines(items)])
        # HTTPヘッダはASCIIのみ。日本語は body へ、Title には ascii_title を使う。
        req = urllib.request.Request(
            f"{server}/{topic}",
            data=body.encode("utf-8"),
            headers={
                "Title": self.ascii_title,
                "Priority": "urgent",
                "Tags": self.emoji_tag,
                "Click": self.url,
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20):
            pass
        print("ntfy通知送信済み")

    def notify(self, items: dict[str, str]) -> None:
        """メールと ntfy を独立に送る（片方失敗でももう片方は送る）。"""
        for name, fn in (("email", self.send_email), ("ntfy", self.send_ntfy)):
            try:
                fn(items)
            except Exception as e:  # noqa: BLE001
                print(f"[warn] {name} 通知失敗: {e}")

    def run(self) -> int:
        html = self.fetch()
        found = self.find_items(html)
        print(f"[{self.slug}] 検知: {len(found)} 件")

        already = self.load_state()
        new_items = {k: u for k, u in found.items() if k not in already}

        if new_items:
            for key, url in new_items.items():
                print(f"新着: {key} {url}")
            self.notify(new_items)
        elif not found:
            print("まだ登場していません。")
        else:
            print("既に通知済みの項目のみ。通知しません。")

        # 状態更新:
        #   sticky   … 累積（消えても記録を残し、二度と通知しない）
        #   非sticky … 現在ある物だけを残す（消えた項目は忘れ、復活時に再通知）
        self.save_state((already | set(found)) if self.sticky_state else set(found))
        return 0
