"""Utilitários compartilhados para blocos JSON-LD de páginas web."""
from __future__ import annotations

import json
from collections.abc import Iterator

from bs4 import BeautifulSoup


def iter_jsonld_items(soup: BeautifulSoup) -> Iterator[dict]:
    """Itera objetos JSON-LD, incluindo itens dentro de ``@graph``."""
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or "")
        except (TypeError, json.JSONDecodeError):
            continue

        items = payload if isinstance(payload, list) else [payload]
        for item in items:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                yield from (entry for entry in graph if isinstance(entry, dict))
            else:
                yield item
