"""notify CLI のテスト。"""
from __future__ import annotations

import logging

import httpx
import pytest

from src.common.healthcheck import make_pinger
from src.notify import __main__ as cli


@pytest.fixture
def restore_levels():
    names = ("httpx", "httpcore")
    before = {n: logging.getLogger(n).level for n in names}
    yield
    for n, level in before.items():
        logging.getLogger(n).setLevel(level)


@pytest.mark.parametrize("verbose", [False, True])
def test_ping_key_not_logged(verbose, caplog, restore_levels):
    caplog.set_level(logging.DEBUG if verbose else logging.INFO)  # pytest の下では basicConfig が効かないため
    cli._setup(verbose=verbose)
    client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    make_pinger(client, "https://hc-ping.com/PINGKEY123")("notify_events", True)
    assert "PINGKEY123" not in caplog.text
