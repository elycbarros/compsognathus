"""
Testes dos parsers com fixtures HTML sintéticas.

Cada teste lê um HTML de exemplo do diretório fixtures/ e verifica
que o parser extrai os campos esperados corretamente.

Por que fixtures sintéticas?
    Fixtures fabricadas permitem testar casos específicos de forma determinística,
    sem depender de conexão com a internet ou de sites que podem mudar.
"""
from pathlib import Path
import pytest

# Diretório onde estão os HTMLs de exemplo
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    """Fixture pytest que retorna uma função para ler HTMLs de teste."""
    def _load(name: str) -> str:
        path = FIXTURES / name
        assert path.exists(), f"Fixture não encontrada: {path}"
        return path.read_text(encoding="utf-8")
    return _load


# ── ZAP Imóveis ───────────────────────────────────────────────────────────────

class TestZapImoveisParser:
    URL = "https://www.zapimoveis.com.br/imovel/apartamento-trindade-123"

    def test_extrai_preco(self, load_fixture):
        from compsognathus.plugins.zapimoveis import parse
        html = load_fixture("zapimoveis_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["preco"] == 650_000.0

    def test_extrai_area(self, load_fixture):
        from compsognathus.plugins.zapimoveis import parse
        html = load_fixture("zapimoveis_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["area_privativa"] == 85.0

    def test_extrai_quartos(self, load_fixture):
        from compsognathus.plugins.zapimoveis import parse
        html = load_fixture("zapimoveis_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["quartos"] == 3

    def test_extrai_bairro(self, load_fixture):
        from compsognathus.plugins.zapimoveis import parse
        html = load_fixture("zapimoveis_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["bairro"] == "Trindade"

    def test_parse_ok_true(self, load_fixture):
        """Fixture completa não deve gerar erros de parse."""
        from compsognathus.plugins.zapimoveis import parse
        html = load_fixture("zapimoveis_sample.html")
        rec = parse(html, self.URL)
        assert rec.parse_ok is True
        assert rec.parse_errors == []

    def test_site_correto(self, load_fixture):
        from compsognathus.plugins.zapimoveis import parse
        html = load_fixture("zapimoveis_sample.html")
        rec = parse(html, self.URL)
        assert rec.site == "zapimoveis"


# ── VivaReal ──────────────────────────────────────────────────────────────────

class TestVivaRealParser:
    URL = "https://www.vivareal.com.br/imovel/casa-palhoca-123"

    def test_extrai_preco(self, load_fixture):
        from compsognathus.plugins.vivareal import parse
        html = load_fixture("vivareal_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["preco"] == 890_000.0

    def test_extrai_area(self, load_fixture):
        from compsognathus.plugins.vivareal import parse
        html = load_fixture("vivareal_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["area_privativa"] == 180.0

    def test_extrai_quartos(self, load_fixture):
        from compsognathus.plugins.vivareal import parse
        html = load_fixture("vivareal_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["quartos"] == 4

    def test_parse_ok_true(self, load_fixture):
        from compsognathus.plugins.vivareal import parse
        html = load_fixture("vivareal_sample.html")
        rec = parse(html, self.URL)
        assert rec.parse_ok is True


# ── Mercado Livre ─────────────────────────────────────────────────────────────

class TestMercadoLivreParser:
    URL = "https://www.mercadolivre.com.br/p/MLB123456"

    def test_extrai_produto(self, load_fixture):
        from compsognathus.plugins.mercadolivre import parse
        html = load_fixture("mercadolivre_sample.html")
        rec = parse(html, self.URL)
        assert "MacBook" in rec.fields["produto"]

    def test_extrai_preco(self, load_fixture):
        from compsognathus.plugins.mercadolivre import parse
        html = load_fixture("mercadolivre_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["preco"] == 11_999.0

    def test_extrai_avaliacao(self, load_fixture):
        from compsognathus.plugins.mercadolivre import parse
        html = load_fixture("mercadolivre_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["avaliacao"] == 4.8

    def test_parse_ok_true(self, load_fixture):
        from compsognathus.plugins.mercadolivre import parse
        html = load_fixture("mercadolivre_sample.html")
        rec = parse(html, self.URL)
        assert rec.parse_ok is True

    def test_dominio_diferente_de_imoveis(self, load_fixture):
        """Valida que o plugin retorna dados de produto, não de imóvel."""
        from compsognathus.plugins.mercadolivre import parse
        html = load_fixture("mercadolivre_sample.html")
        rec = parse(html, self.URL)
        assert "produto" in rec.fields
        assert "quartos" not in rec.fields  # não é imóvel


# ── Catho (Vagas) ─────────────────────────────────────────────────────────────

class TestCathoParser:
    URL = "https://www.catho.com.br/vagas/engenheiro-software-python-123"

    def test_extrai_cargo(self, load_fixture):
        from compsognathus.plugins.catho import parse
        html = load_fixture("catho_sample.html")
        rec = parse(html, self.URL)
        assert "Engenheiro" in rec.fields["cargo"]

    def test_extrai_empresa(self, load_fixture):
        from compsognathus.plugins.catho import parse
        html = load_fixture("catho_sample.html")
        rec = parse(html, self.URL)
        assert "TechCorp" in rec.fields["empresa"]

    def test_extrai_salario(self, load_fixture):
        from compsognathus.plugins.catho import parse
        html = load_fixture("catho_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["salario"] == 12_000.0

    def test_extrai_cidade(self, load_fixture):
        from compsognathus.plugins.catho import parse
        html = load_fixture("catho_sample.html")
        rec = parse(html, self.URL)
        assert "Florianópolis" in rec.fields["cidade"]

    def test_parse_ok_true(self, load_fixture):
        from compsognathus.plugins.catho import parse
        html = load_fixture("catho_sample.html")
        rec = parse(html, self.URL)
        assert rec.parse_ok is True

    def test_dominio_diferente_de_imoveis_e_ecommerce(self, load_fixture):
        """Valida que o plugin retorna dados de vaga, não de produto ou imóvel."""
        from compsognathus.plugins.catho import parse
        html = load_fixture("catho_sample.html")
        rec = parse(html, self.URL)
        assert "cargo" in rec.fields
        assert "preco" not in rec.fields     # não é produto
        assert "quartos" not in rec.fields   # não é imóvel


# ── Books to Scrape (Livros / E-commerce Sandbox) ────────────────────────────

class TestBooksToScrapeParser:
    URL = "http://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"

    def test_extrai_titulo(self, load_fixture):
        from compsognathus.plugins.books_toscrape import parse
        html = load_fixture("books_toscrape_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["titulo"] == "A Light in the Attic"

    def test_extrai_preco(self, load_fixture):
        from compsognathus.plugins.books_toscrape import parse
        html = load_fixture("books_toscrape_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["preco"] == 51.77

    def test_extrai_avaliacao(self, load_fixture):
        from compsognathus.plugins.books_toscrape import parse
        html = load_fixture("books_toscrape_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["avaliacao"] == 3.0

    def test_extrai_upc_e_categoria(self, load_fixture):
        from compsognathus.plugins.books_toscrape import parse
        html = load_fixture("books_toscrape_sample.html")
        rec = parse(html, self.URL)
        assert rec.fields["upc"] == "a897639ed1542c26"
        assert rec.fields["categoria"] == "Poetry"

    def test_parse_ok_true(self, load_fixture):
        from compsognathus.plugins.books_toscrape import parse
        html = load_fixture("books_toscrape_sample.html")
        rec = parse(html, self.URL)
        assert rec.parse_ok is True
