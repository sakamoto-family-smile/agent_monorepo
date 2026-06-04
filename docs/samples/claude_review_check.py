"""Claude PR Review ワークフローの挙動確認用サンプル。

このファイルは claude-review.yml の paths フィルタ (**/*.py) に一致させ、
ワークフローが起動するかを検証するためだけのもの。検証後に削除する。
"""


def add(a: int, b: int) -> int:
    """2 つの整数を加算する（サンプル）。"""
    return a + b
