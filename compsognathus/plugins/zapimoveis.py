"""
Plugin: ZAP Imóveis (zapimoveis.com.br)
Domínio: Imobiliário
Extrai: preco, area_privativa, area_total, quartos, suites, vagas, bairro, endereco, descricao

Estratégia de extração em 3 camadas (da mais confiável para a mais frágil):
    1. __NEXT_DATA__  — JSON estruturado embutido pelo Next.js (mais estável)
    2. Seletores CSS  — atributos data-testid e data-cy (menos frágeis que classes)
    3. JSON-LD        — metadados Schema.org embutidos em <script> tags
"""
import json
from bs4 import BeautifulSoup

from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register
from compsognathus.plugins._next_data import iter_next_payloads
from compsognathus.plugins._real_estate import clean_area as _clean_area
from compsognathus.plugins._real_estate import clean_int as _clean_int
from compsognathus.plugins._real_estate import clean_price as _clean_price


# ── Camada 1: __NEXT_DATA__ ───────────────────────────────────────────────────

def _extract_next_data(soup: BeautifulSoup) -> dict:
    """Extrai dados estruturados do script __NEXT_DATA__ injetado pelo Next.js.

    Por que usar esta camada primeiro?
    O __NEXT_DATA__ contém os dados brutos usados para renderizar a página,
    antes de qualquer formatação HTML. É mais estável que seletores CSS.
    """
    data: dict = {}
    try:
        # Percorre o JSON recursivamente buscando o objeto do anúncio
        def _find_listing(obj):
            if isinstance(obj, dict):
                if (
                    "usableAreas" in obj
                    or "pricingInfos" in obj
                    or "bedrooms" in obj
                    or ("prices" in obj and "amenities" in obj)
                ):
                    return obj
                for v in obj.values():
                    res = _find_listing(v)
                    if res:
                        return res
            elif isinstance(obj, list):
                for item in obj:
                    res = _find_listing(item)
                    if res:
                        return res
            return None

        listing = None
        for payload in iter_next_payloads(soup):
            listing = _find_listing(payload)
            if listing:
                break
        if not isinstance(listing, dict):
            return data

        # Preço
        pricing = listing.get("pricingInfos") or listing.get("pricingInfo")
        if isinstance(pricing, list) and pricing:
            data["preco"] = float(pricing[0].get("price", 0)) or None
        elif isinstance(pricing, dict):
            data["preco"] = float(pricing.get("price", 0)) or None
        elif listing.get("price"):
            data["preco"] = float(listing["price"])
        else:
            sale = (listing.get("prices") or {}).get("sale") or {}
            data["preco"] = float(sale.get("value", 0)) or None

        # Área útil e total
        amenities = listing.get("amenities") or {}
        areas = listing.get("usableAreas") or listing.get("usableArea") or amenities.get("usableAreas")
        if isinstance(areas, list) and areas:
            data["area_privativa"] = float(areas[0])
        elif isinstance(areas, (int, float, str)):
            data["area_privativa"] = float(areas)

        total_areas = listing.get("totalAreas") or listing.get("totalArea")
        if isinstance(total_areas, list) and total_areas:
            data["area_total"] = float(total_areas[0])
        elif isinstance(total_areas, (int, float, str)):
            data["area_total"] = float(total_areas)

        # Quartos, suítes e vagas
        for key_pt, keys_en in [
            ("quartos", ["bedrooms", "bedroom"]),
            ("suites", ["suites", "suite"]),
            ("vagas", ["parkingSpaces", "parkingSpace"]),
        ]:
            for k in keys_en:
                val = listing.get(k) if k in listing else amenities.get(k)
                if isinstance(val, list) and val:
                    data[key_pt] = int(val[0])
                    break
                elif isinstance(val, (int, str)):
                    data[key_pt] = int(val)
                    break

        # Bairro e endereço
        addr = listing.get("address", {})
        if isinstance(addr, dict):
            neighborhood = addr.get("neighborhood") or addr.get("city")
            if neighborhood:
                data["bairro"] = str(neighborhood)
            parts = [addr.get("street"), neighborhood, addr.get("city"), addr.get("state")]
            full = ", ".join(p for p in parts if p)
            if full:
                data["endereco"] = full

        # Descrição e anunciante
        if listing.get("description"):
            data["descricao"] = str(listing["description"])[:2000]
        pub = listing.get("publisher") or listing.get("advertiser", {})
        if isinstance(pub, dict) and pub.get("name"):
            data["anunciante"] = str(pub["name"])

    except Exception:
        pass

    return data


