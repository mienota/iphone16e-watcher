#!/usr/bin/env python3
"""監視対象サイトごとの Watcher サブクラス集と、名前→インスタンスのレジストリ。

新しいサイトを足すには:
  1. Watcher を継承したクラスを書き、find_items() をオーバーライドする
  2. TARGETS にエントリを追加する
これだけ。取得・状態管理・二重通知防止・メール/ntfy通知は基底が担当する。
"""

import html as html_mod
import os
import re
import time
import urllib.error
import urllib.parse

from watcher import Watcher


def _text(fragment: str) -> str:
    """HTML断片 -> 表示用のプレーンテキスト（タグ除去・実体参照復元・空白圧縮）。"""
    return re.sub(r"\s+", " ", html_mod.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _env_words(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """カンマ区切りの環境変数でキーワードを差し替える（コードを触らず調整用）。"""
    raw = os.environ.get(name, "").strip()
    return tuple(w.strip() for w in raw.split(",") if w.strip()) if raw else default


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
        found: dict[str, str] = {}
        for color in self.colors:
            for size in self.sizes:
                if self._in_stock(html, color, size):
                    found[f"{color}-{size}"] = self.url
        return found

    def describe(self, key: str, url: str) -> str:
        color, size = key.split("-")
        return f"{self.product_name} / カラー {color} / サイズ {size} 在庫あり"


class LinkFeedWatcher(Watcher):
    """一覧ページから「リンク＋タイトル」を拾い、キーワードに合うものだけ通知する。

    ニュース・お知らせ・まとめ記事の類はどのサイトも同じ形なので、
    item_re（group1=リンク, group2=タイトル）と keywords を差し替えるだけで足せる。
    キーは記事URLなので、タイトルが後から書き換わっても二重通知にならない。
    """

    sticky_state = True  # 記事は「出た」というイベント。一度通知したら終わり。
    emoji_tag = "loudspeaker"

    item_re: re.Pattern = re.compile(r"(?!)")  # サブクラスで必ず設定
    keywords: tuple[str, ...] = ()   # 空なら全件を対象にする
    exclude: tuple[str, ...] = ()

    def find_items(self, html: str) -> dict[str, str]:
        found: dict[str, str] = {}
        titles: dict[str, str] = {}
        for m in self.item_re.finditer(html):
            href, title = m.group(1), _text(m.group(2))
            if self.keywords and not any(k in title for k in self.keywords):
                continue
            if any(k in title for k in self.exclude):
                continue
            found[href] = urllib.parse.urljoin(self.url, href)
            titles[href] = title
        self.titles = titles
        return found


class PokecenterNewsWatcher(LinkFeedWatcher):
    """ポケモンセンターオンラインのお知らせに抽選・受注・再販の告知が出たら通知。

    お知らせ一覧はトップページのHTMLに素で入っている（/news/ 単体はエラーになる）。
    実例: 「ポケモンカードゲーム30周年記念商品の抽選期間と応募方法について」
    """

    slug = "pco-news"
    display = "ポケモンセンターオンラインに抽選/受注/再販の告知"
    ascii_title = "Pokemon Center Online: lottery/preorder notice"
    url = "https://www.pokemoncenter-online.com/"
    from_name = "Pokemon Center Watcher"
    item_re = re.compile(r'<a href="(/news/\?id=[^"]+)">.*?class="ttl">(.*?)</span>', re.S)

    def __init__(self):
        self.keywords = _env_words("PCO_NEWS_KEYWORDS", ("抽選", "受注", "再販", "予約"))


class PokemonCardInfoWatcher(LinkFeedWatcher):
    """ポケカ公式(pokemon-card.com)のお知らせから新商品・抽選系だけ拾って通知。

    一覧の各記事は <a href="/info/NNNNNN.html"> の直後の img alt にタイトルが入る。
    """

    slug = "pokecard-info"
    display = "ポケカ公式に新しいお知らせ"
    ascii_title = "Pokemon Card official: new info"
    url = "https://www.pokemon-card.com/info/"
    from_name = "Pokemon Card Watcher"
    item_re = re.compile(r'href="(/info/\d+\.html)"[^>]*>.*?alt="([^"]*)"', re.S)

    def __init__(self):
        self.keywords = _env_words(
            "POKECARD_KEYWORDS", ("抽選", "発売", "予約", "再販", "受注", "拡張パック")
        )


class ChusenAggregatorWatcher(LinkFeedWatcher):
    """入荷Nowの抽選カテゴリに新しい「抽選・予約情報まとめ」記事が出たら通知。

    ポケカに限らず Switch 2 / RTX 50xx / LABUBU / MTG など、いま抽選になっている
    ジャンルが1ページに集まる。キーはまとめ記事のURLなので、既存記事が日々更新
    されても再通知はしない（＝新ジャンルが抽選対象になったときだけ鳴る）。
    """

    slug = "chusen"
    display = "新しい抽選・予約情報まとめ記事"
    ascii_title = "New lottery/preorder roundup"
    url = "https://nyuka-now.com/archives/category/chusen"
    from_name = "Chusen Watcher"
    emoji_tag = "game_die"
    item_re = re.compile(
        r'<h2 class="heading heading-secondary">\s*<a href="(https://nyuka-now\.com/archives/\d+)"[^>]*>(.*?)</a>',
        re.S,
    )

    def __init__(self):
        # 既定は全ジャンル。ポケモンだけにしたいなら CHUSEN_KEYWORDS=ポケモン
        self.keywords = _env_words("CHUSEN_KEYWORDS", ())


class PokecenterStockWatcher(Watcher):
    """ポケモンセンターオンラインの一覧ページで、狙った商品が買える状態になったら通知。

    商品タイルは data-pid="<JAN>" ... </li> の塊で、売り切れのタイルだけ
    「品切れ」バッジ（<p class="price none">）を持つ。名前がキーワードに合い、
    かつ品切れバッジが無いものを「在庫あり」とみなす。
    """

    sticky_state = False  # 在庫は増減する。切れて復活したら再通知したい。
    emoji_tag = "card_index"

    _tile = re.compile(r'data-pid="(\d+)">(.*?)</li>', re.S)
    _name = re.compile(r'<p class="txt"><a href="([^"]+)">(.*?)</a>', re.S)

    def __init__(
        self,
        slug: str = "pco-stock",
        page: str = "https://www.pokemoncenter-online.com/pokemon-card-game/",
        keywords: tuple[str, ...] = (),
        label: str = "ポケモンカードゲーム",
    ):
        self.slug = slug
        self.url = page
        self.keywords = keywords
        self.display = f"ポケモンセンターオンラインで『{label}』が購入可能"
        self.ascii_title = "Pokemon Center Online: item in stock!"
        self.from_name = "Pokemon Center Watcher"

    def find_items(self, html: str) -> dict[str, str]:
        found: dict[str, str] = {}
        titles: dict[str, str] = {}
        for pid, tile in self._tile.findall(html):
            m = self._name.search(tile)
            if not m:
                continue
            href, name = m.group(1), _text(m.group(2))
            if self.keywords and not any(k in name for k in self.keywords):
                continue
            if "品切れ" in tile:
                continue
            found[pid] = urllib.parse.urljoin(self.url, href)
            titles[pid] = name
        self.titles = titles
        return found


class AmazonSearchWatcher(Watcher):
    """Amazon.co.jp の検索結果に、狙った商品が新しく並んだら通知。

    ★注意: Amazonはボット対策が厳しく、家庭用回線からでも体感5割は 503 を返す
    （ヘッダを変えても改善しない＝ランダムなレート制限）。GitHub Actionsのrunnerは
    Azure のIPなのでさらに通りにくい。そのため
      - 503 は数回リトライする
      - それでも駄目なら例外で落とす（黙って「0件」＝異常なしに見せない）
    という方針。sticky なので、失敗した回は次回そのまま拾い直せる。
    """

    sticky_state = True  # 新しく並んだASINを一度だけ知らせる
    emoji_tag = "package"

    _asin = re.compile(r'data-asin="([A-Z0-9]{10})"')
    _title = re.compile(r'alt="([^"]{5,})"')
    _blocked = ("api-services-support@amazon.com", "Enter the characters you see below")

    def __init__(self, query: str, keywords: tuple[str, ...] = (), slug: str = "amazon"):
        self.query = query
        self.keywords = keywords or (query,)
        self.slug = slug
        self.display = f"Amazonに『{query}』の新着商品"
        self.ascii_title = "Amazon: new matching item"
        self.url = "https://www.amazon.co.jp/s?k=" + urllib.parse.quote(query)
        self.from_name = "Amazon Watcher"

    def fetch(self) -> str:
        """503（ボット対策のレート制限）は間を空けて数回やり直す。"""
        last: Exception | None = None
        for attempt in range(4):
            if attempt:
                time.sleep(5 * attempt)
            try:
                return super().fetch()
            except urllib.error.HTTPError as e:
                if e.code not in (503, 429):
                    raise
                last = e
                print(f"[amazon] {e.code} でブロック（{attempt + 1}回目）。リトライします")
        raise RuntimeError(f"Amazonに4回ともブロックされました: {last}")

    def find_items(self, html: str) -> dict[str, str]:
        if any(sig in html for sig in self._blocked):
            raise RuntimeError("Amazonにボット判定でブロックされました（DC IPのため）")

        # 検索結果タイルは data-asin から次の data-asin までが1件（1件で10KB超えるので
        # 正規表現で丸ごと囲まず、出現位置で切り出す）。商品名は img の alt に入っている。
        marks = [m for m in self._asin.finditer(html)]
        bounds = [m.start() for m in marks] + [len(html)]

        found: dict[str, str] = {}
        titles: dict[str, str] = {}
        for i, m in enumerate(marks):
            tile = html[bounds[i]:bounds[i + 1]]
            t = self._title.search(tile)
            name = _text(t.group(1)) if t else ""
            if not any(k in name for k in self.keywords):
                continue
            asin = m.group(1)
            found[asin] = f"https://www.amazon.co.jp/dp/{asin}"
            titles[asin] = name
        self.titles = titles
        return found


# ---- レジストリ: WATCH_TARGET の値 -> インスタンスを組み立てる ---------------
#   apple-<model> は WATCH_MODEL でも指定可（後方互換）。
#   モンベルの商品を変えたい場合は MontbellWatcher(product_id=..., colors=..., sizes=...)。
TARGETS: dict[str, "callable"] = {
    "apple-16e": lambda: AppleRefurbWatcher("16e"),
    "montbell": lambda: MontbellWatcher(),  # ライトアルパインダウンパーカ BK×XL
    # --- ポケカ ---
    "pco-news": lambda: PokecenterNewsWatcher(),        # 抽選/受注/再販の告知
    "pokecard-info": lambda: PokemonCardInfoWatcher(),  # 公式の新商品・お知らせ
    "pco-stock": lambda: PokecenterStockWatcher(       # 狙った商品の在庫復活
        page=os.environ.get("PCO_STOCK_URL") or "https://www.pokemoncenter-online.com/pokemon-card-game/",
        keywords=_env_words("PCO_STOCK_KEYWORDS", ("拡張パック", "BOX", "スペシャルセット", "30周年")),
    ),
    "amazon-pokeca": lambda: AmazonSearchWatcher(
        query="ポケモンカード 拡張パック",
        keywords=_env_words("AMAZON_KEYWORDS", ("拡張パック",)),
        slug="amazon-pokeca",
    ),
    # --- ジャンル横断（ポケカ以外の抽選も拾う）---
    "chusen": lambda: ChusenAggregatorWatcher(),
}


def build_target(name: str) -> Watcher:
    name = (name or "apple-16e").strip().lower()
    if name in TARGETS:
        return TARGETS[name]()
    # apple-<任意モデル> は動的に許可（例: apple-15-plus のテスト）
    if name.startswith("apple-"):
        return AppleRefurbWatcher(name[len("apple-"):])
    raise SystemExit(f"未知のターゲット: {name!r}（利用可能: {', '.join(TARGETS)}）")
