from __future__ import annotations

from pathlib import Path

from analytics_platform.observability.content import ContentRouter, LocalFilePayloadWriter


def _router(tmp_path: Path, threshold: int = 8192) -> ContentRouter:
    writer = LocalFilePayloadWriter(root_dir=tmp_path / "payloads")
    return ContentRouter(writer=writer, inline_threshold_bytes=threshold)


def test_small_content_stays_inline(tmp_path: Path) -> None:
    router = _router(tmp_path)
    stored = router.route(
        service_name="svc",
        event_id="e1",
        content="hello",
    )
    assert stored.content_text == "hello"
    assert stored.content_uri is None
    assert stored.content_truncated is False
    assert stored.content_hash.startswith("sha256:")
    assert stored.content_size_bytes == 5


def test_large_content_goes_to_uri(tmp_path: Path) -> None:
    big = "a" * 10_000
    router = _router(tmp_path, threshold=8192)
    stored = router.route(
        service_name="svc",
        event_id="e2",
        content=big,
    )
    assert stored.content_text is None
    assert stored.content_uri is not None
    assert stored.content_uri.startswith("file://")
    assert stored.content_truncated is True
    assert stored.content_size_bytes == 10_000
    # ファイルが実在する
    file_path = Path(stored.content_uri.removeprefix("file://"))
    assert file_path.exists()
    assert file_path.read_bytes() == big.encode("utf-8")


def test_preview_always_present(tmp_path: Path) -> None:
    router = _router(tmp_path)
    stored = router.route(service_name="s", event_id="e", content="x" * 100)
    assert stored.content_preview == "x" * 100


def test_preview_truncated_at_500_by_default(tmp_path: Path) -> None:
    router = _router(tmp_path)
    stored = router.route(service_name="s", event_id="e", content="y" * 2000)
    assert len(stored.content_preview) == 500


def test_to_fields_keys(tmp_path: Path) -> None:
    router = _router(tmp_path)
    stored = router.route(service_name="s", event_id="e", content="hi")
    fields = stored.to_fields()
    for k in (
        "content_text",
        "content_uri",
        "content_hash",
        "content_size_bytes",
        "content_truncated",
        "content_preview",
        "content_mime_type",
    ):
        assert k in fields
