"""直播流网络层的纯逻辑测试。"""

import pytest

from app.media.stream import GetStreamURL, StreamResult, is_valid_stream_url


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/live.flv?token=abc", True),
        ("http://127.0.0.1/stream", True),
        ("  https://cdn.example.com/live  ", True),
        ("", False),
        (None, False),
        ("//example.com/live", False),
        ("file:///tmp/live.flv", False),
        ("not-a-url", False),
    ],
)
def test_is_valid_stream_url(url, expected):
    assert is_valid_stream_url(url) is expected


def test_stream_result_captures_request_metadata(qapp, monkeypatch):
    worker = GetStreamURL()
    worker.setConfig("123", 250, "")
    monkeypatch.setattr(worker, "_get_stream_urls", lambda *args: ["https://cdn.example/live.flv"])
    results = []
    worker.streamUrl.connect(results.append)

    worker.run()

    assert results == [StreamResult(1, "123", 250, ("https://cdn.example/live.flv",))]


def test_stream_worker_drops_result_when_config_changes(qapp, monkeypatch):
    worker = GetStreamURL()
    worker.setConfig("123", 250, "")

    def change_config(*args):
        worker.setConfig("456", 80, "")
        return ["https://cdn.example/old.flv"]

    monkeypatch.setattr(worker, "_get_stream_urls", change_config)
    results = []
    worker.streamUrl.connect(results.append)

    worker.run()

    assert results == []
