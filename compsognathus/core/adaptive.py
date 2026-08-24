"""Utilitários de parsing adaptativo e seletores resilientes para plugins.

Inspirado no conceito de auto-healing do Scrapling, este módulo fornece
estratégias de seleção resilientes a alterações em classes CSS dinâmicas,
layouts ofuscados e atualizações estruturais do DOM.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Pattern

from bs4 import BeautifulSoup, Tag


def _similarity(a: str, b: str) -> float:
    """Calcula a taxa de similaridade entre duas strings (0.0 a 1.0)."""
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a.strip().lower(), b.strip().lower()).ratio()


def fingerprint_element(element: Tag) -> dict[str, Any]:
    """Extrai uma impressão digital estrutural e semântica de uma tag HTML."""
    if not isinstance(element, Tag):
        return {}

    classes = tuple(element.get("class", []))
    attrs = {
        k: v for k, v in element.attrs.items()
        if k not in {"class", "id"} and isinstance(v, str)
    }

    ancestors = []
    parent = element.parent
    while parent and isinstance(parent, Tag) and parent.name != "[document]":
        ancestors.append(parent.name)
        parent = parent.parent

    text_snippet = element.get_text(strip=True)[:150]

    return {
        "tag": element.name,
        "id": element.get("id"),
        "classes": classes,
        "attrs": attrs,
        "ancestors": tuple(ancestors[:4]),
        "text_snippet": text_snippet,
    }


def score_element_similarity(
    candidate: Tag,
    target_tag: str | None = None,
    text_pattern: str | Pattern[str] | None = None,
    target_attrs: dict[str, str] | None = None,
    reference_classes: tuple[str, ...] | list[str] | None = None,
) -> float:
    """Pontua um elemento candidato em relação aos critérios desejados."""
    if not isinstance(candidate, Tag):
        return 0.0

    score = 0.0
    weights_total = 0.0

    # 1. Compatibilidade de Tag (peso 2.0)
    if target_tag:
        weights_total += 2.0
        if candidate.name.lower() == target_tag.lower():
            score += 2.0

    # 2. Correspondência Textual (peso 3.0)
    if text_pattern is not None:
        weights_total += 3.0
        text = candidate.get_text(strip=True)
        if isinstance(text_pattern, (str, bytes)):
            if text_pattern.lower() in text.lower():
                score += 3.0
            else:
                sim = _similarity(text_pattern, text[:len(text_pattern) * 2])
                score += 3.0 * sim
        elif isinstance(text_pattern, re.Pattern):
            if text_pattern.search(text):
                score += 3.0

    # 3. Atributos Semânticos (aria-*, data-*, name, role) (peso 2.5)
    if target_attrs:
        weights_total += 2.5
        matched_attrs = 0
        for k, v in target_attrs.items():
            cand_val = candidate.get(k)
            if cand_val is not None:
                if str(cand_val).strip().lower() == str(v).strip().lower():
                    matched_attrs += 1
                elif _similarity(str(cand_val), str(v)) > 0.7:
                    matched_attrs += 0.7
        if target_attrs:
            score += 2.5 * (matched_attrs / len(target_attrs))

    # 4. Classes CSS similares (peso 1.5)
    if reference_classes:
        weights_total += 1.5
        cand_classes = candidate.get("class", [])
        if cand_classes:
            cand_cls_str = " ".join(cand_classes)
            ref_cls_str = " ".join(reference_classes)
            cls_sim = _similarity(cand_cls_str, ref_cls_str)
            score += 1.5 * cls_sim

    if weights_total == 0.0:
        return 1.0

    return score / weights_total


class AdaptiveSelector:
    """Seletor adaptativo para localização resiliente de elementos em árvores HTML."""

    @staticmethod
    def find_one(
        soup: BeautifulSoup | Tag,
        primary_selector: str,
        *,
        fallback_tag: str | None = None,
        text_pattern: str | Pattern[str] | None = None,
        target_attrs: dict[str, str] | None = None,
        min_score: float = 0.6,
    ) -> Tag | None:
        """Tenta o seletor primário; se falhar, busca por similaridade adaptativa."""
        if not soup:
            return None

        # 1. Tentativa com seletor CSS exato
        try:
            exact = soup.select_one(primary_selector)
            if exact is not None:
                return exact
        except Exception:
            pass

        # 2. Busca adaptativa por candidatos
        candidate_tags = [fallback_tag] if fallback_tag else [
            "div", "span", "p", "a", "h1", "h2", "h3", "h4", "li", "td", "button", "section", "article"
        ]

        best_match: Tag | None = None
        highest_score = 0.0

        for tag_name in candidate_tags:
            candidates = soup.find_all(tag_name)
            for cand in candidates:
                if not isinstance(cand, Tag):
                    continue
                score = score_element_similarity(
                    cand,
                    target_tag=fallback_tag or tag_name,
                    text_pattern=text_pattern,
                    target_attrs=target_attrs,
                )
                if score > highest_score and score >= min_score:
                    highest_score = score
                    best_match = cand

        return best_match

    @staticmethod
    def extract_text(
        soup: BeautifulSoup | Tag,
        selectors: str | list[str],
        *,
        default: str = "",
        strip: bool = True,
        text_pattern: str | Pattern[str] | None = None,
    ) -> str:
        """Extrai texto limpo usando uma lista ordenada de seletores e fallbacks."""
        if not soup:
            return default

        if isinstance(selectors, str):
            selectors = [selectors]

        for sel in selectors:
            elem = AdaptiveSelector.find_one(soup, sel, text_pattern=text_pattern)
            if elem:
                txt = elem.get_text(strip=strip) if strip else elem.get_text()
                if txt:
                    return txt

        return default

    @staticmethod
    def extract_attr(
        soup: BeautifulSoup | Tag,
        selector: str,
        attr: str,
        *,
        default: str = "",
    ) -> str:
        """Extrai um atributo de um elemento selecionado."""
        if not soup:
            return default

        elem = AdaptiveSelector.find_one(soup, selector)
        if elem and elem.has_attr(attr):
            val = elem[attr]
            if isinstance(val, list):
                return " ".join(val)
            return str(val)

        return default
