"""
Plugin: Catho (catho.com.br)
Domínio: Vagas de Emprego
Extrai: cargo, empresa, salario, cidade, estado, regime, nivel, descricao

Este plugin demonstra extração de dados de vagas de emprego — um domínio
completamente diferente de imóveis e e-commerce. O mesmo padrão de plugin
funciona para qualquer site com dados estruturados.

Estratégia de extração:
    1. JSON-LD (Schema.org JobPosting) — padrão para vagas de emprego
    2. Meta tags Open Graph — título e descrição
    3. Seletores CSS — fallback para campos específicos do Catho
"""
import json
import re
from bs4 import BeautifulSoup

from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register


# ── Helpers ───────────────────────────────────────────────────────────────────

def _clean_salary(text: str) -> float | None:
    """Extrai salário numérico de um texto ('R$ 5.000,00' → 5000.0)."""
    # Remove símbolo de moeda e formata para float
    text = text.replace("R$", "").replace("\xa0", "").strip()
    text = text.replace(".", "").replace(",", ".")
    m = re.search(r"[\d]+(?:\.\d+)?", text)
    try:
        return float(m.group(0)) if m else None
    except (ValueError, AttributeError):
        return None


def _extract_jsonld(soup: BeautifulSoup) -> dict:
    """Extrai dados do JSON-LD Schema.org tipo JobPosting.

    Sites de emprego seguem o padrão Schema.org/JobPosting, que inclui
    campos como title, hiringOrganization, baseSalary, jobLocation, etc.
    """
    data: dict = {}
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            ld = json.loads(script.string or "")
            items = ld if isinstance(ld, list) else [ld]
            for item in items:
                if not isinstance(item, dict):
                    continue
                if item.get("@type") not in ("JobPosting", "Job"):
                    continue

                data["cargo"] = item.get("title")

                # Empresa contratante
                org = item.get("hiringOrganization") or {}
                if isinstance(org, dict):
                    data["empresa"] = org.get("name")

                # Localização
                location = item.get("jobLocation") or {}
                if isinstance(location, dict):
                    addr = location.get("address") or {}
                    if isinstance(addr, dict):
                        data["cidade"] = addr.get("addressLocality")
                        data["estado"] = addr.get("addressRegion")

                # Salário (Schema.org MonetaryAmount)
                salary = item.get("baseSalary") or {}
                if isinstance(salary, dict):
                    value = salary.get("value") or {}
                    if isinstance(value, dict):
                        data["salario"] = float(value.get("value", 0)) or None
                    elif isinstance(value, (int, float)):
                        data["salario"] = float(value)

                # Tipo de contrato e nível
                data["regime"] = item.get("employmentType")
                data["descricao"] = str(item.get("description", ""))[:1000] or None
                data["data_publicacao"] = item.get("datePosted")

                if data.get("cargo"):
                    break
        except Exception:
            continue
    return data


# ── Função principal de parse ─────────────────────────────────────────────────

@register("catho.com.br", schema=["cargo", "empresa", "salario", "cidade"])
def parse(html: str, url: str) -> ScrapedRecord:
    """Parser da Catho — extrai dados de vaga de emprego de uma página de anúncio."""
    soup = BeautifulSoup(html, "html.parser")
    errors: list[str] = []

    # Camada 1: JSON-LD tipo JobPosting (preferencial)
    ld = _extract_jsonld(soup)

    # ── Cargo (título da vaga) ────────────────────────────────────────────────
    cargo = ld.get("cargo")
    if not cargo:
        h1 = soup.find("h1")
        if h1:
            cargo = h1.get_text(strip=True)
    if not cargo:
        meta = soup.find("meta", property="og:title")
        if meta:
            cargo = meta.get("content", "").strip() or None
    if not cargo:
        errors.append("cargo")

    # ── Empresa ───────────────────────────────────────────────────────────────
    empresa = ld.get("empresa")
    if not empresa:
        for sel in [
            '[class*="company-name"]', '[class*="empresa"]',
            '[data-testid*="company"]', 'span[class*="CompanyName"]',
        ]:
            el = soup.select_one(sel)
            if el:
                empresa = el.get_text(strip=True) or None
                break
    if not empresa:
        errors.append("empresa")

    # ── Salário ───────────────────────────────────────────────────────────────
    salario = ld.get("salario")
    if salario is None:
        for sel in ['[class*="salary"]', '[class*="salario"]', '[data-testid*="salary"]']:
            el = soup.select_one(sel)
            if el:
                text = el.get_text(strip=True)
                # Pula se for "Combinado" ou "A combinar" (sem valor fixo)
                if "combin" not in text.lower():
                    salario = _clean_salary(text)
                break

    # ── Cidade e Estado ───────────────────────────────────────────────────────
    cidade = ld.get("cidade")
    estado = ld.get("estado")
    if not cidade:
        for sel in [
            '[class*="location"]', '[class*="localizacao"]',
            '[class*="city"]', '[data-testid*="location"]',
        ]:
            el = soup.select_one(sel)
            if el:
                local = el.get_text(strip=True)
                # Formato comum: "São Paulo - SP" ou "São Paulo, SP"
                parts = re.split(r"[-,]", local)
                cidade = parts[0].strip() if parts else local
                estado = parts[1].strip() if len(parts) > 1 else None
                break
    if not cidade:
        errors.append("cidade")

    # ── Regime de trabalho (CLT, PJ, Freelancer...) ───────────────────────────
    regime = ld.get("regime")
    if not regime:
        for sel in ['[class*="job-type"]', '[class*="regime"]', '[class*="employment"]']:
            el = soup.select_one(sel)
            if el:
                regime = el.get_text(strip=True) or None
                break

    # ── Nível da vaga (Júnior, Pleno, Sênior) ────────────────────────────────
    nivel = None
    for sel in ['[class*="seniority"]', '[class*="nivel"]', '[class*="level"]']:
        el = soup.select_one(sel)
        if el:
            nivel = el.get_text(strip=True) or None
            break

    # ── Descrição da vaga ─────────────────────────────────────────────────────
    descricao = ld.get("descricao")
    if not descricao:
        for sel in ['[class*="job-description"]', '[class*="descricao"]', '[class*="description"]']:
            el = soup.select_one(sel)
            if el:
                descricao = el.get_text(separator=" ", strip=True)[:1000] or None
                break

    return ScrapedRecord(
        url=url,
        site="catho",
        fields={
            "cargo": cargo,
            "empresa": empresa,
            "salario": salario,
            "cidade": cidade,
            "estado": estado,
            "regime": regime,
            "nivel": nivel,
            "descricao": descricao,
            "data_publicacao": ld.get("data_publicacao"),
        },
        parse_ok=len(errors) == 0,
        parse_errors=errors,
    )
