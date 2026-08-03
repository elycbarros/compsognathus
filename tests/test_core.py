"""
Testes do core do framework: ScrapedRecord, registry e exportação multi-formato.
"""
import sqlite3
from contextlib import closing
import pandas as pd
import pytest
from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import PluginRegistration, _REGISTRY, get_parser, get_schema, list_plugins, register
from compsognathus.scraper import export_dataframe


# ── Testes do ScrapedRecord ───────────────────────────────────────────────────

class TestScrapedRecord:
    def test_cria_registro_basico(self):
        rec = ScrapedRecord(url="https://example.com", site="test", fields={"preco": 100.0})
        assert rec.url == "https://example.com"
        assert rec.site == "test"
        assert rec.fields["preco"] == 100.0

    def test_defaults_corretos(self):
        rec = ScrapedRecord(url="https://example.com", site="test")
        assert rec.parse_ok is True
        assert rec.parse_errors == []

    def test_data_coleta_gerada_automaticamente(self):
        rec = ScrapedRecord(url="https://example.com", site="test")
        assert rec.data_coleta
        assert "T" in rec.data_coleta

    def test_fields_aceita_qualquer_dominio(self):
        imovel = ScrapedRecord(url="https://a.com", site="x",
                               fields={"preco": 450_000, "quartos": 3, "bairro": "Trindade"})
        vaga = ScrapedRecord(url="https://b.com", site="y",
                             fields={"cargo": "Dev", "salario": 8_000, "empresa": "Acme"})
        produto = ScrapedRecord(url="https://c.com", site="z",
                                fields={"nome": "MacBook", "preco": 12_999, "avaliacao": 4.8})

        assert imovel.fields["bairro"] == "Trindade"
        assert vaga.fields["cargo"] == "Dev"
        assert produto.fields["avaliacao"] == 4.8

    def test_metodo_get_retorna_campo(self):
        rec = ScrapedRecord(url="https://x.com", site="x", fields={"preco": 99.9})
        assert rec.get("preco") == 99.9
        assert rec.get("campo_inexistente") is None
        assert rec.get("campo_inexistente", "fallback") == "fallback"

    def test_parse_errors_registrado(self):
        rec = ScrapedRecord(
            url="https://x.com", site="x",
            parse_ok=False,
            parse_errors=["preco", "bairro"],
        )
        assert "preco" in rec.parse_errors
        assert rec.parse_ok is False


# ── Testes do Registry ────────────────────────────────────────────────────────

class TestRegistry:
    def test_register_decorator_registra_parser(self):
        @register("test-registry.com", schema=["campo1"])
        def _parse_test(html, url):
            return ScrapedRecord(url=url, site="test")

        assert "test-registry.com" in _REGISTRY

    def test_get_parser_retorna_funcao_correta(self):
        @register("meusite-test.com.br", schema=["titulo"])
        def _parse_meu(html, url):
            return ScrapedRecord(url=url, site="meu")

        fn = get_parser("https://www.meusite-test.com.br/produto/123")
        assert fn is _parse_meu

    def test_get_parser_remove_www(self):
        @register("semwww-test.com.br", schema=["x"])
        def _parse_sw(html, url):
            return ScrapedRecord(url=url, site="sw")

        fn1 = get_parser("https://www.semwww-test.com.br/item")
        fn2 = get_parser("https://semwww-test.com.br/item")
        assert fn1 is fn2 is _parse_sw

    def test_get_parser_aceita_subdominio_legitimo(self):
        @register("dominio-seguro.com.br", schema=["x"])
        def _parse_subdomain(html, url):
            return ScrapedRecord(url=url, site="seguro")

        fn = get_parser("https://anuncios.dominio-seguro.com.br/item")
        assert fn is _parse_subdomain

    def test_get_schema_retorna_campos_de_qualidade(self):
        @register("schema-test.com", schema=["titulo", "preco"])
        def _parse_schema(html, url):
            return ScrapedRecord(url=url, site="schema")

        assert get_schema("https://schema-test.com/item") == ["titulo", "preco"]

    def test_registro_tem_campos_nomeados(self):
        @register("registro-nomeado.com", schema=["titulo"])
        def _parse_nomeado(html, url):
            return ScrapedRecord(url=url, site="nomeado")

        registration = _REGISTRY["registro-nomeado.com"]
        assert isinstance(registration, PluginRegistration)
        assert registration.parser is _parse_nomeado
        assert registration.schema == ("titulo",)

    @pytest.mark.parametrize(
        "url",
        [
            "https://evilzapimoveis.com.br/item",
            "https://zapimoveis.com.br.evil.test/item",
            "nao-e-uma-url",
        ],
    )
    def test_get_parser_rejeita_dominio_impostor_ou_url_invalida(self, url):
        with pytest.raises(ValueError):
            get_parser(url)

    def test_get_parser_levanta_erro_para_dominio_desconhecido(self):
        with pytest.raises(ValueError, match="Nenhum plugin"):
            get_parser("https://www.dominio-nao-existe-xyz.com/pagina")

    def test_list_plugins_retorna_lista(self):
        import compsognathus.plugins  # noqa: F401
        plugins = list_plugins()
        assert isinstance(plugins, list)
        assert len(plugins) >= 5
        for p in plugins:
            assert "domain" in p
            assert "schema" in p


# ── Testes de Exportação Multi-Formato ────────────────────────────────────────

class TestExportDataFrame:
    @pytest.fixture
    def sample_df(self):
        return pd.DataFrame([
            {"url": "https://ex.com/1", "site": "ex", "preco": 100.0, "titulo": "Item A"},
            {"url": "https://ex.com/2", "site": "ex", "preco": 200.0, "titulo": "Item B"},
        ])

    def test_export_json(self, sample_df, tmp_path):
        out_json = tmp_path / "test.json"
        export_dataframe(sample_df, out_json, fmt="json")
        assert out_json.exists()
        read_df = pd.read_json(out_json)
        assert len(read_df) == 2
        assert read_df.iloc[0]["preco"] == 100.0

    def test_export_jsonl(self, sample_df, tmp_path):
        out_jsonl = tmp_path / "test.jsonl"
        export_dataframe(sample_df, out_jsonl, fmt="jsonl")
        assert out_jsonl.exists()
        read_df = pd.read_json(out_jsonl, lines=True)
        assert len(read_df) == 2

    def test_export_sqlite(self, sample_df, tmp_path):
        out_db = tmp_path / "test.db"
        export_dataframe(sample_df, out_db, fmt="sqlite")
        assert out_db.exists()

        with closing(sqlite3.connect(out_db)) as conn:
            db_df = pd.read_sql_query("SELECT * FROM scraped_data", conn)
            assert len(db_df) == 2
            assert db_df.iloc[1]["titulo"] == "Item B"
