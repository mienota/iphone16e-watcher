#!/usr/bin/env python3
"""汎用入荷ウォッチャーのエントリポイント。

WATCH_TARGET で監視対象を選ぶ（既定 apple-16e）。実体は targets.py。
  WATCH_TARGET=apple-16e      … Apple整備済ストアの iPhone 16e（WATCH_MODELでも可）
  WATCH_TARGET=montbell       … モンベル ライトアルパインダウンパーカ BK×XL 再入荷

サイトを増やすときは watcher.Watcher を継承して targets.TARGETS に足すだけ。
"""

import os
import sys

from targets import build_target


def main() -> int:
    # 後方互換: WATCH_MODEL だけ指定された旧運用は apple-<model> に読み替える。
    default = f"apple-{os.environ['WATCH_MODEL'].strip().lower()}" if os.environ.get("WATCH_MODEL") else "apple-16e"
    name = os.environ.get("WATCH_TARGET", default)
    return build_target(name).run()


if __name__ == "__main__":
    sys.exit(main())
