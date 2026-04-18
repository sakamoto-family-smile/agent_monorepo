from utils.encoding import detect_encoding


def test_detects_cp932_with_japanese():
    data = "これはテストです".encode("cp932")
    assert detect_encoding(data) in ("cp932", "shift_jis")


def test_detects_utf8_bom():
    data = "テスト".encode("utf-8-sig")
    assert detect_encoding(data) in ("utf-8-sig", "utf-8")


def test_detects_plain_utf8():
    data = "plain ascii only".encode("utf-8")
    assert detect_encoding(data) in ("utf-8-sig", "utf-8")


def test_prefers_utf8_over_cp932_when_ambiguous():
    """ASCII 範囲のみなら utf-8 が優先されるべき（CP932はASCII互換）。"""
    data = b"A,B,C\n1,2,3\n"
    # 優先順リスト最初の成功 = utf-8-sig → utf-8
    assert detect_encoding(data) == "utf-8-sig"


def test_fallback_for_unrecognizable_bytes():
    # 完全ランダムバイトでも例外を投げない
    data = bytes(range(256))
    enc = detect_encoding(data)
    assert isinstance(enc, str)
    assert enc
