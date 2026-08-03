"""
Plugin: Mercado Livre (mercadolivre.com.br)
Domínio: E-commerce
Extrai: produto, preco, preco_original, avaliacao, num_avaliacoes, vendedor, condicao, url_imagem

Este plugin demonstra que o framework funciona para domínios completamente
diferentes de imóveis. O mesmo padrão @register, parse(html, url) → ScrapedRecord
funciona para qualquer tipo de dado estruturado na web.

Estratégia de extração:
    1. JSON-LD (Schema.org Product) — mais estruturado e estável
    2. Seletores CSS + meta tags — fallback para campos não cobertos pelo JSON-LD
"""
import json
import re
from bs4 import BeautifulSoup

from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_price(text: str) -> float | None:
    """Extrai valor numérico de string de preço ('R$\xa012.999' → 12999.0)."""
    # \xa0 é o espaço não-quebrável comum em preços do Mercado Livre
    text = text.replace("\xa0", "").replace(".", "").replace(",", ".")
    m = re.search(r"[\d]+(?:\.\d+)?", text)
    try:
        return float(m.group(0)) if m else None
    except (ValueError, AttributeError):
        return None


def _extract_jsonld(soup: BeautifulSoup) -> dict:
    """Extrai dados do JSON-LD Schema.org (tipo Product).

    Sites de e-commerce frequentemente incluem um bloco <script type="application/ld+json">
    com dados estruturados. Esse é o método mais confiável de extração.
    """
    data: dict = {}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "")
            # Normaliza: pode ser um objeto único ou uma lista
            items = ld if isinstance(ld, list) else [ld]
            for item in items:
                if not isinstance(item, dict):
                    continue
                # Procura pelo tipo Product (Schema.org)
                if item.get("@type") not in ("Product", "Offer"):
                    continue
                data["produto"] = item.get("name")
                data["descricao"] = str(item.get("description", ""))[:500] or None
                data["url_imagem"] = item.get("image")

                offers = item.get("offers") or {}
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                data["preco"] = float(offers.get("price", 0)) or None
                data["condicao"] = offers.get("itemCondition", "").split("/")[-1] or None

                agg = item.get("aggregateRating") or {}
                if agg:
                    data["avaliacao"] = float(agg.get("ratingValue", 0)) or None
                    data["num_avaliacoes"] = int(agg.get("reviewCount", 0)) or None

                if data.get("produto"):
                    break  # achou o produto, sai do loop
        except Exception:
            continue
    return data


# ── Função principal de parse ─────────────────────────────────────────────────

@register("mercadolivre.com.br", schema=["produto", "preco", "avaliacao", "vendedor", "condicao"])
def parse(html: str, url: str) -> ScrapedRecord:
    """Parser do Mercado Livre — extrai dados de produto de uma página de anúncio."""
    soup = BeautifulSoup(html, "html.parser")
    errors: list[str] = []

    # Camada 1: JSON-LD (preferencial — estruturado pelo próprio site)
    ld = _extract_jsonld(soup)

    # ── Produto (título do anúncio) ───────────────────────────────────────────
    produto = ld.get("produto")
    if not produto:
        # Camada 2: tag <h1> principal ou meta og:title
        h1 = soup.find("h1")
        if h1:
            produto = h1.get_text(strip=True)
    if not produto:
        meta = soup.find("meta", property="og:title")
        if meta:
            produto = meta.get("content", "").strip() or None
    if not produto:
        errors.append("produto")

    # ── Preço ─────────────────────────────────────────────────────────────────
    preco = ld.get("preco")
    if preco is None:
        # Seletores CSS do Mercado Livre (podem variar por versão do site)
        for sel in [
            '[class*="price-tag-fraction"]',   # preço inteiro
            'meta[itemprop="price"]',           # microdata
            '[class*="andes-money-amount"]',    # componente interno do ML
        ]:
            el = soup.select_one(sel)
            if el:
                content = el.get("content") or el.get_text(strip=True)
                preco = _clean_price(content)
                if preco:
                    break
    if preco is None:
        errors.append("preco")

    # ── Preço original (antes do desconto) ───────────────────────────────────
    preco_original = None
    for sel in ['[class*="price-tag-original"]', 'del[class*="price"]', 's[class*="price"]']:
        el = soup.select_one(sel)
        if el:
            preco_original = _clean_price(el.get_text(strip=True))
            break

    # ── Avaliação ─────────────────────────────────────────────────────────────
    avaliacao = ld.get("avaliacao")
    if avaliacao is None:
        for sel in ['[class*="reviews-summary__rating"]', 'span[itemprop="ratingValue"]']:
            el = soup.select_one(sel)
            if el:
                try:
                    avaliacao = float(el.get_text(strip=True).replace(",", "."))
                except (ValueError, AttributeError):
                    pass
                break

    num_avaliacoes = ld.get("num_avaliacoes")
    if num_avaliacoes is None:
        for sel in ['[class*="reviews-summary__amount"]', 'span[itemprop="reviewCount"]']:
            el = soup.select_one(sel)
            if el:
                m = re.search(r"\d+", el.get_text())
                num_avaliacoes = int(m.group(0)) if m else None
                break

    # ── Vendedor ─────────────────────────────────────────────────────────────
    vendedor = None
    for sel in [
        '[class*="seller-info__name"]', '[class*="store-info__name"]',
        'meta[name="seller_name"]', '[data-testid="seller-name"]',
    ]:
        el = soup.select_one(sel)
        if el:
            vendedor = el.get("content") or el.get_text(strip=True) or None
            break

    # ── Condição (novo/usado) ─────────────────────────────────────────────────
    condicao = ld.get("condicao")
    if not condicao:
        for sel in ['[class*="subtitle-condition"]', 'span[class*="condition"]']:
            el = soup.select_one(sel)
            if el:
                condicao = el.get_text(strip=True).lower() or None
                break

    return ScrapedRecord(
        url=url,
        site="mercadolivre",
        fields={
            "produto": produto,
            "preco": preco,
            "preco_original": preco_original,
            "avaliacao": avaliacao,
            "num_avaliacoes": num_avaliacoes,
            "vendedor": vendedor,
            "condicao": condicao,
            "descricao": ld.get("descricao"),
            "url_imagem": ld.get("url_imagem"),
        },
        parse_ok=len(errors) == 0,
        parse_errors=errors,
    )
