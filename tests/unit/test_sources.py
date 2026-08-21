from __future__ import annotations

from typing import Self

from uli.core.plan import DistroSelection
from uli.install import sources


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def geturl(self) -> str:
        return "https://releases.ubuntu.com/releases/"

    def read(self, _limit: int) -> bytes:
        return self.payload


def test_current_ubuntu_lts_uses_newest_canonical_lts_and_pins_source(monkeypatch) -> None:
    html = b'''<a href="noble/">Ubuntu 24.04.4 LTS (Noble Numbat)</a>
<a href="resolute/">Ubuntu 26.04 LTS (Resolute Raccoon)</a>'''
    monkeypatch.setattr(sources.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response(html))
    sources.current_ubuntu_lts.cache_clear()

    latest = sources.current_ubuntu_lts()
    assert (latest.version, latest.codename) == ("26.04 LTS", "resolute")
    source = sources.source_for(DistroSelection("ubuntu", "desktop", "Ubuntu Desktop", "26.04 LTS"))
    assert source.inrelease_url.endswith("/dists/resolute/InRelease")

    sources.current_ubuntu_lts.cache_clear()
