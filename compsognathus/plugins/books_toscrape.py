"""
Plugin: Books to Scrape (books.toscrape.com)
Domínio: E-commerce / Livros (Site didático open-to-scrape)
Extrai: titulo, preco, avaliacao, disponibilidade, upc, categoria

Este plugin serve como o exemplo perfeito de demonstração open-to-scrape,
pois o site books.toscrape.com foi feito especificamente para testes de web scraping
sem bloqueios de WAF ou rate-limiting agressivo.
"""
import re
from bs4 import BeautifulSoup

from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register

# Mapeamento de palavras de avaliação para valores numéricos
RATING_MAP = {"One": 1.0, "Two": 2.0, "Three": 3.0, "Four": 4.0, "Five": 5.0}


def _clean_price(text: str) -> float | None:
    """Extrai valor numérico de string de preço ('£51.77' -> 51.77)."""
    m = re.search(r"[\d]+(?:\.\d+)?", text)
    try:
        return float(m.group(0)) if m else None
    except (ValueError, AttributeError):
        return None


@register("books.toscrape.com", schema=["titulo", "preco", "avaliacao", "disponibilidade"])
def parse(html: str, url: str) -> ScrapedRecord:
    """Parser para books.toscrape.com - extrai detalhes de livro."""
    soup = BeautifulSoup(html, "html.parser")
    errors: list[str] = []

    # ── Título ────────────────────────────────────────────────────────────────
    titulo_el = soup.find("h1")
    titulo = titulo_el.get_text(strip=True) if titulo_el else None
    if not titulo:
        errors.append("titulo")

    # ── Preço ─────────────────────────────────────────────────────────────────
    preco_el = soup.select_one("p.price_color")
    preco = _clean_price(preco_el.get_text(strip=True)) if preco_el else None
    if preco is None:
        errors.append("preco")

    # ── Avaliação (Star Rating 1-5) ──────────────────────────────────────────
    rating_el = soup.select_one("p.star-rating")
    avaliacao = None
    if rating_el:
        classes = rating_el.get("class", [])
        rating_word = next((c for c in classes if c != "star-rating"), None)
        if rating_word:
            avaliacao = RATING_MAP.get(rating_word)

    # ── Disponibilidade & Estoque ──────────────────────────────────────────────
    avail_el = soup.select_one("p.instock.availability")
    disponibilidade = None
    if avail_el:
        text = avail_el.get_text(strip=True)
        disponibilidade = "In stock" in text

    # ── Tabela de informações adicionais (UPC, Categoria, etc.) ──────────────
    upc = None
    categoria = None

    table = soup.find("table", class_="table-table-striped") or soup.find("table")
    if table:
        for row in table.find_all("tr"):
            th = row.find("th")
            td = row.find("td")
            if th and td:
                header_text = th.get_text(strip=True).lower()
                val_text = td.get_text(strip=True)
                if "upc" in header_text:
                    upc = val_text

    # Breadcrumb para Categoria
    breadcrumb = soup.select("ul.breadcrumb li a")
    if len(breadcrumb) >= 3:
        categoria = breadcrumb[2].get_text(strip=True)

    return ScrapedRecord(
        url=url,
        site="books_toscrape",
        fields={
            "titulo": titulo,
            "preco": preco,
            "avaliacao": avaliacao,
            "disponibilidade": disponibilidade,
            "upc": upc,
            "categoria": categoria,
        },
        parse_ok=len(errors) == 0,
        parse_errors=errors,
    )
