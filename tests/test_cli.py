"""
Testes de integração da interface CLI (typer + rich).
"""
from typer.testing import CliRunner
from compsognathus.cli import app

runner = CliRunner()


def test_cli_plugins_list():
    result = runner.invoke(app, ["plugins", "list"])
    assert result.exit_code == 0
    assert "Plugins registrados" in result.output
    assert "zapimoveis.com.br" in result.output
    assert "mercadolivre.com.br" in result.output
    assert "catho.com.br" in result.output
    assert "books.toscrape.com" in result.output


def test_cli_scrape_dry_run_url_unica():
    result = runner.invoke(app, ["scrape", "https://books.toscrape.com/catalogue/item", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "books.toscrape.com" in result.output
    assert "1/1 URL(s) possuem plugins compatíveis" in result.output


def test_cli_scrape_dry_run_desconhecido():
    result = runner.invoke(app, ["scrape", "https://site-nao-suportado-xyz.com/item", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY RUN" in result.output
    assert "0/1 URL(s) possuem plugins compatíveis" in result.output
