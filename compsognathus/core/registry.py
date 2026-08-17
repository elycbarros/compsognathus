"""
Registry de plugins: mapeia domínio de URL → função parse.

Como funciona:
    1. Cada plugin usa @register("site.com.br", schema=[...]) no topo do arquivo.
    2. Plugins bundled se registram por importação; plugins externos podem ser
       carregados pelo entry point ``compsognathus.plugins``.
    3. Quando o scraper recebe uma URL, chama get_parser(url) para obter
       a função correta para aquele domínio.

Adicionar um novo plugin é tão simples quanto:
    @register("meusite.com.br", schema=["campo1", "campo2"])
    def parse(html: str, url: str) -> ScrapedRecord:
        ...
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from typing import Callable
from urllib.parse import urlparse

from pydantic import BaseModel

from compsognathus.core.record import ScrapedRecord
from compsognathus.downloader import DownloadPolicy

Parser = Callable[[str, str], ScrapedRecord]


@dataclass(frozen=True)
class PluginRegistration:
    """Contrato explícito de um plugin registrado.

    A classe nomeia os dois valores que antes formavam uma tupla, facilitando
    a leitura para quem está aprendendo como o decorator registra plugins.
    """

    parser: Parser
    schema: tuple[str, ...]
    model: type[BaseModel] | None = None
    download_policy: DownloadPolicy | None = None
    source: str = "bundled"
    version: str | None = None

# Dicionário global: domínio → contrato do plugin.
_REGISTRY: dict[str, PluginRegistration] = {}
_EXTERNAL_LOADED = False
_EXTERNAL_ERRORS: list[str] = []
_ACTIVE_PLUGIN_SOURCE = "bundled"
_ACTIVE_PLUGIN_VERSION: str | None = None


def load_external_plugins() -> list[str]:
    """Carrega plugins instalados pelo entry point ``compsognathus.plugins``.

    Um entry point pode apontar para um módulo que registra funções por efeito
    de importação ou para uma função ``register_plugin()`` sem argumentos.
    Falhas são preservadas para diagnóstico e não impedem os plugins internos.
    """
    global _EXTERNAL_LOADED, _ACTIVE_PLUGIN_SOURCE, _ACTIVE_PLUGIN_VERSION
    if _EXTERNAL_LOADED:
        return list(_EXTERNAL_ERRORS)
    _EXTERNAL_LOADED = True
    try:
        discovered = metadata.entry_points()
        if hasattr(discovered, "select"):
            entries = discovered.select(group="compsognathus.plugins")
        elif isinstance(discovered, dict):
            entries = discovered.get("compsognathus.plugins", [])
        else:
            entries = discovered
    except Exception as exc:
        _EXTERNAL_ERRORS.append(f"entry_points: {type(exc).__name__}: {exc}")
        return list(_EXTERNAL_ERRORS)

    for entry in entries:
        previous_source = _ACTIVE_PLUGIN_SOURCE
        previous_version = _ACTIVE_PLUGIN_VERSION
        _ACTIVE_PLUGIN_SOURCE = f"entry-point:{entry.name}"
        _ACTIVE_PLUGIN_VERSION = getattr(getattr(entry, "dist", None), "version", None)
        try:
            loaded = entry.load()
            if callable(loaded):
                loaded()
        except Exception as exc:
            message = f"{entry.name}: {type(exc).__name__}: {exc}"
            _EXTERNAL_ERRORS.append(message)
        finally:
            _ACTIVE_PLUGIN_SOURCE = previous_source
            _ACTIVE_PLUGIN_VERSION = previous_version
    return list(_EXTERNAL_ERRORS)


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


def register(
    domain: str,
    schema: list[str] | None = None,
    *,
    model: type[BaseModel] | None = None,
    download_policy: DownloadPolicy | None = None,
) -> Callable[[Parser], Parser]:
    """Decorator que registra uma função parse para um domínio.

    Args:
        domain: Domínio do site, ex: "zapimoveis.com.br"
        schema: Campos obrigatórios (mantido para compatibilidade).
        model: Modelo Pydantic opcional para validar e normalizar os campos.
        download_policy: Estratégia de download específica do domínio.

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
        if model is not None and (
            not isinstance(model, type) or not issubclass(model, BaseModel)
        ):
            raise TypeError("model deve ser uma subclasse de pydantic.BaseModel")
        existing = _REGISTRY.get(normalized_domain)
        if existing is not None and existing.parser is not fn:
            raise ValueError(
                f"Conflito de plugin para '{normalized_domain}': "
                f"já registrado por {existing.source}"
            )
        _REGISTRY[normalized_domain] = PluginRegistration(
            fn,
            tuple(schema or ()),
            model=model,
            download_policy=download_policy,
            source=_ACTIVE_PLUGIN_SOURCE,
            version=_ACTIVE_PLUGIN_VERSION,
        )
        return fn
    return decorator


def get_parser(url: str) -> Callable[[str, str], ScrapedRecord]:
    """Retorna a função parse registrada para o domínio da URL.

    Raises:
        ValueError: se nenhum plugin estiver registrado para esse domínio.
    """
    load_external_plugins()
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
    load_external_plugins()
    registration = _find_registration(url)
    if registration:
        return list(registration.schema)
    raise ValueError(f"Nenhum plugin registrado para: {url!r}")


def get_model(url: str) -> type[BaseModel] | None:
    """Retorna o modelo tipado opcional do plugin."""
    load_external_plugins()
    registration = _find_registration(url)
    if registration:
        return registration.model
    raise ValueError(f"Nenhum plugin registrado para: {url!r}")


def get_download_policy(url: str) -> DownloadPolicy | None:
    """Retorna a política de download opcional do plugin."""
    load_external_plugins()
    registration = _find_registration(url)
    if registration:
        return registration.download_policy
    raise ValueError(f"Nenhum plugin registrado para: {url!r}")


def list_plugins() -> list[dict]:
    """Retorna metadados de todos os plugins registrados.

    Usado pelo comando 'comps plugins list'.
    """
    load_external_plugins()
    result = []
    for domain, registration in _REGISTRY.items():
        # Extrai a primeira linha da docstring como descrição curta
        doc = (registration.parser.__doc__ or "").strip().split("\n")[0]
        result.append({
            "domain": domain,
            "schema": ", ".join(registration.schema) if registration.schema else "–",
            "model": registration.model.__name__ if registration.model else "–",
            "download": registration.download_policy.preferred if registration.download_policy else "default",
            "source": registration.source,
            "version": registration.version or "–",
            "description": doc,
        })
    return result


def external_plugin_errors() -> list[str]:
    """Retorna falhas de carregamento de plugins externos para diagnóstico."""
    load_external_plugins()
    return list(_EXTERNAL_ERRORS)


def get_plugin_info(url: str) -> dict[str, str] | None:
    """Retorna metadados do plugin responsável por uma URL, se houver."""
    load_external_plugins()
    registration = _find_registration(url)
    if registration is None:
        return None
    return {
        "domain": _host_for_url(url),
        "source": registration.source,
        "version": registration.version or "–",
    }
