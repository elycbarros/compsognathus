"""Utilitários compartilhados pelos plugins imobiliários.

ZAP e VivaReal usam convenções de preço, área e quantidade semelhantes. Ao
centralizar apenas essas conversões, cada plugin continua livre para explicar
seus próprios seletores CSS e particularidades de página.
"""
from __future__ import annotations

import re


def clean_price(text: str) -> float | None:
    """Extrai ``450000.0`` de textos como ``R$ 450.000,00``."""
    match = re.search(r"\d[\d.]*(?:,\d{1,2})?(?![\d.,])", text)
    if not match:
        return None
    number = match.group(0)
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    elif number.count(".") and len(number.rsplit(".", 1)[1]) == 3:
        number = number.replace(".", "")
    value = float(number)
    return value if value >= 10_000 else None


def clean_area(text: str) -> float | None:
    """Extrai área em m² de textos como ``Área total 1.250 m²``."""
    match = re.search(r"([\d.]+(?:,\d+)?)\s*m", text)
    if not match:
        return None
    number = match.group(1)
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    elif number.count(".") and len(number.rsplit(".", 1)[1]) == 3:
        number = number.replace(".", "")
    value = float(number)
    return value if 10.0 <= value <= 100_000.0 else None


def clean_int(text: str) -> int | None:
    """Extrai uma quantidade plausível, como ``3`` de ``3 quartos``."""
    match = re.search(r"\d+", text)
    value = int(match.group(0)) if match else None
    return value if value is not None and 0 <= value <= 50 else None
