#!/usr/bin/env python3
"""Apple 日本の整備済製品ストアを監視し、iPhone 16e が登場したらメール通知する。

判定方法:
  ページ内の商品タイル URL ( /jp/shop/product/<code>/a/iphone-16e-... ) を探す。
  これは「実際に購入できる商品」が存在するときだけ現れる。
  左サイドのフィルタ定義 ("iphone16e":{...}) は全機種の分類表であり
  在庫とは無関係なので使わない。

state.json に通知済みの商品コードを記録し、同じ商品で繰り返しメールしない。
"""

import json
import os
import re
import smtplib
import sys
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.utils import formataddr
from pathlib import Path

REFURB_URL = "https://www.apple.com/jp/shop/refurbished/iphone"
STATE_FILE = Path(__file__).with_name("state.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# /jp/shop/product/<code>/a/iphone-16e-... の形の商品タイルURLを拾う
TILE_RE = re.compile(r"/jp/shop/product/[a-z0-9]+/a/iphone-16e[^\"'\s]*", re.IGNORECASE)


def fetch_html() -> str:
    req = urllib.request.Request(REFURB_URL, headers={"User-Agent": UA, "Accept-Language": "ja-JP,ja"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def find_16e(html: str) -> dict[str, str]:
    """{商品コード: フルURL} を返す。"""
    found: dict[str, str] = {}
    for path in TILE_RE.findall(html):
        path = urllib.parse.unquote(path)
        m = re.search(r"/product/([a-z0-9]+)/", path)
        code = m.group(1) if m else path
        found[code] = "https://www.apple.com" + path
    return found


def load_state() -> set[str]:
    if STATE_FILE.exists():
        try:
            return set(json.loads(STATE_FILE.read_text()).get("notified_codes", []))
        except Exception:
            return set()
    return set()


def save_state(codes: set[str]) -> None:
    STATE_FILE.write_text(json.dumps({"notified_codes": sorted(codes)}, ensure_ascii=False, indent=2))


def slug_to_name(url: str) -> str:
    slug = url.rsplit("/a/", 1)[-1]
    return slug.replace("-", " ")


def send_email(new_items: dict[str, str]) -> None:
    sender = os.environ["GMAIL_ADDRESS"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ.get("NOTIFY_TO", sender)

    lines = ["Apple 整備済製品ストアに iPhone 16e が登場しました！\n"]
    for code, url in sorted(new_items.items()):
        lines.append(f"● {slug_to_name(url)}")
        lines.append(f"  {url}\n")
    lines.append("整備済製品ストア一覧:")
    lines.append(REFURB_URL)
    body = "\n".join(lines)

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = "🎉 iPhone 16e が整備済製品ストアに登場！"
    msg["From"] = formataddr(("iPhone 16e Watcher", sender))
    msg["To"] = recipient

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)
    print(f"メール送信済み -> {recipient}")


def main() -> int:
    html = fetch_html()
    found = find_16e(html)
    print(f"iPhone 16e 商品タイル: {len(found)} 件")

    if not found:
        print("まだ登場していません。")
        return 0

    already = load_state()
    new_items = {c: u for c, u in found.items() if c not in already}

    if not new_items:
        print("既に通知済みの商品のみ。メールは送りません。")
        return 0

    for code, url in new_items.items():
        print(f"新着: {code} {url}")

    send_email(new_items)
    save_state(already | set(found.keys()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
