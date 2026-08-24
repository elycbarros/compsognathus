from bs4 import BeautifulSoup

from compsognathus.core.adaptive import (
    AdaptiveSelector,
    fingerprint_element,
    score_element_similarity,
)


def test_fingerprint_element():
    html = """
    <div class="product-wrapper container" id="main-prod">
        <span class="price-val" data-price="99.90" aria-label="Preço do produto">R$ 99,90</span>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    span = soup.select_one("span")
    assert span is not None

    fp = fingerprint_element(span)
    assert fp["tag"] == "span"
    assert "price-val" in fp["classes"]
    assert fp["attrs"]["data-price"] == "99.90"
    assert fp["attrs"]["aria-label"] == "Preço do produto"
    assert "div" in fp["ancestors"]
    assert "R$ 99,90" in fp["text_snippet"]


def test_score_element_similarity():
    html = """
    <div>
        <span class="dynamic-class-xyz" data-field="product-title">Notebook Gamer Ultra</span>
        <p class="description">Descrição qualquer</p>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")
    span = soup.select_one("span")
    p = soup.select_one("p")

    score_span = score_element_similarity(
        span,
        target_tag="span",
        text_pattern="Notebook",
        target_attrs={"data-field": "product-title"},
    )
    score_p = score_element_similarity(
        p,
        target_tag="span",
        text_pattern="Notebook",
        target_attrs={"data-field": "product-title"},
    )

    assert score_span > 0.8
    assert score_p < score_span


def test_adaptive_selector_find_one_exact():
    html = '<div class="old-class"><span class="price">R$ 150,00</span></div>'
    soup = BeautifulSoup(html, "html.parser")

    elem = AdaptiveSelector.find_one(soup, "span.price")
    assert elem is not None
    assert elem.get_text(strip=True) == "R$ 150,00"


def test_adaptive_selector_find_one_fallback_when_class_changes():
    # Site mudou a classe CSS de .price para .dynamic-pricing-abc99
    html = """
    <div class="product-card">
        <h2 class="title">Livro Python</h2>
        <span class="dynamic-pricing-abc99" data-qa="price-box">R$ 49,90</span>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")

    # Seletor antigo .price falha, mas o adaptive encontra pela tag e padrão textual
    elem = AdaptiveSelector.find_one(
        soup,
        "span.price",
        fallback_tag="span",
        text_pattern="R$",
        target_attrs={"data-qa": "price-box"},
    )
    assert elem is not None
    assert elem.get_text(strip=True) == "R$ 49,90"


def test_adaptive_selector_extract_text_and_attr():
    html = """
    <div class="product-item">
        <a class="item-link-v2" href="https://example.com/item123" title="Visualizar Item">
            Smartphone Pro Max
        </a>
    </div>
    """
    soup = BeautifulSoup(html, "html.parser")

    text = AdaptiveSelector.extract_text(
        soup,
        ["a.legacy-link", "a.item-link-v2"],
        default="Desconhecido",
    )
    assert text == "Smartphone Pro Max"

    href = AdaptiveSelector.extract_attr(soup, "a.item-link-v2", "href")
    assert href == "https://example.com/item123"

    fallback = AdaptiveSelector.extract_attr(soup, "a.inexistente", "href", default="none")
    assert fallback == "none"
