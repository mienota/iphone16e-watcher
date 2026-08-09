#!/usr/bin/env python3
"""監視対象サイトごとの Watcher サブクラス集と、名前→インスタンスのレジストリ。

新しいサイトを足すには:
  1. Watcher を継承したクラスを書き、find_items() をオーバーライドする
  2. TARGETS にエントリを追加する
これだけ。取得・状態管理・二重通知防止・メール/ntfy通知は基底が担当する。
"""

import re
import urllib.parse

from watcher import Watcher


class AppleRefurbWatcher(Watcher):
    """Apple 日本の整備済製品ストアに特定モデルが登場したら通知（初登場一回きり）。

    判定: 商品タイルURL (/jp/shop/product/<code>/a/iphone-<model>-...) の有無。
    左サイドのフィルタ定義は全機種分類表で在庫と無関係なので使わない。
    """

    sticky_state = True  # 整備済は「登場イベント」。一度通知したら終わり。

    def __init__(self, model: str = "16e"):
        self.model = model.strip().lower()
        label = "iPhone " + " ".join(
            w.capitalize() if w.isalpha() else w for w in self.model.split("-")
        )
        self.slug = f"apple-{self.model}"
        self.display = f"Apple整備済製品ストアに {label} が登場！"
        self.ascii_title = f"{label} available in refurb store!"  # labelはASCII
        self.url = "https://www.apple.com/jp/shop/refurbished/iphone"
        self.from_name = "Apple Refurb Watcher"
        self._tile = re.compile(
            rf"/jp/shop/product/[a-z0-9]+/a/iphone-{re.escape(self.model)}[^\"'\s?]*",
            re.IGNORECASE,
        )

    def find_items(self, html: str) -> dict[str, str]:
        found: dict[str, str] = {}
        for path in self._tile.findall(html):
            path = urllib.parse.unquote(path)
            m = re.search(r"/product/([a-z0-9]+)/", path)
            code = m.group(1) if m else path
            found[code] = "https://www.apple.com" + path
        return found

    def describe(self, key: str, url: str) -> str:
        return url.rsplit("/a/", 1)[-1].replace("-", " ")


class MontbellWatcher(Watcher):
    """モンベル webshop で指定カラー×サイズが再入荷したら通知（再入荷監視）。

    在庫は商品ページ(disp.php)のHTMLに含まれる。
    各カラー×サイズは <SIZE>_<COLOR>_num という数量セレクトで表され、
    value>=1 の option があれば「在庫あり」。完売時は option が 0 のみ。
    """

    sticky_state = False  # 在庫は増減する。切れて復活したら再通知したい。
    emoji_tag = "jacket"
    # モンベルはIPv6で接続すると応答が返らずタイムアウトする（ローカルは0.4秒、
    # GitHub Actionsだけ60秒タイムアウトで判明）。IPv4に固定して回避する。
    ipv4_only = True

    def __init__(
        self,
        product_id: str = "1101606",  # ライトアルパインダウン パーカ Men's
        product_name: str = "ライトアルパインダウン パーカ Men's",
        colors=("BK",),               # BK=ブラック
        sizes=("XL",),
    ):
        self.product_id = str(product_id)
        self.product_name = product_name
        self.colors = tuple(c.upper() for c in colors)
        self.sizes = tuple(s.upper() for s in sizes)

        want = " / ".join(f"{c}×{s}" for c in self.colors for s in self.sizes)
        self.slug = f"montbell-{self.product_id}"
        self.display = f"モンベル『{product_name}』入荷（{want}）"
        self.ascii_title = f"Montbell {self.product_id} back in stock!"
        self.url = f"https://webshop.montbell.jp/goods/disp.php?product_id={self.product_id}"
        self.from_name = "Montbell Watcher"

    # 商品ページなら必ず存在する「<SIZE>_<COLOR>_num」形式の数量セレクト。
    # 1つも無ければ商品ページを掴めていない（取得失敗の判定に使う）。
    _any_select = re.compile(r'name="[A-Z0-9]+_[A-Z0-9]+_num"')

    def _in_stock(self, html: str, color: str, size: str) -> bool:
        m = re.search(
            rf'name="{re.escape(size)}_{re.escape(color)}_num"[^>]*>(.*?)</select>',
            html,
            re.S,
        )
        if not m:
            return False
        opts = re.findall(r'<option value="(\d*)"', m.group(1))
        return any(v.isdigit() and int(v) >= 1 for v in opts)

    def find_items(self, html: str) -> dict[str, str]:
        # 数量セレクトが1つも無いページは「全色全サイズ完売」ではなく取得失敗
        # （ブロックページ・エラーページ・商品ID変更など）。0件＝異常なしと
        # 誤報しないよう、ここで落とす。Amazonと同じ考え方。
        if not self._any_select.search(html):
            raise RuntimeError(
                f"モンベルのページに数量セレクトが0件（取得失敗の疑い, {len(html)}バイト）"
            )

        found: dict[str, str] = {}
        for color in self.colors:
            for size in self.sizes:
                if self._in_stock(html, color, size):
                    found[f"{color}-{size}"] = self.url
        return found

    def describe(self, key: str, url: str) -> str:
        color, size = key.split("-")
        return f"{self.product_name} / カラー {color} / サイズ {size} 在庫あり"


# ---- レジストリ: WATCH_TARGET の値 -> インスタンスを組み立てる ---------------
#   apple-<model> は WATCH_MODEL でも指定可（後方互換）。
#   モンベルの商品を変えたい場合は MontbellWatcher(product_id=..., colors=..., sizes=...)。
TARGETS: dict[str, "callable"] = {
    "apple-16e": lambda: AppleRefurbWatcher("16e"),
    "montbell": lambda: MontbellWatcher(),  # ライトアルパインダウンパーカ BK×XL
}


def build_target(name: str) -> Watcher:
    name = (name or "apple-16e").strip().lower()
    if name in TARGETS:
        return TARGETS[name]()
    # apple-<任意モデル> は動的に許可（例: apple-15-plus のテスト）
    if name.startswith("apple-"):
        return AppleRefurbWatcher(name[len("apple-"):])
    raise SystemExit(f"未知のターゲット: {name!r}（利用可能: {', '.join(TARGETS)}）")
