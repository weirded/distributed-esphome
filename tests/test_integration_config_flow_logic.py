"""HI.12 — config-flow URL normalizer tests.

Pure-function tests that don't need a Home Assistant test harness.
"""

from __future__ import annotations

import pytest

from esphome_fleet.config_flow import _normalize_base_url


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("http://homeassistant.local:8765", "http://homeassistant.local:8765"),
        ("http://homeassistant.local:8765/", "http://homeassistant.local:8765"),
        ("  http://homeassistant.local:8765  ", "http://homeassistant.local:8765"),
        ("https://example.com", "https://example.com"),
        ("https://example.com:443", "https://example.com:443"),
        ("http://192.168.1.10:8765/", "http://192.168.1.10:8765"),
        # IPv6 brackets pass urlparse
        ("http://[fd54::1]:8765", "http://[fd54::1]:8765"),
    ],
)
def test_normalize_base_url_accepts_valid(raw: str, expected: str) -> None:
    assert _normalize_base_url(raw) == expected


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "not-a-url",
        "ftp://host:21",                         # non-http scheme
        "http://",                                # no netloc
        "http://host/path",                       # path not allowed
        "http://host?query=1",                    # query not allowed
        "http://host#fragment",                   # fragment not allowed
        "file:///local/path",
    ],
)
def test_normalize_base_url_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        _normalize_base_url(bad)
