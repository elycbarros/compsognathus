"""
Testes de integração da interface CLI (typer + rich).
"""
from pathlib import Path
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


def test_cli_plugins_new(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["plugins", "new", "testsite.com.br"])
    assert result.exit_code == 0
    assert "Scaffold criado com sucesso" in result.output

    plugin_py = tmp_path / "compsognathus" / "plugins" / "testsite.py"
    fixture_html = tmp_path / "tests" / "fixtures" / "testsite_sample.html"

    assert plugin_py.exists()
    assert fixture_html.exists()
    assert "testsite.com.br" in plugin_py.read_text(encoding="utf-8")


def test_cli_report_html_export(tmp_path):
    # Cria arquivo parquet temporário
    import pandas as pd
    df = pd.DataFrame([{"url": "https://a.com", "site": "a", "parse_ok": True, "preco": 50.0}])
    pq_path = tmp_path / "data.parquet"
    html_path = tmp_path / "report.html"
    df.to_parquet(pq_path, index=False)

    result = runner.invoke(app, ["report", str(pq_path), "--html", str(html_path)])
    assert result.exit_code == 0
    assert "Relatório HTML gerado em:" in result.output
    assert html_path.exists()
    assert "Compsognathus" in html_path.read_text(encoding="utf-8")