# ── Função principal de parse ─────────────────────────────────────────────────

@register("zapimoveis.com.br", schema=["preco", "area_privativa", "quartos", "bairro"])
def parse(html: str, url: str) -> ScrapedRecord:
    """Parser do ZAP Imóveis — retorna ScrapedRecord com campos imobiliários."""
    soup = BeautifulSoup(html, "html.parser")
    errors: list[str] = []

    # Camada 1: dados estruturados do Next.js (fonte mais confiável)
    nd = _extract_next_data(soup)

    # ── Preço ─────────────────────────────────────────────────────────────────
    preco = nd.get("preco")
    if preco is None:
        # Camada 2: seletores CSS (data-testid são mais estáveis que classes)
        for sel in ['[data-testid="listing-price"]', 'p[class*="price"]', 'span[class*="Price"]']:
            el = soup.select_one(sel)
            if el:
                preco = _clean_price(el.get_text())
                if preco:
                    break
    if preco is None:
        # Camada 3: JSON-LD (Schema.org)
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                ld = json.loads(script.string or "")
                offers = ld.get("offers") if isinstance(ld, dict) else None
                if isinstance(offers, dict) and offers.get("price"):
                    preco = float(offers["price"])
                    break
            except Exception:
                pass
    if preco is None:
        errors.append("preco")

    # ── Área privativa ────────────────────────────────────────────────────────
    area_privativa = nd.get("area_privativa")
    area_total = nd.get("area_total")

    # Detecta se é terreno/lote (regra NBR 14653-2: área relevante muda)
    title_text = (soup.find("title").get_text().lower() if soup.find("title") else "")
    is_terreno = any(k in url.lower() or k in title_text for k in ["terreno", "lote", "gleba"])

    if area_privativa is None:
        for el in soup.select('[data-testid*="area"], li[class*="detail"], [class*="area"]'):
            t = el.get_text(strip=True)
            if "m²" in t or "m2" in t.lower():
                val = _clean_area(t)
                if val:
                    t_lower = t.lower()
                    if any(w in t_lower for w in ["priv", "útil", "util", "construí"]):
                        area_privativa = area_privativa or val
                    elif any(w in t_lower for w in ["total", "terreno", "lote"]):
                        area_total = area_total or val
                    elif not area_privativa and not is_terreno:
                        area_privativa = val

    if is_terreno:
        area_privativa = area_total or area_privativa  # em terrenos, área relevante é a total

    if area_privativa is None:
        errors.append("area_privativa")

    # ── Quartos, suítes, vagas ────────────────────────────────────────────────
    quartos = nd.get("quartos")
    if quartos is None:
        for sel in ['[data-testid*="bedroom"]', '[class*="Bedroom"]', '[aria-label*="quarto"]']:
            el = soup.select_one(sel)
            if el:
                quartos = _clean_int(el.get_text())
                if quartos is not None:
                    break
    if quartos is None and not is_terreno:
        errors.append("quartos")

    suites = nd.get("suites")
    if suites is None:
        for sel in ['[data-testid*="suite"]', '[class*="Suite"]']:
            el = soup.select_one(sel)
            if el:
                suites = _clean_int(el.get_text())
                break

    vagas = nd.get("vagas")
    if vagas is None:
        for sel in ['[data-testid*="parking"]', '[class*="Garage"]', '[aria-label*="vaga"]']:
            el = soup.select_one(sel)
            if el:
                vagas = _clean_int(el.get_text())
                break

    # ── Bairro ────────────────────────────────────────────────────────────────
    bairro = nd.get("bairro")
    if bairro is None:
        for sel in ['[data-testid="listing-address"]', 'h2[class*="address"]', 'address']:
            el = soup.select_one(sel)
            if el:
                parts = [p.strip() for p in el.get_text(separator=", ", strip=True).split(",") if p.strip()]
                bairro = parts[0] if parts else None
                break
    if bairro is None:
        errors.append("bairro")

    return ScrapedRecord(
        url=url,
        site="zapimoveis",
        fields={
            "preco": preco,
            "area_privativa": area_privativa,
            "area_total": area_total,
            "quartos": quartos,
            "suites": suites,
            "vagas": vagas,
            "bairro": bairro,
            "endereco": nd.get("endereco"),
            "descricao": nd.get("descricao"),
            "anunciante": nd.get("anunciante"),
        },
        parse_ok=len(errors) == 0,
        parse_errors=errors,
    )
