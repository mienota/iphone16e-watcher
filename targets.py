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
    """Apple 日本の整備済製品ストアに特定モデルが登場したら通知。

    判定: 商品タイルURL (/jp/shop/product/<code>/a/iphone-<model>-<容量>-...) の有無。
    左サイドのフィルタ定義は全機種分類表で在庫と無関係なので使わない。

    capacities を指定すると、その容量のタイルだけ通知対象にする
    （例 ("128gb",) で最小容量モデルだけ）。None なら全容量。
    """

    # 整備済は載ったり消えたりする。買い逃した同じSKUが再登場したときに
    # 鳴ってほしいので「一回きり」にはしない（消えたら忘れ、復活で再通知）。
    sticky_state = False
    notify_channel = "APPLE"  # NTFY_TOPIC_APPLE があればそちらへ送る

    def __init__(self, model: str = "16e", capacities=None):
        self.model = model.strip().lower()
        # ("128gb",) / ("128GB", "256gb") / "128gb" のどれでも受ける
        if isinstance(capacities, str):
            capacities = (capacities,)
        self.capacities = tuple(c.strip().lower() for c in capacities) if capacities else ()

        label = "iPhone " + " ".join(
            w.capitalize() if w.isalpha() else w for w in self.model.split("-")
        )
        cap_label = ""
        if self.capacities:
            cap_label = " " + "/".join(c.upper() for c in self.capacities)
        self.slug = f"apple-{self.model}"
        self.display = f"Apple整備済製品ストアに {label}{cap_label} が登場！"
        self.ascii_title = f"{label}{cap_label} available in refurb store!"  # ASCIIのみ
        self.url = "https://www.apple.com/jp/shop/refurbished/iphone"
        self.from_name = "Apple Refurb Watcher"
        self._tile = re.compile(
            rf"/jp/shop/product/[a-z0-9]+/a/iphone-{re.escape(self.model)}[^\"'\s?]*",
            re.IGNORECASE,
        )
        # モデル名の直後に来る容量表記。iphone-16e-128gb-... なら "128gb"。
        # 直後であることを要求するのが肝で、iphone-15 に対して
        # iphone-15-pro-max-256gb はここで一致しない（別モデル扱いになる）。
        self._cap = re.compile(
            rf"iphone-{re.escape(self.model)}-(\d+(?:gb|tb))(?=-|$)", re.IGNORECASE
        )

    # 機種を問わない iPhone タイル。1つも無ければ整備済ストアのページを掴めて
    # いない（ブロック・改装・URL変更）。「0件＝まだ登場していない」と誤認
    # しないための取得失敗ガード。モンベルの数量セレクトと同じ考え方。
    _any_tile = re.compile(r"/jp/shop/product/[a-z0-9]+/a/iphone-", re.IGNORECASE)

    # URLのどこかに容量表記があるか（モデル名の直後とは限らない）。
    _any_cap = re.compile(r"-\d+(?:gb|tb)(?=-|$)", re.IGNORECASE)

    def find_items(self, html: str) -> dict[str, str]:
        if not self._any_tile.search(html):
            raise RuntimeError(
                f"整備済ストアに iPhone タイルが0件（取得失敗の疑い, {len(html)}バイト）"
            )

        found: dict[str, str] = {}
        for path in self._tile.findall(html):
            path = urllib.parse.unquote(path)
            if self.capacities:
                m = self._cap.search(path)
                if m is not None:
                    if m.group(1).lower() not in self.capacities:
                        continue
                elif self._any_cap.search(path):
                    # 容量表記はあるがモデル名の直後ではない = 派生モデル
                    # （iphone-15 に対する iphone-15-pro-max-256gb など）。対象外。
                    continue
                else:
                    # 容量表記そのものが無い。URL形式が変わった可能性なので、
                    # 取りこぼすより誤検知の方がマシと考えて通す（ログに出す）。
                    print(f"[warn] 容量を判定できないタイル: {path}")
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
    notify_channel = "MONTBELL"  # NTFY_TOPIC_MONTBELL があればそちらへ送る
    # 遮断されたIPからだと接続が握り潰されて既定の60秒を待たされる。
    # 通るときはローカルもrunnerも数秒なので、短く切って早く諦める。
    timeout = 25
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
    # 全容量。絞りたければ capacities=("128gb",) のように渡す（16eは128/256/512GB）。
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
