"""
Testes dos parsers com fixtures HTML sintéticas.

Cada teste lê um HTML de exemplo do diretório fixtures/ e verifica
que o parser extrai os campos esperados corretamente.

Por que fixtures sintéticas?
    Fixtures fabricadas permitem testar casos específicos de forma determinística,
    sem depender de conexão com a internet ou de sites que podem mudar.
"""
import json


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

    def test_normaliza_preco_com_centavos_e_area_com_milhar(self):
        from compsognathus.plugins.zapimoveis import _clean_area, _clean_price

        assert _clean_price("R$ 650.000,00") == 650_000.0
        assert _clean_area("Área total 1.250 m²") == 1_250.0

    def test_terreno_nao_exige_quartos(self):
        from compsognathus.plugins.zapimoveis import parse

        html = """
        <html><head><title>Terreno à venda</title></head><body>
          <p data-testid="listing-price">R$ 450.000,00</p>
          <li data-testid="total-area">Área total 1.250 m²</li>
          <address>Bairro Centro, Florianópolis, SC</address>
        </body></html>
        """
        rec = parse(html, "https://www.zapimoveis.com.br/imovel/terreno-123")
        assert rec.parse_ok is True
        assert rec.fields["quartos"] is None
        assert rec.fields["area_privativa"] == 1_250.0

    def test_extrai_payload_next_f_atual(self):
        from compsognathus.plugins.zapimoveis import parse

        listing = {
            "prices": {"sale": {"value": 548000}},
            "amenities": {"usableAreas": [80], "bedrooms": [2], "parkingSpaces": [1]},
            "address": {"neighborhood": "Bela Vista", "city": "Palhoça", "state": "SC"},
        }
        payload = ["$", "$L1", None, {"baseData": {"pageData": {"listing": listing}}}]
        encoded = json.dumps("1:" + json.dumps(payload, separators=(",", ":")))

        html = f"<html><script>self.__next_f.push([1,{encoded}])</script></html>"
        rec = parse(html, "https://www.zapimoveis.com.br/imovel/casa-123")
        assert rec.parse_ok is True
        assert rec.fields["preco"] == 548000.0
        assert rec.fields["quartos"] == 2

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

    def test_normaliza_preco_com_centavos_e_area_com_milhar(self):
        from compsognathus.plugins.vivareal import _clean_area, _clean_price

        assert _clean_price("R$ 890.000,00") == 890_000.0
        assert _clean_area("Área do terreno 2.500 m²") == 2_500.0

    def test_terreno_nao_exige_quartos(self):
        from compsognathus.plugins.vivareal import parse

        html = """
        <html><head><title>Lote à venda</title></head><body>
          <p data-cy="listing-price">R$ 890.000,00</p>
          <li data-cy="total-area">Área total 2.500 m²</li>
          <address>Bairro Centro, Palhoça, SC</address>
        </body></html>
        """
        rec = parse(html, "https://www.vivareal.com.br/imovel/lote-123")
        assert rec.parse_ok is True
        assert rec.fields["quartos"] is None
        assert rec.fields["area_privativa"] == 2_500.0

    def test_extrai_payload_next_f_atual(self):
        from compsognathus.plugins.vivareal import parse

        listing = {
            "prices": {"sale": {"value": 390000}},
            "amenities": {"usableAreas": [60], "bedrooms": [2], "parkingSpaces": [2]},
            "address": {"neighborhood": "Guarda do Cubatão", "city": "Palhoça", "state": "SC"},
        }
        payload = ["$", "$L1", None, {"baseData": {"pageData": {"listing": listing}}}]
        encoded = json.dumps("1:" + json.dumps(payload, separators=(",", ":")))

        html = f"<html><script>self.__next_f.push([1,{encoded}])</script></html>"
        rec = parse(html, "https://www.vivareal.com.br/imovel/casa-123")
        assert rec.parse_ok is True
        assert rec.fields["preco"] == 390000.0
        assert rec.fields["bairro"] == "Guarda do Cubatão"

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

    def test_extrai_jsonld_dentro_de_graph(self):
        from compsognathus.plugins.mercadolivre import parse

        html = """
        <script type="application/ld+json">
        {"@context":"https://schema.org", "@graph":[
          {"@type":"Product", "name":"Produto Graph",
           "offers":{"price":"199.90"},
           "aggregateRating":{"ratingValue":"4.5", "reviewCount":"10"}}
        ]}
        </script>
        """
        rec = parse(html, "https://www.mercadolivre.com.br/p/graph")
        assert rec.fields["produto"] == "Produto Graph"
        assert rec.fields["preco"] == 199.9


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

    def test_extrai_jobposting_dentro_de_graph(self):
        from compsognathus.plugins.catho import parse

        html = """
        <script type="application/ld+json">
        {"@graph":[{"@type":"JobPosting", "title":"Dev Graph",
          "hiringOrganization":{"name":"Acme"},
          "jobLocation":{"address":{"addressLocality":"Recife"}},
          "baseSalary":{"value":{"value":5000}}}]}
        </script>
        """
        rec = parse(html, "https://www.catho.com.br/vagas/graph")
        assert rec.fields["cargo"] == "Dev Graph"
        assert rec.fields["empresa"] == "Acme"


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
