"""
Registry de plugins: mapeia domínio de URL → função parse.

Como funciona:
    1. Cada plugin usa @register("site.com.br", schema=[...]) no topo do arquivo.
    2. Ao ser importado, o plugin se auto-registra no dicionário _REGISTRY.
    3. Quando o scraper recebe uma URL, chama get_parser(url) para obter
       a função correta para aquele domínio.

Adicionar um novo plugin é tão simples quanto:
    @register("meusite.com.br", schema=["campo1", "campo2"])
    def parse(html: str, url: str) -> ScrapedRecord:
        ...
"""
from __future__ import annotations

from typing import Callable
from urllib.parse import urlparse

from compsognathus.core.record import ScrapedRecord

# Dicionário global: domínio → (função_parse, lista_de_campos_esperados)
# why: populado automaticamente pelo decorator, evita registro manual
_REGISTRY: dict[str, tuple[Callable[[str, str], ScrapedRecord], list[str]]] = {}


def register(domain: str, schema: list[str] | None = None):
    """Decorator que registra uma função parse para um domínio.

    Args:
        domain: Domínio do site, ex: "zapimoveis.com.br"
        schema: Campos que este parser extrai (usado para calcular
                taxa de qualidade no 'comps report').

    Uso:
        @register("meusite.com.br", schema=["titulo", "preco"])
        def parse(html: str, url: str) -> ScrapedRecord:
            ...
    """
    def decorator(fn: Callable[[str, str], ScrapedRecord]) -> Callable[[str, str], ScrapedRecord]:
        # PLUGIN HOOK: cada @register adiciona uma entrada ao dicionário global
        _REGISTRY[domain] = (fn, schema or [])
        return fn
    return decorator


def get_parser(url: str) -> Callable[[str, str], ScrapedRecord]:
    """Retorna a função parse registrada para o domínio da URL.

    Raises:
        ValueError: se nenhum plugin estiver registrado para esse domínio.
    """
    host = urlparse(url).netloc.lower()
    if host.startswith("www."):
        host = host[4:]  # remove "www." para padronizar

    # Busca por correspondência parcial: "zapimoveis.com.br" contém "zapimoveis"
    for domain, (fn, _) in _REGISTRY.items():
        if domain in host:
            return fn

    registered = list(_REGISTRY.keys())
    raise ValueError(
        f"Nenhum plugin registrado para: '{host}'\n"
        f"Plugins disponíveis: {registered}\n"
        f"Para criar um novo plugin, veja: docs/writing-a-plugin.md"
    )


def list_plugins() -> list[dict]:
    """Retorna metadados de todos os plugins registrados.

    Usado pelo comando 'comps plugins list'.
    """
    result = []
    for domain, (fn, schema) in _REGISTRY.items():
        # Extrai a primeira linha da docstring como descrição curta
        doc = (fn.__doc__ or "").strip().split("\n")[0]
        result.append({
            "domain": domain,
            "schema": ", ".join(schema) if schema else "–",
            "description": doc,
        })
    return result
