"""Leitura de payloads estruturados emitidos pelo Next.js moderno."""
from __future__ import annotations

import json
import re
from collections.abc import Iterator

from bs4 import BeautifulSoup


def iter_next_payloads(soup: BeautifulSoup) -> Iterator[object]:
    """Itera payloads de __NEXT_DATA__ e self.__next_f.push."""
    script = soup.find("script", id="__NEXT_DATA__")
    if script and script.string:
        try:
            yield json.loads(script.string)
        except json.JSONDecodeError:
            pass

    pattern = re.compile(r"self\.__next_f\.push\(\[1,(.*)\]\)\s*$", re.DOTALL)
    for script in soup.find_all("script"):
        text = script.string or ""
        if "self.__next_f.push" not in text:
            continue
        match = pattern.search(text)
        if not match:
            continue
        try:
            encoded = json.loads(match.group(1))
            payload = encoded.split(":", 1)[1]
            yield json.loads(payload)
        except (IndexError, TypeError, json.JSONDecodeError):
            continue
