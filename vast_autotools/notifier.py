from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


@dataclass
class BarkMessage:
    title: str
    body: str
    url: str = ""


class BarkNotifier:
    def __init__(self, bark_url: str, group: str, sound: str, timeout: int = 10):
        self._bark_url = bark_url.strip()
        self._group = group.strip()
        self._sound = sound.strip()
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._bark_url)

    def send(self, message: BarkMessage) -> None:
        if not self.configured:
            raise ValueError("Bark URL is empty")
        target_url = self._build_url(message)
        request = Request(target_url, method="GET")
        with urlopen(request, timeout=self._timeout) as response:
            status = response.status
            if status < 200 or status >= 300:
                raise RuntimeError(f"Bark returned HTTP {status}")

    def _build_url(self, message: BarkMessage) -> str:
        if "{title}" in self._bark_url or "{body}" in self._bark_url:
            url = self._bark_url.replace("{title}", quote(message.title, safe=""))
            url = url.replace("{body}", quote(message.body, safe=""))
        else:
            base = self._bark_url.rstrip("/")
            url = f"{base}/{quote(message.title, safe='')}/{quote(message.body, safe='')}"

        params: dict[str, str] = {}
        if self._group:
            params["group"] = self._group
        if self._sound:
            params["sound"] = self._sound
        if message.url:
            params["url"] = message.url
        if params:
            delimiter = "&" if "?" in url else "?"
            url = f"{url}{delimiter}{urlencode(params)}"
        return url


def build_notifier(bark_url: str, group: str, sound: str) -> Optional[BarkNotifier]:
    if not bark_url.strip():
        return None
    return BarkNotifier(bark_url=bark_url, group=group, sound=sound)
