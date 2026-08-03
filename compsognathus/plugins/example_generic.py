"""
Plugin: Exemplo Genérico — Template Didático
============================================

Este arquivo é um template passo-a-passo para criar seu próprio plugin.
Leia os comentários na ordem de cima para baixo antes de escrever código.

Para criar um plugin novo:
    1. Copie este arquivo: cp example_generic.py meusite.py
    2. Substitua "example.com" pelo domínio alvo
    3. Substitua os campos em `schema` pelos que você quer extrair
    4. Implemente a lógica de extração na função parse()
    5. Adicione o import em plugins/__init__.py

Documentação completa: docs/writing-a-plugin.md
"""
import re
from bs4 import BeautifulSoup

from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import register


# ── PASSO 1: Defina helpers de limpeza ────────────────────────────────────────
# Funções puras de limpeza de texto evitam repetição dentro do parser.
# Sempre retornam None em vez de lançar exceção — parse robusto não quebra.

def _extract_text(el) -> str | None:
    """Extrai texto limpo de um elemento BeautifulSoup. Retorna None se vazio."""
    if el is None:
        return None
    text = el.get_text(strip=True)
    return text if text else None


def _extract_number(text: str) -> float | None:
    """Extrai o primeiro número de um texto ('Preço: 99,90' → 99.9)."""
    if not text:
        return None
    # Normaliza separadores decimais brasileiros
    text = text.replace(".", "").replace(",", ".")
    m = re.search(r"[\d]+(?:\.\d+)?", text)
    try:
        return float(m.group(0)) if m else None
    except (ValueError, AttributeError):
        return None


# ── PASSO 2: Registre o parser com @register ──────────────────────────────────
#
# @register("dominio.com.br", schema=["campo1", "campo2"])
#
# - "dominio.com.br"   → qual site este plugin atende
# - schema=[...]       → campos que você se compromete a extrair
#                        (usados para calcular a taxa de qualidade no 'comps report')
#
# PLUGIN HOOK: troque o domínio e o schema para o seu site

@register("example.com", schema=["titulo", "preco", "descricao"])
def parse(html: str, url: str) -> ScrapedRecord:
    """Parser genérico de exemplo — adapte para o seu site alvo.

    Args:
        html: HTML completo da página (já baixado pelo downloader).
        url:  URL original, usada para contexto e identificação.

    Returns:
        ScrapedRecord com os campos extraídos em `fields`.
    """
    # BeautifulSoup é o parser HTML mais popular em Python.
    # "html.parser" é o parser nativo — sem dependências extras.
    soup = BeautifulSoup(html, "html.parser")

    # Lista de campos obrigatórios que falharam
    # (preenchida ao longo do parse)
    errors: list[str] = []


    # ── PASSO 3: Extraia os campos ────────────────────────────────────────────
    # Dica: inspecione o HTML do site no navegador (F12 → Elements)
    # para encontrar os seletores corretos.

    # Exemplo: extraindo o título da página via <h1>
    titulo = _extract_text(soup.find("h1"))
    if not titulo:
        # Fallback: tenta a meta tag og:title (Open Graph)
        meta = soup.find("meta", property="og:title")
        titulo = meta.get("content", "").strip() if meta else None
    if not titulo:
        errors.append("titulo")  # marca como obrigatório ausente

    # Exemplo: extraindo preço via seletor CSS
    # Substitua 'span.price' pelo seletor correto do seu site
    preco_el = soup.select_one("span.price")
    preco = _extract_number(_extract_text(preco_el))
    if preco is None:
        errors.append("preco")

    # Exemplo: extraindo descrição via meta tag
    meta_desc = soup.find("meta", attrs={"name": "description"})
    descricao = meta_desc.get("content", "").strip() if meta_desc else None


    # ── PASSO 4: Retorne o ScrapedRecord ─────────────────────────────────────
    # `fields` é um dicionário livre — coloque os campos que fizer sentido
    # para o SEU domínio. Não há restrição de nome ou tipo.
    return ScrapedRecord(
        url=url,
        site="example",          # identificador curto do site
        fields={
            "titulo": titulo,
            "preco": preco,
            "descricao": descricao,
            # Adicione quantos campos quiser:
            # "categoria": ...,
            # "autor": ...,
        },
        parse_ok=len(errors) == 0,
        parse_errors=errors,
    )
