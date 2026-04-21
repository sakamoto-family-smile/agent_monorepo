from observability.hashing import sha256_prefixed, strip_prefix


def test_sha256_prefixed_returns_prefixed_hex() -> None:
    h = sha256_prefixed("hello")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_sha256_prefixed_bytes_and_str_match() -> None:
    assert sha256_prefixed("abc") == sha256_prefixed(b"abc")


def test_sha256_prefixed_deterministic() -> None:
    assert sha256_prefixed("abc") == sha256_prefixed("abc")


def test_strip_prefix_removes_prefix() -> None:
    h = sha256_prefixed("x")
    assert strip_prefix(h) == h.removeprefix("sha256:")


def test_strip_prefix_passthrough_when_no_prefix() -> None:
    assert strip_prefix("deadbeef") == "deadbeef"
