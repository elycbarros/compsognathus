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

from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlparse

from compsognathus.core.record import ScrapedRecord

Parser = Callable[[str, str], ScrapedRecord]


@dataclass(frozen=True)
class PluginRegistration:
    """Contrato explícito de um plugin registrado.

    A classe nomeia os dois valores que antes formavam uma tupla, facilitando
    a leitura para quem está aprendendo como o decorator registra plugins.
    """

    parser: Parser
    schema: tuple[str, ...]


# Dicionário global: domínio → contrato do plugin.
_REGISTRY: dict[str, PluginRegistration] = {}


def _host_for_url(url: str) -> str:
    """Extrai um hostname normalizado ou retorna vazio para URL inválida."""
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _find_registration(url: str) -> PluginRegistration | None:
    host = _host_for_url(url)
    if not host:
        return None
    for domain, registration in _REGISTRY.items():
        if host == domain or host.endswith(f".{domain}"):
            return registration
    return None


def register(domain: str, schema: list[str] | None = None) -> Callable[[Parser], Parser]:
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
    normalized_domain = domain.strip().lower().rstrip(".")
    if normalized_domain.startswith("www."):
        normalized_domain = normalized_domain[4:]
    if not normalized_domain or any(char in normalized_domain for char in "/:@"):
        raise ValueError(f"Domínio inválido para registro: {domain!r}")

    def decorator(fn: Parser) -> Parser:
        # PLUGIN HOOK: cada @register adiciona uma entrada ao dicionário global
        _REGISTRY[normalized_domain] = PluginRegistration(fn, tuple(schema or ()))
        return fn
    return decorator


def get_parser(url: str) -> Callable[[str, str], ScrapedRecord]:
    """Retorna a função parse registrada para o domínio da URL.

    Raises:
        ValueError: se nenhum plugin estiver registrado para esse domínio.
    """
    host = _host_for_url(url)
    if not host:
        raise ValueError(f"URL inválida ou sem domínio: {url!r}")

    # Aceita o domínio exato e seus subdomínios, sem confundir domínios impostores.
    registration = _find_registration(url)
    if registration:
        return registration.parser

    registered = list(_REGISTRY.keys())
    raise ValueError(
        f"Nenhum plugin registrado para: '{host}'\n"
        f"Plugins disponíveis: {registered}\n"
        f"Para criar um novo plugin, veja: docs/writing-a-plugin.md"
    )


def get_schema(url: str) -> list[str]:
    """Retorna os campos de qualidade declarados pelo plugin da URL."""
    registration = _find_registration(url)
    if registration:
        return list(registration.schema)
    raise ValueError(f"Nenhum plugin registrado para: {url!r}")


def list_plugins() -> list[dict]:
    """Retorna metadados de todos os plugins registrados.

    Usado pelo comando 'comps plugins list'.
    """
    result = []
    for domain, registration in _REGISTRY.items():
        # Extrai a primeira linha da docstring como descrição curta
        doc = (registration.parser.__doc__ or "").strip().split("\n")[0]
        result.append({
            "domain": domain,
            "schema": ", ".join(registration.schema) if registration.schema else "–",
            "description": doc,
        })
    return result
