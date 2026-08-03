"""
Testes do core do framework: ScrapedRecord e sistema de registry.

Estes testes verificam que a espinha dorsal do framework funciona
corretamente — o modelo de dados genérico e o sistema de plugins.
"""
import pytest
from compsognathus.core.record import ScrapedRecord
from compsognathus.core.registry import _REGISTRY, get_parser, list_plugins, register


# ── Testes do ScrapedRecord ───────────────────────────────────────────────────

class TestScrapedRecord:
    def test_cria_registro_basico(self):
        """ScrapedRecord deve aceitar url, site e fields livres."""
        rec = ScrapedRecord(url="https://example.com", site="test", fields={"preco": 100.0})
        assert rec.url == "https://example.com"
        assert rec.site == "test"
        assert rec.fields["preco"] == 100.0

    def test_defaults_corretos(self):
        """parse_ok deve ser True e parse_errors vazio por padrão."""
        rec = ScrapedRecord(url="https://example.com", site="test")
        assert rec.parse_ok is True
        assert rec.parse_errors == []

    def test_data_coleta_gerada_automaticamente(self):
        """data_coleta deve ser gerado se não fornecido."""
        rec = ScrapedRecord(url="https://example.com", site="test")
        assert rec.data_coleta  # não deve ser None ou vazio
        assert "T" in rec.data_coleta  # formato ISO 8601

    def test_fields_aceita_qualquer_dominio(self):
        """fields deve aceitar dicionários de qualquer domínio sem restrição."""
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
        """record.get('campo') deve funcionar como atalho para record.fields.get()."""
        rec = ScrapedRecord(url="https://x.com", site="x", fields={"preco": 99.9})
        assert rec.get("preco") == 99.9
        assert rec.get("campo_inexistente") is None
        assert rec.get("campo_inexistente", "fallback") == "fallback"

    def test_parse_errors_registrado(self):
        """parse_errors deve listar campos obrigatórios ausentes."""
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
        """@register deve adicionar a função ao _REGISTRY global."""
        @register("test-registry.com", schema=["campo1"])
        def _parse_test(html, url):
            return ScrapedRecord(url=url, site="test")

        assert "test-registry.com" in _REGISTRY

    def test_get_parser_retorna_funcao_correta(self):
        """get_parser deve retornar o parser para o domínio da URL."""
        @register("meusite-test.com.br", schema=["titulo"])
        def _parse_meu(html, url):
            return ScrapedRecord(url=url, site="meu")

        fn = get_parser("https://www.meusite-test.com.br/produto/123")
        assert fn is _parse_meu

    def test_get_parser_remove_www(self):
        """get_parser deve normalizar URLs com e sem www."""
        @register("semwww-test.com.br", schema=["x"])
        def _parse_sw(html, url):
            return ScrapedRecord(url=url, site="sw")

        fn1 = get_parser("https://www.semwww-test.com.br/item")
        fn2 = get_parser("https://semwww-test.com.br/item")
        assert fn1 is fn2 is _parse_sw

    def test_get_parser_levanta_erro_para_dominio_desconhecido(self):
        """get_parser deve levantar ValueError para domínios não registrados."""
        with pytest.raises(ValueError, match="Nenhum plugin"):
            get_parser("https://www.dominio-nao-existe-xyz.com/pagina")

    def test_list_plugins_retorna_lista(self):
        """list_plugins deve retornar lista de dicts com domain e schema."""
        # Importa plugins para garantir que estão registrados
        import compsognathus.plugins  # noqa: F401
        plugins = list_plugins()
        assert isinstance(plugins, list)
        assert len(plugins) >= 4  # zapimoveis, vivareal, mercadolivre, catho
        for p in plugins:
            assert "domain" in p
            assert "schema" in p
