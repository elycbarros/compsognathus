"""Testes das validações locais do downloader, sem acesso à rede."""

from pathlib import Path

import pytest

from compsognathus.downloader import _is_valid_html, download_all, download_url


def test_html_pequeno_mas_completo_e_valido():
    html = "<!doctype html><html><body>" + ("conteudo " * 70) + "</body></html>"
    assert len(html) < 8_000
    assert _is_valid_html(html) is True


@pytest.mark.parametrize(
    "html",
    [
        "texto sem estrutura HTML " * 30,
        "<!doctype html><html><body>Access denied" + ("!" * 600) + "</body></html>",
    ],
)
def test_html_invalido_ou_bloqueado_e_rejeitado(html):
    assert _is_valid_html(html) is False


def test_download_all_rejeita_concorrencia_invalida(tmp_path: Path):
    with pytest.raises(ValueError, match="concurrency"):
        download_all([], output_dir=tmp_path, concurrency=0)


def test_download_url_preserva_erros_das_duas_camadas(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "compsognathus.downloader._try_playwright",
        lambda url: (_ for _ in ()).throw(RuntimeError("browser offline")),
    )
    monkeypatch.setattr(
        "compsognathus.downloader._try_httpx",
        lambda url: (_ for _ in ()).throw(TimeoutError("request timeout")),
    )

    result = download_url("https://example.com/item", tmp_path)
    assert result.ok is False
    assert "browser offline" in result.error
    assert "request timeout" in result.error
