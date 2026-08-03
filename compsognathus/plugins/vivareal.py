"""
Plugin: VivaReal (vivareal.com.br)
Domínio: Imobiliário
Extrai: preco, area_privativa, area_total, quartos, suites, vagas, bairro, endereco, descricao

VivaReal e ZAP Imóveis pertencem ao mesmo grupo (OLX Group) e compartilham
a estrutura __NEXT_DATA__ com campos idênticos. Por isso este plugin reutiliza
a mesma lógica de extração, com seletores CSS adaptados ao tema VivaReal.
"""
import json
import re
from bs4 import BeautifulSoup

from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register


# ── Helpers de limpeza (idênticos ao ZAP — mesma estrutura de dados) ─────────

def _clean_price(text: str) -> float | None:
    m = re.search(r"\d[\d.]*(?:,\d{1,2})?(?![\d.,])", text)
    if not m:
        return None
    number = m.group(0)
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    elif number.count(".") and len(number.rsplit(".", 1)[1]) == 3:
        number = number.replace(".", "")
    val = float(number)
    return val if val and val >= 10_000 else None


def _clean_area(text: str) -> float | None:
    m = re.search(r"([\d.]+(?:,\d+)?)\s*m", text)
    if not m:
        return None
    number = m.group(1)
    if "," in number:
        number = number.replace(".", "").replace(",", ".")
    elif number.count(".") and len(number.rsplit(".", 1)[1]) == 3:
        number = number.replace(".", "")
    val = float(number)
    return val if val and 10.0 <= val <= 100_000.0 else None


def _clean_int(text: str) -> int | None:
    m = re.search(r"\d+", text)
    val = int(m.group(0)) if m else None
    return val if val is not None and 0 <= val <= 50 else None


# ── Camada 1: __NEXT_DATA__ ───────────────────────────────────────────────────

def _extract_next_data(soup: BeautifulSoup) -> dict:
    """Extrai dados do JSON __NEXT_DATA__ injetado pelo Next.js."""
    data: dict = {}
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return data

    try:
        payload = json.loads(script.string)

        def _find_listing(obj):
            if isinstance(obj, dict):
                if "usableAreas" in obj or "pricingInfos" in obj or "bedrooms" in obj:
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

        listing = _find_listing(payload)
        if not isinstance(listing, dict):
            return data

        # Preço
        pricing = listing.get("pricingInfos") or listing.get("pricingInfo")
        if isinstance(pricing, list) and pricing:
            data["preco"] = float(pricing[0].get("price", 0)) or None
        elif isinstance(pricing, dict):
            data["preco"] = float(pricing.get("price", 0)) or None

        # Áreas
        areas = listing.get("usableAreas") or listing.get("usableArea")
        if isinstance(areas, list) and areas:
            data["area_privativa"] = float(areas[0])
        elif isinstance(areas, (int, float, str)):
            data["area_privativa"] = float(areas)

        total_areas = listing.get("totalAreas") or listing.get("totalArea")
        if isinstance(total_areas, list) and total_areas:
            data["area_total"] = float(total_areas[0])
        elif isinstance(total_areas, (int, float, str)):
            data["area_total"] = float(total_areas)

        # Quartos, suítes, vagas
        for key_pt, keys_en in [
            ("quartos", ["bedrooms", "bedroom"]),
            ("suites", ["suites", "suite"]),
            ("vagas", ["parkingSpaces", "parkingSpace"]),
        ]:
            for k in keys_en:
                val = listing.get(k)
                if isinstance(val, list) and val:
                    data[key_pt] = int(val[0])
                    break
                elif isinstance(val, (int, str)):
                    data[key_pt] = int(val)
                    break

        # Localização
        addr = listing.get("address", {})
        if isinstance(addr, dict):
            neighborhood = addr.get("neighborhood") or addr.get("city")
            if neighborhood:
                data["bairro"] = str(neighborhood)
            parts = [addr.get("street"), neighborhood, addr.get("city"), addr.get("state")]
            data["endereco"] = ", ".join(p for p in parts if p)

        if listing.get("description"):
            data["descricao"] = str(listing["description"])[:2000]

    except Exception:
        pass

    return data


# ── Função principal de parse ─────────────────────────────────────────────────

@register("vivareal.com.br", schema=["preco", "area_privativa", "quartos", "bairro"])
def parse(html: str, url: str) -> ScrapedRecord:
    """Parser do VivaReal — retorna ScrapedRecord com campos imobiliários."""
    soup = BeautifulSoup(html, "html.parser")
    errors: list[str] = []

    # Camada 1: __NEXT_DATA__ (prioritário — mais estável)
    nd = _extract_next_data(soup)

    # ── Preço ─────────────────────────────────────────────────────────────────
    preco = nd.get("preco")
    if preco is None:
        # Camada 2: seletores CSS com data-cy (atributos de teste são mais estáveis)
        for sel in [
            '[data-cy="listing-price"]', '[data-testid="listing-price"]',
            'p[class*="price"]', 'h2[class*="Price"]', 'strong[class*="price"]',
        ]:
            el = soup.select_one(sel)
            if el:
                preco = _clean_price(el.get_text())
                if preco:
                    break
    if preco is None:
        errors.append("preco")

    # ── Área privativa ────────────────────────────────────────────────────────
    area_privativa = nd.get("area_privativa")
    area_total = nd.get("area_total")

    title_text = (soup.find("title").get_text().lower() if soup.find("title") else "")
    is_terreno = any(k in url.lower() or k in title_text for k in ["terreno", "lote", "gleba"])

    if area_privativa is None:
        for el in soup.select('[data-cy*="area"], li[class*="detail"], [class*="area"]'):
            t = el.get_text(strip=True)
            if "m²" in t or "m2" in t.lower():
                val = _clean_area(t)
                if val:
                    if any(w in t.lower() for w in ["priv", "útil", "util", "construí"]):
                        area_privativa = area_privativa or val
                    elif any(w in t.lower() for w in ["total", "terreno"]):
                        area_total = area_total or val
                    elif not area_privativa and not is_terreno:
                        area_privativa = val

    if is_terreno:
        area_privativa = area_total or area_privativa

    if area_privativa is None:
        errors.append("area_privativa")

    # ── Quartos ───────────────────────────────────────────────────────────────
    quartos = nd.get("quartos")
    if quartos is None:
        for sel in ['[data-cy*="bedroom"]', '[data-testid*="bedroom"]', '[class*="Bedroom"]']:
            el = soup.select_one(sel)
            if el:
                quartos = _clean_int(el.get_text())
                if quartos is not None:
                    break
    if quartos is None and not is_terreno:
        errors.append("quartos")

    suites = nd.get("suites")
    vagas = nd.get("vagas")

    # ── Bairro ────────────────────────────────────────────────────────────────
    bairro = nd.get("bairro")
    if bairro is None:
        for sel in ['[data-cy*="address"]', '[data-testid="listing-address"]', 'address']:
            el = soup.select_one(sel)
            if el:
                parts = [p.strip() for p in el.get_text(separator=", ", strip=True).split(",") if p.strip()]
                bairro = parts[0] if parts else None
                break
    if bairro is None:
        errors.append("bairro")

    return ScrapedRecord(
        url=url,
        site="vivareal",
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
        },
        parse_ok=len(errors) == 0,
        parse_errors=errors,
    )
