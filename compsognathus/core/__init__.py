"""Submódulo core — schema de dados, registry de plugins e parsing adaptativo."""
from compsognathus.core.adaptive import (
    AdaptiveSelector,
    fingerprint_element,
    score_element_similarity,
)
from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import (
    PluginRegistration,
    external_plugin_errors,
    get_download_policy,
    get_model,
    get_parser,
    get_plugin_info,
    get_schema,
    list_plugins,
    load_external_plugins,
    register,
)

__all__ = [
    "AdaptiveSelector",
    "PluginRegistration",
    "ScrapedRecord",
    "external_plugin_errors",
    "fingerprint_element",
    "get_download_policy",
    "get_model",
    "get_parser",
    "get_plugin_info",
    "get_schema",
    "list_plugins",
    "load_external_plugins",
    "register",
    "score_element_similarity",
]
